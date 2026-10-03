import sys
import os
import warnings
import traceback

warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ["OPENCV_LOG_LEVEL"] = "OFF"

try:
    import cv2
    if hasattr(cv2, "setLogLevel"):
        cv2.setLogLevel(0)
except Exception:
    pass

# Robust project-root bootstrap: works from Explorer, a terminal, or a temporary ZIP extraction folder.
PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if not os.path.isdir(SRC_DIR):
    raise RuntimeError(f"Не найдена папка src рядом с main.py: {SRC_DIR}")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

try:
    from src.utils.ffmpeg_utils import ensure_pyqt5_platform_plugin_path
    from src.gui.setup_app import SetupApp
except ImportError as e:
    print("Ошибка импорта модуля. Проверьте структуру проекта и установленные зависимости.")
    print(f"Детали: {e}")
    traceback.print_exc()
    input("Нажмите Enter для выхода...")
    sys.exit(1)

if __name__ == "__main__":
    try:
        ensure_pyqt5_platform_plugin_path()
        print("Запуск RGB SAR-Analys...")
        app = SetupApp()
        app.root.mainloop()
        print("Приложение закрыто.")
    except Exception as e:
        print("Критическая ошибка при запуске приложения:")
        print(f"{e}")
        traceback.print_exc()
        input("Нажмите Enter для выхода...")
        sys.exit(1)
