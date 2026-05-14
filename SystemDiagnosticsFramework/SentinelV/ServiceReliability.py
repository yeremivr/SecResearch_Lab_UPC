
import logging
import os
import shlex
import subprocess
from typing import Dict, Optional
from winreg import HKEY_CURRENT_USER, KEY_SET_VALUE, OpenKey, REG_SZ, SetValueEx

logger = logging.getLogger("SentinelV.ServiceReliability")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class PersistenceRegistrationError(RuntimeError):
    """Error al registrar la persistencia de reinicio."""


class ServiceReliability:
    """Esquema técnico para reiniciar automáticamente el controlador de QA tras reboot."""

    def __init__(self, persistence_name: str = "QA Hardware Agent") -> None:
        self.persistence_name = persistence_name

    def register_registry_startup(self, executable_path: str) -> bool:
        """Registra la aplicación en HKCU Run para reinicio automático en logon."""
        if not os.path.isfile(executable_path):
            raise FileNotFoundError(f"No se encontró el ejecutable: {executable_path}")

        try:
            with OpenKey(HKEY_CURRENT_USER, RUN_KEY_PATH, 0, KEY_SET_VALUE) as key:
                SetValueEx(key, self.persistence_name, 0, REG_SZ, executable_path)
            logger.info(
                "Entrada de reinicio registrada en HKCU Run: %s",
                self.persistence_name,
            )
            return True
        except Exception as exc:
            logger.warning("Fallo al registrar inicio automático en HKCU Run: %s", exc)
            return False

    def register_scheduled_task(
        self,
        executable_path: str,
        task_name: Optional[str] = None,
    ) -> bool:
        """Registra una tarea programada ONLOGON que re-lanza el controlador tras el reinicio."""
        task_name = task_name or self.persistence_name
        if not os.path.isfile(executable_path):
            raise FileNotFoundError(f"No se encontró el ejecutable: {executable_path}")

        command = [
            "schtasks",
            "/Create",
            "/F",
            "/SC",
            "ONLOGON",
            "/RL",
            "HIGHEST",
            "/TN",
            task_name,
            "/TR",
            executable_path,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "schtasks falló: %s %s",
                    result.returncode,
                    result.stderr.strip(),
                )
                return False

            logger.info(
                "Tarea programada de reinicio creada: %s", task_name,
            )
            return True
        except Exception as exc:
            logger.warning("Error al crear tarea programada: %s", exc)
            return False

    def ensure_reboot_persistence(
        self,
        executable_path: str,
        enable_task: bool = True,
    ) -> Dict[str, bool]:
        """Aplica un esquema de persistencia combinado para reiniciar tras reboot.

        1. HKCU Run para arranques de sesión de usuario.
        2. Tarea programada ONLOGON como respaldo.
        """
        result: Dict[str, bool] = {}
        try:
            result["registry"] = self.register_registry_startup(executable_path)
        except Exception as exc:
            logger.warning("Fallo en registro de persistencia HKCU: %s", exc)
            result["registry"] = False

        if enable_task:
            try:
                result["scheduled_task"] = self.register_scheduled_task(executable_path)
            except Exception as exc:
                logger.warning("Fallo en tarea programada de persistencia: %s", exc)
                result["scheduled_task"] = False
        return result

    def describe_reliability_scheme(self) -> str:
        """Devuelve el esquema técnico utilizado para persistencia de reinicio."""
        return (
            "Este esquema utiliza una combinación de entrada en HKCU Run y una tarea "
            "programada ONLOGON. HKCU Run asegura que el controlador se ejecute al "
            "iniciar sesión del usuario, mientras que la tarea programada actúa como "
            "respaldo para garantizar continuidad tras reinicios de sistema y cierres "
            "de sesión."
        )

    def normalize_command_for_registration(self, executable_path: str) -> str:
        return shlex.quote(executable_path)
