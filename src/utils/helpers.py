import os
import cv2
import numpy as np
import time
import socket
import subprocess
import threading
import re

from ..config import LOW_LATENCY_FFMPEG_OPTIONS, get_default_save_folder
from .ffmpeg_utils import find_ffmpeg_exe, ffmpeg_missing_message

                                                                 
VIDEO_FILE_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".m4v", ".wmv", ".webm", ".mpeg", ".mpg"
}


def is_video_file_path(source):
    """Проверяет расширение файла (даже если файл ещё не создан или перемещён)."""
    if not source:
        return False
    try:
        clean = str(source).strip().strip('"').strip("'")
        if not clean:
            return False
        return os.path.splitext(clean)[1].lower() in VIDEO_FILE_EXTENSIONS
    except Exception:
        return False


def is_video_file_source(source):
    """Проверяет, что путь ведёт к существующему видеофайлу."""
    if not source:
        return False
    try:
        clean = str(source).strip().strip('"').strip("'")
        if not clean:
            return False
        value = os.path.abspath(os.path.expanduser(clean))
        return os.path.isfile(value) and os.path.splitext(value)[1].lower() in VIDEO_FILE_EXTENSIONS
    except Exception:
        return False


def is_network_source(source):
    if not source:
        return False
    source_str = str(source).strip().strip('"').strip("'").lower()
    return source_str.startswith(("rtsp://", "http://", "https://"))


def is_rtsp_source(source):
    if not source:
        return False
    return str(source).strip().strip('"').strip("'").lower().startswith("rtsp://")

def apply_low_latency_ffmpeg_options():
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = LOW_LATENCY_FFMPEG_OPTIONS


def get_short_path_name(path):
    """
    Возвращает короткий 8.3 путь Windows для надёжного открытия
    файлов с кириллицей, пробелами и спецсимволами в OpenCV.
    """
    if not path or not os.path.exists(path):
        return path
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
            _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            _GetShortPathNameW.restype = wintypes.DWORD

            buf = ctypes.create_unicode_buffer(260)
            res = _GetShortPathNameW(str(path), buf, 260)
            if res > 260:
                buf = ctypes.create_unicode_buffer(res)
                res = _GetShortPathNameW(str(path), buf, res)
            if res > 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return path


