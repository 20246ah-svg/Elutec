#!/usr/bin/env python3
"""
Сборщик отдельного переносного EXE-файла генератора лицензий «Элютек».
Создает автономный одиночный файл Keygen_Elutek.exe.
"""

import os
import sys
import subprocess

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
SCRIPT_PATH = os.path.join(TOOLS_DIR, "keygen_gui.py")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")


def build_keygen():
    print("=" * 60)
    print("🔨 Сборка автономного генератора ключей (Keygen_Elutek.exe)...")
    print("=" * 60)

    try:
        import PyInstaller
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name=Keygen_Elutek",
        "--paths", PROJECT_ROOT,
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.filedialog",
        SCRIPT_PATH,
    ]

    print("Запуск PyInstaller:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)
    print("=" * 60)
    print("✅ Сборка генератора ключей завершена!")
    print(f"Исполняемый файл: {os.path.join(DIST_DIR, 'Keygen_Elutek.exe' if sys.platform == 'win32' else 'Keygen_Elutek')}")
    print("=" * 60)


if __name__ == "__main__":
    build_keygen()
