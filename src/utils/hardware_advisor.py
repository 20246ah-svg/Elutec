"""Local hardware diagnostics and conservative ELUTEC profile recommendations.

The module intentionally avoids machine identifiers (host name, user name, MAC
address and device serials). The short benchmark performs no file writes and
never changes camera/sensor controls or the active configuration.
"""
from __future__ import annotations

import math
import os
import platform
import struct
import time
from datetime import datetime, timezone

from ..config import DEFAULT_PERFORMANCE_PROFILE, PERFORMANCE_PROFILES


DIAGNOSTIC_SCHEMA_VERSION = 1
BENCHMARK_VERSION = 1
_GIB = 1024 ** 3


def _memory_bytes():
    """Return (total, available) physical memory in bytes when discoverable."""
    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except Exception:
            pass

    if hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            total_pages = int(os.sysconf("SC_PHYS_PAGES"))
            available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            if page_size > 0 and total_pages > 0:
                total = page_size * total_pages
                available = page_size * max(0, available_pages)
                return total, min(total, available)
        except (AttributeError, OSError, TypeError, ValueError):
            pass

    # Fallback for Linux containers and unusual libc builds.
    try:
        values = {}
        with open("/proc/meminfo", "r", encoding="ascii") as stream:
            for line in stream:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    values[key] = int(rest.strip().split()[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if total:
            return total, min(total, available) if available is not None else None
    except (OSError, ValueError, IndexError):
        pass
    return None, None


def _cpu_model():
    value = (platform.processor() or "").strip()
    if value:
        return value[:160]
    if platform.system().lower() == "linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    key, separator, value = line.partition(":")
                    if separator and key.strip().lower() in ("model name", "hardware", "processor"):
                        value = value.strip()
                        if value:
                            return value[:160]
        except OSError:
            pass
    return None


def collect_system_profile():
    """Collect coarse, non-unique computer characteristics using the stdlib."""
    total_memory, available_memory = _memory_bytes()
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "os": platform.system() or "unknown",
        "architecture": platform.machine() or "unknown",
        "python_bits": struct.calcsize("P") * 8,
        "cpu_model": _cpu_model(),
        "logical_cores": max(1, int(os.cpu_count() or 1)),
        "memory_total_bytes": total_memory,
        "memory_available_bytes": available_memory,
    }


def _percentile(values, percentile):
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, int(math.ceil(percentile * len(ordered)) - 1)))
    return ordered[index]


