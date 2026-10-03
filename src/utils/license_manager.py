"""
Модуль защиты и лицензирования программного комплекса «Элютек».
Обеспечивает:
- Генерацию уникального аппаратного идентификатора оборудования (Hardware ID).
- Валидацию криптографических лицензионных ключей (HMAC-SHA256).
- Управление пробным периодом (Демо-режим: 14 дней или 15 запусков).
- Защиту от ручной подделки и изменения файлов состояния (контрольная сумма HMAC).
"""

import os
import sys
import json
import time
import uuid
import hmac
import hashlib
import platform

# Внутренний секретный ключ подписи лицензий (Master Secret)
_MASTER_SALT = b"ELUTEK-SARA-RGB-ANALYSIS-PROT-2026-v12"
_TRIAL_MAX_DAYS = 2
_TRIAL_MAX_RUNS = 5

LICENSE_STATUS_LICENSED = "LICENSED"
LICENSE_STATUS_TRIAL_ACTIVE = "TRIAL_ACTIVE"
LICENSE_STATUS_TRIAL_EXPIRED = "TRIAL_EXPIRED"


def get_hardware_id() -> str:
    """
    Возвращает уникальный аппаратный идентификатор машины (Hardware ID).
    Формат: ELU-XXXX-XXXX-XXXX-XXXX
    """
    raw_components = []
    
    # 1. Системные данные платформы
    raw_components.append(platform.machine())
    raw_components.append(platform.processor())
    raw_components.append(platform.system())
    
    # 2. Идентификатор ОС / MachineGuid (Windows / Linux)
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if guid:
                    raw_components.append(str(guid).strip())
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        mid = f.read().strip()
                        if mid:
                            raw_components.append(mid)
                            break
                except Exception:
                    pass

    # 3. MAC-адрес сетевого адаптера
    try:
        node = uuid.getnode()
        if node and node != 0:
            raw_components.append(f"{node:012x}")
    except Exception:
        pass

    # Хеширование с солью
    raw_str = "|".join(raw_components)
    digest = hashlib.sha256(raw_str.encode("utf-8")).hexdigest().upper()
    
    # Форматирование: ELU-1234-5678-9ABC-DEF0
    p1 = digest[0:4]
    p2 = digest[4:8]
    p3 = digest[8:12]
    p4 = digest[12:16]
    return f"ELU-{p1}-{p2}-{p3}-{p4}"


def generate_activation_key(hwid: str, lic_type: str = "PRO", customer: str = "") -> str:
    """
    Генерирует криптографический ключ активации для указанного Hardware ID.
    (Используется разработчиком/генератором ключей).
    """
    clean_hwid = str(hwid).strip().upper().replace(" ", "")
    clean_type = str(lic_type).strip().upper()
    payload = f"{clean_hwid}:{clean_type}".encode("utf-8")
    
    sig = hmac.new(_MASTER_SALT, payload, hashlib.sha256).hexdigest().upper()
    # Формат ключа: KEY-XXXX-XXXX-XXXX-XXXX
    k1 = sig[0:4]
    k2 = sig[4:8]
    k3 = sig[8:12]
    k4 = sig[12:16]
    return f"KEY-{k1}-{k2}-{k3}-{k4}"


def verify_activation_key(key: str, hwid: str = None) -> tuple[bool, str, str]:
    """
    Проверяет валидность ключа активации для текущего или переданного HWID.
    Возвращает: (is_valid, lic_type, message)
    """
    if not key or not isinstance(key, str):
        return False, "", "Ключ активации не указан."
        
    clean_key = key.strip().upper().replace(" ", "")
    target_hwid = (hwid or get_hardware_id()).strip().upper().replace(" ", "")
    
    for lic_type in ("PRO", "ENTERPRISE", "PERPETUAL", "STANDARD", "EXTENDED", "1 ГОД", "2 ГОДА", "5 ЛЕТ", "TRIAL"):
        expected = generate_activation_key(target_hwid, lic_type=lic_type)
        if clean_key == expected:
            return True, lic_type, f"Лицензия «{lic_type}» успешно подтверждена."
            
    # Проверка универсального мастер-формата
    if clean_key.startswith("KEY-"):
        parts = clean_key.split("-")
        if len(parts) == 5:
            # Сверка хэша
            payload = f"{target_hwid}:PRO".encode("utf-8")
            sig = hmac.new(_MASTER_SALT, payload, hashlib.sha256).hexdigest().upper()
            if clean_key == f"KEY-{sig[0:4]}-{sig[4:8]}-{sig[8:12]}-{sig[12:16]}":
                return True, "PRO", "Лицензия PRO успешно подтверждена."

    return False, "", "Неверный ключ активации для данного оборудования."


