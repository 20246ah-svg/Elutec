"""
Окно расширенных настроек и параметров анализа «Элютек: SARA RGB».
Включает:
- Управление профилями производительности.
- Настройку отображаемых каналов и оформление.
- Двухуровневый конструктор (1. Переменные + 2. Графики) со встроенной справкой.
- Базовые автометки и гибкие пользовательские автометки (логика «И»).
"""

import os
import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, simpledialog
import cv2
import numpy as np
from PIL import Image, ImageTk

from ..config import (
    PERFORMANCE_PROFILES,
    AROM_SLOPE_STANDARD, AROM_SLOPE_STRONG, AROM_SCORE_STANDARD, AROM_SCORE_STRONG,
    BR_SLOPE_THRESHOLD, BR_SCORE_THRESHOLD, BR_CONFIRM_MS, BR_ARM_DELAY_SEC,
    ABR_SLOPE_THRESHOLD, ABR_SCORE_THRESHOLD, ABR_CONFIRM_MS, ABR_STRONG_SLOPE_THRESHOLD,
    ABR_STRONG_SCORE_THRESHOLD, ABR_STRONG_CONFIRM_MS, ABR_ARM_DELAY_SEC,
    AROM_T_MIN_SEC, AROM_T_MAX_SEC, BR_T_MIN_SEC, BR_T_MAX_SEC, ABR_T_MIN_SEC, ABR_T_MAX_SEC,
    DEFAULT_DETECTOR_PRESETS, DEFAULT_AUTO_MARK_COOLDOWN_SEC, DEFAULT_PLAYER_HUD_METRICS
)
from ..utils.helpers import is_miicam_source
from ..data.project_store import ProjectStore
from .theme import get_palette

APP_SETTINGS_FILE = "config.json"

DEFAULT_CONFIG = {
    "performance_profile": "Сбалансированный",
    "display_max_width": 1280,
    "analysis_interval_ms": 15,
    "graph_update_ms": 40,
    "max_points": 50000,
    "preview_interval_ms": 50,
    "preview_rgb_interval_ms": 200,

    # Отображаемые каналы
    "show_r": True,
    "show_g": True,
    "show_b": True,
    "show_log": True,
    "show_slope": True,
    "show_transition": True,
    "antialias": False,

    # Конструктор переменных и графиков (Вариант 2)
    "custom_variables": [],
    "custom_graphs": [],

    # Базовые автометки (Фазы 1-3)
    "auto_marks_enabled": True,
    "sound_alerts_enabled": True,
    "notifications_enabled": True,

    # SAT -> AROM
    "auto_mark_arom_enabled": True,
    "auto_mark_arom_sound": True,
    "auto_mark_arom_slope_std": AROM_SLOPE_STANDARD,
    "auto_mark_arom_slope_strong": AROM_SLOPE_STRONG,
    "auto_mark_arom_score_std": AROM_SCORE_STANDARD,
    "auto_mark_arom_score_strong": AROM_SCORE_STRONG,
    "auto_mark_arom_t_min_sec": AROM_T_MIN_SEC,
    "auto_mark_arom_t_max_sec": AROM_T_MAX_SEC,
    "auto_mark_arom_unit": "мин",

    # AROM -> BR
    "auto_mark_br_enabled": True,
    "auto_mark_br_sound": True,
    "auto_mark_br_slope_th": BR_SLOPE_THRESHOLD,
    "auto_mark_br_score_th": BR_SCORE_THRESHOLD,
    "auto_mark_br_confirm_sec": BR_CONFIRM_MS / 1000.0,
    "auto_mark_br_arm_delay_sec": BR_ARM_DELAY_SEC,
    "auto_mark_br_t_min_sec": BR_T_MIN_SEC,
    "auto_mark_br_t_max_sec": BR_T_MAX_SEC,
    "auto_mark_br_unit": "мин",

    # BR -> ABR
    "auto_mark_abr_enabled": True,
    "auto_mark_abr_sound": True,
    "auto_mark_abr_slope_th": ABR_SLOPE_THRESHOLD,
    "auto_mark_abr_score_th": ABR_SCORE_THRESHOLD,
    "auto_mark_abr_confirm_sec": ABR_CONFIRM_MS / 1000.0,
    "auto_mark_abr_strong_slope_th": ABR_STRONG_SLOPE_THRESHOLD,
    "auto_mark_abr_strong_score_th": ABR_STRONG_SCORE_THRESHOLD,
    "auto_mark_abr_strong_confirm_sec": ABR_STRONG_CONFIRM_MS / 1000.0,
    "auto_mark_abr_arm_delay_sec": ABR_ARM_DELAY_SEC,
    "auto_mark_abr_t_min_sec": ABR_T_MIN_SEC,
    "auto_mark_abr_t_max_sec": ABR_T_MAX_SEC,
    "auto_mark_abr_unit": "мин",

    # Общая задержка повторного срабатывания автометок (Holdoff / Cooldown)
    "auto_mark_cooldown_sec": DEFAULT_AUTO_MARK_COOLDOWN_SEC,

    # Пользовательские автометки
    "custom_auto_marks": [],

    # Настройки RGB-детектора (MiiCam / ToupCam)
    "miicam_auto_exposure": False,
    "miicam_exposure_us": 22000,
    "miicam_gain": 100,
    "miicam_wb_r": 0,
    "miicam_wb_g": 0,
    "miicam_wb_b": 0,
    "wb_r_mult": 1.0,
    "wb_g_mult": 1.0,
    "wb_b_mult": 1.0,
    "miicam_temp": 6500,
    "miicam_tint": 1000,
    "miicam_gamma": 100,
    "miicam_contrast": 5,
    "miicam_brightness": 0,
    "miicam_saturation": 135,
    "miicam_hue": 0,
    "miicam_speed": 2,
    "miicam_binning": 1,
    "miicam_frame_preload": True,
    "miicam_thread_priority": 2,
    "miicam_h_flip": False,
    "miicam_v_flip": False,
    "miicam_anti_flicker": 1,
    "detector_compare_mode": "split",
    "detector_split_pos": 50,
    "detector_presets": DEFAULT_DETECTOR_PRESETS,
    "player_hud_metrics": DEFAULT_PLAYER_HUD_METRICS,

    # Видео и ROI
    "record_video": True,
    "save_roi_on_video": False,
    "snap_roi_green_circle_on_file": True,
    "live_roi": True,
    "allow_roi_resize": True,
    "auto_stop_file": True,
    "playback_speed": 1.0,
    "seek_step_sec": 5,
    "light_theme": False,
}

NOTIFICATION_DEFAULTS = DEFAULT_CONFIG


def settings_path():
    base = os.path.join(os.path.expanduser("~"), ".elutek")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, APP_SETTINGS_FILE)


def load_saved_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    path = settings_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения настроек: {e}")


