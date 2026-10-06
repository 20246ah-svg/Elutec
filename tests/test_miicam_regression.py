import re
from pathlib import Path


def test_miicam_option_ids_match_bundled_sdk_header():
    header = Path('src/utils/miicam.h').read_text(encoding='utf-8', errors='ignore')
    wrapper = Path('src/utils/miicam_wrapper.py').read_text(encoding='utf-8')
    names = [
        'RAW', 'RGB', 'COLORMATIX', 'WBGAIN', 'BYTEORDER', 'BANDWIDTH',
        'FRAME_DEQUE_LENGTH', 'ANTI_SHUTTER_EFFECT', 'AWB_CONTINUOUS', 'ISP'
    ]
    for name in names:
        h = re.search(r'#define\s+MIICAM_OPTION_' + name + r'\s+(0x[0-9A-Fa-f]+)', header)
        w = re.search(r'MIICAM_OPTION_' + name + r'\s*=\s*(0x[0-9A-Fa-f]+)', wrapper)
        assert h and w, name
        assert int(h.group(1), 16) == int(w.group(1), 16), name


def test_wrapper_has_no_stale_frame_preload_option():
    wrapper = Path('src/utils/miicam_wrapper.py').read_text(encoding='utf-8')
    assert 'MIICAM_OPTION_FRAME_PRELOAD' not in wrapper


def test_neutral_detector_defaults():
    config = Path('src/config.py').read_text(encoding='utf-8')
    assert '"miicam_saturation": 128' in config
    assert '"miicam_contrast": 5' not in config
    assert '"miicam_contrast": 0' in config
    assert '"miicam_gamma": 100' in config
    assert '"miicam_hue": 0' in config
