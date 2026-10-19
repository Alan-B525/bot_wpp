import os
import shutil
import tempfile
import unittest
from datetime import datetime

from bot.measurement_store import MeasurementStore, normalize_text_for_comparison, compute_string_similarity


class TestMeasurementStore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_mediciones.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_database_tables_and_indexes_created(self):
        with self.store.get_connection() as conn:
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("estaciones", tables)
            self.assertIn("mediciones", tables)

            indexes = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
            self.assertIn("idx_mediciones_estacion", indexes)
            self.assertIn("idx_mediciones_fecha", indexes)
            self.assertIn("idx_mediciones_telefono", indexes)

    def test_seed_stations_populated(self):
        stations = self.store.get_all_stations()
        self.assertGreater(len(stations), 10)
        station_names = [s["nombre"] for s in stations]
        self.assertIn("Pilar", station_names)
        self.assertIn("Ayolas", station_names)
        self.assertIn("Alberdi", station_names)
        self.assertIn("Concepción", station_names)

    def test_normalize_text_for_comparison(self):
        self.assertEqual(normalize_text_for_comparison("Puerto Pilar"), "pilar")
        self.assertEqual(normalize_text_for_comparison("Pto. Ayolas"), "ayolas")
        self.assertEqual(normalize_text_for_comparison("Escala Alberdi"), "alberdi")
        self.assertEqual(normalize_text_for_comparison("Concepción"), "concepcion")

    def test_compute_string_similarity(self):
        self.assertGreaterEqual(compute_string_similarity("Pilar", "Pto Pilar"), 0.8)
        self.assertGreaterEqual(compute_string_similarity("Concepcion", "Concepción"), 0.95)
        self.assertLess(compute_string_similarity("Pilar", "Corrientes"), 0.4)

    def test_get_or_create_station_matching(self):
        # 1. Coincidencia exacta
        st_id1, name1 = self.store.get_or_create_station("Pilar")
        self.assertEqual(name1, "Pilar")

        # 2. Con prefijo "Pto" o "Puerto"
        st_id2, name2 = self.store.get_or_create_station("Pto Pilar")
        self.assertEqual(st_id1, st_id2)
        self.assertEqual(name2, "Pilar")

        # 3. Sin tilde
        st_id3, name3 = self.store.get_or_create_station("Concepcion")
        self.assertEqual(name3, "Concepción")

        # 4. Creación de nueva estación desconocida
        st_id_new, name_new = self.store.get_or_create_station("Puerto Nuevo Desconocido", river="Río Paraná")
        self.assertEqual(name_new, "Puerto Nuevo Desconocido")
        self.assertIsNotNone(st_id_new)

    def test_save_photo(self):
        fake_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        path = self.store.save_photo(fake_bytes, "2026-10-16 09:30:00", "Pilar")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".jpg"))

        with open(path, "rb") as f:
            content = f.read()
        self.assertEqual(content, fake_bytes)

    def test_save_measurement_and_normalization(self):
        meas_id = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=3.45,
            unidad_detectada="m",
            tendencia_rio="CRECE",
            remitente_nombre="Operador Pilar",
        )
        self.assertIsInstance(meas_id, int)

        measurements = self.store.query_measurements(estacion_nombre="Pilar")
        self.assertEqual(len(measurements), 1)
        m = measurements[0]
        self.assertEqual(m["valor_metros"], 3.45)
        self.assertEqual(m["valor_cm"], 345.0)
        self.assertEqual(m["tendencia_rio"], "CRECE")
        self.assertEqual(m["estacion_nombre_norm"], "Pilar")

    def test_save_measurement_from_cm(self):
        meas_id = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595983322729",
            timestamp_medicion="2026-10-16 10:00:00",
            valor_cm=185.0,
            unidad_detectada="cm",
            tendencia_rio="BAJA",
        )
        m = self.store.query_measurements(estacion_nombre="Ayolas")[0]
        self.assertEqual(m["valor_cm"], 185.0)
        self.assertEqual(m["valor_metros"], 1.85)
        self.assertEqual(m["tendencia_rio"], "BAJA")

    def test_query_filters(self):
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-15 08:00:00",
            valor_metros=3.20,
        )
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.30,
        )
        self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595983322729",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=1.90,
            foto_bytes=b"fake_photo_content",
        )

        # Filtro por estación
        pilar_res = self.store.query_measurements(estacion_nombre="Pilar")
        self.assertEqual(len(pilar_res), 2)

        # Filtro por fecha desde
        fecha_res = self.store.query_measurements(fecha_desde="2026-10-16 00:00:00")
        self.assertEqual(len(fecha_res), 2)

        # Filtro solo con foto
        fotos_res = self.store.query_measurements(solo_con_foto=True)
        self.assertEqual(len(fotos_res), 1)
        self.assertEqual(fotos_res[0]["estacion_nombre_norm"], "Ayolas")

    def test_export_to_csv(self):
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.45,
            tendencia_rio="CRECE",
        )
        csv_path = os.path.join(self.test_dir, "export_test.csv")
        self.store.export_to_csv(csv_path)
        self.assertTrue(os.path.exists(csv_path))

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        self.assertIn("Pilar", content)
        self.assertIn("3.45", content)
        self.assertIn("CRECE", content)

    def test_query_filters_date_boundary_inclusion(self):
        # Medición a mitad del día (08:30)
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-15 08:30:00",
            valor_metros=3.20,
        )
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 14:00:00",
            valor_metros=3.40,
        )

        # Filtro hasta fecha YYYY-MM-DD debe incluir mediciones de ese día
        res_hasta = self.store.query_measurements(fecha_hasta="2026-10-15")
        self.assertEqual(len(res_hasta), 1)
        self.assertEqual(res_hasta[0]["timestamp_medicion"], "2026-10-15 08:30:00")

        # Filtro desde-hasta el mismo día YYYY-MM-DD
        res_mismo_dia = self.store.query_measurements(fecha_desde="2026-10-15", fecha_hasta="2026-10-15")
        self.assertEqual(len(res_mismo_dia), 1)
        self.assertEqual(res_mismo_dia[0]["timestamp_medicion"], "2026-10-15 08:30:00")

    def test_save_photo_formats(self):
        png_bytes = b"\x89PNG\r\n\x1a\nfake_png"
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBPVP8 fake_webp"

        path_png = self.store.save_photo(png_bytes, "2026-10-16 09:30:00", "Pilar")
        self.assertTrue(path_png.endswith(".png"))
        self.assertTrue(os.path.exists(path_png))

        path_webp = self.store.save_photo(webp_bytes, "2026-10-16 09:30:01", "Ayolas")
        self.assertTrue(path_webp.endswith(".webp"))
        self.assertTrue(os.path.exists(path_webp))

    def test_get_stations_summary_ignores_null_levels(self):
        # 1. Medición con nivel válido
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-15 08:00:00",
            valor_metros=3.45,
            tendencia_rio="CRECE",
        )
        # 2. Medición posterior con nivel nulo (solo foto no analizada)
        self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=None,
            tendencia_rio=None,
        )

        summary = self.store.get_stations_summary()
        pilar = next(s for s in summary if s["nombre"] == "Pilar")
        # El último nivel no debe ser nulo sino el último válido (3.45m)
        self.assertEqual(pilar["ultimo_nivel_metros"], 3.45)
        self.assertEqual(pilar["ultima_tendencia"], "CRECE")

    def test_normalized_schema_and_seed_coordinates(self):
        with self.store.get_connection() as conn:
            cur = conn.cursor()
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("operadores", tables)
            self.assertIn("operador_estaciones", tables)
            self.assertIn("adjuntos_multimedia", tables)

            # Check seed station coordinates
            cur.execute("SELECT latitud, longitud FROM estaciones WHERE nombre = 'Ayolas'")
            ayolas = cur.fetchone()
            self.assertAlmostEqual(ayolas[0], -27.4, places=1)
            self.assertAlmostEqual(ayolas[1], -56.9, places=1)

            cur.execute("SELECT latitud, longitud FROM estaciones WHERE nombre = 'Coratei'")
            coratei = cur.fetchone()
            self.assertIsNotNone(coratei)
            self.assertAlmostEqual(coratei[0], -27.42, places=2)

    def test_operator_helpers_and_inference(self):
        op_id = self.store.get_or_create_operator("595972695099", "Fabio Marin")
        self.assertIsInstance(op_id, int)

        # Before any reports, inference returns None
        inferred = self.store.infer_operator_station(op_id)
        self.assertIsNone(inferred)

        # Save 2 reports for Ayolas
        st_id, _ = self.store.get_or_create_station("Ayolas")
        self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595972695099",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=1.80,
        )
        self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595972695099",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=1.82,
        )

        inferred = self.store.infer_operator_station("595972695099")
        self.assertEqual(inferred, st_id)

        stats = self.store.get_operator_station_stats(op_id)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["total_reportes"], 2)

    def test_photo_association_and_station_chat_history(self):
        fake_bytes = b"\xff\xd8\xff\xe0JFIF_fake_image"
        photo_path = self.store.save_photo(fake_bytes, "2026-10-16 10:00:00", "Ayolas")

        # Save measurement with photo and text
        meas_id = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595983322729",
            timestamp_medicion="2026-10-16 10:00:00",
            valor_metros=1.85,
            mensaje_texto="Ayolas 1,85m",
            foto_path=photo_path,
        )
        self.assertIsInstance(meas_id, int)

        chat_data = self.store.get_station_chat_history("Ayolas")
        self.assertIsNotNone(chat_data["estacion"])
        self.assertGreaterEqual(len(chat_data["mensajes"]), 1)
        m = chat_data["mensajes"][0]
        self.assertEqual(m["valor_metros"], 1.85)
        self.assertTrue(m["foto_path"].endswith(".jpg"))

    def test_clean_spurious_stations_marked_inactive(self):
        with self.store.get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO estaciones (nombre, es_activa) VALUES ('Regla Foto', 1)")
            conn.execute("INSERT OR IGNORE INTO estaciones (nombre, es_activa) VALUES ('Estacionado', 1)")
            conn.commit()

        count = self.store.clean_spurious_stations()
        self.assertGreaterEqual(count, 0)

        summary = self.store.get_stations_summary()
        summary_names = [s["nombre"] for s in summary]
        self.assertNotIn("Regla Foto", summary_names)
        self.assertNotIn("Estacionado", summary_names)
        self.assertNotIn("Desconocida", summary_names)


if __name__ == "__main__":
    unittest.main()
