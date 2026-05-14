import io
import logging
import wave
from typing import List, Optional

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import sounddevice as sd
    import numpy as np
except ImportError:  # pragma: no cover
    sd = None
    np = None

logger = logging.getLogger("SentinelV.MediaStreamController")


class DeviceUnavailableError(Exception):
    """Indica que el dispositivo de captura no está disponible."""


class DeviceBusyError(Exception):
    """Indica que el dispositivo de captura está ocupado por otro proceso."""


class MediaStreamController:
    """Controlador de captura de flujo multimedia para pruebas de QA en Windows."""

    def __init__(
        self,
        video_device_index: int = 0,
        audio_device_index: int = 0,
        sample_rate: int = 44100,
        channels: int = 1,
        chunk_size: int = 1024,
        format_: Optional[int] = None,
    ) -> None:
        self.video_device_index = video_device_index
        self.audio_device_index = audio_device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.format_ = format_ or (np.int16 if np is not None else None)
        # FIX: inicializar atributos para evitar AttributeError en close()
        self._audio_stream = None
        self._pyaudio = None

    def _ensure_audio_backend(self) -> None:
        if sd is None or np is None:
            raise ImportError(
                "sounddevice y numpy son requeridos para capturar audio. Instale sounddevice y numpy en el entorno."
            )

    def capture_audio_wav(self, duration_seconds: float = 5.0) -> io.BytesIO:
        """Captura audio de entrada y devuelve un WAV en un buffer en memoria."""
        self._ensure_audio_backend()
        buffer = io.BytesIO()

        try:
            recording = sd.rec(
                int(duration_seconds * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                device=self.audio_device_index,
                dtype='int16'
            )
            sd.wait()

            audio_data = (recording * 32767).astype(np.int16).tobytes()

            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(audio_data)

            buffer.seek(0)
            return buffer
        except Exception as exc:
            raise DeviceUnavailableError(f"No se pudo capturar audio: {exc}") from exc

    def capture_video_frame(self, image_format: str = "JPEG") -> io.BytesIO:
        """Captura un frame de la webcam y lo serializa en memoria."""
        if cv2 is None:
            raise ImportError(
                "OpenCV es requerido para capturar video. Instale opencv-python en el entorno."
            )

        capture = cv2.VideoCapture(self.video_device_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            raise DeviceUnavailableError(
                f"No se pudo abrir el dispositivo de video {self.video_device_index}"
            )

        try:
            success, frame = capture.read()
            if not success or frame is None:
                raise DeviceUnavailableError("No se obtuvo un frame válido de la cámara")

            extension = image_format.lower().replace("jpeg", "jpg")
            success, encoded = cv2.imencode(f".{extension}", frame)
            if not success or encoded is None:
                raise RuntimeError("Fallo al codificar el frame de imagen")

            buffer = io.BytesIO(encoded.tobytes())
            buffer.seek(0)
            return buffer
        except cv2.error as exc:
            raise DeviceBusyError("Error de OpenCV al capturar la cámara") from exc
        finally:
            capture.release()

    def capture_media_snapshot(
        self,
        duration_seconds: float = 5.0,
        frame_count: int = 1,
    ) -> dict:
        """Captura audio y uno o varios frames de video en memoria."""
        audio_buffer = self.capture_audio_wav(duration_seconds=duration_seconds)
        frames: List[io.BytesIO] = [
            self.capture_video_frame() for _ in range(max(1, frame_count))
        ]
        return {"audio": audio_buffer, "frames": frames}

    def close(self) -> None:
        """Libera recursos que mantiene el backend de audio."""
        # FIX: ahora los atributos existen porque se inicializan en __init__
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None
