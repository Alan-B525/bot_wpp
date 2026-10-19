import os
import re
import sys
import zipfile
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

from bot.config import BotConfig
from bot.measurement_store import MeasurementStore
from bot.measurement_agent import MeasurementAgent


def parse_whatsapp_date(date_str: str) -> Optional[str]:
    """
    Intenta convertir distintos formatos de fecha de exportación de WhatsApp
    a formato estándar 'YYYY-MM-DD HH:MM:SS'.
    Formatos comunes:
    - '15/10/23, 08:30:15'
    - '15/10/2023, 08:30:15'
    - '15/10/2023, 08:30'
    - '15/10/2023, 08.30'
    - '15/10/2023, 08.30.15'
    - '15/10/23 8:30 a. m.'
    - '[15/10/23 08:30:15]'
    """
    cleaned = date_str.strip().strip("[]").replace("\u202f", " ").replace("\xa0", " ")
    cleaned = cleaned.replace("a. m.", "AM").replace("p. m.", "PM").replace("a.m.", "AM").replace("p.m.", "PM")
    cleaned = cleaned.replace("am", "AM").replace("pm", "PM")

    # Si la hora viene con puntos en lugar de dos puntos (ej. 08.30 o 08.30.15)
    cleaned = re.sub(r"(\d{1,2})\.(\d{2})\.(\d{2})", r"\1:\2:\3", cleaned)
    cleaned = re.sub(r"(\d{1,2})\.(\d{2})(?!\d)", r"\1:\2", cleaned)

    patterns = [
        ("%d/%m/%y, %H:%M:%S", False),
        ("%d/%m/%Y, %H:%M:%S", False),
        ("%d/%m/%y, %H:%M", False),
        ("%d/%m/%Y, %H:%M", False),
        ("%d/%m/%y %H:%M:%S", False),
        ("%d/%m/%Y %H:%M:%S", False),
        ("%d/%m/%y %H:%M", False),
        ("%d/%m/%Y %H:%M", False),
        ("%d/%m/%y, %I:%M:%S %p", False),
        ("%d/%m/%Y, %I:%M:%S %p", False),
        ("%d/%m/%y, %I:%M %p", False),
        ("%d/%m/%Y, %I:%M %p", False),
        ("%d/%m/%y %I:%M:%S %p", False),
        ("%d/%m/%Y %I:%M:%S %p", False),
        ("%d/%m/%y %I:%M %p", False),
        ("%d/%m/%Y %I:%M %p", False),
        ("%m/%d/%y, %I:%M:%S %p", False),
        ("%m/%d/%Y, %I:%M:%S %p", False),
        ("%Y-%m-%d %H:%M:%S", False),
        ("%Y-%m-%d %H:%M", False),
    ]

    for pat, _ in patterns:
        try:
            dt = datetime.strptime(cleaned, pat)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    # Si no se pudo parsear, devolver timestamp actual
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_whatsapp_chat(chat_file_path: str) -> List[Dict[str, Any]]:
    """
    Lee un archivo _chat.txt de WhatsApp y separa los mensajes con su fecha,
    remitente, texto y archivo adjunto si lo tiene.
    """
    if not os.path.exists(chat_file_path):
        raise FileNotFoundError(f"No se encontró el archivo: {chat_file_path}")

    # Patrón para inicio de línea con fecha (admite /.- en fecha y :. en hora)
    header_pattern = re.compile(
        r"^(?:\[?(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}[, ]+\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s*[ap]\.?\s*m\.?)?)\]?(?:\s*-\s*|\s+))([^:]+?):\s*(.*)$",
        re.IGNORECASE
    )

    messages = []
    current_msg: Optional[Dict[str, Any]] = None

    with open(chat_file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # Quitar marcas de orden de bytes y caracteres invisibles LTR/RTL de WhatsApp
            clean_line = line.replace("\u200e", "").replace("\u200f", "").rstrip("\r\n")
            if not clean_line.strip():
                continue

            match = header_pattern.match(clean_line)
            if match:
                if current_msg:
                    messages.append(current_msg)

                raw_date = match.group(1).strip()
                sender = match.group(2).strip()
                body = match.group(3).strip()

                # Ignorar notificaciones de sistema típicas de WhatsApp
                if "cifrados de extremo a extremo" in body or "creó este grupo" in body:
                    current_msg = None
                    continue

                # Detectar adjunto
                # Formato 1 (iOS): <adjunto: archivo.jpg> o <attached: file.jpg>
                # Formato 2 (Android): "WhatsApp Image ... .jpeg (archivo adjunto)" o "archivo.jpg (archivo adjunto)"
                # Formato 3: Nombre de archivo solitario en la línea
                attachment = None
                att_match = re.search(r"<(?:adjunto|attached):\s*([^>]+)>", body, re.IGNORECASE)
                if att_match:
                    attachment = att_match.group(1).strip()
                    body = re.sub(r"<(?:adjunto|attached):\s*[^>]+>", "", body, flags=re.IGNORECASE).strip()
                else:
                    att_match = re.search(r"([^<>\r\n:]+?\.(?:jpg|jpeg|png|webp))\s*\((?:archivo adjunto|file attached)\)", body, re.IGNORECASE)
                    if att_match:
                        attachment = att_match.group(1).strip()
                        body = re.sub(r"[^<>\r\n:]+?\.(?:jpg|jpeg|png|webp)\s*\((?:archivo adjunto|file attached)\)", "", body, flags=re.IGNORECASE).strip()
                    else:
                        att_match = re.search(r"^([^<>\r\n:]+?\.(?:jpg|jpeg|png|webp))\s*$", body, re.IGNORECASE)
                        if att_match:
                            attachment = att_match.group(1).strip()
                            body = ""

                current_msg = {
                    "raw_date": raw_date,
                    "timestamp": parse_whatsapp_date(raw_date),
                    "sender": sender,
                    "text": body,
                    "attachment": attachment,
                }
            else:
                # Línea de continuación del mensaje anterior
                if current_msg:
                    current_msg["text"] += "\n" + clean_line

    if current_msg:
        messages.append(current_msg)

    return messages


def _extraer_telefono_de_nombre(nombre: str) -> str:
    """Extrae el número de teléfono limpio del nombre del archivo zip o chat."""
    match = re.search(r"\+?(\d[\d\s\-]{6,}\d)", nombre)
    if match:
        return re.sub(r"\D", "", match.group(1))
    return ""


def procesar_un_chat(
    chat_file: str,
    extract_dir: str,
    store: MeasurementStore,
    agent: MeasurementAgent,
    default_sender_phone: str = "",
    limite: Optional[int] = None
) -> Dict[str, Any]:
    """Procesa los mensajes de un archivo _chat.txt con sus fotos adjuntas."""
    messages = parse_whatsapp_chat(chat_file)
    print(f"📄 Archivo: {os.path.basename(chat_file)} ({len(messages)} mensajes)")

    if limite:
        messages = messages[:limite]

    known_stations = [st["nombre"] for st in store.get_all_stations()]

    # Guardar todos los mensajes originales en la tabla mensajes_chat para el historial cronológico
    for m in messages:
        s_phone = default_sender_phone or re.sub(r"\D", "", m["sender"]) or m["sender"]
        store.save_chat_message(
            remitente_telefono=s_phone,
            timestamp_mensaje=m["timestamp"],
            texto=m["text"],
            remitente_nombre=m["sender"],
            archivo_adjunto=m.get("attachment")
        )

    # Fase 1: Asociar fotos de mensajes en ventana de transmisión de hasta 15 minutos (900 segundos)
    # Si un mensaje tiene foto pero no texto, buscar el mensaje de texto explicativo más cercano
    WINDOW_SECONDS = 900
    for i in range(len(messages)):
        msg = messages[i]
        if msg.get("attachment") and not msg.get("text"):
            t1 = None
            try:
                t1 = datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            if not t1:
                continue

            best_cand = None
            min_delta = float("inf")
            for j in range(len(messages)):
                if i == j:
                    continue
                cand = messages[j]
                if cand.get("text") and not cand.get("attachment"):
                    try:
                        t2 = datetime.strptime(cand["timestamp"], "%Y-%m-%d %H:%M:%S")
                        delta = abs((t1 - t2).total_seconds())
                        if delta <= WINDOW_SECONDS and delta < min_delta:
                            min_delta = delta
                            best_cand = cand
                    except Exception:
                        pass

            if best_cand:
                best_cand["attachment"] = msg["attachment"]
                msg["attachment"] = None  # Marcado para no procesar duplicado sin texto

    total_procesados = 0
    total_mediciones = 0
    estaciones_detectadas = set()

    for idx, msg in enumerate(messages, 1):
        total_procesados += 1
        text = msg["text"].strip()
        attachment_name = msg["attachment"]
        timestamp = msg["timestamp"]
        sender = msg["sender"]
        sender_phone = default_sender_phone or re.sub(r"\D", "", sender) or sender

        image_bytes = None
        if attachment_name:
            att_path = os.path.join(extract_dir, attachment_name)
            if os.path.exists(att_path):
                try:
                    with open(att_path, "rb") as img_f:
                        image_bytes = img_f.read()
                except Exception as e:
                    print(f"⚠️ Error leyendo imagen {att_path}: {e}")

        # Si no hay texto ni imagen, continuar
        if not text and not image_bytes:
            continue

        result = agent.process_message(
            text=text,
            image_bytes=image_bytes,
            known_stations=known_stations,
            sender_info={"name": sender, "phone": sender_phone},
        )

        if result and result.get("es_medicion_valida"):
            # Puede venir una lista de mediciones si el mensaje reportó varias estaciones
            mediciones_a_guardar = result.get("mediciones") or [result]

            for item in mediciones_a_guardar:
                st_name = item.get("estacion") or "Desconocida"
                estaciones_detectadas.add(st_name)
                val_m = item.get("valor_metros")
                val_str = f"{val_m:.2f}m" if val_m is not None else "N/D"

                meas_id = store.save_measurement(
                    estacion_detectada=st_name,
                    remitente_telefono=sender_phone,
                    timestamp_medicion=timestamp,
                    valor_original=item.get("valor_original"),
                    valor_metros=item.get("valor_metros"),
                    valor_cm=item.get("valor_cm"),
                    unidad_detectada=item.get("unidad_detectada") or "m",
                    tendencia_rio=item.get("tendencia"),
                    origen_dato=item.get("origen") or ("ambos" if image_bytes and text else ("foto_regla" if image_bytes else "texto")),
                    confianza=item.get("confianza") or "alta",
                    remitente_nombre=sender,
                    mensaje_texto=text or None,
                    foto_bytes=image_bytes,
                    observaciones_ia=item.get("lectura_regla_foto"),
                    rio=item.get("rio"),
                )
                total_mediciones += 1
                has_photo = "📸" if image_bytes else "  "
                print(f"  [{idx}/{len(messages)}] {has_photo} ✅ #{meas_id}: {st_name} | {val_str} ({timestamp})")
        else:
            if idx % 25 == 0:
                print(f"  [{idx}/{len(messages)}] Procesando...")

    return {
        "total_procesados": total_procesados,
        "total_mediciones": total_mediciones,
        "estaciones": list(estaciones_detectadas),
    }


def importar_exportacion(
    source_path: str,
    store: MeasurementStore,
    agent: MeasurementAgent,
    limite: Optional[int] = None
) -> Dict[str, Any]:
    """
    Procesa un archivo ZIP, directorio con archivos ZIP, o directorio con chat extraído.
    """
    # CASO 1: source_path es un directorio que contiene archivos .zip
    if os.path.isdir(source_path):
        zips = [f for f in os.listdir(source_path) if f.lower().endswith(".zip")]
        if zips:
            # Filtrar duplicados con sufijo (1), (2) si existe el original
            zips_filtrados = []
            for z in sorted(zips):
                m_dup = re.search(r"^(.*?)\s*\(\d+\)\.zip$", z, re.IGNORECASE)
                if m_dup:
                    orig = m_dup.group(1) + ".zip"
                    if orig in zips:
                        print(f"⏭️ Omitiendo duplicado '{z}' (ya existe '{orig}')")
                        continue
                zips_filtrados.append(z)

            print(f"📂 Procesando directorio con {len(zips_filtrados)} archivos ZIP de chats...")
            total_proc = 0
            total_med = 0
            todas_estaciones = set()

            for idx, zname in enumerate(zips_filtrados, 1):
                full_zpath = os.path.join(source_path, zname)
                print(f"\n[{idx}/{len(zips_filtrados)}] 📦 Descomprimiendo y procesando: {zname}")
                sub_res = importar_exportacion(full_zpath, store, agent, limite=limite)
                total_proc += sub_res.get("total_procesados", 0)
                total_med += sub_res.get("total_mediciones", 0)
                todas_estaciones.update(sub_res.get("estaciones", []))

            return {
                "total_procesados": total_proc,
                "total_mediciones": total_med,
                "estaciones": list(todas_estaciones),
            }

    # CASO 2: source_path es un único archivo ZIP
    extract_dir = source_path
    temp_dir_to_clean = None
    default_sender_phone = _extraer_telefono_de_nombre(os.path.basename(source_path))

    if os.path.isfile(source_path) and source_path.lower().endswith(".zip"):
        import tempfile
        temp_dir_to_clean = tempfile.mkdtemp(prefix="wpp_import_")
        with zipfile.ZipFile(source_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir_to_clean)
        extract_dir = temp_dir_to_clean

    try:
        # Buscar archivo de chat .txt
        chat_file = None
        if os.path.isfile(extract_dir) and extract_dir.endswith(".txt"):
            chat_file = extract_dir
            extract_dir = os.path.dirname(chat_file)
        else:
            for f in os.listdir(extract_dir):
                if f.endswith(".txt") and ("_chat" in f.lower() or "chat" in f.lower() or "whatsapp" in f.lower()):
                    chat_file = os.path.join(extract_dir, f)
                    break
            if not chat_file:
                for f in os.listdir(extract_dir):
                    if f.endswith(".txt"):
                        chat_file = os.path.join(extract_dir, f)
                        break

        if not chat_file:
            print(f"⚠️ No se encontró archivo de texto de chat en {source_path}")
            return {"total_procesados": 0, "total_mediciones": 0, "estaciones": []}

        return procesar_un_chat(
            chat_file=chat_file,
            extract_dir=extract_dir,
            store=store,
            agent=agent,
            default_sender_phone=default_sender_phone,
            limite=limite,
        )
    finally:
        if temp_dir_to_clean and os.path.exists(temp_dir_to_clean):
            import shutil
            shutil.rmtree(temp_dir_to_clean, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Importador de historial de WhatsApp para mediciones limnimétricas.")
    parser.add_argument("--origen", "-o", default="data/import_historial", help="Ruta al archivo .zip, .txt o directorio con exportación")
    parser.add_argument("--limite", "-l", type=int, default=None, help="Límite de mensajes a procesar")
    parser.add_argument("--db", default=None, help="Ruta a base de datos mediciones.db (opcional)")
    parser.add_argument("--solo-heuristico", action="store_true", help="Usa únicamente el motor de reglas heurístico sin invocar la API de Gemini")
    args = parser.parse_args()

    config = BotConfig.load()
    db_path = args.db or config.measurement_db_path
    store = MeasurementStore(db_path=db_path, photos_dir=config.photos_dir)
    api_key = "" if args.solo_heuristico else config.gemini_api_key
    agent = MeasurementAgent(api_key=api_key)

    source = args.origen
    if not os.path.exists(source):
        # Si la carpeta por defecto no existe, crearla y avisar al usuario
        os.makedirs(source, exist_ok=True)
        print(f"ℹ️ La carpeta '{source}' fue creada. Coloca allí el archivo .zip o _chat.txt exportado de WhatsApp y vuelve a ejecutar este comando.")
        sys.exit(0)

    try:
        resultado = importar_exportacion(source, store, agent, limite=args.limite)
        print("\n" + "=" * 50)
        print("🎉 IMPORTACIÓN FINALIZADA:")
        print(f"• Mensajes procesados: {resultado['total_procesados']}")
        print(f"• Mediciones registradas: {resultado['total_mediciones']}")
        print(f"• Estaciones detectadas ({len(resultado['estaciones'])}): {', '.join(resultado['estaciones'])}")
        print("=" * 50)
    except Exception as e:
        print(f"❌ Error durante la importación: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
