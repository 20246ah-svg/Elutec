@echo off
chcp 65001 > nul
echo ============================================================
echo   Сборка релиза «Элютек» (EXE + Установщик)
echo ============================================================

echo [1/3] Проверка и установка зависимостей...
pip install -r requirements.txt pyinstaller

echo.
echo [2/3] Сборка EXE через PyInstaller...
python build_exe.py
if errorlevel 1 (
    echo [ОШИБКА] Не удалось собрать EXE.
    pause
    exit /b 1
)

echo.
echo [3/3] Проверка наличия Inno Setup Compiler...
where iscc >nul 2>nul
if %errorlevel% equ 0 (
    echo Компиляция инсталлятора через Inno Setup...
    iscc build_installer.iss
    echo [УСПЕХ] Установщик создан в папке Output!
) else (
    echo [ИНФО] Inno Setup (iscc.exe) не найден в PATH.
    echo Папка dist\Elutek готова к запуску или запаковке в архив.
)

echo.
echo ============================================================
echo   Сборка завершена успешно!
echo ============================================================
pause
