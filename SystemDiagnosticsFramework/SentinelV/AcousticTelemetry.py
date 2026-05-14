import io
import logging
import shutil
import subprocess
from typing import Generator, Optional

try:
    from pydub import AudioSegment
except ImportError:  # pragma: no cover
    AudioSegment = None

from .MediaStreamController import MediaStreamController

logger = logging.getLogger("SentinelV.AcousticTelemetry")


def capture_audio_segment(
    seconds: int = 10,
    audio_device_index: int = 0,
    sample_rate: int = 44100,
    channels: int = 2,
    chunk_size: int = 1024,
) -> io.BytesIO:
    """Captura un segmento WAV de audio de la entrada de micrófono."""
    controller = MediaStreamController(
        audio_device_index=audio_device_index,
        sample_rate=sample_rate,
        channels=channels,
        chunk_size=chunk_size,
    )
    return controller.capture_audio_wav(duration_seconds=seconds)


def capture_audio_mp3(
    seconds: int = 10,
    audio_device_index: int = 0,
    sample_rate: int = 44100,
    channels: int = 2,
    chunk_size: int = 1024,
    bitrate: str = "192k",
) -> io.BytesIO:
    """Captura un segmento de audio y lo codifica como MP3 estándar."""
    wav_buffer = capture_audio_segment(
        seconds=seconds,
        audio_device_index=audio_device_index,
        sample_rate=sample_rate,
        channels=channels,
        chunk_size=chunk_size,
    )
    wav_buffer.seek(0)

    if AudioSegment is not None:
        try:
            audio = AudioSegment.from_file(wav_buffer, format="wav")
            audio = audio.set_frame_rate(sample_rate).set_channels(channels)
            mp3_buffer = io.BytesIO()
            audio.export(
                mp3_buffer,
                format="mp3",
                codec="libmp3lame",
                bitrate=bitrate,
                parameters=["-qscale:a", "2"],
            )
            mp3_buffer.seek(0)
            return mp3_buffer
        except Exception as exc:
            logger.warning("Error al convertir WAV a MP3 con pydub: %s", exc)

    if shutil.which("ffmpeg") is not None:
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0", "-vn", "-codec:a", "libmp3lame",
            "-b:a", bitrate, "-f", "mp3", "pipe:1",
        ]
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(wav_buffer.read())
        if process.returncode != 0:
            logger.warning(
                "ffmpeg falló al convertir WAV a MP3: %s. Usando fallback WAV.",
                stderr.decode(errors="replace"),
            )
            wav_buffer.seek(0)
            return wav_buffer
        mp3_buffer = io.BytesIO(stdout)
        mp3_buffer.seek(0)
        return mp3_buffer

    # Fallback controlado: ninguna dependencia de conversión disponible.
    # Se entrega el WAV nativo para garantizar la telemetría bajo cualquier circunstancia.
    logger.warning(
        "No se encontró pydub ni ffmpeg. Entregando audio en formato WAV nativo (fallback)."
    )
    wav_buffer.seek(0)
    return wav_buffer


def open_audio_listener(
    segment_seconds: int = 5,
    total_duration_seconds: int = 30,
    audio_device_index: int = 0,
    sample_rate: int = 44100,
    channels: int = 1,
    chunk_size: int = 1024,
) -> Generator[io.BytesIO, None, None]:
    """Generador de fragmentos de audio continuo si el ancho de banda lo permite."""
    elapsed = 0.0
    while elapsed < total_duration_seconds:
        segment = capture_audio_segment(
            seconds=segment_seconds,
            audio_device_index=audio_device_index,
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
        )
        yield segment
        elapsed += segment_seconds


class AudioStreamListener:
    """Escucha continua de audio que produce segmentos WAV listos para envío."""

    def __init__(
        self,
        segment_seconds: int = 5,
        total_duration_seconds: int = 30,
        audio_device_index: int = 0,
    ) -> None:
        self.segment_seconds = segment_seconds
        self.total_duration_seconds = total_duration_seconds
        self.audio_device_index = audio_device_index
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def stream(self) -> Generator[io.BytesIO, None, None]:
        elapsed = 0.0
        while not self._stopped and elapsed < self.total_duration_seconds:
            yield capture_audio_segment(
                seconds=self.segment_seconds,
                audio_device_index=self.audio_device_index,
            )
            elapsed += self.segment_seconds
