@echo off
setlocal
cd /d "%~dp0"
title OCR Translator

echo Iniciando OCR Translator...
echo.

:: Verifica se o ambiente virtual existe
if not exist ".venv\Scripts\python.exe" (
    echo [AVISO] Ambiente virtual .venv nao encontrado.
    echo Executando o instalador automaticamente...
    echo.
    call instalar.bat
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [ERRO] A instalacao não foi concluída. Abortando inicialização.
        pause
        exit /b 1
    )
)

:: Executa o script principal usando o python do ambiente virtual
.\.venv\Scripts\python.exe app\main.py

echo.
pause