def verify_capture_can_read(cap):
    """Проверяет, что capture объект действительно открыт и может декодировать кадры."""
    if cap is None or not cap.isOpened():
        return False
    try:
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            try:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def repair_video_file_if_needed(file_path):
    """
    Автоматическое восстановление повреждённого MP4/MOV видеофайла
    (включая ошибку 'moov atom not found', возникающую при аварийной остановке записи).
    Пробует FFmpeg remuxing, прямое извлечение NAL/H.264/MPEG4 потока из mdat-атома
    и упаковку в MKV.
    """
    try:
        if not file_path:
            return None
        raw_str = str(file_path).strip().strip('"').strip("'")
        norm_path = os.path.normpath(os.path.abspath(os.path.expanduser(raw_str)))
        if not os.path.isfile(norm_path) or os.path.getsize(norm_path) < 64:
            return None

        base, ext = os.path.splitext(norm_path)
        repaired_path = f"{base}_repaired.mkv"
        recovered_h264 = f"{base}_recovered.h264"
        recovered_m4v = f"{base}_recovered.m4v"

        if os.path.isfile(repaired_path) and os.path.getsize(repaired_path) > 1024:
            return repaired_path

        ffmpeg_exe = find_ffmpeg_exe()
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

        # 1. Попытка FFmpeg прямого ремукса с игнорированием ошибок
        if ffmpeg_exe:
            try:
                cmd1 = [
                    ffmpeg_exe, '-y', '-hide_banner', '-loglevel', 'error',
                    '-err_detect', 'ignore_err',
                    '-i', norm_path,
                    '-c', 'copy',
                    repaired_path
                ]
                subprocess.run(cmd1, capture_output=True, timeout=12, creationflags=flags)
                if os.path.isfile(repaired_path) and os.path.getsize(repaired_path) > 1024:
                    print(f"🔧 Видеофайл успешно восстановлен через FFmpeg remux: {repaired_path}")
                    return repaired_path
            except Exception:
                pass

        # 2. Попытка извлечения сырого mdat-потока (H.264 / MPEG4)
        try:
            with open(norm_path, 'rb') as f_in:
                data = f_in.read()

            mdat_idx = data.find(b'mdat')
            if mdat_idx != -1:
                stream_start = mdat_idx + 4
                raw_payload = data[stream_start:]
                if len(raw_payload) > 1024:
                    # Поиск H.264 start codes (00 00 00 01 или 00 00 01)
                    if b'\x00\x00\x00\x01' in raw_payload or b'\x00\x00\x01' in raw_payload:
                        with open(recovered_h264, 'wb') as f_out:
                            f_out.write(raw_payload)
                        if os.path.isfile(recovered_h264) and os.path.getsize(recovered_h264) > 1024:
                            if ffmpeg_exe:
                                cmd_h264 = [
                                    ffmpeg_exe, '-y', '-hide_banner', '-loglevel', 'error',
                                    '-f', 'h264', '-i', recovered_h264,
                                    '-c', 'copy', repaired_path
                                ]
                                subprocess.run(cmd_h264, capture_output=True, timeout=12, creationflags=flags)
                                if os.path.isfile(repaired_path) and os.path.getsize(repaired_path) > 1024:
                                    print(f"🔧 H.264 поток упакован в MKV: {repaired_path}")
                                    try:
                                        os.remove(recovered_h264)
                                    except Exception:
                                        pass
                                    return repaired_path
                    else:
                        with open(recovered_m4v, 'wb') as f_out:
                            f_out.write(raw_payload)
                        if os.path.isfile(recovered_m4v) and os.path.getsize(recovered_m4v) > 1024:
                            if ffmpeg_exe:
                                cmd_m4v = [
                                    ffmpeg_exe, '-y', '-hide_banner', '-loglevel', 'error',
                                    '-f', 'm4v', '-i', recovered_m4v,
                                    '-c', 'copy', repaired_path
                                ]
                                subprocess.run(cmd_m4v, capture_output=True, timeout=12, creationflags=flags)
                                if os.path.isfile(repaired_path) and os.path.getsize(repaired_path) > 1024:
                                    print(f"🔧 MPEG-4 поток упакован в MKV: {repaired_path}")
                                    try:
                                        os.remove(recovered_m4v)
                                    except Exception:
                                        pass
                                    return repaired_path
        except Exception:
            pass

    except Exception:
        pass
    return None