def benchmark_analysis_path(frame=None, config=None, duration_seconds=0.8):
    """Benchmark a representative ROI + metrics pass without touching a camera.

    When a preview frame is supplied it is used as a read-only sample. Without
    one, a small synthetic frame is used and the result is explicitly marked as
    approximate. History is capped at 20k points to keep the test bounded.
    """
    import numpy as np

    from .helpers import compute_roi_means
    from .math_utils import (
        compute_chrom_distance_from_previous_state_with_current,
        compute_window_mean_with_current,
        compute_window_rate_with_current,
    )

    settings = dict(config or {})
    source = "preview_frame" if frame is not None else "synthetic_frame"
    if frame is None or getattr(frame, "size", 0) == 0:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame_height, frame_width = frame.shape[:2]
    roi_config = {
        "roi_x": int(settings.get("roi_x", 0) or 0),
        "roi_y": int(settings.get("roi_y", 0) or 0),
        "roi_w": max(10, int(settings.get("roi_w", min(200, frame_width)) or 10)),
        "roi_h": max(10, int(settings.get("roi_h", min(200, frame_height)) or 10)),
        "roi_shape": settings.get("roi_shape", "rect"),
        "wb_r_mult": settings.get("wb_r_mult", 1.0),
        "wb_g_mult": settings.get("wb_g_mult", 1.0),
        "wb_b_mult": settings.get("wb_b_mult", 1.0),
    }

    try:
        configured_points = max(1000, int(settings.get("max_points", 50000)))
    except (TypeError, ValueError):
        configured_points = 50000
    history_points = min(configured_points, 20000)
    analysis_interval_ms = max(1, int(settings.get("analysis_interval_ms", 15) or 15))
    tick = np.arange(history_points, dtype=np.float64)
    time_values = tick * analysis_interval_ms
    current_time_ms = float(time_values[-1])
    history_times = time_values[:-1]

    # Positive and smoothly varying signals exercise the same window/derivative
    # routines used by CameraWorker without depending on any real experiment.
    red = 100.0 + 20.0 * np.sin(tick / 37.0)
    green = 110.0 + 15.0 * np.sin(tick / 43.0 + 0.4)
    blue = 90.0 + 18.0 * np.cos(tick / 41.0)
    rgb_sum = red + green + blue
    tri_x = 0.35 + 0.02 * np.sin(tick / 53.0)
    tri_y = 0.25 + 0.02 * np.cos(tick / 59.0)
    log_br = np.log10(blue / red)
    log_bg = np.log10(blue / green)
    signals = (red, green, blue, rgb_sum, tri_x, tri_y, log_br, log_bg)

    def _process_one_sample():
        compute_roi_means(frame, roi_config)
        compute_window_mean_with_current(
            history_times, rgb_sum[:-1], current_time_ms, rgb_sum[-1], window_ms=10000.0
        )
        for signal in signals:
            compute_window_rate_with_current(
                history_times, signal[:-1], current_time_ms, signal[-1], window_ms=30000.0
            )
        compute_chrom_distance_from_previous_state_with_current(
            history_times, tri_x[:-1], tri_y[:-1], current_time_ms, tri_x[-1], tri_y[-1]
        )

    # Warm native OpenCV/NumPy code paths and the circle-ROI mask cache.
    _process_one_sample()
    try:
        duration_seconds = float(duration_seconds)
    except (TypeError, ValueError):
        duration_seconds = 0.8
    duration_seconds = max(0.1, min(duration_seconds, 2.0))
    deadline = time.perf_counter() + duration_seconds
    samples_ms = []
    while time.perf_counter() < deadline or len(samples_ms) < 12:
        started = time.perf_counter()
        _process_one_sample()
        samples_ms.append((time.perf_counter() - started) * 1000.0)

    return {
        "version": BENCHMARK_VERSION,
        "sample_source": source,
        "frame_width": int(frame_width),
        "frame_height": int(frame_height),
        "history_points": int(history_points),
        "iterations": len(samples_ms),
        "duration_ms": round(sum(samples_ms), 3),
        "processing_p50_ms": round(_percentile(samples_ms, 0.50), 4),
        "processing_p95_ms": round(_percentile(samples_ms, 0.95), 4),
    }


