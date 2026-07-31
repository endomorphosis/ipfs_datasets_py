"""Immutable proof-corpus manifests (ProofCorpusManifest@1 / LIG-030).

Corpus snapshots are exact-root, content-addressed, and append-only.  A
manifest binds domain/namespace/schema, parent lineage, ordered body entries,
source set, compiler/solver/circuit/VK registries, separately-addressed index
manifests, revocation root, coverage/licensing/privacy/tenant policy, producer
identity, and promotion receipt.

Bodies and indices are never mixed: body entries live under ``entries`` with
``kind=body``; index artifacts are referenced only via ``index_manifests``.
Mutable ``latest`` aliases, path traversal, duplicate/missing/unbound bodies,
oversize content, hash/CID drift, parent cycles, rollback/downgrade, and
unapproved registry roots fail closed.

This leaf does not rewrite :mod:`.schemas`, :mod:`.store`, :mod:`.query`,
:mod:`.index`, :mod:`.attest`, :mod:`.model`, or :mod:`.policy`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.identity import cid_v1_from_digest

PROOF_CORPUS_MANIFEST_INTERFACE: Final = "ProofCorpusManifest@1"
PROOF_CORPUS_MANIFEST_SCHEMA_VERSION: Final = "proof-corpus-manifest/v1"
MANIFEST_ENTRY_SCHEMA_VERSION: Final = "proof-corpus-manifest-entry/v1"
REGISTRY_BINDING_SCHEMA_VERSION: Final = "proof-corpus-registry-binding/v1"
INDEX_MANIFEST_REF_SCHEMA_VERSION: Final = "proof-corpus-index-manifest-ref/v1"
POLICY_BINDING_SCHEMA_VERSION: Final = "proof-corpus-policy-binding/v1"
PROMOTION_RECEIPT_SCHEMA_VERSION: Final = "proof-corpus-promotion-receipt/v1"
SOURCE_BINDING_SCHEMA_VERSION: Final = "proof-corpus-source-binding/v1"

DEFAULT_MAX_ENTRY_BYTES: Final = 1_048_576
DEFAULT_MAX_MANIFEST_ENTRIES: Final = 65_536

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BARE_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_NAMESPACE_RE: Final = re.compile(
    r"^[a-z][a-z0-9]*(?:[-./][a-z0-9]+)*$"
)
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")
_MUTABLE_LATEST_RE: Final = re.compile(
    r"(^|[./_-])latest($|[./_-])", re.IGNORECASE
)

_MANIFEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "approved_registry_roots",
        "circuit_registry",
        "compiler_registry",
        "content_cid",
        "content_digest",
        "domain",
        "entries",
        "generation",
        "index_manifests",
        "interface",
        "max_entry_bytes",
        "namespace",
        "parent_cid",
        "policy",
        "producer_id",
        "promotion_receipt",
        "revocation_root_cid",
        "root_cid",
        "schema_version",
        "solver_registry",
        "sources",
        "vk_registry",
    }
)


class ProofCorpusManifestError(ValueError):
    """Raised when a proof-corpus manifest is malformed."""


class ProofCorpusManifestIntegrityError(ProofCorpusManifestError):
    """Raised when a manifest fails integrity, lineage, or body binding checks."""


class EntryKind(str, Enum):
    """Closed entry kind vocabulary; bodies and indices stay separate."""

    BODY = "body"
    # Indices never appear as body entries; they are IndexManifestRef only.
    # BODY is the only kind permitted on ManifestEntry.


class RegistryKind(str, Enum):
    """Closed registry vocabulary bound into a corpus manifest."""

    COMPILER = "compiler"
    SOLVER = "solver"
    CIRCUIT = "circuit"
    VK = "vk"


class IndexManifestKind(str, Enum):
    """Secondary index kinds referenced by a corpus manifest."""

    FAMILY = "family"
    SOURCE = "source"
    PROFILE = "profile"
    OBLIGATION = "obligation"
    COMPOSITE = "composite"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise ProofCorpusManifestError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the proof corpus manifest"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofCorpusManifestError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofCorpusManifestError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if _BARE_DIGEST_RE.fullmatch(digest):
        digest = f"sha256:{digest}"
    if not _DIGEST_RE.fullmatch(digest):
        raise ProofCorpusManifestError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    return digest


def _optional_digest(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_digest(value, field_name)


def _require_cid(value: Any, field_name: str) -> str:
    cid = _require_text(value, field_name)
    if not _CID_RE.fullmatch(cid):
        raise ProofCorpusManifestError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    return cid


def _optional_cid(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_cid(value, field_name)


def _require_identifier(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ProofCorpusManifestError(
            f"{field_name} must be a lowercase identifier "
            "(letters, digits, underscore)"
        )
    return text


def _require_profile(value: Any, field_name: str) -> str:
    profile = _require_text(value, field_name)
    if not _PROFILE_RE.fullmatch(profile):
        raise ProofCorpusManifestError(
            f"{field_name} must be a lowercase hyphenated identifier"
        )
    return profile


def _require_namespace(value: Any, field_name: str = "namespace") -> str:
    text = _require_text(value, field_name)
    if not _NAMESPACE_RE.fullmatch(text):
        raise ProofCorpusManifestError(
            f"{field_name} must be a lowercase dotted/hyphenated namespace"
        )
    _reject_mutable_latest(text, field_name)
    return text


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProofCorpusManifestError(f"{field_name} must be an int")
    if value < 0:
        raise ProofCorpusManifestError(
            f"{field_name} must be a non-negative int"
        )
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    number = _require_non_negative_int(value, field_name)
    if number <= 0:
        raise ProofCorpusManifestError(f"{field_name} must be a positive int")
    return number


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProofCorpusManifestError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProofCorpusManifestError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _reject_mutable_latest(value: str, field_name: str) -> None:
    """Reject mutable ``latest`` aliases anywhere in a path or identifier."""

    if value.lower() == "latest" or _MUTABLE_LATEST_RE.search(value):
        raise ProofCorpusManifestIntegrityError(
            f"{field_name} must not use mutable 'latest' alias: {value!r}"
        )


def require_safe_relative_path(value: Any, field_name: str = "path") -> str:
    """Require a root-relative POSIX path with no traversal or latest aliases."""

    path = _require_text(value, field_name)
    if "\\" in path or "\x00" in path:
        raise ProofCorpusManifestIntegrityError(
            f"{field_name} must be a root-relative POSIX path without "
            f"backslashes or null bytes: {path!r}"
        )
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProofCorpusManifestIntegrityError(
            f"{field_name} must be root-relative and contain no '.'/'..' "
            f"segments (path traversal rejected): {path!r}"
        )
    normalized = pure.as_posix()
    if normalized != path:
        raise ProofCorpusManifestIntegrityError(
            f"{field_name} must be normalized POSIX text: {path!r}"
        )
    _reject_mutable_latest(path, field_name)
    return path


def digest_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for raw body bytes."""

    if not isinstance(data, (bytes, bytearray)):
        raise ProofCorpusManifestError("body content must be bytes")
    return _sha256_digest(bytes(data))


