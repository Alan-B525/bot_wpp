import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import unittest
import os
import json
from unittest.mock import MagicMock

from bot.config import BotConfig
from bot.utils import (
    clean_phone_number,
    match_phone_number,
    format_timestamp,
    build_forward_header,
    resolve_group_jid,
)
from bot.forwarder import forward_incoming_message
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message, ExtendedTextMessage, ImageMessage
from neonize.proto.Neonize_pb2 import JID, GroupInfo, GroupName


class TestWhatsAppForwarder(unittest.TestCase):
    def test_clean_phone_number(self):
        self.assertEqual(clean_phone_number("+54 9 11 1234-5678"), "5491112345678")
        self.assertEqual(clean_phone_number("5491112345678@s.whatsapp.net"), "5491112345678")
        self.assertEqual(clean_phone_number(""), "")

    def test_match_phone_number(self):
        # Exact match
        self.assertTrue(match_phone_number("5491112345678", "5491112345678"))
        # Match with spaces and symbols
        self.assertTrue(match_phone_number("5491112345678", "+54 9 11 1234-5678"))
        # Match local vs international
        self.assertTrue(match_phone_number("5491112345678", "1112345678"))
        # Non-matching
        self.assertFalse(match_phone_number("5491112345678", "5491199999999"))

    def test_format_timestamp(self):
        formatted = format_timestamp(1700000000)
        self.assertTrue(isinstance(formatted, str))
        self.assertIn(":", formatted)

    def test_build_forward_header(self):
        template = "📩 De: {sender_name} (+{sender_number}) Hora: {timestamp}\n\n"
        res = build_forward_header(template, "Carlos", "5491112345678", "2026-10-07 10:00:00")
        self.assertIn("Carlos", res)
        self.assertIn("5491112345678", res)
        self.assertIn("2026-10-07 10:00:00", res)

    def test_bot_config_filtering(self):
        config = BotConfig(
            source_numbers=["5491112345678"],
            forward_all_direct_messages=False,
            target_group="Test Group",
        )
        self.assertTrue(config.should_forward_sender("5491112345678"))
        self.assertTrue(config.should_forward_sender("+54 9 11 1234 5678"))
        self.assertFalse(config.should_forward_sender("5491100000000"))

        # Test forward all
        config_all = BotConfig(forward_all_direct_messages=True)
        self.assertTrue(config_all.should_forward_sender("cualquier_numero"))

    def test_resolve_group_jid(self):
        client_mock = MagicMock()

        # Mocking group info
        g1 = GroupInfo(
            JID=JID(User="120363011111111111", Server="g.us"),
            GroupName=GroupName(Name="Alertas Ventas"),
        )
        g2 = GroupInfo(
            JID=JID(User="120363022222222222", Server="g.us"),
            GroupName=GroupName(Name="Familia"),
        )
        client_mock.get_joined_groups.return_value = [g1, g2]

        # Resolution by direct JID
        jid, name = resolve_group_jid(client_mock, "120363011111111111@g.us")
        self.assertEqual(jid.User, "120363011111111111")
        self.assertEqual(jid.Server, "g.us")

        # Resolution by exact name
        jid, name = resolve_group_jid(client_mock, "Alertas Ventas")
        self.assertEqual(jid.User, "120363011111111111")
        self.assertEqual(name, "Alertas Ventas")

        # Resolution by case-insensitive partial name
        jid, name = resolve_group_jid(client_mock, "alertas")
        self.assertEqual(jid.User, "120363011111111111")

        # Resolution not found
        jid, name = resolve_group_jid(client_mock, "Inexistente")
        self.assertIsNone(jid)

    def test_forward_text_message(self):
        client_mock = MagicMock()
        target_jid = JID(User="120363011111111111", Server="g.us")
        config = BotConfig(forward_header=True)

        event_mock = MagicMock()
        event_mock.Info.Pushname = "Martin"
        event_mock.Info.MessageSource.Sender.User = "5491155556666"
        event_mock.Info.MessageSource.Chat.User = "5491155556666"
        event_mock.Info.Timestamp = 1700000000

        msg = Message(conversation="Hola mundo")
        event_mock.Message = msg

        result = forward_incoming_message(client_mock, target_jid, event_mock, config)
        self.assertTrue(result)
        client_mock.send_message.assert_called_once()
        args = client_mock.send_message.call_args[0]
        self.assertEqual(args[0], target_jid)
        self.assertIn("Hola mundo", args[1])
        self.assertIn("Martin", args[1])

    def test_forward_image_message(self):
        client_mock = MagicMock()
        client_mock.download_any.return_value = b"fake_image_bytes"
        target_jid = JID(User="120363011111111111", Server="g.us")
        config = BotConfig(forward_header=True)

        event_mock = MagicMock()
        event_mock.Info.Pushname = "Laura"
        event_mock.Info.MessageSource.Sender.User = "5491144443333"
        event_mock.Info.MessageSource.Chat.User = "5491144443333"
        event_mock.Info.Timestamp = 1700000000

        msg = Message()
        msg.imageMessage.caption = "Mira esta foto"
        event_mock.Message = msg

        result = forward_incoming_message(client_mock, target_jid, event_mock, config)
        self.assertTrue(result)
        client_mock.send_image.assert_called_once()
        args, kwargs = client_mock.send_image.call_args
        self.assertEqual(args[0], target_jid)
        self.assertEqual(args[1], b"fake_image_bytes")
        self.assertIn("Mira esta foto", kwargs["caption"])
        self.assertIn("Laura", kwargs["caption"])

    def test_forward_audio_ptt_message(self):
        client_mock = MagicMock()
        client_mock.download_any.return_value = b"fake_audio_bytes"
        target_jid = JID(User="120363011111111111", Server="g.us")
        config = BotConfig(forward_header=True)

        event_mock = MagicMock()
        event_mock.Info.Pushname = "Lucas"
        event_mock.Info.MessageSource.Sender.User = "5491122221111"
        event_mock.Info.MessageSource.Chat.User = "5491122221111"
        event_mock.Info.Timestamp = 1700000000

        msg = Message()
        msg.audioMessage.PTT = True
        event_mock.Message = msg

        result = forward_incoming_message(client_mock, target_jid, event_mock, config)
        self.assertTrue(result)
        client_mock.send_audio.assert_called_once_with(target_jid, b"fake_audio_bytes", ptt=True)
        # Verify notification header was sent
        client_mock.send_message.assert_called_once()
        self.assertIn("Nota de voz", client_mock.send_message.call_args[0][1])

    def test_forward_document_message(self):
        client_mock = MagicMock()
        client_mock.download_any.return_value = b"fake_pdf_bytes"
        target_jid = JID(User="120363011111111111", Server="g.us")
        config = BotConfig(forward_header=False)

        event_mock = MagicMock()
        event_mock.Info.Pushname = "Ana"
        event_mock.Info.MessageSource.Sender.User = "5491188887777"
        event_mock.Info.MessageSource.Chat.User = "5491188887777"
        event_mock.Info.Timestamp = 1700000000

        msg = Message()
        msg.documentMessage.fileName = "reporte.pdf"
        msg.documentMessage.mimetype = "application/pdf"
        event_mock.Message = msg

        result = forward_incoming_message(client_mock, target_jid, event_mock, config)
        self.assertTrue(result)
        client_mock.send_document.assert_called_once()
        kwargs = client_mock.send_document.call_args[1]
        self.assertEqual(kwargs["filename"], "reporte.pdf")
        self.assertEqual(kwargs["mimetype"], "application/pdf")

    def test_forward_exact_text_without_header(self):
        client_mock = MagicMock()
        target_jid = JID(User="120363011111111111", Server="g.us")
        config = BotConfig(forward_header=False)

        event_mock = MagicMock()
        event_mock.Info.Pushname = "Martin"
        event_mock.Info.MessageSource.Sender.User = "5491155556666"
        event_mock.Info.MessageSource.Chat.User = "5491155556666"
        event_mock.Info.Timestamp = 1700000000

        original_text = "Precio del producto: $500. ¿Tienen stock?"
        event_mock.Message = Message(conversation=original_text)

        result = forward_incoming_message(client_mock, target_jid, event_mock, config)
        self.assertTrue(result)
        # Debe enviar EXACTAMENTE el mismo texto, sin ningún prefijo ni sufijo
        client_mock.send_message.assert_called_once_with(target_jid, original_text)

    def test_forward_contact_without_header(self):
        client_mock = MagicMock()
        target_jid = JID(User="120363011111111111", Server="g.us")
        config = BotConfig(forward_header=False)

        event_mock = MagicMock()
        event_mock.Info.Pushname = "Martin"
        event_mock.Info.MessageSource.Sender.User = "5491155556666"
        event_mock.Info.MessageSource.Chat.User = "5491155556666"

        msg = Message()
        msg.contactMessage.displayName = "Doctor Garcia"
        msg.contactMessage.vcard = "BEGIN:VCARD\nFN:Doctor Garcia\nEND:VCARD"
        event_mock.Message = msg

        result = forward_incoming_message(client_mock, target_jid, event_mock, config)
        self.assertTrue(result)
        client_mock.send_message.assert_called_once()
        sent_msg = client_mock.send_message.call_args[0][1]
        self.assertEqual(sent_msg.contactMessage.displayName, "Doctor Garcia")


if __name__ == "__main__":
    unittest.main()
