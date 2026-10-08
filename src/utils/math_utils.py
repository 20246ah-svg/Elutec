import numpy as np
import math
from collections import deque

# NumPy's vectorized full-history pass is faster for small buffers; reverse
# deque scans are used only after histories grow beyond this crossover.
_DEQUE_FAST_THRESHOLD = 60000

from ..config import (
    LOG_Y_MARGIN_FRAC,
    RATE_WINDOW_MS, RATE_MIN_POINTS,
    RGB_SUM_SMOOTH_WINDOW_MS,
    CHROM_BASELINE_LOOKBACK_MS, CHROM_BASELINE_GAP_MS, CHROM_BASELINE_MIN_POINTS,
    TRANSITION_NOISE_RGB_VECTOR, TRANSITION_NOISE_CHROM_SPEED,
    TRANSITION_NOISE_RGB_SUM_SLOPE, TRANSITION_NOISE_K_CHROM,
    TRANSITION_NOISE_LOG_RATIO_SPEED, TRANSITION_Z_CAP,
    DELTA_FAST_MS
)

def compute_log_br(mean_b, mean_r):
    try:
        b = float(mean_b)
        r = float(mean_r)
    except Exception:
        return float('nan')
    if not np.isfinite(b) or not np.isfinite(r) or r <= 0 or b <= 0:
        return float('nan')
    return float(np.log10(b / r))

def compute_log_bg(mean_b, mean_g):
    try:
        b = float(mean_b)
        g = float(mean_g)
    except Exception:
        return float('nan')
    if not np.isfinite(b) or not np.isfinite(g) or g <= 0 or b <= 0:
        return float('nan')
    return float(np.log10(b / g))

def compute_rgb_triangle(mean_r, mean_g, mean_b):
    try:
        r = float(mean_r)
        g = float(mean_g)
        b = float(mean_b)
        total = r + g + b
        if (not np.isfinite(total)) or total <= 0:
            return float('nan'), float('nan'), float('nan'), float('nan'), float('nan'), float('nan')
        r_frac = r / total
        g_frac = g / total
        b_frac = b / total
        tri_x = g_frac + 0.5 * b_frac
        tri_y = 0.8660254037844386 * b_frac
        return total, r_frac, g_frac, b_frac, tri_x, tri_y
    except Exception:
        return float('nan'), float('nan'), float('nan'), float('nan'), float('nan'), float('nan')

def adaptive_log_y_range(log_vals, margin_frac=LOG_Y_MARGIN_FRAC):
    if log_vals is None or len(log_vals) == 0:
        return -1.0, 1.0
    arr = np.asarray(log_vals, dtype=np.float64)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return -1.0, 1.0
    y_min = float(valid.min())
    y_max = float(valid.max())
    if y_min == y_max:
        y_min -= 0.1
        y_max += 0.1
    else:
        span = y_max - y_min
        margin = max(span * margin_frac, 0.02)
        y_min -= margin
        y_max += margin
    return y_min, y_max


def _py_scalar(value):
    if value is None:
        return None
    try:
        if isinstance(value, np.ndarray):
            if value.size == 0:
                return None
            if value.ndim == 0:
                return value.item()
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        return value
    except Exception:
        return value


