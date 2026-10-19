import os
import sys
import argparse
import subprocess
from datetime import datetime
from colorama import Fore, Style, init

from bot.config import BotConfig
from bot.measurement_store import MeasurementStore

init(autoreset=True)


def cmd_listar(store: MeasurementStore, args):
    """Muestra mediciones recientes en formato tabular de consola."""
    mediciones = store.query_measurements(
        estacion_nombre=args.estacion,
        fecha_desde=args.desde,
        fecha_hasta=args.hasta,
        solo_con_foto=args.fotos,
        limit=args.limite,
    )

    if not mediciones:
        print(Fore.YELLOW + "No se encontraron mediciones con los filtros especificados.")
        return

    print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 90)
    print(Fore.CYAN + Style.BRIGHT + f"{'ID':<6} | {'FECHA Y HORA':<19} | {'ESTACIÓN':<18} | {'NIVEL':<9} | {'TEND.':<8} | {'REMITENTE':<14} | {'FOTO'}")
    print(Fore.CYAN + Style.BRIGHT + "=" * 90)

    for m in mediciones:
        mid = str(m["id"])
        ts = m["timestamp_medicion"] or ""
        st_name = (m.get("estacion_nombre_norm") or m["estacion_detectada"] or "")[:17]
        val_m = f"{m['valor_metros']:.2f} m" if m.get("valor_metros") is not None else "N/D"
        tend = m.get("tendencia_rio") or "-"
        sender = (m.get("remitente_nombre") or m["remitente_telefono"] or "")[:13]
        has_foto = "📷 Sí" if m.get("foto_path") else "No"

        # Color según tendencia
        tend_color = Fore.WHITE
        if tend == "CRECE":
            tend_color = Fore.GREEN
        elif tend == "BAJA":
            tend_color = Fore.RED
        elif tend == "ESTACIONARIO":
            tend_color = Fore.BLUE

        print(
            f"{Fore.WHITE}{mid:<6} | {Fore.LIGHTBLACK_EX}{ts:<19} | {Fore.GREEN}{st_name:<18} | "
            f"{Fore.YELLOW}{val_m:<9} | {tend_color}{tend:<8}{Fore.RESET} | {Fore.CYAN}{sender:<14} | {Fore.MAGENTA}{has_foto}"
        )

    print(Fore.CYAN + Style.BRIGHT + "=" * 90)
    print(Fore.WHITE + f"Total mostrado: {len(mediciones)} registro(s).\n")


def cmd_estaciones(store: MeasurementStore, args):
    """Lista las estaciones registradas con su total de mediciones y último nivel."""
    resumen = store.get_stations_summary()
    if not resumen:
        print(Fore.YELLOW + "No hay estaciones registradas.")
        return

    print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 85)
    print(Fore.CYAN + Style.BRIGHT + f"{'ID':<5} | {'ESTACIÓN':<22} | {'RÍO':<16} | {'MEDICIONES':<10} | {'ÚLT. NIVEL':<11} | {'ÚLTIMA FECHA'}")
    print(Fore.CYAN + Style.BRIGHT + "=" * 85)

    for r in resumen:
        sid = str(r["id"])
        name = (r["nombre"] or "")[:21]
        rio = (r["rio"] or "-")[:15]
        total = str(r["total_mediciones"])
        val = f"{r['ultimo_nivel_metros']:.2f} m" if r.get("ultimo_nivel_metros") is not None else "-"
        fecha = r.get("ultima_fecha") or "-"

        print(
            f"{Fore.WHITE}{sid:<5} | {Fore.GREEN}{name:<22} | {Fore.LIGHTBLUE_EX}{rio:<16} | "
            f"{Fore.YELLOW}{total:<10} | {Fore.MAGENTA}{val:<11} | {Fore.LIGHTBLACK_EX}{fecha}"
        )

    print(Fore.CYAN + Style.BRIGHT + "=" * 85)
    print(Fore.WHITE + f"Total estaciones: {len(resumen)}\n")


def cmd_exportar(store: MeasurementStore, args):
    """Exporta las mediciones filtradas a un archivo CSV compatible con Excel."""
    output_path = args.salida
    path = store.export_to_csv(
        output_path=output_path,
        estacion_nombre=args.estacion,
        fecha_desde=args.desde,
        fecha_hasta=args.hasta,
        solo_con_foto=getattr(args, "fotos", False),
    )
    print(Fore.GREEN + Style.BRIGHT + f"\n✅ Mediciones exportadas exitosamente a: {os.path.abspath(path)}\n")


def cmd_dashboard(store: MeasurementStore, args):
    """Inicia el dashboard web local."""
    port = args.puerto
    dashboard_script = os.path.join(os.path.dirname(__file__), "dashboard_app.py")
    print(Fore.GREEN + f"🚀 Iniciando Dashboard Web en http://localhost:{port}...")
    cmd = [sys.executable, dashboard_script, "--puerto", str(port)]
    if getattr(args, "db", None):
        cmd.extend(["--db", args.db])
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\nDashboard detenido.")


def main():
    parser = argparse.ArgumentParser(description="CLI de Control y Consulta de Mediciones Limnimétricas")
    parser.add_argument("--db", default=None, help="Ruta alternativa a base de datos SQLite mediciones.db")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    # Subcomando: listar
    p_listar = subparsers.add_parser("listar", help="Lista las últimas mediciones registradas")
    p_listar.add_argument("--estacion", "-e", default=None, help="Filtrar por nombre de estación")
    p_listar.add_argument("--desde", default=None, help="Fecha mínima (YYYY-MM-DD)")
    p_listar.add_argument("--hasta", default=None, help="Fecha máxima (YYYY-MM-DD)")
    p_listar.add_argument("--fotos", action="store_true", help="Solo mostrar mediciones con foto")
    p_listar.add_argument("--limite", "-n", type=int, default=20, help="Cantidad de registros (default: 20)")

    # Subcomando: estaciones
    subparsers.add_parser("estaciones", help="Muestra catálogo de estaciones y recuento de mediciones")

    # Subcomando: exportar
    p_export = subparsers.add_parser("exportar", help="Exporta mediciones a CSV para Excel")
    p_export.add_argument("--salida", "-s", default="mediciones.csv", help="Ruta del archivo CSV destino")
    p_export.add_argument("--estacion", "-e", default=None, help="Filtrar por nombre de estación")
    p_export.add_argument("--desde", default=None, help="Fecha mínima (YYYY-MM-DD)")
    p_export.add_argument("--hasta", default=None, help="Fecha máxima (YYYY-MM-DD)")
    p_export.add_argument("--fotos", action="store_true", help="Solo exportar mediciones con foto")

    # Subcomando: dashboard
    p_dash = subparsers.add_parser("dashboard", help="Inicia el dashboard web interactivo")
    p_dash.add_argument("--puerto", "-p", type=int, default=5000, help="Puerto HTTP (default: 5000)")

    args = parser.parse_args()

    config = BotConfig.load()
    db_path = args.db or config.measurement_db_path
    store = MeasurementStore(db_path=db_path, photos_dir=config.photos_dir)

    if args.comando == "listar":
        cmd_listar(store, args)
    elif args.comando == "estaciones":
        cmd_estaciones(store, args)
    elif args.comando == "exportar":
        cmd_exportar(store, args)
    elif args.comando == "dashboard":
        cmd_dashboard(store, args)


if __name__ == "__main__":
    main()
