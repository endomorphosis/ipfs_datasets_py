"""Immutable, source-body-free provenance contracts for the shared IR kernel.

The records in this module identify source bytes and the tools/configuration
that derived semantic IR.  They deliberately do not contain source text,
configuration payloads, prompts, logs, or model responses.  Those values live
in separately addressed artifacts and are joined here by digest and stable ID.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final


IR_PROVENANCE_SCHEMA_VERSION: Final = "ir-provenance/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceValidationError(ValueError):
    """Raised when provenance is malformed or contains dangling references."""


class SourceReviewStatus(str, Enum):
    """Review state of source bytes; this is not proof or policy authority."""

    UNREVIEWED = "unreviewed"
    MACHINE_EXTRACTED = "machine_extracted"
    HUMAN_REVIEWED = "human_reviewed"
    TRUSTED_FIXTURE = "trusted_fixture"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Reference to exact source bytes stored outside the semantic IR."""

    ref_id: str
    source_uri: str
    source_id: str
    source_revision: str
    content_sha256: str
    container_uri: str = ""
    container_sha256: str = ""
    content_cid: str = ""
    license_expression: str = ""
    review_status: SourceReviewStatus = SourceReviewStatus.UNREVIEWED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def content_digest(self) -> str:
        """Algorithm-qualified digest used by generic artifact consumers."""

        return f"sha256:{self.content_sha256}"

    def validate(self) -> None:
        _validate_id("SourceRef.ref_id", self.ref_id)
        _require_text("SourceRef.source_uri", self.source_uri)
        _require_text("SourceRef.source_id", self.source_id)
        _require_text("SourceRef.source_revision", self.source_revision)
        _validate_sha256("SourceRef.content_sha256", self.content_sha256)
        if self.container_sha256:
            _validate_sha256("SourceRef.container_sha256", self.container_sha256)
        _validate_enum("SourceRef.review_status", self.review_status, SourceReviewStatus)

    def to_dict(self) -> dict[str, Any]:
        return {
            "container_sha256": self.container_sha256,
            "container_uri": self.container_uri,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "license_expression": self.license_expression,
            "metadata": thaw_json(self.metadata),
            "ref_id": self.ref_id,
            "review_status": self.review_status.value,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRef":
        result = cls(
            ref_id=str(data.get("ref_id") or ""),
            source_uri=str(data.get("source_uri") or ""),
            source_id=str(data.get("source_id") or ""),
            source_revision=str(data.get("source_revision") or ""),
            content_sha256=str(data.get("content_sha256") or ""),
            container_uri=str(data.get("container_uri") or ""),
            container_sha256=str(data.get("container_sha256") or ""),
            content_cid=str(data.get("content_cid") or ""),
            license_expression=str(data.get("license_expression") or ""),
            review_status=_enum_value(
                SourceReviewStatus,
                data.get("review_status"),
                "SourceRef.review_status",
            ),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Inclusive-exclusive byte span in the content bound by a ``SourceRef``."""

    span_id: str
    source_ref_id: str
    start_byte: int
    end_byte: int
    start_char: int | None = None
    end_char: int | None = None
    start_line: int | None = None
    start_column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def start_offset(self) -> int:
        """Compatibility spelling for the inclusive byte offset."""

        return self.start_byte

    @property
    def end_offset(self) -> int:
        """Compatibility spelling for the exclusive byte offset."""

        return self.end_byte

    def validate(self) -> None:
        _validate_id("SourceSpan.span_id", self.span_id)
        _validate_id("SourceSpan.source_ref_id", self.source_ref_id)
        _validate_half_open("SourceSpan byte", self.start_byte, self.end_byte)
        _validate_optional_pair(
            "SourceSpan character", self.start_char, self.end_char, zero_based=True
        )
        line_values = (
            self.start_line,
            self.start_column,
            self.end_line,
            self.end_column,
        )
        if any(value is not None for value in line_values):
            if any(value is None for value in line_values):
                raise ProvenanceValidationError(
                    "SourceSpan line coordinates must be supplied as a complete pair"
                )
            assert self.start_line is not None
            assert self.start_column is not None
            assert self.end_line is not None
            assert self.end_column is not None
            for name, value in (
                ("start_line", self.start_line),
                ("start_column", self.start_column),
                ("end_line", self.end_line),
                ("end_column", self.end_column),
            ):
                _validate_int(f"SourceSpan.{name}", value, minimum=1)
            if (self.end_line, self.end_column) < (
                self.start_line,
                self.start_column,
            ):
                raise ProvenanceValidationError(
                    "SourceSpan end line/column precedes its start"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_byte": self.end_byte,
            "end_char": self.end_char,
            "end_column": self.end_column,
            "end_line": self.end_line,
            "metadata": thaw_json(self.metadata),
            "source_ref_id": self.source_ref_id,
            "span_id": self.span_id,
            "start_byte": self.start_byte,
            "start_char": self.start_char,
            "start_column": self.start_column,
            "start_line": self.start_line,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSpan":
        result = cls(
            span_id=str(data.get("span_id") or ""),
            source_ref_id=str(data.get("source_ref_id") or ""),
            start_byte=_required_int(data, "start_byte"),
            end_byte=_required_int(data, "end_byte"),
            start_char=_optional_int(data.get("start_char")),
            end_char=_optional_int(data.get("end_char")),
            start_line=_optional_int(data.get("start_line")),
            start_column=_optional_int(data.get("start_column")),
            end_line=_optional_int(data.get("end_line")),
            end_column=_optional_int(data.get("end_column")),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class ProducerBinding:
    """Identity of code or a model that produced an IR artifact."""

    producer_id: str
    name: str
    version: str
    implementation_sha256: str = ""
    repository_revision: str = ""
    model_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def validate(self) -> None:
        _validate_id("ProducerBinding.producer_id", self.producer_id)
        _require_text("ProducerBinding.name", self.name)
        _require_text("ProducerBinding.version", self.version)
        if self.implementation_sha256:
            _validate_sha256(
                "ProducerBinding.implementation_sha256",
                self.implementation_sha256,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation_sha256": self.implementation_sha256,
            "metadata": thaw_json(self.metadata),
            "model_id": self.model_id,
            "name": self.name,
            "producer_id": self.producer_id,
            "repository_revision": self.repository_revision,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProducerBinding":
        result = cls(
            producer_id=str(data.get("producer_id") or ""),
            name=str(data.get("name") or ""),
            version=str(data.get("version") or ""),
            implementation_sha256=str(data.get("implementation_sha256") or ""),
            repository_revision=str(data.get("repository_revision") or ""),
            model_id=str(data.get("model_id") or ""),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class ConfigBinding:
    """Content identity of producer configuration stored out of band."""

    config_id: str
    content_sha256: str
    schema_id: str = ""
    content_cid: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def content_digest(self) -> str:
        return f"sha256:{self.content_sha256}"

    def validate(self) -> None:
        _validate_id("ConfigBinding.config_id", self.config_id)
        _validate_sha256("ConfigBinding.content_sha256", self.content_sha256)
        if self.schema_id:
            _validate_id("ConfigBinding.schema_id", self.schema_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "metadata": thaw_json(self.metadata),
            "schema_id": self.schema_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConfigBinding":
        result = cls(
            config_id=str(data.get("config_id") or ""),
            content_sha256=str(data.get("content_sha256") or ""),
            schema_id=str(data.get("schema_id") or ""),
            content_cid=str(data.get("content_cid") or ""),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class ProvenanceBinding:
    """Grounding of one semantic node, relation, assertion, or formula."""

    binding_id: str
    subject_id: str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    evidence_ref_ids: tuple[str, ...] = ()
    producer_id: str = ""
    config_id: str = ""
    parent_subject_ids: tuple[str, ...] = ()
    derived: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref_ids", _unique_tuple(self.source_ref_ids))
        object.__setattr__(self, "span_ids", _unique_tuple(self.span_ids))
        object.__setattr__(
            self, "evidence_ref_ids", _unique_tuple(self.evidence_ref_ids)
        )
        object.__setattr__(
            self, "parent_subject_ids", _unique_tuple(self.parent_subject_ids)
        )
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def validate(self) -> None:
        _validate_id("ProvenanceBinding.binding_id", self.binding_id)
        _validate_id("ProvenanceBinding.subject_id", self.subject_id)
        for name, values in (
            ("source_ref_ids", self.source_ref_ids),
            ("span_ids", self.span_ids),
            ("evidence_ref_ids", self.evidence_ref_ids),
            ("parent_subject_ids", self.parent_subject_ids),
        ):
            for value in values:
                _validate_id(f"ProvenanceBinding.{name}", value)
        if self.producer_id:
            _validate_id("ProvenanceBinding.producer_id", self.producer_id)
        if self.config_id:
            _validate_id("ProvenanceBinding.config_id", self.config_id)
        if not self.derived and not (self.source_ref_ids or self.span_ids):
            raise ProvenanceValidationError(
                f"ProvenanceBinding {self.binding_id!r} is neither source-grounded "
                "nor explicitly derived"
            )
        if self.derived and not (
            self.parent_subject_ids
            or self.source_ref_ids
            or self.span_ids
            or self.evidence_ref_ids
        ):
            raise ProvenanceValidationError(
                f"Derived ProvenanceBinding {self.binding_id!r} has no lineage"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "config_id": self.config_id,
            "derived": self.derived,
            "evidence_ref_ids": list(self.evidence_ref_ids),
            "metadata": thaw_json(self.metadata),
            "parent_subject_ids": list(self.parent_subject_ids),
            "producer_id": self.producer_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceBinding":
        result = cls(
            binding_id=str(data.get("binding_id") or ""),
            subject_id=str(data.get("subject_id") or ""),
            source_ref_ids=_string_tuple(data.get("source_ref_ids")),
            span_ids=_string_tuple(data.get("span_ids")),
            evidence_ref_ids=_string_tuple(data.get("evidence_ref_ids")),
            producer_id=str(data.get("producer_id") or ""),
            config_id=str(data.get("config_id") or ""),
            parent_subject_ids=_string_tuple(data.get("parent_subject_ids")),
            derived=bool(data.get("derived", False)),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class Provenance:
    """Complete immutable provenance graph for one IR artifact."""

    provenance_id: str
    sources: tuple[SourceRef, ...]
    spans: tuple[SourceSpan, ...] = ()
    producers: tuple[ProducerBinding, ...] = ()
    configs: tuple[ConfigBinding, ...] = ()
    bindings: tuple[ProvenanceBinding, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_PROVENANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sources",
            tuple(
                item
                if isinstance(item, SourceRef)
                else SourceRef.from_dict(_as_mapping(item))
                for item in self.sources
            ),
        )
        object.__setattr__(
            self,
            "spans",
            tuple(
                item
                if isinstance(item, SourceSpan)
                else SourceSpan.from_dict(_as_mapping(item))
                for item in self.spans
            ),
        )
        object.__setattr__(
            self,
            "producers",
            tuple(
                item
                if isinstance(item, ProducerBinding)
                else ProducerBinding.from_dict(_as_mapping(item))
                for item in self.producers
            ),
        )
        object.__setattr__(
            self,
            "configs",
            tuple(
                item
                if isinstance(item, ConfigBinding)
                else ConfigBinding.from_dict(_as_mapping(item))
                for item in self.configs
            ),
        )
        object.__setattr__(
            self,
            "bindings",
            tuple(
                item
                if isinstance(item, ProvenanceBinding)
                else ProvenanceBinding.from_dict(_as_mapping(item))
                for item in self.bindings
            ),
        )
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def validate(self, *, evidence_ref_ids: Sequence[str] | None = None) -> None:
        validate_provenance(self, evidence_ref_ids=evidence_ref_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings": [
                item.to_dict()
                for item in sorted(self.bindings, key=lambda item: item.binding_id)
            ],
            "configs": [
                item.to_dict()
                for item in sorted(self.configs, key=lambda item: item.config_id)
            ],
            "metadata": thaw_json(self.metadata),
            "producers": [
                item.to_dict()
                for item in sorted(
                    self.producers, key=lambda item: item.producer_id
                )
            ],
            "provenance_id": self.provenance_id,
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict()
                for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "spans": [
                item.to_dict()
                for item in sorted(self.spans, key=lambda item: item.span_id)
            ],
        }

    def canonical_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Provenance":
        result = cls(
            provenance_id=str(data.get("provenance_id") or ""),
            sources=tuple(
                SourceRef.from_dict(_as_mapping(item))
                for item in _as_sequence(data.get("sources"))
            ),
            spans=tuple(
                SourceSpan.from_dict(_as_mapping(item))
                for item in _as_sequence(data.get("spans"))
            ),
            producers=tuple(
                ProducerBinding.from_dict(_as_mapping(item))
                for item in _as_sequence(data.get("producers"))
            ),
            configs=tuple(
                ConfigBinding.from_dict(_as_mapping(item))
                for item in _as_sequence(data.get("configs"))
            ),
            bindings=tuple(
                ProvenanceBinding.from_dict(_as_mapping(item))
                for item in _as_sequence(data.get("bindings"))
            ),
            metadata=_as_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or IR_PROVENANCE_SCHEMA_VERSION
            ),
        )
        result.validate()
        return result

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "Provenance":
        return cls.from_dict(_decode_json_object(value, "provenance"))


def validate_provenance(
    provenance: Provenance,
    *,
    evidence_ref_ids: Sequence[str] | None = None,
) -> Provenance:
    """Validate local structure and every provenance cross-reference."""

    if not isinstance(provenance, Provenance):
        raise ProvenanceValidationError("provenance must be a Provenance instance")
    if provenance.schema_version != IR_PROVENANCE_SCHEMA_VERSION:
        raise ProvenanceValidationError(
            f"Unsupported provenance schema_version {provenance.schema_version!r}"
        )
    _validate_id("Provenance.provenance_id", provenance.provenance_id)
    if not provenance.sources:
        raise ProvenanceValidationError("Provenance.sources must not be empty")

    source_ids = _validated_index(
        provenance.sources, "source", lambda item: item.ref_id
    )
    span_ids = _validated_index(provenance.spans, "span", lambda item: item.span_id)
    producer_ids = _validated_index(
        provenance.producers, "producer", lambda item: item.producer_id
    )
    config_ids = _validated_index(
        provenance.configs, "config", lambda item: item.config_id
    )
    _validated_index(
        provenance.bindings, "binding", lambda item: item.binding_id
    )
    subject_ids = _unique_ids(
        (item.subject_id for item in provenance.bindings),
        "provenance subject",
    )

    for span in provenance.spans:
        _require_known(
            (span.source_ref_id,),
            source_ids,
            f"SourceSpan {span.span_id!r}.source_ref_id",
        )
    known_evidence = set(evidence_ref_ids) if evidence_ref_ids is not None else None
    for binding in provenance.bindings:
        _require_known(
            binding.source_ref_ids,
            source_ids,
            f"ProvenanceBinding {binding.binding_id!r}.source_ref_ids",
        )
        _require_known(
            binding.span_ids,
            span_ids,
            f"ProvenanceBinding {binding.binding_id!r}.span_ids",
        )
        for span_id in binding.span_ids:
            span_source = next(
                item.source_ref_id for item in provenance.spans if item.span_id == span_id
            )
            if binding.source_ref_ids and span_source not in binding.source_ref_ids:
                raise ProvenanceValidationError(
                    f"ProvenanceBinding {binding.binding_id!r} span {span_id!r} "
                    f"belongs to unlisted source {span_source!r}"
                )
        if binding.producer_id:
            _require_known(
                (binding.producer_id,),
                producer_ids,
                f"ProvenanceBinding {binding.binding_id!r}.producer_id",
            )
        if binding.config_id:
            _require_known(
                (binding.config_id,),
                config_ids,
                f"ProvenanceBinding {binding.binding_id!r}.config_id",
            )
        if binding.config_id and not binding.producer_id:
            raise ProvenanceValidationError(
                f"ProvenanceBinding {binding.binding_id!r} has config without producer"
            )
        _require_known(
            binding.parent_subject_ids,
            subject_ids,
            f"ProvenanceBinding {binding.binding_id!r}.parent_subject_ids",
        )
        if binding.subject_id in binding.parent_subject_ids:
            raise ProvenanceValidationError(
                f"ProvenanceBinding {binding.binding_id!r} references itself as parent"
            )
        if known_evidence is not None:
            _require_known(
                binding.evidence_ref_ids,
                known_evidence,
                f"ProvenanceBinding {binding.binding_id!r}.evidence_ref_ids",
            )
    _reject_lineage_cycles(
        {
            item.subject_id: item.parent_subject_ids
            for item in provenance.bindings
        },
        "provenance subject",
    )
    return provenance


def canonical_provenance_bytes(provenance: Provenance) -> bytes:
    """Return canonical UTF-8 JSON after validation."""

    return provenance.canonical_bytes()


def canonical_provenance_json(provenance: Provenance) -> str:
    """Return canonical JSON text after validation."""

    return provenance.to_json()


def provenance_sha256(provenance: Provenance) -> str:
    """Return the lowercase SHA-256 hex digest of canonical provenance bytes."""

    return provenance.sha256


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value using the dependency-independent IR profile."""

    try:
        return json.dumps(
            thaw_json(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProvenanceValidationError(f"value is not canonical JSON: {exc}") from exc


def freeze_json_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Defensively copy and deeply freeze a string-keyed JSON mapping."""

    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ProvenanceValidationError("metadata must be a mapping")
    frozen = freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


def freeze_json(value: Any) -> Any:
    """Return an immutable defensive copy of a JSON-compatible value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProvenanceValidationError("non-finite numbers are not JSON")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProvenanceValidationError("JSON object keys must be strings")
            result[key] = freeze_json(item)
        return MappingProxyType(result)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(freeze_json(item) for item in value)
    raise ProvenanceValidationError(
        f"unsupported JSON value type {type(value).__name__}"
    )


def thaw_json(value: Any) -> Any:
    """Return ordinary dictionaries/lists suitable for JSON serialization."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _validated_index(
    records: Sequence[Any],
    kind: str,
    identifier: Any,
) -> set[str]:
    ids: set[str] = set()
    for record in records:
        record.validate()
        record_id = identifier(record)
        if record_id in ids:
            raise ProvenanceValidationError(f"duplicate {kind} id {record_id!r}")
        ids.add(record_id)
    return ids


def _require_known(values: Sequence[str], known: set[str], field_name: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise ProvenanceValidationError(
            f"{field_name} contains unknown ids: {missing}"
        )


def _unique_ids(values: Sequence[str] | Any, kind: str) -> set[str]:
    result: set[str] = set()
    for value in values:
        if value in result:
            raise ProvenanceValidationError(f"duplicate {kind} id {value!r}")
        result.add(value)
    return result


def _reject_lineage_cycles(
    parents_by_id: Mapping[str, Sequence[str]],
    kind: str,
) -> None:
    """Reject cycles in parent/derivation relationships deterministically."""

    visited: set[str] = set()
    active: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in active:
            raise ProvenanceValidationError(
                f"{kind} lineage contains a cycle at {identifier!r}"
            )
        if identifier in visited:
            return
        active.add(identifier)
        for parent_id in parents_by_id.get(identifier, ()):
            visit(parent_id)
        active.remove(identifier)
        visited.add(identifier)

    for identifier in sorted(parents_by_id):
        visit(identifier)


def _validate_id(name: str, value: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ProvenanceValidationError(f"{name} is not a stable identifier")


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceValidationError(f"{name} must not be empty")


def _validate_sha256(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProvenanceValidationError(
            f"{name} must be a normalized lowercase SHA-256 hex digest"
        )


def _validate_enum(name: str, value: Any, enum_type: type[Enum]) -> None:
    if not isinstance(value, enum_type):
        raise ProvenanceValidationError(
            f"{name} must be a {enum_type.__name__} member"
        )


def _validate_int(name: str, value: Any, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProvenanceValidationError(
            f"{name} must be an integer >= {minimum}"
        )


def _validate_half_open(name: str, start: Any, end: Any) -> None:
    _validate_int(f"{name} start", start, minimum=0)
    _validate_int(f"{name} end", end, minimum=0)
    if end < start:
        raise ProvenanceValidationError(f"{name} must satisfy start <= end")


def _validate_optional_pair(
    name: str,
    start: int | None,
    end: int | None,
    *,
    zero_based: bool,
) -> None:
    if start is None and end is None:
        return
    if start is None or end is None:
        raise ProvenanceValidationError(f"{name} offsets must be supplied together")
    _validate_half_open(name, start, end)


def _unique_tuple(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in tuple(values)}))


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _as_sequence(value))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProvenanceValidationError("expected a JSON object")
    return value


def _as_sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    raise ProvenanceValidationError("expected a JSON array")


def _required_int(data: Mapping[str, Any], key: str) -> int:
    if key not in data:
        raise ProvenanceValidationError(f"missing required field {key!r}")
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProvenanceValidationError(f"{key} must be an integer")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProvenanceValidationError("optional coordinate must be an integer")
    return value


def _enum_value(
    enum_type: type[Enum],
    value: Any,
    field_name: str,
) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ProvenanceValidationError(
            f"{field_name} has unsupported value {value!r}"
        ) from exc


def _decode_json_object(
    value: str | bytes | bytearray,
    label: str,
) -> Mapping[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ProvenanceValidationError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(decoded, Mapping):
        raise ProvenanceValidationError(f"{label} JSON must contain an object")
    return decoded


# Descriptive aliases retained for adapters that prefer expanded names.
SourceReference = SourceRef
ConfigurationBinding = ConfigBinding
IRProvenance = Provenance


__all__ = [
    "ConfigBinding",
    "ConfigurationBinding",
    "IRProvenance",
    "IR_PROVENANCE_SCHEMA_VERSION",
    "ProducerBinding",
    "Provenance",
    "ProvenanceBinding",
    "ProvenanceValidationError",
    "SourceRef",
    "SourceReference",
    "SourceReviewStatus",
    "SourceSpan",
    "canonical_provenance_bytes",
    "canonical_provenance_json",
    "provenance_sha256",
    "validate_provenance",
]
