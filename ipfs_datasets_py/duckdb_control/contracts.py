"""Canonical identity, provenance, and blob-reference contracts (DQK-004).

Defines strict shared types for:

* schema identifiers
* database snapshot identities
* content IDs (CIDs) and source-byte digests
* normalized timestamps
* idempotency keys
* export receipts
* immutable IPLD / CAR / Parquet content references

Identity-bearing source bytes round-trip without normalization drift.  JSON
numbers that would lose precision, non-finite floats, and non-UTC wall times
are rejected rather than silently rewritten.  Content references are
storage-neutral (no filesystem paths as authority) and bind a tamper-evident
digest.

Importing this module is inert: no database, network, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence

__all__ = [
    "CONTRACTS_SCHEMA",
    "CONTENT_REF_SCHEMA",
    "EXPORT_RECEIPT_SCHEMA",
    "IDEMPOTENCY_KEY_SCHEMA",
    "SCHEMA_ID_SCHEMA",
    "SNAPSHOT_ID_SCHEMA",
    "ContractError",
    "ContentMediaType",
    "ContentReference",
    "ExportReceipt",
    "IdempotencyKey",
    "SchemaId",
    "SnapshotId",
    "SourceDigest",
    "canonical_json_bytes",
    "content_identity",
    "normalize_timestamp",
    "parse_content_reference",
    "parse_schema_id",
    "parse_snapshot_id",
    "parse_source_digest",
    "round_trip_identity_bytes",
]


# ---------------------------------------------------------------------------
# Schema identities
# ---------------------------------------------------------------------------

CONTRACTS_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-contracts@1"
SCHEMA_ID_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-schema-id@1"
SNAPSHOT_ID_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-snapshot-id@1"
IDEMPOTENCY_KEY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-idempotency-key@1"
)
EXPORT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-export-receipt@1"
)
CONTENT_REF_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-content-reference@1"
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_ID = re.compile(
    r"^[a-z][a-z0-9_.-]{0,190}/[a-z0-9][a-z0-9_.@-]{0,190}$"
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_CID_V0 = re.compile(r"^Qm[1-9A-HJ-NP-Za-km-z]{44}$")
_CID_V1 = re.compile(r"^b[a-z2-7]{10,200}$")
_MAX_JSON_BYTES: Final[int] = 1_048_576
_MAX_KEY_BYTES: Final[int] = 512


class ContractError(ValueError):
    """Raised when a contract input is malformed, drifted, or unsafe."""


class ContentMediaType(str, Enum):
    """Closed set of immutable content reference media types."""

    IPLD_RAW = "ipld-raw"
    IPLD_DAG_CBOR = "ipld-dag-cbor"
    CAR = "car"
    PARQUET = "parquet"
    JSON = "json"
    BYTES = "bytes"


# ---------------------------------------------------------------------------
# Canonical JSON / digests
# ---------------------------------------------------------------------------


def _reject_nonfinite(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN/Inf
            raise ContractError(f"non-finite float at {path}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _reject_nonfinite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_nonfinite(item, f"{path}[{index}]")


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return normalize_timestamp(value)
    return value


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to deterministic UTF-8 JSON bytes.

    Rules (fail-closed):

    * object keys sorted
    * no insignificant whitespace
    * floats must be finite (NaN/Inf rejected)
    * integers stay integers (no silent float coercion)
    * datetimes become normalized UTC ``...Z`` text
    """

    plain = _plain(payload)
    _reject_nonfinite(plain)
    try:
        raw = json.dumps(
            plain,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"payload is not canonical-JSON-safe: {exc}") from exc
    if len(raw) > _MAX_JSON_BYTES:
        raise ContractError(
            f"canonical JSON exceeds {_MAX_JSON_BYTES}-byte bound"
        )
    return raw


def content_identity(payload: Any) -> str:
    """Return ``sha256:<hex>`` over :func:`canonical_json_bytes`."""

    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def parse_source_digest(value: str | SourceDigest) -> str:
    """Accept ``sha256:<64 hex>`` or bare 64-hex; return normalized form."""

    if isinstance(value, SourceDigest):
        return value.digest
    if not isinstance(value, str) or not value.strip():
        raise ContractError("source digest must be nonempty text")
    text = value.strip().lower()
    if text.startswith("sha256:"):
        hex_part = text[len("sha256:") :]
    else:
        hex_part = text
    if _SHA256_HEX.fullmatch(hex_part) is None:
        raise ContractError(
            "source digest must be sha256:<64 lowercase hex> or 64 hex chars"
        )
    return f"sha256:{hex_part}"


@dataclass(frozen=True)
class SourceDigest:
    """Tamper-evident digest of exact source bytes."""

    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", parse_source_digest(self.digest))

    @classmethod
    def from_bytes(cls, data: bytes) -> "SourceDigest":
        if not isinstance(data, (bytes, bytearray)):
            raise ContractError("source bytes must be bytes")
        return cls(digest="sha256:" + hashlib.sha256(bytes(data)).hexdigest())

    def to_dict(self) -> dict[str, str]:
        return {"digest": self.digest}


