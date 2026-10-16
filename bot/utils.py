import os
import re
from datetime import datetime
from typing import Optional, Tuple, List, Dict
import segno
from colorama import Fore, Style, init

from neonize.client import NewClient
from neonize.proto.Neonize_pb2 import JID
from neonize.utils.jid import Jid2String

# Inicializar colorama para soporte de colores en Windows cmd / PowerShell
init(autoreset=True)


def clean_phone_number(number: str) -> str:
    """
    Limpia un número de teléfono, extrayendo únicamente los dígitos.
    Ejemplo: '+54 9 11 1234-5678' -> '5491112345678'
    """
    if not number:
        return ""
    # Si viene con @s.whatsapp.net, extraer solo la parte de usuario
    if "@" in number:
        number = number.split("@")[0]
    return re.sub(r"\D", "", number)


def normalize_core_number(num: str) -> str:
    """
    Extrae y normaliza los dígitos de un número telefónico.
    Maneja variaciones como prefijos móviles de Argentina (549 vs 54).
    """
    d = re.sub(r"\D", "", num)
    if not d:
        return ""
    # Si es número de Argentina con formato 549..., normalizar a 54...
    if d.startswith("549") and len(d) >= 12:
        return "54" + d[3:]
    return d


def match_phone_number(sender: str, configured: str) -> bool:
    """
    Compara el número del remitente con un número configurado.
    Permite coincidencia exacta, normalización regional (ej: Argentina 549 vs 54)
    y coincidencia por número local / sufijo de abonado.
    """
    clean_sender = clean_phone_number(sender)
    clean_conf = clean_phone_number(configured)

    if not clean_sender or not clean_conf:
        return False

    # 1. Coincidencia exacta
    if clean_sender == clean_conf:
        return True

    # 2. Normalización de prefijos móviles (ej: Argentina 549 vs 54)
    norm_sender = normalize_core_number(clean_sender)
    norm_conf = normalize_core_number(clean_conf)
    if norm_sender == norm_conf:
        return True

    # 3. Coincidencia por terminación (número local / abonado)
    min_len = min(len(clean_sender), len(clean_conf))
    if min_len >= 8:
        if clean_sender.endswith(clean_conf) or clean_conf.endswith(clean_sender):
            return True
        if norm_sender.endswith(norm_conf) or norm_conf.endswith(norm_sender):
            return True
        # Comparar últimos 8 a 10 dígitos (número de teléfono sin prefijo de país)
        if clean_sender[-8:] == clean_conf[-8:]:
            return True

    return False


def get_sender_phone_candidates(client: NewClient, source) -> List[str]:
    """
    Extrae todos los posibles números o identificadores de teléfono del remitente
    a partir del objeto MessageSource, incluyendo resolución de LIDs (@lid) y SenderAlt.
    """
    candidates: List[str] = []

    # 1. SenderAlt (cuando WhatsApp usa LID, la alternativa suele ser el número de teléfono directo)
    if hasattr(source, "SenderAlt") and source.SenderAlt and source.SenderAlt.User:
        candidates.append(source.SenderAlt.User)

    # 2. Chat directo
    if hasattr(source, "Chat") and source.Chat and source.Chat.User:
        if source.Chat.Server != "lid":
            candidates.append(source.Chat.User)

    # 3. Sender directo
    if hasattr(source, "Sender") and source.Sender and source.Sender.User:
        if source.Sender.Server != "lid":
            candidates.append(source.Sender.User)

    # 4. Si el servidor es LID (@lid), resolver el número real usando la API interna de Neonize
    for target in [getattr(source, "Sender", None), getattr(source, "Chat", None)]:
        if target and getattr(target, "Server", "") == "lid" and getattr(target, "User", ""):
            try:
                pn_jid = client.get_pn_from_lid(target)
                if pn_jid and getattr(pn_jid, "User", ""):
                    candidates.append(pn_jid.User)
            except Exception:
                pass

    # 5. Fallback a User crudo
    if getattr(source, "Chat", None) and source.Chat.User:
        candidates.append(source.Chat.User)
    if getattr(source, "Sender", None) and source.Sender.User:
        candidates.append(source.Sender.User)

    # Eliminar duplicados manteniendo el orden
    seen = set()
    result = []
    for c in candidates:
        cleaned = clean_phone_number(c)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)

    return result


