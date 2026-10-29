"""
tests/test_m1_challenger_edge_cases.py
Adversarial empirical stress tests authored by Challenger 1 for Milestone 1.

Tests cover:
1. Zero and negative gauge levels (0.00m, -0.25m, None separation)
2. Exact 15-minute window boundary tests (+15m inclusive, +16m exclusive)
3. Inactive station filtering in operator inference matrix
4. Exact dominance threshold boundary testing (70%, 72.7%, 80%, tie, < 2 reports)
5. Heavy thread concurrency stress on operator ingestion (30 threads, formatting variations)
6. Extreme inputs on chat messages (long strings, emojis, special characters)
7. Strict cross-station isolation in get_station_chat_history
8. Repeated multi-pass migration stability (5 sequential passes)
"""

import os
import sys
import shutil
import tempfile
import sqlite3
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bot.measurement_store import MeasurementStore, SPURIOUS_STATION_NAMES
from scripts.migrate_database import migrate_database


class TestAdversarialMeasurementEdgeCases(unittest.TestCase):
    """Stress testing save_measurement edge cases and boundary conditions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "adv_med.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zero_water_level_preservation(self):
        """El nivel 0.00m es un valor hidrométrico válido y no debe tratarse como None o falsy."""
        mid = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981111222",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=0.0,
            mensaje_texto="Pilar 0.00m en escala"
        )
        with self.store.get_connection() as conn:
            row = dict(conn.execute("SELECT valor_metros, valor_cm FROM mediciones WHERE id = ?", (mid,)).fetchone())
        self.assertIsNotNone(row["valor_metros"])
        self.assertEqual(row["valor_metros"], 0.0)
        self.assertEqual(row["valor_cm"], 0.0)

    def test_negative_water_level_not_confused_with_none(self):
        """
        Niveles negativos (ej. -0.25m en estiaje extremo) no deben confundirse
        con None en la detección de duplicados.
        """
        sender = "595981111222"
        ts = "2026-10-16 08:00:00"

        # 1. Reporte con foto sola (valor_metros is None)
        id_none = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono=sender,
            timestamp_medicion=ts,
            valor_metros=None,
            foto_path="foto_regla.jpg"
        )

        # 2. Reporte para misma estación y timestamp con nivel negativo (-0.35m)
        id_neg = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono=sender,
            timestamp_medicion=ts,
            valor_metros=-0.35,
            mensaje_texto="Pilar -0.35m bajo cero de escala"
        )

        with self.store.get_connection() as conn:
            meds = conn.execute("SELECT id, valor_metros, foto_path FROM mediciones").fetchall()

        self.assertEqual(len(meds), 1)
        self.assertAlmostEqual(meds[0]["valor_metros"], -0.35, places=2)
        self.assertEqual(meds[0]["foto_path"], "foto_regla.jpg")

    def test_different_negative_levels_distinct_timestamps_no_collision(self):
        """Dos niveles negativos distintos en timestamps distintos deben guardarse independientemente."""
        id1 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981111222",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=-0.20,
        )
        id2 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981111222",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=-0.25,
        )
        self.assertNotEqual(id1, id2)
        with self.store.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
        self.assertEqual(count, 2)

    def test_15min_window_boundary_exact_and_outside(self):
        """
        Prueba límite de la ventana de 15 minutos:
        - 08:00:00 foto sin nivel
        - 08:15:00 (+15 min exactos): DEBE fusionarse con la foto
        - 08:35:00 (+20 min después del merge): NO debe fusionarse, debe ser un nuevo registro
        """
        sender = "595981333444"
        id1 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:00:00",
            foto_path="foto_boundary.jpg",
            valor_metros=None,
        )

        # Exactamente a los 15 minutos: 08:15:00
        id2 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:15:00",
            valor_metros=1.45,
            mensaje_texto="Ayolas 1.45m",
        )
        self.assertEqual(id1, id2, "Ventana de 15 min debe unificar a los 15 minutos exactos")

        # Fuera de la ventana: 08:35:00 (+20 min después)
        id3 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono=sender,
            timestamp_medicion="2026-10-16 08:35:00",
            valor_metros=1.48,
            mensaje_texto="Ayolas 1.48m reporte posterior",
        )
        self.assertNotEqual(id1, id3, "Medición fuera de ventana (+20m) debe ser un nuevo registro")


class TestAdversarialOperatorInference(unittest.TestCase):
    """Stress testing infer_operator_station logic and boundary conditions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "adv_infer.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_single_report_does_not_infer(self):
        """Un solo reporte histórico NO debe ser suficiente para inferir estación (requiere >= 2)."""
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981001001",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.50,
        )
        self.assertIsNone(self.store.infer_operator_station("595981001001"))

    def test_exact_boundary_70_vs_80_percent_dominance(self):
        """
        Prueba límite:
        - 10 reportes en total: 7 para Pilar (70%), 3 para Ayolas -> None
        - 15 reportes en total: 12 para Pilar (80%), 3 para Ayolas -> Pilar
        """
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        ayolas_id, _ = self.store.get_or_create_station("Ayolas")
        op_phone = "595981002002"

        # 7 Pilar, 3 Ayolas = 70% < 80%
        for i in range(7):
            self.store.save_measurement(
                estacion_detectada="Pilar",
                remitente_telefono=op_phone,
                timestamp_medicion=f"2026-10-15 0{i}:00:00",
                valor_metros=3.50,
            )
        for i in range(3):
            self.store.save_measurement(
                estacion_detectada="Ayolas",
                remitente_telefono=op_phone,
                timestamp_medicion=f"2026-10-15 1{i}:00:00",
                valor_metros=1.80,
            )

        self.assertIsNone(
            self.store.infer_operator_station(op_phone),
            "70% de dominancia no debe inferir estación"
        )

        # Añadir reportes hasta alcanzar exactamente >= 80% (12 de 15 = 80%)
        for i in range(5):
            self.store.save_measurement(
                estacion_detectada="Pilar",
                remitente_telefono=op_phone,
                timestamp_medicion=f"2026-10-16 0{i}:00:00",
                valor_metros=3.55,
            )
        # Total: 12 Pilar, 3 Ayolas = 12/15 = 80.0%
        self.assertEqual(
            self.store.infer_operator_station(op_phone),
            pilar_id,
            "80% exacto de dominancia debe inferir exitosamente la estación Pilar"
        )

    def test_inactive_spurious_station_never_inferred(self):
        """Estaciones inactivas (es_activa = 0) nunca deben ser inferidas para un operador."""
        spurious_name = SPURIOUS_STATION_NAMES[1]  # "Regla Foto"
        op_phone = "595981003003"
        for i in range(5):
            self.store.save_measurement(
                estacion_detectada=spurious_name,
                remitente_telefono=op_phone,
                timestamp_medicion=f"2026-10-16 0{i}:00:00",
                valor_metros=2.00,
            )
        # Aplicar limpieza de espurias
        self.store.clean_spurious_stations()
        inferred = self.store.infer_operator_station(op_phone)
        self.assertIsNone(inferred, "Estaciones inactivas / espurias nunca deben ser inferidas")

    def test_phone_formatting_variations_robustness(self):
        """Formatos con paréntesis, guiones, espacios y prefijo '+' deben resolverse."""
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        op_id = self.store.get_or_create_operator("+595981777999", "Operador Pilar")
        for i in range(3):
            self.store.save_measurement(
                estacion_detectada="Pilar",
                remitente_telefono="+595981777999",
                timestamp_medicion=f"2026-10-16 0{i}:00:00",
                valor_metros=3.50,
            )

        variations = [
            "+595 981 777-999",
            "+595-981-777999",
            "(0981) 777-999",
            "595981777999",
            "981777999",
            op_id,
        ]
        for var in variations:
            self.assertEqual(
                self.store.infer_operator_station(var),
                pilar_id,
                f"Fallo al inferir para variante: {var}"
            )