def open_video_file_capture(file_path):
    """
    Надёжное открытие видеофайла с автоматическим преобразованием в 8.3 путь (для кириллицы),
    перебором бэкендов OpenCV (CAP_ANY, CAP_MSMF, CAP_FFMPEG, CAP_DSHOW), прямым чтением через
    FFmpeg pipe (FFMpegFileCapture) и авто-восстановлением через FFmpeg.
    """
    if not file_path:
        return None
    raw_str = str(file_path).strip().strip('"').strip("'")
    norm_path = os.path.normpath(os.path.abspath(os.path.expanduser(raw_str)))
    if not os.path.isfile(norm_path):
        return None

    short_path = get_short_path_name(norm_path)
    path_candidates = [norm_path]
    if short_path and short_path != norm_path and os.path.isfile(short_path):
        path_candidates.insert(0, short_path)

    backends = []
    if hasattr(cv2, 'CAP_ANY'):
        backends.append(cv2.CAP_ANY)
    if hasattr(cv2, 'CAP_MSMF'):
        backends.append(cv2.CAP_MSMF)
    if hasattr(cv2, 'CAP_FFMPEG'):
        backends.append(cv2.CAP_FFMPEG)
    if hasattr(cv2, 'CAP_DSHOW'):
        backends.append(cv2.CAP_DSHOW)
    if not backends:
        backends.append(None)

    # 1. Пробуем открыть файл перебором путей и бэкендов OpenCV
    for p in path_candidates:
        for backend in backends:
            try:
                cap = cv2.VideoCapture(p, backend) if backend is not None else cv2.VideoCapture(p)
                if verify_capture_can_read(cap):
                    return cap
                if cap is not None:
                    cap.release()
            except Exception:
                pass

    # 2. Если файл повреждён (например, moov atom not found), пробуем восстановить через FFmpeg / mdat
    repaired = repair_video_file_if_needed(norm_path)
    if repaired and os.path.isfile(repaired):
        rep_short = get_short_path_name(repaired)
        rep_paths = [rep_short, repaired] if (rep_short and rep_short != repaired) else [repaired]
        for p in rep_paths:
            for backend in backends:
                try:
                    cap = cv2.VideoCapture(p, backend) if backend is not None else cv2.VideoCapture(p)
                    if verify_capture_can_read(cap):
                        return cap
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
            try:
                from ..analysis.ffmpeg_capture import FFMpegFileCapture
                cap = FFMpegFileCapture(p)
                if verify_capture_can_read(cap):
                    return cap
                if cap is not None:
                    cap.release()
            except Exception:
                pass

    # 3. Пробуем прямое чтение через внешний ffmpeg (FFMpegFileCapture)
    try:
        from ..analysis.ffmpeg_capture import FFMpegFileCapture
        for p in path_candidates:
            cap = FFMpegFileCapture(p)
            if verify_capture_can_read(cap):
                return cap
            if cap is not None:
                cap.release()
    except Exception:
        pass

    return None


def is_miicam_source(source):
    s = str(source).strip().lower()
    return s.startswith("miicam") or s.startswith("rgb_detector") or s == "detector"


def scan_miicam_cameras():
    """Сканирует подключенные научные USB/CMOS RGB-детекторы MiiCam / ToupCam."""
    try:
        from .miicam_wrapper import is_miicam_available, enumerate_miicam_devices
        if not is_miicam_available():
            return []
        devs = enumerate_miicam_devices()
        results = []
        for d in devs:
            src = d.get('source', f"miicam:{d.get('index', 0)}")
            label = f"💡 RGB-детектор MiiCam: {d.get('displayname', 'Sensor')} ({d.get('width', 1920)}x{d.get('height', 1080)})"
            results.append((src, label))
        return results
    except Exception as e:
        print(f"⚠️ Ошибка сканирования MiiCam: {e}")
        return []


