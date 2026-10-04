"""Self-check for the bot and the config export/import:  python tools/check_bot.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenstocks import bot, config_io  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402


def check_strategy() -> None:
    s = bot.BotSettings(shorts=True)
    st = bot.Strategy(s)
    for i in range(300):                                  # calm noise around 10
        st.update("A", i, 10 + (0.05 if i % 2 else -0.05))
    st.update("A", 300, 8.0)                              # sudden drop -> buy signal
    orders = st.orders(300, {"A": 8.0}, {}, True, True)
    assert orders and orders[0][:2] == ("A", "buy"), orders
    assert not st.orders(300, {"A": 8.0}, {}, False, True), "buy cooldown must block entries"
    held = {"A": {"side": "long", "entry_price": 8.0, "entry_s": 300}}
    for i in range(301, 330):                             # price recovers -> target exit
        st.update("A", i, 10.0)
    out = st.orders(330, {"A": 10.0}, held, True, True)
    assert out and out[0][:3] == ("A", "sell", "target"), out
    out = st.orders(330, {"A": 6.0}, held, True, True)
    assert out[0][2] == "stop", out


def check_config_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        src, dst = Storage(Path(d) / "a.db"), Storage(Path(d) / "b.db")
        src.add_rule("$BANK", "stop_loss", "long", "pct", 5.0, 100, 2.0, 0, repeat=True)
        bot.save_settings(src, bot.BotSettings(enabled=True, entry_z=4.0))
        file = Path(d) / "cfg.json"
        config_io.save_file(src, file)
        assert config_io.load_file(dst, file) == 1
        assert config_io.load_file(dst, file) == 0, "re-import must not duplicate rules"
        assert bot.load_settings(dst).entry_z == 4.0 and dst.rules()[0]["repeat"] == 1
        part = config_io.export_config(src, rule_ids=set(), with_events=False, with_bot=False)
        assert set(part) == {"format", "version"}, "only chosen parts may be exported"
        before = bot.load_settings(dst)
        config_io.import_config(dst, part)
        assert bot.load_settings(dst) == before, "absent blocks must not be touched"
        try:
            config_io.import_config(dst, {"format": "nope"})
            raise AssertionError("bad file accepted")
        except ValueError:
            pass
        src.close()
        dst.close()


if __name__ == "__main__":
    check_strategy()
    check_config_roundtrip()
    print("ok")
