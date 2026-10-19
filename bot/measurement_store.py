import os
import re
import csv
import json
import sqlite3
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple, Any

DEFAULT_SEED_STATIONS = [
    # Cuenca Río Paraguay
    {"nombre": "Bahía Negra", "rio": "Río Paraguay", "latitud": -20.23, "longitud": -58.17, "alias": ["Bahia Negra", "Pto Bahia Negra", "Puerto Bahia Negra"]},
    {"nombre": "Fuerte Olimpo", "rio": "Río Paraguay", "latitud": -21.04, "longitud": -57.87, "alias": ["Fuerte Olimpo", "Olimpo", "Pto Olimpo", "Pto Fuerte Olimpo"]},
    {"nombre": "Vallemí", "rio": "Río Paraguay", "latitud": -22.16, "longitud": -57.96, "alias": ["Vallemi", "Pto Vallemi", "Puerto Vallemi"]},
    {"nombre": "Concepción", "rio": "Río Paraguay", "latitud": -23.40, "longitud": -57.43, "alias": ["Concepcion", "Pto Concepcion", "Puerto Concepcion", "Pto. Concepcion"]},
    {"nombre": "Rosario", "rio": "Río Paraguay", "latitud": -24.44, "longitud": -57.09, "alias": ["Puerto Rosario", "Pto Rosario", "Pto. Rosario"]},
    {"nombre": "Antequera", "rio": "Río Paraguay", "latitud": -24.13, "longitud": -57.21, "alias": ["Pto Antequera", "Puerto Antequera"]},
    {"nombre": "Asunción", "rio": "Río Paraguay", "latitud": -25.28, "longitud": -57.64, "alias": ["Asuncion", "Pto Asuncion", "Puerto Asuncion", "Pto. Asuncion"]},
    {"nombre": "Villeta", "rio": "Río Paraguay", "latitud": -25.51, "longitud": -57.56, "alias": ["Pto Villeta", "Puerto Villeta"]},
    {"nombre": "Alberdi", "rio": "Río Paraguay", "latitud": -26.19, "longitud": -58.14, "alias": ["Pto Alberdi", "Puerto Alberdi", "Pto. Alberdi"]},
    {"nombre": "Pilar", "rio": "Río Paraguay", "latitud": -26.86, "longitud": -58.30, "alias": ["Pto Pilar", "Puerto Pilar", "Pto. Pilar", "Prefectura Pilar"]},
    {"nombre": "Humaitá", "rio": "Río Paraguay", "latitud": -27.05, "longitud": -58.55, "alias": ["Humaita", "Pto Humaita", "Puerto Humaita", "Pto. Humaita"]},
    {"nombre": "Carmelo Peralta", "rio": "Río Paraguay", "latitud": -21.69, "longitud": -57.90, "alias": ["Peralta", "Pto Carmelo Peralta"]},
    
    # Cuenca Río Paraná (Paraguay / Argentina)
    {"nombre": "Salto del Guairá", "rio": "Río Paraná", "latitud": -24.06, "longitud": -54.31, "alias": ["Salto del Guaira", "Pto Salto del Guaira"]},
    {"nombre": "Ciudad del Este", "rio": "Río Paraná", "latitud": -25.51, "longitud": -54.61, "alias": ["CDE", "Ciudad del Este", "Pto Pte Franco", "Presidente Franco"]},
    {"nombre": "Encarnación", "rio": "Río Paraná", "latitud": -27.33, "longitud": -55.87, "alias": ["Encarnacion", "Pto Encarnacion", "Puerto Encarnacion"]},
    {"nombre": "San Cosme y Damián", "rio": "Río Paraná", "latitud": -27.32, "longitud": -56.33, "alias": ["San Cosme", "San Cosme y Damian"]},
    {"nombre": "Ayolas", "rio": "Río Paraná", "latitud": -27.40, "longitud": -56.90, "alias": ["Pto Ayolas", "Puerto Ayolas", "Pto. Ayolas", "Ayolas Yacyreta"]},
    {"nombre": "Coratei", "rio": "Río Paraná", "latitud": -27.42, "longitud": -57.02, "alias": ["Puerto Coratei", "Pto Coratei", "Corateí", "Coratei", "Pto. Coratei"]},
    {"nombre": "PZA", "rio": "Río Paraná", "latitud": -27.40, "longitud": -56.90, "alias": ["Prefectura Zona Ayolas", "Prefectura Ayolas", "PZA", "Zona Ayolas"]},
    {"nombre": "Yabebyry", "rio": "Río Paraná", "latitud": -27.39, "longitud": -57.14, "alias": ["Yabebiry", "Pto Yabebyry"]},
    {"nombre": "Panchito López", "rio": "Río Paraná", "latitud": -27.50, "longitud": -57.30, "alias": ["Panchito Lopez", "Pto Panchito Lopez", "Pto. Panchito Lopez", "Panchito"]},
    {"nombre": "Cerrito", "rio": "Río Paraná", "latitud": -27.43, "longitud": -57.73, "alias": ["Pto Cerrito", "Puerto Cerrito"]},
    {"nombre": "Itá Pirú", "rio": "Río Paraná", "latitud": -27.40, "longitud": -58.05, "alias": ["Ita Piru", "Pto Ita Piru"]},
    {"nombre": "Puerto Triunfo", "rio": "Río Paraná", "latitud": -26.54, "longitud": -54.76, "alias": ["Pto Triunfo"]},
    {"nombre": "Campichuelo", "rio": "Río Paraná", "latitud": -27.18, "longitud": -55.62, "alias": ["Pto Campichuelo"]},
    {"nombre": "Bella Vista", "rio": "Río Paraná", "latitud": -27.05, "longitud": -55.57, "alias": ["Pto Bella Vista", "Puerto Bella Vista"]},

    # Estaciones cuenca compartida / principales Argentina
    {"nombre": "Puerto Iguazú", "rio": "Río Iguazú", "latitud": -25.60, "longitud": -54.57, "alias": ["Iguazu", "Puerto Iguazu", "Pto Iguazu"]},
    {"nombre": "Posadas", "rio": "Río Paraná", "latitud": -27.36, "longitud": -55.90, "alias": ["Pto Posadas", "Puerto Posadas"]},
    {"nombre": "Ituzaingó", "rio": "Río Paraná", "latitud": -27.50, "longitud": -56.68, "alias": ["Ituzaingo", "Pto Ituzaingo", "Puerto Ituzaingo"]},
    {"nombre": "Itá Ibaté", "rio": "Río Paraná", "latitud": -27.42, "longitud": -57.33, "alias": ["Ita Ibate", "Pto Ita Ibate"]},
    {"nombre": "Itatí", "rio": "Río Paraná", "latitud": -27.27, "longitud": -58.24, "alias": ["Itati", "Pto Itati"]},
    {"nombre": "Paso de la Patria", "rio": "Río Paraná", "latitud": -27.32, "longitud": -58.57, "alias": ["Paso Patria", "Paso de la Patria"]},
    {"nombre": "Corrientes", "rio": "Río Paraná", "latitud": -27.47, "longitud": -58.83, "alias": ["Pto Corrientes", "Puerto Corrientes"]},
    {"nombre": "Barranqueras", "rio": "Río Paraná", "latitud": -27.48, "longitud": -58.93, "alias": ["Pto Barranqueras", "Barranqueras"]},
    {"nombre": "Formosa", "rio": "Río Paraguay", "latitud": -26.18, "longitud": -58.18, "alias": ["Pto Formosa", "Puerto Formosa"]},
    {"nombre": "Pilcomayo", "rio": "Río Pilcomayo", "latitud": -25.35, "longitud": -57.69, "alias": ["Puerto Pilcomayo", "Pto Pilcomayo"]},
    {"nombre": "Goya", "rio": "Río Paraná", "latitud": -29.14, "longitud": -59.26, "alias": ["Pto Goya", "Puerto Goya"]},
    {"nombre": "Reconquista", "rio": "Río Paraná", "latitud": -29.15, "longitud": -59.65, "alias": ["Pto Reconquista", "Puerto Reconquista"]},
    {"nombre": "Esquina", "rio": "Río Paraná", "latitud": -30.01, "longitud": -59.53, "alias": ["Pto Esquina", "Puerto Esquina"]},
    {"nombre": "La Paz", "rio": "Río Paraná", "latitud": -30.74, "longitud": -59.64, "alias": ["Pto La Paz", "Puerto La Paz"]},
    {"nombre": "Santa Fe", "rio": "Río Paraná", "latitud": -31.64, "longitud": -60.71, "alias": ["Pto Santa Fe", "Puerto Santa Fe"]},
    {"nombre": "Paraná", "rio": "Río Paraná", "latitud": -31.73, "longitud": -60.53, "alias": ["Pto Parana", "Puerto Parana"]},
    {"nombre": "Rosario (Arg)", "rio": "Río Paraná", "latitud": -32.95, "longitud": -60.64, "alias": ["Puerto Rosario Arg", "Rosario Argentina", "Pto Rosario Santa Fe"]},
]