def open_camera_device(index, width=None, height=None, max_attempts=15):
    """
    Надёжно открывает камеру по индексу с перебором бэкендов DirectShow -> MSMF -> ANY,
    прогревом DirectShow-графа и верификацией реального поступления кадров.
    """
    if is_miicam_source(index):
        try:
            from .miicam_wrapper import MiiCamCapture
            cap = MiiCamCapture(index, width=width, height=height)
            if cap.isOpened():
                for _ in range(max_attempts):
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        return cap, frame, "MIICAM"
                    time.sleep(0.04)
                return cap, None, "MIICAM"
        except Exception as e:
            print(f"⚠️ Ошибка open_camera_device (MiiCam): {e}")
        return None, None, "FAILED"

    backend_candidates = []
    if hasattr(cv2, 'CAP_DSHOW'):
        backend_candidates.append((cv2.CAP_DSHOW, "DSHOW"))
    if hasattr(cv2, 'CAP_MSMF'):
        backend_candidates.append((cv2.CAP_MSMF, "MSMF"))
    if hasattr(cv2, 'CAP_ANY'):
        backend_candidates.append((cv2.CAP_ANY, "ANY"))
    if not backend_candidates:
        backend_candidates.append((None, "DEFAULT"))

    for backend, b_name in backend_candidates:
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend) if backend is not None else cv2.VideoCapture(index)
        except Exception:
            cap = None

        if cap is None or not cap.isOpened():
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            continue

        # Пытаемся задать разрешение, если указано
        if width and height:
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            except Exception:
                pass

        # Даем DirectShow/MSMF время на инициализацию потока
        frame = None
        for _ in range(max_attempts):
            try:
                ret, f = cap.read()
                if ret and f is not None and f.size > 0:
                    frame = f
                    break
            except Exception:
                pass
            time.sleep(0.035)

        if frame is not None:
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            return cap, frame, b_name

        # Если с принудительным разрешением кадры не пошли, пробуем без смены разрешения
        if width and height:
            try:
                cap.release()
            except Exception:
                pass
            time.sleep(0.04)
            try:
                cap = cv2.VideoCapture(index, backend) if backend is not None else cv2.VideoCapture(index)
                if cap is not None and cap.isOpened():
                    for _ in range(max_attempts):
                        try:
                            ret, f = cap.read()
                            if ret and f is not None and f.size > 0:
                                frame = f
                                break
                        except Exception:
                            pass
                        time.sleep(0.035)
                    if frame is not None:
                        try:
                            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        except Exception:
                            pass
                        return cap, frame, b_name
            except Exception:
                pass

        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
            time.sleep(0.04)

    # Крайний fallback: VideoCapture(index)
    try:
        cap = cv2.VideoCapture(index)
        if cap is not None and cap.isOpened():
            for _ in range(max_attempts):
                try:
                    ret, f = cap.read()
                    if ret and f is not None and f.size > 0:
                        return cap, f, "AUTO"
                except Exception:
                    pass
                time.sleep(0.035)
            return cap, None, "AUTO"
    except Exception:
        pass

    return None, None, "FAILED"


def create_video_capture(source, width=None, height=None):
    try:
        from ..analysis import ffmpeg_capture
    except ImportError:
        from src.analysis import ffmpeg_capture
    source_str = str(source).strip().strip('"').strip("'")

    if is_miicam_source(source_str):
        try:
            from .miicam_wrapper import MiiCamCapture
            return MiiCamCapture(source_str, width=width, height=height)
        except Exception as e:
            print(f"⚠️ Ошибка создания MiiCamCapture: {e}")
            return None
    elif is_video_file_source(source_str) or is_video_file_path(source_str):
        return open_video_file_capture(source_str)
    elif is_rtsp_source(source_str):
        return ffmpeg_capture.FFMpegLatestFrameCapture(source_str, width=width, height=height)
    elif is_network_source(source_str):
        apply_low_latency_ffmpeg_options()
        return cv2.VideoCapture(source_str, cv2.CAP_FFMPEG)
    else:
        try:
            index = int(source_str)
            cap, _frame, _backend = open_camera_device(index, width, height, max_attempts=15)
            return cap
        except (ValueError, TypeError):
            return cv2.VideoCapture(source_str)


def warmup_capture(cap, frames=8):
    if cap is None:
        return
    for _ in range(frames):
        try:
            cap.grab()
        except Exception:
            break


def read_valid_frame(cap, attempts=30):
    if cap is None:
        return False, None
    for _ in range(attempts):
        try:
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                return True, frame
        except Exception:
            pass
        time.sleep(0.02)
    return False, None

def _run_hidden(cmd):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20, creationflags=flags)

