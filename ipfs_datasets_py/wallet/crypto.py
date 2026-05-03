"""Envelope encryption helpers for wallet data."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .exceptions import DecryptionError
from .manifest import canonical_bytes

ENCRYPTION_SUITE = "AES-256-GCM"
KEY_WRAP_ALGORITHM = "AES-256-GCMKW-local"


def random_key() -> bytes:
    return os.urandom(32)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


@dataclass(frozen=True)
class EncryptedBlob:
    suite: str
    nonce: str
    ciphertext: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "suite": self.suite,
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EncryptedBlob":
        return cls(
            suite=str(data["suite"]),
            nonce=str(data["nonce"]),
            ciphertext=str(data["ciphertext"]),
        )


def encrypt_bytes(plaintext: bytes, key: bytes, aad: Dict[str, Any]) -> EncryptedBlob:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, canonical_bytes(aad))
    return EncryptedBlob(
        suite=ENCRYPTION_SUITE,
        nonce=b64encode(nonce),
        ciphertext=b64encode(ciphertext),
    )


def decrypt_bytes(blob: EncryptedBlob, key: bytes, aad: Dict[str, Any]) -> bytes:
    if blob.suite != ENCRYPTION_SUITE:
        raise DecryptionError(f"Unsupported encryption suite: {blob.suite}")
    try:
        return AESGCM(key).decrypt(b64decode(blob.nonce), b64decode(blob.ciphertext), canonical_bytes(aad))
    except InvalidTag as exc:
        raise DecryptionError("Unable to authenticate encrypted wallet data") from exc


def wrap_key(dek: bytes, recipient_secret: bytes, aad: Dict[str, Any]) -> str:
    blob = encrypt_bytes(dek, recipient_secret, aad)
    return b64encode(canonical_bytes(blob.to_dict()))


def unwrap_key(wrapped_dek: str, recipient_secret: bytes, aad: Dict[str, Any]) -> bytes:
    import json

    try:
        blob_data = json.loads(b64decode(wrapped_dek).decode("utf-8"))
        return decrypt_bytes(EncryptedBlob.from_dict(blob_data), recipient_secret, aad)
    except DecryptionError:
        raise
    except Exception as exc:
        raise DecryptionError("Unable to unwrap wallet data key") from exc
