import json
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    _TK_IMPORT_ERROR = None
except ImportError as exc:
    tk = ttk = messagebox = filedialog = None
    _TK_IMPORT_ERROR = exc
from .settings_window import SettingsWindow, load_saved_settings
import cv2
import numpy as np
import time
import os
import socket
import threading
from PIL import Image, ImageDraw, ImageFont
try:
    from PIL import ImageTk
except ImportError:
    ImageTk = None
from collections import deque
from ..utils.math_utils import compute_log_br

from ..utils.helpers import (
    detect_green_circle_roi,
    scan_cameras, scan_ip_cameras, scan_miicam_cameras, create_video_capture, open_camera_device, warmup_capture,
    read_valid_frame, verify_capture_can_read, is_network_source, is_placeholder_frame, is_miicam_source,
    ivcam_setup_hint, get_default_save_folder, get_local_ip,
    camera_label, camera_priority, is_ivcam_name, is_iriun_name, is_video_file_source, is_video_file_path, repair_video_file_if_needed, open_video_file_capture
)
from ..utils.ffmpeg_utils import ensure_pyqt5_platform_plugin_path
from ..analysis.runner import run_analysis
from ..utils.license_manager import (
    LicenseManager, LICENSE_STATUS_LICENSED,
    LICENSE_STATUS_TRIAL_ACTIVE, LICENSE_STATUS_TRIAL_EXPIRED
)
from .license_dialog import LicenseDialog
from .design_system import apply_ttk_theme, get_palette


def _get_unicode_font(size=14, bold=False):
    candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "tahomabd.ttf" if bold else "tahoma.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\tahomabd.ttf" if bold else "C:\\Windows\\Fonts\\tahoma.ttf"
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


class PreviewWorker:
    """
    Высокопроизводительный фоновый захват кадров предпросмотра SetupApp.
    Полностью избавляет главный GUI-поток Tkinter от блокировок I/O,
    обеспечивая сверхвысокие частоты кадров (60–120+ FPS) с измерением реального FPS.
    """
    def __init__(self, cap, is_file=False, initial_frame=None):
        self.cap = cap
        self.is_file = is_file
        self._running = True
        self._lock = threading.Lock()
        self._latest_frame = initial_frame.copy() if initial_frame is not None else None
        self.current_fps = 0.0
        self._fps_count = 0
        self._fps_time = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            if self.cap is None:
                time.sleep(0.01)
                continue
            try:
                if not self.cap.isOpened():
                    time.sleep(0.01)
                    continue
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    with self._lock:
                        self._latest_frame = frame
                        self._fps_count += 1
                        now = time.time()
                        dt = now - self._fps_time
                        if dt >= 0.5:
                            self.current_fps = round(self._fps_count / dt, 1)
                            self._fps_count = 0
                            self._fps_time = now
                    # Ultra-low latency yield for high FPS throughput
                    time.sleep(0.001)
                elif self.is_file:
                    try:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass
                    time.sleep(0.02)
                else:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.01)

    def get_latest_frame(self):
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
            return None

    def get_fps(self):
        return self.current_fps

    def stop(self):
        self._running = False
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.3)


