import cv2
import numpy as np
import subprocess
import threading
import time
import os
import re
from collections import deque

from ..utils.ffmpeg_utils import find_ffmpeg_exe, ffmpeg_missing_message
from ..config import FFMPEG_PIPE_OUTPUT_FPS


class FFMpegFileCapture:
    """
    Универсальный захват видеофайла через ffmpeg.exe pipe.
    Работает со всеми форматами, кодеками и повреждёнными файлами,
    гарантируя декодирование кадров даже если OpenCV backends не справляются.
    """
    def __init__(self, file_path):
        self.file_path = os.path.normpath(os.path.abspath(os.path.expanduser(str(file_path).strip().strip('"').strip("'"))))
        self.ffmpeg_exe = find_ffmpeg_exe()
        self.width = 1280
        self.height = 720
        self.fps = 25.0
        self.frame_count = 0
        self.duration_sec = 0.0
        self._proc = None
        self._opened = False
        self._current_frame_idx = 0
        self._probe()
        if self._opened:
            self._start_pipe(0.0)

    def _probe(self):
        if not os.path.isfile(self.file_path) or not self.ffmpeg_exe:
            self._opened = False
            return
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        cmd = [self.ffmpeg_exe, '-hide_banner', '-i', self.file_path]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=8, creationflags=flags)
            err = res.stderr or ''
            m_res = re.search(r'Stream #\d+:\d+.*Video:.*,\s*(\d{2,5})x(\d{2,5})', err)
            if m_res:
                self.width = int(m_res.group(1))
                self.height = int(m_res.group(2))
            m_fps = re.search(r'(\d+(?:\.\d+)?)\s*fps', err)
            if m_fps:
                self.fps = float(m_fps.group(1))
            m_dur = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', err)
            if m_dur:
                h, m, s = float(m_dur.group(1)), float(m_dur.group(2)), float(m_dur.group(3))
                self.duration_sec = h * 3600 + m * 60 + s
                self.frame_count = int(self.duration_sec * self.fps)
            self._opened = True
        except Exception:
            self._opened = False

    def _start_pipe(self, start_sec=0.0):
        self._close_pipe()
        if not self._opened or not self.ffmpeg_exe:
            return
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        cmd = [self.ffmpeg_exe, '-hide_banner', '-loglevel', 'error']
        if start_sec > 0.05:
            cmd.extend(['-ss', f'{start_sec:.3f}'])
        cmd.extend([
            '-err_detect', 'ignore_err',
            '-i', self.file_path,
            '-an',
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-'
        ])
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                bufsize=10 * self.width * self.height * 3,
                creationflags=flags
            )
        except Exception:
            self._proc = None

    def _close_pipe(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def isOpened(self):
        return self._opened and (self._proc is not None or os.path.isfile(self.file_path))

    def read(self):
        if self._proc is None or self._proc.stdout is None:
            return False, None
        frame_size = self.width * self.height * 3
        try:
            raw = self._proc.stdout.read(frame_size)
            if len(raw) != frame_size:
                return False, None
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3)).copy()
            self._current_frame_idx += 1
            return True, frame
        except Exception:
            return False, None

    def grab(self):
        ret, _ = self.read()
        return ret

    def set(self, prop, value):
        if prop == cv2.CAP_PROP_POS_FRAMES:
            target_frame = max(0, int(value))
            target_sec = target_frame / self.fps if self.fps > 0 else 0.0
            self._current_frame_idx = target_frame
            self._start_pipe(target_sec)
            return True
        elif prop == cv2.CAP_PROP_POS_MSEC:
            target_sec = max(0.0, float(value) / 1000.0)
            self._current_frame_idx = int(target_sec * self.fps)
            self._start_pipe(target_sec)
            return True
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        if prop == cv2.CAP_PROP_FPS:
            return float(self.fps)
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(self.frame_count)
        if prop == cv2.CAP_PROP_POS_FRAMES:
            return float(self._current_frame_idx)
        if prop == cv2.CAP_PROP_POS_MSEC:
            return float(self._current_frame_idx / self.fps * 1000.0 if self.fps > 0 else 0.0)
        return 0.0

    def release(self):
        self._close_pipe()
        self._opened = False

    def getBackendName(self):
        return 'FFMPEG_PIPE_FILE'


