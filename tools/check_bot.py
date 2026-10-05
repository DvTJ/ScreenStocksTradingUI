"""Self-check for the bot, its calibration and the config export/import:  python tools/check_bot.py"""

import math
from dataclasses import replace
import random
import string
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenstocks import bot, config_io  # noqa: E402
from screenstocks.i18n import de, en, fr  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402


def check_strategy() -> None:
    st = bot.Strategy(bot.Params(confirm_s=1), 3, True)
    for i in range(300):                                  # calm noise around 10
        st.update("A", i, 10 + (0.05 if i % 2 else -0.05))
    st.update("A", 300, 8.0)                              # sudden drop -> buy signal
    orders = st.orders(300, {"A": 8.0}, {}, True, True)
    assert orders and orders[0][:2] == ("A", "buy"), orders
    assert not st.orders(300, {"A": 8.0}, {}, False, True), "buy cooldown must block entries"
    assert not st.orders(300, {"A": 8.0}, {}, True, True, blocked={"A"}), "blocked stock must be skipped"
    held = {"A": {"side": "long", "entry_price": 8.0, "entry_s": 300}}
    for i in range(301, 330):                             # price recovers -> target exit
        st.update("A", i, 10.0)
    out = st.orders(330, {"A": 10.0}, held, True, True)
    assert out and out[0][:3] == ("A", "sell", "target"), out
    assert st.orders(330, {"A": 6.0}, held, True, True)[0][2] == "stop"
    st.per["A"] = bot.Params(stop_pct=50)                 # per-stock parameters win over the default
    assert not [o for o in st.orders(330, {"A": 6.0}, held, True, True) if o[2] == "stop"]


def check_blip_filter() -> None:
    def feed(drop_seconds: int):
        st = bot.Strategy(bot.Params(confirm_s=3), 3, False)
        for i in range(300):
            st.update("A", i, 10 + (0.05 if i % 2 else -0.05))
        for i in range(drop_seconds):                      # the price drops and stays there
            st.update("A", 300 + i, 8.0)
        now = 300 + drop_seconds - 1
        return st.orders(now, {"A": 8.0}, {}, True, True)
    assert not feed(1) and not feed(2), "a 1-2 s blip must not trigger an entry"
    assert feed(3) and feed(3)[0][:2] == ("A", "buy"), "a drop that lasts confirm_s seconds must"


def check_settings_and_sizing() -> None:
    s = bot.BotSettings.from_dict({"level": "bogus", "trade_pct": 500, "entry_z": 4.0, "overrides": {"stop_pct": 5,
                                   "nope": 1, "tau_s": -3}})
    assert (s.level, s.trade_pct, s.overrides) == ("simple", 100, {"stop_pct": 5.0}), s
    assert bot.effective(bot.BotSettings(shorts=True, max_positions=9))[1:] == (bot.PRESETS["balanced"][1], False), "simple level ignores extras"
    base, mp, shorts = bot.effective(bot.BotSettings(level="medium", caution="prudent", max_positions=1, shorts=True))
    assert (base.max_loss_pct, mp, shorts) == (bot.PRESETS["prudent"][0].max_loss_pct, 1, True)
    assert bot.effective(bot.BotSettings(level="advanced", overrides={"stop_pct": 5}))[0].stop_pct == 5
    big, small = bot.Params(stop_pct=10, max_loss_pct=1, jump_pct=60), bot.Params(stop_pct=10, max_loss_pct=1)
    assert bot.stake_pct(100, 20.0, big, 1000, 1000, 10, None, True) < bot.stake_pct(100, 20.0, small, 1000, 1000, 10, None, True),         "a stock that can jump further than the stop gets a smaller stake"
    assert bot.jump_p99([10, 10, 11, 11, 10]) > 9, "jump_p99 measures one-tick moves"
    risk = [bot.PRESETS[c][0].max_loss_pct for c in ("prudent", "balanced", "aggressive")]
    assert risk == sorted(risk) and len(set(risk)) == 3, "caution presets must rise in risk"
    assert len({bot.PRESETS[c][0].entry_z for c in ("prudent", "balanced")}) == 1 and bot.PRESETS["prudent"][0].entry_z <= 2.5,         "cautious presets must still be able to trade $PLAIN (entry_z 3.0+ never fired)"
    assert bot.effective(bot.BotSettings(level="medium", overrides={"stop_pct": 5}))[0].stop_pct == bot.PRESETS["balanced"][0].stop_pct, \
        "overrides only apply in the advanced level"
    sizes = [bot.size_pct(40, z, 3.0) for z in (3.0, 4.5, 6.0, 20.0)]
    assert sizes == sorted(sizes) and sizes[0] == 20 and sizes[-1] == 40, sizes     # never above trade_pct


