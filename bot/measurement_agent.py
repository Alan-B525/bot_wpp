import os
import re
import json
import logging
import unicodedata
from typing import Optional, Dict, Any, List, Tuple

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

logger = logging.getLogger("MeasurementAgent")

SPURIOUS_STATION_NAMES = [
    "Desconocida", "Regla Foto", "Estacionado", "Estacionada", "Marin Por Esta",
    "Corrección", "Correccion", "Que Este Era", "Y Este", "Se Mantiene", "Sin Asignar"
]

SPANISH_CHAT_STOPWORDS = {
    # Pronombres, artículos, preposiciones, conjunciones
    "el", "la", "los", "las", "un", "una", "unos", "unas", "al", "del",
    "de", "en", "a", "por", "para", "con", "sin", "sobre", "entre", "hacia", "desde", "hasta",
    "y", "e", "o", "u", "ni", "que", "pero", "sino", "aunque", "como", "si",
    "yo", "tu", "él", "ella", "ello", "nosotros", "vosotros", "ellos", "ellas", "usted", "ustedes",
    "me", "te", "se", "nos", "os", "le", "les", "lo",
    "mi", "mis", "su", "sus", "nuestro", "nuestra", "nuestros", "nuestras",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas", "aquel", "aquella", "aquellos", "aquellas",
    "esto", "eso", "aquello",
    # Verbos comunes en reportes conversacionales
    "es", "son", "era", "eran", "fue", "fueron", "ser", "sido", "siendo",
    "esta", "está", "están", "estan", "estaba", "estaban", "estuvo", "estuvieron", "estar",
    "mantiene", "mantienen", "mantenemos", "mantener", "quedo", "quedó", "queda", "quedan",
    "sube", "subiendo", "subio", "subió", "baja", "bajando", "bajo", "bajó", "baje",
    "crece", "creciendo", "crecio", "creció", "descenso", "estable", "cambio", "cambios",
    "estacionario", "estacionaria", "estacionado", "estacionada", "estac",
    "comunico", "comunicarle", "comunicar", "informo", "informar", "informe",
    "aviso", "avisar", "paso", "pasó", "pasar", "reporto", "reportar", "reporte",
    "toca", "dio", "diole", "da", "llega", "llego", "llegó",
    "saludos", "saludo", "gracias", "favor", "porfavor", "por favor",
    # Saludos y fórmulas de cortesía
    "buen", "bueno", "buenos", "buena", "buenas", "dia", "dias", "día", "días",
    "tarde", "tardes", "noche", "noches", "hola", "estimado", "estimados", "estimada",
    "señor", "señores", "senor", "senores", "don", "doña", "dona",
    "amigo", "amigos", "colega", "colegas", "camarada", "jefe", "grupo", "central",
    # Rangos y palabras militares / prefectura y nombres de operadores habituales
    "so", "so1", "so2", "so3", "cabo", "sargento", "oficial", "guardia", "prefecto",
    "marinero", "comandante", "teniente", "capitan", "capitán", "mayor", "coronel", "general",
    "suboficial", "2a", "2ª", "1a", "1ª", "3a", "3ª",
    "fabio", "marin", "marín", "diarte", "salomon", "salomón", "dominguez", "domínguez", "sanchez", "sánchez", "acosta",
    # Palabras técnicas que no son estaciones
    "nivel", "altura", "cota", "escala", "regla", "mira", "marca", "marcado",
    "rio", "río", "hidrografia", "hidrometro", "hidrómetro", "hidrometrica", "hidrométrica",
    "costa", "orilla", "banco", "margen", "aguas", "agua",
    "variacion", "variación", "lectura", "medicion", "medición", "dato", "datos",
    "correccion", "corrección", "error", "actualizacion", "actualización",
    # Tiempo
    "hoy", "ayer", "mañana", "manana", "hora", "horas", "hs", "hrs", "min", "minutos",
    "fecha", "tiempo", "momento", "ahora", "actual",
    # Unidades y números
    "m", "cm", "mts", "metros", "centimetros", "centímetros", "milimetros", "milímetros",
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
    # Verbos adicionales y modales
    "queria", "quería", "quisiera", "quise", "comunicarle", "comunicar", "comunico", "comunicó",
}