def nice_y_axis_ticks(y_min, y_max, target_ticks=6):
    try:
        if not np.isfinite(y_min) or not np.isfinite(y_max):
            return [(-1.0, '-1'), (0.0, '0'), (1.0, '1')]
        if y_min >= y_max:
            v = float(y_min)
            return [(v, f"{v:.3g}")]

        span = y_max - y_min
        raw_step = span / max(int(target_ticks), 2)
        if raw_step <= 0:
            raw_step = 0.1
        magnitude = 10 ** np.floor(np.log10(raw_step))
        norm = raw_step / magnitude
        if norm <= 1:
            step = magnitude
        elif norm <= 2:
            step = 2 * magnitude
        elif norm <= 5:
            step = 5 * magnitude
        else:
            step = 10 * magnitude
        step = float(step)
        start = float(np.ceil(y_min / step - 1e-9) * step)
        decimals = max(0, int(-np.floor(np.log10(step)))) if step < 1 else (1 if step < 10 else 0)
        ticks = []
        v = start
        guard = 0
        while v <= y_max + step * 1e-6 and guard < 200:
            if y_min - step * 0.01 <= v <= y_max + step * 0.01:
                label = f"{v:.{decimals}f}" if decimals else f"{v:.0f}"
                ticks.append((float(v), label))
            v += step
            guard += 1
        if len(ticks) < 2:
            ticks = [
                (float(y_min), f"{y_min:.3g}"),
                (float(y_max), f"{y_max:.3g}"),
            ]
        return ticks
    except Exception:
        return [(float(y_min) if np.isfinite(y_min) else -1.0, str(y_min)), (float(y_max) if np.isfinite(y_max) else 1.0, str(y_max))]

def _reverse_aligned_pairs(time_values, signal_values):
    """Yield aligned samples newest-first for monotonic deque histories.

    The worker keeps timestamps ordered and appends values as they arrive. If
    series differ by one point while a derived value is being calculated, the
    extra newest elements are skipped to retain the old prefix-alignment rules.
    """
    count = min(len(time_values), len(signal_values))
    if count <= 0:
        return
    time_iter = iter(reversed(time_values))
    signal_iter = iter(reversed(signal_values))
    for _ in range(len(time_values) - count):
        next(time_iter, None)
    for _ in range(len(signal_values) - count):
        next(signal_iter, None)
    for time_value, signal_value in zip(time_iter, signal_iter):
        try:
            t = float(time_value)
        except (TypeError, ValueError, OverflowError):
            t = float('nan')
        try:
            y = float(signal_value)
        except (TypeError, ValueError, OverflowError):
            y = float('nan')
        yield t, y


def _aligned_arrays(time_values, signal_values):
    t_all = np.asarray(time_values, dtype=np.float64)
    y_all = np.asarray(signal_values, dtype=np.float64)
    count = min(t_all.size, y_all.size)
    return t_all[:count], y_all[:count]


def _recent_deque_window(time_values, signal_values, window_ms):
    """Extract only the active time window; return None for invalid timestamps."""
    pairs = iter(_reverse_aligned_pairs(time_values, signal_values))
    first = next(pairs, None)
    if first is None or not np.isfinite(first[0]):
        return None
    end_t = first[0]
    start_t = end_t - float(window_ms)
    selected_t = []
    selected_y = []
    for t, y in (first,):
        if np.isfinite(t) and np.isfinite(y) and t >= start_t:
            selected_t.append(t)
            selected_y.append(y)
    for t, y in pairs:
        if np.isfinite(t) and t < start_t:
            break
        if np.isfinite(t) and np.isfinite(y) and t >= start_t:
            selected_t.append(t)
            selected_y.append(y)
    return end_t, selected_t, selected_y


def compute_window_rate(time_ms_values, signal_values, window_ms=RATE_WINDOW_MS, min_points=RATE_MIN_POINTS):
    try:
        if time_ms_values is None or signal_values is None:
            return 0.0
        if len(time_ms_values) == 0 or len(signal_values) == 0:
            return 0.0

        selected = None
        if (isinstance(time_ms_values, deque) and isinstance(signal_values, deque)
                and len(time_ms_values) > _DEQUE_FAST_THRESHOLD):
            selected = _recent_deque_window(time_ms_values, signal_values, window_ms)

        if selected is not None and len(selected[1]) >= 2:
            end_t, selected_t, selected_y = selected
            t = (np.asarray(selected_t, dtype=np.float64) - end_t) / 1000.0
            y = np.asarray(selected_y, dtype=np.float64)
        else:
            # Preserve the original fallback for sparse/invalid windows: when
            # fewer than two points are in range, regress over all finite data.
            t_all, y_all = _aligned_arrays(time_ms_values, signal_values)
            if t_all.size == 0 or y_all.size == 0:
                return 0.0
            end_t = float(t_all[-1])
            start_t = end_t - float(window_ms)
            mask = (t_all >= start_t) & np.isfinite(t_all) & np.isfinite(y_all)
            if int(np.count_nonzero(mask)) < 2:
                mask = np.isfinite(t_all) & np.isfinite(y_all)
            if int(np.count_nonzero(mask)) < 2:
                return 0.0
            t = (t_all[mask] - end_t) / 1000.0
            y = y_all[mask]

        t_mean = float(np.mean(t))
        y_mean = float(np.mean(y))
        denom = float(np.sum((t - t_mean) ** 2))
        if denom <= 0 or not np.isfinite(denom):
            return 0.0
        rate = float(np.sum((t - t_mean) * (y - y_mean)) / denom)
        return rate if np.isfinite(rate) else 0.0
    except Exception:
        return 0.0


