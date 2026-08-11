"""Persistent content-addressed patent index snapshot contracts (PATLAW-144).

These records freeze the serialization boundary for durable BM25, vector, and
graph index snapshots. They intentionally contain no builders, embedding I/O,
or retrieval engines. Schema changes must be additive and versioned.

Design invariants
-----------------
* Round-trips are deterministic via :func:`canonical_json` /
  :meth:`PatentIndexSnapshot.to_dict` / :meth:`PatentIndexSnapshot.from_dict`.
* Every index record joins to at least one source CID **and** source version.
* Snapshot roots bind corpus, model, config, code, and schema identities.
* Resume checkpoints, tombstones, compaction roots, and rollback pointers
  retain immutable prior roots; they never rewrite historical payloads.
* Unknown schema or model versions fail closed and cannot open a snapshot.
* Corrupt or cross-tenant manifests fail closed.
* Disclosure and tenant partitions are first-class on every record and
  manifest; private partitions are never collapsible into public ones.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from .retrieval_contracts import (
    DisclosureClass,
    RetrievalFamily,
    SourceSpan,
    is_private_disclosure,
    is_public_disclosure,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

INDEX_SNAPSHOT_SCHEMA_VERSION: Final = "patent.index_snapshot.v1"
INDEX_SNAPSHOT_INTERFACE: Final = "PatentIndexSnapshot@1"
INDEX_STORE_INTERFACE: Final = "PatentIndexStore@1"
INDEX_SNAPSHOT_CODE_VERSION: Final = "1.0.0"

# Known pinned model identity tokens that may open snapshots. Additional
# revisions require an explicit schema/model bump — unknown pins fail closed.
KNOWN_MODEL_PINS: Final[frozenset[str]] = frozenset(
    {
        "local-hashed-term-projection@1.0.0",
        "patent.local_hashed_term_projection@1.0.0",
    }
)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_CID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9+=/_-]{7,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_TENANT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\-]{0,127}\Z")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IndexSnapshotError(ValueError):
    """Base error for patent index snapshot contract violations."""

    code: str = "index_snapshot_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class CorruptManifestError(IndexSnapshotError):
    """Raised when a manifest is missing required fields or fails integrity."""

    code = "corrupt_manifest"


class CrossTenantManifestError(IndexSnapshotError):
    """Raised when a manifest/record tenant does not match the open tenant."""

    code = "cross_tenant"


class UnknownSchemaVersionError(IndexSnapshotError):
    """Raised when a snapshot schema version is not supported."""

    code = "unknown_schema_version"


class UnknownModelVersionError(IndexSnapshotError):
    """Raised when a snapshot model pin is not in the known allow-list."""

    code = "unknown_model_version"


class MissingSourceJoinError(IndexSnapshotError):
    """Raised when a record lacks a source CID and version join."""

    code = "missing_source_join"


class OrphanRecordError(IndexSnapshotError):
    """Raised when a record cannot join to any declared source identity."""

    code = "orphan_record"


class SnapshotImmutabilityError(IndexSnapshotError):
    """Raised when an attempt is made to mutate an existing snapshot root."""

    code = "snapshot_immutability"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SnapshotKind(str, Enum):
    """How a snapshot root was produced."""

    FULL = "full"
    INCREMENTAL = "incremental"
    COMPACTION = "compaction"
    CHECKPOINT = "checkpoint"
    ROLLBACK = "rollback"


class RecordOp(str, Enum):
    """Logical operation of an append-only index log entry."""

    UPSERT = "upsert"
    TOMBSTONE = "tombstone"


class PartitionClass(str, Enum):
    """Top-level disclosure / tenancy partition for a snapshot root."""

    PUBLIC = "public"
    PRIVATE_TENANT = "private_tenant"


class IndexFamily(str, Enum):
    """Index modality materialised in a snapshot."""

    BM25 = "bm25"
    VECTOR = "vector"
    GRAPH = "graph"

    @classmethod
    def from_retrieval_family(cls, value: RetrievalFamily | str) -> "IndexFamily":
        text = value.value if isinstance(value, RetrievalFamily) else str(value)
        text = text.strip().lower()
        if text == "fusion":
            raise IndexSnapshotError(
                "fusion is a retrieval view, not a persistent index family"
            )
        return cls(text)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for contract round-trip equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest_of(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of *value*."""
    material = canonical_json(value).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def cid_from_digest(digest: str, *, prefix: str = "baguqeera") -> str:
    """Deterministic local content identifier derived from a SHA-256 digest.

    The identifier is not a full multihash codec encoding; it is a stable,
    content-bound token suitable for local manifests and join keys.
    """
    text = _sha256_hex(digest, "digest")
    return f"{prefix}{text[:48]}"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(f"{label} has unknown fields: {', '.join(extra)}")


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _tenant_id(value: Any, field: str = "tenant_id") -> str:
    text = _require_str(value, field, max_len=128)
    if not _TENANT_RE.match(text):
        raise ValueError(f"{field} is not a valid tenant id: {text!r}")
    return text