class FFMpegLatestFrameCapture:
    """
    RTSP-захват через внешний ffmpeg.exe
    """
    def __init__(self, url, width=None, height=None):
        self.url = str(url).strip()
        self.width = int(width) if width else 1280
        self.height = int(height) if height else 720
        self.frame_size = self.width * self.height * 3
        self.proc = None
        self._thread = None
        self._stderr_thread = None
        self._running = False
        self._opened = False
        self._latest_frame = None
        self._frame_id = 0
        self._last_read_id = -1
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stderr_lines = deque(maxlen=40)
        self._last_error = ''
        self._cmd_text = ''
        self._variant = 'strict'
        self._tried_safe = False

        self._auto_reconnect = True
        self._reconnect_count = 0
        self._max_reconnects = 50
        self._reconnect_delay_sec = 1.0
        self._last_reconnect_attempt = 0.0
        self._last_frame_time = 0.0

        self._start('strict')

    def _make_cmd(self, ffmpeg_exe, variant):
        base = [ffmpeg_exe, '-hide_banner']
        if variant == 'strict':
            return base + [
                '-loglevel', 'warning',
                '-rtsp_transport', 'tcp',
                '-fflags', 'nobuffer',
                '-flags', 'low_delay',
                '-analyzeduration', '0',
                '-probesize', '32',
                '-max_delay', '0',
                '-i', self.url,
                '-an',
                '-vf', f'fps={FFMPEG_PIPE_OUTPUT_FPS},scale={self.width}:{self.height}',
                '-f', 'rawvideo',
                '-pix_fmt', 'bgr24',
                '-'
            ]
        else:
            return base + [
                '-loglevel', 'warning',
                '-rtsp_transport', 'tcp',
                '-i', self.url,
                '-an',
                '-vf', f'fps={FFMPEG_PIPE_OUTPUT_FPS},scale={self.width}:{self.height}',
                '-f', 'rawvideo',
                '-pix_fmt', 'bgr24',
                '-'
            ]

    def _start(self, variant='strict'):
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        ffmpeg_exe = find_ffmpeg_exe()
        if not ffmpeg_exe:
            self._last_error = ffmpeg_missing_message()
            print('❌ ' + self._last_error.replace('\n', ' '))
            self._opened = False
            return

        self._variant = variant
        cmd = self._make_cmd(ffmpeg_exe, variant)
        self._cmd_text = ' '.join(f'"{x}"' if ' ' in str(x) else str(x) for x in cmd)
        print(f'▶ FFmpeg RTSP режим: {variant}')
        print(f'▶ FFmpeg output FPS limit: {FFMPEG_PIPE_OUTPUT_FPS}')
        print(f'▶ FFmpeg найден: {ffmpeg_exe}')
        print(f'▶ Команда: {self._cmd_text}')

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=0,
                creationflags=flags
            )
            self._running = True
            self._opened = True
            self._thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._thread.start()
            self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
            self._stderr_thread.start()
        except FileNotFoundError:
            self._last_error = ffmpeg_missing_message()
            print('❌ ' + self._last_error.replace('\n', ' '))
            self._opened = False
        except Exception as e:
            self._last_error = f'Не удалось запустить ffmpeg pipe: {e}'
            print(f'❌ {self._last_error}')
            self._opened = False

    def _stderr_loop(self):
        try:
            if self.proc is None or self.proc.stderr is None:
                return
            while self._running and self.proc.poll() is None:
                line = self.proc.stderr.readline()
                if not line:
                    break
                try:
                    text = line.decode('utf-8', errors='replace').strip()
                except Exception:
                    text = str(line).strip()
                if text:
                    with self._lock:
                        self._stderr_lines.append(text)
                        self._last_error = '\n'.join(self._stderr_lines)
                    print('FFmpeg:', text)
        except Exception as e:
            with self._lock:
                self._last_error = f'Ошибка чтения stderr FFmpeg: {e}'

    def _read_exact(self, n):
        if self.proc is None or self.proc.stdout is None:
            return b''
        chunks = []
        total = 0
        while self._running and total < n:
            try:
                chunk = self.proc.stdout.read(n - total)
            except Exception:
                break
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if not chunks:
            return b''
        return b''.join(chunks)

    def _reader_loop(self):
        while self._running and self.proc is not None:
            try:
                if self.proc.stdout is None:
                    break
                raw = self._read_exact(self.frame_size)
                if len(raw) != self.frame_size:
                    if len(raw) == 0:
                        msg = f'FFmpeg завершился до получения кадра. Режим: {self._variant}'
                    else:
                        msg = f'FFmpeg завершился на неполном кадре: собрано {len(raw)} байт из {self.frame_size}'
                    with self._lock:
                        if msg not in self._last_error:
                            self._stderr_lines.append(msg)
                            self._last_error = '\n'.join(self._stderr_lines)
                    print('❌', msg)
                    break
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3)).copy()
                with self._cond:
                    self._latest_frame = frame
                    self._frame_id += 1
                    self._last_frame_time = time.time()
                    self._cond.notify_all()
            except Exception as e:
                with self._lock:
                    self._stderr_lines.append(f'Ошибка чтения rawvideo: {e}')
                    self._last_error = '\n'.join(self._stderr_lines)
                break
        with self._cond:
            self._opened = False
            self._running = False
            self._cond.notify_all()

    def _restart_safe_if_needed(self):
        if self._tried_safe or self._latest_frame is not None:
            return False
        if self.proc is not None and self.proc.poll() is None:
            return False
        self._tried_safe = True
        print('⚠️ Strict FFmpeg режим не дал кадр. Пробую fallback-safe режим...')
        self.release(join=False)
        self._stderr_lines.append('--- fallback-safe mode ---')
        self._last_error = '\n'.join(self._stderr_lines)
        self._running = False
        self._opened = False
        self.proc = None
        self._start('safe')
        return True

    def _terminate_ffmpeg_process(self):
        self._running = False
        try:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass

    def _auto_reconnect_if_needed(self):
        if not self._auto_reconnect:
            return False
        now = time.time()
        if now - self._last_reconnect_attempt < self._reconnect_delay_sec:
            return False
        if self._reconnect_count >= self._max_reconnects:
            return False

        alive = self.proc is not None and self.proc.poll() is None
        if alive and self._running:
            return False

        self._last_reconnect_attempt = now
        self._reconnect_count += 1
        print(f'⚠️ FFmpeg/RTSP поток оборвался. Автопереподключение #{self._reconnect_count}...')

        with self._lock:
            self._stderr_lines.append(f'--- auto reconnect #{self._reconnect_count} ---')
            self._last_error = '\n'.join(self._stderr_lines)

        self._terminate_ffmpeg_process()
        self.proc = None
        self._thread = None
        self._stderr_thread = None
        self._running = False
        self._opened = False
        self._tried_safe = False

        self._start('strict')
        return True

    def isOpened(self):
        return self._opened and self.proc is not None and self.proc.poll() is None

    def read(self):
        deadline = time.time() + 3.0
        while True:
            with self._cond:
                while self._running and self._frame_id == self._last_read_id:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    self._cond.wait(timeout=min(remaining, 0.05))

                if self._latest_frame is not None and self._frame_id != self._last_read_id:
                    self._last_read_id = self._frame_id
                    return True, self._latest_frame.copy()

            if self._restart_safe_if_needed():
                deadline = time.time() + 4.0
                continue

            if self._auto_reconnect_if_needed():
                deadline = time.time() + 5.0
                continue

            return False, None

    def grab(self):
        ret, _ = self.read()
        return ret

    def release(self, join=True):
        self._terminate_ffmpeg_process()
        if join and self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        if join and self._stderr_thread is not None and self._stderr_thread is not threading.current_thread():
            self._stderr_thread.join(timeout=0.5)
        self._opened = False

    def set(self, prop, value):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        if prop == cv2.CAP_PROP_FPS:
            return 30.0
        return 0.0

    def getBackendName(self):
        return f'FFMPEG_PIPE_{self._variant.upper()}'

    def get_last_error(self):
        with self._lock:
            details = self._last_error.strip()
        if details:
            return details
        return f'Кадр не получен. Команда FFmpeg:\n{self._cmd_text}'
