import ast
import ctypes
import re
from pathlib import Path

from src.utils.miicam_sdk import Miicam


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


def test_binning_value_accessor_is_not_duplicated_and_lists_values():
    source_path = Path('src/utils/miicam_sdk.py')
    tree = ast.parse(source_path.read_text(encoding='utf-8'))
    miicam_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Miicam')
    assert sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'get_BinningValue'
        for node in miicam_class.body
    ) == 1

    class FakeLibrary:
        values = (b'1x1', b'2x2', b'4x4')

        def Miicam_get_BinningNumber(self, _handle):
            return len(self.values)

        def Miicam_get_BinningValue(self, _handle, index, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_char_p))[0] = self.values[index]

        def Miicam_Close(self, _handle):
            pass

    camera = Miicam(1)
    camera._Miicam__lib = FakeLibrary()
    assert camera.get_all_BinningValue() == ['1x1', '2x2', '4x4']
    assert camera.get_BinningValue(1) == '2x2'
    camera.Close()
