@echo off
setlocal
cd /d "%~dp0"

:: 1. Checks that the virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    title Installing OCR Translator...
    echo [WARNING] Virtual environment .venv not found.
    echo Running the installer automatically...
    echo.
    call install.bat
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [ERROR] The installation did not finish. Aborting startup.
        pause
        exit /b 1
    )
)

:: 2. Starts the GUI without keeping the black CMD window open
start "" ".\.venv\Scripts\pythonw.exe" app\main.py
exit