def round_trip_identity_bytes(payload: Mapping[str, Any] | Sequence[Any]) -> bytes:
    """Canonicalize, re-parse, re-canonicalize; require byte identity."""

    first = canonical_json_bytes(payload)
    restored = json.loads(first.decode("utf-8"))
    second = canonical_json_bytes(restored)
    if first != second:
        raise ContractError("identity-bearing bytes drifted under round-trip")
    return first


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def normalize_timestamp(value: datetime | str) -> str:
    """Normalize to UTC ISO-8601 with ``Z`` and second precision.

    Naive datetimes are rejected (ambiguous wall time).  Sub-second fields are
    truncated to whole seconds so re-encoding is stable.
    """

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ContractError("timestamp must not be empty")
        # Accept trailing Z or +00:00 only after parse.
        candidate = text.replace("Z", "+00:00") if text.endswith("Z") else text
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ContractError(f"timestamp is not ISO-8601: {value!r}") from exc
    elif isinstance(value, datetime):
        moment = value
    else:
        raise ContractError("timestamp must be datetime or ISO-8601 text")

    if moment.tzinfo is None:
        raise ContractError("timestamp must be timezone-aware (UTC required)")
    utc = moment.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Schema / snapshot / idempotency
# ---------------------------------------------------------------------------


def parse_schema_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("schema_id must be nonempty text")
    text = value.strip()
    if _SCHEMA_ID.fullmatch(text) is None:
        raise ContractError(
            "schema_id must look like 'namespace/name[@version]'; "
            f"got {value!r}"
        )
    return text


@dataclass(frozen=True)
class SchemaId:
    SCHEMA: ClassVar[str] = SCHEMA_ID_SCHEMA 
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", parse_schema_id(self.value))

    def to_dict(self) -> dict[str, str]:
        return {"schema": SCHEMA_ID_SCHEMA, "value": self.value}


def parse_snapshot_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("snapshot_id must be nonempty text")
    text = value.strip()
    if text.startswith("sha256:"):
        return parse_source_digest(text)
    if _SAFE_TOKEN.fullmatch(text) is None:
        raise ContractError(f"snapshot_id is not a safe token: {value!r}")
    return text


@dataclass(frozen=True)
class SnapshotId:
    """Database snapshot identity (generation digest or safe token)."""

    SCHEMA: ClassVar[str] = SNAPSHOT_ID_SCHEMA 
    value: str
    store_generation: int = 0
    schema_checksum: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", parse_snapshot_id(self.value))
        if not isinstance(self.store_generation, int) or isinstance(
            self.store_generation, bool
        ):
            raise ContractError("store_generation must be an integer")
        if self.store_generation < 0:
            raise ContractError("store_generation must be non-negative")
        if self.schema_checksum:
            object.__setattr__(
                self,
                "schema_checksum",
                parse_source_digest(self.schema_checksum),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_ID_SCHEMA,
            "value": self.value,
            "store_generation": self.store_generation,
            "schema_checksum": self.schema_checksum,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True)
class IdempotencyKey:
    """Caller-supplied idempotency key; exact bytes identity."""

    SCHEMA: ClassVar[str] = IDEMPOTENCY_KEY_SCHEMA 
    key: str
    scope: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ContractError("idempotency key must be nonempty text")
        key = self.key.strip()
        if "\x00" in key or "\n" in key or "\r" in key:
            raise ContractError("idempotency key must be single-line text")
        if len(key.encode("utf-8")) > _MAX_KEY_BYTES:
            raise ContractError(
                f"idempotency key exceeds {_MAX_KEY_BYTES}-byte bound"
            )
        if _SAFE_TOKEN.fullmatch(key) is None:
            raise ContractError("idempotency key contains unsafe characters")
        object.__setattr__(self, "key", key)
        scope = str(self.scope or "default").strip()
        if _SAFE_TOKEN.fullmatch(scope) is None:
            raise ContractError("idempotency scope is not a safe token")
        object.__setattr__(self, "scope", scope)

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": IDEMPOTENCY_KEY_SCHEMA,
            "key": self.key,
            "scope": self.scope,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


# ---------------------------------------------------------------------------
# Content references (storage-neutral, tamper-evident)
# ---------------------------------------------------------------------------


def _parse_cid(value: str) -> str:
    text = value.strip()
    if _CID_V0.fullmatch(text) or _CID_V1.fullmatch(text):
        return text
    if text.startswith("sha256:") and _SHA256_HEX.fullmatch(text[7:]):
        return text
    raise ContractError(
        "content reference requires CIDv0, CIDv1 (base32), or sha256 digest; "
        f"got {value!r}"
    )


def parse_content_reference(payload: Mapping[str, Any]) -> "ContentReference":
    if not isinstance(payload, Mapping):
        raise ContractError("content reference must be an object")
    return ContentReference.from_dict(payload)


