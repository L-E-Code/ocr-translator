@echo off
setlocal
cd /d "%~dp0"

:: 1. Legacy terminal mode when called with --cli
if "%1"=="--cli" (
    title OCR Translator - Terminal Mode
    if exist ".venv\Scripts\python.exe" (
        .\.venv\Scripts\python.exe app\main.py --cli
        pause
        exit /b
    )
)

:: 2. Checks that the virtual environment exists
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

:: 3. Starts the GUI without keeping the black CMD window open
start "" ".\.venv\Scripts\pythonw.exe" app\main.py
exit