class SetupApp:
    def __init__(self):
        if tk is None or ImageTk is None:
            raise RuntimeError(
                "Tkinter недоступен. Установите компонент Python Tk/Tcl для запуска интерфейса."
            ) from _TK_IMPORT_ERROR
        self.root = tk.Tk()
        self.root.title("Элютек")
        self.root.geometry("1600x860")
        
        default_save = get_default_save_folder()
        self.config = {
            'source': "0",
            'roi_x': 300, 'roi_y': 150, 'roi_w': 200, 'roi_h': 400,
            'save_folder': default_save,
            'video_folder': default_save,
            'show_r': True, 'show_g': True, 'show_b': True,
            'show_log': True, 'show_slope': True, 'show_transition': True,
            'antialias': False,
            'performance_profile': 'Сбалансированный',
            'analysis_interval_ms': 15,
            'graph_update_ms': 120,
            'max_points': 108000,
            'preview_interval_ms': 50,
            'preview_rgb_interval_ms': 200,
            'display_max_width': 1280,
            'record_video': True,
            'show_video_window': True,
            'playback_speed': 1.0,
            'live_roi': True,
            'allow_roi_resize': True,
            'auto_stop_file': True,
            'light_theme': False,
            'custom_graphs': [],
            # Automatic notification / annotation settings.
            'notifications_enabled': True,
            'alert_confirm_ms': 5000.0,
            'arm_delay_ms': 300000.0,
            'min_rgb_sum': 10.0,
            'arom_slope_standard': 1.0,
            'arom_slope_strong': 2.5,
            'arom_score_standard': 3.0,
            'arom_score_strong': 4.0,
            'br_slope_threshold': 3.5,
            'br_score_threshold': 3.0,
            'br_confirm_ms': 3000.0,
            'abr_slope_threshold': -1.0,
            'abr_score_threshold': 2.5,
            'abr_confirm_ms': 3000.0,
            'abr_strong_slope_threshold': -2.5,
            'abr_strong_score_threshold': 3.0,
            'abr_strong_confirm_ms': 1000.0,
            'alert_display_ms': 120000.0,
        }
        
        try:
            saved_settings = load_saved_settings()
            if isinstance(saved_settings, dict):
                self.config.update(saved_settings)
            self.config.pop('show_triangle', None)
        except Exception:
            pass

        self.cap = None
        self.preview_worker = None
        self.latest_frame = None
        self.devices_combined = []
        self.is_running = True
        self.camera_list = []
        self.ip_camera_list = []
        self.preview_scale = 1.0
        self.preview_width = 640
        self.preview_height = 480
        self.roi_shape = str(self.config.get('roi_shape', 'circle'))
        self.roi_drag = False
        self.roi_action = None
        self.roi_start = (0, 0)
        self.roi_orig = (0, 0, 0, 0)
        self.roi_handle = None
        self.HANDLE_SIZE = 12
        self.MIN_ROI_SIZE = 20

                          
        self.preview_rgb_history = deque(maxlen=300)
        self.preview_interval_ms = int(self.config.get('preview_interval_ms', 50))
        self.preview_rgb_interval_ms = int(self.config.get('preview_rgb_interval_ms', 200))
        self.preview_last_rgb_update = 0.0
        self.preview_current_rgb = None
        self.preview_rgb_var = tk.StringVar(value="RGB ROI: —")
        self.preview_log_var = tk.StringVar(value="Log10(B/R): —")

        self.lic_mgr = LicenseManager()
        self.lic_mgr.register_app_launch()

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Final pass after widget creation: prevents first-launch ttk
        # defaults (white combobox/radiobutton states) from leaking through.
        self._apply_start_theme()

        self.update_preview()
        self.root.mainloop()

    def _apply_start_theme(self):
        """Apply the shared theme and finish styling native Tk widgets."""
        style = ttk.Style(self.root)
        light = bool(self.config.get('light_theme', False))
        palette = apply_ttk_theme(style, light)
        self.root.configure(bg=palette['background'])

        # Canvas and Listbox do not consume ttk styles.  Keeping this here also
        # makes a live theme switch update already-created native widgets.
        for widget_name in ('devices_listbox', 'preview_rgb_canvas', 'left_canvas'):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.configure(
                        bg=palette['surface'], fg=palette['text'],
                        selectbackground=palette['selection'], selectforeground='#FFFFFF',
                    )
                except Exception:
                    try:
                        widget.configure(bg=palette['surface'])
                    except Exception:
                        pass
        if hasattr(self, 'preview_rgb_canvas'):
            try:
                self.preview_rgb_canvas.configure(
                    bg=palette['surface'], highlightbackground=palette['border']
                )
            except Exception:
                pass
        if hasattr(self, 'preview_color_canvas'):
            try:
                self.preview_color_canvas.configure(
                    bg=palette['surface_raised'], highlightbackground=palette['border']
                )
            except Exception:
                pass
        if hasattr(self, 'preview_label'):
            self.preview_label.configure(background=palette['surface'])
        if hasattr(self, 'left_canvas'):
            try:
                self.left_canvas.configure(bg=palette['background'])
            except Exception:
                pass
        if hasattr(self, 'theme_btn'):
            try:
                self.theme_btn.config(
                    text="☀️ Светлая тема" if not light else "🌙 Тёмная тема"
                )
            except Exception:
                pass
        self._update_license_ui()

    def _update_license_ui(self):
        if not hasattr(self, 'lic_btn'):
            return
        try:
            status = self.lic_mgr.get_status()
            st = status.get('status')
            if st == LICENSE_STATUS_LICENSED:
                self.lic_btn.config(text="✅ Лицензия PRO")
            elif st == LICENSE_STATUS_TRIAL_ACTIVE:
                self.lic_btn.config(text=f"⏳ Демо ({status.get('days_left', 0)} дн.)")
            else:
                self.lic_btn.config(text="❌ Активировать ключ")
        except Exception:
            pass

    def open_license_dialog(self, block_if_expired=False):
        LicenseDialog(
            parent=self.root,
            config=self.config,
            lic_mgr=self.lic_mgr,
            on_activated=self._update_license_ui,
            block_if_expired=block_if_expired
        )

    def toggle_theme(self):
        current = bool(self.config.get('light_theme', False))
        self.config['light_theme'] = not current
        self._apply_start_theme()
        self._save_current_settings()

    def _save_current_settings(self):
        try:
            from .settings_window import save_settings
            save_settings(self.config)
        except Exception:
            pass

    def build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')

                    
        try:
            self._apply_start_theme()
        except Exception:
            pass

        header = ttk.Frame(self.root, style="Header.TFrame")
        header.pack(fill="x", padx=18, pady=(16, 10))
        title_row = ttk.Frame(header, style="Header.TFrame")
        title_row.pack(fill='x')

        brand = ttk.Frame(title_row, style="Header.TFrame")
        brand.pack(side='left', fill='x', expand=True)
        ttk.Label(brand, text="ELUTEK · VISUAL ANALYTICS", style="Eyebrow.TLabel").pack(anchor='w')
        ttk.Label(brand, text="RGB SARA — анализ", style="Title.TLabel").pack(anchor='w', pady=(1, 0))
        ttk.Label(
            brand, text="Подключите источник, настройте область и запустите измерение.",
            style="Subtitle.TLabel"
        ).pack(anchor='w', pady=(1, 0))

        actions = ttk.Frame(title_row, style="Header.TFrame")
        actions.pack(side='right', anchor='n', pady=(4, 0))
        ttk.Button(actions, text="⚙ Настройки", style="Primary.TButton",
                   command=self.open_settings).pack(side='right')
        self.lic_btn = ttk.Button(
            actions, text="🔑 Лицензия", style="Compact.TButton",
            command=self.open_license_dialog
        )
        self.lic_btn.pack(side='right', padx=(0, 8))
        self.theme_btn = ttk.Button(
            actions,
            text="☀️ Светлая тема" if not self.config.get('light_theme', False) else "🌙 Тёмная тема",
            style="Compact.TButton", command=self.toggle_theme
        )
        self.theme_btn.pack(side='right', padx=(0, 8))
        self._update_license_ui()

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=18, pady=(0, 16))

                                   
        left_outer = ttk.Frame(main, width=400)
        left_outer.pack(side="left", fill="y", padx=(0, 12))
        left_outer.pack_propagate(False)

        left_canvas = tk.Canvas(left_outer, highlightthickness=0, bg=self.root.cget('bg'))
        self.left_canvas = left_canvas
        left_scrollbar = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        left = ttk.Frame(left_canvas)
        left_window_id = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _update_left_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def _fit_left_width(event):
            left_canvas.itemconfigure(left_window_id, width=event.width)

        def _on_left_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        left.bind("<Configure>", _update_left_scrollregion)
        left_canvas.bind("<Configure>", _fit_left_width)
        left_canvas.bind("<Enter>", lambda event: left_canvas.bind_all("<MouseWheel>", _on_left_mousewheel))
        left_canvas.bind("<Leave>", lambda event: left_canvas.unbind_all("<MouseWheel>"))

                                              
        frame_scan = ttk.LabelFrame(left, text="01 · ИСТОЧНИК ВИДЕО", style="Card.TLabelframe")
        frame_scan.pack(fill="x", pady=5)

        btn_frame = ttk.Frame(frame_scan, style="Card.TFrame")
        btn_frame.pack(fill="x", padx=5, pady=5)

        ttk.Button(btn_frame, text="💡 RGB-детектор (MiiCam)", 
                  command=self.scan_rgb_detector).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="📹 USB-камеры", 
                  command=self.scan_usb_cameras).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="📱 IP-камеры (сеть)", 
                  command=self.scan_network_cameras).pack(fill="x", pady=2)

        devices_box_frame = ttk.Frame(frame_scan, style="Card.TFrame")
        devices_box_frame.pack(fill="both", padx=5, pady=5, expand=True)
        self.devices_listbox = tk.Listbox(devices_box_frame, height=6, width=48, activestyle='none')
        self.devices_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(devices_box_frame, orient="vertical", command=self.devices_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.devices_listbox.config(yscrollcommand=scrollbar.set)
        self.devices_listbox.bind('<<ListboxSelect>>', self.on_device_select)
        self.devices_listbox.bind('<Double-Button-1>', self.on_device_activate)

        self.devices_label = ttk.Label(frame_scan, text="Выбранное устройство: —", wraplength=342, style="CardMuted.TLabel")
        self.devices_label.pack(fill="x", padx=5, pady=(0,5))

                        
        frame_cam = ttk.LabelFrame(left, text="02 · ПОДКЛЮЧЕНИЕ", style="Card.TLabelframe")
        frame_cam.pack(fill="x", pady=5)

        cam_inner = ttk.Frame(frame_cam, style="Card.TFrame")
        cam_inner.pack(fill="x", padx=5, pady=5)
        ttk.Label(cam_inner, text="URL / индекс:", style="Card.TLabel").pack(side="left", padx=5)
        self.entry_source = ttk.Entry(cam_inner, width=28)
        self.entry_source.insert(0, self.config['source'])
        self.entry_source.pack(side="left", padx=5, fill="x", expand=True)

        apply_frame = ttk.Frame(frame_cam, style="Card.TFrame")
        apply_frame.pack(fill="x", padx=5, pady=(4, 6))
        ttk.Button(apply_frame, text="✅ Применить", style="Primary.TButton", command=self.apply_source).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(apply_frame, text="🔄 Переподключить", command=self.check_camera).pack(side="right", fill="x", expand=True, padx=(2, 0))

                     
        frame_file = ttk.LabelFrame(left, text="АЛЬТЕРНАТИВА · ВИДЕОФАЙЛ", style="Card.TLabelframe")
        frame_file.pack(fill="x", pady=5)
        ttk.Label(frame_file, text="Выберите локальный файл — он откроется в отдельном режиме анализа.", wraplength=342, style="CardMuted.TLabel").pack(fill="x", padx=10, pady=(8, 6))
        ttk.Button(frame_file, text="🎞 АНАЛИЗ ВИДЕОФАЙЛА", command=self.choose_video_file_and_analyze).pack(fill="x", padx=8, pady=(0, 8))

        frame_save = ttk.LabelFrame(left, text="03 · СОХРАНЕНИЕ РЕЗУЛЬТАТОВ", style="Card.TLabelframe")
        frame_save.pack(fill="x", pady=5)

        save_inner = ttk.Frame(frame_save, style="Card.TFrame")
        save_inner.pack(fill="x", padx=5, pady=5)
        self.entry_save_folder = ttk.Entry(save_inner, width=35)
        self.entry_save_folder.insert(0, self.config['save_folder'])
        self.entry_save_folder.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(save_inner, text="Обзор...", 
                  command=self.choose_save_folder).pack(side="left", padx=5)

             
        frame_roi = ttk.LabelFrame(left, text="04 · ОБЛАСТЬ АНАЛИЗА (ROI)", style="Card.TLabelframe")
        frame_roi.pack(fill="x", pady=5)

        self.var_x = tk.IntVar(value=300)
        self.var_y = tk.IntVar(value=150)
        self.var_w = tk.IntVar(value=200)
        self.var_h = tk.IntVar(value=200)
        self.roi_shape_var = tk.StringVar(value=str(self.config.get('roi_shape', 'circle')))

        shape_frame = ttk.Frame(frame_roi, style="Card.TFrame")
        shape_frame.pack(fill="x", padx=5, pady=(0,5))
        ttk.Label(shape_frame, text="Форма:", style="Card.TLabel").pack(side="left", padx=(0,5))
        ttk.Radiobutton(shape_frame, text="Круг", style="Card.TRadiobutton", variable=self.roi_shape_var, value='circle').pack(side="left", padx=2)
        ttk.Radiobutton(shape_frame, text="Квадрат", style="Card.TRadiobutton", variable=self.roi_shape_var, value='rect').pack(side="left", padx=2)

        self.coord_label = ttk.Label(frame_roi, text="📍 X: 0  Y: 0  W: 0  H: 0", style="CardMuted.TLabel")
        self.coord_label.pack(fill="x", padx=5, pady=2)

        vcmd = self.root.register(self.validate_roi_entry)
        def create_spin_row(parent, label_text, var, min_val=0, max_val=1920):
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill="x", padx=5, pady=2)
            ttk.Label(row, text=f"{label_text}:", width=10, style="Card.TLabel").pack(side="left", padx=(0,5))
            btn_minus = ttk.Button(row, text="−", width=3, 
                                  command=lambda: self.adjust_value(var, -1, min_val, max_val))
            btn_minus.pack(side="left", padx=1)
            entry = ttk.Entry(row, width=6, textvariable=var, validate='key', validatecommand=(vcmd, '%P', str(min_val), str(max_val)))
            entry.pack(side="left", padx=2)
            btn_plus = ttk.Button(row, text="+", width=3,
                                 command=lambda: self.adjust_value(var, 1, min_val, max_val))
            btn_plus.pack(side="left", padx=1)
            var.trace_add('write', lambda *args: self.update_coord_label())
            return row

        create_spin_row(frame_roi, "X", self.var_x, 0, 1920)
        create_spin_row(frame_roi, "Y", self.var_y, 0, 1080)
        create_spin_row(frame_roi, "Ширина", self.var_w, 20, 1920)
        create_spin_row(frame_roi, "Высота", self.var_h, 20, 1080)

        size_btn_frame = ttk.Frame(frame_roi, style="Card.TFrame")
        size_btn_frame.pack(fill="x", padx=5, pady=3)
        ttk.Button(size_btn_frame, text="⬆ Увеличить", command=lambda: self.change_roi_size(1.2)).pack(side="left", padx=2)
        ttk.Button(size_btn_frame, text="⬇ Уменьшить", command=lambda: self.change_roi_size(0.8)).pack(side="left", padx=2)
        ttk.Button(size_btn_frame, text="⟳ Сбросить", command=self.reset_roi).pack(side="left", padx=2)
        self.update_coord_label()
        


                               
        frame_btn = ttk.Frame(left)
        frame_btn.pack(fill="x", pady=(12, 4))
        ttk.Label(frame_btn, text="ГОТОВЫ К ИЗМЕРЕНИЮ?", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 5))
        ttk.Button(frame_btn, text="▶ ЗАПУСТИТЬ АНАЛИЗ", style="Primary.TButton",
                  command=self.start_analysis).pack(fill="x", pady=(0, 6))
        ttk.Button(frame_btn, text="Выйти из программы", style="Danger.TButton",
                  command=self.on_closing).pack(fill="x")

                                                   
        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True)

        frame_rgb = ttk.LabelFrame(right, text="СИГНАЛ · RGB В ОБЛАСТИ ROI", style="Card.TLabelframe")
        frame_rgb.pack(side="top", fill="x", pady=(0, 6))

        rgb_info = ttk.Frame(frame_rgb, style="Card.TFrame")
        rgb_info.pack(fill="x", padx=6, pady=(5, 2))
        ttk.Label(rgb_info, textvariable=self.preview_rgb_var, style="Card.TLabel", font=('Consolas', 11, 'bold')).pack(side="left", padx=(0, 12))
        ttk.Label(rgb_info, textvariable=self.preview_log_var, style="CardMuted.TLabel", font=('Consolas', 10)).pack(side="left", padx=(0, 12))

        rgb_controls = ttk.Frame(frame_rgb, style="Card.TFrame")
        rgb_controls.pack(fill="x", padx=6, pady=(0, 4))
        self.preview_color_canvas = tk.Canvas(rgb_controls, width=60, height=28, highlightthickness=1, highlightbackground="#777777")
        self.preview_color_canvas.pack(side="left", padx=(0, 8))
        ttk.Label(rgb_controls, text="Шкала 0–300 · последние ~300 измерений", style="CardMuted.TLabel").pack(side="left", padx=10)

        palette = get_palette(bool(self.config.get('light_theme', False)))
        canvas_bg = palette['surface']
        canvas_border = palette['border']
        self.preview_rgb_canvas = tk.Canvas(
            frame_rgb, height=95, bg=canvas_bg,
            highlightthickness=1, highlightbackground=canvas_border
        )
        self.preview_rgb_canvas.pack(fill="x", padx=6, pady=(0, 6))

        frame_prev = ttk.LabelFrame(right, text="ПРЕДПРОСМОТР · РАМКА ROI ПЕРЕТАСКИВАЕТСЯ МЫШЬЮ", style="Card.TLabelframe")
        frame_prev.pack(side="top", fill="both", expand=True)
        self.preview_label = ttk.Label(frame_prev)
        self.preview_label.pack(fill="both", expand=True, padx=5, pady=5)
        self.preview_label.bind('<ButtonPress-1>', self.on_preview_mouse_down)
        self.preview_label.bind('<B1-Motion>', self.on_preview_mouse_move)
        self.preview_label.bind('<ButtonRelease-1>', self.on_preview_mouse_up)
        self.preview_label.bind('<Motion>', self.on_preview_mouse_hover)

                              
        # Native Tk widgets (Canvas/Listbox) are created after ttk styling,
        # so apply the theme once more to eliminate first-launch white flashes.
        try:
            self._apply_start_theme()
        except Exception:
            pass

        self.root.after(500, self.scan_usb_cameras)

                                                  
    def adjust_value(self, var, delta, min_val, max_val):
        current = var.get()
        new_val = max(min_val, min(max_val, current + delta))
        var.set(new_val)
        self.update_coord_label()

    def safe_get_int(self, var, fallback=0):
        try:
            val = var.get()
            value = int(val)
            if str(value) != str(val):
                var.set(value)
            return value
        except Exception:
            try:
                var.set(fallback)
            except Exception:
                pass
            return int(fallback)

    def validate_roi_entry(self, proposed, min_val, max_val):
        if not proposed:
            return True
        if proposed.strip() != proposed:
            return False
        if proposed.startswith('0') and len(proposed) > 1:
            return False
        if not proposed.isdigit():
            return False
        value = int(proposed)
        if value < int(min_val) or value > int(max_val):
            return False
        return True

    def change_roi_size(self, factor):
        x = self.safe_get_int(self.var_x, 0)
        y = self.safe_get_int(self.var_y, 0)
        w = self.safe_get_int(self.var_w, self.MIN_ROI_SIZE)
        h = self.safe_get_int(self.var_h, self.MIN_ROI_SIZE)
        cx = x + w / 2
        cy = y + h / 2
        new_w = max(self.MIN_ROI_SIZE, w * factor)
        new_h = max(self.MIN_ROI_SIZE, h * factor)
        new_x = max(0, int(cx - new_w / 2))
        new_y = max(0, int(cy - new_h / 2))
        self.var_x.set(new_x)
        self.var_y.set(new_y)
        self.var_w.set(int(new_w))
        self.var_h.set(int(new_h))
        self.update_coord_label()

    def reset_roi(self):
        if self.preview_width > 0 and self.preview_height > 0:
            w = min(self.preview_width // 3, 300)
            h = min(self.preview_height // 2, 400)
            x = (self.preview_width - w) // 2
            y = (self.preview_height - h) // 2
            self.var_x.set(max(0, x))
            self.var_y.set(max(0, y))
            self.var_w.set(max(self.MIN_ROI_SIZE, w))
            self.var_h.set(max(self.MIN_ROI_SIZE, h))
            self.update_coord_label()

    def update_coord_label(self):
        x = self.safe_get_int(self.var_x, 0)
        y = self.safe_get_int(self.var_y, 0)
        w = self.safe_get_int(self.var_w, self.MIN_ROI_SIZE)
        h = self.safe_get_int(self.var_h, self.MIN_ROI_SIZE)
        self.coord_label.config(text=f"📍 X: {x}  Y: {y}  W: {w}  H: {h}")

    def choose_save_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку для сохранения результатов")
        if folder:
            self.entry_save_folder.delete(0, tk.END)
            self.entry_save_folder.insert(0, folder)
            self.config['save_folder'] = folder
            self.config['video_folder'] = folder

    def choose_video_folder(self):
        self.choose_save_folder()

    def open_settings(self):
        SettingsWindow(self.root, self.config, on_apply=self.apply_settings, current_cap=self.cap)

    def apply_settings(self):
        # Настройки применяются без перезапуска главного окна.
        try:
            self.preview_interval_ms = max(20, int(self.config.get("preview_interval_ms", 50)))
        except Exception:
            self.preview_interval_ms = 50
        try:
            self.preview_rgb_interval_ms = max(50, int(self.config.get("preview_rgb_interval_ms", 200)))
        except Exception:
            self.preview_rgb_interval_ms = 200
        self.preview_last_rgb_update = 0.0
        self._apply_start_theme()
        self._save_current_settings()

    def snap_roi_to_green_circle(self, verbose=True, source_override=None):
        """Обнаружение нарисованного зеленого круга на видеокадре и установка ROI пиксель в пиксель."""
        frame = None
        src = source_override if source_override else self.config.get('source', '')
        source_clean = str(src).strip().strip('"').strip("'")
        is_file = is_video_file_source(source_clean) or is_video_file_path(source_clean)

        if is_file and os.path.isfile(os.path.abspath(os.path.expanduser(source_clean))):
            temp_cap = create_video_capture(source_clean)
            if temp_cap is not None and temp_cap.isOpened():
                ret, f = read_valid_frame(temp_cap, attempts=15)
                if ret and f is not None:
                    frame = f
                temp_cap.release()
        elif getattr(self, 'latest_frame', None) is not None:
            frame = self.latest_frame
        elif self.cap is not None and self.cap.isOpened():
            ret, f = self.cap.read()
            if ret and f is not None:
                frame = f

        if frame is None or frame.size == 0:
            if verbose:
                messagebox.showwarning("ROI", "Не удалось получить кадр с видео для поиска зеленого круга.", parent=self.root)
            return False

        circle_res = detect_green_circle_roi(frame)
        if circle_res is not None:
            cx, cy, r = circle_res
            x = max(0, cx - r)
            y = max(0, cy - r)
            w = 2 * r
            h = 2 * r
            self.var_x.set(x)
            self.var_y.set(y)
            self.var_w.set(w)
            self.var_h.set(h)
            self.roi_shape_var.set('circle')
            self.config['roi_x'] = x
            self.config['roi_y'] = y
            self.config['roi_w'] = w
            self.config['roi_h'] = h
            self.config['roi_shape'] = 'circle'
            self.coord_label.config(text=f"🎯 ROI выставлен по зеленому кругу на видео: X:{x} Y:{y} W:{w} H:{h} (R:{r})")
            print(f"🎯 Автоматически выставлен ROI по зеленому кругу на видео (пиксель в пиксель): X={x}, Y={y}, W={w}, H={h}, R={r}")
            if verbose:
                msg = (
                    f"Зеленый круг успешно обнаружен на видео!\n\n"
                    f"Координаты (пиксель в пиксель):\n"
                    f"Центр: ({cx}, {cy})\n"
                    f"Радиус: {r} px\n"
                    f"Область ROI: X={x}, Y={y}, W={w}, H={h}"
                )
                messagebox.showinfo("ROI", msg, parent=self.root)
            return True
        else:
            if verbose:
                messagebox.showinfo("ROI", "Зеленый круг настройки на текущем видеокадре не обнаружен.", parent=self.root)
            return False

    def load_roi_for_video(self, video_path):
        """Автоматическая установка ROI по зеленому кругу на видеофайле, если включено в настройках."""
        if not video_path:
            return False
        if self.config.get('snap_roi_green_circle_on_file', True):
            return self.snap_roi_to_green_circle(verbose=False, source_override=video_path)
        return False

    def choose_video_file_and_analyze(self):
        path = filedialog.askopenfilename(
            title="Выберите видеофайл для анализа",
            filetypes=[
                ("Видео", "*.mp4 *.avi *.mkv *.mov *.m4v *.wmv *.webm *.mpeg *.mpg"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return
        clean_path = os.path.normpath(os.path.abspath(os.path.expanduser(str(path).strip().strip('"').strip("'"))))
        if not os.path.isfile(clean_path):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{clean_path}", parent=self.root)
            return

        if os.path.getsize(clean_path) == 0:
            messagebox.showerror(
                "❌ Ошибка",
                f"Видеофайл пуст (0 байт):\n{clean_path}\n\nФайл не был сохранён или повреждён при записи.",
                parent=self.root
            )
            return

        # Быстрая проверка читаемости
        test_cap = create_video_capture(clean_path)
        if test_cap is None or not test_cap.isOpened() or not verify_capture_can_read(test_cap):
            msg = (
                f"Не удалось открыть видеофайл:\n{clean_path}\n\n"
                "Причина: Файл повреждён (отсутствует заголовок moov atom) либо кодек не поддерживается.\n\n"
                "💡 Решение:\n"
                "• Запустите новый анализ с камеры («▶ ЗАПУСТИТЬ АНАЛИЗ») — запись сохраняется в надёжном формате MKV.\n"
                "• Либо выберите другой рабочий видеофайл."
            )
            messagebox.showerror("❌ Ошибка видеофайла", msg, parent=self.root)
            if test_cap is not None:
                try:
                    test_cap.release()
                except Exception:
                    pass
            return

        try:
            test_cap.release()
        except Exception:
            pass

        self.entry_source.delete(0, tk.END)
        self.entry_source.insert(0, clean_path)
        self.config["source"] = clean_path
        self.config["source_is_file"] = True
        self.devices_label.config(text=f"Выбран видеофайл: {os.path.basename(clean_path)}")
        if self.preview_worker is not None:
            try:
                self.preview_worker.stop()
            except Exception:
                pass
            self.preview_worker = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.latest_frame = None
        self.load_roi_for_video(clean_path)
        self.start_analysis()

    def choose_video_file(self):
        path = filedialog.askopenfilename(
            title="Выберите видеофайл для анализа",
            filetypes=[
                ("Видео", "*.mp4 *.avi *.mkv *.mov *.m4v *.wmv *.webm *.mpeg *.mpg"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return
        clean_path = os.path.normpath(os.path.abspath(os.path.expanduser(str(path).strip().strip('"').strip("'"))))
        if not os.path.isfile(clean_path):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{clean_path}", parent=self.root)
            return
        self.entry_source.delete(0, tk.END)
        self.entry_source.insert(0, clean_path)
        self.config["source"] = clean_path
        self.config["source_is_file"] = True
        self.devices_label.config(text=f"Выбран видеофайл: {os.path.basename(clean_path)}")
        self.latest_frame = None
        self.load_roi_for_video(clean_path)
        self.open_camera_source(clean_path, verbose=False)

    def scan_rgb_detector(self):
        self.devices_listbox.delete(0, tk.END)
        self.devices_listbox.insert(tk.END, "💡 Поиск RGB-детектора (MiiCam)...")

        def _scan_thread():
            cam_list = scan_miicam_cameras()
            try:
                from ..utils.miicam_wrapper import is_miicam_available
                dll_avail = is_miicam_available()
            except Exception:
                dll_avail = False

            def _ui_update():
                if not hasattr(self, 'devices_listbox'):
                    return
                self.devices_listbox.delete(0, tk.END)
                self.devices_combined = []
                if cam_list:
                    for src, name in cam_list:
                        display = f"💡 {name}"
                        self.devices_listbox.insert(tk.END, display)
                        self.devices_combined.append((src, name))
                    
                    # Auto select and open first detector
                    first_src = self.devices_combined[0][0]
                    first_name = self.devices_combined[0][1]
                    self.entry_source.delete(0, tk.END)
                    self.entry_source.insert(0, str(first_src))
                    self.config['source'] = str(first_src)
                    self.devices_label.config(text=f"Выбранное устройство: {first_name} ({first_src})")
                    self.devices_listbox.selection_clear(0, tk.END)
                    self.devices_listbox.selection_set(0)
                    self.devices_listbox.activate(0)
                    self.open_camera_source(str(first_src), verbose=False)
                else:
                    self.devices_combined.append(("miicam:0", "💡 RGB-детектор (Канал 0)"))
                    self.devices_listbox.insert(tk.END, "💡 RGB-детектор (Канал 0) — Нажмите для подключения")
                    self.entry_source.delete(0, tk.END)
                    self.entry_source.insert(0, "miicam:0")
                    self.config['source'] = "miicam:0"
                    self.devices_label.config(text="Выбранное устройство: 💡 RGB-детектор (miicam:0)")
                    self.devices_listbox.selection_clear(0, tk.END)
                    self.devices_listbox.selection_set(0)
                    self.devices_listbox.activate(0)
                    success = self.open_camera_source("miicam:0", verbose=False)
                    if not success and not dll_avail:
                        messagebox.showinfo(
                            "💡 RGB-детектор MiiCam",
                            "Библиотека miicam.dll / toupcam.dll не найдена.\n\n"
                            "Поместите файл miicam.dll в папку программы (рядом с main.py / exe), "
                            "подключите детектор к USB и нажмите кнопку «RGB-детектор» снова.",
                            parent=self.root
                        )
                    elif not success:
                        messagebox.showwarning(
                            "💡 RGB-детектор MiiCam",
                            "Библиотека miicam.dll загружена, но устройство не отвечает на порту USB.\n\n"
                            "Проверьте надежность подключения кабеля USB к детектору и повторите попытку.",
                            parent=self.root
                        )

            try:
                self.root.after(0, _ui_update)
            except Exception:
                pass

        threading.Thread(target=_scan_thread, daemon=True).start()

    def scan_usb_cameras(self):
        self.devices_listbox.delete(0, tk.END)
        self.devices_listbox.insert(tk.END, "🔍 Сканирование устройств...")

        def _scan_thread():
            cam_list = scan_cameras(max_index=6)
            try:
                self.root.after(0, lambda: self._on_usb_cameras_scanned(cam_list))
            except Exception:
                pass

        threading.Thread(target=_scan_thread, daemon=True).start()

    def _on_usb_cameras_scanned(self, cam_list):
        if not hasattr(self, 'devices_listbox'):
            return
        self.devices_listbox.delete(0, tk.END)
        self.devices_combined = []
        self.camera_list = cam_list
        if self.camera_list:
            for idx, name in self.camera_list:
                display = f"[{idx}] {name}"
                self.devices_listbox.insert(tk.END, display)
                self.devices_combined.append((idx, name))
                       
            opened = False
            for idx, name in self.devices_combined:
                if "нет видеопотока" in name:
                    continue
                if is_iriun_name(name) and not is_ivcam_name(name):
                    continue
                self.entry_source.delete(0, tk.END)
                self.entry_source.insert(0, str(idx))
                self.config['source'] = str(idx)
                self.devices_label.config(text=f"Выбранное устройство: {name} ({idx})")
                if self.open_camera_source(str(idx), verbose=False):
                    opened = True
                    break
            if not opened:
                for idx, name in self.devices_combined:
                    if "нет видеопотока" in name:
                        continue
                    self.entry_source.delete(0, tk.END)
                    self.entry_source.insert(0, str(idx))
                    self.config['source'] = str(idx)
                    self.devices_label.config(text=f"Выбранное устройство: {name} ({idx})")
                    if self.open_camera_source(str(idx), verbose=False):
                        opened = True
                        break
            if not opened and self.devices_combined:
                first_src, first_name = self.devices_combined[0]
                self.entry_source.delete(0, tk.END)
                self.entry_source.insert(0, str(first_src))
                self.config['source'] = str(first_src)
                self.devices_label.config(text=f"Выбранное устройство: {first_name} ({first_src})")
                self.open_camera_source(str(first_src), verbose=False)
        else:
            self.devices_listbox.insert(tk.END, "❌ USB-камеры не найдены")

    def scan_network_cameras(self):
        self.devices_listbox.delete(0, tk.END)
        self.devices_listbox.insert(tk.END, "📱 Сканирование сети...")

        def _scan_thread():
            ip_list = scan_ip_cameras()
            try:
                self.root.after(0, lambda: self._on_network_cameras_scanned(ip_list))
            except Exception:
                pass

        threading.Thread(target=_scan_thread, daemon=True).start()

    def _on_network_cameras_scanned(self, ip_list):
        if not hasattr(self, 'devices_listbox'):
            return
        self.devices_listbox.delete(0, tk.END)
        self.devices_combined = []
        self.ip_camera_list = ip_list
        if self.ip_camera_list:
            for url, name in self.ip_camera_list:
                display = f"{name} — {url}"
                self.devices_listbox.insert(tk.END, display)
                self.devices_combined.append((url, name))
        else:
            self.devices_listbox.insert(tk.END, "❌ IP-камеры не найдены")
        if getattr(self, 'camera_list', None):
            if self.camera_list:
                for idx, name in self.camera_list:
                    display = f"[{idx}] {name}"
                    self.devices_listbox.insert(tk.END, display)
                    self.devices_combined.append((idx, name))
        if self.devices_combined:
            first_src = self.devices_combined[0][0]
            self.entry_source.delete(0, tk.END)
            self.entry_source.insert(0, str(first_src))
            self.devices_label.config(text=f"Выбранное устройство: {self.devices_combined[0][1]} ({first_src})")
            self.devices_listbox.selection_clear(0, tk.END)
            self.devices_listbox.selection_set(0)
            self.devices_listbox.activate(0)
            self.open_camera_source(str(first_src), verbose=False)

    def open_camera_source(self, source, verbose=True):
        try:
            if self.preview_worker:
                try:
                    self.preview_worker.stop()
                except Exception:
                    pass
                self.preview_worker = None

            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None

            time.sleep(0.05)

            source_clean = str(source).strip().strip('"').strip("'")
            is_file = is_video_file_source(source_clean) or is_video_file_path(source_clean)
            is_net = is_network_source(source_clean)

            cap = None
            frame = None
            ret = False

            if is_file:
                abs_f = os.path.normpath(os.path.abspath(os.path.expanduser(source_clean)))
                if not os.path.isfile(abs_f):
                    if verbose:
                        messagebox.showerror("❌ Ошибка", f"Видеофайл не найден по указанному пути:\n{abs_f}", parent=self.root)
                    return False
                if os.path.getsize(abs_f) == 0:
                    if verbose:
                        messagebox.showerror(
                            "❌ Ошибка",
                            f"Видеофайл пуст (0 байт):\n{abs_f}\n\n"
                            "Файл не был сохранён или повреждён при записи.",
                            parent=self.root
                        )
                    return False
                cap = open_video_file_capture(abs_f)
                ret, frame = read_valid_frame(cap, attempts=10)
                if not ret or frame is None:
                    repaired = repair_video_file_if_needed(abs_f)
                    if repaired and os.path.isfile(repaired):
                        cap = open_video_file_capture(repaired)
                        ret, frame = read_valid_frame(cap, attempts=10)
                        if ret and frame is not None:
                            self.config['source'] = repaired
                            self.entry_source.delete(0, tk.END)
                            self.entry_source.insert(0, repaired)
                            source_clean = repaired
            elif is_net:
                cap = create_video_capture(source_clean)
                ret, frame = read_valid_frame(cap, attempts=20)
            elif is_miicam_source(source_clean):
                cap, frame, backend = open_camera_device(source_clean, width=None, height=None, max_attempts=20)
                ret = (cap is not None and cap.isOpened() and frame is not None and frame.size > 0)
            else:
                try:
                    index = int(source_clean)
                except ValueError:
                    index = 0
                cap, frame, backend = open_camera_device(index, width=None, height=None, max_attempts=20)
                ret = (cap is not None and cap.isOpened() and frame is not None and frame.size > 0)

            if ret and frame is not None:
                if is_file:
                    try:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass

                h, w = frame.shape[:2]
                self.cap = cap
                self.latest_frame = frame.copy()
                self.preview_worker = PreviewWorker(self.cap, is_file=is_file, initial_frame=frame)

                # Применение настроек сенсора RGB-детектора (выдержка, gain, wb)
                if is_miicam_source(source_clean) and hasattr(self.cap, 'apply_settings_dict'):
                    try:
                        self.cap.apply_settings_dict(self.config)
                    except Exception:
                        pass
                
                # Update status label
                display_name = source_clean
                for s, name in getattr(self, 'devices_combined', []):
                    if str(s) == str(source_clean):
                        display_name = name
                        break
                self.devices_label.config(text=f"Выбранное устройство: {display_name} ({w}x{h})")

                if verbose:
                    if is_file:
                        messagebox.showinfo("✅ Успех", f"Видеофайл успешно открыт!\nРазрешение: {w}x{h}", parent=self.root)
                    else:
                        messagebox.showinfo("✅ Успех", f"Камера подключена!\nРазрешение: {w}x{h}", parent=self.root)
                return True

            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

            if verbose:
                if is_file:
                    msg = (
                        f"Не удалось прочитать видеофайл:\n{source_clean}\n\n"
                        "Возможные причины:\n"
                        "• Файл MP4 повреждён или не был финализирован.\n"
                        "• Файл сейчас открыт на запись другой программой.\n"
                        "• Видеокодек не поддерживается системой."
                    )
                elif is_net:
                    msg = f"Не удалось получить видеопоток по сети:\n{source_clean}"
                else:
                    msg = (
                        f"Не удалось получить видеопоток с камеры (источник: {source_clean}).\n\n"
                        "💡 Рекомендации:\n"
                        "1. Если используется телефон через iVCam или Iriun:\n"
                        "   • Убедитесь, что приложение на смартфоне открыто и на экране горит «Подключено».\n"
                        "   • Перезапустите приложение iVCam / Iriun на телефоне.\n\n"
                        "2. Если используется USB-камера:\n"
                        "   • Кликните по камере в списке слева.\n"
                        "   • Проверьте, не открыта ли камера в другой программе (Zoom, Skype, браузер)."
                    )
                messagebox.showwarning("⚠️ Источник не отвечает", msg, parent=self.root)
        except Exception as e:
            if verbose:
                messagebox.showerror("❌ Ошибка", str(e), parent=self.root)
        return False

    def check_camera(self):
        source = self.entry_source.get().strip()
        self.open_camera_source(source, verbose=True)

    def apply_source(self):
        source = self.entry_source.get().strip()
        if not source:
            messagebox.showerror("Ошибка", "Пустое поле источника", parent=self.root)
            return
        self.config['source'] = source

        success = self.open_camera_source(source, verbose=False)
        if success:
            try:
                display_name = source
                for s, name in getattr(self, 'devices_combined', []):
                    if str(s) == str(source) or s == source:
                        display_name = name
                        break
                self.devices_label.config(text=f"Выбранное устройство: {display_name}")
            except Exception:
                pass
            messagebox.showinfo("Применено", "Источник видео применён", parent=self.root)
        else:
            messagebox.showwarning("Внимание", "Источник сохранён, но подключиться не удалось", parent=self.root)

    def on_device_select(self, event):
        sel = event.widget.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < 0 or idx >= len(getattr(self, 'devices_combined', [])):
            self.devices_label.config(text="Выбранное устройство: —")
            return
        src, name = self.devices_combined[idx]
        self.entry_source.delete(0, tk.END)
        self.entry_source.insert(0, str(src))
        self.config['source'] = str(src)
        self.devices_label.config(text=f"Выбранное устройство: {name} ({src})")
        self.open_camera_source(str(src), verbose=False)

    def on_device_activate(self, event):
        self.on_device_select(event)

                                                                   
    def on_preview_mouse_hover(self, event):
        if self.preview_scale <= 0:
            return
        x = int(event.x / self.preview_scale)
        y = int(event.y / self.preview_scale)
        x0 = self.safe_get_int(self.var_x, 0)
        y0 = self.safe_get_int(self.var_y, 0)
        w = self.safe_get_int(self.var_w, self.MIN_ROI_SIZE)
        h = self.safe_get_int(self.var_h, self.MIN_ROI_SIZE)
        x1 = x0 + w
        y1 = y0 + h
        if self.roi_shape_var.get() == 'circle':
            cx = x0 + w / 2
            cy = y0 + h / 2
            radius = min(w, h) / 2
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= radius + self.HANDLE_SIZE and dist >= radius - self.HANDLE_SIZE:
                self.preview_label.config(cursor="fleur")
            elif dist <= radius:
                self.preview_label.config(cursor="fleur")
            else:
                self.preview_label.config(cursor="arrow")
        else:
            handle = self.get_roi_handle(x, y, x0, y0, x1, y1)
            if handle:
                cursors = {
                    'top_left': 'size_nw_se',
                    'top_right': 'size_ne_sw',
                    'bottom_left': 'size_ne_sw',
                    'bottom_right': 'size_nw_se',
                    'left': 'size_we',
                    'right': 'size_we',
                    'top': 'size_ns',
                    'bottom': 'size_ns'
                }
                self.preview_label.config(cursor=cursors.get(handle, 'cross'))
            elif x0 <= x <= x1 and y0 <= y <= y1:
                self.preview_label.config(cursor="fleur")
            else:
                self.preview_label.config(cursor="arrow")

    def on_preview_mouse_down(self, event):
        if self.preview_scale <= 0:
            return
        x = int(event.x / self.preview_scale)
        y = int(event.y / self.preview_scale)
        x0 = self.safe_get_int(self.var_x, 0)
        y0 = self.safe_get_int(self.var_y, 0)
        w = self.safe_get_int(self.var_w, self.MIN_ROI_SIZE)
        h = self.safe_get_int(self.var_h, self.MIN_ROI_SIZE)
        x1 = x0 + w
        y1 = y0 + h
        self.roi_start = (x, y)
        self.roi_orig = (x0, y0, w, h)
        if self.roi_shape_var.get() == 'circle':
            cx = x0 + w / 2
            cy = y0 + h / 2
            radius = min(w, h) / 2
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= radius + self.HANDLE_SIZE and dist >= radius - self.HANDLE_SIZE:
                self.roi_action = 'resize_circle'
                self.roi_drag = True
            elif dist <= radius:
                self.roi_action = 'move'
                self.roi_drag = True
            return
        handle = self.get_roi_handle(x, y, x0, y0, x1, y1)
        if handle:
            self.roi_action = 'resize'
            self.roi_handle = handle
            self.roi_drag = True
        elif x0 <= x <= x1 and y0 <= y <= y1:
            self.roi_action = 'move'
            self.roi_drag = True

    def on_preview_mouse_move(self, event):
        if not self.roi_drag:
            return
        x = int(event.x / self.preview_scale)
        y = int(event.y / self.preview_scale)
        x0, y0, w, h = self.roi_orig
        x1 = x0 + w
        y1 = y0 + h
        if self.roi_action == 'move':
            dx = x - self.roi_start[0]
            dy = y - self.roi_start[1]
            new_x = x0 + dx
            new_y = y0 + dy
            max_x = max(0, self.preview_width - w)
            max_y = max(0, self.preview_height - h)
            self.var_x.set(max(0, min(new_x, max_x)))
            self.var_y.set(max(0, min(new_y, max_y)))
            self.update_coord_label()
        elif self.roi_action == 'resize_circle':
            cx = x0 + w / 2
            cy = y0 + h / 2
            new_radius = max(self.MIN_ROI_SIZE / 2, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5)
            new_size = max(self.MIN_ROI_SIZE, int(new_radius * 2))
            new_x = max(0, int(cx - new_size / 2))
            new_y = max(0, int(cy - new_size / 2))
            self.var_x.set(new_x)
            self.var_y.set(new_y)
            self.var_w.set(new_size)
            self.var_h.set(new_size)
            self.update_coord_label()
        elif self.roi_action == 'resize':
            new_x0, new_y0, new_x1, new_y1 = x0, y0, x1, y1
            if 'left' in self.roi_handle:
                new_x0 = min(x, x1 - self.MIN_ROI_SIZE)
            if 'right' in self.roi_handle:
                new_x1 = max(x, x0 + self.MIN_ROI_SIZE)
            if 'top' in self.roi_handle:
                new_y0 = min(y, y1 - self.MIN_ROI_SIZE)
            if 'bottom' in self.roi_handle:
                new_y1 = max(y, y0 + self.MIN_ROI_SIZE)
            self.var_x.set(max(0, new_x0))
            self.var_y.set(max(0, new_y0))
            self.var_w.set(max(self.MIN_ROI_SIZE, new_x1 - new_x0))
            self.var_h.set(max(self.MIN_ROI_SIZE, new_y1 - new_y0))
            self.update_coord_label()
        self.clamp_roi()

    def on_preview_mouse_up(self, event):
        self.roi_drag = False
        self.roi_action = None
        self.roi_handle = None

    def get_roi_handle(self, x, y, x0, y0, x1, y1):
        th = self.HANDLE_SIZE
        handles = {
            'top_left': (x0, y0),
            'top_right': (x1, y0),
            'bottom_left': (x0, y1),
            'bottom_right': (x1, y1),
            'left': (x0, (y0 + y1) // 2),
            'right': (x1, (y0 + y1) // 2),
            'top': ((x0 + x1) // 2, y0),
            'bottom': ((x0 + x1) // 2, y1)
        }
        for name, (hx, hy) in handles.items():
            if abs(x - hx) <= th and abs(y - hy) <= th:
                return name
        return None

    def clamp_roi(self):
        x = self.safe_get_int(self.var_x, 0)
        y = self.safe_get_int(self.var_y, 0)
        w = self.safe_get_int(self.var_w, self.MIN_ROI_SIZE)
        h = self.safe_get_int(self.var_h, self.MIN_ROI_SIZE)
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        self.var_x.set(x)
        self.var_y.set(y)
        self.var_w.set(max(self.MIN_ROI_SIZE, min(w, max(0, self.preview_width) - x)))
        self.var_h.set(max(self.MIN_ROI_SIZE, min(h, max(0, self.preview_height) - y)))
        self.update_coord_label()

                                            
    def _clamp_rgb_int(self, value):
        return int(max(0, min(255, round(float(value)))))

    def _rgb_hex(self, r, g, b):
        return f"#{self._clamp_rgb_int(r):02x}{self._clamp_rgb_int(g):02x}{self._clamp_rgb_int(b):02x}"

    def _update_preview_rgb_signal(self, mean_r, mean_g, mean_b):
        log_br = compute_log_br(mean_b, mean_r)
        self.preview_current_rgb = (float(mean_r), float(mean_g), float(mean_b), float(log_br))
        self.preview_rgb_history.append((float(mean_r), float(mean_g), float(mean_b), float(log_br)))
        self.preview_rgb_var.set(f"R:{mean_r:6.1f}  G:{mean_g:6.1f}  B:{mean_b:6.1f}")
        if np.isfinite(log_br):
            self.preview_log_var.set(f"Log10(B/R): {log_br: .4f}")
        else:
            self.preview_log_var.set("Log10(B/R): —")
        try:
            self.preview_color_canvas.delete("all")
            self.preview_color_canvas.create_rectangle(
                0, 0, 60, 28, fill=self._rgb_hex(mean_r, mean_g, mean_b), outline=""
            )
        except Exception:
            pass
        self.draw_preview_rgb_graph()

    def draw_preview_rgb_graph(self):
        canvas = getattr(self, 'preview_rgb_canvas', None)
        if canvas is None:
            return
        try:
            canvas.delete("all")
            w = max(200, int(canvas.winfo_width()))
            h = max(80, int(canvas.winfo_height()))
            left, right, top, bottom = 34, 6, 8, 18
            plot_w = max(10, w - left - right)
            plot_h = max(10, h - top - bottom)
            for val in (0, 100, 200, 300):
                y = top + plot_h - (val / 300.0) * plot_h
                canvas.create_line(left, y, left + plot_w, y, fill="#e5e5e5")
                canvas.create_text(4, y, anchor="w", text=str(val), fill="#555555", font=("Arial", 8))
            canvas.create_line(left, top, left, top + plot_h, fill="#888888")
            canvas.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill="#888888")
            data = list(self.preview_rgb_history)
            if len(data) < 2:
                return
            def points(channel_idx):
                pts = []
                n = len(data)
                for i, row in enumerate(data):
                    x = left + (i / max(1, n - 1)) * plot_w
                    y = top + plot_h - (max(0.0, min(300.0, row[channel_idx])) / 300.0) * plot_h
                    pts.extend((x, y))
                return pts
            canvas.create_line(*points(0), fill="red", width=2)
            canvas.create_line(*points(1), fill="green", width=2)
            canvas.create_line(*points(2), fill="blue", width=2)
            canvas.create_text(w - 6, 6, anchor="ne", text="R G B", fill="#333333", font=("Arial", 9, "bold"))
        except Exception:
            pass

    def _compute_roi_means(self, frame, config):
        x = config['roi_x']
        y = config['roi_y']
        w = config['roi_w']
        h = config['roi_h']
        h_f, w_f = frame.shape[:2]
        safe_x = max(0, min(x, w_f - 1))
        safe_y = max(0, min(y, h_f - 1))
        safe_w = max(10, min(w, w_f - safe_x))
        safe_h = max(10, min(h, h_f - safe_y))
        roi = frame[safe_y:safe_y + safe_h, safe_x:safe_x + safe_w]
        if config.get('roi_shape', 'rect') == 'circle':
            mask = np.zeros((safe_h, safe_w), dtype=np.uint8)
            radius = min(safe_w, safe_h) // 2
            center = (safe_w // 2, safe_h // 2)
            cv2.circle(mask, center, radius, 255, -1)
            mean_b, mean_g, mean_r, _ = cv2.mean(roi, mask=mask)
        else:
            mean_b, mean_g, mean_r, _ = cv2.mean(roi)
        return mean_b, mean_g, mean_r, safe_x, safe_y, safe_w, safe_h, h_f, w_f

    def update_preview(self):
        if not getattr(self, 'is_running', False):
            return
        try:
            if getattr(self, 'roi_drag', False):
                return

            raw_frame = None
            if getattr(self, 'preview_worker', None) is not None:
                raw_frame = self.preview_worker.get_latest_frame()
            if raw_frame is None and getattr(self, 'cap', None) is not None and self.cap.isOpened():
                try:
                    ret, f = self.cap.read()
                    if ret and f is not None and f.size > 0:
                        raw_frame = f
                except Exception:
                    pass
            if raw_frame is None and getattr(self, 'latest_frame', None) is not None:
                raw_frame = self.latest_frame.copy()

            if raw_frame is not None and raw_frame.size > 0:
                # Save clean pristine frame in cache
                self.latest_frame = raw_frame.copy()

                # Separate display copy exclusively for on-screen overlays
                display_frame = raw_frame.copy()

                x = self.safe_get_int(self.var_x, 0)
                y = self.safe_get_int(self.var_y, 0)
                w = self.safe_get_int(self.var_w, self.MIN_ROI_SIZE)
                h = self.safe_get_int(self.var_h, self.MIN_ROI_SIZE)
                height, width = raw_frame.shape[:2]
                preview_width = self.preview_label.winfo_width()
                preview_height = self.preview_label.winfo_height()
                if preview_width <= 1:
                    preview_width = 1200
                if preview_height <= 1:
                    preview_height = 800
                scale_w = preview_width / width if width > 0 else 1.0
                scale_h = preview_height / height if height > 0 else 1.0
                scale = min(scale_w, scale_h)
                self.preview_scale = scale
                self.preview_width = width
                self.preview_height = height
                self.update_coord_label()
                now_preview = time.time()
                if now_preview - self.preview_last_rgb_update >= (self.preview_rgb_interval_ms / 1000.0):
                    preview_config = {
                        'roi_x': max(0, int(x)), 'roi_y': max(0, int(y)),
                        'roi_w': max(self.MIN_ROI_SIZE, int(w)), 'roi_h': max(self.MIN_ROI_SIZE, int(h)),
                        'roi_shape': self.roi_shape_var.get(),
                    }
                    try:
                        mean_b, mean_g, mean_r, *_ = self._compute_roi_means(raw_frame, preview_config)
                        self._update_preview_rgb_signal(mean_r, mean_g, mean_b)
                        self.preview_last_rgb_update = now_preview
                    except Exception:
                        pass
                if self.roi_shape_var.get() == 'circle':
                    cx = int(x + w / 2)
                    cy = int(y + h / 2)
                    radius = int(min(w, h) / 2)
                    cv2.circle(display_frame, (cx, cy), radius, (0, 255, 0), 3)
                    for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
                        rad = np.radians(angle)
                        px = int(cx + radius * np.cos(rad))
                        py = int(cy + radius * np.sin(rad))
                        cv2.rectangle(display_frame, (px-6, py-6), (px+6, py+6), (255, 255, 0), 2)
                    cv2.rectangle(display_frame, (cx-4, cy-4), (cx+4, cy+4), (255, 255, 0), -1)
                else:
                    cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 255, 0), 3)
                    handle_color = (255, 255, 0)
                    for cx, cy in [(x, y), (x+w, y), (x, y+h), (x+w, y+h),
                                   (x+w//2, y), (x+w//2, y+h), (x, y+h//2), (x+w, y+h//2)]:
                        cv2.rectangle(display_frame, (cx-6, cy-6), (cx+6, cy+6), handle_color, 2)
                info_text = f"X:{x} Y:{y} W:{w} H:{h}"
                cv2.putText(display_frame, info_text, (10, height - 20), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                if self.preview_current_rgb is not None:
                    pr, pg, pb, plog = self.preview_current_rgb
                    fps_val = getattr(self.preview_worker, 'current_fps', 0.0) if self.preview_worker else 0.0
                    if fps_val <= 0.0 and getattr(self, 'cap', None) is not None:
                        try:
                            fps_val = self.cap.get(cv2.CAP_PROP_FPS)
                        except Exception:
                            fps_val = 0.0
                    fps_str = f"FPS: {fps_val:.0f}" if fps_val > 0 else "FPS: 60"
                    overlay_lines = [
                        f"ROI RGB  R:{pr:5.1f}  G:{pg:5.1f}  B:{pb:5.1f}  |  {fps_str}",
                        f"Log10(B/R): {plog: .4f}",
                    ]
                    cv2.rectangle(display_frame, (8, 8), (470, 68), (0, 0, 0), -1)
                    cv2.rectangle(display_frame, (8, 8), (470, 68), (255, 255, 255), 1)
                    cv2.putText(display_frame, overlay_lines[0], (18, 32),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
                    cv2.putText(display_frame, overlay_lines[1], (18, 58),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
                new_width = int(width * scale)
                new_height = int(height * scale)
                preview_frame = cv2.resize(display_frame, (new_width, new_height))
                rgb_frame = cv2.cvtColor(preview_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb_frame)
                imgtk = ImageTk.PhotoImage(image=img)
                self.preview_label.imgtk = imgtk
                self.preview_label.configure(image=imgtk)
            else:
                self._render_empty_preview_placeholder()
        except Exception:
            pass
        finally:
            if getattr(self, 'is_running', False):
                self.root.after(10, self.update_preview)

    def _render_empty_preview_placeholder(self):
        try:
            pw = max(320, self.preview_label.winfo_width())
            ph = max(240, self.preview_label.winfo_height())
            if pw <= 1:
                pw = 800
            if ph <= 1:
                ph = 500

            light = bool(self.config.get('light_theme', False))
            bg_color = (242, 243, 248) if light else (14, 18, 27)
            card_bg = (255, 255, 255) if light else (22, 30, 46)
            text_color = (20, 30, 50) if light else (235, 240, 250)
            sub_color = (80, 95, 120) if light else (150, 165, 190)
            accent_color = (30, 64, 175) if light else (59, 130, 246)

            img = Image.new("RGB", (pw, ph), color=bg_color)
            draw = ImageDraw.Draw(img)

            font_title = _get_unicode_font(15, bold=True)
            font_body = _get_unicode_font(13, bold=False)
            font_hint = _get_unicode_font(12, bold=False)

            cx, cy = pw // 2, ph // 2
            card_w, card_h = min(pw - 30, 600), min(ph - 30, 230)
            x0, y0 = cx - card_w // 2, cy - card_h // 2
            x1, y1 = cx + card_w // 2, cy + card_h // 2

            draw.rectangle([x0, y0, x1, y1], fill=card_bg, outline=accent_color, width=2)

            cur_src = self.entry_source.get().strip() or "0"
            draw.text((x0 + 24, y0 + 22), f"Камера: [ {cur_src} ] — ожидание видеопотока", font=font_title, fill=text_color)
            draw.text((x0 + 24, y0 + 62), "1. Кликните по нужному устройству в списке «USB-камеры» слева", font=font_body, fill=sub_color)
            draw.text((x0 + 24, y0 + 96), "2. Для iVCam / Iriun: откройте приложение на телефоне и подключите к ПК", font=font_body, fill=sub_color)
            draw.text((x0 + 24, y0 + 130), "3. Либо нажмите кнопку «Переподключить»", font=font_body, fill=sub_color)
            draw.text((x0 + 24, y0 + 165), "[i] Для сетевой IP-камеры нажмите кнопку «IP-камеры (сеть)»", font=font_hint, fill=accent_color)

            imgtk = ImageTk.PhotoImage(image=img)
            self.preview_label.imgtk = imgtk
            self.preview_label.configure(image=imgtk)
        except Exception:
            pass

                                          
    def start_analysis(self):
        # Проверка статуса лицензии и пробного периода
        status = self.lic_mgr.get_status()
        if not status.get("is_allowed", False):
            messagebox.showwarning(
                "Требуется активация",
                "Срок действия ознакомительного демо-режима истёк.\n"
                "Пожалуйста, введите ключ активации для продолжения работы.",
                parent=self.root
            )
            self.open_license_dialog(block_if_expired=False)
            return

        self.config['source'] = self.entry_source.get().strip()
        # The analysis button may be launched while the startup preview is
        # still holding a camera capture. A selected video file must always
        # get its own capture object; never reuse the previously opened camera.
        source_is_file = is_video_file_source(self.config['source']) or is_video_file_path(self.config['source'])
        self.config['source_is_file'] = source_is_file
        self.config['roi_x'] = self.safe_get_int(self.var_x, 0)
        self.config['roi_y'] = self.safe_get_int(self.var_y, 0)
        self.config['roi_w'] = max(self.MIN_ROI_SIZE, self.safe_get_int(self.var_w, self.MIN_ROI_SIZE))
        self.config['roi_h'] = max(self.MIN_ROI_SIZE, self.safe_get_int(self.var_h, self.MIN_ROI_SIZE))
        self.config['roi_shape'] = self.roi_shape_var.get()
        self.config['save_folder'] = self.entry_save_folder.get().strip()
        self.config['video_folder'] = self.config['save_folder']

        if not self.config['source']:
            messagebox.showerror("Ошибка", "Укажите источник видео (индекс или URL)")
            return
        save_folder = self.config['save_folder']
        if not save_folder or not os.path.isdir(save_folder):
            messagebox.showerror(
                "Ошибка",
                "Папка для сохранения результатов не существует или недоступна.\n"
                "Выберите папку через «Обзор...» (не используйте system32)."
            )
            return
        if not os.access(save_folder, os.W_OK):
            messagebox.showerror("Ошибка", f"Нет прав на запись в папку результатов:\n{save_folder}")
            return

        # Never reuse the startup camera capture for a video-file analysis.
        # For video files, always close any preview capture and pass cap=None
        # so run_analysis opens a dedicated fresh capture from frame 0.
        if self.preview_worker is not None:
            try:
                self.preview_worker.stop()
            except Exception:
                pass
            self.preview_worker = None

        if source_is_file:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            cap = None
        elif self.cap is None or not self.cap.isOpened():
            if not self.open_camera_source(self.config['source'], verbose=True):
                return
            if self.preview_worker is not None:
                try:
                    self.preview_worker.stop()
                except Exception:
                    pass
                self.preview_worker = None
            cap = self.cap
            self.cap = None
        else:
            ret, frame = read_valid_frame(self.cap, attempts=10)
            if (not ret) or ((not is_network_source(self.config['source']) and not is_video_file_source(self.config['source'])) and is_placeholder_frame(frame)):
                if not self.open_camera_source(self.config['source'], verbose=True):
                    return
            if self.preview_worker is not None:
                try:
                    self.preview_worker.stop()
                except Exception:
                    pass
                self.preview_worker = None
            cap = self.cap
            self.cap = None

        self.is_running = False
        if not source_is_file:
            self.root.withdraw()
        res = None
        try:
            res = run_analysis(self.config, parent=self.root, cap=cap)
        except Exception as e:
            print(f"❌ Ошибка при выполнении анализа: {e}")
            messagebox.showerror("Ошибка анализа", f"Произошла ошибка при анализе:\n{e}")
        finally:
            self.is_running = True
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            if not source_is_file and self.config.get('source'):
                try:
                    self.open_camera_source(self.config['source'], verbose=False)
                except Exception:
                    pass
            self.update_preview()

            if res and isinstance(res, dict):
                save_err = res.get('save_error')
                if save_err:
                    messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить результаты:\n\n{save_err}", parent=self.root)
                elif res.get('saved_data') or res.get('excel_path'):
                    lines = [
                        f"Записей: {len(res.get('saved_data', []))}",
                        f"Папка: {res.get('save_folder', '')}",
                    ]
                    if res.get('excel_path'):
                        lines.append(f"Excel: {res['excel_path']}")
                    if res.get('raw_csv_path'):
                        lines.append(f"Аварийный CSV RGB: {res['raw_csv_path']}")
                    if res.get('video_saved_path'):
                        lines.append(f"Видео: {res['video_saved_path']}")
                    if res.get('ann_count'):
                        lines.append(f"Метки: {res['ann_count']} шт. (лист Annotations)")
                    msg = "Результаты сохранены:\n\n" + "\n".join(lines)
                    messagebox.showinfo("Сохранено", msg, parent=self.root)

    def on_closing(self):
        self.is_running = False
        if self.cap:
            self.cap.release()
        self.root.destroy()
        exit()


                                                           
if __name__ == "__main__":
    app = SetupApp()

