@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

set "SCRIPT=%~dp0protect.py"
if not exist "%SCRIPT%" (
    echo Ошибка: protect.py не найден рядом с protect.bat.
    goto :fail
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Ошибка: Python не найден в PATH.
    goto :fail
)

echo ==============================================================
echo  ВНИМАНИЕ: установка RDP Level 1 на STM32F405 через USB DFU.
echo  Снятие RDP впоследствии СТИРАЕТ основную Flash.
echo  Убедись, что подключена ТОЛЬКО нужная плата в режиме DFU.
echo ==============================================================
echo.

set "ANSWER="
set /p "ANSWER=Для продолжения введи YES: "
if /i not "%ANSWER%"=="YES" (
    echo Отменено. Запись не выполнялась.
    goto :end
)

echo.
%PY% "%SCRIPT%" --confirm-f405-rdp1 %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Скрипт завершён успешно ^(код 0^).
) else (
    echo Скрипт завершён с ошибкой ^(код %RC%^). Не выполняй Read Unprotect.
)
goto :end

:fail
set "RC=1"

:end
echo.
pause
exit /b %RC%
