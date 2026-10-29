import os
import sys
import time
import queue
import threading
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

        # Inicializar módulo de mediciones si está habilitado
        self.measurement_store = None
        self.measurement_agent = None
        if getattr(self.config, "measurement_db_enabled", True):
            try:
                from .measurement_store import MeasurementStore
                from .measurement_agent import MeasurementAgent
                self.measurement_store = MeasurementStore(
                    db_path=self.config.measurement_db_path,
                    photos_dir=self.config.photos_dir,
                )
                self.measurement_agent = MeasurementAgent(
                    api_key=self.config.gemini_api_key,
                    store=self.measurement_store,
                )
            except Exception as e:
                print(Fore.RED + f"⚠️ No se pudo inicializar módulo de mediciones: {e}")

        # Inicializar cliente de Neonize con el nombre de la base de datos de sesión
        self.client = NewClient(self.config.session_name)

        # Cola de ingesta secuencial FIFO y worker thread dedicado
        self.ingestion_queue = queue.Queue()
        self.is_running = True
        self.worker_thread = None
        self._start_worker()

        # Registrar callback de código QR
        self.client.qr(self._on_qr)

        # Registrar manejadores de eventos
        self._register_events()

    def _start_worker(self):
        """Inicia el worker thread dedicado para procesar mediciones en cola."""
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="MeasurementIngestionWorker",
        )
        self.worker_thread.start()

    def _worker_loop(self):
        """Bucle secuencial FIFO de consumo de mediciones."""
        while self.is_running:
            try:
                task = self.ingestion_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if task is None:  # Sentinel de parada
                self.ingestion_queue.task_done()
                break

            try:
                self._process_measurement_task(task)
            except Exception as e:
                print(Fore.RED + f"⚠️ Error en worker de ingesta: {e}")
            finally:
                self.ingestion_queue.task_done()

    def stop(self):
        """Detiene el bot y drena/apaga el worker thread de forma segura."""
        self.is_running = False
        if hasattr(self, "ingestion_queue"):
            self.ingestion_queue.put(None)
        if hasattr(self, "worker_thread") and self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)

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

        # 8. Procesar y almacenar mensaje de chat en vivo y medición limnimétrica
        sender_name = getattr(info, "Pushname", None) or "Contacto"
        sender_number = candidates[0] if candidates else getattr(getattr(source, "Chat", None), "User", "")

        # Obtener timestamp con formato estándar
        if getattr(info, "Timestamp", None):
            try:
                ts_dt = datetime.fromtimestamp(info.Timestamp)
                timestamp_str = ts_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Extraer texto de campos posibles
        msg = getattr(event, "Message", None)
        text_parts = []
        if msg:
            if hasattr(msg, "HasField"):
                try:
                    if msg.HasField("conversation") and msg.conversation:
                        text_parts.append(msg.conversation)
                    if msg.HasField("extendedTextMessage") and msg.extendedTextMessage.text:
                        text_parts.append(msg.extendedTextMessage.text)
                    if msg.HasField("imageMessage") and msg.imageMessage.caption:
                        text_parts.append(msg.imageMessage.caption)
                    if msg.HasField("documentMessage") and msg.documentMessage.caption:
                        text_parts.append(msg.documentMessage.caption)
                    elif msg.HasField("documentWithCaptionMessage") and msg.documentWithCaptionMessage.message.documentMessage.caption:
                        text_parts.append(msg.documentWithCaptionMessage.message.documentMessage.caption)
                except Exception:
                    pass
            else:
                for attr in ("conversation", "text", "caption"):
                    val = getattr(msg, attr, None)
                    if val and isinstance(val, str):
                        text_parts.append(val)

        full_text = " ".join(text_parts).strip()

        # Extraer imagen si existe (imageMessage o documentos de imagen)
        image_bytes = None
        foto_path = None
        if msg:
            is_image = False
            if hasattr(msg, "HasField"):
                try:
                    if msg.HasField("imageMessage"):
                        is_image = True
                    else:
                        doc = None
                        if msg.HasField("documentMessage"):
                            doc = msg.documentMessage
                        elif msg.HasField("documentWithCaptionMessage"):
                            doc = msg.documentWithCaptionMessage.message.documentMessage
                        if doc and getattr(doc, "mimetype", "") and doc.mimetype.startswith("image/"):
                            is_image = True
                except Exception:
                    pass
            elif getattr(msg, "imageMessage", None):
                is_image = True

            if is_image and hasattr(self.client, "download_any"):
                try:
                    image_bytes = self.client.download_any(msg)
                except Exception as e:
                    print(Fore.YELLOW + f"⚠️ No se pudo descargar imagen para análisis limnimétrico: {e}")

        # 8. Ingestión Causal Estricta:
        # Paso 1: Persistir mensaje en mensajes_chat primero y capturar mensaje_id
        mensaje_id = None
        if self.measurement_store:
            try:
                mensaje_id = self.measurement_store.save_chat_message(
                    remitente_telefono=sender_number,
                    remitente_nombre=sender_name,
                    timestamp_str=timestamp_str,
                    texto=full_text or None,
                    foto_path=None,
                )
            except Exception as e:
                print(Fore.RED + f"⚠️ Error guardando mensaje de chat en vivo: {e}")

        # Paso 2: Si hay imagen, guardar archivo en disco y asociar foto a mensaje para obtener adjunto_id
        adjunto_id = None
        if image_bytes and self.measurement_store:
            try:
                foto_path = self.measurement_store.save_photo(image_bytes, timestamp_str, "chat")
                if hasattr(self.measurement_store, "associate_photo_to_message"):
                    adjunto_id = self.measurement_store.associate_photo_to_message(
                        remitente_telefono=sender_number,
                        timestamp_str=timestamp_str,
                        foto_path=foto_path,
                    )
                if mensaje_id and foto_path:
                    try:
                        with self.measurement_store.get_connection() as conn:
                            conn.cursor().execute(
                                "UPDATE mensajes_chat SET foto_path = ?, archivo_adjunto = ? WHERE id = ?",
                                (foto_path, foto_path, mensaje_id)
                            )
                            conn.commit()
                    except Exception:
                        pass
            except Exception as e:
                print(Fore.YELLOW + f"⚠️ No se pudo guardar/asociar foto en disco: {e}")

        # Paso 3: Encolar tarea en la cola Productor-Consumidor (orden causal garantizado)
        if self.measurement_store and self.measurement_agent:
            if full_text or image_bytes or foto_path:
                task = (
                    mensaje_id,
                    adjunto_id,
                    full_text,
                    image_bytes,
                    foto_path,
                    timestamp_str,
                    sender_name,
                    sender_number,
                )
                self.ingestion_queue.put(task)

    def _process_measurement_task(self, task):
        """Procesa una tarea de ingesta consumida de la cola secuencial FIFO."""
        if isinstance(task, (tuple, list)):
            (
                mensaje_id,
                adjunto_id,
                full_text,
                image_bytes,
                foto_path,
                timestamp_str,
                sender_name,
                sender_number,
            ) = task
        elif isinstance(task, dict):
            mensaje_id = task.get("mensaje_id")
            adjunto_id = task.get("adjunto_id")
            full_text = task.get("full_text")
            image_bytes = task.get("image_bytes")
            foto_path = task.get("foto_path")
            timestamp_str = task.get("timestamp_str")
            sender_name = task.get("sender_name")
            sender_number = task.get("sender_number")
        else:
            return

        if not full_text and not image_bytes and not foto_path:
            return

        if not self.measurement_store or not self.measurement_agent:
            return

        try:
            # Lista de estaciones conocidas
            known_stations = []
            if hasattr(self.measurement_store, "get_all_stations"):
                try:
                    known_stations = [st["nombre"] for st in self.measurement_store.get_all_stations()]
                except Exception:
                    pass

            # Procesar con el agente multimodal
            analysis = self.measurement_agent.process_message(
                text=full_text,
                image_bytes=image_bytes,
                known_stations=known_stations,
                sender_info={"name": sender_name, "phone": sender_number},
                store=self.measurement_store,
            )

            if analysis and analysis.get("es_medicion_valida"):
                meas_id = self.measurement_store.save_measurement(
                    estacion_detectada=analysis.get("estacion") or "Desconocida",
                    remitente_telefono=sender_number,
                    timestamp_medicion=timestamp_str,
                    valor_original=analysis.get("valor_original"),
                    valor_metros=analysis.get("valor_metros"),
                    valor_cm=analysis.get("valor_cm"),
                    unidad_detectada=analysis.get("unidad_detectada") or "m",
                    tendencia_rio=analysis.get("tendencia"),
                    origen_dato=analysis.get("origen") or "texto",
                    confianza=analysis.get("confianza") or "alta",
                    remitente_nombre=sender_name,
                    mensaje_texto=full_text or None,
                    foto_path=foto_path,
                    foto_bytes=None,  # Ya persistido en disco
                    observaciones_ia=analysis.get("observaciones_ia") or analysis.get("lectura_regla_foto"),
                    rio=analysis.get("rio"),
                    metodo_asignacion=analysis.get("metodo_asignacion") or "explicito",
                    mensaje_id=mensaje_id,
                    adjunto_id=adjunto_id,
                    ia_estacion_detectada=analysis.get("ia_estacion_detectada"),
                    ia_valor_metros=analysis.get("ia_valor_metros"),
                    ia_tendencia=analysis.get("ia_tendencia"),
                    ia_confianza=analysis.get("ia_confianza"),
                )

                now_str = datetime.now().strftime("%H:%M:%S")
                st_name = analysis.get("estacion") or "Desconocida"
                val_m = analysis.get("valor_metros")
                try:
                    val_str = f"{float(val_m):.2f}m" if val_m is not None else "N/D"
                except (ValueError, TypeError):
                    val_str = str(val_m) if val_m is not None else "N/D"
                tend_str = f" | Tendencia: {analysis.get('tendencia')}" if analysis.get("tendencia") else ""
                metodo_str = f" [{analysis.get('metodo_asignacion')}]" if analysis.get("metodo_asignacion") else ""
                foto_icon = " 📷 (Foto guardada)" if (image_bytes or foto_path) else ""
                print(
                    Fore.CYAN + Style.BRIGHT +
                    f"[{now_str}] 📊 [MEDICIÓN REGISTRADA #{meas_id}] Estación: {Fore.GREEN}{st_name}{Fore.CYAN} | Nivel: {Fore.YELLOW}{val_str}{Fore.CYAN}{tend_str}{metodo_str}{foto_icon}"
                )
        except Exception as e:
            print(Fore.RED + f"⚠️ Error registrando medición limnimétrica: {e}")

    def _process_measurement(
        self,
        event: MessageEv,
        candidates: list,
        full_text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        foto_path: Optional[str] = None,
        timestamp_str: Optional[str] = None,
        sender_name: Optional[str] = None,
        sender_number: Optional[str] = None,
        mensaje_id: Optional[int] = None,
        adjunto_id: Optional[int] = None,
    ):
        """Wrapper de compatibilidad para procesar medición directamente."""
        try:
            info = getattr(event, "Info", None)
            source = getattr(info, "MessageSource", None) if info else None
            msg = getattr(event, "Message", None)

            if sender_name is None:
                sender_name = getattr(info, "Pushname", None) or "Contacto"
            if sender_number is None:
                sender_number = candidates[0] if candidates else getattr(getattr(source, "Chat", None), "User", "")

            if timestamp_str is None:
                if getattr(info, "Timestamp", None):
                    try:
                        ts_dt = datetime.fromtimestamp(info.Timestamp)
                        timestamp_str = ts_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            task = (
                mensaje_id,
                adjunto_id,
                full_text,
                image_bytes,
                foto_path,
                timestamp_str,
                sender_name,
                sender_number,
            )
            self._process_measurement_task(task)
        except Exception as e:
            print(Fore.RED + f"⚠️ Error en wrapper _process_measurement: {e}")

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
        finally:
            self.stop()


# Alias para conveniencia de integración y pruebas
WhatsAppClient = WhatsAppForwarderBot
