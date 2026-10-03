"""
MiiCam / ToupCam SDK Wrapper for Elutek SARA RGB.
Provides high-performance hardware access to MiiCam USB/CMOS camera detectors via miicam.dll / toupcam.dll.
Compatible with OpenCV VideoCapture interface.
"""

import sys
import os
import ctypes
import threading
import time
import numpy as np

# MiiCam constants
MIICAM_MAX = 128
MIICAM_FLAG_CMOS = 0x00000001
MIICAM_FLAG_CCD_PROGRESSIVE = 0x00000002
MIICAM_FLAG_ROI_HARDWARE = 0x00000008
MIICAM_FLAG_MONO = 0x00000010
MIICAM_FLAG_BINSKIP_SUPPORTED = 0x00000020
MIICAM_FLAG_USB30 = 0x00000040

MIICAM_EVENT_EXPOSURE = 0x0001
MIICAM_EVENT_TEMPTINT = 0x0002
MIICAM_EVENT_IMAGE = 0x0004
MIICAM_EVENT_STILLIMAGE = 0x0005
MIICAM_EVENT_WBGAIN = 0x0006
MIICAM_EVENT_TRIGGERFAIL = 0x0007
MIICAM_EVENT_BLACK = 0x0008
MIICAM_EVENT_FFC = 0x0009
MIICAM_EVENT_DFC = 0x000a
MIICAM_EVENT_ROI = 0x000b
MIICAM_EVENT_LEVELRANGE = 0x000c
MIICAM_EVENT_AUTOEXPO_ONCE = 0x000d
MIICAM_EVENT_AWB_ONCE = 0x000e
MIICAM_EVENT_ERROR = 0x0080
MIICAM_EVENT_DISCONNECTED = 0x0081
MIICAM_EVENT_NOFRAMETIMEOUT = 0x0082
MIICAM_EVENT_AETIMEOUT = 0x0083
MIICAM_EVENT_FACTORY = 0x8001

MIICAM_OPTION_NOFRAME_TIMEOUT = 0x01
MIICAM_OPTION_THREAD_PRIORITY = 0x02
MIICAM_OPTION_RAW = 0x04
MIICAM_OPTION_HISTOGRAM = 0x05
MIICAM_OPTION_BITDEPTH = 0x06
MIICAM_OPTION_FAN = 0x07
MIICAM_OPTION_TEC = 0x08
MIICAM_OPTION_LINEAR = 0x09
MIICAM_OPTION_CURVE = 0x0a
MIICAM_OPTION_TRIGGER = 0x0b
MIICAM_OPTION_RGB = 0x0c
MIICAM_OPTION_COLORMATIX = 0x0d
MIICAM_OPTION_WBGAIN = 0x0e
MIICAM_OPTION_TECTARGET = 0x0f
MIICAM_OPTION_AUTOEXP_POLICY = 0x10
MIICAM_OPTION_AGAIN = 0x11
MIICAM_OPTION_FRAME_PRELOAD = 0x12
MIICAM_OPTION_BINNING = 0x13
MIICAM_OPTION_ROTATE = 0x14
MIICAM_OPTION_CG = 0x15
MIICAM_OPTION_PIXEL_FORMAT = 0x16
MIICAM_OPTION_FFC = 0x17
MIICAM_OPTION_DFC = 0x18
MIICAM_OPTION_SHARPENING = 0x19
MIICAM_OPTION_FACTORY = 0x1a
MIICAM_OPTION_TEC_VOLTAGE = 0x1b
MIICAM_OPTION_TEC_VOLTAGE_MAX = 0x1c
MIICAM_OPTION_DEVICE_RESET = 0x1d
MIICAM_OPTION_UPSIDE_DOWN = 0x1e


class MiicamResolution(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint),
        ('height', ctypes.c_uint)
    ]


class MiicamModelV2(ctypes.Structure):
    _fields_ = [
        ('name', ctypes.c_wchar_p),
        ('flag', ctypes.c_ulonglong),
        ('maxspeed', ctypes.c_uint),
        ('preview', ctypes.c_uint),
        ('still', ctypes.c_uint),
        ('maxfanspeed', ctypes.c_uint),
        ('ioctarget', ctypes.c_uint),
        ('res', MiicamResolution * 16)
    ]


