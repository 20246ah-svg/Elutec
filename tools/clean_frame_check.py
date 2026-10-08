"""Проверка пресета «Чистый кадр» на реальной камере (Windows, MiiCam/ToupCam).

Запуск из корня проекта:
    python tools/clean_frame_check.py                 # 100 кадров на каждый режим
    python tools/clean_frame_check.py --frames 200 --roi 300,150,200,200 --out report.json

Что делает:
  1. Показывает, какие форматы пикселей поддерживает камера (есть ли RAW8/10/12/16).
  2. Снимает серию кадров с пресетом «По умолчанию», затем с пресетом «Чистый кадр».
  3. По каждой серии считает по каналам B, G, R внутри ROI: среднее, временной шум
     (стандартное отклонение среднего по кадрам, и в % от среднего), пространственный шум,
     дрейф за серию, долю пикселей в клиппинге (>=250 и <=2).
  4. Печатает, что камера реально приняла (опции ISP) и предупреждения.

ВАЖНО: образец и освещение на время проверки должны быть неподвижны и стабильны.
Скрипт меняет настройки камеры только в оперативной памяти камеры (файлы настроек не трогает).
"""
import argparse
import ctypes
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHANNELS = ("B", "G", "R")


# ----------------------------------------------------------------------------
# Чистая статистика (не требует камеры, покрыта тестами)
# ----------------------------------------------------------------------------
def clamp_roi(frame_shape, roi):
    h_f, w_f = frame_shape[:2]
    x, y, w, h = [int(v) for v in roi]
    x = max(0, min(x, w_f - 1))
    y = max(0, min(y, h_f - 1))
    w = max(1, min(w, w_f - x))
    h = max(1, min(h, h_f - y))
    return x, y, w, h


def default_roi(frame_shape, size=200):
    h_f, w_f = frame_shape[:2]
    size = min(size, h_f, w_f)
    return (w_f - size) // 2, (h_f - size) // 2, size, size


def summarize(frames, roi):
    """Статистика серии кадров BGR uint8 по ROI. Возвращает словарь с массивами по каналам (B, G, R)."""
    if not frames:
        raise ValueError("пустая серия кадров")
    x, y, w, h = clamp_roi(frames[0].shape, roi)
    subs = [f[y:y + h, x:x + w].reshape(-1, 3) for f in frames]
    means = np.array([s.mean(axis=0) for s in subs], dtype=np.float64)          # N x 3
    n = len(frames)
    mean = means.mean(axis=0)
    t_std = means.std(axis=0, ddof=1) if n > 1 else np.zeros(3)
    spatial = np.mean([s.std(axis=0) for s in subs], axis=0)
    clip_hi = np.mean([(s >= 250).mean(axis=0) for s in subs], axis=0) * 100.0
    clip_lo = np.mean([(s <= 2).mean(axis=0) for s in subs], axis=0) * 100.0
    if n > 2:
        idx = np.arange(n, dtype=np.float64)
        drift = np.array([np.polyfit(idx, means[:, c], 1)[0] * (n - 1) for c in range(3)])
    else:
        drift = np.zeros(3)
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = np.where(mean > 0, t_std / mean * 100.0, 0.0)
    return {
        "frames": n, "roi": (x, y, w, h),
        "mean": mean, "temporal_std": t_std, "temporal_cv_percent": cv,
        "spatial_std": spatial, "drift": drift,
        "clip_hi_percent": clip_hi, "clip_lo_percent": clip_lo,
    }


def advice(summary):
    """Короткие подсказки по результатам серии."""
    tips = []
    if float(np.max(summary["clip_hi_percent"])) > 0.5:
        tips.append("Есть клиппинг по свету (>=250): уменьшите выдержку или яркость подсветки (не усиление).")
    if float(np.max(summary["mean"])) < 60:
        tips.append("Кадр тёмный (макс. канал < 60): добавьте света или увеличьте выдержку кратно 10 мс; усиление держите на 100%.")
    if float(np.max(summary["clip_lo_percent"])) > 5:
        tips.append("Много пикселей около нуля (<=2): сигнал упирается в чёрный уровень, ratio-метрики будут шумными.")
    if float(np.max(np.abs(summary["drift"]))) > 1.5:
        tips.append("Дрейф среднего за серию > 1.5 ед.: дайте камере и подсветке прогреться, проверьте стабильность света.")
    return tips


def format_summary(title, s):
    rows = [f"--- {title} ({s['frames']} кадров, ROI x={s['roi'][0]} y={s['roi'][1]} w={s['roi'][2]} h={s['roi'][3]}) ---",
            "канал   среднее   шум(врем.)   шум %    шум(простр.)   дрейф   клип>=250 %   клип<=2 %"]
    for i, name in enumerate(CHANNELS):
        rows.append(f"  {name}     {s['mean'][i]:7.2f}   {s['temporal_std'][i]:9.3f}   {s['temporal_cv_percent'][i]:6.3f}   "
                    f"{s['spatial_std'][i]:11.2f}   {s['drift'][i]:6.2f}   {s['clip_hi_percent'][i]:10.3f}   {s['clip_lo_percent'][i]:9.3f}")
    for tip in advice(s):
        rows.append("  ! " + tip)
    return "\n".join(rows)


