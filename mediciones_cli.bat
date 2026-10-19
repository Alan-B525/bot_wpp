@echo off
setlocal
chcp 65001 > nul
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" mediciones_cli.py %*
) else (
    python mediciones_cli.py %*
)
