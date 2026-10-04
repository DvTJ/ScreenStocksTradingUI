"""Web user interface (pywebview + Edge WebView2).

The classic Tkinter interface (screenstocks.gui) stays available: it can be
chosen in the settings and starts automatically when WebView2 is missing.
"""

import os
import winreg
from pathlib import Path

WEBVIEW2_CLIENT = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_DOWNLOAD = "https://developer.microsoft.com/microsoft-edge/webview2/"


def webview2_version() -> str:
    """Installed Edge WebView2 runtime version, or "" if it is missing."""
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


def webview_available() -> tuple[bool, str]:
    """(usable, reason) - the web UI needs pywebview and the WebView2 runtime."""
    try:
        import importlib
        importlib.import_module("webview")
    except Exception as exc:  # missing package or .NET bridge failure
        return False, f"pywebview: {exc}"
    if not webview2_version():
        return False, "WebView2 runtime not installed"
    return True, ""
