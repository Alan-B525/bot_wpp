import os
import json
import unittest
from unittest.mock import MagicMock, patch

from bot.measurement_agent import MeasurementAgent


class TestMeasurementAgent(unittest.TestCase):
    def setUp(self):
        # Inicializar agente sin API key para probar comportamiento determinístico de fallback
        self.agent = MeasurementAgent(api_key=None)

    def test_fallback_parse_standard_meters(self):
        res = self.agent.fallback_parse("Pilar 3,45 crece")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Pilar")
        self.assertEqual(res["valor_metros"], 3.45)
        self.assertEqual(res["valor_cm"], 345.0)
        self.assertEqual(res["tendencia"], "CRECE")

    def test_fallback_parse_centimeters(self):
        res = self.agent.fallback_parse("Escala Ayolas: 185 cm baja")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Ayolas")
        self.assertEqual(res["valor_metros"], 1.85)
        self.assertEqual(res["valor_cm"], 185.0)
        self.assertEqual(res["tendencia"], "BAJA")

    def test_fallback_parse_integer_without_unit(self):
        # 245 sin punto ni coma en hidrometría fluvial = 2.45 m / 245 cm
        res = self.agent.fallback_parse("Pto Alberdi 245 estac")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["valor_cm"], 245.0)
        self.assertEqual(res["valor_metros"], 2.45)
        self.assertEqual(res["tendencia"], "ESTACIONARIO")

    def test_fallback_parse_known_stations(self):
        known = ["Panchito López", "Humaitá", "Concepción"]
        res = self.agent.fallback_parse("Panchito Lopez 2.10m", known_stations=known)
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Panchito López")
        self.assertEqual(res["valor_metros"], 2.10)

    def test_fallback_parse_negative_value(self):
        res = self.agent.fallback_parse("Asuncion -0.20m baja")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["valor_metros"], -0.20)
        self.assertEqual(res["valor_cm"], -20.0)
        self.assertEqual(res["tendencia"], "BAJA")

    def test_fallback_parse_non_measurement_message(self):
        res = self.agent.fallback_parse("Hola buenos días grupo, favor avisar si recibieron la planilla")
        self.assertFalse(res["es_medicion_valida"])

    def test_mock_gemini_ai_response(self):
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "es_medicion_valida": True,
            "estacion": "Pilar",
            "rio": "Río Paraguay",
            "valor_original": "3.45m",
            "valor_metros": 3.45,
            "valor_cm": 345.0,
            "unidad_detectada": "m",
            "tendencia": "CRECE",
            "origen": "ambos",
            "confianza": "alta",
            "lectura_regla_foto": "La regla graduada muestra nivel en 3.45m",
        })

        agent = MeasurementAgent(api_key="fake_key")
        agent.client = MagicMock()
        agent.client.models.generate_content.return_value = mock_response

        res = agent.process_message(text="Pilar 3.45m", image_bytes=b"fake_image_bytes")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Pilar")
        self.assertEqual(res["valor_metros"], 3.45)
        self.assertEqual(res["tendencia"], "CRECE")
        self.assertEqual(res["origen"], "ambos")

    def test_mock_gemini_ai_markdown_json_response(self):
        mock_response = MagicMock()
        # Respuesta envuelta en bloque de código markdown ```json ... ```
        mock_response.text = """```json
{
  "es_medicion_valida": true,
  "estacion": "Humaitá",
  "rio": "Río Paraguay",
  "valor_original": "2,15",
  "valor_metros": 2.15,
  "valor_cm": 215.0,
  "unidad_detectada": "m",
  "tendencia": "BAJA",
  "origen": "texto",
  "confianza": "alta",
  "lectura_regla_foto": "Reporte de bajante"
}
```"""

        agent = MeasurementAgent(api_key="fake_key")
        agent.client = MagicMock()
        agent.client.models.generate_content.return_value = mock_response

        res = agent.process_message(text="Humaita 2,15 baja")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Humaitá")
        self.assertEqual(res["valor_metros"], 2.15)
        self.assertEqual(res["tendencia"], "BAJA")

    def test_gemini_failure_triggers_fallback(self):
        agent = MeasurementAgent(api_key="fake_key")
        agent.client = MagicMock()
        agent.client.models.generate_content.side_effect = RuntimeError("API Quota Exceeded")

        # Debe capturar el error y devolver el resultado del fallback regex sin lanzar excepción
        res = agent.process_message(text="Ayolas 1.80m crece")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["valor_metros"], 1.80)
        self.assertEqual(res["tendencia"], "CRECE")

    def test_fallback_parse_rejects_times_dates_phones(self):
        # Asegurar que horas aisladas, fechas aisladas o teléfonos no se interpreten como niveles
        res_time = self.agent.fallback_parse("08:30")
        self.assertFalse(res_time["es_medicion_valida"])

        res_date = self.agent.fallback_parse("15/10/2023")
        self.assertFalse(res_date["es_medicion_valida"])

        res_phone = self.agent.fallback_parse("Te llamo al 0981123456")
        self.assertFalse(res_phone["es_medicion_valida"])

        res_phone_intl = self.agent.fallback_parse("Mi nuevo cel es +595984123456")
        self.assertFalse(res_phone_intl["es_medicion_valida"])

    def test_fallback_parse_with_embedded_time_and_date(self):
        # Mensaje con hora antes de la estación y nivel
        res_hour = self.agent.fallback_parse("08:00 Pilar 3.45m")
        self.assertTrue(res_hour["es_medicion_valida"])
        self.assertEqual(res_hour["estacion"], "Pilar")
        self.assertEqual(res_hour["valor_metros"], 3.45)

        # Mensaje con fecha antes de la estación
        res_date = self.agent.fallback_parse("15/10/2023 Pilar 3.45m")
        self.assertTrue(res_date["es_medicion_valida"])
        self.assertEqual(res_date["estacion"], "Pilar")
        self.assertEqual(res_date["valor_metros"], 3.45)

        # Mensaje con hora con sufijo 'hs'
        res_hs = self.agent.fallback_parse("Nivel de hoy a las 8hs en Pilar: 3.45m")
        self.assertTrue(res_hs["es_medicion_valida"])
        self.assertEqual(res_hs["estacion"], "Pilar")
        self.assertEqual(res_hs["valor_metros"], 3.45)

    def test_fallback_parse_greeting_with_unknown_station(self):
        res = self.agent.fallback_parse("Buenos dias grupo Puerto Nuevo 1.80")
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Puerto Nuevo")
        self.assertEqual(res["valor_metros"], 1.80)

    def test_trend_estacionado_detected_as_estacionario(self):
        # Reporte con 'estacionado'
        res1 = self.agent.fallback_parse("Puerto Coratei 4.12 estacionado")
        self.assertTrue(res1["es_medicion_valida"])
        self.assertEqual(res1["tendencia"], "ESTACIONARIO")
        self.assertEqual(res1["estacion"], "Puerto Coratei")

        # Reporte fluvial típico con paréntesis: "4,13 (E) estacionado"
        res2 = self.agent.fallback_parse("4,13 (E) estacionado")
        self.assertTrue(res2["es_medicion_valida"])
        self.assertEqual(res2["tendencia"], "ESTACIONARIO")
        self.assertIsNone(res2["estacion"])

        # Variante femenina 'estacionada'
        res3 = self.agent.fallback_parse("Ayolas 1.85m estacionada")
        self.assertTrue(res3["es_medicion_valida"])
        self.assertEqual(res3["tendencia"], "ESTACIONARIO")

    def test_spurious_conversational_text_not_extracted_as_station(self):
        # Caso "Que Este Era"
        res1 = self.agent.fallback_parse("Buenos dias señor, le quería comunicarle que este era 3,50")
        self.assertTrue(res1["es_medicion_valida"])
        self.assertIsNone(res1["estacion"])
        self.assertEqual(res1["valor_metros"], 3.50)

        # Caso "Se Mantiene"
        res2 = self.agent.fallback_parse("Buen dia, se mantiene en 3,80")
        self.assertTrue(res2["es_medicion_valida"])
        self.assertIsNone(res2["estacion"])
        self.assertEqual(res2["valor_metros"], 3.80)

        # Caso "Corrección"
        res3 = self.agent.fallback_parse("Corrección 3.25m es")
        self.assertTrue(res3["es_medicion_valida"])
        self.assertIsNone(res3["estacion"])
        self.assertEqual(res3["valor_metros"], 3.25)

        # Caso "Marin Por Esta"
        res4 = self.agent.fallback_parse("Buenas noches SO 2ª E Fabio Marin por esta Altura del Rio 3,65")
        self.assertTrue(res4["es_medicion_valida"])
        self.assertIsNone(res4["estacion"])
        self.assertEqual(res4["valor_metros"], 3.65)

        # Caso sólo número y tendencia
        res5 = self.agent.fallback_parse("4,12 estacionado")
        self.assertTrue(res5["es_medicion_valida"])
        self.assertIsNone(res5["estacion"])
        self.assertEqual(res5["tendencia"], "ESTACIONARIO")

    def test_compute_string_similarity_fixed_subset_bug(self):
        from bot.measurement_store import compute_string_similarity
        # (+2) normalizado a "2" no debe matchear San Pedro 2
        sim = compute_string_similarity("(+2)", "San Pedro 2")
        self.assertLess(sim, 0.30)

        # (+12) no debe matchear San Pedro 12
        sim12 = compute_string_similarity("(+12)", "San Pedro 12")
        self.assertLess(sim12, 0.30)

    def test_operator_inference_consistent_operator(self):
        mock_store = MagicMock()
        mock_store.infer_operator_station.return_value = 17
        mock_store.get_station_by_id.return_value = {"id": 17, "nombre": "Ayolas"}

        agent = MeasurementAgent(api_key=None, store=mock_store)
        res = agent.parse_message("3,45 creciendo", remitente_telefono="595972695099")

        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Ayolas")
        self.assertEqual(res["inferred_station"], "Ayolas")
        self.assertEqual(res["metodo_asignacion"], "inferido_operador")
        self.assertEqual(res["nivel"], 3.45)
        self.assertEqual(res["tendencia"], "CRECE")
        mock_store.infer_operator_station.assert_called_with("595972695099")

    def test_operator_inference_multistation_remains_unassigned(self):
        mock_store = MagicMock()
        # Operador multiestación (patrulla de guardia): infer_operator_station devuelve None
        mock_store.infer_operator_station.return_value = None

        agent = MeasurementAgent(api_key=None, store=mock_store)
        res = agent.parse_message("3,45 creciendo", remitente_telefono="595984621689")

        self.assertTrue(res["es_medicion_valida"])
        self.assertIsNone(res["estacion"])
        self.assertIsNone(res["inferred_station"])
        self.assertEqual(res["metodo_asignacion"], "desconocido")
        self.assertEqual(res["nivel"], 3.45)

    def test_operator_inference_unknown_operator_remains_unassigned(self):
        mock_store = MagicMock()
        # Operador desconocido sin historial: infer_operator_station devuelve None
        mock_store.infer_operator_station.return_value = None

        agent = MeasurementAgent(api_key=None, store=mock_store)
        res = agent.parse_message("3,45 creciendo", remitente_telefono="595999999999")

        self.assertTrue(res["es_medicion_valida"])
        self.assertIsNone(res["estacion"])
        self.assertIsNone(res["inferred_station"])
        self.assertEqual(res["metodo_asignacion"], "desconocido")

    def test_operator_inference_explicit_station_overrides_history(self):
        mock_store = MagicMock()
        # El operador habitualmente reporta Ayolas (id 17)
        mock_store.infer_operator_station.return_value = 17
        mock_store.get_station_by_id.return_value = {"id": 17, "nombre": "Ayolas"}
        mock_store.get_all_stations.return_value = [
            {"id": 17, "nombre": "Ayolas"},
            {"id": 22, "nombre": "Panchito López"},
        ]

        agent = MeasurementAgent(api_key=None, store=mock_store)
        # Pero en este reporte explícitamente reporta "Panchito López 3,40m"
        res = agent.parse_message("Panchito López 3,40m", remitente_telefono="595972695099")

        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Panchito López")
        self.assertIsNone(res["inferred_station"])
        self.assertEqual(res["metodo_asignacion"], "explicito")
        self.assertEqual(res["nivel"], 3.40)

    def test_live_chat_message_ingestion_in_client(self):
        from bot.client import WhatsAppClient

        mock_config = MagicMock()
        mock_config.measurement_db_enabled = False
        mock_config.target_group = "Central"
        mock_config.should_forward_sender.return_value = True

        with patch("bot.client.NewClient"), patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=["595981302739"]):
            client = WhatsAppClient(mock_config)
            client.measurement_store = MagicMock()
            client.measurement_agent = MagicMock()
            client.target_jid = "12345@g.us"

            # Simular evento entrante
            mock_event = MagicMock()
            mock_event.Info.MessageSource.Chat.Server = "s.whatsapp.net"
            mock_event.Info.MessageSource.Chat.User = "595981302739"
            mock_event.Info.MessageSource.IsFromMe = False
            mock_event.Info.MessageSource.IsGroup = False
            mock_event.Info.Pushname = "Salomón Diarte"
            mock_event.Info.Timestamp = 1700000000
            mock_event.Message.HasField.side_effect = lambda field: field == "conversation"
            mock_event.Message.conversation = "3.52 creciendo"

            client._handle_incoming_message(mock_event)

            # Verificar que save_chat_message fue invocado con los campos requeridos
            client.measurement_store.save_chat_message.assert_called_once()
            call_kwargs = client.measurement_store.save_chat_message.call_args.kwargs
            self.assertEqual(call_kwargs["remitente_telefono"], "595981302739")
            self.assertEqual(call_kwargs["remitente_nombre"], "Salomón Diarte")
            self.assertEqual(call_kwargs["texto"], "3.52 creciendo")
            self.assertIn("timestamp_str", call_kwargs)


if __name__ == "__main__":
    unittest.main()

