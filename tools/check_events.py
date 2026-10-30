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
        self.pos = {sid: {"shares_owned": float(sh), "shares_shorted": 0.0, "avg_buy_price": 0.0, "avg_short_price": 0.0}
                    for sid, sh in positions.items()}
        self.prices: dict = {}
        self.fill: dict = {}                                   # (stock, action) -> fill price of the next such order
        self.cd = {"buy": 0, "short": 0}
        self.sent: list = []                                   # (time, stock, action, percent, price)

    def send(self, stock_id: str, action: str, percent: float) -> SentCommand:
        pct = int(percent)
        price = self.fill.pop((stock_id, action), None) or self.prices[stock_id]     # the price may jump before the fill
        p = self.pos.setdefault(stock_id, {"shares_owned": 0.0, "shares_shorted": 0.0, "avg_buy_price": 0.0,
                                           "avg_short_price": 0.0})
        status = "done"
        if action in self.cd and self.cd[action] > self.now:
            status = "rejected"
        elif action == "buy":
            n = self.cash * pct / 100 / price
            p["avg_buy_price"] = (p["shares_owned"] * p["avg_buy_price"] + n * price) / (p["shares_owned"] + n)
            p["shares_owned"] += n
            self.cash -= self.cash * pct / 100
            self.cd["buy"] = self.now + BUY_CD_S * 1000
        elif action == "sell":
            self.cash += p["shares_owned"] * pct / 100 * price
            p["shares_owned"] *= 1 - pct / 100
        elif action == "short":
            n = self.cash * pct / 100 / price
            p["avg_short_price"] = (p["shares_shorted"] * p["avg_short_price"] + n * price) / (p["shares_shorted"] + n)
            p["shares_shorted"] += n
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
    assert acts == [("$PLAIN", "sell"), ("$PLAIN", "short"), ("$A", "sell"), ("$PLAIN", "cover"), ("$PLAIN", "buy"),
                    ("$PLAIN", "sell")], acts
    when = {(sid, a): (t_, price) for t_, sid, a, _, price in game.sent[:-1]}
    sold_back = game.sent[-1]
    assert sold_back[4] >= 10.2 + (774 - 10.2) * 0.9, f"held until mostly recovered: {sold_back}"
    assert when[("$PLAIN", "sell")][0] == T - 15 * 60_000, "sell + short 15 min before"
    assert T - 61_000 <= when[("$A", "sell")][0] < T, "the other positions are sold in the last minute"
    assert when[("$PLAIN", "buy")][1] <= 10 * 1.05, f"bought back at the bottom: {when[('$PLAIN', 'buy')]}"
    assert db.active_events(T)[0]["phase"] == "done"
    short_from = next(t_ for t_, _, r in seen if "short" in r)
    buy_from = next(t_ for t_, _, r in seen if "buy" in r)
    assert short_from == T - 15 * 60_000 - (SHORT_CD_S + events.CD_MARGIN_S) * 1000, short_from - T
    assert buy_from == T - (BUY_CD_S + events.CD_MARGIN_S) * 1000, buy_from - T
    assert any("result" in m and "total +" in m for _, _, _, _, m in db.rule_log(50)), "the event's result is logged"
    print(f"crash: {acts}, bought back at {when[('$PLAIN', 'buy')][1]:.2f}, sold at {sold_back[4]:.1f} after "
          f"{(sold_back[0] - T) / 60_000:.0f} min, cash {game.cash:,.0f} (from {1000 + 100 * 774 + 1000 * 50:,.0f})")


