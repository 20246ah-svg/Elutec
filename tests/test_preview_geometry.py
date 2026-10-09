import math

from src.gui.preview_geometry import (
    display_to_image_coordinates,
    format_preview_fps,
)


def test_pointer_mapping_accounts_for_centered_letterboxing():
    # A 640x480 source is displayed at 800x600 inside a 900x600 label.
    # The 50px side margins are not part of the source image.
    assert display_to_image_coordinates(
        450, 300, 1.25, 1.25, 50, 0, 640, 480
    ) == (320, 240)
    assert display_to_image_coordinates(
        25, 300, 1.25, 1.25, 50, 0, 640, 480
    ) is None


def test_drag_mapping_clamps_to_image_edges():
    assert display_to_image_coordinates(
        -25, 700, 1.25, 1.25, 50, 0, 640, 480, clamp=True
    ) == (0, 479)


def test_unknown_or_invalid_preview_fps_is_not_invented():
    for value in (None, 0, -1, "", "unknown", math.nan, math.inf):
        assert format_preview_fps(value) == "FPS: —"

    assert format_preview_fps(29.97) == "FPS: 30.0"
