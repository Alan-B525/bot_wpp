@echo off
chcp 65001 > nul
title Sincronizador OneDrive - Mediciones Hidrometría
cd /d "%~dp0"
cls
echo ========================================================
echo   SINCRONIZANDO EXCEL CON ONEDRIVE (med_prefectura_PY.xlsx)
echo ========================================================

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else (
    echo [AVISO] Ejecutando con el Python del sistema...
)

python exportar_onedrive.py %*
echo.
echo ========================================================
echo Proceso finalizado.
pause
