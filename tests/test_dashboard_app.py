import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
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
        cls.store = MeasurementStore(db_path=cls.db_path, photos_dir=cls.photos_dir)

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
        self.store.save_chat_message(
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
        req = urllib.request.urlopen(f"{self.base_url}/api/export")
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

        # Exportar con fotos=true
        req = urllib.request.urlopen(f"{self.base_url}/api/export?fotos=true")
        self.assertEqual(req.status, 200)
        content = req.read().decode("utf-8-sig")
        # Debe incluir Pilar (con foto) y NO Concepción (sin foto)
        self.assertIn("Pilar", content)
        self.assertNotIn("Concepción", content)

        # Verificar que no quedó archivo residual export_temp.csv
        project_temp_csv = os.path.join(os.getcwd(), "data", "export_temp.csv")
        self.assertFalse(os.path.exists(project_temp_csv))

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
        """Verifica que el mapa interactivo Leaflet y sus scripts estén presentes en el HTML."""
        req = urllib.request.urlopen(f"{self.base_url}/")
        self.assertEqual(req.status, 200)
        html = req.read().decode("utf-8")
        self.assertIn("mapa-estaciones", html)
        self.assertIn("leaflet.js", html)
        self.assertIn("leaflet.css", html)
        self.assertIn("L.tileLayer", html)
        self.assertIn("cartocdn.com", html)

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


if __name__ == "__main__":
    unittest.main()