def _strip_accents(s: str) -> str:
    norm = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


NORMALIZED_SPANISH_CHAT_STOPWORDS = {_strip_accents(w) for w in SPANISH_CHAT_STOPWORDS}
SPURIOUS_WORDS_SET = {_strip_accents(s) for s in SPURIOUS_STATION_NAMES}


SYSTEM_PROMPT = """Eres un experto hidrólogo y especialista en lectura de escalas limnimétricas (miras hidrométricas fluviales) de la cuenca del Plata (ríos Paraguay, Paraná, Iguazú, Pilcomayo).
Tu tarea es analizar mensajes de texto y/o fotografías de operadores fluviales que reportan el nivel del agua de una estación o puerto.

INSTRUCCIONES CLAVE:
1. Identifica si el mensaje contiene un reporte de nivel de agua de un río.
2. Si hay imagen:
   - Determina si es una fotografía de una mira/regla limnimétrica graduada (escala métrica o centimétrica en el agua).
   - Lee con precisión el nivel donde la superficie del agua corta la escala.
   - Inspecciona también marcas de agua o sellos de texto (por ejemplo marcas de apps de geolocalización tipo GPS Map Camera con nombre de estación, fecha y hora).
3. Si hay texto:
   - Extrae el nombre de la estación/puerto, el valor numérico y la tendencia del río.
4. Normalización de unidades:
   - En hidrometría sudamericana, las lecturas suelen darse en metros o centímetros.
   - Si el valor tiene punto o coma decimal (ej. 2,45 o 2.45 o 0.85), la unidad es metros (valor_metros: 2.45, valor_cm: 245.0).
   - Si el valor es un número entero >= 20 sin decimales (ej. 185 o 245 o 320), típicamente son centímetros (valor_metros: 2.45, valor_cm: 245.0).
   - Si es un número entero pequeño (< 15) como 2 o 3 y el contexto habla de metros, interprete 2.0 m / 200 cm.
   - Los valores negativos pueden existir en estiaje o bajante extrema (ej. -0.20 m).
5. Tendencia del río:
   - "CRECE" si indica subida, crece, +, o flecha arriba.
   - "BAJA" si indica bajada, descenso, -, o flecha abajo.
   - "ESTACIONARIO" si indica sin cambios, estacionario, =.
   - null si no se menciona ni se infiere.
6. Origen del dato:
   - "texto" si sólo provino del texto.
   - "foto_regla" si provino principalmente de la lectura de la foto.
   - "ambos" si el texto y la foto coinciden o se complementan.

Debes responder ÚNICAMENTE con un objeto JSON válido (o una lista JSON de objetos si el mensaje contiene mediciones de varias estaciones distintas) con la siguiente estructura:
{
  "es_medicion_valida": true,
  "estacion": "Nombre de la estación (ej: Pilar, Ayolas)",
  "rio": "Río Paraguay | Río Paraná | Río Iguazú | etc",
  "valor_original": "Texto o lectura exacta (ej: 3.45m)",
  "valor_metros": 3.45,
  "valor_cm": 345.0,
  "unidad_detectada": "m | cm",
  "tendencia": "CRECE | BAJA | ESTACIONARIO | null",
  "origen": "texto | foto_regla | ambos",
  "confianza": "alta | media | baja",
  "lectura_regla_foto": "Breve explicación de la lectura observada en la foto o texto"
}
Si el mensaje reporta múltiples estaciones (ej: lista de puertos), responde con una lista JSON de objetos: `[ {...}, {...} ]`.

Si el mensaje no contiene ninguna información de medición limnimétrica o nivel de río, responde:
{
  "es_medicion_valida": false,
  "estacion": null,
  "rio": null,
  "valor_original": null,
  "valor_metros": null,
  "valor_cm": null,
  "unidad_detectada": null,
  "tendencia": null,
  "origen": null,
  "confianza": "baja",
  "lectura_regla_foto": "No se detectó reporte limnimétrico"
}
"""


