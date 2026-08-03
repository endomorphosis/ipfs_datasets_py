"""Versioned USPTO analysis bundle assembly (PATLAW-050).

Builds an immutable, content-addressed analysis package that binds input
artifact IDs, model/ruleset versions, validation receipts, warnings, and
unsupported checks into a single replayable unit.

Design invariants
-----------------
* Bundle digest is a pure function of material inputs and versions; any
  material change (artifact set, section digests, ruleset/model versions,
  warnings, classification) changes the digest.
* Facts and conclusions bound into the bundle carry provenance links to
  artifact IDs and/or authority node IDs. Missing provenance is recorded as a
  warning, never silently dropped.
* Unsupported and missing checks surface as structured warnings / reason codes.
* Private (or quarantine) classification on any input propagates to the
  assembled bundle via most-restrictive merge.
* This module owns **bundle assembly only**. Source processors and their
  analysis records are inputs and are not mutated.

The thin wire contract remains
:class:`~ipfs_datasets_py.processors.domains.uspto.contracts.AnalysisBundle`;
:class:`UsptoAnalysisBundle` is the rich orchestration record that projects to
it.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AnalysisBundle as ContractAnalysisBundle,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    is_private_classification,
    most_restrictive_classification,
    requires_quarantine,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

ANALYSIS_BUNDLE_SCHEMA_VERSION: Final = "uspto.analysis-bundle.v1"
ANALYSIS_BUNDLE_INTERFACE: Final = "UsptoAnalysisBundle@1"
ANALYSIS_BUNDLE_RULESET_VERSION: Final = "analysis-bundle-rules@1"
PARSER_VERSION: Final = "patlaw-050.analysis-bundle.v1"

DEFAULT_MAX_SECTIONS: Final = 4096
DEFAULT_MAX_WARNINGS: Final = 512
DEFAULT_MAX_PROVENANCE: Final = 8192
DEFAULT_MAX_ARTIFACT_IDS: Final = 512

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BundleSectionKind(str, Enum):
    """Kinds of records that may be bound into an analysis bundle."""

    ARTIFACT_MANIFEST = "artifact_manifest"
    STATUS_SNAPSHOT = "status_snapshot"
    MATTER_EVENT = "matter_event"
    LEDGER_SNAPSHOT = "ledger_snapshot"
    CLAIM_SET = "claim_set"
    OFFICE_ACTION = "office_action"
    INSTRUCTION = "instruction"
    REQUIREMENT = "requirement"
    SUBMISSION_EVIDENCE = "submission_evidence"
    ASSESSMENT = "assessment"
    AUTHORITY = "authority"
    REJECTION_MAPPING = "rejection_mapping"
    CANDIDATE_DATE = "candidate_date"
    INSTRUCTION_CONSISTENCY = "instruction_consistency"
    SPAN_VALIDATION = "span_validation"
    VALIDATION_RECEIPT = "validation_receipt"
    COMPLIANCE = "compliance"
    OTHER = "other"


class BundleWarningCode(str, Enum):
    """Closed-set warning codes for missing / unsupported checks."""

    MISSING_ARTIFACT_MANIFEST = "missing_artifact_manifest"
    MISSING_STATUS = "missing_status"
    MISSING_EVENTS = "missing_events"
    MISSING_CLAIM_SET = "missing_claim_set"
    MISSING_REQUIREMENTS = "missing_requirements"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_ASSESSMENTS = "missing_assessments"
    MISSING_AUTHORITY = "missing_authority"
    MISSING_CANDIDATE_DATES = "missing_candidate_dates"
    MISSING_VALIDATION_RECEIPTS = "missing_validation_receipts"
    MISSING_SPAN_VALIDATION = "missing_span_validation"
    MISSING_PROVENANCE = "missing_provenance"
    UNSUPPORTED_CHECK = "unsupported_check"
    UNSUPPORTED_SECTION = "unsupported_section"
    CLASSIFICATION_PROPAGATED = "classification_propagated"
    PRIVATE_MATERIAL = "private_material"
    QUARANTINE_REQUIRED = "quarantine_required"
    EMPTY_BUNDLE = "empty_bundle"
    SCHEMA_VERSION_DRIFT = "schema_version_drift"
    ORPHAN_RECORD = "orphan_record"


class BundleDisposition(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    EMPTY = "empty"


class AnalysisBundleError(ValueError):
    """Raised for invalid analysis-bundle construction."""

    def __init__(self, message: str, *, code: str = "analysis_bundle_error") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=256) for i, item in enumerate(value))


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
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


def _default_id_factory() -> str:
    return uuid.uuid4().hex


def content_digest_of(value: Any) -> str:
    """SHA-256 of the canonical JSON projection of *value*."""
    if hasattr(value, "to_canonical_json") and callable(value.to_canonical_json):
        return sha256_hex(value.to_canonical_json())
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return sha256_hex(canonical_json(value.to_dict()))
    if isinstance(value, Mapping):
        return sha256_hex(canonical_json(dict(value)))
    return sha256_hex(canonical_json(value))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvenanceLink:
    """Trace from a bound fact/conclusion to artifacts and/or authority."""

    link_id: str
    subject_id: str
    subject_kind: str
    artifact_ids: tuple[str, ...]
    authority_ids: tuple[str, ...]
    span_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_id", _identifier(self.link_id, "link_id"))
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self,
            "subject_kind",
            _require_str(self.subject_kind, "subject_kind", max_len=64),
        )
        object.__setattr__(
            self,
            "artifact_ids",
            _tuple_of_str(self.artifact_ids, "artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_ids",
            _tuple_of_str(self.authority_ids, "authority_ids", max_items=64),
        )
        object.__setattr__(
            self, "span_ids", _tuple_of_str(self.span_ids, "span_ids", max_items=128)
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=16)
        )

    @property
    def is_traced(self) -> bool:
        return bool(self.artifact_ids or self.authority_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ids": list(self.artifact_ids),
            "authority_ids": list(self.authority_ids),
            "link_id": self.link_id,
            "notes": list(self.notes),
            "span_ids": list(self.span_ids),
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProvenanceLink":
        if not isinstance(value, Mapping):
            raise TypeError("ProvenanceLink must be a mapping")
        return cls(
            link_id=value.get("link_id", ""),
            subject_id=value.get("subject_id", ""),
            subject_kind=value.get("subject_kind", "other"),
            artifact_ids=tuple(value.get("artifact_ids") or ()),
            authority_ids=tuple(value.get("authority_ids") or ()),
            span_ids=tuple(value.get("span_ids") or ()),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class BundleWarning:
    """Structured warning for unsupported or missing checks."""

    code: BundleWarningCode
    message: str
    related_record_ids: tuple[str, ...] = ()
    section_kind: BundleSectionKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _coerce_enum(BundleWarningCode, self.code, "code")
        )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=1024)
        )
        object.__setattr__(
            self,
            "related_record_ids",
            _tuple_of_str(
                self.related_record_ids, "related_record_ids", max_items=64
            ),
        )
        if self.section_kind is not None:
            object.__setattr__(
                self,
                "section_kind",
                _coerce_enum(BundleSectionKind, self.section_kind, "section_kind"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "related_record_ids": list(self.related_record_ids),
            "section_kind": (
                None if self.section_kind is None else self.section_kind.value
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BundleWarning":
        if not isinstance(value, Mapping):
            raise TypeError("BundleWarning must be a mapping")
        return cls(
            code=value.get("code", BundleWarningCode.UNSUPPORTED_CHECK.value),
            message=value.get("message", "warning"),
            related_record_ids=tuple(value.get("related_record_ids") or ()),
            section_kind=value.get("section_kind"),
        )


@dataclass(frozen=True, slots=True)
class BundleSectionRef:
    """Content-addressed pointer to one bound analysis record."""

    section_id: str
    kind: BundleSectionKind
    record_id: str
    schema_version: str
    content_digest: str
    classification: DisclosureClassification
    source_artifact_ids: tuple[str, ...] = ()
    authority_ids: tuple[str, ...] = ()
    parent_record_ids: tuple[str, ...] = ()
    ruleset_versions: Mapping[str, str] = MappingProxyType({})
    model_versions: Mapping[str, str] = MappingProxyType({})
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "section_id", _identifier(self.section_id, "section_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(BundleSectionKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "record_id", _identifier(self.record_id, "record_id")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "source_artifact_ids",
            _tuple_of_str(
                self.source_artifact_ids, "source_artifact_ids", max_items=128
            ),
        )
        object.__setattr__(
            self,
            "authority_ids",
            _tuple_of_str(self.authority_ids, "authority_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "parent_record_ids",
            _tuple_of_str(
                self.parent_record_ids, "parent_record_ids", max_items=128
            ),
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "model_versions",
            _frozen_str_map(self.model_versions, "model_versions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ids": list(self.authority_ids),
            "classification": self.classification.value,
            "content_digest": self.content_digest,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "model_versions": dict(self.model_versions),
            "parent_record_ids": list(self.parent_record_ids),
            "record_id": self.record_id,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "section_id": self.section_id,
            "source_artifact_ids": list(self.source_artifact_ids),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BundleSectionRef":
        if not isinstance(value, Mapping):
            raise TypeError("BundleSectionRef must be a mapping")
        return cls(
            section_id=value.get("section_id", ""),
            kind=value.get("kind", BundleSectionKind.OTHER.value),
            record_id=value.get("record_id", ""),
            schema_version=value.get("schema_version", ""),
            content_digest=value.get("content_digest", ""),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            source_artifact_ids=tuple(value.get("source_artifact_ids") or ()),
            authority_ids=tuple(value.get("authority_ids") or ()),
            parent_record_ids=tuple(value.get("parent_record_ids") or ()),
            ruleset_versions=value.get("ruleset_versions") or {},
            model_versions=value.get("model_versions") or {},
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class UsptoAnalysisBundle:
    """Immutable, content-addressed USPTO analysis package.

    Projects to the thin :class:`ContractAnalysisBundle` via
    :meth:`to_contract_bundle`.
    """

    schema_version: str
    bundle_id: str
    matter_id: str | None
    disposition: BundleDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    bundle_digest: str
    input_artifact_ids: tuple[str, ...]
    output_artifact_ids: tuple[str, ...]
    sections: tuple[BundleSectionRef, ...]
    provenance: tuple[ProvenanceLink, ...]
    warnings: tuple[BundleWarning, ...]
    warning_codes: tuple[str, ...]
    unsupported_checks: tuple[str, ...]
    model_versions: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    validation_receipt_ids: tuple[str, ...]
    labels: Mapping[str, str]
    analysis_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != ANALYSIS_BUNDLE_SCHEMA_VERSION:
            raise AnalysisBundleError(
                f"UsptoAnalysisBundle.schema_version must be "
                f"{ANALYSIS_BUNDLE_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, "bundle_id"))
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(BundleDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "bundle_digest",
            _sha256_hex_field(self.bundle_digest, "bundle_digest"),
        )
        object.__setattr__(
            self,
            "input_artifact_ids",
            _tuple_of_str(
                self.input_artifact_ids,
                "input_artifact_ids",
                max_items=DEFAULT_MAX_ARTIFACT_IDS,
            ),
        )
        object.__setattr__(
            self,
            "output_artifact_ids",
            _tuple_of_str(
                self.output_artifact_ids,
                "output_artifact_ids",
                max_items=DEFAULT_MAX_ARTIFACT_IDS,
            ),
        )
        if not isinstance(self.sections, tuple):
            object.__setattr__(self, "sections", tuple(self.sections))
        if len(self.sections) > DEFAULT_MAX_SECTIONS:
            raise AnalysisBundleError(
                f"sections exceeds max {DEFAULT_MAX_SECTIONS}",
                code="too_many_sections",
            )
        for section in self.sections:
            if not isinstance(section, BundleSectionRef):
                raise TypeError("sections must be BundleSectionRef instances")
        if not isinstance(self.provenance, tuple):
            object.__setattr__(self, "provenance", tuple(self.provenance))
        if len(self.provenance) > DEFAULT_MAX_PROVENANCE:
            raise AnalysisBundleError(
                f"provenance exceeds max {DEFAULT_MAX_PROVENANCE}",
                code="too_many_provenance",
            )
        for link in self.provenance:
            if not isinstance(link, ProvenanceLink):
                raise TypeError("provenance must be ProvenanceLink instances")
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if len(self.warnings) > DEFAULT_MAX_WARNINGS:
            raise AnalysisBundleError(
                f"warnings exceeds max {DEFAULT_MAX_WARNINGS}",
                code="too_many_warnings",
            )
        for warning in self.warnings:
            if not isinstance(warning, BundleWarning):
                raise TypeError("warnings must be BundleWarning instances")
        object.__setattr__(
            self,
            "warning_codes",
            _tuple_of_str(self.warning_codes, "warning_codes", max_items=256),
        )
        object.__setattr__(
            self,
            "unsupported_checks",
            _tuple_of_str(
                self.unsupported_checks, "unsupported_checks", max_items=256
            ),
        )
        object.__setattr__(
            self,
            "model_versions",
            _frozen_str_map(self.model_versions, "model_versions", max_items=64),
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=64),
        )
        object.__setattr__(
            self,
            "validation_receipt_ids",
            _tuple_of_str(
                self.validation_receipt_ids,
                "validation_receipt_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    # ---- Queries ----

    @property
    def requires_review(self) -> bool:
        return self.review_state in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ) or self.disposition in (
            BundleDisposition.REVIEW,
            BundleDisposition.UNKNOWN,
            BundleDisposition.QUARANTINE,
            BundleDisposition.PARTIAL,
            BundleDisposition.EMPTY,
        )

    @property
    def is_private(self) -> bool:
        return is_private_classification(self.classification)

    def sections_by_kind(
        self, kind: BundleSectionKind | str
    ) -> tuple[BundleSectionRef, ...]:
        k = _coerce_enum(BundleSectionKind, kind, "kind")
        return tuple(s for s in self.sections if s.kind is k)

    def untraced_subjects(self) -> tuple[str, ...]:
        """Subject IDs whose provenance lacks artifact and authority links."""
        return tuple(p.subject_id for p in self.provenance if not p.is_traced)

    def material_payload(self) -> dict[str, Any]:
        """Payload that participates in the content-addressed bundle digest.

        Excludes generated identity fields that are derived from this payload
        (``bundle_id``, ``bundle_digest``) so callers can recompute digests.
        """
        return {
            "analysis_id": self.analysis_id,
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "input_artifact_ids": list(self.input_artifact_ids),
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "model_versions": dict(self.model_versions),
            "output_artifact_ids": list(self.output_artifact_ids),
            "provenance": [p.to_dict() for p in self.provenance],
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "sections": [s.to_dict() for s in self.sections],
            "unsupported_checks": list(self.unsupported_checks),
            "validation_receipt_ids": list(self.validation_receipt_ids),
            "warning_codes": list(self.warning_codes),
            "warnings": [w.to_dict() for w in self.warnings],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["bundle_digest"] = self.bundle_digest
        payload["bundle_id"] = self.bundle_id
        return payload

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_contract_bundle(self) -> ContractAnalysisBundle:
        """Project to the thin shared contracts.AnalysisBundle."""
        return ContractAnalysisBundle(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            bundle_id=self.bundle_id,
            input_artifact_ids=self.input_artifact_ids,
            output_artifact_ids=self.output_artifact_ids,
            warning_codes=self.warning_codes,
            unsupported_checks=self.unsupported_checks,
            model_versions=self.model_versions,
            ruleset_versions=self.ruleset_versions,
            validation_receipt_ids=self.validation_receipt_ids,
            classification=self.classification,
            review_state=self.review_state,
        )

    def public_projection(self) -> dict[str, Any]:
        """Safe identifiers/counts only — no private body content."""
        return {
            "analysis_id": self.analysis_id,
            "bundle_digest": self.bundle_digest,
            "bundle_id": self.bundle_id,
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "input_artifact_count": len(self.input_artifact_ids),
            "is_private": self.is_private,
            "matter_id": self.matter_id,
            "model_versions": dict(self.model_versions),
            "output_artifact_count": len(self.output_artifact_ids),
            "provenance_count": len(self.provenance),
            "requires_review": self.requires_review,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "section_count": len(self.sections),
            "section_kinds": sorted({s.kind.value for s in self.sections}),
            "unsupported_checks": list(self.unsupported_checks),
            "untraced_subject_count": len(self.untraced_subjects()),
            "validation_receipt_count": len(self.validation_receipt_ids),
            "warning_codes": list(self.warning_codes),
            "warning_count": len(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UsptoAnalysisBundle":
        if not isinstance(value, Mapping):
            raise TypeError("UsptoAnalysisBundle must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", ANALYSIS_BUNDLE_SCHEMA_VERSION
            ),
            bundle_id=value.get("bundle_id", ""),
            matter_id=value.get("matter_id"),
            disposition=value.get("disposition", BundleDisposition.UNKNOWN.value),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            bundle_digest=value.get("bundle_digest", ""),
            input_artifact_ids=tuple(value.get("input_artifact_ids") or ()),
            output_artifact_ids=tuple(value.get("output_artifact_ids") or ()),
            sections=tuple(
                BundleSectionRef.from_dict(s) for s in (value.get("sections") or ())
            ),
            provenance=tuple(
                ProvenanceLink.from_dict(p) for p in (value.get("provenance") or ())
            ),
            warnings=tuple(
                BundleWarning.from_dict(w) for w in (value.get("warnings") or ())
            ),
            warning_codes=tuple(value.get("warning_codes") or ()),
            unsupported_checks=tuple(value.get("unsupported_checks") or ()),
            model_versions=value.get("model_versions") or {},
            ruleset_versions=value.get("ruleset_versions") or {},
            validation_receipt_ids=tuple(
                value.get("validation_receipt_ids") or ()
            ),
            labels=value.get("labels") or {},
            analysis_id=value.get("analysis_id"),
        )


# ---------------------------------------------------------------------------
# Digest + assembly
# ---------------------------------------------------------------------------


def compute_bundle_digest(
    *,
    schema_version: str = ANALYSIS_BUNDLE_SCHEMA_VERSION,
    matter_id: str | None,
    disposition: BundleDisposition | str,
    review_state: ReviewState | str,
    classification: DisclosureClassification | str,
    input_artifact_ids: Sequence[str],
    output_artifact_ids: Sequence[str],
    sections: Sequence[BundleSectionRef],
    provenance: Sequence[ProvenanceLink],
    warnings: Sequence[BundleWarning],
    warning_codes: Sequence[str],
    unsupported_checks: Sequence[str],
    model_versions: Mapping[str, str],
    ruleset_versions: Mapping[str, str],
    validation_receipt_ids: Sequence[str],
    labels: Mapping[str, str],
    analysis_id: str | None = None,
) -> str:
    """Compute the material content digest for an analysis bundle."""
    payload = {
        "analysis_id": analysis_id,
        "classification": (
            classification.value
            if isinstance(classification, DisclosureClassification)
            else str(classification)
        ),
        "disposition": (
            disposition.value if isinstance(disposition, BundleDisposition) else str(disposition)
        ),
        "input_artifact_ids": list(input_artifact_ids),
        "labels": dict(sorted((str(k), str(v)) for k, v in labels.items())),
        "matter_id": matter_id,
        "model_versions": dict(sorted((str(k), str(v)) for k, v in model_versions.items())),
        "output_artifact_ids": list(output_artifact_ids),
        "provenance": [p.to_dict() if isinstance(p, ProvenanceLink) else p for p in provenance],
        "review_state": (
            review_state.value if isinstance(review_state, ReviewState) else str(review_state)
        ),
        "ruleset_versions": dict(
            sorted((str(k), str(v)) for k, v in ruleset_versions.items())
        ),
        "schema_version": schema_version,
        "sections": [
            s.to_dict() if isinstance(s, BundleSectionRef) else s for s in sections
        ],
        "unsupported_checks": list(unsupported_checks),
        "validation_receipt_ids": list(validation_receipt_ids),
        "warning_codes": list(warning_codes),
        "warnings": [
            w.to_dict() if isinstance(w, BundleWarning) else w for w in warnings
        ],
    }
    return sha256_hex(canonical_json(payload))


def merge_classifications(
    values: Iterable[DisclosureClassification | str],
) -> DisclosureClassification:
    """Most-restrictive classification merge (fail-closed empty → UNKNOWN)."""
    return most_restrictive_classification(values)


def section_from_mapping(
    *,
    section_id: str,
    kind: BundleSectionKind | str,
    record_id: str,
    schema_version: str,
    content_digest: str | None = None,
    payload: Any = None,
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN,
    source_artifact_ids: Sequence[str] = (),
    authority_ids: Sequence[str] = (),
    parent_record_ids: Sequence[str] = (),
    ruleset_versions: Mapping[str, str] | None = None,
    model_versions: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> BundleSectionRef:
    """Build a section ref; digest from *content_digest* or *payload*."""
    digest = content_digest
    if digest is None:
        if payload is None:
            raise AnalysisBundleError(
                "section requires content_digest or payload",
                code="missing_section_digest",
            )
        digest = content_digest_of(payload)
    return BundleSectionRef(
        section_id=section_id,
        kind=kind,
        record_id=record_id,
        schema_version=schema_version,
        content_digest=digest,
        classification=classification,
        source_artifact_ids=tuple(source_artifact_ids),
        authority_ids=tuple(authority_ids),
        parent_record_ids=tuple(parent_record_ids),
        ruleset_versions=ruleset_versions or {},
        model_versions=model_versions or {},
        labels=labels or {},
    )


@dataclass
class AnalysisBundleBuilder:
    """Incremental builder for :class:`UsptoAnalysisBundle`.

    Classification is the most restrictive of all added sections and explicit
    seed classifications. Missing/unsupported checks become warnings.
    """

    matter_id: str | None = None
    analysis_id: str | None = None
    seed_classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER
    labels: Mapping[str, str] = MappingProxyType({})
    id_factory: Callable[[], str] = _default_id_factory

    def __post_init__(self) -> None:
        self._sections: list[BundleSectionRef] = []
        self._provenance: list[ProvenanceLink] = []
        self._warnings: list[BundleWarning] = []
        self._unsupported: list[str] = []
        self._input_artifacts: list[str] = []
        self._output_artifacts: list[str] = []
        self._validation_receipt_ids: list[str] = []
        self._model_versions: dict[str, str] = {}
        self._ruleset_versions: dict[str, str] = {
            "analysis_bundle": ANALYSIS_BUNDLE_RULESET_VERSION,
            "parser": PARSER_VERSION,
            "contracts": CONTRACTS_SCHEMA_VERSION,
        }
        self._classifications: list[DisclosureClassification] = [
            _coerce_classification(self.seed_classification)
        ]
        self.labels = _frozen_str_map(self.labels, "labels", max_items=32)
        if self.matter_id is not None:
            self.matter_id = _optional_identifier(self.matter_id, "matter_id")
        if self.analysis_id is not None:
            self.analysis_id = _optional_identifier(self.analysis_id, "analysis_id")

    # ---- mutators ----

    def add_input_artifact_ids(self, *artifact_ids: str) -> "AnalysisBundleBuilder":
        for aid in artifact_ids:
            ident = _identifier(aid, "artifact_id")
            if ident not in self._input_artifacts:
                self._input_artifacts.append(ident)
        return self

    def add_output_artifact_ids(self, *artifact_ids: str) -> "AnalysisBundleBuilder":
        for aid in artifact_ids:
            ident = _identifier(aid, "artifact_id")
            if ident not in self._output_artifacts:
                self._output_artifacts.append(ident)
        return self

    def add_model_versions(self, versions: Mapping[str, str]) -> "AnalysisBundleBuilder":
        for k, v in versions.items():
            self._model_versions[_require_str(k, "model_versions.key", max_len=128)] = (
                _require_str(v, f"model_versions[{k}]", max_len=256)
            )
        return self

    def add_ruleset_versions(
        self, versions: Mapping[str, str]
    ) -> "AnalysisBundleBuilder":
        for k, v in versions.items():
            self._ruleset_versions[
                _require_str(k, "ruleset_versions.key", max_len=128)
            ] = _require_str(v, f"ruleset_versions[{k}]", max_len=256)
        return self

    def add_validation_receipt_ids(self, *receipt_ids: str) -> "AnalysisBundleBuilder":
        for rid in receipt_ids:
            ident = _identifier(rid, "validation_receipt_id")
            if ident not in self._validation_receipt_ids:
                self._validation_receipt_ids.append(ident)
        return self

    def add_unsupported_check(self, check_id: str) -> "AnalysisBundleBuilder":
        check = _require_str(check_id, "unsupported_check", max_len=256)
        if check not in self._unsupported:
            self._unsupported.append(check)
            self._warnings.append(
                BundleWarning(
                    code=BundleWarningCode.UNSUPPORTED_CHECK,
                    message=f"Unsupported check recorded: {check}",
                    related_record_ids=(check,),
                )
            )
        return self

    def add_warning(
        self,
        code: BundleWarningCode | str,
        message: str,
        *,
        related_record_ids: Sequence[str] = (),
        section_kind: BundleSectionKind | str | None = None,
    ) -> "AnalysisBundleBuilder":
        self._warnings.append(
            BundleWarning(
                code=code,
                message=message,
                related_record_ids=tuple(related_record_ids),
                section_kind=section_kind,
            )
        )
        return self

    def add_section(self, section: BundleSectionRef) -> "AnalysisBundleBuilder":
        if not isinstance(section, BundleSectionRef):
            raise TypeError("section must be BundleSectionRef")
        self._sections.append(section)
        self._classifications.append(section.classification)
        for aid in section.source_artifact_ids:
            if aid not in self._input_artifacts:
                self._input_artifacts.append(aid)
        for k, v in section.ruleset_versions.items():
            self._ruleset_versions.setdefault(k, v)
        for k, v in section.model_versions.items():
            self._model_versions.setdefault(k, v)
        if section.kind is BundleSectionKind.VALIDATION_RECEIPT:
            if section.record_id not in self._validation_receipt_ids:
                self._validation_receipt_ids.append(section.record_id)
        return self

    def add_provenance(self, link: ProvenanceLink) -> "AnalysisBundleBuilder":
        if not isinstance(link, ProvenanceLink):
            raise TypeError("link must be ProvenanceLink")
        self._provenance.append(link)
        if not link.is_traced:
            self._warnings.append(
                BundleWarning(
                    code=BundleWarningCode.MISSING_PROVENANCE,
                    message=(
                        f"Subject {link.subject_id} ({link.subject_kind}) "
                        "lacks artifact/authority provenance"
                    ),
                    related_record_ids=(link.subject_id, link.link_id),
                )
            )
        return self

    def bind_section(
        self,
        *,
        kind: BundleSectionKind | str,
        record_id: str,
        schema_version: str,
        content_digest: str | None = None,
        payload: Any = None,
        classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN,
        source_artifact_ids: Sequence[str] = (),
        authority_ids: Sequence[str] = (),
        parent_record_ids: Sequence[str] = (),
        ruleset_versions: Mapping[str, str] | None = None,
        model_versions: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
        provenance_subject_kind: str | None = None,
        span_ids: Sequence[str] = (),
        require_provenance: bool = True,
    ) -> BundleSectionRef:
        """Bind a section and optionally emit a provenance link for it."""
        section_id = f"sec:{self.id_factory()}"
        section = section_from_mapping(
            section_id=section_id,
            kind=kind,
            record_id=record_id,
            schema_version=schema_version,
            content_digest=content_digest,
            payload=payload,
            classification=classification,
            source_artifact_ids=source_artifact_ids,
            authority_ids=authority_ids,
            parent_record_ids=parent_record_ids,
            ruleset_versions=ruleset_versions,
            model_versions=model_versions,
            labels=labels,
        )
        self.add_section(section)
        if require_provenance:
            subject_kind = provenance_subject_kind or (
                section.kind.value
                if isinstance(section.kind, BundleSectionKind)
                else str(section.kind)
            )
            self.add_provenance(
                ProvenanceLink(
                    link_id=f"prov:{self.id_factory()}",
                    subject_id=record_id,
                    subject_kind=subject_kind,
                    artifact_ids=tuple(source_artifact_ids),
                    authority_ids=tuple(authority_ids),
                    span_ids=tuple(span_ids),
                )
            )
        return section

    # ---- build ----

    def _sorted_sections(self) -> tuple[BundleSectionRef, ...]:
        return tuple(
            sorted(
                self._sections,
                key=lambda s: (s.kind.value, s.record_id, s.content_digest),
            )
        )

    def _sorted_provenance(self) -> tuple[ProvenanceLink, ...]:
        return tuple(
            sorted(
                self._provenance,
                key=lambda p: (p.subject_kind, p.subject_id, p.link_id),
            )
        )

    def _sorted_warnings(self) -> tuple[BundleWarning, ...]:
        # Preserve insertion order but de-dupe identical (code, message, section).
        seen: set[tuple[str, str, str | None]] = set()
        out: list[BundleWarning] = []
        for w in self._warnings:
            key = (
                w.code.value,
                w.message,
                None if w.section_kind is None else w.section_kind.value,
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(w)
        return tuple(out)

    def _derive_disposition(
        self,
        *,
        classification: DisclosureClassification,
        warnings: Sequence[BundleWarning],
        sections: Sequence[BundleSectionRef],
        unsupported: Sequence[str],
    ) -> BundleDisposition:
        if requires_quarantine(classification):
            return BundleDisposition.QUARANTINE
        if not sections and not self._input_artifacts:
            return BundleDisposition.EMPTY
        if unsupported or any(
            w.code
            in (
                BundleWarningCode.MISSING_REQUIREMENTS,
                BundleWarningCode.MISSING_EVIDENCE,
                BundleWarningCode.MISSING_ASSESSMENTS,
                BundleWarningCode.MISSING_AUTHORITY,
                BundleWarningCode.MISSING_PROVENANCE,
                BundleWarningCode.UNSUPPORTED_CHECK,
                BundleWarningCode.UNSUPPORTED_SECTION,
            )
            for w in warnings
        ):
            return BundleDisposition.PARTIAL
        if any(
            w.code
            in (
                BundleWarningCode.MISSING_ARTIFACT_MANIFEST,
                BundleWarningCode.MISSING_STATUS,
                BundleWarningCode.MISSING_CLAIM_SET,
            )
            for w in warnings
        ):
            return BundleDisposition.REVIEW
        return BundleDisposition.COMPLETE

    def _derive_review_state(
        self,
        *,
        disposition: BundleDisposition,
        classification: DisclosureClassification,
    ) -> ReviewState:
        if requires_quarantine(classification):
            return ReviewState.REQUIRED
        if is_private_classification(classification):
            return ReviewState.REQUIRED
        if disposition in (
            BundleDisposition.PARTIAL,
            BundleDisposition.UNKNOWN,
            BundleDisposition.REVIEW,
            BundleDisposition.EMPTY,
            BundleDisposition.QUARANTINE,
        ):
            return ReviewState.REQUIRED
        return ReviewState.PENDING

    def build(self, *, bundle_id: str | None = None) -> UsptoAnalysisBundle:
        sections = self._sorted_sections()
        provenance = self._sorted_provenance()
        warnings = list(self._sorted_warnings())
        unsupported = tuple(sorted(set(self._unsupported)))

        classification = merge_classifications(self._classifications)

        # Private / quarantine classification propagates onto every derived
        # section binding (inputs themselves are never mutated).
        if is_private_classification(classification) or requires_quarantine(
            classification
        ):
            propagated: list[BundleSectionRef] = []
            for section in sections:
                merged = merge_classifications(
                    (classification, section.classification)
                )
                if merged is section.classification:
                    propagated.append(section)
                else:
                    propagated.append(
                        BundleSectionRef(
                            section_id=section.section_id,
                            kind=section.kind,
                            record_id=section.record_id,
                            schema_version=section.schema_version,
                            content_digest=section.content_digest,
                            classification=merged,
                            source_artifact_ids=section.source_artifact_ids,
                            authority_ids=section.authority_ids,
                            parent_record_ids=section.parent_record_ids,
                            ruleset_versions=section.ruleset_versions,
                            model_versions=section.model_versions,
                            labels=section.labels,
                        )
                    )
            sections = tuple(
                sorted(
                    propagated,
                    key=lambda s: (s.kind.value, s.record_id, s.content_digest),
                )
            )
            warnings.append(
                BundleWarning(
                    code=BundleWarningCode.CLASSIFICATION_PROPAGATED,
                    message=(
                        "Most-restrictive classification propagated to every "
                        f"derived section binding ({classification.value})"
                    ),
                )
            )

        if is_private_classification(classification):
            warnings.append(
                BundleWarning(
                    code=BundleWarningCode.PRIVATE_MATERIAL,
                    message=(
                        "Private classification propagated to analysis bundle "
                        f"({classification.value})"
                    ),
                )
            )
        if requires_quarantine(classification):
            warnings.append(
                BundleWarning(
                    code=BundleWarningCode.QUARANTINE_REQUIRED,
                    message="Quarantine classification requires human review",
                )
            )
        if not sections and not self._input_artifacts:
            warnings.append(
                BundleWarning(
                    code=BundleWarningCode.EMPTY_BUNDLE,
                    message="Analysis bundle has no bound sections or artifacts",
                )
            )

        # Stable order for inputs/outputs.
        input_ids = tuple(sorted(set(self._input_artifacts)))
        output_ids = tuple(sorted(set(self._output_artifacts)))
        receipt_ids = tuple(sorted(set(self._validation_receipt_ids)))
        final_warnings = tuple(warnings)
        warning_codes = tuple(
            dict.fromkeys(w.code.value for w in final_warnings)
        )

        disposition = self._derive_disposition(
            classification=classification,
            warnings=final_warnings,
            sections=sections,
            unsupported=unsupported,
        )
        review_state = self._derive_review_state(
            disposition=disposition, classification=classification
        )

        digest = compute_bundle_digest(
            schema_version=ANALYSIS_BUNDLE_SCHEMA_VERSION,
            matter_id=self.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            input_artifact_ids=input_ids,
            output_artifact_ids=output_ids,
            sections=sections,
            provenance=provenance,
            warnings=final_warnings,
            warning_codes=warning_codes,
            unsupported_checks=unsupported,
            model_versions=self._model_versions,
            ruleset_versions=self._ruleset_versions,
            validation_receipt_ids=receipt_ids,
            labels=self.labels,
            analysis_id=self.analysis_id,
        )
        bid = bundle_id or f"bundle:{digest[:24]}"
        return UsptoAnalysisBundle(
            schema_version=ANALYSIS_BUNDLE_SCHEMA_VERSION,
            bundle_id=bid,
            matter_id=self.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            bundle_digest=digest,
            input_artifact_ids=input_ids,
            output_artifact_ids=output_ids,
            sections=sections,
            provenance=provenance,
            warnings=final_warnings,
            warning_codes=warning_codes,
            unsupported_checks=unsupported,
            model_versions=self._model_versions,
            ruleset_versions=self._ruleset_versions,
            validation_receipt_ids=receipt_ids,
            labels=self.labels,
            analysis_id=self.analysis_id,
        )


def build_analysis_bundle(
    *,
    matter_id: str | None = None,
    analysis_id: str | None = None,
    sections: Sequence[BundleSectionRef] = (),
    provenance: Sequence[ProvenanceLink] = (),
    input_artifact_ids: Sequence[str] = (),
    output_artifact_ids: Sequence[str] = (),
    validation_receipt_ids: Sequence[str] = (),
    model_versions: Mapping[str, str] | None = None,
    ruleset_versions: Mapping[str, str] | None = None,
    unsupported_checks: Sequence[str] = (),
    warnings: Sequence[BundleWarning] = (),
    seed_classification: DisclosureClassification | str = (
        DisclosureClassification.PUBLIC_USER
    ),
    labels: Mapping[str, str] | None = None,
    id_factory: Callable[[], str] | None = None,
    bundle_id: str | None = None,
) -> UsptoAnalysisBundle:
    """One-shot assembly helper."""
    builder = AnalysisBundleBuilder(
        matter_id=matter_id,
        analysis_id=analysis_id,
        seed_classification=_coerce_classification(seed_classification),
        labels=labels or {},
        id_factory=id_factory or _default_id_factory,
    )
    if input_artifact_ids:
        builder.add_input_artifact_ids(*input_artifact_ids)
    if output_artifact_ids:
        builder.add_output_artifact_ids(*output_artifact_ids)
    if validation_receipt_ids:
        builder.add_validation_receipt_ids(*validation_receipt_ids)
    if model_versions:
        builder.add_model_versions(model_versions)
    if ruleset_versions:
        builder.add_ruleset_versions(ruleset_versions)
    for check in unsupported_checks:
        builder.add_unsupported_check(check)
    for warning in warnings:
        builder.add_warning(
            warning.code,
            warning.message,
            related_record_ids=warning.related_record_ids,
            section_kind=warning.section_kind,
        )
    for section in sections:
        builder.add_section(section)
    for link in provenance:
        builder.add_provenance(link)
    return builder.build(bundle_id=bundle_id)


__all__ = [
    "ANALYSIS_BUNDLE_INTERFACE",
    "ANALYSIS_BUNDLE_RULESET_VERSION",
    "ANALYSIS_BUNDLE_SCHEMA_VERSION",
    "PARSER_VERSION",
    "AnalysisBundleBuilder",
    "AnalysisBundleError",
    "BundleDisposition",
    "BundleSectionKind",
    "BundleSectionRef",
    "BundleWarning",
    "BundleWarningCode",
    "ProvenanceLink",
    "UsptoAnalysisBundle",
    "build_analysis_bundle",
    "compute_bundle_digest",
    "content_digest_of",
    "merge_classifications",
    "section_from_mapping",
    "sha256_hex",
]
