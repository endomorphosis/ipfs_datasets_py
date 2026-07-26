"""Dependency-independent content identity for shared IR documents.

The ``ir-canonical-identity-v1`` profile hashes a canonical JSON envelope that
binds the canonicalization profile, IR domain, schema version, collection
semantics, and payload.  Its wire profile is fixed:

* SHA-256 / ``sha2-256`` multihash (code ``0x12``);
* CIDv1;
* ``raw`` multicodec (code ``0x55``);
* unpadded lowercase base32 multibase text (prefix ``b``).

CID bytes are assembled directly from the fixed multiformat codes.  Optional
CID packages are intentionally neither imported nor consulted, so installing
or removing one cannot change an identifier.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import unicodedata
from typing import Any

from .canonical import (
    CANONICAL_JSON_PROFILE,
    CanonicalizationError,
    CollectionRule,
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes,
    coerce_collection_schema,
)


IDENTITY_PROFILE_NAME = "ir-canonical-identity-v1"
CID_VERSION = 1
MULTICODEC_NAME = "raw"
MULTICODEC_CODE = 0x55
MULTIHASH_NAME = "sha2-256"
MULTIHASH_CODE = 0x12
DIGEST_SIZE = 32
MULTIBASE_NAME = "base32"


@dataclass(frozen=True, slots=True)
class IdentityProfile:
    """Machine-readable declaration of the fixed identity profile."""

    name: str = IDENTITY_PROFILE_NAME
    canonicalization: str = CANONICAL_JSON_PROFILE
    digest: str = "sha256"
    digest_size: int = DIGEST_SIZE
    cid_version: int = CID_VERSION
    multicodec: str = MULTICODEC_NAME
    multicodec_code: int = MULTICODEC_CODE
    multihash: str = MULTIHASH_NAME
    multihash_code: int = MULTIHASH_CODE
    multibase: str = MULTIBASE_NAME

    def to_dict(self) -> dict[str, str | int]:
        """Return a stable JSON-ready description of this profile."""

        return {
            "canonicalization": self.canonicalization,
            "cid_version": self.cid_version,
            "digest": self.digest,
            "digest_size": self.digest_size,
            "multibase": self.multibase,
            "multicodec": self.multicodec,
            "multicodec_code": self.multicodec_code,
            "multihash": self.multihash,
            "multihash_code": self.multihash_code,
            "name": self.name,
        }


IDENTITY_PROFILE = IdentityProfile()


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    """The canonical preimage and both textual forms of one IR identity."""

    profile: str
    domain: str
    schema_version: str
    canonical_bytes: bytes
    digest: str
    cid: str

    @property
    def hexdigest(self) -> str:
        """Return the lowercase SHA-256 hexadecimal digest without its label."""

        return self.digest.removeprefix("sha256:")

    @property
    def identifier(self) -> str:
        """Return the canonical textual identifier (the CIDv1 string)."""

        return self.cid

    def to_dict(self) -> dict[str, str]:
        """Return JSON-ready identity metadata (excluding the byte preimage)."""

        return {
            "cid": self.cid,
            "digest": self.digest,
            "domain": self.domain,
            "profile": self.profile,
            "schema_version": self.schema_version,
        }


def _normalized_discriminator(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized.strip() != normalized:
        raise CanonicalizationError(
            f"{label} must be non-empty and have no surrounding whitespace"
        )
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(
            f"{label} contains an unpaired Unicode surrogate"
        ) from exc
    return normalized


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("unsigned varints cannot encode negative values")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def sha256_digest(data: bytes | bytearray | memoryview) -> str:
    """Return the fixed digest label for raw *data*."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("sha256_digest expects bytes-like input")
    return f"sha256:{hashlib.sha256(bytes(data)).hexdigest()}"


