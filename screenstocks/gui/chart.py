"""Lightweight time-series line chart on a tkinter Canvas (no matplotlib needed)."""

import bisect
import math
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Sequence

from ..i18n import t as tr
from . import fmt


@dataclass
class Series:
    label: str
    color: str
    points: Sequence[tuple]  # (time_ms, value, low, high)
    width: int = 2


@dataclass
class Marker:
    t: int
    v: float
    color: str
    up: bool
    text: str = ""
    letter: str = ""  # set -> drawn as a labelled circle (trades) instead of a triangle


@dataclass
class HLine:
    v: float
    color: str
    label: str
    fit: bool = False  # include in y-scaling


TIME_STEPS_S = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200,
                10800, 21600, 43200, 86400, 172800, 604800]


def nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    f = raw / 10 ** exp
    nf = 1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10
    return nf * 10 ** exp


def split_gaps(points: Sequence[tuple]) -> list[Sequence[tuple]]:
    """Split a series where data is missing (e.g. app was not running) so no line bridges the gap."""
    if len(points) < 3:
        return [points]
    dts = sorted(b[0] - a[0] for a, b in zip(points, points[1:]))
    limit = max(5000, dts[len(dts) // 2] * 10)
    segments, start = [], 0
    for i in range(1, len(points)):
        if points[i][0] - points[i - 1][0] > limit:
            segments.append(points[start:i])
            start = i
    segments.append(points[start:])
    return segments


def blend(c1: str, c2: str, a: float) -> str:
    """Mix colour c1 into c2 with weight a (Canvas has no alpha)."""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (round(r1 * a + r2 * (1 - a)), round(g1 * a + g2 * (1 - a)),
                              round(b1 * a + b2 * (1 - a)))


class LineChart(tk.Canvas):
    PAD_L, PAD_R, PAD_T, PAD_B = 78, 14, 14, 26

    def __init__(self, master, theme: dict, y_fmt: Callable[[float], str] = None, **kw):
        super().__init__(master, bg=theme["chart_bg"], highlightthickness=0, **kw)
        self.theme = theme
        self.y_fmt = y_fmt or (lambda v: f"{v:,.2f}")
        self.series: list[Series] = []
        self.markers: list[Marker] = []
        self.hlines: list[HLine] = []
        self.x_range: Optional[tuple[int, int]] = None
        self.empty_text = ""
        self._times: list[list[int]] = []
        self._geom = None
        self._marker_pos: list[tuple[float, float, str]] = []
        self._mouse: Optional[tuple[int, int]] = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    def set_data(self, series: list[Series], markers: Sequence[Marker] = (),
                 hlines: Sequence[HLine] = (), x_range: Optional[tuple[int, int]] = None,
                 empty_text: str = "", y_fmt: Callable[[float], str] = None) -> None:
        self.series = [s for s in series if s.points]
        self.markers = list(markers)
        self.hlines = list(hlines)
        self.x_range = x_range
        self.empty_text = empty_text
        if y_fmt:
            self.y_fmt = y_fmt
        self._times = [[p[0] for p in s.points] for s in self.series]
        self.redraw()
        if self._mouse:
            self._draw_hover(*self._mouse)

    # ---------------------------------------------------------------- drawing

    def redraw(self) -> None:
        self.delete("all")
        th = self.theme
        w, h = self.winfo_width(), self.winfo_height()
        if w < 120 or h < 80:
            return
        pts = [p for s in self.series for p in s.points]
        if not pts:
            self._geom = None
            self.create_text(w / 2, h / 2, text=self.empty_text or tr("common.no_data"), fill=th["muted"],
                             font=th["font"])
            return

        if self.x_range:
            t0, t1 = self.x_range
        else:
            t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
        if t1 <= t0:
            t1 = t0 + 1000
        lo = min(p[2] for p in pts)
        hi = max(p[3] for p in pts)
        for hl in self.hlines:
            if hl.fit:
                lo, hi = min(lo, hl.v), max(hi, hl.v)
        pad = (hi - lo) * 0.06 if hi - lo > 1e-12 else (abs(hi) * 0.01 or 1.0)
        lo, hi = lo - pad, hi + pad

        x0, x1 = self.PAD_L, w - self.PAD_R
        y0, y1 = self.PAD_T, h - self.PAD_B
        X = lambda t: x0 + (t - t0) / (t1 - t0) * (x1 - x0)  # noqa: E731
        Y = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
        self._geom = (t0, t1, lo, hi, x0, x1, y0, y1)

        # y grid
        step = nice_step((hi - lo) / max(2, (y1 - y0) / 45))
        v = math.ceil(lo / step) * step
        while v <= hi:
            y = Y(v)
            self.create_line(x0, y, x1, y, fill=th["grid"])
            self.create_text(x0 - 6, y, text=self.y_fmt(v), anchor="e", fill=th["muted"], font=th["font_small"])
            v += step

        # x grid
        span_s = (t1 - t0) / 1000
        target = max(2, (x1 - x0) / 95)
        step_s = next((s for s in TIME_STEPS_S if span_s / s <= target), TIME_STEPS_S[-1])
        tz_offset = datetime.fromtimestamp(t0 / 1000).astimezone().utcoffset().total_seconds()
        tf = "%H:%M:%S" if step_s < 60 else "%H:%M" if span_s < 2 * 86400 else fmt.axis_date_format()
        t = (math.ceil((t0 / 1000 + tz_offset) / step_s) * step_s - tz_offset) * 1000
        while t <= t1:
            x = X(t)
            self.create_line(x, y0, x, y1, fill=th["grid"])
            self.create_text(x, y1 + 5, text=datetime.fromtimestamp(t / 1000).strftime(tf),
                             anchor="n", fill=th["muted"], font=th["font_small"])
            t += step_s * 1000

        self.create_rectangle(x0, y0, x1, y1, outline=th["grid_strong"])

        # horizontal reference lines
        for hl in self.hlines:
            if lo <= hl.v <= hi:
                y = Y(hl.v)
                self.create_line(x0, y, x1, y, fill=hl.color, dash=(5, 3))
                self.create_text(x1 - 4, y - 2, text=f"{hl.label} {self.y_fmt(hl.v)}".strip(), anchor="se",
                                 fill=hl.color, font=th["font_small"])

        # series: min/max band when downsampled, then the line
        for s in self.series:
            for p in split_gaps(s.points):
                if len(p) > 1 and any(q[2] != q[3] for q in p):
                    poly = [c for q in p for c in (X(q[0]), Y(q[3]))]
                    poly += [c for q in reversed(p) for c in (X(q[0]), Y(q[2]))]
                    self.create_polygon(poly, fill=blend(s.color, th["chart_bg"], 0.22), outline="")
                if len(p) == 1:
                    x, y = X(p[0][0]), Y(p[0][1])
                    self.create_oval(x - 2, y - 2, x + 2, y + 2, fill=s.color, outline="")
                else:
                    self.create_line([c for q in p for c in (X(q[0]), Y(q[1]))], fill=s.color, width=s.width)

        # last-value tag on the y axis for single-series charts
        if len(self.series) == 1:
            s = self.series[0]
            y = Y(s.points[-1][1])
            txt = self.y_fmt(s.points[-1][1])
            item = self.create_text(x0 - 6, y, text=txt, anchor="e", fill=th["chart_bg"], font=th["font_small_bold"])
            bx = self.bbox(item)
            rect = self.create_rectangle(bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1, fill=s.color, outline="")
            self.tag_lower(rect, item)

        # markers: news as triangles, trades as labelled circles on top
        self._marker_pos = []
        for m in sorted(self.markers, key=lambda m: bool(m.letter)):
            if not (t0 <= m.t <= t1 and lo <= m.v <= hi):
                continue
            x, y = X(m.t), Y(m.v)
            if m.text:
                self._marker_pos.append((x, y, m.text))
            if m.letter:
                # stack trades that land on the same spot (e.g. cover + buy in one update)
                while any(abs(px - x) < 12 and abs(py - y) < 12 for px, py, _ in self._marker_pos[:-1]):
                    y -= 18
                if m.text:
                    self._marker_pos[-1] = (x, y, m.text)
                self.create_oval(x - 8, y - 8, x + 8, y + 8, fill=m.color, outline=th["fg"], width=1.5)
                self.create_text(x, y, text=m.letter, fill="#0d1117", font=th["font_small_bold"])
            elif m.up:
                self.create_polygon(x, y - 12, x - 6, y - 3, x + 6, y - 3, fill=m.color, outline="")
            else:
                self.create_polygon(x, y + 12, x - 6, y + 3, x + 6, y + 3, fill=m.color, outline="")

        # legend for multi-series charts
        if len(self.series) > 1:
            lx = x0 + 8
            for s in self.series:
                self.create_rectangle(lx, y0 + 8, lx + 10, y0 + 18, fill=s.color, outline="")
                item = self.create_text(lx + 14, y0 + 13, text=s.label, anchor="w", fill=th["fg"], font=th["font_small"])
                lx = self.bbox(item)[2] + 12

    # ------------------------------------------------------------------ hover

    def _on_leave(self, _e=None) -> None:
        self._mouse = None
        self.delete("hover")

    def _on_motion(self, e) -> None:
        self._mouse = (e.x, e.y)
        self._draw_hover(e.x, e.y)

    def _draw_hover(self, mx: int, my: int) -> None:
        self.delete("hover")
        if not self._geom:
            return
        t0, t1, lo, hi, x0, x1, y0, y1 = self._geom
        if not (x0 <= mx <= x1 and y0 <= my <= y1):
            return
        th = self.theme
        X = lambda t: x0 + (t - t0) / (t1 - t0) * (x1 - x0)  # noqa: E731
        Y = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
        t = t0 + (mx - x0) / (x1 - x0) * (t1 - t0)

        lines, t_shown = [], None
        for s, times in zip(self.series, self._times):
            i = bisect.bisect_left(times, t)
            cand = [j for j in (i - 1, i) if 0 <= j < len(times)]
            if not cand:
                continue
            j = min(cand, key=lambda k: abs(times[k] - t))
            pt = s.points[j]
            t_shown = t_shown or pt[0]
            x, y = X(pt[0]), Y(pt[1])
            self.create_oval(x - 4, y - 4, x + 4, y + 4, outline=s.color, width=2, tags="hover")
            line = f"{s.label}: {self.y_fmt(pt[1])}"
            if pt[2] != pt[3]:
                line += f"  ({self.y_fmt(pt[2])} – {self.y_fmt(pt[3])})"
            lines.append(line)
        lines += [txt for x, y, txt in self._marker_pos if abs(x - mx) <= 9 and abs(y - my) <= 9]
        if not lines:
            return
        self.create_line(mx, y0, mx, y1, fill=th["muted"], dash=(2, 3), tags="hover")
        header = fmt.clock(t_shown, with_date=True)
        text = "\n".join([header] + lines)
        item = self.create_text(0, 0, text=text, anchor="nw", fill=th["fg"], font=th["font_small"], tags="hover")
        bx = self.bbox(item)
        tw, tht = bx[2] - bx[0], bx[3] - bx[1]
        tx = mx + 14 if mx + 14 + tw + 8 < x1 else mx - 14 - tw
        ty = min(max(my - tht / 2, y0 + 4), y1 - tht - 4)
        self.coords(item, tx, ty)
        rect = self.create_rectangle(tx - 6, ty - 4, tx + tw + 6, ty + tht + 4,
                                     fill=th["panel"], outline=th["grid_strong"], tags="hover")
        self.tag_lower(rect, item)
