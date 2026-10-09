from pathlib import Path

def test_no_noisy_miicam_options_at_startup():
    s=Path("src/utils/miicam_wrapper.py").read_text(encoding="utf-8")
    assert "Bandwidth=100%" not in s
    assert "AntiShutter=ON" not in s

def test_roi_mask_cache_exists():
    s=Path("src/utils/helpers.py").read_text(encoding="utf-8")
    assert "_ROI_MASK_CACHE" in s

def test_gui_does_not_copy_full_frame_each_iteration():
    s=Path("src/analysis/runner.py").read_text(encoding="utf-8")
    assert "snapshot(copy_frame=False)" in s


def test_main_screen_removes_unrequested_context_copy():
    source = Path("src/gui/setup_app.py").read_text(encoding="utf-8")
    assert "РАБОЧАЯ КОНСОЛЬ" not in source
    assert "Визуальный контроль фракционирования" not in source
    assert "SESSION / 01" not in source


def test_preview_size_is_isolated_and_scrollbars_keep_their_own_column():
    setup = Path("src/gui/setup_app.py").read_text(encoding="utf-8")
    projects = Path("src/gui/project_window.py").read_text(encoding="utf-8")
    assert "frame_prev.pack_propagate(False)" in setup
    assert setup.index("left_scrollbar.pack(side='right'") < setup.index("self.left_canvas.pack(side='left'")
    assert projects.index("scrollbar.pack(side=\"right\"") < projects.index("self.dashboard_canvas.pack(side=\"left\"")


def test_project_window_does_not_show_session_statistics_or_activity_feed():
    source = Path("src/gui/project_window.py").read_text(encoding="utf-8")
    for removed_label in (
        "Последние сессии",
        "Последнее измерение",
        "ACTIVITY / LAST 14 DAYS",
        "СЕССИИ",
    ):
        assert removed_label not in source
    assert ".list_sessions()" not in source
