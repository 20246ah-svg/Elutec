import unittest
from collections import deque

try:
    import numpy as np
    from src.utils.math_utils import (
        compute_chrom_distance_from_previous_state_with_current,
        compute_window_mean,
        compute_window_mean_with_current,
        compute_window_median_before,
        compute_window_median_before_with_current,
        compute_window_rate,
        compute_window_rate_with_current,
    )
except ImportError:  # Runtime dependencies are listed in requirements.txt.
    np = None


def _reference_rate(time_values, signal_values, window_ms):
    try:
        t_all = np.asarray(time_values, dtype=np.float64)
        y_all = np.asarray(signal_values, dtype=np.float64)
        count = min(t_all.size, y_all.size)
        t_all = t_all[:count]
        y_all = y_all[:count]
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
        result = float(np.sum((t - t_mean) * (y - y_mean)) / denom)
        return result if np.isfinite(result) else 0.0
    except Exception:
        return 0.0


def _reference_mean(time_values, signal_values, window_ms):
    t_all = np.asarray(time_values, dtype=np.float64)
    y_all = np.asarray(signal_values, dtype=np.float64)
    count = min(t_all.size, y_all.size)
    t_all = t_all[:count]
    y_all = y_all[:count]
    end_t = float(t_all[-1])
    start_t = end_t - float(window_ms)
    mask = (t_all >= start_t) & np.isfinite(t_all) & np.isfinite(y_all)
    if int(np.count_nonzero(mask)) < 1:
        mask = np.isfinite(t_all) & np.isfinite(y_all)
    if int(np.count_nonzero(mask)) < 1:
        return float("nan")
    return float(np.mean(y_all[mask]))


def _reference_median_before(time_values, signal_values, lookback_ms, gap_ms):
    t_all = np.asarray(time_values, dtype=np.float64)
    y_all = np.asarray(signal_values, dtype=np.float64)
    count = min(t_all.size, y_all.size)
    t_all = t_all[:count]
    y_all = y_all[:count]
    current_t = float(t_all[-1])
    t1 = current_t - float(gap_ms) - float(lookback_ms)
    t2 = current_t - float(gap_ms)
    mask = (t_all >= t1) & (t_all <= t2) & np.isfinite(t_all) & np.isfinite(y_all)
    if int(np.count_nonzero(mask)) >= 1:
        return float(np.median(y_all[mask]))
    valid = np.isfinite(t_all) & np.isfinite(y_all)
    if int(np.count_nonzero(valid)) >= 1:
        return float(y_all[valid][-1])
    return float("nan")


