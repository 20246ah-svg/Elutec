import csv
import os
import time
import numpy as np
from typing import List, Any, Optional

from ..config import CSV_FLUSH_INTERVAL_SEC, CSV_FLUSH_ROWS

import csv
import os
import time
from typing import List, Any, Optional


class CsvLogger:
    """
    Пишет строки данных в CSV-файл с периодическим flush.
    Предполагается, что каждая строка содержит: time_ms, R, G, B, log_br, log_bg,
    rgb_sum, r_frac, g_frac, b_frac, tri_x, tri_y, rgb_sum_smooth, rgb_sum_slope10,
    rgb_sum_slope30, rgb_vector_speed30, chromaticity_speed30, k_chrom_previous,
    log_ratio_speed30, rgb_sum_acceleration30, transition_score.
    """

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath
        self._file = None
        self._writer = None
        self._last_flush = 0.0
        self._rows_since_flush = 0
        self._error = ''
        if filepath:
            self._open()

    def _open(self):
        if not self.filepath:
            return
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            self._file = open(self.filepath, 'w', newline='', encoding='utf-8-sig')
            self._writer = csv.writer(self._file, delimiter=';')
            self._writer.writerow([
                'time_ms', 'time_s', 'time_min', 'R', 'G', 'B',
                'Log10(B/R)', 'Log10(B/G)', 'RGB_sum', 'R_frac', 'G_frac', 'B_frac',
                'RGB_triangle_X', 'RGB_triangle_Y', 'RGB_sum_smooth_10s',
                'RGB_sum_slope_10s', 'RGB_sum_slope_30s', 'RGB_vector_speed_30s',
                'Chromaticity_speed_30s', 'K_chrom_from_previous_state',
                'Log_ratio_speed_30s', 'RGB_sum_acceleration_30s', 'Transition_score'
            ])
            self._flush(force=True)
            print(f"🛟 Аварийный CSV RGB: {self.filepath}")
        except Exception as e:
            self._error = f'Не удалось открыть аварийный CSV: {e}'
            self._file = None
            self._writer = None
            print(f"⚠️ {self._error}")

    def write_row(self, row: List[Any]):
        if self._writer is None:
            return
        try:
            t_ms = float(row[0])
            self._writer.writerow([
                int(t_ms),
                round(t_ms / 1000.0, 3),
                round(t_ms / 60000.0, 5),
                *[self._finite_or_blank(v) for v in row[1:]]
            ])
            self._rows_since_flush += 1
            now = time.time()
            if (now - self._last_flush) >= CSV_FLUSH_INTERVAL_SEC or self._rows_since_flush >= CSV_FLUSH_ROWS:
                self._flush(force=True)
        except Exception as e:
            self._error = f'Ошибка записи аварийного CSV: {e}'
            print(f"⚠️ {self._error}")
            self._flush(force=True)
            self._writer = None

    def _flush(self, force=False):
        if self._file is None:
            return
        try:
            self._file.flush()
            if force:
                os.fsync(self._file.fileno())
            self._last_flush = time.time()
            self._rows_since_flush = 0
        except Exception as e:
            self._error = f'Ошибка flush аварийного CSV: {e}'
            print(f"⚠️ {self._error}")

    def close(self):
        if self._file is None:
            return
        try:
            self._flush(force=True)
        except Exception:
            pass
        try:
            self._file.close()
            print(f"🛟 Аварийный CSV закрыт: {self.filepath}")
        except Exception as e:
            print(f"⚠️ Ошибка закрытия аварийного CSV: {e}")
        finally:
            self._file = None
            self._writer = None

    @staticmethod
    def _finite_or_blank(value, ndigits=9):
        try:
            v = float(value)
            if not np.isfinite(v):
                return ''
            return round(v, ndigits)
        except Exception:
            return ''