def compute_window_mean(time_ms_values, signal_values, window_ms=RGB_SUM_SMOOTH_WINDOW_MS, min_points=RATE_MIN_POINTS):
    try:
        if time_ms_values is None or signal_values is None:
            return float('nan')
        if len(time_ms_values) == 0 or len(signal_values) == 0:
            return float('nan')

        selected = None
        if (isinstance(time_ms_values, deque) and isinstance(signal_values, deque)
                and len(time_ms_values) > _DEQUE_FAST_THRESHOLD):
            selected = _recent_deque_window(time_ms_values, signal_values, window_ms)
        if selected is not None and selected[1]:
            return float(np.mean(np.asarray(selected[2], dtype=np.float64)))

        t_all, y_all = _aligned_arrays(time_ms_values, signal_values)
        if t_all.size == 0:
            return float('nan')
        end_t = float(t_all[-1])
        start_t = end_t - float(window_ms)
        mask = (t_all >= start_t) & np.isfinite(t_all) & np.isfinite(y_all)
        if int(np.count_nonzero(mask)) < 1:
            mask = np.isfinite(t_all) & np.isfinite(y_all)
        if int(np.count_nonzero(mask)) < 1:
            return float('nan')
        return float(np.mean(y_all[mask]))
    except Exception:
        return float('nan')


def compute_window_median_before(time_ms_values, signal_values, lookback_ms=CHROM_BASELINE_LOOKBACK_MS,
                                 gap_ms=CHROM_BASELINE_GAP_MS, min_points=CHROM_BASELINE_MIN_POINTS):
    try:
        if time_ms_values is None or signal_values is None:
            return float('nan')
        if len(time_ms_values) == 0 or len(signal_values) == 0:
            return float('nan')

        if (isinstance(time_ms_values, deque) and isinstance(signal_values, deque)
                and len(time_ms_values) > _DEQUE_FAST_THRESHOLD):
            pairs = iter(_reverse_aligned_pairs(time_ms_values, signal_values))
            first = next(pairs, None)
            if first is not None and np.isfinite(first[0]):
                current_t = first[0]
                t1 = current_t - float(gap_ms) - float(lookback_ms)
                t2 = current_t - float(gap_ms)
                baseline = []
                latest_valid = None
                for t, y in (first,):
                    if np.isfinite(t) and np.isfinite(y):
                        latest_valid = y
                        if t1 <= t <= t2:
                            baseline.append(y)
                for t, y in pairs:
                    if np.isfinite(t) and np.isfinite(y):
                        if latest_valid is None:
                            latest_valid = y
                        if t1 <= t <= t2:
                            baseline.append(y)
                    if np.isfinite(t) and t < t1 and (baseline or latest_valid is not None):
                        break
                if baseline:
                    return float(np.median(np.asarray(baseline, dtype=np.float64)))
                if latest_valid is not None:
                    return float(latest_valid)

        # General-sequence fallback retains support for non-deque callers and
        # malformed/non-monotonic timestamp data.
        t_all, y_all = _aligned_arrays(time_ms_values, signal_values)
        if t_all.size == 0:
            return float('nan')
        current_t = float(t_all[-1])
        t1 = current_t - float(gap_ms) - float(lookback_ms)
        t2 = current_t - float(gap_ms)
        mask = (t_all >= t1) & (t_all <= t2) & np.isfinite(t_all) & np.isfinite(y_all)
        if int(np.count_nonzero(mask)) >= 1:
            return float(np.median(y_all[mask]))
        valid = np.isfinite(t_all) & np.isfinite(y_all)
        if int(np.count_nonzero(valid)) >= 1:
            return float(y_all[valid][-1])
        return float('nan')
    except Exception:
        return float('nan')

