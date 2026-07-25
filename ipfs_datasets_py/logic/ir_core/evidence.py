"""Immutable references to evidence carried outside shared IR declarations.

Evidence records bind content and lineage only.  Their presence does not grant
proof, monitoring, or policy authority; those meanings belong to typed result
records in higher layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from .provenance import (
    CrossReferenceIssue,
    CrossReferenceValidation,
    ProvenanceBundle,
    ProvenanceValidationError,
    ReviewStatus,
    canonical_json_bytes,
    canonical_sha256,
    freeze_json,
    thaw_json,
)


IR_EVIDENCE_SCHEMA_VERSION: Final = "ir-evidence/v1"


class EvidenceValidationError(ProvenanceValidationError):
    """Raised when evidence is malformed or cross-reference validation fails."""


class EvidenceKind(str, Enum):
    """Domain-neutral evidence categories; none implies theorem authority."""

    SOURCE = "source"
    DATASET = "dataset"
    ARTIFACT = "artifact"
    OBSERVATION = "observation"
    RECEIPT = "receipt"
    PROOF = "proof"
    REPORT = "report"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Content-addressed pointer to separately stored evidence."""

    evidence_id: str
    kind: EvidenceKind | str
    content_sha256: str
    uri: str = ""
    content_cid: str = ""
    media_type: str = "application/octet-stream"
    schema_id: str = ""
    description: str = ""
    source_reference_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    subject_ids: tuple[str, ...] = ()
    parent_evidence_ids: tuple[str, ...] = ()
    producer_id: str = ""
    configuration_id: str = ""
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier("EvidenceReference.evidence_id", self.evidence_id)
        kind = self.kind.value if isinstance(self.kind, EvidenceKind) else str(self.kind)
        _require_identifier("EvidenceReference.kind", kind)
        object.__setattr__(
            self,
            "kind",
            EvidenceKind(kind) if kind in EvidenceKind._value2member_map_ else kind,
        )
        _require_sha256("EvidenceReference.content_sha256", self.content_sha256)
        if not self.uri and not self.content_cid:
            raise EvidenceValidationError(
                "EvidenceReference requires uri or content_cid"
            )
        _require_text("EvidenceReference.media_type", self.media_type)
        for name in (
            "source_reference_ids",
            "source_span_ids",
            "subject_ids",
            "parent_evidence_ids",
        ):
            object.__setattr__(
                self,
                name,
                _identifier_tuple(
                    f"EvidenceReference.{name}", getattr(self, name)
                ),
            )
        if self.evidence_id in self.parent_evidence_ids:
            raise EvidenceValidationError(
                "EvidenceReference cannot be its own parent"
            )
        if self.producer_id:
            _require_identifier("EvidenceReference.producer_id", self.producer_id)
        if self.configuration_id:
            _require_identifier(
                "EvidenceReference.configuration_id", self.configuration_id
            )
        object.__setattr__(
            self, "review_status", _review_status(self.review_status)
        )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def kind_value(self) -> str:
        return self.kind.value if isinstance(self.kind, EvidenceKind) else self.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "description": self.description,
            "evidence_id": self.evidence_id,
            "kind": self.kind_value,
            "media_type": self.media_type,
            "metadata": thaw_json(self.metadata),
            "parent_evidence_ids": list(self.parent_evidence_ids),
            "producer_id": self.producer_id,
            "review_status": self.review_status.value,
            "schema_id": self.schema_id,
            "source_reference_ids": list(self.source_reference_ids),
            "source_span_ids": list(self.source_span_ids),
            "subject_ids": list(self.subject_ids),
            "uri": self.uri,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceReference":
        return cls(
            evidence_id=str(data.get("evidence_id") or ""),
            kind=str(data.get("kind") or ""),
            content_sha256=str(data.get("content_sha256") or ""),
            uri=str(data.get("uri") or data.get("artifact_uri") or ""),
            content_cid=str(data.get("content_cid") or ""),
            media_type=str(data.get("media_type") or "application/octet-stream"),
            schema_id=str(data.get("schema_id") or ""),
            description=str(data.get("description") or ""),
            source_reference_ids=_strings(data.get("source_reference_ids")),
            source_span_ids=_strings(
                data.get("source_span_ids", data.get("span_ids"))
            ),
            subject_ids=_strings(data.get("subject_ids")),
            parent_evidence_ids=_strings(data.get("parent_evidence_ids")),
            producer_id=str(data.get("producer_id") or ""),
            configuration_id=str(
                data.get("configuration_id") or data.get("config_id") or ""
            ),
            review_status=data.get("review_status") or ReviewStatus.UNREVIEWED,
            metadata=_mapping(data.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class EvidenceCollection:
    """Canonical set-like collection of evidence references."""

    evidence: tuple[EvidenceReference, ...] = ()
    collection_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        converted = tuple(
            item
            if isinstance(item, EvidenceReference)
            else EvidenceReference.from_dict(_mapping(item))
            for item in self.evidence
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(converted, key=lambda item: item.evidence_id)),
        )
        if self.collection_id:
            _require_identifier(
                "EvidenceCollection.collection_id", self.collection_id
            )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def evidence_by_id(self) -> Mapping[str, EvidenceReference]:
        return MappingProxyType(
            {item.evidence_id: item for item in self.evidence}
        )

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def validate_cross_references(
        self, provenance: ProvenanceBundle | Mapping[str, Any] | None = None
    ) -> CrossReferenceValidation:
        return validate_cross_references(self, provenance)

    def assert_valid(
        self, provenance: ProvenanceBundle | Mapping[str, Any] | None = None
    ) -> None:
        result = self.validate_cross_references(provenance)
        if not result.valid:
            summary = "; ".join(
                f"{item.code} at {item.field_path}: {item.message}"
                for item in result.issues
                if item.severity == "error"
            )
            raise EvidenceValidationError(summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": thaw_json(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceCollection":
        return cls(
            evidence=tuple(
                EvidenceReference.from_dict(_mapping(item))
                for item in _sequence(
                    data.get("evidence", data.get("references"))
                )
            ),
            collection_id=str(data.get("collection_id") or ""),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or IR_EVIDENCE_SCHEMA_VERSION
            ),
        )


def validate_cross_references(
    evidence: EvidenceCollection | Mapping[str, Any],
    provenance: ProvenanceBundle | Mapping[str, Any] | None = None,
) -> CrossReferenceValidation:
    """Validate evidence lineage and optional links to a provenance bundle."""

    collection = (
        evidence
        if isinstance(evidence, EvidenceCollection)
        else EvidenceCollection.from_dict(evidence)
    )
    provenance_bundle = (
        provenance
        if isinstance(provenance, ProvenanceBundle)
        else ProvenanceBundle.from_dict(provenance)
        if provenance is not None
        else None
    )
    issues: list[CrossReferenceIssue] = []
    evidence_ids: set[str] = set()
    for index, item in enumerate(collection.evidence):
        if item.evidence_id in evidence_ids:
            issues.append(
                _issue(
                    "ir.reference.duplicate",
                    f"duplicate identifier {item.evidence_id!r}",
                    f"evidence.{index}.evidence_id",
                    item.evidence_id,
                )
            )
        evidence_ids.add(item.evidence_id)

    graph: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(collection.evidence):
        graph[item.evidence_id] = item.parent_evidence_ids
        for offset, parent_id in enumerate(item.parent_evidence_ids):
            _check_reference(
                parent_id,
                evidence_ids,
                "ir.evidence.parent.missing",
                f"evidence.{index}.parent_evidence_ids.{offset}",
                issues,
            )

    if provenance_bundle is not None:
        source_ids = {item.reference_id for item in provenance_bundle.sources}
        spans = {item.span_id: item for item in provenance_bundle.spans}
        producer_ids = {
            item.producer_id for item in provenance_bundle.producers
        }
        configuration_ids = {
            item.configuration_id for item in provenance_bundle.configurations
        }
        subject_ids = {
            item.subject_id for item in provenance_bundle.bindings
        }
        for index, item in enumerate(collection.evidence):
            for offset, reference_id in enumerate(item.source_reference_ids):
                _check_reference(
                    reference_id,
                    source_ids,
                    "ir.evidence.source_reference.missing",
                    f"evidence.{index}.source_reference_ids.{offset}",
                    issues,
                )
            for offset, span_id in enumerate(item.source_span_ids):
                _check_reference(
                    span_id,
                    set(spans),
                    "ir.evidence.span.missing",
                    f"evidence.{index}.source_span_ids.{offset}",
                    issues,
                )
                span = spans.get(span_id)
                if (
                    span is not None
                    and span.source_reference_id not in item.source_reference_ids
                ):
                    issues.append(
                        _issue(
                            "ir.evidence.span.source_unbound",
                            (
                                f"span {span_id!r} belongs to source "
                                f"{span.source_reference_id!r}, which is not "
                                "bound to the evidence"
                            ),
                            f"evidence.{index}.source_span_ids.{offset}",
                            span_id,
                        )
                    )
            for offset, subject_id in enumerate(item.subject_ids):
                _check_reference(
                    subject_id,
                    subject_ids,
                    "ir.evidence.subject.missing",
                    f"evidence.{index}.subject_ids.{offset}",
                    issues,
                )
            if item.producer_id:
                _check_reference(
                    item.producer_id,
                    producer_ids,
                    "ir.evidence.producer.missing",
                    f"evidence.{index}.producer_id",
                    issues,
                )
            if item.configuration_id:
                _check_reference(
                    item.configuration_id,
                    configuration_ids,
                    "ir.evidence.configuration.missing",
                    f"evidence.{index}.configuration_id",
                    issues,
                )

    for cycle in _cycles(graph):
        issues.append(
            _issue(
                "ir.evidence.parent.cycle",
                "evidence lineage contains a cycle: " + " -> ".join(cycle),
                "evidence",
                cycle[0],
            )
        )
    return CrossReferenceValidation(tuple(_sorted_issues(issues)))


def _cycles(graph: Mapping[str, tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    found: set[tuple[str, ...]] = set()
    path: list[str] = []
    active: set[str] = set()
    complete: set[str] = set()

    def visit(node: str) -> None:
        if node in complete:
            return
        if node in active:
            start = path.index(node)
            cycle = tuple(path[start:] + [node])
            rotations = [
                cycle[index:-1] + cycle[:index] + (cycle[index],)
                for index in range(len(cycle) - 1)
            ]
            found.add(min(rotations))
            return
        active.add(node)
        path.append(node)
        for parent in graph.get(node, ()):
            if parent in graph:
                visit(parent)
        path.pop()
        active.remove(node)
        complete.add(node)

    for node in sorted(graph):
        visit(node)
    return tuple(sorted(found))


def _check_reference(
    identifier: str,
    known: set[str],
    code: str,
    field_path: str,
    issues: list[CrossReferenceIssue],
) -> None:
    if identifier not in known:
        issues.append(
            _issue(
                code,
                f"reference {identifier!r} does not exist",
                field_path,
                identifier,
            )
        )


def _issue(
    code: str, message: str, field_path: str, reference_id: str = ""
) -> CrossReferenceIssue:
    return CrossReferenceIssue(
        code=code,
        message=message,
        field_path=field_path,
        reference_id=reference_id,
    )


def _sorted_issues(
    issues: Sequence[CrossReferenceIssue],
) -> tuple[CrossReferenceIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                item.field_path,
                item.code,
                item.reference_id,
                item.message,
            ),
        )
    )


def _require_identifier(name: str, value: Any) -> None:
    # Keep the grammar aligned with provenance without importing private state.
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or not value[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:/@+-")
            for character in value
        )
    ):
        raise EvidenceValidationError(f"{name} must be a stable identifier")


def _require_sha256(name: str, value: Any) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvidenceValidationError(
            f"{name} must be a lowercase 64-character SHA-256 digest"
        )


def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{name} must not be empty")


def _identifier_tuple(name: str, value: Any) -> tuple[str, ...]:
    result = tuple(sorted(set(_strings(value))))
    for identifier in result:
        _require_identifier(name, identifier)
    return result


def _review_status(value: Any) -> ReviewStatus:
    if isinstance(value, ReviewStatus):
        return value
    try:
        return ReviewStatus(str(value))
    except ValueError as exc:
        raise EvidenceValidationError(
            f"invalid review status {value!r}"
        ) from exc


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    raise EvidenceValidationError("identifier collection must be a sequence")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    return ()


# Common terminology used by artifact-manifest consumers.
EvidenceRegistry = EvidenceCollection
EvidenceValidationResult = CrossReferenceValidation
validate_evidence = validate_cross_references
