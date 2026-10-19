"""
tests/test_m1_empirical_stress.py
Empirical stress harness and bug reproduction suite for Milestone 1.
Tests:
- Database migration idempotency and zero-loss counts
- CRUD operations on new tables
- Operator-station inference matrix and phone number formatting
- Cross-station collision and photo association in save_measurement
- save_chat_message contract conformance
- Concurrency and transaction safety
"""

import os
import sys
import shutil
import tempfile
import sqlite3
import unittest
import threading

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bot.measurement_store import MeasurementStore, DEFAULT_SEED_STATIONS, SPURIOUS_STATION_NAMES
from scripts.migrate_database import migrate_database


class TestMigrationIdempotencyAndIntegrity(unittest.TestCase):
    """Pruebas empíricas de idempotencia e integridad del script de migración."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.live_db = os.path.join(PROJECT_ROOT, "data", "mediciones.db")
        self.backup_db = os.path.join(PROJECT_ROOT, "data", "mediciones.db.bak")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_migration_idempotency_on_live_database_copy(self):
        """
        Clona data/mediciones.db y ejecuta la migración DOS veces consecutivas.
        Verifica que la 2da ejecución no lance errores ni altere conteos de registros.
        """
        temp_db = os.path.join(self.test_dir, "cloned_mediciones.db")
        temp_bak = os.path.join(self.test_dir, "cloned_mediciones.db.bak")
        shutil.copy2(self.live_db, temp_db)

        # 1ra ejecución
        res1 = migrate_database(db_path=temp_db, backup_path=temp_bak)
        self.assertEqual(res1["status"], "success")
        self.assertEqual(res1["initial_meds"], res1["final_meds"])
        self.assertEqual(res1["initial_chats"], res1["final_chats"])

        # 2da ejecución (Idempotencia)
        res2 = migrate_database(db_path=temp_db, backup_path=temp_bak)
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["initial_meds"], res2["final_meds"])
        self.assertEqual(res2["initial_chats"], res2["final_chats"])
        self.assertEqual(res1["final_meds"], res2["final_meds"])
        self.assertEqual(res1["final_chats"], res2["final_chats"])
        self.assertEqual(res1["adjuntos_creados"], res2["adjuntos_creados"])
        self.assertEqual(res1["operadores"], res2["operadores"])

    def test_migration_from_original_backup_preserves_zero_loss_invariants(self):
        """
        Migra una copia directa de data/mediciones.db.bak (estado previo a M1)
        y verifica los invariantes exactos exigidos en PROJECT.md y ORIGINAL_REQUEST.md.
        """
        if not os.path.exists(self.backup_db):
            self.skipTest(f"Backup no encontrado en {self.backup_db}")

        test_mig_db = os.path.join(self.test_dir, "mig_from_bak.db")
        test_mig_bak = os.path.join(self.test_dir, "mig_from_bak.db.bak")
        shutil.copy2(self.backup_db, test_mig_db)

        res = migrate_database(db_path=test_mig_db, backup_path=test_mig_bak)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["final_meds"], 402, "Deben preservarse exactamente 402 mediciones")
        self.assertEqual(res["final_chats"], 534, "Deben preservarse exactamente 534 chats")
        self.assertEqual(res["adjuntos_creados"], 272, "Deben registrarse 272 adjuntos")
        self.assertEqual(res["meds_with_adj"], 272, "272 mediciones deben tener adjunto_id")
        self.assertEqual(res["meds_with_op"], 402, "402 mediciones deben tener operador_id resuelto")


class TestAdversarialFindingsAndBugs(unittest.TestCase):
    """Pruebas empíricas que exponen y reproducen los defectos encontrados en bot/measurement_store.py."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "bugs_test.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_BUG_1_save_measurement_drops_different_stations_with_same_level(self):
        """
        DEFECTO 1: Consulta de duplicados en save_measurement usa:
        (estacion_id = ? OR abs(COALESCE(valor_metros, -999) - COALESCE(?, -999)) < 0.001)
        Si un remitente reporta dos estaciones distintas con el mismo nivel (o ambas None)
        en el mismo timestamp, la 2da estación es descartada silenciosamente.
        """
        ts = "2026-10-16 08:00:00"
        sender = "595981111222"

        id1 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion=ts,
            valor_metros=2.00,
        )
        id2 = self.store.save_measurement(
            estacion_detectada="Coratei",
            remitente_telefono=sender,
            timestamp_medicion=ts,
            valor_metros=2.00,
        )

        with self.store.get_connection() as conn:
            meds = [dict(r) for r in conn.execute("SELECT id, estacion_detectada FROM mediciones").fetchall()]

        # Falla en el código actual: len(meds) es 1 en vez de 2
        self.assertEqual(
            len(meds), 2,
            f"BUG 1 CONFIRMADO: Coratei fue descartada silenciosamente por coincidencia de nivel numérico: {meds}"
        )

    def test_BUG_2_cross_station_hijacking_in_15min_window(self):
        """
        DEFECTO 2: La ventana de 15 minutos en save_measurement NO filtra por estacion_id.
        Si un operador envía foto para una estación (valor None) y a los 5 min envía reporte
        de otra estación (valor numérico), la 1ra estación es sobreescrita y reasignada a la 2da.
        """
        sender = "595981111222"
        # 08:00: Foto de regla de Ayolas
        id1 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:00:00",
            foto_path="data/fotos/ayolas.jpg",
            valor_metros=None,
        )
        # 08:05: Reporte de Pilar
        id2 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:05:00",
            valor_metros=3.50,
            mensaje_texto="Pilar 3.50m",
        )

        with self.store.get_connection() as conn:
            meds = [dict(r) for r in conn.execute("SELECT id, estacion_detectada FROM mediciones").fetchall()]

        # Falla en el código actual: Ayolas fue convertida a Pilar y len(meds) es 1
        self.assertEqual(
            len(meds), 2,
            f"BUG 2 CONFIRMADO: Ayolas fue secuestrada y sobreescrita por Pilar: {meds}"
        )

    def test_BUG_3_save_chat_message_positional_contract_drops_text(self):
        """
        DEFECTO 3: Invocar save_chat_message con la firma de PROJECT.md:
        save_chat_message(remitente_telefono, remitente_nombre, timestamp_str, texto, archivo_adjunto)
        descarta el texto y guarda texto = NULL en la base de datos.
        """
        msg_id = self.store.save_chat_message(
            "595981555666",
            "Carlos Operador",
            "2026-10-16 10:00:00",
            "Pilar 3,45m crece",
            "foto1.jpg"
        )

        with self.store.get_connection() as conn:
            row = dict(conn.execute("SELECT texto, remitente_nombre FROM mensajes_chat WHERE id = ?", (msg_id,)).fetchone())

        # Falla en el código actual: row["texto"] es None
        self.assertEqual(
            row["texto"], "Pilar 3,45m crece",
            f"BUG 3 CONFIRMADO: El texto del mensaje se perdió al usar la firma contractual: {row}"
        )

    def test_BUG_4_infer_operator_station_phone_formatting(self):
        """
        DEFECTO 4: infer_operator_station falla al comparar teléfonos con prefijo '+' o de 8-9 dígitos.
        """
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        op_id = self.store.get_or_create_operator("595981123456", "Carlos")

        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981123456",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.50,
        )
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981123456",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=3.52,
        )

        # Invocación con '+' (formato estándar WhatsApp internacional)
        inferred = self.store.infer_operator_station("+595981123456")
        self.assertEqual(
            inferred, pilar_id,
            f"BUG 4 CONFIRMADO: infer_operator_station('+595981123456') devolvió None en vez de {pilar_id}"
        )

    def test_BUG_5_concurrent_operator_creation_crashes(self):
        """
        DEFECTO 5: get_or_create_operator carece de manejo de concurrencia y lanza
        sqlite3.IntegrityError: UNIQUE constraint failed: operadores.telefono bajo concurrencia.
        """
        errors = []

        def worker(idx):
            try:
                self.store.get_or_create_operator("595981999000", f"Op {idx}")
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(
            len(errors), 0,
            f"BUG 5 CONFIRMADO: get_or_create_operator crasheó con colisión de concurrencia: {errors}"
        )


