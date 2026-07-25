"""Dependency-independent identities for shared IR documents.

``IRCanonicalIdentity@1`` hashes a canonical JSON preimage containing the
canonical profile, domain, schema version, and payload.  Its textual content
identifier is always CIDv1/base32-lower/raw/sha2-256.  CID bytes are encoded
locally from fixed multicodec values, so optional CID packages cannot affect
the result.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import (
    CANONICAL_JSON_PROFILE,
    CollectionKind,
    CollectionSchema,
    PathInput,
    canonical_bytes,
)


IDENTITY_PROFILE = "IRCanonicalIdentity@1"
DIGEST_ALGORITHM = "sha2-256"
DIGEST_LABEL = "sha256"
CID_VERSION = 1
CID_CODEC = "raw"
CID_CODEC_CODE = 0x55
MULTIHASH_CODE = 0x12
MULTIBASE = "base32"


class IdentityError(ValueError):
    """Raised for an invalid identity namespace or encoded digest."""


@dataclass(frozen=True)
class IdentityProfile:
    """Machine-readable declaration of the fixed identity profile."""

    name: str = IDENTITY_PROFILE
    canonical_json: str = CANONICAL_JSON_PROFILE
    digest: str = DIGEST_ALGORITHM
    digest_label: str = DIGEST_LABEL
    cid_version: int = CID_VERSION
    cid_codec: str = CID_CODEC
    cid_codec_code: int = CID_CODEC_CODE
    multihash_code: int = MULTIHASH_CODE
    multibase: str = MULTIBASE


DEFAULT_IDENTITY_PROFILE = IdentityProfile()


@dataclass(frozen=True)
class CanonicalIdentity:
    """Canonical preimage bytes and their fixed digest/CID representations."""

    domain: str
    schema_version: str
    canonical_bytes: bytes
    digest: str
    cid: str
    profile: str = IDENTITY_PROFILE

    @property
    def sha256(self) -> str:
        """Return the lower-case SHA-256 hex without its algorithm label."""

        return self.digest.removeprefix(f"{DIGEST_LABEL}:")

    def to_dict(self) -> dict[str, str]:
        """Return stable, payload-free identity metadata."""

        return {
            "cid": self.cid,
            "digest": self.digest,
            "domain": self.domain,
            "profile": self.profile,
            "schema_version": self.schema_version,
        }


# Concise annotation alias for downstream shared-core modules.
IRIdentity = CanonicalIdentity


def _namespace_component(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise IdentityError(f"{name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise IdentityError(f"{name} must not contain control characters")
    if not normalized or normalized != normalized.strip():
        raise IdentityError(
            f"{name} must be non-empty and have no surrounding whitespace"
        )
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise IdentityError(
            f"{name} contains an unpaired Unicode surrogate"
        ) from exc
    return normalized


def identity_preimage(
    value: Any,
    *,
    domain: str,
    schema_version: str,
    collection_schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None = None,
) -> bytes:
    """Return the domain- and schema-separated canonical identity preimage."""

    normalized_domain = _namespace_component(domain, name="domain")
    normalized_version = _namespace_component(
        schema_version,
        name="schema_version",
    )
    payload = canonical_bytes(value, collection_schema=collection_schema)

    # Insert payload bytes directly into the key-sorted envelope.  Decoding
    # and re-encoding through a binary float could lose Decimal precision.
    return b"".join(
        (
            b'{"canonical_json":',
            canonical_bytes(CANONICAL_JSON_PROFILE),
            b',"domain":',
            canonical_bytes(normalized_domain),
            b',"payload":',
            payload,
            b',"profile":',
            canonical_bytes(IDENTITY_PROFILE),
            b',"schema_version":',
            canonical_bytes(normalized_version),
            b"}",
        )
    )


def digest_bytes(data: bytes | bytearray | memoryview) -> bytes:
    """Return the fixed SHA-256 digest bytes."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    return hashlib.sha256(bytes(data)).digest()