SPURIOUS_STATION_NAMES = [
    "Desconocida", "Regla Foto", "Estacionado", "Marin Por Esta",
    "Corrección", "Que Este Era", "Y Este", "Se Mantiene"
]


def normalize_text_for_comparison(text: str) -> str:
    """
    Normaliza un texto para comparaciones difusas:
    - Quita tildes/acentos
    - Convierte a minúsculas
    - Remueve prefijos comunes de hidrometría (puerto, pto, estacion, escala)
    - Remueve signos de puntuación y espacios extras
    """
    if not text:
        return ""
    # Quitar diacríticos
    normalized = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    cleaned = without_accents.lower().strip()
    
    # Quitar prefijos comunes
    prefixes = [
        r"^puerto\s+",
        r"^pto\.?\s+",
        r"^estacion\s+",
        r"^est\.?\s+",
        r"^escala\s+",
        r"^regla\s+",
        r"^rio\s+",
        r"^río\s+",
        r"^prefectura\s+",
    ]
    for p in prefixes:
        cleaned = re.sub(p, "", cleaned)

    # Reemplazar símbolos no alfanuméricos por espacios
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def compute_string_similarity(s1: str, s2: str) -> float:
    """Calcula la similitud entre dos cadenas usando SequenceMatcher (0.0 a 1.0)."""
    n1 = normalize_text_for_comparison(s1)
    n2 = normalize_text_for_comparison(s2)
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0
    # Si una está contenida en la otra como subconjunto significativo
    words1 = set(n1.split())
    words2 = set(n2.split())
    if words1 and words2:
        common = words1.intersection(words2)
        # Exigir que todas las palabras de la intersección tengan longitud >= 4
        # y que la intersección cubra al menos el 80% de las palabras de ambos conjuntos
        if common and all(len(w) >= 4 for w in common):
            coverage = len(common) / max(len(words1), len(words2))
            if coverage >= 0.8:
                return 0.95
    return SequenceMatcher(None, n1, n2).ratio()


