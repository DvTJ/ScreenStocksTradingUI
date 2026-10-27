import pytest

from screenstocks import config, settings


@pytest.fixture
def game_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_EXPORT_DIR", tmp_path / "mods" / "export")
    return tmp_path


def test_settings_file_path(game_dir):
    assert settings.game_settings_file() == game_dir / "thesmallshort_online_settings.sav"


@pytest.mark.parametrize("text, expected", [
    ('{\n    "volume" : 0.5,\n    "modSupport" : true,\n}', True),
    ('{"modSupport":FALSE}', False),
    ('{"volume" : 0.5}', None),
])
def test_mod_support_enabled(game_dir, text, expected):
    sav = game_dir / "thesmallshort_online_settings.sav"
    sav.write_text(text, encoding="utf-8")
    assert settings.mod_support_enabled() is expected
    assert sav.read_text(encoding="utf-8") == text


def test_mod_support_missing_file(game_dir):
    assert settings.mod_support_enabled() is None
