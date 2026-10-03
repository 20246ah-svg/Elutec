@echo off
chcp 65001 >nul
title Генератор лицензий — Элютек SARA RGB
cd /d "%~dp0"
python tools/keygen_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Запуск консольного генератора...
    python tools/keygen.py
    pause
)
