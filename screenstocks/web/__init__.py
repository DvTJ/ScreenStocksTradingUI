"""Web user interface (pywebview: Edge WebView2 on Windows, WebKit on macOS, GTK or Qt on Linux).

The classic Tkinter interface (screenstocks.gui) stays available: it can be
chosen in the settings and starts automatically when the web view is missing.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

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


def qt_sandbox_fix(flag: Path = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")) -> None:
    """Ubuntu 23.10+ blocks the user namespaces Qt WebEngine's sandbox needs (AppArmor); its renderer then dies and
    the window stays blank. Only then run it without the sandbox - the page is the app's own local files."""
    try:
        restricted = flag.read_text().strip() == "1"
    except OSError:
        return
    if restricted:
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")


def webview_available() -> tuple[bool, str]:
    """(usable, reason) - the web UI needs pywebview and, on Windows, the WebView2 runtime,
    on Linux a GTK (gi) or Qt (qtpy) backend. Cheap checks only, no window is started."""
    if sys.platform == "win32":  # the Zone.Identifier mark is an NTFS stream
        unblock_bundled_dlls()
    try:
        importlib.import_module("webview")
    except Exception as exc:  # missing package or .NET bridge failure
        return False, f"pywebview: {exc}"
    if sys.platform == "win32":
        if not webview2_version():
            return False, "WebView2 runtime not installed"
    elif sys.platform != "darwin" and not any(importlib.util.find_spec(m) for m in ("gi", "qtpy")):
        return False, "no pywebview backend (GTK WebKit or Qt) installed"
    return True, ""
