@echo off
setlocal
cd /d "%~dp0"
title GPU Support - OCR Translator

:: Usage: install_gpu.bat [intel|nvidia|cpu] [app_PID_to_wait_for] [relaunch]
:: Without arguments, shows an interactive menu.

set MODE=%~1
set WAITPID=%~2
set RELAUNCH=%~3

echo ======================================================
echo        GPU Support - OCR Translator
echo ======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run install.bat first.
    echo.
    pause
    exit /b 1
)

set INDEX=
if /i "%MODE%"=="nvidia" set INDEX=https://download.pytorch.org/whl/cu126
if /i "%MODE%"=="intel" set INDEX=https://download.pytorch.org/whl/xpu
if /i "%MODE%"=="cpu" set INDEX=https://download.pytorch.org/whl/cpu
if defined INDEX goto install

echo Graphics cards detected on this computer:
powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"
echo.
echo Choose which PyTorch build to install:
echo   [1] NVIDIA GeForce / RTX  (CUDA)
echo   [2] Intel Arc             (XPU)
echo   [3] CPU only              (goes back to no-GPU mode)
echo   [0] Cancel
echo.
set /p OPTION=Option:

if "%OPTION%"=="1" set INDEX=https://download.pytorch.org/whl/cu126
if "%OPTION%"=="2" set INDEX=https://download.pytorch.org/whl/xpu
if "%OPTION%"=="3" set INDEX=https://download.pytorch.org/whl/cpu
if not defined INDEX (
    echo.
    echo Nothing was changed.
    pause
    exit /b 0
)

:install
:: If it was called by the app, waits for it to close (Windows does not let files in use be replaced)
if defined WAITPID (
    echo Waiting for OCR Translator to close...
    call :wait_exit
)

echo.
echo Installing PyTorch from %INDEX%
echo Note: the download can exceed 2 GB and take several minutes.
echo.
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall torch torchvision --index-url %INDEX% --extra-index-url https://pypi.org/simple
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Installation failed. Check your connection and try again.
    pause
    goto reopen
)

echo.
echo Checking...
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'app'); from device import available_gpus; g = available_gpus(); print('Usable GPU:', g if g else 'none (the app will use the CPU)')"

echo.
echo ======================================================
echo   Done.
echo ======================================================
if not defined RELAUNCH pause

:reopen
if defined RELAUNCH (
    echo Reopening OCR Translator...
    start "" ".\.venv\Scripts\pythonw.exe" app\main.py
)
exit /b 0

:wait_exit
tasklist /FI "PID eq %WAITPID%" 2>nul | find "%WAITPID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_exit
)
exit /b 0
