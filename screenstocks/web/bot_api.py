"""Bot tab of the web UI: switch, level, settings, results, positions, journal and the history test.

Mixed into Bridge (bridge.py). The logic (settings, status sentence, history test, export/import) lives
in screenstocks/bot.py and is shared with the classic Tkinter tab.
"""

import os
import threading
import time
from dataclasses import asdict
from typing import Optional

import webview

from .. import bot
from ..i18n import t

JSON_TYPES = ("JSON (*.json)",)
CSV_TYPES = ("CSV (*.csv)",)


class BotApi:
    _bot_test: dict = {"state": "idle"}      # history test: idle / running / done / error (+ text, res)

    # --------------------------------------------------------------------- read

    def bot(self) -> dict:
        """Everything the tab shows (called every second while it is open)."""
        if self._closing:
            return {}
        tr = self._engine.bot
        with self._lock:
            db = self._db
            s = bot.load_settings(db)
            held = bot.BotTrader.held(db)
            res = bot.load_results(db)
            stocks = db.stock_ids()
            positions = []
            for sid, h in held.items():
                last = db.latest_price(sid)
                price = last[1] if last else None
                gain = (price / h["entry_price"] - 1) * (1 if h["side"] == "long" else -1) * 100 if price else None
                positions.append(dict(stock=sid, side=h["side"], side_text=t(f"side.{h['side']}"), entry=h["entry_price"],
                                      target=h.get("target"), price=price, gain=gain, money=h.get("money")))
            prefix = f"{t('bot.name')}: "
            journal = [dict(id=lid, time=ts, msg=msg[len(prefix):])
                       for lid, ts, _rid, _sid, msg in db.rule_log(300) if msg.startswith(prefix)]
            cash = (db.latest_snapshot() or {}).get("cash")
        text, tone = bot.state_sentence(s, self._engine.state, tr, held)
        sm = bot.summarize(res["trades"])
        test = self._bot_test
        return {
            "settings": asdict(s), "auto": bot.auto_params(tr.calib, s), "stocks": stocks, "cash": cash,
            "presets": {k: v[1] for k, v in bot.PRESETS.items()},
            "state": {"text": text, "tone": tone},
            "results": {"since": res["since"], "n": sm["n"], "gain": sm["gain"], "win_rate": sm["win_rate"],
                        "best": sm["best"], "worst": sm["worst"], "none": t("bot.results.none")},
            "positions": positions, "journal": journal,
            "thoughts": [dict(time=ms, sid=sid, msg=msg, code=code) for ms, sid, msg, code in reversed(tr.thoughts)][:150],
            "think_status": {"last_ms": tr.last_check_ms, "watching": tr.watching, "now_ms": int(time.time() * 1000)},
            "test": {"state": test.get("state", "idle"), "text": test.get("text", ""), "has_detail": bool(test.get("res"))},
        }

    def bot_clear_history(self) -> dict:
        """Delete the trades of the current mode, the bot's journal and its thoughts (the UI asks first)."""
        with self._lock:
            bot.clear_history(self._db, self._engine.bot)
        return {"ok": True, "message": t("bot.cleared")}

    def bot_trades(self) -> dict:
        """Every trade of the current activation (real or practice sheet), newest first, with per-stock totals."""
        with self._lock:
            res, paper = bot.load_results(self._db), bot.load_settings(self._db).paper
        return {**bot.trade_history(res), "paper": paper}

    def bot_delete_trade(self, ts: int) -> dict:
        with self._lock:
            bot.delete_trade(self._db, int(ts))
        return {"ok": True}

    def bot_export_trades(self) -> dict:
        path = self._bot_path("screenstocks-bot-trades.csv", CSV_TYPES, ".csv")
        if not path:
            return {"cancelled": True}
        try:
            with self._lock:
                bot.export_trades_csv(bot.load_results(self._db), path)
        except OSError as exc:
            return {"error": t("common.error", error=exc)}
        return {"message": t("bot.trades_exported", path=path), "path": path}

    def bot_test_detail(self) -> dict:
        """Per-stock profit, stats per period and every trade of the last history test."""
        res = self._bot_test.get("res")
        return bot.test_breakdown(res) if res else {}

    # -------------------------------------------------------------------- write

    def bot_save(self, values: dict) -> dict:
        """Store the settings (invalid numbers are clamped by BotSettings). Returns {"ok", "settings"}."""
        try:
            new = bot.BotSettings.from_dict(values)
        except (TypeError, ValueError, AttributeError):
            return {"ok": False}
        with self._lock:
            if new != bot.load_settings(self._db):
                bot.save_settings(self._db, new)
        return {"ok": True, "settings": asdict(new)}

    def bot_reset_auto(self) -> dict:
        """Forget the manual advanced values: the calibration decides again."""
        with self._lock:
            s = bot.load_settings(self._db)
            s.overrides = {}
            bot.save_settings(self._db, s)
        return {"ok": True, "settings": asdict(s)}

    def bot_test_start(self, range_key: str, capital, use_cash: bool) -> None:
        """Run the history test in the background; the tab polls bot() for the outcome."""
        if self._bot_test.get("state") == "running":
            return
        with self._lock:
            s = bot.load_settings(self._db)
            path = self._db.path
        try:
            money: Optional[float] = None if use_cash else max(1.0, float(str(capital).replace(",", ".").replace(" ", "")))
        except ValueError:
            money = None
        test_s = bot.TEST_RANGES.get(range_key)
        self._bot_test = {"state": "running"}

        def work() -> None:
            try:
                text, res = bot.run_test(path, s, test_s, money)
                self._bot_test = {"state": "done", "text": text, "res": res}
            except Exception as exc:
                self._bot_test = {"state": "error", "text": t("common.error", error=exc)}

        threading.Thread(target=work, daemon=True, name="bot-test").start()

    # ------------------------------------------------------------ files (dialogs)

    def _bot_path(self, save_name: Optional[str], types=JSON_TYPES, ext: str = ".json") -> Optional[str]:
        mode = webview.FileDialog.SAVE if save_name else webview.FileDialog.OPEN
        result = self._window.create_file_dialog(mode, save_filename=save_name or "", file_types=types)
        if not result:
            return None
        path = str(result[0] if isinstance(result, (tuple, list)) else result)
        return path + ext if save_name and not path.lower().endswith(ext) else path

    def bot_export_setup(self) -> dict:
        path = self._bot_path("screenstocks-bot.json")
        if not path:
            return {"cancelled": True}
        try:
            with self._lock:
                bot.export_setup(self._db, path)
        except OSError as exc:
            return {"error": t("common.error", error=exc)}
        return {"message": t("bot.exported", path=path), "path": path}

    def reveal_file(self, path: str) -> None:
        """Show an exported file in the file manager."""
        path = os.path.normpath(path or "")
        if os.path.isfile(path):
            bot.reveal(path)
        elif os.path.isdir(os.path.dirname(path)):         # the file is gone: at least open its folder
            os.startfile(os.path.dirname(path)) if os.name == "nt" else bot.reveal(path)

    def bot_experimental(self, ack: bool = False) -> bool:
        """Whether the "experimental" warning was already acknowledged; ack=True records it."""
        with self._lock:
            if ack:
                self._db.set_setting("bot_warning_ack", "1")
            return self._db.get_setting("bot_warning_ack", "") == "1"

    def bot_import_setup(self) -> dict:
        path = self._bot_path(None)
        if not path:
            return {"cancelled": True}
        try:
            with self._lock:
                bot.import_setup(self._db, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"error": t("config.invalid", error=exc)}
        return {"message": t("bot.imported")}

    def bot_export_report(self) -> dict:
        """The last history test with setup, calibration, live results and journal, to share."""
        path = self._bot_path("screenstocks-bot-report.json")
        if not path:
            return {"cancelled": True}
        try:
            with self._lock:
                bot.save_report(self._db, self._engine.bot.calib, self._bot_test.get("res"), path,
                                self._engine.bot.thoughts)
        except (OSError, TypeError, ValueError) as exc:
            return {"error": t("common.error", error=exc)}
        return {"message": t("bot.results_exported", path=path), "path": path}
