import unittest

import numpy as np

from src.analysis.camera_worker import CameraWorker
from src.config import MAX_POINTS


class CameraWorkerMemoryTests(unittest.TestCase):
    def test_graph_buffers_roll_over_but_full_measurements_are_retained(self):
        capacity = 64
        worker = CameraWorker(None, {}, 0.0, max_points=capacity)

        for index in range(400):
            worker.time_data.append(index)
            worker.saved_data.append([index, float(index)])
            worker._append_graph_point(
                index, index, index + 1, index + 2, index / 10, index / 20,
                index / 100, index / 200, index * 3, index * 3,
                index / 2, index / 3, index / 4, index / 5,
                index / 6, index / 7, index / 8, index / 9,
            )

        snapshot = worker.snapshot(copy_frame=False)
        expected = np.arange(400 - capacity, 400, dtype=np.float64)
        np.testing.assert_array_equal(snapshot["graph_t"], expected)
        self.assertEqual(snapshot["point_count"], 400)
        self.assertEqual(len(snapshot["saved_data"]), 400)
        self.assertEqual(len(worker.time_data), capacity)
        self.assertLessEqual(worker._graph_len, worker._graph_capacity_limit)
        self.assertLessEqual(len(worker._graph_t), worker._graph_capacity_limit)

    def test_default_graph_history_uses_configured_limit(self):
        worker = CameraWorker(None, {}, 0.0)
        self.assertEqual(worker.max_points, MAX_POINTS)
        self.assertEqual(worker.time_data.maxlen, MAX_POINTS)


if __name__ == "__main__":
    unittest.main()
