"""Immutable evidence references for shared IR artifacts.

Evidence references bind exact external bytes and their lineage.  They do not
grant theorem, trust, execution, or policy authority; consumers must interpret
``kind`` and ``review_status`` under an explicit policy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .provenance import (
    Provenance,
    ProvenanceValidationError,
    _as_mapping,
    _as_sequence,
    _decode_json_object,
    _enum_value,
    _require_known,
    _reject_lineage_cycles,
    _string_tuple,
    _unique_tuple,
    _validate_id,
    _validate_sha256,
    canonical_json_bytes,
    freeze_json_mapping,
    thaw_json,
)


IR_EVIDENCE_SCHEMA_VERSION: Final = "ir-evidence/v1"


class EvidenceValidationError(ValueError):
    """Raised when an evidence registry or its references are invalid."""


class EvidenceKind(str, Enum):
    """Stable semantic categories; none implies proof authority by itself."""

    SOURCE = "source"
    ARTIFACT = "artifact"
    TEST_RESULT = "test_result"
    PROOF_RECEIPT = "proof_receipt"
    RUNTIME_OBSERVATION = "runtime_observation"
    REVIEW = "review"
    ATTESTATION = "attestation"
    MODEL_OUTPUT = "model_output"
    OTHER = "other"


class EvidenceReviewStatus(str, Enum):
    """Review lifecycle for addressed evidence."""

    UNREVIEWED = "unreviewed"
    MACHINE_CHECKED = "machine_checked"
    HUMAN_REVIEWED = "human_reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Reference to immutable evidence bytes stored outside the IR."""

    evidence_id: str
    kind: EvidenceKind
    content_sha256: str
    uri: str = ""
    content_cid: str = ""
    media_type: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    producer_id: str = ""
    config_id: str = ""
    parent_evidence_ids: tuple[str, ...] = ()
    review_status: EvidenceReviewStatus = EvidenceReviewStatus.UNREVIEWED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref_ids", _unique_tuple(self.source_ref_ids))
        object.__setattr__(self, "span_ids", _unique_tuple(self.span_ids))
        object.__setattr__(
            self, "parent_evidence_ids", _unique_tuple(self.parent_evidence_ids)
        )
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def content_digest(self) -> str:
        return f"sha256:{self.content_sha256}"

    def validate(self) -> None:
        try:
            _validate_id("EvidenceRef.evidence_id", self.evidence_id)
            _validate_sha256("EvidenceRef.content_sha256", self.content_sha256)
            if not isinstance(self.kind, EvidenceKind):
                raise ProvenanceValidationError(
                    "EvidenceRef.kind must be an EvidenceKind member"
                )
            if not isinstance(self.review_status, EvidenceReviewStatus):
                raise ProvenanceValidationError(
                    "EvidenceRef.review_status must be an EvidenceReviewStatus member"
                )
            for name, values in (
                ("source_ref_ids", self.source_ref_ids),
                ("span_ids", self.span_ids),
                ("parent_evidence_ids", self.parent_evidence_ids),
            ):
                for value in values:
                    _validate_id(f"EvidenceRef.{name}", value)
            if self.producer_id:
                _validate_id("EvidenceRef.producer_id", self.producer_id)
            if self.config_id:
                _validate_id("EvidenceRef.config_id", self.config_id)
            if self.config_id and not self.producer_id:
                raise ProvenanceValidationError(
                    "EvidenceRef config_id requires producer_id"
                )
        except ProvenanceValidationError as exc:
            raise EvidenceValidationError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "media_type": self.media_type,
            "metadata": thaw_json(self.metadata),
            "parent_evidence_ids": list(self.parent_evidence_ids),
            "producer_id": self.producer_id,
            "review_status": self.review_status.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "uri": self.uri,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceRef":
        try:
            kind = _enum_value(
                EvidenceKind, data.get("kind"), "EvidenceRef.kind"
            )
            status = _enum_value(
                EvidenceReviewStatus,
                data.get("review_status"),
                "EvidenceRef.review_status",
            )
        except ProvenanceValidationError as exc:
            raise EvidenceValidationError(str(exc)) from exc
        result = cls(
            evidence_id=str(data.get("evidence_id") or ""),
            kind=kind,
            content_sha256=str(data.get("content_sha256") or ""),
            uri=str(data.get("uri") or ""),
            content_cid=str(data.get("content_cid") or ""),
            media_type=str(data.get("media_type") or ""),
            source_ref_ids=_string_tuple(data.get("source_ref_ids")),
            span_ids=_string_tuple(data.get("span_ids")),
            producer_id=str(data.get("producer_id") or ""),
            config_id=str(data.get("config_id") or ""),
            parent_evidence_ids=_string_tuple(data.get("parent_evidence_ids")),
            review_status=status,
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class Evidence:
    """Deterministic registry of evidence references for one artifact."""

    evidence_set_id: str
    references: tuple[EvidenceRef, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "references",
            tuple(
                item
                if isinstance(item, EvidenceRef)
                else EvidenceRef.from_dict(_as_mapping(item))
                for item in self.references
            ),
        )
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def validate(self, *, provenance: Provenance | None = None) -> None:
        validate_evidence(self, provenance=provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_set_id": self.evidence_set_id,
            "metadata": thaw_json(self.metadata),
            "references": [
                item.to_dict()
                for item in sorted(
                    self.references, key=lambda item: item.evidence_id
                )
            ],
            "schema_version": self.schema_version,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "Evidence":
        try:
            result = cls(
                evidence_set_id=str(data.get("evidence_set_id") or ""),
                references=tuple(
                    EvidenceRef.from_dict(_as_mapping(item))
                    for item in _as_sequence(data.get("references"))
                ),
                metadata=_as_mapping(data.get("metadata")),
                schema_version=str(
                    data.get("schema_version") or IR_EVIDENCE_SCHEMA_VERSION
                ),
            )
        except ProvenanceValidationError as exc:
            raise EvidenceValidationError(str(exc)) from exc
        result.validate()
        return result

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "Evidence":
        try:
            data = _decode_json_object(value, "evidence")
        except ProvenanceValidationError as exc:
            raise EvidenceValidationError(str(exc)) from exc
        return cls.from_dict(data)


def validate_evidence(
    evidence: Evidence,
    *,
    provenance: Provenance | None = None,
) -> Evidence:
    """Validate evidence lineage and optional provenance cross-references."""

    if not isinstance(evidence, Evidence):
        raise EvidenceValidationError("evidence must be an Evidence instance")
    try:
        if evidence.schema_version != IR_EVIDENCE_SCHEMA_VERSION:
            raise ProvenanceValidationError(
                f"Unsupported evidence schema_version {evidence.schema_version!r}"
            )
        _validate_id("Evidence.evidence_set_id", evidence.evidence_set_id)
        ids: set[str] = set()
        for reference in evidence.references:
            reference.validate()
            if reference.evidence_id in ids:
                raise ProvenanceValidationError(
                    f"duplicate evidence id {reference.evidence_id!r}"
                )
            ids.add(reference.evidence_id)
        for reference in evidence.references:
            _require_known(
                reference.parent_evidence_ids,
                ids,
                f"EvidenceRef {reference.evidence_id!r}.parent_evidence_ids",
            )
            if reference.evidence_id in reference.parent_evidence_ids:
                raise ProvenanceValidationError(
                    f"EvidenceRef {reference.evidence_id!r} is its own parent"
                )
        _reject_lineage_cycles(
            {
                item.evidence_id: item.parent_evidence_ids
                for item in evidence.references
            },
            "evidence",
        )

        if provenance is not None:
            provenance.validate(evidence_ref_ids=tuple(ids))
            source_ids = {item.ref_id for item in provenance.sources}
            spans = {item.span_id: item for item in provenance.spans}
            producer_ids = {item.producer_id for item in provenance.producers}
            config_ids = {item.config_id for item in provenance.configs}
            for reference in evidence.references:
                _require_known(
                    reference.source_ref_ids,
                    source_ids,
                    f"EvidenceRef {reference.evidence_id!r}.source_ref_ids",
                )
                _require_known(
                    reference.span_ids,
                    set(spans),
                    f"EvidenceRef {reference.evidence_id!r}.span_ids",
                )
                for span_id in reference.span_ids:
                    source_id = spans[span_id].source_ref_id
                    if (
                        reference.source_ref_ids
                        and source_id not in reference.source_ref_ids
                    ):
                        raise ProvenanceValidationError(
                            f"EvidenceRef {reference.evidence_id!r} span "
                            f"{span_id!r} belongs to unlisted source {source_id!r}"
                        )
                if reference.producer_id:
                    _require_known(
                        (reference.producer_id,),
                        producer_ids,
                        f"EvidenceRef {reference.evidence_id!r}.producer_id",
                    )
                if reference.config_id:
                    _require_known(
                        (reference.config_id,),
                        config_ids,
                        f"EvidenceRef {reference.evidence_id!r}.config_id",
                    )
    except ProvenanceValidationError as exc:
        raise EvidenceValidationError(str(exc)) from exc
    return evidence


def canonical_evidence_bytes(evidence: Evidence) -> bytes:
    return evidence.canonical_bytes()


def canonical_evidence_json(evidence: Evidence) -> str:
    return evidence.to_json()


def evidence_sha256(evidence: Evidence) -> str:
    return evidence.sha256


EvidenceReference = EvidenceRef
EvidenceRegistry = Evidence


__all__ = [
    "Evidence",
    "EvidenceKind",
    "EvidenceRef",
    "EvidenceReference",
    "EvidenceRegistry",
    "EvidenceReviewStatus",
    "EvidenceValidationError",
    "IR_EVIDENCE_SCHEMA_VERSION",
    "canonical_evidence_bytes",
    "canonical_evidence_json",
    "evidence_sha256",
    "validate_evidence",
]