def noisy(sigma: float, n: int, seed: int) -> list[float]:
    """Mean-reverting prices: an AR(1) deviation around 10 that lasts a few dozen seconds (so a 2 s order delay
    does not erase the edge); sigma is the std-dev of the deviation."""
    rnd, x, out = random.Random(seed), 0.0, []
    for _ in range(n):
        x = 0.97 * x + rnd.gauss(0, sigma * math.sqrt(1 - 0.97 ** 2))
        out.append(10 * math.exp(x))
    return out


def check_volume_limit() -> None:
    # pct % of what the game allows: all the cash, but a buy is limited by the shares still available
    assert bot.trade_money(10, 25, 1e6, 1e9, True) == 250000              # 25 % of the cash
    assert bot.trade_money(10, 100, 500, 1e6, True) == 500                # cash is the limit
    assert bot.trade_money(10, 100, 1e9, 40, True) == 400                 # few shares left
    assert bot.trade_money(10, 100, 1e9, 40, False) == 400                # ... and so is a short
    assert bot.trade_money(10, 100, 1e9, 0, True) == 0
    g = {"MR": noisy(0.04, 4000, 1)}
    per = {"MR": bot.calibrate(g, bot.BotSettings(level="medium", shorts=True))["MR"].params}
    big = bot.simulate(g, per, 25, 3, True, capital=1e9)
    capped = bot.simulate(g, per, 25, 3, True, capital=1e9, limits={"MR": 100})
    longs = lambda r: [x["stake"] for x in r["trades"] if x["side"] == "long"]  # noqa: E731
    assert longs(big) and max(longs(big)) > 10_000, "without a limit a buy uses the cash"
    assert max(x["stake"] for x in capped["trades"] if x["side"] == "long") <= 100 * 10 * 1.6, "buy stake over the shares left"
    assert all(x["exit_s"] >= x["entry_s"] for x in big["trades"]), "a position cannot be closed before its entry filled"
    no_buy = bot.simulate(g, per, 25, 3, True, limits={"MR": 0})
    assert all(x["side"] == "short" for x in no_buy["trades"]), "no shares available -> no buys"


def check_risk_limits() -> None:
    p = bot.Params(stop_pct=10, max_loss_pct=3.0)                  # 3 % / (10 % x 1.5 slippage) = 20 % of the cash
    assert bot.stake_pct(100, 20.0, p, 1000, 1000, 10, None, True) == 20, "stake capped by the loss budget"
    assert bot.stake_pct(10, 20.0, p, 1000, 1000, 10, None, True) == 10, "a smaller chosen stake is kept"
    assert bot.stake_pct(100, 20.0, p, 1000, 1000, 10, 50, True) == 40, "the budget is money: 40 % of the 50 shares left"
    assert bot.stake_pct(100, 20.0, p, 1000, 1000, 10, 5, True) == 100, "a tiny order is already within budget"
    assert bot.stake_pct(100, 20.0, bot.Params(stop_pct=10, max_loss_pct=0.01), 1000, 1000, 10, None, True) == 0
    lost = {"cash0": 1000, "trades": [{"ret": -10, "money": 600}, {"ret": 2, "money": 100}]}      # -60 + 2 = -58
    assert bot.loss_limit_reached(lost, 5) and not bot.loss_limit_reached(lost, 6) and not bot.loss_limit_reached(lost, 0)
    assert not bot.loss_limit_reached({"cash0": None, "trades": lost["trades"]}, 5), "no limit without the starting cash"
    g = {"MR": noisy(0.04, 4000, 1)}
    per = {"MR": bot.calibrate(g, bot.BotSettings(level="medium", shorts=True))["MR"].params}
    wide = bot.simulate(g, {"MR": bot.replace(per["MR"], max_loss_pct=100)}, 100, 3, True, capital=1e6)
    tight = bot.simulate(g, {"MR": bot.replace(per["MR"], max_loss_pct=1)}, 100, 3, True, capital=1e6)
    assert max(x["stake"] for x in tight["trades"]) < max(x["stake"] for x in wide["trades"]), "budget shrinks the stakes"


