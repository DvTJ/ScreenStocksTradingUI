"""Self-check for the config export/import:  python tools/check_config.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenstocks import config_io, events  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402


def check_config_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as d:
        src, dst = Storage(Path(d) / "a.db"), Storage(Path(d) / "b.db")
        src.add_rule("$BANK", "stop_loss", "long", "pct", 5.0, 100, 2.0, 0, repeat=True)
        events.save_settings(src, events.EventSettings(pumps=True, pump_drop_pct=4.0))
        file = Path(d) / "cfg.json"
        config_io.save_file(src, file)
        assert config_io.load_file(dst, file) == 1
        assert config_io.load_file(dst, file) == 0, "re-import must not duplicate rules"
        assert events.load_settings(dst).pump_drop_pct == 4.0 and dst.rules()[0]["repeat"] == 1
        part = config_io.export_config(src, rule_ids=set(), with_events=False)
        assert set(part) == {"format", "version"}, "only chosen parts may be exported"
        before = events.load_settings(dst)
        config_io.import_config(dst, part)
        assert events.load_settings(dst) == before, "absent blocks must not be touched"
        try:
            config_io.import_config(dst, {"format": "nope"})
            raise AssertionError("bad file accepted")
        except ValueError:
            pass
        src.close()
        dst.close()


if __name__ == "__main__":
    check_config_roundtrip()
    print("ok")
