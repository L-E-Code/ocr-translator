@echo off
setlocal
cd /d "%~dp0"
title Instalador - OCR Translator

echo ======================================================
echo           Instalador do OCR Translator
echo ======================================================
echo.

:: 1. Verifica se o Python esta instalado e acessivel pelo PATH
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao encontrado no sistema!
    echo Por favor, instale o Python 3.10 ou superior e marque a opcao:
    echo "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

echo [1/3] Verificando versao do Python...
python --version
echo.

:: 2. Cria o ambiente virtual se ainda nao existir
if not exist ".venv\Scripts\python.exe" (
    echo [2/3] Criando ambiente virtual .venv...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERRO] Falha ao criar o ambiente virtual.
        pause
        exit /b 1
    )
    echo Ambiente virtual criado com sucesso!
) else (
    echo [2/3] Ambiente virtual .venv ja existe. Pulando criacao...
)
echo.

:: 3. Atualiza o pip e instala as dependencias
echo [3/3] Instalando dependencias do requirements.txt...
echo Aviso: Isso pode levar alguns minutos na primeira vez.
echo.
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRO] Ocorreu uma falha durante a instalacao das dependencias.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo       Instalacao concluida com sucesso!
echo ======================================================
echo.
pause