def check_news_and_events():
    import json, os, tempfile
    from screenstocks.events import SETTINGS_KEY
    from screenstocks.storage import Storage
    st = bot.Strategy(bot.Params(entry_z=3.0, confirm_s=5, min_edge_pct=1.0, news_s=20), 2, True)
    for i in range(300):
        st.update("$A", i, 100.0 if i < 290 else 100.0 * (1 + 0.04 * (i - 289)))
    assert st.z["$A"] is not None and st.z["$A"] > 0
    st._since.clear()                     # no confirmed signal: only the news may trigger
    assert not st.orders(299, {"$A": 108.0}, {}, True, True)
    st.news_event("$A", 298, "high")
    assert [o[:3] for o in st.orders(299, {"$A": 108.0}, {}, True, True)] == [("$A", "short", "entry")], "news short"
    assert not st.orders(299, {"$A": 108.0}, {}, True, True), "a news triggers once"
    db = Storage(os.path.join(tempfile.mkdtemp(), "x.db"))
    db.conn.execute("INSERT INTO scheduled_news VALUES ('o1', '$PLAIN', 'crash', 10, 1000000, 0)")
    assert not bot.BotTrader.event_guard(db, 1000000 - 16 * 60000), "event trading off: no guard"
    db.set_setting(SETTINGS_KEY, json.dumps({"crashes": True, "crash_minutes": 15}))
    assert not bot.BotTrader.event_guard(db, 1000000 - 30 * 60000)
    assert bot.BotTrader.event_guard(db, 1000000 - 16 * 60000), "keep the cooldowns free before an event"
    assert not bot.BotTrader.event_window(db, 1000000 - 3 * 3600_000), "an event announced hours ahead blocks nothing"
    assert "$PLAIN" in bot.BotTrader.event_window(db, 1000000 - 5 * 60000), "close to the event the stock is off limits"
    assert "$PLAIN" in bot.BotTrader.event_window(db, 1000000 + 10 * 60000), "...and while it recovers"
    assert not bot.BotTrader.event_window(db, 1000000 + 40 * 60000), "...but not forever"


def check_paper_mode():
    class NoOrders:
        def send(self, *a, **k):
            raise AssertionError("practice mode must never send an order")

    with tempfile.TemporaryDirectory() as d:
        db = Storage(Path(d) / "p.db")
        s = bot.BotSettings(enabled=True, paper=True, level="advanced", shorts=True, trade_pct=100,
                            overrides={"confirm_s": 3, "tau_s": 60, "entry_z": 2.0})
        bot.save_settings(db, s)
        tr = bot.BotTrader(NoOrders())
        p = bot.replace(bot.PRESETS["balanced"][0], tau_s=60, entry_z=2.0, confirm_s=3, min_edge_pct=2.0)
        tr.calib, tr.calibrated = {"MR": bot.Calib(p, 1.0, 5, 0.8)}, True
        tr._calib_key, tr._calib_at = (s.level, s.caution, s.shorts, tuple(sorted(s.overrides.items())), tuple(s.excluded)), 1e12
        snap = {"cash": 1000.0, "buy_cooldown_s": 85, "short_cooldown_s": 85}
        for i in range(400):
            price = 130.0 if 200 <= i < 230 else 100.0 + 0.05 * (i % 3)
            stocks = {"MR": {"last_price": price, "unlocked": 1, "available_shares": 1e9}}
            tr.step(db, s, True, False, float(i), i * 1000, stocks, {}, snap)     # automation switch OFF
        res = bot.load_results(db)
        assert res["cash0"] == 1000.0 and len(res["trades"]) == 1 and res["trades"][0]["side"] == "short", res
        assert res["trades"][0]["ret"] > 10, "the spike was shorted and covered when back to normal"
        cash, free = bot.paper_wallet(res, bot.BotTrader.held(db))
        assert cash > 1000 and free == cash, (cash, free)
        assert not db.get_setting("bot_results", "") and not db.get_setting("bot_state", ""), "real sheets untouched"
        said = [msg for _, sid, msg, _code in tr.thoughts if sid == "MR"]
        assert said and any("MR" in m for m in said), "the bot explains what it thinks"
        assert len({m for m in said}) > 2, "thoughts change with the situation (calm, confirming, decision ...)"
        db.close()


