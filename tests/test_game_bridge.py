"""Upgrade extension (screenstocks/game_bridge.py): install / remove in a fake game folder, config, client protocol."""

import hashlib
import io
import json
import socket
import threading
import zipfile
from pathlib import Path

import pytest

from screenstocks import game_bridge as gb


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


BEPINEX_ZIP = _zip({"winhttp.dll": b"x", "doorstop_config.ini": b"[General]", ".doorstop_version": b"4",
                    "changelog.txt": b"", "BepInEx/core/BepInEx.dll": b"core"})
BRIDGE_ZIP = _zip({"BepInEx/plugins/": b"", "BepInEx/plugins/ScreenStocksBridge/ScreenStocksBridge.dll": b"plugin",
                   "BepInEx/plugins/ScreenStocksBridge/LICENSE": b"MIT-0"})


@pytest.fixture
def game(tmp_path, monkeypatch):
    (tmp_path / gb.GAME_EXE).write_bytes(b"")
    (tmp_path / "Screen Stocks_Data" / "Managed").mkdir(parents=True)
    packages = {gb.BEPINEX.url: BEPINEX_ZIP, gb.BRIDGE.url: BRIDGE_ZIP}
    monkeypatch.setattr(gb, "BEPINEX", gb.BEPINEX.__class__(
        "BepInEx", "5", gb.BEPINEX.url, hashlib.sha256(BEPINEX_ZIP).hexdigest()))
    monkeypatch.setattr(gb, "BRIDGE", gb.BRIDGE.__class__(
        "Bridge", "0.1", gb.BRIDGE.url, hashlib.sha256(BRIDGE_ZIP).hexdigest()))
    monkeypatch.setattr(gb, "download", lambda pkg: (gb.verify(pkg, packages[pkg.url]), packages[pkg.url])[1])
    monkeypatch.setattr(gb, "game_running", lambda: False)
    return tmp_path


def test_install_and_remove_with_bepinex(game):
    st = gb.install(game)
    assert st["bepinex"] and st["plugin"] and st["ours"] and st["plugin_version"] == "0.1"
    port, token = gb.read_config(game)
    assert port == gb.DEFAULT_PORT and len(token) >= 40
    cfg = (game / gb.CONFIG_FILE).read_text(encoding="utf-8")
    assert "AutoClaimLevelRewards = false" in cfg and "AutoCloseOfflineSummary = false" in cfg
    st = gb.remove(game)
    assert not st["bepinex"] and not st["plugin"]
    assert not (game / "BepInEx").exists() and not (game / "winhttp.dll").exists()
    assert (game / gb.GAME_EXE).exists(), "the game itself stays untouched"


def test_existing_bepinex_is_kept(game):
    (game / "winhttp.dll").write_bytes(b"theirs")
    (game / "BepInEx" / "core").mkdir(parents=True)
    (game / "BepInEx" / "core" / "BepInEx.dll").write_bytes(b"theirs")
    (game / "BepInEx" / "plugins" / "OtherMod").mkdir(parents=True)
    gb.install(game)
    assert (game / "winhttp.dll").read_bytes() == b"theirs"
    gb.remove(game)
    assert (game / "winhttp.dll").exists() and (game / "BepInEx" / "plugins" / "OtherMod").is_dir()
    assert not (game / gb.PLUGIN_DIR).exists()


def test_bad_checksum_writes_nothing(game, monkeypatch):
    monkeypatch.setattr(gb, "BRIDGE", gb.BRIDGE.__class__("Bridge", "0.1", gb.BRIDGE.url, "0" * 64))
    with pytest.raises(gb.BridgeError) as err:
        gb.install(game)
    assert err.value.code == "checksum"
    assert not (game / "BepInEx").exists() and not (game / "winhttp.dll").exists()


def test_archive_cannot_escape_the_game_folder(game):
    with pytest.raises(gb.BridgeError):
        gb._extract(_zip({"BepInEx/plugins/../../evil.dll": b"x"}), game, ("BepInEx/plugins/",))
    with pytest.raises(gb.BridgeError):
        gb._extract(_zip({"elsewhere.dll": b"x"}), game, ("BepInEx/plugins/",))