class MeasurementStore:
    def __init__(self, db_path: str = "data/mediciones.db", photos_dir: str = "data/fotos"):
        self.db_path = db_path
        self.photos_dir = photos_dir
        
        # Asegurar directorios
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        os.makedirs(os.path.abspath(self.photos_dir), exist_ok=True)
        
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Abre conexión con configuración optimizada y soporte WAL, asegurando el cierre."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        """Crea tablas e índices necesarios si no existen y siembra catálogo base."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabla de estaciones
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS estaciones (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo          TEXT UNIQUE,
                    nombre          TEXT NOT NULL UNIQUE,
                    rio             TEXT,
                    cuenca          TEXT DEFAULT 'Cuenca del Plata',
                    latitud         REAL,
                    longitud        REAL,
                    cero_escala_m   REAL,
                    alias           TEXT,
                    es_activa       INTEGER NOT NULL DEFAULT 1,
                    creado_en       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    actualizado_en  TEXT
                );
            """)

            # Tabla de operadores
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS operadores (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    telefono            TEXT NOT NULL UNIQUE,
                    nombre              TEXT,
                    rol_cargo           TEXT,
                    institucion         TEXT DEFAULT 'Prefectura Naval',
                    estacion_fija_id    INTEGER REFERENCES estaciones(id) ON DELETE SET NULL,
                    confianza_reporte   TEXT DEFAULT 'alta',
                    activo              INTEGER NOT NULL DEFAULT 1,
                    notas               TEXT,
                    creado_en           TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    actualizado_en      TEXT
                );
            """)

            # Tabla de consistencia operador_estaciones
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS operador_estaciones (
                    operador_id         INTEGER NOT NULL REFERENCES operadores(id) ON DELETE CASCADE,
                    estacion_id         INTEGER NOT NULL REFERENCES estaciones(id) ON DELETE CASCADE,
                    total_reportes      INTEGER NOT NULL DEFAULT 0,
                    ultimo_reporte      TEXT,
                    es_consistente      INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (operador_id, estacion_id)
                );
            """)

            # Tabla de mensajes de chat históricos y en vivo
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mensajes_chat (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    operador_id         INTEGER REFERENCES operadores(id) ON DELETE SET NULL,
                    remitente_telefono  TEXT NOT NULL,
                    remitente_nombre    TEXT,
                    timestamp_mensaje   TEXT NOT NULL,
                    texto               TEXT,
                    archivo_adjunto     TEXT,
                    foto_path           TEXT,
                    es_saliente         INTEGER NOT NULL DEFAULT 0,
                    creado_en           TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );
            """)

            # Tabla de adjuntos multimedia
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS adjuntos_multimedia (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    mensaje_id          INTEGER REFERENCES mensajes_chat(id) ON DELETE SET NULL,
                    tipo                TEXT NOT NULL DEFAULT 'imagen',
                    ruta_archivo        TEXT NOT NULL UNIQUE,
                    nombre_original     TEXT,
                    mimetype            TEXT DEFAULT 'image/jpeg',
                    tamano_bytes        INTEGER,
                    hash_sha256         TEXT,
                    timestamp_captura   TEXT,
                    creado_en           TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );
            """)

            # Tabla de mediciones
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mediciones (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    estacion_id         INTEGER REFERENCES estaciones(id),
                    operador_id         INTEGER REFERENCES operadores(id) ON DELETE SET NULL,
                    mensaje_id          INTEGER REFERENCES mensajes_chat(id) ON DELETE SET NULL,
                    adjunto_id          INTEGER REFERENCES adjuntos_multimedia(id) ON DELETE SET NULL,
                    estacion_detectada  TEXT NOT NULL,
                    metodo_asignacion   TEXT NOT NULL DEFAULT 'explicito',
                    valor_original      TEXT,
                    valor_metros        REAL,
                    valor_cm            REAL,
                    unidad_detectada    TEXT,
                    tendencia_rio       TEXT,
                    origen_dato         TEXT,
                    confianza           TEXT DEFAULT 'alta',
                    remitente_telefono  TEXT NOT NULL,
                    remitente_nombre    TEXT,
                    mensaje_texto       TEXT,
                    foto_path           TEXT,
                    timestamp_medicion  TEXT NOT NULL,
                    timestamp_registro  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    observaciones_ia    TEXT,
                    revisado            INTEGER DEFAULT 1
                );
            """)

            # Asegurar columnas si las tablas ya existían en bases previas
            st_cols = [c[1] for c in cursor.execute("PRAGMA table_info(estaciones)").fetchall()]
            if "codigo" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN codigo TEXT")
            if "cuenca" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN cuenca TEXT DEFAULT 'Cuenca del Plata'")
            if "latitud" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN latitud REAL")
            if "longitud" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN longitud REAL")
            if "cero_escala_m" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN cero_escala_m REAL")
            if "alias" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN alias TEXT")
            if "es_activa" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN es_activa INTEGER NOT NULL DEFAULT 1")
            if "actualizado_en" not in st_cols:
                cursor.execute("ALTER TABLE estaciones ADD COLUMN actualizado_en TEXT")

            op_cols = [c[1] for c in cursor.execute("PRAGMA table_info(operadores)").fetchall()]
            if "rol_cargo" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN rol_cargo TEXT")
            if "institucion" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN institucion TEXT DEFAULT 'Prefectura Naval'")
            if "estacion_fija_id" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN estacion_fija_id INTEGER REFERENCES estaciones(id)")
            if "confianza_reporte" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN confianza_reporte TEXT DEFAULT 'alta'")
            if "activo" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
            if "notas" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN notas TEXT")
            if "actualizado_en" not in op_cols:
                cursor.execute("ALTER TABLE operadores ADD COLUMN actualizado_en TEXT")

            chat_cols = [c[1] for c in cursor.execute("PRAGMA table_info(mensajes_chat)").fetchall()]
            if "operador_id" not in chat_cols:
                cursor.execute("ALTER TABLE mensajes_chat ADD COLUMN operador_id INTEGER REFERENCES operadores(id)")
            if "es_saliente" not in chat_cols:
                cursor.execute("ALTER TABLE mensajes_chat ADD COLUMN es_saliente INTEGER NOT NULL DEFAULT 0")

            med_cols = [c[1] for c in cursor.execute("PRAGMA table_info(mediciones)").fetchall()]
            if "operador_id" not in med_cols:
                cursor.execute("ALTER TABLE mediciones ADD COLUMN operador_id INTEGER REFERENCES operadores(id)")
            if "mensaje_id" not in med_cols:
                cursor.execute("ALTER TABLE mediciones ADD COLUMN mensaje_id INTEGER REFERENCES mensajes_chat(id)")
            if "adjunto_id" not in med_cols:
                cursor.execute("ALTER TABLE mediciones ADD COLUMN adjunto_id INTEGER REFERENCES adjuntos_multimedia(id)")
            if "metodo_asignacion" not in med_cols:
                cursor.execute("ALTER TABLE mediciones ADD COLUMN metodo_asignacion TEXT DEFAULT 'explicito'")

            # Índices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_estaciones_nombre ON estaciones(nombre);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_operadores_telefono ON operadores(telefono);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_operadores_fija ON operadores(estacion_fija_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_operador_estaciones_op ON operador_estaciones(operador_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_operador_estaciones_est ON operador_estaciones(estacion_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mensajes_operador_ts ON mensajes_chat(operador_id, timestamp_mensaje);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mensajes_tel_ts ON mensajes_chat(remitente_telefono, timestamp_mensaje);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_adjuntos_mensaje ON adjuntos_multimedia(mensaje_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_adjuntos_ruta ON adjuntos_multimedia(ruta_archivo);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mediciones_estacion ON mediciones(estacion_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mediciones_operador ON mediciones(operador_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mediciones_mensaje ON mediciones(mensaje_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mediciones_adjunto ON mediciones(adjunto_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mediciones_fecha ON mediciones(timestamp_medicion);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mediciones_telefono ON mediciones(remitente_telefono);")

            # Marcar estaciones espurias como inactivas
            placeholders = ",".join("?" for _ in SPURIOUS_STATION_NAMES)
            cursor.execute(f"UPDATE estaciones SET es_activa = 0 WHERE nombre IN ({placeholders})", SPURIOUS_STATION_NAMES)

            conn.commit()

        # Sembrar catálogo inicial
        self.seed_stations()

    def clean_spurious_stations(self) -> int:
        """
        Marca las estaciones espurias como inactivas (es_activa = 0).
        Retorna la cantidad de estaciones marcadas.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in SPURIOUS_STATION_NAMES)
            cursor.execute(f"UPDATE estaciones SET es_activa = 0 WHERE nombre IN ({placeholders})", SPURIOUS_STATION_NAMES)
            count = cursor.rowcount
            conn.commit()
            return count

    def seed_stations(self, stations_list: Optional[List[Dict[str, Any]]] = None, hidrografia_db_path: Optional[str] = None):
        """
        Pobla la tabla 'estaciones' con el catálogo base de estaciones y opcionalmente
        importa estaciones existentes de hidrografia.db.
        """
        stations_to_insert = list(stations_list or DEFAULT_SEED_STATIONS)

        # Si se especificó o existe por defecto hidrografia.db, importar estaciones
        candidate_hidro = hidrografia_db_path or r"C:\Users\abazan\Documents\URL-agep\hidrografia.db"
        if os.path.exists(candidate_hidro):
            try:
                hidro_conn = sqlite3.connect(candidate_hidro, timeout=10.0)
                try:
                    hidro_cur = hidro_conn.cursor()
                    hidro_cur.execute("SELECT nombre, latitud, longitud FROM estaciones")
                    for row in hidro_cur.fetchall():
                        h_nombre = row[0]
                        h_lat = row[1]
                        h_lon = row[2]
                        if h_nombre:
                            stations_to_insert.append({
                                "nombre": h_nombre,
                                "rio": "Río Paraná" if "Iguazú" not in h_nombre else "Río Iguazú",
                                "latitud": h_lat,
                                "longitud": h_lon,
                                "alias": [h_nombre]
                            })
                finally:
                    hidro_conn.close()
            except Exception:
                # Si falla leer hidrografia.db no debe interrumpir el funcionamiento
                pass

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for st in stations_to_insert:
                name = st["nombre"].strip()
                rio = st.get("rio")
                lat = st.get("latitud")
                lon = st.get("longitud")
                alias_list = list(st.get("alias", []))
                if name not in alias_list:
                    alias_list.append(name)
                alias_json = json.dumps(alias_list, ensure_ascii=False)
                is_active = 0 if name in SPURIOUS_STATION_NAMES else 1

                cursor.execute("""
                    INSERT INTO estaciones (nombre, rio, latitud, longitud, alias, es_activa)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(nombre) DO UPDATE SET
                        rio = COALESCE(excluded.rio, estaciones.rio),
                        latitud = CASE WHEN excluded.latitud IS NOT NULL THEN excluded.latitud ELSE estaciones.latitud END,
                        longitud = CASE WHEN excluded.longitud IS NOT NULL THEN excluded.longitud ELSE estaciones.longitud END,
                        alias = COALESCE(excluded.alias, estaciones.alias),
                        es_activa = excluded.es_activa
                """, (name, rio, lat, lon, alias_json, is_active))
            conn.commit()

    def get_all_stations(self, active_only: bool = False) -> List[sqlite3.Row]:
        """Devuelve todas las estaciones registradas (opcionalmente solo activas)."""
        sql = "SELECT * FROM estaciones"
        if active_only:
            sql += " WHERE es_activa = 1"
        sql += " ORDER BY nombre ASC"
        with self.get_connection() as conn:
            return conn.execute(sql).fetchall()

    def get_or_create_operator(self, telefono: str, nombre: Optional[str] = None) -> int:
        """
        Obtiene el ID de un operador por su teléfono o lo crea si no existe.
        Si se provee un nombre y el existente está vacío o es genérico, lo actualiza.
        """
        raw_tel = (telefono or "").strip()
        if not raw_tel:
            raw_tel = "desconocido"
        clean_name = (nombre or "").strip() or None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Búsqueda exacta por teléfono
            cursor.execute("SELECT id, nombre FROM operadores WHERE telefono = ?", (raw_tel,))
            row = cursor.fetchone()
            if row:
                op_id = row[0]
                curr_name = row[1]
                if clean_name and (not curr_name or curr_name == raw_tel):
                    cursor.execute("UPDATE operadores SET nombre = ?, actualizado_en = datetime('now', 'localtime') WHERE id = ?", (clean_name, op_id))
                    conn.commit()
                return op_id

            # 2. Búsqueda por dígitos numéricos limpios
            digits = re.sub(r"\D", "", raw_tel)
            if digits and len(digits) >= 8:
                cursor.execute("SELECT id, nombre FROM operadores WHERE telefono LIKE '%' || ? || '%'", (digits,))
                row = cursor.fetchone()
                if row:
                    op_id = row[0]
                    curr_name = row[1]
                    if clean_name and (not curr_name or curr_name == raw_tel):
                        cursor.execute("UPDATE operadores SET nombre = ?, actualizado_en = datetime('now', 'localtime') WHERE id = ?", (clean_name, op_id))
                        conn.commit()
                    return op_id

            try:
                cursor.execute("""
                    INSERT INTO operadores (telefono, nombre)
                    VALUES (?, ?)
                    ON CONFLICT(telefono) DO UPDATE SET
                        nombre = COALESCE(operadores.nombre, excluded.nombre),
                        actualizado_en = datetime('now', 'localtime')
                """, (raw_tel, clean_name))
                conn.commit()
                cursor.execute("SELECT id FROM operadores WHERE telefono = ?", (raw_tel,))
                row = cursor.fetchone()
                if row:
                    return row[0]
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                cursor.execute("SELECT id FROM operadores WHERE telefono = ?", (raw_tel,))
                row = cursor.fetchone()
                if row:
                    return row[0]
                if digits and len(digits) >= 8:
                    cursor.execute("SELECT id FROM operadores WHERE telefono LIKE '%' || ? || '%'", (digits,))
                    row = cursor.fetchone()
                    if row:
                        return row[0]
                raise

    def infer_operator_station(self, operador_id_or_phone: Any) -> Optional[int]:
        """
        Infiere la estación para un operador basándose en su estación fija configurada
        o en su historial consistente (mínimo 2 reportes y >= 80% de dominancia).
        Retorna station_id si es consistente, o None si es multi-estación o desconocido.
        """
        if not operador_id_or_phone:
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Resolver operador
            op_row = None
            if isinstance(operador_id_or_phone, int) and not isinstance(operador_id_or_phone, bool):
                if operador_id_or_phone < 100000:
                    cursor.execute("SELECT id, estacion_fija_id, telefono FROM operadores WHERE id = ?", (operador_id_or_phone,))
                    op_row = cursor.fetchone()
                if not op_row:
                    digits = str(operador_id_or_phone)
                    cursor.execute("SELECT id, estacion_fija_id, telefono FROM operadores WHERE telefono = ?", (digits,))
                    op_row = cursor.fetchone()
            else:
                raw_str = str(operador_id_or_phone).strip()
                digits = re.sub(r"\D", "", raw_str)

                # Si es un número entero corto (<= 4 dígitos), podría ser un ID de operador
                if raw_str.isdigit() and len(raw_str) <= 4:
                    cursor.execute("SELECT id, estacion_fija_id, telefono FROM operadores WHERE id = ?", (int(raw_str),))
                    op_row = cursor.fetchone()

                # Búsqueda exacta por teléfono original o sólo dígitos o prefijo '+'
                if not op_row:
                    candidates = [raw_str]
                    if digits:
                        candidates.extend([digits, "+" + digits])
                    placeholders = " OR ".join(["telefono = ?"] * len(candidates))
                    cursor.execute(f"SELECT id, estacion_fija_id, telefono FROM operadores WHERE {placeholders}", tuple(candidates))
                    op_row = cursor.fetchone()

                # Búsqueda por coincidencia de dígitos limpios
                if not op_row and digits and len(digits) >= 6:
                    key_suffix = digits[-8:] if len(digits) >= 8 else digits
                    cursor.execute("SELECT id, estacion_fija_id, telefono FROM operadores WHERE telefono LIKE '%' || ?", (key_suffix,))
                    for r in cursor.fetchall():
                        db_digits = re.sub(r"\D", "", r[2] or "")
                        if db_digits and (db_digits == digits or db_digits.endswith(key_suffix) or digits.endswith(db_digits[-8:] if len(db_digits) >= 8 else db_digits)):
                            op_row = r
                            break

                # Búsqueda contra todos los operadores normalizando números con espacios o símbolos
                if not op_row and digits and len(digits) >= 8:
                    for r in cursor.execute("SELECT id, estacion_fija_id, telefono FROM operadores").fetchall():
                        db_digits = re.sub(r"\D", "", r[2] or "")
                        if db_digits and (db_digits == digits or (len(db_digits) >= 8 and db_digits[-8:] == digits[-8:])):
                            op_row = r
                            break

            if not op_row:
                return None

            op_id, fixed_station_id = op_row[0], op_row[1]
            if fixed_station_id:
                return fixed_station_id

            # Consultar historial en operador_estaciones
            stats = cursor.execute("""
                SELECT oe.estacion_id, oe.total_reportes, oe.es_consistente
                FROM operador_estaciones oe
                JOIN estaciones e ON oe.estacion_id = e.id
                WHERE oe.operador_id = ? AND e.es_activa = 1
                ORDER BY oe.total_reportes DESC
            """, (op_id,)).fetchall()

            if not stats:
                stats = cursor.execute("""
                    SELECT m.estacion_id, COUNT(m.id) as total_reportes, 0 as es_consistente
                    FROM mediciones m
                    JOIN estaciones e ON m.estacion_id = e.id
                    WHERE m.operador_id = ? AND e.es_activa = 1
                    GROUP BY m.estacion_id
                    ORDER BY total_reportes DESC
                """, (op_id,)).fetchall()

            if not stats:
                return None

            total_all = sum(r[1] for r in stats)
            top_station_id = stats[0][0]
            top_count = stats[0][1]
            is_marked_consistent = any(r[2] == 1 for r in stats)

            if is_marked_consistent:
                return top_station_id

            if total_all >= 2 and (top_count / total_all) >= 0.80:
                return top_station_id

            return None

    def get_station_by_id(self, station_id: int) -> Optional[Dict[str, Any]]:
        """Devuelve los metadatos de una estación por su ID primario."""
        if not station_id:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, nombre, rio, latitud, longitud, es_activa FROM estaciones WHERE id = ?", (int(station_id),))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def infer_operator_station_name(self, operador_id_or_phone: Any) -> Optional[str]:
        """Infiere el nombre de la estación para un operador basándose en su historial consistente."""
        st_id = self.infer_operator_station(operador_id_or_phone)
        if st_id:
            st = self.get_station_by_id(st_id)
            if st:
                return st.get("nombre")
        return None

    def get_operator_station_stats(self, operador_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Devuelve estadísticas de reportes por operador y estación."""
        sql = """
            SELECT 
                oe.operador_id,
                op.nombre AS operador_nombre,
                op.telefono AS operador_telefono,
                oe.estacion_id,
                e.nombre AS estacion_nombre,
                oe.total_reportes,
                oe.ultimo_reporte,
                oe.es_consistente
            FROM operador_estaciones oe
            JOIN operadores op ON oe.operador_id = op.id
            JOIN estaciones e ON oe.estacion_id = e.id
            WHERE 1=1
        """
        params = []
        if operador_id is not None:
            sql += " AND oe.operador_id = ?"
            params.append(operador_id)
        sql += " ORDER BY op.nombre ASC, oe.total_reportes DESC"
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_or_create_station(self, name: str, river: Optional[str] = None) -> Tuple[int, str]:
        """
        Busca una estación usando coincidencia exacta o difusa (fuzzy match).
        Si no existe coincidencia con confianza aceptable, la crea automáticamente.
        Retorna (estacion_id, nombre_normalizado).
        """
        raw_name = (name or "").strip()
        if not raw_name:
            raw_name = "Desconocida"

        norm_query = normalize_text_for_comparison(raw_name)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            stations = cursor.execute("SELECT id, nombre, alias, rio FROM estaciones").fetchall()

            best_match_id = None
            best_match_name = None
            best_score = 0.0

            for st in stations:
                st_id = st["id"]
                st_name = st["nombre"]
                st_alias = st["alias"]

                # 1. Comparación con el nombre oficial
                score = compute_string_similarity(raw_name, st_name)
                if score > best_score:
                    best_score = score
                    best_match_id = st_id
                    best_match_name = st_name

                # 2. Comparación con los alias
                if st_alias:
                    try:
                        aliases = json.loads(st_alias)
                        if isinstance(aliases, list):
                            for al in aliases:
                                al_score = compute_string_similarity(raw_name, al)
                                if al_score > best_score:
                                    best_score = al_score
                                    best_match_id = st_id
                                    best_match_name = st_name
                    except Exception:
                        pass

                # Si es coincidencia casi perfecta (>= 0.95), salimos antes
                if best_score >= 0.95:
                    break

            # Umbral de aceptación para coincidencia difusa: 0.78
            if best_match_id and best_score >= 0.78:
                # Actualizar alias si es una variante nueva y relevante
                try:
                    cursor.execute("SELECT alias FROM estaciones WHERE id = ?", (best_match_id,))
                    row = cursor.fetchone()
                    if row:
                        curr_aliases = json.loads(row["alias"] or "[]")
                        if raw_name not in curr_aliases and len(curr_aliases) < 20:
                            curr_aliases.append(raw_name)
                            cursor.execute("UPDATE estaciones SET alias = ? WHERE id = ?", (json.dumps(curr_aliases, ensure_ascii=False), best_match_id))
                            conn.commit()
                except Exception:
                    pass
                return best_match_id, best_match_name

            # No encontrada: buscar coincidencia insensible a mayúsculas antes de insertar
            new_name = raw_name.strip().title()
            cursor.execute("SELECT id, nombre FROM estaciones WHERE LOWER(nombre) = LOWER(?)", (new_name,))
            exact_case_row = cursor.fetchone()
            if exact_case_row:
                return exact_case_row[0], exact_case_row[1]

            alias_json = json.dumps([raw_name, new_name], ensure_ascii=False)
            cursor.execute("""
                INSERT INTO estaciones (nombre, rio, alias)
                VALUES (?, ?, ?)
                ON CONFLICT(nombre) DO UPDATE SET
                    rio = COALESCE(estaciones.rio, excluded.rio)
            """, (new_name, river, alias_json))
            conn.commit()

            cursor.execute("SELECT id, nombre FROM estaciones WHERE LOWER(nombre) = LOWER(?)", (new_name,))
            created_row = cursor.fetchone()
            return created_row[0], created_row[1]

    def save_photo(self, image_bytes: bytes, timestamp_str: str, station_name: str) -> str:
        """
        Guarda los bytes de la foto en disco en photos_dir con un nombre limpio:
        YYYYMMDD_HHMMSS_Estacion[_idx].jpg
        Retorna la ruta relativa del archivo guardado.
        """
        if not image_bytes:
            return ""

        # Formatear timestamp para el nombre de archivo
        cleaned_ts = re.sub(r"[^\d]", "", timestamp_str or "")
        if len(cleaned_ts) < 14:
            cleaned_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            cleaned_ts = f"{cleaned_ts[:8]}_{cleaned_ts[8:14]}"

        # Sanitizar nombre de estación
        safe_station = re.sub(r"[^\w\-_]", "", normalize_text_for_comparison(station_name).replace(" ", "_")).title()
        if not safe_station:
            safe_station = "Regla"

        # Determinar extensión según bytes
        ext = ".jpg"
        if image_bytes.startswith(b"\x89PNG"):
            ext = ".png"
        elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
            ext = ".webp"

        filename = f"{cleaned_ts}_{safe_station}{ext}"
        full_path = os.path.join(self.photos_dir, filename)

        # Evitar sobreescritura si ya existe
        counter = 1
        base_name, _ = os.path.splitext(filename)
        while os.path.exists(full_path):
            filename = f"{base_name}_{counter}{ext}"
            full_path = os.path.join(self.photos_dir, filename)
            counter += 1

        with open(full_path, "wb") as f:
            f.write(image_bytes)

        # Retornar ruta relativa con barras normales
        return full_path.replace("\\", "/")

    def save_measurement(
        self,
        estacion_detectada: str,
        remitente_telefono: str,
        timestamp_medicion: str,
        valor_original: Optional[str] = None,
        valor_metros: Optional[float] = None,
        valor_cm: Optional[float] = None,
        unidad_detectada: Optional[str] = "m",
        tendencia_rio: Optional[str] = None,
        origen_dato: Optional[str] = "texto",
        confianza: Optional[str] = "alta",
        remitente_nombre: Optional[str] = None,
        mensaje_texto: Optional[str] = None,
        foto_path: Optional[str] = None,
        foto_bytes: Optional[bytes] = None,
        observaciones_ia: Optional[str] = None,
        revisado: int = 1,
        rio: Optional[str] = None,
        metodo_asignacion: Optional[str] = "explicito",
        operador_id: Optional[int] = None,
        mensaje_id: Optional[int] = None,
        adjunto_id: Optional[int] = None,
    ) -> int:
        """
        Normaliza los datos, resuelve la estación, guarda la foto si fue provista en bytes,
        asegura el registro del operador y mensaje, e inserta la medición en la base de datos.
        """
        # Resolver o crear estación
        estacion_id, norm_name = self.get_or_create_station(estacion_detectada, river=rio)

        # Normalizar unidades (metros vs centímetros)
        if valor_metros is not None and valor_cm is None:
            valor_cm = round(valor_metros * 100.0, 2)
        elif valor_cm is not None and valor_metros is None:
            valor_metros = round(valor_cm / 100.0, 4)
        elif valor_metros is not None and valor_cm is not None:
            # Si ambos vienen pero tienen discrepancia evidente
            if abs(valor_metros * 100.0 - valor_cm) > 0.1:
                # Ajustar según unidad detectada
                if unidad_detectada == "cm":
                    valor_metros = round(valor_cm / 100.0, 4)
                else:
                    valor_cm = round(valor_metros * 100.0, 2)

        # Si viene foto_bytes y no foto_path, guardarla en disco
        if foto_bytes and not foto_path:
            foto_path = self.save_photo(foto_bytes, timestamp_medicion, norm_name)

        # Resolver operador si no viene provisto
        op_id = operador_id
        if op_id is None:
            op_id = self.get_or_create_operator(remitente_telefono, remitente_nombre)

        # Resolver adjunto_id si hay foto y no viene provisto
        adj_id = adjunto_id
        if foto_path and adj_id is None:
            adj_id = self.associate_photo_to_message(
                remitente_telefono=remitente_telefono,
                timestamp_str=timestamp_medicion,
                foto_path=foto_path,
            )

        # Resolver mensaje_id si no viene provisto y hay texto o foto
        msg_id = mensaje_id
        if msg_id is None and (mensaje_texto or foto_path):
            msg_id = self.save_chat_message(
                remitente_telefono=remitente_telefono,
                remitente_nombre=remitente_nombre,
                timestamp_str=timestamp_medicion,
                texto=mensaje_texto,
                foto_path=foto_path,
                operador_id=op_id,
            )

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Evitar duplicados exactos en importaciones recurrentes
            cursor.execute("""
                SELECT id, foto_path, adjunto_id, mensaje_id FROM mediciones
                WHERE timestamp_medicion = ?
                  AND remitente_telefono = ?
                  AND estacion_id = ?
                  AND (
                      (valor_metros IS NULL AND ? IS NULL)
                      OR (abs(COALESCE(valor_metros, -999) - COALESCE(?, -999)) < 0.001)
                  )
            """, (timestamp_medicion, remitente_telefono, estacion_id, valor_metros, valor_metros))
            existing = cursor.fetchone()
            if existing:
                existing_id = existing[0]
                existing_photo = existing[1]
                existing_adj = existing[2]
                existing_msg = existing[3]
                needs_update = False
                upd_fields = []
                upd_params = []
                if foto_path and not existing_photo:
                    upd_fields.append("foto_path = ?")
                    upd_params.append(foto_path)
                    needs_update = True
                if adj_id and not existing_adj:
                    upd_fields.append("adjunto_id = ?")
                    upd_params.append(adj_id)
                    needs_update = True
                if msg_id and not existing_msg:
                    upd_fields.append("mensaje_id = ?")
                    upd_params.append(msg_id)
                    needs_update = True
                if op_id:
                    upd_fields.append("operador_id = COALESCE(operador_id, ?)")
                    upd_params.append(op_id)
                    needs_update = True

                if needs_update and upd_fields:
                    upd_params.append(existing_id)
                    cursor.execute(f"UPDATE mediciones SET {', '.join(upd_fields)} WHERE id = ?", upd_params)
                    conn.commit()
                return existing_id

            # Si no hubo match exacto de timestamp, verificar si hay una medición reciente en ventana de 15 min (900s)
            # de este mismo remitente y estación que tenga foto pero no nivel, o nivel pero no foto
            cursor.execute("""
                SELECT id, foto_path, valor_metros, mensaje_texto, estacion_detectada
                FROM mediciones
                WHERE remitente_telefono = ?
                  AND estacion_id = ?
                  AND timestamp_medicion >= datetime(?, '-15 minutes')
                  AND timestamp_medicion <= datetime(?, '+15 minutes')
                ORDER BY id DESC LIMIT 1
            """, (remitente_telefono, estacion_id, timestamp_medicion, timestamp_medicion))
            recent = cursor.fetchone()
            if recent:
                rec_id = recent[0]
                rec_photo = recent[1]
                rec_val_m = recent[2]

                # Caso A: La medición existente tenía foto pero le faltaba valor métrico, y ahora recibimos el valor
                if rec_photo and (rec_val_m is None) and (valor_metros is not None):
                    cursor.execute("""
                        UPDATE mediciones
                        SET estacion_id = ?,
                            operador_id = COALESCE(operador_id, ?),
                            mensaje_id = COALESCE(mensaje_id, ?),
                            adjunto_id = COALESCE(adjunto_id, ?),
                            estacion_detectada = ?,
                            metodo_asignacion = COALESCE(?, metodo_asignacion),
                            valor_original = ?,
                            valor_metros = ?,
                            valor_cm = ?,
                            unidad_detectada = ?,
                            tendencia_rio = COALESCE(?, tendencia_rio),
                            mensaje_texto = COALESCE(mensaje_texto || '\n' || ?, ?),
                            origen_dato = 'ambos'
                        WHERE id = ?
                    """, (estacion_id, op_id, msg_id, adj_id, norm_name, metodo_asignacion,
                          str(valor_original) if valor_original is not None else None,
                          valor_metros, valor_cm, unidad_detectada, tendencia_rio, mensaje_texto, mensaje_texto, rec_id))
                    conn.commit()
                    return rec_id

                # Caso B: La medición existente tenía valor pero no tenía foto, y ahora llega la foto
                elif foto_path and not rec_photo:
                    cursor.execute("""
                        UPDATE mediciones
                        SET foto_path = ?,
                            adjunto_id = COALESCE(adjunto_id, ?),
                            mensaje_id = COALESCE(mensaje_id, ?),
                            operador_id = COALESCE(operador_id, ?),
                            origen_dato = 'ambos',
                            mensaje_texto = COALESCE(mensaje_texto || '\n' || ?, mensaje_texto)
                        WHERE id = ?
                    """, (foto_path, adj_id, msg_id, op_id, mensaje_texto, rec_id))
                    conn.commit()
                    return rec_id

            cursor.execute("""
                INSERT INTO mediciones (
                    estacion_id, operador_id, mensaje_id, adjunto_id,
                    estacion_detectada, metodo_asignacion, valor_original, valor_metros, valor_cm,
                    unidad_detectada, tendencia_rio, origen_dato, confianza,
                    remitente_telefono, remitente_nombre, mensaje_texto, foto_path,
                    timestamp_medicion, observaciones_ia, revisado
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                estacion_id,
                op_id,
                msg_id,
                adj_id,
                estacion_detectada,
                metodo_asignacion or "explicito",
                str(valor_original) if valor_original is not None else None,
                valor_metros,
                valor_cm,
                unidad_detectada,
                tendencia_rio,
                origen_dato,
                confianza,
                remitente_telefono,
                remitente_nombre,
                mensaje_texto,
                foto_path,
                timestamp_medicion,
                observaciones_ia,
                revisado,
            ))
            last_id = cursor.lastrowid

            if op_id and estacion_id:
                cursor.execute("""
                    INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, ultimo_reporte, es_consistente)
                    VALUES (?, ?, 1, ?, 0)
                    ON CONFLICT(operador_id, estacion_id) DO UPDATE SET
                        total_reportes = operador_estaciones.total_reportes + 1,
                        ultimo_reporte = excluded.ultimo_reporte
                """, (op_id, estacion_id, timestamp_medicion))

            conn.commit()
            return last_id

    def query_measurements(
        self,
        estacion_id: Optional[int] = None,
        estacion_nombre: Optional[str] = None,
        fecha_desde: Optional[str] = None,
        fecha_hasta: Optional[str] = None,
        remitente_telefono: Optional[str] = None,
        solo_con_foto: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Consulta mediciones con filtros opcionales."""
        sql = """
            SELECT m.*, e.nombre AS estacion_nombre_norm, e.rio AS estacion_rio
            FROM mediciones m
            LEFT JOIN estaciones e ON m.estacion_id = e.id
            WHERE 1=1
        """
        params: List[Any] = []

        if estacion_id:
            sql += " AND m.estacion_id = ?"
            params.append(estacion_id)
        elif estacion_nombre:
            sql += " AND (e.nombre LIKE ? OR m.estacion_detectada LIKE ?)"
            params.append(f"%{estacion_nombre}%")
            params.append(f"%{estacion_nombre}%")

        if fecha_desde:
            f_desde = fecha_desde.strip()
            if len(f_desde) == 10:
                f_desde = f"{f_desde} 00:00:00"
            sql += " AND m.timestamp_medicion >= ?"
            params.append(f_desde)

        if fecha_hasta:
            f_hasta = fecha_hasta.strip()
            if len(f_hasta) == 10:
                f_hasta = f"{f_hasta} 23:59:59"
            sql += " AND m.timestamp_medicion <= ?"
            params.append(f_hasta)

        if remitente_telefono:
            sql += " AND m.remitente_telefono LIKE ?"
            params.append(f"%{remitente_telefono}%")

        if solo_con_foto:
            sql += " AND m.foto_path IS NOT NULL AND m.foto_path != ''"

        sql += " ORDER BY m.timestamp_medicion DESC, m.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_stations_summary(self) -> List[Dict[str, Any]]:
        """Obtiene resumen de estaciones activas: total de mediciones, coordenadas y última lectura registrada."""
        sql = """
            SELECT 
                e.id, 
                e.nombre, 
                e.rio, 
                e.latitud,
                e.longitud,
                COUNT(m.id) AS total_mediciones,
                MAX(m.timestamp_medicion) AS ultima_fecha,
                (SELECT m2.valor_metros FROM mediciones m2 WHERE m2.estacion_id = e.id AND m2.valor_metros IS NOT NULL ORDER BY m2.timestamp_medicion DESC, m2.id DESC LIMIT 1) AS ultimo_nivel_metros,
                (SELECT m2.tendencia_rio FROM mediciones m2 WHERE m2.estacion_id = e.id AND m2.valor_metros IS NOT NULL ORDER BY m2.timestamp_medicion DESC, m2.id DESC LIMIT 1) AS ultima_tendencia
            FROM estaciones e
            LEFT JOIN mediciones m ON e.id = m.estacion_id
            WHERE COALESCE(e.es_activa, 1) = 1
            GROUP BY e.id, e.nombre, e.rio, e.latitud, e.longitud
            ORDER BY total_mediciones DESC, e.nombre ASC
        """
        with self.get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def export_to_csv(self, output_path: str, **query_kwargs) -> str:
        """
        Exporta mediciones a CSV con codificación UTF-8 con BOM para perfecta
        compatibilidad con Microsoft Excel.
        """
        rows = self.query_measurements(limit=100000, **query_kwargs)
        if not rows:
            # Si no hay filas, escribir encabezados vacíos
            fieldnames = [
                "ID", "Fecha y Hora", "Estación Normalizada", "Estación Detectada", "Río",
                "Nivel (m)", "Nivel (cm)", "Tendencia", "Origen", "Confianza",
                "Remitente Teléfono", "Remitente Nombre", "Texto Mensaje", "Foto", "Observaciones IA"
            ]
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(fieldnames)
            return output_path

        fieldnames = [
            "ID", "Fecha y Hora", "Estación Normalizada", "Estación Detectada", "Río",
            "Nivel (m)", "Nivel (cm)", "Tendencia", "Origen", "Confianza",
            "Remitente Teléfono", "Remitente Nombre", "Texto Mensaje", "Foto", "Observaciones IA"
        ]

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for r in rows:
                writer.writerow([
                    r["id"],
                    r["timestamp_medicion"],
                    r.get("estacion_nombre_norm") or "",
                    r.get("estacion_detectada") or "",
                    r.get("estacion_rio") or "",
                    f"{r['valor_metros']:.2f}" if r.get("valor_metros") is not None else "",
                    f"{r['valor_cm']:.1f}" if r.get("valor_cm") is not None else "",
                    r.get("tendencia_rio") or "",
                    r.get("origen_dato") or "",
                    r.get("confianza") or "",
                    r.get("remitente_telefono") or "",
                    r.get("remitente_nombre") or "",
                    r.get("mensaje_texto") or "",
                    r.get("foto_path") or "",
                    r.get("observaciones_ia") or "",
                ])

        return output_path

    def associate_photo_to_message(
        self,
        remitente_telefono: str,
        timestamp_str: str,
        foto_path: str,
        nombre_original: Optional[str] = None
    ) -> int:
        """
        Vincula de forma biunívoca una foto con su mensaje de chat y/o medición correspondiente
        usando remitente_telefono y ventana temporal de hasta 15 minutos.
        Inserta/actualiza en adjuntos_multimedia y retorna adjunto_id.
        """
        if not foto_path:
            return 0

        clean_tel = re.sub(r"[^\w+]", "", (remitente_telefono or "").strip())
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Buscar en mensajes_chat: coincidencia exacta primero
            cursor.execute("""
                SELECT id, archivo_adjunto FROM mensajes_chat
                WHERE remitente_telefono = ? AND timestamp_mensaje = ? AND archivo_adjunto IS NOT NULL
                LIMIT 1
            """, (clean_tel, timestamp_str))
            c_row = cursor.fetchone()

            if not c_row:
                cursor.execute("""
                    SELECT id, archivo_adjunto FROM mensajes_chat
                    WHERE remitente_telefono = ? AND timestamp_mensaje = ?
                    LIMIT 1
                """, (clean_tel, timestamp_str))
                c_row = cursor.fetchone()

            if not c_row:
                # Ventana de 15 minutos
                cursor.execute("""
                    SELECT id, archivo_adjunto FROM mensajes_chat
                    WHERE remitente_telefono = ?
                      AND timestamp_mensaje >= datetime(?, '-15 minutes')
                      AND timestamp_mensaje <= datetime(?, '+15 minutes')
                    ORDER BY abs(strftime('%s', timestamp_mensaje) - strftime('%s', ?)) ASC
                    LIMIT 1
                """, (clean_tel, timestamp_str, timestamp_str, timestamp_str))
                c_row = cursor.fetchone()

            msg_id = c_row[0] if c_row else None
            orig_name = nombre_original or (c_row[1] if c_row and c_row[1] else os.path.basename(foto_path))

            # Determinar tamaño en bytes si archivo existe en disco
            tamano = None
            if os.path.exists(foto_path):
                try:
                    tamano = os.path.getsize(foto_path)
                except Exception:
                    pass

            # Insertar o actualizar en adjuntos_multimedia
            cursor.execute("""
                INSERT INTO adjuntos_multimedia (mensaje_id, tipo, ruta_archivo, nombre_original, tamano_bytes, timestamp_captura)
                VALUES (?, 'imagen', ?, ?, ?, ?)
                ON CONFLICT(ruta_archivo) DO UPDATE SET
                    mensaje_id = COALESCE(excluded.mensaje_id, adjuntos_multimedia.mensaje_id),
                    nombre_original = COALESCE(excluded.nombre_original, adjuntos_multimedia.nombre_original),
                    tamano_bytes = COALESCE(excluded.tamano_bytes, adjuntos_multimedia.tamano_bytes)
            """, (msg_id, foto_path, orig_name, tamano, timestamp_str))
            conn.commit()

            cursor.execute("SELECT id FROM adjuntos_multimedia WHERE ruta_archivo = ?", (foto_path,))
            adj_id = cursor.fetchone()[0]

            # Actualizar mensajes_chat.foto_path si se encontró mensaje
            if msg_id:
                cursor.execute("UPDATE mensajes_chat SET foto_path = ? WHERE id = ? AND (foto_path IS NULL OR foto_path = '')", (foto_path, msg_id))

            # Actualizar mediciones que referencien esta foto o fecha
            cursor.execute("""
                UPDATE mediciones
                SET adjunto_id = ?,
                    mensaje_id = COALESCE(mensaje_id, ?)
                WHERE foto_path = ? OR (remitente_telefono = ? AND timestamp_medicion = ?)
            """, (adj_id, msg_id, foto_path, clean_tel, timestamp_str))
            conn.commit()

            return adj_id

    def save_chat_message(
        self,
        remitente_telefono: str,
        timestamp_mensaje: Optional[str] = None,
        texto: Optional[str] = None,
        remitente_nombre: Optional[str] = None,
        archivo_adjunto: Optional[str] = None,
        foto_path: Optional[str] = None,
        es_saliente: int = 0,
        timestamp_str: Optional[str] = None,
        operador_id: Optional[int] = None,
        **kwargs
    ) -> int:
        """
        Almacena un mensaje de chat individual para mantener el contexto conversacional en orden cronológico,
        asociándolo a su operador correspondiente.
        """
        ts = timestamp_str or timestamp_mensaje or kwargs.get("timestamp")
        name = remitente_nombre
        txt = texto

        # Si se invoca posicionalmente como (telefono, nombre, timestamp, texto, archivo):
        if ts is None and name is not None:
            if re.match(r"^\d{4}-\d{2}-\d{2}", str(name)):
                ts = name
                name = kwargs.get("remitente_nombre")
        elif ts is not None and not re.match(r"^\d{4}-\d{2}-\d{2}", str(ts)) and txt is not None and re.match(r"^\d{4}-\d{2}-\d{2}", str(txt)):
            actual_name = ts
            actual_ts = txt
            actual_text = name if name is not None else (kwargs.get("texto") or kwargs.get("mensaje_texto"))
            name = actual_name
            ts = actual_ts
            txt = actual_text

        if archivo_adjunto and not foto_path:
            foto_path = archivo_adjunto

        if ts is None:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        clean_text = (txt or "").strip()
        clean_tel = re.sub(r"[^\w+]", "", (remitente_telefono or "").strip())
        if not clean_tel:
            clean_tel = "desconocido"

        # Asegurar existencia de operador
        op_id = operador_id
        if op_id is None:
            op_id = self.get_or_create_operator(clean_tel, name)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Evitar duplicados exactos
            cursor.execute("""
                SELECT id, foto_path FROM mensajes_chat 
                WHERE remitente_telefono = ? AND timestamp_mensaje = ? AND COALESCE(texto, '') = ? AND COALESCE(archivo_adjunto, '') = ?
            """, (clean_tel, ts, clean_text, archivo_adjunto or ""))
            row = cursor.fetchone()
            if row:
                msg_id = row[0]
                if foto_path and not row[1]:
                    cursor.execute("UPDATE mensajes_chat SET foto_path = ?, operador_id = COALESCE(operador_id, ?) WHERE id = ?", (foto_path, op_id, msg_id))
                    conn.commit()
                return msg_id

            cursor.execute("""
                INSERT INTO mensajes_chat (
                    operador_id, remitente_telefono, remitente_nombre, timestamp_mensaje, texto, archivo_adjunto, foto_path, es_saliente
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (op_id, clean_tel, name, ts, clean_text or None, archivo_adjunto, foto_path, es_saliente))
            conn.commit()
            return cursor.lastrowid

    def get_station_chat_history(
        self,
        estacion_id_or_name: Any,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Devuelve los metadatos de la estación y la lista cronológica de mensajes
        (con remitentes, fotos y badges hidrométricos de nivel/tendencia) para el visor de chat.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Resolver estación
            if isinstance(estacion_id_or_name, int) or (isinstance(estacion_id_or_name, str) and str(estacion_id_or_name).isdigit()):
                cursor.execute("SELECT id, nombre, rio, latitud, longitud FROM estaciones WHERE id = ?", (int(estacion_id_or_name),))
            else:
                query_name = str(estacion_id_or_name).strip()
                cursor.execute("""
                    SELECT id, nombre, rio, latitud, longitud FROM estaciones
                    WHERE LOWER(nombre) = LOWER(?)
                       OR LOWER(codigo) = LOWER(?)
                       OR (alias IS NOT NULL AND LOWER(alias) LIKE '%' || LOWER(?) || '%')
                """, (query_name, query_name, query_name))
            st_row = cursor.fetchone()

            if not st_row:
                return {"estacion": None, "mensajes": []}

            estacion_data = {
                "id": st_row["id"],
                "nombre": st_row["nombre"],
                "rio": st_row["rio"],
                "latitud": st_row["latitud"],
                "longitud": st_row["longitud"],
            }
            st_id = st_row["id"]

            sql = """
                SELECT 
                    COALESCE(c.id, m.mensaje_id, m.id) AS mensaje_id,
                    COALESCE(c.remitente_telefono, m.remitente_telefono) AS remitente_telefono,
                    COALESCE(op.nombre, c.remitente_nombre, m.remitente_nombre, m.remitente_telefono) AS remitente_nombre,
                    COALESCE(c.timestamp_mensaje, m.timestamp_medicion) AS timestamp_mensaje,
                    COALESCE(c.texto, m.mensaje_texto) AS texto,
                    COALESCE(c.es_saliente, 0) AS es_saliente,
                    COALESCE(a.ruta_archivo, c.foto_path, m.foto_path) AS foto_path,
                    m.id AS medicion_id,
                    m.valor_metros,
                    m.valor_cm,
                    m.tendencia_rio,
                    m.origen_dato,
                    COALESCE(m.metodo_asignacion, 'explicito') AS metodo_asignacion
                FROM mediciones m
                LEFT JOIN mensajes_chat c ON m.mensaje_id = c.id
                LEFT JOIN operadores op ON m.operador_id = op.id OR (c.operador_id IS NOT NULL AND c.operador_id = op.id)
                LEFT JOIN adjuntos_multimedia a ON m.adjunto_id = a.id OR (c.id IS NOT NULL AND a.mensaje_id = c.id)
                WHERE m.estacion_id = ?
                ORDER BY COALESCE(c.timestamp_mensaje, m.timestamp_medicion) ASC, m.id ASC
                LIMIT ?
            """
            rows = cursor.execute(sql, (st_id, limit)).fetchall()
            mensajes = []

            for r in rows:
                mensajes.append({
                    "mensaje_id": r["mensaje_id"],
                    "remitente_telefono": r["remitente_telefono"],
                    "remitente_nombre": r["remitente_nombre"],
                    "timestamp_mensaje": r["timestamp_mensaje"],
                    "texto": r["texto"],
                    "es_saliente": bool(r["es_saliente"]),
                    "foto_path": r["foto_path"],
                    "medicion_id": r["medicion_id"],
                    "valor_metros": r["valor_metros"],
                    "valor_cm": r["valor_cm"],
                    "tendencia_rio": r["tendencia_rio"],
                    "origen_dato": r["origen_dato"],
                    "metodo_asignacion": r["metodo_asignacion"],
                })

            return {
                "estacion": estacion_data,
                "mensajes": mensajes,
            }

    def get_chronological_messages_for_measurement(
        self,
        measurement_id: int,
        window_minutes: int = 20
    ) -> Dict[str, Any]:
        """
        Obtiene los mensajes de chat en orden cronológico en una ventana de tiempo
        alrededor de la medición (por defecto +-20 minutos).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.*, e.nombre as estacion_nombre_norm, e.rio as estacion_rio
                FROM mediciones m
                LEFT JOIN estaciones e ON m.estacion_id = e.id
                WHERE m.id = ?
            """, (measurement_id,))
            m_row = cursor.fetchone()
            if not m_row:
                return {"medicion": None, "mensajes": []}

            medicion = dict(m_row)
            tel = medicion["remitente_telefono"]
            ts = medicion["timestamp_medicion"]

            # Buscar mensajes en la ventana de tiempo (+- window_minutes)
            cursor.execute("""
                SELECT timestamp_mensaje, remitente_nombre, texto, archivo_adjunto, foto_path
                FROM mensajes_chat
                WHERE remitente_telefono = ?
                  AND timestamp_mensaje >= datetime(?, '-' || ? || ' minutes')
                  AND timestamp_mensaje <= datetime(?, '+' || ? || ' minutes')
                ORDER BY timestamp_mensaje ASC, id ASC
            """, (tel, ts, window_minutes, ts, window_minutes))
            rows = cursor.fetchall()
            mensajes = [dict(r) for r in rows]

            # Si no había mensajes registrados en mensajes_chat para este período,
            # proveer al menos el mensaje original de la propia medición
            if not mensajes and medicion.get("mensaje_texto"):
                mensajes.append({
                    "timestamp_mensaje": medicion["timestamp_medicion"],
                    "remitente_nombre": medicion.get("remitente_nombre") or tel,
                    "texto": medicion["mensaje_texto"],
                    "archivo_adjunto": os.path.basename(medicion["foto_path"]) if medicion.get("foto_path") else None,
                    "foto_path": medicion.get("foto_path"),
                })

            return {"medicion": medicion, "mensajes": mensajes}

    def update_measurement(
        self,
        measurement_id: int,
        station_name: Optional[str] = None,
        valor_metros: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Permite corregir manualmente la estación y/o el valor en metros de una medición existente.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mediciones WHERE id = ?", (measurement_id,))
            row = cursor.fetchone()
            if not row:
                return None

            cur_meas = dict(row)
            new_station_id = cur_meas["estacion_id"]
            new_station_name = cur_meas["estacion_detectada"]

            if station_name and station_name.strip():
                st_id, st_norm = self.get_or_create_station(station_name.strip())
                new_station_id = st_id
                new_station_name = station_name.strip()

            new_val_m = cur_meas["valor_metros"]
            new_val_cm = cur_meas["valor_cm"]

            if valor_metros is not None:
                new_val_m = float(valor_metros)
                new_val_cm = round(new_val_m * 100.0, 2)

            cursor.execute("""
                UPDATE mediciones
                SET estacion_id = ?,
                    estacion_detectada = ?,
                    valor_metros = ?,
                    valor_cm = ?,
                    revisado = 1
                WHERE id = ?
            """, (new_station_id, new_station_name, new_val_m, new_val_cm, measurement_id))
            conn.commit()

            cursor.execute("""
                SELECT m.*, e.nombre as estacion_nombre_norm, e.rio as estacion_rio
                FROM mediciones m
                LEFT JOIN estaciones e ON m.estacion_id = e.id
                WHERE m.id = ?
            """, (measurement_id,))
            updated_row = cursor.fetchone()
            return dict(updated_row) if updated_row else None
