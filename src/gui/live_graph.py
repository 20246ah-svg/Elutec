import time
import math
import traceback
import numpy as np

from ..analysis.annotations import AnnotationManager
from ..utils.math_utils import adaptive_log_y_range, nice_y_axis_ticks
from ..config import (
    RGB_Y_MIN,
    RGB_Y_MAX,
    ELUTEK_ACCENT,
    TRANSITION_ALERT_CONFIRM_MS,
    TRANSITION_ALERTS_ENABLED,
    TRANSITION_ALERT_DISPLAY_MS,
    TRANSITION_MIN_RGB_SUM,
    TRANSITION_STATUS_SHOW_AFTER_MS,
    AROM_SLOPE_STANDARD,
    AROM_SLOPE_STRONG,
    AROM_SCORE_STANDARD,
    AROM_SCORE_STRONG,
    AROM_T_MIN_SEC,
    AROM_T_MAX_SEC,
    BR_SLOPE_THRESHOLD,
    BR_SCORE_THRESHOLD,
    BR_CONFIRM_MS,
    BR_T_MIN_SEC,
    BR_T_MAX_SEC,
    ABR_SLOPE_THRESHOLD,
    ABR_SCORE_THRESHOLD,
    ABR_CONFIRM_MS,
    ABR_STRONG_SLOPE_THRESHOLD,
    ABR_STRONG_SCORE_THRESHOLD,
    ABR_STRONG_CONFIRM_MS,
    ABR_T_MIN_SEC,
    ABR_T_MAX_SEC,
    RGB_SUM_SLOPE_MIN_POINTS,
)
from .theme import get_palette