class TestBackwardCompatibility(unittest.TestCase):
    """Pruebas de compatibilidad hacia atrás con esquemas heredados y migraciones automáticas."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "legacy.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_legacy_schema_auto_migration_on_store_init(self):
        """
        Crea una base de datos con el esquema legado mínimo (solo id, nombre, rio, alias en estaciones)
        y verifica que instanciar MeasurementStore migre automáticamente las columnas
        (latitud, longitud, codigo, cuenca, cero_escala_m, es_activa, actualizado_en)
        sin fallar en seed_stations().
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE estaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                rio TEXT,
                alias TEXT
            );
        """)
        conn.execute("INSERT INTO estaciones (nombre, rio) VALUES ('Pilar', 'Río Paraguay');")
        conn.commit()
        conn.close()

        # Al instanciar, init_db() debe aplicar ALTER TABLE y llamar seed_stations() sin error
        store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)
        with store.get_connection() as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(estaciones)").fetchall()]
        self.assertIn("latitud", cols)
        self.assertIn("longitud", cols)
        self.assertIn("codigo", cols)
        self.assertIn("cuenca", cols)
        self.assertIn("es_activa", cols)

    def test_legacy_schema_with_old_operadores_table(self):
        """
        Verifica que una base con tabla operadores previa sin columnas añadidas
        se migre correctamente al inicializar el store.
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE operadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telefono TEXT NOT NULL UNIQUE,
                nombre TEXT
            );
        """)
        conn.commit()
        conn.close()

        store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)
        with store.get_connection() as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(operadores)").fetchall()]
        self.assertIn("rol_cargo", cols)
        self.assertIn("institucion", cols)
        self.assertIn("estacion_fija_id", cols)


class TestCRUDOperationsNewTables(unittest.TestCase):
    """Pruebas funcionales de CRUD sobre las tablas mensajes_chat, adjuntos_multimedia y operadores."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "crud_test.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mensajes_chat_crud_and_signatures(self):
        # 1. Firma contractual posicional: (tel, nombre, ts, texto, archivo)
        msg_id1 = self.store.save_chat_message(
            "595981555666",
            "Carlos Operador",
            "2026-10-16 10:00:00",
            "Pilar 3,45m crece",
            "foto1.jpg"
        )
        self.assertIsInstance(msg_id1, int)
        with self.store.get_connection() as conn:
            row = dict(conn.execute("SELECT * FROM mensajes_chat WHERE id = ?", (msg_id1,)).fetchone())
            self.assertEqual(row["texto"], "Pilar 3,45m crece")
            self.assertEqual(row["remitente_nombre"], "Carlos Operador")
            self.assertEqual(row["remitente_telefono"], "595981555666")
            self.assertEqual(row["timestamp_mensaje"], "2026-10-16 10:00:00")
            self.assertEqual(row["archivo_adjunto"], "foto1.jpg")

        # 2. Firma con kwargs
        msg_id2 = self.store.save_chat_message(
            remitente_telefono="595981777888",
            remitente_nombre="Juan Perez",
            timestamp_str="2026-10-16 11:00:00",
            texto="Alberdi 4.10m estacionado"
        )
        with self.store.get_connection() as conn:
            row2 = dict(conn.execute("SELECT * FROM mensajes_chat WHERE id = ?", (msg_id2,)).fetchone())
            self.assertEqual(row2["texto"], "Alberdi 4.10m estacionado")
            self.assertEqual(row2["remitente_nombre"], "Juan Perez")

    def test_adjuntos_multimedia_crud(self):
        fake_photo = os.path.join(self.photos_dir, "test_foto.jpg")
        os.makedirs(self.photos_dir, exist_ok=True)
        with open(fake_photo, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0JFIF_fake_data")

        adj_id = self.store.associate_photo_to_message(
            remitente_telefono="595981111222",
            timestamp_str="2026-10-16 12:00:00",
            foto_path=fake_photo
        )
        self.assertIsInstance(adj_id, int)
        with self.store.get_connection() as conn:
            row = dict(conn.execute("SELECT * FROM adjuntos_multimedia WHERE id = ?", (adj_id,)).fetchone())
            self.assertEqual(row["ruta_archivo"], fake_photo)
            self.assertGreater(row["tamano_bytes"], 0)

    def test_operadores_crud(self):
        op_id = self.store.get_or_create_operator("595981333444", "Operador Prueba")
        self.assertIsInstance(op_id, int)
        op_id2 = self.store.get_or_create_operator("595981333444", "Operador Prueba Actualizado")
        self.assertEqual(op_id, op_id2)


class TestOperatorInferenceMatrix(unittest.TestCase):
    """Pruebas completas de inferencia operador-estación por teléfono, dominancia y configuración."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "infer_test.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_inference_with_phone_variations(self):
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        op_id = self.store.get_or_create_operator("595981999888", "Carlos Pilar")

        # Guardar 2 reportes para Pilar
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981999888",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.50,
        )
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981999888",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=3.52,
        )

        # Probar con variaciones de formato
        self.assertEqual(self.store.infer_operator_station("+595 981 999 888"), pilar_id)
        self.assertEqual(self.store.infer_operator_station("+595981999888"), pilar_id)
        self.assertEqual(self.store.infer_operator_station("595981999888"), pilar_id)
        self.assertEqual(self.store.infer_operator_station(op_id), pilar_id)

    def test_dominant_operator_inference(self):
        ayolas_id, _ = self.store.get_or_create_station("Ayolas")
        op_id = self.store.get_or_create_operator("595972695099", "Fabio Marin")
        for i in range(5):
            self.store.save_measurement(
                estacion_detectada="Ayolas",
                remitente_telefono="595972695099",
                timestamp_medicion=f"2026-10-16 0{i}:00:00",
                valor_metros=1.80 + i * 0.01,
            )
        self.assertEqual(self.store.infer_operator_station("595972695099"), ayolas_id)

    def test_multi_station_operator_returns_none(self):
        op_id = self.store.get_or_create_operator("595981000111", "Operador Movil")
        self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595981000111",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=1.80,
        )
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981000111",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=3.50,
        )
        # Sin dominancia clara -> None
        self.assertIsNone(self.store.infer_operator_station("595981000111"))

    def test_unknown_operator_returns_none(self):
        self.assertIsNone(self.store.infer_operator_station("595999999999"))

    def test_fixed_station_override(self):
        concepcion_id, _ = self.store.get_or_create_station("Concepción")
        op_id = self.store.get_or_create_operator("595981222333", "Prefectura Concepción")
        with self.store.get_connection() as conn:
            conn.execute("UPDATE operadores SET estacion_fija_id = ? WHERE id = ?", (concepcion_id, op_id))
            conn.commit()
        # Directamente asignado a estación fija incluso con 0 reportes
        self.assertEqual(self.store.infer_operator_station("595981222333"), concepcion_id)


class TestStationChatHistoryReadOnly(unittest.TestCase):
    """Pruebas de semántica de solo lectura para el visor de chat por estación."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "chat_test.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_chat_history_on_unknown_station_does_not_create_station(self):
        """DEFECTO 7: get_station_chat_history no debe mutar la tabla estaciones."""
        before_count = len(self.store.get_all_stations())
        res = self.store.get_station_chat_history("EstacionInexistente999")
        self.assertIsNone(res["estacion"])
        self.assertEqual(res["mensajes"], [])
        after_count = len(self.store.get_all_stations())
        self.assertEqual(before_count, after_count, "No debe crearse una nueva estación al consultar historial")

    def test_chat_history_returns_chronological_messages_with_photos(self):
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981555666",
            remitente_nombre="Carlos",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.50,
            mensaje_texto="Pilar 3,50m",
        )
        res = self.store.get_station_chat_history("Pilar")
        self.assertIsNotNone(res["estacion"])
        self.assertEqual(res["estacion"]["nombre"], "Pilar")
        self.assertEqual(len(res["mensajes"]), 1)
        self.assertEqual(res["mensajes"][0]["valor_metros"], 3.50)


