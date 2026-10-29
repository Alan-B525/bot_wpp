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
            client.stop()

    def test_gemini_25_models_configuration(self):
        # 1. Configuración por defecto usa gemini-2.5-flash y gemini-2.5-flash-lite
        agent = MeasurementAgent(api_key="fake_key")
        self.assertEqual(agent.model_name, "gemini-2.5-flash")
        self.assertEqual(agent.fallback_models, ["gemini-2.5-flash", "gemini-2.5-flash-lite"])

        # No deben existir modelos obsoletos
        self.assertNotIn("gemini-3.6-flash", agent.fallback_models)
        self.assertNotIn("gemini-3.5-flash-lite", agent.fallback_models)
        self.assertNotIn("gemini-3.5-flash", agent.fallback_models)

        # 2. Configuración con modelo personalizado
        custom_agent = MeasurementAgent(api_key="fake_key", model_name="custom-flash")
        self.assertEqual(custom_agent.model_name, "custom-flash")
        self.assertEqual(custom_agent.fallback_models, ["custom-flash", "gemini-2.5-flash-lite"])

    def test_pydantic_schema_definition_and_validation(self):
        from bot.measurement_agent import MeasurementExtraction

        # Validación del esquema con todos los campos requeridos
        m = MeasurementExtraction(
            es_medicion_valida=True,
            estacion="Pilar",
            rio="Río Paraguay",
            valor_original="3.45m",
            valor_metros=3.45,
            valor_cm=345.0,
            unidad_detectada="m",
            tendencia="CRECE",
            origen="ambos",
            confianza="alta",
            lectura_regla_foto="Regla graduada en 3.45m",
        )
        self.assertTrue(m.es_medicion_valida)
        self.assertEqual(m.estacion, "Pilar")
        self.assertEqual(m.valor_metros, 3.45)
        self.assertEqual(m.valor_cm, 345.0)

        # Validación de serialización JSON y re-hidratación determinista
        json_str = m.model_dump_json()
        m_reconstructed = MeasurementExtraction.model_validate_json(json_str)
        self.assertEqual(m_reconstructed.estacion, "Pilar")
        self.assertEqual(m_reconstructed.valor_metros, 3.45)

    def test_gemini_config_includes_response_schema_and_pydantic_parsing(self):
        from bot.measurement_agent import MeasurementExtraction

        agent = MeasurementAgent(api_key="fake_key")
        agent.client = MagicMock()

        # Respuesta estructurada de Gemini SDK que puebla response.parsed con modelo Pydantic
        mock_response = MagicMock()
        mock_response.parsed = MeasurementExtraction(
            es_medicion_valida=True,
            estacion="Concepción",
            rio="Río Paraguay",
            valor_original="2,50m",
            valor_metros=2.50,
            valor_cm=250.0,
            unidad_detectada="m",
            tendencia="BAJA",
            origen="texto",
            confianza="alta",
            lectura_regla_foto="Reporte oficial Concepción",
        )
        mock_response.text = mock_response.parsed.model_dump_json()
        agent.client.models.generate_content.return_value = mock_response

        res = agent.process_message(text="Concepcion 2.50m baja")

        # Verificar que generate_content fue invocado con response_schema=MeasurementExtraction
        self.assertTrue(agent.client.models.generate_content.called)
        _, kwargs = agent.client.models.generate_content.call_args
        gen_config = kwargs.get("config")
        self.assertIsNotNone(gen_config)
        self.assertEqual(getattr(gen_config, "response_mime_type", None), "application/json")
        self.assertEqual(getattr(gen_config, "response_schema", None), MeasurementExtraction)

        # Verificar resultado procesado y campos inmutables de IA
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Concepción")
        self.assertEqual(res["valor_metros"], 2.50)
        self.assertEqual(res["valor_cm"], 250.0)
        self.assertEqual(res["tendencia"], "BAJA")
        self.assertEqual(res["ia_estacion_detectada"], "Concepción")
        self.assertEqual(res["ia_valor_metros"], 2.50)
        self.assertEqual(res["ia_tendencia"], "BAJA")
        self.assertEqual(res["ia_confianza"], "alta")
        self.assertEqual(res["observaciones_ia"], "Reporte oficial Concepción")

    def test_ai_immutability_preserved_with_operator_inference(self):
        from bot.measurement_agent import MeasurementExtraction

        mock_store = MagicMock()
        # Operador 595972695099 mapeado habitualmente a Ayolas (id 17)
        mock_store.infer_operator_station.return_value = 17
        mock_store.get_station_by_id.return_value = {"id": 17, "nombre": "Ayolas"}

        agent = MeasurementAgent(api_key="fake_key", store=mock_store)
        agent.client = MagicMock()

        # La IA analiza un texto sin estación explícita ("3.45m subiendo")
        mock_response = MagicMock()
        mock_response.parsed = MeasurementExtraction(
            es_medicion_valida=True,
            estacion=None,  # No detectó estación en el texto
            rio=None,
            valor_original="3.45m",
            valor_metros=3.45,
            valor_cm=345.0,
            unidad_detectada="m",
            tendencia="CRECE",
            origen="texto",
            confianza="media",
            lectura_regla_foto="Lectura sin estación",
        )
        agent.client.models.generate_content.return_value = mock_response

        res = agent.parse_message("3.45m subiendo", remitente_telefono="595972695099")

        # Inferencia asignó Ayolas al campo de negocio "estacion"
        self.assertEqual(res["estacion"], "Ayolas")
        self.assertEqual(res["inferred_station"], "Ayolas")
        self.assertEqual(res["metodo_asignacion"], "inferido_operador")

        # Pero el campo original de IA ia_estacion_detectada debe permanecer inmutable (None)
        self.assertIsNone(res["ia_estacion_detectada"])
        self.assertEqual(res["ia_valor_metros"], 3.45)
        self.assertEqual(res["ia_tendencia"], "CRECE")

    def test_producer_consumer_queue_and_strict_causality_linkage(self):
        from bot.client import WhatsAppClient

        mock_config = MagicMock()
        mock_config.measurement_db_enabled = False
        mock_config.target_group = "Central"
        mock_config.should_forward_sender.return_value = True

        with patch("bot.client.NewClient"), patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=["595981302739"]):
            client = WhatsAppClient(mock_config)
            client.target_jid = "12345@g.us"

            # 1. Verificar cola y worker dedicado activo
            self.assertTrue(hasattr(client, "ingestion_queue"))
            self.assertTrue(client.worker_thread.is_alive())

            # Mocks de base de datos y agente
            mock_store = MagicMock()
            mock_store.save_chat_message.return_value = 101  # mensaje_id generado
            mock_store.save_photo.return_value = "data/fotos/chat_20261020_120000.jpg"
            mock_store.associate_photo_to_message.return_value = 202  # adjunto_id generado
            mock_store.get_all_stations.return_value = [{"nombre": "Pilar"}]
            mock_store.save_measurement.return_value = 505

            mock_agent = MagicMock()
            mock_agent.process_message.return_value = {
                "es_medicion_valida": True,
                "estacion": "Pilar",
                "valor_original": "3.45m",
                "valor_metros": 3.45,
                "valor_cm": 345.0,
                "unidad_detectada": "m",
                "tendencia": "CRECE",
                "origen": "ambos",
                "confianza": "alta",
                "lectura_regla_foto": "Regla Pilar",
                "ia_estacion_detectada": "Pilar",
                "ia_valor_metros": 3.45,
                "ia_tendencia": "CRECE",
                "ia_confianza": "alta",
            }

            client.measurement_store = mock_store
            client.measurement_agent = mock_agent

            # Simular descarga de imagen
            client.client.download_any = MagicMock(return_value=b"fake_image_bytes")

            mock_event = MagicMock()
            mock_event.Info.MessageSource.Chat.Server = "s.whatsapp.net"
            mock_event.Info.MessageSource.Chat.User = "595981302739"
            mock_event.Info.MessageSource.IsFromMe = False
            mock_event.Info.MessageSource.IsGroup = False
            mock_event.Info.Pushname = "Salomón Diarte"
            mock_event.Info.Timestamp = 1700000000
            mock_event.Message.HasField.side_effect = lambda f: f == "imageMessage"
            mock_event.Message.imageMessage.caption = "Pilar 3.45m crece"

            # Enviar mensaje al cliente
            client._handle_incoming_message(mock_event)

            # Verificar que save_chat_message fue invocado primero
            mock_store.save_chat_message.assert_called_once()

            # Verificar que associate_photo_to_message fue invocado
            mock_store.associate_photo_to_message.assert_called_once_with(
                remitente_telefono="595981302739",
                timestamp_str=mock_store.save_chat_message.call_args.kwargs["timestamp_str"],
                foto_path="data/fotos/chat_20261020_120000.jpg",
            )

            # Esperar a que la cola sea procesada por el worker
            client.ingestion_queue.join()

            # Verificar que save_measurement fue invocado con mensaje_id=101 y adjunto_id=202 explícitos
            mock_store.save_measurement.assert_called_once()
            call_kwargs = mock_store.save_measurement.call_args.kwargs
            self.assertEqual(call_kwargs["mensaje_id"], 101)
            self.assertEqual(call_kwargs["adjunto_id"], 202)
            self.assertEqual(call_kwargs["estacion_detectada"], "Pilar")
            self.assertEqual(call_kwargs["valor_metros"], 3.45)
            self.assertEqual(call_kwargs["ia_estacion_detectada"], "Pilar")
            self.assertEqual(call_kwargs["ia_valor_metros"], 3.45)

            # Detener cliente de forma segura
            client.stop()
            self.assertFalse(client.worker_thread.is_alive())

    def test_fallback_parse_whatsapp_italics_formatting(self):
        """Verifica que el formato en cursiva de WhatsApp (_texto_) sea correctamente parseado."""
        res = self.agent.fallback_parse("_Humaitá_ _2,15_ _baja_", known_stations=["Humaitá"])
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Humaitá")
        self.assertEqual(res["valor_metros"], 2.15)
        self.assertEqual(res["tendencia"], "BAJA")

    def test_fallback_parse_whatsapp_quoted_reply_stripping(self):
        """Verifica que las líneas citadas con '>' no contaminen la extracción del reporte actual."""
        quote_msg = "> Ayer estuvo 3.20m baja\nHoy Pilar 3.45m crece"
        res = self.agent.fallback_parse(quote_msg, known_stations=["Pilar"])
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Pilar")
        self.assertEqual(res["valor_metros"], 3.45)
        self.assertEqual(res["tendencia"], "CRECE")

    def test_fallback_parse_multi_station_first_appearance(self):
        """Verifica que en mensajes multi-estación se asocie la primera estación con su respectivo valor."""
        text = "Pilar 3.45m\nHumaitá 2.15m"
        res = self.agent.fallback_parse(text, known_stations=["Pilar", "Humaitá"])
        self.assertTrue(res["es_medicion_valida"])
        self.assertEqual(res["estacion"], "Pilar")
        self.assertEqual(res["valor_metros"], 3.45)

    def test_fallback_parse_spurious_regla_foto_does_not_leak_foto(self):
        """Verifica que 'Regla Foto 2.10m' no extraiga 'Foto' como estación espuria."""
        res = self.agent.fallback_parse("Regla Foto 2.10m")
        self.assertTrue(res["es_medicion_valida"])
        self.assertIsNone(res["estacion"])
        self.assertEqual(res["valor_metros"], 2.10)

    def test_sanitize_single_rejects_out_of_range_levels(self):
        """Verifica que _sanitize_single rechace niveles fuera del rango físico plausible (-10m a 35m)."""
        from bot.measurement_agent import MeasurementExtraction
        agent = MeasurementAgent(api_key="fake_key")
        agent.client = MagicMock()

        mock_resp = MagicMock()
        mock_resp.parsed = MeasurementExtraction(
            es_medicion_valida=True,
            estacion="Pilar",
            valor_original="999.0m",
            valor_metros=999.0,
            valor_cm=99900.0,
            unidad_detectada="m",
            tendencia="CRECE",
            confianza="alta",
        )
        agent.client.models.generate_content.return_value = mock_resp

        res = agent.process_message("Pilar 999m")
        self.assertFalse(res["es_medicion_valida"])
        self.assertIsNone(res["valor_metros"])
        self.assertEqual(res["confianza"], "baja")

    def test_ai_immutability_persistence_in_sqlite(self):
        """Verifica que al inferir la estación por operador, ia_estacion_detectada persista como NULL en SQLite."""
        import tempfile
        from bot.measurement_store import MeasurementStore
        from bot.measurement_agent import MeasurementExtraction

        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_immutability.db")
        store = MeasurementStore(db_path=db_path)

        with store.get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO estaciones (id, nombre, rio, es_activa) VALUES (2, 'Ayolas', 'Río Paraná', 1)")
            conn.execute("INSERT OR REPLACE INTO operadores (id, nombre, telefono, estacion_fija_id, activo) VALUES (10, 'Op Ayolas', '595971111111', 2, 1)")
            conn.commit()

        agent = MeasurementAgent(api_key="fake_key", store=store)
        agent.client = MagicMock()

        mock_resp = MagicMock()
        mock_resp.parsed = MeasurementExtraction(
            es_medicion_valida=True,
            estacion=None,
            valor_original="3.45m",
            valor_metros=3.45,
            valor_cm=345.0,
            unidad_detectada="m",
            tendencia="CRECE",
            origen="texto",
            confianza="media",
        )
        agent.client.models.generate_content.return_value = mock_resp

        parsed = agent.parse_message("3.45m crece", remitente_telefono="595971111111", store=store)
        self.assertEqual(parsed.get("estacion"), "Ayolas")
        self.assertIsNone(parsed.get("ia_estacion_detectada"))
        self.assertEqual(parsed.get("metodo_asignacion"), "inferido_operador")

        meas_id = store.save_measurement(
            estacion_detectada=parsed.get("estacion"),
            remitente_telefono="595971111111",
            timestamp_medicion="2026-10-20 12:00:00",
            valor_original=parsed.get("valor_original"),
            valor_metros=parsed.get("valor_metros"),
            valor_cm=parsed.get("valor_cm"),
            unidad_detectada=parsed.get("unidad_detectada") or "m",
            tendencia_rio=parsed.get("tendencia"),
            origen_dato=parsed.get("origen") or "texto",
            confianza=parsed.get("confianza") or "alta",
            mensaje_texto="3.45m crece",
            ia_estacion_detectada=parsed.get("ia_estacion_detectada"),
            ia_valor_metros=parsed.get("ia_valor_metros"),
            ia_tendencia=parsed.get("ia_tendencia"),
            ia_confianza=parsed.get("ia_confianza"),
            observaciones_ia=parsed.get("observaciones_ia"),
            metodo_asignacion=parsed.get("metodo_asignacion"),
        )

        with store.get_connection() as conn:
            row = conn.execute(
                "SELECT id, estacion_id, estacion_detectada, ia_estacion_detectada, metodo_asignacion FROM mediciones WHERE id = ?",
                (meas_id,)
            ).fetchone()

        self.assertEqual(row["estacion_id"], 2)
        self.assertEqual(row["estacion_detectada"], "Ayolas")
        self.assertIsNone(row["ia_estacion_detectada"])
        self.assertEqual(row["metodo_asignacion"], "inferido_operador")


if __name__ == "__main__":
    unittest.main()