def cid_v1_from_digest(digest: bytes | bytearray | memoryview) -> str:
    """Encode a 32-byte SHA-256 digest with the profile's fixed CID settings."""

    raw_digest = bytes(digest)
    if len(raw_digest) != DIGEST_SIZE:
        raise ValueError(
            f"{MULTIHASH_NAME} digest must be exactly {DIGEST_SIZE} bytes"
        )
    multihash = (
        _varint(MULTIHASH_CODE)
        + _varint(DIGEST_SIZE)
        + raw_digest
    )
    cid_bytes = (
        _varint(CID_VERSION)
        + _varint(MULTICODEC_CODE)
        + multihash
    )
    encoded = base64.b32encode(cid_bytes).decode("ascii").rstrip("=").lower()
    return "b" + encoded


def cid_v1(data: bytes | bytearray | memoryview) -> str:
    """Return the fixed-profile CIDv1 for raw *data*."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("cid_v1 expects bytes-like input")
    return cid_v1_from_digest(hashlib.sha256(bytes(data)).digest())


def identity_preimage(
    payload: Any,
    *,
    domain: str,
    schema_version: str,
    collection_schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
    collection_semantics: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
) -> bytes:
    """Return canonical bytes for the domain- and schema-separated preimage."""

    if collection_schema is not None and collection_semantics is not None:
        raise TypeError(
            "use either collection_schema or collection_semantics, not both"
        )
    normalized_domain = _normalized_discriminator(domain, label="domain")
    normalized_version = _normalized_discriminator(
        schema_version, label="schema_version"
    )
    schema = coerce_collection_schema(
        collection_schema
        if collection_schema is not None
        else collection_semantics
    )

    # Canonicalize the payload with its path-relative collection declaration,
    # then parse-free embed those bytes into an envelope.  The fixed envelope
    # fields cannot be affected by caller rules.
    canonical_payload = canonical_json_bytes(
        payload,
        collection_schema=schema,
    )
    # Assemble in map-key order.  Embedding the pre-canonicalized payload this
    # way avoids converting Decimal values through a lossy general JSON parser.
    fields = (
        (b'"canonicalization":', canonical_json_bytes(CANONICAL_JSON_PROFILE)),
        (b'"collection_semantics":', canonical_json_bytes(schema.to_dict())),
        (b'"domain":', canonical_json_bytes(normalized_domain)),
        (b'"identity_profile":', canonical_json_bytes(IDENTITY_PROFILE_NAME)),
        (b'"payload":', canonical_payload),
        (b'"schema_version":', canonical_json_bytes(normalized_version)),
    )
    return b"{" + b",".join(key + value for key, value in fields) + b"}"


def canonical_identity(
    payload: Any,
    *,
    domain: str,
    schema_version: str,
    collection_schema: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
    collection_semantics: (
        CollectionSchema
        | Mapping[str, CollectionSemantics | str]
        | Sequence[CollectionRule]
        | None
    ) = None,
) -> CanonicalIdentity:
    """Compute the shared canonical identity of an IR payload."""

    canonical_bytes = identity_preimage(
        payload,
        domain=domain,
        schema_version=schema_version,
        collection_schema=collection_schema,
        collection_semantics=collection_semantics,
    )
    raw_digest = hashlib.sha256(canonical_bytes).digest()
    return CanonicalIdentity(
        profile=IDENTITY_PROFILE_NAME,
        domain=_normalized_discriminator(domain, label="domain"),
        schema_version=_normalized_discriminator(
            schema_version, label="schema_version"
        ),
        canonical_bytes=canonical_bytes,
        digest=f"sha256:{raw_digest.hex()}",
        cid=cid_v1_from_digest(raw_digest),
    )


# Intuitive aliases for adapters and manifest code.
compute_identity = canonical_identity
identity_for = canonical_identity


__all__ = [
    "CID_VERSION",
    "DIGEST_SIZE",
    "IDENTITY_PROFILE",
    "IDENTITY_PROFILE_NAME",
    "MULTIBASE_NAME",
    "MULTICODEC_CODE",
    "MULTICODEC_NAME",
    "MULTIHASH_CODE",
    "MULTIHASH_NAME",
    "CanonicalIdentity",
    "IdentityProfile",
    "canonical_identity",
    "cid_v1",
    "cid_v1_from_digest",
    "compute_identity",
    "identity_for",
    "identity_preimage",
    "sha256_digest",
]