class SettingsWindow:
    def __init__(self, parent, config, on_apply=None, current_cap=None, project_store=None):
        self.parent = parent
        self.config = config
        self.on_apply = on_apply
        self.current_cap = current_cap
        self.project_store = project_store or ProjectStore()
        # Preserve the old in-memory API for external callers/tests; the main
        # application always passes ProjectStore and uses the isolated libraries.
        self._legacy_preset_compat = project_store is None

        # Determine whether MiiCam (RGB detector) is physically connected and active
        self.is_miicam = (
            self.current_cap is not None 
            and hasattr(self.current_cap, "apply_settings_dict") 
            and getattr(self.current_cap, "isOpened", lambda: False)()
        )

        self.win = tk.Toplevel(parent)
        self.win.title("Параметры и настройки анализа")
        self.win.geometry("1020x760")
        self.win.minsize(920, 680)
        self.win.resizable(True, True)

        self._is_fullscreen = False
        self.win.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.win.bind("<Escape>", lambda e: self._exit_fullscreen_if_active())

        self._build()
        self._load_from_config()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _toggle_fullscreen(self, event=None):
        self._is_fullscreen = not getattr(self, '_is_fullscreen', False)
        try:
            self.win.attributes('-fullscreen', self._is_fullscreen)
        except Exception:
            try:
                if self._is_fullscreen:
                    self.win.state('zoomed')
                else:
                    self.win.state('normal')
            except Exception:
                pass

        if hasattr(self, 'btn_fullscreen'):
            self.btn_fullscreen.config(
                text="🗗 Оконный режим (Esc)" if self._is_fullscreen else "⛶ Полный экран (F11)"
            )
        return "break"

    def _exit_fullscreen_if_active(self, event=None):
        if getattr(self, '_is_fullscreen', False):
            self._toggle_fullscreen()
            return "break"

    def _on_close(self):
        if getattr(self, '_comp_timer_id', None) is not None:
            try:
                self.win.after_cancel(self._comp_timer_id)
            except Exception:
                pass
            self._comp_timer_id = None
        self.win.destroy()

    def _build(self):
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        light = bool(self.config.get("light_theme", False))
        colors = get_palette(light)
        bg = colors['background']
        panel = colors['surface']
        panel_alt = colors['surface_alt']
        fg = colors['text']
        muted = colors['muted']
        border = colors['border']
        accent = colors['accent']

        self.win.configure(bg=bg)
        style.configure('.', background=bg, foreground=fg, font=('Segoe UI', 10))
        style.configure('TFrame', background=bg)
        style.configure('App.TFrame', background=bg)
        style.configure('Header.TFrame', background=panel, relief='solid', borderwidth=1,
                        bordercolor=border, lightcolor=border, darkcolor=border)
        style.configure('BrandMark.TLabel', background=accent, foreground=colors['accent_on'],
                        font=('Segoe UI', 14, 'bold'), padding=(9, 5))
        style.configure('HeaderTitle.TLabel', background=panel, foreground=fg,
                        font=('Segoe UI', 15, 'bold'))
        style.configure('HeaderSub.TLabel', background=panel, foreground=muted,
                        font=('Segoe UI', 9))
        style.configure('TLabel', background=bg, foreground=fg)
        style.configure('TNotebook', background=bg, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure('TNotebook.Tab', background=panel_alt, foreground=muted,
                        padding=(13, 9), borderwidth=0, font=('Segoe UI', 9, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', colors['accent_soft']), ('active', colors['surface_hover'])],
                  foreground=[('selected', accent), ('active', fg)])
        style.configure('TEntry', fieldbackground=panel_alt, foreground=fg, padding=(8, 6),
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        insertcolor=fg, insertwidth=2)
        style.map('TEntry', fieldbackground=[('focus', panel)], foreground=[('focus', fg)])
        style.configure('TSpinbox', fieldbackground=panel_alt, foreground=fg,
                        background=panel_alt, arrowcolor=muted, padding=(6, 5),
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        insertcolor=fg, insertwidth=2)
        style.map('TSpinbox', fieldbackground=[('focus', panel), ('active', panel)],
                  foreground=[('focus', fg), ('active', fg)],
                  background=[('focus', panel), ('active', panel)],
                  arrowcolor=[('focus', accent), ('active', accent)])
        style.configure('TCombobox', fieldbackground=panel_alt, background=panel_alt,
                        foreground=fg, arrowcolor=muted, padding=(7, 5),
                        bordercolor=border, lightcolor=border, darkcolor=border)
        style.map('TCombobox', fieldbackground=[('readonly', panel_alt), ('focus', panel), ('active', panel)],
                  foreground=[('readonly', fg), ('focus', fg), ('active', fg)],
                  background=[('readonly', panel_alt), ('focus', panel), ('active', panel)],
                  arrowcolor=[('focus', accent), ('active', accent)])
        style.configure('TButton', background=panel, foreground=fg, padding=(10, 7),
                        borderwidth=1, bordercolor=border, font=('Segoe UI', 9, 'bold'))
        style.map('TButton', background=[('pressed', colors['surface_hover']), ('active', colors['surface_hover'])],
                  bordercolor=[('active', accent)], foreground=[('disabled', muted)])
        style.configure('Primary.TButton', background=accent, foreground=colors['accent_on'],
                        padding=(13, 9), borderwidth=0, font=('Segoe UI', 9, 'bold'))
        style.map('Primary.TButton', background=[('pressed', colors['accent_hover']), ('active', colors['accent_hover'])])
        style.configure('Quiet.TButton', background=panel, foreground=fg, padding=(10, 7),
                        borderwidth=1, bordercolor=border, font=('Segoe UI', 9, 'bold'))
        style.map('Quiet.TButton', background=[('pressed', colors['surface_hover']), ('active', colors['surface_hover'])],
                  bordercolor=[('active', accent)])
        style.configure('TCheckbutton', background=panel, foreground=fg, padding=(4, 4))
        style.map('TCheckbutton', background=[('active', panel), ('pressed', panel)],
                  foreground=[('active', fg), ('pressed', fg)])
        style.configure('TRadiobutton', background=panel, foreground=fg, padding=(5, 4))
        style.map('TRadiobutton', background=[('active', panel_alt), ('pressed', panel_alt)],
                  foreground=[('active', fg), ('pressed', fg)])
        style.configure('TLabelframe', background=panel, foreground=fg, bordercolor=border,
                        lightcolor=border, darkcolor=border, relief='solid', borderwidth=1)
        style.configure('TLabelframe.Label', background=panel, foreground=fg,
                        font=('Segoe UI', 10, 'bold'), padding=(4, 0))
        style.configure('Treeview', background=panel, fieldbackground=panel,
                        foreground=fg, bordercolor=border, rowheight=29, font=('Segoe UI', 9))
        style.map('Treeview', background=[('selected', colors['accent_soft'])],
                  foreground=[('selected', accent)])
        style.configure('Treeview.Heading', background=panel_alt, foreground=muted,
                        font=('Segoe UI', 9, 'bold'), relief='flat', padding=(8, 7))
        style.map('Treeview.Heading', background=[('active', colors['surface_hover'])],
                  foreground=[('active', fg)])
        style.configure('Vertical.TScrollbar', background=bg, troughcolor=bg,
                        bordercolor=bg, arrowcolor=muted)

        outer = ttk.Frame(self.win, padding=16, style='App.TFrame')
        outer.pack(fill='both', expand=True)

        header_frame = ttk.Frame(outer, style='Header.TFrame', padding=(16, 12))
        header_frame.pack(fill='x', pady=(0, 12))
        ttk.Label(header_frame, text='E', style='BrandMark.TLabel', anchor='center').pack(side='left')
        header_copy = ttk.Frame(header_frame, style='Header.TFrame')
        header_copy.pack(side='left', padx=(11, 0))
        ttk.Label(header_copy, text='Настройки анализа', style='HeaderTitle.TLabel').pack(anchor='w')
        ttk.Label(header_copy, text='Видео · графики · ROI · автометки · производительность',
                  style='HeaderSub.TLabel').pack(anchor='w', pady=(2, 0))

        nb = ttk.Notebook(outer)
        nb.pack(fill='both', expand=True)
        self.nb = nb

        tab_video = ttk.Frame(nb, padding=14)
        tab_graphs = ttk.Frame(nb, padding=14)
        tab_roi = ttk.Frame(nb, padding=14)
        tab_notif = ttk.Frame(nb, padding=14)
        if self.is_miicam:
            tab_detector = ttk.Frame(nb, padding=14)
        tab_perf = ttk.Frame(nb, padding=14)

        nb.add(tab_video, text='Видео и запись')
        nb.add(tab_graphs, text='Графики и формулы')
        nb.add(tab_roi, text='Область ROI')
        nb.add(tab_notif, text='Автометки')
        if self.is_miicam:
            nb.add(tab_detector, text='RGB-детектор')
        nb.add(tab_perf, text='Производительность')

        # =========================================================================
        # 1. TAB: ВИДЕО И ЗАПИСЬ
        # =========================================================================
        lf_playback = ttk.LabelFrame(tab_video, text=" Воспроизведение видеофайлов ", padding=10)
        lf_playback.pack(fill="x", pady=(0, 10))

        row_pb = ttk.Frame(lf_playback)
        row_pb.pack(fill="x", pady=4)
        ttk.Label(row_pb, text="Скорость по умолчанию:").pack(side="left", padx=(0, 8))
        self.playback_speed_var = tk.StringVar(value="1.0x")
        ttk.Combobox(
            row_pb, textvariable=self.playback_speed_var,
            values=["0.25x", "0.5x", "1.0x", "1.5x", "2.0x", "4.0x", "8.0x"],
            state="readonly", width=10
        ).pack(side="left")

        ttk.Label(row_pb, text="Шаг перемотки [← / →]:").pack(side="left", padx=(20, 8))
        self.seek_step_var = tk.StringVar(value="5 сек")
        ttk.Combobox(
            row_pb, textvariable=self.seek_step_var,
            values=["1 сек", "5 сек", "10 сек", "30 сек"],
            state="readonly", width=10
        ).pack(side="left")

        self.video_vars = {}
        self.video_vars["auto_stop_file"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            lf_playback, text="Автоматически завершать анализ при достижении конца видеофайла",
            variable=self.video_vars["auto_stop_file"]
        ).pack(anchor="w", pady=4)

        lf_rec = ttk.LabelFrame(tab_video, text=" Запись видеопотока с камеры ", padding=10)
        lf_rec.pack(fill="x", pady=(0, 10))

        self.video_vars["record_video"] = tk.BooleanVar(value=True)
        self.video_vars["save_roi_on_video"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            lf_rec, text="Записывать видеопоток анализа сессии в файл MKV",
            variable=self.video_vars["record_video"]
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            lf_rec, text="Впечатывать рамку области ROI в записываемый видеофайл",
            variable=self.video_vars["save_roi_on_video"]
        ).pack(anchor="w", pady=4)

        lf_win = ttk.LabelFrame(tab_video, text=" Окно видео ", padding=10)
        lf_win.pack(fill="x", pady=(0, 5))
        row_win = ttk.Frame(lf_win)
        row_win.pack(fill="x", pady=4)
        ttk.Label(row_win, text="Максимальная ширина окна видео:").pack(side="left", padx=(0, 8))
        self.display_max_width_var = tk.IntVar(value=1280)
        ttk.Spinbox(row_win, from_=640, to=3840, increment=80, textvariable=self.display_max_width_var, width=10).pack(side="left")
        ttk.Label(row_win, text="px (1280 - HD, 1920 - Full HD)", foreground="#888888").pack(side="left", padx=8)

        # =========================================================================
        # 2. TAB: ГРАФИКИ И ВИД (Двухуровневый конструктор: Вариант 2 + Справка)
        # =========================================================================
        lf_curves = ttk.LabelFrame(tab_graphs, text=" Отображаемые каналы данных ", padding=8)
        lf_curves.pack(fill="x", pady=(0, 8))

        self.graph_vars = {}
        graph_options = [
            ("show_r", "Показывать Red (R)"),
            ("show_g", "Показывать Green (G)"),
            ("show_b", "Показывать Blue (B)"),
            ("show_log", "Показывать Log10(B/R), Log10(B/G)"),
            ("show_slope", "Показывать скорость изменения RGB_sum_slope_30s"),
            ("show_transition", "Показывать индекс перехода (Transition score)"),
        ]
        g_grid = ttk.Frame(lf_curves)
        g_grid.pack(fill="x")
        for i, (key, label) in enumerate(graph_options):
            var = tk.BooleanVar(value=True)
            self.graph_vars[key] = var
            r = i // 2
            c = i % 2
            ttk.Checkbutton(g_grid, text=label, variable=var, command=self._ensure_one_graph_setting).grid(row=r, column=c, sticky="w", padx=10, pady=2)

        # Top bar with Help button
        custom_hdr_frame = ttk.Frame(tab_graphs)
        custom_hdr_frame.pack(fill="x", pady=(4, 6))
        ttk.Label(custom_hdr_frame, text="🧮 Конструктор пользовательских формул и графиков", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(custom_hdr_frame, text="❓ Подробная инструкция и примеры", command=self._open_formulas_help_dialog).pack(side="right")

        # Block 1: Custom Variables
        lf_vars = ttk.LabelFrame(tab_graphs, text=" 1. Мои пользовательские переменные (Промежуточные вычисления) ", padding=8)
        lf_vars.pack(fill="x", pady=(0, 8))

        var_top = ttk.Frame(lf_vars)
        var_top.pack(fill="x", pady=(0, 4))
        self.var_name_input = tk.StringVar(value="NORM_B")
        self.var_formula_input = tk.StringVar(value="b / (r + g + b + 1e-5)")

        ttk.Label(var_top, text="Имя переменной:").pack(side="left", padx=(0, 4))
        ttk.Entry(var_top, textvariable=self.var_name_input, width=14).pack(side="left", padx=(0, 8))
        ttk.Label(var_top, text="Формула:").pack(side="left", padx=(0, 4))
        ttk.Entry(var_top, textvariable=self.var_formula_input, width=32).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(var_top, text="➕ Добавить", command=self._add_custom_variable).pack(side="left", padx=2)
        ttk.Button(var_top, text="🗑️ Удалить", command=self._remove_custom_variable).pack(side="left", padx=2)

        var_list_frame = ttk.Frame(lf_vars)
        var_list_frame.pack(fill="x")
        self.custom_var_list = tk.Listbox(var_list_frame, height=3, bg=panel, fg=fg,
                                          selectbackground=colors['accent_soft'], selectforeground=accent,
                                          relief='flat', highlightthickness=1, highlightbackground=border,
                                          font=('Segoe UI', 9), activestyle='none')
        self.custom_var_list.pack(fill="x", expand=True)

        # Block 2: Custom Graphs
        lf_custom = ttk.LabelFrame(tab_graphs, text=" 2. Пользовательские графики (Отображаются в окне анализа) ", padding=8)
        lf_custom.pack(fill="both", expand=True)

        cg_top = ttk.Frame(lf_custom)
        cg_top.pack(fill="x", pady=(0, 4))
        self.custom_name_var = tk.StringVar(value="Доля синего (%)")
        self.custom_formula_var = tk.StringVar(value="NORM_B * 100")
        self.custom_color_var = tk.StringVar(value=colors["success"])

        ttk.Label(cg_top, text="Название:").pack(side="left", padx=(0, 4))
        ttk.Entry(cg_top, textvariable=self.custom_name_var, width=16).pack(side="left", padx=(0, 8))
        ttk.Label(cg_top, text="Формула:").pack(side="left", padx=(0, 4))
        ttk.Entry(cg_top, textvariable=self.custom_formula_var, width=28).pack(side="left", fill="x", expand=True, padx=(0, 6))

        color_prev = tk.Canvas(cg_top, width=20, height=20, bg=self.custom_color_var.get(), highlightthickness=1)
        color_prev.pack(side="left", padx=(0, 4))

        def _pick_graph_color():
            res = colorchooser.askcolor(self.custom_color_var.get(), parent=self.win)
            if res and res[1]:
                self.custom_color_var.set(res[1])
                color_prev.configure(bg=res[1])

        ttk.Button(cg_top, text="🎨 Цвет", command=_pick_graph_color, width=7).pack(side="left", padx=(0, 4))
        ttk.Button(cg_top, text="➕ Добавить", command=self._add_custom_graph).pack(side="left", padx=2)
        ttk.Button(cg_top, text="🗑️ Удалить", command=self._remove_custom_graph).pack(side="left", padx=2)

        cg_list_frame = ttk.Frame(lf_custom)
        cg_list_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.custom_graph_list = tk.Listbox(cg_list_frame, height=3, bg=panel, fg=fg,
                                            selectbackground=colors['accent_soft'], selectforeground=accent,
                                            relief='flat', highlightthickness=1, highlightbackground=border,
                                            font=('Segoe UI', 9), activestyle='none')
        self.custom_graph_list.pack(fill="both", expand=True)

        # =========================================================================
        # 3. TAB: ОБЛАСТЬ ROI
        # =========================================================================
        self.roi_vars = {}
        lf_roi_beh = ttk.LabelFrame(tab_roi, text=" Поведение и интерактивность ROI ", padding=10)
        lf_roi_beh.pack(fill="x", pady=(0, 10))

        self.roi_vars["live_roi"] = tk.BooleanVar(value=True)
        self.roi_vars["allow_roi_resize"] = tk.BooleanVar(value=True)
        self.roi_vars["snap_roi_green_circle_on_file"] = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            lf_roi_beh, text="Включить интерактивное перемещение и масштабирование рамки ROI в окне видео",
            variable=self.roi_vars["live_roi"]
        ).pack(anchor="w", pady=4)

        ttk.Checkbutton(
            lf_roi_beh, text="Разрешить пропорциональное изменение размера (ручки по углам рамки)",
            variable=self.roi_vars["allow_roi_resize"]
        ).pack(anchor="w", pady=4)

        ttk.Checkbutton(
            lf_roi_beh, text="Автоматически привязывать ROI к зелёному кругу при открытии видеофайла",
            variable=self.roi_vars["snap_roi_green_circle_on_file"]
        ).pack(anchor="w", pady=4)

        # =========================================================================
        # 4. TAB: АВТОМЕТКИ
        # =========================================================================
        notif_canvas = tk.Canvas(tab_notif, highlightthickness=0, bg=bg)
        notif_scrollbar = ttk.Scrollbar(tab_notif, orient="vertical", command=notif_canvas.yview)
        notif_canvas.configure(yscrollcommand=notif_scrollbar.set)
        notif_scrollbar.pack(side="right", fill="y")
        notif_canvas.pack(side="left", fill="both", expand=True)

        notif_inner = ttk.Frame(notif_canvas)
        notif_win_id = notif_canvas.create_window((0, 0), window=notif_inner, anchor="nw")

        def _update_notif_scroll(event=None):
            notif_canvas.configure(scrollregion=notif_canvas.bbox("all"))

        def _fit_notif_width(event):
            notif_canvas.itemconfigure(notif_win_id, width=event.width)

        notif_inner.bind("<Configure>", _update_notif_scroll)
        notif_canvas.bind("<Configure>", _fit_notif_width)
        self._notif_canvas = notif_canvas

        top_ctrl = ttk.Frame(notif_inner)
        top_ctrl.pack(fill="x", pady=(0, 6))

        self.notification_vars = {}
        self.notification_vars["auto_marks_enabled"] = tk.BooleanVar(value=True)
        self.notification_vars["sound_alerts_enabled"] = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            top_ctrl, text="🔔 Включить общую автодетекцию меток",
            variable=self.notification_vars["auto_marks_enabled"]
        ).pack(side="left", padx=(0, 20))

        ttk.Checkbutton(
            top_ctrl, text="🔊 Системные звуковые сигналы (Alert Beep)",
            variable=self.notification_vars["sound_alerts_enabled"]
        ).pack(side="left")

        # -------------------------------------------------------------------------
        # БЛОК 1: БАЗОВЫЕ АВТОМЕТКИ (ФАЗЫ 1-3)
        # -------------------------------------------------------------------------
        lf_base = ttk.LabelFrame(notif_inner, text=" 🧭 Базовые автометки фазовых переходов (SARA) ", padding=8)
        lf_base.pack(fill="x", pady=4)

        # SAT -> AROM
        lf_arom = ttk.LabelFrame(lf_base, text=" Фаза 1: SAT ➔ AROM ", padding=6)
        lf_arom.pack(fill="x", pady=3)
        row_ar = ttk.Frame(lf_arom)
        row_ar.pack(fill="x")
        self.notification_vars["auto_mark_arom_enabled"] = tk.BooleanVar(value=True)
        self.notification_vars["auto_mark_arom_sound"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_ar, text="Отслеживать", variable=self.notification_vars["auto_mark_arom_enabled"]).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row_ar, text="🔊 Звук", variable=self.notification_vars["auto_mark_arom_sound"]).pack(side="left", padx=(0, 12))
        ttk.Label(row_ar, text="Окно времени: от").pack(side="left", padx=(0, 4))
        self.arom_t_min_var = tk.DoubleVar(value=0.0)
        ttk.Spinbox(row_ar, from_=0, to=1000, increment=0.5, textvariable=self.arom_t_min_var, width=5).pack(side="left")
        ttk.Label(row_ar, text="до").pack(side="left", padx=4)
        self.arom_t_max_var = tk.DoubleVar(value=10.0)
        ttk.Spinbox(row_ar, from_=0, to=1000, increment=0.5, textvariable=self.arom_t_max_var, width=5).pack(side="left")
        self.arom_unit_var = tk.StringVar(value="мин")
        self.arom_unit_combo = ttk.Combobox(row_ar, textvariable=self.arom_unit_var, values=["мин", "сек"], width=5, state="readonly")
        self.arom_unit_combo.pack(side="left", padx=6)
        self._bind_unit_switch(self.arom_t_min_var, self.arom_t_max_var, self.arom_unit_var, self.arom_unit_combo)

        # AROM -> BR
        lf_br = ttk.LabelFrame(lf_base, text=" Фаза 2: AROM ➔ BR ", padding=6)
        lf_br.pack(fill="x", pady=3)
        row_b = ttk.Frame(lf_br)
        row_b.pack(fill="x")
        self.notification_vars["auto_mark_br_enabled"] = tk.BooleanVar(value=True)
        self.notification_vars["auto_mark_br_sound"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_b, text="Отслеживать", variable=self.notification_vars["auto_mark_br_enabled"]).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row_b, text="🔊 Звук", variable=self.notification_vars["auto_mark_br_sound"]).pack(side="left", padx=(0, 12))
        ttk.Label(row_b, text="Задержка:").pack(side="left", padx=(0, 4))
        self.br_delay_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(row_b, from_=0, to=1000, increment=0.5, textvariable=self.br_delay_var, width=5).pack(side="left")
        ttk.Label(row_b, text="макс. время:").pack(side="left", padx=(6, 4))
        self.br_t_max_var = tk.DoubleVar(value=30.0)
        ttk.Spinbox(row_b, from_=0, to=1000, increment=0.5, textvariable=self.br_t_max_var, width=5).pack(side="left")
        self.br_unit_var = tk.StringVar(value="мин")
        self.br_unit_combo = ttk.Combobox(row_b, textvariable=self.br_unit_var, values=["мин", "сек"], width=5, state="readonly")
        self.br_unit_combo.pack(side="left", padx=6)
        self._bind_unit_switch(self.br_delay_var, self.br_t_max_var, self.br_unit_var, self.br_unit_combo)

        # BR -> ABR
        lf_abr = ttk.LabelFrame(lf_base, text=" Фаза 3: BR ➔ ABR ", padding=6)
        lf_abr.pack(fill="x", pady=3)
        row_ab = ttk.Frame(lf_abr)
        row_ab.pack(fill="x")
        self.notification_vars["auto_mark_abr_enabled"] = tk.BooleanVar(value=True)
        self.notification_vars["auto_mark_abr_sound"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_ab, text="Отслеживать", variable=self.notification_vars["auto_mark_abr_enabled"]).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row_ab, text="🔊 Звук", variable=self.notification_vars["auto_mark_abr_sound"]).pack(side="left", padx=(0, 12))
        ttk.Label(row_ab, text="Задержка:").pack(side="left", padx=(0, 4))
        self.abr_delay_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(row_ab, from_=0, to=1000, increment=0.5, textvariable=self.abr_delay_var, width=5).pack(side="left")
        ttk.Label(row_ab, text="макс. время:").pack(side="left", padx=(6, 4))
        self.abr_t_max_var = tk.DoubleVar(value=60.0)
        ttk.Spinbox(row_ab, from_=0, to=1000, increment=0.5, textvariable=self.abr_t_max_var, width=5).pack(side="left")
        self.abr_unit_var = tk.StringVar(value="мин")
        self.abr_unit_combo = ttk.Combobox(row_ab, textvariable=self.abr_unit_var, values=["мин", "сек"], width=5, state="readonly")
        self.abr_unit_combo.pack(side="left", padx=6)
        self._bind_unit_switch(self.abr_delay_var, self.abr_t_max_var, self.abr_unit_var, self.abr_unit_combo)

        # Общая задержка повторного срабатывания автометок (Holdoff / Cooldown)
        row_holdoff = ttk.Frame(lf_base)
        row_holdoff.pack(fill="x", pady=(4, 2))
        ttk.Label(row_holdoff, text="⏳ Задержка повторного срабатывания (Кукдаун / Защита от дублей):", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.notification_vars["auto_mark_cooldown_sec"] = tk.DoubleVar(value=float(self.config.get("auto_mark_cooldown_sec", 30.0)))
        ttk.Spinbox(row_holdoff, from_=1.0, to=3600.0, increment=5.0, textvariable=self.notification_vars["auto_mark_cooldown_sec"], width=6).pack(side="left", padx=(0, 4))
        ttk.Label(row_holdoff, text="сек (метки не будут дублироваться на одном участке)").pack(side="left")

        ttk.Label(
            lf_base,
            text="💡 Подсказка: Значение 0 в поле «до» / «макс. время» означает без ограничения (до конца анализа).",
            font=("Segoe UI", 8, "italic"),
        ).pack(anchor="w", padx=4, pady=(4, 2))

        # -------------------------------------------------------------------------
        # БЛОК 2: ПОЛЬЗОВАТЕЛЬСКИЕ АВТОМЕТКИ
        # -------------------------------------------------------------------------
        lf_custom_marks = ttk.LabelFrame(notif_inner, text=" ⚙️ Пользовательские автометки (Правила и условия) ", padding=8)
        lf_custom_marks.pack(fill="both", expand=True, pady=4)

        table_frame = ttk.Frame(lf_custom_marks)
        table_frame.pack(fill="both", expand=True)

        cols = ("col_status", "col_name", "col_condition", "col_window", "col_color", "col_sound")
        self.custom_marks_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=5, selectmode="browse")
        self.custom_marks_tree.heading("col_status", text="Статус")
        self.custom_marks_tree.heading("col_name", text="Название")
        self.custom_marks_tree.heading("col_condition", text="Условие / Порог")
        self.custom_marks_tree.heading("col_window", text="Окно времени")
        self.custom_marks_tree.heading("col_color", text="Цвет")
        self.custom_marks_tree.heading("col_sound", text="Звук")

        self.custom_marks_tree.column("col_status", width=70, anchor="center")
        self.custom_marks_tree.column("col_name", width=160, anchor="w")
        self.custom_marks_tree.column("col_condition", width=220, anchor="w")
        self.custom_marks_tree.column("col_window", width=120, anchor="center")
        self.custom_marks_tree.column("col_color", width=80, anchor="center")
        self.custom_marks_tree.column("col_sound", width=70, anchor="center")

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.custom_marks_tree.yview)
        self.custom_marks_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.custom_marks_tree.pack(side="left", fill="both", expand=True)
        self.custom_marks_tree.bind("<Double-1>", lambda e: self._edit_custom_auto_mark())

        cm_btn_bar = ttk.Frame(lf_custom_marks)
        cm_btn_bar.pack(fill="x", pady=(6, 0))
        ttk.Button(cm_btn_bar, text="➕ Добавить автометку", command=self._add_custom_auto_mark).pack(side="left", padx=2)
        ttk.Button(cm_btn_bar, text="✏️ Редактировать", command=self._edit_custom_auto_mark).pack(side="left", padx=2)
        ttk.Button(cm_btn_bar, text="🔁 Вкл / Выкл", command=self._toggle_custom_auto_mark).pack(side="left", padx=2)
        ttk.Button(cm_btn_bar, text="🗑️ Удалить", command=self._delete_custom_auto_mark).pack(side="left", padx=2)

        # =========================================================================
        # 5. TAB: RGB-ДЕТЕКТОР (MIICAM / TOUPCAM SENSOR)
        # =========================================================================
        self.detector_vars = {}
        if self.is_miicam:
            self._build_detector_tab(tab_detector, light)

        # =========================================================================
        # 6. TAB: ПРОИЗВОДИТЕЛЬНОСТЬ
        # =========================================================================
        lf_prof = ttk.LabelFrame(tab_perf, text=" Готовые пресеты нагрузки ", padding=10)
        lf_prof.pack(fill="x", pady=(0, 10))

        row_p = ttk.Frame(lf_prof)
        row_p.pack(fill="x", pady=4)
        ttk.Label(row_p, text="Профиль производительности:").pack(side="left", padx=(0, 8))
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(
            row_p, textvariable=self.profile_var,
            values=list(PERFORMANCE_PROFILES.keys()),
            state="readonly", width=22
        )
        self.profile_combo.pack(side="left")
        self.profile_combo.bind("<<ComboboxSelected>>", self._profile_selected)

        lf_fine = ttk.LabelFrame(tab_perf, text=" Тонкие интервалы и буферы памяти ", padding=10)
        lf_fine.pack(fill="x", pady=(0, 10))

        self.perf_vars = {}
        fields = [
            ("analysis_interval_ms", "Интервал обработки кадра, мс", 1, 1000),
            ("graph_update_ms", "Частота обновления графиков, мс", 20, 5000),
            ("max_points", "Максимум точек истории графиков", 1000, 500000),
            ("preview_interval_ms", "Обновление превью камеры, мс", 20, 1000),
            ("preview_rgb_interval_ms", "Расчёт RGB превью, мс", 50, 3000),
        ]
        f_grid = ttk.Frame(lf_fine)
        f_grid.pack(fill="x")
        for row, (key, label, lo, hi) in enumerate(fields):
            ttk.Label(f_grid, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.IntVar(value=100)
            self.perf_vars[key] = var
            ttk.Spinbox(f_grid, from_=lo, to=hi, textvariable=var, width=12).grid(row=row, column=1, sticky="w", padx=12, pady=4)

        # Bottom buttons
        btn_bar = ttk.Frame(outer)
        btn_bar.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_bar, text="Сбросить по умолчанию", command=self._reset, style='Quiet.TButton').pack(side="left")
        ttk.Button(btn_bar, text="Отмена", command=self.win.destroy, style='Quiet.TButton').pack(side="right", padx=(6, 0))
        ttk.Button(btn_bar, text="Сохранить и применить", command=self._apply, style='Primary.TButton').pack(side="right")

    def _build_detector_tab(self, tab_detector, light):
        self.detector_vars = {}
        self._detector_apply_after_id = None

        # 0. Presets & Profiles Management Bar
        lf_presets = ttk.LabelFrame(tab_detector, text=" 💼 Именованные профили и пресеты настроек сенсора ", padding=8)
        lf_presets.pack(fill="x", pady=(0, 6))

        p_row = ttk.Frame(lf_presets)
        p_row.pack(fill="x", pady=2)

        ttk.Label(p_row, text="Пресет сенсора:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))

        self.preset_var = tk.StringVar(value="")
        self.cb_detector_presets = ttk.Combobox(
            p_row, textvariable=self.preset_var, values=(), state="readonly", width=31
        )
        self.cb_detector_presets.pack(side="left", padx=(0, 6))

        self.preset_scope_var = tk.StringVar(value="project" if self.project_store.root else "user")
        scope_options = [("Мои пресеты", "user")]
        if self.project_store.root:
            scope_options.insert(0, ("Проект", "project"))
        self._preset_scope_labels = {label: scope for label, scope in scope_options}
        self._preset_scope_values = {scope: label for label, scope in scope_options}
        self.preset_scope_label_var = tk.StringVar(value=self._preset_scope_values[self.preset_scope_var.get()])
        ttk.Combobox(
            p_row, textvariable=self.preset_scope_label_var,
            values=[label for label, _ in scope_options], state="readonly", width=13
        ).pack(side="left", padx=(0, 5))
        self.preset_scope_label_var.trace_add("write", self._on_preset_scope_changed)

        ttk.Button(p_row, text="⚡ Применить", command=self._apply_detector_preset).pack(side="left", padx=2)
        ttk.Button(p_row, text="💾 Сохранить копию…", command=self._save_detector_preset).pack(side="left", padx=2)
        ttk.Button(p_row, text="По умолчанию", command=self._set_detector_preset_default).pack(side="left", padx=2)
        ttk.Button(p_row, text="🗑️", command=self._delete_detector_preset, width=3).pack(side="left", padx=2)
        active_preset_id = self.config.get("active_detector_preset_id")
        has_active_preset = bool(active_preset_id and self.project_store.get_preset(active_preset_id, "detector"))
        preferred_preset_id = active_preset_id if has_active_preset else self.project_store.get_default_preset_id("detector")
        self._applied_detector_preset_id = active_preset_id if has_active_preset else None
        self._pending_default_preset_id = None
        self._refresh_detector_presets(preferred_preset_id)

        # 2. Sub-Notebook for MiiCam (Color, Expo, WB, Control, Flip)
        nb_det = ttk.Notebook(tab_detector)
        nb_det.pack(fill="both", expand=True, pady=(0, 6))

        tab_sub_color = ttk.Frame(nb_det, padding=12)
        tab_sub_expo = ttk.Frame(nb_det, padding=12)
        tab_sub_wb = ttk.Frame(nb_det, padding=12)
        tab_sub_ctrl = ttk.Frame(nb_det, padding=12)
        tab_sub_flip = ttk.Frame(nb_det, padding=12)

        nb_det.add(tab_sub_color, text="🎨 Цвет (Color)")
        nb_det.add(tab_sub_expo, text="⏱️ Экспозиция (Expo)")
        nb_det.add(tab_sub_wb, text="⚖️ Баланс белого (WB)")
        nb_det.add(tab_sub_ctrl, text="⚡ Управление (Control)")
        nb_det.add(tab_sub_flip, text="🔄 Отражение (Flip)")

        # --- SUB-TAB: COLOR ---
        self.detector_vars["miicam_brightness"] = tk.IntVar(value=int(self.config.get("miicam_brightness", 0)))
        self.detector_vars["miicam_contrast"] = tk.IntVar(value=int(self.config.get("miicam_contrast", 0)))
        self.detector_vars["miicam_gamma"] = tk.IntVar(value=int(self.config.get("miicam_gamma", 100)))
        self.detector_vars["miicam_hue"] = tk.IntVar(value=int(self.config.get("miicam_hue", 0)))
        self.detector_vars["miicam_saturation"] = tk.IntVar(value=int(self.config.get("miicam_saturation", 128)))

        def _add_slider_row(parent, label_text, var, from_val, to_val, def_val):
            r = ttk.Frame(parent)
            r.pack(fill="x", pady=3)
            ttk.Label(r, text=label_text, width=25, anchor="w").pack(side="left")

            def _on_scale_move(val):
                try:
                    iv = int(round(float(val)))
                    if var.get() != iv:
                        var.set(iv)
                        self._on_detector_param_changed()
                except Exception:
                    pass

            s = ttk.Scale(r, from_=from_val, to=to_val, orient="horizontal", command=_on_scale_move)
            try:
                s.set(int(var.get()))
            except Exception:
                s.set(def_val)
            s.pack(side="left", fill="x", expand=True, padx=(4, 10))

            def _on_sp_change(event=None):
                try:
                    iv = int(round(float(var.get())))
                    var.set(iv)
                    s.set(iv)
                    self._on_detector_param_changed()
                except Exception:
                    pass

            sp = ttk.Spinbox(r, from_=from_val, to=to_val, textvariable=var, width=7, command=_on_sp_change)
            sp.pack(side="left")
            sp.bind("<KeyRelease>", _on_sp_change)
            var.scale_widget = s
            return s, sp

        _add_slider_row(tab_sub_color, "Яркость (Brightness):", self.detector_vars["miicam_brightness"], -64, 64, 0)
        _add_slider_row(tab_sub_color, "Контраст (Contrast):", self.detector_vars["miicam_contrast"], -100, 100, 0)
        _add_slider_row(tab_sub_color, "Гамма (Gamma):", self.detector_vars["miicam_gamma"], 20, 180, 100)
        _add_slider_row(tab_sub_color, "Оттенок (Hue):", self.detector_vars["miicam_hue"], -180, 180, 0)
        _add_slider_row(tab_sub_color, "Насыщенность (Saturation):", self.detector_vars["miicam_saturation"], 0, 255, 128)

        row_color_actions = ttk.Frame(tab_sub_color)
        row_color_actions.pack(fill="x", pady=(8, 2))
        ttk.Button(row_color_actions, text="↺ Нейтральный цвет", command=lambda: self._set_color_profile(128, 0, 0, 100)).pack(side="left", padx=(0, 6))
        ttk.Button(row_color_actions, text="⚡ Применить сейчас", command=self._apply_to_sensor_now).pack(side="left", padx=6)

        # --- SUB-TAB: EXPO ---
        self.detector_vars["miicam_auto_exposure"] = tk.BooleanVar(value=bool(self.config.get("miicam_auto_exposure", False)))
        self.detector_vars["miicam_exposure_us"] = tk.IntVar(value=int(self.config.get("miicam_exposure_us", 20000)))
        self.detector_vars["miicam_gain"] = tk.IntVar(value=int(self.config.get("miicam_gain", 100)))

        # One-Touch Auto Exposure button (recommended for stable SARA analysis)
        row_auto_e = ttk.Frame(tab_sub_expo)
        row_auto_e.pack(fill="x", pady=(0, 6))
        ttk.Button(row_auto_e, text="⚡ Автонастройка и фиксация яркости (Рекомендуется)", command=self._trigger_auto_calibrate_exposure).pack(side="left")

        cb_ae = ttk.Checkbutton(
            tab_sub_expo,
            text=" Непрерывная автоэкспозиция (Continuous Auto Exposure)",
            variable=self.detector_vars["miicam_auto_exposure"],
            command=self._on_detector_param_changed
        )
        cb_ae.pack(anchor="w", pady=(2, 6))

        row_e = ttk.Frame(tab_sub_expo)
        row_e.pack(fill="x", pady=4)
        ttk.Label(row_e, text="Время выдержки (Exposure):", width=25, anchor="w").pack(side="left")
        self.lbl_exp_ms = ttk.Label(row_e, text=f"{self.detector_vars['miicam_exposure_us'].get() / 1000.0:.1f} мс", width=11)

        def _on_exp_scale(val):
            try:
                v = int(round(float(val)))
                if self.detector_vars["miicam_exposure_us"].get() != v:
                    self.detector_vars["miicam_exposure_us"].set(v)
                    self.lbl_exp_ms.config(text=f"{v / 1000.0:.1f} мс")
                    self._on_detector_param_changed()
            except Exception:
                pass

        self.s_exp = ttk.Scale(row_e, from_=100, to=1000000, orient="horizontal", command=_on_exp_scale)
        self.s_exp.set(int(self.detector_vars["miicam_exposure_us"].get()))
        self.s_exp.pack(side="left", fill="x", expand=True, padx=(4, 10))

        def _on_exp_sp(event=None):
            try:
                v = int(round(float(self.detector_vars["miicam_exposure_us"].get())))
                self.detector_vars["miicam_exposure_us"].set(v)
                self.s_exp.set(v)
                self.lbl_exp_ms.config(text=f"{v / 1000.0:.1f} мс")
                self._on_detector_param_changed()
            except Exception:
                pass

        sp_e = ttk.Spinbox(row_e, from_=100, to=5000000, increment=1000, textvariable=self.detector_vars["miicam_exposure_us"], width=8, command=_on_exp_sp)
        sp_e.pack(side="left", padx=(0, 4))
        sp_e.bind("<KeyRelease>", _on_exp_sp)
        ttk.Label(row_e, text="мкс").pack(side="left", padx=(0, 4))
        self.lbl_exp_ms.pack(side="left")

        _add_slider_row(tab_sub_expo, "Аналоговое усиление (Gain %):", self.detector_vars["miicam_gain"], 100, 1000, 100)

        # Quick FPS presets row
        row_fps_p = ttk.Frame(tab_sub_expo)
        row_fps_p.pack(fill="x", pady=(6, 0))
        ttk.Label(row_fps_p, text="⚡ Быстрые выдержки под FPS:").pack(side="left", padx=(0, 6))
        ttk.Button(row_fps_p, text="⚡ 120 FPS (8 мс)", command=lambda: self._set_exposure_preset(8000)).pack(side="left", padx=2)
        ttk.Button(row_fps_p, text="⚡ 60 FPS (16 мс)", command=lambda: self._set_exposure_preset(16000)).pack(side="left", padx=2)
        ttk.Button(row_fps_p, text="⚡ 30 FPS (33 мс)", command=lambda: self._set_exposure_preset(33000)).pack(side="left", padx=2)

        # --- SUB-TAB: WB ---
        row_wb_btn = ttk.Frame(tab_sub_wb)
        row_wb_btn.pack(fill="x", pady=(0, 8))
        ttk.Button(row_wb_btn, text="⚖️ Баланс белого (AWB)", command=self._trigger_detector_awb).pack(side="left", padx=(0, 8))

        self.detector_vars["miicam_temp"] = tk.IntVar(value=int(self.config.get("miicam_temp", 6500)))
        self.detector_vars["miicam_tint"] = tk.IntVar(value=int(self.config.get("miicam_tint", 1000)))
        self.detector_vars["miicam_wb_r"] = tk.IntVar(value=int(self.config.get("miicam_wb_r", 0)))
        self.detector_vars["miicam_wb_g"] = tk.IntVar(value=int(self.config.get("miicam_wb_g", 0)))
        self.detector_vars["miicam_wb_b"] = tk.IntVar(value=int(self.config.get("miicam_wb_b", 0)))

        _add_slider_row(tab_sub_wb, "Цветовая темп. (Temp K):", self.detector_vars["miicam_temp"], 2000, 15000, 6500)
        _add_slider_row(tab_sub_wb, "Оттенок темп. (Tint):", self.detector_vars["miicam_tint"], 200, 2500, 1000)

        lf_gains = ttk.LabelFrame(tab_sub_wb, text=" Ручная подстройка каналов (RGB Gain) ", padding=6)
        lf_gains.pack(fill="x", pady=4)
        _add_slider_row(lf_gains, "Красный (R-Gain):", self.detector_vars["miicam_wb_r"], -128, 128, 0)
        _add_slider_row(lf_gains, "Зелёный (G-Gain):", self.detector_vars["miicam_wb_g"], -128, 128, 0)
        _add_slider_row(lf_gains, "Синий (B-Gain):", self.detector_vars["miicam_wb_b"], -128, 128, 0)

        # --- SUB-TAB: CONTROL ---
        self.detector_vars["miicam_speed"] = tk.IntVar(value=int(self.config.get("miicam_speed", 2)))
        self.detector_vars["miicam_anti_flicker"] = tk.IntVar(value=int(self.config.get("miicam_anti_flicker", 1)))
        self.detector_vars["miicam_binning"] = tk.IntVar(value=int(self.config.get("miicam_binning", 1)))
        self.detector_vars["miicam_frame_preload"] = tk.BooleanVar(value=bool(self.config.get("miicam_frame_preload", True)))
        self.detector_vars["miicam_thread_priority"] = tk.IntVar(value=int(self.config.get("miicam_thread_priority", 2)))

        row_sp = ttk.Frame(tab_sub_ctrl)
        row_sp.pack(fill="x", pady=4)
        ttk.Label(row_sp, text="Скорость передачи (Frame Rate / Speed):", width=38, anchor="w").pack(side="left")
        self.speed_combo_var = tk.StringVar(value="2: Максимальная (High / 60-120 FPS)")
        cb_speed = ttk.Combobox(row_sp, textvariable=self.speed_combo_var, values=["0: Низкая (Low)", "1: Нормальная (Normal)", "2: Максимальная (High / 60-120 FPS)"], state="readonly", width=32)
        cb_speed.pack(side="left")
        def _on_speed_cb(event=None):
            idx = cb_speed.current()
            if idx >= 0:
                self.detector_vars["miicam_speed"].set(idx)
                self._on_detector_param_changed()
        cb_speed.bind("<<ComboboxSelected>>", _on_speed_cb)

        row_bin = ttk.Frame(tab_sub_ctrl)
        row_bin.pack(fill="x", pady=4)
        ttk.Label(row_bin, text="Аппаратный биннинг (Hardware Binning):", width=38, anchor="w").pack(side="left")
        self.binning_combo_var = tk.StringVar(value="1: Полное разрешение 1x1")
        cb_bin = ttk.Combobox(row_bin, textvariable=self.binning_combo_var, values=["1: Полное разрешение 1x1", "2: Биннинг 2x2 (Турбо FPS / Высокая чувств.)"], state="readonly", width=32)
        cb_bin.pack(side="left")
        def _on_bin_cb(event=None):
            idx = cb_bin.current()
            if idx == 1:
                self.detector_vars["miicam_binning"].set(2)
            else:
                self.detector_vars["miicam_binning"].set(1)
            self._on_detector_param_changed()
        cb_bin.bind("<<ComboboxSelected>>", _on_bin_cb)

        row_af = ttk.Frame(tab_sub_ctrl)
        row_af.pack(fill="x", pady=4)
        ttk.Label(row_af, text="Подавление мерцания (Anti-Flicker):", width=38, anchor="w").pack(side="left")
        self.af_combo_var = tk.StringVar(value="1: 50 Гц (Россия / Европа)")
        cb_af = ttk.Combobox(row_af, textvariable=self.af_combo_var, values=["0: 60 Гц (США / Япония)", "1: 50 Гц (Россия / Европа)", "2: Выключено (DC)"], state="readonly", width=32)
        cb_af.pack(side="left")
        def _on_af_cb(event=None):
            idx = cb_af.current()
            if idx >= 0:
                self.detector_vars["miicam_anti_flicker"].set(idx)
                self._on_detector_param_changed()
        cb_af.bind("<<ComboboxSelected>>", _on_af_cb)

        # --- SUB-TAB: FLIP ---
        self.detector_vars["miicam_h_flip"] = tk.BooleanVar(value=bool(self.config.get("miicam_h_flip", False)))
        self.detector_vars["miicam_v_flip"] = tk.BooleanVar(value=bool(self.config.get("miicam_v_flip", False)))

        cb_hf = ttk.Checkbutton(tab_sub_flip, text=" Отразить по горизонтали (Horizontal Flip)", variable=self.detector_vars["miicam_h_flip"], command=self._on_detector_param_changed)
        cb_hf.pack(anchor="w", pady=6)

        cb_vf = ttk.Checkbutton(tab_sub_flip, text=" Отразить по вертикали (Vertical Flip)", variable=self.detector_vars["miicam_v_flip"], command=self._on_detector_param_changed)
        cb_vf.pack(anchor="w", pady=6)

        # 3. INTERACTIVE BEFORE / AFTER IMAGE COMPARISON
        lf_comp = ttk.LabelFrame(tab_detector, text=" 👁️ Интерактивное сравнение: Исходное (Before) ⟷ С настройками (After) ", padding=8)
        lf_comp.pack(fill="both", expand=True, pady=(4, 0))

        comp_top = ttk.Frame(lf_comp)
        comp_top.pack(fill="x", pady=(0, 4))

        self.compare_mode_var = tk.StringVar(value=str(self.config.get("detector_compare_mode", "split")))
        ttk.Label(comp_top, text="Режим:").pack(side="left", padx=(0, 6))
        ttk.Radiobutton(comp_top, text="🌓 Сплит (До | После)", variable=self.compare_mode_var, value="split", command=self._trigger_comp_refresh).pack(side="left", padx=4)
        ttk.Radiobutton(comp_top, text="👥 Рядом (Side-by-Side)", variable=self.compare_mode_var, value="side", command=self._trigger_comp_refresh).pack(side="left", padx=4)
        ttk.Radiobutton(comp_top, text="✨ С настройками", variable=self.compare_mode_var, value="after", command=self._trigger_comp_refresh).pack(side="left", padx=4)
        ttk.Radiobutton(comp_top, text="📷 Исходное (Raw)", variable=self.compare_mode_var, value="before", command=self._trigger_comp_refresh).pack(side="left", padx=4)

        ttk.Button(comp_top, text="⚡ Применить настройки", command=self._apply_to_sensor_now).pack(side="right", padx=(6, 0))
        ttk.Button(comp_top, text="📸 Зафиксировать исходный кадр", command=self._capture_new_baseline).pack(side="right", padx=(6, 0))
        ttk.Button(comp_top, text="🔄 Сброс настроек", command=self._reset_detector_defaults).pack(side="right")

        comp_slider_row = ttk.Frame(lf_comp)
        comp_slider_row.pack(fill="x", pady=(0, 4))
        ttk.Label(comp_slider_row, text="Разделение сплита:").pack(side="left", padx=(0, 6))
        self.compare_split_pos_var = tk.IntVar(value=int(self.config.get("detector_split_pos", 50)))

        def _on_split_scale(val):
            try:
                iv = int(round(float(val)))
                if self.compare_split_pos_var.get() != iv:
                    self.compare_split_pos_var.set(iv)
            except Exception:
                pass

        self.s_split = ttk.Scale(comp_slider_row, from_=5, to=95, orient="horizontal", command=_on_split_scale)
        self.s_split.set(int(self.compare_split_pos_var.get()))
        self.s_split.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ttk.Label(comp_slider_row, textvariable=self.compare_split_pos_var, width=3).pack(side="left")
        ttk.Label(comp_slider_row, text="%").pack(side="left")

        self.lbl_comp_img = ttk.Label(lf_comp, anchor="center")
        self.lbl_comp_img.pack(fill="both", expand=True)

        self._baseline_raw_frame = None
        self._comp_timer_id = None
        self._cached_raw_scaled = None
        self._cached_raw_key = None
        self._cached_adj_scaled = None
        self._cached_params_key = None

        self._capture_new_baseline()

        # Start single preview update loop
        self._schedule_comparison_tick(50)

    def _bind_unit_switch(self, var_val1, var_val2, unit_var, combo):
        def _on_unit_change(event=None):
            new_u = unit_var.get()
            prev_u = getattr(combo, '_last_unit', 'мин')
            if new_u == prev_u:
                return
            try:
                v1 = float(var_val1.get())
                v2 = float(var_val2.get())
                if new_u == 'сек' and prev_u == 'мин':
                    var_val1.set(round(v1 * 60.0, 1))
                    if v2 > 0:
                        var_val2.set(round(v2 * 60.0, 1))
                elif new_u == 'мин' and prev_u == 'сек':
                    var_val1.set(round(v1 / 60.0, 2))
                    if v2 > 0:
                        var_val2.set(round(v2 / 60.0, 2))
            except Exception:
                pass
            combo._last_unit = new_u
        combo.bind("<<ComboboxSelected>>", _on_unit_change)
        combo._last_unit = unit_var.get()

    def _ensure_one_graph_setting(self):
        active = sum(1 for v in self.graph_vars.values() if v.get())
        if active == 0:
            self.graph_vars["show_r"].set(True)

    def _trigger_detector_awb(self):
        if self.current_cap and hasattr(self.current_cap, 'trigger_awb_once'):
            ok = self.current_cap.trigger_awb_once()
            if ok:
                if hasattr(self.current_cap, 'wb_temp') and 'miicam_temp' in getattr(self, 'detector_vars', {}):
                    self.detector_vars['miicam_temp'].set(self.current_cap.wb_temp)
                    s = getattr(self.detector_vars['miicam_temp'], 'scale_widget', None)
                    if s:
                        try: s.set(self.current_cap.wb_temp)
                        except Exception: pass
                if hasattr(self.current_cap, 'wb_tint') and 'miicam_tint' in getattr(self, 'detector_vars', {}):
                    self.detector_vars['miicam_tint'].set(self.current_cap.wb_tint)
                    s = getattr(self.detector_vars['miicam_tint'], 'scale_widget', None)
                    if s:
                        try: s.set(self.current_cap.wb_tint)
                        except Exception: pass
                for k, attr in [('miicam_wb_r', 'wb_r'), ('miicam_wb_g', 'wb_g'), ('miicam_wb_b', 'wb_b')]:
                    if hasattr(self.current_cap, attr) and k in getattr(self, 'detector_vars', {}):
                        val = getattr(self.current_cap, attr)
                        self.detector_vars[k].set(val)
                        s = getattr(self.detector_vars[k], 'scale_widget', None)
                        if s:
                            try: s.set(val)
                            except Exception: pass
                self._cached_adj_scaled = None
                self._cached_params_key = None
                messagebox.showinfo("Баланс белого", "Аппаратный баланс белого (AWB) успешно выполнен на сенсоре детектора!", parent=self.win)
            else:
                messagebox.showwarning("Баланс белого", "Не удалось выполнить команду AWB на сенсоре.", parent=self.win)
        else:
            messagebox.showinfo("Баланс белого", "Команда калибровки AWB будет применена при активном подключении RGB-детектора.", parent=self.win)

    def _trigger_auto_calibrate_exposure(self):
        if self.current_cap and hasattr(self.current_cap, 'auto_calibrate_exposure_once'):
            ok = self.current_cap.auto_calibrate_exposure_once()
            if ok:
                if hasattr(self.current_cap, 'exposure_us') and 'miicam_exposure_us' in getattr(self, 'detector_vars', {}):
                    self.detector_vars['miicam_exposure_us'].set(self.current_cap.exposure_us)
                    if hasattr(self, 's_exp'):
                        try: self.s_exp.set(self.current_cap.exposure_us)
                        except Exception: pass
                    if hasattr(self, 'lbl_exp_ms'):
                        self.lbl_exp_ms.config(text=f"{self.current_cap.exposure_us / 1000.0:.1f} мс")
                if hasattr(self.current_cap, 'gain_percent') and 'miicam_gain' in getattr(self, 'detector_vars', {}):
                    self.detector_vars['miicam_gain'].set(self.current_cap.gain_percent)
                    s = getattr(self.detector_vars['miicam_gain'], 'scale_widget', None)
                    if s:
                        try: s.set(self.current_cap.gain_percent)
                        except Exception: pass
                if 'miicam_auto_exposure' in getattr(self, 'detector_vars', {}):
                    self.detector_vars['miicam_auto_exposure'].set(False)
                self._on_detector_param_changed()
                messagebox.showinfo(
                    "Автонастройка экспозиции",
                    f"Яркость успешно подобрана и зафиксирована!\n"
                    f"Выдержка: {self.current_cap.exposure_us / 1000.0:.1f} мс (30+ FPS), Усиление: {self.current_cap.gain_percent}%\n"
                    f"Мерцание и просадка FPS полностью устранены.",
                    parent=self.win
                )
            else:
                messagebox.showwarning("Автонастройка экспозиции", "Не удалось выполнить автонастройку на сенсоре.", parent=self.win)
        else:
            messagebox.showinfo("Автонастройка экспозиции", "Команда калибровки будет применена при активном подключении RGB-детектора.", parent=self.win)

    def _apply_to_sensor_now(self):
        cfg = {k: v.get() for k, v in getattr(self, 'detector_vars', {}).items()}
        if self.current_cap and hasattr(self.current_cap, 'apply_settings_dict'):
            try:
                self._on_detector_param_changed(immediate=True)
                messagebox.showinfo("Настройки камеры", "Текущие настройки успешно применены к камере!", parent=self.win)
            except Exception as e:
                messagebox.showwarning("Настройки камеры", f"Не удалось применить настройки: {e}", parent=self.win)
        else:
            messagebox.showinfo("Настройки камеры", "Настройки сохранены и будут применены при подключении камеры.", parent=self.win)

    def _set_exposure_preset(self, us):
        if 'miicam_exposure_us' in self.detector_vars:
            self.detector_vars['miicam_exposure_us'].set(us)
            if hasattr(self, 's_exp'):
                try:
                    self.s_exp.set(us)
                except Exception:
                    pass
            if hasattr(self, 'lbl_exp_ms'):
                self.lbl_exp_ms.config(text=f"{us / 1000.0:.1f} мс")
            self._on_detector_param_changed()

    def _apply_high_fps_preset(self, target_fps=90):
        if target_fps >= 90:
            self.detector_vars["miicam_exposure_us"].set(8000)
            self.detector_vars["miicam_gain"].set(160)
            self.detector_vars["miicam_speed"].set(2)
            self.detector_vars["miicam_binning"].set(2)
            self.detector_vars["miicam_frame_preload"].set(True)
            self.detector_vars["miicam_thread_priority"].set(2)
            if hasattr(self, 'speed_combo_var'):
                self.speed_combo_var.set("2: Максимальная (High / 60-120 FPS)")
            if hasattr(self, 'binning_combo_var'):
                self.binning_combo_var.set("2: Биннинг 2x2 (Турбо FPS / Высокая чувств.)")
        elif target_fps >= 60:
            self.detector_vars["miicam_exposure_us"].set(16000)
            self.detector_vars["miicam_gain"].set(120)
            self.detector_vars["miicam_speed"].set(2)
            self.detector_vars["miicam_binning"].set(1)
            self.detector_vars["miicam_frame_preload"].set(True)
            self.detector_vars["miicam_thread_priority"].set(2)
            if hasattr(self, 'speed_combo_var'):
                self.speed_combo_var.set("2: Максимальная (High / 60-120 FPS)")
            if hasattr(self, 'binning_combo_var'):
                self.binning_combo_var.set("1: Полное разрешение 1x1")
        self._on_detector_param_changed()

    def _on_preset_scope_changed(self, *args):
        label = self.preset_scope_label_var.get()
        if label in getattr(self, "_preset_scope_labels", {}):
            self.preset_scope_var.set(self._preset_scope_labels[label])

    def _refresh_detector_presets(self, preferred_id=None):
        records = list(self.project_store.list_presets("detector"))
        # Old integrations may still mutate config["detector_presets"] directly.
        # Read these values for compatibility, but never persist them from the
        # application-managed ProjectStore path.
        if self._legacy_preset_compat:
            legacy = self.config.get("detector_presets", {})
            if isinstance(legacy, dict):
                known_builtin_names = {r.get("name", "").casefold() for r in records if r.get("locked")}
                for name, settings in legacy.items():
                    if (isinstance(settings, dict) and str(name).casefold() not in known_builtin_names
                            and not any(r.get("name", "").casefold() == str(name).casefold() for r in records)):
                        records.append({
                            "id": f"legacy:detector:{name}", "kind": "detector", "name": str(name),
                            "origin": "user", "locked": False, "settings": settings,
                        })

        labels = []
        mapping = {}
        selected = None
        for record in records:
            origin = record.get("origin", "user")
            label = record.get("name", "Пресет")
            if origin == "project":
                label += " · проект"
            elif origin == "user":
                label += " · личный"
            if label in mapping:
                label += f" · {str(record.get('id', ''))[-6:]}"
            labels.append(label)
            mapping[label] = record
            if record.get("id") == preferred_id:
                selected = label
        self._detector_preset_records = records
        self._detector_preset_by_label = mapping
        self.cb_detector_presets.configure(values=labels)
        if selected is None and labels:
            selected = labels[0]
        self.preset_var.set(selected or "")

    def _selected_detector_preset(self, preset_name=None):
        value = preset_name or (self.preset_var.get() if hasattr(self, "preset_var") else "")
        record = getattr(self, "_detector_preset_by_label", {}).get(value)
        if record:
            return record
        for item in getattr(self, "_detector_preset_records", []):
            if item.get("name") == value or item.get("id") == value:
                return item
        return None

    def _apply_detector_preset(self, preset_name=None, show_message=True):
        name = preset_name or (self.preset_var.get() if hasattr(self, 'preset_var') else None)
        record = self._selected_detector_preset(name)
        if record is None and self._legacy_preset_compat:
            old_settings = self.config.get("detector_presets", {})
            if isinstance(old_settings, dict) and name in old_settings:
                record = {"id": f"legacy:detector:{name}", "name": name,
                          "locked": str(name).casefold() == "по умолчанию (default)".casefold(),
                          "settings": old_settings[name]}
        if not record:
            messagebox.showwarning("Пресеты", f"Пресет «{name}» не найден.", parent=self.win)
            return
        p_data = record.get("settings", {})
        for k, v in p_data.items():
            if k in getattr(self, 'detector_vars', {}):
                try:
                    self.detector_vars[k].set(v)
                    if hasattr(self.detector_vars[k], 'scale_widget'):
                        self.detector_vars[k].scale_widget.set(v)
                except Exception:
                    pass
        if 'miicam_exposure_us' in self.detector_vars:
            try:
                exp_us = int(self.detector_vars['miicam_exposure_us'].get())
                if hasattr(self, 'lbl_exp_ms'):
                    self.lbl_exp_ms.config(text=f"{exp_us / 1000.0:.1f} мс")
                if hasattr(self, 's_exp'):
                    self.s_exp.set(exp_us)
            except Exception:
                pass
        if 'miicam_binning' in self.detector_vars and hasattr(self, 'binning_combo_var'):
            b_val = self.detector_vars['miicam_binning'].get()
            self.binning_combo_var.set("2: Биннинг 2x2 (Турбо FPS / Высокая чувств.)" if b_val == 2 else "1: Полное разрешение 1x1")
        if 'miicam_speed' in self.detector_vars and hasattr(self, 'speed_combo_var'):
            s_val = self.detector_vars['miicam_speed'].get()
            self.speed_combo_var.set("2: Максимальная (High / 60-120 FPS)" if s_val == 2 else "1: Средняя" if s_val == 1 else "0: Низкая")

        if record.get("id") and not str(record["id"]).startswith("legacy:"):
            self._applied_detector_preset_id = record["id"]
        self._on_detector_param_changed()
        if show_message:
            messagebox.showinfo("Пресеты", f"Пресет «{record.get('name', name)}» успешно применен!", parent=self.win)

    def _save_detector_preset(self):
        name = simpledialog.askstring(
            "Сохранить пресет", "Введите название копии пресета:", parent=self.win
        )
        if not name or not name.strip():
            return
        name = name.strip()
        p_data = {}
        for k, var in getattr(self, 'detector_vars', {}).items():
            try:
                p_data[k] = var.get()
            except Exception:
                pass
        selected = self._selected_detector_preset()
        scope = self.preset_scope_var.get()
        try:
            record = self.project_store.save_preset(
                "detector", name, p_data, scope=scope,
                based_on=selected.get("id") if selected else None,
            )
        except Exception as exc:
            messagebox.showerror("Пресеты", str(exc), parent=self.win)
            return
        self._applied_detector_preset_id = record["id"]
        self._refresh_detector_presets(record["id"])
        messagebox.showinfo(
            "Пресеты", f"Копия «{name}» сохранена ({'проект' if scope == 'project' else 'личная библиотека'}).",
            parent=self.win,
        )

    def _set_detector_preset_default(self):
        record = self._selected_detector_preset()
        if not record:
            return
        self._pending_default_preset_id = record["id"]
        if self._applied_detector_preset_id != record["id"]:
            self._apply_detector_preset(record["id"], show_message=False)
        messagebox.showinfo(
            "Пресеты", f"«{record['name']}» будет пресетом по умолчанию после нажатия «Сохранить и применить».",
            parent=self.win,
        )

    def _delete_detector_preset(self):
        name = self.preset_var.get() if hasattr(self, 'preset_var') else None
        record = self._selected_detector_preset(name)
        if not record and self._legacy_preset_compat:
            legacy = self.config.get("detector_presets", {})
            if isinstance(legacy, dict) and name in legacy:
                record = {"id": f"legacy:detector:{name}", "name": name,
                          "locked": name == "По умолчанию (Default)"}
        if not name or not record:
            return
        if record.get("locked") or str(record.get("id", "")).startswith("builtin:"):
            messagebox.showwarning(
                "Защита пресета", "Встроенный пресет защищен от изменения и удаления. Сохраните его копию под другим именем.",
                parent=self.win
            )
            return
        if not messagebox.askyesno("Удаление пресета", f"Удалить пресет «{record.get('name', name)}»?", parent=self.win):
            return
        try:
            if str(record.get("id", "")).startswith("legacy:") and self._legacy_preset_compat:
                self.config.get("detector_presets", {}).pop(record.get("name"), None)
            else:
                self.project_store.delete_preset(record["id"])
        except Exception as exc:
            messagebox.showerror("Пресеты", str(exc), parent=self.win)
            return
        default_id = self.project_store.get_default_preset_id("detector")
        if record.get("id") == self._applied_detector_preset_id:
            self._applied_detector_preset_id = default_id
        if record.get("id") == self._pending_default_preset_id:
            self._pending_default_preset_id = None
        self._refresh_detector_presets(default_id)
        messagebox.showinfo("Пресеты", f"Пресет «{record.get('name', name)}» удален.", parent=self.win)

    def _capture_new_baseline(self):
        """Зафиксировать чистый эталонный кадр (Raw Baseline) для левой половины сравнения."""
        f = None
        if self.current_cap and hasattr(self.current_cap, 'read') and getattr(self.current_cap, 'isOpened', lambda: False)():
            try:
                ret, frame = self.current_cap.read()
                if ret and frame is not None and frame.size > 0:
                    f = frame.copy()
            except Exception:
                pass
        if f is None and hasattr(self.parent, 'latest_frame') and self.parent.latest_frame is not None:
            f = self.parent.latest_frame.copy()
        if f is None:
            f = np.zeros((320, 560, 3), dtype=np.uint8)
            for x in range(560):
                f[:, x, 0] = int(220 * (x / 560.0))
                f[:, x, 1] = int(240 * (1.0 - abs(x - 280) / 280.0))
                f[:, x, 2] = int(255 * (1.0 - x / 560.0))
            cv2.circle(f, (110, 100), 50, (40, 40, 240), -1)
            cv2.circle(f, (280, 100), 50, (40, 230, 40), -1)
            cv2.circle(f, (450, 100), 50, (240, 120, 30), -1)
            cv2.rectangle(f, (80, 180), (480, 280), (180, 180, 180), -1)
            cv2.putText(f, "RGB TEST PATTERN", (140, 235), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2)
        self._baseline_raw_frame = f
        self._cached_raw_scaled = None
        self._cached_adj_scaled = None
        self._cached_params_key = None

    def _trigger_comp_refresh(self):
        self._cached_adj_scaled = None
        self._cached_params_key = None

    def _schedule_comparison_tick(self, delay_ms=40):
        if getattr(self, '_comp_timer_id', None) is not None:
            try:
                self.win.after_cancel(self._comp_timer_id)
            except Exception:
                pass
            self._comp_timer_id = None
        if hasattr(self, 'win') and self.win.winfo_exists() and getattr(self, 'is_miicam', False):
            self._comp_timer_id = self.win.after(delay_ms, self._update_comparison_view)

    def _update_comparison_view(self):
        if not hasattr(self, 'win') or not self.win.winfo_exists() or not getattr(self, 'is_miicam', False):
            return

        try:
            if getattr(self, '_baseline_raw_frame', None) is None:
                self._capture_new_baseline()

            raw = self._baseline_raw_frame if self._baseline_raw_frame is not None else np.zeros((320, 560, 3), dtype=np.uint8)

            pw = max(360, self.lbl_comp_img.winfo_width())
            ph = max(180, self.lbl_comp_img.winfo_height())
            if pw <= 1:
                pw = 640
            if ph <= 1:
                ph = 250

            scale = min(pw / raw.shape[1], ph / raw.shape[0])
            nw, nh = max(10, int(raw.shape[1] * scale)), max(10, int(raw.shape[0] * scale))

            b = int(self.detector_vars.get("miicam_brightness", tk.IntVar(value=0)).get())
            c = int(self.detector_vars.get("miicam_contrast", tk.IntVar(value=0)).get())
            g = int(self.detector_vars.get("miicam_gamma", tk.IntVar(value=100)).get())
            h = int(self.detector_vars.get("miicam_hue", tk.IntVar(value=0)).get())
            s = int(self.detector_vars.get("miicam_saturation", tk.IntVar(value=128)).get())
            temp = int(self.detector_vars.get("miicam_temp", tk.IntVar(value=6500)).get())
            tint = int(self.detector_vars.get("miicam_tint", tk.IntVar(value=1000)).get())
            gain = int(self.detector_vars.get("miicam_gain", tk.IntVar(value=100)).get())
            wb_r = int(self.detector_vars.get("miicam_wb_r", tk.IntVar(value=0)).get())
            wb_g = int(self.detector_vars.get("miicam_wb_g", tk.IntVar(value=0)).get())
            wb_b = int(self.detector_vars.get("miicam_wb_b", tk.IntVar(value=0)).get())
            hf = bool(self.detector_vars.get("miicam_h_flip", tk.BooleanVar(value=False)).get())
            vf = bool(self.detector_vars.get("miicam_v_flip", tk.BooleanVar(value=False)).get())

            current_params_key = (
                b, c, g, h, s, temp, tint, gain,
                wb_r, wb_g, wb_b, hf, vf, nw, nh, id(self._baseline_raw_frame)
            )

            # 1. Recompute scaled raw only when baseline or geometry changes
            if getattr(self, '_cached_raw_scaled', None) is None or getattr(self, '_cached_raw_key', None) != (nw, nh, id(self._baseline_raw_frame)):
                self._cached_raw_scaled = cv2.resize(raw, (nw, nh))
                self._cached_raw_key = (nw, nh, id(self._baseline_raw_frame))

            raw_scaled = self._cached_raw_scaled

            # 2. Recompute adjusted frame only when sliders or geometry change
            if getattr(self, '_cached_adj_scaled', None) is None or getattr(self, '_cached_params_key', None) != current_params_key:
                adj = raw_scaled.copy()

                # A. Gain
                if gain != 100 and gain > 0:
                    adj = cv2.convertScaleAbs(adj, alpha=gain / 100.0, beta=0)

                # B. Contrast & Brightness
                if c != 0 or b != 0:
                    alpha = max(0.1, (c + 100.0) / 100.0)
                    beta = b
                    adj = cv2.convertScaleAbs(adj, alpha=alpha, beta=beta)

                # C. Gamma
                if g != 100 and g > 0:
                    inv_gamma = 100.0 / float(g)
                    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
                    adj = cv2.LUT(adj, table)

                # D. Color Temperature (Temp K) & Tint (Subtle natural Planckian shift)
                if temp != 6500 or tint != 1000:
                    t_factor = (temp - 6500.0) / 15000.0
                    tint_factor = (tint - 1000.0) / 3000.0
                    r_mult = max(0.1, 1.0 + 0.2 * t_factor + 0.15 * tint_factor)
                    g_mult = max(0.1, 1.0 - 0.15 * tint_factor)
                    b_mult = max(0.1, 1.0 - 0.2 * t_factor + 0.15 * tint_factor)
                    adj_f = adj.astype(np.float32)
                    adj_f[:, :, 0] = np.clip(adj_f[:, :, 0] * b_mult, 0, 255)
                    adj_f[:, :, 1] = np.clip(adj_f[:, :, 1] * g_mult, 0, 255)
                    adj_f[:, :, 2] = np.clip(adj_f[:, :, 2] * r_mult, 0, 255)
                    adj = adj_f.astype(np.uint8)

                # E. White Balance RGB Gains
                if wb_r != 0 or wb_g != 0 or wb_b != 0:
                    adj_f = adj.astype(np.float32)
                    adj_f[:, :, 0] *= (1.0 + wb_b / 128.0)
                    adj_f[:, :, 1] *= (1.0 + wb_g / 128.0)
                    adj_f[:, :, 2] *= (1.0 + wb_r / 128.0)
                    adj = np.clip(adj_f, 0, 255).astype(np.uint8)

                # F. Hue & Saturation
                if h != 0 or s != 128:
                    hsv = cv2.cvtColor(adj, cv2.COLOR_BGR2HSV).astype(np.float32)
                    if h != 0:
                        hsv[:, :, 0] = np.mod(hsv[:, :, 0] + (float(h) / 2.0), 180.0)
                    if s != 128:
                        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (float(s) / 128.0), 0.0, 255.0)
                    adj = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)

                # G. Flips
                if hf:
                    adj = cv2.flip(adj, 1)
                if vf:
                    adj = cv2.flip(adj, 0)

                self._cached_adj_scaled = adj
                self._cached_params_key = current_params_key

            adj_scaled = self._cached_adj_scaled

            # 3. Fast composition (0.1 ms - zero lag during slider drag!)
            mode = self.compare_mode_var.get()
            if mode == "split":
                split_frac = getattr(self, 'compare_split_pos_var', tk.IntVar(value=50)).get() / 100.0
                split_x = max(1, min(nw - 1, int(nw * split_frac)))
                comp = adj_scaled.copy()
                comp[:, :split_x] = raw_scaled[:, :split_x]
                # High-visibility divider line
                cv2.line(comp, (split_x, 0), (split_x, nh), (0, 255, 255), 2)
                # Labels in clean ASCII to avoid Hershey font Cyrillic bugs
                cv2.rectangle(comp, (6, 6), (150, 28), (0, 0, 0), -1)
                cv2.putText(comp, "[ BEFORE / RAW ]", (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1)
                cv2.rectangle(comp, (split_x + 6, 6), (split_x + 180, 28), (0, 0, 0), -1)
                cv2.putText(comp, "[ AFTER / ADJUSTED ]", (split_x + 10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 128), 1)
            elif mode == "side":
                half_w = max(10, nw // 2)
                r_half = cv2.resize(raw_scaled, (half_w, nh))
                a_half = cv2.resize(adj_scaled, (half_w, nh))
                cv2.rectangle(r_half, (4, 4), (150, 26), (0, 0, 0), -1)
                cv2.putText(r_half, "[ BEFORE / RAW ]", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (220, 220, 220), 1)
                cv2.rectangle(a_half, (4, 4), (170, 26), (0, 0, 0), -1)
                cv2.putText(a_half, "[ AFTER / ADJUSTED ]", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 128), 1)
                comp = np.hstack([r_half, a_half])
            elif mode == "before":
                comp = raw_scaled.copy()
                cv2.rectangle(comp, (6, 6), (150, 28), (0, 0, 0), -1)
                cv2.putText(comp, "[ BEFORE / RAW ]", (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            else:
                comp = adj_scaled.copy()
                cv2.rectangle(comp, (6, 6), (180, 28), (0, 0, 0), -1)
                cv2.putText(comp, "[ AFTER / ADJUSTED ]", (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 128), 1)

            rgb = cv2.cvtColor(comp, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            imgtk = ImageTk.PhotoImage(image=img)
            self.lbl_comp_img.imgtk = imgtk
            self.lbl_comp_img.configure(image=imgtk)

        except Exception:
            pass
        finally:
            self._schedule_comparison_tick(40)

    def _on_detector_param_changed(self, event=None, immediate=False):
        self._cached_adj_scaled = None
        self._cached_params_key = None
        cfg = {k: v.get() for k, v in getattr(self, 'detector_vars', {}).items()}
        if hasattr(self, 'config') and isinstance(self.config, dict):
            try:
                self.config.update(cfg)
            except Exception:
                pass

        def _push():
            self._detector_apply_after_id = None
            if self.current_cap and hasattr(self.current_cap, 'is_miicam') and self.current_cap.is_miicam and hasattr(self.current_cap, 'apply_settings_dict'):
                try:
                    latest = {k: v.get() for k, v in getattr(self, 'detector_vars', {}).items()}
                    self.current_cap.apply_settings_dict(latest)
                except Exception:
                    pass

        if immediate:
            if getattr(self, '_detector_apply_after_id', None) is not None:
                try: self.win.after_cancel(self._detector_apply_after_id)
                except Exception: pass
                self._detector_apply_after_id = None
            _push()
            return
        try:
            if getattr(self, '_detector_apply_after_id', None) is not None:
                self.win.after_cancel(self._detector_apply_after_id)
            self._detector_apply_after_id = self.win.after(80, _push)
        except Exception:
            _push()

    def _set_color_profile(self, sat, contrast, brightness, gamma):
        profile = {
            "miicam_saturation": sat,
            "miicam_contrast": contrast,
            "miicam_brightness": brightness,
            "miicam_gamma": gamma,
            "miicam_hue": 0,
        }
        for k, v in profile.items():
            if k in getattr(self, 'detector_vars', {}):
                self.detector_vars[k].set(v)
                s = getattr(self.detector_vars[k], 'scale_widget', None)
                if s is not None:
                    try:
                        s.set(v)
                    except Exception:
                        pass
        self._on_detector_param_changed()

    def _reset_color_defaults(self):
        self._set_color_profile(sat=165, contrast=15, brightness=0, gamma=100)

    def _reset_detector_defaults(self):
        defaults = dict(DEFAULT_DETECTOR_PRESETS.get("По умолчанию (Default)", {}))
        for k, v in defaults.items():
            if k in getattr(self, 'detector_vars', {}):
                self.detector_vars[k].set(v)
                s = getattr(self.detector_vars[k], 'scale_widget', None)
                if s is not None:
                    try:
                        s.set(v)
                    except Exception:
                        pass
        self._on_detector_param_changed()
        exp_val = defaults.get("miicam_exposure_us", 22000)
        if hasattr(self, 's_exp'):
            try:
                self.s_exp.set(exp_val)
            except Exception:
                pass
        if hasattr(self, 'lbl_exp_ms'):
            self.lbl_exp_ms.config(text=f"{exp_val / 1000.0:.1f} мс")
        if hasattr(self, 'compare_mode_var'):
            self.compare_mode_var.set("split")
        if hasattr(self, 'compare_split_pos_var'):
            self.compare_split_pos_var.set(50)
        if hasattr(self, 's_split'):
            try:
                self.s_split.set(50)
            except Exception:
                pass
        if hasattr(self, 'speed_combo_var'):
            self.speed_combo_var.set("2: Максимальная (High / 60-120 FPS)")
        if hasattr(self, 'binning_combo_var'):
            self.binning_combo_var.set("1: Полное разрешение 1x1")
        self._on_detector_param_changed()

    def _profile_selected(self, event=None):
        name = self.profile_var.get()
        prof = PERFORMANCE_PROFILES.get(name)
        if not prof:
            return
        for k, v in prof.items():
            if k in self.perf_vars:
                self.perf_vars[k].set(v)

    def _load_from_config(self):
        saved = load_saved_settings()
        merged = {**DEFAULT_CONFIG, **saved, **self.config}

        prof_name = merged.get("performance_profile", "Сбалансированный")
        self.profile_var.set(prof_name)

        self.display_max_width_var.set(int(merged.get("display_max_width", 1280)))

        for k, var in self.perf_vars.items():
            var.set(int(merged.get(k, DEFAULT_CONFIG.get(k, 100))))

        for k, var in self.graph_vars.items():
            var.set(bool(merged.get(k, DEFAULT_CONFIG.get(k, True))))

        for k, var in self.video_vars.items():
            var.set(bool(merged.get(k, DEFAULT_CONFIG.get(k, False))))

        for k, var in self.roi_vars.items():
            var.set(bool(merged.get(k, DEFAULT_CONFIG.get(k, True))))

        for k, var in self.notification_vars.items():
            var.set(bool(merged.get(k, DEFAULT_CONFIG.get(k, True))))

        for k, var in getattr(self, "detector_vars", {}).items():
            if k in merged:
                var.set(merged[k])
                s = getattr(var, 'scale_widget', None)
                if s is not None:
                    try:
                        s.set(int(merged[k]))
                    except Exception:
                        pass

        # If camera is connected, sync active hardware parameters to UI sliders
        if getattr(self, 'is_miicam', False) and self.current_cap is not None:
            try:
                cap = self.current_cap
                hw_sync = {
                    "miicam_exposure_us": getattr(cap, 'exposure_us', None),
                    "miicam_gain": getattr(cap, 'gain_percent', None),
                    "miicam_brightness": getattr(cap, 'brightness', None),
                    "miicam_contrast": getattr(cap, 'contrast', None),
                    "miicam_gamma": getattr(cap, 'gamma', None),
                    "miicam_hue": getattr(cap, 'hue', None),
                    "miicam_saturation": getattr(cap, 'saturation', None),
                    "miicam_temp": getattr(cap, 'wb_temp', None),
                    "miicam_tint": getattr(cap, 'wb_tint', None),
                    "miicam_wb_r": getattr(cap, 'wb_r', None),
                    "miicam_wb_g": getattr(cap, 'wb_g', None),
                    "miicam_wb_b": getattr(cap, 'wb_b', None),
                    "miicam_speed": getattr(cap, 'speed', None),
                    "miicam_binning": getattr(cap, 'binning_mode', None),
                    "miicam_h_flip": getattr(cap, 'h_flip', None),
                    "miicam_v_flip": getattr(cap, 'v_flip', None),
                }
                for k, v in hw_sync.items():
                    if v is not None and k in getattr(self, "detector_vars", {}):
                        self.detector_vars[k].set(v)
                        s = getattr(self.detector_vars[k], 'scale_widget', None)
                        if s is not None:
                            try:
                                s.set(int(v) if isinstance(v, (int, float)) else v)
                            except Exception:
                                pass
            except Exception:
                pass

        if hasattr(self, 'compare_mode_var'):
            self.compare_mode_var.set(str(merged.get("detector_compare_mode", "split")))
        if hasattr(self, 'compare_split_pos_var'):
            self.compare_split_pos_var.set(int(merged.get("detector_split_pos", 50)))
        if hasattr(self, 's_split'):
            try:
                self.s_split.set(int(merged.get("detector_split_pos", 50)))
            except Exception:
                pass
        if hasattr(self, 'speed_combo_var'):
            sp_idx = int(getattr(self.current_cap, 'speed', merged.get("miicam_speed", 2)))
            vals = ["0: Низкая (Low)", "1: Нормальная (Normal)", "2: Максимальная (High / 60-120 FPS)"]
            if 0 <= sp_idx < len(vals):
                self.speed_combo_var.set(vals[sp_idx])
        if hasattr(self, 'binning_combo_var'):
            bin_idx = int(getattr(self.current_cap, 'binning_mode', merged.get("miicam_binning", 1)))
            self.binning_combo_var.set("2: Биннинг 2x2 (Турбо FPS / Высокая чувств.)" if bin_idx == 2 else "1: Полное разрешение 1x1")
        if hasattr(self, 's_exp') and 'miicam_exposure_us' in getattr(self, 'detector_vars', {}):
            try:
                self.s_exp.set(int(self.detector_vars['miicam_exposure_us'].get()))
            except Exception:
                pass
        if hasattr(self, 'lbl_exp_ms') and 'miicam_exposure_us' in getattr(self, 'detector_vars', {}):
            try:
                v = int(self.detector_vars['miicam_exposure_us'].get())
                self.lbl_exp_ms.config(text=f"{v / 1000.0:.1f} мс")
            except Exception:
                pass

        # Base auto marks
        arom_u = merged.get("auto_mark_arom_unit", "мин")
        self.arom_unit_var.set(arom_u)
        self.arom_unit_combo._last_unit = arom_u
        f_ar = 60.0 if arom_u == "мин" else 1.0
        self.arom_t_min_var.set(round(float(merged.get("auto_mark_arom_t_min_sec", AROM_T_MIN_SEC)) / f_ar, 2))
        self.arom_t_max_var.set(round(float(merged.get("auto_mark_arom_t_max_sec", AROM_T_MAX_SEC)) / f_ar, 2))

        br_u = merged.get("auto_mark_br_unit", "мин")
        self.br_unit_var.set(br_u)
        self.br_unit_combo._last_unit = br_u
        f_br = 60.0 if br_u == "мин" else 1.0
        self.br_delay_var.set(round(float(merged.get("auto_mark_br_arm_delay_sec", BR_ARM_DELAY_SEC)) / f_br, 2))
        self.br_t_max_var.set(round(float(merged.get("auto_mark_br_t_max_sec", BR_T_MAX_SEC)) / f_br, 2))

        abr_u = merged.get("auto_mark_abr_unit", "мин")
        self.abr_unit_var.set(abr_u)
        self.abr_unit_combo._last_unit = abr_u
        f_ab = 60.0 if abr_u == "мин" else 1.0
        self.abr_delay_var.set(round(float(merged.get("auto_mark_abr_arm_delay_sec", ABR_ARM_DELAY_SEC)) / f_ab, 2))
        self.abr_t_max_var.set(round(float(merged.get("auto_mark_abr_t_max_sec", ABR_T_MAX_SEC)) / f_ab, 2))

        speed = float(merged.get("playback_speed", 1.0))
        self.playback_speed_var.set(f"{speed:.2f}x" if speed not in (0.25, 0.5, 1.0, 1.5, 2.0, 4.0, 8.0) else f"{speed:.1f}x")

        seek = int(merged.get("seek_step_sec", 5))
        self.seek_step_var.set(f"{seek} сек")

        self._custom_variables = list(merged.get("custom_variables", [])) if isinstance(merged.get("custom_variables", []), list) else []
        self._custom_graphs = list(merged.get("custom_graphs", [])) if isinstance(merged.get("custom_graphs", []), list) else []
        self._custom_auto_marks = list(merged.get("custom_auto_marks", [])) if isinstance(merged.get("custom_auto_marks", []), list) else []

        self._refresh_custom_var_list()
        self._refresh_custom_graph_list()
        self._refresh_custom_auto_marks_list()

    def _reset(self):
        self.profile_var.set("Сбалансированный")
        self._profile_selected()
        for k, v in DEFAULT_CONFIG.items():
            if k in self.graph_vars:
                self.graph_vars[k].set(v)
            if k in self.video_vars:
                self.video_vars[k].set(v)
            if k in self.roi_vars:
                self.roi_vars[k].set(v)
            if k in self.notification_vars:
                self.notification_vars[k].set(v)
            if k in getattr(self, "detector_vars", {}):
                self.detector_vars[k].set(v)
        if hasattr(self, 'lbl_exp_ms'):
            self.lbl_exp_ms.config(text="20.0 мс")
        self.video_vars["record_video"].set(True)
        self.video_vars["save_roi_on_video"].set(False)
        self.playback_speed_var.set("1.0x")
        self.seek_step_var.set("5 сек")
        self._custom_variables = []
        self._custom_graphs = []
        self._refresh_custom_var_list()
        self._refresh_custom_graph_list()

    def _refresh_custom_auto_marks_list(self):
        if not hasattr(self, 'custom_marks_tree'):
            return
        for item in self.custom_marks_tree.get_children():
            self.custom_marks_tree.delete(item)
        for idx, rule in enumerate(self._custom_auto_marks):
            status = "ВКЛ" if rule.get("enabled", True) else "ВЫКЛ"
            name = rule.get("name") or f"Метка #{idx+1}"
            cond_list = rule.get("conditions")
            if not cond_list:
                metric = rule.get("metric", "RGB_sum_slope_30s")
                op = rule.get("operator", ">=")
                th = rule.get("threshold", 0.0)
                cond = f"{metric} {op} {th}"
            else:
                cond = " И ".join([f"{c.get('metric')} {c.get('operator')} {c.get('threshold')}" for c in cond_list])
            t_min = float(rule.get("t_min_sec", 0.0))
            t_max = float(rule.get("t_max_sec", 0.0))
            if t_min >= 60 or t_max >= 60:
                t_min_m = t_min / 60.0
                t_max_m = t_max / 60.0
                win = f"{t_min_m:.1f} - {t_max_m:.1f} мин" if t_max > 0 else f"от {t_min_m:.1f} мин (до конца)"
            else:
                win = f"{t_min:g} - {t_max:g} с" if t_max > 0 else f"от {t_min:g} с (до конца)"
            color = rule.get("color", get_palette(bool(self.config.get("light_theme", False)))["success"])
            sound = "🔊 Да" if rule.get("sound", True) else "Нет"
            self.custom_marks_tree.insert("", "end", iid=str(idx), values=(status, name, cond, win, color, sound))

    def _add_custom_auto_mark(self):
        self._open_custom_mark_dialog(edit_index=None)

    def _edit_custom_auto_mark(self):
        sel = self.custom_marks_tree.selection()
        if not sel:
            messagebox.showinfo("Автометки", "Выберите правило для редактирования", parent=self.win)
            return
        idx = int(sel[0])
        self._open_custom_mark_dialog(edit_index=idx)

    def _toggle_custom_auto_mark(self):
        sel = self.custom_marks_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._custom_auto_marks):
            curr = bool(self._custom_auto_marks[idx].get("enabled", True))
            self._custom_auto_marks[idx]["enabled"] = not curr
            self._refresh_custom_auto_marks_list()
            self.custom_marks_tree.selection_set(str(idx))

    def _delete_custom_auto_mark(self):
        sel = self.custom_marks_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._custom_auto_marks):
            del self._custom_auto_marks[idx]
            self._refresh_custom_auto_marks_list()

    def _open_custom_mark_dialog(self, edit_index=None):
        rule = {}
        if edit_index is not None and 0 <= edit_index < len(self._custom_auto_marks):
            rule = dict(self._custom_auto_marks[edit_index])

        dlg = tk.Toplevel(self.win)
        dlg.title("Редактирование автометки" if edit_index is not None else "Новая пользовательская автометка")
        dlg.geometry("860x580")
        dlg.minsize(800, 520)
        dlg.transient(self.win)
        dlg.grab_set()

        light = bool(self.config.get("light_theme", False))
        colors = get_palette(light)
        bg = colors['background']
        panel = colors['surface']
        fg = colors['text']
        dlg.configure(bg=bg)

        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill="both", expand=True)

        # 1. Name & Color
        r0 = ttk.Frame(frm)
        r0.pack(fill="x", pady=4)
        ttk.Label(r0, text="Название автометки:", font=("Segoe UI", 9, "bold"), width=20, anchor="w").pack(side="left")
        name_var = tk.StringVar(value=rule.get("name", "Пользовательская метка"))
        ttk.Entry(r0, textvariable=name_var).pack(side="left", fill="x", expand=True, padx=(0, 10))

        color_var = tk.StringVar(value=rule.get("color", get_palette(bool(self.config.get("light_theme", False)))["success"]))
        color_preview = tk.Canvas(r0, width=24, height=22, bg=color_var.get(), highlightthickness=1)
        color_preview.pack(side="left", padx=(0, 6))

        def _choose_color():
            res = colorchooser.askcolor(color_var.get(), parent=dlg)
            if res and res[1]:
                color_var.set(res[1])
                color_preview.configure(bg=res[1])

        ttk.Button(r0, text="🎨 Цвет", command=_choose_color, width=8).pack(side="left")

        # 2. Multi-conditions Frame (Условия срабатывания)
        lf_cond = ttk.LabelFrame(frm, text=" 🎯 Условия срабатывания (логика «И» — должны совпасть все параметры) ", padding=10)
        lf_cond.pack(fill="both", expand=True, pady=6)

        # Conditions list: starts EMPTY on new rule so nothing is pre-filled
        conditions = []
        if edit_index is not None:
            if "conditions" in rule and isinstance(rule["conditions"], list) and len(rule["conditions"]):
                for c in rule["conditions"]:
                    conditions.append(dict(c))
            elif "metric" in rule and "threshold" in rule:
                conditions.append({
                    "metric": rule.get("metric", "RGB_sum_slope_30s"),
                    "operator": rule.get("operator", ">="),
                    "threshold": float(rule.get("threshold", 0.0))
                })

        tree_frame = ttk.Frame(lf_cond)
        tree_frame.pack(fill="both", expand=True, pady=(0, 6))

        cols = ("num", "metric", "op", "th")
        tree_c = ttk.Treeview(tree_frame, columns=cols, show="headings", height=4, selectmode="browse")
        tree_c.heading("num", text="№")
        tree_c.heading("metric", text="Метрика графика")
        tree_c.heading("op", text="Условие")
        tree_c.heading("th", text="Порог")

        tree_c.column("num", width=45, minwidth=35, anchor="center")
        tree_c.column("metric", width=360, minwidth=200, anchor="w")
        tree_c.column("op", width=100, minwidth=70, anchor="center")
        tree_c.column("th", width=120, minwidth=80, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree_c.yview)
        tree_c.configure(yscrollcommand=tree_scroll.set)
        tree_c.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        def _refresh_conditions_view():
            for it in tree_c.get_children():
                tree_c.delete(it)
            for idx, c in enumerate(conditions):
                tree_c.insert("", "end", iid=str(idx), values=(idx + 1, c.get("metric"), c.get("operator"), c.get("threshold")))

        _refresh_conditions_view()

        # Add condition row
        add_box = ttk.Frame(lf_cond)
        add_box.pack(fill="x", pady=(4, 2))

        ttk.Label(add_box, text="Метрика:").pack(side="left", padx=(0, 4))
        available_metrics = [
            "RGB_sum_slope_30s", "Transition_score", "Log10(B/R)", "Log10(B/G)",
            "RGB_sum", "R", "G", "B"
        ]
        for cg in getattr(self, '_custom_graphs', []):
            cg_name = str(cg.get("name", "")).strip()
            if cg_name and cg_name not in available_metrics:
                available_metrics.append(cg_name)
        for cv in getattr(self, '_custom_variables', []):
            cv_name = str(cv.get("name", "")).strip()
            if cv_name and cv_name not in available_metrics:
                available_metrics.append(cv_name)

        new_metric_var = tk.StringVar(value=available_metrics[0])
        cb_m = ttk.Combobox(add_box, textvariable=new_metric_var, values=available_metrics, state="readonly", width=22)
        cb_m.pack(side="left", padx=(0, 6))

        ttk.Label(add_box, text="Знак:").pack(side="left", padx=(0, 4))
        new_op_var = tk.StringVar(value=">=")
        cb_op = ttk.Combobox(add_box, textvariable=new_op_var, values=[">=", ">", "<=", "<", "=="], state="readonly", width=5)
        cb_op.pack(side="left", padx=(0, 6))

        ttk.Label(add_box, text="Порог:").pack(side="left", padx=(0, 4))
        new_th_var = tk.DoubleVar(value=2.0)
        sp_th = ttk.Spinbox(add_box, from_=-10000.0, to=10000.0, increment=0.1, textvariable=new_th_var, width=8)
        sp_th.pack(side="left", padx=(0, 8))

        def _do_add_cond():
            try:
                th_v = float(new_th_var.get())
            except Exception:
                th_v = 0.0
            conditions.append({
                "metric": new_metric_var.get(),
                "operator": new_op_var.get(),
                "threshold": th_v
            })
            _refresh_conditions_view()

        def _do_edit_cond():
            sel = tree_c.selection()
            if not sel:
                messagebox.showinfo("Параметры", "Выберите параметр из списка для изменения", parent=dlg)
                return
            idx = int(sel[0])
            try:
                th_v = float(new_th_var.get())
            except Exception:
                th_v = 0.0
            if 0 <= idx < len(conditions):
                conditions[idx] = {
                    "metric": new_metric_var.get(),
                    "operator": new_op_var.get(),
                    "threshold": th_v
                }
                _refresh_conditions_view()
                tree_c.selection_set(str(idx))

        def _do_del_cond():
            sel = tree_c.selection()
            if not sel:
                return
            idx = int(sel[0])
            if 0 <= idx < len(conditions):
                del conditions[idx]
                _refresh_conditions_view()

        def _on_cond_select(event=None):
            sel = tree_c.selection()
            if sel:
                idx = int(sel[0])
                if 0 <= idx < len(conditions):
                    c = conditions[idx]
                    m_val = c.get("metric", "")
                    if m_val in available_metrics:
                        new_metric_var.set(m_val)
                    op_val = c.get("operator", ">=")
                    if op_val in [">=", ">", "<=", "<", "=="]:
                        new_op_var.set(op_val)
                    try:
                        new_th_var.set(float(c.get("threshold", 0.0)))
                    except Exception:
                        pass

        tree_c.bind("<<TreeviewSelect>>", _on_cond_select)
        tree_c.bind("<Double-1>", _on_cond_select)

        ttk.Button(add_box, text="➕ Добавить параметр", command=_do_add_cond).pack(side="left", padx=(0, 6))
        ttk.Button(add_box, text="✏️ Изменить параметр", command=_do_edit_cond).pack(side="left", padx=(0, 6))
        ttk.Button(add_box, text="🗑️ Удалить параметр", command=_do_del_cond).pack(side="left", padx=2)

        # 3. Time Window (Dropdown Unit Selector matching screenshot)
        lf_time = ttk.LabelFrame(frm, text=" ⏱️ Временной диапазон срабатывания ", padding=10)
        lf_time.pack(fill="x", pady=6)

        raw_t_min = float(rule.get("t_min_sec", 0.0))
        raw_t_max = float(rule.get("t_max_sec", 0.0))

        # Dropdown unit combobox
        unit_var = tk.StringVar(value="мин")
        t_min_var = tk.DoubleVar(value=round(raw_t_min / 60.0, 2))
        t_max_var = tk.DoubleVar(value=round(raw_t_max / 60.0, 2))

        r_time = ttk.Frame(lf_time)
        r_time.pack(fill="x")

        ttk.Label(r_time, text="Диапазон времени: от").pack(side="left", padx=(0, 4))
        ttk.Spinbox(r_time, from_=0.0, to=100000.0, increment=0.5, textvariable=t_min_var, width=7).pack(side="left", padx=(0, 4))

        ttk.Label(r_time, text="до").pack(side="left", padx=4)
        ttk.Spinbox(r_time, from_=0.0, to=100000.0, increment=0.5, textvariable=t_max_var, width=7).pack(side="left", padx=(0, 6))

        unit_combo = ttk.Combobox(r_time, textvariable=unit_var, values=["мин", "сек"], width=5, state="readonly")
        unit_combo.pack(side="left", padx=(0, 8))

        def _on_time_combo_change(event=None):
            u = unit_var.get()
            cur_min = t_min_var.get()
            cur_max = t_max_var.get()
            prev_u = getattr(unit_combo, '_last_u', 'мин')
            if u == prev_u:
                return
            if u == "сек" and prev_u == "мин":
                t_min_var.set(round(cur_min * 60.0, 1))
                if cur_max > 0:
                    t_max_var.set(round(cur_max * 60.0, 1))
            elif u == "мин" and prev_u == "сек":
                t_min_var.set(round(cur_min / 60.0, 2))
                if cur_max > 0:
                    t_max_var.set(round(cur_max / 60.0, 2))
            unit_combo._last_u = u

        unit_combo.bind("<<ComboboxSelected>>", _on_time_combo_change)
        unit_combo._last_u = "мин"

        ttk.Label(r_time, text="(0 = до конца анализа)", font=("Segoe UI", 8, "italic")).pack(side="left")

        # 3.1. Holdoff / Cooldown group (Защита от дублей)
        lf_cooldown = ttk.LabelFrame(frm, text=" ⏳ Защита от дублирования автометок (Holdoff / Cooldown) ", padding=10)
        lf_cooldown.pack(fill="x", pady=6)

        cooldown_enabled_var = tk.BooleanVar(value=bool(rule.get("cooldown_enabled", True)))
        raw_cooldown_sec = float(rule.get("cooldown_sec", 30.0))
        cool_u = "мин" if raw_cooldown_sec >= 60.0 and raw_cooldown_sec % 60 == 0 else "сек"
        cool_val = raw_cooldown_sec / 60.0 if cool_u == "мин" else raw_cooldown_sec
        cooldown_unit_var = tk.StringVar(value=cool_u)
        cooldown_val_var = tk.DoubleVar(value=round(cool_val, 2))

        r_cool = ttk.Frame(lf_cooldown)
        r_cool.pack(fill="x")
        ttk.Checkbutton(
            r_cool,
            text="Защита от дублей: не срабатывать повторно в течение:",
            variable=cooldown_enabled_var
        ).pack(side="left", padx=(0, 8))

        ttk.Spinbox(r_cool, from_=0.5, to=3600.0, increment=5.0, textvariable=cooldown_val_var, width=7).pack(side="left", padx=(0, 4))
        cooldown_unit_combo = ttk.Combobox(r_cool, textvariable=cooldown_unit_var, values=["сек", "мин"], width=5, state="readonly")
        cooldown_unit_combo.pack(side="left", padx=(0, 6))

        def _on_cool_unit_change(event=None):
            u = cooldown_unit_var.get()
            val = cooldown_val_var.get()
            prev_u = getattr(cooldown_unit_combo, '_last_u', 'сек')
            if u == prev_u:
                return
            if u == "мин" and prev_u == "сек":
                cooldown_val_var.set(round(val / 60.0, 2))
            elif u == "сек" and prev_u == "мин":
                cooldown_val_var.set(round(val * 60.0, 1))
            cooldown_unit_combo._last_u = u

        cooldown_unit_combo.bind("<<ComboboxSelected>>", _on_cool_unit_change)
        cooldown_unit_combo._last_u = cool_u

        # 4. Sound & Notification
        r_alert = ttk.Frame(frm)
        r_alert.pack(fill="x", pady=4)
        sound_var = tk.BooleanVar(value=bool(rule.get("sound", True)))
        notify_var = tk.BooleanVar(value=bool(rule.get("notify", True)))
        ttk.Checkbutton(r_alert, text="🔊 Системный звук при срабатывании", variable=sound_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(r_alert, text="🔔 Всплывающее уведомление (Toast)", variable=notify_var).pack(side="left")

        # 5. Buttons
        btn_bar = ttk.Frame(frm)
        btn_bar.pack(fill="x", pady=(12, 0))

        def _save_rule():
            if not len(conditions):
                messagebox.showerror("Ошибка", "Добавьте хотя бы одно условие срабатывания перед сохранением.", parent=dlg)
                return
            name = name_var.get().strip() or "Автометка"

            u = unit_var.get()
            factor = 60.0 if u == "мин" else 1.0
            t_min_sec = max(0.0, float(t_min_var.get()) * factor)
            t_max_val = float(t_max_var.get())
            t_max_sec = 0.0 if t_max_val <= 0 else t_max_val * factor

            cool_factor = 60.0 if cooldown_unit_var.get() == "мин" else 1.0
            cooldown_sec = max(0.0, float(cooldown_val_var.get()) * cool_factor)

            first_c = conditions[0]
            new_rule = {
                "enabled": True if edit_index is None else bool(rule.get("enabled", True)),
                "name": name,
                "description": name,
                "metric": first_c.get("metric"),
                "operator": first_c.get("operator"),
                "threshold": float(first_c.get("threshold", 0.0)),
                "conditions": list(conditions),
                "t_min_sec": t_min_sec,
                "t_max_sec": t_max_sec,
                "cooldown_enabled": bool(cooldown_enabled_var.get()),
                "cooldown_sec": cooldown_sec,
                "color": color_var.get().strip() or get_palette(bool(self.config.get("light_theme", False)))["success"],
                "sound": bool(sound_var.get()),
                "notify": bool(notify_var.get()),
            }
            if edit_index is not None and 0 <= edit_index < len(self._custom_auto_marks):
                self._custom_auto_marks[edit_index] = new_rule
            else:
                self._custom_auto_marks.append(new_rule)
            self._refresh_custom_auto_marks_list()
            dlg.destroy()

        ttk.Button(btn_bar, text="Отмена", command=dlg.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_bar, text="💾 Сохранить автометку", command=_save_rule).pack(side="right")

    # =========================================================================
    # КОНСТРУКТОР ПЕРЕМЕННЫХ И ГРАФИКОВ (Вариант 2)
    # =========================================================================
    def _refresh_custom_var_list(self):
        if not hasattr(self, 'custom_var_list'):
            return
        self.custom_var_list.delete(0, tk.END)
        for v in self._custom_variables:
            self.custom_var_list.insert(tk.END, f"  🔹 {v.get('name', 'VAR')} = {v.get('formula', '')}")

    def _add_custom_variable(self):
        name = self.var_name_input.get().strip()
        formula = self.var_formula_input.get().strip()
        if not name or not formula:
            messagebox.showwarning("Переменные", "Укажите имя переменной и формулу.", parent=self.win)
            return
        if not name.isidentifier():
            messagebox.showerror("Ошибка", f"Имя переменной «{name}» некорректно. Используйте буквы латиницы и цифры (например: TOTAL_RGB, NORM_B).", parent=self.win)
            return
        self._custom_variables.append({"name": name, "formula": formula})
        self._refresh_custom_var_list()

    def _remove_custom_variable(self):
        sel = self.custom_var_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._custom_variables):
            self._custom_variables.pop(idx)
            self._refresh_custom_var_list()

    def _refresh_custom_graph_list(self):
        if not hasattr(self, 'custom_graph_list'):
            return
        self.custom_graph_list.delete(0, tk.END)
        for g in self._custom_graphs:
            self.custom_graph_list.insert(tk.END, f"  📈 {g.get('name', 'График')}: {g.get('formula', '')} [{g.get('color', get_palette(bool(self.config.get('light_theme', False)))['accent'])}]")

    def _add_custom_graph(self):
        name = self.custom_name_var.get().strip()
        formula = self.custom_formula_var.get().strip()
        color = self.custom_color_var.get().strip() or get_palette(bool(self.config.get("light_theme", False)))["accent"]
        if not name or not formula:
            messagebox.showwarning("Графики", "Укажите название и формулу графика.", parent=self.win)
            return
        self._custom_graphs.append({"name": name, "formula": formula, "color": color})
        self._refresh_custom_graph_list()

    def _remove_custom_graph(self):
        sel = self.custom_graph_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._custom_graphs):
            self._custom_graphs.pop(idx)
            self._refresh_custom_graph_list()

    def _open_formulas_help_dialog(self):
        dlg = tk.Toplevel(self.win)
        dlg.title("❓ Справочник переменных, функций и формул")
        dlg.geometry("740x600")
        dlg.minsize(680, 520)
        dlg.transient(self.win)
        dlg.grab_set()

        light = bool(self.config.get("light_theme", False))
        colors = get_palette(light)
        bg = colors['background']
        panel = colors['surface']
        fg = colors['text']
        dlg.configure(bg=bg)

        outer = ttk.Frame(dlg, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="📚 Инструкция по созданию формул и графиков", font=("Segoe UI", 13, "bold"), foreground=get_palette(light)["accent"]).pack(anchor="w", pady=(0, 8))

        txt = tk.Text(outer, wrap="word", bg=panel, fg=fg, font=("Segoe UI", 9), relief="solid", borderwidth=1, padx=12, pady=10)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)

        scroll.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        help_content = """1. ВСТРОЕННЫЕ БАЗОВЫЕ ПЕРЕМЕННЫЕ
----------------------------------------------------------------------
Каналы цвета:
  • r (или R)               — интенсивность красного канала (0..255)
  • g (или G)               — интенсивность зелёного канала (0..255)
  • b (или B)               — интенсивность синего канала (0..255)
  • rgb_sum                 — суммарная интенсивность (r + g + b)

Логарифмические отношения:
  • log_br                  — десятичный логарифм Log10(B / R)
  • log_bg                  — десятичный логарифм Log10(B / G)

Скорости и детекторы:
  • slope30                 — скорость изменения RGB_sum за 30 секунд (наклон кривой)
  • transition_score        — комбинированный индекс перехода (Transition Score 0..10)
  • t                       — время анализа от старта в секундах


2. ПОЛЬЗОВАТЕЛЬСКИЕ ПЕРЕМЕННЫЕ (Блок 1)
----------------------------------------------------------------------
Вы можете объявить свои промежуточные переменные, чтобы не дублировать длинные выражения.
Примеры:
  • TOTAL_INT = r + g + b
  • NORM_BLUE = b / (TOTAL_INT + 1e-5)
  • DELTA_LOG = log_br - log_bg


3. ДОСТУПНЫЕ МАТЕМАТИЧЕСКИЕ ФУНКЦИИ
----------------------------------------------------------------------
  • log10(x)                — десятичный логарифм
  • sqrt(x)                 — квадратный корень
  • exp(x)                  — экспонента e^x
  • abs(x)                  — абсолютное значение (модуль)
  • min(x, y), max(x, y)    — минимум / максимум
  • mean(x)                 — среднее значение
  • diff(x)                 — первая производная (градиент)
  • sin(x), cos(x)          — тригонометрические функции
  • np.*                    — любые функции NumPy (np.gradient, np.std, np.clip)


4. ПРАКТИЧЕСКИЕ ПРИМЕРЫ ГОТОВЫХ ФОРМУЛ
----------------------------------------------------------------------
1. Процентная доля синего цвета (Blue %):
   (b / (r + g + b + 1e-5)) * 100

2. Отношение синего к красному:
   b / (r + 1e-5)

3. Разность логарифмов (Log difference):
   log_br - log_bg

4. Взвешенная оптическая яркость (Luma):
   0.299 * r + 0.587 * g + 0.114 * b

5. Индекс хроматического контраста:
   (r - b) / (r + b + 1e-5)

6. Нормализованный синий сигнал (Z-score):
   (b - mean(b)) / (np.std(b) + 1e-5)

7. Сглаженная разность каналов:
   abs(r - g) + abs(g - b)
"""
        txt.insert("1.0", help_content)
        txt.configure(state="disabled")

    def _apply(self):
        self._ensure_one_graph_setting()

        arom_u = self.arom_unit_var.get()
        arom_t_min_sec = float(self.arom_t_min_var.get()) * (60.0 if arom_u == "мин" else 1.0)
        arom_t_max_sec = float(self.arom_t_max_var.get()) * (60.0 if arom_u == "мин" else 1.0)

        br_u = self.br_unit_var.get()
        br_delay_sec = float(self.br_delay_var.get()) * (60.0 if br_u == "мин" else 1.0)
        br_t_max_sec = float(self.br_t_max_var.get()) * (60.0 if br_u == "мин" else 1.0)

        abr_u = self.abr_unit_var.get()
        abr_delay_sec = float(self.abr_delay_var.get()) * (60.0 if abr_u == "мин" else 1.0)
        abr_t_max_sec = float(self.abr_t_max_var.get()) * (60.0 if abr_u == "мин" else 1.0)

        seek_s = 5
        try:
            seek_s = int(str(self.seek_step_var.get()).replace("сек", "").strip())
        except Exception:
            seek_s = 5

        values = {
            "performance_profile": self.profile_var.get(),
            "display_max_width": int(self.display_max_width_var.get()),
            **{key: var.get() for key, var in self.perf_vars.items()},
            **{key: var.get() for key, var in self.graph_vars.items()},
            **{key: var.get() for key, var in self.video_vars.items()},
            **{key: var.get() for key, var in self.roi_vars.items()},
            **{key: var.get() for key, var in self.notification_vars.items()},
            **{key: var.get() for key, var in getattr(self, "detector_vars", {}).items()},
            "detector_compare_mode": self.compare_mode_var.get() if hasattr(self, 'compare_mode_var') else "split",
            "detector_split_pos": int(self.compare_split_pos_var.get()) if hasattr(self, 'compare_split_pos_var') else 50,
            "auto_mark_arom_unit": arom_u,
            "auto_mark_arom_t_min_sec": arom_t_min_sec,
            "auto_mark_arom_t_max_sec": arom_t_max_sec,
            "auto_mark_br_unit": br_u,
            "auto_mark_br_arm_delay_sec": br_delay_sec,
            "auto_mark_br_t_min_sec": 0.0,
            "auto_mark_br_t_max_sec": br_t_max_sec,
            "auto_mark_abr_unit": abr_u,
            "auto_mark_abr_arm_delay_sec": abr_delay_sec,
            "auto_mark_abr_t_min_sec": 0.0,
            "auto_mark_abr_t_max_sec": abr_t_max_sec,
            "playback_speed": float(self.playback_speed_var.get().replace("x", "")),
            "seek_step_sec": seek_s,
            "light_theme": bool(self.config.get("light_theme", False)),
            "custom_variables": list(getattr(self, "_custom_variables", [])),
            "custom_graphs": list(getattr(self, "_custom_graphs", [])),
            "custom_auto_marks": list(getattr(self, "_custom_auto_marks", [])),
            "active_detector_preset_id": (
                self._applied_detector_preset_id or self.config.get("active_detector_preset_id")
            ),
            "player_hud_metrics": list(self.config.get("player_hud_metrics", DEFAULT_PLAYER_HUD_METRICS)),
        }
        self.config.update(values)
        if not self._legacy_preset_compat:
            self.config.pop("detector_presets", None)
        if self._pending_default_preset_id:
            try:
                self.project_store.set_default_preset("detector", self._pending_default_preset_id)
            except Exception as e:
                messagebox.showwarning("Пресеты", f"Не удалось назначить пресет по умолчанию:\n{e}", parent=self.win)
        try:
            save_settings(values)
        except Exception as e:
            messagebox.showwarning("Настройки", f"Не удалось сохранить настройки:\n{e}", parent=self.win)

        # Apply settings to active MiiCam camera on Save & Apply
        if self.current_cap and hasattr(self.current_cap, 'is_miicam') and self.current_cap.is_miicam and hasattr(self.current_cap, 'apply_settings_dict'):
            try:
                self.current_cap.apply_settings_dict(values)
            except Exception as e:
                print(f"⚠️ Ошибка применения настроек сенсора: {e}")

        if self.on_apply:
            try:
                self.on_apply()
            except Exception:
                pass
        self._on_close()
