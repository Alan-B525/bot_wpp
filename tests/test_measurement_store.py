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

        # 4. Rechazo de creación si allow_create=False (por defecto)
        res_none = self.store.get_or_create_station("Puerto Nuevo Desconocido", river="Río Paraná")
        self.assertIsNone(res_none)

        # 5. Creación explícita si allow_create=True
        st_id_new, name_new = self.store.get_or_create_station("Puerto Nuevo Desconocido", river="Río Paraná", allow_create=True)
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

    def test_export_to_excel_and_discarded_exclusion(self):
        import openpyxl
        # Medición normal
        id1 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=3.45,
        )
        # Medición descartada
        id2 = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=1.85,
        )
        self.store.update_measurement(id2, estado_revision="DESCARTADO")

        xlsx_path = os.path.join(self.test_dir, "export_test.xlsx")
        self.store.export_to_excel(xlsx_path)
        self.assertTrue(os.path.exists(xlsx_path))

        wb = openpyxl.load_workbook(xlsx_path)
        sheet = wb.active
        # Exactamente 3 columnas en encabezado: Fecha, Estación, Medición
        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(headers, ["Fecha", "Estación", "Medición"])

        # Verificar contenido de filas
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        # Debe contener Pilar y NO Ayolas (descartado)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "Pilar")
        self.assertEqual(rows[0][2], 3.45)

        # También verificar CSV con minimal=True
        csv_path = os.path.join(self.test_dir, "export_minimal.csv")
        self.store.export_to_csv(csv_path, minimal=True)
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            csv_lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(csv_lines[0], "Fecha,Estación,Medición")
        self.assertIn("Pilar", csv_lines[1])
        self.assertNotIn("Ayolas", "".join(csv_lines))

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

    def test_ia_immutability_on_update_measurement(self):
        """Verifica que update_measurement actualice campos oficiales sin tocar los campos ia_*."""
        meas_id = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=3.45,
            tendencia_rio="CRECE",
            ia_estacion_detectada="Pilar",
            ia_valor_metros=3.45,
            ia_tendencia="CRECE",
            ia_confianza="alta",
        )

        humaita_id, _ = self.store.get_or_create_station("Humaitá")
        updated = self.store.update_measurement(
            measurement_id=meas_id,
            station_id=humaita_id,
            valor_metros=4.12,
            tendencia_rio="BAJA",
            estado_revision="CORREGIDO",
        )

        self.assertIsNotNone(updated)
        # Campos oficiales modificados
        self.assertEqual(updated["estacion_id"], humaita_id)
        self.assertEqual(updated["estacion_detectada"], "Humaitá")
        self.assertEqual(updated["valor_metros"], 4.12)
        self.assertEqual(updated["valor_cm"], 412.0)
        self.assertEqual(updated["tendencia_rio"], "BAJA")
        self.assertEqual(updated["estado_revision"], "CORREGIDO")
        self.assertIsNotNone(updated["actualizado_en"])

        # Campos IA inmutables
        self.assertEqual(updated["ia_estacion_detectada"], "Pilar")
        self.assertEqual(updated["ia_valor_metros"], 3.45)
        self.assertEqual(updated["ia_tendencia"], "CRECE")
        self.assertEqual(updated["ia_confianza"], "alta")

    def test_unmatched_station_stores_null_and_pendiente(self):
        """Si la estación no se reconoce y allow_create=False, estacion_id debe ser NULL y estado_revision 'PENDIENTE'."""
        meas_id = self.store.save_measurement(
            estacion_detectada="Estacion Inexistente XYZ",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 11:00:00",
            valor_metros=2.50,
        )
        with self.store.get_connection() as conn:
            row = conn.execute("SELECT estacion_id, estado_revision FROM mediciones WHERE id = ?", (meas_id,)).fetchone()
            self.assertIsNone(row["estacion_id"])
            self.assertEqual(row["estado_revision"], "PENDIENTE")

            # Catálogo estaciones no contaminado
            st_count = conn.execute("SELECT COUNT(*) FROM estaciones WHERE nombre = 'Estacion Inexistente XYZ'").fetchone()[0]
            self.assertEqual(st_count, 0)

    def test_operator_pinning_in_update_measurement(self):
        """Verifica que fijar_operador=True actualice operadores.estacion_fija_id y operador_estaciones."""
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        meas_id = self.store.save_measurement(
            estacion_detectada="Desconocida",
            remitente_telefono="595972000111",
            timestamp_medicion="2026-10-16 12:00:00",
            valor_metros=2.0,
        )

        self.store.update_measurement(
            measurement_id=meas_id,
            station_id=pilar_id,
            fijar_operador=True,
        )

        with self.store.get_connection() as conn:
            op_row = conn.execute("SELECT estacion_fija_id FROM operadores WHERE telefono = '595972000111'").fetchone()
            self.assertEqual(op_row["estacion_fija_id"], pilar_id)

        inferred = self.store.infer_operator_station("595972000111")
        self.assertEqual(inferred, pilar_id)

    def test_create_manual_measurement_from_message(self):
        """Verifica la creación manual vinculada a un chat con origen manual y campos IA en NULL."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595972999888",
            timestamp_str="2026-10-16 13:00:00",
            texto="Nivel en Pilar 3.80m crece",
        )
        pilar_id, _ = self.store.get_or_create_station("Pilar")
        new_id = self.store.create_manual_measurement_from_message(
            mensaje_id=msg_id,
            station_id=pilar_id,
            valor_metros=3.80,
            tendencia_rio="CRECE",
            estado_revision="VALIDADO",
            observaciones="Carga manual de prueba",
        )
        self.assertIsInstance(new_id, int)

        with self.store.get_connection() as conn:
            m = conn.execute("SELECT * FROM mediciones WHERE id = ?", (new_id,)).fetchone()
            self.assertEqual(m["origen_dato"], "manual")
            self.assertEqual(m["metodo_asignacion"], "manual")
            self.assertEqual(m["valor_metros"], 3.80)
            self.assertEqual(m["valor_cm"], 380.0)
            self.assertEqual(m["tendencia_rio"], "CRECE")
            self.assertEqual(m["estado_revision"], "VALIDADO")
            self.assertEqual(m["observaciones_ia"], "Carga manual de prueba")
            self.assertIsNone(m["ia_estacion_detectada"])
            self.assertIsNone(m["ia_valor_metros"])
            self.assertIsNone(m["ia_tendencia"])
            self.assertIsNone(m["ia_confianza"])

    def test_soft_delete_and_query_by_status(self):
        """Verifica soft delete a 'DESCARTADO' y filtrado por estado_revision en query_measurements."""
        m1 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 14:00:00",
            valor_metros=3.50,
            estado_revision="VALIDADO",
        )
        m2 = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 14:05:00",
            valor_metros=3.52,
            estado_revision="VALIDADO",
        )

        deleted = self.store.delete_measurement(m2, soft=True)
        self.assertTrue(deleted)

        # Filtrar solo 'VALIDADO'
        valid_list = self.store.query_measurements(estacion_nombre="Pilar", estado_revision="VALIDADO")
        valid_ids = [x["id"] for x in valid_list]
        self.assertIn(m1, valid_ids)
        self.assertNotIn(m2, valid_ids)

        # Filtrar solo 'DESCARTADO'
        discard_list = self.store.query_measurements(estacion_nombre="Pilar", estado_revision="DESCARTADO")
        discard_ids = [x["id"] for x in discard_list]
        self.assertIn(m2, discard_ids)

        # Filtrar 'TODOS'
        all_list = self.store.query_measurements(estacion_nombre="Pilar", estado_revision="TODOS")
        all_ids = [x["id"] for x in all_list]
        self.assertIn(m1, all_ids)
        self.assertIn(m2, all_ids)

        # Hard delete de m2
        hard_deleted = self.store.delete_measurement(m2, soft=False)
        self.assertTrue(hard_deleted)
        with self.store.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM mediciones WHERE id = ?", (m2,)).fetchone()[0]
            self.assertEqual(count, 0)

    def test_add_station_and_fuzzy_match(self):
        """Verifica que add_station cree una nueva estación y sea reconocible por fuzzy matching."""
        st = self.store.add_station(
            nombre="Puerto Atinguy",
            rio="Brazo Aña Cuá",
            latitud=-27.35,
            longitud=-56.80,
            alias="Atinguy, Pto Atinguy"
        )
        self.assertEqual(st["nombre"], "Puerto Atinguy")
        self.assertEqual(st["rio"], "Brazo Aña Cuá")
        self.assertEqual(st["latitud"], -27.35)
        self.assertEqual(st["es_activa"], 1)
        self.assertIn("Atinguy", st["alias"])

        # Fuzzy match
        match = self.store.get_or_create_station("Pto Atinguy")
        self.assertIsNotNone(match)
        self.assertEqual(match[1], "Puerto Atinguy")

    def test_clean_distant_stations_deactivates_non_regional(self):
        """Verifica que clean_distant_stations desactive estaciones fuera de la región Ayolas sin mediciones."""
        # Insertar una estación lejana sin mediciones
        with self.store.get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO estaciones (nombre, rio, es_activa) VALUES ('Estacion Lejana Test', 'Río Amazonas', 1)")
            conn.commit()

        deactivated = self.store.clean_distant_stations()
        self.assertGreaterEqual(deactivated, 1)

        with self.store.get_connection() as conn:
            row = conn.execute("SELECT es_activa FROM estaciones WHERE nombre = 'Estacion Lejana Test'").fetchone()
            self.assertEqual(row[0], 0)


if __name__ == "__main__":
    unittest.main()
