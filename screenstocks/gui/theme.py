"""Dark theme shared by the dashboard and the setup wizard."""

import tkinter as tk
from tkinter import ttk

from ..settings import resource_path

THEME = {
    "bg": "#1b1c1f",
    "panel": "#26282c",
    "panel_alt": "#2d3035",
    "chart_bg": "#202226",
    "fg": "#e6e6e6",
    "muted": "#959ba3",
    "grid": "#2f3237",
    "grid_strong": "#454950",
    "accent": "#58a6ff",
    "up": "#3fb950",
    "down": "#f85149",
    "warn": "#d29922",
    "select": "#2f4a6b",
    "font": ("Segoe UI", 10),
    "font_bold": ("Segoe UI", 10, "bold"),
    "font_small": ("Segoe UI", 8),
    "font_small_bold": ("Segoe UI", 8, "bold"),
    "font_kpi": ("Segoe UI", 15, "bold"),
}


def set_window_icon(win: tk.Misc) -> None:
    icon = resource_path("assets/icon.ico")
    if icon.exists():
        try:
            win.iconbitmap(default=str(icon))
        except tk.TclError:
            pass


def apply_style(root: tk.Tk) -> None:
    s = ttk.Style(root)
    s.theme_use("clam")
    bg, panel, fg, muted = THEME["bg"], THEME["panel"], THEME["fg"], THEME["muted"]
    alt = THEME["panel_alt"]
    s.configure(".", background=panel, foreground=fg, font=THEME["font"], bordercolor=THEME["grid_strong"],
                lightcolor=panel, darkcolor=panel, troughcolor=bg, fieldbackground=panel)
    s.configure("Panel.TFrame", background=panel)
    s.configure("Header.TFrame", background=bg)
    s.configure("Card.TFrame", background=alt)
    s.configure("Panel.TLabel", background=panel, foreground=muted)
    s.configure("Muted.TLabel", background=panel, foreground=muted)
    s.configure("Title.TLabel", background=panel, foreground=fg, font=("Segoe UI", 13, "bold"))
    s.configure("Heading.TLabel", background=panel, foreground=fg, font=("Segoe UI", 16, "bold"))
    s.configure("Section.TLabel", background=panel, foreground=fg, font=THEME["font_bold"])
    s.configure("Body.TLabel", background=panel, foreground=fg)
    s.configure("Ok.TLabel", background=panel, foreground=THEME["up"])
    s.configure("Warn.TLabel", background=panel, foreground=THEME["warn"])
    s.configure("Bad.TLabel", background=panel, foreground=THEME["down"])
    s.configure("HeaderMuted.TLabel", background=bg, foreground=muted, font=THEME["font_small"])
    s.configure("HeaderValue.TLabel", background=bg, foreground=fg, font=("Segoe UI", 12, "bold"))
    s.configure("HeaderLive.TLabel", background=bg, foreground=THEME["up"], font=("Segoe UI", 12, "bold"))
    s.configure("HeaderWarn.TLabel", background=bg, foreground=THEME["warn"], font=("Segoe UI", 12, "bold"))
    s.configure("CardMuted.TLabel", background=alt, foreground=muted, font=THEME["font_small"])
    s.configure("CardTitle.TLabel", background=alt, foreground=fg, font=("Segoe UI", 12, "bold"))
    s.configure("CardValue.TLabel", background=alt, foreground=fg, font=THEME["font_bold"])
    s.configure("Kpi.TLabel", background=alt, foreground=fg, font=THEME["font_kpi"])
    s.configure("KpiUp.TLabel", background=alt, foreground=THEME["up"], font=THEME["font_kpi"])
    s.configure("KpiDown.TLabel", background=alt, foreground=THEME["down"], font=THEME["font_kpi"])
    s.configure("Status.TLabel", background=bg, foreground=muted, font=THEME["font_small"])
    s.configure("TNotebook", background=bg, borderwidth=0)
    s.configure("TNotebook.Tab", background=bg, foreground=muted, padding=(10, 5), borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", panel)], foreground=[("selected", fg)])
    s.configure("Treeview", background=panel, fieldbackground=panel, foreground=fg, rowheight=24, borderwidth=0)
    s.map("Treeview", background=[("selected", THEME["select"])], foreground=[("selected", fg)])
    s.configure("Treeview.Heading", background=alt, foreground=muted, relief="flat", font=THEME["font_small_bold"])
    s.map("Treeview.Heading", background=[("active", THEME["grid_strong"])])
    s.configure("Range.Toolbutton", background=alt, foreground=muted, padding=(8, 2))
    s.map("Range.Toolbutton", background=[("selected", THEME["accent"]), ("active", THEME["grid_strong"])],
          foreground=[("selected", "#0d1117")])
    s.configure("TButton", background=alt, foreground=fg, padding=(10, 3))
    s.map("TButton", background=[("active", THEME["grid_strong"]), ("disabled", panel)],
          foreground=[("disabled", muted)])
    s.configure("Header.TButton", background=bg, foreground=muted, padding=(8, 2))
    s.map("Header.TButton", background=[("active", alt)], foreground=[("active", fg)])
    s.configure("Accent.TButton", background=THEME["accent"], foreground="#0d1117", font=THEME["font_bold"],
                padding=(14, 4))
    s.map("Accent.TButton", background=[("active", "#79b8ff"), ("disabled", alt)],
          foreground=[("disabled", muted)])
    for w, font in (("TRadiobutton", ("Segoe UI", 11)), ("TCheckbutton", THEME["font"])):
        s.configure(w, background=panel, foreground=fg, font=font, indicatorbackground=alt,
                    indicatorforeground=fg, indicatorrelief="flat", upperbordercolor=THEME["grid_strong"],
                    lowerbordercolor=THEME["grid_strong"])
        s.map(w, background=[("active", panel)],
              indicatorbackground=[("selected", THEME["accent"]), ("active", THEME["grid_strong"])],
              indicatorforeground=[("selected", "#0d1117")])
    s.configure("TPanedwindow", background=panel)
    for w in ("TCombobox", "TEntry"):
        s.configure(w, fieldbackground=panel, background=alt, foreground=fg, insertcolor=fg, arrowcolor=fg,
                    padding=3)
        s.map(w, fieldbackground=[("readonly", panel), ("disabled", alt)],
              foreground=[("disabled", muted), ("readonly", fg)],
              selectbackground=[("readonly", panel)], selectforeground=[("readonly", fg)])
    root.option_add("*TCombobox*Listbox.background", panel)
    root.option_add("*TCombobox*Listbox.foreground", fg)
    root.option_add("*TCombobox*Listbox.selectBackground", THEME["select"])
    root.option_add("*TCombobox*Listbox.selectForeground", fg)
    s.configure("Vertical.TScrollbar", background=alt, arrowcolor=muted)
