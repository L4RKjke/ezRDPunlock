@echo off
chcp 65001 >nul
title Betaflight FC - снятие защиты от чтения
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python не найден. Установите Python 3 и отметьте "Add Python to PATH".
    pause
    exit /b 1
)

python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Не удалось установить зависимости.
    pause
    exit /b 1
)

echo.
echo  1 - Снять защиту от чтения (RDP1 - RDP0, стирание основной Flash)
echo  2 - Полное стирание основной Flash
echo.
choice /c 12 /n /m "Выберите режим: "
if errorlevel 2 (set MODE=erase) else (set MODE=unprotect)

python fc_unprotect.py --mode %MODE%
echo.
pause