class LiveGraphWindow:
    RGB_Y_MIN = RGB_Y_MIN
    RGB_Y_MAX = RGB_Y_MAX

    def __init__(self, pg, QtWidgets, QtCore, QtGui, theme_mode="dark", custom_graphs=None, notification_settings=None, is_video_file=False):
        self.pg = pg
        self.QtWidgets = QtWidgets
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.theme_mode = theme_mode if theme_mode in ("dark", "light") else "dark"
        self._theme_colors = get_palette(self.theme_mode == 'light')
        self.custom_graph_defs = list(custom_graphs or [])
        self.custom_graphs = []
        self.is_video_file = bool(is_video_file)
        self._pending_playback_actions = []
        self._slider_is_down = False
        # Automatic transition notifications are configurable from the Tk settings
        # window. Keep a local copy so the detector is deterministic for one run.
        self.notification_settings = dict(notification_settings or {})
        self._custom_auto_mark_active = {}
        self._custom_auto_mark_last_fired = {}
        # QMainWindow owns the actual native window geometry.  LiveGraphWindow
        # is a controller, not a QWidget, so its old resizeEvent() methods were
        # never called.  Use a tiny QMainWindow subclass to forward real resize
        # events and keep the graph grid synchronized with maximize/fullscreen.
        owner = self
        class _GraphMainWindow(QtWidgets.QMainWindow):
            def resizeEvent(self, event):
                super().resizeEvent(event)
                try:
                    owner._schedule_graph_layout_rebuild()
                except Exception:
                    pass

            def showEvent(self, event):
                super().showEvent(event)
                try:
                    owner._schedule_graph_layout_rebuild()
                except Exception:
                    pass

        self.win = _GraphMainWindow()
        self.win.setWindowTitle("Элютек · Аналитическая сессия")
        self.win.setGeometry(100, 100, 1180, 820)
        self.win.setMinimumSize(520, 420)
        try:
            self.win.setFont(self.QtGui.QFont('Segoe UI', 9))
        except Exception:
            pass
        central = QtWidgets.QWidget()
        self.central_widget = central
        central.setMinimumSize(0, 0)
        self.win.setCentralWidget(central)
        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setSizeConstraint(self.QtWidgets.QLayout.SetNoConstraint)
        central.setLayout(self.layout)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(10)

        # Must be initialized before _build_custom_graphs(): custom graph
        # construction uses self.unit_mode for the X-axis label.
        self.unit_mode = 'MS'

        self.annotation_manager = AnnotationManager()
        self.annotation_lines = []
        self.log_annotation_lines = []
        self.log_bg_annotation_lines = []
        self.slope_annotation_lines = []
        self.score_annotation_lines = []
        self.custom_annotation_lines = []
        self.annotation_texts = []
        self.session_excel_path = None
        self._annotation_dialog_open = False
        self._menu_open_in_progress = False
        self._active_annotation_dialog = None
        self._pick_annotation_mode = False
        self._transition_alerts_triggered = set()
        self._transition_detection_stage = 'arom'
        self._transition_stage_started_ms = 0.0
        self._transition_condition_started_ms = None
        self._transition_condition_mode = None
        self._transition_event_times = {}
        self._transition_last_current_t = 0.0
        self._transition_last_slope = float('nan')

        # Data caches MUST exist before any custom graph is built.
        # Otherwise a saved/custom formula can be evaluated during window
        # construction before the normal analysis state is initialized.
        self._cached_xs = []
        self._cached_r = []
        self._cached_g = []
        self._cached_b = []
        self._cached_log = []
        self._cached_log_bg = []
        self._cached_rgb_sum = []
        self._cached_rgb_sum_smooth = []
        self._cached_rgb_sum_slope10 = []
        self._cached_rgb_sum_slope30 = []
        self._cached_rgb_vector_speed30 = []
        self._cached_chromaticity_speed30 = []
        self._cached_k_chrom_previous = []
        self._cached_log_ratio_speed30 = []
        self._cached_rgb_sum_acceleration30 = []
        self._cached_transition_score = []
        self._cached_tri_x = []
        self._cached_tri_y = []
        self._cached_pts = 0

        # Single source of truth for the horizontal time window.
        # QGridLayout/PlotWidget can auto-range a hidden/re-shown plot when
        # the grid changes. Keeping the shared X range outside the widgets
        # lets every layout rebuild restore the exact same time window.
        self._shared_x_range_display = None
        self._ignore_view_change = False

        try:
            central.setObjectName("ElutekCentral")
        except Exception:
            pass

        # Analysis controls are grouped into a quiet two-level toolbar so
        # channel, view and annotation actions remain easy to scan.
        self.btn_r = QtWidgets.QPushButton('R')
        self.btn_r.setCheckable(True)
        self.btn_r.setChecked(True)
        self.btn_g = QtWidgets.QPushButton('G')
        self.btn_g.setCheckable(True)
        self.btn_g.setChecked(True)
        self.btn_b = QtWidgets.QPushButton('B')
        self.btn_b.setCheckable(True)
        self.btn_b.setChecked(True)

        self.unit_btn = QtWidgets.QPushButton('ВРЕМЯ · МС')
        self.unit_btn.setCheckable(False)
        self.track_btn = QtWidgets.QPushButton('СЛЕДИТЬ')
        self.track_btn.setCheckable(True)
        self.track_btn.setChecked(True)
        self.track_btn.setToolTip('Автообзор графика. Ручное масштабирование переключает режим в Manual.')
        self.log_btn = QtWidgets.QPushButton('Log B/R · B/G')
        self.log_btn.setCheckable(True)
        self.log_btn.setChecked(True)
        self.refresh_btn = QtWidgets.QPushButton('Обновить')
        self.refresh_btn.setCheckable(False)
        self.refresh_btn.setToolTip('Перерисовать графики, не сбрасывая ручной масштаб в режиме Manual.')
        self.fs_btn = QtWidgets.QPushButton('На весь экран')
        self.fs_btn.setCheckable(True)

        self.stop_btn = QtWidgets.QPushButton('Остановить')
        self.stop_btn.setToolTip('Для безопасной остановки нажмите кнопку дважды. Данные сохраняются перед закрытием.')
        self.stop_btn.setObjectName('dangerButton')
        self.pts_label = QtWidgets.QLabel('Точки · 0')
        self.pts_label.setMinimumWidth(78)
        self.pts_label.setAlignment(self.QtCore.Qt.AlignCenter)
        self.pts_label.setObjectName('pointsBadge')
        self.graphs_btn = QtWidgets.QPushButton('Графики · 2×N')
        self.graphs_btn.setToolTip('Выбор отображаемых графиков и раскладки')
        self.graphs_btn.clicked.connect(self._open_graph_selector)

        self.ann_btn = QtWidgets.QPushButton('Добавить метку')
        self.ann_btn.setCheckable(False)
        self.ann_btn.setToolTip('Добавить метку в текущий момент времени (M — быстро, Shift+M — с описанием)')
        self.ann_btn.clicked.connect(lambda: self._safe_call(self._add_annotation_dialog))
        self.ann_pick_btn = QtWidgets.QPushButton('По точке')
        self.ann_pick_btn.setCheckable(True)
        self.ann_pick_btn.setToolTip('Включите режим и выберите точку на графике для метки')
        self.ann_pick_btn.toggled.connect(self._on_pick_mode_toggled)
        self.ann_list_btn = QtWidgets.QPushButton('Метки')
        self.ann_list_btn.setCheckable(False)
        self.ann_list_btn.clicked.connect(lambda: self._safe_call(self._show_annotations_list))
        self.ann_clear_btn = QtWidgets.QPushButton('Очистить')
        self.ann_clear_btn.setCheckable(False)
        self.ann_clear_btn.clicked.connect(lambda: self._safe_call(self._clear_annotations))

        toolbar_widgets = [
            self.btn_r, self.btn_g, self.btn_b, self.unit_btn, self.log_btn,
            self.track_btn, self.refresh_btn, self.fs_btn, self.ann_btn,
            self.ann_pick_btn, self.ann_list_btn, self.ann_clear_btn,
            self.stop_btn, self.pts_label, self.graphs_btn
        ]
        for widget in toolbar_widgets:
            try:
                widget.setMinimumWidth(0)
                widget.setMinimumHeight(31)
                widget.setSizePolicy(self.QtWidgets.QSizePolicy.Preferred, self.QtWidgets.QSizePolicy.Fixed)
            except Exception:
                pass

        toolbar = QtWidgets.QFrame()
        toolbar.setObjectName('toolbarPanel')
        toolbar_layout = QtWidgets.QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(9)

        toolbar_top = QtWidgets.QHBoxLayout()
        toolbar_top.setSpacing(9)
        brand_mark = QtWidgets.QLabel('E')
        brand_mark.setObjectName('toolbarBrandMark')
        brand_mark.setAlignment(self.QtCore.Qt.AlignCenter)
        brand_mark.setFixedSize(34, 34)
        toolbar_top.addWidget(brand_mark)
        title_stack = QtWidgets.QVBoxLayout()
        title_stack.setSpacing(1)
        graph_title = QtWidgets.QLabel('Аналитическая сессия')
        graph_title.setObjectName('toolbarTitle')
        graph_subtitle = QtWidgets.QLabel('RGB · SARA мониторинг')
        graph_subtitle.setObjectName('toolbarSubtitle')
        title_stack.addWidget(graph_title)
        title_stack.addWidget(graph_subtitle)
        toolbar_top.addLayout(title_stack)
        toolbar_top.addStretch(1)
        toolbar_top.addWidget(self.pts_label)
        toolbar_top.addWidget(self.graphs_btn)
        toolbar_top.addWidget(self.stop_btn)
        toolbar_layout.addLayout(toolbar_top)

        def make_tool_group(label):
            group = QtWidgets.QFrame()
            group.setObjectName('toolGroup')
            group_layout = QtWidgets.QHBoxLayout(group)
            group_layout.setContentsMargins(6, 5, 6, 5)
            group_layout.setSpacing(5)
            group_label = QtWidgets.QLabel(label)
            group_label.setObjectName('toolGroupLabel')
            group_layout.addWidget(group_label)
            return group, group_layout

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)
        channel_group, channel_layout = make_tool_group('КАНАЛЫ')
        for widget in (self.btn_r, self.btn_g, self.btn_b, self.log_btn):
            channel_layout.addWidget(widget)
        view_group, view_layout = make_tool_group('ВИД')
        for widget in (self.unit_btn, self.track_btn, self.refresh_btn, self.fs_btn):
            view_layout.addWidget(widget)
        mark_group, mark_layout = make_tool_group('МЕТКИ')
        for widget in (self.ann_btn, self.ann_pick_btn, self.ann_list_btn, self.ann_clear_btn):
            mark_layout.addWidget(widget)
        controls.addWidget(channel_group, 0)
        controls.addWidget(view_group, 0)
        controls.addWidget(mark_group, 1)
        toolbar_layout.addLayout(controls)
        self.layout.addWidget(toolbar)

        # Cursor coordinates appear here when the pointer is over a graph.
        self.cursor_hud = QtWidgets.QFrame()
        self.cursor_hud.setObjectName('cursorHud')
        self.cursor_hud.setFixedHeight(30)
        self.cursor_hud.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Fixed)
        hud_layout = QtWidgets.QHBoxLayout(self.cursor_hud)
        hud_layout.setContentsMargins(10, 0, 8, 0)
        hud_layout.setSpacing(10)
        self.cursor_hud_label = QtWidgets.QLabel('Наведите курсор на график, чтобы увидеть координаты времени и значения.')
        self.cursor_hud_label.setObjectName('cursorHudLabel')
        hud_layout.addWidget(self.cursor_hud_label)
        hud_layout.addStretch()
        self._apply_elutek_qss()
        self.layout.addWidget(self.cursor_hud)

        if self.is_video_file:
            player_bar = QtWidgets.QHBoxLayout()
            player_bar.setSpacing(8)

            self.player_play_btn = QtWidgets.QPushButton('⏸ ПАУЗА')
            self.player_play_btn.setMinimumHeight(32)
            self.player_play_btn.setToolTip('Приостановить / продолжить воспроизведение видео (Пробел)')
            self.player_play_btn.clicked.connect(self._on_player_toggle_pause)

            self.player_restart_btn = QtWidgets.QPushButton('⏮ В НАЧАЛО')
            self.player_restart_btn.setMinimumHeight(32)
            self.player_restart_btn.setToolTip('Перемотать видео на первый кадр (R)')
            self.player_restart_btn.clicked.connect(self._on_player_restart)

            self.player_back5_btn = QtWidgets.QPushButton('⏪ -5 сек')
            self.player_back5_btn.setMinimumHeight(32)
            self.player_back5_btn.setToolTip('Перемотать на 5 секунд назад (A или стрелка влево)')
            self.player_back5_btn.clicked.connect(lambda: self._on_player_seek_rel(-5.0))

            self.player_fwd5_btn = QtWidgets.QPushButton('⏩ +5 сек')
            self.player_fwd5_btn.setMinimumHeight(32)
            self.player_fwd5_btn.setToolTip('Перемотать на 5 секунд вперёд (D или стрелка вправо)')
            self.player_fwd5_btn.clicked.connect(lambda: self._on_player_seek_rel(5.0))

            self.player_speed_label = QtWidgets.QLabel('Скорость:')
            self.player_speed_combo = QtWidgets.QComboBox()
            self.player_speed_combo.setMinimumHeight(32)
            speeds = [('0.25x', 0.25), ('0.5x', 0.5), ('1.0x (Норма)', 1.0), ('1.5x', 1.5), ('2.0x', 2.0), ('4.0x', 4.0), ('8.0x', 8.0)]
            for s_name, s_val in speeds:
                self.player_speed_combo.addItem(s_name, s_val)
            self.player_speed_combo.setCurrentIndex(2)
            self.player_speed_combo.currentIndexChanged.connect(self._on_player_speed_changed)

            self.player_slider = QtWidgets.QSlider(self.QtCore.Qt.Horizontal)
            self.player_slider.setMinimum(0)
            self.player_slider.setMaximum(100)
            self.player_slider.setValue(0)
            self.player_slider.setToolTip('Таймлайн воспроизведения — перетаскивайте для быстрого перехода')
            self.player_slider.sliderPressed.connect(self._on_player_slider_pressed)
            self.player_slider.sliderReleased.connect(self._on_player_slider_released)

            self.player_time_label = QtWidgets.QLabel('⏱ 00:00 / 00:00')
            self.player_time_label.setMinimumWidth(160)

            for w in [self.player_play_btn, self.player_restart_btn, self.player_back5_btn, self.player_fwd5_btn,
                      self.player_speed_label, self.player_speed_combo, self.player_slider, self.player_time_label]:
                player_bar.addWidget(w)

            self.layout.addLayout(player_bar)

        # Flexible graph workspace: selected graphs can be shown in any combination.
        self.graph_scroll = self.QtWidgets.QScrollArea()
        self.graph_scroll.setObjectName('graphScroll')
        self.graph_scroll.setWidgetResizable(False)
        # The scroll area itself must follow the real window height.  The
        # graph host will fill that viewport when possible and become taller
        # only when scrolling is actually required.  Previously the scroll
        # area was fixed to its first calculated height, so maximizing the
        # window left the graphs at their old size.
        self.graph_scroll.setSizePolicy(
            self.QtWidgets.QSizePolicy.Expanding,
            self.QtWidgets.QSizePolicy.Expanding,
        )
        self.graph_scroll.setFrameShape(self.QtWidgets.QFrame.NoFrame)
        # Do not top-align a resizable graph host: with QScrollArea this can
        # leave the viewport larger than the host, producing the large empty
        # (and on some Windows themes white) area below the graphs.
        self.graph_scroll.setAlignment(self.QtCore.Qt.AlignTop | self.QtCore.Qt.AlignLeft)
        self.graph_scroll.setHorizontalScrollBarPolicy(self.QtCore.Qt.ScrollBarAlwaysOff)
        self.graph_host = self.QtWidgets.QWidget()
        self.graph_host.setObjectName('graphHost')
        self.graph_host.setSizePolicy(self.QtWidgets.QSizePolicy.Fixed, self.QtWidgets.QSizePolicy.Fixed)
        self.graph_host.setAttribute(self.QtCore.Qt.WA_StyledBackground, True)
        self.graph_layout = self.QtWidgets.QGridLayout(self.graph_host)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_layout.setSpacing(8)
        self.graph_scroll.setWidget(self.graph_host)
        self.layout.addWidget(self.graph_scroll, 1)

                             
        self.time_axis_rgb = pg.AxisItem(orientation='bottom')
        self.time_axis_rgb.tickStrings = self._format_time_ticks
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': self.time_axis_rgb})
        self.plot_widget.setMinimumSize(260, 100)
        self.plot_widget.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Expanding)
        self.plot = self.plot_widget.getPlotItem()
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel('left', 'Value')
        self.plot.setLabel('bottom', 'Time', units='MS')
        self.plot.setYRange(RGB_Y_MIN, RGB_Y_MAX)
        self.plot.setLimits(yMin=RGB_Y_MIN, yMax=RGB_Y_MAX)
        self.r_curve = self.plot.plot(pen=pg.mkPen(self._theme_colors['channel_r'], width=2))
        self.g_curve = self.plot.plot(pen=pg.mkPen(self._theme_colors['channel_g'], width=2))
        self.b_curve = self.plot.plot(pen=pg.mkPen(self._theme_colors['channel_b'], width=2))
        self._register_graph_widget('RGB', self.plot_widget)

                                  
        self.time_axis_rgb_sum_slope30 = pg.AxisItem(orientation='bottom')
        self.time_axis_rgb_sum_slope30.tickStrings = self._format_time_ticks
        self.rgb_sum_slope_plot_widget = pg.PlotWidget(axisItems={'bottom': self.time_axis_rgb_sum_slope30})
        self.rgb_sum_slope_plot_widget.setMinimumSize(260, 95)
        self.rgb_sum_slope_plot_widget.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Expanding)
        self.rgb_sum_slope_plot = self.rgb_sum_slope_plot_widget.getPlotItem()
        self.rgb_sum_slope_plot.setMouseEnabled(x=True, y=True)
        self.rgb_sum_slope_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rgb_sum_slope_plot.setTitle('RGB_sum_slope_30s')
        self.rgb_sum_slope_plot.setLabel('left', 'd(R+G+B)/dt')
        self.rgb_sum_slope_plot.setLabel('bottom', 'Time', units='MS')
        self._rgb_sum_slope30_y_min, self._rgb_sum_slope30_y_max = -2.0, 2.0
        self.rgb_sum_slope_curve = self.rgb_sum_slope_plot.plot(pen=pg.mkPen(self._theme_colors['success'], width=2.2))
        self.rgb_sum_slope_zero_line = self.pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(self._theme_colors['muted'], width=1))
        self.rgb_sum_slope_plot.addItem(self.rgb_sum_slope_zero_line)
        self._register_graph_widget('RGB_sum_slope_30s', self.rgb_sum_slope_plot_widget)
        # Direct range sync used

                                 
        self.time_axis_transition_score = pg.AxisItem(orientation='bottom')
        self.time_axis_transition_score.tickStrings = self._format_time_ticks
        self.transition_score_plot_widget = pg.PlotWidget(axisItems={'bottom': self.time_axis_transition_score})
        self.transition_score_plot_widget.setMinimumSize(260, 95)
        self.transition_score_plot_widget.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Expanding)
        self.transition_score_plot = self.transition_score_plot_widget.getPlotItem()
        self.transition_score_plot.setMouseEnabled(x=True, y=True)
        self.transition_score_plot.showGrid(x=True, y=True, alpha=0.3)
        self.transition_score_plot.setTitle('Transition_score')
        self.transition_score_plot.setLabel('left', 'score')
        self.transition_score_plot.setLabel('bottom', 'Time', units='MS')
        self._transition_score_y_min, self._transition_score_y_max = 0.0, 10.0
        self.transition_score_curve = self.transition_score_plot.plot(pen=pg.mkPen(self._theme_colors['warning'], width=2.2))
        self.transition_score_line_warn = self.pg.InfiniteLine(pos=3, angle=0, pen=pg.mkPen(self._theme_colors['muted'], width=1))
        self.transition_score_line_prob = self.pg.InfiniteLine(pos=5, angle=0, pen=pg.mkPen(self._theme_colors['warning'], width=1))
        self.transition_score_line_strong = self.pg.InfiniteLine(pos=8, angle=0, pen=pg.mkPen(self._theme_colors['danger'], width=1.5))
        self.transition_score_plot.addItem(self.transition_score_line_warn)
        self.transition_score_plot.addItem(self.transition_score_line_prob)
        self.transition_score_plot.addItem(self.transition_score_line_strong)
        self._register_graph_widget('Transition_score', self.transition_score_plot_widget)
        # Direct range sync used

                                         
        self.log_row = QtWidgets.QWidget()
        self.log_row_layout = QtWidgets.QHBoxLayout(self.log_row)
        self.log_row_layout.setContentsMargins(0, 0, 0, 0)
        self.log_row_layout.setSpacing(6)

        self.time_axis_log = pg.AxisItem(orientation='bottom')
        self.time_axis_log.tickStrings = self._format_time_ticks
        self.log_plot_widget = pg.PlotWidget(axisItems={'bottom': self.time_axis_log})
        self.log_plot_widget.setMinimumSize(220, 100)
        self.log_plot_widget.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Expanding)
        self.log_plot = self.log_plot_widget.getPlotItem()
        self.log_plot.setMouseEnabled(x=True, y=True)
        self.log_plot.showGrid(x=True, y=True, alpha=0.3)
        self.log_plot.setLabel('left', 'Log10(B/R)')
        self.log_plot.setLabel('bottom', 'Time', units='MS')
        self._log_br_y_min, self._log_br_y_max = -1.0, 1.0
        self.log_curve = self.log_plot.plot(pen=pg.mkPen(self._theme_colors['accent'], width=2.2))

        self.time_axis_log_bg = pg.AxisItem(orientation='bottom')
        self.time_axis_log_bg.tickStrings = self._format_time_ticks
        self.log_bg_plot_widget = pg.PlotWidget(axisItems={'bottom': self.time_axis_log_bg})
        self.log_bg_plot_widget.setMinimumSize(220, 100)
        self.log_bg_plot_widget.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Expanding)
        self.log_bg_plot = self.log_bg_plot_widget.getPlotItem()
        self.log_bg_plot.setMouseEnabled(x=True, y=True)
        self.log_bg_plot.showGrid(x=True, y=True, alpha=0.3)
        self.log_bg_plot.setLabel('left', 'Log10(B/G)')
        self.log_bg_plot.setLabel('bottom', 'Time', units='MS')
        self._log_bg_y_min, self._log_bg_y_max = -1.0, 1.0
        self.log_bg_curve = self.log_bg_plot.plot(pen=pg.mkPen(self._theme_colors['channel_b'], width=2.2))

        self._apply_log_y_ranges()
        self._register_graph_widget('Log10(B/R)', self.log_plot_widget, kind='log')
        self._register_graph_widget('Log10(B/G)', self.log_bg_plot_widget, kind='log')
        # Direct range sync used
        # Direct range sync used

                              
        # RGB triangle trajectory was removed from the UI; its derived
        # chromaticity metrics are still calculated internally.

        # Пользовательские графики: каждый график регистрируется отдельно,
        # чтобы его можно было независимо включать/выключать в селекторе.
        self._build_custom_graphs()

                                                                            
        self.rate_rgb_row = QtWidgets.QWidget()
        self.rate_rgb_layout = QtWidgets.QHBoxLayout(self.rate_rgb_row)
        self.rate_rgb_layout.setContentsMargins(0, 0, 0, 0)
        self.rate_rgb_layout.setSpacing(6)
        self.rate_b_plot_widget = pg.PlotWidget()
        self.rate_r_plot_widget = pg.PlotWidget()
        self.rate_g_plot_widget = pg.PlotWidget()
                                                                     
        self.rate_rgb_row.setVisible(False)

        self.rate_log_row = QtWidgets.QWidget()
        self.rate_log_layout = QtWidgets.QHBoxLayout(self.rate_log_row)
        self.rate_log_layout.setContentsMargins(0, 0, 0, 0)
        self.rate_log_layout.setSpacing(6)
        self.rate_log_plot_widget = pg.PlotWidget()
        self.rate_log_bg_plot_widget = pg.PlotWidget()
        self.rate_log_row.setVisible(False)

        self.fastslow_row = QtWidgets.QWidget()
        self.fastslow_layout = QtWidgets.QHBoxLayout(self.fastslow_row)
        self.fastslow_layout.setContentsMargins(0, 0, 0, 0)
        self.fastslow_layout.setSpacing(6)
        self.fastslow_log_plot_widget = pg.PlotWidget()
        self.fastslow_log_bg_plot_widget = pg.PlotWidget()
        self.fastslow_row.setVisible(False)

                                          
        self._init_transition_alert_overlay()

                            
        self.annotation_manager = AnnotationManager()
        self.annotation_lines = []
        self.log_annotation_lines = []
        self.log_bg_annotation_lines = []
        self.slope_annotation_lines = []
        self.annotation_texts = []
        self.session_excel_path = None
        self._annotation_dialog_open = False
        self._menu_open_in_progress = False
        self._active_annotation_dialog = None
        self._pick_annotation_mode = False
        self._transition_alerts_triggered = set()
        self._transition_detection_stage = 'arom'
        self._transition_stage_started_ms = 0.0
        self._transition_condition_started_ms = None
        self._transition_condition_mode = None
        self._transition_event_times = {}
        self._transition_last_current_t = 0.0
        self._transition_last_slope = float('nan')
        self._transition_last_score = float('nan')
        self._cached_tri_x = []
        self._cached_tri_y = []
        self._cached_pts = 0
        self.stop_requested = False
        self._stop_confirm_deadline = 0.0
        self._video_resize_request = None
        self._autoscroll = True
        self._ignore_view_change = False
        self.show_log = True

                              
        self.btn_r.toggled.connect(lambda checked: self._on_channel_toggle('r', checked))
        self.btn_g.toggled.connect(lambda checked: self._on_channel_toggle('g', checked))
        self.btn_b.toggled.connect(lambda checked: self._on_channel_toggle('b', checked))
        self.unit_btn.clicked.connect(self._cycle_unit)
        self.log_btn.toggled.connect(self._on_log_toggle)
        self.track_btn.toggled.connect(self._on_track_toggled)
        self.refresh_btn.clicked.connect(self._refresh_plot)
        self.fs_btn.clicked.connect(self._on_fullscreen)
        self.stop_btn.clicked.connect(lambda: self._safe_call(self._request_stop_analysis))
                         
        shortcut_m = QtWidgets.QShortcut(QtCore.Qt.Key_M, self.win)
        shortcut_m.activated.connect(self._add_annotation_current)
        shortcut_shift_m = QtWidgets.QShortcut(QtCore.Qt.Key_M | QtCore.Qt.ShiftModifier, self.win)
        shortcut_shift_m.activated.connect(self._add_annotation_dialog)
        shortcut_l = QtWidgets.QShortcut(QtCore.Qt.Key_L, self.win)
        shortcut_l.activated.connect(self._show_annotations_list)
        shortcut_t = QtWidgets.QShortcut(QtCore.Qt.Key_T, self.win)
        shortcut_t.activated.connect(lambda: self.track_btn.setChecked(not self.track_btn.isChecked()))
        shortcut_ctrl0 = QtWidgets.QShortcut(QtCore.Qt.ControlModifier | QtCore.Qt.Key_0, self.win)
        shortcut_ctrl0.activated.connect(lambda: self.track_btn.setChecked(True))

        # Горячие клавиши управления видео и ROI (работают даже когда фокус на окне графиков)
        shortcut_s = QtWidgets.QShortcut(QtCore.Qt.Key_S, self.win)
        shortcut_s.activated.connect(lambda: self._pending_playback_actions.append(('snap_roi', None)))
        shortcut_space = QtWidgets.QShortcut(QtCore.Qt.Key_Space, self.win)
        shortcut_space.activated.connect(lambda: self._pending_playback_actions.append(('toggle_pause', None)))
        shortcut_ret = QtWidgets.QShortcut(QtCore.Qt.Key_Return, self.win)
        shortcut_ret.activated.connect(lambda: self._pending_playback_actions.append(('start_analysis', None)))
        shortcut_ent = QtWidgets.QShortcut(QtCore.Qt.Key_Enter, self.win)
        shortcut_ent.activated.connect(lambda: self._pending_playback_actions.append(('start_analysis', None)))
        shortcut_r = QtWidgets.QShortcut(QtCore.Qt.Key_R, self.win)
        shortcut_r.activated.connect(lambda: self._pending_playback_actions.append(('reset', None)))

                                           
        self._plot_widgets_for_mouse = (
            self.plot_widget, self.log_plot_widget, self.log_bg_plot_widget,
            self.rgb_sum_slope_plot_widget, self.transition_score_plot_widget,
        )
        for widget in self._plot_widgets_for_mouse:
            try:
                widget.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
            except Exception:
                pass
            try:
                widget.setMenuEnabled(True)
            except Exception:
                pass
            try:
                widget.getPlotItem().setMenuEnabled(True)
            except Exception:
                pass

        for widget in self._plot_widgets_for_mouse:
            widget.scene().sigMouseClicked.connect(
                lambda evt, w=widget: self._on_plot_mouse_clicked(evt, w)
            )

        def _on_window_close(event):
            self.stop_requested = True
            event.accept()

        self.win.closeEvent = _on_window_close

        self._apply_theme()
        self.win.show()
        self.win.raise_()
        try:
            self.win.activateWindow()
        except Exception:
            pass

        # The first grid build happens during construction, before Qt has
        # assigned the real window/viewport geometry.  In that state the
        # scroll area's width/height can be 0 or only a sizeHint, so the
        # calculated grid is initially clipped/overlapped.  Grid changes work
        # later because they happen after the window is laid out.  Always run
        # a real geometry pass after the window is visible (and once more after
        # the first layout pass) so the initial state is identical to changing
        # the grid manually.
        try:
            self._schedule_graph_layout_rebuild(0)
            self.QtCore.QTimer.singleShot(50, self._rebuild_graph_layout)
        except Exception:
            pass

                                                  
    def _init_transition_alert_overlay(self):
        self.transition_alert_label = self.QtWidgets.QLabel(self.central_widget)
        self.transition_alert_label.setObjectName('transitionAlert')
        self.transition_alert_label.setAlignment(self.QtCore.Qt.AlignCenter)
        self.transition_alert_label.setWordWrap(True)
        self.transition_alert_label.setMinimumHeight(76)
        self.transition_alert_label.setCursor(self.QtCore.Qt.PointingHandCursor)
        self.transition_alert_label.setToolTip("Нажмите в любое место уведомления, чтобы закрыть его")
        self.transition_alert_label.setSizePolicy(
            self.QtWidgets.QSizePolicy.Expanding,
            self.QtWidgets.QSizePolicy.Fixed,
        )
        self.transition_alert_label.mousePressEvent = self._on_transition_alert_clicked
        self.transition_alert_label.hide()
        self.layout.insertWidget(1, self.transition_alert_label)

        self._transition_alert_hide_timer = self.QtCore.QTimer(self.win)
        self._transition_alert_hide_timer.setSingleShot(True)
        self._transition_alert_hide_timer.timeout.connect(
            self._hide_transition_alert_and_relayout
        )

        self.transition_status_panel = self.QtWidgets.QFrame(self.central_widget)
        self.transition_status_panel.setObjectName('transitionStatusPanel')
        status_layout = self.QtWidgets.QVBoxLayout(self.transition_status_panel)
        status_layout.setContentsMargins(14, 10, 14, 10)
        status_layout.setSpacing(3)

        self.transition_status_header = self.QtWidgets.QLabel('ХОД АНАЛИЗА')
        self.transition_status_header.setObjectName('transitionStatusHeader')
        status_layout.addWidget(self.transition_status_header)

        self.transition_status_lines = []
        for _ in range(4):
            line = self.QtWidgets.QLabel('')
            line.setObjectName('transitionStatusLine')
            line.setMinimumHeight(20)
            line.hide()
            status_layout.addWidget(line)
            self.transition_status_lines.append(line)

        self.transition_detector_status = self.QtWidgets.QLabel('')
        self.transition_detector_status.setObjectName('transitionStatusDetail')
        self.transition_detector_status.setWordWrap(True)
        status_layout.addWidget(self.transition_detector_status)

        self.transition_status_panel.setSizePolicy(
            self.QtWidgets.QSizePolicy.Expanding,
            self.QtWidgets.QSizePolicy.Fixed,
        )
        self.transition_status_panel.hide()
        self.layout.addWidget(self.transition_status_panel)

    def _hide_transition_alert_and_relayout(self):
        if not hasattr(self, 'transition_alert_label') or self.transition_alert_label is None:
            return
        self.transition_alert_label.hide()
        try:
            if hasattr(self, 'layout') and self.layout:
                self.layout.activate()
            if hasattr(self, 'central_widget') and self.central_widget:
                self.central_widget.updateGeometry()
        except Exception:
            pass
        try:
            self._schedule_graph_layout_rebuild(0)
            self._rebuild_graph_layout()
        except Exception:
            pass

    def _on_transition_alert_clicked(self, event=None):
        try:
            if hasattr(self, '_transition_alert_hide_timer') and self._transition_alert_hide_timer.isActive():
                self._transition_alert_hide_timer.stop()
            self._hide_transition_alert_and_relayout()
        except Exception as e:
            print(f'⚠️ Ошибка закрытия alert по клику: {e}')

                                                         
    def _attach_hover_tracker(self, name, widget):
        """Attach high-precision hover coordinate inspector (X time, Y value) to plot widget."""
        if widget is None:
            return
        try:
            view_box = widget.getPlotItem().getViewBox()
            scene = widget.scene()
            if hasattr(scene, 'sigMouseMoved'):
                def _on_mouse_moved(pos):
                    if not hasattr(self, 'cursor_hud_label') or not widget.isVisible():
                        return
                    try:
                        if hasattr(view_box, 'sceneBoundingRect') and view_box.sceneBoundingRect().contains(pos):
                            pt = view_box.mapSceneToView(pos)
                            x_val = float(pt.x())
                            y_val = float(pt.y())
                            t_sec = max(0.0, x_val)
                            mins = int(t_sec // 60)
                            secs = t_sec % 60
                            time_str = f"{mins:02d}:{secs:04.1f} ({t_sec:.2f} с)"

                            is_light = (getattr(self, 'theme_mode', 'dark') == 'light')
                            hover_colors = get_palette(is_light)
                            y_col = hover_colors['accent']
                            slope_col = hover_colors['success']
                            score_col = hover_colors['warning']

                            extra_info = ""
                            if name == 'RGB' and hasattr(self, 'time_history') and len(self.time_history):
                                th = np.array(self.time_history, dtype=float)
                                idx = np.searchsorted(th, x_val)
                                idx = max(0, min(len(th) - 1, idx))
                                if len(self.r_history) > idx and len(self.g_history) > idx and len(self.b_history) > idx:
                                    rv = float(self.r_history[idx])
                                    gv = float(self.g_history[idx])
                                    bv = float(self.b_history[idx])
                                    extra_info = (
                                        f" | <span style='color:{hover_colors['channel_r']};'>R:{rv:.1f}</span> "
                                        f"<span style='color:{hover_colors['channel_g']};'>G:{gv:.1f}</span> "
                                        f"<span style='color:{hover_colors['channel_b']};'>B:{bv:.1f}</span>"
                                    )
                            elif name == 'RGB_sum_slope_30s' and hasattr(self, 'slope30_history') and len(self.slope30_history):
                                th = np.array(self.time_history, dtype=float) if hasattr(self, 'time_history') else []
                                if len(th):
                                    idx = max(0, min(len(self.slope30_history) - 1, np.searchsorted(th, x_val)))
                                    sv = float(self.slope30_history[idx])
                                    extra_info = f" | <span style='color:{slope_col};'>Наклон: {sv:+.3f}/s</span>"
                            elif name == 'Transition_score' and hasattr(self, 'transition_score_history') and len(self.transition_score_history):
                                th = np.array(self.time_history, dtype=float) if hasattr(self, 'time_history') else []
                                if len(th):
                                    idx = max(0, min(len(self.transition_score_history) - 1, np.searchsorted(th, x_val)))
                                    sc = float(self.transition_score_history[idx])
                                    extra_info = f" | <span style='color:{score_col};'>Индекс: {sc:.2f}</span>"

                            self.cursor_hud_label.setText(
                                f"📍 <b>{name}</b> ➔ ⏱ <b>X:</b> {time_str} | 📈 <b>Y:</b> <span style='color:{y_col};'>{y_val:+.4f}</span>{extra_info}"
                            )
                    except Exception:
                        pass
                scene.sigMouseMoved.connect(_on_mouse_moved)
        except Exception:
            pass

    def _register_graph_widget(self, name, widget, kind='builtin'):
        if not hasattr(self, '_graph_items'):
            self._graph_items = []
        self._graph_items.append({'name': name, 'widget': widget, 'visible': True, 'kind': kind})
        self._graph_columns = getattr(self, '_graph_columns', 2)

        # Connect hover coordinate tracking on all curves
        self._attach_hover_tracker(name, widget)

        # Every registered graph must participate in manual X-range changes,
        # including custom graphs. Previously only built-in graphs were
        # connected, so a custom/full-width graph could become the outlier.
        try:
            view_box = widget.getPlotItem().getViewBox()
            if hasattr(view_box, 'sigRangeChangedManually'):
                view_box.sigRangeChangedManually.connect(
                    lambda _range, vb=view_box: self._on_manual_range_changed(vb)
                )
        except Exception:
            pass

    def _ensure_one_graph_visible(self, preferred_index=0):
        """Guarantee that the graph workspace never ends up completely empty.

        Visibility is a workspace-level setting, separate from the R/G/B curve
        toggles.  The RGB graph is the safe fallback because it is always
        available and does not depend on optional/custom graph data.
        """
        items = [
            item for item in getattr(self, '_graph_items', [])
            if item.get('widget') is not None
        ]
        if not items:
            return -1
        visible = [i for i, item in enumerate(items) if bool(item.get('visible', True))]
        if visible:
            return visible[0]
        try:
            preferred_index = int(preferred_index)
        except (TypeError, ValueError):
            preferred_index = 0
        preferred_index = max(0, min(preferred_index, len(items) - 1))
        # Prefer RGB when available; otherwise use the first registered graph.
        rgb_index = next((i for i, item in enumerate(items) if item.get('name') == 'RGB'), None)
        fallback = rgb_index if rgb_index is not None else preferred_index
        items[fallback]['visible'] = True
        return fallback

    def _set_graph_visibility(self, states):
        """Apply visibility states by graph name and enforce the non-empty rule."""
        items = getattr(self, '_graph_items', [])
        if isinstance(states, dict):
            for item in items:
                name = item.get('name')
                if name in states:
                    item['visible'] = bool(states[name])
        self._ensure_one_graph_visible()
        self._rebuild_graph_layout()

    def _schedule_graph_layout_rebuild(self, delay=0):
        if not hasattr(self, 'graph_scroll'):
            return
        try:
            timer = getattr(self, '_graph_layout_timer', None)
            if timer is None:
                timer = self.QtCore.QTimer(self.win)
                timer.setSingleShot(True)
                timer.timeout.connect(self._rebuild_graph_layout)
                self._graph_layout_timer = timer
            timer.start(max(0, int(delay)))
        except Exception:
            try:
                self.QtCore.QTimer.singleShot(max(0, int(delay)), self._rebuild_graph_layout)
            except Exception:
                pass

    def _rebuild_graph_layout(self):
        """Rebuild the grid from the *current* window/viewport geometry.

        The grid is responsive in both directions:
        - columns are controlled by the selected 1xN/2xN/3xN/4xN mode;
        - an incomplete last row distributes its widgets across the whole row;
        - row heights expand to fill the available viewport;
        - if the window is too small, the host becomes scrollable;
        - maximizing/fullscreen therefore immediately enlarges the plots.
        """
        if not hasattr(self, 'graph_layout'):
            return

        # Detach every previously managed plot from the grid *and hide it*
        # before rebuilding.  QGridLayout.takeAt() removes a widget from the
        # layout, but does not hide it.  If we re-parent the old widget to
        # graph_host here, an unchecked graph can remain as a free child at its
        # previous geometry and become a "ghost" plot on top of the new grid.
        # This was the main reason the selector could say that a graph was off
        # while the graph was still visible on screen.
        managed_widgets = []
        for graph_item in getattr(self, '_graph_items', []):
            widget = graph_item.get('widget')
            if widget is not None:
                managed_widgets.append(widget)
                try:
                    widget.hide()
                except Exception:
                    pass

        while self.graph_layout.count():
            item = self.graph_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                try:
                    widget.hide()
                except Exception:
                    pass
                # Keep the widget owned by graph_host so it can be reused on
                # the next rebuild.  It stays hidden until explicitly added
                # below.
                try:
                    widget.setParent(self.graph_host)
                except Exception:
                    pass

        self._ensure_one_graph_visible()
        visible = [
            item for item in getattr(self, '_graph_items', [])
            if item.get('visible', True) and item.get('widget') is not None
        ]
        cols = max(1, min(4, int(getattr(self, '_graph_columns', 2))))
        spacing = max(0, int(self.graph_layout.spacing()))

        try:
            self.layout.activate()
            self.central_widget.updateGeometry()
            self.central_widget.layout().activate()
        except Exception:
            pass

        viewport = self.graph_scroll.viewport()
        viewport_w = max(1, int(viewport.width()) - 2)
        viewport_h = max(1, int(viewport.height()) - 2)

        if not visible:
            self.graph_host.setFixedSize(viewport_w, 1)
            self.graph_layout.invalidate()
            viewport.update()
            return

        rows = (len(visible) + cols - 1) // cols
        min_row_height = 180
        min_content_height = rows * min_row_height + max(0, rows - 1) * spacing
        content_height = max(min_content_height, viewport_h)
        row_height = max(1, (content_height - max(0, rows - 1) * spacing) // rows)

        for r in range(max(rows, 32)):
            self.graph_layout.setRowStretch(r, 0)
            self.graph_layout.setRowMinimumHeight(r, 0)
        for c in range(4):
            self.graph_layout.setColumnStretch(c, 0)
            self.graph_layout.setColumnMinimumWidth(c, 0)

        for item in visible:
            widget = item['widget']
            widget.setMinimumSize(220, min_row_height)
            widget.setSizePolicy(
                self.QtWidgets.QSizePolicy.Expanding,
                self.QtWidgets.QSizePolicy.Expanding,
            )

        for i, item in enumerate(visible):
            row, col = divmod(i, cols)
            remaining = len(visible) - row * cols
            if row == rows - 1 and remaining < cols:
                base = cols // remaining
                extra = cols % remaining
                span = base + (1 if col < extra else 0)
                start_col = sum(base + (1 if j < extra else 0) for j in range(col))
                self.graph_layout.addWidget(item['widget'], row, start_col, 1, span)
            else:
                self.graph_layout.addWidget(item['widget'], row, col, 1, 1)
            try:
                item['widget'].show()
            except Exception:
                pass

        for r in range(rows):
            self.graph_layout.setRowMinimumHeight(r, row_height)
            self.graph_layout.setRowStretch(r, 1)
        for c in range(cols):
            self.graph_layout.setColumnStretch(c, 1)

        self.graph_host.setFixedSize(viewport_w, content_height)
        self.graph_layout.invalidate()
        self.graph_layout.activate()
        self.graph_host.updateGeometry()

        def _resize_plots():
            for item in visible:
                widget = item.get('widget')
                if widget is None:
                    continue
                try:
                    widget.updateGeometry()
                    widget.resize(widget.size())
                    widget.repaint()
                except Exception:
                    pass
            try:
                self.graph_scroll.viewport().update()
            except Exception:
                pass

        self.QtCore.QTimer.singleShot(0, _resize_plots)

        # Re-applying the canonical range after Qt has completed the geometry
        # pass is essential. Showing a PlotWidget after a grid rebuild may
        # auto-range it to its own data extent, which used to produce exactly
        # the split time scales seen with 2xN/3xN/4xN layouts.
        shared = getattr(self, '_shared_x_range_display', None)
        if shared is not None:
            self.QtCore.QTimer.singleShot(
                0, lambda xr=tuple(shared): self._sync_all_x_ranges(xr[0], xr[1])
            )

    def _open_graph_selector(self):
        dlg = self.QtWidgets.QDialog(self.win)
        dlg.setWindowFlags(dlg.windowFlags() & ~self.QtCore.Qt.WindowContextHelpButtonHint)
        dlg.setWindowTitle('Управление отображением графиков')
        dlg.resize(560, 620)
        lay = self.QtWidgets.QVBoxLayout(dlg)
        title = self.QtWidgets.QLabel('Выберите любые графики. Можно оставить один, несколько или все.')
        title.setWordWrap(True)
        lay.addWidget(title)
        mode_box = self.QtWidgets.QGroupBox('Раскладка')
        mode_lay = self.QtWidgets.QHBoxLayout(mode_box)
        mode_group = self.QtWidgets.QButtonGroup(dlg)
        modes = [(1, '1 колонка'), (2, '2 колонки'), (3, '3 колонки'), (4, '4 колонки')]
        buttons = []
        for value, text in modes:
            b = self.QtWidgets.QRadioButton(text)
            b.setProperty('cols', value)
            mode_group.addButton(b, value)
            mode_lay.addWidget(b)
            buttons.append(b)
        current_cols = int(getattr(self, '_graph_columns', 1))
        for b in buttons:
            if b.property('cols') == current_cols:
                b.setChecked(True)
        lay.addWidget(mode_box)
        listw = self.QtWidgets.QListWidget()
        listw.setSelectionMode(self.QtWidgets.QAbstractItemView.SingleSelection)
        graph_items = [
            item for item in getattr(self, '_graph_items', [])
            if item.get('widget') is not None
        ]
        # Repair an invalid persisted/runtime state before opening the dialog.
        self._ensure_one_graph_visible()
        for item in graph_items:
            lw = self.QtWidgets.QListWidgetItem(item['name'])
            lw.setFlags(lw.flags() | self.QtCore.Qt.ItemIsUserCheckable)
            lw.setCheckState(self.QtCore.Qt.Checked if item.get('visible', True) else self.QtCore.Qt.Unchecked)
            listw.addItem(lw)
        lay.addWidget(listw, 1)

        def ensure_checked_item(changed_item=None):
            # QListWidget emits itemChanged after the state has changed. If the
            # user tries to clear the final checked item, immediately restore it.
            checked = [
                i for i in range(listw.count())
                if listw.item(i).checkState() == self.QtCore.Qt.Checked
            ]
            if checked:
                return
            fallback = listw.row(changed_item) if changed_item is not None else 0
            if fallback < 0 or fallback >= listw.count():
                fallback = 0
            listw.blockSignals(True)
            try:
                listw.item(fallback).setCheckState(self.QtCore.Qt.Checked)
                listw.setCurrentRow(fallback)
            finally:
                listw.blockSignals(False)

        listw.itemChanged.connect(ensure_checked_item)
        row = self.QtWidgets.QHBoxLayout()
        all_btn = self.QtWidgets.QPushButton('Показать все')
        none_btn = self.QtWidgets.QPushButton('Скрыть все')
        one_btn = self.QtWidgets.QPushButton('Только выбранный')
        row.addWidget(all_btn); row.addWidget(none_btn); row.addWidget(one_btn)
        lay.addLayout(row)
        def show_all():
            listw.blockSignals(True)
            try:
                for i in range(listw.count()):
                    listw.item(i).setCheckState(self.QtCore.Qt.Checked)
            finally:
                listw.blockSignals(False)

        def keep_one():
            # "Hide all" is intentionally a one-graph operation: the UI must
            # never reach an empty workspace.
            listw.blockSignals(True)
            try:
                for i in range(listw.count()):
                    listw.item(i).setCheckState(self.QtCore.Qt.Unchecked)
                if listw.count():
                    listw.item(0).setCheckState(self.QtCore.Qt.Checked)
                    listw.setCurrentRow(0)
            finally:
                listw.blockSignals(False)

        all_btn.clicked.connect(show_all)
        none_btn.clicked.connect(keep_one)

        def only_selected():
            selected = listw.currentRow()
            if selected < 0:
                selected = 0
                listw.setCurrentRow(selected)
            listw.blockSignals(True)
            try:
                for i in range(listw.count()):
                    listw.item(i).setCheckState(
                        self.QtCore.Qt.Checked if i == selected else self.QtCore.Qt.Unchecked
                    )
            finally:
                listw.blockSignals(False)

        one_btn.clicked.connect(only_selected)
        buttons_row = self.QtWidgets.QDialogButtonBox(self.QtWidgets.QDialogButtonBox.Ok | self.QtWidgets.QDialogButtonBox.Cancel)
        lay.addWidget(buttons_row)
        buttons_row.accepted.connect(dlg.accept); buttons_row.rejected.connect(dlg.reject)
        if dlg.exec() == self.QtWidgets.QDialog.Accepted:
            states = {}
            for i, item in enumerate(graph_items):
                states[item['name']] = listw.item(i).checkState() == self.QtCore.Qt.Checked
            self._set_graph_visibility(states)
            checked_id = mode_group.checkedId()
            self._graph_columns = checked_id if checked_id > 0 else 1
            self._ensure_one_graph_visible()
            self._rebuild_graph_layout()

    def _format_time_ticks(self, values, scale, spacing):
        formatted = []
        if self.unit_mode == 'MS':
            for v in values:
                formatted.append(f"{int(v)}")
        elif self.unit_mode == 'SEC':
            for v in values:
                formatted.append(f"{v:.1f}")
        else:
            for v in values:
                formatted.append(f"{v:.2f}")
        return formatted

    def _ms_to_display(self, ms_value, unit_mode=None):
        mode = unit_mode or self.unit_mode
        if mode == 'MS':
            return ms_value
        if mode == 'SEC':
            return ms_value / 1000.0
        return ms_value / 60000.0

    def _display_to_ms(self, display_value, unit_mode=None):
        mode = unit_mode or self.unit_mode
        if mode == 'MS':
            return display_value
        if mode == 'SEC':
            return display_value * 1000.0
        return display_value * 60000.0

    @staticmethod
    def _format_analysis_time(time_ms):
        try:
            total_seconds = max(0, int(round(float(time_ms) / 1000.0)))
        except Exception:
            total_seconds = 0
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

    @staticmethod
    def _format_countdown_ms(remaining_ms):
        try:
            total_seconds = max(0, int(math.ceil(float(remaining_ms) / 1000.0)))
        except Exception:
            total_seconds = 0
        minutes, seconds = divmod(total_seconds, 60)
        return f'{minutes:02d}:{seconds:02d}'

                                        
    def _apply_elutek_qss(self):
        try:
            light = self.theme_mode == 'light'
            colors = get_palette(light)
            bg = colors['background']
            panel = colors['surface']
            panel_alt = colors['surface_alt']
            fg = colors['text']
            border = colors['border']
            accent = colors['accent']

            self.win.setStyleSheet(f"""
                QMainWindow, QWidget#ElutekCentral {{ background: {bg}; color: {fg}; }}
                QWidget {{ font-family: 'Segoe UI'; font-size: 9pt; }}
                QLabel {{ color: {fg}; font-family: 'Segoe UI', Arial; font-size: 9pt; }}
                QFrame#toolbarPanel {{ background: {panel}; border: 1px solid {border}; border-radius: 7px; }}
                QFrame#toolGroup {{ background: {panel_alt}; border: 1px solid {border}; border-radius: 5px; }}
                QLabel#toolbarBrandMark {{ background: {accent}; color: {colors['accent_on']}; border-radius: 5px; font-size: 14pt; font-weight: 800; }}
                QLabel#toolbarTitle {{ font-size: 12pt; font-weight: 750; }}
                QLabel#toolbarSubtitle {{ color: {colors['muted']}; font-size: 8pt; }}
                QLabel#toolGroupLabel {{ color: {colors['muted']}; font-size: 7pt; font-weight: 750; padding: 0 3px; }}
                QLabel#pointsBadge {{ background: {colors['accent_soft']}; color: {accent}; border-radius: 4px; padding: 7px 10px; font-weight: 700; }}
                QPushButton {{ background: {panel}; color: {fg}; border: 1px solid {border}; border-radius: 5px; padding: 7px 11px; font-size: 9pt; font-weight: 600; }}
                QPushButton:hover {{ background: {colors['surface_hover']}; border-color: {accent}; }}
                QPushButton:checked {{ background: {colors['accent_soft']}; color: {accent}; border: 1px solid {accent}; }}
                QPushButton#dangerButton {{ background: {colors['danger_soft']}; color: {colors['danger']}; border: 1px solid {colors['danger_soft']}; font-weight: 700; }}
                QPushButton#dangerButton:hover {{ background: {colors['danger']}; color: {colors['danger_on']}; }}
                QLabel#transitionAlert {{ background: {colors['danger']}; color: {colors['danger_on']}; border: 1px solid {colors['danger']}; border-radius: 7px; padding: 11px 20px; font-size: 14pt; font-weight: 800; }}
                QLabel#transitionAlert:hover {{ background: {colors['danger_hover']}; border-color: {colors['danger_hover']}; }}
                QFrame#transitionStatusPanel {{ background: {panel}; border: 1px solid {border}; border-radius: 7px; }}
                QLabel#transitionStatusHeader {{ color: {fg}; font-weight: 800; }}
                QLabel#transitionStatusLine {{ color: {fg}; font-weight: 600; }}
                QLabel#transitionStatusLine[state="active"] {{ color: {accent}; font-weight: 800; }}
                QLabel#transitionStatusLine[state="done"] {{ color: {colors['success']}; font-weight: 700; }}
                QLabel#transitionStatusDetail {{ color: {colors['muted']}; border-top: 1px solid {border}; padding-top: 5px; font-family: Consolas, 'Segoe UI', Arial; }}
                QMainWindow, QDialog, QScrollArea, QAbstractScrollArea, QScrollArea > QWidget, QScrollArea QWidget#qt_scrollarea_viewport, QWidget#graphHost {{ background: {bg}; color: {fg}; }}
                QScrollArea#graphScroll {{ background: {bg}; border: none; }}
                QDialog {{ background: {bg}; color: {fg}; }}
                QDialog QLabel, QGroupBox, QRadioButton, QListWidget, QListWidget::item {{ color: {fg}; }}
                QGroupBox {{ background: {panel}; border: 1px solid {border}; border-radius: 5px; margin-top: 10px; padding: 8px 10px 10px; }}
                QGroupBox::title {{ color: {fg}; subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
                QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {panel_alt}; color: {fg}; border: 1px solid {border}; border-radius: 4px; padding: 6px 8px; selection-background-color: {colors['accent_soft']}; selection-color: {fg}; }}
                QListWidget {{ alternate-background-color: {panel}; }}
                QScrollBar:vertical {{ background: {bg}; width: 8px; margin: 0px; border: none; border-radius: 4px; }}
                QScrollBar::handle:vertical {{ background: {colors['muted']}; border-radius: 4px; min-height: 25px; }}
                QScrollBar::handle:vertical:hover {{ background: {accent}; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; background: none; }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
                QScrollBar:horizontal {{ background: {bg}; height: 8px; margin: 0px; border: none; border-radius: 4px; }}
                QScrollBar::handle:horizontal {{ background: {colors['muted']}; border-radius: 4px; min-width: 25px; }}
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; background: none; }}
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
            """)

            if hasattr(self, 'cursor_hud') and self.cursor_hud is not None:
                self.cursor_hud.setStyleSheet(
                    f"QFrame#cursorHud {{ background-color: {panel_alt}; border: 1px solid {border}; border-radius: 5px; padding: 2px 10px; }}"
                )
                if hasattr(self, 'cursor_hud_label') and self.cursor_hud_label is not None:
                    self.cursor_hud_label.setStyleSheet(
                        f"font-family: 'Consolas', 'Segoe UI', monospace; font-size: 10px; font-weight: 600; color: {accent};"
                    )
        except Exception:
            pass

    def _build_custom_graphs(self):
        # Remove previous custom graph widgets from the workspace registry.
        old_custom = [x for x in getattr(self, '_graph_items', []) if x.get('kind') == 'custom']
        self._graph_items = [x for x in getattr(self, '_graph_items', []) if x.get('kind') != 'custom']
        for item in getattr(self, 'custom_graphs', []):
            try:
                item['widget'].deleteLater()
            except Exception:
                pass
        self.custom_graphs = []
        is_light = (self.theme_mode == 'light')
        palette = get_palette(is_light)
        title_color = palette['text']

        for definition in self.custom_graph_defs:
            name = str(definition.get('name', 'Пользовательский график')).strip()
            formula = str(definition.get('formula', '')).strip()
            color = definition.get('color', palette['accent'])
            if not name or not formula:
                continue
            time_axis = self.pg.AxisItem(orientation='bottom')
            time_axis.tickStrings = self._format_time_ticks
            widget = self.pg.PlotWidget(axisItems={'bottom': time_axis})
            widget.setMinimumSize(260, 120)
            widget.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Expanding)
            plot = widget.getPlotItem()
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setTitle(name, color=title_color, size="11pt", bold=True)
            plot.setLabel('left', 'Value')
            plot.setLabel('bottom', 'Time')
            try:
                pen = self.pg.mkPen(color, width=2.2)
            except Exception:
                pen = self.pg.mkPen(ELUTEK_ACCENT, width=2.2)
            curve = plot.plot(pen=pen)
            item = {'name': name, 'formula': formula, 'widget': widget, 'plot': plot, 'curve': curve, 'color': color, 'time_axis': time_axis}
            self.custom_graphs.append(item)
            self._register_graph_widget(name, widget, kind='custom')
            widget.scene().sigMouseClicked.connect(
                lambda evt, w=widget: self._on_plot_mouse_clicked(evt, w)
            )
        self._apply_theme()
        self._rebuild_graph_layout()

    def set_custom_graphs(self, definitions):
        self.custom_graph_defs = list(definitions or [])
        self._build_custom_graphs()

    def _update_custom_graphs(self, x_display):
        if not self.custom_graphs:
            return
        xs_arr = np.asarray(getattr(self, '_cached_xs', []), dtype=np.float64)
        r_arr = np.asarray(getattr(self, '_cached_r', []), dtype=np.float64)
        g_arr = np.asarray(getattr(self, '_cached_g', []), dtype=np.float64)
        b_arr = np.asarray(getattr(self, '_cached_b', []), dtype=np.float64)
        log_br_arr = np.asarray(getattr(self, '_cached_log', []), dtype=np.float64)
        log_bg_arr = np.asarray(getattr(self, '_cached_log_bg', []), dtype=np.float64)
        rgb_sum_arr = np.asarray(getattr(self, '_cached_rgb_sum', []), dtype=np.float64)
        slope30_arr = np.asarray(getattr(self, '_cached_rgb_sum_slope30', []), dtype=np.float64)
        transition_arr = np.asarray(getattr(self, '_cached_transition_score', []), dtype=np.float64)

        env = {
            'np': np,
            'log10': np.log10,
            'sqrt': np.sqrt,
            'exp': np.exp,
            'abs': np.abs,
            'sin': np.sin,
            'cos': np.cos,
            'mean': np.mean,
            'diff': lambda x: np.gradient(x) if len(x) else x,
            't': xs_arr,
            'T': xs_arr,
            'r': r_arr,
            'R': r_arr,
            'g': g_arr,
            'G': g_arr,
            'b': b_arr,
            'B': b_arr,
            'log_br': log_br_arr,
            'log_bg': log_bg_arr,
            'rgb_sum': rgb_sum_arr,
            'RGB_sum': rgb_sum_arr,
            'RGB_SUM': rgb_sum_arr,
            'slope30': slope30_arr,
            'transition_score': transition_arr,
            'rgb_vector_speed30': np.asarray(getattr(self, '_cached_rgb_vector_speed30', []), dtype=np.float64),
            'chromaticity_speed30': np.asarray(getattr(self, '_cached_chromaticity_speed30', []), dtype=np.float64),
            'k_chrom_previous': np.asarray(getattr(self, '_cached_k_chrom_previous', []), dtype=np.float64),
            'log_ratio_speed30': np.asarray(getattr(self, '_cached_log_ratio_speed30', []), dtype=np.float64),
            'rgb_sum_acceleration30': np.asarray(getattr(self, '_cached_rgb_sum_acceleration30', []), dtype=np.float64),
        }
        safe_builtins = {'abs': abs, 'min': min, 'max': max, 'round': round, 'float': float, 'int': int}

        # Evaluate custom variables first (Option 2)
        cfg = getattr(self, 'notification_settings', {}) or {}
        custom_vars = cfg.get('custom_variables', []) if isinstance(cfg, dict) else []
        for cv in custom_vars:
            v_name = str(cv.get('name', '')).strip()
            v_formula = str(cv.get('formula', '')).strip()
            if v_name and v_formula and v_name.isidentifier():
                try:
                    v_val = eval(v_formula, {'__builtins__': safe_builtins}, env)
                    env[v_name] = np.asarray(v_val, dtype=np.float64)
                except Exception:
                    pass

        for item in self.custom_graphs:
            try:
                value = eval(item['formula'], {'__builtins__': safe_builtins}, env)
                arr = np.asarray(value, dtype=np.float64)
                if arr.ndim == 0:
                    arr = np.full(len(x_display), float(arr), dtype=np.float64)
                if len(arr) != len(x_display):
                    item['curve'].setData([], [])
                    continue
                finite = np.isfinite(arr)
                if not finite.any():
                    item['curve'].setData([], [])
                    continue
                item['curve'].setData(x_display, arr, downsample=max(1, len(arr)//4000))
            except Exception:
                item['curve'].setData([], [])
                item['curve'].setData([], [])

    def _apply_theme(self):
        self._apply_elutek_qss()
        is_light = (self.theme_mode == 'light')
        colors = get_palette(is_light)
        bg = colors['background']
        axis_color = colors['muted']
        text_color = colors['muted']
        title_color = colors['text']
        grid_alpha = 0.14 if is_light else 0.19

        axis_pen = self.pg.mkPen(axis_color, width=1.2)
        text_pen = self.pg.mkPen(text_color)

        for widget in (
            self.plot_widget, self.log_plot_widget, self.log_bg_plot_widget,
            self.rgb_sum_slope_plot_widget, self.transition_score_plot_widget,
            *[item['plot'].getViewWidget() if hasattr(item['plot'], 'getViewWidget') else item['widget'] for item in getattr(self, 'custom_graphs', [])],
        ):
            try:
                widget.setBackground(bg)
            except Exception:
                pass

        # High-contrast bold titles for all built-in plots
        self.log_plot.setTitle('Log10(B/R)', color=title_color, size="11pt", bold=True)
        self.log_bg_plot.setTitle('Log10(B/G)', color=title_color, size="11pt", bold=True)
        self.rgb_sum_slope_plot.setTitle('RGB_sum_slope_30s', color=title_color, size="11pt", bold=True)
        self.transition_score_plot.setTitle('Transition_score', color=title_color, size="11pt", bold=True)

        for item in getattr(self, 'custom_graphs', []):
            try:
                item['plot'].setTitle(item['name'], color=title_color, size="11pt", bold=True)
                item['plot'].getAxis('left').setPen(axis_pen)
                item['plot'].getAxis('bottom').setPen(axis_pen)
                item['plot'].getAxis('left').setTextPen(text_pen)
                item['plot'].getAxis('bottom').setTextPen(text_pen)
                item['plot'].showGrid(x=True, y=True, alpha=grid_alpha)
                item['plot'].setLabel('bottom', 'Time', **{'color': text_color})
                item['plot'].setLabel('left', 'Value', **{'color': text_color})
                item['widget'].setStyleSheet('background: transparent;')
                plot_widget = item['widget'].findChild(self.QtWidgets.QWidget)
                if plot_widget is not None:
                    plot_widget.setStyleSheet(f'background: {bg};')
            except Exception:
                pass

        all_base_plots = (self.plot, self.log_plot, self.log_bg_plot, self.rgb_sum_slope_plot, self.transition_score_plot)
        for p in all_base_plots:
            try:
                p.getAxis('left').setPen(axis_pen)
                p.getAxis('bottom').setPen(axis_pen)
                p.getAxis('left').setTextPen(text_pen)
                p.getAxis('bottom').setTextPen(text_pen)
                p.showGrid(x=True, y=True, alpha=grid_alpha)
            except Exception:
                pass

        self.plot.setLabel('left', 'Value', **{'color': text_color})
        self._update_axis_labels()

        self.log_plot.setLabel('left', 'Log10(B/R)', **{'color': text_color})
        self.log_plot.setLabel('bottom', 'Time', **{'color': text_color})
        self.log_bg_plot.setLabel('left', 'Log10(B/G)', **{'color': text_color})
        self.log_bg_plot.setLabel('bottom', 'Time', **{'color': text_color})
        self.rgb_sum_slope_plot.setLabel('left', 'd(R+G+B)/dt', **{'color': text_color})
        self.rgb_sum_slope_plot.setLabel('bottom', 'Time', **{'color': text_color})
        self.transition_score_plot.setLabel('left', 'score', **{'color': text_color})
        self.transition_score_plot.setLabel('bottom', 'Time', **{'color': text_color})

        self.r_curve.setPen(self.pg.mkPen(colors['channel_r'], width=2.1))
        self.g_curve.setPen(self.pg.mkPen(colors['channel_g'], width=2.1))
        self.b_curve.setPen(self.pg.mkPen(colors['channel_b'], width=2.1))
        self.log_curve.setPen(self.pg.mkPen(colors['warning'], width=2.3))
        self.log_bg_curve.setPen(self.pg.mkPen(colors['channel_b'], width=2.3))
        self.rgb_sum_slope_curve.setPen(self.pg.mkPen(colors['success'], width=2.2))
        self.rgb_sum_slope_zero_line.setPen(self.pg.mkPen(colors['border'], width=1))
        self.transition_score_curve.setPen(self.pg.mkPen(colors['warning'], width=2.2))
        self.transition_score_line_warn.setPen(self.pg.mkPen(colors['border'], width=1))
        self.transition_score_line_prob.setPen(self.pg.mkPen(colors['warning'], width=1))
        self.transition_score_line_strong.setPen(self.pg.mkPen(colors['danger'], width=1.4))

        self._apply_log_y_ranges(
            self._cached_log if len(self._cached_log) else None,
            self._cached_log_bg if len(self._cached_log_bg) else None,
        )
        self._apply_single_log_y_range(
            self.rgb_sum_slope_plot,
            self._cached_rgb_sum_slope30 if len(self._cached_rgb_sum_slope30) else None,
            '_rgb_sum_slope30_y_min', '_rgb_sum_slope30_y_max'
        )
        self._apply_transition_score_y_range(
            self._cached_transition_score if len(self._cached_transition_score) else None
        )
        for plot_item in (self.plot, self.rgb_sum_slope_plot, self.transition_score_plot, self.log_plot, self.log_bg_plot):
            try:
                plot_item.getAxis('left').setTextPen(text_pen)
                plot_item.getAxis('bottom').setTextPen(text_pen)
                plot_item.getAxis('left').setPen(axis_pen)
                plot_item.getAxis('bottom').setPen(axis_pen)
            except Exception:
                pass
        self._update_annotations()

    def _apply_single_log_y_range(self, plot_item, values, attr_min_name, attr_max_name):
        if values is not None and len(values) > 0:
            y_min, y_max = adaptive_log_y_range(values)
            setattr(self, attr_min_name, y_min)
            setattr(self, attr_max_name, y_max)
        y_min = getattr(self, attr_min_name)
        y_max = getattr(self, attr_max_name)
        plot_item.setYRange(y_min, y_max, padding=0)
        plot_item.setLimits(yMin=y_min)
        try:
            log_left = plot_item.getAxis('left')
            ticks = nice_y_axis_ticks(y_min, y_max)
            log_left.setTicks([ticks])
            log_left.setWidth(60)
        except Exception:
            pass

    def _apply_transition_score_y_range(self, values=None):
        # Transition_score is not logarithmic.  Reusing the log-range helper
        # here was a real data/axis bug: negative Log10-like ranges could be
        # applied to a 0..10 transition score and clip the entire curve.
        if values is not None and len(values) > 0:
            arr = np.asarray(values, dtype=np.float64)
            finite = arr[np.isfinite(arr)]
            if finite.size:
                y_min = max(0.0, float(finite.min()) - 0.25)
                y_max = min(10.0, float(finite.max()) + 0.25)
                if y_max - y_min < 1.0:
                    center = float(np.clip(np.nanmean(finite), 0.0, 10.0))
                    y_min = max(0.0, center - 1.0)
                    y_max = min(10.0, center + 1.0)
                self._transition_score_y_min = y_min
                self._transition_score_y_max = y_max

        y_min = getattr(self, '_transition_score_y_min', 0.0)
        y_max = getattr(self, '_transition_score_y_max', 10.0)
        self.transition_score_plot.setYRange(y_min, y_max, padding=0)
        self.transition_score_plot.setLimits(yMin=0.0, yMax=10.0)
        try:
            axis = self.transition_score_plot.getAxis('left')
            axis.setTicks([nice_y_axis_ticks(y_min, y_max)])
            axis.setWidth(60)
        except Exception:
            pass

    def _apply_log_y_ranges(self, log_br_vals=None, log_bg_vals=None):
        self._apply_single_log_y_range(self.log_plot, log_br_vals, '_log_br_y_min', '_log_br_y_max')
        self._apply_single_log_y_range(self.log_bg_plot, log_bg_vals, '_log_bg_y_min', '_log_bg_y_max')

    def _update_axis_labels(self):
        text_color = get_palette(self.theme_mode == 'light')['muted']
        unit_str = self.unit_mode.lower()
        lbl = f"Time ({unit_str})"
        self.plot.setLabel('bottom', lbl, **{'color': text_color})
        for plot_item in (self.log_plot, self.log_bg_plot, self.rgb_sum_slope_plot, self.transition_score_plot):
            plot_item.setLabel('bottom', lbl, **{'color': text_color})
        for item in getattr(self, 'custom_graphs', []):
            try:
                item['plot'].setLabel('bottom', lbl, **{'color': text_color})
            except Exception:
                pass

                                             
    def set_data(self, xs, r_vals, g_vals, b_vals, log_vals=None, log_bg_vals=None,
                 tri_x_vals=None, tri_y_vals=None, rgb_sum_vals=None,
                 rgb_sum_smooth_vals=None, rgb_sum_slope10_vals=None,
                 rgb_sum_slope30_vals=None, rgb_vector_speed30_vals=None,
                 chromaticity_speed30_vals=None, k_chrom_previous_vals=None,
                 log_ratio_speed30_vals=None, rgb_sum_acceleration30_vals=None,
                 transition_score_vals=None, pts=None):
        self._cached_xs = xs
        self._cached_r = r_vals
        self._cached_g = g_vals
        self._cached_b = b_vals
        if log_vals is not None:
            self._cached_log = log_vals
        if log_bg_vals is not None:
            self._cached_log_bg = log_bg_vals
        if tri_x_vals is not None:
            self._cached_tri_x = tri_x_vals
        if tri_y_vals is not None:
            self._cached_tri_y = tri_y_vals
        if rgb_sum_vals is not None:
            self._cached_rgb_sum = rgb_sum_vals
        if rgb_sum_smooth_vals is not None:
            self._cached_rgb_sum_smooth = rgb_sum_smooth_vals
        if rgb_sum_slope10_vals is not None:
            self._cached_rgb_sum_slope10 = rgb_sum_slope10_vals
        if rgb_sum_slope30_vals is not None:
            self._cached_rgb_sum_slope30 = rgb_sum_slope30_vals
        if rgb_vector_speed30_vals is not None:
            self._cached_rgb_vector_speed30 = rgb_vector_speed30_vals
        if chromaticity_speed30_vals is not None:
            self._cached_chromaticity_speed30 = chromaticity_speed30_vals
        if k_chrom_previous_vals is not None:
            self._cached_k_chrom_previous = k_chrom_previous_vals
        if log_ratio_speed30_vals is not None:
            self._cached_log_ratio_speed30 = log_ratio_speed30_vals
        if rgb_sum_acceleration30_vals is not None:
            self._cached_rgb_sum_acceleration30 = rgb_sum_acceleration30_vals
        if transition_score_vals is not None:
            self._cached_transition_score = transition_score_vals
        self._cached_pts = len(xs) if pts is None else pts

        self.show_r = self.btn_r.isChecked()
        self.show_g = self.btn_g.isChecked()
        self.show_b = self.btn_b.isChecked()
        self.show_log = self.log_btn.isChecked()

        n = len(xs)
        if n == 0:
            self.r_curve.setData([], [])
            self.g_curve.setData([], [])
            self.b_curve.setData([], [])
            self.log_curve.setData([], [])
            self.log_bg_curve.setData([], [])
            self.rgb_sum_slope_curve.setData([], [])
            self.transition_score_curve.setData([], [])
            for item in getattr(self, 'custom_graphs', []):
                item['curve'].setData([], [])
            if pts is not None:
                self.pts_label.setText(f'Точки · {pts}')
            return

        x_arr = np.asarray(xs, dtype=np.float64)
        if self.unit_mode == 'MS':
            x_display = x_arr
        elif self.unit_mode == 'SEC':
            x_display = x_arr / 1000.0
        else:
            x_display = x_arr / 60000.0
        ds = max(1, n // 4000)

        def _aligned(values):
            """Return an x/y pair with a safe common length."""
            if values is None:
                return x_display[:0], np.empty(0, dtype=np.float64)
            try:
                arr = np.asarray(values, dtype=np.float64).reshape(-1)
            except Exception:
                return x_display[:0], np.empty(0, dtype=np.float64)
            m = min(len(x_display), len(arr))
            if m <= 0:
                return x_display[:0], np.empty(0, dtype=np.float64)
            return x_display[:m], arr[:m]

        self._update_custom_graphs(x_display)

        xr, rr = _aligned(r_vals)
        xg, gg = _aligned(g_vals)
        xb, bb = _aligned(b_vals)
        if self.show_r:
            self.r_curve.setData(xr, rr, downsample=ds)
        else:
            self.r_curve.setData([], [])
        if self.show_g:
            self.g_curve.setData(xg, gg, downsample=ds)
        else:
            self.g_curve.setData([], [])
        if self.show_b:
            self.b_curve.setData(xb, bb, downsample=ds)
        else:
            self.b_curve.setData([], [])

        # Do not synchronize X before the other curves are updated: setData()
        # can trigger pyqtgraph's auto-range on a graph that is not currently
        # linked.  The final synchronization below is therefore the single
        # source of truth for the complete graph workspace.
        if self._autoscroll:
            first_x = float(x_display[0])
            last_x = float(x_display[-1])
            if last_x <= first_x:
                last_x = first_x + max(1.0, abs(first_x) * 0.01 + 1.0)
            self.plot.setYRange(RGB_Y_MIN, RGB_Y_MAX, padding=0)
            self.plot.setLimits(yMin=RGB_Y_MIN, yMax=RGB_Y_MAX)

        if self.show_log:
            log_x, log_arr = _aligned(self._cached_log)
            valid_mask = np.isfinite(log_arr)
            if np.any(valid_mask):
                self.log_curve.setData(log_x[valid_mask], log_arr[valid_mask], downsample=ds)
            else:
                self.log_curve.setData([], [])

            log_bg_x, log_bg_arr = _aligned(self._cached_log_bg)
            valid_mask_bg = np.isfinite(log_bg_arr)
            if np.any(valid_mask_bg):
                self.log_bg_curve.setData(log_bg_x[valid_mask_bg], log_bg_arr[valid_mask_bg], downsample=ds)
            else:
                self.log_bg_curve.setData([], [])
        else:
            self.log_curve.setData([], [])
            self.log_bg_curve.setData([], [])

        def _set_valid_curve(curve, values):
            curve_x, arr = _aligned(values)
            if len(arr) == 0:
                curve.setData([], [])
                return
            mask = np.isfinite(arr)
            if np.any(mask):
                curve.setData(curve_x[mask], arr[mask], downsample=ds)
            else:
                curve.setData([], [])

        _set_valid_curve(self.rgb_sum_slope_curve, self._cached_rgb_sum_slope30)
        self._apply_single_log_y_range(
            self.rgb_sum_slope_plot,
            self._cached_rgb_sum_slope30 if len(self._cached_rgb_sum_slope30) else None,
            '_rgb_sum_slope30_y_min', '_rgb_sum_slope30_y_max'
        )
        _set_valid_curve(self.transition_score_curve, self._cached_transition_score)
        self._apply_transition_score_y_range(
            self._cached_transition_score if len(self._cached_transition_score) else None
        )

        self._apply_log_y_ranges(
            self._cached_log if (self.show_log and self._cached_log is not None and len(self._cached_log) > 0) else None,
            self._cached_log_bg if (self.show_log and self._cached_log_bg is not None and len(self._cached_log_bg) > 0) else None,
        )

        if pts is not None:
            self.pts_label.setText(f'Точки · {pts}')

        # IMPORTANT: all curves (including custom graphs) have now received
        # their data.  Only here do we force the common X range, otherwise a
        # full-width/custom graph may auto-range to the whole recording while
        # the linked graphs keep the range inherited from RGB.
        if self._autoscroll:
            first_x = float(x_display[0])
            last_x = float(x_display[-1])
            if last_x <= first_x:
                last_x = first_x + max(1.0, abs(first_x) * 0.01 + 1.0)
            self._sync_all_x_ranges(first_x, last_x)

        self._update_annotations()
        self._check_transition_alerts(
            self._cached_xs,
            self._cached_r, self._cached_g, self._cached_b,
            self._cached_rgb_sum_slope30,
            self._cached_transition_score,
        )

                                             
    def _update_transition_status_panel(self, current_t=None, current_slope=None,
                                        current_score=None, force_show=False):
        try:
            cfg = getattr(self, 'notification_settings', {}) or {}
            master_enabled = bool(cfg.get('auto_marks_enabled', True))
            arom_on = bool(cfg.get('auto_mark_arom_enabled', True))
            br_on = bool(cfg.get('auto_mark_br_enabled', True))
            abr_on = bool(cfg.get('auto_mark_abr_enabled', True))
            sara_enabled = master_enabled and (arom_on or br_on or abr_on)

            if not sara_enabled and not force_show:
                self.transition_status_panel.hide()
                return

            if current_t is None:
                current_t = getattr(self, '_transition_last_current_t', 0.0)
            if current_slope is None:
                current_slope = getattr(self, '_transition_last_slope', float('nan'))
            if current_score is None:
                current_score = getattr(self, '_transition_last_score', float('nan'))

            current_t = float(current_t or 0.0)
            stage = getattr(self, '_transition_detection_stage', 'arom')
            event_times = getattr(self, '_transition_event_times', {})

            should_show = (
                force_show or
                (sara_enabled and (
                    current_t >= TRANSITION_STATUS_SHOW_AFTER_MS or
                    stage != 'arom' or
                    bool(event_times)
                ))
            )
            self.transition_status_panel.setVisible(should_show)
            if not should_show:
                return

            if arom_on:
                if 'arom' in event_times:
                    self._set_transition_status_line(
                        0,
                        f"✓ 1. Переход SAT → AROM обнаружен в "
                        f"{self._format_analysis_time(event_times['arom'])}",
                        'done', True,
                    )
                else:
                    self._set_transition_status_line(
                        0,
                        '● 1. Идет фракция SAT, ожидается выход AROM',
                        'active', True,
                    )
            else:
                self._set_transition_status_line(0, '', 'future', False)

            show_line_2 = br_on and ('arom' in event_times or not arom_on)
            if br_on and 'br' in event_times:
                self._set_transition_status_line(
                    1,
                    f"✓ 2. Переход AROM → BR обнаружен в "
                    f"{self._format_analysis_time(event_times['br'])}",
                    'done', True,
                )
            elif show_line_2:
                self._set_transition_status_line(
                    1,
                    '● 2. Идет фракция AROM, ожидается BR',
                    'active', True,
                )
            else:
                self._set_transition_status_line(1, '', 'future', False)

            show_line_3 = abr_on and ('br' in event_times or not br_on)
            if abr_on and 'abr' in event_times:
                self._set_transition_status_line(
                    2,
                    f"✓ 3. Переход BR → ABR обнаружен в "
                    f"{self._format_analysis_time(event_times['abr'])}",
                    'done', True,
                )
            elif show_line_3:
                self._set_transition_status_line(
                    2,
                    '● 3. Идет фракция BR, ожидается ABR',
                    'active', True,
                )
            else:
                self._set_transition_status_line(2, '', 'future', False)

            if abr_on and 'abr' in event_times:
                self._set_transition_status_line(
                    3,
                    '● 4. Идет фракция ABR, после выхода анализ будет завершен',
                    'active', True,
                )
            else:
                self._set_transition_status_line(3, '', 'future', False)

            slope_text = '—' if not np.isfinite(current_slope) else f'{current_slope:.2f}'
            score_text = '—' if not np.isfinite(current_score) else f'{current_score:.2f}'

            br_delay_ms = float(self._notification_value('auto_mark_br_arm_delay_sec', 300.0)) * 1000.0
            abr_delay_ms = float(self._notification_value('auto_mark_abr_arm_delay_sec', 300.0)) * 1000.0
            br_slope_th = float(self._notification_value('auto_mark_br_slope_th', BR_SLOPE_THRESHOLD))
            br_score_th = float(self._notification_value('auto_mark_br_score_th', BR_SCORE_THRESHOLD))
            abr_slope_th = float(self._notification_value('auto_mark_abr_slope_th', ABR_SLOPE_THRESHOLD))
            abr_score_th = float(self._notification_value('auto_mark_abr_score_th', ABR_SCORE_THRESHOLD))

            if stage == 'arom':
                detail = (
                    'Детектор AROM: АКТИВЕН  |  '
                    f'RGB_sum_slope_30s: {slope_text}  |  '
                    f'Transition_score: {score_text}'
                )
            elif stage == 'delay_br':
                elapsed = current_t - float(getattr(self, '_transition_stage_started_ms', current_t))
                remaining = br_delay_ms - elapsed
                detail = (
                    f'Детектор BR включится через {self._format_countdown_ms(remaining)}  |  '
                    f'RGB_sum_slope_30s: {slope_text}  |  '
                    f'Transition_score: {score_text}'
                )
            elif stage == 'br':
                detail = (
                    'Детектор BR: ВЗВЕДЁН  |  '
                    f'RGB_sum_slope_30s: {slope_text} / > {br_slope_th:.2f}  |  '
                    f'Transition_score: {score_text} / > {br_score_th:.2f}'
                )
            elif stage == 'delay_abr':
                elapsed = current_t - float(getattr(self, '_transition_stage_started_ms', current_t))
                remaining = abr_delay_ms - elapsed
                detail = (
                    f'Детектор ABR включится через {self._format_countdown_ms(remaining)}  |  '
                    f'RGB_sum_slope_30s: {slope_text}  |  '
                    f'Transition_score: {score_text}'
                )
            elif stage == 'abr':
                detail = (
                    'Детектор ABR: ВЗВЕДЁН  |  '
                    f'RGB_sum_slope_30s: {slope_text} / ≤ {abr_slope_th:.2f}  |  '
                    f'Transition_score: {score_text} / ≥ {abr_score_th:.2f}'
                )
            else:
                detail = 'Детектор переходов: ЗАВЕРШЁН'

            self.transition_detector_status.setText(detail)
        except Exception as exc:
            print(f'⚠️ Ошибка обновления панели стадий: {exc}')

    def _set_transition_status_line(self, index, text, state='future', visible=True):
        try:
            label = self.transition_status_lines[index]
            label.setText(text)
            label.setProperty('state', state)
            label.style().unpolish(label)
            label.style().polish(label)
            label.setVisible(bool(visible))
        except Exception:
            pass

    def _reset_transition_condition_timer(self):
        self._transition_condition_started_ms = None
        self._transition_condition_mode = None

    def _condition_held(self, condition, current_t, hold_ms, mode):
        if not condition:
            self._reset_transition_condition_timer()
            return False
        started = getattr(self, '_transition_condition_started_ms', None)
        current_mode = getattr(self, '_transition_condition_mode', None)
        if started is None or current_mode != mode:
            self._transition_condition_started_ms = float(current_t)
            self._transition_condition_mode = mode
            return False
        return float(current_t) - float(started) >= float(hold_ms)

    def _advance_transition_stage_by_time(self, current_t):
        stage = getattr(self, '_transition_detection_stage', 'arom')
        started = float(getattr(self, '_transition_stage_started_ms', current_t))
        br_delay_ms = float(self._notification_value('auto_mark_br_arm_delay_sec', 300.0)) * 1000.0
        abr_delay_ms = float(self._notification_value('auto_mark_abr_arm_delay_sec', 300.0)) * 1000.0

        if stage == 'delay_br' and current_t - started >= br_delay_ms:
            self._transition_detection_stage = 'br'
            self._reset_transition_condition_timer()
            print(f'✅ Детектор BR взведён через {br_delay_ms / 60000.0:.1f} мин после AROM.')
        elif stage == 'delay_abr' and current_t - started >= abr_delay_ms:
            self._transition_detection_stage = 'abr'
            self._reset_transition_condition_timer()
            print(f'✅ Детектор ABR взведён через {abr_delay_ms / 60000.0:.1f} мин после BR.')

    def _notification_value(self, key, default):
        """Return a validated notification setting, falling back to the code default."""
        try:
            value = self.notification_settings.get(key, default)
            value = float(value)
            if not np.isfinite(value):
                return float(default)
            return value
        except (TypeError, ValueError, AttributeError):
            return float(default)

    def _sync_all_x_ranges(self, x_min=None, x_max=None, source_plot=None):
        """Keep every registered graph on exactly the same time window.

        The range is stored independently from the PlotWidgets because a
        hidden/re-shown widget may auto-range during a grid/layout change.
        """
        plots = []
        for item in getattr(self, '_graph_items', []):
            widget = item.get('widget')
            try:
                plot = widget.getPlotItem() if widget is not None else None
            except Exception:
                plot = None
            if plot is not None and plot not in plots:
                plots.append(plot)
        if not plots:
            plots = [self.plot, self.log_plot, self.log_bg_plot,
                     self.rgb_sum_slope_plot, self.transition_score_plot]
        try:
            if source_plot is not None:
                xr = source_plot.getViewBox().viewRange()[0]
                x_min, x_max = float(xr[0]), float(xr[1])
            elif x_min is None or x_max is None:
                shared = getattr(self, '_shared_x_range_display', None)
                if shared is not None:
                    x_min, x_max = float(shared[0]), float(shared[1])
                else:
                    xr = self.plot.getViewBox().viewRange()[0]
                    x_min, x_max = float(xr[0]), float(xr[1])
            if not np.isfinite(x_min) or not np.isfinite(x_max) or x_min == x_max:
                return

            # Store the range before touching any widget. This is the
            # canonical range that survives hide/show, grid changes and
            # geometry-driven auto-ranging.
            self._shared_x_range_display = (float(x_min), float(x_max))
            self._ignore_view_change = True
            try:
                for plot in plots:
                    plot.setXRange(x_min, x_max, padding=0)
            finally:
                self._ignore_view_change = False
        except Exception:
            pass

    def _play_system_alert_sound(self):
        try:
            import threading
            def _play():
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    return
                except Exception:
                    pass
                try:
                    if hasattr(self, 'QtWidgets') and hasattr(self.QtWidgets, 'QApplication'):
                        self.QtWidgets.QApplication.beep()
                        return
                except Exception:
                    pass
                try:
                    import sys
                    sys.stdout.write('\a')
                    sys.stdout.flush()
                except Exception:
                    pass
            threading.Thread(target=_play, daemon=True).start()
        except Exception:
            pass

    def _check_custom_auto_marks(self, time_ms, r, g, b, slope30, transition_score):
        """Evaluate user-defined automatic marker rules on the latest sample."""
        if not bool(self.notification_settings.get("auto_marks_enabled", True)):
            return
        if not hasattr(self, '_custom_auto_mark_active'):
            self._custom_auto_mark_active = {}
        if not hasattr(self, '_custom_auto_mark_last_fired'):
            self._custom_auto_mark_last_fired = {}
        rules = self.notification_settings.get("custom_auto_marks", []) or []
        time_sec = float(time_ms) / 1000.0

        rgb_sum_val = (r + g + b) if all(v is not None and np.isfinite(v) for v in (r, g, b)) else np.nan
        log_br_val = np.log10(b / r) if r not in (None, 0) and b is not None and r > 0 and b > 0 else np.nan
        log_bg_val = np.log10(b / g) if g not in (None, 0) and b is not None and g > 0 and b > 0 else np.nan

        values = {
            "RGB_sum": rgb_sum_val,
            "RGB_SUM": rgb_sum_val,
            "rgb_sum": rgb_sum_val,
            "RGB_sum_slope_30s": slope30,
            "slope30": slope30,
            "Transition_score": transition_score,
            "transition_score": transition_score,
            "Log10(B/R)": log_br_val,
            "log_br": log_br_val,
            "Log10(B/G)": log_bg_val,
            "log_bg": log_bg_val,
            "R": r,
            "r": r,
            "G": g,
            "g": g,
            "B": b,
            "b": b,
            "t": time_sec,
            "T": time_sec,
        }

        # Math environment for evaluating custom variables and custom graphs
        env = {
            'np': np,
            'log10': np.log10, 'sqrt': np.sqrt, 'exp': np.exp, 'abs': np.abs,
            'sin': np.sin, 'cos': np.cos,
            'r': r, 'R': r, 'g': g, 'G': g, 'b': b, 'B': b,
            't': time_sec, 'T': time_sec,
            'rgb_sum': rgb_sum_val, 'RGB_sum': rgb_sum_val, 'RGB_SUM': rgb_sum_val,
            'slope30': slope30,
            'transition_score': transition_score,
            'log_br': log_br_val,
            'log_bg': log_bg_val,
        }
        safe_builtins = {'abs': abs, 'min': min, 'max': max, 'round': round, 'float': float, 'int': int}

        # 1. Evaluate custom variables
        cfg = getattr(self, 'notification_settings', {}) or {}
        custom_vars = cfg.get('custom_variables', []) if isinstance(cfg, dict) else []
        for cv in custom_vars:
            v_name = str(cv.get('name', '')).strip()
            v_formula = str(cv.get('formula', '')).strip()
            if v_name and v_formula and v_name.isidentifier():
                try:
                    v_val = eval(v_formula, {'__builtins__': safe_builtins}, env)
                    f_val = float(v_val)
                    env[v_name] = f_val
                    values[v_name] = f_val
                except Exception:
                    pass

        # 2. Evaluate custom graphs
        custom_graphs = cfg.get('custom_graphs', []) if isinstance(cfg, dict) else []
        for cg in custom_graphs:
            cg_name = str(cg.get('name', '')).strip()
            cg_formula = str(cg.get('formula', '')).strip()
            if cg_name and cg_formula:
                try:
                    cg_val = eval(cg_formula, {'__builtins__': safe_builtins}, env)
                    f_val = float(cg_val)
                    values[cg_name] = f_val
                    if cg_name.isidentifier():
                        env[cg_name] = f_val
                except Exception:
                    pass

        for index, rule in enumerate(rules):
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            rule_key = str(rule.get("name") or f"rule_{index}")
            t_min = float(rule.get("t_min_sec", 0.0))
            t_max_val = float(rule.get("t_max_sec", 0.0))
            t_max = float('inf') if t_max_val <= 0.0 else t_max_val
            if not (t_min <= time_sec <= t_max):
                self._custom_auto_mark_active[rule_key] = False
                continue

            cond_list = rule.get("conditions")
            if not cond_list or not isinstance(cond_list, list):
                cond_list = [{
                    "metric": rule.get("metric", "RGB_sum_slope_30s"),
                    "operator": rule.get("operator", ">="),
                    "threshold": float(rule.get("threshold", 0.0))
                }]

            all_matched = True
            matched_details = []
            for cond in cond_list:
                metric = cond.get("metric", "RGB_sum_slope_30s")
                value = values.get(metric, np.nan)
                try:
                    threshold = float(cond.get("threshold", 0.0))
                    op = str(cond.get("operator", ">="))
                except Exception:
                    all_matched = False
                    break
                if not np.isfinite(value):
                    all_matched = False
                    break
                hit = {
                    ">=": value >= threshold,
                    ">": value > threshold,
                    "<=": value <= threshold,
                    "<": value < threshold,
                    "==": abs(value - threshold) < 1e-4
                }.get(op, False)
                if not hit:
                    all_matched = False
                    break
                matched_details.append(f"{metric}={value:.3g} {op} {threshold:.3g}")

            if not all_matched:
                self._custom_auto_mark_active[rule_key] = False
                continue

            # Holdoff / Cooldown check (защита от дублирования автометок на одном участке)
            last_fired_sec = float(self._custom_auto_mark_last_fired.get(rule_key, -1e9))
            cooldown_enabled = bool(rule.get("cooldown_enabled", False))
            cooldown_sec = float(rule.get("cooldown_sec", 0.0))
            if cooldown_enabled and cooldown_sec > 0.0:
                if (time_sec - last_fired_sec) < cooldown_sec:
                    continue

            was_active = bool(self._custom_auto_mark_active.get(rule_key, False))
            if was_active:
                continue
            self._custom_auto_mark_active[rule_key] = True
            self._custom_auto_mark_last_fired[rule_key] = time_sec
            description = str(rule.get("description") or rule.get("name") or "Пользовательская автометка")
            color = str(rule.get("color") or get_palette(self.theme_mode == 'light')['success'])
            try:
                self.annotation_manager.add_annotation(
                    time_ms, description, color=color, is_auto=True,
                    r=r, g=g, b=b, rgb_sum_slope_30s=slope30, transition_score=transition_score
                )
                self._update_annotations()
                self._persist_annotations()
                if bool(rule.get("notify", True)) and bool(self.notification_settings.get("notifications_enabled", True)):
                    self._show_transition_alert(f"ОБНАРУЖЕНА АВТОМЕТКА:\n{description}")
                    self._show_toast(f"📌 Автометка: {description}")
                if bool(rule.get("sound", True)) and bool(self.notification_settings.get("sound_alerts_enabled", True)):
                    self._play_system_alert_sound()
                print(f"📌 Пользовательская автометка: {description} | Условия: {', '.join(matched_details)}")
            except Exception as e:
                print(f"⚠️ Ошибка пользовательской автометки: {e}")

    def _check_transition_alerts(self, xs, r_vals, g_vals, b_vals,
                                 slope30_vals, transition_score_vals=None):
        cfg = getattr(self, 'notification_settings', {}) or {}
        master_enabled = bool(cfg.get('auto_marks_enabled', True))
        arom_enabled = master_enabled and bool(cfg.get('auto_mark_arom_enabled', True))
        br_enabled = master_enabled and bool(cfg.get('auto_mark_br_enabled', True))
        abr_enabled = master_enabled and bool(cfg.get('auto_mark_abr_enabled', True))
        sara_enabled = master_enabled and (arom_enabled or br_enabled or abr_enabled)
        notifications_enabled = bool(cfg.get('notifications_enabled', TRANSITION_ALERTS_ENABLED))

        try:
            arrays = (xs, r_vals, g_vals, b_vals, slope30_vals)
            if any(v is None or len(v) == 0 for v in arrays):
                return

            t = np.asarray(xs, dtype=np.float64)
            r = np.asarray(r_vals, dtype=np.float64)
            g = np.asarray(g_vals, dtype=np.float64)
            b = np.asarray(b_vals, dtype=np.float64)
            s = np.asarray(slope30_vals, dtype=np.float64)

            if transition_score_vals is None or len(transition_score_vals) == 0:
                score = np.full_like(s, np.nan, dtype=np.float64)
            else:
                score = np.asarray(transition_score_vals, dtype=np.float64)

            n = min(t.size, r.size, g.size, b.size, s.size, score.size)
            if n < RGB_SUM_SLOPE_MIN_POINTS:
                return
            t, r, g, b, s, score = (arr[:n] for arr in (t, r, g, b, s, score))
            current_t = float(t[-1])

            if sara_enabled:
                self._advance_transition_stage_by_time(current_t)
            stage = getattr(self, '_transition_detection_stage', 'arom')

            current_slope = float(s[-1]) if np.isfinite(s[-1]) else float('nan')
            current_score = float(score[-1]) if np.isfinite(score[-1]) else float('nan')
            self._transition_last_current_t = current_t
            self._transition_last_slope = current_slope
            self._transition_last_score = current_score
            self._update_transition_status_panel(current_t, current_slope, current_score)
            self._check_custom_auto_marks(current_t, r[-1], g[-1], b[-1], current_slope, current_score)

            if not sara_enabled:
                return

            recent_mask = (
                (t >= current_t - TRANSITION_ALERT_CONFIRM_MS) &
                np.isfinite(t) & np.isfinite(r) & np.isfinite(g) &
                np.isfinite(b) & np.isfinite(s) & np.isfinite(score)
            )
            if int(np.count_nonzero(recent_mask)) < 3:
                return

            rr = r[recent_mask]
            gg = g[recent_mask]
            bb = b[recent_mask]
            ss = s[recent_mask]
            scores = score[recent_mask]

            median_slope = float(np.median(ss))
            peak_pos_slope = float(np.max(ss))
            peak_neg_slope = float(np.min(ss))
            peak_score = float(np.max(scores))
            median_rgb_sum = float(np.median(rr + gg + bb))
            valid_signal = median_rgb_sum >= TRANSITION_MIN_RGB_SUM

            def fire_alert(rid, label, message, next_stage):
                self._transition_alerts_triggered.add(rid)
                self._transition_event_times[rid] = current_t
                self._transition_detection_stage = next_stage
                self._transition_stage_started_ms = current_t
                self._reset_transition_condition_timer()
                self._update_transition_status_panel(
                    current_t, current_slope, current_score, force_show=True
                )

                mark_cfg = self._auto_mark_config(rid)
                if mark_cfg.get('enabled', True):
                    self._add_auto_vial_annotation(
                        current_t,
                        message,
                        r[-1] if len(r) and np.isfinite(r[-1]) else None,
                        g[-1] if len(g) and np.isfinite(g[-1]) else None,
                        b[-1] if len(b) and np.isfinite(b[-1]) else None,
                        current_slope,
                        current_score,
                        stage_key=rid,
                    )
                should_notify = bool(
                    notifications_enabled and mark_cfg.get('notify', True)
                )
                if should_notify:
                    self._show_transition_alert(message)
                if mark_cfg.get('sound', True):
                    self._play_system_alert_sound()

                print(
                    f'⚠️ Transition alert: {label} | '
                    f't={current_t / 60000.0:.2f} min | '
                    f'slope30 current={current_slope:.3f}, '
                    f'median5s={median_slope:.3f}, '
                    f'min5s={peak_neg_slope:.3f}, max5s={peak_pos_slope:.3f} | '
                    f'score current={current_score:.3f}, max5s={peak_score:.3f} | '
                    f'stage->{next_stage}'
                )

            if stage == 'arom':
                if not arom_enabled:
                    return
                cfg_arom = self._auto_mark_config('arom')
                t_min_ms = max(0.0, float(self._notification_value('auto_mark_arom_t_min_sec', AROM_T_MIN_SEC))) * 1000.0
                t_max_sec = float(self._notification_value('auto_mark_arom_t_max_sec', AROM_T_MAX_SEC))
                t_max_ms = float('inf') if t_max_sec <= 0.0 else t_max_sec * 1000.0
                if t_min_ms <= current_t <= t_max_ms:
                    slope_std = float(self._notification_value('auto_mark_arom_slope_std', AROM_SLOPE_STANDARD))
                    slope_strong = float(self._notification_value('auto_mark_arom_slope_strong', AROM_SLOPE_STRONG))
                    score_std = float(self._notification_value('auto_mark_arom_score_std', AROM_SCORE_STANDARD))
                    score_strong = float(self._notification_value('auto_mark_arom_score_strong', AROM_SCORE_STRONG))

                    positive_share = float(np.mean(ss >= (slope_std * 0.8))) if len(ss) else 0.0
                    standard_hit = (
                        median_slope >= slope_std and
                        peak_score >= score_std and
                        positive_share >= 0.35
                    )
                    strong_hit = (
                        peak_pos_slope >= slope_strong and
                        peak_score >= score_strong and
                        (float(np.mean(ss >= slope_std)) >= 0.20 if len(ss) else False)
                    )
                    instant_hit = (
                        np.isfinite(current_slope) and np.isfinite(current_score) and
                        current_slope >= slope_strong and current_score >= score_strong
                    )
                    if valid_signal and (standard_hit or strong_hit or instant_hit):
                        fire_alert(
                            'arom', 'AROM',
                            cfg_arom.get('message', 'ОБНАРУЖЕН ПЕРЕХОД SAT → AROM\nСМЕНИТЕ ПРИЁМНУЮ ВИАЛУ'),
                            'delay_br',
                        )
                return

            if stage in ('delay_br', 'delay_abr'):
                return

            if stage == 'br':
                if not br_enabled:
                    return
                cfg_br = self._auto_mark_config('br')
                t_min_ms = max(0.0, float(self._notification_value('auto_mark_br_t_min_sec', BR_T_MIN_SEC))) * 1000.0
                t_max_sec = float(self._notification_value('auto_mark_br_t_max_sec', BR_T_MAX_SEC))
                t_max_ms = float('inf') if t_max_sec <= 0.0 else t_max_sec * 1000.0
                slope_th = float(self._notification_value('auto_mark_br_slope_th', BR_SLOPE_THRESHOLD))
                score_th = float(self._notification_value('auto_mark_br_score_th', BR_SCORE_THRESHOLD))
                confirm_ms = float(self._notification_value('auto_mark_br_confirm_sec', BR_CONFIRM_MS / 1000.0)) * 1000.0

                if t_min_ms <= current_t <= t_max_ms:
                    br_condition = (
                        np.isfinite(current_slope) and
                        np.isfinite(current_score) and
                        current_slope > slope_th and
                        current_score > score_th
                    )
                    if self._condition_held(
                        br_condition, current_t, confirm_ms, 'br_standard'
                    ):
                        fire_alert(
                            'br', 'BR',
                            cfg_br.get('message', 'ОБНАРУЖЕН ПЕРЕХОД AROM → BR\nСМЕНИТЕ ПРИЁМНУЮ ВИАЛУ'),
                            'delay_abr',
                        )
                return

            if stage == 'abr':
                if not abr_enabled:
                    return
                cfg_abr = self._auto_mark_config('abr')
                t_min_ms = max(0.0, float(self._notification_value('auto_mark_abr_t_min_sec', ABR_T_MIN_SEC))) * 1000.0
                t_max_sec = float(self._notification_value('auto_mark_abr_t_max_sec', ABR_T_MAX_SEC))
                t_max_ms = float('inf') if t_max_sec <= 0.0 else t_max_sec * 1000.0
                slope_th = float(self._notification_value('auto_mark_abr_slope_th', ABR_SLOPE_THRESHOLD))
                score_th = float(self._notification_value('auto_mark_abr_score_th', ABR_SCORE_THRESHOLD))
                strong_slope_th = float(self._notification_value('auto_mark_abr_strong_slope_th', ABR_STRONG_SLOPE_THRESHOLD))
                strong_score_th = float(self._notification_value('auto_mark_abr_strong_score_th', ABR_STRONG_SCORE_THRESHOLD))
                confirm_ms = float(self._notification_value('auto_mark_abr_confirm_sec', ABR_CONFIRM_MS / 1000.0)) * 1000.0

                if t_min_ms <= current_t <= t_max_ms:
                    strong_condition = (
                        np.isfinite(current_slope) and
                        np.isfinite(current_score) and
                        current_slope <= strong_slope_th and
                        current_score >= strong_score_th
                    )
                    standard_condition = (
                        np.isfinite(current_slope) and
                        np.isfinite(current_score) and
                        current_slope <= slope_th and
                        current_score >= score_th
                    )

                    if strong_condition:
                        hit = self._condition_held(
                            True, current_t, ABR_STRONG_CONFIRM_MS, 'abr_strong'
                        )
                    elif standard_condition:
                        hit = self._condition_held(
                            True, current_t, confirm_ms, 'abr_standard'
                        )
                    else:
                        self._reset_transition_condition_timer()
                        hit = False

                    if hit:
                        fire_alert(
                            'abr', 'ABR',
                            cfg_abr.get('message', 'ОБНАРУЖЕН ПЕРЕХОД BR → ABR\nСМЕНИТЕ ПРИЁМНУЮ ВИАЛУ'),
                            'done',
                        )
                return

        except Exception as e:
            print(f'⚠️ Ошибка проверки transition alerts: {e}')

        except Exception as e:
            print(f'⚠️ Ошибка проверки transition alerts: {e}')

    def _show_transition_alert(self, message):
        try:
            if not hasattr(self, 'transition_alert_label') or self.transition_alert_label is None:
                return
            formatted_text = f"⚠️  {message}\n(нажмите в любое место уведомления, чтобы закрыть ✕)"
            self.transition_alert_label.setText(formatted_text)
            self.transition_alert_label.show()

            # Showing the notification changes the main QVBoxLayout geometry.
            # Rebuild immediately after Qt processes that change; otherwise
            # graph_scroll retains the height from the hidden-alert state. A
            # manual grid change used to trigger this rebuild, which is why the
            # bug disappeared as soon as the user switched 2xN/3xN/etc.
            try:
                self.layout.activate()
                self.central_widget.updateGeometry()
            except Exception:
                pass
            try:
                self._schedule_graph_layout_rebuild(0)
                self.QtCore.QTimer.singleShot(50, self._rebuild_graph_layout)
            except Exception:
                pass

            self._transition_alert_hide_timer.start(int(TRANSITION_ALERT_DISPLAY_MS))
            self._show_toast(message.replace('\n', ' — '))
        except Exception as e:
            print(f'⚠️ Ошибка transition alert: {e}')

    def _auto_mark_config(self, stage_key):
        """Configuration for built-in markers from user settings."""
        colors = get_palette(getattr(self, 'theme_mode', 'dark') == 'light')
        defaults = {
            'arom': (colors['success'], 'Смена виалы · SAT → AROM', 'Обнаружен переход SAT → AROM\nСмените приёмную виалу'),
            'br': (colors['warning'], 'Смена виалы · AROM → BR', 'Обнаружен переход AROM → BR\nСмените приёмную виалу'),
            'abr': (colors['danger'], 'Смена виалы · BR → ABR', 'Обнаружен переход BR → ABR\nСмените приёмную виалу'),
        }
        def_color, def_label, def_msg = defaults.get(stage_key, (colors['success'], 'Смена виалы', 'Смените приёмную виалу'))
        cfg = self.notification_settings or {}
        color = str(cfg.get(f'auto_mark_{stage_key}_color', def_color))
        label = str(cfg.get(f'auto_mark_{stage_key}_label', def_label))
        message = str(cfg.get(f'auto_mark_{stage_key}_message', def_msg))
        enabled = bool(cfg.get(f'auto_mark_{stage_key}_enabled', True)) and bool(cfg.get('auto_marks_enabled', True))
        notify = enabled and bool(cfg.get(f'auto_mark_{stage_key}_notify', True)) and bool(cfg.get('notifications_enabled', True))
        sound = enabled and bool(cfg.get(f'auto_mark_{stage_key}_sound', True)) and bool(cfg.get('sound_alerts_enabled', True))
        return {
            'enabled': enabled,
            'notify': notify,
            'sound': sound,
            'color': color,
            'description': label,
            'message': message,
        }

    def _add_auto_vial_annotation(self, time_ms, message, r, g, b, slope30, transition_score, stage_key='arom'):
        try:
            if not self._has_plot_data():
                return
            cfg = self._auto_mark_config(stage_key)
            if not cfg['enabled']:
                return
            ann = self.annotation_manager.add_annotation(
                time_ms,
                cfg['description'],
                color=cfg['color'],
                is_auto=True,
                r=r,
                g=g,
                b=b,
                rgb_sum_slope_30s=slope30,
                transition_score=transition_score,
            )
            self._update_annotations()
            self._persist_annotations()
            if bool(self.notification_settings.get('notifications_enabled', TRANSITION_ALERTS_ENABLED)) and cfg['notify']:
                self._show_toast(f"📌 Авто-метка: {cfg['description']}")
        except Exception as e:
            print(f'⚠️ Ошибка создания авто-метки: {e}')

                                               
    def set_session_excel(self, excel_path):
        self.session_excel_path = excel_path

    def _persist_annotations(self):
        if not self.session_excel_path:
            return
        path = self.session_excel_path
        manager = self.annotation_manager

        def _save():
            try:
                from ..data.excel_exporter import save_annotations_to_workbook
                save_annotations_to_workbook(path, manager)
            except Exception as e:
                print(f"⚠️ Не удалось сохранить метки в Excel: {e}")

        self.QtCore.QTimer.singleShot(0, _save)

    def _add_annotation_current(self):
        if not self._has_plot_data():
            self._show_toast("⚠️ Нет данных для добавления метки")
            return
        current_time = float(self._cached_xs[-1])
        ann = self.annotation_manager.add_annotation(
            current_time,
            f"Метка {len(self.annotation_manager.annotations) + 1}"
        )
        self._update_annotations()
        self._persist_annotations()
        self._refresh_plot()
        self._show_toast(f"📌 Метка добавлена: {ann.description}")

    def _add_annotation_dialog(self):
        if not self._has_plot_data():
            self._show_toast("⚠️ Нет данных для добавления метки")
            return
        time_ms = float(self._cached_xs[-1])
        self._open_annotation_dialog(time_ms)

    def _open_annotation_dialog(self, time_ms):
        if self._annotation_dialog_open:
            return
        self._annotation_dialog_open = True

        try:
            dialog = self.QtWidgets.QDialog(self.win)
            dialog.setWindowFlags((dialog.windowFlags() | self.QtCore.Qt.WindowStaysOnTopHint) & ~self.QtCore.Qt.WindowContextHelpButtonHint)
            dialog.setWindowTitle("Добавить метку")
            dialog.setMinimumWidth(420)
            dialog.setWindowModality(self.QtCore.Qt.ApplicationModal)
            self._active_annotation_dialog = dialog

            layout = self.QtWidgets.QVBoxLayout()

            time_label = self.QtWidgets.QLabel(
                f"⏱️ Время: {time_ms:.0f} мс ({time_ms / 1000:.1f} с)"
            )
            time_label.setStyleSheet("font-weight: bold; font-size: 12px;")
            layout.addWidget(time_label)

            layout.addWidget(self.QtWidgets.QLabel("📝 Описание:"))
            desc_edit = self.QtWidgets.QLineEdit()
            desc_edit.setPlaceholderText("Введите описание метки...")
            layout.addWidget(desc_edit)

            layout.addWidget(self.QtWidgets.QLabel("🎨 Цвет:"))
            color_combo = self.QtWidgets.QComboBox()
            color_combo.setIconSize(self.QtCore.QSize(32, 32))
            for color in AnnotationManager.COLORS:
                color_combo.addItem(self._color_icon(color), " ", color)
            layout.addWidget(color_combo)

            btn_layout = self.QtWidgets.QHBoxLayout()
            ok_btn = self.QtWidgets.QPushButton("✅ Добавить")
            cancel_btn = self.QtWidgets.QPushButton("❌ Отмена")
            btn_layout.addWidget(ok_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)
            dialog.setLayout(layout)

            def on_ok():
                description = desc_edit.text().strip() or (
                    f"Метка {len(self.annotation_manager.annotations) + 1}"
                )
                color = self._combo_color(color_combo)
                self.annotation_manager.add_annotation(time_ms, description, color)
                self._update_annotations()
                self._persist_annotations()
                self._refresh_plot()
                self._show_toast(f"📌 Метка добавлена: {description}")
                dialog.accept()

            ok_btn.clicked.connect(on_ok)
            cancel_btn.clicked.connect(dialog.reject)
            desc_edit.returnPressed.connect(on_ok)

            desc_edit.setFocus()
            dialog.exec_()
        finally:
            self._annotation_dialog_open = False
            self._active_annotation_dialog = None

    def _color_icon(self, hex_color, size=32):
        pixmap = self.QtGui.QPixmap(size, size)
        pixmap.fill(self.QtGui.QColor(hex_color))
        painter = self.QtGui.QPainter(pixmap)
        painter.setPen(self.QtGui.QPen(self.QtGui.QColor('#333333')))
        painter.drawRect(1, 1, size - 2, size - 2)
        painter.end()
        return self.QtGui.QIcon(pixmap)

    def _combo_color(self, color_combo):
        data = color_combo.currentData()
        if data:
            return str(data)
        idx = color_combo.currentIndex()
        if 0 <= idx < len(AnnotationManager.COLORS):
            return AnnotationManager.COLORS[idx]
        return AnnotationManager.COLORS[0]

    def _show_annotations_list(self):
        annotations = self.annotation_manager.get_annotations()
        if not annotations:
            self._show_toast("📭 Нет добавленных меток")
            return

        dialog = self.QtWidgets.QDialog(self.win)
        dialog.setWindowFlags((dialog.windowFlags() | self.QtCore.Qt.WindowStaysOnTopHint) & ~self.QtCore.Qt.WindowContextHelpButtonHint)
        dialog.setWindowTitle("📋 Список меток")
        dialog.setMinimumSize(500, 400)
        dialog.setWindowModality(self.QtCore.Qt.ApplicationModal)

        layout = self.QtWidgets.QVBoxLayout()

        info_label = self.QtWidgets.QLabel(f"Всего меток: {len(annotations)}")
        info_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(info_label)

        list_widget = self.QtWidgets.QListWidget()
        list_widget.setSelectionMode(self.QtWidgets.QAbstractItemView.SingleSelection)
        for i, ann in enumerate(annotations):
            time_str = f"{ann.time_ms:.0f} мс ({ann.time_ms/1000:.1f} с)"
            item_text = f"{i+1}. {time_str}  -  {ann.description}"
            list_widget.addItem(self.QtWidgets.QListWidgetItem(item_text))
        layout.addWidget(list_widget)

        btn_layout = self.QtWidgets.QHBoxLayout()
        delete_btn = self.QtWidgets.QPushButton("🗑️ Удалить выбранную")
        goto_btn = self.QtWidgets.QPushButton("🔍 Перейти к метке")
        close_btn = self.QtWidgets.QPushButton("❌ Закрыть")
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(goto_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dialog.setLayout(layout)

        def delete_selected():
            current = list_widget.currentRow()
            if current >= 0:
                self.annotation_manager.remove_annotation(current)
                self._update_annotations()
                self._persist_annotations()
                self._refresh_plot()
                list_widget.takeItem(current)
                self._show_toast("🗑️ Метка удалена")
                remaining = len(self.annotation_manager.get_annotations())
                info_label.setText(f"Всего меток: {remaining}")
                if remaining == 0:
                    dialog.accept()

        def goto_selected():
            current = list_widget.currentRow()
            if current >= 0 and current < len(annotations):
                self._goto_annotation(annotations[current])
                dialog.accept()

        delete_btn.clicked.connect(delete_selected)
        goto_btn.clicked.connect(goto_selected)
        close_btn.clicked.connect(dialog.accept)
        list_widget.itemDoubleClicked.connect(lambda: goto_selected())
        dialog.exec_()

    def _clear_annotations(self):
        if self.annotation_manager.get_annotations():
            reply = self._ask_yes_no("Подтверждение", "Удалить все метки?")
            if reply == self.QtWidgets.QMessageBox.Yes:
                self.annotation_manager.clear()
                self._update_annotations()
                self._persist_annotations()
                self._refresh_plot()
                self._show_toast("🗑️ Все метки удалены")

    def _ask_yes_no(self, title, text):
        box = self.QtWidgets.QMessageBox(self.win)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No
        )
        box.setDefaultButton(self.QtWidgets.QMessageBox.No)
        box.setWindowModality(self.QtCore.Qt.ApplicationModal)
        box.setWindowFlag(self.QtCore.Qt.WindowStaysOnTopHint, True)
        return box.exec_()

    def _goto_annotation(self, ann):
        self._ignore_view_change = True
        x_pos = self._ms_to_display(ann.time_ms)
        margin_ms = self._plot_time_span_ms()
        margin = self._ms_to_display(margin_ms)
        try:
            for plot_item in (self.plot, self.log_plot, self.log_bg_plot,
                              self.rgb_sum_slope_plot, self.transition_score_plot):
                plot_item.setXRange(x_pos - margin, x_pos + margin, padding=0.02)
        finally:
            self._ignore_view_change = False
        self._show_toast(f"🔍 Переход к: {ann.description}")

    def _plot_time_span_ms(self):
        if not self._has_plot_data():
            return 5000
        try:
            return max(5000, float(self._cached_xs[-1] - self._cached_xs[0]) * 0.1)
        except Exception:
            return 5000

    def _has_plot_data(self):
        try:
            return len(self._cached_xs) > 0
        except TypeError:
            return False

    def _update_annotations(self):
        if not hasattr(self, 'annotation_lines') or not hasattr(self, 'plot') or self.plot is None:
            return
        try:
            for line in self.annotation_lines:
                self.plot.removeItem(line)
            self.annotation_lines = []

            for line in self.log_annotation_lines:
                self.log_plot.removeItem(line)
            self.log_annotation_lines = []

            for line in self.log_bg_annotation_lines:
                self.log_bg_plot.removeItem(line)
            self.log_bg_annotation_lines = []

            for line in self.slope_annotation_lines:
                self.rgb_sum_slope_plot.removeItem(line)
            self.slope_annotation_lines = []

            for line in getattr(self, 'score_annotation_lines', []):
                try:
                    self.transition_score_plot.removeItem(line)
                except Exception:
                    pass
            self.score_annotation_lines = []

            for line, p in getattr(self, 'custom_annotation_lines', []):
                try:
                    p.removeItem(line)
                except Exception:
                    pass
            self.custom_annotation_lines = []

            for text in self.annotation_texts:
                self.plot.removeItem(text)
            self.annotation_texts = []

            pen_style = self.QtCore.Qt.DashLine
            for ann in self.annotation_manager.get_annotations():
                x_pos = self._ms_to_display(float(ann.time_ms))
                pen = self.pg.mkPen(ann.color, width=2, style=pen_style)

                rgb_line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen)
                self.plot.addItem(rgb_line)
                self.annotation_lines.append(rgb_line)

                log_line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen)
                self.log_plot.addItem(log_line)
                self.log_annotation_lines.append(log_line)

                log_bg_line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen)
                self.log_bg_plot.addItem(log_bg_line)
                self.log_bg_annotation_lines.append(log_bg_line)

                slope_line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen)
                self.rgb_sum_slope_plot.addItem(slope_line)
                self.slope_annotation_lines.append(slope_line)

                score_line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen)
                self.transition_score_plot.addItem(score_line)
                self.score_annotation_lines.append(score_line)

                for item in getattr(self, 'custom_graphs', []):
                    p = item.get('plot')
                    if p is not None:
                        c_line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen)
                        p.addItem(c_line)
                        self.custom_annotation_lines.append((c_line, p))

                y_val = 0
                if self._has_plot_data():
                    idx = min(
                        range(len(self._cached_xs)),
                        key=lambda i: abs(float(self._cached_xs[i]) - float(ann.time_ms))
                    )
                    if idx < len(self._cached_r):
                        y_val = max(
                            float(self._cached_r[idx]) if idx < len(self._cached_r) else 0,
                            float(self._cached_g[idx]) if idx < len(self._cached_g) else 0,
                            float(self._cached_b[idx]) if idx < len(self._cached_b) else 0
                        )

                text_item = self.pg.TextItem(
                    text=f"📌 {ann.description}",
                    color=ann.color,
                    anchor=(0, 1),
                    border=self.pg.mkPen(ann.color, width=1),
                    fill=self.pg.mkBrush('k' if self.theme_mode == 'dark' else 'w')
                )
                y_pos = y_val + 15 if y_val < 200 else y_val - 15
                text_item.setPos(x_pos, y_pos)
                self.plot.addItem(text_item)
                self.annotation_texts.append(text_item)
        except Exception as e:
            print(f"⚠️ Ошибка отображения меток: {e}")
            traceback.print_exc()

                                                              
    def _safe_call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            print(f"⚠️ Ошибка UI: {e}")
            traceback.print_exc()
            self._show_toast(f"⚠️ Ошибка: {e}")
            return None

    def _show_toast(self, message):
        self.pts_label.setText(str(message))
        self.QtCore.QTimer.singleShot(3000, lambda: self.pts_label.setText(f'Точки · {self._cached_pts}'))

    def _refresh_plot(self):
        if not self._has_plot_data():
            return
        try:
            self.set_data(
                self._cached_xs, self._cached_r, self._cached_g, self._cached_b,
                log_vals=self._cached_log, log_bg_vals=self._cached_log_bg,
                tri_x_vals=self._cached_tri_x, tri_y_vals=self._cached_tri_y,
                rgb_sum_vals=self._cached_rgb_sum,
                rgb_sum_smooth_vals=self._cached_rgb_sum_smooth,
                rgb_sum_slope10_vals=self._cached_rgb_sum_slope10,
                rgb_sum_slope30_vals=self._cached_rgb_sum_slope30,
                rgb_vector_speed30_vals=self._cached_rgb_vector_speed30,
                chromaticity_speed30_vals=self._cached_chromaticity_speed30,
                k_chrom_previous_vals=self._cached_k_chrom_previous,
                log_ratio_speed30_vals=self._cached_log_ratio_speed30,
                rgb_sum_acceleration30_vals=self._cached_rgb_sum_acceleration30,
                transition_score_vals=self._cached_transition_score,
                pts=self._cached_pts
            )
        except Exception as e:
            print(f"⚠️ Ошибка обновления графика: {e}")

    def _on_channel_toggle(self, color, checked):
        buttons = {
            'r': self.btn_r,
            'g': self.btn_g,
            'b': self.btn_b
        }
        if not checked:
            other_states = [buttons[k].isChecked() for k in buttons if k != color]
            if not any(other_states):
                buttons[color].setChecked(True)
                return
        self.show_r = self.btn_r.isChecked()
        self.show_g = self.btn_g.isChecked()
        self.show_b = self.btn_b.isChecked()
        self._refresh_plot()

    def _on_log_toggle(self, checked):
        self.show_log = bool(checked)
        self.log_btn.setText('Log B/R · B/G' if checked else 'Log выключен')
        # Logs are independent graph items. Never hide their parent container,
        # because the plots themselves live in the main grid.
        for item in getattr(self, '_graph_items', []):
            if item.get('kind') == 'log':
                item['visible'] = bool(checked)
        self._rebuild_graph_layout()
        self._refresh_plot()

    def _on_track_toggled(self, checked):
        self._autoscroll = checked
        self.track_btn.setText('Автообзор' if checked else 'Ручной режим')
        if checked:
            self._refresh_plot()

    def _on_manual_range_changed(self, source_view_box=None):
        if getattr(self, '_ignore_view_change', False):
            return
        self._autoscroll = False
        try:
            self.track_btn.blockSignals(True)
            self.track_btn.setChecked(False)
            self.track_btn.setText('Ручной режим')
            source_plot = None
            for item in getattr(self, '_graph_items', []):
                widget = item.get('widget')
                try:
                    if widget is not None and widget.getPlotItem().getViewBox() is source_view_box:
                        source_plot = widget.getPlotItem()
                        break
                except Exception:
                    pass
            if source_plot is not None:
                xr = source_plot.getViewBox().viewRange()[0]
                self._sync_all_x_ranges(float(xr[0]), float(xr[1]))
        finally:
            self.track_btn.blockSignals(False)

    def _reset_view(self):
        self._autoscroll = True
        self.track_btn.blockSignals(True)
        self.track_btn.setChecked(True)
        self.track_btn.setText('Автообзор')
        self.track_btn.blockSignals(False)
        self._refresh_plot()
        self._show_toast("🔄 TRACK: автообзор графика")

    def _cycle_unit(self):
        order = ['MS', 'SEC', 'MIN']
        old_mode = self.unit_mode
        index = order.index(old_mode)
        self.unit_mode = order[(index + 1) % len(order)]
        self.unit_btn.setText(f'ВРЕМЯ · {self.unit_mode}')
        self._update_axis_labels()
        self.log_plot.setLabel('bottom', 'Time', units=self.unit_mode)

        if self._has_plot_data():
            try:
                x_range = self.plot.getViewBox().viewRange()[0]
                ms_min = self._display_to_ms(x_range[0], old_mode)
                ms_max = self._display_to_ms(x_range[1], old_mode)
                new_min = self._ms_to_display(ms_min, self.unit_mode)
                new_max = self._ms_to_display(ms_max, self.unit_mode)
                if new_min != new_max:
                    self._shared_x_range_display = (float(new_min), float(new_max))
                    self._ignore_view_change = True
                    try:
                        self._sync_all_x_ranges(new_min, new_max)
                    finally:
                        self._ignore_view_change = False
            except Exception:
                pass

        self._refresh_plot()


    def _on_pick_mode_toggled(self, checked):
        self._pick_annotation_mode = checked
        if checked:
            self.ann_pick_btn.setText('Выберите точку')
            self._show_toast('Кликните на график для метки')
        else:
            self.ann_pick_btn.setText('По точке')

    def _on_plot_mouse_clicked(self, evt, widget):
        try:
            is_left = (evt.button() == self.QtCore.Qt.LeftButton)
        except Exception:
            is_left = True
        if not is_left:
            return

        try:
            is_double = bool(evt.double())
        except Exception:
            is_double = False

        if is_double and not self._pick_annotation_mode:
            self._reset_view()
            try:
                evt.accept()
            except Exception:
                pass
            return

        try:
            plot_item = widget.getPlotItem() if hasattr(widget, 'getPlotItem') else getattr(widget, 'plotItem', None)
            if plot_item is None:
                return
            vb = plot_item.vb
            scene_pos = evt.scenePos()
            if hasattr(vb, 'sceneBoundingRect'):
                if not vb.sceneBoundingRect().contains(scene_pos):
                    return
            view_pos = vb.mapSceneToView(scene_pos)
            time_ms = self._display_to_ms(view_pos.x())
        except Exception as err:
            return

        if self._pick_annotation_mode:
            try:
                self.ann_pick_btn.setChecked(False)
            except Exception:
                self._pick_annotation_mode = False
            self._open_annotation_dialog(time_ms)
            try:
                evt.accept()
            except Exception:
                pass
            return

        # В режиме анализа видеофайла одиночный клик без PICK перематывает видео
        if self.is_video_file:
            self._pending_playback_actions.append(('seek_time_ms', max(0.0, float(time_ms))))
            self._update_playhead_needle(max(0.0, float(time_ms)))
            try:
                evt.accept()
            except Exception:
                pass
            return

    def _on_fullscreen(self):
        if self.fs_btn.isChecked():
            self.win.showFullScreen()
            self.fs_btn.setText('Оконный режим')
        else:
            self.win.showNormal()
            self.fs_btn.setText('На весь экран')

        # The native window may commit its new geometry one event-loop turn
        # after showFullScreen()/showNormal().  Rebuild after that geometry is
        # available as well; the QMainWindow resizeEvent handles subsequent
        # live resizing.
        self._schedule_graph_layout_rebuild(0)
        self.QtCore.QTimer.singleShot(80, self._rebuild_graph_layout)

    def _request_stop_analysis(self):
        now = time.time()
        if self.stop_requested:
            return
        if now <= self._stop_confirm_deadline:
            self.stop_requested = True
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText('Сохраняем…')
            self._show_toast('Остановка анализа. Сначала сохраняется CSV/Excel...')
            return

        self._stop_confirm_deadline = now + 5.0
        self.stop_btn.setText('Нажмите ещё раз для остановки')
        self.stop_btn.setStyleSheet(f'background-color: {get_palette(self.theme_mode == "light")["warning"]}; color: {get_palette(self.theme_mode == "light")["accent_on"]}; font-weight: bold; border: none; border-radius: 5px;')
        self._show_toast('Для остановки нажмите STOP ещё раз в течение 5 секунд')
        self.QtCore.QTimer.singleShot(5200, self._reset_stop_button_if_needed)

    def _reset_stop_button_if_needed(self):
        if self.stop_requested:
            return
        if time.time() > self._stop_confirm_deadline:
            self._stop_confirm_deadline = 0.0
            self.stop_btn.setText('Остановить')
            self.stop_btn.setStyleSheet(f'background-color: {get_palette(self.theme_mode == "light")["danger"]}; color: {get_palette(self.theme_mode == "light")["danger_on"]}; font-weight: bold; border: none; border-radius: 5px;')

    def take_video_resize_request(self):
        factor = self._video_resize_request
        self._video_resize_request = None
        return factor

    def _on_player_toggle_pause(self):
        self._pending_playback_actions.append(('toggle_pause', None))

    def _on_player_restart(self):
        self._pending_playback_actions.append(('restart', None))

    def _on_player_seek_rel(self, delta_sec):
        self._pending_playback_actions.append(('seek_rel', float(delta_sec)))

    def _on_player_speed_changed(self, idx):
        if hasattr(self, 'player_speed_combo'):
            val = self.player_speed_combo.itemData(idx)
            if val is not None:
                self._pending_playback_actions.append(('set_speed', float(val)))

    def _on_player_slider_pressed(self):
        self._slider_is_down = True

    def _on_player_slider_released(self):
        self._slider_is_down = False
        if hasattr(self, 'player_slider'):
            val = self.player_slider.value()
            self._pending_playback_actions.append(('seek_frame', int(val)))

    def take_playback_actions(self):
        actions = list(self._pending_playback_actions)
        self._pending_playback_actions.clear()
        return actions

    def update_playback_hud(self, is_paused, speed, cur_frame, total_frames, elapsed_sec, duration_sec):
        if not getattr(self, 'is_video_file', False):
            return
        try:
            if hasattr(self, 'player_play_btn'):
                if is_paused:
                    self.player_play_btn.setText('▶ СТАРТ')
                    self.player_play_btn.setStyleSheet(f'background-color: {get_palette(self.theme_mode == "light")["success_soft"]}; color: {get_palette(self.theme_mode == "light")["success"]}; font-weight: bold; border: none; border-radius: 5px;')
                else:
                    self.player_play_btn.setText('⏸ ПАУЗА')
                    self.player_play_btn.setStyleSheet(f'background-color: {get_palette(self.theme_mode == "light")["warning_soft"]}; color: {get_palette(self.theme_mode == "light")["warning"]}; font-weight: bold; border: none; border-radius: 5px;')

            if hasattr(self, 'player_speed_combo'):
                for idx in range(self.player_speed_combo.count()):
                    v = self.player_speed_combo.itemData(idx)
                    if v is not None and abs(float(v) - float(speed)) < 0.05:
                        if self.player_speed_combo.currentIndex() != idx:
                            self.player_speed_combo.blockSignals(True)
                            self.player_speed_combo.setCurrentIndex(idx)
                            self.player_speed_combo.blockSignals(False)
                        break

            if hasattr(self, 'player_slider') and not self._slider_is_down:
                if total_frames > 0 and self.player_slider.maximum() != total_frames:
                    self.player_slider.setMaximum(total_frames)
                self.player_slider.blockSignals(True)
                self.player_slider.setValue(int(cur_frame))
                self.player_slider.blockSignals(False)

            if hasattr(self, 'player_time_label'):
                cur_m = int(elapsed_sec // 60)
                cur_s = int(elapsed_sec % 60)
                dur_m = int(duration_sec // 60)
                dur_s = int(duration_sec % 60)
                pct = int((cur_frame / total_frames * 100)) if total_frames > 0 else 0
                self.player_time_label.setText(f"⏱ {cur_m:02d}:{cur_s:02d} / {dur_m:02d}:{dur_s:02d} ({pct}%) [{cur_frame}/{total_frames}]")

            # Обновление вертикального визира текущего кадра на всех графиках
            self._update_playhead_needle(elapsed_sec * 1000.0)
        except Exception:
            pass

    def _update_playhead_needle(self, time_ms):
        """Отображает вертикальный визир текущего момента видео на всех активных графиках."""
        try:
            x_pos = self._ms_to_display(float(time_ms))
            pen = self.pg.mkPen(get_palette(self.theme_mode == 'light')['accent'], width=2.3, style=self.QtCore.Qt.SolidLine)

            plots = [self.plot, self.log_plot, self.log_bg_plot, self.rgb_sum_slope_plot, self.transition_score_plot]
            for item in getattr(self, 'custom_graphs', []):
                if 'plot' in item and item['plot'] is not None:
                    plots.append(item['plot'])

            if not hasattr(self, '_playhead_lines') or len(self._playhead_lines) != len(plots):
                if hasattr(self, '_playhead_lines'):
                    for line, plot_item in self._playhead_lines:
                        try:
                            plot_item.removeItem(line)
                        except Exception:
                            pass
                self._playhead_lines = []
                for p in plots:
                    try:
                        line = self.pg.InfiniteLine(pos=x_pos, angle=90, pen=pen, movable=False)
                        p.addItem(line)
                        self._playhead_lines.append((line, p))
                    except Exception:
                        pass
            else:
                for line, p in self._playhead_lines:
                    try:
                        line.setPos(x_pos)
                        line.setPen(pen)
                    except Exception:
                        pass
        except Exception:
            pass