def check_crash_spike():
    """$IDXA, 29.10.: at the crash the price jumped 18.67 -> 229 -> 950 -> 35 within 20 s. Before, the short was
    covered at 229 (-511 %) and everything bought back at 950. Now both wait for the price to come back."""
    T = 60_000_000
    db, s = new_db(), events.EventSettings(crashes=True, fund_events=False)
    path = {0: 18.67, 1: 229.3, 2: 950.0, 3: 908.4}

    def prices_at(now):
        dt = (now - T) // 1000
        return {"$IDXA": 60.0 if dt < 0 else path.get(dt, 35.4 if dt < 20 else 45.0)}
    add_stocks(db, prices_at(0))
    announce(db, "$IDXA", "crash", 15.0, T, T - 3600_000)
    game = FakeGame(db, cash=1000.0, positions={})
    play(db, game, s, prices_at, T - 16 * 60_000, T + 50 * 60_000)
    acts = [(a, price) for _, sid, a, _, price in game.sent]
    assert [a for a, _ in acts] == ["short", "cover", "buy", "sell"], acts
    assert all(price < 60 for a, price in acts if a in ("cover", "buy")), f"no cover / buy-back on the jump: {acts}"
    bought, sold = game.sent[2][0], game.sent[3][0]
    assert 0 <= sold - bought - s.crash_hold_max_min * 60_000 <= 3000, "no recovery to the target: sold after the maximum hold"
    msgs = [m for *_, m in db.rule_log(50)]
    assert any("229.3" in m for m in msgs), "the jump is logged"

    # a jump that does not end: covered after crash_safety_s + CRASH_SPIKE_WAIT_S, never bought back above the start
    db = new_db()
    game = FakeGame(db, cash=1000.0, positions={})
    add_stocks(db, {"$IDXA": 60.0})
    announce(db, "$IDXA", "crash", 15.0, T, T - 3600_000)
    play(db, game, s, lambda now: {"$IDXA": 60.0 if now < T else 200.0}, T - 16 * 60_000, T + 15 * 60_000)
    cover = next(x for x in game.sent if x[2] == "cover")
    assert cover[0] == T + (s.crash_safety_s + events.CRASH_SPIKE_WAIT_S) * 1000, (cover[0] - T) / 1000
    assert not any(x[2] == "buy" for x in game.sent), "no buy-back above the price before the crash"
    print(f"crash spike: {acts}")


