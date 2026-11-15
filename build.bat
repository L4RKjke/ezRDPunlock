@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден в PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Создание виртуального окружения...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

call ".venv\Scripts\activate.bat"

echo Установка зависимостей...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Сборка EXE...
python build.py
if errorlevel 1 goto :fail

echo.
echo Сборка завершена. Файл находится в папке dist.
pause
exit /b 0

:fail
echo.
echo ОШИБКА: сборка прервана.
pause
exit /b 1
