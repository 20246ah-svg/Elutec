import os

RGB_Y_MIN = 0
RGB_Y_MAX = 300
LOG_Y_MARGIN_FRAC = 0.08

                                                        
ELUTEK_LIGHT_BG = "#ECEFED"
ELUTEK_200 = "#D1D9D2"
ELUTEK_300 = "#82929B"
ELUTEK_BRAND = "#D8F26A"
ELUTEK_600 = "#E4FB83"
ELUTEK_INK = "#090D11"
ELUTEK_VOID = "#080D11"
ELUTEK_PANEL_DARK = "#0E1419"
ELUTEK_CARD_DARK = "#131C23"
ELUTEK_ACCENT = "#D8F26A"
ELUTEK_SUCCESS = "#B9DC6D"
ELUTEK_DANGER = "#FF7774"

                                             
CSV_FLUSH_INTERVAL_SEC = 2.0
CSV_FLUSH_ROWS = 200

                                                              
RATE_WINDOW_MS = 5000.0
DELTA_FAST_MS = 1000.0
DELTA_MID_MS = 3000.0
RATE_MIN_POINTS = 5
EMA_FAST_TAU_MS = 1000.0
EMA_SLOW_TAU_MS = 8000.0

                                                                      
RGB_SUM_SMOOTH_WINDOW_MS = 10000.0
RGB_SUM_SLOPE_FAST_MS = 10000.0
RGB_SUM_SLOPE_SLOW_MS = 30000.0
RGB_SUM_SLOPE_MIN_POINTS = 10
TRANSITION_ALERT_CONFIRM_MS = 5000.0
TRANSITION_ALERTS_ENABLED = True

                                        
RGB_VECTOR_WINDOW_MS = 30000.0
CHROMATICITY_WINDOW_MS = 30000.0
LOG_RATIO_WINDOW_MS = 30000.0
RGB_SUM_ACCEL_WINDOW_MS = 30000.0
CHROM_BASELINE_LOOKBACK_MS = 90000.0
CHROM_BASELINE_GAP_MS = 30000.0
CHROM_BASELINE_MIN_POINTS = 10

                                  
TRANSITION_NOISE_RGB_VECTOR = 0.51
TRANSITION_NOISE_CHROM_SPEED = 0.0016
TRANSITION_NOISE_RGB_SUM_SLOPE = 0.44
TRANSITION_NOISE_K_CHROM = 0.075
TRANSITION_NOISE_LOG_RATIO_SPEED = 0.064
TRANSITION_Z_CAP = 10.0

                                                                          
# Отображать панель «ХОД АНАЛИЗА» сразу со старта
TRANSITION_STATUS_SHOW_AFTER_MS = 0.0
TRANSITION_ARM_DELAY_MS = 5 * 60 * 1000.0
TRANSITION_ALERT_DISPLAY_MS = 2 * 60 * 1000
TRANSITION_MIN_RGB_SUM = 10.0

                
AROM_SLOPE_STANDARD = 1.0
AROM_SLOPE_STRONG = 2.5
AROM_SCORE_STANDARD = 3.0
AROM_SCORE_STRONG = 4.0
AROM_T_MIN_SEC = 0.0
AROM_T_MAX_SEC = 600.0

              
BR_SLOPE_THRESHOLD = 3.5
BR_SCORE_THRESHOLD = 3.0
BR_CONFIRM_MS = 3000.0
BR_ARM_DELAY_SEC = 300.0
BR_T_MIN_SEC = 0.0
BR_T_MAX_SEC = 1800.0

               
ABR_SLOPE_THRESHOLD = -1.0
ABR_SCORE_THRESHOLD = 2.5
ABR_CONFIRM_MS = 3000.0
ABR_STRONG_SLOPE_THRESHOLD = -2.5
ABR_STRONG_SCORE_THRESHOLD = 3.0
ABR_STRONG_CONFIRM_MS = 1000.0
ABR_ARM_DELAY_SEC = 300.0
ABR_T_MIN_SEC = 0.0
ABR_T_MAX_SEC = 3600.0

# Автометки: задержка повторного срабатывания (Holdoff / Cooldown) по умолчанию
DEFAULT_AUTO_MARK_COOLDOWN_SEC = 30.0

# Метрики для отображения в HUD сноске видеоплеера по умолчанию
DEFAULT_PLAYER_HUD_METRICS = [
    "RGB_sum",
    "RGB_sum_slope_30s",
    "Transition_score",
    "Log10(B/R)"
]