def check_prewarm_and_why():
    with tempfile.TemporaryDirectory() as d:
        db = Storage(Path(d) / "w.db")
        db.conn.execute("INSERT INTO stocks (stock_id, unlocked, last_price) VALUES ('MR', 1, 10)")
        for i, p in enumerate(noisy(0.01, 1800, 3)):
            db.conn.execute("INSERT INTO prices (stock_id, time_ms, price, tick) VALUES ('MR', ?, ?, ?)", (i * 1000, p, i))
        db.conn.commit()
        s = bot.BotSettings(enabled=True, paper=True)
        tr = bot.BotTrader(None)
        tr.calibrated, tr._calib_key, tr._calib_at = True, (s.level, s.caution, s.shorts, (), ()), 1e12
        stocks = {"MR": {"last_price": 10.0, "unlocked": 1, "available_shares": 1e9}}
        tr.step(db, s, True, False, 5000.0, 0, stocks, {}, {"cash": 1000.0})
        assert tr.strategy.z.get("MR") is not None, "history is replayed at start: no tau_s wait after a restart"
        st = bot.Strategy(bot.Params(entry_z=2.0, confirm_s=3), 1, True)
        assert st.why_not("X", 0, 10.0, None, True, True, {"buy": 0, "short": 0}, 0)[0] == "warmup"
        db.close()


def check_trade_history():
    res = {"since": 1, "cash0": 1000.0, "trades": [
        {"ts": 2000, "sid": "A", "side": "short", "ret": 3.0, "money": 100.0, "entry": 10.0, "exit": 9.7, "reason": "target", "held_s": 5},
        {"ts": 3000, "sid": "B", "side": "long", "ret": -2.0, "money": 50.0, "entry": 5.0, "exit": 4.9, "reason": "stop", "held_s": 9}]}
    h = bot.trade_history(res)
    assert [x["stock_id"] for x in h["trades"]] == ["B", "A"], "newest first"
    assert h["n"] == 2 and abs(h["profit"] - 2.0) < 1e-9 and h["win_rate"] == 50.0 and h["per_stock"]["A"]["profit"] == 3.0
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.csv"
        bot.export_trades_csv(res, path)
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        assert len(lines) == 3 and lines[1].split(",")[1] == "A", lines


def check_clear_history():
    from screenstocks.i18n import de, en, fr
    with tempfile.TemporaryDirectory() as d:
        db = Storage(Path(d) / "c.db")
        bot.save_results(db, {"since": 1, "cash0": 100.0, "trades": [{"ts": 1, "sid": "A", "side": "long", "ret": 1.0, "money": 5.0, "reason": "target"}]})
        for lang in (de, en, fr):                      # journal lines written in any language go
            db.log_rule(1, None, "A", f"{lang.STRINGS['bot.name']}: something")
        db.log_rule(1, None, "A", "Limit buy triggered: your own automation rule")
        tr = bot.BotTrader(None)
        tr.thoughts.append((1, "A", "x", "calm"))
        tr._blocked["A"] = 1e18
        bot.clear_history(db, tr)
        assert bot.load_results(db)["trades"] == [] and not tr.thoughts and not tr._blocked
        left = [m for *_, m in db.rule_log(10)]
        assert left == ["Limit buy triggered: your own automation rule"], left
        db.close()


def check_calibration() -> None:
    s = bot.BotSettings(level="medium", shorts=True)
    grids = {"MR": noisy(0.04, 4000, 1), "FLAT": [10.0] * 4000}   # mean-reverting noise vs a dead stock
    calib = bot.calibrate(grids, s)
    assert calib["MR"].good, calib["MR"]
    assert not calib["FLAT"].good and calib["FLAT"].n == 0
    assert bot.pick(calib, 3) == ["MR"]
    assert bot.auto_params(calib, s)["tau_s"] == calib["MR"].params.tau_s
    res = bot.simulate({"MR": grids["MR"]}, {"MR": calib["MR"].params}, 25, 3, True)
    assert res["n"] > 0 and res["worst"] <= res["best"], res
    gain = bot.summarize([{"ret": 10.0, "money": 100, "sid": "A"}, {"ret": -4.0, "money": 50, "sid": "B"}])
    assert gain["n"] == 2 and gain["gain"] == 8.0 and gain["win_rate"] == 50 and gain["worst"]["sid"] == "B", gain


