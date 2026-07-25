"""Domain-neutral immutable provenance records for the shared IR kernel.

The records in this module identify source bytes and transformations without
embedding source bodies.  Collections are defensively copied, normalized, and
frozen at construction time so a caller cannot mutate an already validated IR
artifact through an alias.
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

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_REVISIONS = frozenset(
    {
        "head",
        "latest",
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
    }
)


class ProvenanceValidationError(ValueError):
    """Raised when provenance is malformed or contains invalid references."""


class ReviewStatus(str, Enum):
    """Review state carried by a source reference; it does not imply proof."""

    UNREVIEWED = "unreviewed"
    MACHINE_EXTRACTED = "machine_extracted"
    MACHINE_REVIEWED = "machine_reviewed"
    HUMAN_REVIEWED = "human_reviewed"
    TRUSTED_FIXTURE = "trusted_fixture"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class SpanUnit(str, Enum):
    """Unit used by the inclusive-exclusive offsets in :class:`SourceSpan`."""

    BYTE = "byte"
    CHARACTER = "character"
    TOKEN = "token"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Immutable reference to separately stored source content."""

    reference_id: str
    source_uri: str
    source_id: str
    revision: str
    content_sha256: str
    content_cid: str = ""
    bundle_sha256: str = ""
    bundle_uri: str = ""
    byte_length: int | None = None
    media_type: str = "application/octet-stream"
    license_expression: str = ""
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("SourceReference.reference_id", self.reference_id)
        _require_text("SourceReference.source_uri", self.source_uri)
        _require_text("SourceReference.source_id", self.source_id)
        _require_text("SourceReference.revision", self.revision)
        if self.revision.strip().lower() in _MUTABLE_REVISIONS:
            raise ProvenanceValidationError(
                "SourceReference.revision must be immutable, not a moving ref"
            )
        _require_sha256("SourceReference.content_sha256", self.content_sha256)
        if self.bundle_sha256:
            _require_sha256("SourceReference.bundle_sha256", self.bundle_sha256)
        if self.byte_length is not None:
            _require_nonnegative_int(
                "SourceReference.byte_length", self.byte_length
            )
        _require_text("SourceReference.media_type", self.media_type)
        object.__setattr__(self, "review_status", _enum_value(ReviewStatus, self.review_status))
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_sha256": self.bundle_sha256,
            "bundle_uri": self.bundle_uri,
            "byte_length": self.byte_length,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "license_expression": self.license_expression,
            "metadata": thaw_json(self.metadata),
            "media_type": self.media_type,
            "reference_id": self.reference_id,
            "review_status": self.review_status.value,
            "revision": self.revision,
            "source_id": self.source_id,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceReference":
        return cls(
            reference_id=str(data.get("reference_id") or data.get("ref_id") or ""),
            source_uri=str(data.get("source_uri") or ""),
            source_id=str(data.get("source_id") or data.get("source_native_id") or ""),
            revision=str(data.get("revision") or data.get("source_revision") or ""),
            content_sha256=str(data.get("content_sha256") or ""),
            content_cid=str(data.get("content_cid") or ""),
            bundle_sha256=str(
                data.get("bundle_sha256") or data.get("container_sha256") or ""
            ),
            bundle_uri=str(data.get("bundle_uri") or data.get("container_uri") or ""),
            byte_length=_optional_integer(data.get("byte_length")),
            media_type=str(data.get("media_type") or "application/octet-stream"),
            license_expression=str(data.get("license_expression") or ""),
            review_status=data.get("review_status") or ReviewStatus.UNREVIEWED,
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open offset range within one source reference."""

    span_id: str
    source_reference_id: str
    start: int
    end: int
    unit: SpanUnit = SpanUnit.BYTE
    start_line: int | None = None
    start_column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("SourceSpan.span_id", self.span_id)
        _require_identifier(
            "SourceSpan.source_reference_id", self.source_reference_id
        )
        _require_nonnegative_int("SourceSpan.start", self.start)
        _require_nonnegative_int("SourceSpan.end", self.end)
        if self.end < self.start:
            raise ProvenanceValidationError(
                "SourceSpan must satisfy 0 <= start <= end"
            )
        object.__setattr__(self, "unit", _enum_value(SpanUnit, self.unit))
        positions = (
            self.start_line,
            self.start_column,
            self.end_line,
            self.end_column,
        )
        if any(value is not None for value in positions):
            if any(value is None for value in positions):
                raise ProvenanceValidationError(
                    "SourceSpan line/column positions must be supplied together"
                )
            for name, value in zip(
                ("start_line", "start_column", "end_line", "end_column"),
                positions,
                strict=True,
            ):
                _require_nonnegative_int(f"SourceSpan.{name}", value)
            if (self.end_line, self.end_column) < (
                self.start_line,
                self.start_column,
            ):
                raise ProvenanceValidationError(
                    "SourceSpan line/column end precedes its start"
                )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "end": self.end,
            "end_column": self.end_column,
            "end_line": self.end_line,
            "metadata": thaw_json(self.metadata),
            "source_reference_id": self.source_reference_id,
            "span_id": self.span_id,
            "start": self.start,
            "start_column": self.start_column,
            "start_line": self.start_line,
            "unit": self.unit.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSpan":
        return cls(
            span_id=str(data.get("span_id") or ""),
            source_reference_id=str(
                data.get("source_reference_id") or data.get("source_ref_id") or ""
            ),
            start=_integer(data.get("start", data.get("start_offset", 0))),
            end=_integer(data.get("end", data.get("end_offset", 0))),
            unit=data.get("unit") or SpanUnit.BYTE,
            start_line=_optional_integer(data.get("start_line")),
            start_column=_optional_integer(data.get("start_column")),
            end_line=_optional_integer(data.get("end_line")),
            end_column=_optional_integer(data.get("end_column")),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class ProducerBinding:
    """Identity of a tool, model, or human process that produced an artifact."""

    producer_id: str
    name: str
    version: str
    executable_sha256: str = ""
    repository_revision: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("ProducerBinding.producer_id", self.producer_id)
        _require_text("ProducerBinding.name", self.name)
        _require_text("ProducerBinding.version", self.version)
        if self.executable_sha256:
            _require_sha256(
                "ProducerBinding.executable_sha256", self.executable_sha256
            )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable_sha256": self.executable_sha256,
            "metadata": thaw_json(self.metadata),
            "name": self.name,
            "producer_id": self.producer_id,
            "repository_revision": self.repository_revision,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProducerBinding":
        return cls(
            producer_id=str(data.get("producer_id") or ""),
            name=str(data.get("name") or ""),
            version=str(data.get("version") or ""),
            executable_sha256=str(data.get("executable_sha256") or ""),
            repository_revision=str(data.get("repository_revision") or ""),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class ConfigurationBinding:
    """Content binding for producer configuration without storing secrets."""

    configuration_id: str
    content_sha256: str
    schema_id: str = ""
    profile: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(
            "ConfigurationBinding.configuration_id", self.configuration_id
        )
        _require_sha256(
            "ConfigurationBinding.content_sha256", self.content_sha256
        )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "content_sha256": self.content_sha256,
            "metadata": thaw_json(self.metadata),
            "profile": self.profile,
            "schema_id": self.schema_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConfigurationBinding":
        return cls(
            configuration_id=str(
                data.get("configuration_id") or data.get("config_id") or ""
            ),
            content_sha256=str(data.get("content_sha256") or ""),
            schema_id=str(data.get("schema_id") or ""),
            profile=str(data.get("profile") or ""),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceBinding:
    """Source and transformation lineage for one semantic subject."""

    subject_id: str
    source_reference_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    parent_subject_ids: tuple[str, ...] = ()
    producer_id: str = ""
    configuration_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("ProvenanceBinding.subject_id", self.subject_id)
        for name in (
            "source_reference_ids",
            "source_span_ids",
            "parent_subject_ids",
        ):
            values = _identifier_tuple(
                f"ProvenanceBinding.{name}", getattr(self, name)
            )
            object.__setattr__(self, name, values)
        if not (
            self.source_reference_ids
            or self.source_span_ids
            or self.parent_subject_ids
        ):
            raise ProvenanceValidationError(
                "ProvenanceBinding requires a source, span, or parent subject"
            )
        if self.subject_id in self.parent_subject_ids:
            raise ProvenanceValidationError(
                "ProvenanceBinding cannot derive a subject from itself"
            )
        if self.producer_id:
            _require_identifier("ProvenanceBinding.producer_id", self.producer_id)
        if self.configuration_id:
            _require_identifier(
                "ProvenanceBinding.configuration_id", self.configuration_id
            )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def derived(self) -> bool:
        return bool(self.parent_subject_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "derived": self.derived,
            "metadata": thaw_json(self.metadata),
            "parent_subject_ids": list(self.parent_subject_ids),
            "producer_id": self.producer_id,
            "source_reference_ids": list(self.source_reference_ids),
            "source_span_ids": list(self.source_span_ids),
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceBinding":
        return cls(
            subject_id=str(data.get("subject_id") or data.get("node_id") or ""),
            source_reference_ids=_strings(data.get("source_reference_ids")),
            source_span_ids=_strings(
                data.get("source_span_ids", data.get("span_ids"))
            ),
            parent_subject_ids=_strings(
                data.get("parent_subject_ids", data.get("derived_from_ids"))
            ),
            producer_id=str(data.get("producer_id") or ""),
            configuration_id=str(
                data.get("configuration_id") or data.get("config_id") or ""
            ),
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class CrossReferenceIssue:
    """One stable, machine-readable validation finding."""

    code: str
    message: str
    field_path: str
    reference_id: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "reference_id": self.reference_id,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class CrossReferenceValidation:
    """Deterministic result of validating references between immutable records."""

    issues: tuple[CrossReferenceIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.to_dict() for issue in self.issues],
            "valid": self.valid,
        }

    def raise_for_errors(self) -> None:
        if not self.valid:
            summary = "; ".join(
                f"{issue.code} at {issue.field_path}: {issue.message}"
                for issue in self.issues
                if issue.severity == "error"
            )
            raise ProvenanceValidationError(summary)


@dataclass(frozen=True, slots=True)
class ProvenanceBundle:
    """Canonical registry of sources, spans, producers, and subject bindings."""

    sources: tuple[SourceReference, ...] = ()
    spans: tuple[SourceSpan, ...] = ()
    producers: tuple[ProducerBinding, ...] = ()
    configurations: tuple[ConfigurationBinding, ...] = ()
    bindings: tuple[ProvenanceBinding, ...] = ()
    bundle_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_PROVENANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sources",
            _records(self.sources, SourceReference, "reference_id"),
        )
        object.__setattr__(
            self, "spans", _records(self.spans, SourceSpan, "span_id")
        )
        object.__setattr__(
            self,
            "producers",
            _records(self.producers, ProducerBinding, "producer_id"),
        )
        object.__setattr__(
            self,
            "configurations",
            _records(
                self.configurations, ConfigurationBinding, "configuration_id"
            ),
        )
        object.__setattr__(
            self,
            "bindings",
            _records(self.bindings, ProvenanceBinding, "subject_id"),
        )
        if self.bundle_id:
            _require_identifier("ProvenanceBundle.bundle_id", self.bundle_id)
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def source_by_id(self) -> Mapping[str, SourceReference]:
        return MappingProxyType(
            {item.reference_id: item for item in self.sources}
        )

    @property
    def span_by_id(self) -> Mapping[str, SourceSpan]:
        return MappingProxyType({item.span_id: item for item in self.spans})

    @property
    def producer_by_id(self) -> Mapping[str, ProducerBinding]:
        return MappingProxyType(
            {item.producer_id: item for item in self.producers}
        )

    @property
    def configuration_by_id(self) -> Mapping[str, ConfigurationBinding]:
        return MappingProxyType(
            {item.configuration_id: item for item in self.configurations}
        )

    @property
    def binding_by_subject_id(self) -> Mapping[str, ProvenanceBinding]:
        return MappingProxyType(
            {item.subject_id: item for item in self.bindings}
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def validate_cross_references(self) -> CrossReferenceValidation:
        return validate_cross_references(self)

    def assert_valid(self) -> None:
        self.validate_cross_references().raise_for_errors()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings": [item.to_dict() for item in self.bindings],
            "bundle_id": self.bundle_id,
            "configurations": [
                item.to_dict() for item in self.configurations
            ],
            "metadata": thaw_json(self.metadata),
            "producers": [item.to_dict() for item in self.producers],
            "schema_version": self.schema_version,
            "sources": [item.to_dict() for item in self.sources],
            "spans": [item.to_dict() for item in self.spans],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceBundle":
        return cls(
            sources=tuple(
                SourceReference.from_dict(_mapping(item))
                for item in _sequence(data.get("sources"))
            ),
            spans=tuple(
                SourceSpan.from_dict(_mapping(item))
                for item in _sequence(data.get("spans"))
            ),
            producers=tuple(
                ProducerBinding.from_dict(_mapping(item))
                for item in _sequence(data.get("producers"))
            ),
            configurations=tuple(
                ConfigurationBinding.from_dict(_mapping(item))
                for item in _sequence(data.get("configurations"))
            ),
            bindings=tuple(
                ProvenanceBinding.from_dict(_mapping(item))
                for item in _sequence(data.get("bindings"))
            ),
            bundle_id=str(data.get("bundle_id") or ""),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or IR_PROVENANCE_SCHEMA_VERSION
            ),
        )


def validate_cross_references(
    provenance: ProvenanceBundle | Mapping[str, Any],
) -> CrossReferenceValidation:
    """Validate all provenance identifiers, including derived-node cycles."""

    bundle = (
        provenance
        if isinstance(provenance, ProvenanceBundle)
        else ProvenanceBundle.from_dict(provenance)
    )
    issues: list[CrossReferenceIssue] = []
    source_ids = _ids_with_duplicate_issues(
        bundle.sources, "reference_id", "sources", issues
    )
    source_by_id = {item.reference_id: item for item in bundle.sources}
    span_ids = _ids_with_duplicate_issues(
        bundle.spans, "span_id", "spans", issues
    )
    producer_ids = _ids_with_duplicate_issues(
        bundle.producers, "producer_id", "producers", issues
    )
    configuration_ids = _ids_with_duplicate_issues(
        bundle.configurations,
        "configuration_id",
        "configurations",
        issues,
    )
    subject_ids = _ids_with_duplicate_issues(
        bundle.bindings, "subject_id", "bindings", issues
    )

    span_sources: dict[str, str] = {}
    for index, span in enumerate(bundle.spans):
        span_sources[span.span_id] = span.source_reference_id
        _check_reference(
            span.source_reference_id,
            source_ids,
            "ir.provenance.source_reference.missing",
            f"spans.{index}.source_reference_id",
            issues,
        )
        source = source_by_id.get(span.source_reference_id)
        if (
            source is not None
            and source.byte_length is not None
            and span.unit is SpanUnit.BYTE
            and span.end > source.byte_length
        ):
            issues.append(
                CrossReferenceIssue(
                    code="ir.provenance.span.out_of_bounds",
                    message=(
                        f"byte span ends at {span.end}, beyond source length "
                        f"{source.byte_length}"
                    ),
                    field_path=f"spans.{index}.end",
                    reference_id=span.span_id,
                )
            )

    graph: dict[str, tuple[str, ...]] = {}
    for index, binding in enumerate(bundle.bindings):
        graph[binding.subject_id] = tuple(
            sorted(
                set(graph.get(binding.subject_id, ()))
                | set(binding.parent_subject_ids)
            )
        )
        for offset, source_id in enumerate(binding.source_reference_ids):
            _check_reference(
                source_id,
                source_ids,
                "ir.provenance.source_reference.missing",
                f"bindings.{index}.source_reference_ids.{offset}",
                issues,
            )
        for offset, span_id in enumerate(binding.source_span_ids):
            _check_reference(
                span_id,
                span_ids,
                "ir.provenance.span.missing",
                f"bindings.{index}.source_span_ids.{offset}",
                issues,
            )
            span_source = span_sources.get(span_id)
            if span_source and span_source not in binding.source_reference_ids:
                issues.append(
                    CrossReferenceIssue(
                        code="ir.provenance.span.source_unbound",
                        message=(
                            f"span {span_id!r} belongs to source "
                            f"{span_source!r}, which is not bound to the subject"
                        ),
                        field_path=f"bindings.{index}.source_span_ids.{offset}",
                        reference_id=span_id,
                    )
                )
        for offset, parent_id in enumerate(binding.parent_subject_ids):
            _check_reference(
                parent_id,
                subject_ids,
                "ir.provenance.parent_subject.missing",
                f"bindings.{index}.parent_subject_ids.{offset}",
                issues,
            )
        if binding.producer_id:
            _check_reference(
                binding.producer_id,
                producer_ids,
                "ir.provenance.producer.missing",
                f"bindings.{index}.producer_id",
                issues,
            )
        if binding.configuration_id:
            _check_reference(
                binding.configuration_id,
                configuration_ids,
                "ir.provenance.configuration.missing",
                f"bindings.{index}.configuration_id",
                issues,
            )

    for cycle in _cycles(graph):
        issues.append(
            CrossReferenceIssue(
                code="ir.provenance.parent_subject.cycle",
                message="derived provenance contains a cycle: " + " -> ".join(cycle),
                field_path="bindings",
                reference_id=cycle[0],
            )
        )
    return CrossReferenceValidation(tuple(_sorted_issues(issues)))


def canonical_json_bytes(value: Any) -> bytes:
    """Return dependency-independent canonical UTF-8 JSON bytes."""

    return json.dumps(
        thaw_json(freeze_json(value)),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Hash a canonical JSON value with SHA-256."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def freeze_json(value: Any) -> Any:
    """Defensively copy a JSON value into deeply immutable containers."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProvenanceValidationError("JSON numbers must be finite")
        return value
    if isinstance(value, Enum):
        return freeze_json(value.value)
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProvenanceValidationError("JSON object keys must be strings")
            frozen[key] = freeze_json(item)
        return MappingProxyType(dict(sorted(frozen.items())))
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise ProvenanceValidationError(
        f"value of type {type(value).__name__} is not JSON serializable"
    )


def thaw_json(value: Any) -> Any:
    """Return mutable JSON-compatible containers for serialization."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _records(
    values: Sequence[Any],
    cls: type[Any],
    id_attribute: str,
) -> tuple[Any, ...]:
    converted = tuple(
        item if isinstance(item, cls) else cls.from_dict(_mapping(item))
        for item in values
    )
    return tuple(sorted(converted, key=lambda item: getattr(item, id_attribute)))


def _ids_with_duplicate_issues(
    values: Sequence[Any],
    id_attribute: str,
    field_name: str,
    issues: list[CrossReferenceIssue],
) -> set[str]:
    found: set[str] = set()
    for index, item in enumerate(values):
        identifier = getattr(item, id_attribute)
        if identifier in found:
            issues.append(
                CrossReferenceIssue(
                    code="ir.reference.duplicate",
                    message=f"duplicate identifier {identifier!r}",
                    field_path=f"{field_name}.{index}.{id_attribute}",
                    reference_id=identifier,
                )
            )
        found.add(identifier)
    return found


def _check_reference(
    identifier: str,
    known: set[str],
    code: str,
    field_path: str,
    issues: list[CrossReferenceIssue],
) -> None:
    if identifier not in known:
        issues.append(
            CrossReferenceIssue(
                code=code,
                message=f"reference {identifier!r} does not exist",
                field_path=field_path,
                reference_id=identifier,
            )
        )


def _cycles(graph: Mapping[str, tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    cycles: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    active: set[str] = set()
    complete: set[str] = set()

    def visit(node: str) -> None:
        if node in complete:
            return
        if node in active:
            start = visiting.index(node)
            cycle = tuple(visiting[start:] + [node])
            rotations = [
                cycle[index:-1] + cycle[:index] + (cycle[index],)
                for index in range(len(cycle) - 1)
            ]
            cycles.add(min(rotations))
            return
        active.add(node)
        visiting.append(node)
        for parent in graph.get(node, ()):
            if parent in graph:
                visit(parent)
        visiting.pop()
        active.remove(node)
        complete.add(node)

    for node in sorted(graph):
        visit(node)
    return tuple(sorted(cycles))


def _sorted_issues(
    issues: Sequence[CrossReferenceIssue],
) -> tuple[CrossReferenceIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                issue.field_path,
                issue.code,
                issue.reference_id,
                issue.message,
            ),
        )
    )


def _require_identifier(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ProvenanceValidationError(f"{name} must be a stable identifier")


def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceValidationError(f"{name} must not be empty")


def _require_sha256(name: str, value: Any) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProvenanceValidationError(
            f"{name} must be a lowercase 64-character SHA-256 digest"
        )


def _require_nonnegative_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProvenanceValidationError(f"{name} must be a non-negative integer")


def _enum_value(enum_type: type[Enum], value: Any) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ProvenanceValidationError(
            f"{enum_type.__name__} must be one of: {allowed}"
        ) from exc


def _identifier_tuple(name: str, values: Sequence[Any] | None) -> tuple[str, ...]:
    result = tuple(sorted(set(_strings(values))))
    for value in result:
        _require_identifier(name, value)
    return result


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    raise ProvenanceValidationError("identifier collection must be a sequence")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    return ()


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ProvenanceValidationError("boolean is not an integer offset")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ProvenanceValidationError("offset must be an integer") from exc


def _optional_integer(value: Any) -> int | None:
    return None if value is None else _integer(value)


# Descriptive aliases retained for consumers that call the registry a source map.
ProvenanceMap = ProvenanceBundle
ProvenanceGraph = ProvenanceBundle
ProvenanceRecord = ProvenanceBinding
ProvenanceIssue = CrossReferenceIssue
ProvenanceValidationResult = CrossReferenceValidation
validate_provenance = validate_cross_references
