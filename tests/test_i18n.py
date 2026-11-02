"""Translation catalogue consistency (screenstocks/i18n)."""

import re
import types

import pytest

from screenstocks import i18n

PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.fixture(autouse=True)
def restore_language():
    """Keep the module-level language from leaking into other tests."""
    yield
    i18n.set_language("en")


def test_every_language_has_the_same_keys():
    english = set(i18n.en.STRINGS)
    for code in i18n.LANGUAGES:
        strings = i18n._STRINGS[code]
        assert set(strings) == english, f"{code} differs from en: {set(strings) ^ english}"
        assert all(isinstance(text, str) and text.strip() for text in strings.values())


def test_placeholders_match_english():
    """A missing placeholder raises KeyError at runtime; an extra one is shown literally."""
    for code in i18n.LANGUAGES:
        if code == "en":
            continue
        for key, english in i18n.en.STRINGS.items():
            expected = sorted(PLACEHOLDER.findall(english))
            actual = sorted(PLACEHOLDER.findall(i18n._STRINGS[code][key]))
            assert actual == expected, f"{code}/{key}: {actual} != {expected}"


def test_chinese_is_registered_and_formats():
    assert i18n.LANGUAGES["zh"] == "简体中文"
    i18n.set_language("zh")
    assert i18n.t("tab.market").strip() == "行情"
    assert i18n.t("trade.result", action="买入", p=50, stock="$BASE", status="完成") == "买入 50% $BASE：完成"
    assert i18n.texts("zh")["settings.title"] == "设置"
    assert i18n.texts("zh")["app.title"] == "Screen Stocks – 行情数据与历史记录"


@pytest.mark.parametrize("langid, expected", [
    (0x0804, "zh"),   # Chinese (PRC)
    (0x1004, "zh"),   # Chinese (Singapore)
    (0x0404, "en"),   # Chinese (Taiwan) - not Simplified
    (0x0407, "de"),
    (0x040C, "fr"),
    (0x0409, "en"),
])
def test_system_language_from_windows_langid(monkeypatch, langid, expected):
    kernel32 = types.SimpleNamespace(GetUserDefaultUILanguage=lambda: langid)
    monkeypatch.setattr(i18n, "ctypes", types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=kernel32)))
    assert i18n.system_language() == expected


@pytest.mark.parametrize("locale_name, expected", [
    ("zh_CN", "zh"),
    ("zh-Hans-CN", "zh"),
    ("zh_TW", "en"),
    ("de_DE", "de"),
    ("fr_FR", "fr"),
])
def test_system_language_from_locale(monkeypatch, locale_name, expected):
    monkeypatch.setattr(i18n, "ctypes", types.SimpleNamespace())  # no windll
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *args: (locale_name, "UTF-8"))
    assert i18n.system_language() == expected
