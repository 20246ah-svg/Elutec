import json
import time
import numpy as np
import cv2
import os
import traceback
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from ..gui.live_graph import LiveGraphWindow
from ..analysis.camera_worker import CameraWorker
from ..analysis.video_recorder import AsyncVideoRecorder
from ..data.excel_exporter import create_session_excel, save_to_excel, save_annotations_to_workbook, save_graph_to_image
from ..data.csv_logger import CsvLogger
from ..utils.helpers import (
    create_video_capture, warmup_capture, read_valid_frame,
    is_network_source, is_placeholder_frame, is_video_file_source,
    is_video_file_path, ivcam_setup_hint, detect_green_circle_roi,
    repair_video_file_if_needed, compute_roi_means
)
from ..utils.ffmpeg_utils import find_ffmpeg_exe
from ..config import (
    FFMPEG_PIPE_OUTPUT_FPS, MAX_POINTS, DEFAULT_GRAPH_UPDATE_MS, DEFAULT_PLAYER_HUD_METRICS
)


_UNICODE_FONT_CACHE = {}

def _get_unicode_font(size=12, bold=False):
    key = (size, bold)
    if key in _UNICODE_FONT_CACHE:
        return _UNICODE_FONT_CACHE[key]
    candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "tahomabd.ttf" if bold else "tahoma.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\tahomabd.ttf" if bold else "C:\\Windows\\Fonts\\tahoma.ttf"
    ]
    for c in candidates:
        try:
            f = ImageFont.truetype(c, size)
            _UNICODE_FONT_CACHE[key] = f
            return f
        except Exception:
            continue
    try:
        f = ImageFont.load_default()
        _UNICODE_FONT_CACHE[key] = f
        return f
    except Exception:
        return None


