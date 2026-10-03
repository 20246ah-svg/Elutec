import numpy as np
import math

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

def compute_window_rate(time_ms_values, signal_values, window_ms=RATE_WINDOW_MS, min_points=RATE_MIN_POINTS):
    try:
        if time_ms_values is None or signal_values is None:
            return 0.0
        if len(time_ms_values) == 0 or len(signal_values) == 0:
            return 0.0
        t_all = np.asarray(time_ms_values, dtype=np.float64)
        y_all = np.asarray(signal_values, dtype=np.float64)
        if t_all.size == 0 or y_all.size == 0:
            return 0.0
        n_all = min(t_all.size, y_all.size)
        t_all = t_all[:n_all]
        y_all = y_all[:n_all]
        end_t = float(t_all[-1])
        start_t = end_t - float(window_ms)
        mask = (t_all >= start_t) & np.isfinite(t_all) & np.isfinite(y_all)
        count = int(np.count_nonzero(mask))

        if count < 2:
            mask = np.isfinite(t_all) & np.isfinite(y_all)
            count = int(np.count_nonzero(mask))
        if count < 2:
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
        t_all = np.asarray(time_ms_values, dtype=np.float64)
        y_all = np.asarray(signal_values, dtype=np.float64)
        n_all = min(t_all.size, y_all.size)
        if n_all == 0:
            return float('nan')
        t_all = t_all[:n_all]
        y_all = y_all[:n_all]
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
        t_all = np.asarray(time_ms_values, dtype=np.float64)
        y_all = np.asarray(signal_values, dtype=np.float64)
        n_all = min(t_all.size, y_all.size)
        t_all = t_all[:n_all]
        y_all = y_all[:n_all]
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