def _aligned_history_view(time_ms_values, signal_values, current_time_ms, history_start_ms=None,
                          history_start_index=None):
    """Return zero-copy views of retained arrays that precede the new point."""
    t_all = np.asarray(time_ms_values, dtype=np.float64)
    y_all = np.asarray(signal_values, dtype=np.float64)
    count = min(t_all.size, y_all.size)
    t_all = t_all[:count]
    y_all = y_all[:count]
    current_t = float(current_time_ms)
    stop = int(np.searchsorted(t_all, current_t, side='right')) if count else 0
    start = 0
    if history_start_index is not None:
        try:
            start = int(history_start_index)
        except (TypeError, ValueError, OverflowError):
            start = 0
    elif history_start_ms is not None and count:
        try:
            start = int(np.searchsorted(t_all, float(history_start_ms), side='left'))
        except (TypeError, ValueError, OverflowError):
            start = 0
    start = max(0, min(start, stop))
    return t_all[start:stop], y_all[start:stop], current_t


def _full_history_with_current(history_t, history_y, current_t, current_signal_value):
    return (
        np.concatenate((history_t, np.asarray([current_t], dtype=np.float64))),
        np.concatenate((history_y, np.asarray([current_signal_value], dtype=np.float64))),
    )


def compute_window_rate_with_current(time_ms_values, signal_values, current_time_ms, current_signal_value,
                                     window_ms=RATE_WINDOW_MS, history_start_ms=None,
                                     history_start_index=None):
    """Fast array-backed regression for CameraWorker's new point.

    Binary-search the contiguous graph history and run NumPy over only the
    active window. The retained full history is materialized only for the rare
    legacy fallback where the window contains fewer than two finite samples.
    """
    try:
        history_t, history_y, end_t = _aligned_history_view(
            time_ms_values, signal_values, current_time_ms, history_start_ms, history_start_index
        )
        current_y = float(current_signal_value)
        start_t = end_t - float(window_ms)
        start_idx = int(np.searchsorted(history_t, start_t, side='left'))
        recent_t = history_t[start_idx:]
        recent_y = history_y[start_idx:]
        recent_mask = np.isfinite(recent_t) & np.isfinite(recent_y)
        recent_count = int(np.count_nonzero(recent_mask))
        current_valid = np.isfinite(end_t) and np.isfinite(current_y) and end_t >= start_t
        if recent_count + int(current_valid) >= 2:
            selected_t = recent_t[recent_mask]
            selected_y = recent_y[recent_mask]
            if current_valid:
                selected_t = np.concatenate((selected_t, np.asarray([end_t], dtype=np.float64)))
                selected_y = np.concatenate((selected_y, np.asarray([current_y], dtype=np.float64)))
            t = (selected_t - end_t) / 1000.0
            y = selected_y
        else:
            all_t, all_y = _full_history_with_current(history_t, history_y, end_t, current_y)
            mask = np.isfinite(all_t) & np.isfinite(all_y)
            if int(np.count_nonzero(mask)) < 2:
                return 0.0
            t = (all_t[mask] - end_t) / 1000.0
            y = all_y[mask]
        t_mean = float(np.mean(t))
        y_mean = float(np.mean(y))
        denom = float(np.sum((t - t_mean) ** 2))
        if denom <= 0 or not np.isfinite(denom):
            return 0.0
        rate = float(np.sum((t - t_mean) * (y - y_mean)) / denom)
        return rate if np.isfinite(rate) else 0.0
    except Exception:
        return 0.0


