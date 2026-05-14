
import logging
from io import BytesIO
from typing import Any, Dict, Iterator, Optional

try:
    import requests
    from requests import Response, Session
except ImportError:  # pragma: no cover
    requests = None
    Session = None

logger = logging.getLogger("SentinelV.ReportDispatcher")

MAX_PAYLOAD_SIZE = 8 * 1024 * 1024  # 8 MB


class PayloadTooLargeError(ValueError):
    """Indica que una carga útil excede el tamaño máximo después de segmentación."""


class ReportDispatcher:
    """Despachador de telemetría remota con control de tamaño de carga útil."""

    def __init__(self, session: Optional[Session] = None) -> None:
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            raise ImportError(
                "requests es requerido para enviar reportes HTTPS. Instale requests en el entorno."
            )

    @staticmethod
    def _chunk_bytes(data: bytes) -> Iterator[bytes]:
        for offset in range(0, len(data), MAX_PAYLOAD_SIZE):
            yield data[offset : offset + MAX_PAYLOAD_SIZE]

    def _post_chunk(
        self,
        endpoint: str,
        chunk: bytes,
        metadata: Dict[str, Any],
        chunk_index: int,
        total_chunks: int,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Response:
        payload = {
            "metadata": {**metadata, "chunk_index": chunk_index, "chunk_count": total_chunks},
            "chunk_size": len(chunk),
        }
        files = {
            "payload": ("chunk.bin", chunk, "application/octet-stream"),
        }
        logger.debug(
            "Enviando chunk %s/%s a %s, metadata=%s",
            chunk_index,
            total_chunks,
            endpoint,
            payload["metadata"],
        )
        response = self.session.post(
            endpoint,
            data=payload,
            files=files,
            headers=headers,
            timeout=timeout,
            verify=True,
        )
        response.raise_for_status()
        return response

    def send_report(
        self,
        endpoint: str,
        payload: BytesIO,
        metadata: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> None:
        """Envía el contenido de un buffer segmentado si excede el límite de 8 MB."""
        metadata = metadata or {}
        payload.seek(0)
        data = payload.read()
        if not data:
            raise ValueError("La carga útil está vacía")

        chunks = list(self._chunk_bytes(data))
        total_chunks = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            try:
                self._post_chunk(
                    endpoint=endpoint,
                    chunk=chunk,
                    metadata=metadata,
                    chunk_index=index,
                    total_chunks=total_chunks,
                    headers=headers,
                    timeout=timeout,
                )
            except Exception as exc:
                logger.exception(
                    "Fallo al enviar chunk %s/%s: %s",
                    index,
                    total_chunks,
                    exc,
                )
                raise

    def send_payload(
        self,
        endpoint: str,
        payload_bytes: bytes,
        metadata: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> None:
        buffer = BytesIO(payload_bytes)
        self.send_report(
            endpoint=endpoint,
            payload=buffer,
            metadata=metadata,
            headers=headers,
            timeout=timeout,
        )
