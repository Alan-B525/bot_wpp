@echo off
chcp 65001 > nul
title WhatsApp Forwarder Bot
cd /d "%~dp0"
cls
echo ========================================================
echo       INICIANDO WHATSAPP FORWARDER BOT
echo ========================================================

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo [AVISO] No se encontro el entorno virtual en venv.
    echo Ejecutando con el Python del sistema...
)

python main.py
echo.
echo ========================================================
echo El bot se ha detenido.
pause
