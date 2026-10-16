"""
WhatsApp Forwarder Bot
Módulo principal del bot de reenvío de mensajes para WhatsApp.
"""

import sys

import os
import shutil

# Asegurar soporte de codificación UTF-8 en consolas de Windows para emojis y caracteres especiales
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Asegurar que FFmpeg esté en PATH en Windows si fue instalado mediante WinGet
    if not shutil.which("ffmpeg"):
        winget_pkg_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
        if os.path.exists(winget_pkg_dir):
            for root, _, files in os.walk(winget_pkg_dir):
                if "ffmpeg.exe" in files:
                    os.environ["PATH"] = root + os.pathsep + os.environ["PATH"]
                    break

__version__ = "1.0.0"
