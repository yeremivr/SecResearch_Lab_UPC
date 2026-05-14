import io
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Generator, Optional

from .VolatileMedia import VolatileMedia

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

logger = logging.getLogger("SentinelV.MediaSensorValidation")

# Instancia global para evitar overhead de creación repetida
_media_instance: Optional[VolatileMedia] = None


def get_media_instance() -> VolatileMedia:
    """Obtiene la instancia singleton de VolatileMedia."""
    global _media_instance
    if _media_instance is None:
        _media_instance = VolatileMedia()
    return _media_instance


def take_screenshot(image_format: str = "PNG") -> io.BytesIO:
    """Captura la pantalla completa y devuelve un buffer en memoria."""
    return get_media_instance().capture_screenshot(image_format=image_format)


def take_webcam_photo(
    video_device_index: int = 0,
    image_format: str = "JPEG",
) -> io.BytesIO:
    """Captura una fotografía de la webcam y devuelve un buffer en memoria."""
    return get_media_instance().capture_webcam_frame(video_device_index=video_device_index, image_format=image_format)


def _encode_video_with_ffmpeg(input_path: str, output_path: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg no está disponible para codificar video con libx264.")

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_path,
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        output_path,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló al codificar el video: {result.stderr.strip()}"
        )


def record_diagnostic_video(
    seconds: int = 6,
    fps: int = 4,
    video_device_index: int = 0,
    jpeg_quality: int = 80,
) -> io.BytesIO:
    """Registra un video MP4 compatible de la webcam en memoria."""
    if cv2 is None:
        raise ImportError(
            "OpenCV es requerido para capturar video. Instale opencv-python en el entorno."
        )

    capture = cv2.VideoCapture(video_device_index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"No se pudo abrir el dispositivo de video {video_device_index}")

    temp_raw_path = None
    temp_final_path = None
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        frame_count = max(1, int(seconds * fps))

        temp_raw_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_raw_path = temp_raw_file.name
        temp_raw_file.close()

        fourcc = cv2.VideoWriter_fourcc("m", "p", "4", "v")
        writer = cv2.VideoWriter(temp_raw_path, fourcc, float(fps), (width, height))
        if not writer.isOpened():
            raise RuntimeError("No se pudo inicializar el codificador de video MP4.")

        for frame_index in range(frame_count):
            success, frame = capture.read()
            if not success or frame is None:
                logger.warning("Fallo al capturar frame %d, saltando", frame_index)
                continue

            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height))

            writer.write(frame)
            time.sleep(1.0 / max(1.0, fps))

        writer.release()

        final_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_final_path = final_file.name
        final_file.close()

        if shutil.which("ffmpeg") is not None:
            _encode_video_with_ffmpeg(temp_raw_path, temp_final_path)
            source_path = temp_final_path
        else:
            logger.warning(
                "ffmpeg no disponible, retornando MP4 codificado con mp4v."
            )
            source_path = temp_raw_path

        buffer = io.BytesIO()
        with open(source_path, "rb") as source_file:
            buffer.write(source_file.read())
        buffer.seek(0)
        return buffer
    finally:
        capture.release()
        for path in (temp_raw_path, temp_final_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def stream_live_video_fragments(
    duration_seconds: int = 10,
    fps: int = 2,
    video_device_index: int = 0,
    jpeg_quality: int = 80,
) -> Generator[bytes, None, None]:
    """Generador de fragmentos de video en vivo con compresión JPEG."""
    if cv2 is None:
        raise ImportError("OpenCV es requerido para streaming de video.")
    
    capture = cv2.VideoCapture(video_device_index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"No se pudo abrir el dispositivo de video {video_device_index}")

    encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
    end_time = time.time() + duration_seconds

    try:
        while time.time() < end_time:
            success, frame = capture.read()
            if not success or frame is None:
                logger.warning("Error capturando frame en stream, saltando")
                continue
            
            success, encoded = cv2.imencode(".jpg", frame, encode_params)
            if success and encoded is not None:
                yield encoded.tobytes()
            
            time.sleep(1.0 / max(1.0, fps))
    finally:
        capture.release()


def stream_live_video_socket_stub(
    host: str = "127.0.0.1",
    port: int = 9001,
    duration_seconds: int = 10,
    fps: int = 2,
) -> None:
    """Stub básico para transmitir fragmentos rápidos de imagen a través de sockets."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.settimeout(5)
        try:
            client_socket.connect((host, port))
            for fragment in stream_live_video_fragments(
                duration_seconds=duration_seconds,
                fps=fps,
            ):
                client_socket.sendall(fragment)
        except Exception as exc:
            logger.warning("No se pudo establecer transmisión socket stub: %s", exc)
            raise
