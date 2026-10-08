import cv2
import numpy as np
import time
import threading
from collections import deque

from ..utils.math_utils import (
    compute_log_br, compute_log_bg, compute_rgb_triangle,
    compute_window_mean_with_current, compute_window_rate_with_current,
    compute_chrom_distance_from_previous_state_with_current,
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
    EMA_FAST_TAU_MS, EMA_SLOW_TAU_MS, MAX_POINTS
)

class CameraWorker:
    def __init__(self, cap, config, start_time, save_interval_ms=10, max_points=MAX_POINTS, raw_csv_path=None):
        self.cap = cap
        self.config = config
        self.start_time = start_time
        self.save_interval_ms = save_interval_ms
        self._lock = threading.RLock()
        self._running = False
        self._thread = None

        self.max_points = max(1, int(max_points))
        self._graph_compaction_margin = max(256, self.max_points // 10)
        self._graph_capacity_limit = self.max_points + self._graph_compaction_margin
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
        self._processing_durations_ms = deque(maxlen=512)
        self._processing_sample_count = 0
        self._processing_total_ms = 0.0
        self._processing_max_ms = 0.0
        self._processing_overrun_count = 0
        self._frame_width = None
        self._frame_height = None
        self.graph_version = 0
        self._graph_len = 0
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
                    self._frame_height, self._frame_width = frame_init.shape[:2]
                    self.current_means = (mean_b, mean_g, mean_r)
                    self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                    self._file_frame_index = 0
                if self.source_is_file:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            except Exception as init_err:
                pass

    def _truncate_data_to_time(self, target_ms):
        """Обрезает все буферы данных до момента target_ms при перемотке назад,
        гарантируя монотонность оси X и единственную чистую линию графика."""
        if not self.time_data:
            self.last_save_ms = target_ms - self.save_interval_ms
            return

        target_val = float(target_ms)
        if target_val <= 50.0:
            self.time_data.clear()
            self.r_data.clear()
            self.g_data.clear()
            self.b_data.clear()
            self.log_data.clear()
            self.log_bg_data.clear()
            self.rgb_sum_data.clear()
            self.rgb_sum_smooth_data.clear()
            self.rgb_sum_slope10_data.clear()
            self.rgb_sum_slope30_data.clear()
            self.tri_x_data.clear()
            self.tri_y_data.clear()
            self.rgb_vector_speed30_data.clear()
            self.chromaticity_speed30_data.clear()
            self.k_chrom_previous_data.clear()
            self.log_ratio_speed30_data.clear()
            self.rgb_sum_acceleration30_data.clear()
            self.transition_score_data.clear()
            self.rate_b_data.clear()
            self.rate_r_data.clear()
            self.rate_g_data.clear()
            self.rate_log_data.clear()
            self.rate_log_bg_data.clear()
            self.fastslow_log_data.clear()
            self.fastslow_log_bg_data.clear()
            self.saved_data.clear()
            self.point_count = 0
            self._graph_len = 0
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
            self.time_data.clear()
            self.r_data.clear()
            self.g_data.clear()
            self.b_data.clear()
            self.log_data.clear()
            self.log_bg_data.clear()
            self.rgb_sum_data.clear()
            self.rgb_sum_smooth_data.clear()
            self.rgb_sum_slope10_data.clear()
            self.rgb_sum_slope30_data.clear()
            self.tri_x_data.clear()
            self.tri_y_data.clear()
            self.rgb_vector_speed30_data.clear()
            self.chromaticity_speed30_data.clear()
            self.k_chrom_previous_data.clear()
            self.log_ratio_speed30_data.clear()
            self.rgb_sum_acceleration30_data.clear()
            self.transition_score_data.clear()
            self.rate_b_data.clear()
            self.rate_r_data.clear()
            self.rate_g_data.clear()
            self.rate_log_data.clear()
            self.rate_log_bg_data.clear()
            self.fastslow_log_data.clear()
            self.fastslow_log_bg_data.clear()
            self.saved_data.clear()
            self.point_count = 0
            self._graph_len = 0
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
        self._graph_len = keep_count
        self.last_save_ms = self.time_data[-1] if self.time_data else (target_val - self.save_interval_ms)
        self.graph_version += 1

        # Синхронизируем массивы графиков
        if keep_count > 0:
            if len(self._graph_t) < keep_count:
                alloc_size = max(keep_count * 2, int(self.config.get('max_points', MAX_POINTS)))
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
            self.time_data.clear()
            self.r_data.clear()
            self.g_data.clear()
            self.b_data.clear()
            self.log_data.clear()
            self.log_bg_data.clear()
            self.rgb_sum_data.clear()
            self.rgb_sum_smooth_data.clear()
            self.rgb_sum_slope10_data.clear()
            self.rgb_sum_slope30_data.clear()
            self.tri_x_data.clear()
            self.tri_y_data.clear()
            self.rgb_vector_speed30_data.clear()
            self.chromaticity_speed30_data.clear()
            self.k_chrom_previous_data.clear()
            self.log_ratio_speed30_data.clear()
            self.rgb_sum_acceleration30_data.clear()
            self.transition_score_data.clear()
            self.saved_data.clear()
            self.point_count = 0
            self._graph_len = 0
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

    def _compact_graph_history(self):
        """Keep graph buffers bounded without dropping rows from saved_data/CSV."""
        keep_count = min(self.max_points, self._graph_len)
        if keep_count <= 0 or keep_count == self._graph_len:
            return
        start = self._graph_len - keep_count
        capacity = max(keep_count, min(self._graph_capacity_limit, len(self._graph_t)))
        array_names = (
            "_graph_t", "_graph_r", "_graph_g", "_graph_b", "_graph_log", "_graph_log_bg",
            "_graph_rgb_sum", "_graph_rgb_sum_smooth", "_graph_rgb_sum_slope10",
            "_graph_rgb_sum_slope30", "_graph_rgb_vector_speed30", "_graph_chromaticity_speed30",
            "_graph_k_chrom_previous", "_graph_log_ratio_speed30", "_graph_rgb_sum_acceleration30",
            "_graph_transition_score", "_graph_tri_x", "_graph_tri_y",
        )
        old_length = self._graph_len
        for name in array_names:
            old_array = getattr(self, name)
            compacted = np.empty(capacity, dtype=np.float64)
            compacted[:keep_count] = old_array[start:old_length]
            setattr(self, name, compacted)
        self._graph_len = keep_count

    def _append_graph_point(self, t, r, g, b, log_v, log_bg_v, tri_x, tri_y,
                            rgb_sum, rgb_sum_smooth, rgb_sum_slope10, rgb_sum_slope30,
                            rgb_vector_speed30, chromaticity_speed30, k_chrom_previous,
                            log_ratio_speed30, rgb_sum_acceleration30, transition_score):
        if self._graph_len >= self._graph_capacity_limit:
            self._compact_graph_history()
        n = self._graph_len + 1
        if n > len(self._graph_t):
            preferred_cap = len(self._graph_t) * 2 if len(self._graph_t) else 4096
            new_cap = max(n, min(self._graph_capacity_limit, preferred_cap))
            self._graph_t = np.resize(self._graph_t, new_cap)
            self._graph_r = np.resize(self._graph_r, new_cap)
            self._graph_g = np.resize(self._graph_g, new_cap)
            self._graph_b = np.resize(self._graph_b, new_cap)
            self._graph_log = np.resize(self._graph_log, new_cap)
            self._graph_log_bg = np.resize(self._graph_log_bg, new_cap)
            self._graph_rgb_sum = np.resize(self._graph_rgb_sum, new_cap)
            self._graph_rgb_sum_smooth = np.resize(self._graph_rgb_sum_smooth, new_cap)
            self._graph_rgb_sum_slope10 = np.resize(self._graph_rgb_sum_slope10, new_cap)
            self._graph_rgb_sum_slope30 = np.resize(self._graph_rgb_sum_slope30, new_cap)
            self._graph_rgb_vector_speed30 = np.resize(self._graph_rgb_vector_speed30, new_cap)
            self._graph_chromaticity_speed30 = np.resize(self._graph_chromaticity_speed30, new_cap)
            self._graph_k_chrom_previous = np.resize(self._graph_k_chrom_previous, new_cap)
            self._graph_log_ratio_speed30 = np.resize(self._graph_log_ratio_speed30, new_cap)
            self._graph_rgb_sum_acceleration30 = np.resize(self._graph_rgb_sum_acceleration30, new_cap)
            self._graph_transition_score = np.resize(self._graph_transition_score, new_cap)
            self._graph_tri_x = np.resize(self._graph_tri_x, new_cap)
            self._graph_tri_y = np.resize(self._graph_tri_y, new_cap)
        idx = self._graph_len
        self._graph_t[idx] = t
        self._graph_r[idx] = r
        self._graph_g[idx] = g
        self._graph_b[idx] = b
        self._graph_log[idx] = log_v
        self._graph_log_bg[idx] = log_bg_v
        self._graph_rgb_sum[idx] = rgb_sum
        self._graph_rgb_sum_smooth[idx] = rgb_sum_smooth
        self._graph_rgb_sum_slope10[idx] = rgb_sum_slope10
        self._graph_rgb_sum_slope30[idx] = rgb_sum_slope30
        self._graph_rgb_vector_speed30[idx] = rgb_vector_speed30
        self._graph_chromaticity_speed30[idx] = chromaticity_speed30
        self._graph_k_chrom_previous[idx] = k_chrom_previous
        self._graph_log_ratio_speed30[idx] = log_ratio_speed30
        self._graph_rgb_sum_acceleration30[idx] = rgb_sum_acceleration30
        self._graph_transition_score[idx] = transition_score
        self._graph_tri_x[idx] = tri_x
        self._graph_tri_y[idx] = tri_y
        self._graph_len = n

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

            # During ROI dragging the live camera must keep delivering fresh frames.
            # Defer ROI statistics until the drag is released so the preview never freezes.
            roi_dragging = bool(self.config.get('_roi_dragging', False))
            if roi_dragging and not self.source_is_file:
                h_f, w_f = frame.shape[:2]
                x = int(self.config.get('roi_x', 0))
                y = int(self.config.get('roi_y', 0))
                w = int(self.config.get('roi_w', 20))
                h = int(self.config.get('roi_h', 20))
                safe_x = max(0, min(x, w_f - 1))
                safe_y = max(0, min(y, h_f - 1))
                safe_w = max(10, min(w, w_f - safe_x))
                safe_h = max(10, min(h, h_f - safe_y))
                mean_b, mean_g, mean_r = self.current_means
            else:
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
                self._frame_height, self._frame_width = frame.shape[:2]
                self.current_means = (mean_b, mean_g, mean_r)
                self.roi_info = (safe_x, safe_y, safe_w, safe_h, h_f, w_f)
                self.frame_count += 1

            if roi_dragging and not self.source_is_file:
                # Camera acquisition/display continues; do not commit analytical points
                # until the ROI becomes stable again.
                time.sleep(0.001)
                continue

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
                    # Reuse the contiguous NumPy history already maintained for
                    # the live graphs. Binary-searching its time axis and slicing
                    # the active window avoids rebuilding whole Python deques for
                    # every channel and every new measurement.
                    history_times = self._graph_t[:self._graph_len]
                    history_start_index = max(0, self._graph_len - max(0, len(self.time_data) - 1))
                    rgb_sum_smooth = compute_window_mean_with_current(
                        history_times, self._graph_rgb_sum[:self._graph_len], rounded_ms, rgb_sum,
                        window_ms=RGB_SUM_SMOOTH_WINDOW_MS, history_start_index=history_start_index
                    )
                    self.rgb_sum_smooth_data.append(rgb_sum_smooth)
                    rgb_sum_slope10 = compute_window_rate_with_current(
                        history_times, self._graph_rgb_sum_smooth[:self._graph_len], rounded_ms, rgb_sum_smooth,
                        window_ms=RGB_SUM_SLOPE_FAST_MS, history_start_index=history_start_index
                    )
                    rgb_sum_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_rgb_sum_smooth[:self._graph_len], rounded_ms, rgb_sum_smooth,
                        window_ms=RGB_SUM_SLOPE_SLOW_MS, history_start_index=history_start_index
                    )
                    self.rgb_sum_slope10_data.append(rgb_sum_slope10)
                    self.rgb_sum_slope30_data.append(rgb_sum_slope30)
                    self.tri_x_data.append(tri_x)
                    self.tri_y_data.append(tri_y)

                    r_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_r[:self._graph_len], rounded_ms, mean_r,
                        window_ms=RGB_VECTOR_WINDOW_MS, history_start_index=history_start_index
                    )
                    g_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_g[:self._graph_len], rounded_ms, mean_g,
                        window_ms=RGB_VECTOR_WINDOW_MS, history_start_index=history_start_index
                    )
                    b_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_b[:self._graph_len], rounded_ms, mean_b,
                        window_ms=RGB_VECTOR_WINDOW_MS, history_start_index=history_start_index
                    )
                    if np.isfinite(r_slope30) and np.isfinite(g_slope30) and np.isfinite(b_slope30):
                        rgb_vector_speed30 = float(np.sqrt(r_slope30 ** 2 + g_slope30 ** 2 + b_slope30 ** 2))
                    else:
                        rgb_vector_speed30 = float('nan')

                    tri_x_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_tri_x[:self._graph_len], rounded_ms, tri_x,
                        window_ms=CHROMATICITY_WINDOW_MS, history_start_index=history_start_index
                    )
                    tri_y_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_tri_y[:self._graph_len], rounded_ms, tri_y,
                        window_ms=CHROMATICITY_WINDOW_MS, history_start_index=history_start_index
                    )
                    if np.isfinite(tri_x_slope30) and np.isfinite(tri_y_slope30):
                        chromaticity_speed30 = float(np.sqrt(tri_x_slope30 ** 2 + tri_y_slope30 ** 2))
                    else:
                        chromaticity_speed30 = float('nan')

                    k_chrom_previous = compute_chrom_distance_from_previous_state_with_current(
                        history_times, self._graph_tri_x[:self._graph_len],
                        self._graph_tri_y[:self._graph_len], rounded_ms, tri_x, tri_y,
                        history_start_index=history_start_index
                    )

                    log_br_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_log[:self._graph_len], rounded_ms, log_br,
                        window_ms=LOG_RATIO_WINDOW_MS, history_start_index=history_start_index
                    )
                    log_bg_slope30 = compute_window_rate_with_current(
                        history_times, self._graph_log_bg[:self._graph_len], rounded_ms, log_bg,
                        window_ms=LOG_RATIO_WINDOW_MS, history_start_index=history_start_index
                    )
                    if np.isfinite(log_br_slope30) and np.isfinite(log_bg_slope30):
                        log_ratio_speed30 = float(np.sqrt(log_br_slope30 ** 2 + log_bg_slope30 ** 2))
                    else:
                        log_ratio_speed30 = float('nan')

                    rgb_sum_acceleration30 = compute_window_rate_with_current(
                        history_times, self._graph_rgb_sum_slope30[:self._graph_len], rounded_ms, rgb_sum_slope30,
                        window_ms=RGB_SUM_ACCEL_WINDOW_MS, history_start_index=history_start_index
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
            with self._lock:
                self._processing_durations_ms.append(spent_ms)
                self._processing_sample_count += 1
                self._processing_total_ms += spent_ms
                self._processing_max_ms = max(self._processing_max_ms, spent_ms)
                if spent_ms > target_ms:
                    self._processing_overrun_count += 1
            sleep_ms = max(0.0, target_ms - spent_ms)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

    def performance_summary(self):
        """Return bounded, privacy-safe timing counters for the session manifest."""
        with self._lock:
            samples = list(self._processing_durations_ms)
            sample_count = self._processing_sample_count
            total_ms = self._processing_total_ms
            max_ms = self._processing_max_ms
            overruns = self._processing_overrun_count
            frame_count = self.frame_count
            point_count = len(self.saved_data)
            history_capacity = self.time_data.maxlen
            width = self._frame_width
            height = self._frame_height
        if samples:
            ordered = sorted(samples)
            p95_index = max(0, min(len(ordered) - 1, int(np.ceil(0.95 * len(ordered))) - 1))
            p95_ms = round(float(ordered[p95_index]), 4)
        else:
            p95_ms = None
        return {
            "processed_frames": int(frame_count),
            "analysis_points": int(point_count),
            "timing_sample_count": int(sample_count),
            "timing_window_samples": len(samples),
            "analysis_interval_ms": int(self.processing_interval_ms),
            "processing_mean_ms": round(float(total_ms / sample_count), 4) if sample_count else None,
            "processing_p95_ms": p95_ms,
            "processing_max_ms": round(float(max_ms), 4) if sample_count else None,
            "interval_overrun_count": int(overruns),
            "graph_history_capacity": int(history_capacity) if history_capacity is not None else None,
            "frame_width": int(width) if width is not None else None,
            "frame_height": int(height) if height is not None else None,
        }

    def snapshot(self, copy_frame=True):
        with self._lock:
            frame = self.latest_frame.copy() if (copy_frame and self.latest_frame is not None) else None
            graph_start = max(0, self._graph_len - self.max_points)
            graph_end = self._graph_len
            return {
                'frame': frame,
                'means': self.current_means,
                'roi_info': self.roi_info,
                'graph_t': self._graph_t[graph_start:graph_end],
                'graph_r': self._graph_r[graph_start:graph_end],
                'graph_g': self._graph_g[graph_start:graph_end],
                'graph_b': self._graph_b[graph_start:graph_end],
                'graph_log': self._graph_log[graph_start:graph_end],
                'graph_log_bg': self._graph_log_bg[graph_start:graph_end],
                'graph_rgb_sum': self._graph_rgb_sum[graph_start:graph_end],
                'graph_rgb_sum_smooth': self._graph_rgb_sum_smooth[graph_start:graph_end],
                'graph_rgb_sum_slope10': self._graph_rgb_sum_slope10[graph_start:graph_end],
                'graph_rgb_sum_slope30': self._graph_rgb_sum_slope30[graph_start:graph_end],
                'graph_rgb_vector_speed30': self._graph_rgb_vector_speed30[graph_start:graph_end],
                'graph_chromaticity_speed30': self._graph_chromaticity_speed30[graph_start:graph_end],
                'graph_k_chrom_previous': self._graph_k_chrom_previous[graph_start:graph_end],
                'graph_log_ratio_speed30': self._graph_log_ratio_speed30[graph_start:graph_end],
                'graph_rgb_sum_acceleration30': self._graph_rgb_sum_acceleration30[graph_start:graph_end],
                'graph_transition_score': self._graph_transition_score[graph_start:graph_end],
                'graph_rate_b': np.empty(0, dtype=np.float64),
                'graph_rate_r': np.empty(0, dtype=np.float64),
                'graph_rate_g': np.empty(0, dtype=np.float64),
                'graph_rate_log': np.empty(0, dtype=np.float64),
                'graph_rate_log_bg': np.empty(0, dtype=np.float64),
                'graph_fastslow_log': np.empty(0, dtype=np.float64),
                'graph_fastslow_log_bg': np.empty(0, dtype=np.float64),
                'graph_tri_x': self._graph_tri_x[graph_start:graph_end],
                'graph_tri_y': self._graph_tri_y[graph_start:graph_end],
                'graph_version': self.graph_version,
                'point_count': len(self.saved_data),
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
