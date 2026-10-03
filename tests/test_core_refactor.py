"""Focused regression tests for the refactored non-GUI core."""

import os
import tempfile
import unittest

import numpy as np

from src.analysis.camera_worker import CameraWorker
from src.analysis.ffmpeg_capture import FFMpegFileCapture
from src.analysis.annotations import Annotation
from src.data.csv_logger import CsvLogger
from src.data.excel_exporter import save_to_excel
from src.utils.formulas import FormulaValidationError, evaluate_formula, validate_formula
from src.utils.helpers import compute_roi_means, normalize_roi
from src.utils.math_utils import (
    compute_chrom_distance_from_previous_state,
    compute_window_mean,
    compute_window_rate,
)


class FormulaTests(unittest.TestCase):
    def test_formula_evaluates_numeric_arrays(self):
        values = evaluate_formula(
            "np.clip((r + b) / 2, 0, 255)",
            {"r": np.array([10.0, 20.0]), "b": np.array([30.0, 40.0])},
        )
        np.testing.assert_allclose(values, [20.0, 30.0])

    def test_formula_rejects_python_escape_hatches(self):
        for formula in ("np.__dict__", "().__class__", "__import__('os')"):
            with self.assertRaises(FormulaValidationError):
                validate_formula(formula)

    def test_formula_rejects_unknown_name_at_evaluation(self):
        with self.assertRaises(FormulaValidationError):
            evaluate_formula("missing_metric + 1", {"r": 1.0})


class SignalMathTests(unittest.TestCase):
    def test_window_functions_respect_minimum_sample_count(self):
        times = [0, 1000, 2000]
        signal = [1.0, 2.0, 3.0]
        self.assertEqual(compute_window_rate(times, signal, window_ms=5000, min_points=4), 0.0)
        self.assertTrue(np.isnan(compute_window_mean(times, signal, window_ms=5000, min_points=4)))

    def test_chromaticity_baseline_requires_real_history(self):
        # The previous implementation used the latest sample as a substitute
        # baseline and could emit a false confident value during warm-up.
        times = [0, 1000, 2000, 3000, 4000]
        xs = [0.1, 0.1, 0.1, 0.2, 0.3]
        ys = [0.2, 0.2, 0.2, 0.2, 0.2]
        result = compute_chrom_distance_from_previous_state(
            times, xs, ys, lookback_ms=2000, gap_ms=1000, min_points=4
        )
        self.assertTrue(np.isnan(result))


class RoiTests(unittest.TestCase):
    def test_roi_is_consistent_for_tiny_frames_and_bad_settings(self):
        frame = np.zeros((4, 5, 3), dtype=np.uint8)
        config = {"roi_x": "bad", "roi_y": 50, "roi_w": -100, "roi_h": None, "roi_shape": "circle"}
        self.assertEqual(normalize_roi(frame, config), (0, 3, 5, 1))
        _b, _g, _r, x, y, w, h, frame_h, frame_w = compute_roi_means(frame, config)
        self.assertEqual((x, y, w, h), (0, 3, 5, 1))
        self.assertEqual((frame_h, frame_w), (4, 5))

    def test_roi_defaults_when_config_is_incomplete(self):
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        result = compute_roi_means(frame, {})
        self.assertEqual(result[3:7], (0, 0, 30, 20))


class StorageTests(unittest.TestCase):
    def test_relative_csv_path_is_valid_and_malformed_row_does_not_close_logger(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                logger = CsvLogger("emergency.csv")
                self.assertTrue(logger.is_open)
                self.assertFalse(logger.write_row([]))
                self.assertTrue(logger.is_open)
                self.assertTrue(logger.write_row([1000, 1.0, 2.0, 3.0]))
                logger.close()
                self.assertTrue(os.path.isfile("emergency.csv"))
            finally:
                os.chdir(old_cwd)

    def test_excel_escapes_annotation_formula(self):
        with tempfile.TemporaryDirectory() as directory:
            output = save_to_excel(
                directory,
                [[0, 10.0, 20.0, 30.0, 0.1, 0.2, 60.0, 0.1, 0.2, 0.3,
                  0.4, 0.5, 60.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
                annotations=[Annotation(0, "=HYPERLINK(\"https://example.invalid\")")],
            )
            from openpyxl import load_workbook
            workbook = load_workbook(output, data_only=False)
            self.assertEqual(workbook["Все метки"]["M2"].value, "'=HYPERLINK(\"https://example.invalid\")")


class AnnotationTests(unittest.TestCase):
    def test_corrupted_annotation_time_is_normalized_for_sorting(self):
        from src.analysis.annotations import AnnotationManager
        manager = AnnotationManager.from_dict_list([
            {"time_ms": "not-a-time", "description": "corrupt"},
            {"time_ms": 1000, "description": "valid"},
        ])
        self.assertEqual([item.time_ms for item in manager.get_annotations()], [0.0, 1000.0])


class GraphBufferTests(unittest.TestCase):
    def test_graph_history_is_a_bounded_chronological_ring(self):
        worker = CameraWorker(None, {"analysis_interval_ms": 10}, 0.0, max_points=3)
        for index in range(5):
            worker._append_graph_point(
                index, index, index, index, index, index, index, index,
                index, index, index, index, index, index, index, index,
                index, index,
            )
        snapshot = worker.snapshot(copy_frame=False)
        np.testing.assert_array_equal(snapshot["graph_t"], [2.0, 3.0, 4.0])
        np.testing.assert_array_equal(snapshot["graph_r"], [2.0, 3.0, 4.0])
        self.assertEqual(snapshot["point_count"], 3)

    def test_clear_resets_every_series_and_ema_state(self):
        worker = CameraWorker(None, {"analysis_interval_ms": 10}, 0.0, max_points=3)
        worker.rate_b_data.append(1.0)
        worker.fastslow_log_data.append(2.0)
        worker._ema_state["signal"] = {"fast": 1.0}
        worker.clear_data()
        self.assertFalse(worker.rate_b_data)
        self.assertFalse(worker.fastslow_log_data)
        self.assertEqual(worker._ema_state, {})


class FfmpegFileCaptureTests(unittest.TestCase):
    class _ChunkedStream:
        def __init__(self, payload, chunk_size):
            self.payload = bytearray(payload)
            self.chunk_size = chunk_size

        def read(self, requested):
            if not self.payload:
                return b""
            take = min(requested, self.chunk_size, len(self.payload))
            value = bytes(self.payload[:take])
            del self.payload[:take]
            return value

    class _Process:
        def __init__(self, payload):
            self.stdout = FfmpegFileCaptureTests._ChunkedStream(payload, 2)

        def poll(self):
            return None

    def test_partial_pipe_reads_are_assembled_into_a_frame(self):
        capture = FFMpegFileCapture.__new__(FFMpegFileCapture)
        capture.width = 2
        capture.height = 1
        capture._opened = True
        capture._current_frame_idx = 0
        capture._proc = self._Process(bytes(range(6)))
        ok, frame = capture.read()
        self.assertTrue(ok)
        np.testing.assert_array_equal(frame.reshape(-1), np.arange(6, dtype=np.uint8))
        self.assertEqual(capture._current_frame_idx, 1)


if __name__ == "__main__":
    unittest.main()
