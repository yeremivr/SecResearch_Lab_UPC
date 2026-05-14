import json
import os
import sys
import logging
from typing import Optional, Tuple

logger = logging.getLogger("SentinelV.DiscordConfig")

LAB_HARDCODED_CONFIG = {
    "DISCORD_BOT_TOKEN": "MTUwMzk1MDA0Mjk2NzMxNDQ4Mg.GxBVNK.h0DDYz1Iy_S3cgPbhwmWFn6rUBZa6ZZCZ_Hd7Q",
    "DISCORD_ADMIN_CHANNEL_ID": 1503955307267620998,
}

PLACEHOLDER_TOKENS = {
    "YOUR_DISCORD_BOT_TOKEN_HERE",
    "DISCORD_BOT_TOKEN",
    "TOKEN_HERE",
    "PEGA_AQUI_TU_NUEVO_TOKEN",
}


def _resolve_package_path(filename: str) -> str:
    if getattr(sys, "_MEIPASS", None):
        candidate = os.path.join(sys._MEIPASS, filename)
        if os.path.exists(candidate):
            return candidate
        candidate = os.path.join(sys._MEIPASS, "SentinelV", filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(os.path.dirname(__file__), filename)


def _valid_discord_credentials(bot_token: Optional[str], channel_id: Optional[int]) -> bool:
    if not bot_token or not isinstance(bot_token, str):
        return False
    if bot_token.strip() in PLACEHOLDER_TOKENS:
        return False
    if not channel_id or not isinstance(channel_id, int) or channel_id <= 0:
        return False
    return True


def load_discord_credentials() -> Tuple[Optional[str], Optional[int]]:
    """Carga credenciales Discord con fallback a variables, archivo o config hardcoded."""
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id_str = os.environ.get("DISCORD_ADMIN_CHANNEL_ID")

    if bot_token and channel_id_str:
        try:
            channel_id = int(channel_id_str)
            if _valid_discord_credentials(bot_token, channel_id):
                logger.info("Credenciales Discord cargadas desde variables de entorno")
                return bot_token, channel_id
            logger.warning("Variables de entorno Discord contienen valores inválidos o placeholders")
        except ValueError:
            logger.warning("DISCORD_ADMIN_CHANNEL_ID no es un entero válido")

    config_path = _resolve_package_path("discord_config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            bot_token = config.get("bot_token")
            channel_id = config.get("channel_id")
            if _valid_discord_credentials(bot_token, channel_id):
                logger.info("Credenciales Discord cargadas desde discord_config.json")
                return bot_token, channel_id
            logger.warning("discord_config.json contiene valores inválidos o placeholders")
        except Exception as exc:
            logger.warning("No se pudo leer discord_config.json: %s", exc)

    bot_token = LAB_HARDCODED_CONFIG.get("DISCORD_BOT_TOKEN")
    channel_id = LAB_HARDCODED_CONFIG.get("DISCORD_ADMIN_CHANNEL_ID")
    if _valid_discord_credentials(bot_token, channel_id):
        logger.warning("Usando credenciales hardcodeadas Discord (laboratorio)")
        return bot_token, channel_id

    logger.warning("No se encontraron credenciales Discord en ningún origen")
    return None, None
