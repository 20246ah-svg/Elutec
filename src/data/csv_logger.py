"""Durable emergency CSV logging for an active analysis session."""

from __future__ import annotations

import csv
import os
import threading
import time
from typing import Any, Iterable, Optional

import numpy as np

from ..config import CSV_FLUSH_INTERVAL_SEC, CSV_FLUSH_ROWS


CSV_HEADERS = (
    "time_ms", "time_s", "time_min", "R", "G", "B",
    "Log10(B/R)", "Log10(B/G)", "RGB_sum", "R_frac", "G_frac", "B_frac",
    "RGB_triangle_X", "RGB_triangle_Y", "RGB_sum_smooth_10s",
    "RGB_sum_slope_10s", "RGB_sum_slope_30s", "RGB_vector_speed_30s",
    "Chromaticity_speed_30s", "K_chrom_from_previous_state",
    "Log_ratio_speed_30s", "RGB_sum_acceleration_30s", "Transition_score",
)


class CsvLogger:
    """Write analysis samples to an emergency CSV with bounded flush intervals.

    The logger deliberately keeps working if one malformed sample arrives.  A
    write/flush I/O error is retained in :attr:`error` and disables subsequent
    writes so the analysis thread itself never crashes.
    """

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath
        self._file = None
        self._writer = None
        self._lock = threading.RLock()
        self._last_flush = 0.0
        self._rows_since_flush = 0
        self._error = ""
        if filepath:
            self._open()

    @property
    def error(self) -> str:
        return self._error

    @property
    def is_open(self) -> bool:
        return self._writer is not None and self._file is not None

    def _open(self) -> bool:
        if not self.filepath:
            return False
        with self._lock:
            try:
                # ``dirname('session.csv')`` is empty.  Resolving it first also
                # makes a relative emergency-log path valid.
                parent = os.path.dirname(os.path.abspath(self.filepath))
                os.makedirs(parent, exist_ok=True)
                self._file = open(self.filepath, "w", newline="", encoding="utf-8-sig")
                self._writer = csv.writer(self._file, delimiter=";")
                self._writer.writerow(CSV_HEADERS)
                self._flush(force=True)
                print(f"🛟 Аварийный CSV RGB: {self.filepath}")
                return True
            except OSError as exc:
                self._error = f"Не удалось открыть аварийный CSV: {exc}"
                self._file = None
                self._writer = None
                print(f"⚠️ {self._error}")
                return False

    def write_row(self, row: Iterable[Any]) -> bool:
        """Write one raw analysis row; return ``True`` only when it was stored."""
        with self._lock:
            if self._writer is None:
                return False
            try:
                values = list(row)
                if not values:
                    raise ValueError("пустая строка")
                time_ms = float(values[0])
                if not np.isfinite(time_ms):
                    raise ValueError("time_ms не является конечным числом")
            except (TypeError, ValueError) as exc:
                self._error = f"Строка аварийного CSV пропущена: {exc}"
                return False

            try:
                self._writer.writerow((
                    int(time_ms),
                    round(time_ms / 1000.0, 3),
                    round(time_ms / 60000.0, 5),
                    *(self._finite_or_blank(value) for value in values[1:]),
                ))
                self._rows_since_flush += 1
                now = time.monotonic()
                if (
                    now - self._last_flush >= CSV_FLUSH_INTERVAL_SEC
                    or self._rows_since_flush >= CSV_FLUSH_ROWS
                ):
                    self._flush(force=True)
                return True
            except (OSError, csv.Error) as exc:
                self._error = f"Ошибка записи аварийного CSV: {exc}"
                print(f"⚠️ {self._error}")
                self._disable_writer()
                return False

    def _flush(self, force: bool = False) -> bool:
        if self._file is None:
            return False
        try:
            self._file.flush()
            if force:
                os.fsync(self._file.fileno())
            self._last_flush = time.monotonic()
            self._rows_since_flush = 0
            return True
        except OSError as exc:
            self._error = f"Ошибка flush аварийного CSV: {exc}"
            print(f"⚠️ {self._error}")
            return False

    def _disable_writer(self) -> None:
        file_obj, self._file = self._file, None
        self._writer = None
        if file_obj is not None:
            try:
                file_obj.close()
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            if self._file is None:
                return
            self._flush(force=True)
            file_obj, self._file = self._file, None
            self._writer = None
            try:
                file_obj.close()
                print(f"🛟 Аварийный CSV закрыт: {self.filepath}")
            except OSError as exc:
                self._error = f"Ошибка закрытия аварийного CSV: {exc}"
                print(f"⚠️ {self._error}")

    @staticmethod
    def _finite_or_blank(value: Any, ndigits: int = 9):
        try:
            number = float(value)
            return round(number, ndigits) if np.isfinite(number) else ""
        except (TypeError, ValueError):
            return ""