# Именованные пресеты RGB-детектора (MiiCam / ToupCam)
DEFAULT_DETECTOR_PRESETS = {
    "По умолчанию (Default)": {
        "miicam_auto_exposure": False,
        "miicam_exposure_us": 22000,
        "miicam_gain": 100,
        "miicam_brightness": 0,
        "miicam_contrast": 0,
        "miicam_gamma": 100,
        "miicam_hue": 0,
        "miicam_saturation": 128,
        "miicam_temp": 6500,
        "miicam_tint": 1000,
        "miicam_wb_r": 0,
        "miicam_wb_g": 0,
        "miicam_wb_b": 0,
        "miicam_speed": 2,
        "miicam_binning": 1,
        "miicam_frame_preload": False,
        "miicam_thread_priority": 2,
        "miicam_h_flip": False,
        "miicam_v_flip": False,
        "miicam_anti_flicker": 1,
        # Узлы ISP камеры (значения = заводские по SDK, поведение «по умолчанию» не меняется)
        "miicam_color_matrix": True,
        "miicam_wb_gain_enable": True,
        "miicam_tone_curve": 2,
        "miicam_linear_tone": 1,
        "miicam_sharpening": 0,
        "miicam_demosaic": 0,
        "miicam_clean_frame": False,
    },
}

# Пресет «Чистый кадр»: нейтральный ISP + полностью зафиксированная экспозиция.
# Идея: на одинаковый образец в одинаковом свете камера всегда выдаёт одни и те же
# числа, и в них нет «улучшайзеров» (матрица, баланс белого, кривая, резкость).
CLEAN_FRAME_PRESET_NAME = "Чистый кадр (Clean Frame)"
CLEAN_FRAME_PRESET = {
    # --- экспозиция: всё фиксировано, автоматики нет ---
    "miicam_auto_exposure": False,
    "miicam_exposure_us": 20000,      # кратно 10 мс: нет биений при свете от сети 50 Гц
    "miicam_gain": 100,               # минимальное аналоговое усиление (×1), минимум шума
    # --- нейтральные пользовательские коррекции ---
    "miicam_brightness": 0,
    "miicam_contrast": 0,
    "miicam_gamma": 100,
    "miicam_hue": 0,
    "miicam_saturation": 128,
    # --- баланс белого: никаких поправок внутри камеры ---
    "miicam_temp": 6500,
    "miicam_tint": 1000,
    "miicam_wb_r": 0,
    "miicam_wb_g": 0,
    "miicam_wb_b": 0,
    "miicam_wb_gain_enable": False,   # WBGAIN=0: встроенный баланс белого выключен
    # --- узлы ISP, которые «улучшают» картинку ---
    "miicam_color_matrix": False,     # COLORMATIX=0: без цветовой матрицы производителя
    "miicam_tone_curve": 0,           # CURVE=0: без тон-кривой
    "miicam_linear_tone": 0,          # LINEAR=0: без линейного тон-маппинга
    "miicam_sharpening": 0,           # без резкости
    "miicam_demosaic": 0,             # билинейный демозаик: самый предсказуемый
    # --- канал связи и поток ---
    "miicam_speed": 2,
    "miicam_binning": 1,              # полное разрешение, без аппаратного биннинга
    "miicam_frame_preload": False,
    "miicam_thread_priority": 2,
    "miicam_h_flip": False,
    "miicam_v_flip": False,
    "miicam_anti_flicker": 1,
    "miicam_clean_frame": True,       # включает отчёт и защиту от автоматики в обёртке
}

                                                                    

FFMPEG_PIPE_OUTPUT_FPS = 20
MAX_POINTS = 108000

# Настройки производительности по умолчанию.
PERFORMANCE_PROFILES = {
    "Турбо FPS (60-120 FPS)": {
        "analysis_interval_ms": 5,
        "graph_update_ms": 25,
        "max_points": 150000,
        "preview_interval_ms": 10,
        "preview_rgb_interval_ms": 50,
    },
    "Максимальная точность": {
        "analysis_interval_ms": 10,
        "graph_update_ms": 30,
        "max_points": 100000,
        "preview_interval_ms": 30,
        "preview_rgb_interval_ms": 100,
    },
    "Сбалансированный": {
        "analysis_interval_ms": 15,
        "graph_update_ms": 40,
        "max_points": 50000,
        "preview_interval_ms": 50,
        "preview_rgb_interval_ms": 200,
    },
    "Экономия ресурсов": {
        "analysis_interval_ms": 30,
        "graph_update_ms": 100,
        "max_points": 25000,
        "preview_interval_ms": 100,
        "preview_rgb_interval_ms": 500,
    },
    "Слабый ПК / Ноутбук": {
        "analysis_interval_ms": 50,
        "graph_update_ms": 200,
        "max_points": 10000,
        "preview_interval_ms": 150,
        "preview_rgb_interval_ms": 1000,
    },
}


                                                                                           
def get_default_save_folder():
    home = os.path.expanduser('~')
    candidates = [
        os.path.join(home, 'OneDrive', 'Desktop'),
        os.path.join(home, 'Desktop'),
        os.path.join(home, 'OneDrive', 'Документы'),
        os.path.join(home, 'Documents'),
        home,
    ]
    for path in candidates:
        if os.path.isdir(path) and os.access(path, os.W_OK):
            return path
    return home