def compute_window_mean_with_current(time_ms_values, signal_values, current_time_ms, current_signal_value,
                                     window_ms=RGB_SUM_SMOOTH_WINDOW_MS, history_start_ms=None,
                                     history_start_index=None):
    try:
        history_t, history_y, end_t = _aligned_history_view(
            time_ms_values, signal_values, current_time_ms, history_start_ms, history_start_index
        )
        current_y = float(current_signal_value)
        start_t = end_t - float(window_ms)
        start_idx = int(np.searchsorted(history_t, start_t, side='left'))
        recent_t = history_t[start_idx:]
        recent_y = history_y[start_idx:]
        recent_mask = np.isfinite(recent_t) & np.isfinite(recent_y)
        recent_count = int(np.count_nonzero(recent_mask))
        current_valid = np.isfinite(end_t) and np.isfinite(current_y) and end_t >= start_t
        if recent_count + int(current_valid) > 0:
            selected = recent_y[recent_mask]
            if current_valid:
                selected = np.concatenate((selected, np.asarray([current_y], dtype=np.float64)))
            return float(np.mean(selected))
        all_t, all_y = _full_history_with_current(history_t, history_y, end_t, current_y)
        valid = np.isfinite(all_t) & np.isfinite(all_y)
        return float(np.mean(all_y[valid])) if np.any(valid) else float('nan')
    except Exception:
        return float('nan')


def compute_window_median_before_with_current(time_ms_values, signal_values, current_time_ms,
                                              current_signal_value, lookback_ms=CHROM_BASELINE_LOOKBACK_MS,
                                              gap_ms=CHROM_BASELINE_GAP_MS, history_start_ms=None,
                                              history_start_index=None):
    try:
        history_t, history_y, end_t = _aligned_history_view(
            time_ms_values, signal_values, current_time_ms, history_start_ms, history_start_index
        )
        current_y = float(current_signal_value)
        t1 = end_t - float(gap_ms) - float(lookback_ms)
        t2 = end_t - float(gap_ms)
        start_idx = int(np.searchsorted(history_t, t1, side='left'))
        end_idx = int(np.searchsorted(history_t, t2, side='right'))
        baseline_t = history_t[start_idx:end_idx]
        baseline_y = history_y[start_idx:end_idx]
        valid_baseline = np.isfinite(baseline_t) & np.isfinite(baseline_y)
        if np.any(valid_baseline):
            return float(np.median(baseline_y[valid_baseline]))
        if np.isfinite(end_t) and np.isfinite(current_y):
            return current_y
        valid = np.isfinite(history_t) & np.isfinite(history_y)
        if np.any(valid):
            return float(history_y[valid][-1])
        return float('nan')
    except Exception:
        return float('nan')


def compute_chrom_distance_from_previous_state_with_current(
        time_ms_values, tri_x_values, tri_y_values, current_time_ms, current_tri_x, current_tri_y,
        lookback_ms=CHROM_BASELINE_LOOKBACK_MS, gap_ms=CHROM_BASELINE_GAP_MS,
        min_points=CHROM_BASELINE_MIN_POINTS, history_start_ms=None, history_start_index=None):
    try:
        if time_ms_values is None or tri_x_values is None or tri_y_values is None:
            return float('nan')
        if history_start_index is not None:
            available = max(0, min(len(time_ms_values), len(tri_x_values), len(tri_y_values)) - int(history_start_index))
        else:
            available = min(len(time_ms_values), len(tri_x_values), len(tri_y_values))
        if available + 1 < min_points:
            return float('nan')
        x_now = float(current_tri_x)
        y_now = float(current_tri_y)
        if not (np.isfinite(x_now) and np.isfinite(y_now)):
            return float('nan')
        x0 = compute_window_median_before_with_current(
            time_ms_values, tri_x_values, current_time_ms, current_tri_x,
            lookback_ms, gap_ms, history_start_ms, history_start_index
        )
        y0 = compute_window_median_before_with_current(
            time_ms_values, tri_y_values, current_time_ms, current_tri_y,
            lookback_ms, gap_ms, history_start_ms, history_start_index
        )
        if not (np.isfinite(x0) and np.isfinite(y0)):
            return float('nan')
        return float(np.sqrt((x_now - x0) ** 2 + (y_now - y0) ** 2))
    except Exception:
        return float('nan')


