@echo off
chcp 65001 > nul
title Reiniciar Sesión - WhatsApp Bot
cd /d "%~dp0"
cls
echo ========================================================
echo       REINICIAR SESIÓN DE WHATSAPP
echo ========================================================
echo.
echo Asegúrate de cerrar la ventana de start_bot.bat antes de continuar.
echo.
del /f /q bot_session.sqlite3* 2>nul
del /f /q qr.png 2>nul
echo.
echo ========================================================
echo ✅ Sesión eliminada correctamente.
echo La próxima vez que inicies el bot se generará un nuevo
echo código QR para vincular otra cuenta.
echo ========================================================
echo.
pause