def crash_run(prices_after, fill=None, minutes=20):
    """A crash at T on $X (60 before it, target 15) with prices_after(seconds after T); fill = a different fill price
    for the buy-back. Returns (game, log messages)."""
    T = 80_000_000
    db, s = new_db(), events.EventSettings(crashes=True, fund_events=False)
    add_stocks(db, {"$X": 60.0})
    announce(db, "$X", "crash", 15.0, T, T - 3600_000)
    game = FakeGame(db, cash=1000.0, positions={})
    if fill:
        game.fill[("$X", "buy")] = fill
    play(db, game, s, lambda now: {"$X": 60.0 if now < T else prices_after((now - T) // 1000)}, T - 16 * 60_000,
         T + minutes * 60_000)
    return game, [m for *_, m in db.rule_log(100)], db


def check_rebuy_checks():
    # 1. the real fill: signal at 15, but the game fills at 58 (a jump in between) -> sold again at once
    game, msgs, _ = crash_run(lambda dt: 15.0 if dt < 3 else 40.0, fill=58.0)
    acts = [(a, p) for _, _, a, _, p in game.sent]
    assert [a for a, _ in acts] == ["short", "cover", "buy", "sell"] and game.sent[3][0] - game.sent[2][0] <= 2000, acts
    assert any("58" in m and "57" in m for m in msgs), "the fill above the accepted price is logged"
    # 2. not enough room left: the price is back at 56 (only 7 % under the 60 before it, margin 10 %) -> no buy-back
    game, msgs, _ = crash_run(lambda dt: 15.0 if dt < 1 else 56.0)
    assert [a for _, _, a, _, _ in game.sent] == ["short", "cover"], game.sent
    assert any("56" in m and "54" in m for m in msgs), "the skipped buy-back is logged"
    # 3. the hold's stop-loss: a 2 s dip is ignored, a lasting fall below fill - 15 % sells
    game, msgs, db = crash_run(lambda dt: 15.0 if dt < 5 else 12.0 if 100 <= dt < 102 else 11.0 if dt >= 200 else 16.0)
    sells = [(t_, p) for t_, _, a, _, p in game.sent if a == "sell"]
    assert len(sells) == 1 and sells[0][1] == 11.0, f"no sale on the dip, one on the lasting fall: {game.sent}"
    assert db.active_events(80_000_000)[0]["phase"] == "done"
    assert any("result" in m for m in msgs), "the result is logged"
    print(f"rebuy checks: fill jump sold at once, no buy-back at 56, stop-loss at 11 after the buy at 15 - {msgs[0]}")


def check_excluded():
    T = 70_000_000
    db = new_db()
    s = events.EventSettings(pumps=True, crashes=True, excluded=["$IDXA", "$IDXA"])
    assert s.excluded == ["$IDXA"]
    add_stocks(db, {"$IDXA": 60.0, "$PLAIN": 700.0})
    announce(db, "$IDXA", "crash", 15.0, T, T - 3600_000)
    db.conn.execute("INSERT INTO scheduled_news VALUES (?,?,?,?,?,?)", ("crash2", "$PLAIN", "crash", 10.0, T, T - 3600_000))
    db.conn.commit()
    game = FakeGame(db, cash=1000.0, positions={})
    play(db, game, s, lambda now: {"$IDXA": 60.0, "$PLAIN": 700.0 if now < T else 10.0}, T - 16 * 60_000, T + 60_000)
    assert {sid for _, sid, *_ in game.sent} == {"$PLAIN"}, game.sent
    owned, _ = events.reservations(db, s, T - 60_000, game.snap())
    assert "$IDXA" not in owned, "an excluded stock is not reserved for the event trader"
    db.set_setting(events.SETTINGS_KEY, json.dumps({"crashes": True, "excluded": ["$IDXA"]}))
    assert events.load_settings(db).excluded == ["$IDXA"]


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


def check_repeat_rounds():
    """Repeat in rounds: 2 runs, then a pause; after the pause the next round; without a pause the rule stops."""
    T = 90_000_000
    db = new_db()
    db.store_market(MarketSnapshot(
        format_version=1, game_version="test", sequence=1, written_at_ms=T, server_time_ms=T, server_tick=1,
        last_price_update_at_ms=T, market_ready=True, stocks=[Stock("$B", "$B", 20.0, True, 20.0, 1000, 0, 1000, 10**9)],
        player=Player(1000.0, 11000.0, 1, 0, 0, 0, BUY_CD_S, SHORT_CD_S, [Position("$B", 500, 25.0, 0, 0)]),
        market_news=[], scheduled_news=[]))
    rid = db.add_rule("$B", "stop_loss", "long", "price", 25.0, 10, 0.0, T, repeat=True,
                      repeat_times=2, repeat_wait_s=600)
    stop = db.add_rule("$B", "stop_loss", "long", "price", 24.0, 10, 0.0, T, repeat=True, repeat_times=1)
    game = FakeGame(db, 1000.0, {"$B": 500})
    game.now, game.prices = T, {"$B": 20.0}
    collector = SimpleNamespace(status=SimpleNamespace(copy=lambda: SimpleNamespace(last_market_read=time.time())))
    engine = AutomationEngine(collector, db.path, game)
    engine.bot.calibrated = True
    rule = lambda i: next(r for r in db.rules() if r["id"] == i)  # noqa: E731

    def step():
        engine._rearm.clear()                        # stands in for the price leaving the trigger zone
        engine._step(db)

    for _ in range(4):                               # fire, done, fire, done
        step()
    assert rule(rid)["runs"] == 2 and rule(rid)["pause_until_ms"] > time.time() * 1000, rule(rid)
    assert not rule(stop)["enabled"] and rule(stop)["runs"] == 1, "a round without a pause switches the rule off"
    sent = len(game.sent)
    step()
    step()
    assert len(game.sent) == sent and json.loads(rule(rid)["status"])["k"] == "rule.st.paused", "no run while paused"
    db.update_rule(rid, pause_until_ms=int(time.time() * 1000) - 1)
    step()
    assert len(game.sent) == sent + 1, "the next round starts after the pause"
    step()                                           # done: run 3, mid-round
    db.update_rule(rid, repeat=0, pause_until_ms=int(time.time() * 1000) + 600_000)
    step()
    assert len(game.sent) == sent + 2, "without repeat an old pause does not hold the rule"
    print(f"repeat rounds: {status_display(rule(rid)['status'])!r}, {len(game.sent)} sells")


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
    check_crash_spike()
    check_rebuy_checks()
    check_excluded()
    check_rules_yield()
    check_repeat_rounds()
    print("ok")
