import importlib
import importlib.util
import os
import subprocess
import sys
import types

import pytest

from screenstocks import i18n, updater

RELEASE = {
    "tag_name": "v1.4.0",
    "html_url": "https://github.com/x/y/releases/tag/v1.4.0",
    "assets": [
        {"name": "ScreenStocksTradingBot-1.4.0-portable.zip", "browser_download_url": "https://dl/zip", "size": 5},
        {"name": "ScreenStocksTradingBot-Setup-1.4.0.exe", "browser_download_url": "https://dl/exe", "size": 7},
        {"name": "ScreenStocksTradingBot-1.4.0-macos-arm64.dmg", "browser_download_url": "https://dl/dmg", "size": 9},
    ],
}


@pytest.fixture
def web(monkeypatch):
    """screenstocks.web imported freshly as on macOS / Linux: no winreg module."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "winreg", None)       # import winreg -> ImportError
    monkeypatch.delitem(sys.modules, "screenstocks.web", raising=False)
    monkeypatch.setitem(sys.modules, "webview", types.ModuleType("webview"))  # importable, never started
    return importlib.import_module("screenstocks.web")


def _backends(monkeypatch, *present):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: (object() if name in present else None) if name in ("gi", "qtpy")
                        else real(name, *a))


@pytest.mark.parametrize("flag, label, expected", [
    ("1\n", "unconfined", "1"),                      # blocked, no profile: sandbox off
    ("1\n", "", "1"),
    ("1\n", "screenstocks-trading-bot", None),       # install-apparmor-profile.sh allowed it: sandbox stays on
    ("0\n", "unconfined", None),
    (None, "unconfined", None),                      # no such restriction on this kernel
])
def test_qt_sandbox_only_off_when_blocked(web, monkeypatch, tmp_path, flag, label, expected):
    monkeypatch.delenv("QTWEBENGINE_DISABLE_SANDBOX", raising=False)
    path = tmp_path / "apparmor_restrict_unprivileged_userns"
    if flag is not None:
        path.write_text(flag)
    web.qt_sandbox_fix(path, label)
    assert os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") == expected


def test_apparmor_label(web, tmp_path):
    current = tmp_path / "current"
    current.write_text("screenstocks-trading-bot (unconfined)\n")
    assert web.apparmor_label((tmp_path / "missing", current)) == "screenstocks-trading-bot"
    assert web.apparmor_label((tmp_path / "missing",)) == ""


@pytest.mark.parametrize("code, stderr, reason", [
    (0, "", ""),
    (-6, "qt.qpa.plugin: could not load xcb\nThis application failed to start\n",
     "Qt cannot start (exit code -6): This application failed to start"),
])
def test_qt_probe(web, monkeypatch, code, stderr, reason):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, code, "", stderr)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert web.qt_probe() == reason
    assert seen[0][-1] == "--probe-web"


def test_qt_only_linux_setup_is_probed(web, monkeypatch):
    _backends(monkeypatch, "qtpy")
    monkeypatch.setattr(web, "qt_probe", lambda: "Qt cannot start (exit code -6)")
    assert web.webview_available() == (False, "Qt cannot start (exit code -6)")
    _backends(monkeypatch, "gi", "qtpy")                    # GTK is used then: no probe
    assert web.webview_available() == (True, "")


def test_stuck_page_call_does_not_keep_the_app_alive(monkeypatch):
    import logging
    import threading
    import main
    exits = []
    monkeypatch.setattr(main.os, "_exit", exits.append)
    monkeypatch.setattr(main.logging, "shutdown", lambda: None)
    release = threading.Event()
    stuck = threading.Thread(target=release.wait, name="page-call")     # like a pywebview call into a dead loop
    stuck.start()
    try:
        main._leave_stuck_threads(logging.getLogger("test"), 3)
    finally:
        release.set()
        stuck.join()
    assert exits == [3]                                                  # the real exit code, not a hang
    main._leave_stuck_threads(logging.getLogger("test"), 0)              # nothing stuck: normal exit
    assert exits == [3]


def test_self_command(monkeypatch):
    from screenstocks import settings
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert settings.self_command("--x") == [sys.executable, "--x"]
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "argv", ["main.py", "--setup"])
    assert settings.self_command("--x") == [sys.executable, "main.py", "--x"]


def test_tk_fonts_unchanged_on_windows(monkeypatch):
    from screenstocks.gui import theme
    monkeypatch.setattr(sys, "platform", "win32")
    assert theme.font(12, "bold") == ("Segoe UI", 12, "bold")
    assert theme.THEME["font_kpi"] == ("Segoe UI", 15, "bold")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert theme.font(12, "bold") == ("Segoe UI", 16, "bold")   # macOS Tk points are 72 dpi


def test_lock_unreachable_db_folder_does_not_crash(tmp_path):
    from screenstocks import single_instance
    if sys.platform == "win32":
        pytest.skip("the POSIX lock file branch")
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert single_instance.acquire(blocker / "sub" / "screenstocks.db", wait_s=0) is True


def test_web_imports_without_winreg(web):
    assert web.WEBVIEW2_DOWNLOAD.startswith("https://")


def test_webview_linux_needs_backend(web, monkeypatch):
    _backends(monkeypatch)
    ok, reason = web.webview_available()
    assert not ok and "backend" in reason
    _backends(monkeypatch, "qtpy")
    monkeypatch.setattr(web, "qt_probe", lambda: "")          # Qt starts (checked in a child process)
    assert web.webview_available() == (True, "")


def test_webview_macos_needs_only_pywebview(web, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _backends(monkeypatch)
    assert web.webview_available() == (True, "")


def test_webview_windows_needs_webview2(web, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(web, "webview2_version", lambda: "")
    assert web.webview_available() == (False, "WebView2 runtime not installed")
    monkeypatch.setattr(web, "webview2_version", lambda: "130.0.2849.80")
    assert web.webview_available() == (True, "")


def test_installer_only_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    r = updater.parse_release(RELEASE)
    assert (r.version, r.installer_name, r.installer_url, r.installer_size) == \
        ("1.4.0", "ScreenStocksTradingBot-Setup-1.4.0.exe", "https://dl/exe", 7)
    for plat in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", plat)
        r = updater.parse_release(RELEASE)
        assert (r.version, r.page_url) == ("1.4.0", RELEASE["html_url"])
        assert (r.installer_name, r.installer_url, r.installer_size) == (None, None, 0)


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(i18n, "ctypes", types.SimpleNamespace())  # no windll
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a: (None, None))


def test_macos_language_from_apple_languages(mac, monkeypatch):
    out = '(\n    "fr-FR",\n    "en-US"\n)\n'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out))
    assert i18n.system_language() == "fr"


def test_macos_language_fallback(mac, monkeypatch):
    def fail(*a, **k):
        raise subprocess.TimeoutExpired("defaults", 2)
    monkeypatch.setattr(subprocess, "run", fail)
    assert i18n.system_language() == "en"
