#!/usr/bin/env python3
"""
exportar_onedrive.py
Rutina automática y manual para sincronizar las mediciones limnimétricas
a la carpeta de OneDrive especificada, manteniendo siempre el archivo más reciente:
C:\\Users\\abazan\\OneDrive - eby.org.ar\\Mediciones_prefectura_PY\\med_prefectura_PY.xlsx

Excluye estrictamente:
- Mediciones con estado DESCARTADO
- Estaciones desconocidas que no tienen datos (sin nivel en metros)
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Asegurar codificación UTF-8 en consola de Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bot.config import BotConfig
from bot.measurement_store import MeasurementStore


def ejecutar_sincronizacion(store: MeasurementStore, target_dir: str, filename: str) -> bool:
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ahora}] 🔄 Sincronizando datos hacia OneDrive...")
    
    destino = store.sync_to_onedrive(target_dir=target_dir, filename=filename)
    if destino and os.path.exists(destino):
        tamanio_kb = os.path.getsize(destino) / 1024.0
        print(f"[{ahora}] ✅ Excel generado y reemplazado con éxito:")
        print(f"       📂 Ruta: {destino}")
        print(f"       📊 Tamaño: {tamanio_kb:.1f} KB")
        return True
    else:
        print(f"[{ahora}] ❌ No se pudo completar la sincronización en {target_dir}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Rutina de exportación automática a OneDrive (med_prefectura_PY.xlsx)")
    parser.add_argument("--config", "-c", default="config.json", help="Ruta a config.json")
    parser.add_argument("--destino", "-d", default=None, help="Carpeta de destino en OneDrive")
    parser.add_argument("--archivo", "-f", default=None, help="Nombre de archivo (default: med_prefectura_PY.xlsx)")
    parser.add_argument("--loop", "-l", action="store_true", help="Ejecutar continuamente como servicio en segundo plano")
    parser.add_argument("--intervalo", "-i", type=int, default=None, help="Intervalo en segundos para modo continuo (default: de config o 60s)")
    args = parser.parse_args()

    config = BotConfig.load(args.config)
    target_dir = args.destino or config.onedrive_export_dir
    filename = args.archivo or config.onedrive_export_filename
    intervalo = args.intervalo or getattr(config, "onedrive_sync_interval_seconds", 60)
    intervalo = max(10, intervalo)

    store = MeasurementStore(
        db_path=config.measurement_db_path,
        photos_dir=config.photos_dir,
    )

    print("=" * 70)
    print("      RUTINA DE SINCRONIZACIÓN DE MEDICIONES LIMNIMÉTRICAS A ONEDRIVE")
    print("=" * 70)
    print(f"• Base de datos:    {store.db_path}")
    print(f"• Carpeta destino:  {target_dir}")
    print(f"• Nombre archivo:   {filename}")
    if args.loop:
        print(f"• Modo continuo:    ACTIVO (cada {intervalo} segundos)")
    print("=" * 70)

    if not args.loop:
        exito = ejecutar_sincronizacion(store, target_dir, filename)
        sys.exit(0 if exito else 1)
    else:
        print("Presione Ctrl+C para detener la rutina.\n")
        try:
            while True:
                ejecutar_sincronizacion(store, target_dir, filename)
                time.sleep(intervalo)
        except KeyboardInterrupt:
            print("\nRutina de sincronización detenida por el usuario.")


if __name__ == "__main__":
    main()
