"""Self-check for the announced-event trading (events.py) and its precedence over the rules:  python tools/check_events.py

A fake command writer fills every order at once (result row + simple portfolio), and synthetic pump / crash price
paths shaped like the ones described in events.py are played through the event trader second by second."""

import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenstocks import events  # noqa: E402
from screenstocks.automation import AutomationEngine, status_display  # noqa: E402
from screenstocks.commands import SentCommand  # noqa: E402
from screenstocks.reader import MarketSnapshot, Player, Position, ScheduledNews, Stock  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402

BUY_CD_S, SHORT_CD_S = 132, 136


class FakeGame:
    """Command writer that executes at once: writes the 'done' result the event trader waits for and keeps cash,
    positions and the shared buy / short cooldowns (ponytail: no fees, shorts only track their shares)."""

    def __init__(self, db: Storage, cash: float, positions: dict):
        self.db, self.cash, self.now, self.n = db, cash, 0, 0
        self.pos = {sid: {"shares_owned": float(sh), "shares_shorted": 0.0} for sid, sh in positions.items()}
        self.prices: dict = {}
        self.cd = {"buy": 0, "short": 0}
        self.sent: list = []                                   # (time, stock, action, percent, price)

    def send(self, stock_id: str, action: str, percent: float) -> SentCommand:
        pct, price = int(percent), self.prices[stock_id]
        p = self.pos.setdefault(stock_id, {"shares_owned": 0.0, "shares_shorted": 0.0})
        status = "done"
        if action in self.cd and self.cd[action] > self.now:
            status = "rejected"
        elif action == "buy":
            p["shares_owned"] += self.cash * pct / 100 / price
            self.cash -= self.cash * pct / 100
            self.cd["buy"] = self.now + BUY_CD_S * 1000
        elif action == "sell":
            self.cash += p["shares_owned"] * pct / 100 * price
            p["shares_owned"] *= 1 - pct / 100
        elif action == "short":
            p["shares_shorted"] += self.cash * pct / 100 / price
            self.cd["short"] = self.now + SHORT_CD_S * 1000
        elif action == "cover":
            p["shares_shorted"] = 0.0
        self.n += 1
        self.db.conn.execute("INSERT INTO command_results (id, run, action, stock_id, percent, status, reason, "
                             "retry_at_ms, received_ms, finished_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (f"c{self.n}", 1, f"{action}percent", stock_id, pct, status, "", 0, self.now, self.now))
        self.db.conn.commit()
        if status == "done":
            self.sent.append((self.now, stock_id, action, pct, price))
        return SentCommand(stock_id, action, pct, Path("unused"))

    def cancel(self, sent) -> bool:
        return False

    def positions(self) -> dict:
        return {sid: dict(p) for sid, p in self.pos.items() if p["shares_owned"] or p["shares_shorted"]}

    def snap(self) -> dict:
        return {"cash": self.cash, "next_buy_ms": self.cd["buy"], "next_short_ms": self.cd["short"],
                "buy_cooldown_s": BUY_CD_S, "short_cooldown_s": SHORT_CD_S}


def new_db() -> Storage:
    return Storage(Path(tempfile.mkdtemp()) / "x.db")


def add_stocks(db: Storage, prices: dict, available: int = 10**9) -> None:
    db.conn.executemany("INSERT OR REPLACE INTO stocks (stock_id, name, unlocked, available_shares, last_price) "
                        "VALUES (?,?,1,?,?)", [(sid, sid, available, p) for sid, p in prices.items()])


def announce(db: Storage, sid: str, direction: str, target: float, sched: int, published: int) -> None:
    db.conn.execute("INSERT INTO scheduled_news VALUES (?,?,?,?,?,?)", (f"{direction}1", sid, direction, target,
                                                                          sched, published))
    db.conn.commit()


def play(db, game: FakeGame, s: events.EventSettings, prices_at, start: int, end: int) -> list:
    """Step the event trader once per second; returns the reservations seen at every step."""
    trader, seen = events.EventTrader(game), []
    for now in range(start, end, 1000):
        game.now = now
        game.prices = prices_at(now)
        trader.step(db, s, True, True, now, game.prices, game.positions(), game.snap())
        seen.append((now, *events.reservations(db, s, now, game.snap())))
    return seen


def check_pump():
    T = 10_000_000
    db, s = new_db(), events.EventSettings(pumps=True, crashes=True)

    def prices_at(now):
        dt = (now - T) / 1000
        pump = 9.0 if dt < 0 else 100.0 if dt < 1 else 109.0 if dt < 2 else max(9.0, 109 - 100 * (dt - 2) / 43)
        return {"$PUMP": pump, "$A": 50.0, "$B": 20.0}
    add_stocks(db, prices_at(0))
    announce(db, "$PUMP", "pump", 109.0, T, T - 60_000)
    game = FakeGame(db, cash=1000.0, positions={"$A": 1000, "$B": 500})
    seen = play(db, game, s, prices_at, T - 60_000, T + 200_000)
    acts = [(sid, a) for _, sid, a, _, _ in game.sent]
    assert acts[:3] == [("$A", "sell"), ("$B", "sell"), ("$PUMP", "buy")], f"fund the pump, biggest first: {acts}"
    buy = next(x for x in game.sent if x[2] == "buy")
    assert buy[0] < T and buy[4] == 9.0, "bought before the pump at the pre-pump price"
    sell = next(x for x in game.sent if x[1] == "$PUMP" and x[2] == "sell")
    assert sell[4] >= 9 + 100 * 0.85, f"sold close to the target, not after the pullback: {sell}"
    short = next(x for x in game.sent if x[2] == "short")
    cover = next(x for x in game.sent if x[2] == "cover")
    assert short[0] >= sell[0] and cover[4] <= 9 * 1.2, f"short after the peak, cover near the start: {short} {cover}"
    assert db.active_events(T)[0]["phase"] == "done"
    owned, reserved = seen[0][1], seen[0][2]
    assert "$PUMP" in owned and set(reserved) == {"buy", "short"}, "announcement: stock owned, both cooldowns kept"
    after_buy = next(r for t_, _, r in seen if t_ > buy[0])
    assert set(after_buy) == {"short"}, "the buy is done: only the short cooldown stays reserved"
    assert not seen[-1][1] and not seen[-1][2], "done: nothing owned or reserved"
    print(f"pump: {acts}, sold at {sell[4]:.1f}, cash {game.cash:,.0f} (from 1,000 + 60,000 in positions)")


def check_crash():
    T = 50_000_000
    db, s = new_db(), events.EventSettings(pumps=True, crashes=True)

    def prices_at(now):
        dt = (now - T) / 1000
        if dt < -300:
            plain = 774.0
        elif dt < 0:
            plain = 774.0 - 74 * (dt + 300) / 300            # drifts down in the last minutes
        elif dt < 5:
            plain = 10.2                                    # a few seconds at roughly the target
        else:
            plain = min(774.0, 10.2 + 763.8 * (dt - 5) / 1800)  # recovers within ~30 min
        return {"$PLAIN": plain, "$A": 50.0}
    add_stocks(db, prices_at(0))
    announce(db, "$PLAIN", "crash", 10.0, T, T - 6 * 3600_000)
    game = FakeGame(db, cash=1000.0, positions={"$PLAIN": 100, "$A": 1000})
    assert events.reservations(db, s, T - 3 * 3600_000, game.snap()) == ({}, {}), "hours ahead: nothing blocked"
    seen = play(db, game, s, prices_at, T - 20 * 60_000, T + 40 * 60_000)
    acts = [(sid, a) for _, sid, a, _, _ in game.sent]
    assert acts == [("$PLAIN", "sell"), ("$PLAIN", "short"), ("$A", "sell"), ("$PLAIN", "cover"), ("$PLAIN", "buy")], acts
    when = {(sid, a): (t_, price) for t_, sid, a, _, price in game.sent}
    assert when[("$PLAIN", "sell")][0] == T - 15 * 60_000, "sell + short 15 min before"
    assert T - 61_000 <= when[("$A", "sell")][0] < T, "the other positions are sold in the last minute"
    assert when[("$PLAIN", "buy")][1] <= 10 * 1.05, f"bought back at the bottom: {when[('$PLAIN', 'buy')]}"
    assert db.active_events(T)[0]["phase"] == "done"
    short_from = next(t_ for t_, _, r in seen if "short" in r)
    buy_from = next(t_ for t_, _, r in seen if "buy" in r)
    assert short_from == T - 15 * 60_000 - (SHORT_CD_S + events.CD_MARGIN_S) * 1000, short_from - T
    assert buy_from == T - (BUY_CD_S + events.CD_MARGIN_S) * 1000, buy_from - T
    shares = game.pos["$PLAIN"]["shares_owned"]
    print(f"crash: {acts}, bought back {shares:,.0f} shares at {when[('$PLAIN', 'buy')][1]:.2f}, "
          f"worth {shares * 774:,.0f} recovered (from {1000 + 100 * 774 + 1000 * 50:,.0f})")


def check_rules_yield():
    """The real rule engine: an entry rule waits while its cooldown is reserved, a rule on the event's stock pauses,
    an exit on another stock still fires."""
    T = 90_000_000
    db = new_db()
    db.set_setting(events.SETTINGS_KEY, json.dumps({"pumps": True, "fund_events": False}))
    db.store_market(MarketSnapshot(
        format_version=1, game_version="test", sequence=1, written_at_ms=T, server_time_ms=T, server_tick=1,
        last_price_update_at_ms=T, market_ready=True,
        stocks=[Stock(sid, sid, p, True, p, 1000, 0, 1000, 10**9) for sid, p in (("$PUMP", 9.0), ("$A", 50.0), ("$B", 20.0))],
        player=Player(1000.0, 11000.0, 1, 0, T + 20_000, 0, BUY_CD_S, SHORT_CD_S,   # buy cooldown busy for 20 s
                      [Position("$B", 500, 25.0, 0, 0)]),
        market_news=[], scheduled_news=[ScheduledNews("pump1", "$PUMP", "pump", 109.0, T + 50_000, T - 10_000)]))
    add_rule = lambda sid, kind, value: db.add_rule(sid, kind, "long", "price", value, 100, 0.0, T)  # noqa: E731
    r_buy, r_pump, r_stop = add_rule("$A", "buy_limit", 100.0), add_rule("$PUMP", "buy_limit", 100.0), \
        add_rule("$B", "stop_loss", 25.0)
    game = FakeGame(db, 1000.0, {"$B": 500})
    game.now, game.prices = T, {"$PUMP": 9.0, "$A": 50.0, "$B": 20.0}
    game.cd["buy"] = T + 20_000
    collector = SimpleNamespace(status=SimpleNamespace(copy=lambda: SimpleNamespace(last_market_read=time.time())))
    engine = AutomationEngine(collector, db.path, game)
    engine.bot.calibrated = True                     # no calibration process in a self-check
    engine._step(db)
    acts = [(sid, a) for _, sid, a, _, _ in game.sent]
    assert ("$B", "sell") in acts, f"a stop-loss on another stock still fires: {acts}"
    assert ("$A", "buy") not in acts and ("$PUMP", "buy") not in acts, f"no buy while the pump needs it: {acts}"
    rules = {r["id"]: r for r in db.rules()}
    assert json.loads(rules[r_buy]["status"])["k"] == "rule.st.event_reserved", rules[r_buy]["status"]
    assert json.loads(rules[r_pump]["status"])["k"] == "rule.st.event_paused", rules[r_pump]["status"]
    print(f"rules: {status_display(rules[r_buy]['status'])!r} / {status_display(rules[r_pump]['status'])!r} / "
          f"stop-loss #{r_stop} sent")


def check_rule_near():
    """A far-away limit rule must not stop the bot's entries of its kind (a limit buy at 2 with the price at 30)."""
    from screenstocks.bot import rule_near
    buy = {"kind": "buy_limit", "value": 2.0}
    assert not rule_near(buy, 29.7) and rule_near(buy, 2.1) and rule_near(buy, 1.5)
    short = {"kind": "short_limit", "value": 100.0}
    assert not rule_near(short, 50.0) and rule_near(short, 95.0)
    assert not rule_near({"kind": "trailing_buy", "value": 5, "extreme": None}, 10.0), "waits for its activation"
    assert rule_near({"kind": "trailing_buy", "value": 5, "extreme": 9.0}, 10.0), "follows the price: may fire any time"
    assert rule_near(buy, None), "no price: stay careful"


def check_trailing_zone():
    """A trailing buy activated below 7.56 must not buy a spike at 34 (live, before ZONE_K)."""
    from screenstocks.automation import left_zone, trigger_price, condition_met
    stub = SimpleNamespace(update_rule=lambda *a, **k: None)
    rule = {"id": 1, "kind": "trailing_buy", "side": "long", "value": 2.0, "activation": 7.56, "extreme": None}
    follow = AutomationEngine._follow
    assert not follow(stub, rule, 9.0), "above the activation price: waits"
    assert follow(stub, rule, 7.4) and rule["extreme"] == 7.4, "dipped below it: follows the low"
    assert follow(stub, rule, 7.2) and rule["extreme"] == 7.2
    assert condition_met(rule, 7.35, trigger_price(rule, None)), "turned up 2 % inside the zone: buys"
    assert left_zone(rule, 34.0) and not follow(stub, rule, 34.0) and rule["extreme"] is None, "a spike ends the following"
    short = {"id": 2, "kind": "trailing_short", "side": "short", "value": 4.0, "activation": 11.09, "extreme": 11.8}
    assert left_zone(short, 8.17) and not left_zone(short, 10.7), "a short never sells the bottom of a drop"
    assert not left_zone({**rule, "activation": None}, 34.0), "no activation price: no zone"


def check_settings():
    db = new_db()
    db.set_setting(events.SETTINGS_KEY, json.dumps({"pumps": True, "crashes": True}))       # stored by an older version
    s = events.load_settings(db)
    assert s.fund_events and s.pump_target_share == 85.0 and s.crash_target_pct == 5.0, "new settings default on"
    db.set_setting(events.SETTINGS_KEY, json.dumps({"crashes": True, "crash_target_pct": 0, "fund_events": False}))
    s = events.load_settings(db)
    assert not s.fund_events and s.crash_target_pct == 0


if __name__ == "__main__":
    check_settings()
    check_rule_near()
    check_trailing_zone()
    check_pump()
    check_crash()
    check_rules_yield()
    print("ok")
