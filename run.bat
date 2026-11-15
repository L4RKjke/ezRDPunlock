@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
title FC DFU Unprotect

where python >nul 2>&1 || (echo [ОШИБКА] Python не найден в PATH & pause & exit /b 1)

python -c "import serial, usb.core" >nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    python -m pip install -r requirements.txt || (echo [ОШИБКА] pip & pause & exit /b 1)
)

echo Выберите режим:
echo   1 - Снятие защиты (unprotect)
echo   2 - Полное стирание (erase)
choice /c 12 /n /m "Режим [1/2]: "
if errorlevel 2 (set "MODE=erase") else (set "MODE=unprotect")

echo.
echo Запуск, режим %MODE%. Для выхода нажмите Ctrl+C.
echo.
python fc_unprotect.py --mode %MODE%

echo.
echo Программа завершена.
pause
