import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import numpy as np
from src.gui.live_graph import LiveGraphWindow
from src.gui.settings_window import NOTIFICATION_DEFAULTS
from src.analysis.camera_worker import CameraWorker

class FakeViewBox:
    def __init__(self, x):
        self.x = list(x)
    def viewRange(self):
        return [list(self.x), [0, 1]]

class FakePlot:
    def __init__(self, x):
        self.vb = FakeViewBox(x)
        self.calls = []
    def getViewBox(self):
        return self.vb
    def setXRange(self, a, b, padding=0):
        self.calls.append((float(a), float(b), padding))
        self.vb.x = [float(a), float(b)]

class FakeWidget:
    def __init__(self, p):
        self.plot = p
    def getPlotItem(self):
        return self.plot

class Probe(LiveGraphWindow):
    pass

class Tests(unittest.TestCase):
    def test_x_sync(self):
        o = Probe.__new__(Probe)
        ps = [FakePlot((0, 5)), FakePlot((0, 10)), FakePlot((2, 30))]
        o._graph_items = [{'widget': FakeWidget(p)} for p in ps]
        o._ignore_view_change = False
        o._sync_all_x_ranges(0, 30)
        self.assertTrue(all(p.vb.x == [0.0, 30.0] for p in ps))

    def test_default_marks_settings(self):
        self.assertTrue(NOTIFICATION_DEFAULTS['auto_mark_arom_enabled'])
        self.assertTrue(NOTIFICATION_DEFAULTS['auto_mark_br_enabled'])
        self.assertTrue(NOTIFICATION_DEFAULTS['auto_mark_abr_enabled'])
        self.assertIn('auto_mark_arom_t_min_sec', NOTIFICATION_DEFAULTS)
        self.assertIn('auto_mark_arom_t_max_sec', NOTIFICATION_DEFAULTS)
        self.assertIn('auto_mark_br_arm_delay_sec', NOTIFICATION_DEFAULTS)

    def test_auto_mark_config_and_customization(self):
        o = Probe.__new__(Probe)
        o.notification_settings = {
            'auto_marks_enabled': True,
            'auto_mark_arom_enabled': True,
            'auto_mark_arom_color': '#85E889',
            'auto_mark_arom_label': '★ СМЕНА ВИАЛЫ — SAT → AROM',
        }
        c = o._auto_mark_config('arom')
        self.assertTrue(c['enabled'])
        self.assertEqual(c['color'], '#85E889')
        self.assertIn('SAT → AROM', c['description'])

        o.notification_settings['auto_mark_arom_enabled'] = False
        self.assertFalse(o._auto_mark_config('arom')['enabled'])

    def test_custom_rule_fires_once_and_rearms(self):
        class M:
            def __init__(self):
                self.annotations = []
            def add_annotation(self, *a, **k):
                self.annotations.append((a, k))

        o = Probe.__new__(Probe)
        o.notification_settings = {
            'auto_marks_enabled': True,
            'sound_alerts_enabled': True,
            'custom_auto_marks': [{
                'enabled': True, 'name': 'S', 'metric': 'RGB_sum_slope_30s',
                'operator': '>=', 'threshold': 2, 'color': '#123456',
                'description': 'hit', 'notify': False, 'sound': True,
                't_min_sec': 0.0, 't_max_sec': 3600.0
            }]
        }
        o._custom_auto_mark_active = {}
        o.annotation_manager = M()
        o._update_annotations = lambda: None
        o._persist_annotations = lambda: None
        o._show_toast = lambda x: None
        o._play_system_alert_sound = lambda: None

        o._check_custom_auto_marks(1000, 10, 20, 30, 3, 1)
        o._check_custom_auto_marks(2000, 10, 20, 30, 4, 1)
        self.assertEqual(len(o.annotation_manager.annotations), 1)

        o._check_custom_auto_marks(3000, 10, 20, 30, 1, 1)
        o._check_custom_auto_marks(4000, 10, 20, 30, 3, 1)
        self.assertEqual(len(o.annotation_manager.annotations), 2)

    def test_custom_rule_time_window_filtering(self):
        class M:
            def __init__(self):
                self.annotations = []
            def add_annotation(self, *a, **k):
                self.annotations.append((a, k))

        o = Probe.__new__(Probe)
        o.notification_settings = {
            'auto_marks_enabled': True,
            'sound_alerts_enabled': True,
            'custom_auto_marks': [{
                'enabled': True, 'name': 'WinTest', 'metric': 'Transition_score',
                'operator': '>=', 'threshold': 5.0, 'color': '#FF0000',
                'description': 'Window Test', 'notify': True, 'sound': True,
                't_min_sec': 10.0, 't_max_sec': 20.0
            }]
        }
        o._custom_auto_mark_active = {}
        o.annotation_manager = M()
        o._update_annotations = lambda: None
        o._persist_annotations = lambda: None
        o._show_toast = lambda x: None
        sounds_played = []
        o._play_system_alert_sound = lambda: sounds_played.append(1)

        # Before time window (t = 5 sec = 5000 ms) -> does not fire
        o._check_custom_auto_marks(5000, 10, 20, 30, 0, 7.0)
        self.assertEqual(len(o.annotation_manager.annotations), 0)
        self.assertEqual(len(sounds_played), 0)

        # Inside time window (t = 15 sec = 15000 ms) -> fires and plays sound
        o._check_custom_auto_marks(15000, 10, 20, 30, 0, 7.0)
        self.assertEqual(len(o.annotation_manager.annotations), 1)
        self.assertEqual(len(sounds_played), 1)

        # After time window (t = 25 sec = 25000 ms) -> does not fire
        o._custom_auto_mark_active = {} # reset active state
        o._check_custom_auto_marks(25000, 10, 20, 30, 0, 7.0)
        self.assertEqual(len(o.annotation_manager.annotations), 1)


    def test_detect_green_circle_roi_exact(self):
        import cv2
        from src.utils.helpers import detect_green_circle_roi
        # Create a frame with a green circle
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # BGR: pure green (0, 255, 0)
        cv2.circle(frame, (320, 240), 50, (0, 255, 0), -1)
        res = detect_green_circle_roi(frame)
        self.assertIsNotNone(res)
        cx, cy, r = res
        self.assertAlmostEqual(cx, 320, delta=1)
        self.assertAlmostEqual(cy, 240, delta=1)
        self.assertAlmostEqual(r, 50, delta=1)

    def test_detect_green_circle_roi_ring(self):
        import cv2
        from src.utils.helpers import detect_green_circle_roi
        # Create a frame with a green circle ring (thickness=2)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.circle(frame, (600, 350), 80, (0, 255, 0), 2)
        res = detect_green_circle_roi(frame)
        self.assertIsNotNone(res)
        cx, cy, r = res
        self.assertAlmostEqual(cx, 600, delta=1)
        self.assertAlmostEqual(cy, 350, delta=1)
        self.assertAlmostEqual(r, 80, delta=2)

    def test_detect_green_circle_roi_no_circle(self):
        from src.utils.helpers import detect_green_circle_roi
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        res = detect_green_circle_roi(frame)
        self.assertIsNone(res)


    def test_video_file_detection_and_quotes(self):
        from src.utils.helpers import is_video_file_path, is_video_file_source
        self.assertTrue(is_video_file_path('test.mp4'))
        self.assertTrue(is_video_file_path('"test.mp4"'))
        self.assertTrue(is_video_file_path("'test.mkv'"))
        self.assertFalse(is_video_file_path('0'))
        self.assertFalse(is_video_file_path('rtsp://192.168.1.10/live'))


    def test_new_video_settings_keys(self):
        self.assertIn('save_roi_on_video', NOTIFICATION_DEFAULTS)
        self.assertIn('snap_roi_green_circle_on_file', NOTIFICATION_DEFAULTS)
        self.assertTrue(NOTIFICATION_DEFAULTS['snap_roi_green_circle_on_file'])
        self.assertFalse(NOTIFICATION_DEFAULTS['save_roi_on_video'])

    def test_camera_worker_playback_controls(self):
        from src.analysis.camera_worker import CameraWorker
        class DummyCap:
            def __init__(self):
                self.pos = 0
            def isOpened(self):
                return True
            def get(self, prop):
                import cv2
                if prop == cv2.CAP_PROP_FPS:
                    return 25.0
                if prop == cv2.CAP_PROP_FRAME_COUNT:
                    return 1000
                return 0
            def set(self, prop, val):
                self.pos = val
                return True
            def read(self):
                frame = np.zeros((100, 100, 3), dtype=np.uint8)
                return True, frame

        cap = DummyCap()
        worker = CameraWorker(cap, {'source_is_file': True, 'playback_speed': 1.0}, 0.0)
        self.assertTrue(worker.is_paused)
        self.assertFalse(worker.is_analysis_started)
        self.assertEqual(worker.playback_speed, 1.0)
        self.assertEqual(worker.total_frames, 1000)

        # Start analysis
        worker.start_analysis()
        self.assertFalse(worker.is_paused)
        self.assertTrue(worker.is_analysis_started)

        # Pause toggle
        worker.toggle_pause()
        self.assertTrue(worker.is_paused)
        worker.set_paused(False)
        self.assertFalse(worker.is_paused)

        # Speed adjustment
        worker.set_speed(2.5)
        self.assertEqual(worker.playback_speed, 2.5)

        # Seek relative & absolute
        worker.seek_to_frame(120)
        self.assertEqual(worker._seek_target_frame, 120)
        worker.seek_relative(5.0)
        self.assertEqual(worker._seek_target_frame, 125) # 0 + 5*25 = 125

    def test_live_graph_window_playback_actions(self):
        o = Probe.__new__(Probe)
        o.is_video_file = True
        o._pending_playback_actions = []
        o._on_player_toggle_pause()
        o._on_player_restart()
        o._on_player_seek_rel(5.0)
        actions = o.take_playback_actions()
        self.assertEqual(actions, [
            ('toggle_pause', None),
            ('restart', None),
            ('seek_rel', 5.0),
        ])
        self.assertEqual(len(o.take_playback_actions()), 0)

    def test_rewind_data_truncation_monotonic(self):
        class DummyCap:
            def __init__(self):
                self.pos = 0
            def isOpened(self):
                return True
            def get(self, prop):
                import cv2
                if prop == cv2.CAP_PROP_FPS:
                    return 25.0
                if prop == cv2.CAP_PROP_FRAME_COUNT:
                    return 10000
                return 0
            def set(self, prop, val):
                self.pos = val
                return True
            def read(self):
                frame = np.zeros((100, 100, 3), dtype=np.uint8)
                return True, frame

        cap = DummyCap()
        worker = CameraWorker(cap, {'source_is_file': True, 'playback_speed': 1.0, 'analysis_interval_ms': 10}, 0.0)
        
        # Симуляция первичной записи (от 0 до 60000 мс)
        for t_ms in range(0, 60000, 100):
            worker.time_data.append(t_ms)
            worker.r_data.append(50.0 + t_ms / 1000.0)
            worker.g_data.append(60.0 + t_ms / 1000.0)
            worker.b_data.append(70.0 + t_ms / 1000.0)
        worker.point_count = len(worker.time_data)
        self.assertEqual(len(worker.time_data), 600)
        
        # Пользователь перематывает назад на 20000 мс (на 20.0 сек)
        worker._truncate_data_to_time(20000.0)
        self.assertEqual(len(worker.time_data), 201)
        self.assertEqual(worker.time_data[-1], 20000)
        self.assertEqual(len(worker.r_data), 201)
        
        # Пользователь продолжает запись вперед
        for t_ms in range(20100, 40000, 100):
            worker.time_data.append(t_ms)
            worker.r_data.append(80.0)
            worker.g_data.append(90.0)
            worker.b_data.append(100.0)
            
        # Проверка строгой монотонности: петли и задвоения исключены, график строится ровно в 1 линию!
        t_list = list(worker.time_data)
        for i in range(len(t_list) - 1):
            self.assertLess(t_list[i], t_list[i + 1])

    def test_video_analysis_setup_and_reset_workflow(self):
        class DummyCap:
            def __init__(self):
                self.pos = 0
            def isOpened(self):
                return True
            def get(self, prop):
                import cv2
                if prop == cv2.CAP_PROP_FPS:
                    return 25.0
                if prop == cv2.CAP_PROP_FRAME_COUNT:
                    return 1000
                return 0
            def set(self, prop, val):
                self.pos = val
                return True
            def read(self):
                frame = np.zeros((100, 100, 3), dtype=np.uint8)
                return True, frame

        cap = DummyCap()
        worker = CameraWorker(cap, {'source_is_file': True, 'playback_speed': 1.0}, 0.0)

        # 1. При открытии видео - режим настройки: пауза, анализ не запущен
        self.assertTrue(worker.is_paused)
        self.assertFalse(worker.is_analysis_started)
        self.assertEqual(len(worker.time_data), 0)

        # 2. Пользователь нажимает Start: начинается запись данных
        worker.start_analysis()
        self.assertFalse(worker.is_paused)
        self.assertTrue(worker.is_analysis_started)
        worker.time_data.append(100)
        worker.time_data.append(200)

        # 3. Пользователь нажимает Reset [R]: возврат в режим настройки, пауза на кадре 0, очистка данных
        worker.reset_to_setup_mode()
        self.assertTrue(worker.is_paused)
        self.assertFalse(worker.is_analysis_started)
        self.assertEqual(len(worker.time_data), 0)
        self.assertEqual(worker._seek_target_frame, 0)

    def test_runner_compute_roi_means_importable(self):
        import src.analysis.runner as runner
        self.assertTrue(hasattr(runner, 'compute_roi_means'))
        self.assertTrue(hasattr(runner, 'is_video_file_path'))
        self.assertTrue(hasattr(runner, 'is_video_file_source'))
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        cfg = {'roi_x': 10, 'roi_y': 10, 'roi_w': 20, 'roi_h': 20, 'roi_shape': 'circle'}
        mb, mg, mr, sx, sy, sw, sh, hf, wf = runner.compute_roi_means(frame, cfg)
        self.assertEqual(sx, 10)
        self.assertEqual(sy, 10)
        self.assertEqual(sw, 20)
        self.assertEqual(sh, 20)

    def test_preview_worker(self):
        import time
        from src.gui.setup_app import PreviewWorker
        class DummyCap:
            def __init__(self):
                self.opened = True
            def isOpened(self):
                return self.opened
            def read(self):
                return True, np.ones((50, 50, 3), dtype=np.uint8) * 123
        cap = DummyCap()
        worker = PreviewWorker(cap, is_file=False)
        time.sleep(0.08)
        frame = worker.get_latest_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (50, 50, 3))
        self.assertEqual(frame[0, 0, 0], 123)
        worker.stop()
        self.assertFalse(worker._running)

    def test_license_manager_hwid_and_activation(self):
        import tempfile
        from src.utils.license_manager import (
            get_hardware_id, generate_activation_key,
            verify_activation_key, LicenseManager,
            LICENSE_STATUS_LICENSED, LICENSE_STATUS_TRIAL_ACTIVE
        )
        hwid = get_hardware_id()
        self.assertTrue(hwid.startswith("ELU-"))
        self.assertEqual(len(hwid.split("-")), 5)

        # Generate valid key
        key = generate_activation_key(hwid, "PRO")
        is_valid, lic_type, _ = verify_activation_key(key, hwid)
        self.assertTrue(is_valid)
        self.assertEqual(lic_type, "PRO")

        # Wrong key
        is_valid_wrong, _, _ = verify_activation_key("KEY-0000-0000-0000-0000", hwid)
        self.assertFalse(is_valid_wrong)

        # Test manager in clean temp dir
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = LicenseManager(storage_dir=tmpdir)
            st = mgr.get_status()
            self.assertEqual(st["status"], LICENSE_STATUS_TRIAL_ACTIVE)
            self.assertTrue(st["is_allowed"])

            # Activate
            ok, msg = mgr.activate(key, "Test Lab")
            self.assertTrue(ok)
            st_after = mgr.get_status()
            self.assertEqual(st_after["status"], LICENSE_STATUS_LICENSED)
            self.assertTrue(st_after["is_allowed"])
            self.assertEqual(st_after["customer_name"], "Test Lab")

    def test_theme_toggle_logic(self):
        from src.gui.setup_app import SetupApp
        class DummySetupApp(SetupApp):
            def __init__(self):
                self.config = {'light_theme': False}
                self.theme_calls = []
            def _apply_start_theme(self):
                self.theme_calls.append(self.config['light_theme'])
            def _save_current_settings(self):
                pass
        app = DummySetupApp()
        self.assertFalse(app.config['light_theme'])
        app.toggle_theme()
        self.assertTrue(app.config['light_theme'])
        app.toggle_theme()
        self.assertFalse(app.config['light_theme'])
        self.assertEqual(app.theme_calls, [True, False])

    def test_alert_dismiss_on_click(self):
        o = Probe.__new__(Probe)
        o.hidden_called = False
        def fake_hide():
            o.hidden_called = True
        o._hide_transition_alert_and_relayout = fake_hide
        o._on_transition_alert_clicked(None)
        self.assertTrue(o.hidden_called)

    def test_miicam_source_helpers(self):
        from src.utils.helpers import is_miicam_source
        self.assertTrue(is_miicam_source("miicam:0"))
        self.assertTrue(is_miicam_source("MIICAM:1"))
        self.assertTrue(is_miicam_source("rgb_detector"))
        self.assertFalse(is_miicam_source("0"))
        self.assertFalse(is_miicam_source("video.mp4"))

    def test_miicam_wrapper_defaults(self):
        from src.utils.miicam_wrapper import MiiCamCapture
        cap = MiiCamCapture(source="miicam:0")
        self.assertEqual(cap.exposure_us, 20000)
        self.assertEqual(cap.gain_percent, 100)
        self.assertEqual(cap.gamma, 100)
        cap.apply_settings_dict({
            "miicam_exposure_us": 15000,
            "miicam_gain": 250,
            "miicam_gamma": 110,
            "miicam_binning": 2,
            "miicam_frame_preload": True,
            "miicam_thread_priority": 2,
        })
        self.assertEqual(cap.exposure_us, 15000)
        self.assertEqual(cap.gain_percent, 250)
        self.assertEqual(cap.gamma, 110)
        self.assertEqual(cap.binning_mode, 2)
        self.assertTrue(cap.frame_preload)
        self.assertEqual(cap.thread_priority, 2)

        # Test high FPS mode preset helper
        cap.set_high_fps_mode(90)
        self.assertEqual(cap.exposure_us, 8000)
        self.assertEqual(cap.binning_mode, 2)
        self.assertEqual(cap.speed, 2)

        cap.set_high_fps_mode(60)
        self.assertEqual(cap.exposure_us, 15000)
        self.assertEqual(cap.binning_mode, 1)

        cap.release()

    def test_detector_comparison_defaults(self):
        from src.gui.settings_window import DEFAULT_CONFIG
        self.assertIn("detector_compare_mode", DEFAULT_CONFIG)
        self.assertIn("detector_split_pos", DEFAULT_CONFIG)
        self.assertIn("miicam_binning", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["detector_compare_mode"], "split")
        self.assertEqual(DEFAULT_CONFIG["detector_split_pos"], 50)

    def test_preview_worker_fps(self):
        from src.gui.setup_app import PreviewWorker
        w = PreviewWorker(cap=None)
        self.assertEqual(w.get_fps(), 0.0)
        w.stop()

    def test_settings_window_detector_tab_visibility(self):
        import tkinter as tk
        from src.gui.settings_window import SettingsWindow
        from src.utils.helpers import is_miicam_source

        # Test helper logic without GUI
        self.assertFalse(is_miicam_source("0"))
        self.assertFalse(is_miicam_source("video.mp4"))
        self.assertTrue(is_miicam_source("miicam:0"))
        self.assertTrue(is_miicam_source("rgb_detector"))

        try:
            root = tk.Tk()
            root.withdraw()
        except Exception:
            # Skip GUI-bound assertion in headless CI without X11
            return

        try:
            # 1. Non-MiiCam source: tab should NOT be present
            cfg_webcam = {"source": "0"}
            sw_webcam = SettingsWindow(root, cfg_webcam, current_cap=None)
            self.assertFalse(sw_webcam.is_miicam)
            tab_names_webcam = [sw_webcam.nb.tab(i, "text") for i in range(sw_webcam.nb.index("end"))]
            self.assertNotIn("💡 RGB-детектор", tab_names_webcam)
            sw_webcam.win.destroy()

            # 2. MiiCam source without active hardware connection: tab should NOT be present
            cfg_miicam = {"source": "miicam:0"}
            sw_miicam_no_hw = SettingsWindow(root, cfg_miicam, current_cap=None)
            self.assertFalse(sw_miicam_no_hw.is_miicam)
            tab_names_no_hw = [sw_miicam_no_hw.nb.tab(i, "text") for i in range(sw_miicam_no_hw.nb.index("end"))]
            self.assertNotIn("💡 RGB-детектор", tab_names_no_hw)
            sw_miicam_no_hw.win.destroy()

            # 3. MiiCam source with active connected hardware: tab MUST be present
            class MockMiiCam:
                def apply_settings_dict(self, d): pass
                def isOpened(self): return True
                def read(self): return True, np.zeros((100, 100, 3), dtype=np.uint8)

            sw_miicam = SettingsWindow(root, cfg_miicam, current_cap=MockMiiCam())
            self.assertTrue(sw_miicam.is_miicam)
            tab_names_miicam = [sw_miicam.nb.tab(i, "text") for i in range(sw_miicam.nb.index("end"))]
            self.assertIn("💡 RGB-детектор", tab_names_miicam)

            # Test comparison view generation and math
            sw_miicam._update_comparison_view()
            self.assertIsNotNone(sw_miicam._baseline_raw_frame)
            self.assertIsNotNone(sw_miicam._cached_raw_scaled)
            self.assertIsNotNone(sw_miicam._cached_adj_scaled)

            # Adjust Hue, Saturation, Brightness, Contrast, Temp, Tint
            sw_miicam.detector_vars["miicam_hue"].set(45)
            sw_miicam.detector_vars["miicam_saturation"].set(180)
            sw_miicam.detector_vars["miicam_temp"].set(7500)
            sw_miicam.detector_vars["miicam_tint"].set(1200)
            sw_miicam.detector_vars["miicam_brightness"].set(20)
            sw_miicam.detector_vars["miicam_contrast"].set(15)
            sw_miicam._on_detector_param_changed()

            # Calling update comparison view recomputes adjusted preview
            sw_miicam._update_comparison_view()
            adj_scaled = sw_miicam._cached_adj_scaled
            raw_scaled = sw_miicam._cached_raw_scaled

            # The adjusted frame must reflect changes while raw frame remains identical
            self.assertFalse(np.array_equal(raw_scaled, adj_scaled))

            sw_miicam.win.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def test_detector_hue_and_color_simulation_math(self):
        import cv2
        import numpy as np
        # Create test frame
        raw = np.full((100, 100, 3), 128, dtype=np.uint8)
        raw[20:50, 20:50] = [200, 50, 50] # Blue/Red area

        # Test Hue -180 to 180 degrees
        for h in [-180, -90, 0, 45, 90, 180]:
            hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 0] = np.mod(hsv[:, :, 0] + (float(h) / 2.0), 180.0)
            adj = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
            self.assertEqual(adj.shape, raw.shape)
            self.assertEqual(adj.dtype, np.uint8)

        # Test Temp & Tint
        for temp, tint in [(2000, 500), (6500, 1000), (12000, 1800)]:
            t_factor = (temp - 6500.0) / 8500.0
            tint_factor = (tint - 1000.0) / 1500.0
            r_mult = max(0.0, 1.0 + 0.45 * t_factor + 0.35 * tint_factor)
            g_mult = max(0.0, 1.0 - 0.35 * tint_factor)
            b_mult = max(0.0, 1.0 - 0.45 * t_factor + 0.35 * tint_factor)
            adj_f = raw.astype(np.float32)
            adj_f[:, :, 0] = np.clip(adj_f[:, :, 0] * b_mult, 0, 255)
            adj_f[:, :, 1] = np.clip(adj_f[:, :, 1] * g_mult, 0, 255)
            adj_f[:, :, 2] = np.clip(adj_f[:, :, 2] * r_mult, 0, 255)
            adj = adj_f.astype(np.uint8)
            self.assertEqual(adj.shape, raw.shape)
            self.assertEqual(adj.dtype, np.uint8)

    def test_miicam_set_resolution_dynamic(self):
        from src.utils.miicam_wrapper import MiiCamCapture
        cap = MiiCamCapture(source="miicam:0")
        # Direct call to set_resolution should return boolean without throwing
        res = cap.set_resolution(1280, 720)
        self.assertIsInstance(res, bool)
        cap.release()

    def test_custom_auto_mark_cooldown_holdoff(self):
        class M:
            def __init__(self):
                self.annotations = []
            def add_annotation(self, *a, **k):
                self.annotations.append((a, k))

        o = Probe.__new__(Probe)
        o.notification_settings = {
            'auto_marks_enabled': True,
            'sound_alerts_enabled': True,
            'custom_auto_marks': [{
                'enabled': True, 'name': 'PeakHoldoff', 'metric': 'RGB_sum_slope_30s',
                'operator': '>=', 'threshold': 2.0, 'color': '#FF0055',
                'description': 'Peak Holdoff Test', 'notify': False, 'sound': False,
                't_min_sec': 0.0, 't_max_sec': 3600.0,
                'cooldown_enabled': True,
                'cooldown_sec': 30.0
            }]
        }
        o._custom_auto_mark_active = {}
        o._custom_auto_mark_last_fired = {}
        o.annotation_manager = M()
        o._update_annotations = lambda: None
        o._persist_annotations = lambda: None
        o._show_toast = lambda x: None
        o._play_system_alert_sound = lambda: None

        # First trigger at t=5s (5000ms) -> Must FIRE
        o._check_custom_auto_marks(5000, 10, 20, 30, 3.5, 1.0)
        self.assertEqual(len(o.annotation_manager.annotations), 1)

        # Condition dips at t=8s
        o._check_custom_auto_marks(8000, 10, 20, 30, 0.5, 1.0)
        self.assertEqual(len(o.annotation_manager.annotations), 1)

        # Condition rises again at t=12s (only 7s after first fire, cooldown is 30s) -> MUST BE SUPPRESSED
        o._check_custom_auto_marks(12000, 10, 20, 30, 3.8, 1.0)
        self.assertEqual(len(o.annotation_manager.annotations), 1)

        # Condition dips at t=20s
        o._check_custom_auto_marks(20000, 10, 20, 30, 0.2, 1.0)

        # Condition rises again at t=40s (35s after first fire, past 30s cooldown) -> MUST FIRE 2ND MARK
        o._check_custom_auto_marks(40000, 10, 20, 30, 4.0, 1.0)
        self.assertEqual(len(o.annotation_manager.annotations), 2)

    def test_detector_named_presets_save_apply_delete(self):
        import tkinter as tk
        from src.gui.settings_window import SettingsWindow, DEFAULT_CONFIG
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception:
            return

        try:
            cfg = dict(DEFAULT_CONFIG)
            cfg["source"] = "miicam:0"

            class MockMiiCam:
                def isOpened(self): return True
                def read(self): return True, np.zeros((100, 100, 3), dtype=np.uint8)
                def apply_settings_dict(self, d): pass

            sw = SettingsWindow(root, cfg, current_cap=MockMiiCam())
            self.assertTrue(sw.is_miicam)

            # Test applying built-in preset "Бром (Bromine)"
            sw._apply_detector_preset("Бром (Bromine)")
            self.assertEqual(sw.detector_vars["miicam_exposure_us"].get(), 15000)
            self.assertEqual(sw.detector_vars["miicam_gain"].get(), 120)
            self.assertEqual(sw.detector_vars["miicam_temp"].get(), 5800)
            self.assertEqual(sw.detector_vars["miicam_contrast"].get(), 15)

            # Test applying "Ароматика (Aromatics)"
            sw._apply_detector_preset("Ароматика (Aromatics)")
            self.assertEqual(sw.detector_vars["miicam_exposure_us"].get(), 25000)
            self.assertEqual(sw.detector_vars["miicam_gain"].get(), 150)
            self.assertEqual(sw.detector_vars["miicam_contrast"].get(), 20)

            # Test creating a custom named preset
            sw.detector_vars["miicam_exposure_us"].set(42000)
            sw.detector_vars["miicam_gain"].set(185)
            custom_data = {k: v.get() for k, v in sw.detector_vars.items()}
            sw.config["detector_presets"]["Нефть фракция 1"] = custom_data

            # Apply another preset then re-apply our custom preset
            sw._apply_detector_preset("По умолчанию (Default)")
            self.assertEqual(sw.detector_vars["miicam_exposure_us"].get(), 20000)

            sw._apply_detector_preset("Нефть фракция 1")
            self.assertEqual(sw.detector_vars["miicam_exposure_us"].get(), 42000)
            self.assertEqual(sw.detector_vars["miicam_gain"].get(), 185)

            # Clean up
            sw.win.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def test_player_hud_metrics_defaults(self):
        from src.config import DEFAULT_PLAYER_HUD_METRICS
        self.assertIn("RGB_sum", DEFAULT_PLAYER_HUD_METRICS)
        self.assertIn("RGB_sum_slope_30s", DEFAULT_PLAYER_HUD_METRICS)
        self.assertIn("Transition_score", DEFAULT_PLAYER_HUD_METRICS)
        self.assertIn("Log10(B/R)", DEFAULT_PLAYER_HUD_METRICS)

if __name__ == '__main__':
    unittest.main()
