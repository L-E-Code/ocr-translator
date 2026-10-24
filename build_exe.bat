@echo off
setlocal
cd /d "%~dp0"
title Build - OCR Translator

:: Builds the portable version (folder dist\OCR Translator\ with OCR Translator.exe).
:: Usage: build_exe.bat [current|cpu]
::   current  uses the .venv as it is (the PyTorch installed there decides: GPU build if it is a GPU PyTorch)
::   cpu      creates .venv-build-cpu with the CPU-only PyTorch (much smaller) and builds from it
:: The result can be zipped and shared: the user only needs to extract it and run the .exe.

set VARIANT=%~1
if "%VARIANT%"=="" set VARIANT=current

if /i "%VARIANT%"=="cpu" (
    set PY=.venv-build-cpu\Scripts\python.exe
    if not exist ".venv-build-cpu\Scripts\python.exe" (
        echo [1/3] Creating the CPU build environment...
        python -m venv .venv-build-cpu || goto :error
        .venv-build-cpu\Scripts\python.exe -m pip install --upgrade pip || goto :error
        .venv-build-cpu\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu || goto :error
        .venv-build-cpu\Scripts\python.exe -m pip install -r requirements.txt || goto :error
    )
) else (
    set PY=.venv\Scripts\python.exe
    if not exist ".venv\Scripts\python.exe" (
        echo [ERROR] .venv not found. Run install.bat first.
        goto :error
    )
)

echo [2/3] Installing PyInstaller...
%PY% -m pip install --quiet pyinstaller || goto :error

echo [3/3] Building (this takes several minutes and the folder is large)...
%PY% -m PyInstaller ocr_translator.spec --noconfirm --distpath "dist\%VARIANT%" --workpath "build\%VARIANT%" || goto :error

echo.
echo ======================================================
echo  Done: dist\%VARIANT%\OCR Translator\OCR Translator.exe
echo ======================================================
pause
exit /b 0

:error
echo.
echo [ERROR] The build failed. See the messages above.
pause
exit /b 1