# ----------------------------------------------------------------------------
# Работа с камерой
# ----------------------------------------------------------------------------
def probe_pixel_formats(cap):
    """Список форматов пикселей, которые поддерживает камера (RAW8/10/12/16 и т.д.). Только чтение."""
    from src.utils.miicam_wrapper import _find_and_load_dll
    dll = _find_and_load_dll()
    out = []
    if not dll or not getattr(cap, "handle", None):
        return out
    get_support = getattr(dll, "Miicam_get_PixelFormatSupport", None) or getattr(dll, "Toupcam_get_PixelFormatSupport", None)
    get_name = getattr(dll, "Miicam_get_PixelFormatName", None) or getattr(dll, "Toupcam_get_PixelFormatName", None)
    get_depth = getattr(dll, "Miicam_get_PixelFormatBitdepth", None) or getattr(dll, "Toupcam_get_PixelFormatBitdepth", None)
    if not get_support:
        return out
    try:
        get_support.restype = ctypes.c_int
        get_support.argtypes = [ctypes.c_void_p, ctypes.c_byte, ctypes.POINTER(ctypes.c_int)]
        val = ctypes.c_int(0)
        hr = int(get_support(cap.handle, ctypes.c_byte(-1), ctypes.byref(val)))
        count = hr if hr > 0 else int(val.value)
        for i in range(max(0, min(count, 32))):
            fmt = ctypes.c_int(-1)
            if int(get_support(cap.handle, ctypes.c_byte(i), ctypes.byref(fmt))) < 0:
                continue
            name = f"format {fmt.value}"
            depth = None
            if get_name:
                get_name.restype = ctypes.c_char_p
                get_name.argtypes = [ctypes.c_int]
                raw = get_name(fmt.value)
                if raw:
                    name = raw.decode("ascii", "replace")
            if get_depth:
                get_depth.restype = ctypes.c_int
                get_depth.argtypes = [ctypes.c_int]
                depth = int(get_depth(fmt.value))
            out.append({"id": int(fmt.value), "name": name, "bitdepth": depth})
    except Exception as exc:  # диагностика не должна ронять скрипт
        out.append({"id": -1, "name": f"ошибка запроса: {exc}", "bitdepth": None})
    return out


def collect_frames(cap, n, timeout_s=30.0):
    frames, t_end = [], time.time() + timeout_s
    last_id = None
    while len(frames) < n and time.time() < t_end:
        ok, frame = cap.read()
        if ok and frame is not None and frame.size:
            fid = id(frame)
            if fid != last_id:
                frames.append(frame.copy())
                last_id = fid
        time.sleep(0.01)
    return frames


def run_mode(cap, title, cfg, n_frames, roi, settle_s):
    cap.apply_settings_dict(cfg)
    time.sleep(settle_s)
    frames = collect_frames(cap, n_frames)
    if not frames:
        print(f"{title}: кадры не получены")
        return None
    use_roi = roi or default_roi(frames[0].shape)
    summary = summarize(frames, use_roi)
    print(format_summary(title, summary))
    return summary


def _to_jsonable(summary):
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in summary.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Сравнение пресетов «По умолчанию» и «Чистый кадр»")
    ap.add_argument("--frames", type=int, default=100, help="кадров на режим (по умолчанию 100)")
    ap.add_argument("--roi", type=str, default="", help="x,y,w,h (по умолчанию центр 200x200)")
    ap.add_argument("--settle", type=float, default=1.5, help="пауза после смены настроек, с")
    ap.add_argument("--out", type=str, default="", help="сохранить результаты в JSON")
    args = ap.parse_args(argv)

    from src.config import DEFAULT_DETECTOR_PRESETS, CLEAN_FRAME_PRESET
    from src.utils.miicam_wrapper import MiiCamCapture, enumerate_miicam_devices

    devices = enumerate_miicam_devices()
    if not devices:
        print("Камера MiiCam не найдена (проверьте USB, драйвер, не занята ли другой программой).")
        return 3
    cap = MiiCamCapture(f"miicam:{devices[0]['index']}")
    try:
        if not cap.isOpened():
            print("Не удалось открыть камеру.")
            return 4
        print(f"Камера: {devices[0]['name']}  кадр {cap._width}x{cap._height}")
        formats = probe_pixel_formats(cap)
        print("Поддерживаемые форматы пикселей:", ", ".join(
            f"{f['name']}" + (f" ({f['bitdepth']} бит)" if f.get("bitdepth") else "") for f in formats) or "нет данных")
        roi = tuple(int(v) for v in args.roi.split(",")) if args.roi else None

        base = run_mode(cap, "По умолчанию", DEFAULT_DETECTOR_PRESETS["По умолчанию (Default)"], args.frames, roi, args.settle)
        clean = run_mode(cap, "Чистый кадр", CLEAN_FRAME_PRESET, args.frames, roi, args.settle)

        report = cap.get_clean_frame_report()
        print("\nЧто приняла камера:")
        for name, r in report["options"].items():
            print(f"  {name:14s} = {r['value']:<6} {'OK' if r['ok'] else 'ОТКЛОНЕНО'}"
                  + ("" if r.get("readback") is None else f"   (readback {r['readback']})"))
        for w in report["warnings"]:
            print("  ! " + w)
        if base and clean:
            print("\nСравнение шума (временной, % от среднего):")
            for i, name in enumerate(CHANNELS):
                print(f"  {name}: {base['temporal_cv_percent'][i]:.3f}% -> {clean['temporal_cv_percent'][i]:.3f}%")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump({"pixel_formats": formats, "default": _to_jsonable(base) if base else None,
                           "clean": _to_jsonable(clean) if clean else None, "camera_report": report},
                          fh, ensure_ascii=False, indent=2)
            print("Отчёт сохранён:", args.out)
        return 0
    finally:
        cap.release()


if __name__ == "__main__":
    raise SystemExit(main())