@dataclass(frozen=True)
class ContentReference:
    """Storage-neutral immutable content pointer.

    Must not embed filesystem paths as authority.  The digest/CID is the
    identity; optional location hints are non-authoritative.
    """

    SCHEMA: ClassVar[str] = CONTENT_REF_SCHEMA 

    media_type: ContentMediaType
    content_id: str
    byte_size: int
    source_digest: str = ""
    location_hint: str = ""

    def __post_init__(self) -> None:
        media = self.media_type
        if not isinstance(media, ContentMediaType):
            try:
                media = ContentMediaType(str(media))
            except ValueError as exc:
                raise ContractError(
                    f"unsupported content media type: {self.media_type!r}"
                ) from exc
        object.__setattr__(self, "media_type", media)
        object.__setattr__(self, "content_id", _parse_cid(str(self.content_id)))
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise ContractError("byte_size must be an integer")
        if self.byte_size < 0:
            raise ContractError("byte_size must be non-negative")
        if self.source_digest:
            object.__setattr__(
                self, "source_digest", parse_source_digest(self.source_digest)
            )
        hint = str(self.location_hint or "").strip()
        # Reject absolute paths and Windows drives as authority.
        if hint:
            if (
                hint.startswith(("/", "\\"))
                or ".." in hint.split("/")
                or re.match(r"^[A-Za-z]:", hint)
            ):
                raise ContractError(
                    "location_hint must not be a filesystem path authority; "
                    "use a storage-neutral URI or omit"
                )
            if len(hint.encode("utf-8")) > 1024:
                raise ContractError("location_hint exceeds 1024-byte bound")
        object.__setattr__(self, "location_hint", hint)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        media_type: ContentMediaType = ContentMediaType.BYTES,
        location_hint: str = "",
    ) -> "ContentReference":
        digest = SourceDigest.from_bytes(data)
        return cls(
            media_type=media_type,
            content_id=digest.digest,
            byte_size=len(data),
            source_digest=digest.digest,
            location_hint=location_hint,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContentReference":
        return cls(
            media_type=payload.get("media_type", ContentMediaType.BYTES),
            content_id=str(payload.get("content_id") or ""),
            byte_size=int(payload.get("byte_size", 0)),
            source_digest=str(payload.get("source_digest") or ""),
            location_hint=str(payload.get("location_hint") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTENT_REF_SCHEMA,
            "media_type": self.media_type.value,
            "content_id": self.content_id,
            "byte_size": self.byte_size,
            "source_digest": self.source_digest,
            "location_hint": self.location_hint,
        }

    @property
    def identity_id(self) -> str:
        # Identity excludes non-authoritative location hints.
        return content_identity(
            {
                "media_type": self.media_type.value,
                "content_id": self.content_id,
                "byte_size": self.byte_size,
                "source_digest": self.source_digest,
            }
        )

    def verify_bytes(self, data: bytes) -> None:
        """Fail closed when observed bytes do not match the bound digest."""

        observed = SourceDigest.from_bytes(data).digest
        expected = self.source_digest or self.content_id
        if expected.startswith("sha256:") and observed != expected:
            raise ContractError(
                "content reference digest mismatch "
                f"(expected {expected}, observed {observed})"
            )
        if len(data) != self.byte_size:
            raise ContractError(
                f"content reference size mismatch "
                f"(expected {self.byte_size}, observed {len(data)})"
            )


# ---------------------------------------------------------------------------
# Export receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportReceipt:
    """Receipt for a deterministic export render."""

    SCHEMA: ClassVar[str] = EXPORT_RECEIPT_SCHEMA 

    export_id: str
    snapshot: SnapshotId
    content: ContentReference
    created_at: str
    renderer_version: str
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.export_id, str) or not self.export_id.strip():
            raise ContractError("export_id is required")
        if _SAFE_TOKEN.fullmatch(self.export_id.strip()) is None:
            raise ContractError("export_id is not a safe token")
        object.__setattr__(self, "export_id", self.export_id.strip())
        if not isinstance(self.snapshot, SnapshotId):
            raise ContractError("snapshot must be SnapshotId")
        if not isinstance(self.content, ContentReference):
            raise ContractError("content must be ContentReference")
        object.__setattr__(
            self, "created_at", normalize_timestamp(self.created_at)
        )
        if not isinstance(self.renderer_version, str) or not self.renderer_version.strip():
            raise ContractError("renderer_version is required")
        if not self.non_authoritative:
            raise ContractError(
                "export receipts must declare non_authoritative=true"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPORT_RECEIPT_SCHEMA,
            "export_id": self.export_id,
            "snapshot": self.snapshot.to_dict(),
            "content": self.content.to_dict(),
            "created_at": self.created_at,
            "renderer_version": self.renderer_version,
            "non_authoritative": True,
            "identity_id": self.identity_id,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "export_id": self.export_id,
                "snapshot": self.snapshot.to_dict(),
                "content": self.content.to_dict(),
                "created_at": self.created_at,
                "renderer_version": self.renderer_version,
                "non_authoritative": True,
            }
        )