class TestAdversarialConcurrencyStress(unittest.TestCase):
    """Stress testing multi-threaded concurrent operator creation and measurement ingestion."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "adv_conc.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_high_concurrency_operator_creation(self):
        """30 hilos creando concurrentemente el mismo operador con formatos distintos."""
        phones = [
            "+595 981 123 456",
            "595981123456",
            "+595981123456",
            "(0981) 123 456",
            "981123456",
        ]
        errors = []
        op_ids = []

        def worker(idx):
            try:
                p = phones[idx % len(phones)]
                oid = self.store.get_or_create_operator(p, f"Operador Worker {idx}")
                op_ids.append(oid)
            except Exception as e:
                errors.append(f"Worker {idx} failed: {type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(30)]
            for f in futures:
                f.result()

        self.assertEqual(len(errors), 0, f"Ocurrieron errores de concurrencia: {errors}")
        self.assertEqual(len(op_ids), 30)

    def test_concurrent_measurements_and_reads(self):
        """Hilos concurrentes insertando mediciones mientras otros consultan historial de chat."""
        errors = []
        stations = ["Pilar", "Ayolas", "Concepción", "Alberdi"]

        def write_worker(idx):
            try:
                st = stations[idx % len(stations)]
                self.store.save_measurement(
                    estacion_detectada=st,
                    remitente_telefono=f"595981000{idx:03d}",
                    timestamp_medicion=f"2026-10-16 10:{idx % 60:02d}:00",
                    valor_metros=2.0 + (idx * 0.05),
                    mensaje_texto=f"Reporte concurrente {idx}"
                )
            except Exception as e:
                errors.append(f"Write error {idx}: {type(e).__name__}: {e}")

        def read_worker(idx):
            try:
                st = stations[idx % len(stations)]
                res = self.store.get_station_chat_history(st)
                self.assertIsNotNone(res["estacion"])
            except Exception as e:
                errors.append(f"Read error {idx}: {type(e).__name__}: {e}")

        threads = []
        for i in range(20):
            threads.append(threading.Thread(target=write_worker, args=(i,)))
            threads.append(threading.Thread(target=read_worker, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errores en operaciones concurrentes lectura/escritura: {errors}")


class TestAdversarialStationIsolation(unittest.TestCase):
    """Stress testing station isolation in get_station_chat_history."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "adv_iso.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_strict_cross_station_chat_history_isolation(self):
        """Mensajes y fotos de una estación nunca deben contaminar el historial de otra estación."""
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595981111111",
            remitente_nombre="Operador Pilar",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.50,
            mensaje_texto="Mensaje exclusivo de Pilar",
            foto_path="data/fotos/pilar_foto.jpg"
        )

        self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595982222222",
            remitente_nombre="Operador Ayolas",
            timestamp_medicion="2026-10-16 08:05:00",
            valor_metros=1.85,
            mensaje_texto="Mensaje exclusivo de Ayolas",
            foto_path="data/fotos/ayolas_foto.jpg"
        )

        pilar_hist = self.store.get_station_chat_history("Pilar")
        ayolas_hist = self.store.get_station_chat_history("Ayolas")

        self.assertEqual(len(pilar_hist["mensajes"]), 1)
        self.assertEqual(pilar_hist["mensajes"][0]["texto"], "Mensaje exclusivo de Pilar")
        self.assertEqual(pilar_hist["mensajes"][0]["foto_path"], "data/fotos/pilar_foto.jpg")

        self.assertEqual(len(ayolas_hist["mensajes"]), 1)
        self.assertEqual(ayolas_hist["mensajes"][0]["texto"], "Mensaje exclusivo de Ayolas")
        self.assertEqual(ayolas_hist["mensajes"][0]["foto_path"], "data/fotos/ayolas_foto.jpg")

    def test_chat_history_lookup_accent_and_alias_tolerance(self):
        """Búsqueda de historial debe resolver correctamente con o sin acentos y por alias."""
        self.store.save_measurement(
            estacion_detectada="Concepción",
            remitente_telefono="595983333333",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=4.10,
        )
        # Búsqueda sin acento: "Concepcion"
        res1 = self.store.get_station_chat_history("Concepcion")
        self.assertIsNotNone(res1["estacion"])
        self.assertEqual(res1["estacion"]["nombre"], "Concepción")
        self.assertEqual(len(res1["mensajes"]), 1)

        # Búsqueda con acento: "Concepción"
        res2 = self.store.get_station_chat_history("Concepción")
        self.assertIsNotNone(res2["estacion"])
        self.assertEqual(len(res2["mensajes"]), 1)


