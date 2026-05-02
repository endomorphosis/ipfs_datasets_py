"""Cryptographic helpers for the document wallet.

The first implementation uses envelope encryption:
- A random 256-bit document encryption key encrypts each document version.
- Recipient wrapping keys encrypt that document key.
- Storage backends only receive ciphertext.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .exceptions import KeyUnwrapError, ManifestIntegrityError

AES256_GCM = "AES-256-GCM"
KEY_WRAP_AES256_GCM = "AES-256-GCM-KW"
NONCE_SIZE = 12
KEY_SIZE = 32


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def generate_key() -> bytes:
    """Return a random 256-bit key."""

    return os.urandom(KEY_SIZE)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_ref(data: bytes) -> str:
    return f"sha256:{sha256_hex(data)}"


@dataclass(frozen=True)
class EncryptedBytes:
    """Serializable encrypted payload."""

    suite: str
    nonce: str
    ciphertext: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite": self.suite,
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EncryptedBytes":
        return cls(
            suite=str(data["suite"]),
            nonce=str(data["nonce"]),
            ciphertext=str(data["ciphertext"]),
        )


def _validate_key(key: bytes) -> None:
    if len(key) != KEY_SIZE:
        raise ValueError("document wallet keys must be 32 bytes")


def encrypt_bytes(
    plaintext: bytes,
    key: bytes,
    *,
    aad: Optional[bytes] = None,
    suite: str = AES256_GCM,
) -> EncryptedBytes:
    """Encrypt bytes with AES-256-GCM."""

    if suite != AES256_GCM:
        raise ValueError(f"unsupported encryption suite: {suite}")
    _validate_key(key)
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return EncryptedBytes(suite=suite, nonce=b64encode(nonce), ciphertext=b64encode(ciphertext))


def decrypt_bytes(payload: EncryptedBytes, key: bytes, *, aad: Optional[bytes] = None) -> bytes:
    """Decrypt an :class:`EncryptedBytes` payload."""

    if payload.suite != AES256_GCM:
        raise ValueError(f"unsupported encryption suite: {payload.suite}")
    _validate_key(key)
    try:
        return AESGCM(key).decrypt(b64decode(payload.nonce), b64decode(payload.ciphertext), aad)
    except InvalidTag as exc:
        raise ManifestIntegrityError("ciphertext authentication failed") from exc


def pack_encrypted_bytes(payload: EncryptedBytes) -> bytes:
    """Pack encrypted bytes for opaque blob storage."""

    return b".".join(
        [
            payload.suite.encode("ascii"),
            payload.nonce.encode("ascii"),
            payload.ciphertext.encode("ascii"),
        ]
    )


def unpack_encrypted_bytes(data: bytes) -> EncryptedBytes:
    """Unpack bytes produced by :func:`pack_encrypted_bytes`."""

    try:
        suite, nonce, ciphertext = data.split(b".", 2)
    except ValueError as exc:
        raise ManifestIntegrityError("encrypted payload has invalid storage format") from exc
    return EncryptedBytes(
        suite=suite.decode("ascii"),
        nonce=nonce.decode("ascii"),
        ciphertext=ciphertext.decode("ascii"),
    )


def wrap_key(dek: bytes, wrapping_key: bytes, *, aad: Optional[bytes] = None) -> EncryptedBytes:
    """Encrypt a document encryption key for a recipient."""

    try:
        return encrypt_bytes(dek, wrapping_key, aad=aad, suite=AES256_GCM)
    except Exception as exc:
        raise KeyUnwrapError("failed to wrap document key") from exc


def unwrap_key(wrapped_dek: EncryptedBytes, wrapping_key: bytes, *, aad: Optional[bytes] = None) -> bytes:
    """Decrypt a wrapped document encryption key."""

    try:
        dek = decrypt_bytes(wrapped_dek, wrapping_key, aad=aad)
    except Exception as exc:
        raise KeyUnwrapError("failed to unwrap document key") from exc
    _validate_key(dek)
    return dek

