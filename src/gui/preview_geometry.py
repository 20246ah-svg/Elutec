"""Coordinate and display helpers for the letterboxed camera preview."""
import math


def display_to_image_coordinates(x, y, scale_x, scale_y, offset_x=0.0, offset_y=0.0,
                                image_width=None, image_height=None, clamp=False):
    """Map a pointer from the centered preview widget into source-image pixels.

    ``offset_x`` and ``offset_y`` are the letterbox margins around the resized
    image. Return ``None`` when a non-clamped pointer is outside the actual image.
    """
    try:
        px = float(x) - float(offset_x)
        py = float(y) - float(offset_y)
        sx = float(scale_x)
        sy = float(scale_y)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (px, py, sx, sy)) or sx <= 0 or sy <= 0:
        return None

    if image_width is not None:
        try:
            width = int(image_width)
        except (TypeError, ValueError, OverflowError):
            return None
        if width <= 0:
            return None
        display_width = width * sx
        if clamp:
            px = min(max(px, 0.0), max(0.0, display_width - 1e-9))
        elif px < 0 or px >= display_width:
            return None
    else:
        width = None
        if px < 0 and not clamp:
            return None
        if clamp:
            px = max(0.0, px)

    if image_height is not None:
        try:
            height = int(image_height)
        except (TypeError, ValueError, OverflowError):
            return None
        if height <= 0:
            return None
        display_height = height * sy
        if clamp:
            py = min(max(py, 0.0), max(0.0, display_height - 1e-9))
        elif py < 0 or py >= display_height:
            return None
    else:
        height = None
        if py < 0 and not clamp:
            return None
        if clamp:
            py = max(0.0, py)

    image_x = max(0, int(px / sx))
    image_y = max(0, int(py / sy))
    if width is not None:
        image_x = min(image_x, width - 1)
    if height is not None:
        image_y = min(image_y, height - 1)
    return image_x, image_y


def format_preview_fps(value):
    """Format a known positive finite frame rate; never invent a fallback."""
    try:
        fps = float(value)
    except (TypeError, ValueError, OverflowError):
        return "FPS: —"
    if not math.isfinite(fps) or fps <= 0:
        return "FPS: —"
    return f"FPS: {fps:.1f}"
