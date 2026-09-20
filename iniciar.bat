@echo off
setlocal
cd /d "%~dp0"

:: 1. Modo terminal legado caso chamado com --cli
if "%1"=="--cli" (
    title OCR Translator - Modo Terminal
    if exist ".venv\Scripts\python.exe" (
        .\.venv\Scripts\python.exe app\main.py --cli
        pause
        exit /b
    )
)

:: 2. Verifica se o ambiente virtual existe
if not exist ".venv\Scripts\python.exe" (
    title Instalando OCR Translator...
    echo [AVISO] Ambiente virtual .venv nao encontrado.
    echo Executando o instalador automaticamente...
    echo.
    call instalar.bat
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [ERRO] A instalacao nao foi concluida. Abortando inicializacao.
        pause
        exit /b 1
    )
)

:: 3. Inicia a GUI sem manter a janela preta do CMD aberta
start "" ".\.venv\Scripts\pythonw.exe" app\main.py
exit
