@echo off
chcp 65001 >nul
title Генератор лицензий — Элютек SARA RGB
cd /d "%~dp0"
python keygen_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ошибка запуска графического интерфейса. Запуск консольного режима...
    python keygen.py
    pause
)