class MiicamDeviceV2(ctypes.Structure):
    _fields_ = [
        ('displayname', ctypes.c_wchar * 64),
        ('id', ctypes.c_wchar * 64),
        ('model', ctypes.POINTER(MiicamModelV2))
    ]


class MiicamFrameInfoV2(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint),
        ('height', ctypes.c_uint),
        ('flag', ctypes.c_uint),
        ('seq', ctypes.c_uint),
        ('timestamp', ctypes.c_ulonglong)
    ]


# Global DLL handle and singleton tracker
_miicam_dll = None
_miicam_loaded = False
_miicam_load_error = None
_active_miicam_instance = None


def _find_and_load_dll():
    global _miicam_dll, _miicam_loaded, _miicam_load_error
    if _miicam_loaded:
        return _miicam_dll

    dll_names = [
        'miicam.dll', 'toupcam.dll', 'libmiicam.so', 'libmiicam.dylib',
        'libtoupcam.so', 'libtoupcam.dylib'
    ]

    # Search folders
    search_dirs = [
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'drivers')),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'drivers')),
    ]

    for p in sys.path:
        if os.path.isdir(p) and p not in search_dirs:
            search_dirs.append(p)

    for d in search_dirs:
        for name in dll_names:
            full_path = os.path.join(d, name)
            if os.path.isfile(full_path):
                try:
                    if sys.platform == 'win32':
                        _miicam_dll = ctypes.windll.LoadLibrary(full_path)
                    else:
                        _miicam_dll = ctypes.cdll.LoadLibrary(full_path)
                    _miicam_loaded = True
                    _miicam_load_error = None
                    print(f"✓ Успешно загружена библиотека RGB-детектора: {full_path}")
                    return _miicam_dll
                except Exception as e:
                    _miicam_load_error = str(e)
                    print(f"⚠️ Ошибка загрузки {full_path}: {e}")

    for name in dll_names:
        try:
            if sys.platform == 'win32':
                _miicam_dll = ctypes.windll.LoadLibrary(name)
            else:
                _miicam_dll = ctypes.cdll.LoadLibrary(name)
            _miicam_loaded = True
            _miicam_load_error = None
            print(f"✓ Успешно загружена системная библиотека RGB-детектора: {name}")
            return _miicam_dll
        except Exception:
            pass

    _miicam_load_error = "Файл miicam.dll / toupcam.dll не найден."
    return None


def is_miicam_available():
    """Check if MiiCam DLL is loaded and functional."""
    dll = _find_and_load_dll()
    return dll is not None


def enumerate_miicam_devices():
    """Returns a list of available MiiCam / RGB-detector devices."""
    dll = _find_and_load_dll()
    if not dll:
        return []

    try:
        if hasattr(dll, 'Miicam_EnumV2'):
            arr = (MiicamDeviceV2 * MIICAM_MAX)()
            dll.Miicam_EnumV2.restype = ctypes.c_uint
            dll.Miicam_EnumV2.argtypes = [ctypes.POINTER(MiicamDeviceV2)]
            cnt = dll.Miicam_EnumV2(arr)
            devices = []
            for i in range(cnt):
                dev = arr[i]
                dname = dev.displayname or f"MiiCam #{i}"
                cid = dev.id or str(i)
                w, h = 2048, 1536
                res_list = []
                try:
                    if dev.model and dev.model.contents:
                        m = dev.model.contents
                        if m.preview > 0:
                            for r_idx in range(m.preview):
                                rw = m.res[r_idx].width
                                rh = m.res[r_idx].height
                                if rw > 0 and rh > 0:
                                    res_list.append((rw, rh))
                        if res_list:
                            w, h = res_list[0]
                except Exception:
                    pass
                devices.append({
                    'index': i,
                    'id': cid,
                    'displayname': dname,
                    'width': w,
                    'height': h,
                    'resolutions': res_list,
                    'source': f"miicam:{i}"
                })
            return devices
    except Exception as e:
        print(f"⚠️ Ошибка перечисления устройств MiiCam: {e}")

    return []


# Callback prototype
if sys.platform == 'win32':
    CALLBACK_TYPE = ctypes.WINFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)