def _render_sidebar_hud_pil(shown, hud_x, hud_y, hud_w, hud_h, time_str, items_data):
    """
    Высококачественный рендеринг боковой информационной HUD-панели видеоплеера с поддержкой
    кириллицы (Unicode) и авто-выравниванием значений без перекрытий.
    """
    sub = shown[hud_y:hud_y+hud_h, hud_x:hud_x+hud_w]
    if sub.size == 0 or sub.shape[0] != hud_h or sub.shape[1] != hud_w:
        return

    hud_overlay = sub.copy()
    cv2.rectangle(hud_overlay, (0, 0), (hud_w, hud_h), (14, 18, 26), -1)
    cv2.addWeighted(hud_overlay, 0.88, sub, 0.12, 0, sub)
    cv2.rectangle(sub, (0, 0), (hud_w - 1, hud_h - 1), (48, 62, 80), 1)

    # Кнопка [+ SELECT]
    btn_w, btn_h = 70, 20
    bx1 = hud_w - btn_w - 6
    by1 = 5
    cv2.rectangle(sub, (bx1, by1), (bx1 + btn_w, by1 + btn_h), (25, 36, 52), -1)
    cv2.rectangle(sub, (bx1, by1), (bx1 + btn_w, by1 + btn_h), (0, 200, 240), 1)

    # Разделитель
    header_h = 32
    cv2.line(sub, (6, header_h), (hud_w - 6, header_h), (40, 52, 70), 1)

    pil_sub = Image.fromarray(cv2.cvtColor(sub, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_sub)

    font_head = _get_unicode_font(13, bold=True)
    font_btn = _get_unicode_font(10, bold=True)
    font_lbl = _get_unicode_font(11, bold=False)
    font_val = _get_unicode_font(11, bold=True)

    # Заголовок и время
    draw.text((8, 6), time_str, font=font_head, fill=(0, 255, 160))
    draw.text((bx1 + 8, by1 + 3), '+ SELECT', font=font_btn, fill=(220, 240, 255))

    item_h = 24
    for i, item in enumerate(items_data):
        iy = header_h + i * item_h + 4
        bullet_rgb = item.get('bullet_color', (200, 120, 255))
        draw.ellipse([10, iy + 4, 18, iy + 12], fill=bullet_rgb)

        lbl = str(item.get('label', ''))
        if len(lbl) > 22:
            lbl = lbl[:21] + '…'
        draw.text((24, iy + 1), lbl, font=font_lbl, fill=(210, 220, 230))

        val_str = str(item.get('value', ''))
        if val_str:
            val_rgb = item.get('val_color', (0, 240, 220))
            try:
                tw = draw.textlength(val_str, font=font_val)
            except Exception:
                tw = len(val_str) * 7.0
            draw.text((hud_w - tw - 10, iy + 1), val_str, font=font_val, fill=val_rgb)

    res = cv2.cvtColor(np.array(pil_sub), cv2.COLOR_RGB2BGR)
    shown[hud_y:hud_y+hud_h, hud_x:hud_x+hud_w] = res


def _render_picker_popup_pil(shown, p_x, p_y, p_w, p_h, all_metrics, curr_sel_set, hx, hy):
    """
    Рендеринг интерактивного меню выбора метрик HUD с поддержкой кириллицы (Unicode).
    """
    sub = shown[p_y:p_y+p_h, p_x:p_x+p_w]
    if sub.size == 0 or sub.shape[0] != p_h or sub.shape[1] != p_w:
        return

    p_ov = sub.copy()
    cv2.rectangle(p_ov, (0, 0), (p_w, p_h), (12, 16, 24), -1)
    cv2.addWeighted(p_ov, 0.92, sub, 0.08, 0, sub)
    cv2.rectangle(sub, (0, 0), (p_w - 1, p_h - 1), (0, 200, 240), 2)

    # Кнопка закрытия [X]
    cv2.rectangle(sub, (p_w - 24, 6), (p_w - 6, 24), (40, 20, 20), -1)
    cv2.rectangle(sub, (p_w - 24, 6), (p_w - 6, 24), (200, 60, 60), 1)

    header_h = 32
    cv2.line(sub, (4, header_h), (p_w - 4, header_h), (50, 65, 85), 1)

    # Строки метрик и чекбоксы
    row_h = 24
    for i, (m_k, m_lbl) in enumerate(all_metrics):
        ry = header_h + i * row_h
        is_row_hov = (p_x <= hx <= p_x + p_w and p_y + ry <= hy <= p_y + ry + row_h)
        if is_row_hov:
            cv2.rectangle(sub, (2, ry + 1), (p_w - 2, ry + row_h - 1), (30, 48, 68), -1)

        is_active = m_k in curr_sel_set
        cv2.rectangle(sub, (10, ry + 4), (26, ry + 20), (20, 30, 42), -1)
        cv2.rectangle(sub, (10, ry + 4), (26, ry + 20), (0, 220, 200) if is_active else (80, 95, 115), 1)
        if is_active:
            cv2.rectangle(sub, (14, ry + 8), (22, ry + 16), (0, 240, 160), -1)

    # Кнопка «DONE (CLOSE)» внизу
    by = p_h - 30
    is_btn_hov = (p_x + 8 <= hx <= p_x + p_w - 8 and p_y + by <= hy <= p_y + by + 24)
    btn_bg = (25, 120, 60) if is_btn_hov else (20, 90, 45)
    cv2.rectangle(sub, (8, by), (p_w - 8, by + 24), btn_bg, -1)
    cv2.rectangle(sub, (8, by), (p_w - 8, by + 24), (80, 255, 140), 1)

    pil_sub = Image.fromarray(cv2.cvtColor(sub, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_sub)

    font_title = _get_unicode_font(12, bold=True)
    font_row = _get_unicode_font(11, bold=False)
    font_btn = _get_unicode_font(11, bold=True)

    # Заголовок и крестик
    draw.text((10, 8), 'SELECT HUD METRICS', font=font_title, fill=(0, 240, 220))
    draw.text((p_w - 18, 6), '✕', font=font_title, fill=(255, 255, 255))

    # Тексты строк
    for i, (m_k, m_lbl) in enumerate(all_metrics):
        ry = header_h + i * row_h
        is_active = m_k in curr_sel_set
        lbl = str(m_lbl)
        if len(lbl) > 28:
            lbl = lbl[:27] + '…'
        text_color = (245, 245, 245) if is_active else (150, 160, 175)
        draw.text((34, ry + 4), lbl, font=font_row, fill=text_color)

    # Текст кнопки
    draw.text((p_w // 2 - 50, by + 4), 'DONE (CLOSE)', font=font_btn, fill=(255, 255, 255))

    res = cv2.cvtColor(np.array(pil_sub), cv2.COLOR_RGB2BGR)
    shown[p_y:p_y+p_h, p_x:p_x+p_w] = res


def run_analysis(config, parent=None, cap=None):
    """
    Запускает анализ видео с заданной конфигурацией.
    """
    print("🚀 Запуск анализа...")
    source = config['source']
    config['source_is_file'] = is_video_file_source(source)
    save_folder = config['save_folder']
    video_folder = config.get('video_folder') or save_folder
    print(f"💾 Папка сохранения Excel: {save_folder}")
    print(f"🎥 Папка сохранения видео: {video_folder}")

                     
    try:
        from PyQt5 import QtWidgets, QtCore, QtGui
        import pyqtgraph as pg
    except Exception as e:
        msg = (
            "Не удалось загрузить PyQt5/pyqtgraph.\n\n"
            f"{e}\n\n"
            "Попробуйте в терминале:\npip install pyqtgraph PyQt5"
        )
        print(f"❌ {msg}")
        if cap is not None and hasattr(cap, 'release'):
            cap.release()
        if parent is not None:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", msg, parent=parent)
        return

    source_clean = str(source).strip().strip('"').strip("'")
    is_file = is_video_file_source(source_clean) or is_video_file_path(source_clean)
    config['source_is_file'] = is_file

    if cap is None:
        cap = create_video_capture(source_clean)
        if cap is not None and cap.isOpened() and not is_file:
            warmup_capture(cap, frames=2 if is_network_source(source_clean) else 8)

    # Применение параметров сенсора (выдержка, gain, wb) для MiiCam RGB-детектора
    if cap is not None and hasattr(cap, 'apply_settings_dict'):
        try:
            cap.apply_settings_dict(config)
        except Exception:
            pass

    if cap is None or not cap.isOpened():
        if is_file:
            msg = (
                f"Не удалось открыть видеофайл:\n{source_clean}\n\n"
                "Причина: Файл повреждён (отсутствует индекс moov atom) или кодек не поддерживается.\n\n"
                "💡 Решение:\n"
                "• Запустите запись нового видео с камеры («▶ ЗАПУСТИТЬ АНАЛИЗ»)\n"
                "• Либо выберите другой рабочий видеофайл."
            )
        else:
            msg = f"Не удалось открыть камеру (источник: {source_clean}). Проверьте подключение."
        print(f"❌ Ошибка: {msg}")
        if parent is not None:
            from tkinter import messagebox
            messagebox.showerror("Ошибка видеофайла", msg, parent=parent)
        return

    ret, test_frame = read_valid_frame(cap, attempts=10 if is_file else 30)
    if not ret and is_file:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        repaired = repair_video_file_if_needed(source_clean)
        if repaired and os.path.isfile(repaired):
            cap = create_video_capture(repaired)
            if cap is not None and cap.isOpened():
                ret, test_frame = read_valid_frame(cap, attempts=10)
                if ret:
                    source_clean = repaired
                    config['source'] = repaired
    elif not ret and not is_file and not is_network_source(source_clean):
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        cap = create_video_capture(source_clean, None, None)
        if cap is not None and cap.isOpened():
            warmup_capture(cap, frames=4)
            ret, test_frame = read_valid_frame(cap, attempts=20)

    if not ret:
        extra = ''
        try:
            if hasattr(cap, 'get_last_error'):
                extra = cap.get_last_error()
        except Exception:
            extra = ''
        if is_file:
            msg = (
                f"Не удалось получить кадры из видеофайла:\n{source_clean}\n\n"
                "Возможные причины:\n"
                "• Файл повреждён или не был финализирован (ошибка 'moov atom not found' возникает, если запись была прервана до сохранения заголовка MP4)\n"
                "• Файл пуст (0 байт)\n"
                "• Неподдерживаемый видеокодек"
            )
        else:
            msg = "Камера открыта, но кадры не поступают. Проверьте подключение."
        if extra:
            msg += "\n\nДиагностика FFmpeg:\n" + extra[-1800:]
        print(f"❌ Ошибка: {msg}")
        if cap is not None and hasattr(cap, 'release'):
            try:
                cap.release()
            except Exception:
                pass
        if parent is not None:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", msg, parent=parent)
        return

    if (not is_network_source(source) and not config.get('source_is_file')) and is_placeholder_frame(test_frame):
        msg = (
            "Видеопоток не активен (чёрный экран).\n\n"
            + ivcam_setup_hint()
        )
        print(f"❌ Ошибка: {msg}")
        if cap is not None and hasattr(cap, 'release'):
            try:
                cap.release()
            except Exception:
                pass
        if parent is not None:
            from tkinter import messagebox
            messagebox.showwarning("Нет видеопотока", msg, parent=parent)
        return

                         
    WINDOW_NAME = 'Video Source'
    show_video_window = bool(config.get('show_video_window', True))
    if show_video_window:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    # Keep the display aspect ratio equal to the source frame. This makes the
    # mouse-to-frame coordinate mapping deterministic, including 4:3 cameras.
    source_h, source_w = test_frame.shape[:2]

    # Если анализируется видеофайл и включена опция привязки к зеленому кругу — выставляем ROI пиксель в пиксель
    if config.get('source_is_file') and config.get('snap_roi_green_circle_on_file', True):
        circle_res = detect_green_circle_roi(test_frame)
        if circle_res is not None:
            cx, cy, r = circle_res
            config['roi_x'] = max(0, cx - r)
            config['roi_y'] = max(0, cy - r)
            config['roi_w'] = 2 * r
            config['roi_h'] = 2 * r
            config['roi_shape'] = 'circle'
            print(f"🎯 На видео обнаружен записанный зеленый круг: ROI установлен пиксель в пиксель (X={config['roi_x']}, Y={config['roi_y']}, W={config['roi_w']}, H={config['roi_h']})")

    target_w = min(int(config.get('display_max_width', 960)), 1024)
    target_h = 580
    scale = min(target_w / max(1, source_w), target_h / max(1, source_h), 1.0)
    video_window_w = int(max(360, source_w * scale))
    video_window_h = int(max(240, source_h * scale))

    if show_video_window:
        cv2.resizeWindow(WINDOW_NAME, video_window_w, video_window_h)

    # ROI can be moved and resized while analysis continues.
    roi_drag = {'active': False, 'action': None, 'handle': None, 'start': (0, 0), 'orig': (0, 0, 0, 0), 'frame_w': video_window_w, 'frame_h': video_window_h}
    config['_roi_dragging'] = False
    HANDLE_SIZE = 14
    MIN_ROI_SIZE = 20

    def _trigger_snap_roi():
        if not is_file:
            roi_drag['toast_time'] = time.time() + 2.0
            roi_drag['toast_msg'] = "Snap ROI is available for Video Analysis"
            return
        is_st = getattr(camera_worker, 'is_analysis_started', True) if camera_worker else True
        if is_file and is_st:
            roi_drag['toast_time'] = time.time() + 2.0
            roi_drag['toast_msg'] = "ROI LOCKED: Press [R] to Reset & Adjust"
            return
        cur_frame = getattr(camera_worker, 'latest_frame', None)
        if cur_frame is not None:
            circle_res = detect_green_circle_roi(cur_frame)
            if circle_res is not None:
                cx, cy, r = circle_res
                config['roi_x'] = max(0, cx - r)
                config['roi_y'] = max(0, cy - r)
                config['roi_w'] = 2 * r
                config['roi_h'] = 2 * r
                config['roi_shape'] = 'circle'
                roi_drag['toast_time'] = time.time() + 2.5
                roi_drag['toast_msg'] = f"SNAP OK: X={config['roi_x']} Y={config['roi_y']} R={r}"
                print(f"🎯 Привязка к зеленому кругу выполнена: X={config['roi_x']} Y={config['roi_y']} R={r}")
            else:
                roi_drag['toast_time'] = time.time() + 2.5
                roi_drag['toast_msg'] = "GREEN CIRCLE NOT FOUND"
                print("⚠️ Зеленый круг не обнаружен в текущем кадре")

    def _trigger_toggle_shape():
        cur_shape = config.get('roi_shape', 'circle')
        new_shape = 'rect' if cur_shape == 'circle' else 'circle'
        config['roi_shape'] = new_shape
        roi_drag['toast_time'] = time.time() + 2.0
        roi_drag['toast_msg'] = f"SHAPE: {'CIRCLE' if new_shape == 'circle' else 'SQUARE'}"
        print(f"🔄 Форма ROI переключена на: {new_shape}")

    def _trigger_toggle_lock():
        is_locked = not bool(config.get('roi_locked', False))
        config['roi_locked'] = is_locked
        roi_drag['toast_time'] = time.time() + 2.0
        roi_drag['toast_msg'] = "ROI LOCKED (Editing Disabled)" if is_locked else "ROI UNLOCKED (Free to Drag)"
        print(f"🔒 Блокировка ROI: {'ВКЛЮЧЕНА' if is_locked else 'ВЫКЛЮЧЕНА'}")

    def _trigger_center_roi():
        if config.get('roi_locked', False):
            roi_drag['toast_time'] = time.time() + 2.0
            roi_drag['toast_msg'] = "ROI LOCKED: Press [L] to Unlock"
            return
        frame_w = max(1, int(roi_drag.get('frame_w', video_window_w)))
        frame_h = max(1, int(roi_drag.get('frame_h', video_window_h)))
        rw = max(MIN_ROI_SIZE, int(config.get('roi_w', 200)))
        rh = max(MIN_ROI_SIZE, int(config.get('roi_h', 200)))
        config['roi_x'] = max(0, min(frame_w - rw, (frame_w - rw) // 2))
        config['roi_y'] = max(0, min(frame_h - rh, (frame_h - rh) // 2))
        roi_drag['toast_time'] = time.time() + 2.0
        roi_drag['toast_msg'] = f"ROI CENTERED: X={config['roi_x']} Y={config['roi_y']}"
        print(f"🎯 ROI отцентрирован: X={config['roi_x']} Y={config['roi_y']}")

    def _roi_handle(x, y, x0, y0, x1, y1):
        th = max(HANDLE_SIZE, 18)
        handles = {
            'top_left': (x0, y0), 'top_right': (x1, y0),
            'bottom_left': (x0, y1), 'bottom_right': (x1, y1),
            'left': (x0, (y0 + y1) // 2), 'right': (x1, (y0 + y1) // 2),
            'top': ((x0 + x1) // 2, y0), 'bottom': ((x0 + x1) // 2, y1),
        }
        for name, (hx, hy) in handles.items():
            if abs(x - hx) <= th and abs(y - hy) <= th:
                return name
        return None

    def roi_mouse(event, mx, my, flags, _param):
        try:
            deck_h = 52
            scrub_y = video_window_h - 44
            is_started = getattr(camera_worker, 'is_analysis_started', True) if camera_worker else True

            # Track mouse hover coordinates
            roi_drag['hover_x'] = mx
            roi_drag['hover_y'] = my

            # 1. Если открыто интерактивное меню выбора метрик HUD прямо в плеере:
            if bool(roi_drag.get('hud_picker_open', False)):
                px = roi_drag.get('picker_x', -1)
                py = roi_drag.get('picker_y', -1)
                pw = roi_drag.get('picker_w', 0)
                ph = roi_drag.get('picker_h', 0)
                header_h = 32
                row_h = roi_drag.get('picker_row_h', 24)
                metrics = roi_drag.get('picker_metrics', [])

                if event == cv2.EVENT_LBUTTONDOWN:
                    # Клик вне окна меню выбора метрик -> закрыть меню
                    if not (px <= mx <= px + pw and py <= my <= py + ph):
                        roi_drag['hud_picker_open'] = False
                        return

                    # Клик по кнопке [X] закрытия (справа вверху)
                    if (px + pw - 28 <= mx <= px + pw - 4) and (py + 4 <= my <= py + 26):
                        roi_drag['hud_picker_open'] = False
                        return

                    # Клик по кнопке [ DONE (CLOSE) ] внизу
                    by = py + ph - 30
                    if (px + 8 <= mx <= px + pw - 8) and (by <= my <= by + 26):
                        roi_drag['hud_picker_open'] = False
                        return

                    # Клик по строке конкретной метрики -> переключить чекбокс
                    if py + header_h <= my < by:
                        row_idx = int((my - (py + header_h)) // row_h)
                        if 0 <= row_idx < len(metrics):
                            k = metrics[row_idx][0]
                            cur = list(config.get('player_hud_metrics', DEFAULT_PLAYER_HUD_METRICS))
                            if k in cur:
                                cur.remove(k)
                            else:
                                cur.append(k)
                            config['player_hud_metrics'] = cur
                            return
                    return
                return

            # 2. Если меню закрыто: клик по боковой HUD-сноске для открытия меню выбора
            if event == cv2.EVENT_LBUTTONDOWN:
                hud_x = roi_drag.get('hud_x', -1)
                hud_y = roi_drag.get('hud_y', -1)
                hud_w = roi_drag.get('hud_w', 0)
                hud_h = roi_drag.get('hud_h', 0)
                if hud_x > 0 and hud_x <= mx <= hud_x + hud_w and hud_y <= my <= hud_y + hud_h:
                    roi_drag['hud_picker_open'] = True
                    return

            if is_file:
                roi_drag['hover_x'] = mx
                roi_drag['hover_y'] = my

                if event == cv2.EVENT_LBUTTONDOWN:
                    # 1. Клик по нижней полосе перемотки (YouTube Scrub Bar)
                    if abs(my - scrub_y) <= 12 or (video_window_h - deck_h <= my <= video_window_h - 36):
                        roi_drag['action'] = 'timeline_scrub'
                        roi_drag['active'] = True
                        tot_f = max(1, int(camera_worker.total_frames if camera_worker else 100))
                        bar_w = max(1, video_window_w - 24)
                        pct = max(0.0, min(1.0, (mx - 12) / float(bar_w)))
                        target_frame = int(pct * tot_f)
                        if camera_worker is not None:
                            camera_worker.seek_to_frame(target_frame)
                        return

                    # 2. Клик по кнопкам нижней панели YouTube Deck
                    if my > video_window_h - 36:
                        # Кнопка Play / Pause / Start (x = 10..48)
                        if 10 <= mx <= 48:
                            if camera_worker is not None:
                                if not is_started:
                                    camera_worker.start_analysis()
                                else:
                                    camera_worker.toggle_pause()
                            return

                        speed_x1 = max(300, min(350, video_window_w - 340))

                        # Переключение скорости (Speed Badge)
                        if is_started and (speed_x1 <= mx <= speed_x1 + 52):
                            if camera_worker is not None:
                                speeds = [0.25, 0.5, 1.0, 1.5, 2.0, 4.0, 8.0]
                                cur_spd = camera_worker.playback_speed
                                next_spd = 1.0
                                for s in speeds:
                                    if s > cur_spd + 0.05:
                                        next_spd = s
                                        break
                                else:
                                    next_spd = speeds[0]
                                camera_worker.set_speed(next_spd)
                            return

                        # Кнопка [S] Snap ROI в режиме настройки
                        snap_bx1 = max(300, video_window_w - 305)
                        snap_bx2 = snap_bx1 + 130
                        if not is_started and (snap_bx1 <= mx <= snap_bx2):
                            _trigger_snap_roi()
                            return

                        # Кнопка [START [ENTER]] в режиме настройки
                        start_bx1 = snap_bx2 + 10
                        start_bx2 = video_window_w - 12
                        if not is_started and (start_bx1 <= mx <= start_bx2):
                            if camera_worker is not None:
                                camera_worker.start_analysis()
                            return

                        # Кнопка [R] Reset ROI в режиме активного анализа
                        rst_bx1 = max(video_window_w - 140, speed_x1 + 175)
                        rst_bx2 = video_window_w - 12
                        if is_started and (rst_bx1 <= mx <= rst_bx2):
                            if camera_worker is not None:
                                camera_worker.reset_to_setup_mode()
                            return

                elif event == cv2.EVENT_MOUSEMOVE and roi_drag.get('action') == 'timeline_scrub' and roi_drag.get('active'):
                    tot_f = max(1, int(camera_worker.total_frames if camera_worker else 100))
                    bar_w = max(1, video_window_w - 24)
                    pct = max(0.0, min(1.0, (mx - 12) / float(bar_w)))
                    target_frame = int(pct * tot_f)
                    if camera_worker is not None:
                        camera_worker.seek_to_frame(target_frame)
                    return

                elif event == cv2.EVENT_LBUTTONUP and roi_drag.get('action') == 'timeline_scrub':
                    roi_drag['active'] = False
                    roi_drag['action'] = None
                    return

            # Во время активного анализа видеофайла ROI заблокирован от случайных смещений ("кружок больше не может двигаться")
            if is_file and is_started:
                if event == cv2.EVENT_LBUTTONDOWN and my < video_window_h - deck_h - 8:
                    roi_drag['toast_time'] = time.time() + 2.0
                    roi_drag['toast_msg'] = "ROI LOCKED: Press [R] to Reset & Adjust"
                return

            # Клик по нижней панели deck в видео не должен перемещать ROI
            if is_file and my >= video_window_h - deck_h:
                return

            # Живая камера: клики по нижней панели управления ROI
            if not is_file:
                live_deck_h = 44
                if my >= video_window_h - live_deck_h:
                    if event == cv2.EVENT_LBUTTONDOWN:
                        btn_center_w = 95
                        btn_lock_w = 115
                        btn_shape_w = 115

                        btn_center_x2 = video_window_w - 10
                        btn_center_x1 = btn_center_x2 - btn_center_w
                        btn_lock_x2 = btn_center_x1 - 8
                        btn_lock_x1 = btn_lock_x2 - btn_lock_w
                        btn_shape_x2 = btn_lock_x1 - 8
                        btn_shape_x1 = max(btn_shape_x2 - btn_shape_w, 240)

                        if btn_shape_x1 <= mx <= btn_shape_x2:
                            _trigger_toggle_shape()
                            return
                        if btn_lock_x1 <= mx <= btn_lock_x2:
                            _trigger_toggle_lock()
                            return
                        if btn_center_x1 <= mx <= btn_center_x2:
                            _trigger_center_roi()
                            return
                    return

                # Заблокированный ROI в режиме живой камеры
                if config.get('roi_locked', False):
                    if event == cv2.EVENT_LBUTTONDOWN:
                        roi_drag['toast_time'] = time.time() + 2.0
                        roi_drag['toast_msg'] = "ROI LOCKED: Press [L] to Unlock"
                    return

            # Перемотка колесиком мыши
            if is_file and event == cv2.EVENT_MOUSEWHEEL:
                step_s = float(config.get('seek_step_sec', 5.0))
                if camera_worker is not None:
                    if flags > 0:
                        camera_worker.seek_relative(step_s)
                    else:
                        camera_worker.seek_relative(-step_s)
                return

            if not config.get('live_roi', True):
                return
            frame_w = max(1, int(roi_drag.get('frame_w', video_window_w)))
            frame_h = max(1, int(roi_drag.get('frame_h', video_window_h)))
            sx = frame_w / max(1, video_window_w)
            sy = frame_h / max(1, video_window_h)
            x = int(round(mx * sx))
            y = int(round(my * sy))
            x = max(0, min(frame_w - 1, x))
            y = max(0, min(frame_h - 1, y))
            x0 = int(config.get('roi_x', 0))
            y0 = int(config.get('roi_y', 0))
            w = max(MIN_ROI_SIZE, int(config.get('roi_w', 20)))
            h = max(MIN_ROI_SIZE, int(config.get('roi_h', 20)))
            x1, y1 = x0 + w, y0 + h

            if event == cv2.EVENT_LBUTTONDOWN:
                if config.get('roi_shape', 'rect') == 'circle' and config.get('allow_roi_resize', True):
                    cx, cy = x0 + w / 2.0, y0 + h / 2.0
                    radius = min(w, h) / 2.0
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if abs(dist - radius) <= HANDLE_SIZE:
                        config['_roi_dragging'] = True
                        roi_drag.update(active=True, action='resize_circle', handle=None, start=(x, y), orig=(x0, y0, w, h))
                        return
                    elif dist <= radius:
                        config['_roi_dragging'] = True
                        roi_drag.update(active=True, action='move', handle=None, start=(x, y), orig=(x0, y0, w, h))
                        return
                handle = _roi_handle(x, y, x0, y0, x1, y1) if (config.get('allow_roi_resize', True) and config.get('roi_shape', 'rect') != 'circle') else None
                if handle:
                    config['_roi_dragging'] = True
                    roi_drag.update(active=True, action='resize', handle=handle, start=(x, y), orig=(x0, y0, w, h))
                elif x0 <= x <= x1 and y0 <= y <= y1:
                    config['_roi_dragging'] = True
                    roi_drag.update(active=True, action='move', handle=None, start=(x, y), orig=(x0, y0, w, h))
                else:
                    # Клик в свободную область — мгновенный перенос центра ROI в точку клика
                    nx = max(0, min(int(x - w / 2), frame_w - w))
                    ny = max(0, min(int(y - h / 2), frame_h - h))
                    config['roi_x'], config['roi_y'] = nx, ny
                    config['_roi_dragging'] = True
                    roi_drag.update(active=True, action='move', handle=None, start=(x, y), orig=(nx, ny, w, h))
                return

            if event == cv2.EVENT_MOUSEMOVE and roi_drag['active']:
                ox, oy, ow, oh = roi_drag['orig']
                if roi_drag['action'] == 'move':
                    dx, dy = x - roi_drag['start'][0], y - roi_drag['start'][1]
                    nx = max(0, min(ox + dx, max(0, frame_w - ow)))
                    ny = max(0, min(oy + dy, max(0, frame_h - oh)))
                    config['roi_x'], config['roi_y'] = int(nx), int(ny)
                elif roi_drag['action'] == 'resize_circle':
                    cx, cy = ox + ow / 2.0, oy + oh / 2.0
                    radius = max(MIN_ROI_SIZE / 2.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5)
                    size = int(max(MIN_ROI_SIZE, min(2 * radius, min(frame_w, frame_h))))
                    nx = max(0, min(int(cx - size / 2), frame_w - size))
                    ny = max(0, min(int(cy - size / 2), frame_h - size))
                    config['roi_x'], config['roi_y'] = nx, ny
                    config['roi_w'], config['roi_h'] = size, size
                else:
                    nx0, ny0, nx1, ny1 = ox, oy, ox + ow, oy + oh
                    handle = roi_drag['handle']
                    if 'left' in handle:
                        nx0 = min(x, nx1 - MIN_ROI_SIZE)
                    if 'right' in handle:
                        nx1 = max(x, nx0 + MIN_ROI_SIZE)
                    if 'top' in handle:
                        ny0 = min(y, ny1 - MIN_ROI_SIZE)
                    if 'bottom' in handle:
                        ny1 = max(y, ny0 + MIN_ROI_SIZE)
                    nx0 = max(0, nx0)
                    ny0 = max(0, ny0)
                    nx1 = min(frame_w, nx1)
                    ny1 = min(frame_h, ny1)
                    if nx1 - nx0 >= MIN_ROI_SIZE and ny1 - ny0 >= MIN_ROI_SIZE:
                        config['roi_x'], config['roi_y'] = int(nx0), int(ny0)
                        config['roi_w'], config['roi_h'] = int(nx1 - nx0), int(ny1 - ny0)
                return

            if event == cv2.EVENT_LBUTTONUP:
                roi_drag['active'] = False
                roi_drag['action'] = None
                roi_drag['handle'] = None
                config['_roi_dragging'] = False
        except Exception:
            # Completely exception-safe to prevent OpenCV UI loop freezing
            pass

    if show_video_window:
        cv2.setMouseCallback(WINDOW_NAME, roi_mouse)

    start_time = time.time()
    should_close = False
    camera_worker = None
    raw_csv_path = None
    pg_last_update = 0
    last_graph_version = -1
    live_win = None
    session_excel_path = None
    video_recorder = None
    video_path = None
    last_recorded_frame_count = -1

    try:
        session_excel_path = create_session_excel(save_folder)
        raw_csv_path = os.path.splitext(session_excel_path)[0] + "_raw_rgb.csv"
        camera_worker = CameraWorker(
            cap, config, start_time,
            save_interval_ms=max(1, int(config.get('analysis_interval_ms', 15))), max_points=int(config.get('max_points', MAX_POINTS)),
            raw_csv_path=raw_csv_path,
        )
        video_base = os.path.splitext(os.path.basename(session_excel_path))[0]
        os.makedirs(video_folder, exist_ok=True)
        video_path = os.path.join(video_folder, f"{video_base}_video.mkv")
        if config.get('record_video', True):
            video_recorder = AsyncVideoRecorder(video_path, fps=FFMPEG_PIPE_OUTPUT_FPS)
        else:
            video_recorder = None

                                
        pg.setConfigOptions(antialias=bool(config.get('antialias', False)))
        pg_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        try:
            live_win = LiveGraphWindow(
                pg, QtWidgets, QtCore, QtGui,
                theme_mode=("light" if config.get("light_theme", False) else "dark"),
                custom_graphs=config.get("custom_graphs", []),
                notification_settings=config,
                is_video_file=is_file,
            )
        except Exception as graph_error:
            # A malformed saved custom graph must not make the whole analysis
            # unusable. Start the standard graph set and report the bad entry.
            print(f"⚠️ Пользовательский график отключён: {graph_error}")
            live_win = LiveGraphWindow(
                pg, QtWidgets, QtCore, QtGui,
                theme_mode=("light" if config.get("light_theme", False) else "dark"),
                custom_graphs=[],
                notification_settings=config,
                is_video_file=is_file,
            )
        # Применяем сохранённые настройки видимости графиков.
        live_win.btn_r.setChecked(bool(config.get('show_r', True)))
        live_win.btn_g.setChecked(bool(config.get('show_g', True)))
        live_win.btn_b.setChecked(bool(config.get('show_b', True)))
        show_log = bool(config.get('show_log', True))
        live_win.log_btn.setChecked(show_log)
        for item in getattr(live_win, '_graph_items', []):
            if item.get('name') in ('Log10(B/R)', 'Log10(B/G)'):
                item['visible'] = show_log
            elif item.get('name') == 'RGB_sum_slope_30s':
                item['visible'] = bool(config.get('show_slope', True))
            elif item.get('name') == 'Transition_score':
                item['visible'] = bool(config.get('show_transition', True))
        live_win._rebuild_graph_layout()
        live_win.set_session_excel(session_excel_path)
        pg_app.processEvents()

        print(f"📌 Excel сессии (метки в реальном времени): {session_excel_path}")
        print(f"🛟 Аварийный CSV RGB: {raw_csv_path}")
        print(f"🎥 Видео анализа будет сохранено: {video_path}")

    except Exception as e:
        msg = (
            "Не удалось запустить PyQt5/pyqtgraph.\n\n"
            f"{e}\n\n"
            "Попробуйте в терминале:\npip install pyqtgraph PyQt5"
        )
        print(f"❌ {msg}")
        if camera_worker is not None:
            config['_roi_dragging'] = False
        camera_worker.stop()
        if cap is not None and hasattr(cap, 'release'):
            try:
                cap.release()
            except Exception:
                pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        if parent is not None:
            from tkinter import messagebox
            messagebox.showerror("Ошибка", msg, parent=parent)
        return

    camera_worker.start()
    print("✅ Анализ запущен!")
    print("📊 Live: RGB + Log10(B/R) + Log10(B/G) + RGB_sum_slope_30s + Transition_score")
    print("📊 График — в окне «RGB Live Graph»")
    print("📌 Горячие клавиши для меток (окно камеры или графика):")
    print("   m - добавить метку в текущий момент")
    print("   M (Shift+m) - добавить метку с описанием")
    print("   l - список меток")
    print("   📍 Pick + клик на графике - метка в любой точке")
    print("   Двойной ЛКМ по графику - вернуться в TRACK")
    print("   ПКМ на графике - штатное меню PyQtGraph")
    print("Q/Esc — выход из окна камеры")

    window_was_visible = False
    try:
        snap_toast_time = 0.0
        snap_toast_msg = ""

        while not should_close:
            snap = camera_worker.snapshot(copy_frame=False)
            try:
                now_ms = int((time.time() - start_time) * 1000)
                if snap['graph_version'] != last_graph_version and now_ms >= pg_last_update + int(config.get('graph_update_ms', DEFAULT_GRAPH_UPDATE_MS)):
                    graph_t = snap['graph_t']
                    graph_r = snap['graph_r']
                    graph_g = snap['graph_g']
                    graph_b = snap['graph_b']
                    graph_log = snap['graph_log']
                    graph_log_bg = snap['graph_log_bg']
                    graph_rgb_sum = snap['graph_rgb_sum']
                    graph_rgb_sum_smooth = snap['graph_rgb_sum_smooth']
                    graph_rgb_sum_slope10 = snap['graph_rgb_sum_slope10']
                    graph_rgb_sum_slope30 = snap['graph_rgb_sum_slope30']
                    graph_rgb_vector_speed30 = snap['graph_rgb_vector_speed30']
                    graph_chromaticity_speed30 = snap['graph_chromaticity_speed30']
                    graph_k_chrom_previous = snap['graph_k_chrom_previous']
                    graph_log_ratio_speed30 = snap['graph_log_ratio_speed30']
                    graph_rgb_sum_acceleration30 = snap['graph_rgb_sum_acceleration30']
                    graph_transition_score = snap['graph_transition_score']

                    live_win.set_data(
                        graph_t, graph_r, graph_g, graph_b,
                        graph_log, graph_log_bg,
                        None, None,
                        rgb_sum_vals=graph_rgb_sum,
                        rgb_sum_smooth_vals=graph_rgb_sum_smooth,
                        rgb_sum_slope10_vals=graph_rgb_sum_slope10,
                        rgb_sum_slope30_vals=graph_rgb_sum_slope30,
                        rgb_vector_speed30_vals=graph_rgb_vector_speed30,
                        chromaticity_speed30_vals=graph_chromaticity_speed30,
                        k_chrom_previous_vals=graph_k_chrom_previous,
                        log_ratio_speed30_vals=graph_log_ratio_speed30,
                        rgb_sum_acceleration30_vals=graph_rgb_sum_acceleration30,
                        transition_score_vals=graph_transition_score,
                        pts=snap['point_count']
                    )
                    last_graph_version = snap['graph_version']
                    pg_last_update = now_ms
                pg_app.processEvents(QtCore.QEventLoop.AllEvents, 2)
                if live_win is not None:
                    if getattr(live_win, 'stop_requested', False) or (hasattr(live_win, 'win') and not live_win.win.isVisible()):
                        should_close = True
                        break
                if live_win is not None and hasattr(live_win, 'take_playback_actions'):
                    for action, val in live_win.take_playback_actions():
                        if action == 'snap_roi':
                            _trigger_snap_roi()
                        elif action == 'toggle_shape':
                            _trigger_toggle_shape()
                        elif action == 'toggle_lock':
                            _trigger_toggle_lock()
                        elif action == 'center_roi':
                            _trigger_center_roi()
                        elif action == 'start_analysis':
                            if camera_worker is not None:
                                camera_worker.start_analysis()
                        elif action == 'reset':
                            if camera_worker is not None:
                                if is_file:
                                    camera_worker.reset_to_setup_mode()
                                else:
                                    _trigger_center_roi()
                        elif action == 'toggle_pause':
                            if camera_worker is not None:
                                if not getattr(camera_worker, 'is_analysis_started', True):
                                    camera_worker.start_analysis()
                                else:
                                    camera_worker.toggle_pause()
                        elif action == 'restart':
                            camera_worker.seek_to_frame(0)
                        elif action == 'seek_rel':
                            camera_worker.seek_relative(val)
                        elif action == 'seek_frame':
                            camera_worker.seek_to_frame(val)
                        elif action == 'seek_time_ms':
                            camera_worker.seek_to_time_ms(val)
                        elif action == 'set_speed':
                            camera_worker.set_speed(val)
                        elif action == 'open_settings':
                            try:
                                from ..gui.settings_window import SettingsWindow
                                def _on_settings_applied():
                                    if live_win is not None:
                                        live_win.notification_settings = dict(config)
                                        live_win.set_custom_graphs(config.get("custom_graphs", []))
                                        live_win.btn_r.setChecked(bool(config.get('show_r', True)))
                                        live_win.btn_g.setChecked(bool(config.get('show_g', True)))
                                        live_win.btn_b.setChecked(bool(config.get('show_b', True)))
                                        show_l = bool(config.get('show_log', True))
                                        live_win.log_btn.setChecked(show_l)
                                        for itm in getattr(live_win, '_graph_items', []):
                                            if itm.get('name') in ('Log10(B/R)', 'Log10(B/G)'):
                                                itm['visible'] = show_l
                                            elif itm.get('name') == 'RGB_sum_slope_30s':
                                                itm['visible'] = bool(config.get('show_slope', True))
                                            elif itm.get('name') == 'Transition_score':
                                                itm['visible'] = bool(config.get('show_transition', True))
                                        live_win._rebuild_graph_layout()
                                tk_p = parent if (parent is not None and hasattr(parent, 'winfo_exists') and parent.winfo_exists()) else None
                                SettingsWindow(tk_p, config, on_apply=_on_settings_applied)
                            except Exception as se:
                                print(f"⚠️ Ошибка открытия настроек: {se}")
                if parent is not None:
                    try:
                        if hasattr(parent, 'winfo_exists') and parent.winfo_exists():
                            parent.update_idletasks()
                            parent.update()
                    except Exception:
                        pass
                else:
                    try:
                        import tkinter as _tk
                        _root = getattr(_tk, '_default_root', None)
                        if _root is not None and hasattr(_root, 'winfo_exists') and _root.winfo_exists():
                            _root.update_idletasks()
                            _root.update()
                    except Exception:
                        pass
                if live_win is not None and hasattr(live_win, 'update_playback_hud'):
                    fps_val = snap.get('file_fps') or 25.0
                    cur_f = snap.get('file_frame_index', 0)
                    total_f = snap.get('total_frames', 0)
                    cur_sec = cur_f / fps_val if fps_val > 0 else 0.0
                    dur_sec = snap.get('duration_sec', 0.0)
                    is_paused = snap.get('is_paused', False)
                    speed_val = snap.get('playback_speed', 1.0)
                    live_win.update_playback_hud(is_paused, speed_val, cur_f, total_f, cur_sec, dur_sec)
                if live_win is not None:
                    resize_factor = live_win.take_video_resize_request()
                    if resize_factor:
                        video_window_w = int(max(320, min(3840, video_window_w * resize_factor)))
                        video_window_h = int(max(240, min(2160, video_window_h * resize_factor)))
                        cv2.resizeWindow(WINDOW_NAME, video_window_w, video_window_h)
                        try:
                            cv2.setWindowTitle(WINDOW_NAME, f'{WINDOW_NAME} — {video_window_w}x{video_window_h}')
                        except Exception:
                            pass
            except Exception:
                pass

            if config.get('source_is_file') and not getattr(camera_worker, '_running', True):
                should_close = True
                break

            frame = snap['frame']
            if frame is None:
                frame = getattr(camera_worker, 'latest_frame', None)
                if frame is None:
                    time.sleep(0.001)
                    continue

            h_f, w_f = int(frame.shape[0]), int(frame.shape[1])
            roi_drag['frame_w'], roi_drag['frame_h'] = w_f, h_f

            # Ограничиваем ROI границами кадра (без затирания пользовательских координат старыми значениями safe_x)
            config['roi_x'] = int(max(0, min(config.get('roi_x', 0), max(0, w_f - 1))))
            config['roi_y'] = int(max(0, min(config.get('roi_y', 0), max(0, h_f - 1))))
            config['roi_w'] = int(max(MIN_ROI_SIZE, min(config.get('roi_w', 20), w_f - config['roi_x'])))
            config['roi_h'] = int(max(MIN_ROI_SIZE, min(config.get('roi_h', 20), h_f - config['roi_y'])))

            # Worker already calculated ROI for this frame; reuse it on the GUI thread.
            mean_b, mean_g, mean_r = snap.get('means', (0.0, 0.0, 0.0))
            roi_info = snap.get('roi_info') or (config.get('roi_x', 0), config.get('roi_y', 0), config.get('roi_w', 20), config.get('roi_h', 20), h_f, w_f)
            safe_x, safe_y, safe_w, safe_h = map(int, roi_info[:4])

            if is_file:
                cur_f = snap.get('file_frame_index', 0)
                fps_val = snap.get('file_fps') or 25.0
                elapsed_time = cur_f / fps_val if fps_val > 0 else 0.0
                elapsed_ms = elapsed_time * 1000.0
            else:
                elapsed_time = time.time() - start_time
                elapsed_ms = elapsed_time * 1000.0

            frame_count = snap.get('frame_count', 0)
            is_analysis_active = snap.get('is_analysis_started', True) and not snap.get('is_paused', False)

            if is_analysis_active and frame_count > 0 and frame_count % 100 == 0:
                print(
                    f"t={elapsed_ms:.0f}ms | R={mean_r:.0f} G={mean_g:.0f} B={mean_b:.0f} | "
                    f"Точек: {snap['point_count']}"
                )

            display_frame = frame.copy()
            if config.get('roi_shape', 'rect') == 'circle':
                center = (safe_x + safe_w // 2, safe_y + safe_h // 2)
                radius = min(safe_w, safe_h) // 2
                cv2.circle(display_frame, center, radius, (0, 255, 0), 2)
                cv2.drawMarker(display_frame, center, (0, 255, 120), cv2.MARKER_CROSS, 14, 1)
                if config.get('allow_roi_resize', True):
                    hx, hy = center[0] + radius, center[1]
                    cv2.circle(display_frame, (hx, hy), 6, (255, 255, 255), -1)
                    cv2.circle(display_frame, (hx, hy), 6, (0, 180, 0), 1)
            else:
                cv2.rectangle(display_frame, (safe_x, safe_y), (safe_x + safe_w, safe_y + safe_h), (0, 255, 0), 2)
                if config.get('allow_roi_resize', True):
                    for hx, hy in ((safe_x, safe_y), (safe_x + safe_w, safe_y),
                                   (safe_x, safe_y + safe_h), (safe_x + safe_w, safe_y + safe_h),
                                   (safe_x + safe_w // 2, safe_y), (safe_x + safe_w // 2, safe_y + safe_h),
                                   (safe_x, safe_y + safe_h // 2), (safe_x + safe_w, safe_y + safe_h // 2)):
                        cv2.rectangle(display_frame, (hx - 5, hy - 5), (hx + 5, hy + 5), (255, 255, 255), -1)
                        cv2.rectangle(display_frame, (hx - 5, hy - 5), (hx + 5, hy + 5), (0, 180, 0), 1)

            mins = int(elapsed_time // 60)
            secs = int(elapsed_time % 60)
            hours = mins // 60
            mins = mins % 60

            if show_video_window:
                try:
                    rect = cv2.getWindowImageRect(WINDOW_NAME)
                    if rect is not None and len(rect) >= 4 and rect[2] > 100 and rect[3] > 100:
                        video_window_w = int(rect[2])
                        video_window_h = int(rect[3])
                except Exception:
                    pass

                shown = cv2.resize(display_frame, (video_window_w, video_window_h), interpolation=cv2.INTER_LINEAR)

                # 1. Информационная боковая HUD-сноска справа (Real-time Sidebar HUD с выбором анализируемых графиков)
                is_picker_open = bool(roi_drag.get('hud_picker_open', False))

                # Список доступных для выбора метрик и графиков с полной поддержкой кириллицы (Unicode)
                all_metrics = [
                    ("RGB_sum", "RGB Sum (R+G+B)"),
                    ("Log10(B/G)", "Log10(B/G)"),
                    ("Log10(B/R)", "Log10(B/R)"),
                    ("Transition_score", "Transition (Индекс)"),
                    ("RGB_sum_slope_30s", "Slope 30s (Тренд)"),
                    ("R", "R (Красный)"),
                    ("G", "G (Зеленый)"),
                    ("B", "B (Синий)"),
                ]
                for cg in config.get('custom_graphs', []):
                    cg_name = cg.get('name', '').strip()
                    if cg_name and not any(k == cg_name for k, _ in all_metrics):
                        all_metrics.append((cg_name, cg_name))

                if is_picker_open:
                    p_w = 280
                    p_x = video_window_w - p_w - 10
                    p_y = 10
                    header_h = 32
                    row_h = 24
                    p_h = header_h + len(all_metrics) * row_h + 38
                    roi_drag['picker_x'], roi_drag['picker_y'] = p_x, p_y
                    roi_drag['picker_w'], roi_drag['picker_h'] = p_w, p_h
                    roi_drag['picker_row_h'] = row_h
                    roi_drag['picker_metrics'] = all_metrics

                    curr_sel_set = set(config.get('player_hud_metrics', DEFAULT_PLAYER_HUD_METRICS))
                    hx, hy = roi_drag.get('hover_x', -1), roi_drag.get('hover_y', -1)
                    _render_picker_popup_pil(shown, p_x, p_y, p_w, p_h, all_metrics, curr_sel_set, hx, hy)
                else:
                    # Обычный режим отображения HUD-сноски
                    hud_metrics = config.get('player_hud_metrics', DEFAULT_PLAYER_HUD_METRICS)
                    if not isinstance(hud_metrics, list) or len(hud_metrics) == 0:
                        hud_metrics = list(DEFAULT_PLAYER_HUD_METRICS)

                    hud_w = 280
                    hud_x = video_window_w - hud_w - 10
                    hud_y = 10
                    header_h = 32
                    item_h = 24
                    hud_h = header_h + len(hud_metrics) * item_h + 10
                    roi_drag['hud_x'], roi_drag['hud_y'] = hud_x, hud_y
                    roi_drag['hud_w'], roi_drag['hud_h'] = hud_w, hud_h

                    # Заголовок HUD и время
                    time_str = f"T: {hours:02d}:{mins:02d}:{secs:02d}"

                    # Значения метрик
                    slope30_val = np.nan
                    try:
                        slope30_arr = snap.get('graph_rgb_sum_slope30')
                        if slope30_arr is not None and len(slope30_arr):
                            slope30_val = float(slope30_arr[-1])
                    except Exception:
                        pass

                    score_val = np.nan
                    try:
                        score_arr = snap.get('graph_transition_score')
                        if score_arr is not None and len(score_arr):
                            score_val = float(score_arr[-1])
                    except Exception:
                        pass

                    log_br_val = np.log10(mean_b / mean_r) if mean_r > 0 and mean_b > 0 else np.nan
                    log_bg_val = np.log10(mean_b / mean_g) if mean_g > 0 and mean_b > 0 else np.nan
                    rgb_sum_val = mean_r + mean_g + mean_b

                    items_data = []
                    for m_key in hud_metrics:
                        if m_key == 'R':
                            items_data.append({
                                'label': 'R (Red):',
                                'value': f'{mean_r:.1f}',
                                'bullet_color': (240, 60, 60),
                                'val_color': (255, 100, 100)
                            })
                        elif m_key == 'G':
                            items_data.append({
                                'label': 'G (Green):',
                                'value': f'{mean_g:.1f}',
                                'bullet_color': (60, 220, 80),
                                'val_color': (100, 255, 120)
                            })
                        elif m_key == 'B':
                            items_data.append({
                                'label': 'B (Blue):',
                                'value': f'{mean_b:.1f}',
                                'bullet_color': (60, 160, 240),
                                'val_color': (100, 190, 255)
                            })
                        elif m_key == 'RGB_sum':
                            items_data.append({
                                'label': 'RGB Sum:',
                                'value': f'{rgb_sum_val:.1f}',
                                'bullet_color': (220, 220, 0),
                                'val_color': (240, 240, 60)
                            })
                        elif m_key == 'RGB_sum_slope_30s':
                            sl_str = f'{slope30_val:+.2f}/s' if np.isfinite(slope30_val) else '--'
                            items_data.append({
                                'label': 'Slope 30s:',
                                'value': sl_str,
                                'bullet_color': (120, 240, 140),
                                'val_color': (120, 255, 140)
                            })
                        elif m_key == 'Transition_score':
                            sc_str = f'{score_val:.2f}' if np.isfinite(score_val) else '--'
                            items_data.append({
                                'label': 'Transition:',
                                'value': sc_str,
                                'bullet_color': (80, 180, 255),
                                'val_color': (80, 200, 255)
                            })
                        elif m_key == 'Log10(B/R)':
                            lbr_str = f'{log_br_val:.4f}' if np.isfinite(log_br_val) else '--'
                            items_data.append({
                                'label': 'Log10(B/R):',
                                'value': lbr_str,
                                'bullet_color': (50, 170, 255),
                                'val_color': (80, 190, 255)
                            })
                        elif m_key == 'Log10(B/G)':
                            lbg_str = f'{log_bg_val:.4f}' if np.isfinite(log_bg_val) else '--'
                            items_data.append({
                                'label': 'Log10(B/G):',
                                'value': lbg_str,
                                'bullet_color': (255, 200, 100),
                                'val_color': (255, 200, 120)
                            })
                        else:
                            cg = next((c for c in config.get('custom_graphs', []) if c.get('name') == m_key), None)
                            cg_val = np.nan
                            custom_color = (200, 120, 255)
                            if cg is not None:
                                formula = cg.get('formula', '')
                                hex_c = cg.get('color', '#C084FC')
                                if hex_c and hex_c.startswith('#') and len(hex_c) == 7:
                                    try:
                                        custom_color = (int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16))
                                    except Exception:
                                        pass
                                if formula:
                                    try:
                                        safe_builtins = {
                                            'abs': abs, 'min': min, 'max': max, 'round': round, 'pow': pow,
                                            'float': float, 'int': int, 'np': np, 'math': np,
                                            'sin': np.sin, 'cos': np.cos, 'tan': np.tan,
                                            'exp': np.exp, 'log': np.log, 'log10': np.log10, 'sqrt': np.sqrt
                                        }
                                        env = {
                                            'R': float(mean_r),
                                            'G': float(mean_g),
                                            'B': float(mean_b),
                                            'RGB': float(rgb_sum_val),
                                            'RGB_sum': float(rgb_sum_val),
                                            'Slope': float(slope30_val) if np.isfinite(slope30_val) else 0.0,
                                            'Slope30': float(slope30_val) if np.isfinite(slope30_val) else 0.0,
                                            'Transition': float(score_val) if np.isfinite(score_val) else 0.0,
                                            'Score': float(score_val) if np.isfinite(score_val) else 0.0,
                                            'LogBR': float(log_br_val) if np.isfinite(log_br_val) else 0.0,
                                            'LogBG': float(log_bg_val) if np.isfinite(log_bg_val) else 0.0,
                                        }
                                        for cv in config.get('custom_variables', []):
                                            cv_name = cv.get('name', '').strip()
                                            cv_formula = cv.get('formula', '').strip()
                                            if cv_name and cv_formula:
                                                try:
                                                    env[cv_name] = float(eval(cv_formula, {'__builtins__': safe_builtins}, env))
                                                except Exception:
                                                    env[cv_name] = 0.0
                                        cg_val = float(eval(formula, {'__builtins__': safe_builtins}, env))
                                    except Exception:
                                        cg_val = np.nan

                            if np.isfinite(cg_val):
                                val_str = f"{cg_val:.4f}" if (abs(cg_val) < 0.1 and cg_val != 0) else f"{cg_val:.2f}"
                            else:
                                val_str = "--"

                            items_data.append({
                                'label': f"{m_key}:",
                                'value': val_str,
                                'bullet_color': custom_color,
                                'val_color': custom_color
                            })

                    _render_sidebar_hud_pil(shown, hud_x, hud_y, hud_w, hud_h, time_str, items_data)

                # 2. Всплывающее уведомление (Toast Notification)
                active_toast_time = max(snap_toast_time, roi_drag.get('toast_time', 0))
                active_toast_msg = roi_drag.get('toast_msg') if roi_drag.get('toast_time', 0) >= snap_toast_time else snap_toast_msg
                if active_toast_time > time.time() and active_toast_msg:
                    toast_w, toast_h = 440, 36
                    toast_x, toast_y = (video_window_w - toast_w) // 2, video_window_h - 100
                    toast_ov = shown.copy()
                    cv2.rectangle(toast_ov, (toast_x, toast_y), (toast_x + toast_w, toast_y + toast_h), (20, 35, 25) if "OK" in active_toast_msg else (35, 20, 20), -1)
                    cv2.addWeighted(toast_ov, 0.9, shown, 0.1, 0, shown)
                    cv2.rectangle(shown, (toast_x, toast_y), (toast_x + toast_w, toast_y + toast_h), (0, 255, 120) if "OK" in active_toast_msg else (80, 80, 255), 1)

                    t_sub = shown[toast_y:toast_y+toast_h, toast_x:toast_x+toast_w]
                    if t_sub.size > 0 and t_sub.shape[0] == toast_h and t_sub.shape[1] == toast_w:
                        pil_t = Image.fromarray(cv2.cvtColor(t_sub, cv2.COLOR_BGR2RGB))
                        draw_t = ImageDraw.Draw(pil_t)
                        f_t = _get_unicode_font(13, bold=True)
                        draw_t.text((15, 8), active_toast_msg, font=f_t, fill=(255, 255, 255))
                        shown[toast_y:toast_y+toast_h, toast_x:toast_x+toast_w] = cv2.cvtColor(np.array(pil_t), cv2.COLOR_RGB2BGR)

                # 3. Нижняя панель в стиле YouTube (YouTube Scrub & Control Deck)
                if is_file:
                    deck_h = 52
                    deck_y = video_window_h - deck_h
                    overlay = shown.copy()
                    cv2.rectangle(overlay, (0, deck_y), (video_window_w, video_window_h), (12, 16, 22), -1)
                    cv2.addWeighted(overlay, 0.88, shown, 0.12, 0, shown)

                    is_started = snap.get('is_analysis_started', False)
                    is_paused = snap.get('is_paused', False)
                    speed = snap.get('playback_speed', 1.0)
                    cur_f = snap.get('file_frame_index', 0)
                    tot_f = snap.get('total_frames', 0)
                    fps_val = snap.get('file_fps', 25.0)
                    cur_sec = cur_f / fps_val if fps_val > 0 else 0.0
                    dur_sec = snap.get('duration_sec', 0.0)
                    cur_m, cur_s = int(cur_sec // 60), int(cur_sec % 60)
                    dur_m, dur_s = int(dur_sec // 60), int(dur_sec % 60)

                    # 3.1. Интерактивная полоса таймлайна (YouTube Scrub Line)
                    tl_y = deck_y + 8
                    tl_x1 = 12
                    tl_x2 = video_window_w - 12
                    tl_w = tl_x2 - tl_x1
                    hx, hy = roi_drag.get('hover_x', -1), roi_drag.get('hover_y', -1)
                    is_hovering_tl = (tl_x1 <= hx <= tl_x2 and abs(hy - tl_y) <= 12)
                    line_th = 5 if is_hovering_tl else 3

                    if tl_w > 20:
                        # Фоновая линия
                        cv2.line(shown, (tl_x1, tl_y), (tl_x2, tl_y), (50, 58, 72), line_th)
                        fill_w = int(max(0.0, min(1.0, cur_f / max(1, tot_f))) * tl_w)
                        if fill_w > 0:
                            # Прогресс (красный в стиле YouTube)
                            cv2.line(shown, (tl_x1, tl_y), (tl_x1 + fill_w, tl_y), (0, 60, 230), line_th)
                            circle_r = 7 if is_hovering_tl else 5
                            cv2.circle(shown, (tl_x1 + fill_w, tl_y), circle_r, (255, 255, 255), -1)
                            cv2.circle(shown, (tl_x1 + fill_w, tl_y), circle_r, (0, 60, 230), 2)

                        # Всплывающий таймкод при наведении мыши
                        if is_hovering_tl:
                            hover_pct = (hx - tl_x1) / float(tl_w)
                            hover_sec = hover_pct * dur_sec
                            hm, hs = int(hover_sec // 60), int(hover_sec % 60)
                            tip_f = int(hover_pct * tot_f)
                            tip_text = f"{hm:02d}:{hs:02d} ({tip_f})"
                            tip_w = 96
                            tip_x = max(tl_x1, min(hx - tip_w // 2, tl_x2 - tip_w))
                            cv2.rectangle(shown, (tip_x, tl_y - 28), (tip_x + tip_w, tl_y - 6), (18, 24, 34), -1)
                            cv2.rectangle(shown, (tip_x, tl_y - 28), (tip_x + tip_w, tl_y - 6), (0, 230, 210), 1)
                            cv2.putText(shown, tip_text, (tip_x + 6, tl_y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)

                    # 3.2. Нижняя строка элементов управления
                    ctrl_y = deck_y + 36

                    # Кнопка Play / Pause / Start (геометрическая отрисовка иконки)
                    btn_play_w = 36
                    if not is_started:
                        cv2.rectangle(shown, (12, deck_y + 18), (12 + btn_play_w, deck_y + 44), (20, 135, 45), -1)
                        cv2.rectangle(shown, (12, deck_y + 18), (12 + btn_play_w, deck_y + 44), (80, 255, 120), 1)
                        pts_play = np.array([[23, deck_y + 24], [23, deck_y + 38], [37, deck_y + 31]], np.int32)
                        cv2.fillPoly(shown, [pts_play], (255, 255, 255))
                    elif is_paused:
                        cv2.rectangle(shown, (12, deck_y + 18), (12 + btn_play_w, deck_y + 44), (30, 90, 210), -1)
                        cv2.rectangle(shown, (12, deck_y + 18), (12 + btn_play_w, deck_y + 44), (80, 160, 255), 1)
                        pts_play = np.array([[23, deck_y + 24], [23, deck_y + 38], [37, deck_y + 31]], np.int32)
                        cv2.fillPoly(shown, [pts_play], (255, 255, 255))
                    else:
                        cv2.rectangle(shown, (12, deck_y + 18), (12 + btn_play_w, deck_y + 44), (35, 140, 45), -1)
                        cv2.rectangle(shown, (12, deck_y + 18), (12 + btn_play_w, deck_y + 44), (100, 240, 120), 1)
                        cv2.rectangle(shown, (23, deck_y + 24), (27, deck_y + 38), (255, 255, 255), -1)
                        cv2.rectangle(shown, (31, deck_y + 24), (35, deck_y + 38), (255, 255, 255), -1)

                    # Таймкод: 01:23 / 05:40
                    time_deck_str = f"{cur_m:02d}:{cur_s:02d} / {dur_m:02d}:{dur_s:02d}"
                    cv2.putText(shown, time_deck_str, (56, ctrl_y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

                    # Кадры и FPS
                    frame_info_str = f"| {cur_f}/{tot_f} ({fps_val:.0f}fps)"
                    cv2.putText(shown, frame_info_str, (170, ctrl_y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 190, 205), 1, cv2.LINE_AA)

                    # Правая секция в зависимости от режима:
                    if not is_started:
                        # Режим настройки ROI (до пуска)
                        snap_bx1 = max(310, video_window_w - 305)
                        snap_bx2 = snap_bx1 + 130
                        cv2.rectangle(shown, (snap_bx1, deck_y + 18), (snap_bx2, deck_y + 44), (25, 75, 95), -1)
                        cv2.rectangle(shown, (snap_bx1, deck_y + 18), (snap_bx2, deck_y + 44), (0, 220, 200), 1)
                        cv2.putText(shown, "[S] Snap ROI", (snap_bx1 + 12, ctrl_y - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (255, 255, 255), 1, cv2.LINE_AA)

                        start_bx1 = snap_bx2 + 10
                        start_bx2 = video_window_w - 12
                        cv2.rectangle(shown, (start_bx1, deck_y + 18), (start_bx2, deck_y + 44), (20, 135, 45), -1)
                        cv2.rectangle(shown, (start_bx1, deck_y + 18), (start_bx2, deck_y + 44), (80, 255, 120), 2)
                        cv2.putText(shown, "START [ENTER]", (start_bx1 + 10, ctrl_y - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 2, cv2.LINE_AA)
                    else:
                        # Режим активного анализа (после пуска)
                        speed_x1 = max(300, min(350, video_window_w - 340))
                        cv2.rectangle(shown, (speed_x1, deck_y + 20), (speed_x1 + 48, deck_y + 42), (30, 38, 50), -1)
                        cv2.rectangle(shown, (speed_x1, deck_y + 20), (speed_x1 + 48, deck_y + 42), (70, 85, 110), 1)
                        cv2.putText(shown, f"{speed:.1f}x", (speed_x1 + 7, ctrl_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 235, 200), 1, cv2.LINE_AA)

                        # Статус блокировки ROI
                        cv2.putText(shown, "ROI LOCKED", (max(speed_x1 + 60, video_window_w - 275), ctrl_y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (120, 240, 160), 1, cv2.LINE_AA)

                        # Кнопка сброса [R] Reset ROI
                        rst_bx1 = max(video_window_w - 140, speed_x1 + 175)
                        rst_bx2 = video_window_w - 12
                        cv2.rectangle(shown, (rst_bx1, deck_y + 18), (rst_bx2, deck_y + 44), (35, 45, 60), -1)
                        cv2.rectangle(shown, (rst_bx1, deck_y + 18), (rst_bx2, deck_y + 44), (80, 100, 130), 1)
                        cv2.putText(shown, "[R] Reset", (rst_bx1 + 14, ctrl_y - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (220, 220, 220), 1, cv2.LINE_AA)
                else:
                    # Живая камера (Live Camera HUD & Interactive ROI Controls)
                    live_deck_h = 44
                    bot_y = video_window_h - live_deck_h
                    bot_overlay = shown.copy()
                    cv2.rectangle(bot_overlay, (0, bot_y), (video_window_w, video_window_h), (14, 18, 25), -1)
                    cv2.addWeighted(bot_overlay, 0.90, shown, 0.10, 0, shown)
                    cv2.line(shown, (0, bot_y), (video_window_w, bot_y), (40, 52, 70), 1)

                    ctrl_y = bot_y + 28

                    # 1. LIVE индикатор
                    cv2.rectangle(shown, (10, bot_y + 8), (72, bot_y + 36), (20, 20, 190), -1)
                    cv2.rectangle(shown, (10, bot_y + 8), (72, bot_y + 36), (60, 60, 255), 1)
                    cv2.circle(shown, (22, bot_y + 22), 4, (255, 255, 255), -1)
                    cv2.putText(shown, "LIVE", (32, ctrl_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (255, 255, 255), 2, cv2.LINE_AA)

                    # Время и точки
                    time_live_str = f"{hours:02d}:{mins:02d}:{secs:02d} | PTS:{snap['point_count']}"
                    cv2.putText(shown, time_live_str, (82, ctrl_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 240, 220), 1, cv2.LINE_AA)

                    # 2. Интерактивные кнопки управления ROI:
                    is_locked = bool(config.get('roi_locked', False))
                    shape_name = config.get('roi_shape', 'circle')

                    btn_center_w = 95
                    btn_lock_w = 115
                    btn_shape_w = 115

                    btn_center_x2 = video_window_w - 10
                    btn_center_x1 = btn_center_x2 - btn_center_w

                    btn_lock_x2 = btn_center_x1 - 8
                    btn_lock_x1 = btn_lock_x2 - btn_lock_w

                    btn_shape_x2 = btn_lock_x1 - 8
                    btn_shape_x1 = max(btn_shape_x2 - btn_shape_w, 240)

                    # Кнопка переключения формы: [C] Circle / [C] Square
                    cv2.rectangle(shown, (btn_shape_x1, bot_y + 8), (btn_shape_x2, bot_y + 36), (30, 45, 60), -1)
                    cv2.rectangle(shown, (btn_shape_x1, bot_y + 8), (btn_shape_x2, bot_y + 36), (0, 200, 240), 1)
                    shape_label = "[C] Circle" if shape_name == 'circle' else "[C] Square"
                    cv2.putText(shown, shape_label, (btn_shape_x1 + 10, ctrl_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (240, 240, 240), 1, cv2.LINE_AA)

                    # Кнопка блокировки ROI: [B] Free / [B] Locked
                    if is_locked:
                        cv2.rectangle(shown, (btn_lock_x1, bot_y + 8), (btn_lock_x2, bot_y + 36), (60, 25, 25), -1)
                        cv2.rectangle(shown, (btn_lock_x1, bot_y + 8), (btn_lock_x2, bot_y + 36), (80, 80, 255), 1)
                        cv2.putText(shown, "[B] Locked", (btn_lock_x1 + 10, ctrl_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 140, 255), 1, cv2.LINE_AA)
                    else:
                        cv2.rectangle(shown, (btn_lock_x1, bot_y + 8), (btn_lock_x2, bot_y + 36), (20, 55, 35), -1)
                        cv2.rectangle(shown, (btn_lock_x1, bot_y + 8), (btn_lock_x2, bot_y + 36), (0, 220, 120), 1)
                        cv2.putText(shown, "[B] Free", (btn_lock_x1 + 10, ctrl_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 255, 160), 1, cv2.LINE_AA)

                    # Кнопка центрирования: [R] Center
                    cv2.rectangle(shown, (btn_center_x1, bot_y + 8), (btn_center_x2, bot_y + 36), (30, 40, 52), -1)
                    cv2.rectangle(shown, (btn_center_x1, bot_y + 8), (btn_center_x2, bot_y + 36), (70, 90, 120), 1)
                    cv2.putText(shown, "[R] Center", (btn_center_x1 + 8, ctrl_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)

                try:
                    vis_check = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE)
                    if window_was_visible and vis_check < 1:
                        should_close = True
                        break
                    cv2.imshow(WINDOW_NAME, shown)
                except Exception:
                    if window_was_visible:
                        should_close = True
                        break

            if video_recorder is not None and frame_count != last_recorded_frame_count:
                # Если включена настройка «Сохранять область анализа на видео» — записываем с наложенным ROI кругом
                if config.get('save_roi_on_video', False):
                    rec_frame = frame.copy()
                    if config.get('roi_shape', 'rect') == 'circle':
                        center = (safe_x + safe_w // 2, safe_y + safe_h // 2)
                        radius = min(safe_w, safe_h) // 2
                        cv2.circle(rec_frame, center, radius, (0, 255, 0), 2)
                    else:
                        cv2.rectangle(rec_frame, (safe_x, safe_y), (safe_x + safe_w, safe_y + safe_h), (0, 255, 0), 2)
                    frame_to_record = rec_frame
                else:
                    frame_to_record = frame
                video_recorder.write(frame_to_record)
                last_recorded_frame_count = frame_count

            raw_key = cv2.waitKey(1 if show_video_window else 5)
            key = raw_key & 0xFF if raw_key != -1 else -1
            if key in (ord('q'), ord('Q'), 27):
                should_close = True
                break
            
            is_started = getattr(camera_worker, 'is_analysis_started', True) if camera_worker else True

            # Горячие клавиши формы и блокировки ROI
            is_c_pressed = (
                key in (ord('c'), ord('C'), 241, 209, 0x43, 0x63) or
                raw_key in (ord('c'), ord('C'), 1089, 1057, 1745, 1713, 241, 209, 0x43, 0x63)
            )
            if is_c_pressed:
                _trigger_toggle_shape()

            is_b_pressed = (
                key in (ord('b'), ord('B'), 232, 200, 0x42, 0x62) or
                raw_key in (ord('b'), ord('B'), 1080, 1048, 1736, 1704, 232, 200, 0x42, 0x62)
            )
            if is_b_pressed:
                _trigger_toggle_lock()

            # Горячая клавиша 'S' / 's' / 'ы' / 'Ы'
            is_s_pressed = (
                key in (ord('s'), ord('S'), 251, 219, 0x53, 0x73) or
                raw_key in (ord('s'), ord('S'), 1099, 1067, 1755, 1723, 251, 219, 0x53, 0x73) or
                (raw_key & 0xFFFF) in (ord('s'), ord('S'), 1099, 1067, 1755, 1723, 251, 219)
            )
            if is_s_pressed:
                _trigger_snap_roi()

            if is_file:
                seek_step = float(config.get('seek_step_sec', 5.0))
                if not is_started:
                    # Режим настройки ROI (до пуска анализа)
                    if key in (32, 13, 10, ord('\r'), ord('\n')) or raw_key in (32, 13, 10): # Space or Enter -> Запуск активного анализа
                        if camera_worker is not None:
                            camera_worker.start_analysis()
                    elif key in (ord('a'), ord('A'), 81, 2424832):
                        camera_worker.seek_relative(-seek_step)
                    elif key in (ord('d'), ord('D'), 83, 2555904):
                        camera_worker.seek_relative(seek_step)
                else:
                    # Режим активного анализа (после пуска)
                    if key == 32 or raw_key == 32: # Space -> Toggle pause
                        camera_worker.toggle_pause()
                    elif key in (ord('r'), ord('R'), 234, 202) or raw_key in (ord('r'), ord('R'), 1082, 1050): # R -> Reset to setup mode & unlock ROI
                        if camera_worker is not None:
                            camera_worker.reset_to_setup_mode()
                            snap_toast_time = time.time() + 2.0
                            snap_toast_msg = "RESET: ROI UNLOCKED FOR ADJUSTMENT"
                            roi_drag['toast_time'] = snap_toast_time
                            roi_drag['toast_msg'] = snap_toast_msg
                            print("🔄 Анализ сброшен. Кружок ROI разблокирован для настройки.")
                    elif key in (ord('+'), ord('=')):
                        camera_worker.set_speed(min(16.0, camera_worker.playback_speed * 1.5))
                    elif key in (ord('-'), ord('_')):
                        camera_worker.set_speed(max(0.1, camera_worker.playback_speed / 1.5))
                    elif key == ord('1'):
                        camera_worker.set_speed(1.0)
                    elif key == ord('2'):
                        camera_worker.set_speed(2.0)
                    elif key == ord('4'):
                        camera_worker.set_speed(4.0)
                    elif key == ord('8'):
                        camera_worker.set_speed(8.0)
                    elif key in (ord('0'), ord('5')):
                        camera_worker.set_speed(0.5)
                    elif key in (ord('a'), ord('A'), 81, 2424832):
                        camera_worker.seek_relative(-seek_step)
                    elif key in (ord('d'), ord('D'), 83, 2555904):
                        camera_worker.seek_relative(seek_step)
                    elif key == ord('.'):
                        camera_worker.seek_relative(1.0 / max(1.0, float(snap.get('file_fps') or 25.0)))
                    elif key == ord(','):
                        camera_worker.seek_relative(-1.0 / max(1.0, float(snap.get('file_fps') or 25.0)))
            else:
                # Живая камера: клавиша R центрирует ROI
                if key in (ord('r'), ord('R'), 234, 202) or raw_key in (ord('r'), ord('R'), 1082, 1050):
                    _trigger_center_roi()

            if live_win is not None:
                if key == ord('m'):
                    live_win._safe_call(live_win._add_annotation_current)
                elif key == ord('M'):
                    live_win._safe_call(live_win._add_annotation_dialog)

            vis = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) if show_video_window else 1
            if vis >= 1:
                window_was_visible = True
            elif window_was_visible and vis == 0:
                should_close = True
                break

    except KeyboardInterrupt:
        print("\n⏹️ Остановлено.")
    finally:
        video_saved_path = None
        saved_data = []
        performance_summary = {}
        if camera_worker is not None and camera_worker._thread is not None:
            camera_worker.stop()
        if camera_worker is not None:
            final_snapshot = camera_worker.snapshot(copy_frame=False)
            # The worker has stopped, so reuse its immutable-for-this-finalize
            # row list instead of allocating a second pointer list for long runs.
            saved_data = final_snapshot['saved_data']
            performance_summary = camera_worker.performance_summary()
        excel_path = None
        graph_path = None
        graph_error = None
        annotations_path = None
        save_error = None
        ann_count = 0
        if live_win is not None and live_win.session_excel_path:
            try:
                save_annotations_to_workbook(live_win.session_excel_path, live_win.annotation_manager)
                annotations_path = live_win.session_excel_path
                ann_count = len(live_win.annotation_manager.get_annotations())
                if ann_count:
                    print(f"📌 Меток в Excel: {ann_count} (лист Annotations)")
            except Exception as e:
                print(f"❌ Ошибка сохранения меток: {e}")

        if saved_data:
            try:
                ann_list = (
                    live_win.annotation_manager.get_annotations()
                    if live_win is not None else []
                )
                excel_path = save_to_excel(
                    save_folder, saved_data,
                    excel_path=session_excel_path if session_excel_path else None,
                    annotations=ann_list,
                    custom_graphs=config.get("custom_graphs", []),
                    custom_variables=config.get("custom_variables", []),
                )
                print(f"\n💾 Сохранено в Excel: {excel_path}")
                print(f"📊 Записей: {len(saved_data)}")
                print(f"⏱️ Длительность: {saved_data[-1][0]:.0f} мс")
            except Exception as e:
                save_error = f"Excel: {e}\n{traceback.format_exc()}"
                print(f"❌ Ошибка сохранения Excel: {e}")
                traceback.print_exc()

            # PNG is a convenience export only; never let Matplotlib or a
            # filesystem error prevent the analysis result from being returned.
            try:
                graph_folder = config.get("exports_folder") or os.path.join(save_folder, "exports")
                os.makedirs(graph_folder, exist_ok=True)
                source_excel = excel_path or session_excel_path
                graph_base = os.path.splitext(os.path.basename(source_excel or "analysis"))[0]
                graph_path = save_graph_to_image(graph_folder, saved_data, graph_base)
            except Exception as e:
                graph_error = str(e)
                print(f"⚠️ Не удалось экспортировать PNG-график: {e}")

        if video_recorder is not None:
            try:
                print("🎥 Завершаю видео после сохранения Excel/CSV...")
                video_saved_path = video_recorder.stop()
                if video_saved_path:
                    print(f"🎥 Видео сохранено: {video_saved_path}")
                else:
                    video_warning = video_recorder.get_last_error()
                    if video_warning:
                        print(f"⚠️ Видео не сохранено или пустое: {video_warning}")
            except Exception as e:
                print(f"⚠️ Ошибка завершения записи видео: {e}")
                traceback.print_exc()

        if cap is not None and hasattr(cap, 'release'):
            try:
                cap.release()
            except Exception:
                pass

        if live_win is not None:
            try:
                live_win.win.close()
                live_win.win.deleteLater()
                if pg_app is not None:
                    pg_app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            except Exception:
                pass

        try:
            cv2.destroyAllWindows()
            for _ in range(5):
                cv2.waitKey(1)
        except Exception:
            pass

        print("✅ Завершено.")

        return {
            'saved_data': saved_data,
            'excel_path': excel_path,
            'session_excel_path': session_excel_path,
            'graph_path': graph_path,
            'graph_error': graph_error,
            'raw_csv_path': raw_csv_path,
            'video_saved_path': video_saved_path,
            'save_error': save_error,
            'ann_count': ann_count,
            'save_folder': save_folder,
            'performance_summary': performance_summary,
        }

