import cv2
import numpy as np
import time
import threading
from collections import deque

from ..utils.math_utils import (
    compute_log_br, compute_log_bg, compute_rgb_triangle,
    compute_window_mean, compute_window_rate,
    compute_chrom_distance_from_previous_state,
    compute_transition_score
)
from ..utils.helpers import compute_roi_means
from ..data.csv_logger import CsvLogger                
from ..config import (
    RGB_SUM_SMOOTH_WINDOW_MS, RATE_MIN_POINTS,
    RGB_SUM_SLOPE_FAST_MS, RGB_SUM_SLOPE_SLOW_MS, RGB_SUM_SLOPE_MIN_POINTS,
    RGB_VECTOR_WINDOW_MS, CHROMATICITY_WINDOW_MS, LOG_RATIO_WINDOW_MS,
    RGB_SUM_ACCEL_WINDOW_MS, CHROM_BASELINE_LOOKBACK_MS, CHROM_BASELINE_GAP_MS,
    CHROM_BASELINE_MIN_POINTS,
    EMA_FAST_TAU_MS, EMA_SLOW_TAU_MS
)

class CameraWorker:
    _SERIES_NAMES = (
        "time_data", "r_data", "g_data", "b_data", "log_data", "log_bg_data",
        "rgb_sum_data", "rgb_sum_smooth_data", "rgb_sum_slope10_data", "rgb_sum_slope30_data",
        "tri_x_data", "tri_y_data", "rgb_vector_speed30_data", "chromaticity_speed30_data",
        "k_chrom_previous_data", "log_ratio_speed30_data", "rgb_sum_acceleration30_data",
        "transition_score_data", "rate_b_data", "rate_r_data", "rate_g_data", "rate_log_data",
        "rate_log_bg_data", "fastslow_log_data", "fastslow_log_bg_data",
    )
    _GRAPH_ARRAY_NAMES = (
        "_graph_t", "_graph_r", "_graph_g", "_graph_b", "_graph_log", "_graph_log_bg",
        "_graph_rgb_sum", "_graph_rgb_sum_smooth", "_graph_rgb_sum_slope10", "_graph_rgb_sum_slope30",
        "_graph_rgb_vector_speed30", "_graph_chromaticity_speed30", "_graph_k_chrom_previous",
        "_graph_log_ratio_speed30", "_graph_rgb_sum_acceleration30", "_graph_transition_score",
        "_graph_tri_x", "_graph_tri_y",
    )

    def __init__(self, cap, config, start_time, save_interval_ms=10, max_points=108000, raw_csv_path=None):
        self.cap = cap
        self.config = config
        self.start_time = start_time
        self.save_interval_ms = max(1, int(save_interval_ms))
        self.max_points = max(1, int(max_points))
        self._lock = threading.RLock()
        self._running = False
        self._thread = None

        self.time_data = deque(maxlen=self.max_points)
        self.r_data = deque(maxlen=self.max_points)
        self.g_data = deque(maxlen=self.max_points)
        self.b_data = deque(maxlen=self.max_points)
        self.log_data = deque(maxlen=self.max_points)
        self.log_bg_data = deque(maxlen=self.max_points)
        self.rgb_sum_data = deque(maxlen=self.max_points)
        self.rgb_sum_smooth_data = deque(maxlen=self.max_points)
        self.rgb_sum_slope10_data = deque(maxlen=self.max_points)
        self.rgb_sum_slope30_data = deque(maxlen=self.max_points)
        self.tri_x_data = deque(maxlen=self.max_points)
        self.tri_y_data = deque(maxlen=self.max_points)
        self.rgb_vector_speed30_data = deque(maxlen=self.max_points)
        self.chromaticity_speed30_data = deque(maxlen=self.max_points)
        self.k_chrom_previous_data = deque(maxlen=self.max_points)
        self.log_ratio_speed30_data = deque(maxlen=self.max_points)
        self.rgb_sum_acceleration30_data = deque(maxlen=self.max_points)
        self.transition_score_data = deque(maxlen=self.max_points)
        self.rate_b_data = deque(maxlen=self.max_points)
        self.rate_r_data = deque(maxlen=self.max_points)
        self.rate_g_data = deque(maxlen=self.max_points)
        self.rate_log_data = deque(maxlen=self.max_points)
        self.rate_log_bg_data = deque(maxlen=self.max_points)
        self.fastslow_log_data = deque(maxlen=self.max_points)
        self.fastslow_log_bg_data = deque(maxlen=self.max_points)
        self._ema_state = {}
        self.saved_data = []
        self.last_save_ms = 0
        self.frame_count = 0
        self.point_count = 0
        self.excel_rows_written = 0
        self.graph_version = 0
        self._graph_len = 0
        self._graph_start = 0
        self._graph_t = np.empty(0, dtype=np.float64)
        self._graph_r = np.empty(0, dtype=np.float64)
        self._graph_g = np.empty(0, dtype=np.float64)
        self._graph_b = np.empty(0, dtype=np.float64)
        self._graph_log = np.empty(0, dtype=np.float64)
        self._graph_log_bg = np.empty(0, dtype=np.float64)
        self._graph_rgb_sum = np.empty(0, dtype=np.float64)
        self._graph_rgb_sum_smooth = np.empty(0, dtype=np.float64)
        self._graph_rgb_sum_slope10 = np.empty(0, dtype=np.float64)
        self._graph_rgb_sum_slope30 = np.empty(0, dtype=np.float64)
        self._graph_rgb_vector_speed30 = np.empty(0, dtype=np.float64)
        self._graph_chromaticity_speed30 = np.empty(0, dtype=np.float64)
        self._graph_k_chrom_previous = np.empty(0, dtype=np.float64)
        self._graph_log_ratio_speed30 = np.empty(0, dtype=np.float64)
        self._graph_rgb_sum_acceleration30 = np.empty(0, dtype=np.float64)
        self._graph_transition_score = np.empty(0, dtype=np.float64)
        self._graph_rate_b = np.empty(0, dtype=np.float64)
        self._graph_rate_r = np.empty(0, dtype=np.float64)
        self._graph_rate_g = np.empty(0, dtype=np.float64)
        self._graph_rate_log = np.empty(0, dtype=np.float64)
        self._graph_rate_log_bg = np.empty(0, dtype=np.float64)
        self._graph_fastslow_log = np.empty(0, dtype=np.float64)
        self._graph_fastslow_log_bg = np.empty(0, dtype=np.float64)
        self._graph_tri_x = np.empty(0, dtype=np.float64)
        self._graph_tri_y = np.empty(0, dtype=np.float64)

        self.raw_csv_path = raw_csv_path
        self.processing_interval_ms = max(1, int(config.get('analysis_interval_ms', 15)))
        self.source_is_file = bool(config.get('source_is_file', False))
        self.is_analysis_started = not self.source_is_file
        self.playback_speed = max(0.05, float(config.get('playback_speed', 1.0)))
        self._file_fps = 0.0
        self._file_frame_index = 0
        self.total_frames = 0
        self.duration_sec = 0.0
        self.is_paused = self.source_is_file
        self._seek_target_frame = None

        if self.source_is_file and self.cap is not None:
            try:
                self._file_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 25.0)
                self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if self._file_fps > 0 and self.total_frames > 0:
                    self.duration_sec = self.total_frames / self._file_fps
            except Exception:
                self._file_fps = 25.0
                            
        self.csv_logger = CsvLogger(raw_csv_path) if raw_csv_path else None

        self.latest_frame = None
        self.current_means = (0.0, 0.0, 0.0)
        self.roi_info = (0, 0, 10, 10, 480, 640)

        # Сразу считываем начальный кадр (кадр 0) для мгновенного отображения первого кадра в плеере
        if self.cap is not None:
            try:
                if self.source_is_file:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret_init, frame_init = self.cap.read()
                if ret_init and frame_init is not None:
                    mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f = compute_roi_means(
                        frame_init, self.config
                    )
                    self.latest_frame = frame_init
                    self.current_means = (mean_b, mean_g, mean_r)
                    self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                    self._file_frame_index = 0
                if self.source_is_file:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            except Exception as init_err:
                pass

    def _clear_measurements(self):
        """Clear every synchronized data series and all derived-state caches."""
        for name in self._SERIES_NAMES:
            getattr(self, name).clear()
        self.saved_data.clear()
        self._ema_state.clear()
        self.point_count = 0

    def _truncate_data_to_time(self, target_ms):
        """Обрезает все буферы данных до момента target_ms при перемотке назад,
        гарантируя монотонность оси X и единственную чистую линию графика."""
        if not self.time_data:
            self.last_save_ms = target_ms - self.save_interval_ms
            return

        target_val = float(target_ms)
        if target_val <= 50.0:
            self._clear_measurements()
            self._graph_len = 0
            self._graph_start = 0
            self.graph_version += 1
            self.last_save_ms = -1e9
            return

        keep_count = 0
        for i, t in enumerate(self.time_data):
            if t <= target_val:
                keep_count = i + 1
            else:
                break

        if keep_count == 0:
            self._clear_measurements()
            self._graph_len = 0
            self._graph_start = 0
            self.graph_version += 1
            self.last_save_ms = target_val - self.save_interval_ms
            return

        if keep_count >= len(self.time_data):
            self.last_save_ms = self.time_data[-1]
            return

        deques_to_truncate = [
            self.time_data, self.r_data, self.g_data, self.b_data,
            self.log_data, self.log_bg_data, self.rgb_sum_data,
            self.rgb_sum_smooth_data, self.rgb_sum_slope10_data, self.rgb_sum_slope30_data,
            self.tri_x_data, self.tri_y_data, self.rgb_vector_speed30_data,
            self.chromaticity_speed30_data, self.k_chrom_previous_data,
            self.log_ratio_speed30_data, self.rgb_sum_acceleration30_data,
            self.transition_score_data, self.rate_b_data, self.rate_r_data,
            self.rate_g_data, self.rate_log_data, self.rate_log_bg_data,
            self.fastslow_log_data, self.fastslow_log_bg_data
        ]
        for dq in deques_to_truncate:
            while len(dq) > keep_count:
                dq.pop()

        if len(self.saved_data) > keep_count:
            self.saved_data = self.saved_data[:keep_count]

        self.point_count = keep_count
        # EMA state cannot be reconstructed from a truncated tail.  Reset it so
        # a post-seek sample never uses future (discarded) data.
        self._ema_state.clear()
        self._graph_len = keep_count
        self.last_save_ms = self.time_data[-1] if self.time_data else (target_val - self.save_interval_ms)
        self.graph_version += 1

        # Синхронизируем массивы графиков
        if keep_count > 0:
            if len(self._graph_t) < keep_count:
                alloc_size = min(self.max_points, max(keep_count, min(self.max_points, keep_count * 2)))
                self._graph_t = np.empty(alloc_size, dtype=np.float64)
                self._graph_r = np.empty(alloc_size, dtype=np.float64)
                self._graph_g = np.empty(alloc_size, dtype=np.float64)
                self._graph_b = np.empty(alloc_size, dtype=np.float64)
                self._graph_log = np.empty(alloc_size, dtype=np.float64)
                self._graph_log_bg = np.empty(alloc_size, dtype=np.float64)
                self._graph_rgb_sum = np.empty(alloc_size, dtype=np.float64)
                self._graph_rgb_sum_smooth = np.empty(alloc_size, dtype=np.float64)
                self._graph_rgb_sum_slope10 = np.empty(alloc_size, dtype=np.float64)
                self._graph_rgb_sum_slope30 = np.empty(alloc_size, dtype=np.float64)
                self._graph_rgb_vector_speed30 = np.empty(alloc_size, dtype=np.float64)
                self._graph_chromaticity_speed30 = np.empty(alloc_size, dtype=np.float64)
                self._graph_k_chrom_previous = np.empty(alloc_size, dtype=np.float64)
                self._graph_log_ratio_speed30 = np.empty(alloc_size, dtype=np.float64)
                self._graph_rgb_sum_acceleration30 = np.empty(alloc_size, dtype=np.float64)
                self._graph_transition_score = np.empty(alloc_size, dtype=np.float64)
                self._graph_tri_x = np.empty(alloc_size, dtype=np.float64)
                self._graph_tri_y = np.empty(alloc_size, dtype=np.float64)

            self._graph_start = 0
            if len(self.time_data) == keep_count:
                self._graph_t[:keep_count] = np.array(self.time_data, dtype=np.float64)
            if len(self.r_data) == keep_count:
                self._graph_r[:keep_count] = np.array(self.r_data, dtype=np.float64)
            if len(self.g_data) == keep_count:
                self._graph_g[:keep_count] = np.array(self.g_data, dtype=np.float64)
            if len(self.b_data) == keep_count:
                self._graph_b[:keep_count] = np.array(self.b_data, dtype=np.float64)
            if len(self.log_data) == keep_count:
                self._graph_log[:keep_count] = np.array(self.log_data, dtype=np.float64)
            if len(self.log_bg_data) == keep_count:
                self._graph_log_bg[:keep_count] = np.array(self.log_bg_data, dtype=np.float64)
            if len(self.rgb_sum_data) == keep_count:
                self._graph_rgb_sum[:keep_count] = np.array(self.rgb_sum_data, dtype=np.float64)
            if len(self.rgb_sum_smooth_data) == keep_count:
                self._graph_rgb_sum_smooth[:keep_count] = np.array(self.rgb_sum_smooth_data, dtype=np.float64)
            if len(self.rgb_sum_slope10_data) == keep_count:
                self._graph_rgb_sum_slope10[:keep_count] = np.array(self.rgb_sum_slope10_data, dtype=np.float64)
            if len(self.rgb_sum_slope30_data) == keep_count:
                self._graph_rgb_sum_slope30[:keep_count] = np.array(self.rgb_sum_slope30_data, dtype=np.float64)
            if len(self.rgb_vector_speed30_data) == keep_count:
                self._graph_rgb_vector_speed30[:keep_count] = np.array(self.rgb_vector_speed30_data, dtype=np.float64)
            if len(self.chromaticity_speed30_data) == keep_count:
                self._graph_chromaticity_speed30[:keep_count] = np.array(self.chromaticity_speed30_data, dtype=np.float64)
            if len(self.k_chrom_previous_data) == keep_count:
                self._graph_k_chrom_previous[:keep_count] = np.array(self.k_chrom_previous_data, dtype=np.float64)
            if len(self.log_ratio_speed30_data) == keep_count:
                self._graph_log_ratio_speed30[:keep_count] = np.array(self.log_ratio_speed30_data, dtype=np.float64)
            if len(self.rgb_sum_acceleration30_data) == keep_count:
                self._graph_rgb_sum_acceleration30[:keep_count] = np.array(self.rgb_sum_acceleration30_data, dtype=np.float64)
            if len(self.transition_score_data) == keep_count:
                self._graph_transition_score[:keep_count] = np.array(self.transition_score_data, dtype=np.float64)
            if len(self.tri_x_data) == keep_count:
                self._graph_tri_x[:keep_count] = np.array(self.tri_x_data, dtype=np.float64)
            if len(self.tri_y_data) == keep_count:
                self._graph_tri_y[:keep_count] = np.array(self.tri_y_data, dtype=np.float64)

    def start_analysis(self):
        """Запуск активного анализа видеофайла с кадра 0 со сбросом графиков и фиксацией ROI."""
        with self._lock:
            if not self.source_is_file:
                return
            self.clear_data()
            self._seek_target_frame = 0
            self.is_analysis_started = True
            self.is_paused = False

    def reset_to_setup_mode(self):
        """Возврат в режим настройки ROI: очистка данных, перемотка в начало, пауза, разблокировка ROI."""
        with self._lock:
            if not self.source_is_file:
                return
            self.clear_data()
            self._seek_target_frame = 0
            self.is_analysis_started = False
            self.is_paused = True

    def clear_data(self):
        with self._lock:
            self._clear_measurements()
            self._graph_len = 0
            self._graph_start = 0
            self.graph_version += 1
            self.last_save_ms = -1e9
            self.excel_rows_written = 0

    def toggle_pause(self):
        with self._lock:
            if not self.is_analysis_started:
                self.is_analysis_started = True
                self.is_paused = False
                return False
            self.is_paused = not self.is_paused
            return self.is_paused

    def set_paused(self, paused):
        with self._lock:
            if not paused and not self.is_analysis_started:
                self.is_analysis_started = True
            self.is_paused = bool(paused)
            return self.is_paused

    def set_speed(self, speed):
        with self._lock:
            self.playback_speed = max(0.1, min(16.0, float(speed)))
            return self.playback_speed

    def seek_relative(self, seconds):
        with self._lock:
            if not self.source_is_file:
                return
            fps = self._file_fps if self._file_fps > 0 else 25.0
            delta_f = int(seconds * fps)
            target = max(0, self._file_frame_index + delta_f)
            if self.total_frames > 0:
                target = min(target, self.total_frames - 1)
            self._seek_target_frame = target

    def seek_to_frame(self, frame_idx):
        with self._lock:
            if not self.source_is_file:
                return
            target = max(0, int(frame_idx))
            if self.total_frames > 0:
                target = min(target, self.total_frames - 1)
            self._seek_target_frame = target

    def seek_to_time_ms(self, time_ms):
        with self._lock:
            if not self.source_is_file:
                return
            fps = self._file_fps if self._file_fps > 0 else 25.0
            target_frame = int((float(time_ms) / 1000.0) * fps)
            if self.total_frames > 0:
                target_frame = max(0, min(target_frame, self.total_frames - 1))
            self._seek_target_frame = target_frame

    def _graph_values(self, array):
        """Return the graph ring buffer in chronological order."""
        if self._graph_len <= 0:
            return np.empty(0, dtype=np.float64)
        end = self._graph_start + self._graph_len
        if end <= len(array):
            return array[self._graph_start:end]
        return np.concatenate((array[self._graph_start:], array[:end % len(array)]))

    def _ensure_graph_capacity(self, required):
        """Grow graph storage up to ``max_points`` while preserving ordering."""
        current = len(self._graph_t)
        if required <= current or current >= self.max_points:
            return
        capacity = min(self.max_points, max(required, current * 2 if current else min(4096, self.max_points)))
        previous = {name: self._graph_values(getattr(self, name)) for name in self._GRAPH_ARRAY_NAMES}
        for name in self._GRAPH_ARRAY_NAMES:
            replacement = np.empty(capacity, dtype=np.float64)
            values = previous[name]
            if len(values):
                replacement[:len(values)] = values
            setattr(self, name, replacement)
        self._graph_start = 0

    def _append_graph_point(self, t, r, g, b, log_v, log_bg_v, tri_x, tri_y,
                            rgb_sum, rgb_sum_smooth, rgb_sum_slope10, rgb_sum_slope30,
                            rgb_vector_speed30, chromaticity_speed30, k_chrom_previous,
                            log_ratio_speed30, rgb_sum_acceleration30, transition_score):
        self._ensure_graph_capacity(self._graph_len + 1)
        capacity = len(self._graph_t)
        if capacity == 0:
            return
        if self._graph_len < capacity:
            index = (self._graph_start + self._graph_len) % capacity
            self._graph_len += 1
        else:
            # History is a fixed-size ring: discard the oldest point in O(1),
            # rather than growing arrays for an unbounded live session.
            index = self._graph_start
            self._graph_start = (self._graph_start + 1) % capacity

        values = (
            t, r, g, b, log_v, log_bg_v, rgb_sum, rgb_sum_smooth,
            rgb_sum_slope10, rgb_sum_slope30, rgb_vector_speed30,
            chromaticity_speed30, k_chrom_previous, log_ratio_speed30,
            rgb_sum_acceleration30, transition_score, tri_x, tri_y,
        )
        for name, value in zip(self._GRAPH_ARRAY_NAMES, values):
            getattr(self, name)[index] = value

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.csv_logger:
            self.csv_logger.close()

    def _update_fastslow(self, key, time_ms, value):
        try:
            v = float(value)
            if not np.isfinite(v):
                return float('nan')
            state = self._ema_state.get(key)
            if state is None:
                self._ema_state[key] = {'fast': v, 'slow': v, 'last_t': float(time_ms)}
                return 0.0

            dt_ms = max(0.0, float(time_ms) - float(state.get('last_t', time_ms)))
            dt_s = dt_ms / 1000.0
            tau_fast_s = max(0.001, EMA_FAST_TAU_MS / 1000.0)
            tau_slow_s = max(0.001, EMA_SLOW_TAU_MS / 1000.0)
            alpha_fast = 1.0 - float(np.exp(-dt_s / tau_fast_s))
            alpha_slow = 1.0 - float(np.exp(-dt_s / tau_slow_s))

            state['fast'] = state['fast'] + alpha_fast * (v - state['fast'])
            state['slow'] = state['slow'] + alpha_slow * (v - state['slow'])
            state['last_t'] = float(time_ms)
            return float(state['fast'] - state['slow'])
        except Exception:
            return float('nan')

    def _loop(self):
        while self._running:
            loop_started = time.perf_counter()

            # Handle seeking
            target_f = None
            paused = False
            with self._lock:
                target_f = self._seek_target_frame
                self._seek_target_frame = None
                paused = self.is_paused

            if target_f is not None:
                try:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, target_f)
                    self._file_frame_index = target_f
                    fps_val = self._file_fps if self._file_fps > 0 else 25.0
                    seek_ms = (target_f / fps_val) * 1000.0
                    with self._lock:
                        self._truncate_data_to_time(seek_ms)
                    ret_seek, frame_seek = self.cap.read()
                    if ret_seek and frame_seek is not None:
                        mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f = compute_roi_means(
                            frame_seek, self.config
                        )
                        with self._lock:
                            self.latest_frame = frame_seek
                            self.current_means = (mean_b, mean_g, mean_r)
                            self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                except Exception:
                    pass

            if paused:
                if self.latest_frame is not None:
                    try:
                        mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f = compute_roi_means(
                            self.latest_frame, self.config
                        )
                        with self._lock:
                            self.current_means = (mean_b, mean_g, mean_r)
                            self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                    except Exception:
                        pass
                else:
                    try:
                        if self.source_is_file:
                            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret_p, frame_p = self.cap.read()
                        if ret_p and frame_p is not None:
                            mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f = compute_roi_means(
                                frame_p, self.config
                            )
                            with self._lock:
                                self.latest_frame = frame_p
                                self.current_means = (mean_b, mean_g, mean_r)
                                self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                                self._file_frame_index = 0
                            if self.source_is_file:
                                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass
                time.sleep(0.015)
                continue

            # Быстрый пропуск кадров (fast-forward grab) при высоких скоростях 4x / 8x
            if self.source_is_file and self.playback_speed >= 3.0:
                skip_count = int(self.playback_speed / 2.0) - 1
                for _ in range(skip_count):
                    if not self.cap.grab():
                        break
                    self._file_frame_index += 1

            ret, frame = self.cap.read()
            if not ret:
                if self.source_is_file:
                    with self._lock:
                        self.is_paused = True
                    time.sleep(0.05)
                    if not self.config.get('auto_stop_file', True):
                        continue
                    else:
                        self._running = False
                        break
                time.sleep(0.001)
                continue

            mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f = compute_roi_means(
                frame, self.config
            )
            if self.source_is_file and self._file_fps > 0:
                elapsed_ms = (self._file_frame_index / self._file_fps) * 1000.0
            else:
                elapsed_ms = (time.time() - self.start_time) * 1000.0
            self._file_frame_index += 1
            row_to_write = None

            with self._lock:
                if self.source_is_file and self.time_data and elapsed_ms < self.time_data[-1]:
                    self._truncate_data_to_time(elapsed_ms)
                self.latest_frame = frame
                self.current_means = (mean_b, mean_g, mean_r)
                self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                self.frame_count += 1

            if not self.is_analysis_started:
                # В режиме настройки ROI (предпросмотр) только вычисляем средние для экрана,
                # но не записываем точки в графики, логгеры и Excel
                time.sleep(0.01)
                continue

            with self._lock:
                if elapsed_ms >= self.last_save_ms + self.save_interval_ms:
                    rounded_ms = int((elapsed_ms // 10) * 10)
                    log_br = compute_log_br(mean_b, mean_r)
                    log_bg = compute_log_bg(mean_b, mean_g)
                    rgb_sum, r_frac, g_frac, b_frac, tri_x, tri_y = compute_rgb_triangle(mean_r, mean_g, mean_b)

                    self.time_data.append(rounded_ms)
                    self.r_data.append(mean_r)
                    self.g_data.append(mean_g)
                    self.b_data.append(mean_b)
                    self.log_data.append(log_br)
                    self.log_bg_data.append(log_bg)
                    self.rgb_sum_data.append(rgb_sum)
                    rgb_sum_smooth = compute_window_mean(
                        self.time_data, self.rgb_sum_data,
                        window_ms=RGB_SUM_SMOOTH_WINDOW_MS, min_points=RATE_MIN_POINTS
                    )
                    self.rgb_sum_smooth_data.append(rgb_sum_smooth)
                    rgb_sum_slope10 = compute_window_rate(
                        self.time_data, self.rgb_sum_smooth_data,
                        window_ms=RGB_SUM_SLOPE_FAST_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS
                    )
                    rgb_sum_slope30 = compute_window_rate(
                        self.time_data, self.rgb_sum_smooth_data,
                        window_ms=RGB_SUM_SLOPE_SLOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS
                    )
                    self.rgb_sum_slope10_data.append(rgb_sum_slope10)
                    self.rgb_sum_slope30_data.append(rgb_sum_slope30)
                    self.tri_x_data.append(tri_x)
                    self.tri_y_data.append(tri_y)

                    r_slope30 = compute_window_rate(self.time_data, self.r_data, window_ms=RGB_VECTOR_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    g_slope30 = compute_window_rate(self.time_data, self.g_data, window_ms=RGB_VECTOR_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    b_slope30 = compute_window_rate(self.time_data, self.b_data, window_ms=RGB_VECTOR_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    if np.isfinite(r_slope30) and np.isfinite(g_slope30) and np.isfinite(b_slope30):
                        rgb_vector_speed30 = float(np.sqrt(r_slope30 ** 2 + g_slope30 ** 2 + b_slope30 ** 2))
                    else:
                        rgb_vector_speed30 = float('nan')

                    tri_x_slope30 = compute_window_rate(self.time_data, self.tri_x_data, window_ms=CHROMATICITY_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    tri_y_slope30 = compute_window_rate(self.time_data, self.tri_y_data, window_ms=CHROMATICITY_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    if np.isfinite(tri_x_slope30) and np.isfinite(tri_y_slope30):
                        chromaticity_speed30 = float(np.sqrt(tri_x_slope30 ** 2 + tri_y_slope30 ** 2))
                    else:
                        chromaticity_speed30 = float('nan')

                    k_chrom_previous = compute_chrom_distance_from_previous_state(self.time_data, self.tri_x_data, self.tri_y_data)

                    log_br_slope30 = compute_window_rate(self.time_data, self.log_data, window_ms=LOG_RATIO_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    log_bg_slope30 = compute_window_rate(self.time_data, self.log_bg_data, window_ms=LOG_RATIO_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS)
                    if np.isfinite(log_br_slope30) and np.isfinite(log_bg_slope30):
                        log_ratio_speed30 = float(np.sqrt(log_br_slope30 ** 2 + log_bg_slope30 ** 2))
                    else:
                        log_ratio_speed30 = float('nan')

                    rgb_sum_acceleration30 = compute_window_rate(
                        self.time_data, self.rgb_sum_slope30_data,
                        window_ms=RGB_SUM_ACCEL_WINDOW_MS, min_points=RGB_SUM_SLOPE_MIN_POINTS
                    )
                    transition_score = compute_transition_score(
                        rgb_vector_speed30, chromaticity_speed30, rgb_sum_slope30,
                        k_chrom_previous, log_ratio_speed30
                    )

                    self.rgb_vector_speed30_data.append(rgb_vector_speed30)
                    self.chromaticity_speed30_data.append(chromaticity_speed30)
                    self.k_chrom_previous_data.append(k_chrom_previous)
                    self.log_ratio_speed30_data.append(log_ratio_speed30)
                    self.rgb_sum_acceleration30_data.append(rgb_sum_acceleration30)
                    self.transition_score_data.append(transition_score)

                    row_to_write = [
                        rounded_ms, mean_r, mean_g, mean_b, log_br, log_bg,
                        rgb_sum, r_frac, g_frac, b_frac, tri_x, tri_y,
                        rgb_sum_smooth, rgb_sum_slope10, rgb_sum_slope30,
                        rgb_vector_speed30, chromaticity_speed30, k_chrom_previous,
                        log_ratio_speed30, rgb_sum_acceleration30, transition_score,
                    ]
                    self.saved_data.append(row_to_write)
                    self.last_save_ms = rounded_ms
                    self._append_graph_point(
                        rounded_ms, mean_r, mean_g, mean_b, log_br, log_bg,
                        tri_x, tri_y, rgb_sum, rgb_sum_smooth, rgb_sum_slope10, rgb_sum_slope30,
                        rgb_vector_speed30, chromaticity_speed30, k_chrom_previous,
                        log_ratio_speed30, rgb_sum_acceleration30, transition_score,
                    )
                    self.graph_version += 1

            if row_to_write is not None and self.csv_logger:
                self.csv_logger.write_row(row_to_write)

            target_ms = self.processing_interval_ms
            if self.source_is_file and self._file_fps > 0:
                step = max(1, int(self.playback_speed / 2.0)) if self.playback_speed >= 3.0 else 1
                target_ms = (1000.0 * step) / (self._file_fps * max(0.05, self.playback_speed))
            spent_ms = (time.perf_counter() - loop_started) * 1000.0
            sleep_ms = max(0.0, target_ms - spent_ms)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

    def snapshot(self, copy_frame=True):
        with self._lock:
            frame = self.latest_frame.copy() if (copy_frame and self.latest_frame is not None) else None
            return {
                'frame': frame,
                'means': self.current_means,
                'roi_info': self.roi_info,
                'graph_t': self._graph_values(self._graph_t),
                'graph_r': self._graph_values(self._graph_r),
                'graph_g': self._graph_values(self._graph_g),
                'graph_b': self._graph_values(self._graph_b),
                'graph_log': self._graph_values(self._graph_log),
                'graph_log_bg': self._graph_values(self._graph_log_bg),
                'graph_rgb_sum': self._graph_values(self._graph_rgb_sum),
                'graph_rgb_sum_smooth': self._graph_values(self._graph_rgb_sum_smooth),
                'graph_rgb_sum_slope10': self._graph_values(self._graph_rgb_sum_slope10),
                'graph_rgb_sum_slope30': self._graph_values(self._graph_rgb_sum_slope30),
                'graph_rgb_vector_speed30': self._graph_values(self._graph_rgb_vector_speed30),
                'graph_chromaticity_speed30': self._graph_values(self._graph_chromaticity_speed30),
                'graph_k_chrom_previous': self._graph_values(self._graph_k_chrom_previous),
                'graph_log_ratio_speed30': self._graph_values(self._graph_log_ratio_speed30),
                'graph_rgb_sum_acceleration30': self._graph_values(self._graph_rgb_sum_acceleration30),
                'graph_transition_score': self._graph_values(self._graph_transition_score),
                'graph_rate_b': np.empty(0, dtype=np.float64),
                'graph_rate_r': np.empty(0, dtype=np.float64),
                'graph_rate_g': np.empty(0, dtype=np.float64),
                'graph_rate_log': np.empty(0, dtype=np.float64),
                'graph_rate_log_bg': np.empty(0, dtype=np.float64),
                'graph_fastslow_log': np.empty(0, dtype=np.float64),
                'graph_fastslow_log_bg': np.empty(0, dtype=np.float64),
                'graph_tri_x': self._graph_values(self._graph_tri_x),
                'graph_tri_y': self._graph_values(self._graph_tri_y),
                'graph_version': self.graph_version,
                'point_count': self._graph_len,
                'frame_count': self.frame_count,
                'saved_data': self.saved_data,
                'raw_csv_path': self.raw_csv_path,
                'is_paused': self.is_paused,
                'is_analysis_started': self.is_analysis_started,
                'playback_speed': self.playback_speed,
                'file_frame_index': self._file_frame_index,
                'total_frames': self.total_frames,
                'duration_sec': self.duration_sec,
                'file_fps': self._file_fps,
            }