else:
    CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)


class MiiCamCapture:
    """
    High-performance OpenCV VideoCapture compatible wrapper for MiiCam cameras.
    """
    def __init__(self, source="miicam:0", width=None, height=None):
        global _active_miicam_instance
        # Safely release previous instance to avoid ERROR_BUSY (-2147024726)
        if _active_miicam_instance is not None and _active_miicam_instance is not self:
            try:
                _active_miicam_instance.release()
            except Exception:
                pass
            _active_miicam_instance = None

        self.source = str(source)
        self.handle = None
        self._opened = False
        self._pulling = False
        self._lock = threading.RLock()
        self._latest_frame = None
        self._frame_ready_event = threading.Event()
        self._width = width or 2048
        self._height = height or 1536
        self._req_w = width
        self._req_h = height
        self._res_index = 0
        self._buffer = None
        self._callback_ptr = None
        self._is_stopped = False
        self._frame_count = 0

        # Optical settings cache
        self.exposure_us = 20000  # 20 ms
        self.auto_exposure = False
        self.gain_percent = 100
        self.wb_r = 0
        self.wb_g = 0
        self.wb_b = 0
        self.wb_temp = 6500
        self.wb_tint = 1000
        self.gamma = 100
        self.contrast = 0
        self.brightness = 0
        self.saturation = 128
        self.hue = 0
        self.speed = 2          # High speed for smooth FPS
        self.binning_mode = 1   # 1: 1x1, 2: 2x2 binning
        self.frame_preload = True
        self.thread_priority = 2
        self.h_flip = False
        self.v_flip = False
        self.anti_flicker = 1   # 0: 60Hz, 1: 50Hz, 2: DC
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

            dll.Miicam_Open.restype = ctypes.c_void_p
            dll.Miicam_Open.argtypes = [ctypes.c_wchar_p]

            h = None
            for attempt in range(4):
                h = dll.Miicam_Open(cam_id)
                if h:
                    break
                time.sleep(0.12)

            if not h:
                print(f"❌ Ошибка открытия камеры MiiCam: {cam_id}")
                return False

            self.handle = h
            self._opened = True

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
            if hasattr(dll, 'Miicam_put_eSize'):
                dll.Miicam_put_eSize.restype = ctypes.c_int
                dll.Miicam_put_eSize.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                dll.Miicam_put_eSize(h, ctypes.c_uint(best_idx))

            # Query resulting dimensions
            w_c = ctypes.c_int()
            h_c = ctypes.c_int()
            if hasattr(dll, 'Miicam_get_Size'):
                dll.Miicam_get_Size.restype = ctypes.c_int
                dll.Miicam_get_Size.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                dll.Miicam_get_Size(h, ctypes.byref(w_c), ctypes.byref(h_c))
                if w_c.value > 0 and h_c.value > 0:
                    self._width = w_c.value
                    self._height = h_c.value
            elif best_idx < len(resolutions):
                self._width, self._height = resolutions[best_idx]

            # Set USB transfer speed to max for high FPS
            if hasattr(dll, 'Miicam_put_Speed'):
                dll.Miicam_put_Speed.restype = ctypes.c_int
                dll.Miicam_put_Speed.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                dll.Miicam_put_Speed(h, ctypes.c_ushort(2))

            # Enable hardware high throughput & low latency options:
            if hasattr(dll, 'Miicam_put_Option'):
                dll.Miicam_put_Option.restype = ctypes.c_int
                dll.Miicam_put_Option.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
                # High thread priority (2 = real-time/critical)
                dll.Miicam_put_Option(h, ctypes.c_uint(MIICAM_OPTION_THREAD_PRIORITY), ctypes.c_int(2))
                # DMA frame preloading for high FPS
                dll.Miicam_put_Option(h, ctypes.c_uint(MIICAM_OPTION_FRAME_PRELOAD), ctypes.c_int(1))

            # Allocate frame buffer (24-bit BGR aligned to 4 bytes per row)
            row_pitch = ((self._width * 24 + 31) // 32) * 4
            self._buf_size = row_pitch * self._height
            self._buffer = (ctypes.c_ubyte * self._buf_size)()

            # Setup pull callback
            def _event_callback(n_event, ctx):
                if n_event == MIICAM_EVENT_IMAGE:
                    self._pull_latest_frame()

            self._callback_ptr = CALLBACK_TYPE(_event_callback)

            if hasattr(dll, 'Miicam_StartPullModeWithCallback'):
                dll.Miicam_StartPullModeWithCallback.restype = ctypes.c_int
                dll.Miicam_StartPullModeWithCallback.argtypes = [ctypes.c_void_p, CALLBACK_TYPE, ctypes.c_void_p]
                ret = dll.Miicam_StartPullModeWithCallback(h, self._callback_ptr, None)
                if ret >= 0:
                    self._pulling = True
                else:
                    print(f"⚠️ StartPullModeWithCallback status: {ret}")

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
        if not dll or not hasattr(dll, 'Miicam_PullImageV2'):
            return

        try:
            with self._lock:
                if not self.handle or not self._opened or self._is_stopped or not self._pulling:
                    return

                # Ensure buffer is allocated
                w = self._width if self._width > 0 else 640
                h = self._height if self._height > 0 else 480
                row_pitch = ((w * 24 + 31) // 32) * 4
                needed_buf = max(row_pitch * h, 1920 * 1080 * 4)
                if self._buffer is None or len(self._buffer) < needed_buf:
                    self._buf_size = needed_buf
                    self._buffer = (ctypes.c_ubyte * needed_buf)()

                info = MiicamFrameInfoV2()
                dll.Miicam_PullImageV2.restype = ctypes.c_int
                dll.Miicam_PullImageV2.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.POINTER(MiicamFrameInfoV2)
                ]
                res = dll.Miicam_PullImageV2(
                    self.handle,
                    ctypes.cast(self._buffer, ctypes.c_void_p),
                    24,
                    ctypes.byref(info)
                )
                if res >= 0 and info.width > 0 and info.height > 0:
                    w, h = info.width, info.height
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

                        self._latest_frame = frame.copy()
                        self._width = w
                        self._height = h
                        self._frame_count += 1
                        self._fps_count += 1
                        now = time.time()
                        dt = now - self._fps_start
                        if dt >= 0.5:
                            self.fps = round(self._fps_count / dt, 1)
                            self._fps_count = 0
                            self._fps_start = now
                        self._frame_ready_event.set()
        except Exception:
            pass

    def _sync_hardware_settings(self):
        """Query and cache current camera parameters."""
        dll = _find_and_load_dll()
        if not dll or not self.handle:
            return

        try:
            if hasattr(dll, 'Miicam_get_ExpoTime'):
                t_c = ctypes.c_uint()
                dll.Miicam_get_ExpoTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
                if dll.Miicam_get_ExpoTime(self.handle, ctypes.byref(t_c)) >= 0:
                    self.exposure_us = t_c.value

            if hasattr(dll, 'Miicam_get_AutoExpoEnable'):
                ae_c = ctypes.c_int()
                dll.Miicam_get_AutoExpoEnable.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_AutoExpoEnable(self.handle, ctypes.byref(ae_c)) >= 0:
                    self.auto_exposure = bool(ae_c.value)

            if hasattr(dll, 'Miicam_get_ExpoAGain'):
                g_c = ctypes.c_ushort()
                dll.Miicam_get_ExpoAGain.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort)]
                if dll.Miicam_get_ExpoAGain(self.handle, ctypes.byref(g_c)) >= 0:
                    self.gain_percent = int(g_c.value)

            if hasattr(dll, 'Miicam_get_Gamma'):
                val = ctypes.c_int()
                dll.Miicam_get_Gamma.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_Gamma(self.handle, ctypes.byref(val)) >= 0:
                    self.gamma = val.value

            if hasattr(dll, 'Miicam_get_Contrast'):
                val = ctypes.c_int()
                dll.Miicam_get_Contrast.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_Contrast(self.handle, ctypes.byref(val)) >= 0:
                    self.contrast = val.value

            if hasattr(dll, 'Miicam_get_Brightness'):
                val = ctypes.c_int()
                dll.Miicam_get_Brightness.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_Brightness(self.handle, ctypes.byref(val)) >= 0:
                    self.brightness = val.value

            if hasattr(dll, 'Miicam_get_Hue'):
                val = ctypes.c_int()
                dll.Miicam_get_Hue.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_Hue(self.handle, ctypes.byref(val)) >= 0:
                    self.hue = val.value

            if hasattr(dll, 'Miicam_get_Saturation'):
                val = ctypes.c_int()
                dll.Miicam_get_Saturation.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_Saturation(self.handle, ctypes.byref(val)) >= 0:
                    self.saturation = val.value

            if hasattr(dll, 'Miicam_get_TempTint'):
                p_temp = ctypes.c_int()
                p_tint = ctypes.c_int()
                dll.Miicam_get_TempTint.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_TempTint(self.handle, ctypes.byref(p_temp), ctypes.byref(p_tint)) >= 0:
                    self.wb_temp = p_temp.value
                    self.wb_tint = p_tint.value

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
            if hasattr(dll, 'Miicam_get_ResolutionNumber') and hasattr(dll, 'Miicam_get_Resolution'):
                dll.Miicam_get_ResolutionNumber.restype = ctypes.c_int
                dll.Miicam_get_ResolutionNumber.argtypes = [ctypes.c_void_p]
                cnt = dll.Miicam_get_ResolutionNumber(self.handle)

                dll.Miicam_get_Resolution.restype = ctypes.c_int
                dll.Miicam_get_Resolution.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint,
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
                ]
                for i in range(cnt):
                    w_c = ctypes.c_int()
                    h_c = ctypes.c_int()
                    dll.Miicam_get_Resolution(self.handle, ctypes.c_uint(i), ctypes.byref(w_c), ctypes.byref(h_c))
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
                if hasattr(dll, 'Miicam_Stop'):
                    dll.Miicam_Stop(self.handle)
                self._pulling = False
                self._frame_ready_event.clear()
                time.sleep(0.04)

                # 2. Set new resolution index
                if hasattr(dll, 'Miicam_put_eSize'):
                    dll.Miicam_put_eSize.restype = ctypes.c_int
                    dll.Miicam_put_eSize.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    dll.Miicam_put_eSize(self.handle, ctypes.c_uint(best_idx))

                # Query actual resulting dimensions
                w_c = ctypes.c_int()
                h_c = ctypes.c_int()
                if hasattr(dll, 'Miicam_get_Size'):
                    dll.Miicam_get_Size.restype = ctypes.c_int
                    dll.Miicam_get_Size.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
                    if dll.Miicam_get_Size(self.handle, ctypes.byref(w_c), ctypes.byref(h_c)) >= 0:
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
                if hasattr(dll, 'Miicam_StartPullModeWithCallback') and self._callback_ptr:
                    dll.Miicam_StartPullModeWithCallback.restype = ctypes.c_int
                    dll.Miicam_StartPullModeWithCallback.argtypes = [ctypes.c_void_p, CALLBACK_TYPE, ctypes.c_void_p]
                    ret = dll.Miicam_StartPullModeWithCallback(self.handle, self._callback_ptr, None)
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
        if not self.isOpened():
            return False, None

        if self._latest_frame is None:
            self._frame_ready_event.wait(timeout=0.04)

        with self._lock:
            if self._latest_frame is not None:
                return True, self._latest_frame.copy()

        return False, None

    def release(self):
        global _active_miicam_instance
        self._is_stopped = True
        self._opened = False
        self._pulling = False
        dll = _find_and_load_dll()
        if dll and self.handle:
            try:
                if hasattr(dll, 'Miicam_Stop'):
                    dll.Miicam_Stop(self.handle)
                time.sleep(0.04)
                if hasattr(dll, 'Miicam_Close'):
                    dll.Miicam_Close(self.handle)
                time.sleep(0.12)
            except Exception:
                pass
        self.handle = None
        self._latest_frame = None
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
        if dll and self.handle and hasattr(dll, 'Miicam_put_ExpoTime'):
            try:
                dll.Miicam_put_ExpoTime.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                dll.Miicam_put_ExpoTime(self.handle, ctypes.c_uint(us))
                return True
            except Exception as e:
                print(f"⚠️ Ошибка установки выдержки: {e}")
        return False

    def set_auto_exposure(self, enabled):
        self.auto_exposure = bool(enabled)
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_AutoExpoEnable'):
            try:
                dll.Miicam_put_AutoExpoEnable.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_AutoExpoEnable(self.handle, ctypes.c_int(1 if enabled else 0))
                return True
            except Exception as e:
                print(f"⚠️ Ошибка автоэкспозиции: {e}")
        return False

    def set_gain_percent(self, gain):
        gain = max(100, min(1000, int(gain)))
        self.gain_percent = gain
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_ExpoAGain'):
            try:
                dll.Miicam_put_ExpoAGain.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                dll.Miicam_put_ExpoAGain(self.handle, ctypes.c_ushort(gain))
                return True
            except Exception as e:
                print(f"⚠️ Ошибка установки усиления: {e}")
        return False

    def trigger_awb_once(self):
        """Execute one-push auto white balance."""
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_AwbOnce'):
            try:
                dll.Miicam_AwbOnce.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                dll.Miicam_AwbOnce(self.handle, None, None)
                print("✓ Выполнен Auto White Balance (AWB)")
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
        if dll and self.handle and hasattr(dll, 'Miicam_put_TempTint'):
            try:
                dll.Miicam_put_TempTint.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                dll.Miicam_put_TempTint(self.handle, ctypes.c_int(temp), ctypes.c_int(tint))
                return True
            except Exception:
                pass
        return False

    def set_white_balance_gains(self, r_gain, g_gain, b_gain):
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_WhiteBalanceGain'):
            try:
                arr = (ctypes.c_int * 3)(int(r_gain), int(g_gain), int(b_gain))
                dll.Miicam_put_WhiteBalanceGain.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                dll.Miicam_put_WhiteBalanceGain(self.handle, arr)
                self.wb_r, self.wb_g, self.wb_b = int(r_gain), int(g_gain), int(b_gain)
                return True
            except Exception as e:
                print(f"⚠️ Ошибка баланса белого: {e}")
        return False

    def set_gamma(self, gamma):
        gamma = max(20, min(180, int(gamma)))
        self.gamma = gamma
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_Gamma'):
            try:
                dll.Miicam_put_Gamma.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_Gamma(self.handle, ctypes.c_int(gamma))
                return True
            except Exception:
                pass
        return False

    def set_contrast(self, contrast):
        contrast = max(-100, min(100, int(contrast)))
        self.contrast = contrast
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_Contrast'):
            try:
                dll.Miicam_put_Contrast.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_Contrast(self.handle, ctypes.c_int(contrast))
                return True
            except Exception:
                pass
        return False

    def set_brightness(self, brightness):
        brightness = max(-64, min(64, int(brightness)))
        self.brightness = brightness
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_Brightness'):
            try:
                dll.Miicam_put_Brightness.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_Brightness(self.handle, ctypes.c_int(brightness))
                return True
            except Exception:
                pass
        return False

    def set_saturation(self, saturation):
        saturation = max(0, min(255, int(saturation)))
        self.saturation = saturation
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_Saturation'):
            try:
                dll.Miicam_put_Saturation.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_Saturation(self.handle, ctypes.c_int(saturation))
                return True
            except Exception:
                pass
        return False

    def set_hue(self, hue):
        hue = max(-180, min(180, int(hue)))
        self.hue = hue
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_Hue'):
            try:
                dll.Miicam_put_Hue.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_Hue(self.handle, ctypes.c_int(hue))
                return True
            except Exception:
                pass
        return False

    def set_speed(self, speed):
        speed = max(0, min(2, int(speed)))
        self.speed = speed
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_Speed'):
            try:
                dll.Miicam_put_Speed.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
                dll.Miicam_put_Speed(self.handle, ctypes.c_ushort(speed))
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
                if hasattr(dll, 'Miicam_put_HFlip'):
                    dll.Miicam_put_HFlip.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    dll.Miicam_put_HFlip(self.handle, 1 if h_flip else 0)
                if hasattr(dll, 'Miicam_put_VFlip'):
                    dll.Miicam_put_VFlip.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    dll.Miicam_put_VFlip(self.handle, 1 if v_flip else 0)
            except Exception:
                pass

    def set_anti_flicker(self, hz_mode):
        # 0: 60Hz, 1: 50Hz, 2: DC
        self.anti_flicker = int(hz_mode)
        dll = _find_and_load_dll()
        if dll and self.handle and hasattr(dll, 'Miicam_put_HZ'):
            try:
                dll.Miicam_put_HZ.argtypes = [ctypes.c_void_p, ctypes.c_int]
                dll.Miicam_put_HZ(self.handle, ctypes.c_int(self.anti_flicker))
            except Exception:
                pass

    def put_option(self, option_id, val):
        """Set low-level hardware option (e.g. MIICAM_OPTION_BINNING, MIICAM_OPTION_FRAME_PRELOAD)."""
        if not self.handle:
            return False
        dll = _find_and_load_dll()
        if dll and hasattr(dll, 'Miicam_put_Option'):
            try:
                dll.Miicam_put_Option.restype = ctypes.c_int
                dll.Miicam_put_Option.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
                return dll.Miicam_put_Option(self.handle, ctypes.c_uint(option_id), ctypes.c_int(val)) >= 0
            except Exception:
                pass
        return False

    def get_option(self, option_id):
        """Get low-level hardware option."""
        if not self.handle:
            return None
        dll = _find_and_load_dll()
        if dll and hasattr(dll, 'Miicam_get_Option'):
            try:
                val = ctypes.c_int()
                dll.Miicam_get_Option.restype = ctypes.c_int
                dll.Miicam_get_Option.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
                if dll.Miicam_get_Option(self.handle, ctypes.c_uint(option_id), ctypes.byref(val)) >= 0:
                    return val.value
            except Exception:
                pass
        return None

    def set_binning(self, bin_mode=1):
        """1 = 1x1 standard, 2 = 2x2 hardware binning (ultra-high FPS / max light sensitivity)."""
        self.binning_mode = int(bin_mode)
        return self.put_option(MIICAM_OPTION_BINNING, int(bin_mode))

    def set_frame_preload(self, enable=True):
        """Enable DMA frame preloading for high throughput and minimum jitter."""
        self.frame_preload = bool(enable)
        return self.put_option(MIICAM_OPTION_FRAME_PRELOAD, 1 if enable else 0)

    def set_thread_priority(self, priority=2):
        """0 = Normal, 1 = High, 2 = Real-Time/Critical."""
        self.thread_priority = int(priority)
        return self.put_option(MIICAM_OPTION_THREAD_PRIORITY, int(priority))

    def set_high_fps_mode(self, target_fps=60):
        """Fast preset for high-speed tracking (> 30 up to 120 FPS)."""
        self.set_speed(2)
        self.set_frame_preload(True)
        self.set_thread_priority(2)
        if target_fps >= 90:
            self.set_exposure_time_us(8000)   # 8 ms -> up to 125 FPS
            self.set_binning(2)
        elif target_fps >= 60:
            self.set_exposure_time_us(15000)  # 15 ms -> up to 66 FPS
            self.set_binning(1)
        else:
            self.set_exposure_time_us(30000)  # 30 ms
        return True

    def get_realtime_fps(self):
        return float(self.fps)

    def apply_settings_dict(self, cfg):
        """Batch apply settings dictionary to the camera hardware."""
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
        if 'miicam_temp' in cfg and 'miicam_tint' in cfg:
            self.set_temp_tint(int(cfg['miicam_temp']), int(cfg['miicam_tint']))
        if 'miicam_wb_r' in cfg and 'miicam_wb_g' in cfg and 'miicam_wb_b' in cfg:
            self.set_white_balance_gains(
                int(cfg.get('miicam_wb_r', 0)),
                int(cfg.get('miicam_wb_g', 0)),
                int(cfg.get('miicam_wb_b', 0))
            )
        if 'miicam_h_flip' in cfg or 'miicam_v_flip' in cfg:
            self.set_flips(bool(cfg.get('miicam_h_flip', False)), bool(cfg.get('miicam_v_flip', False)))
        if 'miicam_anti_flicker' in cfg:
            self.set_anti_flicker(int(cfg.get('miicam_anti_flicker', 1)))
