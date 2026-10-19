"""
tests/test_e2e_verification.py
Comprehensive End-to-End Verification Test Suite for WhatsApp Bot Hidrométrico.

Validates all 4 acceptance criteria in ORIGINAL_REQUEST.md and all 4 test tiers in TEST_INFRA.md:
1. Database Migration & Zero-Loss Query Integrity (402/402 mediciones, 534/534 chats, 272/272 photos, FK checks).
2. Classification & Operator-Station Inference (consistent operator auto-inferred, multi-station & unknown unassigned without blind guessing, explicit station overriding history, trend 'estacionado', subset similarity fix).
3. Bi-Directional Photo-Message Association and Station Chat API.
4. Dashboard UI Validation (complete absence of KPI summary cards, presence of Leaflet map and WhatsApp chat modal).

Test Tiers:
- Tier 1: Feature Coverage (F1 to F10, >= 5 cases per feature)
- Tier 2: Boundary & Corner Cases (>= 5 boundary/corner cases per feature)
- Tier 3: Cross-Feature Interactions (Pairwise interactions across DB, Inference, Photos, UI)
- Tier 4: Real-World Hydrometric Workloads (6 concrete real-world scenarios)
"""

import os
import sys
import re
import json
import shutil
import sqlite3
import unittest
import tempfile
import threading
import urllib.request
import urllib.parse
from http.server import HTTPServer

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bot.measurement_store import (
    MeasurementStore,
    DEFAULT_SEED_STATIONS,
    SPURIOUS_STATION_NAMES,
    compute_string_similarity,
    normalize_text_for_comparison,
)
from bot.measurement_agent import MeasurementAgent
from dashboard_app import DashboardHTTPHandler
from scripts.migrate_database import migrate_database

BACKUP_DB_PATH = os.path.join(PROJECT_ROOT, "data", "mediciones.db.bak")
LIVE_DB_PATH = os.path.join(PROJECT_ROOT, "data", "mediciones.db")


# ==============================================================================
# TIER 1: FEATURE COVERAGE (F1 to F10)
# ==============================================================================

