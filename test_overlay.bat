@echo off
chcp 65001 >nul
title Teste do Overlay
echo Iniciando Janela Overlay de Teste...
echo.

:: Verifica se o ambiente virtual existe
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado. 
    pause
    exit /b
)

:: Executa o script do overlay usando o python do ambiente virtual
.\.venv\Scripts\python.exe app\overlay.py

echo.
pause

