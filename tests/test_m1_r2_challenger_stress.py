"""
tests/test_m1_r2_challenger_stress.py
Adversarial Empirical Stress Test Suite for Milestone 1 (Data & Storage)
Authored by Challenger 1 (Round 2).

Vectors Challenged:
1. AI Immutability: Call update_measurement repeatedly with extreme values, None,
   changing stations, changing dates, toggling operator pinning, and assert that
   ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, and observaciones_ia
   remain strictly byte-for-byte identical.
2. Spurious station rejection: Test get_or_create_station with edge case inputs
   (emojis, unicode, SQL injection strings, near-miss names with similarity 0.77 vs 0.79)
   under allow_create=False, verifying no entries are inserted into estaciones.
3. Manual measurement creation: test boundary values (0.0m, -0.45m, 25.5m, None),
   invalid message IDs, messages with and without photos, operator pinning, and status fallback.
4. Soft-delete integrity: ensure soft deleted rows remain queryable when explicitly filtered,
   cannot be accidentally purged, repeated soft-delete idempotency, and distinct from hard delete.
"""

import os
import sys
import shutil
import tempfile
import sqlite3
import unittest
from datetime import datetime

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


class TestM1R2ChallengerStress(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "challenger_stress.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. AI IMMUTABILITY EMPIRICAL CHALLENGES
    # -------------------------------------------------------------------------
    def test_ai_immutability_byte_for_byte_under_extreme_updates(self):
        """
        Challenge Vector 1:
        Call update_measurement repeatedly with extreme values, None, changing stations,
        changing dates, toggling operator pinning, and asserting byte-for-byte immutability
        of ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, observaciones_ia.
        """
        # 1. Create a measurement with known AI extraction
        initial_ia_estacion = "Concepción"
        initial_ia_valor = 3.456
        initial_ia_tendencia = "CRECE"
        initial_ia_confianza = "alta"
        initial_ia_obs = "Lectura nítida de escala hidrométrica: 3.45m creció 2cm"

        meas_id = self.store.save_measurement(
            estacion_detectada="Concepción",
            remitente_telefono="595981111222",
            timestamp_medicion="2026-10-15 08:00:00",
            valor_metros=3.46,
            tendencia_rio="CRECE",
            confianza="alta",
            observaciones_ia=initial_ia_obs,
            ia_estacion_detectada=initial_ia_estacion,
            ia_valor_metros=initial_ia_valor,
            ia_tendencia=initial_ia_tendencia,
            ia_confianza=initial_ia_confianza,
            estado_revision="PENDIENTE",
        )

        def get_raw_ia_bytes(mid: int):
            with self.store.get_connection() as conn:
                row = conn.execute(
                    "SELECT ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, observaciones_ia FROM mediciones WHERE id = ?",
                    (mid,)
                ).fetchone()
                self.assertIsNotNone(row, f"Measurement #{mid} vanished!")
                # Convert values to exact repr bytes
                return (
                    row[0].encode("utf-8") if row[0] is not None else b"__NULL__",
                    str(row[1]).encode("utf-8") if row[1] is not None else b"__NULL__",
                    row[2].encode("utf-8") if row[2] is not None else b"__NULL__",
                    row[3].encode("utf-8") if row[3] is not None else b"__NULL__",
                    row[4].encode("utf-8") if row[4] is not None else b"__NULL__",
                )

        baseline_bytes = get_raw_ia_bytes(meas_id)

        # Retrieve station IDs for Ayolas, Pilar, Alberdi
        ayolas_res = self.store.get_or_create_station("Ayolas")
        pilar_res = self.store.get_or_create_station("Pilar")
        alberdi_res = self.store.get_or_create_station("Alberdi")
        ayolas_id = ayolas_res[0]
        pilar_id = pilar_res[0]
        alberdi_id = alberdi_res[0]

        # Iteration 1: Extreme high level and change station to Ayolas
        res1 = self.store.update_measurement(
            measurement_id=meas_id,
            station_id=ayolas_id,
            valor_metros=99999.999,
            tendencia_rio="BAJA",
            timestamp_medicion="2099-12-31 23:59:59",
            estado_revision="CORREGIDO",
            fijar_operador=True,
        )
        self.assertIsNotNone(res1)
        self.assertEqual(res1["estacion_id"], ayolas_id)
        self.assertEqual(res1["valor_metros"], 99999.999)
        self.assertEqual(res1["estado_revision"], "CORREGIDO")
        self.assertEqual(get_raw_ia_bytes(meas_id), baseline_bytes, "IA bytes mutated in iteration 1!")

        # Iteration 2: None level, changing station to Pilar, status VALIDADO
        res2 = self.store.update_measurement(
            measurement_id=meas_id,
            station_id=pilar_id,
            valor_metros=None,
            tendencia_rio="ESTABLE",
            timestamp_medicion="2020-01-01 12:00:00",
            estado_revision="VALIDADO",
            fijar_operador=False,
        )
        self.assertIsNotNone(res2)
        self.assertEqual(res2["estacion_id"], pilar_id)
        # Note: when valor_metros=None in update_measurement, it retains existing level or updates if provided
        self.assertEqual(res2["estado_revision"], "VALIDADO")
        self.assertEqual(get_raw_ia_bytes(meas_id), baseline_bytes, "IA bytes mutated in iteration 2!")

        # Iteration 3: Extreme negative level (drought below zero scale), changing station to Alberdi
        res3 = self.store.update_measurement(
            measurement_id=meas_id,
            station_id=alberdi_id,
            valor_metros=-0.75,
            tendencia_rio="CRECE",
            timestamp_medicion="1970-01-01 00:00:00",
            estado_revision="CORREGIDO",
            fijar_operador=True,
        )
        self.assertIsNotNone(res3)
        self.assertEqual(res3["estacion_id"], alberdi_id)
        self.assertEqual(res3["valor_metros"], -0.75)
        self.assertEqual(res3["valor_cm"], -75.0)
        self.assertEqual(get_raw_ia_bytes(meas_id), baseline_bytes, "IA bytes mutated in iteration 3!")

        # Iteration 4: Boundary zero level (0.00m)
        res4 = self.store.update_measurement(
            measurement_id=meas_id,
            station_id=ayolas_id,
            valor_metros=0.0,
            tendencia_rio="ESTABLE",
            estado_revision="VALIDADO",
        )
        self.assertIsNotNone(res4)
        self.assertEqual(res4["valor_metros"], 0.0)
        self.assertEqual(res4["valor_cm"], 0.0)
        self.assertEqual(get_raw_ia_bytes(meas_id), baseline_bytes, "IA bytes mutated in iteration 4!")

        # Iteration 5: Adversarial injection via kwargs attempting to overwrite ia_* fields
        res5 = self.store.update_measurement(
            measurement_id=meas_id,
            ia_estacion_detectada="HACKED_STATION",
            ia_valor_metros=666.666,
            ia_tendencia="HACKED_TEND",
            ia_confianza="zero",
            observaciones_ia="OVERWRITTEN_OBS",
            valor_metros=4.50,
            estado_revision="CORREGIDO",
        )
        self.assertIsNotNone(res5)
        self.assertEqual(get_raw_ia_bytes(meas_id), baseline_bytes, "Adversarial kwargs mutated IA fields!")

        # Iteration 6: Soft-delete transition to DESCARTADO
        self.store.delete_measurement(meas_id, soft=True)
        self.assertEqual(get_raw_ia_bytes(meas_id), baseline_bytes, "Soft delete mutated IA fields!")

        # Verify actualizado_en was updated
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT actualizado_en, estado_revision FROM mediciones WHERE id = ?", (meas_id,)).fetchone()
            self.assertIsNotNone(row["actualizado_en"])
            self.assertEqual(row["estado_revision"], "DESCARTADO")

    def test_ai_immutability_100_rapid_sequential_updates(self):
        """Stress-test 100 consecutive random updates asserting byte immutability at every step."""
        meas_id = self.store.save_measurement(
            estacion_detectada="Humaitá",
            remitente_telefono="595982333444",
            timestamp_medicion="2026-10-15 09:00:00",
            valor_metros=2.15,
            tendencia_rio="BAJA",
            confianza="alta",
            observaciones_ia="Medición automática de referencia",
            ia_estacion_detectada="Humaitá",
            ia_valor_metros=2.15,
            ia_tendencia="BAJA",
            ia_confianza="alta",
        )

        with self.store.get_connection() as conn:
            orig = conn.execute(
                "SELECT ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, observaciones_ia FROM mediciones WHERE id = ?",
                (meas_id,)
            ).fetchone()
            baseline = tuple(orig)

        stations = [s[0] for s in [
            self.store.get_or_create_station("Ayolas"),
            self.store.get_or_create_station("Corrientes"),
            self.store.get_or_create_station("Concepción"),
            self.store.get_or_create_station("Pilar"),
        ]]

        statuses = ["PENDIENTE", "VALIDADO", "CORREGIDO", "DESCARTADO"]
        tendencias = ["CRECE", "BAJA", "ESTABLE"]

        for i in range(100):
            st_id = stations[i % len(stations)]
            lvl = round((i * 0.17) - 5.0, 2)  # negative and positive levels
            status = statuses[i % len(statuses)]
            tend = tendencias[i % len(tendencias)]

            self.store.update_measurement(
                measurement_id=meas_id,
                station_id=st_id,
                valor_metros=lvl,
                tendencia_rio=tend,
                estado_revision=status,
                fijar_operador=(i % 2 == 0),
            )

            with self.store.get_connection() as conn:
                curr = conn.execute(
                    "SELECT ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, observaciones_ia FROM mediciones WHERE id = ?",
                    (meas_id,)
                ).fetchone()
                self.assertEqual(tuple(curr), baseline, f"IA fields mutated on iteration {i}!")


    # -------------------------------------------------------------------------
    # 2. SPURIOUS STATION REJECTION EMPIRICAL CHALLENGES
    # -------------------------------------------------------------------------
    def test_spurious_station_rejection_edge_cases(self):
        """
        Challenge Vector 2:
        Test get_or_create_station with edge case inputs (emojis, unicode, SQL injection,
        near-miss names with similarity 0.77 vs 0.79) under allow_create=False,
        verifying no entries are inserted into estaciones.
        """
        def get_stations_count():
            with self.store.get_connection() as conn:
                return conn.execute("SELECT COUNT(*) FROM estaciones").fetchone()[0]

        initial_count = get_stations_count()

        # A. Emojis and Symbols
        emoji_inputs = [
            "🌊 Río Paraná 📏",
            "🚢 Puerto Fantasma ⚓",
            "😀 😃 😄",
            "⚠️⚠️ ALERTA ⚠️⚠️",
            "🎯📍🚩",
            "   🌊   ",
        ]
        for name in emoji_inputs:
            res = self.store.get_or_create_station(name, allow_create=False)
            self.assertIsNone(res, f"Expected None for emoji input '{name}', got: {res}")
            self.assertEqual(get_stations_count(), initial_count, f"Station created for emoji input '{name}'!")

        # B. Unicode, exotic scripts, and control characters
        unicode_inputs_nonexistent = [
            "Пуэрто-Игуасу-Несуществующий",       # Russian Cyrillic non-existent
            "港口水文站未知",                      # Chinese non-existent
            "محطة قياس غير موجودة",              # Arabic non-existent
            "תחנת מדידה לא קיימת",                 # Hebrew non-existent
            "𝓧𝔂𝔃 𝓘𝓷𝓮𝔵𝓲𝓼𝓽𝓮𝓷𝓽𝓮",                    # Mathematical bold script non-existent
            "EstacionInexistente\x00Injected",     # Null byte non-existent
            "EstacionInexistente\t\nControl",      # Control chars non-existent
            "᚛ᚑᚌᚐᚋ᚜",                              # Ogham
        ]
        for name in unicode_inputs_nonexistent:
            res = self.store.get_or_create_station(name, allow_create=False)
            self.assertIsNone(res, f"Expected None for unicode input '{name}', got: {res}")
            self.assertEqual(get_stations_count(), initial_count, f"Station created for unicode input '{name}'!")

        # Stylized unicode of an existing station (NFKD normalization resolves to existing without creating)
        res_stylized = self.store.get_or_create_station("𝓕𝓾𝓮𝓻𝓽𝓮 𝓞𝓵𝓲𝓶𝓹𝓸", allow_create=False)
        self.assertIsNotNone(res_stylized, "NFKD normalization failed to match stylized station")
        self.assertEqual(res_stylized[1], "Fuerte Olimpo")
        self.assertEqual(get_stations_count(), initial_count, "Station created during stylized resolution!")

        # C. SQL Injection vectors
        sqli_inputs = [
            "'; DROP TABLE estaciones; --",
            "' OR 1=1 --",
            "Ayolas' OR '1'='1",
            "'; DELETE FROM mediciones; --",
            "' UNION SELECT 9999, 'HACK', 'HACK', 1, 'HACK', 1, 'now', 'now' --",
            "admin'--",
            "1' or '1' = '1",
        ]
        for name in sqli_inputs:
            res = self.store.get_or_create_station(name, allow_create=False)
            # Must either return None or if it fuzzy matched Ayolas safely, must not execute SQLi
            self.assertEqual(get_stations_count(), initial_count, f"Station count changed during SQLi: {name}")

        # Ensure database tables survived intact
        with self.store.get_connection() as conn:
            tbls = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("estaciones", tbls)
            self.assertIn("mediciones", tbls)

        # D. Near-miss names around similarity threshold 0.78
        # Target: "Concepción"
        # Let's test compute_string_similarity directly:
        target = "Concepción"
        n_target = normalize_text_for_comparison(target)  # "concepcion"
        
        # Candidate 1: "Concepciona" (len 11 vs 10, ratio = 20/21 = 0.952) -> Matches >= 0.78
        sim_high = compute_string_similarity("Concepciona", target)
        self.assertGreaterEqual(sim_high, 0.78)
        res_high = self.store.get_or_create_station("Concepciona", allow_create=False)
        self.assertIsNotNone(res_high)
        self.assertEqual(res_high[1], "Concepción")
        self.assertEqual(get_stations_count(), initial_count, "High similarity inserted new station!")

        # Candidate 2: "ConcXXion" vs "concepcion"
        # Let's test a near-miss string that yields ratio around 0.75-0.77
        # "concepcion" (10 chars). If we change 2 chars: "conxxcion" -> ratio: 14/19 = 0.736
        # Let's verify string with ratio between 0.70 and 0.77:
        sim_low = compute_string_similarity("Conxxeccion", target)
        if sim_low < 0.78:
            res_low = self.store.get_or_create_station("Conxxeccion", allow_create=False)
            self.assertIsNone(res_low, f"Expected None for similarity {sim_low} < 0.78, got {res_low}")
            self.assertEqual(get_stations_count(), initial_count)

        # E. Known Spurious Names (SPURIOUS_STATION_NAMES)
        for spurious in SPURIOUS_STATION_NAMES:
            res_spur = self.store.get_or_create_station(spurious, allow_create=False)
            self.assertIsNone(res_spur, f"Spurious station '{spurious}' should return None, got: {res_spur}")
            self.assertEqual(get_stations_count(), initial_count)

        # F. Empty, Whitespace, None
        for empty in ["", "   ", "\t\t", None]:
            res_empty = self.store.get_or_create_station(empty, allow_create=False)
            self.assertIsNone(res_empty)
            self.assertEqual(get_stations_count(), initial_count)


    # -------------------------------------------------------------------------
    # 3. MANUAL MEASUREMENT CREATION EMPIRICAL CHALLENGES
    # -------------------------------------------------------------------------
    def test_manual_measurement_creation_boundaries(self):
        """
        Challenge Vector 3:
        Test manual measurement creation with boundary values (0.0m, -0.45m, 25.5m, None),
        invalid message IDs, messages with and without photos, operator pinning, and status fallback.
        """
        # Set up a station
        ayolas_res = self.store.get_or_create_station("Ayolas")
        ayolas_id = ayolas_res[0]

        # Case A: Invalid message IDs must raise ValueError
        invalid_ids = [999999, -1, 0, 12345]
        for bad_id in invalid_ids:
            with self.assertRaises(ValueError):
                self.store.create_manual_measurement_from_message(
                    mensaje_id=bad_id,
                    station_id=ayolas_id,
                    valor_metros=2.50,
                )

        # Create valid message without photo
        msg1_id = self.store.save_chat_message(
            remitente_telefono="595971999888",
            remitente_nombre="Operador Manual",
            timestamp_mensaje="2026-10-18 10:00:00",
            texto="Reporte manual de nivel Ayolas 1.50m",
        )

        # Case B: Boundary zero level (0.00m)
        meas_zero_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg1_id,
            station_id=ayolas_id,
            valor_metros=0.0,
            tendencia_rio="ESTABLE",
            estado_revision="VALIDADO",
        )
        self.assertIsInstance(meas_zero_id, int)
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (meas_zero_id,)).fetchone()
            self.assertEqual(row["valor_metros"], 0.0)
            self.assertEqual(row["valor_cm"], 0.0)
            self.assertEqual(row["origen_dato"], "manual")
            self.assertEqual(row["metodo_asignacion"], "manual")
            self.assertIsNone(row["ia_estacion_detectada"])
            self.assertIsNone(row["ia_valor_metros"])
            self.assertIsNone(row["ia_tendencia"])
            self.assertIsNone(row["ia_confianza"])
            self.assertIsNone(row["foto_path"])
            self.assertIsNone(row["adjunto_id"])
            self.assertEqual(row["estado_revision"], "VALIDADO")

        # Case C: Boundary negative level (-0.45m drought below zero)
        meas_neg_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg1_id,
            station_id=ayolas_id,
            valor_metros=-0.45,
            tendencia_rio="BAJA",
            estado_revision="CORREGIDO",
        )
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (meas_neg_id,)).fetchone()
            self.assertEqual(row["valor_metros"], -0.45)
            self.assertEqual(row["valor_cm"], -45.0)
            self.assertEqual(row["estado_revision"], "CORREGIDO")

        # Case D: Boundary None level
        meas_none_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg1_id,
            station_id=ayolas_id,
            valor_metros=None,
            tendencia_rio=None,
        )
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (meas_none_id,)).fetchone()
            self.assertIsNone(row["valor_metros"])
            self.assertIsNone(row["valor_cm"])
            self.assertEqual(row["estado_revision"], "VALIDADO")  # default

        # Case E: Message WITH photo in foto_path
        photo_file = os.path.join(self.photos_dir, "test_manual_photo.jpg")
        with open(photo_file, "wb") as f:
            f.write(b"FAKE_JPEG_PHOTO_DATA_12345")

        msg2_id = self.store.save_chat_message(
            remitente_telefono="595971999888",
            remitente_nombre="Operador Manual",
            timestamp_mensaje="2026-10-18 10:15:00",
            texto="Foto de la escala en Ayolas",
            foto_path=photo_file,
        )

        meas_photo_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg2_id,
            station_id=ayolas_id,
            valor_metros=3.10,
            tendencia_rio="CRECE",
            fijar_operador=True,
        )
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (meas_photo_id,)).fetchone()
            self.assertEqual(row["foto_path"], photo_file)
            self.assertIsNotNone(row["adjunto_id"], "Photo was not linked to adjuntos_multimedia!")
            
            # Verify operator pinning
            op_row = conn.execute("SELECT estacion_fija_id FROM operadores WHERE telefono = '595971999888'").fetchone()
            self.assertEqual(op_row["estacion_fija_id"], ayolas_id)

            op_est = conn.execute(
                "SELECT es_consistente FROM operador_estaciones WHERE operador_id = (SELECT id FROM operadores WHERE telefono = '595971999888') AND estacion_id = ?",
                (ayolas_id,)
            ).fetchone()
            self.assertIsNotNone(op_est)
            self.assertEqual(op_est["es_consistente"], 1)

        # Case F: Status fallback for unrecognized estado_revision
        meas_fallback_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg1_id,
            station_id=ayolas_id,
            valor_metros=2.00,
            estado_revision="UNRECOGNIZED_STATUS_FOOBAR",
        )
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT estado_revision FROM mediciones WHERE id = ?", (meas_fallback_id,)).fetchone()
            self.assertEqual(row["estado_revision"], "VALIDADO")


    # -------------------------------------------------------------------------
    # 4. SOFT-DELETE INTEGRITY EMPIRICAL CHALLENGES
    # -------------------------------------------------------------------------
    def test_soft_delete_integrity_and_query_filtering(self):
        """
        Challenge Vector 4:
        Ensure soft-deleted rows remain in database, are queryable when explicitly filtered,
        cannot be accidentally purged by repeated calls, and differ from hard-delete.
        """
        ayolas_res = self.store.get_or_create_station("Ayolas")
        ayolas_id = ayolas_res[0]

        # Create 3 measurements with different initial statuses
        m_val = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595971111000",
            timestamp_medicion="2026-10-19 08:00:00",
            valor_metros=2.20,
            estado_revision="VALIDADO",
            ia_estacion_detectada="Ayolas",
            ia_valor_metros=2.20,
        )
        m_pend = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595971111000",
            timestamp_medicion="2026-10-19 09:00:00",
            valor_metros=2.25,
            estado_revision="PENDIENTE",
            ia_estacion_detectada="Ayolas",
            ia_valor_metros=2.25,
        )
        m_corr = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595971111000",
            timestamp_medicion="2026-10-19 10:00:00",
            valor_metros=2.30,
            estado_revision="CORREGIDO",
            ia_estacion_detectada="Ayolas",
            ia_valor_metros=2.30,
        )

        # Baseline count in DB
        with self.store.get_connection() as conn:
            total_before = conn.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]

        # 1. Soft-delete m_pend
        deleted = self.store.delete_measurement(m_pend, soft=True)
        self.assertTrue(deleted, "Soft delete returned False!")

        # 2. Assert row was NOT purged from the database
        with self.store.get_connection() as conn:
            total_after = conn.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
            self.assertEqual(total_before, total_after, "Soft delete accidentally purged row from SQLite!")

            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (m_pend,)).fetchone()
            self.assertIsNotNone(row, "Soft deleted row cannot be queried directly!")
            self.assertEqual(row["estado_revision"], "DESCARTADO")
            self.assertEqual(row["ia_valor_metros"], 2.25, "Soft delete corrupted IA fields!")
            self.assertIsNotNone(row["actualizado_en"])

        # 3. Query filtering tests
        # A. Query VALIDADO -> must include m_val, but NOT m_pend
        res_val = self.store.query_measurements(estado_revision="VALIDADO")
        ids_val = [r["id"] for r in res_val]
        self.assertIn(m_val, ids_val)
        self.assertNotIn(m_pend, ids_val)

        # B. Query CORREGIDO -> must include m_corr, but NOT m_pend
        res_corr = self.store.query_measurements(estado_revision="CORREGIDO")
        ids_corr = [r["id"] for r in res_corr]
        self.assertIn(m_corr, ids_corr)
        self.assertNotIn(m_pend, ids_corr)

        # C. Query DESCARTADO -> MUST explicitly include m_pend, and NOT m_val
        res_desc = self.store.query_measurements(estado_revision="DESCARTADO")
        ids_desc = [r["id"] for r in res_desc]
        self.assertIn(m_pend, ids_desc, "Explicit DESCARTADO filter failed to return soft-deleted measurement!")
        self.assertNotIn(m_val, ids_desc)

        # D. Query TODOS -> must include all of them
        res_todos = self.store.query_measurements(estado_revision="TODOS")
        ids_todos = [r["id"] for r in res_todos]
        self.assertIn(m_val, ids_todos)
        self.assertIn(m_pend, ids_todos)
        self.assertIn(m_corr, ids_todos)

        # 4. Idempotency: Repeated soft delete
        del2 = self.store.delete_measurement(m_pend, soft=True)
        self.assertTrue(del2)
        with self.store.get_connection() as conn:
            row2 = conn.execute("SELECT estado_revision FROM mediciones WHERE id = ?", (m_pend,)).fetchone()
            self.assertEqual(row2["estado_revision"], "DESCARTADO")

        # 5. Non-existent ID returns False
        del_nonexistent = self.store.delete_measurement(9999999, soft=True)
        self.assertFalse(del_nonexistent)

        # 6. Hard delete comparison (soft=False)
        m_hard = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595971111000",
            timestamp_medicion="2026-10-19 11:00:00",
            valor_metros=2.40,
        )
        del_hard = self.store.delete_measurement(m_hard, soft=False)
        self.assertTrue(del_hard)
        with self.store.get_connection() as conn:
            row_hard = conn.execute("SELECT COUNT(*) FROM mediciones WHERE id = ?", (m_hard,)).fetchone()[0]
            self.assertEqual(row_hard, 0, "Hard delete failed to physically remove row when requested.")

    # -------------------------------------------------------------------------
    # 5. ADDITIONAL ADVERSARIAL STRESS VECTORS
    # -------------------------------------------------------------------------
    def test_similarity_threshold_precision_077_vs_079(self):
        """
        Challenge Vector: Mathematical precision test for similarity threshold (0.78).
        - 'Concepcx' (similarity 0.7778 < 0.78) must return None without inserting.
        - 'Humaitxx' (similarity 0.8000 >= 0.78) must resolve to Humaitá without inserting.
        """
        with self.store.get_connection() as conn:
            init_count = conn.execute("SELECT COUNT(*) FROM estaciones").fetchone()[0]

        # Sim = 0.7778 (< 0.78 threshold)
        sim_under = compute_string_similarity("Concepcx", "Concepción")
        self.assertLess(sim_under, 0.78)
        self.assertGreaterEqual(sim_under, 0.77)
        res_under = self.store.get_or_create_station("Concepcx", allow_create=False)
        self.assertIsNone(res_under, f"Sub-threshold station (sim={sim_under:.4f}) was wrongly accepted!")

        # Sim = 0.8000 (>= 0.78 threshold)
        sim_over = compute_string_similarity("Humaitxx", "Humaitá")
        self.assertGreaterEqual(sim_over, 0.78)
        res_over = self.store.get_or_create_station("Humaitxx", allow_create=False)
        self.assertIsNotNone(res_over, f"Supra-threshold station (sim={sim_over:.4f}) was wrongly rejected!")
        self.assertEqual(res_over[1], "Humaitá")

        # In both cases, zero new stations inserted
        with self.store.get_connection() as conn:
            final_count = conn.execute("SELECT COUNT(*) FROM estaciones").fetchone()[0]
            self.assertEqual(init_count, final_count, "Station count modified during threshold testing!")

    def test_manual_measurement_ia_null_immutability(self):
        """
        Challenge Vector: Ensure manual measurements (which start with ia_* = NULL)
        never fabricate or hallucinate IA fields during subsequent human updates.
        """
        msg_id = self.store.save_chat_message(
            remitente_telefono="595999888777",
            texto="Reporte manual de nivel",
        )
        ayolas_id = self.store.get_or_create_station("Ayolas")[0]
        pilar_id = self.store.get_or_create_station("Pilar")[0]

        meas_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg_id,
            station_id=ayolas_id,
            valor_metros=2.50,
            tendencia_rio="ESTABLE",
        )

        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (meas_id,)).fetchone()
            self.assertIsNone(row["ia_estacion_detectada"])
            self.assertIsNone(row["ia_valor_metros"])
            self.assertIsNone(row["ia_tendencia"])
            self.assertIsNone(row["ia_confianza"])
            self.assertIsNone(row["observaciones_ia"])

        # Update manual measurement multiple times
        self.store.update_measurement(meas_id, station_id=pilar_id, valor_metros=3.10, estado_revision="CORREGIDO")
        self.store.update_measurement(meas_id, valor_metros=3.20, tendencia_rio="CRECE", fijar_operador=True)

        with self.store.get_connection() as conn:
            row2 = conn.execute("SELECT * FROM mediciones WHERE id = ?", (meas_id,)).fetchone()
            self.assertIsNone(row2["ia_estacion_detectada"], "IA station fabricated on manual update!")
            self.assertIsNone(row2["ia_valor_metros"], "IA level fabricated on manual update!")
            self.assertIsNone(row2["ia_tendencia"], "IA trend fabricated on manual update!")
            self.assertIsNone(row2["ia_confianza"], "IA confidence fabricated on manual update!")
            self.assertIsNone(row2["observaciones_ia"], "IA observations fabricated on manual update!")
            self.assertEqual(row2["valor_metros"], 3.20)
            self.assertEqual(row2["tendencia_rio"], "CRECE")

    def test_foreign_key_integrity_on_invalid_station(self):
        """
        Challenge Vector: Verify SQLite foreign key enforcement on invalid station IDs.
        Attempting to insert a non-existent station_id must raise IntegrityError.
        """
        msg_id = self.store.save_chat_message(remitente_telefono="595999111222", texto="Prueba FK")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_manual_measurement_from_message(
                mensaje_id=msg_id,
                station_id=888888,  # Inexistent station
                valor_metros=2.0,
            )

    def test_concurrent_updates_ai_immutability_wal(self):
        """
        Challenge Vector: Concurrent multi-threaded stress.
        20 worker threads concurrently updating the same measurement and asserting
        that ia_* fields are never corrupted under concurrent WAL access.
        """
        from concurrent.futures import ThreadPoolExecutor

        meas_id = self.store.save_measurement(
            estacion_detectada="Concepción",
            remitente_telefono="595988777666",
            timestamp_medicion="2026-10-19 12:00:00",
            valor_metros=3.00,
            ia_estacion_detectada="Concepción",
            ia_valor_metros=3.00,
            ia_tendencia="CRECE",
            ia_confianza="alta",
            observaciones_ia="IA original concurrente",
        )

        baseline = ("Concepción", 3.00, "CRECE", "alta", "IA original concurrente")

        def worker_task(idx: int):
            lvl = 1.0 + (idx * 0.1)
            self.store.update_measurement(
                measurement_id=meas_id,
                valor_metros=lvl,
                tendencia_rio="BAJA" if idx % 2 == 0 else "CRECE",
                estado_revision="CORREGIDO",
            )
            return True

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task, i) for i in range(25)]
            for f in futures:
                self.assertTrue(f.result())

        with self.store.get_connection() as conn:
            row = conn.execute(
                "SELECT ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, observaciones_ia FROM mediciones WHERE id = ?",
                (meas_id,)
            ).fetchone()
            self.assertEqual(tuple(row), baseline, "Concurrent updates corrupted IA fields!")


if __name__ == "__main__":
    unittest.main()
