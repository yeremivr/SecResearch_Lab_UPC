from io import BytesIO
import logging
import threading
from queue import Empty, Queue
from typing import Optional, Tuple

from PIL import ImageGrab

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentinelV.VolatileMedia")


class VolatileMedia:
    """Captura multimedia que evita escritura en disco para análisis forense limitado."""

    def __init__(self) -> None:
        self._task_queue: Queue[Tuple[str, int, str, Queue[BytesIO]]] = Queue()
        self._worker_stop = threading.Event()
        self._worker_thread = threading.Thread(target=self._media_worker, daemon=True)
        self._worker_thread.start()

    def _media_worker(self) -> None:
        while not self._worker_stop.is_set():
            try:
                task_type, device_index, image_format, response_queue = self._task_queue.get(timeout=0.5)
                try:
                    if task_type == "screenshot":
                        result = self._capture_screenshot(image_format)
                    else:
                        result = self._capture_webcam_frame(device_index, image_format)
                    response_queue.put(result)
                except Exception as exc:
                    logger.exception("Error en worker de VolatileMedia: %s", exc)
                    response_queue.put(None)
            except Empty:
                continue

    def stop(self) -> None:
        self._worker_stop.set()
        self._worker_thread.join(timeout=2.0)

    def capture_screenshot(self, image_format: str = "PNG") -> BytesIO:
        """Solicita una captura de pantalla serializada a través de la cola de media."""
        response_queue: Queue[Optional[BytesIO]] = Queue(maxsize=1)
        self._task_queue.put(("screenshot", 0, image_format, response_queue))
        result = response_queue.get(timeout=15)
        if result is None:
            raise RuntimeError("Error al capturar la pantalla en el worker")
        return result

    def capture_webcam_frame(self, video_device_index: int = 0, image_format: str = "JPEG") -> BytesIO:
        """Solicita un frame de webcam serializado a través de la cola de media."""
        response_queue: Queue[Optional[BytesIO]] = Queue(maxsize=1)
        self._task_queue.put(("webcam", video_device_index, image_format, response_queue))
        result = response_queue.get(timeout=15)
        if result is None:
            raise RuntimeError("Error al capturar el frame de webcam en el worker")
        return result

    def _capture_screenshot(self, image_format: str) -> BytesIO:
        try:
            image = ImageGrab.grab()
            buffer = BytesIO()
            image.save(buffer, format=image_format)
            buffer.seek(0)
            return buffer
        except Exception as exc:
            logger.exception("Fallo al capturar la pantalla: %s", exc)
            raise

    def _capture_webcam_frame(self, video_device_index: int = 0, image_format: str = "JPEG") -> BytesIO:
        if cv2 is None:
            raise RuntimeError("OpenCV no está disponible en el entorno")

        capture = cv2.VideoCapture(video_device_index, cv2.CAP_DSHOW)
        try:
            # FIX: corregido de 'device_index' (NameError) a 'video_device_index'
            if not capture.isOpened():
                raise RuntimeError(f"No se pudo abrir la webcam en el dispositivo {video_device_index}")

            success, frame = capture.read()
            if not success or frame is None:
                raise RuntimeError("No se obtuvo un frame válido de la webcam")

            is_success, encoded = cv2.imencode(f".{image_format.lower()}", frame)
            if not is_success or encoded is None:
                raise RuntimeError("Fallo al codificar el frame de webcam")

            buffer = BytesIO(encoded.tobytes())
            buffer.seek(0)
            return buffer
        except Exception as exc:
            logger.exception("Fallo al capturar webcam: %s", exc)
            raise
        finally:
            capture.release()
