"""
MiiCam / ToupCam Direct C-SDK Hardware Integration Wrapper
===========================================================
High-performance direct C-API bindings for MiiCam / ToupTek industrial CMOS cameras
(including Sony IMX178 / E3ISPM06300KPA and related RGB detector sensors).

Bypasses DirectShow / Media Foundation overhead for:
- Zero-copy / low-latency frame buffer delivery
- Full 24-bit RGB hardware color demosaicing with hardware Color Matrix & White Balance Gain
- Direct hardware optical controls (Exposure, Gain, Temp/Tint, Contrast, Saturation, Gamma)
- Automatic exposure & hardware luminance calibration preventing black screen issues
- Dynamic hardware binning and FPS configuration (up to 120 FPS)
- Elimination of startup green frames via hardware ISP warm-up and frame filtering
- Robust USB endpoint state-machine handling preventing ERROR_BUSY (-2147024726)
"""

import ctypes
import os
import sys
import threading
import time
import cv2
import numpy as np

# MiiCam / ToupCam C SDK Constants
MIICAM_FLAG_CMOS            = 0x00000001
MIICAM_FLAG_RAW10           = 0x00000200
MIICAM_FLAG_RAW12           = 0x00000400
MIICAM_FLAG_RAW14           = 0x00000800
MIICAM_FLAG_RAW16           = 0x00001000

# Hardware / image-pipeline options. IMPORTANT: these values MUST match
# the bundled miicam.h (SDK 60.31488.20260519). The previous wrapper used
# several stale values, so e.g. "RGB" and "Color Matrix" writes were sent to
# unrelated options. That can prevent correct initialization and badly distort
# colors.
MIICAM_OPTION_NOFRAME_TIMEOUT        = 0x01
MIICAM_OPTION_THREAD_PRIORITY        = 0x02
MIICAM_OPTION_RAW                    = 0x04
MIICAM_OPTION_HISTOGRAM              = 0x05
MIICAM_OPTION_BITDEPTH               = 0x06
MIICAM_OPTION_FAN                    = 0x07
MIICAM_OPTION_TEC                    = 0x08
MIICAM_OPTION_LINEAR                 = 0x09
MIICAM_OPTION_CURVE                  = 0x0A
MIICAM_OPTION_TRIGGER                = 0x0B
MIICAM_OPTION_RGB                    = 0x0C
MIICAM_OPTION_COLORMATIX             = 0x0D
MIICAM_OPTION_WBGAIN                 = 0x0E
MIICAM_OPTION_TECTARGET              = 0x0F
MIICAM_OPTION_AUTOEXP_POLICY         = 0x10
MIICAM_OPTION_FRAMERATE              = 0x11
MIICAM_OPTION_DEMOSAIC               = 0x12
MIICAM_OPTION_DEMOSAIC_VIDEO         = 0x13
MIICAM_OPTION_DEMOSAIC_STILL         = 0x14
MIICAM_OPTION_BLACKLEVEL             = 0x15
MIICAM_OPTION_MULTITHREAD            = 0x16
MIICAM_OPTION_BINNING                = 0x17
MIICAM_OPTION_SHARPENING             = 0x1E
MIICAM_OPTION_BYTEORDER              = 0x2A
MIICAM_OPTION_BANDWIDTH              = 0x2E
MIICAM_OPTION_CALLBACK_THREAD        = 0x30
MIICAM_OPTION_FRAME_DEQUE_LENGTH     = 0x31
MIICAM_OPTION_ANTI_SHUTTER_EFFECT    = 0x4B
MIICAM_OPTION_AWB_CONTINUOUS         = 0x6C
MIICAM_OPTION_ISP                    = 0x5F

# Event Flags
MIICAM_EVENT_EXPOSURE       = 0x0001
MIICAM_EVENT_TEMPTINT       = 0x0002
MIICAM_EVENT_CHROME         = 0x0003
MIICAM_EVENT_IMAGE          = 0x0004
MIICAM_EVENT_STILLIMAGE     = 0x0005
MIICAM_EVENT_WBGAIN         = 0x0006
MIICAM_EVENT_ERROR          = 0x0080
MIICAM_EVENT_DISCONNECTED   = 0x0081

# Maximum models / resolutions
MIICAM_MAX = 16


class MiicamResolution(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint),
        ('height', ctypes.c_uint)
    ]


class MiicamModel(ctypes.Structure):
    _fields_ = [
        ('name', ctypes.c_wchar_p),
        ('flag', ctypes.c_uint),
        ('maxspeed', ctypes.c_uint),
        ('preview', ctypes.c_uint),
        ('still', ctypes.c_uint),
        ('res', MiicamResolution * MIICAM_MAX)
    ]


class MiicamDevice(ctypes.Structure):
    _fields_ = [
        ('displayname', ctypes.c_wchar * 64),
        ('id', ctypes.c_wchar * 64),
        ('model', ctypes.POINTER(MiicamModel))
    ]


class MiicamFrameInfoV2(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint),
        ('height', ctypes.c_uint),
        ('flag', ctypes.c_uint),
        ('seq', ctypes.c_uint),
        ('timestamp', ctypes.c_longlong)
    ]


# Global DLL Handle Cache & Active Device Singleton
_cached_miicam_dll = None
_dll_search_done = False
_active_miicam_instance = None


def _find_and_load_dll():
    global _cached_miicam_dll, _dll_search_done
    if _cached_miicam_dll is not None:
        return _cached_miicam_dll
    if _dll_search_done and _cached_miicam_dll is None:
        return None

    _dll_search_done = True

    # Register directories for Windows DLL dependency resolution
    bundled_root = getattr(sys, "_MEIPASS", None)
    search_dirs = [
        os.path.join(bundled_root, "src", "utils") if bundled_root else None,
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.getcwd(),
        r"C:\Program Files\ToupTek\ToupView",
        r"C:\Program Files (x86)\ToupTek\ToupView",
    ]
    search_dirs = [d for d in search_dirs if d]

    for d in search_dirs:
        if os.path.isdir(d):
            if sys.platform == "win32" and hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass

    # Check explicit absolute file paths first
    candidate_paths = []
    for d in search_dirs:
        for fname in ["miicam.dll", "toupcam.dll"]:
            p = os.path.abspath(os.path.join(d, fname))
            if p not in candidate_paths and os.path.isfile(p):
                candidate_paths.append(p)

    for p in candidate_paths:
        try:
            dll = ctypes.WinDLL(p) if sys.platform == "win32" else ctypes.CDLL(p)
            _cached_miicam_dll = dll
            print(f"✓ Успешно загружена библиотека RGB-детектора: {p}")
            return _cached_miicam_dll
        except Exception as e:
            pass

    # Fallback to system-level library names
    for name in ["miicam.dll", "toupcam.dll", "miicam", "toupcam"]:
        try:
            dll = ctypes.WinDLL(name) if sys.platform == "win32" else ctypes.CDLL(name)
            _cached_miicam_dll = dll
            print(f"✓ Загружена системная библиотека MiiCam/ToupCam: {name}")
            return _cached_miicam_dll
        except Exception:
            pass

    return None


def is_miicam_available():
    """Check if MiiCam/ToupCam native SDK is present in the system."""
    return _find_and_load_dll() is not None


