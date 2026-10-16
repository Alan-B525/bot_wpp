import sys

# Asegurar codificación UTF-8 en Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
from colorama import Fore, Style, init

from bot.config import BotConfig
from bot.client import WhatsAppForwarderBot

init(autoreset=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="WhatsApp Forwarder Bot - Reenvía mensajes recibidos a un grupo de WhatsApp."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default="config.json",
        help="Ruta al archivo de configuración JSON (por defecto: config.json)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + Style.BRIGHT + "       WHATSAPP FORWARDER BOT (REENVÍO A GRUPO)")
    print(Fore.CYAN + "=" * 60)

    try:
        config = BotConfig.load(args.config)
    except Exception as e:
        print(Fore.RED + f"❌ Error cargando configuración desde {args.config}: {e}")
        sys.exit(1)

    bot = WhatsAppForwarderBot(config=config)
    bot.run()


if __name__ == "__main__":
    main()