class TestTier1FeatureCoverage(unittest.TestCase):
    """
    Tier 1: Feature Coverage across all 10 core features from TEST_INFRA.md.
    Each feature has at least 5 targeted test cases.
    """

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.photos_dir = os.path.join(cls.test_dir, "fotos")
        os.makedirs(cls.photos_dir, exist_ok=True)

        cls.migrated_db = os.path.join(cls.test_dir, "tier1_migrated.db")
        cls.backup_copy = os.path.join(cls.test_dir, "tier1_migrated.db.bak")

        # Clona data/mediciones.db.bak y ejecuta la migración
        shutil.copy2(BACKUP_DB_PATH, cls.migrated_db)
        cls.migration_result = migrate_database(db_path=cls.migrated_db, backup_path=cls.backup_copy)

        # Inicializa store y mock de fotos
        cls.store = MeasurementStore(db_path=cls.migrated_db, photos_dir=cls.photos_dir)
        cls.agent = MeasurementAgent(api_key=None, store=cls.store)

        # Levanta servidor web local para pruebas de UI y endpoints
        DashboardHTTPHandler.store = cls.store
        cls.httpd = HTTPServer(("127.0.0.1", 0), DashboardHTTPHandler)
        cls.port = cls.httpd.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # F1: DB Schema & Migration Integrity
    # --------------------------------------------------------------------------
    def test_f1_01_core_tables_and_columns_exist(self):
        """Verifica que existan las 6 tablas relacionales normalizadas y sus columnas principales."""
        expected_tables = [
            "estaciones", "operadores", "operador_estaciones",
            "mensajes_chat", "adjuntos_multimedia", "mediciones"
        ]
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for tbl in expected_tables:
                self.assertIn(tbl, tables, f"La tabla {tbl} debe existir en el esquema normalizado.")

            # Columnas críticas en mediciones
            cur.execute("PRAGMA table_info(mediciones)")
            med_cols = {r[1] for r in cur.fetchall()}
            for col in ["estacion_id", "operador_id", "mensaje_id", "adjunto_id", "valor_metros", "metodo_asignacion"]:
                self.assertIn(col, med_cols, f"Columna {col} ausente en mediciones.")

    def test_f1_02_backward_compatible_legacy_columns_and_queries(self):
        """Verifica que la tabla mediciones mantenga columnas retrocompatibles y soporte consultas existentes."""
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*), remitente_telefono, foto_path, mensaje_texto, timestamp_medicion
                FROM mediciones
                GROUP BY remitente_telefono
            """)
            rows = cur.fetchall()
            self.assertGreater(len(rows), 0, "Consultas agrupadas con columnas heredadas deben funcionar.")


    def test_f1_03_foreign_key_constraints_enforced_and_clean(self):
        """Verifica que la base de datos migrada no tenga violaciones de integridad referencial (FKs)."""
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            fk_violations = cur.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(fk_violations), 0, f"Violaciones de clave foránea detectadas: {fk_violations}")

    def test_f1_04_geographic_coordinates_in_estaciones(self):
        """Verifica que la tabla estaciones contenga columnas de latitud y longitud con valores válidos."""
        with sqlite3.connect(self.migrated_db) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            ayolas = cur.execute("SELECT latitud, longitud FROM estaciones WHERE nombre = 'Ayolas'").fetchone()
            self.assertIsNotNone(ayolas)
            self.assertIsNotNone(ayolas["latitud"])
            self.assertIsNotNone(ayolas["longitud"])
            self.assertAlmostEqual(ayolas["latitud"], -27.40, places=1)
            self.assertAlmostEqual(ayolas["longitud"], -56.90, places=1)

    def test_f1_05_zero_data_loss_counts(self):
        """Verifica que la migración preserve con exactitud cero pérdida: 402 mediciones, 534 chats, 272 fotos."""
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            total_meds = cur.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
            total_chats = cur.execute("SELECT COUNT(*) FROM mensajes_chat").fetchone()[0]
            total_adj = cur.execute("SELECT COUNT(*) FROM adjuntos_multimedia").fetchone()[0]
            meds_with_adj = cur.execute("SELECT COUNT(*) FROM mediciones WHERE adjunto_id IS NOT NULL").fetchone()[0]
            meds_with_op = cur.execute("SELECT COUNT(*) FROM mediciones WHERE operador_id IS NOT NULL").fetchone()[0]

            self.assertEqual(total_meds, 402, "Deben existir exactamente 402 mediciones.")
            self.assertEqual(total_chats, 534, "Deben existir exactamente 534 mensajes de chat.")
            self.assertEqual(total_adj, 272, "Deben existir exactamente 272 adjuntos multimedia.")
            self.assertEqual(meds_with_adj, 272, "Las 272 fotos deben tener adjunto_id vinculado.")
            self.assertEqual(meds_with_op, 402, "Las 402 mediciones deben tener operador_id asignado.")

    # --------------------------------------------------------------------------
    # F2: Station Catalog & Spurious Prevention
    # --------------------------------------------------------------------------
    def test_f2_01_master_seed_stations_present(self):
        """Verifica que las estaciones hidrológicas canónicas maestras estén registradas."""
        canonical_samples = ["Ayolas", "Coratei", "Panchito López", "PZA", "Pilar", "Alberdi", "Asunción"]
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            for st in canonical_samples:
                row = cur.execute("SELECT id, nombre, es_activa FROM estaciones WHERE nombre = ?", (st,)).fetchone()
                self.assertIsNotNone(row, f"Estación canónica {st} no encontrada.")
                self.assertEqual(row[2], 1, f"Estación {st} debe estar activa.")

    def test_f2_02_spurious_stations_marked_inactive(self):
        """Verifica que las 8 estaciones espurias tengan es_activa = 0."""
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            placeholders = ",".join("?" for _ in SPURIOUS_STATION_NAMES)
            spurious_active = cur.execute(
                f"SELECT COUNT(*) FROM estaciones WHERE es_activa = 1 AND nombre IN ({placeholders})",
                SPURIOUS_STATION_NAMES
            ).fetchone()[0]
            self.assertEqual(spurious_active, 0, "No debe haber estaciones espurias activas.")

            spurious_inactive = cur.execute(
                f"SELECT COUNT(*) FROM estaciones WHERE es_activa = 0 AND nombre IN ({placeholders})",
                SPURIOUS_STATION_NAMES
            ).fetchone()[0]
            self.assertEqual(spurious_inactive, len(SPURIOUS_STATION_NAMES), "Las 8 estaciones espurias deben estar inactivas.")

    def test_f2_03_active_summary_excludes_spurious_stations(self):
        """Verifica que get_stations_summary excluya totalmente estaciones espurias."""
        summary = self.store.get_stations_summary()
        summary_names = {s["nombre"] for s in summary}
        for spur in SPURIOUS_STATION_NAMES:
            self.assertNotIn(spur, summary_names, f"La estación espuria {spur} no debe aparecer en el resumen activo.")

    def test_f2_04_station_name_normalization_with_diacritics_and_prefixes(self):
        """Verifica que normalize_text_for_comparison elimine tildes y prefijos comunes."""
        self.assertEqual(normalize_text_for_comparison("Puerto Coratei"), "coratei")
        self.assertEqual(normalize_text_for_comparison("Pto. Ayolas"), "ayolas")
        self.assertEqual(normalize_text_for_comparison("Escala Pilar"), "pilar")
        self.assertEqual(normalize_text_for_comparison("Prefectura Zona Ayolas"), "zona ayolas")

    def test_f2_05_geographic_coordinates_valid_range(self):
        """Verifica que las estaciones canónicas maestras con coordenadas estén dentro del rango de la cuenca."""
        for seed in DEFAULT_SEED_STATIONS:
            lat = seed.get("latitud")
            lon = seed.get("longitud")
            if lat is not None and lon is not None:
                self.assertTrue(-40.0 <= lat <= -15.0, f"Latitud fuera de rango para {seed['nombre']}: {lat}")
                self.assertTrue(-70.0 <= lon <= -50.0, f"Longitud fuera de rango para {seed['nombre']}: {lon}")

    # --------------------------------------------------------------------------
    # F3: Operator Ingestion & History
    # --------------------------------------------------------------------------
    def test_f3_01_get_or_create_operator_formats_phone(self):
        """Verifica que get_or_create_operator registre un nuevo operador con su teléfono y nombre."""
        op_id = self.store.get_or_create_operator("595981777888", "Operador Prueba F3")
        self.assertIsInstance(op_id, int)
        with sqlite3.connect(self.migrated_db) as conn:
            row = conn.cursor().execute("SELECT telefono, nombre FROM operadores WHERE id = ?", (op_id,)).fetchone()
            self.assertEqual(row[0], "595981777888")
            self.assertEqual(row[1], "Operador Prueba F3")



    def test_f3_02_operator_creation_idempotent(self):
        """Verifica que invocar get_or_create_operator repetidamente con el mismo número devuelva el mismo ID."""
        id1 = self.store.get_or_create_operator("595982111222", "Nombre 1")
        id2 = self.store.get_or_create_operator("+595 982 111 222", "Nombre 2")
        self.assertEqual(id1, id2, "El operador debe ser único por número de teléfono.")

    def test_f3_03_operator_display_name_enrichment(self):
        """Verifica que un operador creado sin nombre sea actualizado cuando se suministre un nombre."""
        id_op = self.store.get_or_create_operator("595983333444", None)
        id_op2 = self.store.get_or_create_operator("595983333444", "Nombre Nuevo")
        self.assertEqual(id_op, id_op2)
        with sqlite3.connect(self.migrated_db) as conn:
            nombre = conn.cursor().execute("SELECT nombre FROM operadores WHERE id = ?", (id_op,)).fetchone()[0]
            self.assertEqual(nombre, "Nombre Nuevo")

    def test_f3_04_operator_station_stats_aggregation(self):
        """Verifica que get_operator_station_stats retorne el reporte agregado por operador y estación."""
        stats = self.store.get_operator_station_stats()
        self.assertIsInstance(stats, list)
        self.assertGreater(len(stats), 0)
        first = stats[0]
        self.assertIn("operador_id", first)
        self.assertIn("estacion_id", first)
        self.assertIn("total_reportes", first)

    def test_f3_05_save_measurement_links_operator_foreign_key(self):
        """Verifica que una nueva medición guardada vincule automáticamente el operador_id correspondiente."""
        mid = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984555666",
            remitente_nombre="Juan Operador",
            timestamp_medicion="2026-10-16 10:00:00",
            valor_metros=3.10
        )
        with sqlite3.connect(self.migrated_db) as conn:
            op_id = conn.cursor().execute("SELECT operador_id FROM mediciones WHERE id = ?", (mid,)).fetchone()[0]
            self.assertIsNotNone(op_id)
            op_tel = conn.cursor().execute("SELECT telefono FROM operadores WHERE id = ?", (op_id,)).fetchone()[0]
            self.assertEqual(op_tel, "595984555666")

    # --------------------------------------------------------------------------
    # F4: Operator-Station Inference (Consistent Operator)
    # --------------------------------------------------------------------------
    def test_f4_01_consistent_operator_inferred_automatically(self):
        """Verifica que Fabio Marin (595972695099) sea inferido automáticamente a Ayolas."""
        inferred_id = self.store.infer_operator_station("595972695099")
        self.assertIsNotNone(inferred_id)
        with sqlite3.connect(self.migrated_db) as conn:
            st_name = conn.cursor().execute("SELECT nombre FROM estaciones WHERE id = ?", (inferred_id,)).fetchone()[0]
            self.assertEqual(st_name, "Ayolas")

    def test_f4_02_metodo_asignacion_is_inferido_operador(self):
        """Verifica que el clasificador marque metodo_asignacion = 'inferido_operador' al aplicar inferencia."""
        res = self.agent.parse_message("3,45 creciendo", remitente_telefono="595972695099")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Ayolas")
        self.assertEqual(res["metodo_asignacion"], "inferido_operador")

    def test_f4_03_inferred_station_field_matches_assigned_station(self):
        """Verifica que el campo inferred_station del resultado contenga el nombre de la estación deducida."""
        res = self.agent.parse_message("3,45 creciendo", remitente_telefono="595972695099")
        self.assertEqual(res["inferred_station"], "Ayolas")
        self.assertEqual(res["estacion"], "Ayolas")

    def test_f4_04_dominance_ratio_calculation(self):
        """Verifica que un operador con historial >= 80% en una estación sea marcado consistente."""
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT oe.es_consistente FROM operador_estaciones oe
                JOIN operadores op ON oe.operador_id = op.id
                WHERE op.telefono = '595972695099' AND oe.estacion_id = (SELECT id FROM estaciones WHERE nombre = 'Ayolas')
            """)
            es_consistente = cur.fetchone()[0]
            self.assertEqual(es_consistente, 1)

    def test_f4_05_fixed_station_override_without_reports(self):
        """Verifica que si un operador tiene estacion_fija_id configurada, sea inferido de inmediato."""
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Humaitá'")
            humaita_id = cur.fetchone()[0]
            cur.execute("INSERT INTO operadores (telefono, nombre, estacion_fija_id) VALUES ('595989123456', 'Fijo Humaitá', ?)", (humaita_id,))
            conn.commit()

        inf_id = self.store.infer_operator_station("595989123456")
        self.assertEqual(inf_id, humaita_id)

    # --------------------------------------------------------------------------
    # F5: Operator-Station Protection (Multi/Unknown)
    # --------------------------------------------------------------------------
    def test_f5_01_multistation_operator_remains_unassigned(self):
        """Verifica que el operador multi-estación Juan Domínguez (595984621689) retorne None en inferencia."""
        inferred = self.store.infer_operator_station("595984621689")
        self.assertIsNone(inferred, "Operador de patrulla móvil no debe ser asignado automáticamente a una estación fija.")

    def test_f5_02_unknown_operator_remains_unassigned(self):
        """Verifica que un remitente nuevo sin historial previo retorne None en inferencia."""
        inferred = self.store.infer_operator_station("595999888777")
        self.assertIsNone(inferred, "Remitente desconocido no debe ser asignado por adivinanza ciega.")

    def test_f5_03_metodo_asignacion_is_desconocido(self):
        """Verifica que al no haber estación explícita ni inferible, metodo_asignacion sea 'desconocido'."""
        res = self.agent.parse_message("3,45 creciendo", remitente_telefono="595984621689")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["metodo_asignacion"], "desconocido")

    def test_f5_04_inferred_station_is_none_for_unassigned(self):
        """Verifica que inferred_station y estacion sean None para reportes no asignados."""
        res = self.agent.parse_message("3,45 creciendo", remitente_telefono="595984621689")
        self.assertIsNone(res["estacion"])
        self.assertIsNone(res["inferred_station"])

    def test_f5_05_balanced_multistation_history_not_guessed(self):
        """Verifica que un operador con historial 50%/50% en dos estaciones no sea inferido ciegamente."""
        op_id = self.store.get_or_create_operator("595971555444", "Operador 50/50")
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Humaitá'")
            humaita_id = cur.fetchone()[0]
            cur.execute("INSERT OR REPLACE INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 5, 0)", (op_id, pilar_id))
            cur.execute("INSERT OR REPLACE INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 5, 0)", (op_id, humaita_id))
            conn.commit()

        inferred = self.store.infer_operator_station("595971555444")
        self.assertIsNone(inferred, "Historial empatado (50%/50%) no debe inferir ninguna estación.")

    # --------------------------------------------------------------------------
    # F6: Photo-Message Bi-Directional Association
    # --------------------------------------------------------------------------
    def test_f6_01_photo_associated_with_exact_timestamp(self):
        """Verifica que una foto enviada con el mismo timestamp del mensaje sea vinculada."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981100200",
            timestamp_str="2026-10-16 11:00:00",
            texto="Reporte con foto exacta"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981100200",
            timestamp_str="2026-10-16 11:00:00",
            foto_path="data/fotos/test_exact.jpg"
        )
        self.assertGreater(adj_id, 0)
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,))
            linked_msg = cur.fetchone()[0]
            self.assertEqual(linked_msg, msg_id)

    def test_f6_02_photo_associated_within_15min_window(self):
        """Verifica que una foto enviada a los 8 minutos del mensaje sea vinculada en la ventana de 15 min."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981100300",
            timestamp_str="2026-10-16 12:00:00",
            texto="Reporte previo a la foto"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981100300",
            timestamp_str="2026-10-16 12:08:00",
            foto_path="data/fotos/test_window.jpg"
        )
        self.assertGreater(adj_id, 0)
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            linked_msg = cur.execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertEqual(linked_msg, msg_id)

    def test_f6_03_photo_not_associated_outside_15min_window(self):
        """Verifica que una foto enviada a los 25 minutos del mensaje NO sea vinculada al mensaje."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981100400",
            timestamp_str="2026-10-16 13:00:00",
            texto="Reporte lejano"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981100400",
            timestamp_str="2026-10-16 13:25:00",
            foto_path="data/fotos/test_far.jpg"
        )
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            linked_msg = cur.execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertIsNone(linked_msg, "Foto fuera de ventana de 15 min no debe vincularse al mensaje anterior.")

    def test_f6_04_photo_different_sender_not_associated(self):
        """Verifica que una foto no se asocie a un mensaje de otro remitente aunque coincida el timestamp."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981111111",
            timestamp_str="2026-10-16 14:00:00",
            texto="Mensaje remitente A"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595982222222",
            timestamp_str="2026-10-16 14:00:00",
            foto_path="data/fotos/test_other_sender.jpg"
        )
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            linked_msg = cur.execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertNotEqual(linked_msg, msg_id)

    def test_f6_05_adjuntos_multimedia_record_created_with_metadata(self):
        """Verifica que adjuntos_multimedia contenga tipo, ruta, y timestamp_captura."""
        fake_path = os.path.join(self.photos_dir, "meta_test.jpg")
        with open(fake_path, "wb") as f:
            f.write(b"1234567890")

        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595983000999",
            timestamp_str="2026-10-16 15:00:00",
            foto_path=fake_path
        )
        with sqlite3.connect(self.migrated_db) as conn:
            cur = conn.cursor()
            row = cur.execute("SELECT tipo, ruta_archivo, tamano_bytes, timestamp_captura FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()
            self.assertEqual(row[0], "imagen")
            self.assertEqual(row[1], fake_path)
            self.assertEqual(row[2], 10)
            self.assertEqual(row[3], "2026-10-16 15:00:00")

    # --------------------------------------------------------------------------
    # F7: WhatsApp Chat History API
    # --------------------------------------------------------------------------
    def test_f7_01_chat_history_by_station_name(self):
        """Verifica que get_station_chat_history retorne el historial consultando por nombre de estación."""
        chat_ayolas = self.store.get_station_chat_history("Ayolas")
        self.assertIsNotNone(chat_ayolas["estacion"])
        self.assertEqual(chat_ayolas["estacion"]["nombre"], "Ayolas")
        self.assertGreater(len(chat_ayolas["mensajes"]), 0)

    def test_f7_02_chat_history_by_station_id(self):
        """Verifica que get_station_chat_history retorne el mismo historial consultando por ID numérico."""
        ayolas_info = self.store.get_station_chat_history("Ayolas")
        ayolas_id = ayolas_info["estacion"]["id"]
        chat_by_id = self.store.get_station_chat_history(ayolas_id)
        self.assertEqual(chat_by_id["estacion"]["id"], ayolas_id)
        self.assertEqual(len(chat_by_id["mensajes"]), len(ayolas_info["mensajes"]))

    def test_f7_03_chat_history_nonexistent_station(self):
        """Verifica que una estación no registrada devuelva estacion: None y lista vacía sin arrojar error."""
        res = self.store.get_station_chat_history("EstacionInexistenteF7")
        self.assertIsNone(res["estacion"])
        self.assertEqual(res["mensajes"], [])

    def test_f7_04_chat_history_chronological_ordering(self):
        """Verifica que los mensajes en el chat de estación estén ordenados cronológicamente ascendentes."""
        chat = self.store.get_station_chat_history("Ayolas", limit=50)
        mensajes = chat["mensajes"]
        if len(mensajes) >= 2:
            timestamps = [m["timestamp_mensaje"] for m in mensajes if m["timestamp_mensaje"]]
            sorted_timestamps = sorted(timestamps)
            self.assertEqual(timestamps, sorted_timestamps, "Los mensajes del chat deben estar ordenados cronológicamente.")

    def test_f7_05_chat_history_includes_hydro_badges_and_photos(self):
        """Verifica que los mensajes del historial incluyan valor métrico, tendencia y foto si aplica."""
        chat = self.store.get_station_chat_history("Ayolas", limit=100)
        found_level = any(m.get("valor_metros") is not None for m in chat["mensajes"])
        found_photo = any(m.get("foto_path") for m in chat["mensajes"])
        self.assertTrue(found_level, "El chat de Ayolas debe contener al menos una medición con nivel numérico.")
        self.assertTrue(found_photo, "El chat de Ayolas debe contener al menos un mensaje con foto adjunta.")

    # --------------------------------------------------------------------------
    # F8: WhatsApp Chat Viewer UI Rendering
    # --------------------------------------------------------------------------
    def test_f8_01_modal_whatsapp_chat_container_present(self):
        """Verifica que el contenedor modal de WhatsApp Web esté presente en el HTML del dashboard."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn('id="modal-whatsapp-chat"', html)

    def test_f8_02_whatsapp_chat_bubbles_and_tails(self):
        """Verifica las clases CSS de burbujas de WhatsApp Web (.wpp-chat-bubble, incoming, outgoing)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("wpp-chat-bubble", html)
        self.assertIn("incoming", html)
        self.assertIn("outgoing", html)
        self.assertIn("wpp-bubble-wrapper", html)

    def test_f8_03_date_divider_badges(self):
        """Verifica la presencia de insignias divisoras de fecha estilo WhatsApp (wpp-date-divider)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("wpp-date-divider", html)

    def test_f8_04_photo_preview_and_lightbox_modal(self):
        """Verifica la vista previa de fotos en burbujas y el modal lightbox (#modal-lightbox)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("wpp-photo-preview", html)
        self.assertIn('id="modal-lightbox"', html)

    def test_f8_05_station_switcher_select_present(self):
        """Verifica el selector de estación integrado en el encabezado del visor de chat."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn('id="chat-estacion-select"', html)

    # --------------------------------------------------------------------------
    # F9: Dashboard Top KPI Removal
    # --------------------------------------------------------------------------
    def test_f9_01_kpi_grid_absent_from_dashboard(self):
        """Verifica que la cuadrícula .kpi-grid esté completamente eliminada del dashboard (R4)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertNotIn("kpi-grid", html)

    def test_f9_02_kpi_cards_absent_from_dashboard(self):
        """Verifica que las tarjetas individuales .kpi-card estén completamente eliminadas (R4)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertNotIn("kpi-card", html)

    def test_f9_03_kpi_total_and_estaciones_absent(self):
        """Verifica que los selectores de totales numéricos de KPIs hayan sido retirados (R4)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertNotIn("kpi-total", html)
        self.assertNotIn("kpi-estaciones", html)

    def test_f9_04_actualizar_kpis_function_absent(self):
        """Verifica que la función JavaScript obsoleta actualizarKPIs no exista en el frontend (R4)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertNotIn("actualizarKPIs", html)

    def test_f9_05_clean_layout_focuses_on_map_and_table(self):
        """Verifica que la página principal renderice directamente el mapa y la tabla de catálogo."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("mapa-estaciones", html)
        self.assertIn("tabla-body", html)
        self.assertIn("table-container", html)


    # --------------------------------------------------------------------------
    # F10: Interactive Map Catalog & Navigation
    # --------------------------------------------------------------------------
    def test_f10_01_mapa_estaciones_div_present(self):
        """Verifica la presencia del div principal para el mapa interactivo (#mapa-estaciones)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn('id="mapa-estaciones"', html)

    def test_f10_02_leaflet_css_and_js_included(self):
        """Verifica que los recursos de Leaflet.js y Leaflet CSS estén incluidos en el head."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("leaflet.js", html)
        self.assertIn("leaflet.css", html)

    def test_f10_03_cartodb_dark_tiles_configured(self):
        """Verifica que la capa de mosaicos oscuros CartoDB esté configurada en los scripts."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("cartocdn.com", html)
        self.assertIn("L.tileLayer", html)

    def test_f10_04_map_marker_click_opens_chat_modal(self):
        """Verifica que el script del mapa configure la interacción para abrir el chat de la estación."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        html = req.read().decode("utf-8")
        self.assertIn("abrirChatEstacion", html)

    def test_f10_05_api_estaciones_serves_valid_coordinates(self):
        """Verifica que el endpoint /api/estaciones sirva coordenadas geográficas válidas."""
        req = urllib.request.urlopen(f"{self.base_url}/api/estaciones")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        ayolas = next((s for s in data if s["nombre"] == "Ayolas"), None)
        self.assertIsNotNone(ayolas)
        self.assertIsNotNone(ayolas["latitud"])
        self.assertIsNotNone(ayolas["longitud"])


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES
# ==============================================================================

class TestTier2BoundaryAndEdgeCases(unittest.TestCase):
    """
    Tier 2: Boundary, corner, and adversarial stress conditions.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "tier2_edge.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        os.makedirs(self.photos_dir, exist_ok=True)
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)
        self.agent = MeasurementAgent(api_key=None, store=self.store)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_tier2_01_zero_gauge_level_preserved(self):
        """Nivel 0.00m es un valor físico válido (nivel de referencia) y no debe tratarse como falsy."""
        mid = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981001001",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=0.0
        )
        with sqlite3.connect(self.db_path) as conn:
            row = conn.cursor().execute("SELECT valor_metros, valor_cm FROM mediciones WHERE id = ?", (mid,)).fetchone()
            self.assertEqual(row[0], 0.0)
            self.assertEqual(row[1], 0.0)

    def test_tier2_02_negative_gauge_level_preserved(self):
        """Nivel negativo -0.25m (estiaje severo) debe guardarse con signo negativo en metros y cm."""
        mid = self.store.save_measurement(
            estacion_detectada="Asunción",
            remitente_telefono="595981001002",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=-0.25
        )
        with sqlite3.connect(self.db_path) as conn:
            row = conn.cursor().execute("SELECT valor_metros, valor_cm FROM mediciones WHERE id = ?", (mid,)).fetchone()
            self.assertEqual(row[0], -0.25)
            self.assertEqual(row[1], -25.0)

    def test_tier2_03_high_gauge_level_parsed(self):
        """Nivel elevado 9.85m (inundación / crecida extraordinaria) debe parsearse sin anomalías."""
        res = self.agent.fallback_parse("Pilar 9.85m crece")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["valor_metros"], 9.85)
        self.assertEqual(res["valor_cm"], 985.0)

    def test_tier2_04_exact_15_minute_window_boundary_matched(self):
        """Foto tomada exactamente a los +15 minutos (900 seg) de diferencia debe vincularse."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981002001",
            timestamp_str="2026-10-16 08:00:00",
            texto="Reporte de escala"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981002001",
            timestamp_str="2026-10-16 08:15:00",
            foto_path="data/fotos/boundary_15m.jpg"
        )
        with sqlite3.connect(self.db_path) as conn:
            linked_msg = conn.cursor().execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertEqual(linked_msg, msg_id, "+15 min exactos debe asociarse.")

    def test_tier2_05_16_minute_window_boundary_rejected(self):
        """Foto tomada a los +16 minutos de diferencia debe ser rechazada de la asociación."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981002002",
            timestamp_str="2026-10-16 08:00:00",
            texto="Reporte previo"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981002002",
            timestamp_str="2026-10-16 08:16:00",
            foto_path="data/fotos/boundary_16m.jpg"
        )
        with sqlite3.connect(self.db_path) as conn:
            linked_msg = conn.cursor().execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertIsNone(linked_msg, "+16 min excede la ventana de 15 minutos.")

    def test_tier2_06_negative_15_minute_window_boundary_matched(self):
        """Foto enviada -15 minutos ANTES del reporte de chat debe vincularse."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981002003",
            timestamp_str="2026-10-16 08:15:00",
            texto="Reporte posterior a la foto"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981002003",
            timestamp_str="2026-10-16 08:00:00",
            foto_path="data/fotos/boundary_minus_15m.jpg"
        )
        with sqlite3.connect(self.db_path) as conn:
            linked_msg = conn.cursor().execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertEqual(linked_msg, msg_id, "-15 min exactos debe asociarse.")

    def test_tier2_07_negative_16_minute_window_boundary_rejected(self):
        """Foto enviada -16 minutos antes del reporte de chat debe ser rechazada."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595981002004",
            timestamp_str="2026-10-16 08:16:00",
            texto="Reporte tardío"
        )
        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981002004",
            timestamp_str="2026-10-16 08:00:00",
            foto_path="data/fotos/boundary_minus_16m.jpg"
        )
        with sqlite3.connect(self.db_path) as conn:
            linked_msg = conn.cursor().execute("SELECT mensaje_id FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone()[0]
            self.assertIsNone(linked_msg, "-16 min excede la ventana de 15 minutos.")

    def test_tier2_08_dominance_threshold_boundary_79_percent_rejected(self):
        """Operador con dominancia del 79.9% (< 80%) no debe ser inferido automáticamente."""
        op_id = self.store.get_or_create_operator("595981003001", "Op 79%")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Ayolas'")
            ayolas_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Coratei'")
            coratei_id = cur.fetchone()[0]
            # 79 reportes Ayolas, 21 reportes Coratei -> 79% dominancia
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 79, 0)", (op_id, ayolas_id))
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 21, 0)", (op_id, coratei_id))
            conn.commit()

        inf_id = self.store.infer_operator_station("595981003001")
        self.assertIsNone(inf_id, "79% de dominancia no alcanza el umbral de 80%.")

    def test_tier2_09_dominance_threshold_boundary_80_percent_accepted(self):
        """Operador con dominancia exactamente del 80% (>= 80%) debe ser inferido."""
        op_id = self.store.get_or_create_operator("595981003002", "Op 80%")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Ayolas'")
            ayolas_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Coratei'")
            coratei_id = cur.fetchone()[0]
            # 80 reportes Ayolas, 20 reportes Coratei -> 80% dominancia
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 80, 0)", (op_id, ayolas_id))
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 20, 0)", (op_id, coratei_id))
            conn.commit()

        inf_id = self.store.infer_operator_station("595981003002")
        self.assertEqual(inf_id, ayolas_id, "80% de dominancia satisface el umbral de consistencia.")

    def test_tier2_10_single_report_not_enough_for_consistency(self):
        """Operador con un único reporte (100% dominancia pero total_reportes < 2) no debe ser inferido."""
        op_id = self.store.get_or_create_operator("595981003003", "Op 1 reporte")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cur.fetchone()[0]
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 1, 0)", (op_id, pilar_id))
            conn.commit()

        inf_id = self.store.infer_operator_station("595981003003")
        self.assertIsNone(inf_id, "Se requiere un mínimo de 2 reportes para inferir consistencia.")

    def test_tier2_11_tie_dominance_not_consistent(self):
        """Operador con empate exacto de reportes en dos estaciones no es consistente."""
        op_id = self.store.get_or_create_operator("595981003004", "Op Empate")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Humaitá'")
            humaita_id = cur.fetchone()[0]
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 10, 0)", (op_id, pilar_id))
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 10, 0)", (op_id, humaita_id))
            conn.commit()

        inf_id = self.store.infer_operator_station("595981003004")
        self.assertIsNone(inf_id, "Empate de reportes no debe inferir estación.")

    def test_tier2_12_trend_estacionado_and_variations(self):
        """Verifica que las variaciones fluviales de 'estacionado' se mapeen a ESTACIONARIO."""
        test_phrases = [
            ("Puerto Coratei 4.12 estacionado", "Coratei", 4.12, "ESTACIONARIO"),
            ("4,13 (E) estacionado", None, 4.13, "ESTACIONARIO"),
            ("Ayolas 1.85m estacionada", "Ayolas", 1.85, "ESTACIONARIO"),
            ("Pilar 3.40 estac", "Pilar", 3.40, "ESTACIONARIO"),
        ]
        for phrase, exp_station, exp_val, exp_trend in test_phrases:
            res = self.agent.fallback_parse(phrase)
            self.assertTrue(res["es_medicion_valida"])
            self.assertEqual(res["tendencia"], exp_trend)
            if exp_station:
                self.assertEqual(res["estacion"], exp_station)
            self.assertEqual(res["valor_metros"], exp_val)

    def test_tier2_13_subset_similarity_parenthesis_numbers(self):
        """Verifica que (+2) y (+12) no hagan match espurio con San Pedro 2 o San Pedro 12."""
        sim2 = compute_string_similarity("(+2)", "San Pedro 2")
        self.assertLess(sim2, 0.30, "(+2) no debe asemejarse a San Pedro 2.")

        sim12 = compute_string_similarity("(+12)", "San Pedro 12")
        self.assertLess(sim12, 0.30, "(+12) no debe asemejarse a San Pedro 12.")

    def test_tier2_14_spurious_conversational_phrases_rejected(self):
        """Verifica que frases conversacionales comunes no se extraigan como estaciones."""
        spurious_phrases = [
            "Buenos dias señor, le quería comunicarle que este era 3,50",
            "Buen dia, se mantiene en 3,80",
            "Corrección 3.25m es",
            "Buenas noches SO 2ª E Fabio Marin por esta Altura del Rio 3,65"
        ]
        for sp in spurious_phrases:
            res = self.agent.fallback_parse(sp)
            self.assertTrue(res["es_medicion_valida"])
            self.assertIsNone(res["estacion"], f"Frase no debe extraer estación espuria: {sp}")

    def test_tier2_15_extreme_text_payload_handling(self):
        """Verifica que textos largos (5,000 caracteres) y caracteres emoji no causen excepciones."""
        long_text = "🌊 Hidrometría Río Paraná 📍 " + ("palabra de reporte " * 400) + " Ayolas 2.15m crece"
        res = self.agent.fallback_parse(long_text)
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Ayolas")
        self.assertEqual(res["valor_metros"], 2.15)

    def test_tier2_16_special_characters_in_chat_api_url(self):
        """Verifica que caracteres SQL especiales en la URL de chat sean parametrizados de forma segura."""
        res = self.store.get_station_chat_history("Pilar' OR 1=1 --")
        self.assertIsNone(res["estacion"])
        self.assertEqual(res["mensajes"], [])


# ==============================================================================
# TIER 3: CROSS-FEATURE INTERACTIONS
# ==============================================================================

class TestTier3CrossFeatureInteractions(unittest.TestCase):
    """
    Tier 3: Pairwise interactions across Database, Parser, Operator Inference,
    Photo Association, and Dashboard HTTP APIs.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "tier3_cross.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        os.makedirs(self.photos_dir, exist_ok=True)
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)
        self.agent = MeasurementAgent(api_key=None, store=self.store)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_tier3_01_end_to_end_ingestion_to_chat_api(self):
        """
        Interacción: Recepción de mensaje de chat -> Inferencia de operador consistente ->
        Almacenamiento de medición y mensaje -> Vinculación de foto -> Consulta a API de chat.
        """
        # 1. Configurar operador consistente para Alberdi
        op_id = self.store.get_or_create_operator("595971999111", "Operador Alberdi")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Alberdi'")
            alberdi_id = cur.fetchone()[0]
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 10, 1)", (op_id, alberdi_id))
            conn.commit()

        # 2. Agente analiza mensaje sin nombre de estación
        parsed = self.agent.parse_message("2.80m crece", remitente_telefono="595971999111")
        self.assertEqual(parsed["estacion"], "Alberdi")
        self.assertEqual(parsed["metodo_asignacion"], "inferido_operador")

        # 3. Guardar medición en el store
        mid = self.store.save_measurement(
            estacion_detectada=parsed["estacion"],
            remitente_telefono="595971999111",
            remitente_nombre="Operador Alberdi",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=parsed["nivel"],
            tendencia_rio=parsed["tendencia"],
            metodo_asignacion=parsed["metodo_asignacion"],
            mensaje_texto="2.80m crece"
        )
        self.assertGreater(mid, 0)

        # 4. Asociar foto recibida 2 minutos después
        fake_photo = os.path.join(self.photos_dir, "alberdi_0902.jpg")
        with open(fake_photo, "wb") as f:
            f.write(b"\xff\xd8\xffalberdi")

        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595971999111",
            timestamp_str="2026-10-16 09:02:00",
            foto_path=fake_photo
        )
        self.assertGreater(adj_id, 0)

        # 5. Consultar API de chat para Alberdi
        chat_data = self.store.get_station_chat_history("Alberdi")
        self.assertEqual(chat_data["estacion"]["nombre"], "Alberdi")
        self.assertGreaterEqual(len(chat_data["mensajes"]), 1)
        last_msg = chat_data["mensajes"][-1]
        self.assertEqual(last_msg["remitente_telefono"], "595971999111")
        self.assertEqual(last_msg["remitente_nombre"], "Operador Alberdi")
        self.assertEqual(last_msg["valor_metros"], 2.80)
        self.assertEqual(last_msg["metodo_asignacion"], "inferido_operador")

    def test_tier3_02_migration_then_live_consistent_ingestion(self):
        """
        Interacción: Migración de BD histórica completa -> Ingesta de nuevo reporte en vivo
        de operador consistente migrado -> Verificación de FKs y actualización de resúmenes.
        """
        temp_mig = os.path.join(self.test_dir, "mig_live.db")
        temp_bak = os.path.join(self.test_dir, "mig_live.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_mig)

        # Migración
        res_mig = migrate_database(db_path=temp_mig, backup_path=temp_bak)
        self.assertEqual(res_mig["final_meds"], 402)

        live_store = MeasurementStore(db_path=temp_mig, photos_dir=self.photos_dir)
        live_agent = MeasurementAgent(api_key=None, store=live_store)

        # Ingesta en vivo de Fabio Marin (595972695099)
        parsed = live_agent.parse_message("3,70 estacionado", remitente_telefono="595972695099")
        self.assertEqual(parsed["estacion"], "Ayolas")
        self.assertEqual(parsed["metodo_asignacion"], "inferido_operador")

        mid = live_store.save_measurement(
            estacion_detectada=parsed["estacion"],
            remitente_telefono="595972695099",
            timestamp_medicion="2026-10-16 16:30:00",
            valor_metros=parsed["nivel"],
            tendencia_rio=parsed["tendencia"],
            metodo_asignacion=parsed["metodo_asignacion"],
            mensaje_texto="3,70 estacionado"
        )
        self.assertGreater(mid, 402)

        # Verificación de integridad de claves foráneas tras la inserción
        with sqlite3.connect(temp_mig) as conn:
            violations = conn.cursor().execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(violations), 0)

            # Total mediciones pasó a 403
            total = conn.cursor().execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
            self.assertEqual(total, 403)

    def test_tier3_03_explicit_override_with_photo_and_operator_history(self):
        """
        Interacción: Operador con historial consistente en Ayolas envía foto y texto explícito
        'Pilar 4.50m crece' -> Prioridad para Pilar, foto adjunta a Pilar, Ayolas no recibe reporte.
        """
        # Configurar operador consistente para Ayolas
        op_id = self.store.get_or_create_operator("595972695099", "Fabio Marin")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Ayolas'")
            ayolas_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cur.fetchone()[0]
            cur.execute("INSERT INTO operador_estaciones (operador_id, estacion_id, total_reportes, es_consistente) VALUES (?, ?, 20, 1)", (op_id, ayolas_id))
            conn.commit()

        # Reporte explícito Pilar
        parsed = self.agent.parse_message("Pilar 4.50m crece", remitente_telefono="595972695099")
        self.assertEqual(parsed["estacion"], "Pilar")
        self.assertEqual(parsed["metodo_asignacion"], "explicito")

        pilar_photo = os.path.join(self.photos_dir, "pilar_override.jpg")
        with open(pilar_photo, "wb") as f:
            f.write(b"pilar_photo_data")

        mid = self.store.save_measurement(
            estacion_detectada=parsed["estacion"],
            remitente_telefono="595972695099",
            timestamp_medicion="2026-10-16 10:30:00",
            valor_metros=parsed["nivel"],
            tendencia_rio=parsed["tendencia"],
            metodo_asignacion=parsed["metodo_asignacion"],
            foto_path=pilar_photo
        )

        # Verificar que la medición esté en Pilar y no en Ayolas
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            st_id = cur.execute("SELECT estacion_id FROM mediciones WHERE id = ?", (mid,)).fetchone()[0]
            self.assertEqual(st_id, pilar_id)

        chat_ayolas = self.store.get_station_chat_history("Ayolas")
        self.assertNotIn("pilar_override.jpg", [m.get("foto_path") for m in chat_ayolas["mensajes"] if m.get("foto_path")])

    def test_tier3_04_multistation_operator_clarification_flow(self):
        """
        Interacción: Operador patrulla envía primero un mensaje ambiguo sin estación (queda 'desconocido'),
        luego envía un segundo mensaje aclaratorio con estación 'Coratei 3.80m' (queda 'explicito').
        """
        op_tel = "595984621689"
        # Primer reporte ambiguo
        res1 = self.agent.parse_message("3.80m crece", remitente_telefono=op_tel)
        self.assertIsNone(res1["estacion"])
        self.assertEqual(res1["metodo_asignacion"], "desconocido")

        # Segundo reporte con nombre explícito
        res2 = self.agent.parse_message("Coratei 3.80m crece", remitente_telefono=op_tel)
        self.assertEqual(res2["estacion"], "Coratei")
        self.assertEqual(res2["metodo_asignacion"], "explicito")

    def test_tier3_05_inactive_spurious_station_isolation_across_api_and_ui(self):
        """
        Interacción: Las estaciones espurias marcadas como inactivas (es_activa = 0) no
        aparecen en /api/estaciones, y get_station_chat_history no mezcla sus historiales.
        """
        # Desactivar explícitamente estación 'Regla Foto'
        with sqlite3.connect(self.db_path) as conn:
            conn.cursor().execute("UPDATE estaciones SET es_activa = 0 WHERE nombre = 'Regla Foto'")
            conn.commit()

        active_summaries = self.store.get_stations_summary()
        self.assertNotIn("Regla Foto", [s["nombre"] for s in active_summaries])

        # Consultar chat de la estación espuria
        chat_spurious = self.store.get_station_chat_history("Regla Foto")
        self.assertEqual(chat_spurious["mensajes"], [])


