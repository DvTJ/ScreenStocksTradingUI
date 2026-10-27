import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from screenstocks import config, settings

APP = settings.APP_NAME
PROTON = Path("pfx/drive_c/users/steamuser/AppData/LocalLow")
EXPORT = config.GAME_DIR / "mods" / "export"


@pytest.fixture
def home(monkeypatch):
    # mkdtemp rather than tmp_path: Proton paths are deep and Windows hosts cap paths at 260 chars
    path = Path(tempfile.mkdtemp(prefix="ss"))
    monkeypatch.setattr(Path, "home", lambda: path)
    for var in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def on(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)


def compat(lib, app="4356780"):
    return lib / "steamapps" / "compatdata" / app / PROTON


# --- Windows: identical to the expressions used before macOS/Linux support ---

@pytest.mark.parametrize("env", [True, False])
def test_windows_paths_unchanged(home, monkeypatch, env):
    on(monkeypatch, "win32")
    if env:
        monkeypatch.setenv("APPDATA", str(home / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(home / "Local"))
        monkeypatch.setenv("USERPROFILE", str(home / "profile"))
    (home / APP).mkdir()   # the off-Windows legacy folder must not matter here
    assert settings.user_config_dir() == Path(os.environ.get("APPDATA", Path.home())) / APP
    assert settings.user_data_dir() == Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP
    old = (Path(os.environ.get("USERPROFILE", str(Path.home())))
           / "AppData" / "LocalLow" / "Conradical Games" / "Screen Stocks" / "mods" / "export")
    assert config.default_export_dir() == old
    assert settings.user_config_dir() == (home / "Roaming" if env else home) / APP


@pytest.mark.skipif(sys.platform != "win32", reason="module-level value is computed for the host OS")
def test_windows_module_default_unchanged():
    assert config.DEFAULT_EXPORT_DIR == (
        Path(os.environ.get("USERPROFILE", str(Path.home())))
        / "AppData" / "LocalLow" / "Conradical Games" / "Screen Stocks" / "mods" / "export")


def test_windows_detects_renamed_game_folder(home, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.setattr(config, "DEFAULT_EXPORT_DIR", config.default_export_dir())
    demo = home / "AppData" / "LocalLow" / "Conradical Games" / "Screen Stocks Demo" / "mods" / "export"
    demo.mkdir(parents=True)
    assert settings.detect_export_dir() == demo


# --- macOS ---

def test_macos_paths(home, monkeypatch):
    on(monkeypatch, "darwin")
    support = home / "Library" / "Application Support"
    assert settings.user_config_dir() == support / APP
    assert settings.user_data_dir() == support / APP
    assert config.game_data_roots() == [support]
    assert config.default_export_dir() == support / EXPORT


# --- Linux ---

def test_linux_xdg_unset(home, monkeypatch):
    on(monkeypatch, "linux")
    assert settings.user_config_dir() == home / ".config" / APP
    assert settings.user_data_dir() == home / ".local" / "share" / APP
    assert config.game_data_roots()[-1] == home / ".config" / "unity3d"


def test_linux_xdg_set(home, monkeypatch):
    on(monkeypatch, "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "data"))
    assert settings.user_config_dir() == home / "cfg" / APP
    assert settings.user_data_dir() == home / "data" / APP
    assert config.game_data_roots()[-1] == home / "cfg" / "unity3d"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_legacy_home_folder_kept(home, monkeypatch, platform):
    on(monkeypatch, platform)
    (home / APP).mkdir()
    assert settings.user_config_dir() == home / APP
    assert settings.user_data_dir() == home / APP


def test_linux_proton_default(home, monkeypatch):
    on(monkeypatch, "linux")
    steam = home / ".steam" / "steam"
    flatpak = home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
    roots = config.game_data_roots()
    assert roots[0] == compat(steam)
    assert compat(flatpak) in roots and compat(flatpak, "5124200") in roots
    assert roots.index(compat(flatpak)) < roots.index(compat(steam, "5124200"))   # full game before demo
    assert config.default_export_dir() == compat(steam) / EXPORT


def test_linux_extra_library_from_vdf(home, monkeypatch):
    on(monkeypatch, "linux")
    steam = home / ".local" / "share" / "Steam"
    extra = home / "mnt" / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % (steam.as_posix(), extra.as_posix()), encoding="utf-8")
    (compat(extra) / config.GAME_DIR).mkdir(parents=True)
    libs = config.steam_libraries()
    assert libs.count(steam) == 1 and extra in libs
    assert config.default_export_dir() == compat(extra) / EXPORT


def test_linux_garbled_vdf_ignored(home, monkeypatch):
    on(monkeypatch, "linux")
    apps = home / ".steam" / "steam" / "steamapps"
    apps.mkdir(parents=True)
    (apps / "libraryfolders.vdf").write_bytes(b'\xff\xfe"path" "\x00bad"\x00garbage')
    (home / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf").mkdir(parents=True)
    assert len(config.steam_libraries()) == 4


def test_linux_symlinked_steam_root_deduplicated(home, monkeypatch):
    on(monkeypatch, "linux")
    real = home / ".local" / "share" / "Steam"
    real.mkdir(parents=True)
    (home / ".steam").mkdir()
    try:
        os.symlink(real, home / ".steam" / "steam", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted")
    assert real not in config.steam_libraries()


def test_linux_flatpak_demo_detected(home, monkeypatch):
    on(monkeypatch, "linux")
    monkeypatch.setattr(config, "DEFAULT_EXPORT_DIR", config.default_export_dir())
    flatpak = home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
    export = compat(flatpak, "5124200") / EXPORT
    export.mkdir(parents=True)
    assert config.default_export_dir() == export
    assert settings.detect_export_dir() == export


def test_linux_native_renamed_folder_detected(home, monkeypatch):
    on(monkeypatch, "linux")
    monkeypatch.setattr(config, "DEFAULT_EXPORT_DIR", config.default_export_dir())
    export = home / ".config" / "unity3d" / "Conradical Games" / "Screen Stocks Playtest" / "mods" / "export"
    export.mkdir(parents=True)
    assert settings.detect_export_dir() == export


def test_detect_none_when_game_missing(home, monkeypatch):
    on(monkeypatch, "linux")
    monkeypatch.setattr(config, "DEFAULT_EXPORT_DIR", config.default_export_dir())
    assert settings.detect_export_dir() is None
