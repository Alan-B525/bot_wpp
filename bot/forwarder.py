import logging
from datetime import datetime
from typing import Optional
from colorama import Fore, Style

from neonize.client import NewClient
from neonize.proto.Neonize_pb2 import JID
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from neonize.events import MessageEv
from .config import BotConfig
from .utils import format_timestamp, build_forward_header

logger = logging.getLogger("WhatsAppForwarder.Forwarder")


def forward_incoming_message(
    client: NewClient,
    target_jid: JID,
    event: MessageEv,
    config: BotConfig,
) -> bool:
    """
    Procesa un evento de mensaje entrante y lo reenvía al grupo de destino según su tipo.
    Retorna True si fue reenviado exitosamente, False en caso contrario.
    """
    info = event.Info
    msg = event.Message

    sender_name = info.Pushname or "Desconocido"
    sender_number = info.MessageSource.Sender.User or info.MessageSource.Chat.User
    timestamp_str = format_timestamp(info.Timestamp)

    # Construir encabezado
    header = ""
    if config.forward_header:
        header = build_forward_header(
            template=config.header_template,
            sender_name=sender_name,
            sender_number=sender_number,
            timestamp_str=timestamp_str,
        )

    now_str = datetime.now().strftime("%H:%M:%S")

    # 1. Mensaje de Texto Simple (conversation)
    if msg.HasField("conversation") and msg.conversation:
        content = f"{header}{msg.conversation}"
        client.send_message(target_jid, content)
        print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Mensaje de texto de {sender_name} (+{sender_number})")
        return True

    # 2. Mensaje de Texto Extendido (links, menciones, citas)
    if msg.HasField("extendedTextMessage") and msg.extendedTextMessage.text:
        content = f"{header}{msg.extendedTextMessage.text}"
        client.send_message(target_jid, content)
        print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Mensaje de texto de {sender_name} (+{sender_number})")
        return True

    # 3. Imagen
    if msg.HasField("imageMessage"):
        img = msg.imageMessage
        caption_orig = img.caption or ""
        caption = f"{header}{caption_orig}".strip() if header else caption_orig

        try:
            media_bytes = client.download_any(msg)
            if media_bytes:
                client.send_image(target_jid, media_bytes, caption=caption or None)
                print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Imagen de {sender_name} (+{sender_number})")
                return True
            else:
                logger.error("No se recibieron bytes al descargar la imagen.")
        except Exception as e:
            logger.error(f"Error al descargar/enviar imagen: {e}")
            if header:
                client.send_message(target_jid, f"{header}⚠️ *[No se pudo descargar la imagen adjunta]*")
            return False

    # 4. Video / GIF
    if msg.HasField("videoMessage"):
        vid = msg.videoMessage
        caption_orig = vid.caption or ""
        caption = f"{header}{caption_orig}".strip() if header else caption_orig
        is_gif = bool(vid.gifPlayback)

        try:
            media_bytes = client.download_any(msg)
            if media_bytes:
                client.send_video(
                    target_jid,
                    media_bytes,
                    caption=caption or None,
                    gifplayback=is_gif,
                )
                print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Video/GIF de {sender_name} (+{sender_number})")
                return True
            else:
                logger.error("No se recibieron bytes al descargar el video.")
        except Exception as e:
            logger.error(f"Error al descargar/enviar video: {e}")
            if header:
                client.send_message(target_jid, f"{header}⚠️ *[No se pudo descargar el video adjunto]*")
            return False

    # 5. Audio / Nota de voz
    if msg.HasField("audioMessage"):
        aud = msg.audioMessage
        is_ptt = bool(aud.PTT)

        try:
            media_bytes = client.download_any(msg)
            if media_bytes:
                if header:
                    tag = "🎙️ *[Nota de voz]*" if is_ptt else "🎵 *[Archivo de Audio]*"
                    client.send_message(target_jid, f"{header}{tag}")

                client.send_audio(target_jid, media_bytes, ptt=is_ptt)
                print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Audio de {sender_name} (+{sender_number})")
                return True
            else:
                logger.error("No se recibieron bytes al descargar el audio.")
        except Exception as e:
            logger.error(f"Error al descargar/enviar audio: {e}")
            if header:
                client.send_message(target_jid, f"{header}⚠️ *[No se pudo descargar el audio adjunto]*")
            return False

    # 6. Documento / Archivo (PDF, Word, etc.)
    doc = None
    if msg.HasField("documentMessage"):
        doc = msg.documentMessage
    elif msg.HasField("documentWithCaptionMessage"):
        doc = msg.documentWithCaptionMessage.message.documentMessage

    if doc:
        filename = doc.fileName or "documento"
        mimetype = doc.mimetype or None
        caption_orig = doc.caption or ""
        caption = f"{header}{caption_orig}".strip() if header else caption_orig

        try:
            media_bytes = client.download_any(msg)
            if media_bytes:
                client.send_document(
                    target_jid,
                    media_bytes,
                    caption=caption or None,
                    filename=filename,
                    mimetype=mimetype,
                )
                print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Documento '{filename}' de {sender_name} (+{sender_number})")
                return True
            else:
                logger.error("No se recibieron bytes al descargar el documento.")
        except Exception as e:
            logger.error(f"Error al descargar/enviar documento: {e}")
            if header:
                client.send_message(target_jid, f"{header}⚠️ *[No se pudo descargar el documento '{filename}']*")
            return False

    # 7. Sticker
    if msg.HasField("stickerMessage"):
        try:
            media_bytes = client.download_any(msg)
            if media_bytes:
                if header:
                    client.send_message(target_jid, f"{header}🏷️ *[Sticker]*")
                client.send_sticker(target_jid, media_bytes)
                print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Sticker de {sender_name}")
                return True
            else:
                logger.error("No se recibieron bytes al descargar el sticker.")
        except Exception as e:
            logger.error(f"Error al descargar/enviar sticker: {e}")
            return False

    # 8. Contacto
    if msg.HasField("contactMessage"):
        if header:
            c = msg.contactMessage
            name = c.displayName or "Contacto"
            vcard = c.vcard or ""
            text = f"{header}👤 *[Contacto Compartido]*\n*Nombre:* {name}\n{vcard}"
            client.send_message(target_jid, text)
        else:
            client.send_message(target_jid, Message(contactMessage=msg.contactMessage))
        print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Contacto compartido por {sender_name}")
        return True

    # 9. Ubicación
    if msg.HasField("locationMessage"):
        if header:
            loc = msg.locationMessage
            lat = loc.degreesLatitude
            lng = loc.degreesLongitude
            name = loc.name or ""
            address = loc.address or ""
            text = (
                f"{header}📍 *[Ubicación Compartida]*\n"
                f"{name} {address}\n"
                f"🌐 Coordenadas: {lat}, {lng}\n"
                f"🔗 Ver en Maps: https://maps.google.com/?q={lat},{lng}"
            )
            client.send_message(target_jid, text)
        else:
            client.send_message(target_jid, Message(locationMessage=msg.locationMessage))
        print(Fore.GREEN + f"[{now_str}] ✔️ [REENVIADO] Ubicación compartida por {sender_name}")
        return True

    return False
