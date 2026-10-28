"""Number and time formatting for the GUI, following the UI language."""

from datetime import datetime
from typing import Optional

from ..i18n import get_language


def _de() -> bool:
    """Day-first dates, decimal comma and "12 %" spacing (German and French)."""
    return get_language() in ("de", "fr")


def _localize(s: str) -> str:
    # 1,234,567.89 -> 1.234.567,89 for German, 1 234 567,89 for French
    if not _de():
        return s
    group = " " if get_language() == "fr" else "."
    return s.replace(",", "_").replace(".", ",").replace("_", group)


def decimal_sep() -> str:
    return "," if _de() else "."


def num(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "–"
    return _localize(f"{v:,.{decimals}f}")


def price(v: Optional[float]) -> str:
    if v is None:
        return "–"
    a = abs(v)
    return num(v, 2 if a >= 100 else 3 if a >= 1 else 4)


# From 10^15 on every language uses the American short scale (Qa = quadrillion, Qi = quintillion ...);
# below that German / French keep Tsd. / Mio. / Mrd. / Bio. Keep in step with SS.fmt.big in web/static/js/core.js.
_US = ((1e33, "Dc"), (1e30, "No"), (1e27, "Oc"), (1e24, "Sp"), (1e21, "Sx"), (1e18, "Qi"), (1e15, "Qa"))
BIG_EN = _US + ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e4, "K"))
BIG_DE = tuple((v, " " + s) for v, s in _US) + ((1e12, " Bio."), (1e9, " Mrd."), (1e6, " Mio."), (1e4, " Tsd."))


def big(v: Optional[float]) -> str:
    """Compact money/share amounts: 6,34 Mrd. / 6.34B, up to 10^33 (Dc / Quintd.)"""
    if v is None:
        return "–"
    a = abs(v)
    for limit, suffix in BIG_DE if _de() else BIG_EN:
        if a >= limit:
            return _localize(f"{v / limit:,.2f}") + suffix
    return num(v, 2)


def pct(v: Optional[float], signed: bool = True) -> str:
    if v is None:
        return "–"
    s = _localize(f"{v:+.2f}" if signed else f"{v:.2f}")
    return s + (" %" if _de() else "%")


def pct_int(v: int) -> str:
    return f"{v} %" if _de() else f"{v}%"


def change_pct(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or not old:
        return None
    return (new / old - 1.0) * 100.0


def clock(ms: Optional[int], with_date: bool = False) -> str:
    if not ms:
        return "–"
    dt = datetime.fromtimestamp(ms / 1000)
    if not with_date:
        return dt.strftime("%H:%M:%S")
    return dt.strftime("%d.%m. %H:%M:%S" if _de() else "%m/%d %H:%M:%S")


def axis_date_format() -> str:
    return "%d.%m. %H:%M" if _de() else "%m/%d %H:%M"


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{sign}{h}:{m:02d}:{s:02d}"
    return f"{sign}{m}:{s:02d}"