class TestSaveMeasurementCrossStationAndDuplicateIntegrity(unittest.TestCase):
    """Pruebas adicionales de integridad y aislamiento entre estaciones en save_measurement."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "cross_test.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_same_station_exact_duplicate_updates_existing(self):
        id1 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595981111222",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=2.00,
        )
        id2 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595981111222",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=2.00,
        )
        self.assertEqual(id1, id2, "El duplicado exacto de la misma estación debe retornar el mismo ID")

    def test_15min_window_same_station_merges_photo_and_text(self):
        sender = "595981111222"
        # Foto primero a las 08:00
        id1 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:00:00",
            foto_path="data/fotos/ayolas_rule.jpg",
            valor_metros=None,
        )
        # Nivel a las 08:03 para la MISMA estación
        id2 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:03:00",
            valor_metros=2.15,
            mensaje_texto="Ayolas 2.15m estacionado",
        )
        self.assertEqual(id1, id2, "Misma estación en ventana de 15 min debe fusionar foto y texto")
        with self.store.get_connection() as conn:
            row = dict(conn.execute("SELECT * FROM mediciones WHERE id = ?", (id1,)).fetchone())
            self.assertEqual(row["valor_metros"], 2.15)
            self.assertEqual(row["foto_path"], "data/fotos/ayolas_rule.jpg")
            self.assertEqual(row["origen_dato"], "ambos")

    def test_15min_window_different_stations_do_not_merge(self):
        sender = "595981111222"
        id1 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:00:00",
            foto_path="data/fotos/ayolas_rule.jpg",
            valor_metros=None,
        )
        id2 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:04:00",
            valor_metros=3.80,
            mensaje_texto="Pilar 3.80m",
        )
        self.assertNotEqual(id1, id2, "Estaciones distintas en ventana de 15 min NO deben fusionarse")
        with self.store.get_connection() as conn:
            meds = [dict(r) for r in conn.execute("SELECT id, estacion_detectada FROM mediciones ORDER BY id ASC").fetchall()]
            self.assertEqual(len(meds), 2)
            self.assertEqual(meds[0]["estacion_detectada"], "Ayolas")
            self.assertEqual(meds[1]["estacion_detectada"], "Pilar")


if __name__ == "__main__":
    unittest.main()
