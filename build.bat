@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/4] Установка зависимостей...
python -m pip install -r requirements.txt pyinstaller || goto :error

echo [2/4] Чтение версии из build_config.json...
for /f "usebackq delims=" %%V in (`python -c "import json; print(json.load(open('build_config.json', encoding='utf-8'))['version'])"`) do set "APP_VER=%%V"
if not defined APP_VER goto :error

echo [3/4] Сборка FcUnprotect_%APP_VER%.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "FcUnprotect_%APP_VER%" ^
    --add-data "style.qss;." ^
    --add-data "build_config.json;." ^
    --collect-all libusb_package ^
    gui.py || goto :error

echo [4/4] Очистка временных файлов...
rmdir /s /q build 2>nul
del /q "FcUnprotect_%APP_VER%.spec" 2>nul

echo.
echo Готово: dist\FcUnprotect_%APP_VER%.exe
pause
exit /b 0

:error
echo.
echo ОШИБКА СБОРКИ
pause
exit /b 1
