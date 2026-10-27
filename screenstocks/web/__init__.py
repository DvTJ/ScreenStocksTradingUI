"""Web user interface (pywebview: Edge WebView2 on Windows, WebKit on macOS, GTK or Qt on Linux).

The classic Tkinter interface (screenstocks.gui) stays available: it can be
chosen in the settings and starts automatically when the web view is missing.
"""

import importlib.util
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# AppArmor profile written by installer/linux/install-apparmor-profile.sh (shipped next to the Linux executable)
APPARMOR_PROFILE = "screenstocks-trading-bot"
WEBVIEW2_CLIENT = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_DOWNLOAD = "https://developer.microsoft.com/microsoft-edge/webview2/"
# Microsoft's official Evergreen bootstrapper (tiny; downloads and installs the runtime)
WEBVIEW2_BOOTSTRAPPER = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def webview2_version() -> str:
    """Installed Edge WebView2 runtime version, or "" if it is missing."""
    import winreg
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + WEBVIEW2_CLIENT[8:]),
                      (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE" + WEBVIEW2_CLIENT[8:]),
                      (winreg.HKEY_CURRENT_USER, WEBVIEW2_CLIENT)):
        try:
            with winreg.OpenKey(hive, key) as k:
                version, _ = winreg.QueryValueEx(k, "pv")
                if version and version != "0.0.0.0":
                    return str(version)
        except OSError:
            continue
    # fallback: runtime folder (e.g. installed together with Edge)
    base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "EdgeWebView" / "Application"
    versions = sorted(p.name for p in base.glob("*.*.*.*") if (p / "msedgewebview2.exe").exists()) if base.is_dir() else []
    return versions[-1] if versions else ""


def install_webview2() -> str:
    """Download Microsoft's WebView2 bootstrapper and run it silently (Windows may ask for permission).
    Returns "" on success, else the error text."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "MicrosoftEdgeWebview2Setup.exe"
            with urllib.request.urlopen(WEBVIEW2_BOOTSTRAPPER, timeout=60) as resp, open(exe, "wb") as fh:
                fh.write(resp.read())
            subprocess.run([str(exe), "/silent", "/install"], timeout=600, check=False)
    except Exception as exc:
        return str(exc)
    return "" if webview2_version() else "installer finished but WebView2 is still not detected"


def unblock_bundled_dlls() -> None:
    """Remove the "downloaded from the internet" mark from the bundled .NET DLLs.

    Unpacking the portable zip with Explorer copies the mark onto every file, and .NET then
    refuses to load them ("Failed to resolve Python.Runtime.Loader.Initialize")."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return
    for sub in ("pythonnet", "clr_loader", "webview"):
        folder = Path(base) / sub
        if folder.is_dir():
            for dll in folder.rglob("*.dll"):
                try:
                    os.remove(f"{dll}:Zone.Identifier")
                except OSError:
                    pass                         # not marked, or no write access


def close_window(window) -> None:
    """Close a pywebview window from code. On macOS pywebview then stops the Cocoa event loop, but AppKit only
    stops after the next event - without a click or key press the app would hang, so post an empty one."""
    window.destroy()
    if sys.platform != "darwin":
        return
    window.events.closed.wait(5)
    import AppKit
    event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        AppKit.NSEventTypeApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0)
    AppKit.NSApp.postEvent_atStart_(event, True)      # may be called from any thread


def apparmor_label(paths=(Path("/proc/self/attr/apparmor/current"), Path("/proc/self/attr/current"))) -> str:
    """Name of the AppArmor profile this process runs under ("unconfined" or "" without one)."""
    for path in paths:
        try:
            return path.read_text().strip("\0\n ").split(" ")[0]
        except OSError:
            continue
    return ""


def qt_sandbox_fix(flag: Path = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns"),
                   label: Optional[str] = None) -> None:
    """Ubuntu 23.10+ blocks the user namespaces Qt WebEngine's sandbox needs (AppArmor); its renderer then dies and
    the window stays blank. Unless install-apparmor-profile.sh allowed them for this app, run it without the
    sandbox - the page is the app's own local files."""
    try:
        restricted = flag.read_text().strip() == "1"
    except OSError:
        return
    if not restricted:
        return
    if (apparmor_label() if label is None else label) == APPARMOR_PROFILE:
        log.info("Qt WebEngine sandbox on (AppArmor profile %s)", APPARMOR_PROFILE)
        return
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    log.warning("AppArmor blocks user namespaces: Qt WebEngine sandbox off "
                "(sudo ./install-apparmor-profile.sh in the app folder keeps it on)")


# Qt WebEngine without OpenGL: Chromium draws in software, Qt Quick too, and Qt does not touch GLX at all
QT_SOFTWARE_RENDERING = {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu", "QT_QUICK_BACKEND": "software",
                         "QT_XCB_GL_INTEGRATION": "none"}


def qt_probe(env: Optional[dict] = None) -> str:
    """"" if Qt WebEngine shows a page in a child process, else why not. A missing system library or a broken
    OpenGL makes Qt abort the whole process, so the web UI could not fall back to the classic one by itself."""
    from ..settings import self_command
    try:
        result = subprocess.run(self_command("--probe-web"), capture_output=True, text=True, timeout=90,
                                env={**os.environ, **(env or {})})
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Qt check failed: {exc}"
    if result.returncode == 0:
        return ""
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    return f"Qt cannot start (exit code {result.returncode})" + (f": {lines[-1]}" if lines else "")


def webview_available() -> tuple[bool, str]:
    """(usable, reason) - the web UI needs pywebview and, on Windows, the WebView2 runtime,
    on Linux a GTK (gi) or Qt (qtpy) backend; a Qt-only setup is test-started in a child process."""
    if sys.platform == "win32":  # the Zone.Identifier mark is an NTFS stream
        unblock_bundled_dlls()
    try:
        importlib.import_module("webview")
    except Exception as exc:  # missing package or .NET bridge failure
        return False, f"pywebview: {exc}"
    if sys.platform == "win32":
        if not webview2_version():
            return False, "WebView2 runtime not installed"
    elif sys.platform != "darwin":
        if not any(importlib.util.find_spec(m) for m in ("gi", "qtpy")):
            return False, "no pywebview backend (GTK WebKit or Qt) installed"
        if importlib.util.find_spec("gi") is None:
            qt_sandbox_fix()                  # before the check: its child process inherits the decision
            reason = qt_probe()
            if reason:
                if qt_probe(QT_SOFTWARE_RENDERING):
                    return False, reason
                os.environ.update(QT_SOFTWARE_RENDERING)
                log.warning("Qt WebEngine cannot use OpenGL (%s) - drawing in software", reason)
    return True, ""
