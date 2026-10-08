import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from src.config import (
    CLEAN_FRAME_PRESET, CLEAN_FRAME_PRESET_NAME, DEFAULT_DETECTOR_PRESETS,
)
from src.data.project_store import BUILTIN_BY_ID, BUILTIN_PRESETS
from src.utils import miicam_wrapper as mw


DEFAULT = DEFAULT_DETECTOR_PRESETS["По умолчанию (Default)"]


class FakeCam(mw.MiiCamCapture):
    """MiiCamCapture без железа: записывает отправленные опции."""
    def __init__(self):
        self.handle = 1
        self._isp_applied = {}
        self._isp_report = {}
        self.sent = []
        self.reject = set()
        self.auto_exposure = False
        self.gain_percent = 100
        self.exposure_us = 20000
        self.anti_flicker = 1

    def put_option(self, option_id, val):
        self.sent.append((option_id, val))
        return option_id not in self.reject

    def get_option(self, option_id):
        return dict((o, v) for o, v in self.sent).get(option_id)


def test_default_preset_can_restore_every_clean_key():
    # Переключение «Чистый кадр» -> «По умолчанию» обязано вернуть каждую изменённую опцию.
    assert set(CLEAN_FRAME_PRESET) <= set(DEFAULT)


def test_clean_preset_is_neutral_and_fixed():
    c = CLEAN_FRAME_PRESET
    assert c["miicam_auto_exposure"] is False
    assert c["miicam_gain"] == 100
    assert (c["miicam_brightness"], c["miicam_contrast"], c["miicam_gamma"], c["miicam_hue"]) == (0, 0, 100, 0)
    assert c["miicam_saturation"] == 128
    assert c["miicam_color_matrix"] is False and c["miicam_wb_gain_enable"] is False
    assert c["miicam_tone_curve"] == 0 and c["miicam_linear_tone"] == 0 and c["miicam_sharpening"] == 0
    assert c["miicam_binning"] == 1
    assert c["miicam_clean_frame"] is True
    assert c["miicam_exposure_us"] % 10000 == 0


def test_default_preset_values_equal_sdk_defaults():
    assert DEFAULT["miicam_color_matrix"] is True and DEFAULT["miicam_wb_gain_enable"] is True
    assert DEFAULT["miicam_tone_curve"] == 2 and DEFAULT["miicam_linear_tone"] == 1
    assert DEFAULT["miicam_clean_frame"] is False


def test_clean_preset_registered_and_default_stays_first():
    assert BUILTIN_PRESETS["detector"][0]["id"] == "builtin:detector.default"
    rec = BUILTIN_BY_ID["builtin:detector.clean_frame"]
    assert rec["name"] == CLEAN_FRAME_PRESET_NAME and rec["locked"] is True
    assert rec["settings"] == CLEAN_FRAME_PRESET


def test_apply_clean_sends_neutral_options_once():
    cam = FakeCam()
    cam.apply_isp_settings(CLEAN_FRAME_PRESET)
    sent = dict(cam.sent)
    assert sent[mw.MIICAM_OPTION_COLORMATIX] == 0
    assert sent[mw.MIICAM_OPTION_WBGAIN] == 0
    assert sent[mw.MIICAM_OPTION_CURVE] == 0
    assert sent[mw.MIICAM_OPTION_LINEAR] == 0
    assert sent[mw.MIICAM_OPTION_SHARPENING] == 0
    assert sent[mw.MIICAM_OPTION_DEMOSAIC] == 0
    assert sent[mw.MIICAM_OPTION_AWB_CONTINUOUS] == 0
    n = len(cam.sent)
    cam.apply_isp_settings(CLEAN_FRAME_PRESET)      # слайдер двинули — ничего лишнего не уходит
    assert len(cam.sent) == n


def test_switch_back_to_default_restores_factory_isp():
    cam = FakeCam()
    cam.apply_isp_settings(CLEAN_FRAME_PRESET)
    cam.sent.clear()
    cam.apply_isp_settings(DEFAULT)
    sent = dict(cam.sent)
    assert sent[mw.MIICAM_OPTION_COLORMATIX] == 1
    assert sent[mw.MIICAM_OPTION_WBGAIN] == 1
    assert sent[mw.MIICAM_OPTION_CURVE] == 2
    assert sent[mw.MIICAM_OPTION_LINEAR] == 1


def test_sharpening_encoding():
    cam = FakeCam()
    cam.apply_isp_settings({"miicam_sharpening": 100})
    assert dict(cam.sent)[mw.MIICAM_OPTION_SHARPENING] == (2 << 16) | 100


def test_missing_keys_are_not_touched():
    cam = FakeCam()
    cam.apply_isp_settings({"miicam_gain": 100})    # старый пресет без ISP-ключей
    assert cam.sent == []


def test_report_lists_rejected_options_and_warnings():
    cam = FakeCam()
    cam.reject = {mw.MIICAM_OPTION_CURVE}
    cam.exposure_us = 22000
    cam.gain_percent = 300
    cam.auto_exposure = True
    cam.apply_isp_settings(CLEAN_FRAME_PRESET)
    rep = cam.get_clean_frame_report()
    assert rep["failed"] == ["ToneCurve"]
    text = " ".join(rep["warnings"])
    assert "Автоэкспозиция" in text and "300%" in text and "22000" in text and "ToneCurve" in text


def test_flicker_helpers():
    assert mw.exposure_flicker_warning(20000, 1) is None
    assert mw.exposure_flicker_warning(10000, 1) is None
    assert mw.exposure_flicker_warning(22000, 1) is not None
    assert mw.exposure_flicker_warning(22000, 2) is None           # DC-свет: ограничения нет
    assert mw.exposure_flicker_warning(16667, 0) is None           # 2 периода при 60 Гц
    assert mw.exposure_flicker_warning(20000, 0) is not None


def test_check_tool_statistics():
    import clean_frame_check as tool
    rng = np.random.default_rng(1)
    frames = []
    for i in range(50):
        f = np.full((100, 120, 3), (60, 120, 200), dtype=np.uint8)
        f = np.clip(f.astype(np.int16) + rng.integers(-3, 4, f.shape), 0, 255).astype(np.uint8)
        frames.append(f)
    s = tool.summarize(frames, (10, 10, 50, 50))
    assert np.allclose(s["mean"], (60, 120, 200), atol=0.5)
    assert float(np.max(s["temporal_std"])) < 0.3
    assert float(np.max(s["clip_hi_percent"])) == 0.0
    assert tool.advice(s) == []
    hot = [np.full((40, 40, 3), 255, dtype=np.uint8)] * 3
    assert any("клиппинг" in t for t in tool.advice(tool.summarize(hot, (0, 0, 20, 20))))
    dark = [np.full((40, 40, 3), 10, dtype=np.uint8)] * 3
    assert any("тёмный" in t for t in tool.advice(tool.summarize(dark, (0, 0, 20, 20))))
    ramp = [np.full((40, 40, 3), 100 + i * 2, dtype=np.uint8) for i in range(10)]
    assert any("Дрейф" in t for t in tool.advice(tool.summarize(ramp, (0, 0, 20, 20))))
