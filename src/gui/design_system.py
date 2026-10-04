"""Shared visual language for the Tk and Qt parts of the Elutek desktop UI.

The app uses Tk for setup/settings and Qt for the analysis workspace.  Keeping
colour tokens and control hierarchy here prevents those two interfaces from
slowly becoming separate products.  This module deliberately has no GUI
imports, so colour decisions can be tested in a headless environment.
"""

from __future__ import annotations

from typing import Dict


DARK_PALETTE = {
    "background": "#0B1220",
    "surface": "#111C2E",
    "surface_raised": "#17243A",
    "surface_hover": "#1D2C45",
    "border": "#2A3B59",
    "border_focus": "#60A5FA",
    "text": "#F7FAFF",
    "muted": "#A8B7CE",
    "accent": "#3B82F6",
    "accent_hover": "#2563EB",
    "accent_soft": "#1E3A5F",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "danger_hover": "#DC2626",
    "selection": "#2563EB",
    "chart_grid": "#334155",
}

LIGHT_PALETTE = {
    "background": "#F4F7FB",
    "surface": "#FFFFFF",
    "surface_raised": "#F8FAFC",
    "surface_hover": "#EAF1FA",
    "border": "#D6E0EF",
    "border_focus": "#2563EB",
    "text": "#14213A",
    "muted": "#5F6F86",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "accent_soft": "#DBEAFE",
    "success": "#15803D",
    "warning": "#B45309",
    "danger": "#DC2626",
    "danger_hover": "#B91C1C",
    "selection": "#2563EB",
    "chart_grid": "#CBD5E1",
}


def get_palette(light: bool = False) -> Dict[str, str]:
    """Return a copy of the visual palette for the requested appearance."""
    return dict(LIGHT_PALETTE if light else DARK_PALETTE)


