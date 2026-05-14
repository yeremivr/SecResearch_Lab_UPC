
import ctypes
import ctypes.wintypes as wintypes
import logging
from typing import Dict, Optional

try:
    import win32gui
    import win32process
except ImportError:  # pragma: no cover
    win32gui = None
    win32process = None

logger = logging.getLogger("SentinelV.AppMetadataProvider")

user32 = ctypes.windll.user32


class AppMetadataProvider:
    """Obtiene título de ventana activa y PID asociado para QA de aplicación."""

    @classmethod
    def _get_foreground_window_handle(cls) -> Optional[int]:
        handle = user32.GetForegroundWindow()
        return handle if handle != 0 else None

    @classmethod
    def _get_window_title(cls, hwnd: int) -> str:
        if win32gui is not None:
            title = win32gui.GetWindowText(hwnd)
            return title or "<sin título>"

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return "<sin título>"

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value or "<sin título>"

    @classmethod
    def _get_process_id(cls, hwnd: int) -> Optional[int]:
        if win32process is not None:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                return int(pid)
            except Exception as exc:
                logger.debug("Error al resolver PID con pywin32: %s", exc)
                return None

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(process_id.value) if process_id.value != 0 else None

    @classmethod
    def get_active_window_metadata(cls) -> Dict[str, Optional[str]]:
        """Devuelve metadata del proceso que tiene el foco en el escritorio."""
        hwnd = cls._get_foreground_window_handle()
        if hwnd is None:
            return {
                "window_handle": None,
                "window_title": "<sin ventana activa>",
                "process_id": None,
            }

        title = cls._get_window_title(hwnd)
        pid = cls._get_process_id(hwnd)
        return {
            "window_handle": hwnd,
            "window_title": title,
            "process_id": pid,
        }