# ==============================================================================
# TIER 4: REAL-WORLD HYDROMETRIC WORKLOAD SCENARIOS
# ==============================================================================

class TestTier4RealWorldScenarios(unittest.TestCase):
    """
    Tier 4: End-to-end real-world scenarios from hydrometric operations.
    Directly exercises Scenarios 1 to 6 from TEST_INFRA.md.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        os.makedirs(self.photos_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_scenario_1_historical_migration_simulation(self):
        """
        Escenario 1 (TEST_INFRA.md): Simulación de Migración Histórica.
        - Clona data/mediciones.db.bak a un entorno de prueba.
        - Ejecuta migrate_database.
        - Invariantes: 402/402 mediciones, 534/534 chats, 272/272 fotos preservadas (0 pérdidas).
        - 0 fallas en PRAGMA foreign_key_check.
        - 8 estaciones espurias saneadas a es_activa = 0.
        """
        temp_db = os.path.join(self.test_dir, "scenario1.db")
        temp_bak = os.path.join(self.test_dir, "scenario1.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_db)

        result = migrate_database(db_path=temp_db, backup_path=temp_bak)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["final_meds"], 402, "Invariante de 402 mediciones violado.")
        self.assertEqual(result["final_chats"], 534, "Invariante de 534 chats violado.")
        self.assertEqual(result["adjuntos_creados"], 272, "Invariante de 272 fotos violado.")

        with sqlite3.connect(temp_db) as conn:
            cur = conn.cursor()
            fk_check = cur.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(len(fk_check), 0, "No debe haber violaciones de clave foránea.")

            placeholders = ",".join("?" for _ in SPURIOUS_STATION_NAMES)
            active_spurious = cur.execute(
                f"SELECT COUNT(*) FROM estaciones WHERE es_activa = 1 AND nombre IN ({placeholders})",
                SPURIOUS_STATION_NAMES
            ).fetchone()[0]
            self.assertEqual(active_spurious, 0, "Todas las 8 estaciones espurias deben estar inactivas.")

    def test_scenario_2_single_station_operator_daily_report(self):
        """
        Escenario 2 (TEST_INFRA.md): Reporte diario de operador de estación única.
        - Fabio Marin (595972695099) envía '3,45 creciendo' sin mencionar el nombre de la estación.
        - El sistema infiere automáticamente que pertenece a Ayolas.
        - Metodo de asignación: 'inferido_operador'.
        """
        temp_db = os.path.join(self.test_dir, "scenario2.db")
        temp_bak = os.path.join(self.test_dir, "scenario2.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_db)
        migrate_database(db_path=temp_db, backup_path=temp_bak)

        store = MeasurementStore(db_path=temp_db, photos_dir=self.photos_dir)
        agent = MeasurementAgent(api_key=None, store=store)

        parsed = agent.parse_message("3,45 creciendo", remitente_telefono="595972695099", remitente_nombre="Fabio Marin")
        self.assertTrue(parsed["es_medicion_valida"])
        self.assertEqual(parsed["estacion"], "Ayolas")
        self.assertEqual(parsed["inferred_station"], "Ayolas")
        self.assertEqual(parsed["metodo_asignacion"], "inferido_operador")
        self.assertEqual(parsed["nivel"], 3.45)
        self.assertEqual(parsed["tendencia"], "CRECE")

    def test_scenario_3_multistation_guard_report_without_station(self):
        """
        Escenario 3 (TEST_INFRA.md): Reporte de guardia de patrulla sin estación.
        - Juan Domínguez (595984621689) envía '3,45' sin nombre de estación.
        - Al tener historial en múltiples estaciones, NO debe asignarse a ciegas.
        - Metodo de asignación: 'desconocido', estacion: None.
        """
        temp_db = os.path.join(self.test_dir, "scenario3.db")
        temp_bak = os.path.join(self.test_dir, "scenario3.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_db)
        migrate_database(db_path=temp_db, backup_path=temp_bak)

        store = MeasurementStore(db_path=temp_db, photos_dir=self.photos_dir)
        agent = MeasurementAgent(api_key=None, store=store)

        parsed = agent.parse_message("3,45", remitente_telefono="595984621689", remitente_nombre="Juan Domínguez")
        self.assertTrue(parsed["es_medicion_valida"])
        self.assertIsNone(parsed["estacion"], "Operador móvil no debe asignarse ciegamente a una estación.")
        self.assertIsNone(parsed["inferred_station"])
        self.assertEqual(parsed["metodo_asignacion"], "desconocido")
        self.assertEqual(parsed["nivel"], 3.45)

    def test_scenario_4_photo_sent_3_minutes_after_measurement(self):
        """
        Escenario 4 (TEST_INFRA.md): Foto enviada 3 minutos después de la medición.
        - Remitente envía medición a las 08:00:00.
        - Remitente envía foto de regla a las 08:03:00.
        - La foto debe quedar vinculada biunívocamente a la medición y visible en el chat de la estación.
        """
        temp_db = os.path.join(self.test_dir, "scenario4.db")
        temp_bak = os.path.join(self.test_dir, "scenario4.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_db)
        migrate_database(db_path=temp_db, backup_path=temp_bak)

        store = MeasurementStore(db_path=temp_db, photos_dir=self.photos_dir)

        # 1. Medición guardada
        mid = store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595972695099",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=1.85,
            mensaje_texto="Ayolas 1.85m estacionado"
        )

        # 2. Foto guardada 3 minutos después
        photo_file = os.path.join(self.photos_dir, "ayolas_0803.jpg")
        with open(photo_file, "wb") as f:
            f.write(b"fake_jpeg_content_regla")

        adj_id = store.associate_photo_to_message(
            remitente_telefono="595972695099",
            timestamp_str="2026-10-16 08:03:00",
            foto_path=photo_file
        )
        self.assertGreater(adj_id, 0)

        # 3. Verificar que get_station_chat_history incluya la foto vinculada
        chat_ayolas = store.get_station_chat_history("Ayolas", limit=300)
        found = any(m.get("foto_path") == photo_file for m in chat_ayolas["mensajes"])
        self.assertTrue(found, "La foto de las 08:03:00 debe aparecer integrada en el chat de Ayolas.")


    def test_scenario_5_operator_switching_stations_explicitly(self):
        """
        Escenario 5 (TEST_INFRA.md): Operador cambiando de estación explícitamente.
        - Fabio Marin (habitual de Ayolas) envía explícitamente 'Pilar 4.50m'.
        - La estación explícita tiene prioridad absoluta y se asigna a Pilar.
        - Metodo de asignación: 'explicito'.
        """
        temp_db = os.path.join(self.test_dir, "scenario5.db")
        temp_bak = os.path.join(self.test_dir, "scenario5.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_db)
        migrate_database(db_path=temp_db, backup_path=temp_bak)

        store = MeasurementStore(db_path=temp_db, photos_dir=self.photos_dir)
        agent = MeasurementAgent(api_key=None, store=store)

        parsed = agent.parse_message("Pilar 4.50m", remitente_telefono="595972695099")
        self.assertTrue(parsed["es_medicion_valida"])
        self.assertEqual(parsed["estacion"], "Pilar")
        self.assertEqual(parsed["metodo_asignacion"], "explicito")
        self.assertIsNone(parsed["inferred_station"])
        self.assertEqual(parsed["nivel"], 4.50)

    def test_scenario_6_full_dashboard_navigation_and_chat_view(self):
        """
        Escenario 6 (TEST_INFRA.md): Navegación completa en dashboard y visor de chat.
        - Servidor HTTP sirviendo la aplicación con base de datos migrada.
        - Verificación de ausencia completa de tarjetas KPI superiores.
        - Presencia del mapa interactivo y visor modal de WhatsApp.
        - Consulta exitosa al endpoint GET /api/estaciones/<nombre>/chat.
        """
        temp_db = os.path.join(self.test_dir, "scenario6.db")
        temp_bak = os.path.join(self.test_dir, "scenario6.db.bak")
        shutil.copy2(BACKUP_DB_PATH, temp_db)
        migrate_database(db_path=temp_db, backup_path=temp_bak)

        store = MeasurementStore(db_path=temp_db, photos_dir=self.photos_dir)
        DashboardHTTPHandler.store = store
        httpd = HTTPServer(("127.0.0.1", 0), DashboardHTTPHandler)
        port = httpd.server_address[1]
        base_url = f"http://127.0.0.1:{port}"

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        try:
            # 1. GET / - Verificar ausencia de KPIs y presencia de elementos requeridos
            req_home = urllib.request.urlopen(f"{base_url}/")
            self.assertEqual(req_home.status, 200)
            html = req_home.read().decode("utf-8")
            self.assertNotIn("kpi-grid", html)
            self.assertNotIn("kpi-card", html)
            self.assertNotIn("actualizarKPIs", html)
            self.assertIn("mapa-estaciones", html)
            self.assertIn("modal-whatsapp-chat", html)

            # 2. GET /api/estaciones/Ayolas/chat - Obtener flujo conversacional
            req_chat = urllib.request.urlopen(f"{base_url}/api/estaciones/Ayolas/chat")
            self.assertEqual(req_chat.status, 200)
            chat_data = json.loads(req_chat.read().decode("utf-8"))
            self.assertIsNotNone(chat_data["estacion"])
            self.assertEqual(chat_data["estacion"]["nombre"], "Ayolas")
            self.assertIsInstance(chat_data["mensajes"], list)
            self.assertGreater(len(chat_data["mensajes"]), 0)

            # Verificar que los mensajes contengan campos de chat de WhatsApp
            sample = chat_data["mensajes"][0]
            self.assertIn("remitente_telefono", sample)
            self.assertIn("timestamp_mensaje", sample)
            self.assertIn("texto", sample)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
