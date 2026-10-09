import unittest

from src.config import (
    DEFAULT_ANALYSIS_INTERVAL_MS,
    DEFAULT_GRAPH_UPDATE_MS,
    DEFAULT_PERFORMANCE_PROFILE,
    DEFAULT_PREVIEW_INTERVAL_MS,
    DEFAULT_PREVIEW_RGB_INTERVAL_MS,
    MAX_POINTS,
    PERFORMANCE_PROFILES,
)
from src.utils.hardware_advisor import (
    collect_system_profile,
    recommend_performance_profile,
)


class HardwareAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.system = {
            "logical_cores": 8,
            "memory_total_bytes": 16 * 1024 ** 3,
            "memory_available_bytes": 8 * 1024 ** 3,
        }

    def test_recommends_fastest_profile_with_measured_headroom(self):
        recommendation = recommend_performance_profile(
            self.system,
            {"processing_p95_ms": 2.0, "sample_source": "preview_frame"},
        )
        self.assertEqual(recommendation["profile"], "Турбо FPS (60-120 FPS)")
        self.assertEqual(
            recommendation["settings"],
            PERFORMANCE_PROFILES["Турбо FPS (60-120 FPS)"],
        )
        self.assertIn("P95", recommendation["reasons"][0])

    def test_camera_rate_prevents_unhelpful_over_sampling(self):
        recommendation = recommend_performance_profile(
            self.system,
            {"processing_p95_ms": 1.0, "sample_source": "preview_frame"},
            camera_fps=30.0,
        )
        self.assertEqual(recommendation["profile"], "Экономия ресурсов")
        self.assertTrue(any("не добавит кадров" in reason for reason in recommendation["reasons"]))

    def test_memory_pressure_avoids_large_history_profiles(self):
        low_memory = dict(self.system, memory_total_bytes=3 * 1024 ** 3)
        recommendation = recommend_performance_profile(
            low_memory,
            {"processing_p95_ms": 1.0, "sample_source": "preview_frame"},
        )
        self.assertIn(recommendation["profile"], ("Экономия ресурсов", "Слабый ПК / Ноутбук"))
        self.assertTrue(any("RAM" in reason for reason in recommendation["reasons"]))

    def test_extremely_slow_test_uses_safe_fallback(self):
        recommendation = recommend_performance_profile(
            self.system,
            {"processing_p95_ms": 100.0, "sample_source": "synthetic_frame"},
        )
        self.assertEqual(recommendation["profile"], "Слабый ПК / Ноутбук")
        self.assertIn("синтетическом кадре", " ".join(recommendation["reasons"]))

    def test_default_runtime_values_match_the_balanced_profile(self):
        balanced = PERFORMANCE_PROFILES[DEFAULT_PERFORMANCE_PROFILE]
        self.assertEqual(DEFAULT_ANALYSIS_INTERVAL_MS, balanced["analysis_interval_ms"])
        self.assertEqual(DEFAULT_GRAPH_UPDATE_MS, balanced["graph_update_ms"])
        self.assertEqual(MAX_POINTS, balanced["max_points"])
        self.assertEqual(DEFAULT_PREVIEW_INTERVAL_MS, balanced["preview_interval_ms"])
        self.assertEqual(DEFAULT_PREVIEW_RGB_INTERVAL_MS, balanced["preview_rgb_interval_ms"])

    def test_profile_does_not_collect_unique_device_identifiers(self):
        profile = collect_system_profile()
        self.assertIn("logical_cores", profile)
        self.assertNotIn("hostname", profile)
        self.assertNotIn("username", profile)
        self.assertNotIn("mac_address", profile)
        self.assertNotIn("serial_number", profile)


if __name__ == "__main__":
    unittest.main()
