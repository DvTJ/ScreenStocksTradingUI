"""Minimal translation layer (German / English / French).

    from screenstocks.i18n import t
    t("market.title")                 -> "Markt" / "Market" / "Marché"
    t("trade.sent", action="Buy", ...) -> formatted string

Strings live in one module per language (de.py, en.py, fr.py). Adding a
language = add a file and a LANGUAGES entry; missing keys fall back to English.

The language is chosen once at startup (set_language) and stays fixed for
the session; switching it in the settings takes effect after a restart.
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