def enumerate_miicam_devices():
    """Enumerate all connected MiiCam/ToupCam RGB detector cameras."""
    dll = _find_and_load_dll()
    if not dll:
        return []

    try:
        # Determine Enum function signature
        enum_fn = getattr(dll, 'Miicam_Enum', None) or getattr(dll, 'Toupcam_Enum', None)
        if not enum_fn:
            return []

        enum_fn.restype = ctypes.c_uint
        devices_array = (MiicamDevice * MIICAM_MAX)()
        cnt = enum_fn(devices_array)

        results = []
        for i in range(cnt):
            dev = devices_array[i]
            d_name = dev.displayname
            d_id = dev.id
            resolutions = []
            if dev.model:
                m = dev.model.contents
                for r_idx in range(m.preview):
                    resolutions.append((m.res[r_idx].width, m.res[r_idx].height))

            results.append({
                'index': i,
                'name': d_name,
                'id': d_id,
                'source': f"miicam:{i}",
                'resolutions': resolutions
            })
        return results
    except Exception as e:
        print(f"⚠️ Ошибка перечисления устройств MiiCam: {e}")
        return []


if sys.platform == "win32":
    CALLBACK_TYPE = ctypes.WINFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)
else:
    CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)


def mains_flicker_period_us(anti_flicker_mode):
    """Период мерцания света от сети в мкс: 0 -> 60 Гц (120 Гц мерцание), 1 -> 50 Гц (100 Гц), 2 -> DC (нет)."""
    return {0: 1_000_000.0 / 120.0, 1: 1_000_000.0 / 100.0}.get(int(anti_flicker_mode))


def exposure_flicker_warning(exposure_us, anti_flicker_mode, tol_us=60.0):
    """Текст предупреждения, если выдержка не кратна периоду мерцания света; иначе None."""
    period = mains_flicker_period_us(anti_flicker_mode)
    if not period or exposure_us <= 0:
        return None
    k = max(1, round(exposure_us / period))
    nearest = k * period
    if abs(exposure_us - nearest) <= tol_us:
        return None
    return (f"Выдержка {exposure_us} мкс не кратна периоду мерцания сети ({period:.0f} мкс): "
            f"при питании света от сети возможны биения яркости. Ближайшее кратное: {nearest:.0f} мкс.")


