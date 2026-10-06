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