def get_windows_camera_names():
    names = []
    seen = set()

    # FFmpeg DirectShow names are much closer to the actual capture-device
    # order than a generic PnP enumeration. Filter out alternative names and audio devices.
    try:
        ffmpeg = find_ffmpeg_exe()
        if ffmpeg:
            result = _run_hidden(
                [ffmpeg, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"]
            )
            text = (result.stderr or "") + "\n" + (result.stdout or "")
            in_video_section = True
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if "DirectShow audio devices" in line:
                    in_video_section = False
                    continue
                if "DirectShow video devices" in line:
                    in_video_section = True
                    continue
                if not in_video_section:
                    continue
                if "Alternative name" in line or "@device" in line:
                    continue
                m = re.search(r'"([^"]+)"', line)
                if not m:
                    continue
                name = m.group(1).strip()
                if not name or name.lower() in ("dummy", "default"):
                    continue
                if name.startswith("@device_"):
                    continue
                if name not in seen:
                    seen.add(name)
                    names.append(name)
    except Exception:
        pass

    if names:
        return names

    # Fallback: PnP names.
    try:
        ps = (
            "Get-PnpDevice -Status OK | Where-Object { "
            "$_.Class -in @('Camera','Image') -or "
            "$_.FriendlyName -match 'cam|webcam|ivcam|iriun|video' "
            "} | ForEach-Object { $_.FriendlyName } | Where-Object { $_ }"
        )
        result = _run_hidden(["powershell", "-NoProfile", "-Command", ps])
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and line not in seen and not line.startswith("@device_"):
                seen.add(line)
                names.append(line)
    except Exception:
        pass
    return names


def is_ivcam_name(name):
    n = name.lower()
    return 'ivcam' in n or 'e2esoft' in n

def is_iriun_name(name):
    return 'iriun' in name.lower()

def camera_priority(name):
    has_stream = "нет видеопотока" not in name
    if is_ivcam_name(name) and has_stream:
        return 0
    if is_ivcam_name(name):
        return 1
    if has_stream and not is_iriun_name(name):
        return 2
    if has_stream:
        return 3
    if is_iriun_name(name):
        return 5
    return 4

def is_placeholder_frame(frame):
    if frame is None or frame.size == 0:
        return True
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if gray.mean() > 25:
        return False
    _, bright = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    return cv2.countNonZero(bright) > 500

def camera_label(index, width, height, backend, has_stream=True, win_names=None):
    win_name = None
    if win_names and index < len(win_names):
        win_name = win_names[index]
    if win_name:
        base = f"{win_name} ({width}x{height}, {backend})"
    else:
        base = f"Камера {index} ({width}x{height}, {backend})"
    if not has_stream:
        base += " — нет видеопотока"
    return base

def scan_cameras(max_index=6):
    available = []
    win_names = get_windows_camera_names()
    print("🔍 Сканирование камер...")
    if win_names:
        print("📷 Устройства Windows:", ", ".join(win_names))
    for i in range(max_index):
        try:
            cap, frame, backend = open_camera_device(i, width=None, height=None, max_attempts=8)
            if cap is not None and cap.isOpened():
                if frame is not None and frame.size > 0:
                    h, w = frame.shape[:2]
                    has_stream = not is_placeholder_frame(frame)
                    label = camera_label(i, w, h, backend, has_stream, win_names)
                    available.append((str(i), label))
                    if has_stream:
                        print(f"✅ [{i}] {label}")
                    else:
                        print(f"⚠️ [{i}] {label}")
                else:
                    label = camera_label(i, 640, 480, backend, False, win_names)
                    available.append((str(i), label))
                try:
                    cap.release()
                except Exception:
                    pass
                time.sleep(0.04)
        except Exception as e:
            print(f"⚠️ Ошибка проверки камеры [{i}]: {e}")
    available.sort(key=lambda item: (camera_priority(item[1]), int(item[0]) if item[0].isdigit() else 99))
    return available

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.1.1"

def scan_ip_cameras():
    found = []
    local_ip = get_local_ip()
    subnet = '.'.join(local_ip.split('.')[:3])
    ports = [8080, 80, 554, 4747, 7070]
    print(f"📱 Сканирование сети {subnet}.x...")
    
    def check_host(ip, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.3)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result == 0:
                url = f"http://{ip}:{port}/video"
                test_cap = cv2.VideoCapture(url)
                if test_cap.isOpened():
                    ret, _ = test_cap.read()
                    test_cap.release()
                    if ret:
                        found.append((url, f"IP Camera: {ip}:{port}"))
                        print(f"✅ Найдена IP-камера: {ip}:{port}")
        except:
            pass
    
    threads = []
    for i in range(1, 50):
        ip = f"{subnet}.{i}"
        for port in ports:
            t = threading.Thread(target=check_host, args=(ip, port))
            t.start()
            threads.append(t)
    
    for t in threads:
        t.join()
    
    return found

def ivcam_setup_hint():
    return (
        "Запустите iVCam:\n"
        "1. На ПК — клиент e2eSoft iVCam (должен быть запущен)\n"
        "2. На телефоне — приложение iVCam\n"
        "3. Подключите телефон и ПК к одной Wi‑Fi сети (или USB)\n"
        "4. В списке камер выберите «e2eSoft iVCam»"
    )

                                                                   
def compute_roi_means(frame, config):
    x = config['roi_x']
    y = config['roi_y']
    w = config['roi_w']
    h = config['roi_h']

    h_f, w_f = frame.shape[:2]
    safe_x = max(0, min(x, w_f - 1))
    safe_y = max(0, min(y, h_f - 1))
    safe_w = max(10, min(w, w_f - safe_x))
    safe_h = max(10, min(h, h_f - safe_y))

    roi = frame[safe_y:safe_y + safe_h, safe_x:safe_x + safe_w]

    if config.get('roi_shape', 'rect') == 'circle':
        mask = np.zeros((safe_h, safe_w), dtype=np.uint8)
        radius = min(safe_w, safe_h) // 2
        center = (safe_w // 2, safe_h // 2)
        cv2.circle(mask, center, radius, 255, -1)
        mean_b, mean_g, mean_r, _ = cv2.mean(roi, mask=mask)
    else:
        mean_b, mean_g, mean_r, _ = cv2.mean(roi)

    return mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f

def detect_green_circle_roi(frame):
    """
    Автоматическое обнаружение нарисованного зеленого круга ROI на видеокадре.
    Возвращает кортеж (cx, cy, radius) пиксель в пиксель или None.
    """
    if frame is None or frame.size == 0:
        return None

    # 1. Поиск ярко-зеленых пикселей (в HSV и BGR)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask_hsv = cv2.inRange(hsv, np.array([30, 45, 45]), np.array([90, 255, 255]))

    b = frame[:, :, 0].astype(np.int32)
    g = frame[:, :, 1].astype(np.int32)
    r = frame[:, :, 2].astype(np.int32)
    mask_bgr = ((g > 75) & (g > r + 20) & (g > b + 20)).astype(np.uint8) * 255

    mask = cv2.bitwise_or(mask_hsv, mask_bgr)
    cnts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None

    candidates = []
    for c in cnts:
        arc = cv2.arcLength(c, True)
        if arc < 25 or len(c) < 15:
            continue
        pts = c.reshape(-1, 2).astype(np.float64)
        x = pts[:, 0]
        y = pts[:, 1]
        A = np.column_stack([x, y, np.ones_like(x)])
        f = x**2 + y**2
        try:
            sol, _, _, _ = np.linalg.lstsq(A, f, rcond=None)
            cx = sol[0] / 2.0
            cy = sol[1] / 2.0
            r_sq = sol[2] + cx**2 + cy**2
            if r_sq > 0:
                r_calc = np.sqrt(r_sq)
                if 8 <= r_calc <= max(frame.shape[:2]):
                    residuals = np.abs(np.hypot(x - cx, y - cy) - r_calc)
                    mean_err = np.mean(residuals)
                    if mean_err < max(5.0, 0.22 * r_calc):
                        score = mean_err / r_calc
                        candidates.append((score, len(c), int(round(cx)), int(round(cy)), int(round(r_calc))))
        except Exception:
            pass

    if candidates:
        candidates.sort(key=lambda item: (item[0], -item[1]))
        best = candidates[0]
        return best[2], best[3], best[4]
    return None

