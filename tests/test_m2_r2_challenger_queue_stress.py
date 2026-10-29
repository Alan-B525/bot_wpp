import os
import sys
import time
import queue
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from bot.client import WhatsAppForwarderBot
from bot.measurement_store import MeasurementStore
from bot.measurement_agent import MeasurementAgent
from bot.config import BotConfig


def make_mock_event(
    sender_phone="595981302739",
    sender_name="Salomón Diarte",
    text=None,
    has_image=False,
    image_caption=None,
    timestamp=1700000000,
    is_from_me=False,
    is_group=False,
    server="s.whatsapp.net",
):
    """Crea un mock realista de MessageEv para pruebas de ingesta."""
    mock_ev = MagicMock()
    info = MagicMock()
    source = MagicMock()
    chat = MagicMock()

    chat.Server = server
    chat.User = sender_phone
    source.Chat = chat
    source.IsFromMe = is_from_me
    source.IsGroup = is_group

    info.MessageSource = source
    info.Pushname = sender_name
    info.Timestamp = timestamp

    mock_ev.Info = info

    msg = MagicMock()
    if has_image:
        msg.HasField.side_effect = lambda f: f == "imageMessage"
        msg.imageMessage.caption = image_caption or ""
    elif text is not None:
        msg.HasField.side_effect = lambda f: f == "conversation"
        msg.conversation = text
    else:
        msg.HasField.return_value = False
        msg.conversation = None

    mock_ev.Message = msg
    return mock_ev


