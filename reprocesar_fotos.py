import os
import sys
import time
import json
import logging
import sqlite3
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ReprocesarFotos")

# Cargar entorno
load_dotenv()

from bot.measurement_store import MeasurementStore
from bot.measurement_agent import MeasurementAgent, SYSTEM_PROMPT

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


def obtener_estacion_frecuente(cur, telefono: str) -> str:
    """Busca si el remitente tiene una estación habitual en sus otras mediciones."""
    cur.execute("""
        SELECT estacion_detectada, COUNT(*) as cnt 
        FROM mediciones 
        WHERE remitente_telefono = ? AND estacion_detectada NOT IN ('Regla Foto', 'Desconocida', '')
        GROUP BY estacion_detectada 
        ORDER BY cnt DESC 
        LIMIT 1
    """, (telefono,))
    row = cur.fetchone()
    return row[0] if row else ""


def reprocesar(limite: int = 50, delay_seconds: float = 2.0):
    store = MeasurementStore(db_path="data/mediciones.db", photos_dir="data/fotos")
    
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("No se encontró GEMINI_API_KEY en el entorno.")
        return

    client = genai.Client(api_key=api_key)
    
    # Modelos a probar en orden de preferencia
    models = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]
    
    known_stations = [s["nombre"] for s in store.get_all_stations()]

    with store.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, remitente_telefono, remitente_nombre, timestamp_medicion, foto_path, mensaje_texto, estacion_detectada
            FROM mediciones
            WHERE valor_metros IS NULL AND foto_path IS NOT NULL
            ORDER BY id ASC
            LIMIT ?
        """, (limite,))
        pendientes = cur.fetchall()

    logger.info(f"Se encontraron {len(pendientes)} fotos pendientes para reprocesar con IA.")
    if not pendientes:
        print("No hay fotos pendientes.")
        return

    actualizados = 0
    no_detectados = 0

    for idx, row in enumerate(pendientes, 1):
        m_id = row["id"]
        telefono = row["remitente_telefono"]
        nombre_remitente = row["remitente_nombre"] or ""
        timestamp = row["timestamp_medicion"]
        foto_path = row["foto_path"]
        texto = row["mensaje_texto"] or ""
        estacion_actual = row["estacion_detectada"]

        print(f"\n[{idx}/{len(pendientes)}] Procesando Medición #{m_id} - Foto: {foto_path}...")

        if not os.path.exists(foto_path):
            logger.warning(f"Archivo de foto no encontrado en disco: {foto_path}")
            continue

        with open(foto_path, "rb") as f:
            img_bytes = f.read()

        # Determinar estación probable a partir de nombre de archivo o historial de teléfono
        estacion_sugerida = ""
        filename = os.path.basename(foto_path)
        for st in known_stations:
            if st.lower() in filename.lower() or (texto and st.lower() in texto.lower()):
                estacion_sugerida = st
                break

        if not estacion_sugerida:
            with store.get_connection() as conn_sub:
                estacion_sugerida = obtener_estacion_frecuente(conn_sub.cursor(), telefono)

        mime = "image/jpeg"
        if img_bytes.startswith(b"\x89PNG"):
            mime = "image/png"
        elif img_bytes.startswith(b"RIFF") and b"WEBP" in img_bytes[:16]:
            mime = "image/webp"

        prompt_context = f"Mensaje de texto original: \"{texto}\"\n"
        if estacion_sugerida:
            prompt_context += f"Estación o puerto habitual del operador: {estacion_sugerida}\n"
        prompt_context += "Estaciones conocidas en la cuenca: " + ", ".join(known_stations[:25])

        result_data = None
        for model in models:
            for intento in range(3):
                try:
                    config = types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1,
                    )
                    resp = client.models.generate_content(
                        model=model,
                        contents=[
                            types.Part.from_bytes(data=img_bytes, mime_type=mime),
                            f"Por favor analiza esta foto de regla limnimétrica/mira hidrométrica fluvial y lee el nivel del agua:\n{prompt_context}"
                        ],
                        config=config
                    )
                    raw_text = (resp.text or "").strip()
                    if raw_text.startswith("```"):
                        import re
                        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                        raw_text = re.sub(r"\s*```$", "", raw_text)
                    result_data = json.loads(raw_text)
                    if isinstance(result_data, list) and result_data:
                        result_data = result_data[0]
                    break
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        logger.warning(f"429 Quota en {model}, reintentando en 10s...")
                        time.sleep(10)
                    elif "503" in err_str or "Overloaded" in err_str:
                        logger.warning(f"503 Servicio ocupado en {model}, reintentando en 5s...")
                        time.sleep(5)
                    else:
                        logger.warning(f"Error con modelo {model}: {e}")
                        break
            if result_data:
                break

        if not result_data:
            logger.error(f"No se pudo obtener respuesta de IA para Medición #{m_id}.")
            continue

        es_valida = result_data.get("es_medicion_valida", False)
        valor_m = result_data.get("valor_metros")
        valor_cm = result_data.get("valor_cm")
        est_detectada = result_data.get("estacion") or estacion_sugerida or estacion_actual
        tendencia = result_data.get("tendencia")
        observacion = result_data.get("lectura_regla_foto") or "Lectura limnimétrica por IA"

        if valor_m is not None:
            try:
                valor_m = float(valor_m)
                if valor_cm is None:
                    valor_cm = round(valor_m * 100, 1)
                else:
                    valor_cm = float(valor_cm)
            except (ValueError, TypeError):
                valor_m = None

        if valor_m is not None:
            # Obtener o resolver id de estación
            estacion_id, st_norm = store.get_or_create_station(
                est_detectada, 
                river=result_data.get("rio")
            )
            
            with store.get_connection() as conn:
                conn.execute("""
                    UPDATE mediciones
                    SET estacion_id = ?,
                        estacion_detectada = ?,
                        valor_original = ?,
                        valor_metros = ?,
                        valor_cm = ?,
                        unidad_detectada = ?,
                        tendencia_rio = coalesce(?, tendencia_rio),
                        origen_dato = 'foto_regla',
                        confianza = ?,
                        observaciones_ia = ?
                    WHERE id = ?
                """, (
                    estacion_id,
                    st_norm or est_detectada,
                    result_data.get("valor_original") or f"{valor_m:.2f}m",
                    valor_m,
                    valor_cm,
                    result_data.get("unidad_detectada") or "m",
                    tendencia,
                    result_data.get("confianza", "alta"),
                    f"Lectura IA: {observacion}",
                    m_id
                ))
                conn.commit()
            print(f"  ✅ Medición #{m_id} actualizada: {st_norm or est_detectada} = {valor_m:.2f} m ({valor_cm:.1f} cm) | {observacion}")
            actualizados += 1
        else:
            # No se detectó regla o escala visible
            with store.get_connection() as conn:
                conn.execute("""
                    UPDATE mediciones
                    SET observaciones_ia = ?
                    WHERE id = ?
                """, (
                    f"Foto inspeccionada por IA: {observacion}",
                    m_id
                ))
                conn.commit()
            print(f"  ℹ️ Medición #{m_id} no contiene lectura clara: {observacion}")
            no_detectados += 1

        time.sleep(delay_seconds)

    print("\n" + "="*50)
    print(f"Proceso finalizado:")
    print(f"  - Actualizados con valor métrico: {actualizados}")
    print(f"  - No detectados / sin regla visible: {no_detectados}")
    print("="*50)

    # Actualizar CSV de exportación
    store.export_to_csv("mediciones_historico.csv")
    print("Exportación actualizada en mediciones_historico.csv")


if __name__ == "__main__":
    reprocesar()
