import os
import json
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

from .utils import clean_phone_number, match_phone_number


@dataclass
class BotConfig:
    source_numbers: List[str] = field(default_factory=list)
    forward_all_direct_messages: bool = False
    target_group: str = ""
    forward_header: bool = True
    header_template: str = (
        "📩 *Mensaje reenviado*\n"
        "👤 *De:* {sender_name} (+{sender_number})\n"
        "🕒 *Hora:* {timestamp}\n\n"
    )
    session_name: str = "bot_session.sqlite3"
    measurement_db_enabled: bool = True
    measurement_db_path: str = "data/mediciones.db"
    photos_dir: str = "data/fotos"
    gemini_api_key: str = ""

    @classmethod
    def load(cls, config_path: str = "config.json") -> "BotConfig":
        """
        Carga la configuración desde config.json y complementa con variables de entorno si existen.
        """
        load_dotenv()
        data = {}

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"⚠️ Error al leer {config_path}: {e}. Se utilizarán valores por defecto.")

        # Leer valores de archivo o defaults
        source_numbers_raw = data.get("source_numbers", [])
        if isinstance(source_numbers_raw, str):
            source_numbers_raw = [n.strip() for n in source_numbers_raw.split(",") if n.strip()]

        # Overrides por variables de entorno (.env) si están definidas
        env_source_numbers = os.getenv("SOURCE_NUMBERS")
        if env_source_numbers:
            source_numbers_raw = [n.strip() for n in env_source_numbers.split(",") if n.strip()]

        forward_all = data.get("forward_all_direct_messages", False)
        env_forward_all = os.getenv("FORWARD_ALL_DIRECT_MESSAGES")
        if env_forward_all is not None:
            forward_all = env_forward_all.strip().lower() in ("true", "1", "yes")

        target_group = os.getenv("TARGET_GROUP") or data.get("target_group", "")
        forward_header = data.get("forward_header", True)
        env_forward_header = os.getenv("FORWARD_HEADER")
        if env_forward_header is not None:
            forward_header = env_forward_header.strip().lower() in ("true", "1", "yes")

        header_template = data.get(
            "header_template",
            "📩 *Mensaje reenviado*\n👤 *De:* {sender_name} (+{sender_number})\n🕒 *Hora:* {timestamp}\n\n",
        )
        session_name = os.getenv("SESSION_NAME") or data.get("session_name", "bot_session.sqlite3")

        measurement_db_enabled = data.get("measurement_db_enabled", True)
        env_measurement_db_enabled = os.getenv("MEASUREMENT_DB_ENABLED")
        if env_measurement_db_enabled is not None:
            measurement_db_enabled = env_measurement_db_enabled.strip().lower() in ("true", "1", "yes")

        measurement_db_path = os.getenv("MEASUREMENT_DB_PATH") or data.get("measurement_db_path", "data/mediciones.db")
        photos_dir = os.getenv("PHOTOS_DIR") or data.get("photos_dir", "data/fotos")
        gemini_api_key = os.getenv("GEMINI_API_KEY") or data.get("gemini_api_key", "")

        # Limpiar números de origen
        clean_sources = [clean_phone_number(num) for num in source_numbers_raw if clean_phone_number(num)]

        return cls(
            source_numbers=clean_sources,
            forward_all_direct_messages=forward_all,
            target_group=str(target_group).strip(),
            forward_header=forward_header,
            header_template=header_template,
            session_name=str(session_name).strip(),
            measurement_db_enabled=measurement_db_enabled,
            measurement_db_path=str(measurement_db_path).strip(),
            photos_dir=str(photos_dir).strip(),
            gemini_api_key=str(gemini_api_key).strip(),
        )

    def should_forward_sender(self, sender_number) -> bool:
        """
        Verifica si el número remitente está autorizado para reenvío según la configuración.
        Acepta una cadena (str) o una lista de candidatos (list[str]).
        """
        if self.forward_all_direct_messages:
            return True

        if not self.source_numbers:
            return False

        if isinstance(sender_number, (list, tuple, set)):
            for num in sender_number:
                if self.should_forward_sender(num):
                    return True
            return False

        clean_sender = clean_phone_number(str(sender_number))
        for conf_num in self.source_numbers:
            if match_phone_number(clean_sender, conf_num):
                return True

        return False