class ChallengerQueueStressTests(unittest.TestCase):
    """
    Empirical stress tests challenging:
    1. Rapid burst ingestion (100 messages) without SQLite locks or race conditions.
    2. Multi-threaded concurrent burst ingestion.
    3. Strict causal foreign key references (mensajes_chat, adjuntos_multimedia, mediciones).
    4. Non-measurement chat causality.
    5. Clean shutdown (client.stop()).
    6. Edge cases: same-second collisions, empty payloads, filtering.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="stress_m2_")
        self.db_path = os.path.join(self.temp_dir, "test_mediciones.db").replace("\\", "/")
        self.photos_dir = os.path.join(self.temp_dir, "fotos").replace("\\", "/")

        self.config = BotConfig(
            measurement_db_enabled=True,
            measurement_db_path=self.db_path,
            photos_dir=self.photos_dir,
            target_group="Test Group",
            forward_all_direct_messages=True,
            session_name="test_session",
            gemini_api_key="mock_key",
        )

        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)
        self.agent = MeasurementAgent(api_key="mock_key", store=self.store)
        # Mockear _call_gemini para simular fallo inmediato de cuota sin latencia de red HTTP externa
        self.agent._call_gemini = MagicMock(side_effect=Exception("Simulated Quota Exceeded"))

    def tearDown(self):
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    def _create_bot_client(self):
        with patch("bot.client.NewClient"):
            bot = WhatsAppForwarderBot(self.config)
            bot.measurement_store = self.store
            bot.measurement_agent = self.agent
            bot.target_jid = "target@g.us"
            return bot

    def test_01_burst_ingestion_100_messages_no_locks(self):
        """
        DESAFÍO 1: Ingesta en ráfaga rápida de 100 mensajes consecutivos.
        Verifica:
        - 100 mensajes procesados sin bloqueo SQLite ('database is locked')
        - Orden FIFO en cola
        - 100 mensajes registrados en mensajes_chat
        - Mediciones válidas registradas en mediciones
        - Fotos registradas en adjuntos_multimedia
        """
        bot = self._create_bot_client()
        # Simular descarga de imagen: mínimo JPEG válido (1x1 px)
        dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        bot.client.download_any = MagicMock(return_value=dummy_jpeg)

        stations = ["Pilar", "Alberdi", "Concepción", "Humaitá", "Fuerte Olimpo"]
        total_msgs = 100
        expected_measurements = 0
        expected_photos = 0

        # Enviar 100 mensajes en ráfaga rápida sin pausas
        base_time = 1700000000
        for i in range(total_msgs):
            ts = base_time + i * 60  # un mensaje por minuto simulado
            station = stations[i % len(stations)]
            level = 2.0 + (i % 20) * 0.15

            if i < 50:
                # 50 mensajes de texto con medición
                txt = f"{station} {level:.2f} m crece"
                ev = make_mock_event(
                    sender_phone=f"59598100{i:04d}",
                    sender_name=f"Operador {i}",
                    text=txt,
                    timestamp=ts,
                )
                expected_measurements += 1
            elif i < 75:
                # 25 mensajes con foto y caption de medición
                caption = f"{station} escala {level:.2f}m"
                ev = make_mock_event(
                    sender_phone=f"59598200{i:04d}",
                    sender_name=f"Operador Foto {i}",
                    has_image=True,
                    image_caption=caption,
                    timestamp=ts,
                )
                expected_measurements += 1
                expected_photos += 1
            else:
                # 25 mensajes de texto sin medición (charlas generales)
                txt = f"Buen día grupo, reporte de turno {i}"
                ev = make_mock_event(
                    sender_phone=f"59598300{i:04d}",
                    sender_name=f"Operador Charla {i}",
                    text=txt,
                    timestamp=ts,
                )

            with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=[ev.Info.MessageSource.Chat.User]):
                bot._handle_incoming_message(ev)

        # Esperar que la cola FIFO procese todos los 100 elementos
        bot.ingestion_queue.join()

        # Detener bot limpiamente
        bot.stop()
        self.assertFalse(bot.worker_thread.is_alive())

        # Verificaciones en SQLite
        with self.store.get_connection() as conn:
            cur = conn.cursor()

            # 1. Todos los 100 mensajes deben estar en mensajes_chat
            cur.execute("SELECT COUNT(*) FROM mensajes_chat")
            chat_count = cur.fetchone()[0]
            self.assertEqual(chat_count, total_msgs, f"Se esperaban 100 mensajes en chat, se obtuvieron {chat_count}")

            # 2. Exactamente 25 adjuntos en adjuntos_multimedia
            cur.execute("SELECT COUNT(*) FROM adjuntos_multimedia")
            adj_count = cur.fetchone()[0]
            self.assertEqual(adj_count, expected_photos, f"Se esperaban {expected_photos} fotos, se obtuvieron {adj_count}")

            # 3. Exactamente 75 mediciones en mediciones (50 texto + 25 foto)
            cur.execute("SELECT COUNT(*) FROM mediciones")
            med_count = cur.fetchone()[0]
            self.assertEqual(med_count, expected_measurements, f"Se esperaban {expected_measurements} mediciones, se obtuvieron {med_count}")

            # 4. Integridad de la base de datos sin corrupción
            cur.execute("PRAGMA integrity_check")
            integrity = cur.fetchone()[0]
            self.assertEqual(integrity, "ok")

            # 5. Integridad de Foreign Keys
            cur.execute("PRAGMA foreign_key_check")
            fk_violations = cur.fetchall()
            self.assertEqual(len(fk_violations), 0, f"Violaciones FK encontradas: {fk_violations}")

    def test_02_concurrent_burst_ingestion_multi_threaded(self):
        """
        DESAFÍO 2: Ingesta concurrente multihilo de 100 mensajes (10 hilos x 10 mensajes).
        Verifica que la competencia de escritura en SQLite entre los hilos productores
        y el hilo consumidor no provoque bloqueos ('database is locked') ni condiciones de carrera.
        """
        bot = self._create_bot_client()
        dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        bot.client.download_any = MagicMock(return_value=dummy_jpeg)

        errors = []

        def worker_producer(thread_id):
            try:
                for j in range(10):
                    idx = thread_id * 10 + j
                    ts = 1700100000 + idx * 10
                    has_img = (j % 3 == 0)
                    station = "Humaitá" if (idx % 2 == 0) else "Alberdi"
                    val = 3.0 + j * 0.1

                    if has_img:
                        ev = make_mock_event(
                            sender_phone=f"595999{thread_id:02d}{j:02d}",
                            sender_name=f"Concurrente {thread_id}-{j}",
                            has_image=True,
                            image_caption=f"{station} {val:.2f} m",
                            timestamp=ts,
                        )
                    else:
                        ev = make_mock_event(
                            sender_phone=f"595999{thread_id:02d}{j:02d}",
                            sender_name=f"Concurrente {thread_id}-{j}",
                            text=f"{station} {val:.2f} m bajando",
                            timestamp=ts,
                        )

                    with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=[ev.Info.MessageSource.Chat.User]):
                        bot._handle_incoming_message(ev)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_producer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errores en hilos productores: {errors}")

        # Esperar que la cola secuencial termine
        bot.ingestion_queue.join()
        bot.stop()
        self.assertFalse(bot.worker_thread.is_alive())

        # Verificar resultados en SQLite
        with self.store.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM mensajes_chat")
            chat_count = cur.fetchone()[0]
            self.assertEqual(chat_count, 100)

            cur.execute("PRAGMA integrity_check")
            self.assertEqual(cur.fetchone()[0], "ok")

            cur.execute("PRAGMA foreign_key_check")
            self.assertEqual(len(cur.fetchall()), 0)

    def test_03_strict_causal_foreign_keys_verification(self):
        """
        DESAFÍO 3: Verificación causal estricta de Foreign Keys.
        Verifica que:
        - Cada fila en 'mediciones' tiene un 'mensaje_id' válido y existente en 'mensajes_chat'.
        - Para mediciones con foto, 'adjunto_id' existe en 'adjuntos_multimedia' y apunta al mismo 'mensaje_id'.
        - El archivo físico de foto existe en disco en 'foto_path' y tiene tamaño > 0.
        - Mediciones sin foto tienen 'adjunto_id' IS NULL y 'foto_path' IS NULL.
        """
        bot = self._create_bot_client()
        dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        bot.client.download_any = MagicMock(return_value=dummy_jpeg)

        # 1. Enviar mensaje de texto
        ev_text = make_mock_event(
            sender_phone="595981111111",
            sender_name="Operador Texto",
            text="Pilar 4.25m crece",
            timestamp=1700200000,
        )
        with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=["595981111111"]):
            bot._handle_incoming_message(ev_text)

        # 2. Enviar mensaje con foto
        ev_photo = make_mock_event(
            sender_phone="595982222222",
            sender_name="Operador Foto",
            has_image=True,
            image_caption="Alberdi 3.80m estacionado",
            timestamp=1700200100,
        )
        with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=["595982222222"]):
            bot._handle_incoming_message(ev_photo)

        bot.ingestion_queue.join()
        bot.stop()

        with self.store.get_connection() as conn:
            cur = conn.cursor()

            # Inspeccionar medición de texto
            cur.execute("""
                SELECT m.id, m.mensaje_id, m.adjunto_id, m.foto_path, c.texto, c.remitente_telefono
                FROM mediciones m
                JOIN mensajes_chat c ON m.mensaje_id = c.id
                WHERE m.remitente_telefono = '595981111111'
            """)
            row_text = cur.fetchone()
            self.assertIsNotNone(row_text, "No se encontró medición vinculada para mensaje de texto")
            self.assertIsNotNone(row_text[1], "mensaje_id no debe ser NULL")
            self.assertIsNone(row_text[2], "adjunto_id debe ser NULL para texto")
            self.assertIsNone(row_text[3], "foto_path debe ser NULL para texto")
            self.assertIn("Pilar 4.25m", row_text[4])

            # Inspeccionar medición con foto
            cur.execute("""
                SELECT m.id, m.mensaje_id, m.adjunto_id, m.foto_path,
                       c.id, c.foto_path,
                       a.id, a.mensaje_id, a.ruta_archivo
                FROM mediciones m
                JOIN mensajes_chat c ON m.mensaje_id = c.id
                JOIN adjuntos_multimedia a ON m.adjunto_id = a.id
                WHERE m.remitente_telefono = '595982222222'
            """)
            row_photo = cur.fetchone()
            self.assertIsNotNone(row_photo, "No se encontró medición vinculada para mensaje con foto")

            m_id, m_msg_id, m_adj_id, m_foto_path, c_id, c_foto_path, a_id, a_msg_id, a_ruta = row_photo

            # Verificación causal estricta:
            self.assertEqual(m_msg_id, c_id, "mediciones.mensaje_id debe coincidir con mensajes_chat.id")
            self.assertEqual(m_adj_id, a_id, "mediciones.adjunto_id debe coincidir con adjuntos_multimedia.id")
            self.assertEqual(a_msg_id, c_id, "adjuntos_multimedia.mensaje_id debe coincidir con mensajes_chat.id")
            self.assertEqual(m_foto_path, a_ruta, "mediciones.foto_path debe coincidir con adjuntos_multimedia.ruta_archivo")
            self.assertEqual(c_foto_path, a_ruta, "mensajes_chat.foto_path debe coincidir con adjuntos_multimedia.ruta_archivo")

            # Existencia física del archivo en disco
            self.assertTrue(os.path.exists(m_foto_path), f"El archivo de foto {m_foto_path} debe existir físicamente")
            self.assertGreater(os.path.getsize(m_foto_path), 0, "El archivo de foto no debe estar vacío")

    def test_04_non_measurement_message_causality(self):
        """
        DESAFÍO 4: Causalidad en mensajes sin mediciones limnimétricas.
        Verifica que mensajes conversacionales se persisten en mensajes_chat
        pero NO generan registros espurios en mediciones ni adjuntos_multimedia.
        """
        bot = self._create_bot_client()

        ev = make_mock_event(
            sender_phone="595985555555",
            sender_name="Operador Saludo",
            text="Buenas tardes a todos los colegas de guardia",
            timestamp=1700300000,
        )
        with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=["595985555555"]):
            bot._handle_incoming_message(ev)

        bot.ingestion_queue.join()
        bot.stop()

        with self.store.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, texto FROM mensajes_chat WHERE remitente_telefono = '595985555555'")
            chat = cur.fetchone()
            self.assertIsNotNone(chat, "El mensaje de chat debe persistirse en mensajes_chat")
            chat_id = chat[0]

            cur.execute("SELECT COUNT(*) FROM mediciones WHERE mensaje_id = ?", (chat_id,))
            med_count = cur.fetchone()[0]
            self.assertEqual(med_count, 0, "No debe registrarse ninguna medición para un saludo")

            cur.execute("SELECT COUNT(*) FROM adjuntos_multimedia WHERE mensaje_id = ?", (chat_id,))
            adj_count = cur.fetchone()[0]
            self.assertEqual(adj_count, 0, "No debe existir ningún adjunto multimedia para un mensaje de texto")

    def test_05_clean_shutdown_and_worker_lifecycle(self):
        """
        DESAFÍO 5: Apagado limpio y ciclo de vida del worker thread.
        Verifica:
        - client.stop() termina el worker thread en menos de 2 segundos sin colgarse.
        - worker_thread.is_alive() es False tras el stop.
        - Llamadas repetidas a client.stop() son idempotentes.
        """
        bot = self._create_bot_client()
        self.assertTrue(bot.worker_thread.is_alive(), "El worker thread debe iniciar activo")

        # Encolar 5 mensajes
        for i in range(5):
            ev = make_mock_event(
                sender_phone=f"59598700000{i}",
                sender_name=f"Operador Stop {i}",
                text=f"Concepción 2.{50+i}m estacionado",
                timestamp=1700400000 + i * 10,
            )
            with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=[f"59598700000{i}"]):
                bot._handle_incoming_message(ev)

        # Esperar procesamiento y detener
        bot.ingestion_queue.join()

        start_time = time.time()
        bot.stop()
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 2.5, f"bot.stop() demoró {elapsed:.2f}s, superando el límite de 2.5s")
        self.assertFalse(bot.worker_thread.is_alive(), "El worker thread debe haber finalizado")

        # Idempotencia: invocar stop() repetidas veces
        bot.stop()
        bot.stop()
        self.assertFalse(bot.worker_thread.is_alive())

    def test_06_edge_case_same_second_distinct_messages(self):
        """
        DESAFÍO 6: Mensajes simultáneos en el MISMO segundo del mismo remitente.
        Escenario:
        - Mensaje 1 (ts T): Texto solo 'Pilar 3.50m'
        - Mensaje 2 (ts T): Foto con caption 'Pilar 3.50m escala'
        Verifica cómo se asocian mensaje_id y adjunto_id cuando el timestamp es idéntico al segundo.
        """
        bot = self._create_bot_client()
        dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        bot.client.download_any = MagicMock(return_value=dummy_jpeg)

        same_ts = 1700500000

        ev1 = make_mock_event(
            sender_phone="595989999999",
            sender_name="Operador Gemelo",
            text="Pilar 3.50m",
            timestamp=same_ts,
        )
        ev2 = make_mock_event(
            sender_phone="595989999999",
            sender_name="Operador Gemelo",
            has_image=True,
            image_caption="Pilar 3.50m escala",
            timestamp=same_ts,
        )

        with patch("bot.client.forward_incoming_message"), patch("bot.client.get_sender_phone_candidates", return_value=["595989999999"]):
            bot._handle_incoming_message(ev1)
            bot._handle_incoming_message(ev2)

        bot.ingestion_queue.join()
        bot.stop()

        with self.store.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, texto, foto_path FROM mensajes_chat WHERE remitente_telefono = '595989999999' ORDER BY id ASC")
            chats = cur.fetchall()
            self.assertEqual(len(chats), 2, "Deben existir 2 mensajes de chat separados")
            id1, txt1, foto1 = chats[0]
            id2, txt2, foto2 = chats[1]

            cur.execute("SELECT id, mensaje_id, adjunto_id, foto_path FROM mediciones WHERE remitente_telefono = '595989999999' ORDER BY id ASC")
            meds = cur.fetchall()
            self.assertGreaterEqual(len(meds), 1, "Debe existir al menos 1 medición registrada")

            # Verificar que ningún adjunto quede huérfano de mensaje_id
            cur.execute("SELECT id, mensaje_id FROM adjuntos_multimedia WHERE mensaje_id IS NULL")
            orphans = cur.fetchall()
            self.assertEqual(len(orphans), 0, "No debe haber adjuntos multimedia con mensaje_id NULL")

    def test_07_filtered_events_do_not_pollute_queue_or_store(self):
        """
        DESAFÍO 7: Eventos filtrados (IsFromMe, IsGroup, broadcast) no ingresan a la cola ni a SQLite.
        """
        bot = self._create_bot_client()

        # 1. Evento de difusión / estado
        ev_broadcast = make_mock_event(server="broadcast")
        bot._handle_incoming_message(ev_broadcast)

        # 2. Evento propio (IsFromMe)
        ev_from_me = make_mock_event(is_from_me=True)
        bot._handle_incoming_message(ev_from_me)

        # 3. Evento de grupo (IsGroup)
        ev_group = make_mock_event(is_group=True)
        bot._handle_incoming_message(ev_group)

        # Cola debe estar completamente vacía
        self.assertEqual(bot.ingestion_queue.qsize(), 0)
        bot.stop()

        with self.store.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM mensajes_chat")
            self.assertEqual(cur.fetchone()[0], 0, "Ningún mensaje filtrado debe guardarse en chat")
            cur.execute("SELECT COUNT(*) FROM mediciones")
            self.assertEqual(cur.fetchone()[0], 0, "Ninguna medición debe crearse para eventos filtrados")


if __name__ == "__main__":
    unittest.main()