def _cid(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _CID_RE.match(text):
        raise ValueError(f"{field} is not a valid content identifier: {text!r}")
    return text


def _optional_cid(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    return _cid(text, field)


def _sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_sha256_hex(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    return _sha256_hex(text, field)


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    return _iso_utc(text, field)


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _positive_int(value: Any, field: str) -> int:
    number = _nonneg_int(value, field)
    if number < 1:
        raise ValueError(f"{field} must be >= 1")
    return number


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_disclosure(value: Any) -> DisclosureClass:
    if isinstance(value, DisclosureClass):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClass(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure class: {value!r}") from exc
    raise TypeError(
        f"disclosure must be DisclosureClass or str, got {type(value).__name__}"
    )


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _schema_pinned(value: Any, expected: str, label: str) -> str:
    text = _require_str(value, f"{label}.schema_version", max_len=64)
    if text != expected:
        raise UnknownSchemaVersionError(
            f"{label}.schema_version must be {expected}, got {text!r}"
        )
    return text


def assert_known_schema_version(schema_version: str) -> str:
    """Fail closed when *schema_version* is not the current pin."""
    return _schema_pinned(schema_version, INDEX_SNAPSHOT_SCHEMA_VERSION, "snapshot")


def assert_known_model_pin(model_pin: str) -> str:
    """Fail closed when *model_pin* is not in :data:`KNOWN_MODEL_PINS`."""
    text = _require_str(model_pin, "model_pin", max_len=256)
    if text not in KNOWN_MODEL_PINS:
        raise UnknownModelVersionError(
            f"unknown model pin {text!r}; known pins: {sorted(KNOWN_MODEL_PINS)}"
        )
    return text


# ---------------------------------------------------------------------------
# Identity records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContentAddress:
    """Content-bound identity (SHA-256 digest + derived CID)."""

    sha256: str
    cid: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", _sha256_hex(self.sha256, "sha256"))
        object.__setattr__(self, "cid", _cid(self.cid, "cid"))

    def to_dict(self) -> dict[str, str]:
        return {"cid": self.cid, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContentAddress":
        value = _mapping(value, "ContentAddress")
        _reject_unknown(value, frozenset({"sha256", "cid"}), "ContentAddress")
        return cls(sha256=value.get("sha256", ""), cid=value.get("cid", ""))

    @classmethod
    def from_payload(cls, payload: Any) -> "ContentAddress":
        digest = content_digest_of(payload)
        return cls(sha256=digest, cid=cid_from_digest(digest))


@dataclass(frozen=True, slots=True)
class CodeIdentity:
    """Pinned code version + content digest for the snapshot writer."""

    code_version: str
    code_digest: str
    interface: str = INDEX_SNAPSHOT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "code_version",
            _require_str(self.code_version, "code_version", max_len=64),
        )
        object.__setattr__(
            self, "code_digest", _sha256_hex(self.code_digest, "code_digest")
        )
        object.__setattr__(
            self, "interface", _require_str(self.interface, "interface", max_len=128)
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "code_digest": self.code_digest,
            "code_version": self.code_version,
            "interface": self.interface,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeIdentity":
        value = _mapping(value, "CodeIdentity")
        _reject_unknown(
            value,
            frozenset({"code_version", "code_digest", "interface"}),
            "CodeIdentity",
        )
        return cls(
            code_version=value.get("code_version", ""),
            code_digest=value.get("code_digest", ""),
            interface=value.get("interface", INDEX_SNAPSHOT_INTERFACE),
        )


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Pinned embedding / projection model identity for vector materializations."""

    model_pin: str
    provider: str
    model_id: str
    model_version: str
    dimension: int
    config_cid: str
    model_cid: str | None = None
    backend: str = "pinned"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "model_pin", assert_known_model_pin(self.model_pin)
        )
        object.__setattr__(
            self, "provider", _require_str(self.provider, "provider", max_len=128)
        )
        object.__setattr__(
            self, "model_id", _require_str(self.model_id, "model_id", max_len=256)
        )
        object.__setattr__(
            self,
            "model_version",
            _require_str(self.model_version, "model_version", max_len=128),
        )
        object.__setattr__(self, "dimension", _positive_int(self.dimension, "dimension"))
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(
            self, "model_cid", _optional_cid(self.model_cid, "model_cid")
        )
        object.__setattr__(
            self, "backend", _require_str(self.backend, "backend", max_len=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "config_cid": self.config_cid,
            "dimension": self.dimension,
            "model_cid": self.model_cid,
            "model_id": self.model_id,
            "model_pin": self.model_pin,
            "model_version": self.model_version,
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelIdentity":
        value = _mapping(value, "ModelIdentity")
        _reject_unknown(
            value,
            frozenset(
                {
                    "model_pin",
                    "provider",
                    "model_id",
                    "model_version",
                    "dimension",
                    "config_cid",
                    "model_cid",
                    "backend",
                }
            ),
            "ModelIdentity",
        )
        return cls(
            model_pin=value.get("model_pin", ""),
            provider=value.get("provider", ""),
            model_id=value.get("model_id", ""),
            model_version=value.get("model_version", ""),
            dimension=value.get("dimension", 0),
            config_cid=value.get("config_cid", ""),
            model_cid=value.get("model_cid"),
            backend=value.get("backend", "pinned"),
        )

    @classmethod
    def default_local_hashed(cls) -> "ModelIdentity":
        """Pinned default local hashed-term projection model."""
        return cls(
            model_pin="local-hashed-term-projection@1.0.0",
            provider="local",
            model_id="local-hashed-term-projection",
            model_version="1.0.0",
            dimension=384,
            config_cid=(
                "bafybeigembeddingconfigpinpatentv1hashedterm000000000000000001"
            ),
            model_cid=(
                "bafybeigembeddingmodelpinpatentv1hashedtermproj0000000000000001"
            ),
            backend="local_hashed_term_projection",
        )


@dataclass(frozen=True, slots=True)
class ConfigIdentity:
    """Pinned retrieval / index build configuration identity."""

    config_cid: str
    config_digest: str
    field_weights_config_cid: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(
            self, "config_digest", _sha256_hex(self.config_digest, "config_digest")
        )
        object.__setattr__(
            self,
            "field_weights_config_cid",
            _optional_cid(self.field_weights_config_cid, "field_weights_config_cid"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "config_digest": self.config_digest,
            "field_weights_config_cid": self.field_weights_config_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfigIdentity":
        value = _mapping(value, "ConfigIdentity")
        _reject_unknown(
            value,
            frozenset({"config_cid", "config_digest", "field_weights_config_cid"}),
            "ConfigIdentity",
        )
        return cls(
            config_cid=value.get("config_cid", ""),
            config_digest=value.get("config_digest", ""),
            field_weights_config_cid=value.get("field_weights_config_cid"),
        )


@dataclass(frozen=True, slots=True)
class CorpusIdentity:
    """Immutable corpus / source-manifest identity bound into a snapshot root."""

    corpus_cid: str
    corpus_digest: str
    source_manifest_cid: str
    corpus_version: str
    record_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_cid", _cid(self.corpus_cid, "corpus_cid"))
        object.__setattr__(
            self, "corpus_digest", _sha256_hex(self.corpus_digest, "corpus_digest")
        )
        object.__setattr__(
            self,
            "source_manifest_cid",
            _cid(self.source_manifest_cid, "source_manifest_cid"),
        )
        object.__setattr__(
            self,
            "corpus_version",
            _require_str(self.corpus_version, "corpus_version", max_len=128),
        )
        object.__setattr__(
            self, "record_count", _nonneg_int(self.record_count, "record_count")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_cid": self.corpus_cid,
            "corpus_digest": self.corpus_digest,
            "corpus_version": self.corpus_version,
            "record_count": self.record_count,
            "source_manifest_cid": self.source_manifest_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CorpusIdentity":
        value = _mapping(value, "CorpusIdentity")
        _reject_unknown(
            value,
            frozenset(
                {
                    "corpus_cid",
                    "corpus_digest",
                    "source_manifest_cid",
                    "corpus_version",
                    "record_count",
                }
            ),
            "CorpusIdentity",
        )
        return cls(
            corpus_cid=value.get("corpus_cid", ""),
            corpus_digest=value.get("corpus_digest", ""),
            source_manifest_cid=value.get("source_manifest_cid", ""),
            corpus_version=value.get("corpus_version", ""),
            record_count=value.get("record_count", 0),
        )


@dataclass(frozen=True, slots=True)
class SnapshotIdentityBundle:
    """Full identity pin set bound into every durable snapshot root."""

    schema_version: str
    corpus: CorpusIdentity
    code: CodeIdentity
    config: ConfigIdentity
    model: ModelIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            assert_known_schema_version(self.schema_version),
        )
        if not isinstance(self.corpus, CorpusIdentity):
            if isinstance(self.corpus, Mapping):
                object.__setattr__(
                    self, "corpus", CorpusIdentity.from_dict(self.corpus)
                )
            else:
                raise TypeError("corpus must be CorpusIdentity or mapping")
        if not isinstance(self.code, CodeIdentity):
            if isinstance(self.code, Mapping):
                object.__setattr__(self, "code", CodeIdentity.from_dict(self.code))
            else:
                raise TypeError("code must be CodeIdentity or mapping")
        if not isinstance(self.config, ConfigIdentity):
            if isinstance(self.config, Mapping):
                object.__setattr__(
                    self, "config", ConfigIdentity.from_dict(self.config)
                )
            else:
                raise TypeError("config must be ConfigIdentity or mapping")
        if self.model is not None and not isinstance(self.model, ModelIdentity):
            if isinstance(self.model, Mapping):
                object.__setattr__(self, "model", ModelIdentity.from_dict(self.model))
            else:
                raise TypeError("model must be ModelIdentity, mapping, or None")

    def require_model_for_family(self, family: IndexFamily | str) -> None:
        fam = _coerce_enum(IndexFamily, family, "family")
        if fam is IndexFamily.VECTOR and self.model is None:
            raise UnknownModelVersionError(
                "vector snapshots require a pinned ModelIdentity"
            )
        if self.model is not None:
            assert_known_model_pin(self.model.model_pin)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.to_dict(),
            "config": self.config.to_dict(),
            "corpus": self.corpus.to_dict(),
            "model": None if self.model is None else self.model.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotIdentityBundle":
        value = _mapping(value, "SnapshotIdentityBundle")
        _reject_unknown(
            value,
            frozenset({"schema_version", "corpus", "code", "config", "model"}),
            "SnapshotIdentityBundle",
        )
        model_raw = value.get("model")
        return cls(
            schema_version=value.get(
                "schema_version", INDEX_SNAPSHOT_SCHEMA_VERSION
            ),
            corpus=CorpusIdentity.from_dict(value.get("corpus") or {}),
            code=CodeIdentity.from_dict(value.get("code") or {}),
            config=ConfigIdentity.from_dict(value.get("config") or {}),
            model=(
                None
                if model_raw is None
                else ModelIdentity.from_dict(model_raw)
            ),
        )


# ---------------------------------------------------------------------------
# Source joins and index records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceJoin:
    """Mandatory join from an index record to a source artifact CID + version.

    Every durable index row must retain at least one of these joins so that
    retrieval, claim charts, and audit receipts can re-ground the record.
    """

    source_cid: str
    source_version: str
    artifact_id: str
    span: SourceSpan | None = None
    source_receipt_id: str | None = None
    authority_tier: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "source_version",
            _require_str(self.source_version, "source_version", max_len=128),
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if self.span is not None and not isinstance(self.span, SourceSpan):
            if isinstance(self.span, Mapping):
                object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
            else:
                raise TypeError("span must be SourceSpan, mapping, or None")
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_str(self.source_receipt_id, "source_receipt_id", max_len=256),
        )
        object.__setattr__(
            self,
            "authority_tier",
            _optional_str(self.authority_tier, "authority_tier", max_len=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_tier": self.authority_tier,
            "source_cid": self.source_cid,
            "source_receipt_id": self.source_receipt_id,
            "source_version": self.source_version,
            "span": None if self.span is None else self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceJoin":
        value = _mapping(value, "SourceJoin")
        _reject_unknown(
            value,
            frozenset(
                {
                    "source_cid",
                    "source_version",
                    "artifact_id",
                    "span",
                    "source_receipt_id",
                    "authority_tier",
                }
            ),
            "SourceJoin",
        )
        span_raw = value.get("span")
        span = None if span_raw is None else SourceSpan.from_dict(span_raw)
        return cls(
            source_cid=value.get("source_cid", ""),
            source_version=value.get("source_version", ""),
            artifact_id=value.get("artifact_id", ""),
            span=span,
            source_receipt_id=value.get("source_receipt_id"),
            authority_tier=value.get("authority_tier"),
        )


def _tuple_of_source_joins(
    value: Any, field: str, *, max_items: int = 64, require_nonempty: bool = True
) -> tuple[SourceJoin, ...]:
    if value is None:
        joins: tuple[SourceJoin, ...] = ()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) > max_items:
            raise ValueError(f"{field} exceeds max items {max_items}")
        out: list[SourceJoin] = []
        for i, item in enumerate(value):
            if isinstance(item, SourceJoin):
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(SourceJoin.from_dict(item))
            else:
                raise TypeError(f"{field}[{i}] must be SourceJoin or mapping")
        joins = tuple(out)
    else:
        raise TypeError(f"{field} must be a sequence of SourceJoin")
    if require_nonempty and not joins:
        raise MissingSourceJoinError(
            f"{field} must contain at least one source join "
            "(source_cid + source_version)"
        )
    return joins


@dataclass(frozen=True, slots=True)
class IndexSnapshotRecord:
    """One append-only index log entry bound to source joins and partition."""

    schema_version: str
    record_id: str
    document_id: str
    family: IndexFamily
    op: RecordOp
    source_joins: tuple[SourceJoin, ...]
    disclosure: DisclosureClass
    tenant_id: str
    content_digest: str
    payload_digest: str | None = None
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None
    tombstoned_utc: str | None = None
    prior_content_digest: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            assert_known_schema_version(self.schema_version),
        )
        object.__setattr__(
            self, "record_id", _identifier(self.record_id, "record_id")
        )
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "family", _coerce_enum(IndexFamily, self.family, "family")
        )
        object.__setattr__(self, "op", _coerce_enum(RecordOp, self.op, "op"))
        object.__setattr__(
            self,
            "source_joins",
            _tuple_of_source_joins(self.source_joins, "source_joins"),
        )
        object.__setattr__(self, "disclosure", _coerce_disclosure(self.disclosure))
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        object.__setattr__(
            self, "content_digest", _sha256_hex(self.content_digest, "content_digest")
        )
        object.__setattr__(
            self,
            "payload_digest",
            _optional_sha256_hex(self.payload_digest, "payload_digest"),
        )
        object.__setattr__(
            self,
            "effective_from_utc",
            _optional_iso_utc(self.effective_from_utc, "effective_from_utc"),
        )
        object.__setattr__(
            self,
            "effective_to_utc",
            _optional_iso_utc(self.effective_to_utc, "effective_to_utc"),
        )
        if (
            self.effective_from_utc
            and self.effective_to_utc
            and self.effective_to_utc < self.effective_from_utc
        ):
            raise ValueError("effective_to_utc must be >= effective_from_utc")
        object.__setattr__(
            self,
            "tombstoned_utc",
            _optional_iso_utc(self.tombstoned_utc, "tombstoned_utc"),
        )
        object.__setattr__(
            self,
            "prior_content_digest",
            _optional_sha256_hex(self.prior_content_digest, "prior_content_digest"),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )
        if self.op is RecordOp.TOMBSTONE:
            if self.tombstoned_utc is None:
                raise ValueError("tombstone records require tombstoned_utc")
            if self.prior_content_digest is None:
                raise ValueError(
                    "tombstone records require prior_content_digest "
                    "(immutable prior root retention)"
                )

    def is_tombstone(self) -> bool:
        return self.op is RecordOp.TOMBSTONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "disclosure": self.disclosure.value,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "family": self.family.value,
            "metadata": dict(self.metadata),
            "op": self.op.value,
            "payload_digest": self.payload_digest,
            "prior_content_digest": self.prior_content_digest,
            "record_id": self.record_id,
            "schema_version": self.schema_version,
            "source_joins": [j.to_dict() for j in self.source_joins],
            "tenant_id": self.tenant_id,
            "tombstoned_utc": self.tombstoned_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IndexSnapshotRecord":
        value = _mapping(value, "IndexSnapshotRecord")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "record_id",
                    "document_id",
                    "family",
                    "op",
                    "source_joins",
                    "disclosure",
                    "tenant_id",
                    "content_digest",
                    "payload_digest",
                    "effective_from_utc",
                    "effective_to_utc",
                    "tombstoned_utc",
                    "prior_content_digest",
                    "metadata",
                }
            ),
            "IndexSnapshotRecord",
        )
        return cls(
            schema_version=value.get(
                "schema_version", INDEX_SNAPSHOT_SCHEMA_VERSION
            ),
            record_id=value.get("record_id", ""),
            document_id=value.get("document_id", ""),
            family=value.get("family", IndexFamily.BM25.value),
            op=value.get("op", RecordOp.UPSERT.value),
            source_joins=value.get("source_joins") or (),
            disclosure=value.get("disclosure", DisclosureClass.UNKNOWN.value),
            tenant_id=value.get("tenant_id", ""),
            content_digest=value.get("content_digest", ""),
            payload_digest=value.get("payload_digest"),
            effective_from_utc=value.get("effective_from_utc"),
            effective_to_utc=value.get("effective_to_utc"),
            tombstoned_utc=value.get("tombstoned_utc"),
            prior_content_digest=value.get("prior_content_digest"),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Checkpoint / root pointers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckpointCursor:
    """Crash-safe resume cursor for incremental index builds.

    Retains the prior committed root so interrupted work never loses the
    last known-good snapshot identity.
    """

    schema_version: str
    checkpoint_id: str
    tenant_id: str
    shard_id: str
    offset: int
    prior_root_cid: str
    prior_root_digest: str
    last_record_id: str | None = None
    incomplete: bool = True
    updated_utc: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            assert_known_schema_version(self.schema_version),
        )
        object.__setattr__(
            self, "checkpoint_id", _identifier(self.checkpoint_id, "checkpoint_id")
        )
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        object.__setattr__(self, "shard_id", _identifier(self.shard_id, "shard_id"))
        object.__setattr__(self, "offset", _nonneg_int(self.offset, "offset"))
        object.__setattr__(
            self, "prior_root_cid", _cid(self.prior_root_cid, "prior_root_cid")
        )
        object.__setattr__(
            self,
            "prior_root_digest",
            _sha256_hex(self.prior_root_digest, "prior_root_digest"),
        )
        object.__setattr__(
            self,
            "last_record_id",
            _optional_str(self.last_record_id, "last_record_id", max_len=256),
        )
        if not isinstance(self.incomplete, bool):
            raise TypeError("incomplete must be bool")
        object.__setattr__(
            self, "updated_utc", _optional_iso_utc(self.updated_utc, "updated_utc")
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "incomplete": self.incomplete,
            "last_record_id": self.last_record_id,
            "metadata": dict(self.metadata),
            "offset": self.offset,
            "prior_root_cid": self.prior_root_cid,
            "prior_root_digest": self.prior_root_digest,
            "schema_version": self.schema_version,
            "shard_id": self.shard_id,
            "tenant_id": self.tenant_id,
            "updated_utc": self.updated_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CheckpointCursor":
        value = _mapping(value, "CheckpointCursor")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "checkpoint_id",
                    "tenant_id",
                    "shard_id",
                    "offset",
                    "prior_root_cid",
                    "prior_root_digest",
                    "last_record_id",
                    "incomplete",
                    "updated_utc",
                    "metadata",
                }
            ),
            "CheckpointCursor",
        )
        return cls(
            schema_version=value.get(
                "schema_version", INDEX_SNAPSHOT_SCHEMA_VERSION
            ),
            checkpoint_id=value.get("checkpoint_id", ""),
            tenant_id=value.get("tenant_id", ""),
            shard_id=value.get("shard_id", ""),
            offset=value.get("offset", 0),
            prior_root_cid=value.get("prior_root_cid", ""),
            prior_root_digest=value.get("prior_root_digest", ""),
            last_record_id=value.get("last_record_id"),
            incomplete=bool(value.get("incomplete", True)),
            updated_utc=value.get("updated_utc"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class RootPointer:
    """Immutable historical root retained across compaction / rollback."""

    root_cid: str
    root_digest: str
    kind: SnapshotKind
    retained_from_utc: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_cid", _cid(self.root_cid, "root_cid"))
        object.__setattr__(
            self, "root_digest", _sha256_hex(self.root_digest, "root_digest")
        )
        object.__setattr__(self, "kind", _coerce_enum(SnapshotKind, self.kind, "kind"))
        object.__setattr__(
            self,
            "retained_from_utc",
            _optional_iso_utc(self.retained_from_utc, "retained_from_utc"),
        )
        object.__setattr__(
            self, "note", _optional_str(self.note, "note", max_len=512)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "note": self.note,
            "retained_from_utc": self.retained_from_utc,
            "root_cid": self.root_cid,
            "root_digest": self.root_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RootPointer":
        value = _mapping(value, "RootPointer")
        _reject_unknown(
            value,
            frozenset(
                {"root_cid", "root_digest", "kind", "retained_from_utc", "note"}
            ),
            "RootPointer",
        )
        return cls(
            root_cid=value.get("root_cid", ""),
            root_digest=value.get("root_digest", ""),
            kind=value.get("kind", SnapshotKind.FULL.value),
            retained_from_utc=value.get("retained_from_utc"),
            note=value.get("note"),
        )


# ---------------------------------------------------------------------------
# Manifest + snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexSnapshotManifest:
    """Append-only corpus/index snapshot manifest.

    Binds identities, partition, family counts, and immutable prior roots
    (parent, compaction, rollback). Content identity is derived from the
    canonical payload so storage can address roots without wall-clock noise.
    """

    schema_version: str
    snapshot_id: str
    tenant_id: str
    partition: PartitionClass
    kind: SnapshotKind
    identities: SnapshotIdentityBundle
    families: tuple[IndexFamily, ...]
    record_count: int
    tombstone_count: int
    active_record_count: int
    created_utc: str
    parent_root: RootPointer | None = None
    compaction_root: RootPointer | None = None
    rollback_root: RootPointer | None = None
    prior_roots: tuple[RootPointer, ...] = ()
    checkpoint: CheckpointCursor | None = None
    allowed_disclosures: tuple[DisclosureClass, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            assert_known_schema_version(self.schema_version),
        )
        object.__setattr__(
            self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))
        object.__setattr__(
            self,
            "partition",
            _coerce_enum(PartitionClass, self.partition, "partition"),
        )
        object.__setattr__(
            self, "kind", _coerce_enum(SnapshotKind, self.kind, "kind")
        )
        if not isinstance(self.identities, SnapshotIdentityBundle):
            if isinstance(self.identities, Mapping):
                object.__setattr__(
                    self,
                    "identities",
                    SnapshotIdentityBundle.from_dict(self.identities),
                )
            else:
                raise TypeError("identities must be SnapshotIdentityBundle or mapping")
        if self.identities.schema_version != self.schema_version:
            raise CorruptManifestError(
                "manifest.schema_version must match identities.schema_version"
            )
        fams: list[IndexFamily] = []
        if not isinstance(self.families, Sequence) or isinstance(
            self.families, (str, bytes)
        ):
            raise TypeError("families must be a sequence of IndexFamily")
        for i, item in enumerate(self.families):
            fams.append(_coerce_enum(IndexFamily, item, f"families[{i}]"))
        object.__setattr__(self, "families", tuple(fams))
        for fam in self.families:
            self.identities.require_model_for_family(fam)
        object.__setattr__(
            self, "record_count", _nonneg_int(self.record_count, "record_count")
        )
        object.__setattr__(
            self,
            "tombstone_count",
            _nonneg_int(self.tombstone_count, "tombstone_count"),
        )
        object.__setattr__(
            self,
            "active_record_count",
            _nonneg_int(self.active_record_count, "active_record_count"),
        )
        if self.active_record_count + self.tombstone_count != self.record_count:
            raise CorruptManifestError(
                "active_record_count + tombstone_count must equal record_count"
            )
        object.__setattr__(
            self, "created_utc", _iso_utc(self.created_utc, "created_utc")
        )
        object.__setattr__(
            self, "parent_root", _coerce_root_pointer(self.parent_root, "parent_root")
        )
        object.__setattr__(
            self,
            "compaction_root",
            _coerce_root_pointer(self.compaction_root, "compaction_root"),
        )
        object.__setattr__(
            self,
            "rollback_root",
            _coerce_root_pointer(self.rollback_root, "rollback_root"),
        )
        prior: list[RootPointer] = []
        if self.prior_roots is None:
            prior_seq: Sequence[Any] = ()
        elif isinstance(self.prior_roots, Sequence) and not isinstance(
            self.prior_roots, (str, bytes)
        ):
            prior_seq = self.prior_roots
        else:
            raise TypeError("prior_roots must be a sequence of RootPointer")
        for i, item in enumerate(prior_seq):
            ptr = _coerce_root_pointer(item, f"prior_roots[{i}]")
            if ptr is None:
                raise ValueError(f"prior_roots[{i}] must not be null")
            prior.append(ptr)
        object.__setattr__(self, "prior_roots", tuple(prior))
        if self.checkpoint is not None and not isinstance(
            self.checkpoint, CheckpointCursor
        ):
            if isinstance(self.checkpoint, Mapping):
                object.__setattr__(
                    self, "checkpoint", CheckpointCursor.from_dict(self.checkpoint)
                )
            else:
                raise TypeError("checkpoint must be CheckpointCursor, mapping, or None")
        if self.checkpoint is not None and self.checkpoint.tenant_id != self.tenant_id:
            raise CrossTenantManifestError(
                "checkpoint.tenant_id does not match manifest.tenant_id"
            )
        disclosures: list[DisclosureClass] = []
        if self.allowed_disclosures is None:
            disc_seq: Sequence[Any] = ()
        elif isinstance(self.allowed_disclosures, Sequence) and not isinstance(
            self.allowed_disclosures, (str, bytes)
        ):
            disc_seq = self.allowed_disclosures
        else:
            raise TypeError("allowed_disclosures must be a sequence")
        for i, item in enumerate(disc_seq):
            disclosures.append(_coerce_disclosure(item))
        object.__setattr__(self, "allowed_disclosures", tuple(disclosures))
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=64)
        )
        if self.partition is PartitionClass.PUBLIC:
            for d in self.allowed_disclosures:
                if is_private_disclosure(d):
                    raise CorruptManifestError(
                        "public partition cannot allow private disclosure classes"
                    )

    def content_address(self) -> ContentAddress:
        return ContentAddress.from_payload(self.to_dict())

    @property
    def root_digest(self) -> str:
        return self.content_address().sha256

    @property
    def root_cid(self) -> str:
        return self.content_address().cid

    def retained_prior_roots(self) -> tuple[RootPointer, ...]:
        """All immutable prior roots retained by this manifest."""
        collected: list[RootPointer] = list(self.prior_roots)
        for ptr in (self.parent_root, self.compaction_root, self.rollback_root):
            if ptr is not None and all(
                p.root_digest != ptr.root_digest for p in collected
            ):
                collected.append(ptr)
        return tuple(collected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_record_count": self.active_record_count,
            "allowed_disclosures": [d.value for d in self.allowed_disclosures],
            "checkpoint": (
                None if self.checkpoint is None else self.checkpoint.to_dict()
            ),
            "compaction_root": (
                None
                if self.compaction_root is None
                else self.compaction_root.to_dict()
            ),
            "created_utc": self.created_utc,
            "families": [f.value for f in self.families],
            "identities": self.identities.to_dict(),
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "parent_root": (
                None if self.parent_root is None else self.parent_root.to_dict()
            ),
            "partition": self.partition.value,
            "prior_roots": [p.to_dict() for p in self.prior_roots],
            "record_count": self.record_count,
            "rollback_root": (
                None if self.rollback_root is None else self.rollback_root.to_dict()
            ),
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "tenant_id": self.tenant_id,
            "tombstone_count": self.tombstone_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IndexSnapshotManifest":
        value = _mapping(value, "IndexSnapshotManifest")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "snapshot_id",
                    "tenant_id",
                    "partition",
                    "kind",
                    "identities",
                    "families",
                    "record_count",
                    "tombstone_count",
                    "active_record_count",
                    "created_utc",
                    "parent_root",
                    "compaction_root",
                    "rollback_root",
                    "prior_roots",
                    "checkpoint",
                    "allowed_disclosures",
                    "metadata",
                }
            ),
            "IndexSnapshotManifest",
        )
        return cls(
            schema_version=value.get(
                "schema_version", INDEX_SNAPSHOT_SCHEMA_VERSION
            ),
            snapshot_id=value.get("snapshot_id", ""),
            tenant_id=value.get("tenant_id", ""),
            partition=value.get("partition", PartitionClass.PUBLIC.value),
            kind=value.get("kind", SnapshotKind.FULL.value),
            identities=SnapshotIdentityBundle.from_dict(
                value.get("identities") or {}
            ),
            families=tuple(value.get("families") or ()),
            record_count=value.get("record_count", 0),
            tombstone_count=value.get("tombstone_count", 0),
            active_record_count=value.get("active_record_count", 0),
            created_utc=value.get("created_utc", ""),
            parent_root=value.get("parent_root"),
            compaction_root=value.get("compaction_root"),
            rollback_root=value.get("rollback_root"),
            prior_roots=tuple(value.get("prior_roots") or ()),
            checkpoint=value.get("checkpoint"),
            allowed_disclosures=tuple(value.get("allowed_disclosures") or ()),
            metadata=value.get("metadata") or {},
        )


def _coerce_root_pointer(
    value: Any, field: str
) -> RootPointer | None:
    if value is None:
        return None
    if isinstance(value, RootPointer):
        return value
    if isinstance(value, Mapping):
        return RootPointer.from_dict(value)
    raise TypeError(f"{field} must be RootPointer, mapping, or None")


@dataclass(frozen=True, slots=True)
class PatentIndexSnapshot:
    """Complete content-addressed index snapshot (manifest + records).

    Serialization is deterministic. Content identity covers both the
    manifest payload and the ordered record log so storage can fail closed
    on bit-level drift.
    """

    manifest: IndexSnapshotManifest
    records: tuple[IndexSnapshotRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, IndexSnapshotManifest):
            if isinstance(self.manifest, Mapping):
                object.__setattr__(
                    self, "manifest", IndexSnapshotManifest.from_dict(self.manifest)
                )
            else:
                raise TypeError("manifest must be IndexSnapshotManifest or mapping")
        if not isinstance(self.records, Sequence) or isinstance(
            self.records, (str, bytes)
        ):
            raise TypeError("records must be a sequence of IndexSnapshotRecord")
        normalized: list[IndexSnapshotRecord] = []
        for i, item in enumerate(self.records):
            if isinstance(item, IndexSnapshotRecord):
                rec = item
            elif isinstance(item, Mapping):
                rec = IndexSnapshotRecord.from_dict(item)
            else:
                raise TypeError(
                    f"records[{i}] must be IndexSnapshotRecord or mapping"
                )
            if rec.tenant_id != self.manifest.tenant_id:
                raise CrossTenantManifestError(
                    f"record {rec.record_id!r} tenant {rec.tenant_id!r} does not "
                    f"match snapshot tenant {self.manifest.tenant_id!r}"
                )
            if rec.schema_version != self.manifest.schema_version:
                raise UnknownSchemaVersionError(
                    f"record {rec.record_id!r} schema_version mismatch"
                )
            if rec.family not in self.manifest.families:
                raise CorruptManifestError(
                    f"record {rec.record_id!r} family {rec.family.value!r} "
                    "not declared in manifest.families"
                )
            if self.manifest.allowed_disclosures and rec.disclosure not in (
                self.manifest.allowed_disclosures
            ):
                raise CorruptManifestError(
                    f"record {rec.record_id!r} disclosure "
                    f"{rec.disclosure.value!r} not admitted by manifest"
                )
            if self.manifest.partition is PartitionClass.PUBLIC and is_private_disclosure(
                rec.disclosure
            ):
                raise CorruptManifestError(
                    f"public snapshot cannot contain private record {rec.record_id!r}"
                )
            normalized.append(rec)
        # Stable ordering for deterministic content addressing.
        normalized.sort(key=lambda r: (r.record_id, r.content_digest))
        object.__setattr__(self, "records", tuple(normalized))
        if len(self.records) != self.manifest.record_count:
            raise CorruptManifestError(
                f"record log length {len(self.records)} != "
                f"manifest.record_count {self.manifest.record_count}"
            )
        tombstones = sum(1 for r in self.records if r.is_tombstone())
        if tombstones != self.manifest.tombstone_count:
            raise CorruptManifestError(
                f"tombstone count {tombstones} != "
                f"manifest.tombstone_count {self.manifest.tombstone_count}"
            )
        active = len(self.records) - tombstones
        if active != self.manifest.active_record_count:
            raise CorruptManifestError(
                f"active count {active} != "
                f"manifest.active_record_count {self.manifest.active_record_count}"
            )
        # Vector family requires model pin (also enforced on identities).
        for fam in self.manifest.families:
            self.manifest.identities.require_model_for_family(fam)

    def content_address(self) -> ContentAddress:
        return ContentAddress.from_payload(self.to_dict())

    @property
    def root_digest(self) -> str:
        return self.content_address().sha256

    @property
    def root_cid(self) -> str:
        return self.content_address().cid

    def active_records(self) -> tuple[IndexSnapshotRecord, ...]:
        return tuple(r for r in self.records if not r.is_tombstone())

    def tombstone_records(self) -> tuple[IndexSnapshotRecord, ...]:
        return tuple(r for r in self.records if r.is_tombstone())

    def records_by_id(self) -> Mapping[str, IndexSnapshotRecord]:
        return MappingProxyType({r.record_id: r for r in self.records})

    def verify_source_joins(self) -> None:
        """Fail closed if any record lacks a source CID + version join."""
        for rec in self.records:
            if not rec.source_joins:
                raise MissingSourceJoinError(
                    f"record {rec.record_id!r} has no source joins"
                )
            for join in rec.source_joins:
                if not join.source_cid or not join.source_version:
                    raise MissingSourceJoinError(
                        f"record {rec.record_id!r} join missing cid/version"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "records": [r.to_dict() for r in self.records],
            "schema_version": self.manifest.schema_version,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_canonical_bytes(self) -> bytes:
        return self.to_canonical_json().encode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatentIndexSnapshot":
        value = _mapping(value, "PatentIndexSnapshot")
        _reject_unknown(
            value,
            frozenset({"manifest", "records", "schema_version"}),
            "PatentIndexSnapshot",
        )
        # Fail closed on unknown top-level schema before constructing nested.
        if "schema_version" in value:
            assert_known_schema_version(value["schema_version"])
        manifest_raw = value.get("manifest")
        if not isinstance(manifest_raw, Mapping):
            raise CorruptManifestError("snapshot.manifest must be a mapping")
        records_raw = value.get("records") or ()
        if not isinstance(records_raw, Sequence) or isinstance(
            records_raw, (str, bytes)
        ):
            raise CorruptManifestError("snapshot.records must be a sequence")
        return cls(
            manifest=IndexSnapshotManifest.from_dict(manifest_raw),
            records=tuple(records_raw),
        )

    @classmethod
    def from_canonical_json(cls, text: str | bytes) -> "PatentIndexSnapshot":
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptManifestError(f"invalid snapshot JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise CorruptManifestError("snapshot JSON must decode to a mapping")
        return cls.from_dict(payload)


# ---------------------------------------------------------------------------
# Build helpers (pure; no I/O)
# ---------------------------------------------------------------------------


def default_code_identity(*, code_digest: str | None = None) -> CodeIdentity:
    """Pinned code identity for this contract revision."""
    digest = code_digest or content_digest_of(
        {
            "code_version": INDEX_SNAPSHOT_CODE_VERSION,
            "interface": INDEX_SNAPSHOT_INTERFACE,
            "schema_version": INDEX_SNAPSHOT_SCHEMA_VERSION,
        }
    )
    return CodeIdentity(
        code_version=INDEX_SNAPSHOT_CODE_VERSION,
        code_digest=digest,
        interface=INDEX_SNAPSHOT_INTERFACE,
    )


def build_tombstone_record(
    prior: IndexSnapshotRecord,
    *,
    tombstoned_utc: str,
    content_digest: str | None = None,
) -> IndexSnapshotRecord:
    """Create a tombstone that retains the prior content digest and source joins."""
    if prior.is_tombstone():
        raise IndexSnapshotError("cannot tombstone an existing tombstone record")
    digest = content_digest or content_digest_of(
        {
            "op": RecordOp.TOMBSTONE.value,
            "prior_content_digest": prior.content_digest,
            "record_id": prior.record_id,
            "tombstoned_utc": tombstoned_utc,
        }
    )
    return IndexSnapshotRecord(
        schema_version=prior.schema_version,
        record_id=prior.record_id,
        document_id=prior.document_id,
        family=prior.family,
        op=RecordOp.TOMBSTONE,
        source_joins=prior.source_joins,
        disclosure=prior.disclosure,
        tenant_id=prior.tenant_id,
        content_digest=digest,
        payload_digest=prior.payload_digest,
        effective_from_utc=prior.effective_from_utc,
        effective_to_utc=prior.effective_to_utc,
        tombstoned_utc=tombstoned_utc,
        prior_content_digest=prior.content_digest,
        metadata=dict(prior.metadata),
    )


def open_snapshot_payload(
    payload: Mapping[str, Any],
    *,
    expected_tenant_id: str | None = None,
) -> PatentIndexSnapshot:
    """Open and validate a snapshot mapping; fail closed on unknown versions.

    *expected_tenant_id*, when provided, enforces tenant isolation.
    """
    if not isinstance(payload, Mapping):
        raise CorruptManifestError("payload must be a mapping")
    schema = payload.get("schema_version")
    if schema is None and isinstance(payload.get("manifest"), Mapping):
        schema = payload["manifest"].get("schema_version")
    if schema is None:
        raise CorruptManifestError("snapshot missing schema_version")
    assert_known_schema_version(str(schema))
    snapshot = PatentIndexSnapshot.from_dict(payload)
    # Model pin check (vector families already require model).
    model = snapshot.manifest.identities.model
    if model is not None:
        assert_known_model_pin(model.model_pin)
    if expected_tenant_id is not None:
        expected = _tenant_id(expected_tenant_id, "expected_tenant_id")
        if snapshot.manifest.tenant_id != expected:
            raise CrossTenantManifestError(
                f"snapshot tenant {snapshot.manifest.tenant_id!r} does not "
                f"match expected {expected!r}"
            )
    snapshot.verify_source_joins()
    return snapshot


__all__ = [
    "INDEX_SNAPSHOT_SCHEMA_VERSION",
    "INDEX_SNAPSHOT_INTERFACE",
    "INDEX_STORE_INTERFACE",
    "INDEX_SNAPSHOT_CODE_VERSION",
    "KNOWN_MODEL_PINS",
    "IndexSnapshotError",
    "CorruptManifestError",
    "CrossTenantManifestError",
    "UnknownSchemaVersionError",
    "UnknownModelVersionError",
    "MissingSourceJoinError",
    "OrphanRecordError",
    "SnapshotImmutabilityError",
    "SnapshotKind",
    "RecordOp",
    "PartitionClass",
    "IndexFamily",
    "canonical_json",
    "content_digest_of",
    "cid_from_digest",
    "assert_known_schema_version",
    "assert_known_model_pin",
    "ContentAddress",
    "CodeIdentity",
    "ModelIdentity",
    "ConfigIdentity",
    "CorpusIdentity",
    "SnapshotIdentityBundle",
    "SourceJoin",
    "IndexSnapshotRecord",
    "CheckpointCursor",
    "RootPointer",
    "IndexSnapshotManifest",
    "PatentIndexSnapshot",
    "default_code_identity",
    "build_tombstone_record",
    "open_snapshot_payload",
    "is_public_disclosure",
    "is_private_disclosure",
]
