@echo off
setlocal
cd /d "%~dp0"
title Suporte a GPU - OCR Translator

:: Uso: instalar_gpu.bat [intel|nvidia|cpu] [PID_do_app_para_aguardar] [relaunch]
:: Sem argumentos, mostra um menu interativo.

set MODO=%~1
set WAITPID=%~2
set RELAUNCH=%~3

echo ======================================================
echo        Suporte a GPU - OCR Translator
echo ======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado. Execute o instalar.bat primeiro.
    echo.
    pause
    exit /b 1
)

set INDEX=
if /i "%MODO%"=="nvidia" set INDEX=https://download.pytorch.org/whl/cu126
if /i "%MODO%"=="intel" set INDEX=https://download.pytorch.org/whl/xpu
if /i "%MODO%"=="cpu" set INDEX=https://download.pytorch.org/whl/cpu
if defined INDEX goto instalar

echo Placas de video detectadas neste computador:
powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"
echo.
echo Escolha qual versao do PyTorch instalar:
echo   [1] NVIDIA GeForce / RTX  (CUDA)
echo   [2] Intel Arc             (XPU)
echo   [3] Somente CPU           (volta ao modo sem GPU)
echo   [0] Cancelar
echo.
set /p OPCAO=Opcao: 

if "%OPCAO%"=="1" set INDEX=https://download.pytorch.org/whl/cu126
if "%OPCAO%"=="2" set INDEX=https://download.pytorch.org/whl/xpu
if "%OPCAO%"=="3" set INDEX=https://download.pytorch.org/whl/cpu
if not defined INDEX (
    echo.
    echo Nada foi alterado.
    pause
    exit /b 0
)

:instalar
:: Se foi chamado pelo app, espera ele fechar (o Windows nao deixa trocar arquivos em uso)
if defined WAITPID (
    echo Aguardando o OCR Translator fechar...
    call :aguardar
)

echo.
echo Instalando PyTorch de %INDEX%
echo Aviso: o download pode passar de 2 GB e levar varios minutos.
echo.
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall torch torchvision --index-url %INDEX% --extra-index-url https://pypi.org/simple
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRO] Falha na instalacao. Verifique a conexao e tente novamente.
    pause
    goto reabrir
)

echo.
echo Verificando...
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'app'); from device import available_gpus; g = available_gpus(); print('GPU utilizavel:', g if g else 'nenhuma (o app usara a CPU)')"

echo.
echo ======================================================
echo   Concluido.
echo ======================================================
if not defined RELAUNCH pause

:reabrir
if defined RELAUNCH (
    echo Reabrindo o OCR Translator...
    start "" ".\.venv\Scripts\pythonw.exe" app\main.py
)
exit /b 0

:aguardar
tasklist /FI "PID eq %WAITPID%" 2>nul | find "%WAITPID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto aguardar
)
exit /b 0
