@echo off
title OCR Translator
echo Iniciando OCR Translator...
echo.

:: Verifica se o ambiente virtual existe
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado. 
    echo Por favor, certifique-se de que a instalacao foi concluida.
    pause
    exit /b
)

:: Executa o script principal usando o python do ambiente virtual
.\.venv\Scripts\python.exe app\main.py

echo.
pause
