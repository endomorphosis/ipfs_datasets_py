"""Canonical, immutable records for the derived CVEfixes Security IR dataset.

These records are deliberately *data* contracts.  A policy candidate, formal
view, graph relation, or evaluation result cannot grant execution authority.
Every record binds exact source, parent, and producer-configuration identities
and receives a CID from the shared :mod:`ir_core` identity profile.

``record_id`` is computed from deterministic content.  Decoders accept it only
as an integrity assertion: an omitted ID is computed, while a supplied ID must
match.  This makes records convenient to construct without permitting callers
to choose or preserve a stale identity.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any, ClassVar, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity, canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)


CVEFIXES_SCHEMA_VERSION: Final = "cvefixes-security-ir-derived/v1"
CVEFIXES_DATASET_SCHEMA_VERSION: Final = "cvefixes-security-ir-dataset/v1"
CVEFIXES_IDENTITY_DOMAIN_PREFIX: Final = "cvefixes-security-ir"

_CID_LENGTH = 59
_CID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_IR_CORE_CID_HEADER = b"\x01\x55\x12\x20"


class CVEfixesSchemaError(ValueError):
    """Raised when a derived CVEfixes record violates the schema contract."""


class DerivedAuthority(str, Enum):
    """Non-granting authority labels admitted by the derived-data schema."""

    NON_AUTHORITATIVE = "non_authoritative"
    CANDIDATE = "candidate"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CVEfixesSchemaError(f"{label} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CVEfixesSchemaError(
            f"unknown {label} field(s): {', '.join(unknown)}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CVEfixesSchemaError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise CVEfixesSchemaError(
            f"{label} must not have surrounding whitespace"
        )
    return value


def _cid(value: Any, label: str) -> str:
    result = _text(value, label)
    if (
        len(result) != _CID_LENGTH
        or not result.startswith("b")
        or any(character not in _CID_ALPHABET for character in result)
    ):
        raise CVEfixesSchemaError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        )
    try:
        encoded = result[1:].upper()
        raw = base64.b32decode(encoded + ("=" * ((-len(encoded)) % 8)))
    except (ValueError, base64.binascii.Error) as exc:
        raise CVEfixesSchemaError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        ) from exc
    if len(raw) != 36 or not raw.startswith(_IR_CORE_CID_HEADER):
        raise CVEfixesSchemaError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        )
    return result


def _cid_tuple(value: Any, label: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise CVEfixesSchemaError(f"{label} must be a sequence of CIDs")
    result = tuple(_cid(item, f"{label} item") for item in value)
    if nonempty and not result:
        raise CVEfixesSchemaError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise CVEfixesSchemaError(f"{label} must not contain duplicate IDs")
    return tuple(sorted(result))


def _string_tuple(
    value: Any, label: str, *, nonempty: bool = False
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise CVEfixesSchemaError(f"{label} must be a sequence of strings")
    result = tuple(_text(item, f"{label} item") for item in value)
    if nonempty and not result:
        raise CVEfixesSchemaError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise CVEfixesSchemaError(f"{label} must not contain duplicate IDs")
    return tuple(sorted(result))


def _frozen_mapping(value: Any, label: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(_mapping(value, label))
    except ProvenanceValidationError as exc:
        raise CVEfixesSchemaError(f"{label}: {exc}") from exc


def _authority(value: Any, expected: DerivedAuthority) -> DerivedAuthority:
    try:
        result = (
            value
            if isinstance(value, DerivedAuthority)
            else DerivedAuthority(value)
        )
    except (TypeError, ValueError) as exc:
        raise CVEfixesSchemaError(
            "authority must be 'non_authoritative' or 'candidate'; "
            "derived records cannot grant authority"
        ) from exc
    if result is not expected:
        raise CVEfixesSchemaError(
            f"this record requires authority={expected.value!r}; "
            "derived records cannot broaden authority"
        )
    return result


def _schema_version(value: Any, expected: str) -> str:
    if value != expected:
        raise CVEfixesSchemaError(
            f"unsupported schema_version {value!r}; expected {expected!r}"
        )
    return expected


def canonical_config_cid(
    config: Mapping[str, Any],
    *,
    schema_version: str = "cvefixes-security-ir-config/v1",
) -> str:
    """Return the shared-profile CID for an out-of-band producer config."""

    return canonical_identity(
        _mapping(config, "config"),
        domain=f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/config",
        schema_version=_text(schema_version, "schema_version"),
    ).cid


def _decode_json_object(
    value: str | bytes | bytearray, label: str
) -> Mapping[str, Any]:
    if not isinstance(value, (str, bytes, bytearray)):
        raise CVEfixesSchemaError(f"{label} JSON must be text or bytes")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise CVEfixesSchemaError(
                    f"{label} JSON contains duplicate field {key!r}"
                )
            result[key] = item
        return result

    def reject_constant(constant: str) -> None:
        raise CVEfixesSchemaError(
            f"{label} JSON contains non-finite number {constant}"
        )

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except CVEfixesSchemaError:
        raise
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise CVEfixesSchemaError(f"{label} is not valid JSON") from exc
    return _mapping(decoded, label)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalDerivedRecord:
    """Common lineage, identity, and strict wire behavior for derived records."""

    source_cids: tuple[str, ...]
    parent_cids: tuple[str, ...]
    config_cid: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    authority: DerivedAuthority = DerivedAuthority.NON_AUTHORITATIVE
    record_id: str = ""
    schema_version: str = CVEFIXES_SCHEMA_VERSION

    RECORD_TYPE: ClassVar[str] = "derived_record"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/derived-record"
    )
    EXPECTED_AUTHORITY: ClassVar[DerivedAuthority] = (
        DerivedAuthority.NON_AUTHORITATIVE
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_cids", _cid_tuple(self.source_cids, "source_cids")
        )
        object.__setattr__(
            self, "parent_cids", _cid_tuple(self.parent_cids, "parent_cids")
        )
        object.__setattr__(
            self, "config_cid", _cid(self.config_cid, "config_cid")
        )
        object.__setattr__(
            self, "payload", _frozen_mapping(self.payload, "payload")
        )
        object.__setattr__(
            self,
            "authority",
            _authority(self.authority, self.EXPECTED_AUTHORITY),
        )
        object.__setattr__(
            self,
            "schema_version",
            _schema_version(self.schema_version, CVEFIXES_SCHEMA_VERSION),
        )
        self._validate_specific()
        computed = self.identity.cid
        if self.record_id and self.record_id != computed:
            raise CVEfixesSchemaError(
                f"{self.RECORD_TYPE} record_id does not match deterministic content"
            )
        object.__setattr__(self, "record_id", computed)

    def _validate_specific(self) -> None:
        """Validate and freeze subclass fields."""

    def _specific_dict(self) -> dict[str, Any]:
        return {}

    def deterministic_dict(self) -> dict[str, Any]:
        """Return the complete record identity preimage, excluding its CID."""

        return {
            "authority": self.authority.value,
            "config_cid": self.config_cid,
            "parent_cids": list(self.parent_cids),
            "payload": thaw_json(self.payload),
            "record_type": self.RECORD_TYPE,
            "schema_version": self.schema_version,
            "source_cids": list(self.source_cids),
            **self._specific_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-ready wire record."""

        return {"record_id": self.record_id, **self.deterministic_dict()}

    def canonical_bytes(self) -> bytes:
        """Return canonical bytes for the complete wire record."""

        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        """Return canonical JSON for the complete wire record."""

        return self.canonical_bytes().decode("utf-8")

    @property
    def identity(self) -> CanonicalIdentity:
        """Return the shared ``ir_core`` canonical identity."""

        return canonical_identity(
            self.deterministic_dict(),
            domain=self.IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.record_id

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def canonical_id(self) -> str:
        return self.record_id

    @classmethod
    def _common_values(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "authority": value.get(
                "authority", cls.EXPECTED_AUTHORITY.value
            ),
            "config_cid": value.get("config_cid", ""),
            "parent_cids": value.get("parent_cids", ()),
            "payload": value.get("payload", {}),
            "record_id": value.get("record_id", ""),
            "schema_version": value.get(
                "schema_version", CVEFIXES_SCHEMA_VERSION
            ),
            "source_cids": value.get("source_cids", ()),
        }

    @classmethod
    def _prepare_dict(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        value = _mapping(value, cls.RECORD_TYPE)
        _known_fields(
            value,
            frozenset(
                {
                    "authority",
                    "config_cid",
                    "parent_cids",
                    "payload",
                    "record_id",
                    "record_type",
                    "schema_version",
                    "source_cids",
                    *cls.SPECIFIC_FIELDS,
                }
            ),
            cls.RECORD_TYPE,
        )
        if value.get("record_type") != cls.RECORD_TYPE:
            raise CVEfixesSchemaError(
                f"record_type must be {cls.RECORD_TYPE!r}"
            )
        return value

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "CanonicalDerivedRecord":
        """Decode strict JSON, rejecting duplicate keys and non-finite values."""

        return cls.from_dict(_decode_json_object(value, cls.RECORD_TYPE))


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRecord(CanonicalDerivedRecord):
    """One inert CVEfixes row bound to the pinned source snapshot."""

    source_uri: str
    source_revision: str
    row_key: str

    RECORD_TYPE: ClassVar[str] = "source_record"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/source-record"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"source_uri", "source_revision", "row_key"}
    )

    def _validate_specific(self) -> None:
        for name in ("source_uri", "source_revision", "row_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "row_key": self.row_key,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceRecord":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            source_uri=value.get("source_uri", ""),
            source_revision=value.get("source_revision", ""),
            row_key=value.get("row_key", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CodeUnit(CanonicalDerivedRecord):
    """A file, hunk, or symbol projection with vulnerable/fixed polarity."""

    unit_kind: str
    language: str
    path: str
    polarity: str

    RECORD_TYPE: ClassVar[str] = "code_unit"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/code-unit"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"unit_kind", "language", "path", "polarity"}
    )

    def _validate_specific(self) -> None:
        for name in ("unit_kind", "language", "path", "polarity"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.polarity not in {"vulnerable", "fixed"}:
            raise CVEfixesSchemaError(
                "polarity must be 'vulnerable' or 'fixed'"
            )

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "path": self.path,
            "polarity": self.polarity,
            "unit_kind": self.unit_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeUnit":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            unit_kind=value.get("unit_kind", ""),
            language=value.get("language", ""),
            path=value.get("path", ""),
            polarity=value.get("polarity", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphNode(CanonicalDerivedRecord):
    """A typed, non-authoritative GraphRAG node."""

    node_type: str

    RECORD_TYPE: ClassVar[str] = "graph_node"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/graph-node"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"node_type"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "node_type", _text(self.node_type, "node_type"))

    def _specific_dict(self) -> dict[str, Any]:
        return {"node_type": self.node_type}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphNode":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            node_type=value.get("node_type", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphEdge(CanonicalDerivedRecord):
    """A typed graph relation whose endpoints are canonical node CIDs."""

    edge_type: str
    source_node_cid: str
    target_node_cid: str

    RECORD_TYPE: ClassVar[str] = "graph_edge"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/graph-edge"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"edge_type", "source_node_cid", "target_node_cid"}
    )

    def _validate_specific(self) -> None:
        object.__setattr__(self, "edge_type", _text(self.edge_type, "edge_type"))
        object.__setattr__(
            self,
            "source_node_cid",
            _cid(self.source_node_cid, "source_node_cid"),
        )
        object.__setattr__(
            self,
            "target_node_cid",
            _cid(self.target_node_cid, "target_node_cid"),
        )

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "edge_type": self.edge_type,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphEdge":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            edge_type=value.get("edge_type", ""),
            source_node_cid=value.get("source_node_cid", ""),
            target_node_cid=value.get("target_node_cid", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyCandidate(CanonicalDerivedRecord):
    """A proposed policy that remains distinct from reviewed authority."""

    effect: str
    scope: Mapping[str, Any]
    authority: DerivedAuthority = DerivedAuthority.CANDIDATE

    RECORD_TYPE: ClassVar[str] = "policy_candidate"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/policy-candidate"
    )
    EXPECTED_AUTHORITY: ClassVar[DerivedAuthority] = DerivedAuthority.CANDIDATE
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset({"effect", "scope"})

    def _validate_specific(self) -> None:
        object.__setattr__(self, "effect", _text(self.effect, "effect"))
        if self.effect not in {"allow", "deny", "require", "audit"}:
            raise CVEfixesSchemaError(
                "effect must be allow, deny, require, or audit"
            )
        object.__setattr__(
            self, "scope", _frozen_mapping(self.scope, "scope")
        )
        if not self.scope:
            raise CVEfixesSchemaError("scope must not be empty")

    def _specific_dict(self) -> dict[str, Any]:
        return {"effect": self.effect, "scope": thaw_json(self.scope)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyCandidate":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            effect=value.get("effect", ""),
            scope=value.get("scope", {}),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FormalView(CanonicalDerivedRecord):
    """A non-authoritative formula or obligation derived from candidates."""

    formalism: str
    expression: str

    RECORD_TYPE: ClassVar[str] = "formal_view"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/formal-view"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"formalism", "expression"}
    )

    def _validate_specific(self) -> None:
        object.__setattr__(self, "formalism", _text(self.formalism, "formalism"))
        object.__setattr__(
            self, "expression", _text(self.expression, "expression")
        )

    def _specific_dict(self) -> dict[str, Any]:
        return {"expression": self.expression, "formalism": self.formalism}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalView":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            formalism=value.get("formalism", ""),
            expression=value.get("expression", ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationRecord(CanonicalDerivedRecord):
    """Measured evaluation data, never a promotion or execution grant."""

    subject_cids: tuple[str, ...]
    metrics: Mapping[str, Any]

    RECORD_TYPE: ClassVar[str] = "evaluation"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/evaluation"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"subject_cids", "metrics"}
    )

    def _validate_specific(self) -> None:
        object.__setattr__(
            self, "subject_cids", _cid_tuple(self.subject_cids, "subject_cids")
        )
        object.__setattr__(
            self, "metrics", _frozen_mapping(self.metrics, "metrics")
        )
        if not self.metrics:
            raise CVEfixesSchemaError("metrics must not be empty")

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "metrics": thaw_json(self.metrics),
            "subject_cids": list(self.subject_cids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationRecord":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            subject_cids=value.get("subject_cids", ()),
            metrics=value.get("metrics", {}),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseManifest(CanonicalDerivedRecord):
    """A deterministic release inventory bound to all emitted record CIDs."""

    dataset_id: str
    profile: str
    record_cids: tuple[str, ...]
    shard_cids: tuple[str, ...]

    RECORD_TYPE: ClassVar[str] = "release_manifest"
    IDENTITY_DOMAIN: ClassVar[str] = (
        f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/release-manifest"
    )
    SPECIFIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"dataset_id", "profile", "record_cids", "shard_cids"}
    )

    def _validate_specific(self) -> None:
        object.__setattr__(self, "dataset_id", _text(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "profile", _text(self.profile, "profile"))
        object.__setattr__(
            self, "record_cids", _cid_tuple(self.record_cids, "record_cids")
        )
        object.__setattr__(
            self, "shard_cids", _cid_tuple(self.shard_cids, "shard_cids")
        )

    def _specific_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "profile": self.profile,
            "record_cids": list(self.record_cids),
            "shard_cids": list(self.shard_cids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleaseManifest":
        value = cls._prepare_dict(value)
        return cls(
            **cls._common_values(value),
            dataset_id=value.get("dataset_id", ""),
            profile=value.get("profile", ""),
            record_cids=value.get("record_cids", ()),
            shard_cids=value.get("shard_cids", ()),
        )


DerivedRecord = (
    SourceRecord
    | CodeUnit
    | GraphNode
    | GraphEdge
    | PolicyCandidate
    | FormalView
    | EvaluationRecord
    | ReleaseManifest
)

_RECORD_TYPES: Final[dict[str, type[CanonicalDerivedRecord]]] = {
    record_type.RECORD_TYPE: record_type
    for record_type in (
        SourceRecord,
        CodeUnit,
        GraphNode,
        GraphEdge,
        PolicyCandidate,
        FormalView,
        EvaluationRecord,
        ReleaseManifest,
    )
}


def record_from_dict(value: Mapping[str, Any]) -> DerivedRecord:
    """Decode one strict record using its required ``record_type`` tag."""

    value = _mapping(value, "record")
    record_type = value.get("record_type")
    try:
        decoder = _RECORD_TYPES[record_type]
    except (KeyError, TypeError) as exc:
        raise CVEfixesSchemaError(
            f"unknown record_type {record_type!r}"
        ) from exc
    return decoder.from_dict(value)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class DerivedDataset:
    """Canonical aggregate that rejects duplicate semantic or content IDs."""

    records: tuple[DerivedRecord, ...]
    dataset_id: str = ""
    schema_version: str = CVEFIXES_DATASET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version, CVEFIXES_DATASET_SCHEMA_VERSION)
        if isinstance(self.records, (str, bytes, bytearray)) or not isinstance(
            self.records, Sequence
        ):
            raise CVEfixesSchemaError("records must be a sequence")
        records = tuple(
            item
            if isinstance(item, CanonicalDerivedRecord)
            else record_from_dict(_mapping(item, "record"))
            for item in self.records
        )
        if not records:
            raise CVEfixesSchemaError("records must not be empty")
        record_ids = tuple(item.record_id for item in records)
        if len(record_ids) != len(set(record_ids)):
            raise CVEfixesSchemaError("records contain duplicate IDs")
        records = tuple(sorted(records, key=lambda item: item.record_id))
        object.__setattr__(self, "records", records)
        computed = self.identity.cid
        if self.dataset_id and self.dataset_id != computed:
            raise CVEfixesSchemaError(
                "dataset_id does not match deterministic content"
            )
        object.__setattr__(self, "dataset_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "records": [item.to_dict() for item in self.records],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"dataset_id": self.dataset_id, **self.deterministic_dict()}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain=f"{CVEFIXES_IDENTITY_DOMAIN_PREFIX}/dataset",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.dataset_id

    @property
    def digest(self) -> str:
        return self.identity.digest

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DerivedDataset":
        value = _mapping(value, "dataset")
        _known_fields(
            value,
            frozenset({"dataset_id", "records", "schema_version"}),
            "dataset",
        )
        raw_records = value.get("records", ())
        if isinstance(raw_records, (str, bytes, bytearray)) or not isinstance(
            raw_records, Sequence
        ):
            raise CVEfixesSchemaError("records must be a sequence")
        return cls(
            records=tuple(
                record_from_dict(_mapping(item, "record"))
                for item in raw_records
            ),
            dataset_id=value.get("dataset_id", ""),
            schema_version=value.get(
                "schema_version", CVEFIXES_DATASET_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "DerivedDataset":
        return cls.from_dict(_decode_json_object(value, "dataset"))


# Descriptive compatibility spellings for downstream pipeline modules.
CVEfixesSourceRecord = SourceRecord
CVEfixesCodeUnit = CodeUnit
CVEfixesGraphNode = GraphNode
CVEfixesGraphEdge = GraphEdge
CVEfixesPolicyCandidate = PolicyCandidate
CVEfixesFormalView = FormalView
CVEfixesEvaluation = EvaluationRecord
CVEfixesReleaseManifest = ReleaseManifest
CVEfixesDerivedDataset = DerivedDataset
Evaluation = EvaluationRecord
DatasetReleaseManifest = ReleaseManifest


__all__ = [
    "CVEFIXES_DATASET_SCHEMA_VERSION",
    "CVEFIXES_IDENTITY_DOMAIN_PREFIX",
    "CVEFIXES_SCHEMA_VERSION",
    "CVEfixesCodeUnit",
    "CVEfixesDerivedDataset",
    "CVEfixesEvaluation",
    "CVEfixesFormalView",
    "CVEfixesGraphEdge",
    "CVEfixesGraphNode",
    "CVEfixesPolicyCandidate",
    "CVEfixesReleaseManifest",
    "CVEfixesSchemaError",
    "CVEfixesSourceRecord",
    "CanonicalDerivedRecord",
    "CodeUnit",
    "DatasetReleaseManifest",
    "DerivedAuthority",
    "DerivedDataset",
    "DerivedRecord",
    "Evaluation",
    "EvaluationRecord",
    "FormalView",
    "GraphEdge",
    "GraphNode",
    "PolicyCandidate",
    "ReleaseManifest",
    "SourceRecord",
    "canonical_config_cid",
    "record_from_dict",
]
