"""Optional upgrade extension: the Screen Stocks Bridge (third-party BepInEx plugin, github.com/fuubox).

The game's own mod interface (export + command files) knows nothing about upgrades. The bridge runs
inside the game and answers on 127.0.0.1 with a token: upgrade catalog, levels, prices and purchases
through the game's normal purchase method (the server stays in charge online).

Only on request, this module installs pinned releases of BepInEx and the bridge into the game folder
(checksums checked before anything is unpacked), removes them again, and talks to the bridge.

Two game builds: the Windows one (on Windows, and on Linux under Steam Proton / Wine, where the BepInEx
loader winhttp.dll needs a DLL override in the Steam launch options) and the native macOS one (started
through BepInEx's run_bepinex.sh, also set in the Steam launch options).
"""

import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import __version__

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    url: str
    sha256: str


BEPINEX = Package("BepInEx", "5.4.23.6",
                  "https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.6/BepInEx_win_x64_5.4.23.6.zip",
                  "6c57a714a892efb4e9e1fef63d608a3391f30ec984031c465404e4ee381a0755")
BEPINEX_MAC = Package("BepInEx", "5.4.23.6",
                      "https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.6/BepInEx_macos_universal_5.4.23.6.zip",
                      "2e711e21f6570da964fce4654b1976500dbe043f61778bce0008500078564638")
BRIDGE = Package("Screen Stocks Bridge", "0.14.2",
                 "https://github.com/fuubox/screen-stocks-bridge/releases/download/v0.14.2/ScreenStocksBridge-v0.14.2.zip",
                 "5636f0b61150d045d5c04f5dc4f71a710ba01e288391a89b214d8409751f1ca5")
BRIDGE_PAGE = "https://github.com/fuubox/screen-stocks-bridge"
# Assembly-CSharp.dll of the game builds the pinned bridge release was reviewed against
TESTED_GAME_BUILDS = {"ac975fe30dad297c78b5c9adeccfde5a2fa4b2cbbb763000279326fd6d76c826"}

STEAM_APP_ID = "4356780"
GAME_EXE = "Screen Stocks.exe"
DEFAULT_PORT = 48721
# files BepInEx puts next to the game executable / app bundle (besides the BepInEx folder)
BEPINEX_ROOT_FILES = (".doorstop_version", "changelog.txt", "doorstop_config.ini", "winhttp.dll")
BEPINEX_MAC_ROOT_FILES = (".doorstop_version", "changelog.txt", "libdoorstop.dylib", "run_bepinex.sh")
MAC_START_SCRIPT = "run_bepinex.sh"
WINE_OVERRIDE = 'WINEDLLOVERRIDES="winhttp=n,b" %command%'
PLUGIN_DIR = Path("BepInEx") / "plugins" / "ScreenStocksBridge"
CONFIG_FILE = Path("BepInEx") / "config" / "screenstocks.bridge.cfg"
MARKER_FILE = PLUGIN_DIR / "installed-by-screenstocks-trading-bot.json"


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str = "", retry_after_ms: int = 0):
        super().__init__(message or code)
        self.code = code
        self.retry_after_ms = retry_after_ms


def big_number(value) -> Optional[float]:
    """A game amount: a decimal string, a number, or the game's "{m=1.16,e=12}" (mantissa, exponent) form."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    m = re.fullmatch(r"\{\s*m\s*=\s*([-+\d.eE]+)\s*,\s*e\s*=\s*([-+\d]+)\s*\}", text)
    try:
        return float(m.group(1)) * 10 ** int(m.group(2)) if m else float(text)
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------- game folder

def mac_app(path: Path) -> Optional[Path]:
    """The app bundle of the native macOS build in the game folder."""
    try:
        return next((app for app in sorted(path.glob("*.app")) if (app / "Contents" / "Resources" / "Data").is_dir()),
                    None)
    except OSError:
        return None


def game_build(path: Path) -> str:
    """"windows" (also under Proton / Wine), "macos" (native app bundle) or "" (no game in this folder)."""
    if (path / GAME_EXE).is_file() and (path / "Screen Stocks_Data").is_dir():
        return "windows"
    return "macos" if mac_app(path) else ""


def is_game_dir(path: Path) -> bool:
    return bool(game_build(path))


def game_dir_of(path: Path) -> Path:
    """A folder chosen by hand: the app bundle itself (macOS) stands for the folder around it."""
    return path.parent if path.suffix == ".app" else path


def managed_dir(game_dir: Path) -> Optional[Path]:
    """The game's .NET assemblies; missing in an IL2CPP build, which BepInEx 5 cannot load."""
    app = mac_app(game_dir) if game_build(game_dir) == "macos" else None
    managed = (app / "Contents" / "Resources" / "Data" / "Managed" if app
               else game_dir / "Screen Stocks_Data" / "Managed")
    return managed if managed.is_dir() else None


