import cv2
import numpy as np
import subprocess
import os
import re

from ..utils.ffmpeg_utils import find_ffmpeg_exe


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