def test_closed_game_and_foreign_install_are_refused(game, monkeypatch):
    with pytest.raises(gb.BridgeError) as err:
        gb.remove(game)
    assert err.value.code == "not_ours"
    monkeypatch.setattr(gb, "game_running", lambda: True)
    with pytest.raises(gb.BridgeError) as err:
        gb.install(game)
    assert err.value.code == "game_running"


def test_client_protocol(game):
    """JSON lines with id + token; events in between are skipped; errors keep their code."""
    gb.write_config(game)
    _, token = gb.read_config(game)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    cfg = game / gb.CONFIG_FILE
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(f"Port = {gb.DEFAULT_PORT}",
                                                           f"Port = {server.getsockname()[1]}"), encoding="utf-8")
    seen = []

    def serve():
        conn, _ = server.accept()
        f = conn.makefile("rwb")
        for line in f:
            req = json.loads(line)
            seen.append(req)
            if req["token"] != token:
                out = {"id": req["id"], "ok": False, "error": {"code": "unauthorized"}}
            elif req["method"] == "upgrades.snapshot":
                f.write(b'{"event":"market.updated","data":{}}\n')
                out = {"id": req["id"], "ok": True, "result": {"ready": True, "upgrades": [
                    {"upgradeId": "BuyCooldown", "currentLevel": 3, "nextPrice": "1500"}]}}
            else:
                out = {"id": req["id"], "ok": False, "error": {"code": "purchase_rejected", "message": "no"}}
            f.write((json.dumps(out) + "\n").encode())
            f.flush()

    threading.Thread(target=serve, daemon=True).start()
    client = gb.Client(game, timeout=5)
    try:
        assert client.upgrades()[0]["upgradeId"] == "BuyCooldown"
        with pytest.raises(gb.BridgeError) as err:
            client.purchase("BuyCooldown", 1)
        assert err.value.code == "purchase_rejected"
        assert seen[1]["params"] == {"upgradeId": "BuyCooldown", "quantity": 1}
    finally:
        client.close()
        server.close()


def test_offline_bridge(game):
    gb.write_config(game)
    cfg = game / gb.CONFIG_FILE
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(f"Port = {gb.DEFAULT_PORT}", "Port = 1"), encoding="utf-8")
    with pytest.raises(gb.BridgeError) as err:
        gb.Client(game, timeout=1).upgrades()
    assert err.value.code == "offline"


def test_pinned_packages_look_sane():
    for pkg in (gb.BEPINEX, gb.BRIDGE):
        assert pkg.url.startswith("https://github.com/") and len(pkg.sha256) == 64
    assert Path(gb.MARKER_FILE).parent == gb.PLUGIN_DIR


def test_big_number_forms():
    assert gb.big_number("{m=1.1609495412814,e=12}") == 1.1609495412814e12
    assert gb.big_number("134266761891.88789") == 134266761891.88789
    assert gb.big_number(5) == 5.0
    assert gb.big_number("") is None and gb.big_number(None) is None and gb.big_number("{m=x,e=1}") is None


def test_leaderboard_cache_and_rate_limit(game, monkeypatch):
    """A board is asked for at most once a minute; while the game rate-limits, the last copy is shown."""
    from screenstocks.web.upgrades_api import UpgradesApi

    class FakeClient:
        game_dir = game
        calls = 0
        limited = False

        def leaderboard(self, mode):
            FakeClient.calls += 1
            if FakeClient.limited:
                raise gb.BridgeError("rate_limited", "", 12000)
            return {"selfRank": 7, "totalRanked": 99, "entries": [
                {"rank": 7, "displayName": "me", "clan": "c", "netWorth": "{m=2,e=9}", "ipoCount": 1}]}

        def close(self):
            pass

    api = UpgradesApi()
    api._closing, api._boards = False, {}
    monkeypatch.setattr(api, "extension", lambda: {"installed": True, "game_dir": str(game)})
    monkeypatch.setattr(api, "_ext", lambda game_dir, board=False: FakeClient())
    d = api.leaderboard("current")
    assert d["rows"][0]["net"] == 2e9 and d["self_rank"] == 7 and d["total"] == 99
    api.leaderboard("current")
    assert FakeClient.calls == 1, "fresh copy reused"
    FakeClient.limited = True
    d = api.leaderboard("current", force=True)
    assert d["rows"] and d["retry_s"] == 12, "rate limited: the last copy with the wait time"
    d = api.leaderboard("ipo")
    assert d["error"] == "rate_limited" and d["retry_s"] == 12, "nothing cached for that list yet"
    assert api.leaderboard("nonsense") == {}