class MeasurementAgent:
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-3.6-flash", store: Optional[Any] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model_name
        self.store = store
        self.client = None
        self.quota_exhausted = False
        self.fallback_models = [self.model_name, "gemini-3.5-flash-lite", "gemini-3.5-flash"]

        if GENAI_AVAILABLE and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"No se pudo inicializar cliente de Gemini: {e}")
                self.client = None

    def is_ai_available(self) -> bool:
        """Indica si el cliente de IA de Gemini está configurado y listo."""
        return self.client is not None and not self.quota_exhausted

    def process_message(
        self,
        text: Optional[str] = "",
        image_bytes: Optional[bytes] = None,
        known_stations: Optional[List[str]] = None,
        sender_info: Optional[Dict[str, Any]] = None,
        store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Procesa el mensaje (texto y/o foto). Si el cliente de IA está disponible,
        usa Gemini Flash con respaldo multimodal. Si falla o no está disponible, utiliza el motor heurístico regex.
        Aplica inferencia de operador-estación cuando la estación no está explícita en el texto.
        """
        text = (text or "").strip()
        effective_store = store or getattr(self, "store", None)

        if not known_stations and effective_store and hasattr(effective_store, "get_all_stations"):
            try:
                known_stations = [st["nombre"] for st in effective_store.get_all_stations()]
            except Exception:
                pass

        result = None

        # Si tenemos cliente IA, intentamos con Gemini
        if self.is_ai_available() and (text or image_bytes):
            try:
                ai_result = self._call_gemini(text=text, image_bytes=image_bytes, known_stations=known_stations)
                if ai_result and ai_result.get("es_medicion_valida"):
                    result = ai_result
                elif ai_result and not ai_result.get("es_medicion_valida"):
                    # Si la IA determinó que no es válida pero hay texto, intentamos fallback por si acaso
                    fallback = self.fallback_parse(text=text, known_stations=known_stations)
                    if fallback.get("es_medicion_valida"):
                        result = fallback
                    else:
                        result = ai_result
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "Quota exceeded" in err_msg:
                    if not self.quota_exhausted:
                        self.quota_exhausted = True
                        print("⚠️ Cuota de Gemini agotada temporalmente (429). Continuando con motor heurístico de alta velocidad.")
                else:
                    logger.error(f"Error llamando a Gemini API: {e}. Usando fallback heurístico.")

        # Fallback heurístico si no hay resultado de Gemini
        if result is None:
            result = self.fallback_parse(text=text, image_bytes=image_bytes, known_stations=known_stations)

        # Aplicar inferencia de operador-estación
        result = self._apply_operator_inference(result, sender_info=sender_info, store=effective_store)
        return result

    def _apply_operator_inference(
        self,
        res: Dict[str, Any],
        sender_info: Optional[Dict[str, Any]] = None,
        store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Aplica las reglas de inferencia operador-estación:
        - Si la estación está explícita en el texto -> prioridad al texto explícito (metodo_asignacion = 'explicito').
        - Si la estación NO está explícita:
            - Consulta store.infer_operator_station(phone)
            - Si retorna estación consistente -> asigna esa estación (metodo_asignacion = 'inferido_operador').
            - Si el operador es multi-estación o desconocido -> no adivina a ciegas (estacion = None, metodo_asignacion = 'desconocido').
        """
        if not isinstance(res, dict):
            return res

        res["nivel"] = res.get("valor_metros")
        current_station = res.get("estacion")

        is_spurious = (
            not current_station or
            current_station in SPURIOUS_STATION_NAMES or
            current_station.lower() in {s.lower() for s in SPURIOUS_STATION_NAMES}
        )

        phone = None
        if sender_info:
            phone = sender_info.get("phone") or sender_info.get("remitente_telefono")

        if not is_spurious:
            # Estación explícita válida en el texto: prioridad absoluta sobre historial
            res["metodo_asignacion"] = "explicito"
            res["inferred_station"] = None
            return res

        # No hay estación explícita válida: inferencia por historial del operador
        effective_store = store or getattr(self, "store", None)
        inferred_station_name = None

        if effective_store and phone:
            try:
                inferred_id = effective_store.infer_operator_station(phone)
                if inferred_id:
                    if hasattr(effective_store, "get_station_by_id"):
                        st_obj = effective_store.get_station_by_id(inferred_id)
                        if st_obj:
                            inferred_station_name = st_obj.get("nombre")
                    if not inferred_station_name:
                        with effective_store.get_connection() as conn:
                            row = conn.cursor().execute("SELECT nombre FROM estaciones WHERE id = ?", (int(inferred_id),)).fetchone()
                            if row:
                                inferred_station_name = row[0]
            except Exception as e:
                logger.warning(f"Error inferiendo estación para operador {phone}: {e}")

        if inferred_station_name:
            res["estacion"] = inferred_station_name
            res["inferred_station"] = inferred_station_name
            res["metodo_asignacion"] = "inferido_operador"
            res["confianza"] = "media_alta"
        else:
            # Operador multi-estación o desconocido: NO adivinar a ciegas
            res["estacion"] = None
            res["inferred_station"] = None
            res["metodo_asignacion"] = "desconocido"

        return res

    def parse_message(
        self,
        texto: str,
        remitente_telefono: Optional[str] = None,
        remitente_nombre: Optional[str] = None,
        store: Optional[Any] = None,
        image_bytes: Optional[bytes] = None,
        known_stations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Analiza un mensaje hidrométrico, extrayendo nivel, tendencia y estación.
        Aplica inferencia de operador-estación si la estación no está explícitamente en el texto.
        """
        sender_info = {}
        if remitente_telefono:
            sender_info["phone"] = remitente_telefono
        if remitente_nombre:
            sender_info["name"] = remitente_nombre

        return self.process_message(
            text=texto,
            image_bytes=image_bytes,
            known_stations=known_stations,
            sender_info=sender_info if sender_info else None,
            store=store,
        )

    def _call_gemini(
        self,
        text: str,
        image_bytes: Optional[bytes] = None,
        known_stations: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Invoca la API de Gemini con imagen y texto probando modelos en cascada."""
        prompt_parts = []

        context_stations = ""
        if known_stations:
            sample_st = ", ".join(known_stations[:25])
            context_stations = f"\nCatálogo de estaciones conocidas de referencia:\n{sample_st}\n"

        user_content = f"Mensaje recibido del operador:\n\"{text}\"\n{context_stations}"

        if image_bytes:
            mime = "image/jpeg"
            if image_bytes.startswith(b"\x89PNG"):
                mime = "image/png"
            elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
                mime = "image/webp"
            elif image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
                mime = "image/gif"
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime)
            prompt_parts.append(image_part)

        prompt_parts.append(user_content)

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.1,
        )

        last_err = None
        for mod in self.fallback_models:
            try:
                response = self.client.models.generate_content(
                    model=mod,
                    contents=prompt_parts,
                    config=config,
                )
                raw_text = response.text or ""
                clean_json = raw_text.strip()
                if clean_json.startswith("```"):
                    clean_json = re.sub(r"^```(?:json)?\s*", "", clean_json)
                    clean_json = re.sub(r"\s*```$", "", clean_json)

                data = json.loads(clean_json)
                return self._sanitize_result(data, has_image=bool(image_bytes), has_text=bool(text))
            except Exception as e:
                last_err = e
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "Overloaded" in err_str:
                    logger.warning(f"Modelo {mod} en alta demanda (503). Intentando modelo alternativo...")
                    continue
                elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    raise e
                else:
                    logger.warning(f"Error con {mod}: {e}. Probando siguiente modelo...")
                    continue

        if last_err:
            raise last_err
        return None

    def _sanitize_single(self, item: Dict[str, Any], has_image: bool, has_text: bool) -> Dict[str, Any]:
        """Sanitiza una medición individual."""
        if not isinstance(item, dict):
            return {"es_medicion_valida": False, "confianza": "baja"}

        is_valid = bool(item.get("es_medicion_valida", False))
        if not is_valid:
            return item

        valor_m = item.get("valor_metros")
        valor_cm = item.get("valor_cm")

        # Conversiones seguras a float
        try:
            if valor_m is not None:
                valor_m = float(valor_m)
            if valor_cm is not None:
                valor_cm = float(valor_cm)
        except (ValueError, TypeError):
            pass

        if valor_m is not None and valor_cm is None:
            valor_cm = round(valor_m * 100.0, 2)
        elif valor_cm is not None and valor_m is None:
            valor_m = round(valor_cm / 100.0, 4)

        item["valor_metros"] = valor_m
        item["valor_cm"] = valor_cm

        # Normalizar tendencia
        tendencia = str(item.get("tendencia") or "").upper().strip()
        if "CREC" in tendencia or "SUB" in tendencia:
            item["tendencia"] = "CRECE"
        elif "BAJ" in tendencia or "DESC" in tendencia:
            item["tendencia"] = "BAJA"
        elif "ESTAC" in tendencia or "IGUAL" in tendencia:
            item["tendencia"] = "ESTACIONARIO"
        else:
            item["tendencia"] = None

        # Determinar origen si no vino o es ambiguo
        if not item.get("origen"):
            if has_image and has_text:
                item["origen"] = "ambos"
            elif has_image:
                item["origen"] = "foto_regla"
            else:
                item["origen"] = "texto"

        return item

    def _sanitize_result(self, data: Any, has_image: bool, has_text: bool) -> Dict[str, Any]:
        """Asegura consistencia numérica y formato en la respuesta del agente (dict o list)."""
        if isinstance(data, list):
            sanitized_list = []
            for elem in data:
                if isinstance(elem, dict):
                    # Si no vino es_medicion_valida explícito pero tiene estacion y valor
                    if "es_medicion_valida" not in elem:
                        if elem.get("estacion") or elem.get("valor_metros") is not None:
                            elem["es_medicion_valida"] = True
                    s = self._sanitize_single(elem, has_image, has_text)
                    if s.get("es_medicion_valida"):
                        sanitized_list.append(s)

            if not sanitized_list:
                return {"es_medicion_valida": False, "confianza": "baja", "mediciones": []}

            # Retornar el primer elemento como base y adjuntar la lista completa en 'mediciones'
            res = dict(sanitized_list[0])
            res["mediciones"] = sanitized_list
            return res

        elif isinstance(data, dict):
            res = self._sanitize_single(data, has_image, has_text)
            if res.get("es_medicion_valida"):
                res["mediciones"] = [dict(res)]
            return res

        return {"es_medicion_valida": False, "confianza": "baja", "mediciones": []}

    def fallback_parse(
        self,
        text: str,
        image_bytes: Optional[bytes] = None,
        known_stations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Parser heurístico basado en expresiones regulares para cuando no se dispone
        de conexión con Gemini o no hay API key configurada.
        """
        raw_text = (text or "").strip()
        if not raw_text:
            if image_bytes:
                return {
                    "es_medicion_valida": True,
                    "estacion": None,
                    "rio": None,
                    "valor_original": "Foto sin texto",
                    "valor_metros": None,
                    "valor_cm": None,
                    "unidad_detectada": "indeterminada",
                    "tendencia": None,
                    "origen": "foto_regla",
                    "confianza": "baja",
                    "lectura_regla_foto": "Se recibió foto de escala pero no hay IA disponible para leerla",
                }
            return {
                "es_medicion_valida": False,
                "estacion": None,
                "confianza": "baja",
                "lectura_regla_foto": "Texto vacío y sin imagen",
            }

        # 1. Detectar tendencia
        tendencia = None
        lower_text = raw_text.lower()
        if re.search(r"\b(crece|creciendo|sube|subiendo|\+)\b", lower_text):
            tendencia = "CRECE"
        elif re.search(r"\b(baja|bajando|descenso|baje|-)\b", lower_text):
            tendencia = "BAJA"
        elif re.search(r"\b(estacionario|estacionado|estacionada|estac|estacionaria|=|sin cambios|estable)\b", lower_text):
            tendencia = "ESTACIONARIO"

        # 2. Limpiar texto de fechas, horas, marcas de WhatsApp y teléfonos
        raw_text = re.sub(r"<[^>]+>", " ", raw_text)
        # Normalizar espacios antes o después de comas en números (ej. '4, 18' -> '4,18')
        raw_text = re.sub(r"(\d+)\s*,\s*(\d+)", r"\1,\2", raw_text)
        text_for_numbers = raw_text

        # Quitar teléfonos tipo +595984123456 o 0981123456
        text_for_numbers = re.sub(r"(?:\b|\+)\d{7,15}\b", " ", text_for_numbers)

        # Quitar fechas completas con / o - (ej. 15/10/2023 o 15/10 o 15-10-2023)
        text_for_numbers = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", text_for_numbers)
        # Quitar fechas con 3 partes con puntos (ej. 15.10.2023)
        text_for_numbers = re.sub(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b", " ", text_for_numbers)

        # Quitar horas hh:mm o hh:mm:ss
        text_for_numbers = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:hs|hrs|horas|am|pm|a\.m\.|p\.m\.))?\b", " ", text_for_numbers, flags=re.IGNORECASE)

        # Quitar horas con puntos solo si tienen indicador de hora (ej. 08.30 hs o a las 08.30)
        text_for_numbers = re.sub(r"\b(?:[01]?\d|2[0-3])\.[0-5]\d\s*(?:hs|hrs|horas|am|pm|a\.m\.|p\.m\.)\b", " ", text_for_numbers, flags=re.IGNORECASE)

        # Quitar referencias de hora aisladas tipo "8hs", "8 hrs", "8 horas"
        text_for_numbers = re.sub(r"\b\d{1,2}\s*(?:hs|hrs|horas)\b", " ", text_for_numbers, flags=re.IGNORECASE)

        # 3. Detectar estación en catálogo conocido si se proveyó
        detected_station = None

        def _strip_accents(s: str) -> str:
            norm = unicodedata.normalize("NFKD", str(s or ""))
            return "".join(c for c in norm if not unicodedata.combining(c)).lower()

        lower_no_acc = _strip_accents(raw_text)

        stations_to_check = known_stations
        if not stations_to_check and hasattr(self, "store") and self.store and hasattr(self.store, "get_all_stations"):
            try:
                stations_to_check = [st["nombre"] for st in self.store.get_all_stations()]
            except Exception:
                stations_to_check = None

        if stations_to_check:
            # Ordenar por longitud descendente para que nombres más específicos coincidan primero
            filtered_stations = [st for st in stations_to_check if st not in SPURIOUS_STATION_NAMES]
            sorted_stations = sorted(filtered_stations, key=len, reverse=True)
            for st in sorted_stations:
                st_no_acc = _strip_accents(st)
                st_clean = re.sub(r"[^\w\s]", "", st_no_acc).strip()
                if st_clean and re.search(rf"\b{re.escape(st_clean)}\b", lower_no_acc):
                    detected_station = st
                    break

        # 4. Detectar valor numérico y unidad
        # Prioridad 1: Número con unidad explícita (m, mts, metros, cm, centimetros)
        num_match = re.search(r"(-?\d+(?:[\.,]\d+)?)\s*(m|mts|metros|cm|centimetros)\b", text_for_numbers, re.IGNORECASE)

        # Prioridad 2: Número con separador decimal (ej. 2,45 o 2.45)
        if not num_match:
            num_match = re.search(r"(-?\d+[\.,]\d+)\b", text_for_numbers)

        # Prioridad 3: Número entero tras palabras clave limnimétricas (nivel, altura, escala, regla, etc.)
        if not num_match:
            num_match = re.search(r"(?:nivel|altura|cota|escala|regla)\s*[:=]?\s*(-?\d+)\b", text_for_numbers, re.IGNORECASE)

        # Prioridad 4: Cualquier entero restante sólo si ya detectamos estación o tendencia
        if not num_match and (detected_station or tendencia):
            num_match = re.search(r"\b(-?\d+)\b", text_for_numbers)

        # 5. Detectar estación fuera de catálogo buscando antes o después del número
        if not detected_station and num_match:
            num_str = num_match.group(0).strip()
            num_idx = raw_text.find(num_str)
            if num_idx > 0:
                text_before = raw_text[:num_idx].strip().rstrip(":=; -")
                # Limpiar referencias de hora y fecha previas
                text_before = re.sub(r"\b\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s*(?:hs|hrs|horas))?\b", " ", text_before, flags=re.IGNORECASE)
                text_before = re.sub(r"\b\d{1,2}\s*(?:hs|hrs|horas)\b", " ", text_before, flags=re.IGNORECASE)
                text_before = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", text_before)
                # Limpiar saludos y fórmulas de cortesía al inicio
                cand = re.sub(r"^(?:buen(?:os)?\s*(?:dias?|tardes?|noches?)|hola|estimados?|grupo)\s*,?\s*", "", text_before, flags=re.IGNORECASE).strip()
                cand = re.sub(r"^(?:grupo)\s+", "", cand, flags=re.IGNORECASE).strip()
                cand = re.sub(r"^(?:escala\s+hidrom[eé]trica|escala|regla|mira)\s+", "", cand, flags=re.IGNORECASE).strip()

                # Si viene con patrón "en Estacion", "de Estacion" o "puerto Estacion"
                m_pref = re.search(r"\b(?:en|de|puerto|pto\.?)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)$", cand, re.IGNORECASE)
                if m_pref:
                    target_cand = m_pref.group(1).strip()
                    if re.search(r"\b(?:puerto|pto\.?)\s+", cand, re.IGNORECASE):
                        target_cand = "Puerto " + target_cand
                else:
                    target_cand = cand

                # Limpiar puntuación
                target_cand_clean = re.sub(r"[^\w\s]", " ", target_cand)
                raw_words = target_cand_clean.split()

                words = []
                for w in raw_words:
                    wnorm = _strip_accents(w)
                    if any(char.isdigit() for char in wnorm):
                        continue
                    if wnorm in NORMALIZED_SPANISH_CHAT_STOPWORDS and wnorm not in ("puerto", "pto", "villa", "paso", "isla", "san", "santa"):
                        continue
                    words.append(w)

                if words:
                    sub_words = words[-3:]
                    # Debe contener al menos una palabra de longitud >= 4 que no sea stopword
                    has_substantive = any(
                        len(w) >= 4 and _strip_accents(w) not in NORMALIZED_SPANISH_CHAT_STOPWORDS
                        for w in sub_words
                    )
                    all_stop = all(_strip_accents(w) in NORMALIZED_SPANISH_CHAT_STOPWORDS for w in sub_words)
                    if has_substantive and not all_stop:
                        cand_name = " ".join(sub_words).title()
                        if _strip_accents(cand_name) not in SPURIOUS_WORDS_SET:
                            detected_station = cand_name

            # No extraer palabras arbitrarias de text_after salvo prefijo explícito de lugar
            if not detected_station and num_idx >= 0:
                text_after = raw_text[num_idx + len(num_str):].strip().lstrip(":=; -")
                m_after = re.search(r"^(?:en|de|puerto|pto\.?)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)", text_after, re.IGNORECASE)
                if m_after:
                    cand_after = re.sub(r"[^\w\s]", " ", m_after.group(1)).strip()
                    words_after = [
                        w for w in cand_after.split()
                        if _strip_accents(w) not in NORMALIZED_SPANISH_CHAT_STOPWORDS and not _strip_accents(w).isdigit()
                    ]
                    if words_after and any(len(w) >= 4 for w in words_after[:2]):
                        cand_name = " ".join(words_after[:2]).title()
                        if _strip_accents(cand_name) not in SPURIOUS_WORDS_SET:
                            detected_station = cand_name

        # Validar que si detected_station existe, no sea espuria y tenga al menos 3 letras
        if detected_station:
            if detected_station in SPURIOUS_STATION_NAMES or _strip_accents(detected_station) in SPURIOUS_WORDS_SET:
                detected_station = None
            elif not re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{3,}", detected_station):
                detected_station = None

        if not num_match:
            if image_bytes:
                return {
                    "es_medicion_valida": True,
                    "estacion": detected_station or None,
                    "rio": None,
                    "valor_original": "Foto de escala",
                    "valor_metros": None,
                    "valor_cm": None,
                    "unidad_detectada": "indeterminada",
                    "tendencia": tendencia,
                    "origen": "foto_regla",
                    "confianza": "baja",
                    "lectura_regla_foto": "Se recibió foto pero no hay IA disponible para leer el número",
                }
            return {
                "es_medicion_valida": False,
                "estacion": detected_station or None,
                "confianza": "baja",
                "lectura_regla_foto": "No se encontraron valores limnimétricos válidos",
            }

        val_str = num_match.group(1).replace(",", ".")
        raw_val = num_match.group(1)
        unit_str = (num_match.group(2) if len(num_match.groups()) > 1 else "") or ""
        unit_str = unit_str.lower()

        try:
            num = float(val_str)
        except ValueError:
            return {
                "es_medicion_valida": False,
                "estacion": detected_station or None,
                "confianza": "baja",
                "lectura_regla_foto": "Error al convertir valor numérico",
            }

        # Deducción de metros vs centímetros
        if unit_str in ("cm", "centimetros"):
            if ("." in val_str or "," in raw_val) and abs(num) < 15.0:
                valor_m = num
                valor_cm = round(num * 100.0, 2)
                unidad = "m"
            else:
                valor_cm = num
                valor_m = round(num / 100.0, 4)
                unidad = "cm"
        elif unit_str in ("m", "mts", "metros"):
            valor_m = num
            valor_cm = round(num * 100.0, 2)
            unidad = "m"
        else:
            # Sin unidad explícita:
            # Si tiene decimales o es menor a 20: son metros
            if ("." in val_str or "," in raw_val) or abs(num) < 15.0:
                valor_m = num
                valor_cm = round(num * 100.0, 2)
                unidad = "m"
            else:
                valor_cm = num
                valor_m = round(num / 100.0, 4)
                unidad = "cm"

        # Validación de rango físico plausible en hidrometría (-10m a 35m)
        if valor_m < -10.0 or valor_m > 35.0:
            if not image_bytes:
                return {
                    "es_medicion_valida": False,
                    "estacion": detected_station or None,
                    "confianza": "baja",
                    "lectura_regla_foto": f"Valor fuera de rango hidrométrico plausible ({valor_m}m)",
                }

        detected_station = detected_station or None

        origen = "ambos" if (image_bytes and raw_text) else ("foto_regla" if image_bytes else "texto")

        return {
            "es_medicion_valida": True,
            "estacion": detected_station,
            "rio": None,
            "valor_original": raw_val + (f" {unit_str}" if unit_str else ""),
            "valor_metros": valor_m,
            "valor_cm": valor_cm,
            "unidad_detectada": unidad,
            "tendencia": tendencia,
            "origen": origen,
            "confianza": "media" if not image_bytes else "baja",
            "lectura_regla_foto": f"Extraído heurísticamente por regex (valor: {valor_m}m)",
        }
