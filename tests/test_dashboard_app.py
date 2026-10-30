import os
import io
import shutil
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import json
from http.server import HTTPServer

from bot.measurement_store import MeasurementStore
from dashboard_app import DashboardHTTPHandler


class TestDashboardApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, "dash_test.db")
        cls.photos_dir = os.path.join(cls.test_dir, "fotos")
        cls.onedrive_dir = os.path.join(cls.test_dir, "test_onedrive")
        cls.store = MeasurementStore(
            db_path=cls.db_path,
            photos_dir=cls.photos_dir,
            onedrive_export_dir=cls.onedrive_dir,
            onedrive_export_filename="med_prefectura_PY.xlsx",
        )

        # Crear una foto de prueba
        os.makedirs(cls.photos_dir, exist_ok=True)
        cls.fake_photo_filename = "test_regla.jpg"
        cls.fake_photo_path = os.path.join(cls.photos_dir, cls.fake_photo_filename)
        with open(cls.fake_photo_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0test_jpg_data")

        # Insertar medición de prueba
        cls.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984621689",
            timestamp_medicion="2026-10-16 09:00:00",
            valor_metros=3.45,
            tendencia_rio="CRECE",
            foto_path=f"data/fotos/{cls.fake_photo_filename}",
        )

        # Configurar handler con el store de prueba
        DashboardHTTPHandler.store = cls.store

        # Levantar servidor en puerto aleatorio disponible
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

    def test_dashboard_home_page(self):
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn("Monitor Hidrométrico Inteligente", html)
        self.assertIn("nivelesChart", html)

    def test_dashboard_chart_click_and_detail_modal(self):
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn("onClick: (evt, elements)", html)
        self.assertIn("abrirDetalle", html)
        self.assertIn("Corregir Estación y Medición", html)
        self.assertIn("modal-chat-stream", html)
        self.assertIn("modal-img", html)
        self.assertIn("modal-meta", html)

    def test_dashboard_table_columns_removed(self):
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        # Verificar que se quitaron Nivel (cm), Tendencia, Origen y Observación IA de los encabezados
        self.assertNotIn("<th>Nivel (cm)</th>", html)
        self.assertNotIn("<th>Tendencia</th>", html)
        self.assertNotIn("<th>Origen</th>", html)
        self.assertNotIn("<th>Observación IA</th>", html)
        # Verificar que existen las columnas requeridas y Acciones
        self.assertIn("<th>Nivel (m)</th>", html)
        self.assertIn("Acciones</th>", html)

    def test_api_contexto(self):
        # Guardar un mensaje de chat previo
        msg_id = self.store.save_chat_message(
            remitente_telefono="595984621689",
            timestamp_mensaje="2026-10-16 08:58:00",
            texto="Buen día, envío reporte",
            remitente_nombre="Operador Pilar"
        )
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones/1/contexto")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIn("medicion", data)
        self.assertIn("mensajes", data)
        self.assertGreaterEqual(len(data["mensajes"]), 1)
        first_msg = data["mensajes"][0]
        self.assertIn("mensaje_id", first_msg)
        self.assertIn("adjunto_id", first_msg)

    def test_api_editar_medicion(self):
        # Insertar medición aislada para editar sin alterar la medición 1
        test_id = self.store.save_measurement(
            estacion_detectada="Ayolas",
            remitente_telefono="595984999888",
            timestamp_medicion="2026-10-16 12:30:00",
            valor_metros=2.10,
        )
        payload = json.dumps({"estacion": "Puerto Corateí", "valor_metros": 2.45}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/{test_id}/editar",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            res_data = json.loads(response.read().decode("utf-8"))
            self.assertTrue(res_data["success"])
            self.assertEqual(res_data["medicion"]["valor_metros"], 2.45)
            self.assertIn("Corateí", res_data["medicion"]["estacion_detectada"])

    def test_api_mediciones(self):
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIsInstance(data, list)
        pilar = next((m for m in data if m["estacion_nombre_norm"] == "Pilar"), None)
        self.assertIsNotNone(pilar)
        self.assertEqual(pilar["valor_metros"], 3.45)

    def test_api_estaciones(self):
        req = urllib.request.urlopen(f"{self.base_url}/api/estaciones")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIsInstance(data, list)
        pilar = next((s for s in data if s["nombre"] == "Pilar"), None)
        self.assertIsNotNone(pilar)
        self.assertEqual(pilar["total_mediciones"], 1)

    def test_api_export_csv(self):
        req = urllib.request.urlopen(f"{self.base_url}/api/export?format=csv")
        self.assertEqual(req.status, 200)
        self.assertIn("text/csv", req.headers.get("Content-Type", ""))
        content = req.read().decode("utf-8-sig")
        self.assertIn("Pilar", content)
        self.assertIn("3.45", content)

    def test_api_export_csv_fotos_filter_and_cleanup(self):
        # Insertar medición sin foto
        self.store.save_measurement(
            estacion_detectada="Concepción",
            remitente_telefono="595984111222",
            timestamp_medicion="2026-10-16 11:00:00",
            valor_metros=2.80,
            foto_path=None,
        )

        # Exportar con fotos=true en formato CSV
        req = urllib.request.urlopen(f"{self.base_url}/api/export?fotos=true&format=csv")
        self.assertEqual(req.status, 200)
        content = req.read().decode("utf-8-sig")
        # Debe incluir Pilar (con foto) y NO Concepción (sin foto)
        self.assertIn("Pilar", content)
        self.assertNotIn("Concepción", content)

        # Verificar que no quedó archivo residual export_temp.csv
        project_temp_csv = os.path.join(os.getcwd(), "data", "export_temp.csv")
        self.assertFalse(os.path.exists(project_temp_csv))

    def test_api_export_excel_default_and_3_columns(self):
        import openpyxl
        req = urllib.request.urlopen(f"{self.base_url}/api/export")
        self.assertEqual(req.status, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", req.headers.get("Content-Type", ""))
        self.assertIn("mediciones_hidrometria.xlsx", req.headers.get("Content-Disposition", ""))

        wb = openpyxl.load_workbook(io.BytesIO(req.read()))
        sheet = wb.active
        # Exactamente 3 columnas: Fecha, Estación, Medición
        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(headers, ["Fecha", "Estación", "Medición"])
        self.assertEqual(len(headers), 3)

        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        pilar_rows = [r for r in rows if r[1] == "Pilar"]
        self.assertTrue(len(pilar_rows) >= 1)
        self.assertEqual(pilar_rows[0][2], 3.45)

    def test_api_export_and_chart_exclude_discarded_points(self):
        import openpyxl
        # Insertar punto descartado
        discarded_id = self.store.save_measurement(
            estacion_detectada="PuntaDescarte",
            remitente_telefono="595984999111",
            timestamp_medicion="2026-10-16 15:00:00",
            valor_metros=9.99,
        )
        self.store.update_measurement(discarded_id, estado_revision="DESCARTADO")

        # 1. Verificar exportación Excel
        req_excel = urllib.request.urlopen(f"{self.base_url}/api/export")
        wb = openpyxl.load_workbook(io.BytesIO(req_excel.read()))
        sheet = wb.active
        excel_estaciones = [r[1] for r in sheet.iter_rows(min_row=2, values_only=True)]
        self.assertNotIn("PuntaDescarte", excel_estaciones)

        # 2. Verificar exportación CSV
        req_csv = urllib.request.urlopen(f"{self.base_url}/api/export?format=csv")
        csv_content = req_csv.read().decode("utf-8-sig")
        self.assertNotIn("PuntaDescarte", csv_content)

        # 3. Verificar que el script del frontend en el HTML excluye DESCARTADO del gráfico
        req_html = urllib.request.urlopen(f"{self.base_url}/")
        html = req_html.read().decode("utf-8")
        self.assertIn("DESCARTADO", html)
        self.assertIn("(m.estado_revision || '').toUpperCase() !== 'DESCARTADO'", html)

    def test_api_sync_onedrive(self):
        req = urllib.request.Request(f"{self.base_url}/api/sync-onedrive", method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertIn("path", data)
            self.assertIn("med_prefectura_PY.xlsx", data["filename"])
            self.assertTrue(os.path.exists(data["path"]))

    def test_serve_photo(self):
        req = urllib.request.urlopen(f"{self.base_url}/data/fotos/{self.fake_photo_filename}")
        self.assertEqual(req.status, 200)
        bytes_read = req.read()
        self.assertEqual(bytes_read, b"\xff\xd8\xff\xe0test_jpg_data")

    def test_kpi_summary_cards_completely_removed(self):
        """Verifica que las tarjetas de KPIs superiores hayan sido eliminadas completamente del HTML (R4)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertNotIn("kpi-grid", html)
        self.assertNotIn("kpi-card", html)
        self.assertNotIn("kpi-total", html)
        self.assertNotIn("kpi-estaciones", html)
        self.assertNotIn("actualizarKPIs", html)

    def test_leaflet_interactive_map_rendered(self):
        """Verifica que el mapa interactivo y catálogo geográfico hayan sido removidos del HTML."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertNotIn("mapa-estaciones", html)
        self.assertNotIn("leaflet.js", html)
        self.assertNotIn("leaflet.css", html)
        self.assertNotIn("L.tileLayer", html)
        self.assertNotIn("cartocdn.com", html)
        self.assertNotIn("Catálogo Geográfico y Mapa de Estaciones", html)

    def test_whatsapp_chat_modal_components(self):
        """Verifica los elementos del visor estilo WhatsApp Web Dark (#modal-whatsapp-chat)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn("modal-whatsapp-chat", html)
        self.assertIn("chat-estacion-select", html)
        self.assertIn("wpp-chat-bubble", html)
        self.assertIn("wpp-photo-preview", html)
        self.assertIn("wpp-hydro-badge", html)
        self.assertIn("modal-lightbox", html)

    def test_api_estacion_chat_by_name(self):
        """Verifica el endpoint GET /api/estaciones/<name>/chat retornando JSON correcto."""
        req = urllib.request.urlopen(f"{self.base_url}/api/estaciones/Pilar/chat")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIn("estacion", data)
        self.assertIn("mensajes", data)
        self.assertIsNotNone(data["estacion"])
        self.assertEqual(data["estacion"]["nombre"], "Pilar")
        self.assertGreaterEqual(len(data["mensajes"]), 1)
        first_msg = data["mensajes"][0]
        self.assertEqual(first_msg["valor_metros"], 3.45)
        self.assertIn("test_regla.jpg", first_msg["foto_path"])

    def test_api_estacion_chat_by_id(self):
        """Verifica el endpoint GET /api/estaciones/<id>/chat con ID numérico."""
        estaciones_req = urllib.request.urlopen(f"{self.base_url}/api/estaciones")
        estaciones = json.loads(estaciones_req.read().decode("utf-8"))
        pilar = next(s for s in estaciones if s["nombre"] == "Pilar")
        pilar_id = pilar["id"]

        req = urllib.request.urlopen(f"{self.base_url}/api/estaciones/{pilar_id}/chat")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIn("estacion", data)
        self.assertEqual(data["estacion"]["id"], pilar_id)
        self.assertEqual(data["estacion"]["nombre"], "Pilar")

    def test_api_estacion_chat_nonexistent(self):
        """Verifica que una estación no registrada retorne estacion: None y lista vacía sin romper."""
        req = urllib.request.urlopen(f"{self.base_url}/api/estaciones/EstacionInexistente999/chat")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIn("estacion", data)
        self.assertIsNone(data["estacion"])
        self.assertEqual(data["mensajes"], [])

    def test_api_estaciones_includes_coordinates(self):
        """Verifica que /api/estaciones incluya coordenadas latitud y longitud."""
        req = urllib.request.urlopen(f"{self.base_url}/api/estaciones")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        for st in data:
            self.assertIn("latitud", st)
            self.assertIn("longitud", st)


    def test_put_api_mediciones_success(self):
        """Verifica PUT /api/mediciones/<id> actualizando campos oficiales y preservando inmutabilidad IA."""
        with self.store.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO operadores (telefono, nombre, creado_en)
                VALUES ('595984111333', 'Operador Test', datetime('now'))
            """)
            op_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO mediciones (
                    estacion_id, operador_id, estacion_detectada, valor_metros, valor_cm, tendencia_rio,
                    timestamp_medicion, remitente_telefono, remitente_nombre, estado_revision,
                    ia_estacion_detectada, ia_valor_metros, ia_tendencia, ia_confianza, observaciones_ia
                ) VALUES (?, ?, 'Pilar', 3.10, 310.0, 'ESTACIONARIO', '2026-10-16 12:00:00', '595984111333', 'Operador Test', 'PENDIENTE',
                    'Pilar Original', 3.10, 'ESTACIONARIO', 'alta', 'Lectura de prueba IA')
            """, (pilar_id, op_id))
            test_id = cursor.lastrowid
            conn.commit()

        payload = json.dumps({
            "estacion_id": pilar_id,
            "valor_metros": 3.75,
            "tendencia_rio": "CRECE",
            "timestamp_medicion": "2026-10-16 13:00:00",
            "estado_revision": "CORREGIDO",
            "fijar_operador": False
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/{test_id}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["message"], "Medición actualizada exitosamente")
            self.assertIn("medicion", data)

        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (test_id,)).fetchone()
            self.assertEqual(row["valor_metros"], 3.75)
            self.assertEqual(row["valor_cm"], 375.0)
            self.assertEqual(row["tendencia_rio"], "CRECE")
            self.assertEqual(row["estado_revision"], "CORREGIDO")
            # Inmutabilidad IA
            self.assertEqual(row["ia_estacion_detectada"], "Pilar Original")
            self.assertEqual(row["ia_valor_metros"], 3.10)
            self.assertEqual(row["ia_tendencia"], "ESTACIONARIO")
            self.assertEqual(row["ia_confianza"], "alta")
            self.assertEqual(row["observaciones_ia"], "Lectura de prueba IA")

    def test_put_api_mediciones_fijar_operador(self):
        """Verifica PUT /api/mediciones/<id> con fijar_operador=True fijando estacion_fija_id en operadores."""
        with self.store.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO operadores (telefono, nombre, creado_en)
                VALUES ('595984777888', 'Op Fijar', datetime('now'))
            """)
            op_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO mediciones (
                    estacion_id, operador_id, estacion_detectada, valor_metros,
                    timestamp_medicion, remitente_telefono, remitente_nombre, estado_revision
                ) VALUES (?, ?, 'Pilar', 3.00, '2026-10-16 12:00:00', '595984777888', 'Op Fijar', 'PENDIENTE')
            """, (pilar_id, op_id))
            test_id = cursor.lastrowid
            conn.commit()

        payload = json.dumps({
            "estacion_id": pilar_id,
            "valor_metros": 3.05,
            "tendencia_rio": "BAJA",
            "fijar_operador": True
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/{test_id}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

        with self.store.get_connection() as conn:
            op_row = conn.execute("SELECT estacion_fija_id FROM operadores WHERE id = ?", (op_id,)).fetchone()
            self.assertEqual(op_row["estacion_fija_id"], pilar_id)

    def test_put_api_mediciones_nonexistent(self):
        """Verifica que PUT /api/mediciones/999999 retorne HTTP 404."""
        payload = json.dumps({"valor_metros": 1.23}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/999999",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="PUT"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_post_api_mediciones_manual_success(self):
        """Verifica POST /api/mediciones/manual vinculando una medición a un mensaje de chat existente."""
        msg_id = self.store.save_chat_message(
            remitente_telefono="595984555666",
            timestamp_mensaje="2026-10-16 15:30:00",
            texto="Reporte manual desde chat: Pilar 3.80 m crece",
            remitente_nombre="Operador Manual"
        )

        with self.store.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cursor.fetchone()[0]

        payload = json.dumps({
            "mensaje_id": msg_id,
            "estacion_id": pilar_id,
            "valor_metros": 3.80,
            "tendencia_rio": "CRECE",
            "timestamp_medicion": "2026-10-16 15:30:00",
            "estado_revision": "VALIDADO",
            "fijar_operador": False
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/manual",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertIn("medicion_id", data)
            new_id = data["medicion_id"]

        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (new_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["mensaje_id"], msg_id)
            self.assertEqual(row["estacion_id"], pilar_id)
            self.assertEqual(row["valor_metros"], 3.80)
            self.assertEqual(row["valor_cm"], 380.0)
            self.assertEqual(row["tendencia_rio"], "CRECE")
            self.assertEqual(row["estado_revision"], "VALIDADO")
            self.assertEqual(row["metodo_asignacion"], "manual")
            self.assertIsNone(row["ia_estacion_detectada"])
            self.assertIsNone(row["ia_valor_metros"])

    def test_post_api_mediciones_manual_missing_mensaje_id(self):
        """Verifica que POST /api/mediciones/manual sin mensaje_id retorne HTTP 400."""
        payload = json.dumps({
            "estacion_id": 1,
            "valor_metros": 3.80
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/manual",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

    def test_delete_api_mediciones_soft_delete(self):
        """Verifica DELETE /api/mediciones/<id> aplicando soft delete (estado_revision = 'DESCARTADO')."""
        test_id = self.store.save_measurement(
            estacion_detectada="Pilar",
            remitente_telefono="595984000111",
            timestamp_medicion="2026-10-16 16:00:00",
            valor_metros=2.90,
            tendencia_rio="ESTACIONARIO",
        )

        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/{test_id}",
            method="DELETE"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["estado_revision"], "DESCARTADO")
            self.assertIn("descartada (soft delete)", data["message"])

        with self.store.get_connection() as conn:
            row = conn.execute("SELECT * FROM mediciones WHERE id = ?", (test_id,)).fetchone()
            self.assertIsNotNone(row)  # El registro NO se borró físicamente de la BD
            self.assertEqual(row["estado_revision"], "DESCARTADO")

    def test_delete_api_mediciones_nonexistent(self):
        """Verifica que DELETE /api/mediciones/999999 retorne HTTP 404."""
        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/999999",
            method="DELETE"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_get_api_mediciones_filter_estado_revision(self):
        """Verifica filtrado por estado_revision en GET /api/mediciones (VALIDADO, CORREGIDO, DESCARTADO, TODOS)."""
        with self.store.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM estaciones WHERE nombre = 'Pilar'")
            pilar_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO operadores (telefono, nombre, creado_en)
                VALUES ('595984222333', 'Op Filtro', datetime('now'))
            """)
            op_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO mediciones (estacion_id, operador_id, remitente_telefono, estacion_detectada, valor_metros, timestamp_medicion, estado_revision)
                VALUES (?, ?, '595984222333', 'Pilar', 2.00, '2026-10-16 17:00:00', 'VALIDADO')
            """, (pilar_id, op_id))
            cursor.execute("""
                INSERT INTO mediciones (estacion_id, operador_id, remitente_telefono, estacion_detectada, valor_metros, timestamp_medicion, estado_revision)
                VALUES (?, ?, '595984222333', 'Pilar', 2.10, '2026-10-16 17:05:00', 'CORREGIDO')
            """, (pilar_id, op_id))
            cursor.execute("""
                INSERT INTO mediciones (estacion_id, operador_id, remitente_telefono, estacion_detectada, valor_metros, timestamp_medicion, estado_revision)
                VALUES (?, ?, '595984222333', 'Pilar', 2.20, '2026-10-16 17:10:00', 'DESCARTADO')
            """, (pilar_id, op_id))
            conn.commit()

        # Filtrar VALIDADO
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones?estado_revision=VALIDADO")
        self.assertEqual(req.status, 200)
        data_val = json.loads(req.read().decode("utf-8"))
        for m in data_val:
            self.assertEqual(m["estado_revision"], "VALIDADO")

        # Filtrar CORREGIDO
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones?estado_revision=CORREGIDO")
        self.assertEqual(req.status, 200)
        data_corr = json.loads(req.read().decode("utf-8"))
        for m in data_corr:
            self.assertEqual(m["estado_revision"], "CORREGIDO")

        # Filtrar DESCARTADO
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones?estado_revision=DESCARTADO")
        self.assertEqual(req.status, 200)
        data_desc = json.loads(req.read().decode("utf-8"))
        for m in data_desc:
            self.assertEqual(m["estado_revision"], "DESCARTADO")

        # Filtrar TODOS
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones?estado_revision=TODOS")
        self.assertEqual(req.status, 200)
        data_todos = json.loads(req.read().decode("utf-8"))
        estados = {m.get("estado_revision") for m in data_todos}
        self.assertIn("VALIDADO", estados)
        self.assertIn("DESCARTADO", estados)

    def test_options_cors_preflight(self):
        """Verifica manejo de peticiones OPTIONS CORS preflight con encabezados Access-Control."""
        req = urllib.request.Request(f"{self.base_url}/api/mediciones/1", method="OPTIONS")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            allow_methods = resp.headers.get("Access-Control-Allow-Methods", "")
            self.assertIn("PUT", allow_methods)
            self.assertIn("DELETE", allow_methods)
            self.assertIn("OPTIONS", allow_methods)
            self.assertIn("GET", allow_methods)
            self.assertIn("POST", allow_methods)

    def test_split_view_audit_console_html_components(self):
        """Verifica que el HTML renderice los elementos de la consola Split-View de Auditoría (#modal-foto)."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        # Layout Split-View de 2 columnas
        self.assertIn("split-modal-content", html)
        self.assertIn("split-modal-body", html)
        self.assertIn("split-col-left", html)
        self.assertIn("split-col-right", html)
        # Controles de zoom y rotación
        self.assertIn("zoomFoto", html)
        self.assertIn("rotarFoto", html)
        self.assertIn("resetTransformFoto", html)
        self.assertIn("split-photo-viewport", html)
        self.assertIn("zoom-level-badge", html)
        # Hilo cronológico y revinculación
        self.assertIn("is-origin", html)
        self.assertIn("relinkPhoto", html)
        # Tarjeta Detectado por IA
        self.assertIn("ia-cmp-estacion", html)
        self.assertIn("ia-cmp-nivel", html)
        self.assertIn("ia-cmp-tendencia", html)
        self.assertIn("ia-cmp-confianza", html)
        self.assertIn("ia-cmp-obs", html)
        # Formulario Datos Oficiales
        self.assertIn("split-edit-estacion", html)
        self.assertIn("split-edit-nivel", html)
        self.assertIn("split-edit-tendencia", html)
        self.assertIn("split-edit-timestamp", html)
        self.assertIn("split-edit-estado", html)
        self.assertIn("split-edit-fijar-operador", html)
        self.assertIn("Guardar y Validar", html)
        self.assertIn("Descartar falso positivo", html)
        self.assertIn("descartarFalsoPositivoSplit", html)

    def test_whatsapp_chat_manual_tagging_button_and_dialog_rendered(self):
        """Verifica que el visor de chat contenga el botón '+ Etiquetar Medición' y el modal manual."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn("+ Etiquetar Medición", html)
        self.assertIn("btn-etiquetar-medicion", html)
        self.assertIn("abrirModalEtiquetarManual", html)
        self.assertIn("modal-etiquetar-manual", html)
        self.assertIn("guardarMedicionManual", html)

    def test_dashboard_has_nueva_estacion_modal_and_button(self):
        """Verifica que el dashboard incluya el botón y el modal para registrar nuevas estaciones."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn("➕ Nueva Estación", html)
        self.assertIn("modal-nueva-estacion", html)
        self.assertIn("abrirModalNuevaEstacion", html)
        self.assertIn("guardarNuevaEstacion", html)

    def test_post_api_estaciones_creates_new_station(self):
        """Verifica que POST /api/estaciones registre exitosamente una nueva estación no registrada."""
        payload = {
            "nombre": "Puerto Itá Corá",
            "rio": "Río Paraná",
            "latitud": -27.45,
            "longitud": -57.48,
            "alias": "Ita Cora, Pto Ita Cora"
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/estaciones",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            self.assertEqual(data["station"]["nombre"], "Puerto Itá Corá")
            self.assertEqual(data["station"]["rio"], "Río Paraná")

        # Verificar que aparezca en el resumen de estaciones activas
        with urllib.request.urlopen(f"{self.base_url}/api/estaciones") as resp:
            summary = json.loads(resp.read().decode("utf-8"))
            names = [s["nombre"] for s in summary]
            self.assertIn("Puerto Itá Corá", names)

    def test_post_api_estaciones_validation_error(self):
        """Verifica que POST /api/estaciones valide que el nombre sea obligatorio."""
        payload = {"nombre": "   ", "rio": "Río Paraná"}
        req = urllib.request.Request(
            f"{self.base_url}/api/estaciones",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_iguazu_and_alto_parana_not_in_active_stations(self):
        """Verifica que estaciones oficiales lejanas (Iguazú, Salto del Guairá, CDE) no figuren como activas."""
        with urllib.request.urlopen(f"{self.base_url}/api/estaciones") as resp:
            summary = json.loads(resp.read().decode("utf-8"))
            names = [s["nombre"] for s in summary]
            self.assertNotIn("Puerto Iguazú", names)
            self.assertNotIn("Salto del Guairá", names)
            self.assertNotIn("Ciudad del Este", names)


if __name__ == "__main__":
    unittest.main()
