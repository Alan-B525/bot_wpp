@echo off
chcp 65001 > nul
title Listador de Grupos - WhatsApp Bot
cd /d "%~dp0"
cls
echo ========================================================
echo       LISTANDO GRUPOS DE WHATSAPP
echo ========================================================

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo [AVISO] No se encontro el entorno virtual en venv.
    echo Ejecutando con el Python del sistema...
)

python list_groups.py
echo.
pause
