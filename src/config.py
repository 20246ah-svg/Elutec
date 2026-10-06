import os

RGB_Y_MIN = 0
RGB_Y_MAX = 300
LOG_Y_MARGIN_FRAC = 0.08

                                                        
ELUTEK_LIGHT_BG = "#F3F6F5"
ELUTEK_200 = "#DEE7E3"
ELUTEK_300 = "#9BAAA4"
ELUTEK_BRAND = "#1E7569"
ELUTEK_600 = "#185E55"
ELUTEK_INK = "#121A17"
ELUTEK_VOID = "#0F1714"
ELUTEK_PANEL_DARK = "#19231F"
ELUTEK_CARD_DARK = "#202C27"
ELUTEK_ACCENT = "#76BBAE"
ELUTEK_SUCCESS = "#83C6A7"
ELUTEK_DANGER = "#D08084"

                                             
CSV_FLUSH_INTERVAL_SEC = 2.0
CSV_FLUSH_ROWS = 200

                                                              
RATE_WINDOW_MS = 5000.0
RATE_SLOW_WINDOW_MS = 10000.0
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

# Настройки ROI и видео по умолчанию
DEFAULT_RECORD_VIDEO = True
DEFAULT_SAVE_ROI_ON_VIDEO = False
DEFAULT_SNAP_ROI_GREEN_CIRCLE_ON_FILE = True
DEFAULT_RECORD_CLEAN_VIDEO = True
DEFAULT_AUTO_LOAD_VIDEO_ROI = True
DEFAULT_ROI_DISPLAY_MODE = "full"

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
    },
}

                                                                    
LOW_LATENCY_FFMPEG_OPTIONS = (
    "rtsp_transport;tcp|"
    "fflags;nobuffer|"
    "flags;low_delay|"
    "max_delay;0|"
    "probesize;32|"
    "analyzeduration;0"
)

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

DEFAULT_PERFORMANCE_PROFILE = "Сбалансированный"
DEFAULT_ANALYSIS_INTERVAL_MS = 15
DEFAULT_GRAPH_UPDATE_MS = 120
DEFAULT_PREVIEW_INTERVAL_MS = 50
DEFAULT_PREVIEW_RGB_INTERVAL_MS = 200
DEFAULT_DISPLAY_MAX_WIDTH = 1280
DEFAULT_PLAYBACK_SPEED = 1.0

                                                                                           
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