MAC_BEPINEX_ZIP = _zip({"libdoorstop.dylib": b"x", "run_bepinex.sh": b"#!/bin/sh\n", ".doorstop_version": b"4",
                        "changelog.txt": b"", "BepInEx/core/BepInEx.dll": b"core"})


@pytest.fixture
def mac_game(game, monkeypatch):
    """The native macOS build: an app bundle instead of Screen Stocks.exe."""
    (game / gb.GAME_EXE).unlink()
    (game / "Screen Stocks_Data" / "Managed").rmdir()
    (game / "Screen Stocks_Data").rmdir()
    (game / "Screen Stocks.app" / "Contents" / "Resources" / "Data" / "Managed").mkdir(parents=True)
    monkeypatch.setattr(gb, "BEPINEX_MAC", gb.BEPINEX.__class__(
        "BepInEx", "5", "mac-url", hashlib.sha256(MAC_BEPINEX_ZIP).hexdigest()))
    bridge = gb.BRIDGE
    packages = {"mac-url": MAC_BEPINEX_ZIP, bridge.url: BRIDGE_ZIP}
    monkeypatch.setattr(gb, "download", lambda pkg: (gb.verify(pkg, packages[pkg.url]), packages[pkg.url])[1])
    monkeypatch.setattr(gb, "steam_roots", lambda: [])
    return game


def test_macos_build_install_and_remove(mac_game):
    assert gb.game_build(mac_game) == "macos" and gb.game_dir_of(mac_game / "Screen Stocks.app") == mac_game
    st = gb.install(mac_game)
    assert st["build"] == "macos" and st["bepinex"] and st["plugin"]
    assert st["launch_option"] == f'"{mac_game / "run_bepinex.sh"}" %command%'
    assert st["launch_set"] is None, "no Steam user found: unknown"
    assert not (mac_game / "winhttp.dll").exists()
    gb.remove(mac_game)
    assert not (mac_game / "libdoorstop.dylib").exists() and not (mac_game / "run_bepinex.sh").exists()
    assert (mac_game / "Screen Stocks.app").is_dir()


def test_il2cpp_build_is_refused(mac_game):
    (mac_game / "Screen Stocks.app" / "Contents" / "Resources" / "Data" / "Managed").rmdir()
    with pytest.raises(gb.BridgeError) as err:
        gb.install(mac_game)
    assert err.value.code == "il2cpp"


def test_proton_launch_option_is_read_from_steam(game, tmp_path_factory, monkeypatch):
    """The Windows build on Linux needs the winhttp DLL override; it is only read from Steam, never written."""
    steam = tmp_path_factory.mktemp("steam")
    cfg = steam / "userdata" / "123" / "config" / "localconfig.vdf"
    cfg.parent.mkdir(parents=True)
    monkeypatch.setattr(gb, "steam_roots", lambda: [steam])
    monkeypatch.setattr(gb.sys, "platform", "linux")
    assert gb.launch_option(game) == gb.WINE_OVERRIDE
    assert gb.launch_option_set(game) is None
    vdf = '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n' \
          '\t\t\t\t\t"4356780"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LastPlayed"\t\t"1"\n%s\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
    cfg.write_text(vdf % "", encoding="utf-8")
    assert gb.launch_option_set(game) is False
    cfg.write_text(vdf % '\t\t\t\t\t\t"LaunchOptions"\t\t"WINEDLLOVERRIDES=\\"winhttp=n,b\\" %command%"\n', encoding="utf-8")
    assert gb.steam_launch_options() == [gb.WINE_OVERRIDE]
    assert gb.launch_option_set(game) is True
    monkeypatch.setattr(gb.sys, "platform", "win32")
    assert gb.launch_option(game) == "", "nothing to set on Windows"
