"""
GarbageCollector.py — Auto-limpieza de huellas forenses para SentinelV.

Elimina residuos de compilación, logs temporales ya transmitidos y archivos
basura generados durante las pruebas de laboratorio, sin tocar el .exe principal
ni los archivos de configuración activos.
"""

import glob
import logging
import os
import shutil
import tempfile
from typing import List, Tuple

logger = logging.getLogger("SentinelV.GarbageCollector")


# ── Patrones de archivos seguros para eliminar ───────────────────────────────
_TEMP_PATTERNS = [
    "sentinel_keylog_*.txt",     # Reportes forenses ya transmitidos
    "huella_*.txt",              # Huellas digitales ya transmitidas
    "sentinel_debug.log",        # Log de debug del ghost process
    "sentinel_ghost_startup.log",
    "cleanup_supergame.bat",     # Scripts de autolimpieza residuales
]

_BUILD_RESIDUES = [
    "build",       # Carpeta de PyInstaller
    "__pycache__", # Bytecode compilado
    "*.pyc",
    "*.pyo",
    "*.spec",      # Specs de compilación anteriores (excepto el activo)
]


def _safe_remove(path: str) -> Tuple[bool, str]:
    """Elimina un archivo o directorio de forma segura. Retorna (éxito, mensaje)."""
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True, f"Archivo eliminado: {path}"
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            return True, f"Directorio eliminado: {path}"
        return False, f"No encontrado: {path}"
    except PermissionError:
        return False, f"Sin permisos para eliminar: {path}"
    except Exception as exc:
        return False, f"Error al eliminar {path}: {exc}"


def clean_temp_logs(base_dir: str = "") -> List[str]:
    """
    Elimina logs temporales y reportes ya transmitidos del directorio TEMP
    y del directorio base del proyecto.
    Retorna lista de acciones realizadas.
    """
    actions: List[str] = []
    search_dirs = [tempfile.gettempdir()]
    if base_dir and os.path.isdir(base_dir):
        search_dirs.append(base_dir)

    for directory in search_dirs:
        for pattern in _TEMP_PATTERNS:
            for match in glob.glob(os.path.join(directory, pattern)):
                ok, msg = _safe_remove(match)
                actions.append(msg)
                if ok:
                    logger.info("GC: %s", msg)
    return actions


def clean_build_residues(project_root: str) -> List[str]:
    """
    Elimina residuos de compilación PyInstaller: carpeta build/, __pycache__/
    y bytecode .pyc/.pyo dentro del proyecto.
    NO elimina dist/ (contiene el .exe activo) ni el .spec activo.
    Retorna lista de acciones realizadas.
    """
    actions: List[str] = []
    if not os.path.isdir(project_root):
        return [f"Directorio no encontrado: {project_root}"]

    # Carpeta build/
    build_path = os.path.join(project_root, "build")
    if os.path.isdir(build_path):
        ok, msg = _safe_remove(build_path)
        actions.append(msg)

    # __pycache__ recursivos
    for root, dirs, _ in os.walk(project_root):
        # No entrar en .venv ni en dist
        dirs[:] = [d for d in dirs if d not in (".venv", "dist")]
        for d in dirs:
            if d == "__pycache__":
                ok, msg = _safe_remove(os.path.join(root, d))
                actions.append(msg)

    # Archivos .pyc / .pyo sueltos
    for pattern in ("**/*.pyc", "**/*.pyo"):
        for match in glob.glob(os.path.join(project_root, pattern), recursive=True):
            if ".venv" not in match and "dist" not in match:
                ok, msg = _safe_remove(match)
                actions.append(msg)

    return actions


def run_full_gc(project_root: str) -> dict:
    """
    Ejecuta el ciclo completo de Garbage Collection:
    1. Limpia logs temporales en TEMP y en el proyecto.
    2. Limpia residuos de compilación.
    Retorna un diccionario con el resumen de acciones.
    """
    logger.info("GarbageCollector: iniciando ciclo completo de limpieza...")
    temp_actions  = clean_temp_logs(base_dir=project_root)
    build_actions = clean_build_residues(project_root=project_root)

    summary = {
        "temp_logs_cleaned":   len([a for a in temp_actions  if a.startswith("Archivo") or a.startswith("Directorio")]),
        "build_residues_cleaned": len([a for a in build_actions if a.startswith("Archivo") or a.startswith("Directorio")]),
        "temp_actions":  temp_actions,
        "build_actions": build_actions,
    }
    logger.info(
        "GarbageCollector: limpieza completa. Temp: %d | Build: %d",
        summary["temp_logs_cleaned"],
        summary["build_residues_cleaned"],
    )
    return summary