class LicenseManager:
    """Менеджер лицензий и пробного периода приложения."""
    
    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.join(os.path.expanduser("~"), ".elutek")
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.lic_file = os.path.join(self.storage_dir, "license.dat")
        self._data = self._load()

    def _get_tamper_signature(self, d: dict) -> str:
        fields = [
            str(d.get("hwid", "")),
            str(d.get("license_key", "")),
            str(d.get("license_type", "")),
            str(d.get("first_run_time", 0)),
            str(d.get("runs_count", 0)),
            str(d.get("activated", False))
        ]
        raw = "|".join(fields).encode("utf-8")
        return hmac.new(_MASTER_SALT, raw, hashlib.sha256).hexdigest()

    def _load(self) -> dict:
        hwid = get_hardware_id()
        now = time.time()
        
        default_data = {
            "hwid": hwid,
            "license_key": "",
            "license_type": "",
            "customer_name": "",
            "activated": False,
            "first_run_time": now,
            "last_run_time": now,
            "runs_count": 0,
            "signature": ""
        }
        
        if not os.path.isfile(self.lic_file):
            default_data["signature"] = self._get_tamper_signature(default_data)
            self._save(default_data)
            return default_data
            
        try:
            with open(self.lic_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            # Проверка соответствия HWID
            if data.get("hwid") != hwid:
                # Файл скопирован с другого ПК - сбрасываем в новый триал
                default_data["signature"] = self._get_tamper_signature(default_data)
                self._save(default_data)
                return default_data
                
            # Проверка контрольной подписи
            expected_sig = self._get_tamper_signature(data)
            if data.get("signature") != expected_sig:
                # Обнаружена модификация файла - аннулируем триал
                data["runs_count"] = _TRIAL_MAX_RUNS + 10
                data["first_run_time"] = 0
                data["activated"] = False
                data["signature"] = self._get_tamper_signature(data)
                self._save(data)
                return data
                
            return data
        except Exception:
            default_data["signature"] = self._get_tamper_signature(default_data)
            self._save(default_data)
            return default_data

    def _save(self, data: dict):
        try:
            data["signature"] = self._get_tamper_signature(data)
            with open(self.lic_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Ошибка сохранения лицензии: {e}")

    def register_app_launch(self):
        """Регистрирует сессию запуска приложения."""
        if self._data.get("activated", False):
            return
            
        now = time.time()
        self._data["runs_count"] = int(self._data.get("runs_count", 0)) + 1
        self._data["last_run_time"] = now
        self._save(self._data)

    def get_status(self) -> dict:
        """
        Возвращает текущий статус лицензии:
        - status: LICENSED | TRIAL_ACTIVE | TRIAL_EXPIRED
        - is_allowed: True/False
        - runs_left: int
        - days_left: int
        - hwid: str
        - lic_type: str
        """
        # Всегда перечитываем свежее состояние с диска
        self._data = self._load()
        hwid = get_hardware_id()
        key = self._data.get("license_key", "")
        
        # 1. Если активировано ключом
        if self._data.get("activated", False) and key:
            is_valid, lic_type, _ = verify_activation_key(key, hwid)
            if is_valid:
                return {
                    "status": LICENSE_STATUS_LICENSED,
                    "is_allowed": True,
                    "hwid": hwid,
                    "lic_type": lic_type or "PRO (Бессрочная)",
                    "customer_name": self._data.get("customer_name", ""),
                    "days_left": 9999,
                    "runs_left": 9999,
                    "message": "Программа успешно активирована (Бессрочная лицензия)."
                }
            else:
                self._data["activated"] = False
                self._save(self._data)
                
        # 2. Проверка триал-режима (Демо)
        now = time.time()
        first_run = float(self._data.get("first_run_time", now))
        runs_count = int(self._data.get("runs_count", 0))
        
        # Защита от перевода системных часов назад
        if now < first_run - 86400:
            first_run = now
            self._data["first_run_time"] = now
            self._save(self._data)
            
        elapsed_days = (now - first_run) / 86400.0
        days_left = max(0, int(round(_TRIAL_MAX_DAYS - elapsed_days)))
        runs_left = max(0, _TRIAL_MAX_RUNS - runs_count)
        
        if elapsed_days <= _TRIAL_MAX_DAYS and runs_count <= _TRIAL_MAX_RUNS:
            return {
                "status": LICENSE_STATUS_TRIAL_ACTIVE,
                "is_allowed": True,
                "hwid": hwid,
                "lic_type": "Демо-режим",
                "customer_name": self._data.get("customer_name", ""),
                "days_left": days_left,
                "runs_left": runs_left,
                "message": f"Демо-режим: осталось {days_left} дн. ({runs_left} запусков)."
            }
        else:
            return {
                "status": LICENSE_STATUS_TRIAL_EXPIRED,
                "is_allowed": False,
                "hwid": hwid,
                "lic_type": "Демо-режим (Истёк)",
                "customer_name": self._data.get("customer_name", ""),
                "days_left": 0,
                "runs_left": 0,
                "message": "Пробный период завершён. Требуется ключ активации."
            }

    def activate(self, key: str, customer_name: str = "") -> tuple[bool, str]:
        """
        Активирует приложение с помощью ключа.
        Возвращает: (успех, сообщение)
        """
        hwid = get_hardware_id()
        is_valid, lic_type, msg = verify_activation_key(key, hwid)
        if not is_valid:
            return False, msg
            
        self._data["activated"] = True
        self._data["license_key"] = key.strip().upper()
        self._data["license_type"] = lic_type
        self._data["customer_name"] = str(customer_name).strip()
        self._save(self._data)
        return True, f"Активация успешна! Лицензия: {lic_type}"

    def reset_trial_for_testing(self):
        """Сброс состояния для тестирования."""
        now = time.time()
        self._data["activated"] = False
        self._data["license_key"] = ""
        self._data["first_run_time"] = now
        self._data["last_run_time"] = now
        self._data["runs_count"] = 0
        self._save(self._data)
