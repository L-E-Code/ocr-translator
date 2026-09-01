@echo off
chcp 65001 >nul
title Teste do OCR
echo Testando leitura de Inteligencia Artificial (EasyOCR)...
echo.

:: Verifica se o ambiente virtual existe
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado. 
    pause
    exit /b
)

:: Executa o script do OCR usando o python do ambiente virtual
.\.venv\Scripts\python.exe app\ocr.py

echo.
pause