def cid_for_digest(digest: str) -> str:
    """Return CIDv1 base32 for a ``sha256:<hex>`` digest."""

    normalized = _require_digest(digest, "digest")
    return cid_v1_from_digest(bytes.fromhex(normalized.removeprefix("sha256:")))


# ---------------------------------------------------------------------------
# Nested bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One ordered body entry in a proof-corpus manifest.

    Only body kind is permitted.  Indices are bound separately via
    :class:`IndexManifestRef` so bodies and indices never share the same list.
    """

    entry_id: str
    path: str
    content_cid: str
    content_digest: str
    size_bytes: int
    ordinal: int = 0
    source_id: str = ""
    envelope_cid: str = ""
    media_type: str = ""
    kind: EntryKind | str = EntryKind.BODY
    schema_version: str = MANIFEST_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_id", _require_identifier(self.entry_id, "entry_id")
        )
        _reject_mutable_latest(self.entry_id, "entry_id")
        object.__setattr__(
            self, "path", require_safe_relative_path(self.path, "path")
        )
        object.__setattr__(
            self, "content_cid", _require_cid(self.content_cid, "content_cid")
        )
        object.__setattr__(
            self,
            "content_digest",
            _require_digest(self.content_digest, "content_digest"),
        )
        expected_cid = cid_for_digest(self.content_digest)
        if self.content_cid != expected_cid:
            raise ProofCorpusManifestIntegrityError(
                f"entry {self.entry_id!r} content_cid does not match "
                "content_digest"
            )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self, "ordinal", _require_non_negative_int(self.ordinal, "ordinal")
        )
        object.__setattr__(
            self, "source_id", _optional_text(self.source_id, "source_id")
        )
        if self.source_id:
            _reject_mutable_latest(self.source_id, "source_id")
        object.__setattr__(
            self,
            "envelope_cid",
            _optional_cid(self.envelope_cid, "envelope_cid"),
        )
        object.__setattr__(
            self, "media_type", _optional_text(self.media_type, "media_type")
        )
        kind = _parse_enum(self.kind, EntryKind, "kind")
        if kind is not EntryKind.BODY:
            raise ProofCorpusManifestIntegrityError(
                "manifest entries must be kind=body; bind indices via "
                "index_manifests (bodies and indices are separate)"
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != MANIFEST_ENTRY_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported manifest entry schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "entry_id": self.entry_id,
            "envelope_cid": self.envelope_cid,
            "kind": self.kind.value if isinstance(self.kind, EntryKind) else self.kind,
            "media_type": self.media_type,
            "ordinal": self.ordinal,
            "path": self.path,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ManifestEntry":
        if isinstance(value, ManifestEntry):
            return value
        payload = dict(_as_mapping(value, "manifest entry"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "content_cid",
                    "content_digest",
                    "entry_id",
                    "envelope_cid",
                    "kind",
                    "media_type",
                    "ordinal",
                    "path",
                    "schema_version",
                    "size_bytes",
                    "source_id",
                }
            ),
            "manifest entry",
        )
        return cls(
            entry_id=payload["entry_id"],
            path=payload["path"],
            content_cid=payload["content_cid"],
            content_digest=payload["content_digest"],
            size_bytes=int(payload.get("size_bytes", 0) or 0),
            ordinal=int(payload.get("ordinal", 0) or 0),
            source_id=payload.get("source_id", ""),
            envelope_cid=payload.get("envelope_cid", ""),
            media_type=payload.get("media_type", ""),
            kind=payload.get("kind", EntryKind.BODY),
            schema_version=payload.get(
                "schema_version", MANIFEST_ENTRY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Declared source snapshot bound into a corpus manifest."""

    source_id: str
    snapshot_cid: str
    snapshot_digest: str = ""
    license_id: str = ""
    schema_version: str = SOURCE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _require_text(self.source_id, "source_id")
        )
        _reject_mutable_latest(self.source_id, "source_id")
        object.__setattr__(
            self,
            "snapshot_cid",
            _require_cid(self.snapshot_cid, "snapshot_cid"),
        )
        object.__setattr__(
            self,
            "snapshot_digest",
            _optional_digest(self.snapshot_digest, "snapshot_digest"),
        )
        object.__setattr__(
            self, "license_id", _optional_text(self.license_id, "license_id")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SOURCE_BINDING_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported source binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "schema_version": self.schema_version,
            "snapshot_cid": self.snapshot_cid,
            "snapshot_digest": self.snapshot_digest,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SourceBinding":
        if isinstance(value, SourceBinding):
            return value
        payload = dict(_as_mapping(value, "source binding"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "license_id",
                    "schema_version",
                    "snapshot_cid",
                    "snapshot_digest",
                    "source_id",
                }
            ),
            "source binding",
        )
        return cls(
            source_id=payload["source_id"],
            snapshot_cid=payload["snapshot_cid"],
            snapshot_digest=payload.get("snapshot_digest", ""),
            license_id=payload.get("license_id", ""),
            schema_version=payload.get(
                "schema_version", SOURCE_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class RegistryBinding:
    """Compiler / solver / circuit / VK registry root binding."""

    registry_kind: RegistryKind | str
    registry_id: str
    root_cid: str
    version: int = 1
    digest: str = ""
    schema_version: str = REGISTRY_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = _parse_enum(self.registry_kind, RegistryKind, "registry_kind")
        object.__setattr__(self, "registry_kind", kind)
        object.__setattr__(
            self,
            "registry_id",
            _require_text(self.registry_id, "registry_id"),
        )
        _reject_mutable_latest(self.registry_id, "registry_id")
        object.__setattr__(
            self, "root_cid", _require_cid(self.root_cid, "root_cid")
        )
        object.__setattr__(
            self, "version", _require_positive_int(self.version, "version")
        )
        object.__setattr__(
            self, "digest", _optional_digest(self.digest, "digest")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != REGISTRY_BINDING_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported registry binding schema: {self.schema_version!r}"
            )

    @property
    def registry_ref(self) -> str:
        return f"{self.registry_id}@v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        kind = (
            self.registry_kind.value
            if isinstance(self.registry_kind, RegistryKind)
            else self.registry_kind
        )
        return {
            "digest": self.digest,
            "registry_id": self.registry_id,
            "registry_kind": kind,
            "registry_ref": self.registry_ref,
            "root_cid": self.root_cid,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RegistryBinding":
        if isinstance(value, RegistryBinding):
            return value
        payload = dict(_as_mapping(value, "registry binding"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "digest",
                    "registry_id",
                    "registry_kind",
                    "registry_ref",
                    "root_cid",
                    "schema_version",
                    "version",
                }
            ),
            "registry binding",
        )
        return cls(
            registry_kind=payload["registry_kind"],
            registry_id=payload["registry_id"],
            root_cid=payload["root_cid"],
            version=int(payload.get("version", 1) or 1),
            digest=payload.get("digest", ""),
            schema_version=payload.get(
                "schema_version", REGISTRY_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class IndexManifestRef:
    """Separately-addressed secondary index manifest reference.

    Index artifacts are never body entries; they bind via this structure so
    bodies and indices remain distinct surfaces.
    """

    index_id: str
    index_cid: str
    index_digest: str
    index_kind: IndexManifestKind | str = IndexManifestKind.COMPOSITE
    schema_version: str = INDEX_MANIFEST_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "index_id", _require_identifier(self.index_id, "index_id")
        )
        _reject_mutable_latest(self.index_id, "index_id")
        object.__setattr__(
            self, "index_cid", _require_cid(self.index_cid, "index_cid")
        )
        object.__setattr__(
            self,
            "index_digest",
            _require_digest(self.index_digest, "index_digest"),
        )
        expected_cid = cid_for_digest(self.index_digest)
        if self.index_cid != expected_cid:
            raise ProofCorpusManifestIntegrityError(
                f"index {self.index_id!r} index_cid does not match "
                "index_digest"
            )
        object.__setattr__(
            self,
            "index_kind",
            _parse_enum(self.index_kind, IndexManifestKind, "index_kind"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != INDEX_MANIFEST_REF_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported index manifest ref schema: "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        kind = (
            self.index_kind.value
            if isinstance(self.index_kind, IndexManifestKind)
            else self.index_kind
        )
        return {
            "index_cid": self.index_cid,
            "index_digest": self.index_digest,
            "index_id": self.index_id,
            "index_kind": kind,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "IndexManifestRef":
        if isinstance(value, IndexManifestRef):
            return value
        payload = dict(_as_mapping(value, "index manifest ref"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "index_cid",
                    "index_digest",
                    "index_id",
                    "index_kind",
                    "schema_version",
                }
            ),
            "index manifest ref",
        )
        return cls(
            index_id=payload["index_id"],
            index_cid=payload["index_cid"],
            index_digest=payload["index_digest"],
            index_kind=payload.get("index_kind", IndexManifestKind.COMPOSITE),
            schema_version=payload.get(
                "schema_version", INDEX_MANIFEST_REF_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PolicyBinding:
    """Coverage / licensing / privacy / tenant policy binding."""

    coverage_policy_id: str = ""
    licensing_policy_id: str = ""
    privacy_policy_id: str = ""
    tenant_policy_id: str = ""
    policy_root_cid: str = ""
    schema_version: str = POLICY_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "coverage_policy_id",
            "licensing_policy_id",
            "privacy_policy_id",
            "tenant_policy_id",
        ):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name)
            )
            value = getattr(self, name)
            if value:
                _reject_mutable_latest(value, name)
        object.__setattr__(
            self,
            "policy_root_cid",
            _optional_cid(self.policy_root_cid, "policy_root_cid"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != POLICY_BINDING_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported policy binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_policy_id": self.coverage_policy_id,
            "licensing_policy_id": self.licensing_policy_id,
            "policy_root_cid": self.policy_root_cid,
            "privacy_policy_id": self.privacy_policy_id,
            "schema_version": self.schema_version,
            "tenant_policy_id": self.tenant_policy_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PolicyBinding":
        if isinstance(value, PolicyBinding):
            return value
        if value in (None, ""):
            return cls()
        payload = dict(_as_mapping(value, "policy binding"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "coverage_policy_id",
                    "licensing_policy_id",
                    "policy_root_cid",
                    "privacy_policy_id",
                    "schema_version",
                    "tenant_policy_id",
                }
            ),
            "policy binding",
        )
        return cls(
            coverage_policy_id=payload.get("coverage_policy_id", ""),
            licensing_policy_id=payload.get("licensing_policy_id", ""),
            privacy_policy_id=payload.get("privacy_policy_id", ""),
            tenant_policy_id=payload.get("tenant_policy_id", ""),
            policy_root_cid=payload.get("policy_root_cid", ""),
            schema_version=payload.get(
                "schema_version", POLICY_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    """Producer promotion receipt bound into a corpus manifest."""

    receipt_id: str
    producer_id: str
    promoted_at: str
    source_manifest_cid: str = ""
    target_namespace: str = ""
    reviewer_id: str = ""
    approval_digest: str = ""
    schema_version: str = PROMOTION_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _require_text(self.receipt_id, "receipt_id")
        )
        _reject_mutable_latest(self.receipt_id, "receipt_id")
        object.__setattr__(
            self, "producer_id", _require_text(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self, "promoted_at", _require_text(self.promoted_at, "promoted_at")
        )
        object.__setattr__(
            self,
            "source_manifest_cid",
            _optional_cid(self.source_manifest_cid, "source_manifest_cid"),
        )
        object.__setattr__(
            self,
            "target_namespace",
            _optional_text(self.target_namespace, "target_namespace"),
        )
        if self.target_namespace:
            _reject_mutable_latest(self.target_namespace, "target_namespace")
        object.__setattr__(
            self, "reviewer_id", _optional_text(self.reviewer_id, "reviewer_id")
        )
        object.__setattr__(
            self,
            "approval_digest",
            _optional_digest(self.approval_digest, "approval_digest"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROMOTION_RECEIPT_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported promotion receipt schema: "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_digest": self.approval_digest,
            "producer_id": self.producer_id,
            "promoted_at": self.promoted_at,
            "receipt_id": self.receipt_id,
            "reviewer_id": self.reviewer_id,
            "schema_version": self.schema_version,
            "source_manifest_cid": self.source_manifest_cid,
            "target_namespace": self.target_namespace,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PromotionReceipt":
        if isinstance(value, PromotionReceipt):
            return value
        if value in (None, ""):
            raise ProofCorpusManifestError(
                "promotion_receipt is required when provided as a field"
            )
        payload = dict(_as_mapping(value, "promotion receipt"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "approval_digest",
                    "producer_id",
                    "promoted_at",
                    "receipt_id",
                    "reviewer_id",
                    "schema_version",
                    "source_manifest_cid",
                    "target_namespace",
                }
            ),
            "promotion receipt",
        )
        return cls(
            receipt_id=payload["receipt_id"],
            producer_id=payload["producer_id"],
            promoted_at=payload["promoted_at"],
            source_manifest_cid=payload.get("source_manifest_cid", ""),
            target_namespace=payload.get("target_namespace", ""),
            reviewer_id=payload.get("reviewer_id", ""),
            approval_digest=payload.get("approval_digest", ""),
            schema_version=payload.get(
                "schema_version", PROMOTION_RECEIPT_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _normalize_registry_list(
    value: Any, expected_kind: RegistryKind, field_name: str
) -> tuple[RegistryBinding, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping, RegistryBinding)):
        raise ProofCorpusManifestError(
            f"{field_name} must be a sequence of registry bindings"
        )
    try:
        items = tuple(
            item
            if isinstance(item, RegistryBinding)
            else RegistryBinding.from_dict(item)
            for item in value
        )
    except TypeError as exc:
        raise ProofCorpusManifestError(
            f"{field_name} must be a sequence of registry bindings"
        ) from exc
    seen_ids: set[str] = set()
    for item in items:
        if item.registry_kind is not expected_kind:
            raise ProofCorpusManifestIntegrityError(
                f"{field_name} entry {item.registry_id!r} must have "
                f"registry_kind={expected_kind.value!r}"
            )
        if item.registry_id in seen_ids:
            raise ProofCorpusManifestIntegrityError(
                f"{field_name} contains duplicate registry_id "
                f"{item.registry_id!r}"
            )
        seen_ids.add(item.registry_id)
    return items


def _normalize_sources(value: Any) -> tuple[SourceBinding, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping, SourceBinding)):
        raise ProofCorpusManifestError(
            "sources must be a sequence of source bindings"
        )
    try:
        items = tuple(
            item if isinstance(item, SourceBinding) else SourceBinding.from_dict(item)
            for item in value
        )
    except TypeError as exc:
        raise ProofCorpusManifestError(
            "sources must be a sequence of source bindings"
        ) from exc
    seen: set[str] = set()
    for item in items:
        if item.source_id in seen:
            raise ProofCorpusManifestIntegrityError(
                f"sources contains duplicate source_id {item.source_id!r}"
            )
        seen.add(item.source_id)
    return items


def _normalize_index_manifests(value: Any) -> tuple[IndexManifestRef, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping, IndexManifestRef)):
        raise ProofCorpusManifestError(
            "index_manifests must be a sequence of index manifest refs"
        )
    try:
        items = tuple(
            item
            if isinstance(item, IndexManifestRef)
            else IndexManifestRef.from_dict(item)
            for item in value
        )
    except TypeError as exc:
        raise ProofCorpusManifestError(
            "index_manifests must be a sequence of index manifest refs"
        ) from exc
    seen: set[str] = set()
    for item in items:
        if item.index_id in seen:
            raise ProofCorpusManifestIntegrityError(
                f"index_manifests contains duplicate index_id {item.index_id!r}"
            )
        seen.add(item.index_id)
    return items


def _normalize_entries(value: Any) -> tuple[ManifestEntry, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping, ManifestEntry)):
        raise ProofCorpusManifestError(
            "entries must be a sequence of manifest entries"
        )
    try:
        items = tuple(
            item if isinstance(item, ManifestEntry) else ManifestEntry.from_dict(item)
            for item in value
        )
    except TypeError as exc:
        raise ProofCorpusManifestError(
            "entries must be a sequence of manifest entries"
        ) from exc
    return items


def _normalize_approved_roots(value: Any) -> tuple[str, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        raise ProofCorpusManifestError(
            "approved_registry_roots must be a sequence of CIDs"
        )
    try:
        items = tuple(_require_cid(item, "approved_registry_roots") for item in value)
    except TypeError as exc:
        raise ProofCorpusManifestError(
            "approved_registry_roots must be a sequence of CIDs"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofCorpusManifestIntegrityError(
            "approved_registry_roots values must be unique"
        )
    return items


@dataclass(frozen=True, slots=True)
class ProofCorpusManifest:
    """Immutable exact-root proof corpus manifest (ProofCorpusManifest@1).

    Identity is content-addressed over the canonical authority payload.  Load
    paths rehash and fail closed on digest/CID drift.  Parent lineage is
    append-only: generation must strictly increase and parent cycles are
    rejected when checked via :func:`check_append_only_lineage`.
    """

    domain: str
    namespace: str
    entries: tuple[ManifestEntry, ...] | Sequence[ManifestEntry] = ()
    sources: tuple[SourceBinding, ...] | Sequence[SourceBinding] = ()
    compiler_registry: (
        tuple[RegistryBinding, ...] | Sequence[RegistryBinding]
    ) = ()
    solver_registry: tuple[RegistryBinding, ...] | Sequence[RegistryBinding] = ()
    circuit_registry: (
        tuple[RegistryBinding, ...] | Sequence[RegistryBinding]
    ) = ()
    vk_registry: tuple[RegistryBinding, ...] | Sequence[RegistryBinding] = ()
    index_manifests: (
        tuple[IndexManifestRef, ...] | Sequence[IndexManifestRef]
    ) = ()
    revocation_root_cid: str = ""
    policy: PolicyBinding | Mapping[str, Any] | None = None
    producer_id: str = ""
    promotion_receipt: PromotionReceipt | Mapping[str, Any] | None = None
    parent_cid: str = ""
    generation: int = 1
    approved_registry_roots: tuple[str, ...] | Sequence[str] = ()
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES
    content_digest: str = ""
    content_cid: str = ""
    root_cid: str = ""
    schema_version: str = PROOF_CORPUS_MANIFEST_SCHEMA_VERSION
    interface: str = PROOF_CORPUS_MANIFEST_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain", _require_identifier(self.domain, "domain")
        )
        object.__setattr__(
            self, "namespace", _require_namespace(self.namespace, "namespace")
        )
        object.__setattr__(
            self, "entries", _normalize_entries(self.entries)
        )
        if len(self.entries) > DEFAULT_MAX_MANIFEST_ENTRIES:
            raise ProofCorpusManifestIntegrityError(
                f"entries exceed max_manifest_entries "
                f"({DEFAULT_MAX_MANIFEST_ENTRIES})"
            )

        # Ordered entries: ordinals must be unique and sorted non-decreasing.
        ordinals = [entry.ordinal for entry in self.entries]
        if ordinals != sorted(ordinals):
            raise ProofCorpusManifestIntegrityError(
                "entries must be ordered by non-decreasing ordinal"
            )
        if len(ordinals) != len(set(ordinals)):
            raise ProofCorpusManifestIntegrityError(
                "entries must have unique ordinals"
            )

        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ProofCorpusManifestIntegrityError(
                "entries contain duplicate entry_id (duplicate bodies rejected)"
            )
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ProofCorpusManifestIntegrityError(
                "entries contain duplicate path (duplicate bodies rejected)"
            )
        body_cids = [entry.content_cid for entry in self.entries]
        if len(body_cids) != len(set(body_cids)):
            raise ProofCorpusManifestIntegrityError(
                "entries contain duplicate content_cid "
                "(duplicate bodies rejected)"
            )

        object.__setattr__(self, "sources", _normalize_sources(self.sources))
        source_ids = {source.source_id for source in self.sources}
        for entry in self.entries:
            if entry.source_id and entry.source_id not in source_ids:
                raise ProofCorpusManifestIntegrityError(
                    f"entry {entry.entry_id!r} source_id "
                    f"{entry.source_id!r} is not in the source set"
                )

        object.__setattr__(
            self,
            "compiler_registry",
            _normalize_registry_list(
                self.compiler_registry, RegistryKind.COMPILER, "compiler_registry"
            ),
        )
        object.__setattr__(
            self,
            "solver_registry",
            _normalize_registry_list(
                self.solver_registry, RegistryKind.SOLVER, "solver_registry"
            ),
        )
        object.__setattr__(
            self,
            "circuit_registry",
            _normalize_registry_list(
                self.circuit_registry, RegistryKind.CIRCUIT, "circuit_registry"
            ),
        )
        object.__setattr__(
            self,
            "vk_registry",
            _normalize_registry_list(
                self.vk_registry, RegistryKind.VK, "vk_registry"
            ),
        )
        object.__setattr__(
            self,
            "index_manifests",
            _normalize_index_manifests(self.index_manifests),
        )
        # Indices must never appear as body paths/ids.
        index_ids = {ref.index_id for ref in self.index_manifests}
        index_cids = {ref.index_cid for ref in self.index_manifests}
        for entry in self.entries:
            if entry.entry_id in index_ids:
                raise ProofCorpusManifestIntegrityError(
                    f"body entry_id {entry.entry_id!r} collides with an "
                    "index_manifests id (bodies and indices must be separate)"
                )
            if entry.content_cid in index_cids:
                raise ProofCorpusManifestIntegrityError(
                    f"body content_cid collides with an index_manifests cid "
                    f"(bodies and indices must be separate)"
                )

        object.__setattr__(
            self,
            "revocation_root_cid",
            _optional_cid(self.revocation_root_cid, "revocation_root_cid"),
        )

        policy = self.policy
        if policy is None:
            policy = PolicyBinding()
        elif not isinstance(policy, PolicyBinding):
            policy = PolicyBinding.from_dict(policy)
        object.__setattr__(self, "policy", policy)

        object.__setattr__(
            self, "producer_id", _optional_text(self.producer_id, "producer_id")
        )

        receipt = self.promotion_receipt
        if receipt is None:
            receipt_obj: PromotionReceipt | None = None
        elif isinstance(receipt, PromotionReceipt):
            receipt_obj = receipt
        else:
            receipt_obj = PromotionReceipt.from_dict(receipt)
        object.__setattr__(self, "promotion_receipt", receipt_obj)
        if receipt_obj is not None and self.producer_id:
            if receipt_obj.producer_id != self.producer_id:
                raise ProofCorpusManifestIntegrityError(
                    "promotion_receipt.producer_id must match producer_id"
                )
        if receipt_obj is not None and not self.producer_id:
            object.__setattr__(self, "producer_id", receipt_obj.producer_id)

        object.__setattr__(
            self, "parent_cid", _optional_cid(self.parent_cid, "parent_cid")
        )
        object.__setattr__(
            self,
            "generation",
            _require_positive_int(self.generation, "generation"),
        )
        if self.parent_cid == "" and self.generation != 1:
            # Roots may use any positive generation, but generation 1 is the
            # conventional root; no hard constraint beyond positivity.
            pass

        object.__setattr__(
            self,
            "approved_registry_roots",
            _normalize_approved_roots(self.approved_registry_roots),
        )
        object.__setattr__(
            self,
            "max_entry_bytes",
            _require_positive_int(self.max_entry_bytes, "max_entry_bytes"),
        )

        for entry in self.entries:
            if entry.size_bytes > self.max_entry_bytes:
                raise ProofCorpusManifestIntegrityError(
                    f"entry {entry.entry_id!r} size_bytes "
                    f"{entry.size_bytes} exceeds max_entry_bytes "
                    f"{self.max_entry_bytes} (oversize content rejected)"
                )

        # Unapproved registry roots fail closed when an allowlist is set.
        if self.approved_registry_roots:
            approved = set(self.approved_registry_roots)
            for reg in (
                *self.compiler_registry,
                *self.solver_registry,
                *self.circuit_registry,
                *self.vk_registry,
            ):
                if reg.root_cid not in approved:
                    raise ProofCorpusManifestIntegrityError(
                        f"unapproved registry root {reg.root_cid!r} for "
                        f"{reg.registry_kind.value} registry "
                        f"{reg.registry_id!r}"
                    )

        if self.schema_version != PROOF_CORPUS_MANIFEST_SCHEMA_VERSION:
            raise ProofCorpusManifestError(
                f"unsupported proof corpus manifest schema: "
                f"{self.schema_version!r}"
            )
        if self.interface != PROOF_CORPUS_MANIFEST_INTERFACE:
            raise ProofCorpusManifestError(
                f"unsupported proof corpus manifest interface: "
                f"{self.interface!r}"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise ProofCorpusManifestIntegrityError(
                    "manifest content_digest does not match payload "
                    "(hash mismatch)"
                )
        if self.content_cid:
            recorded_cid = _require_cid(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise ProofCorpusManifestIntegrityError(
                    "manifest content_cid does not match payload (CID mismatch)"
                )
        if self.root_cid:
            recorded_root = _require_cid(self.root_cid, "root_cid")
            if recorded_root != cid:
                raise ProofCorpusManifestIntegrityError(
                    "manifest root_cid does not match payload (CID mismatch)"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "root_cid", cid)

    # -- identity / serialization --------------------------------------------

    def _identity_payload(self) -> dict[str, Any]:
        assert isinstance(self.policy, PolicyBinding)
        return {
            "approved_registry_roots": list(self.approved_registry_roots),
            "circuit_registry": [item.to_dict() for item in self.circuit_registry],
            "compiler_registry": [
                item.to_dict() for item in self.compiler_registry
            ],
            "domain": self.domain,
            "entries": [item.to_dict() for item in self.entries],
            "generation": self.generation,
            "index_manifests": [
                item.to_dict() for item in self.index_manifests
            ],
            "interface": self.interface,
            "max_entry_bytes": self.max_entry_bytes,
            "namespace": self.namespace,
            "parent_cid": self.parent_cid,
            "policy": self.policy.to_dict(),
            "producer_id": self.producer_id,
            "promotion_receipt": (
                self.promotion_receipt.to_dict()
                if self.promotion_receipt is not None
                else None
            ),
            "revocation_root_cid": self.revocation_root_cid,
            "schema_version": self.schema_version,
            "solver_registry": [item.to_dict() for item in self.solver_registry],
            "sources": [item.to_dict() for item in self.sources],
            "vk_registry": [item.to_dict() for item in self.vk_registry],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        payload["root_cid"] = self.root_cid
        return _json_ready(payload)

    @classmethod
    def from_dict(cls, value: Any) -> "ProofCorpusManifest":
        if isinstance(value, ProofCorpusManifest):
            return value
        payload = dict(_as_mapping(value, "proof corpus manifest"))
        _reject_unknown(payload, _MANIFEST_FIELDS, "proof corpus manifest")
        return cls(
            domain=payload["domain"],
            namespace=payload["namespace"],
            entries=tuple(payload.get("entries", ()) or ()),
            sources=tuple(payload.get("sources", ()) or ()),
            compiler_registry=tuple(payload.get("compiler_registry", ()) or ()),
            solver_registry=tuple(payload.get("solver_registry", ()) or ()),
            circuit_registry=tuple(payload.get("circuit_registry", ()) or ()),
            vk_registry=tuple(payload.get("vk_registry", ()) or ()),
            index_manifests=tuple(payload.get("index_manifests", ()) or ()),
            revocation_root_cid=payload.get("revocation_root_cid", ""),
            policy=payload.get("policy"),
            producer_id=payload.get("producer_id", ""),
            promotion_receipt=payload.get("promotion_receipt"),
            parent_cid=payload.get("parent_cid", ""),
            generation=int(payload.get("generation", 1) or 1),
            approved_registry_roots=tuple(
                payload.get("approved_registry_roots", ()) or ()
            ),
            max_entry_bytes=int(
                payload.get("max_entry_bytes", DEFAULT_MAX_ENTRY_BYTES)
                or DEFAULT_MAX_ENTRY_BYTES
            ),
            content_digest=payload.get("content_digest", ""),
            content_cid=payload.get("content_cid", ""),
            root_cid=payload.get("root_cid", ""),
            schema_version=payload.get(
                "schema_version", PROOF_CORPUS_MANIFEST_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", PROOF_CORPUS_MANIFEST_INTERFACE
            ),
        )

    def verify_integrity(self) -> None:
        """Rehash identity and fail closed on digest/CID drift."""

        restored = ProofCorpusManifest.from_dict(self.to_dict())
        if restored.content_digest != self.content_digest:
            raise ProofCorpusManifestIntegrityError(
                "manifest content_digest drifted on rehash"
            )
        if restored.root_cid != self.root_cid:
            raise ProofCorpusManifestIntegrityError(
                "manifest root_cid drifted on rehash"
            )

    def body_paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries)

    def body_cids(self) -> tuple[str, ...]:
        return tuple(entry.content_cid for entry in self.entries)

    def entry_by_id(self, entry_id: str) -> ManifestEntry:
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return entry
        raise KeyError(entry_id)

    def all_registry_bindings(self) -> tuple[RegistryBinding, ...]:
        return (
            *self.compiler_registry,
            *self.solver_registry,
            *self.circuit_registry,
            *self.vk_registry,
        )


def build_manifest_entry(
    *,
    entry_id: str,
    path: str,
    content: bytes,
    ordinal: int = 0,
    source_id: str = "",
    envelope_cid: str = "",
    media_type: str = "",
) -> ManifestEntry:
    """Build a body entry from raw bytes (digest and CID derived)."""

    if not isinstance(content, (bytes, bytearray)):
        raise ProofCorpusManifestError("content must be bytes")
    raw = bytes(content)
    digest = digest_bytes(raw)
    return ManifestEntry(
        entry_id=entry_id,
        path=path,
        content_cid=cid_for_digest(digest),
        content_digest=digest,
        size_bytes=len(raw),
        ordinal=ordinal,
        source_id=source_id,
        envelope_cid=envelope_cid,
        media_type=media_type,
    )


def build_index_manifest_ref(
    *,
    index_id: str,
    content: bytes,
    index_kind: IndexManifestKind | str = IndexManifestKind.COMPOSITE,
) -> IndexManifestRef:
    """Build an index-manifest reference from raw index bytes."""

    if not isinstance(content, (bytes, bytearray)):
        raise ProofCorpusManifestError("content must be bytes")
    raw = bytes(content)
    digest = digest_bytes(raw)
    return IndexManifestRef(
        index_id=index_id,
        index_cid=cid_for_digest(digest),
        index_digest=digest,
        index_kind=index_kind,
    )


def build_proof_corpus_manifest(**kwargs: Any) -> ProofCorpusManifest:
    """Construct a validated :class:`ProofCorpusManifest`."""

    return ProofCorpusManifest(**kwargs)


def verify_manifest_bodies(
    manifest: ProofCorpusManifest,
    bodies: Mapping[str, bytes],
    *,
    allow_extra: bool = False,
) -> None:
    """Verify body store against a manifest (missing/unbound/hash/size).

    Parameters
    ----------
    manifest:
        The exact-root corpus manifest.
    bodies:
        Mapping of root-relative path → raw body bytes.
    allow_extra:
        When false (default), any path present in *bodies* but not bound by
        the manifest is rejected as an unbound body.
    """

    if not isinstance(manifest, ProofCorpusManifest):
        raise ProofCorpusManifestError(
            "manifest must be a ProofCorpusManifest"
        )
    if not isinstance(bodies, Mapping):
        raise ProofCorpusManifestError("bodies must be a mapping of path→bytes")

    bound_paths = set(manifest.body_paths())
    provided_paths = set(bodies)

    missing = sorted(bound_paths - provided_paths)
    if missing:
        raise ProofCorpusManifestIntegrityError(
            f"missing bodies for manifest paths: {', '.join(missing)}"
        )

    if not allow_extra:
        unbound = sorted(provided_paths - bound_paths)
        if unbound:
            raise ProofCorpusManifestIntegrityError(
                f"unbound bodies not declared in manifest: "
                f"{', '.join(unbound)}"
            )

    for entry in manifest.entries:
        # Path safety already enforced on construction; re-check traversal on
        # provided keys to catch attacker-controlled body maps.
        require_safe_relative_path(entry.path, "body path")
        raw = bodies[entry.path]
        if not isinstance(raw, (bytes, bytearray)):
            raise ProofCorpusManifestIntegrityError(
                f"body for {entry.path!r} must be bytes"
            )
        data = bytes(raw)
        if len(data) > manifest.max_entry_bytes:
            raise ProofCorpusManifestIntegrityError(
                f"body for {entry.path!r} exceeds max_entry_bytes "
                f"(oversize content rejected)"
            )
        if len(data) != entry.size_bytes:
            raise ProofCorpusManifestIntegrityError(
                f"body for {entry.path!r} size mismatch: "
                f"got {len(data)}, expected {entry.size_bytes}"
            )
        digest = digest_bytes(data)
        if digest != entry.content_digest:
            raise ProofCorpusManifestIntegrityError(
                f"body for {entry.path!r} content_digest mismatch "
                f"(hash mismatch)"
            )
        cid = cid_for_digest(digest)
        if cid != entry.content_cid:
            raise ProofCorpusManifestIntegrityError(
                f"body for {entry.path!r} content_cid mismatch (CID mismatch)"
            )


def detect_parent_cycle(
    child_cid: str,
    parent_cid: str,
    lineage: Mapping[str, str] | None = None,
) -> None:
    """Reject parent cycles in manifest lineage.

    Parameters
    ----------
    child_cid:
        The child's own root CID.
    parent_cid:
        Immediate parent CID (empty for roots).
    lineage:
        Optional mapping of ``cid → parent_cid`` for ancestors already known.
    """

    if not parent_cid:
        return
    child = _require_cid(child_cid, "child_cid")
    parent = _require_cid(parent_cid, "parent_cid")
    if parent == child:
        raise ProofCorpusManifestIntegrityError(
            "manifest parent_cid must not equal its own root_cid "
            "(parent cycle rejected)"
        )
    if lineage is None:
        return
    seen: set[str] = {child}
    current = parent
    while current:
        if current in seen:
            raise ProofCorpusManifestIntegrityError(
                f"manifest parent lineage contains a cycle at {current!r}"
            )
        seen.add(current)
        current = lineage.get(current, "")
        if current:
            current = _require_cid(current, "lineage parent_cid")


def check_append_only_lineage(
    child: ProofCorpusManifest,
    parent: ProofCorpusManifest,
    *,
    lineage: Mapping[str, str] | None = None,
) -> None:
    """Validate append-only parent lineage and reject rollback/downgrade.

    Rules:

    * ``child.parent_cid`` must equal ``parent.root_cid``;
    * ``child.generation`` must be strictly greater than ``parent.generation``;
    * domain/namespace must match;
    * no parent cycle;
    * registry versions for a shared ``registry_id`` must not decrease.
    """

    if not isinstance(child, ProofCorpusManifest):
        raise ProofCorpusManifestError("child must be a ProofCorpusManifest")
    if not isinstance(parent, ProofCorpusManifest):
        raise ProofCorpusManifestError("parent must be a ProofCorpusManifest")

    if not child.parent_cid:
        raise ProofCorpusManifestIntegrityError(
            "child manifest must declare parent_cid for lineage check"
        )
    if child.parent_cid != parent.root_cid:
        raise ProofCorpusManifestIntegrityError(
            "child.parent_cid must equal parent.root_cid"
        )
    if child.generation <= parent.generation:
        raise ProofCorpusManifestIntegrityError(
            f"child generation {child.generation} must be strictly greater "
            f"than parent generation {parent.generation} "
            "(rollback/downgrade rejected)"
        )
    if child.domain != parent.domain or child.namespace != parent.namespace:
        raise ProofCorpusManifestIntegrityError(
            "child domain/namespace must match parent "
            "(cross-namespace lineage rejected)"
        )

    detect_parent_cycle(
        child.root_cid,
        child.parent_cid,
        lineage={**(lineage or {}), parent.root_cid: parent.parent_cid},
    )

    parent_versions: dict[tuple[str, str], int] = {}
    for reg in parent.all_registry_bindings():
        kind = (
            reg.registry_kind.value
            if isinstance(reg.registry_kind, RegistryKind)
            else str(reg.registry_kind)
        )
        parent_versions[(kind, reg.registry_id)] = reg.version
    for reg in child.all_registry_bindings():
        kind = (
            reg.registry_kind.value
            if isinstance(reg.registry_kind, RegistryKind)
            else str(reg.registry_kind)
        )
        key = (kind, reg.registry_id)
        if key in parent_versions and reg.version < parent_versions[key]:
            raise ProofCorpusManifestIntegrityError(
                f"registry {kind}/{reg.registry_id} version downgrade "
                f"{parent_versions[key]} → {reg.version} rejected"
            )


def deterministic_rebuild_root(
    manifest: ProofCorpusManifest,
    bodies: Mapping[str, bytes],
) -> str:
    """Rebuild identity from bodies and return the expected root CID.

    Verifies bodies, re-derives digests, reconstructs the manifest, and
    returns the root CID.  Used as a deterministic offline rebuild receipt.
    """

    verify_manifest_bodies(manifest, bodies)
    rebuilt_entries: list[ManifestEntry] = []
    for entry in manifest.entries:
        raw = bodies[entry.path]
        rebuilt_entries.append(
            build_manifest_entry(
                entry_id=entry.entry_id,
                path=entry.path,
                content=bytes(raw),
                ordinal=entry.ordinal,
                source_id=entry.source_id,
                envelope_cid=entry.envelope_cid,
                media_type=entry.media_type,
            )
        )
    rebuilt = ProofCorpusManifest(
        domain=manifest.domain,
        namespace=manifest.namespace,
        entries=tuple(rebuilt_entries),
        sources=manifest.sources,
        compiler_registry=manifest.compiler_registry,
        solver_registry=manifest.solver_registry,
        circuit_registry=manifest.circuit_registry,
        vk_registry=manifest.vk_registry,
        index_manifests=manifest.index_manifests,
        revocation_root_cid=manifest.revocation_root_cid,
        policy=manifest.policy,
        producer_id=manifest.producer_id,
        promotion_receipt=manifest.promotion_receipt,
        parent_cid=manifest.parent_cid,
        generation=manifest.generation,
        approved_registry_roots=manifest.approved_registry_roots,
        max_entry_bytes=manifest.max_entry_bytes,
    )
    if rebuilt.root_cid != manifest.root_cid:
        raise ProofCorpusManifestIntegrityError(
            "deterministic rebuild root does not match original root_cid"
        )
    return rebuilt.root_cid


__all__ = [
    "DEFAULT_MAX_ENTRY_BYTES",
    "DEFAULT_MAX_MANIFEST_ENTRIES",
    "EntryKind",
    "INDEX_MANIFEST_REF_SCHEMA_VERSION",
    "IndexManifestKind",
    "IndexManifestRef",
    "MANIFEST_ENTRY_SCHEMA_VERSION",
    "ManifestEntry",
    "POLICY_BINDING_SCHEMA_VERSION",
    "PROMOTION_RECEIPT_SCHEMA_VERSION",
    "PROOF_CORPUS_MANIFEST_INTERFACE",
    "PROOF_CORPUS_MANIFEST_SCHEMA_VERSION",
    "PolicyBinding",
    "PromotionReceipt",
    "ProofCorpusManifest",
    "ProofCorpusManifestError",
    "ProofCorpusManifestIntegrityError",
    "REGISTRY_BINDING_SCHEMA_VERSION",
    "RegistryBinding",
    "RegistryKind",
    "SOURCE_BINDING_SCHEMA_VERSION",
    "SourceBinding",
    "build_index_manifest_ref",
    "build_manifest_entry",
    "build_proof_corpus_manifest",
    "check_append_only_lineage",
    "cid_for_digest",
    "detect_parent_cycle",
    "deterministic_rebuild_root",
    "digest_bytes",
    "require_safe_relative_path",
    "verify_manifest_bodies",
]
