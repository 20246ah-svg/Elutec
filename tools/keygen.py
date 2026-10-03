#!/usr/bin/env python3
"""
Генератор лицензионных ключей для программного комплекса «Элютек».
Используется разработчиком для генерации ключей активации клиентам.

Использование:
    python tools/keygen.py [HARDWARE_ID] [TYPE]

Пример:
    python tools/keygen.py ELU-1234-5678-9ABC-DEF0 PRO
"""

import sys
import os

# Добавление корневой директории проекта в путь поиска
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils.license_manager import generate_activation_key, get_hardware_id, verify_activation_key


def main():
    print("=" * 60)
    print("🔑 Генератор лицензионных ключей — Элютек SARA RGB")
    print("=" * 60)
    
    if len(sys.argv) > 1:
        hwid = sys.argv[1].strip()
    else:
        current_hwid = get_hardware_id()
        print(f"Текущий Hardware ID этой машины: {current_hwid}")
        user_input = input(f"Введите Hardware ID клиента (Enter для {current_hwid}): ").strip()
        hwid = user_input if user_input else current_hwid

    lic_type = "PRO"
    if len(sys.argv) > 2:
        lic_type = sys.argv[2].strip().upper()

    key = generate_activation_key(hwid, lic_type=lic_type)
    is_valid, verified_type, _ = verify_activation_key(key, hwid)
    
    print("-" * 60)
    print(f"Hardware ID:   {hwid}")
    print(f"Тип лицензии:  {lic_type}")
    print(f"КЛЮЧ АКТИВАЦИИ: {key}")
    print(f"Статус сверки: {'✅ Валиден' if is_valid else '❌ Ошибка'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