@unittest.skipIf(np is None, "NumPy is required by ELUTEC runtime dependencies")
class WindowFunctionCompatibilityTests(unittest.TestCase):
    def _assert_same_number(self, actual, expected):
        if np.isnan(expected):
            self.assertTrue(np.isnan(actual))
        else:
            self.assertAlmostEqual(actual, expected, places=8)

    def test_large_monotonic_deques_match_full_history_reference(self):
        times = np.arange(20000, dtype=np.float64) * 10.0
        values = 100.0 + np.sin(times / 701.0) * 13.0
        values[15000] = np.nan
        time_history = deque(times, maxlen=len(times))
        value_history = deque(values, maxlen=len(values))

        self._assert_same_number(
            compute_window_rate(time_history, value_history, 30000.0),
            _reference_rate(time_history, value_history, 30000.0),
        )
        self._assert_same_number(
            compute_window_mean(time_history, value_history, 10000.0),
            _reference_mean(time_history, value_history, 10000.0),
        )
        self._assert_same_number(
            compute_window_median_before(time_history, value_history, 90000.0, 30000.0),
            _reference_median_before(time_history, value_history, 90000.0, 30000.0),
        )

    def test_prefix_alignment_when_deques_have_different_lengths(self):
        times = deque([0.0, 10.0, 20.0, 30.0, 40.0])
        shorter_values = deque([1.0, 2.0, 3.0, 4.0])
        longer_values = deque([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        for values in (shorter_values, longer_values):
            self._assert_same_number(
                compute_window_rate(times, values, 20.0),
                _reference_rate(times, values, 20.0),
            )
            self._assert_same_number(
                compute_window_mean(times, values, 20.0),
                _reference_mean(times, values, 20.0),
            )
            self._assert_same_number(
                compute_window_median_before(times, values, 20.0, 10.0),
                _reference_median_before(times, values, 20.0, 10.0),
            )

    def test_sparse_window_and_nan_fallback_match_existing_behavior(self):
        times = deque([0.0, 100.0, 200.0, 300.0])
        values = deque([1.0, np.nan, 4.0, 9.0])
        self._assert_same_number(
            compute_window_rate(times, values, 0.0),
            _reference_rate(times, values, 0.0),
        )
        self._assert_same_number(
            compute_window_mean(times, values, 0.0),
            _reference_mean(times, values, 0.0),
        )
        self._assert_same_number(
            compute_window_median_before(times, values, 0.0, 0.0),
            _reference_median_before(times, values, 0.0, 0.0),
        )

    def test_array_backed_new_sample_helpers_match_deque_reference(self):
        all_times = np.arange(12000, dtype=np.float64) * 15.0
        all_values = 100.0 + np.sin(all_times / 271.0) * 17.0
        all_values[5000] = np.nan
        history_times = all_times[:-1]
        history_values = all_values[:-1]
        current_time = all_times[-1]
        current_value = all_values[-1]
        full_times = deque(all_times)
        full_values = deque(all_values)

        self._assert_same_number(
            compute_window_rate_with_current(
                history_times, history_values, current_time, current_value, 30000.0
            ),
            _reference_rate(full_times, full_values, 30000.0),
        )
        self._assert_same_number(
            compute_window_mean_with_current(
                history_times, history_values, current_time, current_value, 10000.0
            ),
            _reference_mean(full_times, full_values, 10000.0),
        )
        self._assert_same_number(
            compute_window_median_before_with_current(
                history_times, history_values, current_time, current_value, 90000.0, 30000.0
            ),
            _reference_median_before(full_times, full_values, 90000.0, 30000.0),
        )

    def test_array_backed_history_index_matches_bounded_ring_buffer(self):
        all_times = np.floor(np.arange(40000, dtype=np.float64) * 5.0 / 10.0) * 10.0
        all_values = 40.0 + np.cos(np.arange(40000, dtype=np.float64) / 83.0)
        current_time = all_times[-1] + 10.0
        current_value = 42.0
        retained = 1000
        start = len(all_times) - retained
        expected_times = deque(list(all_times[start:]) + [current_time])
        expected_values = deque(list(all_values[start:]) + [current_value])

        self._assert_same_number(
            compute_window_rate_with_current(
                all_times, all_values, current_time, current_value, 30000.0,
                history_start_index=start,
            ),
            _reference_rate(expected_times, expected_values, 30000.0),
        )
        self._assert_same_number(
            compute_window_median_before_with_current(
                all_times, all_values, current_time, current_value, 90000.0, 30000.0,
                history_start_index=start,
            ),
            _reference_median_before(expected_times, expected_values, 90000.0, 30000.0),
        )

    def test_large_deque_reverse_scan_matches_full_history(self):
        times = np.arange(70000, dtype=np.float64) * 10.0
        values = np.sin(times / 707.0) * 25.0
        time_history = deque(times)
        value_history = deque(values)
        self._assert_same_number(
            compute_window_rate(time_history, value_history, 30000.0),
            _reference_rate(time_history, value_history, 30000.0),
        )
        self._assert_same_number(
            compute_window_median_before(time_history, value_history, 90000.0, 30000.0),
            _reference_median_before(time_history, value_history, 90000.0, 30000.0),
        )


if __name__ == "__main__":
    unittest.main()
