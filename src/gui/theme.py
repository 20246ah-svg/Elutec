"""Shared, low-contrast color tokens for the desktop interface."""


def get_palette(light=True):
    """Return semantic UI colors for the requested appearance mode.

    The light palette is intentionally the default: high legibility, soft neutral
    surfaces, and a restrained teal accent keep long laboratory sessions easy on
    the eyes. Dark mode uses the same hierarchy without pure-black surfaces.
    """
    if light:
        return {
            "background": "#F3F6F5",
            "surface": "#FFFFFF",
            "surface_alt": "#F8FAF9",
            "surface_hover": "#EEF3F1",
            "text": "#1B2925",
            "muted": "#71817B",
            "border": "#DEE7E3",
            "accent": "#1E7569",
            "accent_hover": "#185E55",
            "accent_soft": "#E7F2EF",
            "accent_on": "#FFFFFF",
            "success": "#2F856D",
            "success_soft": "#E8F4EF",
            "warning": "#A9753D",
            "warning_soft": "#F8F0E4",
            "danger": "#B45F64",
            "danger_hover": "#9F5056",
            "danger_soft": "#F7EBEC",
            "danger_on": "#FFFFFF",
            "channel_r": "#C96F68",
            "channel_g": "#4E9272",
            "channel_b": "#6682AF",
            "chart_grid": "#E6ECE9",
            "video_background": "#17211E",
        }
    return {
        "background": "#121A17",
        "surface": "#19231F",
        "surface_alt": "#202C27",
        "surface_hover": "#283731",
        "text": "#E7EFEB",
        "muted": "#9BAAA4",
        "border": "#2D3D36",
        "accent": "#76BBAE",
        "accent_hover": "#92CCBF",
        "accent_soft": "#263A34",
        "accent_on": "#14211D",
        "success": "#83C6A7",
        "success_soft": "#263B32",
        "warning": "#D2A66C",
        "warning_soft": "#3B3023",
        "danger": "#D08084",
        "danger_hover": "#DE9699",
        "danger_soft": "#402C2E",
        "danger_on": "#241719",
        "channel_r": "#E18A80",
        "channel_g": "#79BC92",
        "channel_b": "#89A5D3",
        "chart_grid": "#2B3934",
        "video_background": "#0F1714",
    }
