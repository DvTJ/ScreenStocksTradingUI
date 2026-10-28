"""Upgrades and Leaderboard tabs and the extension settings page: the optional game extension
(screenstocks/game_bridge.py).

Mixed into Bridge (bridge.py). Nothing is installed or bought without a click; the two tabs only exist
while the extension is installed. Errors come back as {"error": code, "detail": text} and the page
translates the code.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from .. import game_bridge, settings as settings_mod

log = logging.getLogger(__name__)

BOARD_FRESH_S = 60            # a leaderboard younger than this is shown without asking the game again


class UpgradesApi:
    _ext_client: Optional[game_bridge.Client] = None
    _board_client: Optional[game_bridge.Client] = None   # own connection: a board request may take seconds
    _ext_lock = threading.Lock()
    _boards: dict = {}                                    # mode -> (local time, rows)

    def _game_dir(self) -> Optional[Path]:
        chosen = Path(self._settings.game_dir) if self._settings.game_dir else None
        if chosen and game_bridge.is_game_dir(chosen):
            return chosen
        return game_bridge.find_game_dir()

    def _ext(self, game_dir: Path, board: bool = False) -> game_bridge.Client:
        attr = "_board_client" if board else "_ext_client"
        with self._ext_lock:
            client = getattr(self, attr)
            if client is None or client.game_dir != game_dir:
                if client is not None:
                    client.close()
                client = game_bridge.Client(game_dir, timeout=20 if board else 5)
                setattr(self, attr, client)
            return client

    def _close_ext(self) -> None:
        for client in (self._ext_client, self._board_client):
            if client is not None:
                client.close()

    @staticmethod
    def _error(exc: Exception) -> dict:
        if isinstance(exc, game_bridge.BridgeError):
            return {"error": exc.code, "detail": str(exc) if str(exc) != exc.code else ""}
        log.exception("game extension")
        return {"error": "failed", "detail": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ state

    def extension(self) -> dict:
        """What is installed (settings page, wizard, and whether the page shows the extension tabs)."""
        info = {"supported": game_bridge.supported(), "bridge": game_bridge.BRIDGE.version,
                "bepinex": game_bridge.BEPINEX.version, "page": game_bridge.BRIDGE_PAGE}
        if info["supported"]:
            info.update(game_bridge.status(self._game_dir()))
        info["installed"] = bool(info.get("plugin"))
        return info

    def upgrades(self) -> dict:
        """Extension state and, when the bridge answers, the game's upgrade catalog (every 2 s while open)."""
        if self._closing:
            return {}
        info = self.extension()
        if not info["installed"]:
            return info
        try:
            info["upgrades"] = self._ext(Path(info["game_dir"])).upgrades()
        except Exception as exc:
            info["conn"] = self._error(exc)
        return info

    def leaderboard(self, mode: str, force: bool = False) -> dict:
        """{"mode", "rows", "self_rank", "total", "age_s", "retry_s"} - a fresh board at most every BOARD_FRESH_S
        (the game allows one request per 30 s for all boards together); otherwise the last one of that mode."""
        if self._closing or mode not in game_bridge.LEADERBOARD_MODES:
            return {}
        info = self.extension()
        if not info["installed"]:
            return {"error": "not_installed"}
        now = time.time()
        cached = self._boards.get(mode)
        retry_s = 0
        if force or cached is None or now - cached[0] >= BOARD_FRESH_S:
            try:
                res = self._ext(Path(info["game_dir"]), board=True).leaderboard(mode)
                cached = (now, self._board_rows(res))
                self._boards[mode] = cached
            except game_bridge.BridgeError as exc:
                if cached is None or exc.code not in ("rate_limited", "leaderboard_busy"):
                    return {**self._error(exc), "retry_s": exc.retry_after_ms / 1000}
                retry_s = exc.retry_after_ms / 1000
            except Exception as exc:
                return self._error(exc)
        return {"mode": mode, **cached[1], "age_s": now - cached[0], "retry_s": retry_s}

    @staticmethod
    def _board_rows(res: dict) -> dict:
        rows = [{"rank": e.get("rank"), "name": e.get("displayName") or "", "clan": e.get("clan") or "",
                 "net": game_bridge.big_number(e.get("netWorth")), "ipo": e.get("ipoCount"),
                 "share": e.get("playerPercentage")} for e in res.get("entries") or []]
        return {"rows": rows, "self_rank": res.get("selfRank"), "total": res.get("totalRanked")}

    # ------------------------------------------------------------------ install / remove

    def upgrades_install(self) -> dict:
        game_dir = self._game_dir()
        if game_dir is None:
            return {"error": "no_game"}
        try:
            game_bridge.install(game_dir)
        except Exception as exc:
            return self._error(exc)
        return {"ok": True}

    def upgrades_remove(self) -> dict:
        game_dir = self._game_dir()
        if game_dir is None:
            return {"error": "no_game"}
        self._close_ext()
        before = game_bridge.status(game_dir)
        try:
            after = game_bridge.remove(game_dir)
        except Exception as exc:
            return self._error(exc)
        # the Steam launch option stays: on macOS the game does not start while it names a removed script
        gone = before.get("bepinex") and not after.get("bepinex")
        return {"ok": True, "build": before.get("build"), "launch_option": before.get("launch_option", "") if gone else ""}

    def upgrades_buy(self, upgrade_id: str, quantity: int = 1) -> dict:
        game_dir = self._game_dir()
        if game_dir is None or not isinstance(upgrade_id, str):
            return {"error": "no_game"}
        try:
            result = self._ext(game_dir).purchase(upgrade_id, max(1, min(1000, int(quantity))))
        except Exception as exc:
            return self._error(exc)
        log.info("upgrade purchase submitted: %s x%s (level %s -> %s)", upgrade_id, quantity,
                 result.get("levelBefore"), result.get("levelAfter"))
        return {"ok": True, **result}

    def upgrades_choose_game(self) -> dict:
        """Folder dialog for a game installed outside Steam's usual places."""
        import webview                          # only here: the tests import this module without pywebview
        start = str(self._game_dir() or "")
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        if not result:
            return {}
        chosen = game_bridge.game_dir_of(Path(result[0] if isinstance(result, (tuple, list)) else result))
        if not game_bridge.is_game_dir(chosen):
            return {"error": "not_game_dir", "detail": str(chosen)}
        self._settings = settings_mod.load()
        self._settings.game_dir = str(chosen)
        settings_mod.save(self._settings)
        return {"ok": True}