def steam_roots() -> list[Path]:
    """Steam's own folder(s) on this OS (with userdata and the first library)."""
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Steam"]
    if sys.platform != "win32":
        from .config import steam_libraries as linux_steam_folders
        return linux_steam_folders()             # native, Flatpak and Snap Steam plus their libraries
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except OSError:
        pass
    roots.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
    return roots


def steam_libraries() -> list[Path]:
    """Steam library folders (Steam folder first, then libraryfolders.vdf entries)."""
    roots = steam_roots()
    libs: list[Path] = []
    for root in roots:
        libs.append(root)
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        libs += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    unique: list[Path] = []
    for lib in libs:
        if not any(os.path.normcase(str(lib)) == os.path.normcase(str(u)) for u in unique):
            unique.append(lib)
    return unique


def find_game_dir() -> Optional[Path]:
    for lib in steam_libraries():
        apps = lib / "steamapps"
        try:
            text = (apps / f"appmanifest_{STEAM_APP_ID}.acf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'"installdir"\s+"([^"]+)"', text)
        if m and is_game_dir(apps / "common" / m.group(1)):
            return (apps / "common" / m.group(1)).resolve()      # Steam's registry path is lower case
    return None


_fingerprints: dict = {}


def game_fingerprint(game_dir: Path) -> str:
    """SHA-256 of the game's Assembly-CSharp.dll (changes with every game update), "" if unreadable."""
    managed = managed_dir(game_dir)
    if managed is None:
        return ""
    dll = managed / "Assembly-CSharp.dll"
    try:
        st = dll.stat()
        key = (str(dll), st.st_mtime_ns, st.st_size)
        if key not in _fingerprints:
            _fingerprints[key] = hashlib.sha256(dll.read_bytes()).hexdigest()
        return _fingerprints[key]
    except OSError:
        return ""


def game_running() -> bool:
    """The game locks the BepInEx and plugin DLLs while it runs: install and remove only with it closed."""
    if sys.platform != "win32":
        # the Windows build under Proton / Wine, or the executable inside the macOS app bundle
        try:
            return subprocess.run(["pgrep", "-f", r"Screen Stocks(\.exe|\.app/Contents/MacOS)"],
                                  capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE}", "/NH", "/FO", "CSV"],
                             capture_output=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    # bytes: the "no tasks" message of a German Windows has an OEM-code-page "ü" that text=True cannot decode
    return f'"{GAME_EXE.lower()}"' in (out or b"").decode("ascii", "replace").lower()


def _writable(path: Path) -> bool:
    probe = path / f".screenstocks-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------- Steam launch options

def launch_option(game_dir: Path) -> str:
    """What the game's Steam launch options must hold for BepInEx to load ("" = nothing needed)."""
    build = game_build(game_dir)
    if build == "macos":
        return f'"{game_dir / MAC_START_SCRIPT}" %command%'
    if build == "windows" and sys.platform != "win32":
        return WINE_OVERRIDE             # Wine uses its own winhttp.dll unless told to prefer the game's
    return ""


def _vdf(text: str) -> dict:
    """Steam's KeyValues text format -> nested dicts with lower-case keys."""
    stack: list[dict] = [{}]
    key = None
    for quoted, brace in re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text):
        if brace == "{":
            child: dict = {}
            stack[-1][(key or "").lower()] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted
        else:
            stack[-1][key.lower()] = re.sub(r"\\(.)", r"\1", quoted)
            key = None
    return stack[0]


def _app_launch_options(tree: dict) -> Optional[str]:
    apps = tree.get("apps")
    if isinstance(apps, dict) and isinstance(apps.get(STEAM_APP_ID), dict):
        return apps[STEAM_APP_ID].get("launchoptions", "")
    for child in tree.values():
        if isinstance(child, dict):
            found = _app_launch_options(child)
            if found is not None:
                return found
    return None


def steam_launch_options() -> list[str]:
    """The game's launch options of every Steam user on this computer (only read, never changed)."""
    found = []
    for root in steam_roots():
        for cfg in sorted(root.glob("userdata/*/config/localconfig.vdf")):
            try:
                options = _app_launch_options(_vdf(cfg.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
            if options is not None:
                found.append(options)
    return found


def launch_option_set(game_dir: Path) -> Optional[bool]:
    """Whether Steam starts the game with the needed launch option; None = unknown (no Steam user found)."""
    if not launch_option(game_dir):
        return True
    options = steam_launch_options()
    if not options:
        return None
    needed = MAC_START_SCRIPT if game_build(game_dir) == "macos" else "winhttp=n"
    return any(needed in o for o in options)


# ---------------------------------------------------------------------------- state

def _loader_files(build: str) -> tuple:
    return BEPINEX_MAC_ROOT_FILES if build == "macos" else BEPINEX_ROOT_FILES


def status(game_dir: Optional[Path]) -> dict:
    """What is installed in the game folder and whether this game build was tested with the bridge."""
    if game_dir is None or not is_game_dir(game_dir):
        return {"game_dir": str(game_dir) if game_dir else "", "found": False}
    marker: dict = {}
    try:
        marker = json.loads((game_dir / MARKER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    build = game_build(game_dir)
    loader = "libdoorstop.dylib" if build == "macos" else "winhttp.dll"
    plugin = (game_dir / PLUGIN_DIR / "ScreenStocksBridge.dll").is_file()
    return {
        "game_dir": str(game_dir), "found": True, "build": build,
        "bepinex": (game_dir / loader).is_file() and (game_dir / "BepInEx" / "core" / "BepInEx.dll").is_file(),
        "plugin": plugin,
        "ours": bool(marker),                       # installed by this app (it may remove it again)
        "plugin_version": marker.get("bridge", ""),
        "tested": game_fingerprint(game_dir) in TESTED_GAME_BUILDS,
        "launch_option": launch_option(game_dir),   # to be set in Steam by the user (macOS, Proton)
        "launch_set": launch_option_set(game_dir) if plugin else None,
    }


# ---------------------------------------------------------------------------- install / remove

def download(pkg: Package, timeout: float = 60) -> bytes:
    req = urllib.request.Request(pkg.url, headers={"User-Agent": f"ScreenStocksTradingBot/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    verify(pkg, data)
    return data


def verify(pkg: Package, data: bytes) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != pkg.sha256:
        raise BridgeError("checksum", f"{pkg.name} {pkg.version}: checksum mismatch ({digest[:12]}…)")


def _extract(data: bytes, game_dir: Path, allowed: tuple) -> list[str]:
    """Unpack a verified zip into the game folder; every entry must stay below one of the allowed paths."""
    written = []
    root = game_dir.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name.startswith(allowed) or ".." in name.split("/"):
                raise BridgeError("archive", f"unexpected file in archive: {name}")
            target = (root / name).resolve()
            if root not in target.parents:
                raise BridgeError("archive", f"unexpected file in archive: {name}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(name)
    return written


def write_config(game_dir: Path) -> None:
    """Bridge settings before its first start: our own token, and no automatic level claims or closing of
    the welcome-back screen (the bridge's defaults) - the extension should only do what the user starts."""
    path = game_dir / CONFIG_FILE
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Bridge]\n\n"
        f"Port = {DEFAULT_PORT}\n"
        f"Token = {secrets.token_urlsafe(32)}\n\n"
        "[QualityOfLife]\n\n"
        "AutoClaimLevelRewards = false\n"
        "AutoCloseOfflineSummary = false\n", encoding="utf-8")


def install(game_dir: Path) -> dict:
    """Download, verify and unpack BepInEx (unless already there) and the bridge. Returns status()."""
    if not is_game_dir(game_dir):
        raise BridgeError("no_game", str(game_dir))
    if managed_dir(game_dir) is None:
        raise BridgeError("il2cpp", str(game_dir))
    if game_running():
        raise BridgeError("game_running")
    if not _writable(game_dir):
        raise BridgeError("read_only", str(game_dir))
    before = status(game_dir)
    with_bepinex = not before["bepinex"]
    build = before["build"]
    bepinex = BEPINEX_MAC if build == "macos" else BEPINEX
    # download and check everything first: nothing is written when a download fails
    bepinex_zip = download(bepinex) if with_bepinex else None
    bridge_zip = download(BRIDGE)
    if bepinex_zip is not None:
        _extract(bepinex_zip, game_dir, _loader_files(build) + ("BepInEx/",))
        if build == "macos":
            (game_dir / MAC_START_SCRIPT).chmod(0o755)          # unpacked files lose their execute bit
    _extract(bridge_zip, game_dir, ("BepInEx/plugins/",))
    write_config(game_dir)
    (game_dir / MARKER_FILE).write_text(json.dumps({
        "bridge": BRIDGE.version, "bepinex": bepinex.version if with_bepinex else "",
        "build": build, "app": __version__}, indent=1), encoding="utf-8")
    log.info("upgrade extension installed in %s (%s build, BepInEx %s, bridge %s)", game_dir, build,
             bepinex.version if with_bepinex else "already there", BRIDGE.version)
    return status(game_dir)


def remove(game_dir: Path) -> dict:
    """Remove the bridge, and BepInEx too when this app installed it (other BepInEx mods keep working)."""
    try:
        marker = json.loads((game_dir / MARKER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BridgeError("not_ours", str(game_dir)) from None
    if game_running():
        raise BridgeError("game_running")
    if marker.get("bepinex"):
        for name in _loader_files(marker.get("build") or game_build(game_dir)):
            (game_dir / name).unlink(missing_ok=True)
        shutil.rmtree(game_dir / "BepInEx")
    else:
        shutil.rmtree(game_dir / PLUGIN_DIR)
        (game_dir / CONFIG_FILE).unlink(missing_ok=True)
    log.info("upgrade extension removed from %s", game_dir)
    return status(game_dir)


# ---------------------------------------------------------------------------- talking to the bridge

def read_config(game_dir: Path) -> tuple[int, str]:
    """(port, token) from the bridge's config file."""
    port, token, section = DEFAULT_PORT, "", ""
    try:
        lines = (game_dir / CONFIG_FILE).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return port, token
    for line in lines:
        line = line.strip()
        if line.startswith("["):
            section = line.strip("[]")
        elif section == "Bridge" and "=" in line and not line.startswith("#"):
            key, value = (s.strip() for s in line.split("=", 1))
            if key == "Port" and value.isdigit():
                port = int(value)
            elif key == "Token":
                token = value
    return port, token


class Client:
    """One connection to the bridge (JSON lines over 127.0.0.1); calls are serialised, reconnects on demand."""

    MAX_FRAME = 128 * 1024

    def __init__(self, game_dir: Path, timeout: float = 5.0):
        self.game_dir = game_dir
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buf = b""
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._drop()

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock, self._buf = None, b""

    def request(self, method: str, params: Optional[dict] = None) -> dict:
        with self._lock:
            port, token = read_config(self.game_dir)
            if not token:
                raise BridgeError("no_token")
            if self._sock is None:
                try:
                    self._sock = socket.create_connection(("127.0.0.1", port), timeout=self.timeout)
                except OSError as exc:
                    raise BridgeError("offline", str(exc)) from None
            rid = uuid.uuid4().hex
            frame = json.dumps({"id": rid, "method": method, "token": token, "params": params or {}},
                               separators=(",", ":")) + "\n"
            try:
                self._sock.sendall(frame.encode("utf-8"))
                while True:
                    msg = self._read_line()
                    if msg.get("id") == rid:
                        break                   # events and stale answers are skipped
            except (OSError, ValueError) as exc:
                self._drop()
                raise BridgeError("offline", str(exc)) from None
        if not msg.get("ok"):
            err = msg.get("error") or {}
            retry = err.get("retryAfterMs")
            raise BridgeError(str(err.get("code", "error")), str(err.get("message", "")),
                              retry if isinstance(retry, int) and retry > 0 else 0)
        result = msg.get("result")
        return result if isinstance(result, dict) else {}

    def _read_line(self) -> dict:
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise OSError("the bridge closed the connection")
            self._buf += chunk
            if len(self._buf) > self.MAX_FRAME and b"\n" not in self._buf:
                raise ValueError("frame too large")
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def upgrades(self) -> list[dict]:
        return self.request("upgrades.snapshot").get("upgrades", [])

    def purchase(self, upgrade_id: str, quantity: int = 1) -> dict:
        return self.request("upgrades.purchase", {"upgradeId": upgrade_id, "quantity": int(quantity)})

    def leaderboard(self, mode: str) -> dict:
        """One of LEADERBOARD_MODES; the game allows one request per 30 s (BridgeError "rate_limited")."""
        params = {"mode": mode}
        if mode in ("current", "all_time", "ipo"):
            params["radius"] = 25
        elif mode == "current_top":
            params["count"] = 100
        return self.request("leaderboard.snapshot", params)


# player lists around you (current / all-time / IPO), the top 100, and the two clan lists
LEADERBOARD_MODES = ("current", "all_time", "ipo", "current_top", "clan_net_worth", "clan_player_share")


def supported() -> bool:
    return sys.platform in ("win32", "darwin") or sys.platform.startswith("linux")
