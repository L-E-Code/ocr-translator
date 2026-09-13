@echo off
chcp 65001 >nul
title Instalador de Aceleração por GPU (NVIDIA CUDA)
echo =======================================================
echo    Instalador de Aceleração por GPU para OCR Translator
echo =======================================================
echo.
echo Este script vai instalar a versão do PyTorch com suporte a
echo placas de vídeo NVIDIA (CUDA).
echo.
echo Benefícios:
echo  - Reduz o tempo de leitura do OCR de ~2s para ~0.2s!
echo  - Libera o seu processador (CPU) enquanto você joga.
echo.
echo Requisitos:
echo  - Placa de vídeo NVIDIA (GeForce GTX / RTX)
echo  - Cerca de 2.5 GB de espaço livre e conexão com a internet.
echo.
set /p resp="Deseja iniciar a instalação agora? (S/N): "
if /i not "%resp%"=="S" (
    echo Operação cancelada.
    pause
    exit /b
)

echo.
echo Baixando e instalando PyTorch com suporte CUDA... (Aguarde alguns minutos)
echo.

.\.venv\Scripts\python.exe -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu124

echo.
echo Verificando se a GPU foi reconhecida...
.\.venv\Scripts\python.exe -c "import torch; print('CUDA Ativo:', torch.cuda.is_available()); print('Nome da GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Nenhuma GPU detectada')"

echo.
echo Concluído! Se o CUDA estiver ativo, o OCR agora rodará voando na sua placa de vídeo!
pause