def compute_chrom_distance_from_previous_state(time_ms_values, tri_x_values, tri_y_values,
                                                lookback_ms=CHROM_BASELINE_LOOKBACK_MS,
                                                gap_ms=CHROM_BASELINE_GAP_MS,
                                                min_points=CHROM_BASELINE_MIN_POINTS):
    try:
        if tri_x_values is None or tri_y_values is None or time_ms_values is None:
            return float('nan')
        if len(time_ms_values) < min_points or len(tri_x_values) < min_points or len(tri_y_values) < min_points:
            return float('nan')
        x_now = float(tri_x_values[-1])
        y_now = float(tri_y_values[-1])
        if not (np.isfinite(x_now) and np.isfinite(y_now)):
            return float('nan')
        x0 = compute_window_median_before(time_ms_values, tri_x_values, lookback_ms, gap_ms, min_points)
        y0 = compute_window_median_before(time_ms_values, tri_y_values, lookback_ms, gap_ms, min_points)
        if not (np.isfinite(x0) and np.isfinite(y0)):
            return float('nan')
        return float(np.sqrt((x_now - x0) ** 2 + (y_now - y0) ** 2))
    except Exception:
        return float('nan')

def _norm_transition_component(value, noise, cap=TRANSITION_Z_CAP, absolute=True):
    try:
        v = float(value)
        if not np.isfinite(v):
            return 0.0
        if absolute:
            v = abs(v)
        noise = max(float(noise), 1e-12)
        return float(min(max(v / noise, 0.0), float(cap)))
    except Exception:
        return 0.0

def compute_transition_score(rgb_vector_speed, chromaticity_speed, rgb_sum_slope30,
                             k_chrom_previous, log_ratio_speed):
    try:
        score = (
            0.30 * _norm_transition_component(rgb_vector_speed, TRANSITION_NOISE_RGB_VECTOR) +
            0.25 * _norm_transition_component(chromaticity_speed, TRANSITION_NOISE_CHROM_SPEED) +
            0.20 * _norm_transition_component(rgb_sum_slope30, TRANSITION_NOISE_RGB_SUM_SLOPE) +
            0.15 * _norm_transition_component(k_chrom_previous, TRANSITION_NOISE_K_CHROM) +
            0.10 * _norm_transition_component(log_ratio_speed, TRANSITION_NOISE_LOG_RATIO_SPEED)
        )
        return float(score)
    except Exception:
        return float('nan')

def compute_window_delta(time_ms_values, signal_values, window_ms=DELTA_FAST_MS):
    try:
        if time_ms_values is None or signal_values is None:
            return float('nan')
        if len(time_ms_values) < 2 or len(signal_values) < 2:
            return float('nan')

        t_all = np.asarray(time_ms_values, dtype=np.float64)
        y_all = np.asarray(signal_values, dtype=np.float64)
        finite = np.isfinite(t_all) & np.isfinite(y_all)
        if int(np.count_nonzero(finite)) < 2:
            return float('nan')

        valid_idx = np.where(finite)[0]
        current_idx = int(valid_idx[-1])
        current_t = float(t_all[current_idx])
        current_y = float(y_all[current_idx])
        target_t = current_t - float(window_ms)

        prev_candidates = valid_idx[t_all[valid_idx] <= target_t]
        if prev_candidates.size == 0:
            return float('nan')
        prev_idx = int(prev_candidates[-1])
        return float(current_y - float(y_all[prev_idx]))
    except Exception:
        return float('nan')

