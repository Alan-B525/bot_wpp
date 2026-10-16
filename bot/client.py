import os
import sys
import time
from datetime import datetime
from typing import Optional
from colorama import Fore, Style, init

from neonize.client import NewClient
from neonize.events import ConnectedEv, MessageEv, PairStatusEv, LoggedOutEv, DisconnectedEv
from neonize.proto.Neonize_pb2 import JID
from neonize.utils.jid import Jid2String

from .config import BotConfig
from .forwarder import forward_incoming_message
from .utils import (
    save_and_display_qr,
    remove_qr_image,
    resolve_group_jid,
    list_all_groups,
    clean_phone_number,
    get_sender_phone_candidates,
)

init(autoreset=True)


class WhatsAppForwarderBot:
    def __init__(self, config: Optional[BotConfig] = None):
        self.config = config or BotConfig.load()
        self.target_jid: Optional[JID] = None
        self.target_group_name: Optional[str] = None
        self.is_connected = False

        # Inicializar cliente de Neonize con el nombre de la base de datos de sesión
        self.client = NewClient(self.config.session_name)

        # Registrar callback de código QR
        self.client.qr(self._on_qr)

        # Registrar manejadores de eventos
        self._register_events()

    def _on_qr(self, client: NewClient, data_qr: bytes):
        """Callback cuando WhatsApp solicita escanear el código QR."""
        save_and_display_qr(data_qr, save_path="qr.png")

    def _register_events(self):
        @self.client.event(ConnectedEv)
        def on_connected(client: NewClient, event: ConnectedEv):
            self.is_connected = True
            remove_qr_image("qr.png")

            print("\n" + Fore.GREEN + Style.BRIGHT + "=" * 60)
            print(Fore.GREEN + Style.BRIGHT + "   🟢 ¡BOT CONECTADO CON ÉXITO A WHATSAPP!")
            print(Fore.GREEN + Style.BRIGHT + "=" * 60)

            # Mostrar información de la cuenta
            if client.me and client.me.JID:
                me_jid = Jid2String(client.me.JID)
                me_name = client.me.PushName or "Bot"
                print(Fore.WHITE + f"👤 Cuenta: {Fore.CYAN}{me_name} ({me_jid})")

            # Resolver grupo destino
            self._resolve_destination_group()

            # Mostrar resumen de reglas de reenvío
            print("\n" + Fore.CYAN + "📋 CONFIGURACIÓN ACTIVA:")
            if self.config.forward_all_direct_messages:
                print(Fore.YELLOW + "   • Filtro de remitentes: REENVIAR TODOS LOS MENSAJES PRIVADOS")
            else:
                num_count = len(self.config.source_numbers)
                print(Fore.WHITE + f"   • Números a vigilar: {Fore.YELLOW}{num_count} número(s) configurado(s)")

            if self.target_jid:
                print(Fore.WHITE + f"   • Grupo destino: {Fore.GREEN}{self.target_group_name or self.config.target_group}")
            else:
                print(Fore.RED + f"   • Grupo destino: ⚠️ NO RESUELTO ('{self.config.target_group}')")

            print(Fore.CYAN + "-" * 60)
            print(Fore.MAGENTA + "👂 Bot escuchando mensajes entrantes... Presiona Ctrl+C para detener.\n")

        @self.client.event(MessageEv)
        def on_message(client: NewClient, event: MessageEv):
            self._handle_incoming_message(event)

        @self.client.event(PairStatusEv)
        def on_pair_status(client: NewClient, event: PairStatusEv):
            pass

        @self.client.event(DisconnectedEv)
        def on_disconnected(client: NewClient, event: DisconnectedEv):
            self.is_connected = False
            print(Fore.YELLOW + "⚠️  Desconectado temporalmente de WhatsApp. Reconectando...")

        @self.client.event(LoggedOutEv)
        def on_logged_out(client: NewClient, event: LoggedOutEv):
            self.is_connected = False
            print(Fore.RED + Style.BRIGHT + "❌ Sesión cerrada desde el teléfono. Vuelve a escanear el QR.")

    def _resolve_destination_group(self):
        """Intenta encontrar el JID del grupo destino a partir de la configuración."""
        if not self.config.target_group:
            print(Fore.YELLOW + "⚠️  No se ha especificado 'target_group' en config.json.")
            self._print_available_groups()
            return

        jid, group_name = resolve_group_jid(self.client, self.config.target_group)

        if jid:
            self.target_jid = jid
            self.target_group_name = group_name
            print(Fore.GREEN + f"✅ Grupo destino vinculado: '{group_name}'")
        else:
            print(Fore.RED + Style.BRIGHT + f"❌ No se encontró ningún grupo que coincida con '{self.config.target_group}'.")
            self._print_available_groups()

    def _print_available_groups(self):
        """Muestra en pantalla todos los grupos en los que participa la cuenta."""
        print("\n" + Fore.YELLOW + "📌 Lista de grupos en los que está tu cuenta:")
        groups = list_all_groups(self.client)
        if not groups:
            print(Fore.WHITE + "   (No se encontraron grupos unidos)")
        else:
            for idx, g in enumerate(groups, 1):
                name = g['name'] or "(Sin nombre)"
                print(Fore.WHITE + f"   {idx}. {Fore.GREEN}{name} {Fore.WHITE}-> JID: {Fore.CYAN}{g['jid_str']}")
            print(Fore.YELLOW + "\n💡 Sugerencia: Copia el nombre exacto o el JID en 'target_group' dentro de config.json y reinicia el bot.\n")

    def _handle_incoming_message(self, event: MessageEv):
        """Filtra y envía los mensajes elegibles al reenvío de forma limpia y silenciosa."""
        info = event.Info
        source = info.MessageSource

        chat_server = getattr(source.Chat, "Server", "")

        # 1. Ignorar estados / historias de WhatsApp
        if chat_server == "broadcast":
            return

        # 2. Ignorar mensajes enviados por el propio bot
        if source.IsFromMe:
            return

        # 3. Ignorar mensajes provenientes de otros grupos
        if source.IsGroup:
            return

        # 4. Obtener candidatos de número de teléfono del remitente
        candidates = get_sender_phone_candidates(self.client, source)

        # 5. Si no está en la lista permitida, mostrar hora de recepción y remitente
        if not self.config.should_forward_sender(candidates):
            now_str = datetime.now().strftime("%H:%M:%S")
            sender_name = info.Pushname or "Contacto"
            primary_num = candidates[0] if candidates else getattr(source.Chat, "User", "")
            print(Fore.YELLOW + f"[{now_str}] ℹ️  [NO EN LISTA] Mensaje recibido de {sender_name} (+{primary_num}) (no reenviado)")
            return

        # 6. Asegurar grupo destino
        if not self.target_jid:
            self._resolve_destination_group()
            if not self.target_jid:
                print(Fore.RED + "❌ Grupo destino no resuelto. Revisa 'target_group' en config.json.")
                return

        # 7. Reenviar mensaje
        try:
            forward_incoming_message(
                client=self.client,
                target_jid=self.target_jid,
                event=event,
                config=self.config,
            )
        except Exception as e:
            print(Fore.RED + f"❌ Error durante el reenvío: {e}")

    def run(self):
        """Inicia la conexión del bot."""
        print(Fore.CYAN + Style.BRIGHT + "🚀 Iniciando WhatsApp Forwarder Bot...")
        print(Fore.WHITE + f"📁 Sesión SQLite: {self.config.session_name}")
        try:
            self.client.connect()
        except KeyboardInterrupt:
            print(Fore.YELLOW + "\n🛑 Bot detenido por el usuario.")
        except Exception as e:
            print(Fore.RED + f"\n❌ Error en la ejecución del bot: {e}")
            raise
