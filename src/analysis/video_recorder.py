import cv2
import numpy as np
import subprocess
import threading
import queue
import time
import os
from collections import deque

from ..utils.ffmpeg_utils import find_ffmpeg_exe, ffmpeg_missing_message

class AsyncVideoRecorder:
    """Асинхронная запись видео через ffmpeg stdin."""
    def __init__(self, output_path, fps=20.0, max_queue=120):
        self.output_path = output_path
        self.fps = float(fps) if fps else 20.0
        self.max_queue = int(max_queue)
        self._queue = queue.Queue(maxsize=self.max_queue)
        self._proc = None
        self._writer_thread = None
        self._stderr_thread = None
        self._running = False
        self._started = False
        self._size = None
        self._last_error = ''
        self._stderr_lines = deque(maxlen=30)
        self._frames_written = 0
        self._frames_dropped = 0
        self._lock = threading.Lock()

    def start(self, frame_shape):
        if self._started:
            return True
        if frame_shape is None or len(frame_shape) < 2:
            self._last_error = 'Некорректный размер кадра для записи видео'
            return False

        h, w = int(frame_shape[0]), int(frame_shape[1])
        self._size = (w, h)
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        ffmpeg_exe = find_ffmpeg_exe()
        if not ffmpeg_exe:
            self._last_error = ffmpeg_missing_message()
            print('⚠️ Видео не будет записано: ffmpeg.exe не найден')
            return False

        cmd = [
            ffmpeg_exe,
            '-hide_banner', '-y',
            '-loglevel', 'warning',
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{w}x{h}',
            '-r', f'{self.fps:g}',
            '-i', '-',
            '-an',
            '-c:v', 'mpeg4',
            '-q:v', '4',
            '-pix_fmt', 'yuv420p',
        ]
        if self.output_path.lower().endswith(('.mp4', '.m4v', '.mov')):
            cmd.extend(['-movflags', '+frag_keyframe+empty_moov+default_base_moof'])
        cmd.append(self.output_path)

        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=flags,
            )
            self._running = True
            self._started = True
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()
            self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
            self._stderr_thread.start()
            print(f'🎥 Запись видео анализа: {self.output_path}')
            print(f'🎥 Видео: {w}x{h}, {self.fps:g} FPS, codec=mpeg4, container=MKV')
            return True
        except Exception as e:
            self._last_error = f'Не удалось запустить ffmpeg для записи видео: {e}'
            print(f'⚠️ {self._last_error}')
            self._started = False
            self._running = False
            return False

    def _stderr_loop(self):
        try:
            if self._proc is None or self._proc.stderr is None:
                return
            while self._running or (self._proc is not None and self._proc.poll() is None):
                line = self._proc.stderr.readline()
                if not line:
                    break
                text = line.decode('utf-8', errors='replace').strip()
                if text:
                    with self._lock:
                        self._stderr_lines.append(text)
                        self._last_error = '\n'.join(self._stderr_lines)
                    print('FFmpeg video:', text)
        except Exception as e:
            with self._lock:
                self._last_error = f'Ошибка чтения stderr FFmpeg video: {e}'

    def _writer_loop(self):
        try:
            while self._running or not self._queue.empty():
                try:
                    frame = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if self._proc is None or self._proc.stdin is None:
                    break
                if self._proc.poll() is not None:
                    break
                try:
                    self._proc.stdin.write(frame.tobytes())
                    self._frames_written += 1
                except Exception as e:
                    with self._lock:
                        self._last_error = f'Ошибка записи кадра в ffmpeg video: {e}'
                    break
        finally:
            try:
                if self._proc is not None and self._proc.stdin is not None:
                    self._proc.stdin.close()
            except Exception:
                pass

    def write(self, frame):
        if frame is None:
            return False
        if not self._started:
            if not self.start(frame.shape):
                return False
        if not self._running:
            return False

        try:
            if self._size:
                w, h = self._size
                if frame.shape[1] != w or frame.shape[0] != h:
                    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            if frame.dtype != np.uint8:
                frame = frame.astype(np.uint8)
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)
            frame_copy = frame.copy()

            if self._queue.full():
                try:
                    self._queue.get_nowait()
                    self._frames_dropped += 1
                except queue.Empty:
                    pass
            self._queue.put_nowait(frame_copy)
            return True
        except Exception as e:
            with self._lock:
                self._last_error = f'Ошибка постановки кадра в очередь видео: {e}'
            return False

    def stop(self):
        self._running = False
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=10.0)
        try:
            if self._proc is not None:
                try:
                    self._proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=2.0)
        except Exception:
            pass
        if self._stderr_thread is not None and self._stderr_thread is not threading.current_thread():
            self._stderr_thread.join(timeout=0.5)

        if self._started:
            print(
                f'🎥 Видео завершено: кадров записано {self._frames_written}, '
                f'пропущено из-за очереди {self._frames_dropped}'
            )
        return self.output_path if os.path.isfile(self.output_path) and os.path.getsize(self.output_path) > 0 else None

    def get_last_error(self):
        with self._lock:
            return self._last_error.strip()