def check_backtest_and_state() -> None:
    with tempfile.TemporaryDirectory() as d:
        db = Storage(Path(d) / "a.db")
        db.conn.execute("INSERT INTO stocks (stock_id, unlocked, last_price) VALUES ('MR', 1, 10)")
        for i, p in enumerate(noisy(0.04, 14000, 2)):
            db.conn.execute("INSERT INTO prices (stock_id, time_ms, price, tick) VALUES ('MR', ?, ?, ?)",
                           (i * 1000, p, i))
        db.conn.commit()
        assert bot.backtest(db, bot.BotSettings(), 0, 600_000) is None, "too little history must be refused"
        res = bot.backtest(db, bot.BotSettings(level="advanced", overrides={"confirm_s": 1}), 0, 13_999_000)
        assert res and res["n"] > 0 and res["hours"] > 1, res
        short = bot.backtest(db, bot.BotSettings(level="advanced", overrides={"confirm_s": 1}), 0, 13_999_000, test_s=3600)
        assert short and abs(short["hours"] - 1) < 0.01, "test period must follow the chosen range"
        assert all(x["stake"] > 0 and "exit_s" in x for x in short["trades"]) and short["cooldowns"] == (85, 85)
        assert bot.backtest(db, bot.BotSettings(excluded=["MR"]), 0, 13_999_000) is None, "excluded stocks are not traded"
        r = bot.load_results(db)
        assert r == {"since": None, "trades": [], "cash0": None}
        bot.save_results(db, {"since": 5, "trades": [{"ret": 1}]})
        assert bot.load_results(db)["trades"] == [{"ret": 1}]
        db.close()


def check_config_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        src, dst = Storage(Path(d) / "a.db"), Storage(Path(d) / "b.db")
        src.add_rule("$BANK", "stop_loss", "long", "pct", 5.0, 100, 2.0, 0, repeat=True)
        mine = bot.BotSettings(enabled=True, level="advanced", trade_pct=40, excluded=["$X"], overrides={"entry_z": 4.0})
        bot.save_settings(src, mine)
        file = Path(d) / "cfg.json"
        config_io.save_file(src, file, with_bot=True)
        assert config_io.load_file(dst, file) == 1
        assert config_io.load_file(dst, file) == 0, "re-import must not duplicate rules"
        assert bot.load_settings(dst) == replace(mine, enabled=False) and dst.rules()[0]["repeat"] == 1, "bot settings arrive switched off"
        part = config_io.export_config(src, rule_ids=set(), with_events=False, with_bot=False)
        assert set(part) == {"format", "version"}, "only chosen parts may be exported"
        before = bot.load_settings(dst)
        config_io.import_config(dst, part)
        assert bot.load_settings(dst) == before, "absent blocks must not be touched"
        old_file = {"format": config_io.FORMAT, "version": 1, "bot": {"enabled": True, "entry_z": 4.0, "tau_s": 99}}
        config_io.import_config(dst, old_file)
        assert not bot.load_settings(dst).enabled and bot.load_settings(dst).level == "simple", "old files import but never switch the bot on"
        try:
            config_io.import_config(dst, {"format": "nope"})
            raise AssertionError("bad file accepted")
        except ValueError:
            pass
        src.close()
        dst.close()


def check_translations() -> None:
    fmt = string.Formatter()
    holes = lambda s: {f[1] for f in fmt.parse(s) if f[1]}  # noqa: E731
    assert set(de.STRINGS) == set(en.STRINGS) == set(fr.STRINGS), "language files must have the same keys"
    for k, v in en.STRINGS.items():
        assert holes(v) == holes(de.STRINGS[k]) == holes(fr.STRINGS[k]), f"placeholders differ: {k}"
    assert bot.BotSettings().enabled is False, "the bot must be off by default"
    assert bot.BotSettings().trade_events is False and bot.BotSettings().paper is False, "events and practice are opt-in"


if __name__ == "__main__":
    check_strategy()
    check_blip_filter()
    check_settings_and_sizing()
    check_volume_limit()
    check_risk_limits()
    check_news_and_events()
    check_paper_mode()
    check_prewarm_and_why()
    check_trade_history()
    check_clear_history()
    check_calibration()
    check_backtest_and_state()
    check_config_roundtrip()
    check_translations()
    print("ok")