def digest_for_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return ``sha256:<lowercase hex>`` for bytes."""

    return f"{DIGEST_LABEL}:{digest_bytes(data).hex()}"


def _uvarint(value: int) -> bytes:
    if value < 0:
        raise IdentityError("varints cannot encode negative values")
    encoded = bytearray()
    while True:
        octet = value & 0x7F
        value >>= 7
        encoded.append(octet | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def cid_from_digest(digest: bytes | bytearray | memoryview) -> str:
    """Encode a 32-byte SHA-256 digest using the fixed CID profile."""

    if not isinstance(digest, (bytes, bytearray, memoryview)):
        raise TypeError("digest must be bytes-like")
    raw_digest = bytes(digest)
    digest_size = hashlib.sha256().digest_size
    if len(raw_digest) != digest_size:
        raise IdentityError(
            f"{DIGEST_ALGORITHM} digest must be {digest_size} bytes"
        )

    multihash = (
        _uvarint(MULTIHASH_CODE)
        + _uvarint(len(raw_digest))
        + raw_digest
    )
    cid_bytes = (
        _uvarint(CID_VERSION)
        + _uvarint(CID_CODEC_CODE)
        + multihash
    )
    encoded = (
        base64.b32encode(cid_bytes)
        .decode("ascii")
        .lower()
        .rstrip("=")
    )
    return "b" + encoded


def cid_for_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return CIDv1/raw/sha2-256/base32-lower for ``data``."""

    return cid_from_digest(digest_bytes(data))


def identity_for(
    value: Any,
    *,
    domain: str,
    schema_version: str,
    collection_schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None = None,
) -> CanonicalIdentity:
    """Build a canonical identity for a JSON-like IR declaration."""

    normalized_domain = _namespace_component(domain, name="domain")
    normalized_version = _namespace_component(
        schema_version,
        name="schema_version",
    )
    preimage = identity_preimage(
        value,
        domain=normalized_domain,
        schema_version=normalized_version,
        collection_schema=collection_schema,
    )
    raw_digest = digest_bytes(preimage)
    return CanonicalIdentity(
        domain=normalized_domain,
        schema_version=normalized_version,
        canonical_bytes=preimage,
        digest=f"{DIGEST_LABEL}:{raw_digest.hex()}",
        cid=cid_from_digest(raw_digest),
    )


def verify_identity(
    identity: CanonicalIdentity,
    value: Any,
    *,
    collection_schema: CollectionSchema
    | Mapping[PathInput, CollectionKind | str]
    | None = None,
) -> bool:
    """Return whether ``value`` exactly matches a recorded identity."""

    if (
        not isinstance(identity, CanonicalIdentity)
        or identity.profile != IDENTITY_PROFILE
        or not isinstance(identity.domain, str)
        or not isinstance(identity.schema_version, str)
        or not isinstance(identity.canonical_bytes, bytes)
        or not isinstance(identity.digest, str)
        or not isinstance(identity.cid, str)
        or not identity.digest.isascii()
        or not identity.cid.isascii()
    ):
        return False
    try:
        actual = identity_for(
            value,
            domain=identity.domain,
            schema_version=identity.schema_version,
            collection_schema=collection_schema,
        )
    except (TypeError, ValueError):
        return False
    return (
        hmac.compare_digest(
            actual.canonical_bytes,
            identity.canonical_bytes,
        )
        and hmac.compare_digest(actual.digest, identity.digest)
        and hmac.compare_digest(actual.cid, identity.cid)
    )


# Readable aliases used by callers with different identity vocabulary.
canonical_identity = identity_for
compute_identity = identity_for
sha256_digest = digest_for_bytes


__all__ = [
    "CID_CODEC",
    "CID_CODEC_CODE",
    "CID_VERSION",
    "CanonicalIdentity",
    "DEFAULT_IDENTITY_PROFILE",
    "DIGEST_ALGORITHM",
    "DIGEST_LABEL",
    "IDENTITY_PROFILE",
    "IRIdentity",
    "IdentityError",
    "IdentityProfile",
    "MULTIBASE",
    "MULTIHASH_CODE",
    "canonical_identity",
    "cid_for_bytes",
    "cid_from_digest",
    "compute_identity",
    "digest_bytes",
    "digest_for_bytes",
    "identity_for",
    "identity_preimage",
    "sha256_digest",
    "verify_identity",
]