def format_timestamp(timestamp: int) -> str:
    """
    Convierte un timestamp Unix a una cadena legible local (YYYY-MM-DD HH:MM:SS).
    """
    try:
        ts = int(timestamp)
        if ts <= 0:
            dt = datetime.now()
        else:
            dt = datetime.fromtimestamp(ts)
    except Exception:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_forward_header(
    template: str,
    sender_name: str,
    sender_number: str,
    timestamp_str: str,
) -> str:
    """
    Genera el encabezado formateado para el mensaje reenviado.
    """
    clean_num = clean_phone_number(sender_number)
    display_name = sender_name.strip() if sender_name else "Desconocido"

    header = template.format(
        sender_name=display_name,
        sender_number=clean_num,
        timestamp=timestamp_str,
    )
    return header


def save_and_display_qr(data_qr: bytes, save_path: str = "qr.png") -> None:
    """
    Muestra el código QR en la consola y lo guarda como imagen PNG en el disco.
    """
    try:
        qr_str = data_qr.decode("utf-8") if isinstance(data_qr, bytes) else str(data_qr)
        qr = segno.make_qr(qr_str)

        print("\n" + Fore.CYAN + "=" * 60)
        print(Fore.YELLOW + Style.BRIGHT + "   📲 VINCULACIÓN DE WHATSAPP (CÓDIGO QR)")
        print(Fore.CYAN + "=" * 60)
        print(Fore.WHITE + "1. Abre WhatsApp en tu celular.")
        print(Fore.WHITE + "2. Ve a Menú (o Ajustes) -> " + Fore.GREEN + "Dispositivos vinculados" + Fore.WHITE + ".")
        print(Fore.WHITE + "3. Toca en " + Fore.GREEN + "Vincular un dispositivo" + Fore.WHITE + " y escanea:")
        print(Fore.CYAN + "-" * 60 + "\n")

        # Intentar mostrar en terminal
        try:
            qr.terminal(compact=True)
        except Exception as e:
            print(Fore.YELLOW + f"⚠️  No se pudo renderizar en texto en la terminal ({e}).")

        # Guardar en archivo PNG
        try:
            qr.save(save_path, scale=8)
            print("\n" + Fore.GREEN + Style.BRIGHT + f"📁 Imagen guardada: '{save_path}'")
            print(Fore.WHITE + "   (Puedes abrir este archivo PNG en tu computadora si se ve mejor)")
        except Exception as e:
            print(Fore.RED + f"⚠️  No se pudo guardar la imagen PNG: {e}")

        print(Fore.CYAN + "=" * 60 + "\n")

    except Exception as e:
        print(Fore.RED + f"Error procesando código QR: {e}")


def remove_qr_image(path: str = "qr.png") -> None:
    """
    Elimina la imagen temporal del QR cuando ya no sea necesaria.
    """
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def list_all_groups(client: NewClient) -> List[Dict[str, str]]:
    """
    Obtiene la lista de todos los grupos a los que pertenece la cuenta.
    """
    results: List[Dict[str, str]] = []
    try:
        groups = client.get_joined_groups()
        for g in groups:
            group_name = ""
            if g.GroupName and g.GroupName.Name:
                group_name = g.GroupName.Name
            jid_str = Jid2String(g.JID)
            results.append({
                "name": group_name,
                "jid_str": jid_str,
                "jid": g.JID,
            })
    except Exception as e:
        print(Fore.RED + f"Error al consultar grupos unidos: {e}")
    return results


def resolve_group_jid(
    client: NewClient,
    target_identifier: str,
) -> Tuple[Optional[JID], Optional[str]]:
    """
    Resuelve el identificador de grupo configurado (sea nombre o JID)
    a un objeto JID válido de Neonize.
    Retorna (JID, group_name) o (None, None).
    """
    target = target_identifier.strip()
    if not target:
        return None, None

    # Obtener grupos a los que pertenece la cuenta
    all_groups = list_all_groups(client)

    # Si ya tiene formato de JID de grupo (ej: 120363041234567890@g.us)
    if "@g.us" in target:
        user_part = target.split("@")[0]
        for g in all_groups:
            if g["jid"].User == user_part or g["jid_str"].lower() == target.lower():
                return g["jid"], g["name"]

        group_jid = JID(
            User=user_part,
            Server="g.us",
            RawAgent=0,
            Device=0,
            Integrator=0,
            IsEmpty=False,
        )
        return group_jid, target

    target_lower = target.lower()

    # 1. Búsqueda exacta por nombre
    for g in all_groups:
        if g["name"].strip().lower() == target_lower:
            return g["jid"], g["name"]

    # 2. Búsqueda parcial / subcadena
    for g in all_groups:
        if target_lower in g["name"].strip().lower():
            return g["jid"], g["name"]

    return None, None
