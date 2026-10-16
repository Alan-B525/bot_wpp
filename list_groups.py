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

import time
from colorama import Fore, Style, init

from neonize.client import NewClient
from neonize.events import ConnectedEv
from neonize.utils.jid import Jid2String

from bot.config import BotConfig
from bot.utils import save_and_display_qr, remove_qr_image, list_all_groups

init(autoreset=True)


def main():
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + Style.BRIGHT + "       LISTADOR DE GRUPOS DE WHATSAPP")
    print(Fore.CYAN + "=" * 60)
    print(Fore.WHITE + "Conectando para obtener los grupos a los que pertenece la cuenta...\n")

    config = BotConfig.load()
    client = NewClient(config.session_name)

    client.qr(lambda c, qr_data: save_and_display_qr(qr_data, save_path="qr.png"))

    @client.event(ConnectedEv)
    def on_connected(c: NewClient, event: ConnectedEv):
        remove_qr_image("qr.png")
        print("\n" + Fore.GREEN + Style.BRIGHT + "✅ ¡Conectado exitosamente!")
        time.sleep(1)  # Pequeña pausa para sincronizar lista de grupos

        groups = list_all_groups(c)
        print("\n" + Fore.YELLOW + Style.BRIGHT + f"📋 GRUPOS ENCONTRADOS ({len(groups)}):")
        print(Fore.CYAN + "-" * 60)

        if not groups:
            print(Fore.WHITE + "   No se encontraron grupos unidos en esta cuenta.")
        else:
            for idx, g in enumerate(groups, 1):
                name = g["name"] or "(Sin título)"
                jid = g["jid_str"]
                print(Fore.WHITE + f"{idx:2d}. Nombre: " + Fore.GREEN + Style.BRIGHT + f"{name}")
                print(Fore.WHITE + f"    JID:    " + Fore.CYAN + f"{jid}\n")

            print(Fore.CYAN + "=" * 60)
            print(Fore.YELLOW + "💡 Instrucciones:")
            print(Fore.WHITE + "   Copia el Nombre exacto o el JID del grupo donde deseas recibir")
            print(Fore.WHITE + "   los mensajes y pégalo en el campo 'target_group' de config.json.")
            print(Fore.CYAN + "=" * 60 + "\n")

        # Detener cliente para salir limpiamente
        c.stop()

    try:
        client.connect()
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\nOperación cancelada por el usuario.")
    except Exception as e:
        print(Fore.RED + f"\nError: {e}")


if __name__ == "__main__":
    main()