def recommend_performance_profile(system_profile, benchmark=None, camera_fps=None):
    """Map measured headroom and coarse RAM limits to an existing profile.

    Recommendations deliberately favour UI/resource throttling over sensor
    controls. The caller applies the selected profile only after user action.
    """
    system_profile = dict(system_profile or {})
    benchmark = dict(benchmark or {})
    profiles = sorted(
        PERFORMANCE_PROFILES.items(),
        key=lambda item: int(item[1].get("analysis_interval_ms", 1000)),
    )
    if not profiles:
        return {
            "profile": DEFAULT_PERFORMANCE_PROFILE,
            "settings": {},
            "confidence": "low",
            "reasons": ["Не найдены встроенные профили производительности."],
        }

    total_memory = system_profile.get("memory_total_bytes")
    available_memory = system_profile.get("memory_available_bytes")
    try:
        total_memory = int(total_memory) if total_memory is not None else None
    except (TypeError, ValueError):
        total_memory = None
    try:
        available_memory = int(available_memory) if available_memory is not None else None
    except (TypeError, ValueError):
        available_memory = None

    # Large live histories and session export need memory as well as CPU.
    minimum_index = 0
    memory_limited = False
    if total_memory is not None and total_memory < 4 * _GIB:
        minimum_index = 3
        memory_limited = True
    elif total_memory is not None and total_memory < 8 * _GIB:
        minimum_index = 2
        memory_limited = True
    if available_memory is not None and available_memory < 512 * 1024 ** 2:
        minimum_index = max(minimum_index, len(profiles) - 1)
        memory_limited = True
    elif available_memory is not None and available_memory < 1024 * 1024 ** 2:
        minimum_index = max(minimum_index, min(3, len(profiles) - 1))
        memory_limited = True
    minimum_index = min(minimum_index, len(profiles) - 1)

    try:
        measured_p95 = float(benchmark.get("processing_p95_ms"))
        if not math.isfinite(measured_p95) or measured_p95 < 0:
            measured_p95 = None
    except (TypeError, ValueError):
        measured_p95 = None
    try:
        camera_fps = float(camera_fps)
        if not math.isfinite(camera_fps) or camera_fps <= 0:
            camera_fps = None
    except (TypeError, ValueError):
        camera_fps = None
    camera_interval_floor = 900.0 / camera_fps if camera_fps else 0.0

    selected_index = None
    if measured_p95 is not None:
        for index, (name, values) in enumerate(profiles):
            if index < minimum_index:
                continue
            interval = max(1, int(values.get("analysis_interval_ms", 50)))
            if interval < camera_interval_floor:
                continue
            # Keep ~30% headroom so the worker has time for capture, UI and I/O.
            if measured_p95 <= interval * 0.70:
                selected_index = index
                break

    reasons = []
    if selected_index is None:
        # A fallback is still useful when the source rate or measured throughput
        # cannot be met by any preset; choose the slowest safe existing option.
        selected_index = max(minimum_index, len(profiles) - 1)
        if measured_p95 is None:
            try:
                cores = int(system_profile.get("logical_cores") or 0)
            except (TypeError, ValueError):
                cores = 0
            if total_memory is not None and total_memory < 4 * _GIB or (cores and cores <= 2):
                selected_index = len(profiles) - 1
            elif total_memory is not None and total_memory < 8 * _GIB or (cores and cores <= 4):
                selected_index = max(minimum_index, min(3, len(profiles) - 1))
            else:
                selected_index = max(minimum_index, min(2, len(profiles) - 1))
            reasons.append("Точный тест не завершён; выбор предварительный, по числу ядер и доступной памяти.")
        else:
            reasons.append("Тестовая нагрузка не укладывается в интервалы более быстрых профилей с запасом.")

    name, settings = profiles[selected_index]
    if measured_p95 is not None:
        interval = max(1, int(settings.get("analysis_interval_ms", 50)))
        reasons.insert(0, "P95 расчётного пакета: {:.2f} мс; интервал профиля: {} мс.".format(measured_p95, interval))
    if camera_fps:
        camera_period = 1000.0 / camera_fps
        reasons.append("Источник выдаёт около {:.1f} кадр/с (≈{:.1f} мс на кадр); более частый анализ не добавит кадров.".format(camera_fps, camera_period))
    if memory_limited:
        reasons.append("Учтена доступная/общая RAM; выбрана настройка с меньшей историей графиков.")
    if benchmark.get("sample_source") == "synthetic_frame":
        reasons.append("Камера не участвовала в тесте: скорость ROI оценена на синтетическом кадре.")
    if benchmark.get("sample_source") == "preview_frame":
        reasons.append("Проверка использовала копию кадра предпросмотра; выдержка, усиление и ROI не менялись.")

    confidence = "medium" if measured_p95 is not None and benchmark.get("sample_source") == "preview_frame" else "approximate"
    return {
        "profile": name,
        "settings": dict(settings),
        "confidence": confidence,
        "reasons": reasons,
        "camera_fps_used": round(camera_fps, 2) if camera_fps else None,
        "processing_p95_ms": round(measured_p95, 4) if measured_p95 is not None else None,
    }


def run_hardware_diagnostic(frame=None, config=None, camera_fps=None, duration_seconds=0.8):
    """Collect a local system profile, run a bounded test and make a suggestion."""
    system_profile = collect_system_profile()
    benchmark = benchmark_analysis_path(frame, config, duration_seconds=duration_seconds)
    recommendation = recommend_performance_profile(system_profile, benchmark, camera_fps)
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": system_profile,
        "benchmark": benchmark,
        "recommendation": recommendation,
        "notes": [
            "Рекомендация не применяется автоматически.",
            "Интервал анализа влияет на временное разрешение данных; настройки камеры не изменяются.",
            "Тест не включает кодек, сетевой источник и сохранение на диск.",
        ],
    }
