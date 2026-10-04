#!/usr/bin/env python3
"""
Скрипт автоматизированной сборки EXE-файла проекта «Элютек» с помощью PyInstaller.
"""

import os
import sys
import shutil
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Определение расположения исходников (в текущей папке или в соседней Elutek_App)
if os.path.isfile(os.path.join(SCRIPT_DIR, "main.py")):
    PROJECT_ROOT = SCRIPT_DIR
    MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
    SRC_DIR = os.path.join(SCRIPT_DIR, "src")
elif os.path.isfile(os.path.join(SCRIPT_DIR, "..", "Elutek_App", "main.py")):
    PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "Elutek_App"))
    MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")
    SRC_DIR = os.path.join(PROJECT_ROOT, "src")
else:
    PROJECT_ROOT = SCRIPT_DIR
    MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
    SRC_DIR = os.path.join(SCRIPT_DIR, "src")

MIICAM_DLL = os.path.join(PROJECT_ROOT, "miicam.dll")
DIST_DIR = os.path.join(SCRIPT_DIR, "dist")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
APP_NAME = "Elutek"


def build():
    print("=" * 60)
    print("🔨 Сборка исполняемого файла «Элютек» (PyInstaller)...")
    print(f"📁 Исходники: {PROJECT_ROOT}")
    print("=" * 60)
    
    # Проверка наличия PyInstaller
    try:
        import PyInstaller
        print(f"✓ PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("⚠️ PyInstaller не найден. Установка: pip install pyinstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        
    # Команда PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        f"--name={APP_NAME}",
        "--clean",
        "--paths", PROJECT_ROOT,
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--hidden-import", "PyQt5",
        "--hidden-import", "PyQt5.QtCore",
        "--hidden-import", "PyQt5.QtGui",
        "--hidden-import", "PyQt5.QtWidgets",
        "--hidden-import", "pyqtgraph",
        "--hidden-import", "cv2",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "openpyxl",
        "--hidden-import", "numpy",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.filedialog",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.colorchooser",
    ]
    
    # Add package data and the optional scientific-camera driver.
    sep = ";" if sys.platform == "win32" else ":"
    if os.path.isdir(SRC_DIR):
        cmd.extend(["--add-data", f"{SRC_DIR}{sep}src"])
    if os.path.isfile(MIICAM_DLL):
        # MiiCamCapture searches the application root, which is also the root
        # of PyInstaller's onedir distribution.
        cmd.extend(["--add-binary", f"{MIICAM_DLL}{sep}."])

    cmd.append(MAIN_SCRIPT)
    
    print("\nЗапуск команды сборки:")
    print(" ".join(cmd))
    print("-" * 60)
    
    res = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if res.returncode == 0:
        print("\n" + "=" * 60)
        print("✅ Сборка успешно завершена!")
        out_app = os.path.join(DIST_DIR, APP_NAME)
        print(f"📁 Исполняемые файлы находятся в папке: {out_app}")
        print("=" * 60)
    else:
        print(f"\n❌ Ошибка сборки (код возврата: {res.returncode})")
        sys.exit(res.returncode)


if __name__ == "__main__":
    build()
