import json
import textwrap
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .settings_window import SettingsWindow, load_saved_settings
import cv2
import numpy as np
import time
import os
import socket
import threading
from PIL import Image, ImageTk, ImageDraw, ImageFont
from collections import deque
from ..utils.math_utils import compute_log_br

from ..utils.helpers import (
    compute_roi_means,
    detect_green_circle_roi,
    scan_cameras, scan_ip_cameras, scan_miicam_cameras, create_video_capture, open_camera_device, warmup_capture,
    read_valid_frame, verify_capture_can_read, is_network_source, is_placeholder_frame, is_miicam_source,
    ivcam_setup_hint, get_default_save_folder, get_local_ip,
    camera_label, camera_priority, is_ivcam_name, is_iriun_name, is_video_file_source, is_video_file_path, repair_video_file_if_needed, open_video_file_capture
)
from ..utils.ffmpeg_utils import ensure_pyqt5_platform_plugin_path
from ..analysis.runner import run_analysis
from ..config import ELUTEK_LIGHT_BG, ELUTEK_200, ELUTEK_300, ELUTEK_BRAND, ELUTEK_600, ELUTEK_INK, ELUTEK_ACCENT, ELUTEK_PANEL_DARK
from ..utils.license_manager import (
    LicenseManager, LICENSE_STATUS_LICENSED,
    LICENSE_STATUS_TRIAL_ACTIVE, LICENSE_STATUS_TRIAL_EXPIRED
)
from .theme import get_palette
from .license_dialog import LicenseDialog


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
                    # High-throughput non-blocking sleep (up to 120+ FPS with 0% CPU overhead)
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
            return self._latest_frame

    def get_fps(self):
        return self.current_fps

    def stop(self):
        self._running = False
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.3)


class SetupApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Элютек · SARA RGB анализ")
        self.root.geometry("1480x900")
        self.root.minsize(1180, 720)
        
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
            'light_theme': True,
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
            # Calibrated RGB Detector (MiiCam) default parameters
            'miicam_auto_exposure': False,
            'miicam_exposure_us': 22000,
            'miicam_gain': 100,
            'miicam_brightness': 0,
            'miicam_contrast': 0,
            'miicam_gamma': 100,
            'miicam_hue': 0,
            'miicam_saturation': 128,
            'miicam_temp': 6500,
            'miicam_tint': 1000,
            'miicam_wb_r': 0,
            'miicam_wb_g': 0,
            'miicam_wb_b': 0,
            'miicam_speed': 2,
            'miicam_binning': 1,
            'miicam_frame_preload': False,
            'miicam_thread_priority': 2,
            'miicam_h_flip': False,
            'miicam_v_flip': False,
            'miicam_anti_flicker': 1,
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
        self.preview_r_var = tk.StringVar(value="—")
        self.preview_g_var = tk.StringVar(value="—")
        self.preview_b_var = tk.StringVar(value="—")
        self.preview_log_value_var = tk.StringVar(value="—")
        self.camera_status_var = tk.StringVar(value="Ожидание камеры")
        self._preview_has_frame = False

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
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass

        light = bool(self.config.get('light_theme', True))
        colors = get_palette(light)
        bg = colors['background']
        surface = colors['surface']
        surface_alt = colors['surface_alt']
        fg = colors['text']
        muted = colors['muted']
        border = colors['border']
        accent = colors['accent']
        self._ui_palette = colors

        self.root.configure(bg=bg)
        style.configure('.', font=('Segoe UI', 10), background=bg, foreground=fg)
        style.configure('TFrame', background=bg)
        style.configure('App.TFrame', background=bg)
        style.configure('Header.TFrame', background=surface)
        style.configure(
            'Card.TFrame', background=surface, relief='solid', borderwidth=1,
            bordercolor=border, lightcolor=border, darkcolor=border
        )
        style.configure('CardInset.TFrame', background=surface_alt)
        style.configure('Metric.TFrame', background=surface, relief='solid', borderwidth=1,
                        bordercolor=border, lightcolor=border, darkcolor=border)

        style.configure('TLabel', background=bg, foreground=fg)
        style.configure('Header.TLabel', background=surface, foreground=fg)
        style.configure('BrandMark.TLabel', background=accent, foreground=colors['accent_on'],
                        font=('Segoe UI', 15, 'bold'), padding=(10, 6))
        style.configure('Title.TLabel', background=surface, foreground=fg,
                        font=('Segoe UI', 16, 'bold'))
        style.configure('Subtitle.TLabel', background=surface, foreground=muted,
                        font=('Segoe UI', 9))
        style.configure('SectionTitle.TLabel', background=bg, foreground=fg,
                        font=('Segoe UI', 16, 'bold'))
        style.configure('SectionSub.TLabel', background=bg, foreground=muted,
                        font=('Segoe UI', 9))
        style.configure('CardTitle.TLabel', background=surface, foreground=fg,
                        font=('Segoe UI', 10, 'bold'))
        style.configure('CardText.TLabel', background=surface, foreground=fg)
        style.configure('CardMuted.TLabel', background=surface, foreground=muted,
                        font=('Segoe UI', 9))
        style.configure('Muted.TLabel', background=bg, foreground=muted,
                        font=('Segoe UI', 9))
        style.configure('Eyebrow.TLabel', background=surface, foreground=muted,
                        font=('Segoe UI', 8, 'bold'))
        style.configure('MetricName.TLabel', background=surface, foreground=muted,
                        font=('Segoe UI', 9, 'bold'))
        style.configure('MetricValue.TLabel', background=surface, foreground=fg,
                        font=('Segoe UI', 20, 'bold'))
        style.configure('R.TLabel', background=surface, foreground=colors['channel_r'],
                        font=('Segoe UI', 9, 'bold'))
        style.configure('G.TLabel', background=surface, foreground=colors['channel_g'],
                        font=('Segoe UI', 9, 'bold'))
        style.configure('B.TLabel', background=surface, foreground=colors['channel_b'],
                        font=('Segoe UI', 9, 'bold'))
        style.configure('OnlineBadge.TLabel', background=colors['success_soft'],
                        foreground=colors['success'], padding=(10, 5), font=('Segoe UI', 9, 'bold'))
        style.configure('WaitingBadge.TLabel', background=surface_alt,
                        foreground=muted, padding=(10, 5), font=('Segoe UI', 9, 'bold'))
        style.configure('Preview.TLabel', background=colors['video_background'], foreground=colors['text'])

        style.configure('TButton', background=surface, foreground=fg, borderwidth=1,
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        focusthickness=0, padding=(10, 7), font=('Segoe UI', 9, 'bold'))
        style.map('TButton', background=[('disabled', surface_alt), ('pressed', colors['surface_hover']), ('active', colors['surface_hover'])],
                  foreground=[('disabled', muted)], bordercolor=[('active', colors['accent'])])
        style.configure('Primary.TButton', background=accent, foreground=colors['accent_on'],
                        borderwidth=0, padding=(14, 10), font=('Segoe UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('disabled', border), ('pressed', colors['accent_hover']), ('active', colors['accent_hover'])],
                  foreground=[('disabled', muted)])
        style.configure('Secondary.TButton', background=colors['accent_soft'], foreground=accent,
                        borderwidth=0, padding=(10, 8), font=('Segoe UI', 9, 'bold'))
        style.map('Secondary.TButton', background=[('pressed', colors['surface_hover']), ('active', colors['surface_hover'])],
                  foreground=[('disabled', muted)])
        style.configure('Quiet.TButton', background=surface, foreground=fg, borderwidth=1,
                        bordercolor=border, padding=(9, 7), font=('Segoe UI', 9, 'bold'))
        style.map('Quiet.TButton', background=[('pressed', colors['surface_hover']), ('active', colors['surface_hover'])],
                  bordercolor=[('active', colors['accent'])])
        style.configure('Small.TButton', background=surface_alt, foreground=fg, borderwidth=0,
                        padding=(5, 3), font=('Segoe UI', 9, 'bold'))
        style.map('Small.TButton', background=[('pressed', colors['surface_hover']), ('active', colors['surface_hover'])])
        style.configure('Danger.TButton', background=colors['danger_soft'], foreground=colors['danger'],
                        borderwidth=0, padding=(9, 7), font=('Segoe UI', 9, 'bold'))
        style.map('Danger.TButton', background=[('pressed', colors['danger_soft']), ('active', colors['danger_soft'])])

        style.configure('TEntry', fieldbackground=surface_alt, foreground=fg, padding=(8, 7),
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        insertcolor=fg, insertwidth=2)
        style.map('TEntry', fieldbackground=[('focus', surface), ('disabled', surface_alt)],
                  foreground=[('focus', fg), ('disabled', muted)])
        style.configure('TSpinbox', fieldbackground=surface_alt, foreground=fg, background=surface_alt,
                        arrowcolor=muted, padding=(6, 5), bordercolor=border,
                        lightcolor=border, darkcolor=border, insertcolor=fg)
        style.map('TSpinbox', fieldbackground=[('focus', surface), ('active', surface)],
                  foreground=[('focus', fg), ('active', fg)], background=[('focus', surface), ('active', surface)],
                  arrowcolor=[('focus', accent), ('active', accent)])
        style.configure('TCombobox', fieldbackground=surface_alt, background=surface_alt,
                        foreground=fg, arrowcolor=muted, padding=(7, 6), bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.map('TCombobox', fieldbackground=[('readonly', surface_alt), ('focus', surface), ('active', surface)],
                  foreground=[('readonly', fg), ('focus', fg), ('active', fg)],
                  background=[('readonly', surface_alt), ('focus', surface), ('active', surface)],
                  arrowcolor=[('readonly', muted), ('focus', accent), ('active', accent)])

        style.configure('TRadiobutton', background=surface, foreground=fg, padding=(8, 5))
        style.map('TRadiobutton', background=[('active', surface_alt), ('pressed', surface_alt)],
                  foreground=[('active', fg), ('pressed', fg)])
        style.configure('TCheckbutton', background=surface, foreground=fg, padding=(4, 4))
        style.map('TCheckbutton', background=[('active', surface), ('pressed', surface)],
                  foreground=[('active', fg), ('pressed', fg)])
        style.configure('TNotebook', background=bg, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', background=surface_alt, foreground=muted,
                        padding=(13, 9), borderwidth=0, font=('Segoe UI', 9, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', colors['accent_soft']), ('active', colors['surface_hover'])],
                  foreground=[('selected', accent), ('active', fg)])
        style.configure('TLabelframe', background=surface, foreground=fg, bordercolor=border,
                        lightcolor=border, darkcolor=border, relief='solid', borderwidth=1)
        style.configure('TLabelframe.Label', background=surface, foreground=fg,
                        font=('Segoe UI', 10, 'bold'), padding=(4, 0))
        style.configure('Treeview', background=surface, fieldbackground=surface,
                        foreground=fg, bordercolor=border, rowheight=30, font=('Segoe UI', 9))
        style.map('Treeview', background=[('selected', colors['accent_soft'])],
                  foreground=[('selected', accent)])
        style.configure('Treeview.Heading', background=surface_alt, foreground=muted,
                        font=('Segoe UI', 9, 'bold'), relief='flat', padding=(8, 7))
        style.map('Treeview.Heading', background=[('active', colors['surface_hover'])],
                  foreground=[('active', fg)])
        style.configure('Vertical.TScrollbar', background=bg, troughcolor=bg,
                        bordercolor=bg, arrowcolor=muted, gripcount=0)

        if hasattr(self, 'devices_listbox'):
            try:
                self.devices_listbox.configure(
                    bg=surface, fg=fg, selectbackground=colors['accent_soft'],
                    selectforeground=accent, font=('Segoe UI', 9), relief='flat', bd=0,
                    highlightthickness=1, highlightbackground=border, highlightcolor=accent,
                    activestyle='none'
                )
            except Exception:
                pass
        if hasattr(self, 'preview_color_canvas'):
            try:
                self.preview_color_canvas.configure(
                    bg=surface_alt, highlightthickness=1, highlightbackground=border
                )
            except Exception:
                pass
        if hasattr(self, 'preview_rgb_canvas'):
            try:
                self.preview_rgb_canvas.configure(
                    bg=surface, highlightthickness=1, highlightbackground=border
                )
            except Exception:
                pass
        if hasattr(self, 'preview_label'):
            try:
                self.preview_label.configure(background=colors['video_background'])
            except Exception:
                pass
        if hasattr(self, 'left_canvas'):
            try:
                self.left_canvas.configure(bg=bg, highlightthickness=0)
            except Exception:
                pass
        if hasattr(self, 'theme_btn'):
            try:
                self.theme_btn.config(text='Тёмная тема' if light else 'Светлая тема')
            except Exception:
                pass
        self._update_license_ui()

    def _set_preview_connection_state(self, connected):
        connected = bool(connected)
        if connected == getattr(self, '_preview_has_frame', False):
            return
        self._preview_has_frame = connected
        try:
            self.camera_status_var.set('Видеосигнал активен' if connected else 'Ожидание камеры')
            if hasattr(self, 'camera_status_badge'):
                self.camera_status_badge.configure(
                    style='OnlineBadge.TLabel' if connected else 'WaitingBadge.TLabel'
                )
        except Exception:
            pass

    def _update_license_ui(self):
        if not hasattr(self, 'lic_btn'):
            return
        try:
            status = self.lic_mgr.get_status()
            st = status.get('status')
            if st == LICENSE_STATUS_LICENSED:
                self.lic_btn.config(text="Лицензия · PRO")
            elif st == LICENSE_STATUS_TRIAL_ACTIVE:
                self.lic_btn.config(text=f"Демо · {status.get('days_left', 0)} дн.")
            else:
                self.lic_btn.config(text="Активировать лицензию")
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
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        try:
            self._apply_start_theme()
        except Exception:
            pass

        app_shell = ttk.Frame(self.root, style='App.TFrame')
        app_shell.pack(fill='both', expand=True)

        # Compact product header: identity and utilities stay separate from the
        # camera and analysis controls below.
        header = ttk.Frame(app_shell, style='Header.TFrame', padding=(22, 13))
        header.pack(fill='x')
        brand_mark = ttk.Label(header, text='E', style='BrandMark.TLabel', anchor='center')
        brand_mark.pack(side='left')
        brand_copy = ttk.Frame(header, style='Header.TFrame')
        brand_copy.pack(side='left', padx=(12, 0))
        ttk.Label(brand_copy, text='Элютек · SARA RGB', style='Title.TLabel').pack(anchor='w')
        ttk.Label(brand_copy, text='Визуально-оптический контроль фракционирования',
                  style='Subtitle.TLabel').pack(anchor='w', pady=(1, 0))

        self.theme_btn = ttk.Button(
            header, text='Тёмная тема' if self.config.get('light_theme', True) else 'Светлая тема',
            command=self.toggle_theme, style='Quiet.TButton'
        )
        self.theme_btn.pack(side='right')
        settings_btn = ttk.Button(
            header, text='Настройки', command=self.open_settings, style='Secondary.TButton'
        )
        settings_btn.pack(side='right', padx=(0, 8))
        self.lic_btn = ttk.Button(
            header, text='Лицензия', command=self.open_license_dialog, style='Quiet.TButton'
        )
        self.lic_btn.pack(side='right', padx=(0, 8))
        self._update_license_ui()

        main = ttk.Frame(app_shell, style='App.TFrame', padding=(20, 15, 20, 18))
        main.pack(fill='both', expand=True)

        # Workspace heading and live connection state.
        workspace_heading = ttk.Frame(main, style='App.TFrame')
        workspace_heading.pack(fill='x', pady=(0, 13))
        heading_copy = ttk.Frame(workspace_heading, style='App.TFrame')
        heading_copy.pack(side='left', fill='x', expand=True)
        ttk.Label(heading_copy, text='Рабочее пространство', style='SectionTitle.TLabel').pack(anchor='w')
        ttk.Label(heading_copy, text='Подключите источник, проверьте область ROI и запускайте анализ.',
                  style='SectionSub.TLabel').pack(anchor='w', pady=(3, 0))
        self.camera_status_badge = ttk.Label(
            workspace_heading, textvariable=self.camera_status_var, style='WaitingBadge.TLabel'
        )
        self.camera_status_badge.pack(side='right', padx=(12, 0), pady=(3, 0))

        main_body = ttk.Frame(main, style='App.TFrame')
        main_body.pack(fill='both', expand=True)

        # Scrollable control rail; the session action stays pinned at the bottom.
        left_outer = ttk.Frame(main_body, width=326, style='App.TFrame')
        left_outer.pack(side='left', fill='y')
        left_outer.pack_propagate(False)

        scroll_area = ttk.Frame(left_outer, style='App.TFrame')
        scroll_area.pack(fill='both', expand=True)
        left_canvas = tk.Canvas(scroll_area, highlightthickness=0, bd=0)
        self.left_canvas = left_canvas
        left_scrollbar = ttk.Scrollbar(scroll_area, orient='vertical', command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_canvas.pack(side='left', fill='both', expand=True)
        left_scrollbar.pack(side='right', fill='y')

        left = ttk.Frame(left_canvas, style='App.TFrame')
        left_window_id = left_canvas.create_window((0, 0), window=left, anchor='nw')

        def _update_left_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox('all'))

        def _fit_left_width(event):
            left_canvas.itemconfigure(left_window_id, width=event.width)

        def _on_left_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

        left.bind('<Configure>', _update_left_scrollregion)
        left_canvas.bind('<Configure>', _fit_left_width)
        left_canvas.bind('<Enter>', lambda event: left_canvas.bind_all('<MouseWheel>', _on_left_mousewheel))
        left_canvas.bind('<Leave>', lambda event: left_canvas.unbind_all('<MouseWheel>'))

        def make_card(parent, title, description=None):
            card = ttk.Frame(parent, style='Card.TFrame', padding=13)
            card.pack(fill='x', pady=(0, 10))
            title_row = ttk.Frame(card, style='Card.TFrame')
            title_row.pack(fill='x')
            ttk.Label(title_row, text=title, style='CardTitle.TLabel').pack(side='left', anchor='w')
            if description:
                ttk.Label(card, text=description, style='CardMuted.TLabel', wraplength=270,
                          justify='left').pack(anchor='w', pady=(4, 10))
            else:
                title_row.pack_configure(pady=(0, 10))
            return card

        # Camera discovery
        frame_scan = make_card(left, 'Устройства', 'Найдите подключённый RGB-детектор или камеру.')
        btn_frame = ttk.Frame(frame_scan, style='Card.TFrame')
        btn_frame.pack(fill='x', pady=(0, 8))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        ttk.Button(btn_frame, text='RGB-детектор', command=self.scan_rgb_detector,
                   style='Quiet.TButton').grid(row=0, column=0, sticky='ew', padx=(0, 4), pady=(0, 5))
        ttk.Button(btn_frame, text='USB-камеры', command=self.scan_usb_cameras,
                   style='Quiet.TButton').grid(row=0, column=1, sticky='ew', padx=(4, 0), pady=(0, 5))
        ttk.Button(btn_frame, text='IP-камеры', command=self.scan_network_cameras,
                   style='Quiet.TButton').grid(row=1, column=0, columnspan=2, sticky='ew')

        devices_box_frame = ttk.Frame(frame_scan, style='CardInset.TFrame', padding=4)
        devices_box_frame.pack(fill='both', expand=True, pady=(0, 8))
        self.devices_listbox = tk.Listbox(devices_box_frame, height=4, width=34, activestyle='none')
        self.devices_listbox.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(devices_box_frame, orient='vertical', command=self.devices_listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.devices_listbox.config(yscrollcommand=scrollbar.set)
        self.devices_listbox.bind('<<ListboxSelect>>', self.on_device_select)
        self.devices_listbox.bind('<Double-Button-1>', self.on_device_activate)
        self.devices_label = ttk.Label(
            frame_scan, text='Выбранное устройство: —', wraplength=270, style='CardMuted.TLabel'
        )
        self.devices_label.pack(fill='x')

        # Camera / stream source
        frame_cam = make_card(left, 'Источник видео', 'Индекс камеры, локальный адрес или RTSP-ссылка.')
        ttk.Label(frame_cam, text='URL или индекс устройства', style='CardMuted.TLabel').pack(anchor='w', pady=(0, 5))
        self.entry_source = ttk.Entry(frame_cam)
        self.entry_source.insert(0, self.config['source'])
        self.entry_source.pack(fill='x', pady=(0, 8))
        apply_frame = ttk.Frame(frame_cam, style='Card.TFrame')
        apply_frame.pack(fill='x')
        apply_frame.columnconfigure(0, weight=1)
        apply_frame.columnconfigure(1, weight=1)
        ttk.Button(apply_frame, text='Применить', command=self.apply_source,
                   style='Secondary.TButton').grid(row=0, column=0, sticky='ew', padx=(0, 4))
        ttk.Button(apply_frame, text='Переподключить', command=self.check_camera,
                   style='Quiet.TButton').grid(row=0, column=1, sticky='ew', padx=(4, 0))

        # Offline analysis remains available without changing the live path.
        frame_file = make_card(left, 'Видео из файла', 'Офлайн-анализ с перемоткой и теми же параметрами RGB/SARA.')
        ttk.Button(frame_file, text='Открыть видеофайл', command=self.choose_video_file_and_analyze,
                   style='Quiet.TButton').pack(fill='x')

        # ROI controls — all original variables and callbacks are preserved.
        frame_roi = make_card(left, 'Область анализа (ROI)', 'Задайте геометрию вручную или передвигайте ROI прямо на кадре.')
        self.var_x = tk.IntVar(value=300)
        self.var_y = tk.IntVar(value=150)
        self.var_w = tk.IntVar(value=200)
        self.var_h = tk.IntVar(value=200)
        self.roi_shape_var = tk.StringVar(value=str(self.config.get('roi_shape', 'circle')))

        shape_frame = ttk.Frame(frame_roi, style='Card.TFrame')
        shape_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(shape_frame, text='Форма', style='CardMuted.TLabel').pack(side='left', padx=(0, 7))
        ttk.Radiobutton(shape_frame, text='Круг', variable=self.roi_shape_var, value='circle').pack(side='left', padx=(0, 4))
        ttk.Radiobutton(shape_frame, text='Прямоугольник', variable=self.roi_shape_var, value='rect').pack(side='left')

        self.coord_label = ttk.Label(frame_roi, text='X: 0  Y: 0  W: 0  H: 0', style='CardMuted.TLabel')
        self.coord_label.pack(fill='x', pady=(0, 5))
        vcmd = self.root.register(self.validate_roi_entry)

        def create_spin_row(parent, label_text, var, min_val=0, max_val=1920):
            row = ttk.Frame(parent, style='Card.TFrame')
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=label_text, style='CardMuted.TLabel', width=9).pack(side='left')
            ttk.Button(row, text='−', width=2, style='Small.TButton',
                       command=lambda: self.adjust_value(var, -1, min_val, max_val)).pack(side='left', padx=(2, 3))
            entry = ttk.Entry(row, width=7, justify='center', textvariable=var,
                              validate='key', validatecommand=(vcmd, '%P', str(min_val), str(max_val)))
            entry.pack(side='left', padx=2)
            ttk.Button(row, text='+', width=2, style='Small.TButton',
                       command=lambda: self.adjust_value(var, 1, min_val, max_val)).pack(side='left', padx=(3, 0))
            var.trace_add('write', lambda *args: self.update_coord_label())
            return row

        create_spin_row(frame_roi, 'X', self.var_x, 0, 1920)
        create_spin_row(frame_roi, 'Y', self.var_y, 0, 1080)
        create_spin_row(frame_roi, 'Ширина', self.var_w, 20, 1920)
        create_spin_row(frame_roi, 'Высота', self.var_h, 20, 1080)

        size_btn_frame = ttk.Frame(frame_roi, style='Card.TFrame')
        size_btn_frame.pack(fill='x', pady=(8, 0))
        ttk.Button(size_btn_frame, text='Увеличить', style='Small.TButton',
                   command=lambda: self.change_roi_size(1.2)).pack(side='left', fill='x', expand=True, padx=(0, 3))
        ttk.Button(size_btn_frame, text='Уменьшить', style='Small.TButton',
                   command=lambda: self.change_roi_size(0.8)).pack(side='left', fill='x', expand=True, padx=3)
        ttk.Button(size_btn_frame, text='Сбросить', style='Small.TButton',
                   command=self.reset_roi).pack(side='left', fill='x', expand=True, padx=(3, 0))
        self.update_coord_label()

        frame_save = make_card(left, 'Сохранение результатов', 'Ряды, метки и видео будут сохранены в выбранную папку.')
        save_inner = ttk.Frame(frame_save, style='Card.TFrame')
        save_inner.pack(fill='x')
        self.entry_save_folder = ttk.Entry(save_inner)
        self.entry_save_folder.insert(0, self.config['save_folder'])
        self.entry_save_folder.pack(fill='x', pady=(0, 7))
        ttk.Button(save_inner, text='Выбрать папку…', command=self.choose_save_folder,
                   style='Quiet.TButton').pack(anchor='e')

        # The primary action is always visible, even when the control rail scrolls.
        action_bar = ttk.Frame(left_outer, style='App.TFrame', padding=(0, 12, 0, 0))
        action_bar.pack(fill='x')
        ttk.Button(action_bar, text='Запустить анализ', command=self.start_analysis,
                   style='Primary.TButton').pack(fill='x')
        ttk.Button(action_bar, text='Закрыть приложение', command=self.on_closing,
                   style='Quiet.TButton').pack(fill='x', pady=(7, 0))

        # Live monitoring workspace
        right = ttk.Frame(main_body, style='App.TFrame')
        right.pack(side='left', fill='both', expand=True, padx=(17, 0))
        metrics = ttk.Frame(right, style='App.TFrame')
        metrics.pack(fill='x', pady=(0, 13))

        metric_defs = [
            ('R', self.preview_r_var, 'R.TLabel', 'Среднее по ROI'),
            ('G', self.preview_g_var, 'G.TLabel', 'Среднее по ROI'),
            ('B', self.preview_b_var, 'B.TLabel', 'Среднее по ROI'),
            ('Log10 (B/R)', self.preview_log_value_var, 'MetricName.TLabel', 'Цветовой индекс'),
        ]
        for column, (label, value_var, label_style, caption) in enumerate(metric_defs):
            metrics.columnconfigure(column, weight=1, uniform='metric')
            tile = ttk.Frame(metrics, style='Metric.TFrame', padding=(14, 10))
            tile.grid(row=0, column=column, sticky='nsew', padx=(0 if column == 0 else 7, 7 if column < 3 else 0))
            ttk.Label(tile, text=label, style=label_style).pack(anchor='w')
            ttk.Label(tile, textvariable=value_var, style='MetricValue.TLabel').pack(anchor='w', pady=(2, 0))
            ttk.Label(tile, text=caption, style='CardMuted.TLabel').pack(anchor='w', pady=(1, 0))

        content = ttk.Frame(right, style='App.TFrame')
        content.pack(fill='both', expand=True)

        frame_prev = ttk.Frame(content, style='Card.TFrame', padding=13)
        frame_prev.pack(side='left', fill='both', expand=True)
        preview_header = ttk.Frame(frame_prev, style='Card.TFrame')
        preview_header.pack(fill='x', pady=(0, 10))
        preview_copy = ttk.Frame(preview_header, style='Card.TFrame')
        preview_copy.pack(side='left', fill='x', expand=True)
        ttk.Label(preview_copy, text='Видеопоток', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(preview_copy, text='Перетаскивайте контур, чтобы точно задать ROI.',
                  style='CardMuted.TLabel').pack(anchor='w', pady=(3, 0))
        ttk.Label(preview_header, text='ROI активна', style='OnlineBadge.TLabel').pack(side='right')
        self.preview_label = ttk.Label(frame_prev, style='Preview.TLabel', anchor='center')
        self.preview_label.pack(fill='both', expand=True)
        self.preview_label.bind('<ButtonPress-1>', self.on_preview_mouse_down)
        self.preview_label.bind('<B1-Motion>', self.on_preview_mouse_move)
        self.preview_label.bind('<ButtonRelease-1>', self.on_preview_mouse_up)
        self.preview_label.bind('<Motion>', self.on_preview_mouse_hover)

        # Signal detail rail
        aside = ttk.Frame(content, width=306, style='App.TFrame')
        aside.pack(side='right', fill='y', padx=(13, 0))
        aside.pack_propagate(False)

        frame_rgb = ttk.Frame(aside, style='Card.TFrame', padding=13)
        frame_rgb.pack(fill='x', pady=(0, 11))
        ttk.Label(frame_rgb, text='Динамика RGB', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(frame_rgb, text='Последние измерения ROI · шкала 0–300',
                  style='CardMuted.TLabel').pack(anchor='w', pady=(3, 10))
        rgb_info = ttk.Frame(frame_rgb, style='Card.TFrame')
        rgb_info.pack(fill='x', pady=(0, 9))
        self.preview_color_canvas = tk.Canvas(
            rgb_info, width=58, height=32, bg='#F8FAF9',
            highlightthickness=1, highlightbackground='#DEE7E3'
        )
        self.preview_color_canvas.pack(side='left', padx=(0, 9))
        ttk.Label(rgb_info, text='Средний цвет ROI', style='CardMuted.TLabel').pack(side='left', anchor='center')
        ttk.Label(frame_rgb, textvariable=self.preview_log_var, style='CardMuted.TLabel').pack(anchor='w', pady=(0, 7))
        self.preview_rgb_canvas = tk.Canvas(frame_rgb, height=205, highlightthickness=1)
        self.preview_rgb_canvas.pack(fill='x')
        legend = ttk.Frame(frame_rgb, style='Card.TFrame')
        legend.pack(fill='x', pady=(9, 0))
        for code, label_style in (('R', 'R.TLabel'), ('G', 'G.TLabel'), ('B', 'B.TLabel')):
            ttk.Label(legend, text=f'● {code}', style=label_style).pack(side='left', padx=(0, 12))

        frame_roi_info = ttk.Frame(aside, style='Card.TFrame', padding=13)
        frame_roi_info.pack(fill='x')
        ttk.Label(frame_roi_info, text='Геометрия ROI', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(frame_roi_info, text='Активная область подсвечивается поверх видеопотока. Координаты и размер можно менять в левой панели или перетаскиванием рамки.',
                  style='CardMuted.TLabel', wraplength=265, justify='left').pack(anchor='w', pady=(5, 0))

        # Native Tk widgets need explicit colors; applying a second time avoids
        # first-launch platform defaults flashing through the custom surface.
        try:
            self._apply_start_theme()
        except Exception:
            pass

        self.root.after(200, self.auto_connect_startup_camera)

    def auto_connect_startup_camera(self):
        """Автоматически сканирует USB-камеры при запуске и подключает первую доступную рабочую камеру с видеопотоком."""
        cfg_source = str(self.config.get('source', '')).strip()

        def _startup_worker():
            # 1. Если в конфигурации был сохранен существующий локальный видеофайл
            if cfg_source and os.path.isfile(cfg_source):
                self.root.after(0, lambda: self.open_camera_source(cfg_source, verbose=False))
                return

            # 2. Сначала всегда сканируем USB-камеры и подключаем рабочую камеру
            self.root.after(0, self.scan_usb_cameras)

        threading.Thread(target=_startup_worker, daemon=True).start()

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

        # Прямое применение параметров к активному захвату камеры (MiiCam / ToupCam)
        if getattr(self, 'cap', None) is not None and hasattr(self.cap, 'apply_settings_dict'):
            try:
                self.cap.apply_settings_dict(self.config)
            except Exception:
                pass

        self._apply_start_theme()
        self._save_current_settings()

    def trigger_camera_awb(self):
        """Выполняет аппаратную автокалибровку баланса белого (AWB) на сенсоре детектора."""
        if getattr(self, 'cap', None) is not None and hasattr(self.cap, 'trigger_awb_once'):
            ok = self.cap.trigger_awb_once()
            if ok:
                messagebox.showinfo("Баланс белого", "Аппаратный баланс белого (AWB) успешно выполнен на сенсоре!", parent=self.root)
            else:
                messagebox.showwarning("Баланс белого", "Не удалось выполнить команду AWB на сенсоре.", parent=self.root)
        else:
            messagebox.showinfo("Баланс белого", "Функция доступна при подключении RGB-детектора MiiCam.", parent=self.root)

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
                       
            current_src = str(self.config.get('source', '')).strip()
            selected_idx = -1

            # 1. First check if current source is in scanned cameras and opens
            for row_i, (idx, name) in enumerate(self.devices_combined):
                if str(idx) == current_src and "нет видеопотока" not in name:
                    if self.open_camera_source(str(idx), verbose=False):
                        selected_idx = row_i
                        break

            # 2. If not opened yet, try each working camera
            if selected_idx < 0:
                for row_i, (idx, name) in enumerate(self.devices_combined):
                    if "нет видеопотока" in name:
                        continue
                    if is_iriun_name(name) and not is_ivcam_name(name):
                        continue
                    if self.open_camera_source(str(idx), verbose=False):
                        selected_idx = row_i
                        break

            # 3. Fallback to any camera without "нет видеопотока"
            if selected_idx < 0:
                for row_i, (idx, name) in enumerate(self.devices_combined):
                    if "нет видеопотока" in name:
                        continue
                    if self.open_camera_source(str(idx), verbose=False):
                        selected_idx = row_i
                        break

            if selected_idx >= 0:
                target_src, target_name = self.devices_combined[selected_idx]
                self.entry_source.delete(0, tk.END)
                self.entry_source.insert(0, str(target_src))
                self.config['source'] = str(target_src)
                self.devices_label.config(text=f"Выбранное устройство: {target_name} ({target_src})")
                self.devices_listbox.selection_clear(0, tk.END)
                self.devices_listbox.selection_set(selected_idx)
                self.devices_listbox.activate(selected_idx)
            elif self.devices_combined:
                first_src, first_name = self.devices_combined[0]
                self.entry_source.delete(0, tk.END)
                self.entry_source.insert(0, str(first_src))
                self.config['source'] = str(first_src)
                self.devices_label.config(text=f"Выбранное устройство: {first_name} ({first_src})")
                self.devices_listbox.selection_clear(0, tk.END)
                self.devices_listbox.selection_set(0)
                self.devices_listbox.activate(0)
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
        self.preview_r_var.set(f"{mean_r:0.1f}")
        self.preview_g_var.set(f"{mean_g:0.1f}")
        self.preview_b_var.set(f"{mean_b:0.1f}")
        if np.isfinite(log_br):
            self.preview_log_var.set(f"Log10(B/R): {log_br: .4f}")
            self.preview_log_value_var.set(f"{log_br:+.4f}")
        else:
            self.preview_log_var.set("Log10(B/R): —")
            self.preview_log_value_var.set("—")
        try:
            canvas = self.preview_color_canvas
            canvas.delete('all')
            width = max(20, int(canvas.winfo_width()) - 2)
            height = max(14, int(canvas.winfo_height()) - 2)
            canvas.create_rectangle(
                1, 1, width, height,
                fill=self._rgb_hex(mean_r, mean_g, mean_b), outline=''
            )
        except Exception:
            pass
        self.draw_preview_rgb_graph()

    def draw_preview_rgb_graph(self):
        canvas = getattr(self, 'preview_rgb_canvas', None)
        if canvas is None:
            return
        try:
            colors = getattr(self, '_ui_palette', get_palette(bool(self.config.get('light_theme', True))))
            canvas.delete('all')
            w = max(200, int(canvas.winfo_width()))
            h = max(100, int(canvas.winfo_height()))
            left, right, top, bottom = 34, 9, 10, 20
            plot_w = max(10, w - left - right)
            plot_h = max(10, h - top - bottom)
            for val in (0, 100, 200, 300):
                y = top + plot_h - (val / 300.0) * plot_h
                canvas.create_line(left, y, left + plot_w, y, fill=colors['chart_grid'], width=1)
                canvas.create_text(4, y, anchor='w', text=str(val), fill=colors['muted'], font=('Segoe UI', 8))
            canvas.create_line(left, top, left, top + plot_h, fill=colors['border'])
            canvas.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill=colors['border'])
            data = list(self.preview_rgb_history)
            if len(data) < 2:
                return

            def points(channel_idx):
                pts = []
                count = len(data)
                for i, row in enumerate(data):
                    x = left + (i / max(1, count - 1)) * plot_w
                    y = top + plot_h - (max(0.0, min(300.0, row[channel_idx])) / 300.0) * plot_h
                    pts.extend((x, y))
                return pts

            for channel_idx, channel_key in enumerate(('channel_r', 'channel_g', 'channel_b')):
                canvas.create_line(*points(channel_idx), fill=colors[channel_key], width=2, smooth=True,
                                   splinesteps=8, capstyle='round', joinstyle='round')
        except Exception:
            pass

    def _compute_roi_means(self, frame, config):
        cfg = dict(config)
        if 'wb_r_mult' not in cfg and hasattr(self, 'config'):
            cfg['wb_r_mult'] = float(self.config.get('wb_r_mult', 1.0))
            cfg['wb_g_mult'] = float(self.config.get('wb_g_mult', 1.0))
            cfg['wb_b_mult'] = float(self.config.get('wb_b_mult', 1.0))
        return compute_roi_means(frame, cfg)

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

            self._set_preview_connection_state(
                raw_frame is not None and getattr(raw_frame, 'size', 0) > 0
            )
            if raw_frame is not None and raw_frame.size > 0:
                self.latest_frame = raw_frame

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

                # Fast preview downscale first for 60+ FPS high-throughput rendering
                new_width = max(10, int(width * scale))
                new_height = max(10, int(height * scale))
                preview_frame = cv2.resize(raw_frame, (new_width, new_height))

                # Periodically compute accurate ROI RGB stats
                now_preview = time.time()
                if self.preview_current_rgb is None or (now_preview - self.preview_last_rgb_update >= (self.preview_rgb_interval_ms / 1000.0)):
                    preview_config = {
                        'roi_x': max(0, int(x)), 'roi_y': max(0, int(y)),
                        'roi_w': max(self.MIN_ROI_SIZE, int(w)), 'roi_h': max(self.MIN_ROI_SIZE, int(h)),
                        'roi_shape': self.roi_shape_var.get(),
                        'wb_r_mult': float(self.config.get('wb_r_mult', 1.0)),
                        'wb_g_mult': float(self.config.get('wb_g_mult', 1.0)),
                        'wb_b_mult': float(self.config.get('wb_b_mult', 1.0)),
                    }
                    try:
                        mean_b, mean_g, mean_r, *_ = self._compute_roi_means(raw_frame, preview_config)
                        self._update_preview_rgb_signal(mean_r, mean_g, mean_b)
                        self.preview_last_rgb_update = now_preview
                    except Exception:
                        pass

                # Draw ROI directly in preview coordinate space (smooth, zero-overhead)
                sx = int(x * scale)
                sy = int(y * scale)
                sw = max(6, int(w * scale))
                sh = max(6, int(h * scale))

                # A restrained teal ROI outline remains clear on both bright and dark footage.
                roi_color = (142, 174, 108)  # BGR: muted teal-green
                handle_color = (102, 155, 194)  # BGR: soft warm highlight
                if self.roi_shape_var.get() == 'circle':
                    cx = int(sx + sw / 2)
                    cy = int(sy + sh / 2)
                    radius = int(min(sw, sh) / 2)
                    cv2.circle(preview_frame, (cx, cy), radius, roi_color, 2)
                    for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
                        rad = np.radians(angle)
                        px = int(cx + radius * np.cos(rad))
                        py = int(cy + radius * np.sin(rad))
                        cv2.rectangle(preview_frame, (px-4, py-4), (px+4, py+4), handle_color, 1)
                    cv2.rectangle(preview_frame, (cx-3, cy-3), (cx+3, cy+3), handle_color, -1)
                else:
                    cv2.rectangle(preview_frame, (sx, sy), (sx+sw, sy+sh), roi_color, 2)
                    for cx, cy in [(sx, sy), (sx+sw, sy), (sx, sy+sh), (sx+sw, sy+sh),
                                   (sx+sw//2, sy), (sx+sw//2, sy+sh), (sx, sy+sh//2), (sx+sw, sy+sh//2)]:
                        cv2.rectangle(preview_frame, (cx-4, cy-4), (cx+4, cy+4), handle_color, 1)

                info_text = f"X:{x} Y:{y} W:{w} H:{h}"
                cv2.putText(preview_frame, info_text, (10, new_height - 12),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.45, roi_color, 1, cv2.LINE_AA)

                # Compact dark HUD keeps measurements legible without a pure-black block.
                pr, pg, pb, plog = self.preview_current_rgb if self.preview_current_rgb is not None else (0.0, 0.0, 0.0, 0.0)
                fps_val = getattr(self.preview_worker, 'current_fps', 0.0) if self.preview_worker else 0.0
                if fps_val <= 0.0 and getattr(self, 'cap', None) is not None:
                    try:
                        fps_val = self.cap.get(cv2.CAP_PROP_FPS)
                    except Exception:
                        fps_val = 0.0
                fps_str = f"FPS: {fps_val:.0f}" if fps_val > 0 else "FPS: 60"
                overlay_lines = [
                    f"ROI RGB  R: {pr:4.1f}  G: {pg:4.1f}  B: {pb:4.1f} | {fps_str}",
                    f"Log10(B/R): {plog: .4f}",
                ]
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.49
                thickness = 1
                (tw1, th1), _ = cv2.getTextSize(overlay_lines[0], font, font_scale, thickness)
                (tw2, th2), _ = cv2.getTextSize(overlay_lines[1], font, font_scale, thickness)
                box_w = max(tw1, tw2) + 20
                box_h = th1 + th2 + 22
                cv2.rectangle(preview_frame, (10, 10), (10 + box_w, 10 + box_h), (38, 48, 42), -1)
                cv2.rectangle(preview_frame, (10, 10), (10 + box_w, 10 + box_h), (94, 122, 110), 1)
                cv2.putText(preview_frame, overlay_lines[0], (16, 10 + th1 + 5),
                            font, font_scale, (238, 244, 241), thickness, cv2.LINE_AA)
                cv2.putText(preview_frame, overlay_lines[1], (16, 10 + th1 + th2 + 14),
                            font, font_scale, (203, 219, 212), thickness, cv2.LINE_AA)

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
                self.root.after(16, self.update_preview)

    def _render_empty_preview_placeholder(self):
        try:
            pw = max(320, self.preview_label.winfo_width())
            ph = max(240, self.preview_label.winfo_height())
            if pw <= 1:
                pw = 800
            if ph <= 1:
                ph = 500

            colors = getattr(self, '_ui_palette', get_palette(bool(self.config.get('light_theme', True))))

            def rgb(hex_color):
                value = str(hex_color).lstrip('#')
                return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))

            img = Image.new('RGB', (pw, ph), color=rgb(colors['video_background']))
            draw = ImageDraw.Draw(img)
            font_title = _get_unicode_font(16, bold=True)
            font_body = _get_unicode_font(12, bold=False)
            font_hint = _get_unicode_font(11, bold=False)

            cx, cy = pw // 2, ph // 2
            card_w = min(max(0, pw - 40), 680)
            card_h = min(max(0, ph - 40), 255)
            x0, y0 = cx - card_w // 2, cy - card_h // 2
            x1, y1 = x0 + card_w, y0 + card_h
            draw.rounded_rectangle(
                [x0, y0, x1, y1], radius=16,
                fill=rgb(colors['surface']), outline=rgb(colors['border']), width=1
            )

            # A small, quiet signal glyph anchors the empty state without competing
            # with the live image once a camera is connected.
            draw.rounded_rectangle(
                [x0 + 22, y0 + 20, x0 + 54, y0 + 52], radius=9,
                fill=rgb(colors['accent_soft'])
            )
            draw.ellipse([x0 + 32, y0 + 30, x0 + 44, y0 + 42], fill=rgb(colors['accent']))
            draw.text((x0 + 68, y0 + 20), 'Видеопоток ожидает источник',
                      font=font_title, fill=rgb(colors['text']))
            draw.text((x0 + 68, y0 + 48), f"Текущий источник: {self.entry_source.get().strip() or 'не выбран'}",
                      font=font_hint, fill=rgb(colors['muted']))

            hints = [
                'Выберите MiiCam или USB-камеру в списке слева, затем примените источник.',
                'Для сетевой камеры откройте список IP-устройств и подключитесь по адресу RTSP.',
                'Можно открыть локальное видео — анализ начнётся в отдельном окне.',
            ]
            y = y0 + 91
            max_chars = max(38, min(78, (card_w - 56) // 8))
            for index, hint in enumerate(hints, start=1):
                draw.ellipse([x0 + 25, y + 4, x0 + 31, y + 10], fill=rgb(colors['accent']))
                wrapped = textwrap.wrap(hint, width=max_chars) or [hint]
                for line in wrapped:
                    draw.text((x0 + 43, y), line, font=font_body, fill=rgb(colors['muted']))
                    y += 22
                y += 8

            draw.text((x0 + 24, y1 - 29), 'Перетащите ROI по кадру после подключения камеры',
                      font=font_hint, fill=rgb(colors['accent']))

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
            # MiiCam/ToupCam needs a short USB/SDK quiescence interval after
            # Miicam_Stop/Miicam_Close. Reopening it synchronously here used to
            # race the SDK callback thread and could leave the whole GUI frozen
            # with ERROR_BUSY (-2147024726). Reconnect asynchronously after the
            # native handle has fully settled.
            if not source_is_file and self.config.get('source'):
                source_to_restore = self.config['source']
                self.root.after(650, lambda s=source_to_restore: self._restore_camera_after_analysis(s))
            self.root.after(0, self.update_preview)

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

    def _restore_camera_after_analysis(self, source):
        """Restore the live camera without blocking the analysis finalization path."""
        if not self.is_running:
            return
        try:
            if self.open_camera_source(source, verbose=False):
                self.update_preview()
        except Exception as exc:
            print(f"⚠️ Не удалось автоматически восстановить камеру после анализа: {exc}")

    def on_closing(self):
        self.is_running = False
        if self.cap:
            self.cap.release()
        self.root.destroy()
        exit()


                                                           
if __name__ == "__main__":
    app = SetupApp()

