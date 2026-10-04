"""Minimal translation layer (German / English / French).

    from screenstocks.i18n import t
    t("market.title")                 -> "Markt" / "Market" / "Marché"
    t("trade.sent", action="Buy", ...) -> formatted string

Strings live in one module per language (de.py, en.py, fr.py). Adding a
language = add a file and a LANGUAGES entry; missing keys fall back to English.

The language is chosen at startup (set_language). The classic interface keeps it
for the session (a change applies after a restart); the web interface switches it
live and reloads its page with texts() of the new language.
"""

import ctypes
import locale
from typing import Optional

from . import de, en, fr

LANGUAGES = {"de": "Deutsch", "en": "English", "fr": "Français"}

_STRINGS = {"de": de.STRINGS, "en": en.STRINGS, "fr": fr.STRINGS}
_lang = "en"


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "en"


def get_language() -> str:
    return _lang


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    text = _STRINGS[_lang].get(key)
    if text is None:
        text = en.STRINGS.get(key, default if default is not None else key)
    return text.format(**kwargs) if kwargs else text


def texts(lang: Optional[str] = None) -> dict:
    """All texts of a language (default: the current one); missing keys come from English. For the web UI."""
    return {**en.STRINGS, **_STRINGS.get(lang or _lang, {})}


def variants(key: str) -> list[str]:
    """The text of a key in every language (to recognise texts stored before they became translatable)."""
    return [strings[key] for strings in _STRINGS.values() if key in strings]


def keys() -> list[str]:
    return list(en.STRINGS)


def system_language() -> str:
    """'de' / 'fr' for a German / French Windows UI, otherwise 'en'."""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return {0x07: "de", 0x0C: "fr"}.get(primary, "en")
    except Exception:
        loc = (locale.getlocale()[0] or "").lower()
        for code, names in (("de", ("de", "german")), ("fr", ("fr", "french"))):
            if loc.startswith(names):
                return code
        return "en"