def apply_ttk_theme(style, light: bool = False) -> Dict[str, str]:
    """Configure a compact, accessible Tk/ttk design system.

    ``style`` is intentionally duck-typed to keep this module importable when
    Tkinter is not installed.  The caller owns ``theme_use('clam')`` because
    changing a process-wide ttk engine unexpectedly is not this helper's job.
    """
    palette = get_palette(light)
    bg = palette["background"]
    surface = palette["surface"]
    raised = palette["surface_raised"]
    text = palette["text"]
    muted = palette["muted"]
    border = palette["border"]
    accent = palette["accent"]

    style.configure(".", background=bg, foreground=text, font=("Segoe UI", 10))
    style.configure("TFrame", background=bg)
    style.configure("Surface.TFrame", background=surface)
    style.configure("Header.TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=text)
    style.configure("Surface.TLabel", background=surface, foreground=text)
    style.configure("Title.TLabel", background=bg, foreground=text, font=("Segoe UI", 18, "bold"))
    style.configure("Eyebrow.TLabel", background=bg, foreground=accent, font=("Segoe UI", 9, "bold"))
    style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
    style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
    style.configure("TLabelframe", background=bg, foreground=accent, bordercolor=border, relief="flat")
    style.configure("TLabelframe.Label", background=bg, foreground=accent, font=("Segoe UI", 10, "bold"))
    style.configure("Card.TLabelframe", background=surface, foreground=accent, bordercolor=border, relief="flat")
    style.configure(
        "Card.TLabelframe.Label",
        background=surface,
        foreground=text,
        font=("Segoe UI", 10, "bold"),
    )
    style.configure("Card.TFrame", background=surface)
    style.configure("Card.TLabel", background=surface, foreground=text)
    style.configure("CardMuted.TLabel", background=surface, foreground=muted, font=("Segoe UI", 9))
    style.configure("Status.TLabel", background=surface, foreground=palette["success"], font=("Segoe UI", 9, "bold"))

    style.configure(
        "TButton",
        background=raised,
        foreground=text,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        relief="flat",
        borderwidth=1,
        padding=(11, 7),
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "TButton",
        background=[("active", palette["surface_hover"]), ("pressed", palette["accent_soft"]), ("disabled", surface)],
        foreground=[("disabled", muted)],
        bordercolor=[("focus", palette["border_focus"]), ("active", palette["border_focus"])],
    )
    style.configure(
        "Primary.TButton",
        background=accent,
        foreground="#FFFFFF",
        bordercolor=accent,
        lightcolor=accent,
        darkcolor=accent,
        font=("Segoe UI", 10, "bold"),
        padding=(13, 9),
    )
    style.map(
        "Primary.TButton",
        background=[("active", palette["accent_hover"]), ("pressed", palette["accent_hover"]), ("disabled", border)],
        foreground=[("disabled", "#E2E8F0")],
        bordercolor=[("focus", palette["border_focus"]), ("active", palette["accent_hover"])],
    )
    style.configure(
        "Danger.TButton",
        background=palette["danger"],
        foreground="#FFFFFF",
        bordercolor=palette["danger"],
        lightcolor=palette["danger"],
        darkcolor=palette["danger"],
        padding=(11, 7),
    )
    style.map(
        "Danger.TButton",
        background=[("active", palette["danger_hover"]), ("pressed", palette["danger_hover"])],
        bordercolor=[("focus", "#FCA5A5")],
    )
    style.configure("Compact.TButton", padding=(8, 5), font=("Segoe UI", 9, "bold"))

    style.configure(
        "TEntry",
        fieldbackground=surface,
        foreground=text,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        insertcolor=text,
        padding=6,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", palette["border_focus"])],
        lightcolor=[("focus", palette["border_focus"])],
        darkcolor=[("focus", palette["border_focus"])],
    )
    style.configure(
        "TCombobox",
        fieldbackground=surface,
        background=surface,
        foreground=text,
        arrowcolor=accent,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", surface), ("focus", surface), ("active", surface)],
        foreground=[("readonly", text), ("focus", text), ("active", text)],
        background=[("readonly", surface), ("focus", surface), ("active", surface)],
        bordercolor=[("focus", palette["border_focus"])],
        arrowcolor=[("active", palette["border_focus"])],
    )
    style.configure(
        "TSpinbox",
        fieldbackground=surface,
        background=surface,
        foreground=text,
        arrowcolor=accent,
        bordercolor=border,
        lightcolor=border,
        darkcolor=border,
        insertcolor=text,
    )
    style.map("TSpinbox", fieldbackground=[("focus", surface)], foreground=[("focus", text)])

    style.configure("TCheckbutton", background=bg, foreground=text, font=("Segoe UI", 9))
    style.configure("TRadiobutton", background=bg, foreground=text, font=("Segoe UI", 9))
    style.configure("Card.TCheckbutton", background=surface, foreground=text, font=("Segoe UI", 9))
    style.configure("Card.TRadiobutton", background=surface, foreground=text, font=("Segoe UI", 9))
    style.map(
        "TCheckbutton",
        background=[("active", bg), ("pressed", bg), ("focus", bg)],
        foreground=[("disabled", muted), ("active", text)],
    )
    style.map(
        "TRadiobutton",
        background=[("active", bg), ("pressed", bg), ("focus", bg)],
        foreground=[("disabled", muted), ("active", text)],
    )
    style.map(
        "Card.TCheckbutton",
        background=[("active", surface), ("pressed", surface), ("focus", surface)],
        foreground=[("disabled", muted), ("active", text)],
    )
    style.map(
        "Card.TRadiobutton",
        background=[("active", surface), ("pressed", surface), ("focus", surface)],
        foreground=[("disabled", muted), ("active", text)],
    )

    style.configure("TNotebook", background=bg, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=surface, foreground=muted, padding=(13, 8), font=("Segoe UI", 9, "bold"))
    style.map(
        "TNotebook.Tab",
        background=[("selected", accent), ("active", palette["surface_hover"])],
        foreground=[("selected", "#FFFFFF"), ("active", text)],
    )

    style.configure("Treeview", background=surface, fieldbackground=surface, foreground=text, bordercolor=border, rowheight=28)
    style.map("Treeview", background=[("selected", palette["selection"])], foreground=[("selected", "#FFFFFF")])
    style.configure("Treeview.Heading", background=raised, foreground=muted, font=("Segoe UI", 9, "bold"), relief="flat", padding=6)
    style.map("Treeview.Heading", background=[("active", palette["surface_hover"])], foreground=[("active", text)])
    return palette
