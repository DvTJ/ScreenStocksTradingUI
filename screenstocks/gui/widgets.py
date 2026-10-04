"""Small widgets shared by the dashboard tabs."""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..i18n import t

RANGES = [("1m", 60), ("5m", 300), ("15m", 900), ("1h", 3600),
          ("6h", 21600), ("24h", 86400), ("common.all", None)]


# --------------------------------------------------------------------- widgets

class RangeBar(ttk.Frame):
    def __init__(self, master, on_change: Callable[[], None], default: str = "15m"):
        super().__init__(master, style="Panel.TFrame")
        self.var = tk.StringVar(value=default)
        ttk.Label(self, text=t("common.range"), style="Panel.TLabel").pack(side="left", padx=(0, 6))
        for label, _ in RANGES:
            ttk.Radiobutton(self, text=t(label), value=label, variable=self.var, command=on_change,
                            style="Range.Toolbutton").pack(side="left", padx=1)

    @property
    def label(self) -> str:
        return t(self.var.get())

    @property
    def seconds(self) -> Optional[int]:
        return dict(RANGES)[self.var.get()]


class SortableTree(ttk.Treeview):
    """Treeview whose rows are re-sorted on every update by the clicked column.

    Column titles are i18n keys; anything that is not a key ("Δ 1m", "%") is shown as is.
    """

    def __init__(self, master, columns: list[tuple], **kw):
        super().__init__(master, columns=[c[0] for c in columns], show="headings", **kw)
        self.sort_col: Optional[str] = None
        self.sort_desc = False
        self._sort_values: dict[str, dict] = {}
        for key, title, width, anchor in columns:
            self.heading(key, text=t(title), command=lambda k=key: self._toggle_sort(k))
            self.column(key, width=width, anchor=anchor, stretch=anchor == "w")

    def _toggle_sort(self, key: str) -> None:
        if self.sort_col == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = key, key not in ("ticker", "name", "stock")
        self._apply_sort()

    def set_rows(self, rows: list[tuple[str, tuple, dict, tuple]]) -> None:
        """rows: (iid, display_values, sort_values, tags)."""
        wanted = {r[0] for r in rows}
        for iid in self.get_children():
            if iid not in wanted:
                self.delete(iid)
        for iid, values, sort_values, tags in rows:
            if self.exists(iid):
                self.item(iid, values=values, tags=tags)
            else:
                self.insert("", "end", iid=iid, values=values, tags=tags)
            self._sort_values[iid] = sort_values
        self._apply_sort()

    def _apply_sort(self) -> None:
        if not self.sort_col:
            return
        def key(iid):
            v = self._sort_values.get(iid, {}).get(self.sort_col)
            return (v is None, v if v is not None else 0)
        items = sorted(self.get_children(), key=key, reverse=self.sort_desc)
        if self.sort_desc:  # keep empty values at the bottom
            items = [i for i in items if key(i)[0] is False] + [i for i in items if key(i)[0]]
        for idx, iid in enumerate(items):
            self.move(iid, "", idx)


def scrolled(master, widget_factory):
    frame = ttk.Frame(master, style="Panel.TFrame")
    widget = widget_factory(frame)
    sb = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
    widget.configure(yscrollcommand=sb.set)
    widget.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame, widget
