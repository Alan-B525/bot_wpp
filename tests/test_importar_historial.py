import os
import shutil
import tempfile
import unittest

from importar_historial import parse_whatsapp_date, parse_whatsapp_chat, importar_exportacion
from bot.measurement_store import MeasurementStore
from bot.measurement_agent import MeasurementAgent


class TestImportarHistorial(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_historial.db")
        self.photos_dir = os.path.join(self.test_dir, "fotos")
        self.store = MeasurementStore(db_path=self.db_path, photos_dir=self.photos_dir)
        self.agent = MeasurementAgent(api_key=None)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_whatsapp_date(self):
        d1 = parse_whatsapp_date("15/10/23, 08:30:15")
        self.assertEqual(d1, "2023-10-15 08:30:15")

        d2 = parse_whatsapp_date("15/10/2023, 14:45")
        self.assertEqual(d2, "2023-10-15 14:45:00")

        d3 = parse_whatsapp_date("[16/10/26 10:00:00]")
        self.assertEqual(d3, "2026-10-16 10:00:00")

        # Formato con puntos en la hora (típico en Android español)
        d4 = parse_whatsapp_date("15/10/2023, 08.30")
        self.assertEqual(d4, "2023-10-15 08:30:00")

        d5 = parse_whatsapp_date("15/10/2023, 08.30.15")
        self.assertEqual(d5, "2023-10-15 08:30:15")

    def test_parse_whatsapp_chat_file(self):
        sample_chat = (
            "15/10/2023, 08:00 - Los mensajes y las llamadas están cifrados de extremo a extremo.\n"
            "15/10/2023, 08:30 - Carlos Operador: Pilar 3,45m crece\n"
            "15/10/2023, 09:00 - Mario Ayolas: <adjunto: IMG-20231015-WA0001.jpg>\n"
            "15/10/2023, 09.15 - Mario Ayolas: WhatsApp Image 2023-10-15 at 09.15.00.jpeg (archivo adjunto) Escala 1.85m baja\n"
            "15/10/2023, 10:00 - Juan: Mensaje en varias líneas\n"
            "continuación de la línea del mensaje\n"
        )
        chat_path = os.path.join(self.test_dir, "_chat.txt")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(sample_chat)

        messages = parse_whatsapp_chat(chat_path)
        self.assertEqual(len(messages), 4)

        # Primer mensaje
        self.assertEqual(messages[0]["sender"], "Carlos Operador")
        self.assertEqual(messages[0]["text"], "Pilar 3,45m crece")
        self.assertIsNone(messages[0]["attachment"])

        # Segundo mensaje con adjunto formato iOS
        self.assertEqual(messages[1]["sender"], "Mario Ayolas")
        self.assertEqual(messages[1]["attachment"], "IMG-20231015-WA0001.jpg")

        # Tercer mensaje con adjunto formato Android con espacios y hora con punto
        self.assertEqual(messages[2]["sender"], "Mario Ayolas")
        self.assertEqual(messages[2]["attachment"], "WhatsApp Image 2023-10-15 at 09.15.00.jpeg")
        self.assertEqual(messages[2]["text"], "Escala 1.85m baja")
        self.assertEqual(messages[2]["timestamp"], "2023-10-15 09:15:00")

        # Mensaje multilínea
        self.assertIn("continuación de la línea", messages[3]["text"])

    def test_importar_exportacion(self):
        sample_chat = (
            "15/10/2023, 08:30 - Carlos: Pilar 3,45m crece\n"
            "15/10/2023, 09:15 - Mario: Ayolas 185 cm baja\n"
            "15/10/2023, 11:00 - Pedro: Buen día compañeros\n"
        )
        chat_path = os.path.join(self.test_dir, "_chat.txt")
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(sample_chat)

        res = importar_exportacion(self.test_dir, self.store, self.agent)
        self.assertEqual(res["total_procesados"], 3)
        self.assertEqual(res["total_mediciones"], 2)

        mediciones = self.store.query_measurements()
        self.assertEqual(len(mediciones), 2)


if __name__ == "__main__":
    unittest.main()