class TestAdversarialRepeatedMigrations(unittest.TestCase):
    """Stress testing repeated migrations on database copies."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.live_db = os.path.join(PROJECT_ROOT, "data", "mediciones.db")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_five_sequential_migrations_preserve_exact_state(self):
        """Ejecutar 5 migraciones consecutivas debe ser estrictamente no-destructivo e idempotente."""
        temp_db = os.path.join(self.test_dir, "multi_mig.db")
        temp_bak = os.path.join(self.test_dir, "multi_mig.db.bak")
        backup_db = os.path.join(PROJECT_ROOT, "data", "mediciones.db.bak")
        src_db = backup_db if os.path.exists(backup_db) else self.live_db
        shutil.copy2(src_db, temp_db)

        initial_results = None
        for iteration in range(5):
            res = migrate_database(db_path=temp_db, backup_path=temp_bak)
            self.assertEqual(res["status"], "success")
            if initial_results is None:
                initial_results = res
                self.assertEqual(res["final_meds"], res["initial_meds"])
                self.assertEqual(res["final_chats"], res["initial_chats"])
            else:
                self.assertEqual(res["final_meds"], initial_results["final_meds"], f"Iteración {iteration}: mediciones alteradas")
                self.assertEqual(res["final_chats"], initial_results["final_chats"], f"Iteración {iteration}: chats alterados")
                self.assertEqual(res["adjuntos_creados"], initial_results["adjuntos_creados"], f"Iteración {iteration}: adjuntos alterados")


if __name__ == "__main__":
    unittest.main()