class MiiCamCapture:
    """
    High-performance OpenCV VideoCapture compatible wrapper for MiiCam cameras.
    """
    def __init__(self, source="miicam:0", width=None, height=None):
        global _active_miicam_instance
        # Safely release previous instance to avoid USB endpoint contention ERROR_BUSY (-2147024726)
        if _active_miicam_instance is not None and _active_miicam_instance is not self:
            try:
                _active_miicam_instance.release()
            except Exception:
                pass
            _active_miicam_instance = None
            time.sleep(0.18)

        self.is_miicam = True
        self.source = str(source)
        self.handle = None
        self._opened = False
        self._pulling = False
        self._lock = threading.RLock()
        self._latest_frame = None
        self._frame_ready_event = threading.Event()
        # Native SDK callbacks can arrive on an SDK-owned thread.  During
        # shutdown we must drain an in-flight PullImage call before calling
        # Miicam_Close, otherwise a fast stop->reopen cycle can return
        # ERROR_BUSY (-2147024726) and wedge the application.
        self._active_pull_count = 0
        self._pull_drain_event = threading.Event()
        self._pull_drain_event.set()
        self._width = width or 2048
        self._height = height or 1536
        self._req_w = width
        self._req_h = height
        self._res_index = 0
        self._buffer = None
        self._callback_ptr = None
        self._is_stopped = False
        self._frame_count = 0
        self._awb_settled = False

        # Optical settings cache (Calibrated defaults for bright, clear RGB imaging)
        self.exposure_us = 22000  # 22 ms
        self.auto_exposure = True # Enable Auto-Exposure by default to prevent black frames
        self.gain_percent = 100
        self.wb_r = 0
        self.wb_g = 0
        self.wb_b = 0
        self.wb_temp = 6500
        self.wb_tint = 1000
        self.gamma = 100
        self.contrast = 5
        self.brightness = 0
        self.saturation = 135
        self.hue = 0
        self.speed = 2          # High speed for smooth FPS
        self.binning_mode = 1   # 1: 1x1, 2: 2x2 binning
        self.frame_preload = True
        self.thread_priority = 2
        self.h_flip = False
        self.v_flip = False
        self.anti_flicker = 1   # 0: 60Hz, 1: 50Hz, 2: DC
        self._isp_applied = {}  # option id -> last value sent (avoid re-sending on every slider move)
        self._isp_report = {}   # label -> {'value', 'ok', 'readback'}
        self.fps = 30.0
        self._fps_count = 0
        self._fps_start = time.time()

        self._open_device()
        if self._opened:
            _active_miicam_instance = self

    def _open_device(self):
        dll = _find_and_load_dll()
        if not dll:
            print(f"❌ MiiCam DLL не найдена. Не удалось открыть {self.source}")
            return False

        try:
            cam_id = None
            if ":" in self.source:
                spec = self.source.split(":", 1)[1].strip()
                try:
                    idx = int(spec)
                    devs = enumerate_miicam_devices()
                    if 0 <= idx < len(devs):
                        cam_id = devs[idx]['id']
                except ValueError:
                    cam_id = spec

            open_fn = getattr(dll, 'Miicam_Open', None) or getattr(dll, 'Toupcam_Open', None)
            if not open_fn:
                print("❌ Функция открытия камеры не найдена в DLL")
                return False

            open_fn.restype = ctypes.c_void_p
            open_fn.argtypes = [ctypes.c_wchar_p]

            h = None
            for attempt in range(4):
                h = open_fn(cam_id)
                if h:
                    break
                time.sleep(0.15)

            # Some driver/firmware combinations are more reliable with the
            # SDK's explicit index opener than with the enumerated opaque ID.
            if not h and ':' in self.source:
                try:
                    idx = int(self.source.split(':', 1)[1].strip())
                except ValueError:
                    idx = None
                open_index_fn = getattr(dll, 'Miicam_OpenByIndex', None) or getattr(dll, 'Toupcam_OpenByIndex', None)
                if idx is not None and open_index_fn:
                    open_index_fn.restype = ctypes.c_void_p
                    open_index_fn.argtypes = [ctypes.c_uint]
                    for attempt in range(3):
                        h = open_index_fn(ctypes.c_uint(idx))
                        if h:
                            break
                        time.sleep(0.2)

            if not h:
                print(f"❌ Ошибка открытия камеры MiiCam: {cam_id or self.source}")
                return False

            self.handle = h
            self._opened = True
            self._frame_count = 0
            self._awb_settled = False

            # Determine available hardware resolutions
            resolutions = self.get_available_resolutions()
            
            # Select resolution: prefer fast live mode (Index 1 or requested resolution)
            best_idx = 0
            if self._req_w and self._req_h:
                best_diff = float('inf')
                for idx, (rw, rh) in enumerate(resolutions):
                    diff = abs(rw - self._req_w) + abs(rh - self._req_h)
                    if diff < best_diff:
                        best_diff = diff
                        best_idx = idx
            elif len(resolutions) > 1:
                # If no resolution specified, pick index 1 (medium resolution ~2048x1536 / 1536x1024)
                # for smooth 30 FPS over USB 2.0 without choking bus bandwidth
                best_idx = 1 if len(resolutions) > 1 else 0

            self._res_index = best_idx
            set_esize_fn = getattr(dll, 'Miicam_put_eSize', None) or getattr(dll, 'Toupcam_put_eSize', None)
            if set_esize_fn:
                set_esize_fn.restype = ctypes.c_int
                set_esize_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                set_esize_fn(h, ctypes.c_uint(best_idx))

            # Query resulting dimensions
            w_c = ctypes.c_int()
            h_c = ctypes.c_int()
            get_size_fn = getattr(dll, 'Miicam_get_Size', None) or getattr(dll, 'Toupcam_get_Size', None)
            if get_size_fn:
                get_size_fn.restype = ctypes.c_int
                get_size_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                get_size_fn(h, ctypes.byref(w_c), ctypes.byref(h_c))
                if w_c.value > 0 and h_c.value > 0:
                    self._width = w_c.value
                    self._height = h_c.value
            elif best_idx < len(resolutions):
                self._width, self._height = resolutions[best_idx]

            # Set USB transfer speed to max for high FPS
            set_speed_fn = getattr(dll, 'Miicam_put_Speed', None) or getattr(dll, 'Toupcam_put_Speed', None)
            if set_speed_fn:
                set_speed_fn.restype = ctypes.c_int
                set_speed_fn.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                set_speed_fn(h, ctypes.c_ushort(2))

            # Pre-streaming standard color options:
            put_opt_fn = getattr(dll, 'Miicam_put_Option', None) or getattr(dll, 'Toupcam_put_Option', None)
            # Pre-streaming standard color & performance options:
            put_opt_fn = getattr(dll, 'Miicam_put_Option', None) or getattr(dll, 'Toupcam_put_Option', None)
            if put_opt_fn:
                put_opt_fn.restype = ctypes.c_int
                put_opt_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]

                # True RGB pipeline: let the camera ISP demosaic the Bayer sensor,
                # output BGR24 for OpenCV, and use the manufacturer's color matrix.
                # These option IDs are taken from the bundled SDK header.
                color_options = [
                    (MIICAM_OPTION_RAW, 0, 'RAW=RGB'),
                    (MIICAM_OPTION_BYTEORDER, 1, 'BYTEORDER=BGR'),
                    (MIICAM_OPTION_RGB, 0, 'RGB24'),
                    (MIICAM_OPTION_COLORMATIX, 1, 'ColorMatrix=ON'),
                    (MIICAM_OPTION_WBGAIN, 1, 'WBGain=ON'),
                    (MIICAM_OPTION_FRAME_DEQUE_LENGTH, 4, 'FrameQueue=4'),
                    (MIICAM_OPTION_THREAD_PRIORITY, 2, 'ThreadPriority=2'),
                ]
                for opt, value, label in color_options:
                    try:
                        rc = int(put_opt_fn(h, ctypes.c_uint(opt), ctypes.c_int(value)))
                        if rc < 0:
                            pass
                    except Exception as exc:
                        print(f'⚠️ MiiCam option {label} failed: {exc}')

            # Enable full color mode (In ToupCam/MiiCam C SDK: 0 => Color mode, 1 => Monochromatic mode!)
            set_chrome_fn = getattr(dll, 'Miicam_put_Chrome', None) or getattr(dll, 'Toupcam_put_Chrome', None)
            if set_chrome_fn:
                set_chrome_fn.restype = ctypes.c_int
                set_chrome_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                set_chrome_fn(h, ctypes.c_int(0))

            # Enable 50Hz Anti-flicker
            self.set_anti_flicker(1)

            # Cap max auto-exposure time to 33ms (30 FPS) and allow gain up to 800%
            max_ae_fn = getattr(dll, 'Miicam_put_MaxAutoExpoTimeAGain', None) or getattr(dll, 'Toupcam_put_MaxAutoExpoTimeAGain', None)
            if max_ae_fn:
                try:
                    max_ae_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ushort]
                    max_ae_fn(h, ctypes.c_uint(33000), ctypes.c_ushort(800))
                except Exception:
                    pass

            # Enable Auto-Exposure by default with 120 target luminance so camera is bright and clear
            set_ae_fn = getattr(dll, 'Miicam_put_AutoExpoEnable', None) or getattr(dll, 'Toupcam_put_AutoExpoEnable', None)
            if set_ae_fn:
                set_ae_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                set_ae_fn(h, ctypes.c_int(1))
            set_aet_fn = getattr(dll, 'Miicam_put_AutoExpoTarget', None) or getattr(dll, 'Toupcam_put_AutoExpoTarget', None)
            if set_aet_fn:
                set_aet_fn.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                set_aet_fn(h, ctypes.c_ushort(120))

            # Apply initial calibrated optical settings
            self.set_saturation(128)
            self.set_contrast(0)
            self.set_brightness(0)
            self.set_gamma(100)
            self.set_gain_percent(100)
            self.set_exposure_time_us(22000)

            # Allocate frame buffer (24-bit BGR aligned to 4 bytes per row)
            row_pitch = ((self._width * 24 + 31) // 32) * 4
            self._buf_size = row_pitch * self._height
            self._buffer = (ctypes.c_ubyte * self._buf_size)()

            # Setup pull callback
            def _event_callback(n_event, ctx):
                if n_event in (MIICAM_EVENT_IMAGE, MIICAM_EVENT_STILLIMAGE, MIICAM_EVENT_EXPOSURE, MIICAM_EVENT_TEMPTINT):
                    self._pull_latest_frame()

            self._callback_ptr = CALLBACK_TYPE(_event_callback)

            start_pull_fn = getattr(dll, 'Miicam_StartPullModeWithCallback', None) or getattr(dll, 'Toupcam_StartPullModeWithCallback', None)
            if start_pull_fn:
                start_pull_fn.restype = ctypes.c_int
                start_pull_fn.argtypes = [ctypes.c_void_p, CALLBACK_TYPE, ctypes.c_void_p]
                ret = start_pull_fn(h, self._callback_ptr, None)
                if ret < 0:
                    time.sleep(0.15)
                    ret = start_pull_fn(h, self._callback_ptr, None)
                if ret >= 0:
                    self._pulling = True
                else:
                    print(f"⚠️ StartPullModeWithCallback status: {ret}")
                    self.release()
                    return False

            # Options applied AFTER streaming starts
            if put_opt_fn:
                try:
                    # High thread priority (2 = real-time/critical)
                    put_opt_fn(h, ctypes.c_uint(MIICAM_OPTION_THREAD_PRIORITY), ctypes.c_int(2))
                    # Do NOT continuously rewrite WB while measuring color. A changing
                    # white balance makes the same physical color produce different RGB
                    # values. We do one-push AWB below, then lock it.
                    put_opt_fn(h, ctypes.c_uint(MIICAM_OPTION_AWB_CONTINUOUS), ctypes.c_int(0))
                except Exception:
                    pass

            # Trigger immediate Auto White Balance on startup
            awb_fn = getattr(dll, 'Miicam_AwbOnce', None) or getattr(dll, 'Toupcam_AwbOnce', None) or getattr(dll, 'Toupcam_AwbOnePush', None)
            if awb_fn:
                try:
                    awb_fn.restype = ctypes.c_int
                    awb_fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                    rc = int(awb_fn(h, None, None))
                    if rc < 0:
                        print(f'⚠️ MiiCam One-Push AWB returned: {rc}')
                except Exception as exc:
                    print(f'⚠️ MiiCam AWB initialization failed: {exc}')

            # Let AWB and the ISP settle, then explicitly disable continuous AWB.
            self._frame_ready_event.wait(timeout=1.2)
            try:
                if put_opt_fn:
                    put_opt_fn(h, ctypes.c_uint(MIICAM_OPTION_AWB_CONTINUOUS), ctypes.c_int(0))
            except Exception:
                pass

            # Read initial parameters
            self._sync_hardware_settings()
            print(f"✅ MiiCam RGB-детектор успешно подключен: {self._width}x{self._height} (Режим #{self._res_index})")
            return True

        except Exception as e:
            print(f"❌ Исключение при открытии MiiCam: {e}")
            self.release()
            return False

    def _pull_latest_frame(self):
        if not self.handle or not self._opened or self._is_stopped:
            return
        dll = _find_and_load_dll()
        if not dll:
            return

        try:
            with self._lock:
                if not self.handle or not self._opened or self._is_stopped or not self._pulling:
                    return
                self._active_pull_count += 1
                self._pull_drain_event.clear()

                # Ensure buffer is allocated
                w = self._width if self._width > 0 else 640
                h = self._height if self._height > 0 else 480
                row_pitch = ((w * 24 + 31) // 32) * 4
                needed_buf = max(row_pitch * h, 1920 * 1080 * 4)
                if self._buffer is None or len(self._buffer) < needed_buf:
                    self._buf_size = needed_buf
                    self._buffer = (ctypes.c_ubyte * needed_buf)()

                # Support both PullImageV2 and classic PullImage
                pull_v2 = getattr(dll, 'Miicam_PullImageV2', None) or getattr(dll, 'Toupcam_PullImageV2', None)
                pull_v1 = getattr(dll, 'Miicam_PullImage', None) or getattr(dll, 'Toupcam_PullImage', None)

                frame_w, frame_h = 0, 0
                got_frame = False

                if pull_v2:
                    info = MiicamFrameInfoV2()
                    pull_v2.restype = ctypes.c_int
                    pull_v2.argtypes = [
                        ctypes.c_void_p,
                        ctypes.c_void_p,
                        ctypes.c_int,
                        ctypes.POINTER(MiicamFrameInfoV2)
                    ]
                    res = pull_v2(
                        self.handle,
                        ctypes.cast(self._buffer, ctypes.c_void_p),
                        24,
                        ctypes.byref(info)
                    )
                    if res == 0 and info.width > 0 and info.height > 0:
                        frame_w, frame_h = info.width, info.height
                        got_frame = True
                
                if not got_frame and pull_v1:
                    w_out = ctypes.c_uint(0)
                    h_out = ctypes.c_uint(0)
                    pull_v1.restype = ctypes.c_int
                    pull_v1.argtypes = [
                        ctypes.c_void_p,
                        ctypes.c_void_p,
                        ctypes.c_int,
                        ctypes.POINTER(ctypes.c_uint),
                        ctypes.POINTER(ctypes.c_uint)
                    ]
                    res = pull_v1(
                        self.handle,
                        ctypes.cast(self._buffer, ctypes.c_void_p),
                        24,
                        ctypes.byref(w_out),
                        ctypes.byref(h_out)
                    )
                    if res == 0 and w_out.value > 0 and h_out.value > 0:
                        frame_w, frame_h = w_out.value, h_out.value
                        got_frame = True

                if got_frame and frame_w > 0 and frame_h > 0:
                    w, h = frame_w, frame_h
                    row_pitch = ((w * 24 + 31) // 32) * 4
                    total_needed = row_pitch * h

                    if len(self._buffer) < total_needed:
                        self._buf_size = total_needed * 2
                        self._buffer = (ctypes.c_ubyte * self._buf_size)()
                        return

                    raw_bytes = bytes(self._buffer)
                    if len(raw_bytes) >= total_needed:
                        if row_pitch == w * 3:
                            frame = np.frombuffer(raw_bytes[:w * h * 3], dtype=np.uint8).reshape((h, w, 3))
                        else:
                            arr = np.frombuffer(raw_bytes[:row_pitch * h], dtype=np.uint8).reshape((h, row_pitch))
                            frame = arr[:, :w * 3].reshape((h, w, 3))

                        # Frame is native OpenCV BGR24 format (BYTEORDER=1)
                        if getattr(self, 'swap_rb', False):
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                        self._frame_count += 1
                        self._fps_count += 1
                        now = time.time()
                        dt = now - self._fps_start
                        if dt >= 0.5:
                            self.fps = round(self._fps_count / dt, 1)
                            self._fps_count = 0
                            self._fps_start = now

                        # Trigger AWB on first frame to immediately adapt to ambient lighting
                        if self._frame_count == 1:
                            awb_fn = getattr(dll, 'Miicam_AwbOnce', None) or getattr(dll, 'Toupcam_AwbOnce', None)
                            if awb_fn:
                                try:
                                    awb_fn(self.handle, None, None)
                                except Exception:
                                    pass

                        # Discard first 2 raw frames before hardware AWB calculation settles
                        # to eliminate any momentary green tint on startup
                        if self._frame_count < 3 and not self._awb_settled:
                            return

                        if not self._awb_settled:
                            self._awb_settled = True
                            self._sync_hardware_settings()

                        self._latest_frame = frame.copy()
                        self._width = w
                        self._height = h
                        self._frame_ready_event.set()
        except Exception:
            pass
        finally:
            with self._lock:
                self._active_pull_count = max(0, self._active_pull_count - 1)
                if self._active_pull_count == 0:
                    self._pull_drain_event.set()

    def _sync_hardware_settings(self):
        """Query and cache current camera parameters."""
        dll = _find_and_load_dll()
        if not dll or not self.handle:
            return

        try:
            get_exp_fn = getattr(dll, 'Miicam_get_ExpoTime', None) or getattr(dll, 'Toupcam_get_ExpoTime', None)
            if get_exp_fn:
                t_c = ctypes.c_uint()
                get_exp_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
                if get_exp_fn(self.handle, ctypes.byref(t_c)) >= 0:
                    self.exposure_us = t_c.value

            get_ae_fn = getattr(dll, 'Miicam_get_AutoExpoEnable', None) or getattr(dll, 'Toupcam_get_AutoExpoEnable', None)
            if get_ae_fn:
                ae_c = ctypes.c_int()
                get_ae_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_ae_fn(self.handle, ctypes.byref(ae_c)) >= 0:
                    self.auto_exposure = bool(ae_c.value)

            get_gain_fn = getattr(dll, 'Miicam_get_ExpoAGain', None) or getattr(dll, 'Toupcam_get_ExpoAGain', None)
            if get_gain_fn:
                g_c = ctypes.c_ushort()
                get_gain_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort)]
                if get_gain_fn(self.handle, ctypes.byref(g_c)) >= 0:
                    self.gain_percent = int(g_c.value)

            get_gamma_fn = getattr(dll, 'Miicam_get_Gamma', None) or getattr(dll, 'Toupcam_get_Gamma', None)
            if get_gamma_fn:
                val = ctypes.c_int()
                get_gamma_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_gamma_fn(self.handle, ctypes.byref(val)) >= 0:
                    self.gamma = val.value

            get_contrast_fn = getattr(dll, 'Miicam_get_Contrast', None) or getattr(dll, 'Toupcam_get_Contrast', None)
            if get_contrast_fn:
                val = ctypes.c_int()
                get_contrast_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_contrast_fn(self.handle, ctypes.byref(val)) >= 0:
                    self.contrast = val.value

            get_bright_fn = getattr(dll, 'Miicam_get_Brightness', None) or getattr(dll, 'Toupcam_get_Brightness', None)
            if get_bright_fn:
                val = ctypes.c_int()
                get_bright_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_bright_fn(self.handle, ctypes.byref(val)) >= 0:
                    self.brightness = val.value

            get_hue_fn = getattr(dll, 'Miicam_get_Hue', None) or getattr(dll, 'Toupcam_get_Hue', None)
            if get_hue_fn:
                val = ctypes.c_int()
                get_hue_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_hue_fn(self.handle, ctypes.byref(val)) >= 0:
                    self.hue = val.value

            get_sat_fn = getattr(dll, 'Miicam_get_Saturation', None) or getattr(dll, 'Toupcam_get_Saturation', None)
            if get_sat_fn:
                val = ctypes.c_int()
                get_sat_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_sat_fn(self.handle, ctypes.byref(val)) >= 0:
                    self.saturation = val.value

            get_tt_fn = getattr(dll, 'Miicam_get_TempTint', None) or getattr(dll, 'Toupcam_get_TempTint', None)
            if get_tt_fn:
                p_temp = ctypes.c_int()
                p_tint = ctypes.c_int()
                get_tt_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                if get_tt_fn(self.handle, ctypes.byref(p_temp), ctypes.byref(p_tint)) >= 0:
                    if p_temp.value > 0 and p_tint.value > 0:
                        self.wb_temp = p_temp.value
                        self.wb_tint = p_tint.value

            get_wbg_fn = getattr(dll, 'Miicam_get_WhiteBalanceGain', None) or getattr(dll, 'Toupcam_get_WhiteBalanceGain', None)
            if get_wbg_fn:
                arr = (ctypes.c_int * 3)()
                get_wbg_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if get_wbg_fn(self.handle, arr) >= 0:
                    self.wb_r = arr[0]
                    self.wb_g = arr[1]
                    self.wb_b = arr[2]

        except Exception:
            pass

    # OpenCV VideoCapture API interface
    def isOpened(self):
        return self._opened and (self.handle is not None)

    def get_available_resolutions(self):
        dll = _find_and_load_dll()
        if not dll or not self.handle:
            return [(self._width, self._height)]
        resolutions = []
        try:
            get_res_num_fn = getattr(dll, 'Miicam_get_ResolutionNumber', None) or getattr(dll, 'Toupcam_get_ResolutionNumber', None)
            get_res_fn = getattr(dll, 'Miicam_get_Resolution', None) or getattr(dll, 'Toupcam_get_Resolution', None)

            if get_res_num_fn and get_res_fn:
                get_res_num_fn.restype = ctypes.c_int
                get_res_num_fn.argtypes = [ctypes.c_void_p]
                cnt = get_res_num_fn(self.handle)

                get_res_fn.restype = ctypes.c_int
                get_res_fn.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint,
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
                ]
                for i in range(cnt):
                    w_c = ctypes.c_int()
                    h_c = ctypes.c_int()
                    get_res_fn(self.handle, ctypes.c_uint(i), ctypes.byref(w_c), ctypes.byref(h_c))
                    if w_c.value > 0 and h_c.value > 0:
                        resolutions.append((w_c.value, h_c.value))
        except Exception as e:
            print(f"⚠️ Ошибка получения списка разрешений MiiCam: {e}")
        if not resolutions:
            resolutions = [(self._width, self._height)]
        return resolutions

    def set_resolution(self, target_w, target_h):
        dll = _find_and_load_dll()
        if not dll or not self.handle:
            return False
        try:
            target_w, target_h = int(target_w), int(target_h)
            resolutions = self.get_available_resolutions()
            if not resolutions:
                return False

            best_idx = 0
            best_diff = float('inf')
            for idx, (rw, rh) in enumerate(resolutions):
                if rw == target_w and rh == target_h:
                    best_idx = idx
                    best_diff = 0
                    break
                diff = abs(rw - target_w) + abs(rh - target_h)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = idx

            chosen_w, chosen_h = resolutions[best_idx]
            if chosen_w == self._width and chosen_h == self._height and self._res_index == best_idx and self._pulling:
                return True

            print(f"🔄 Смена аппаратного разрешения MiiCam на индекс #{best_idx}: {chosen_w}x{chosen_h}")

            with self._lock:
                # 1. Stop streaming
                stop_fn = getattr(dll, 'Miicam_Stop', None) or getattr(dll, 'Toupcam_Stop', None)
                if stop_fn:
                    stop_fn(self.handle)
                self._pulling = False
                self._frame_ready_event.clear()
                time.sleep(0.04)

                # 2. Set new resolution index
                set_esize_fn = getattr(dll, 'Miicam_put_eSize', None) or getattr(dll, 'Toupcam_put_eSize', None)
                if set_esize_fn:
                    set_esize_fn.restype = ctypes.c_int
                    set_esize_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    set_esize_fn(self.handle, ctypes.c_uint(best_idx))

                # Query actual resulting dimensions
                w_c = ctypes.c_int()
                h_c = ctypes.c_int()
                get_size_fn = getattr(dll, 'Miicam_get_Size', None) or getattr(dll, 'Toupcam_get_Size', None)
                if get_size_fn:
                    get_size_fn.restype = ctypes.c_int
                    get_size_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                    if get_size_fn(self.handle, ctypes.byref(w_c), ctypes.byref(h_c)) >= 0:
                        if w_c.value > 0 and h_c.value > 0:
                            chosen_w = w_c.value
                            chosen_h = h_c.value

                self._width = chosen_w
                self._height = chosen_h
                self._res_index = best_idx

                # 3. Preallocate safe frame buffer
                row_pitch = ((self._width * 24 + 31) // 32) * 4
                self._buf_size = max(row_pitch * self._height, 1920 * 1080 * 4)
                self._buffer = (ctypes.c_ubyte * self._buf_size)()
                self._latest_frame = None

                # 4. Restart streaming
                start_pull_fn = getattr(dll, 'Miicam_StartPullModeWithCallback', None) or getattr(dll, 'Toupcam_StartPullModeWithCallback', None)
                if start_pull_fn and self._callback_ptr:
                    start_pull_fn.restype = ctypes.c_int
                    start_pull_fn.argtypes = [ctypes.c_void_p, CALLBACK_TYPE, ctypes.c_void_p]
                    ret = start_pull_fn(self.handle, self._callback_ptr, None)
                    if ret >= 0:
                        self._pulling = True
                        time.sleep(0.03)

            # Wait briefly for first frame
            self._frame_ready_event.wait(timeout=0.35)
            return True
        except Exception as e:
            print(f"❌ Ошибка смены разрешения MiiCam: {e}")
            return False

    def read(self):
        if not self.isOpened() or self._is_stopped:
            return False, None

        # Wait for a fresh hardware frame arrival event (synchronizes with true sensor FPS)
        got_event = self._frame_ready_event.wait(timeout=0.04)
        self._frame_ready_event.clear()

        # If callback didn't trigger in time, poll frame directly
        if not got_event:
            self._pull_latest_frame()

        with self._lock:
            if self._latest_frame is not None:
                return True, self._latest_frame

        return False, None

    def release(self):
        """Stop and close the native camera without racing SDK callbacks."""
        global _active_miicam_instance

        # Make release idempotent.
        with self._lock:
            handle = self.handle
            if handle is None:
                self._opened = False
                self._pulling = False
                self._is_stopped = True
                if _active_miicam_instance is self:
                    _active_miicam_instance = None
                return

            # Prevent any new callback from entering PullImage. An already
            # running callback is drained below before Stop/Close.
            self._is_stopped = True
            self._opened = False
            self._pulling = False
            self._frame_ready_event.set()

        dll = _find_and_load_dll()
        if dll:
            try:
                # Wait for a callback that was already inside PullImage.
                self._pull_drain_event.wait(timeout=1.0)
            except Exception:
                pass

            try:
                stop_fn = getattr(dll, 'Miicam_Stop', None) or getattr(dll, 'Toupcam_Stop', None)
                if stop_fn:
                    stop_fn.restype = ctypes.c_int
                    stop_fn.argtypes = [ctypes.c_void_p]
                    stop_fn(handle)
            except Exception:
                pass

            # The SDK tears down its USB callback/queue asynchronously. Give
            # it a deterministic grace period before Close and subsequent Open.
            time.sleep(0.12)

            try:
                close_fn = getattr(dll, 'Miicam_Close', None) or getattr(dll, 'Toupcam_Close', None)
                if close_fn:
                    close_fn.argtypes = [ctypes.c_void_p]
                    close_fn(handle)
            except Exception:
                pass

            # A second short settle interval prevents an immediate reopen from
            # colliding with the SDK's USB endpoint teardown.
            time.sleep(0.12)

        with self._lock:
            if self.handle == handle:
                self.handle = None
            self._latest_frame = None
            self._callback_ptr = None
            self._frame_ready_event.clear()

        if _active_miicam_instance is self:
            _active_miicam_instance = None

    def get(self, prop_id):
        import cv2
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._width)
        elif prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._height)
        elif prop_id == cv2.CAP_PROP_FPS:
            return float(self.fps)
        elif prop_id == cv2.CAP_PROP_EXPOSURE:
            return float(self.exposure_us)
        elif prop_id == cv2.CAP_PROP_GAIN:
            return float(self.gain_percent)
        return 0.0

    def set(self, prop_id, value):
        import cv2
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            self._target_w = int(value)
            if hasattr(self, '_target_h') and self._target_h:
                self.set_resolution(self._target_w, self._target_h)
            return True
        elif prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            self._target_h = int(value)
            if hasattr(self, '_target_w') and self._target_w:
                self.set_resolution(self._target_w, self._target_h)
            return True
        elif prop_id == cv2.CAP_PROP_EXPOSURE:
            return self.set_exposure_time_us(int(value))
        elif prop_id == cv2.CAP_PROP_GAIN:
            return self.set_gain_percent(int(value))
        return True

    # Hardware Control Methods
    def set_exposure_time_us(self, us):
        us = max(100, min(10000000, int(us)))
        self.exposure_us = us
        dll = _find_and_load_dll()
        if dll and self.handle:
            exp_fn = getattr(dll, 'Miicam_put_ExpoTime', None) or getattr(dll, 'Toupcam_put_ExpoTime', None)
            if exp_fn:
                try:
                    exp_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    exp_fn(self.handle, ctypes.c_uint(us))
                    return True
                except Exception as e:
                    print(f"⚠️ Ошибка установки выдержки: {e}")
        return False

    def set_auto_exposure(self, enabled):
        self.auto_exposure = bool(enabled)
        dll = _find_and_load_dll()
        if dll and self.handle:
            ae_fn = getattr(dll, 'Miicam_put_AutoExpoEnable', None) or getattr(dll, 'Toupcam_put_AutoExpoEnable', None)
            if ae_fn:
                try:
                    ae_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    ae_fn(self.handle, ctypes.c_int(1 if enabled else 0))
                    if enabled:
                        # Enable 50Hz Anti-flicker and bound exposure to max 33ms (30 FPS) to prevent lag
                        self.set_anti_flicker(1)
                        max_fn = getattr(dll, 'Miicam_put_MaxAutoExpoTimeAGain', None) or getattr(dll, 'Toupcam_put_MaxAutoExpoTimeAGain', None)
                        if max_fn:
                            try:
                                max_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ushort]
                                max_fn(self.handle, ctypes.c_uint(33000), ctypes.c_ushort(800))
                            except Exception:
                                pass
                    return True
                except Exception as e:
                    print(f"⚠️ Ошибка автоэкспозиции: {e}")
        return False

    def auto_calibrate_exposure_once(self, target_brightness=120, max_expo_us=33000, wait_seconds=0.7):
        """
        One-touch auto exposure calibration capped at 30/60 FPS:
        Restricts max exposure to 33ms (30 FPS) so the video framerate never drops or lags,
        while letting hardware analog gain (up to 800%) compensate for room light level.
        """
        dll = _find_and_load_dll()
        if not dll or not self.handle:
            return False

        try:
            # 1. Enable 50Hz anti-flicker
            self.set_anti_flicker(1)

            # 2. Strict FPS cap: Max auto-exposure = 33ms (30 FPS), Max Gain = 800%
            max_fn = getattr(dll, 'Miicam_put_MaxAutoExpoTimeAGain', None) or getattr(dll, 'Toupcam_put_MaxAutoExpoTimeAGain', None)
            if max_fn:
                try:
                    max_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ushort]
                    max_fn(self.handle, ctypes.c_uint(int(max_expo_us)), ctypes.c_ushort(800))
                except Exception:
                    pass

            # 3. Enable Auto-Exposure temporarily
            set_ae_fn = getattr(dll, 'Miicam_put_AutoExpoEnable', None) or getattr(dll, 'Toupcam_put_AutoExpoEnable', None)
            if set_ae_fn:
                set_ae_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                set_ae_fn(self.handle, ctypes.c_int(1))
            
            set_aet_fn = getattr(dll, 'Miicam_put_AutoExpoTarget', None) or getattr(dll, 'Toupcam_put_AutoExpoTarget', None)
            if set_aet_fn:
                set_aet_fn.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                set_aet_fn(self.handle, ctypes.c_ushort(int(target_brightness)))

            # 4. Wait for ISP feedback loop to settle
            time.sleep(wait_seconds)

            # 5. Lock Auto-Exposure OFF (fix exposure and gain)
            if set_ae_fn:
                set_ae_fn(self.handle, ctypes.c_int(0))
            self.auto_exposure = False

            # 6. Read converged hardware values
            self._sync_hardware_settings()

            # 7. Safety clamp: If exposure is still > 35ms, clamp it to 33ms and boost gain proportionally
            if self.exposure_us > 35000:
                ratio = float(self.exposure_us) / 33000.0
                new_gain = min(1000, max(100, int(self.gain_percent * ratio)))
                self.set_exposure_time_us(33000)
                self.set_gain_percent(new_gain)
                self._sync_hardware_settings()

            print(f"✓ Выполнена автонастройка и фиксация экспозиции: Выдержка={self.exposure_us/1000.0:.1f} мс, Gain={self.gain_percent}% (FPS зафиксирован: 30+ FPS)")
            return True
        except Exception as e:
            print(f"⚠️ Ошибка автонастройки экспозиции: {e}")
            return False

    def set_gain_percent(self, gain):
        gain = max(100, min(1000, int(gain)))
        self.gain_percent = gain
        dll = _find_and_load_dll()
        if dll and self.handle:
            gain_fn = getattr(dll, 'Miicam_put_ExpoAGain', None) or getattr(dll, 'Toupcam_put_ExpoAGain', None)
            if gain_fn:
                try:
                    gain_fn.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                    gain_fn(self.handle, ctypes.c_ushort(gain))
                    return True
                except Exception as e:
                    print(f"⚠️ Ошибка установки усиления: {e}")
        return False

    def trigger_awb_once(self):
        """Execute one-push auto white balance and synchronize resulting parameters."""
        dll = _find_and_load_dll()
        if dll and self.handle:
            awb_fn = getattr(dll, 'Miicam_AwbOnce', None) or getattr(dll, 'Toupcam_AwbOnce', None) or getattr(dll, 'Toupcam_AwbOnePush', None)
            if awb_fn:
                try:
                    awb_fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                    awb_fn(self.handle, None, None)
                    time.sleep(0.06)
                    self._sync_hardware_settings()
                    print(f"✓ Выполнен Auto White Balance (AWB): Temp={self.wb_temp}, Tint={self.wb_tint}, WB_Gains=({self.wb_r}, {self.wb_g}, {self.wb_b})")
                    return True
                except Exception as e:
                    print(f"⚠️ Ошибка AWB: {e}")
        return False

    def set_temp_tint(self, temp, tint):
        temp = max(2000, min(15000, int(temp)))
        tint = max(200, min(2500, int(tint)))
        self.wb_temp = temp
        self.wb_tint = tint
        dll = _find_and_load_dll()
        if dll and self.handle:
            tt_fn = getattr(dll, 'Miicam_put_TempTint', None) or getattr(dll, 'Toupcam_put_TempTint', None)
            if tt_fn:
                try:
                    tt_fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                    tt_fn(self.handle, ctypes.c_int(temp), ctypes.c_int(tint))
                    return True
                except Exception:
                    pass
        return False

    def set_white_balance_gains(self, r_gain, g_gain, b_gain):
        dll = _find_and_load_dll()
        if dll and self.handle:
            wbg_fn = getattr(dll, 'Miicam_put_WhiteBalanceGain', None) or getattr(dll, 'Toupcam_put_WhiteBalanceGain', None)
            if wbg_fn:
                try:
                    arr = (ctypes.c_int * 3)(int(r_gain), int(g_gain), int(b_gain))
                    wbg_fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                    wbg_fn(self.handle, arr)
                    self.wb_r, self.wb_g, self.wb_b = int(r_gain), int(g_gain), int(b_gain)
                    return True
                except Exception as e:
                    print(f"⚠️ Ошибка баланса белого: {e}")
        return False

    def set_gamma(self, gamma):
        gamma = max(20, min(180, int(gamma)))
        self.gamma = gamma
        dll = _find_and_load_dll()
        if dll and self.handle:
            gamma_fn = getattr(dll, 'Miicam_put_Gamma', None) or getattr(dll, 'Toupcam_put_Gamma', None)
            if gamma_fn:
                try:
                    gamma_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    gamma_fn(self.handle, ctypes.c_int(gamma))
                    return True
                except Exception:
                    pass
        return False

    def set_contrast(self, contrast):
        contrast = max(-100, min(100, int(contrast)))
        self.contrast = contrast
        dll = _find_and_load_dll()
        if dll and self.handle:
            c_fn = getattr(dll, 'Miicam_put_Contrast', None) or getattr(dll, 'Toupcam_put_Contrast', None)
            if c_fn:
                try:
                    c_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    c_fn(self.handle, ctypes.c_int(contrast))
                    return True
                except Exception:
                    pass
        return False

    def set_brightness(self, brightness):
        brightness = max(-64, min(64, int(brightness)))
        self.brightness = brightness
        dll = _find_and_load_dll()
        if dll and self.handle:
            b_fn = getattr(dll, 'Miicam_put_Brightness', None) or getattr(dll, 'Toupcam_put_Brightness', None)
            if b_fn:
                try:
                    b_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    b_fn(self.handle, ctypes.c_int(brightness))
                    return True
                except Exception:
                    pass
        return False

    def set_saturation(self, saturation):
        saturation = max(0, min(255, int(saturation)))
        self.saturation = saturation
        dll = _find_and_load_dll()
        if dll and self.handle:
            s_fn = getattr(dll, 'Miicam_put_Saturation', None) or getattr(dll, 'Toupcam_put_Saturation', None)
            if s_fn:
                try:
                    s_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    s_fn(self.handle, ctypes.c_int(saturation))
                    return True
                except Exception:
                    pass
        return False

    def set_hue(self, hue):
        hue = max(-180, min(180, int(hue)))
        self.hue = hue
        dll = _find_and_load_dll()
        if dll and self.handle:
            h_fn = getattr(dll, 'Miicam_put_Hue', None) or getattr(dll, 'Toupcam_put_Hue', None)
            if h_fn:
                try:
                    h_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    h_fn(self.handle, ctypes.c_int(hue))
                    return True
                except Exception:
                    pass
        return False

    def set_speed(self, speed):
        speed = max(0, min(2, int(speed)))
        self.speed = speed
        dll = _find_and_load_dll()
        if dll and self.handle:
            sp_fn = getattr(dll, 'Miicam_put_Speed', None) or getattr(dll, 'Toupcam_put_Speed', None)
            if sp_fn:
                try:
                    sp_fn.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                    sp_fn(self.handle, ctypes.c_ushort(speed))
                    return True
                except Exception:
                    pass
        return False

    def set_flips(self, h_flip, v_flip):
        self.h_flip = bool(h_flip)
        self.v_flip = bool(v_flip)
        dll = _find_and_load_dll()
        if dll and self.handle:
            try:
                hf_fn = getattr(dll, 'Miicam_put_HFlip', None) or getattr(dll, 'Toupcam_put_HFlip', None)
                if hf_fn:
                    hf_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    hf_fn(self.handle, 1 if h_flip else 0)
                vf_fn = getattr(dll, 'Miicam_put_VFlip', None) or getattr(dll, 'Toupcam_put_VFlip', None)
                if vf_fn:
                    vf_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    vf_fn(self.handle, 1 if v_flip else 0)
            except Exception:
                pass

    def set_anti_flicker(self, hz_mode):
        # 0: 60Hz, 1: 50Hz, 2: DC
        self.anti_flicker = int(hz_mode)
        dll = _find_and_load_dll()
        if dll and self.handle:
            hz_fn = getattr(dll, 'Miicam_put_HZ', None) or getattr(dll, 'Toupcam_put_HZ', None)
            if hz_fn:
                try:
                    hz_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    hz_fn(self.handle, ctypes.c_int(self.anti_flicker))
                except Exception:
                    pass

    def set_chrome(self, enable_color=True):
        """Set color mode: enable_color=True (0 => Color mode), enable_color=False (1 => Monochromatic mode)."""
        self.chrome = bool(enable_color)
        dll = _find_and_load_dll()
        if dll and self.handle:
            ch_fn = getattr(dll, 'Miicam_put_Chrome', None) or getattr(dll, 'Toupcam_put_Chrome', None)
            if ch_fn:
                try:
                    ch_fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    ch_fn(self.handle, 0 if enable_color else 1)
                    return True
                except Exception:
                    pass
        return False

    def put_option(self, option_id, val):
        """Set a low-level option using an ID from the bundled SDK header."""
        if not self.handle:
            return False
        dll = _find_and_load_dll()
        if dll:
            put_opt_fn = getattr(dll, 'Miicam_put_Option', None) or getattr(dll, 'Toupcam_put_Option', None)
            if put_opt_fn:
                try:
                    put_opt_fn.restype = ctypes.c_int
                    put_opt_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
                    return put_opt_fn(self.handle, ctypes.c_uint(option_id), ctypes.c_int(val)) >= 0
                except Exception:
                    pass
        return False

    def get_option(self, option_id):
        """Get low-level hardware option."""
        if not self.handle:
            return None
        dll = _find_and_load_dll()
        if dll:
            get_opt_fn = getattr(dll, 'Miicam_get_Option', None) or getattr(dll, 'Toupcam_get_Option', None)
            if get_opt_fn:
                try:
                    val = ctypes.c_int()
                    get_opt_fn.restype = ctypes.c_int
                    get_opt_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
                    if get_opt_fn(self.handle, ctypes.c_uint(option_id), ctypes.byref(val)) >= 0:
                        return val.value
                except Exception:
                    pass
        return None

    def set_binning(self, bin_mode=1):
        """1 = 1x1 standard, 2 = 2x2 hardware binning (ultra-high FPS / max light sensitivity)."""
        self.binning_mode = int(bin_mode)
        return self.put_option(MIICAM_OPTION_BINNING, int(bin_mode))

    def set_frame_preload(self, enable=True):
        """Compatibility setting. The current SDK has no FRAME_PRELOAD option.

        Do not write a guessed option number: doing so can change an unrelated
        camera register. The SDK itself manages the USB frame queues.
        """
        self.frame_preload = bool(enable)
        return True

    def set_thread_priority(self, priority=2):
        """0 = Normal, 1 = High, 2 = Real-Time/Critical."""
        self.thread_priority = int(priority)
        return self.put_option(MIICAM_OPTION_THREAD_PRIORITY, int(priority))


    # ------------------------------------------------------------------
    # ISP-узлы и режим «Чистый кадр»
    # ------------------------------------------------------------------
    def _set_isp_option(self, option_id, value, label):
        """Отправить опцию один раз (повторно только при смене значения) и записать результат в отчёт."""
        value = int(value)
        if self._isp_applied.get(option_id) == value:
            return
        ok = bool(self.put_option(option_id, value))
        readback = self.get_option(option_id) if ok else None
        self._isp_applied[option_id] = value
        self._isp_report[label] = {'value': value, 'ok': ok, 'readback': readback}

    def apply_isp_settings(self, cfg):
        """Применить узлы ISP из словаря настроек. Ключи, которых нет в cfg, не трогаются."""
        if 'miicam_color_matrix' in cfg:
            self._set_isp_option(MIICAM_OPTION_COLORMATIX, bool(cfg['miicam_color_matrix']), 'ColorMatrix')
        if 'miicam_wb_gain_enable' in cfg:
            self._set_isp_option(MIICAM_OPTION_WBGAIN, bool(cfg['miicam_wb_gain_enable']), 'WBGain')
        if 'miicam_tone_curve' in cfg:
            self._set_isp_option(MIICAM_OPTION_CURVE, int(cfg['miicam_tone_curve']), 'ToneCurve')
        if 'miicam_linear_tone' in cfg:
            self._set_isp_option(MIICAM_OPTION_LINEAR, int(cfg['miicam_linear_tone']), 'LinearTone')
        if 'miicam_sharpening' in cfg:
            strength = max(0, min(500, int(cfg['miicam_sharpening'])))
            # strength == 0 -> выключено; иначе (threshold<<24)|(radius<<16)|strength, radius=2
            self._set_isp_option(MIICAM_OPTION_SHARPENING, 0 if strength == 0 else (2 << 16) | strength, 'Sharpening')
        if 'miicam_demosaic' in cfg:
            self._set_isp_option(MIICAM_OPTION_DEMOSAIC, int(cfg['miicam_demosaic']), 'Demosaic')
        if cfg.get('miicam_clean_frame'):
            # В режиме «Чистый кадр» баланс белого не должен подстраиваться сам ни при каких условиях.
            self._set_isp_option(MIICAM_OPTION_AWB_CONTINUOUS, 0, 'AWBContinuous')

    def get_clean_frame_report(self):
        """Что реально приняла камера и что может испортить воспроизводимость кадра."""
        warnings = []
        if self.auto_exposure:
            warnings.append("Автоэкспозиция включена: яркость кадра будет плавать.")
        if self.gain_percent > 100:
            warnings.append(f"Усиление {self.gain_percent}% > 100%: лишний шум. Лучше менять свет или выдержку.")
        flicker = exposure_flicker_warning(self.exposure_us, self.anti_flicker)
        if flicker:
            warnings.append(flicker)
        options = dict(self._isp_report)
        failed = [name for name, r in options.items() if not r['ok']]
        if failed:
            warnings.append("Камера отклонила опции: " + ", ".join(failed) + " (на этой модели не поддерживаются).")
        return {'options': options, 'failed': failed, 'warnings': warnings}

    def apply_settings_dict(self, cfg):
        """Batch apply settings dictionary to the camera hardware without overwriting calibrated AWB."""
        if not isinstance(cfg, dict):
            return
        if 'miicam_auto_exposure' in cfg:
            self.set_auto_exposure(bool(cfg['miicam_auto_exposure']))
        if 'miicam_exposure_us' in cfg:
            self.set_exposure_time_us(int(cfg['miicam_exposure_us']))
        if 'miicam_gain' in cfg:
            self.set_gain_percent(int(cfg['miicam_gain']))
        if 'miicam_gamma' in cfg:
            self.set_gamma(int(cfg['miicam_gamma']))
        if 'miicam_contrast' in cfg:
            self.set_contrast(int(cfg['miicam_contrast']))
        if 'miicam_brightness' in cfg:
            self.set_brightness(int(cfg['miicam_brightness']))
        if 'miicam_saturation' in cfg:
            self.set_saturation(int(cfg['miicam_saturation']))
        if 'miicam_hue' in cfg:
            self.set_hue(int(cfg['miicam_hue']))
        if 'miicam_speed' in cfg:
            self.set_speed(int(cfg['miicam_speed']))
        if 'miicam_binning' in cfg:
            self.set_binning(int(cfg['miicam_binning']))
        if 'miicam_frame_preload' in cfg:
            self.set_frame_preload(bool(cfg['miicam_frame_preload']))
        if 'miicam_thread_priority' in cfg:
            self.set_thread_priority(int(cfg['miicam_thread_priority']))
        if 'miicam_h_flip' in cfg or 'miicam_v_flip' in cfg:
            self.set_flips(bool(cfg.get('miicam_h_flip', False)), bool(cfg.get('miicam_v_flip', False)))
        if 'miicam_anti_flicker' in cfg:
            self.set_anti_flicker(int(cfg.get('miicam_anti_flicker', 1)))

        self.apply_isp_settings(cfg)

        # White balance handling:
        # Only apply manual WB channel gain offsets if explicitly non-zero.
        # NEVER send [0,0,0] because that resets/destroys the hardware AWB matrix!
        wb_r = int(cfg.get('miicam_wb_r', 0))
        wb_g = int(cfg.get('miicam_wb_g', 0))
        wb_b = int(cfg.get('miicam_wb_b', 0))
        if wb_r != 0 or wb_g != 0 or wb_b != 0:
            if wb_r != self.wb_r or wb_g != self.wb_g or wb_b != self.wb_b:
                self.set_white_balance_gains(wb_r, wb_g, wb_b)

        # Color Temperature & Tint:
        # Only update if user explicitly changed Temp/Tint slider
        if 'miicam_temp' in cfg and 'miicam_tint' in cfg:
            t = int(cfg['miicam_temp'])
            tint = int(cfg['miicam_tint'])
            if self.wb_temp > 0 and (t != self.wb_temp or tint != self.wb_tint) and (t != 6500 or tint != 1000):
                self.set_temp_tint(t, tint)

        self.set_chrome(True)
