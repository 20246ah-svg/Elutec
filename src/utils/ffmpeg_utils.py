import os
import pathlib
import importlib.util
import shutil
from typing import Optional

_FFMPEG_EXE_CACHE = None

def find_ffmpeg_exe() -> Optional[str]:
    global _FFMPEG_EXE_CACHE
    if _FFMPEG_EXE_CACHE and os.path.isfile(_FFMPEG_EXE_CACHE):
        return _FFMPEG_EXE_CACHE

    found = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    if found and os.path.isfile(found):
        _FFMPEG_EXE_CACHE = found
        return found

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            _FFMPEG_EXE_CACHE = exe
            return exe
    except Exception:
        pass

    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    cwd = os.getcwd()
    local_candidates = [
        os.path.join(script_dir, 'ffmpeg.exe'),
        os.path.join(script_dir, 'bin', 'ffmpeg.exe'),
        os.path.join(script_dir, 'ffmpeg', 'bin', 'ffmpeg.exe'),
        os.path.join(cwd, 'ffmpeg.exe'),
        os.path.join(cwd, 'bin', 'ffmpeg.exe'),
        os.path.join(cwd, 'ffmpeg', 'bin', 'ffmpeg.exe'),
    ]

    env = os.environ
    win_candidates = [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe',
        r'C:\ProgramData\chocolatey\bin\ffmpeg.exe',
        os.path.join(env.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Links', 'ffmpeg.exe'),
        os.path.join(env.get('LOCALAPPDATA', ''), 'Programs', 'ffmpeg', 'bin', 'ffmpeg.exe'),
        os.path.join(env.get('USERPROFILE', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
        os.path.join(env.get('USERPROFILE', ''), 'Downloads', 'ffmpeg', 'bin', 'ffmpeg.exe'),
        os.path.join(env.get('USERPROFILE', ''), 'Desktop', 'ffmpeg', 'bin', 'ffmpeg.exe'),
    ]

    for path in local_candidates + win_candidates:
        if path and os.path.isfile(path):
            _FFMPEG_EXE_CACHE = path
            return path

    return None

def ffmpeg_missing_message() -> str:
    return (
        'ffmpeg.exe не найден.\n\n'
        'Варианты исправления:\n'
        '1) Добавьте папку ffmpeg\\bin в PATH и перезапустите программу.\n'
        '2) Или положите папку ffmpeg рядом со скриптом так, чтобы был путь:\n'
        '   <папка_скрипта>\\ffmpeg\\bin\\ffmpeg.exe\n\n'
        'Проверка в CMD: ffmpeg -version'
    )

def ensure_pyqt5_platform_plugin_path() -> Optional[str]:
    try:
        spec = importlib.util.find_spec("PyQt5")
        if spec is None or not spec.submodule_search_locations:
            return None

        pyqt5_dir = pathlib.Path(list(spec.submodule_search_locations)[0]).resolve()
        candidates = [
            pyqt5_dir / "Qt5" / "plugins" / "platforms",
            pyqt5_dir / "Qt" / "plugins" / "platforms",
        ]

        for platforms_dir in candidates:
            if (platforms_dir / "qwindows.dll").exists():
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)
                return str(platforms_dir)
    except Exception as exc:
        print(f"⚠️ Не удалось автоматически задать путь Qt/PyQt5 plugin: {exc}")
    return None

