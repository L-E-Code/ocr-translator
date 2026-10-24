@echo off
setlocal
cd /d "%~dp0"
title Installer - OCR Translator

echo ======================================================
echo           OCR Translator Installer
echo ======================================================
echo.

:: 1. Checks that Python is installed and reachable through PATH
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found on this system!
    echo Please install Python 3.10 or newer and check the option:
    echo "Add Python to PATH" during the installation.
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking the Python version...
python --version
echo.

:: 2. Creates the virtual environment if it does not exist yet
if not exist ".venv\Scripts\python.exe" (
    echo [2/3] Creating the .venv virtual environment...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully!
) else (
    echo [2/3] The .venv virtual environment already exists. Skipping creation...
)
echo.

:: 3. Upgrades pip and installs the dependencies
echo [3/3] Installing the dependencies from requirements.txt...
echo Note: this can take a few minutes the first time.
echo.
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] A failure occurred while installing the dependencies.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo       Installation completed successfully!
echo ======================================================
echo.
pause
