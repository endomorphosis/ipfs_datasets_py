"""Admit submission facts and build exact support/counter-evidence maps (PATLAW-041).

Fail-closed pipeline that:

* admits only span-bound submission facts that resolve to a known artifact
  content version;
* maps exact supporting and contradicting evidence edges (never summaries);
* excludes stale, invalid, or ambiguous evidence with machine-readable reasons;
* produces no implicit support when the submission is empty; and
* exposes a typed patent adapter over the reusable SupportMap helpers.

This module does not perform top-level compliance aggregation (PATLAW-042).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ExtractedSpan,
    ReviewState,
    SubmissionFact,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_processor import (
    ClaimVersion,
    EnrichedSubmissionFact,
    FactExtractionStatus,
    SubmissionAnalysisResult,
    SubmissionFactType,
)
from ipfs_datasets_py.processors.legal_data.support_map import (
    MotionSupportMap,
    SupportFact,
    SupportMapBuilder,
    SupportMapEntry,
)

SUBMISSION_EVIDENCE_SCHEMA_VERSION: Final = "uspto.submission-evidence.v1"
SUBMISSION_EVIDENCE_INTERFACE: Final = "UsptoSubmissionEvidence@1"
PARSER_VERSION: Final = "patlaw-041.submission-evidence.v1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

# Fact types that are never exact evidence (summaries / unsupported placeholders).
_SUMMARY_FACT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "summary",
        "llm_summary",
        "narrative_summary",
        "abstract_summary",
        SubmissionFactType.UNSUPPORTED.value,
    }
)

# Extraction statuses that cannot be admitted as exact evidence.
_EXCLUDED_EXTRACTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        FactExtractionStatus.MISSING.value,
        FactExtractionStatus.UNKNOWN.value,
        FactExtractionStatus.REVIEW_REQUIRED.value,
    }
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EvidenceEdgeRole(str, Enum):
    """Role of a fact↔span evidence edge."""

    SUPPORT = "support"
    COUNTER = "counter"


class EvidenceDisposition(str, Enum):
    """Pipeline disposition after fact admission and mapping."""

    MAPPED = "mapped"
    EMPTY = "empty"
    PARTIAL = "partial"
    REVIEW = "review"
    REJECTED = "rejected"


class ExclusionReasonCode(str, Enum):
    """Why a candidate fact/evidence edge was excluded (fail-closed)."""

    EMPTY_SUBMISSION = "empty_submission"
    MISSING_SPAN = "missing_span"
    INVALID_SPAN = "invalid_span"
    STALE_SPAN = "stale_span"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    MISSING_ARTIFACT_VERSION = "missing_artifact_version"
    ARTIFACT_VERSION_MISMATCH = "artifact_version_mismatch"
    ARTIFACT_UNKNOWN = "artifact_unknown"
    SUMMARY_NOT_EVIDENCE = "summary_not_evidence"
    EXTRACTION_STATUS_EXCLUDED = "extraction_status_excluded"
    SPAN_ARTIFACT_MISMATCH = "span_artifact_mismatch"
    FACT_SPAN_UNRESOLVED = "fact_span_unresolved"
    DUPLICATE_FACT_AMBIGUOUS = "duplicate_fact_ambiguous"
    COUNTER_CANDIDATE_INVALID = "counter_candidate_invalid"
    NO_EXACT_SPAN = "no_exact_span"


class EvidenceReasonCode(str, Enum):
    """Positive / informational map-level reason codes."""

    FACTS_ADMITTED = "facts_admitted"
    SUPPORT_EDGES_MAPPED = "support_edges_mapped"
    COUNTER_EDGES_MAPPED = "counter_edges_mapped"
    EXCLUSIONS_RECORDED = "exclusions_recorded"
    EMPTY_NO_IMPLICIT_SUPPORT = "empty_no_implicit_support"
    CLAIM_VERSIONS_RECONSTRUCTED = "claim_versions_reconstructed"
    DOCUMENT_VERSIONS_BOUND = "document_versions_bound"
    SUPPORT_MAP_ADAPTED = "support_map_adapted"
    REVIEW_REQUIRED = "review_required"


class SubmissionEvidenceError(ValueError):
    """Bounded evidence mapping failure with a stable machine-readable code."""

    def __init__(
        self, message: str, *, code: str = "submission_evidence_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


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


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field} must be sha256 hex")
    return lowered


def _require_sha256(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise ValueError(f"invalid classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    items = tuple(_require_str(str(v), field, max_len=512) for v in value)
    if len(items) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return items


def _frozen_str_map(
    value: Any,
    field: str,
    *,
    max_items: int = 256,
    max_value_len: int = 4096,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for k, v in value.items():
        key = _require_str(str(k), f"{field}.key", max_len=256)
        val = _require_str(str(v), f"{field}.value", max_len=max_value_len)
        out[key] = val
    return MappingProxyType(out)


def _default_id_factory() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactVersionBinding:
    """Artifact identity bound to an immutable content digest (version)."""

    artifact_id: str
    content_sha256: str
    version_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "version_label",
            _optional_str(self.version_label, "version_label", max_len=128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "version_label": self.version_label,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactVersionBinding":
        if not isinstance(value, Mapping):
            raise TypeError("ArtifactVersionBinding must be a mapping")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256", ""),
            version_label=value.get("version_label"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    """Exact fact ↔ span ↔ artifact-version edge (support or counter)."""

    edge_id: str
    fact_id: str
    span_id: str
    artifact_id: str
    content_sha256: str
    role: EvidenceEdgeRole
    fact_type: str
    fact_version: str
    page_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    text_digest: str | None = None
    field_name: str | None = None
    relation_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(self, "span_id", _identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self, "role", _coerce_enum(EvidenceEdgeRole, self.role, "role")
        )
        object.__setattr__(
            self, "fact_type", _require_str(self.fact_type, "fact_type", max_len=128)
        )
        object.__setattr__(
            self,
            "fact_version",
            _require_str(self.fact_version, "fact_version", max_len=64),
        )
        if self.page_index is not None:
            object.__setattr__(
                self, "page_index", _nonneg_int(self.page_index, "page_index")
            )
        if self.char_start is not None:
            object.__setattr__(
                self, "char_start", _nonneg_int(self.char_start, "char_start")
            )
        if self.char_end is not None:
            object.__setattr__(
                self, "char_end", _nonneg_int(self.char_end, "char_end")
            )
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be >= char_start")
        object.__setattr__(
            self, "text_digest", _optional_sha256(self.text_digest, "text_digest")
        )
        object.__setattr__(
            self, "field_name", _optional_str(self.field_name, "field_name", max_len=128)
        )
        object.__setattr__(
            self,
            "relation_note",
            _optional_str(self.relation_note, "relation_note", max_len=256),
        )

    def round_trip_key(self) -> tuple[str, str, str, str, str]:
        """Stable key used to verify edge → artifact version/span resolution."""
        return (
            self.fact_id,
            self.span_id,
            self.artifact_id,
            self.content_sha256,
            self.role.value,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "char_end": self.char_end,
            "char_start": self.char_start,
            "content_sha256": self.content_sha256,
            "edge_id": self.edge_id,
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "fact_version": self.fact_version,
            "field_name": self.field_name,
            "page_index": self.page_index,
            "relation_note": self.relation_note,
            "role": self.role.value,
            "span_id": self.span_id,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceEdge":
        if not isinstance(value, Mapping):
            raise TypeError("EvidenceEdge must be a mapping")
        return cls(
            edge_id=value.get("edge_id", ""),
            fact_id=value.get("fact_id", ""),
            span_id=value.get("span_id", ""),
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256", ""),
            role=value.get("role", EvidenceEdgeRole.SUPPORT.value),
            fact_type=value.get("fact_type", "unknown"),
            fact_version=value.get("fact_version", "1"),
            page_index=value.get("page_index"),
            char_start=value.get("char_start"),
            char_end=value.get("char_end"),
            text_digest=value.get("text_digest"),
            field_name=value.get("field_name"),
            relation_note=value.get("relation_note"),
        )


@dataclass(frozen=True, slots=True)
class ExcludedEvidence:
    """A fact/evidence candidate that was not admitted, with reasons."""

    exclusion_id: str
    fact_id: str
    evidence_span_id: str | None
    artifact_id: str | None
    reason_codes: tuple[str, ...]
    detail: str | None = None
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exclusion_id", _identifier(self.exclusion_id, "exclusion_id")
        )
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(
            self,
            "evidence_span_id",
            _optional_identifier(self.evidence_span_id, "evidence_span_id"),
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        if not self.reason_codes:
            raise ValueError("ExcludedEvidence.reason_codes must be non-empty")
        object.__setattr__(
            self, "detail", _optional_str(self.detail, "detail", max_len=512)
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "detail": self.detail,
            "evidence_span_id": self.evidence_span_id,
            "exclusion_id": self.exclusion_id,
            "fact_id": self.fact_id,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExcludedEvidence":
        if not isinstance(value, Mapping):
            raise TypeError("ExcludedEvidence must be a mapping")
        return cls(
            exclusion_id=value.get("exclusion_id", ""),
            fact_id=value.get("fact_id", ""),
            evidence_span_id=value.get("evidence_span_id"),
            artifact_id=value.get("artifact_id"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            detail=value.get("detail"),
            content_sha256=value.get("content_sha256"),
        )


@dataclass(frozen=True, slots=True)
class AdmittedSubmissionFact:
    """A validated submission fact with exact support/counter edge ids."""

    fact: SubmissionFact
    artifact_id: str
    content_sha256: str
    value_digest: str | None
    field_name: str | None
    is_authoritative: bool
    support_edge_ids: tuple[str, ...]
    counter_edge_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.fact, SubmissionFact):
            raise TypeError("fact must be SubmissionFact")
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self, "value_digest", _optional_sha256(self.value_digest, "value_digest")
        )
        object.__setattr__(
            self, "field_name", _optional_str(self.field_name, "field_name", max_len=128)
        )
        if not isinstance(self.is_authoritative, bool):
            raise TypeError("is_authoritative must be bool")
        object.__setattr__(
            self,
            "support_edge_ids",
            _tuple_of_str(self.support_edge_ids, "support_edge_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "counter_edge_ids",
            _tuple_of_str(self.counter_edge_ids, "counter_edge_ids", max_items=64),
        )
        if not self.support_edge_ids and not self.counter_edge_ids:
            raise ValueError(
                "AdmittedSubmissionFact must retain at least one evidence edge"
            )

    @property
    def fact_id(self) -> str:
        return self.fact.fact_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "counter_edge_ids": list(self.counter_edge_ids),
            "fact": self.fact.to_dict(),
            "field_name": self.field_name,
            "is_authoritative": self.is_authoritative,
            "support_edge_ids": list(self.support_edge_ids),
            "value_digest": self.value_digest,
        }

    def public_projection(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "counter_edge_ids": list(self.counter_edge_ids),
            "evidence_span_id": self.fact.evidence_span_id,
            "extraction_status": self.fact.extraction_status,
            "fact_id": self.fact.fact_id,
            "fact_type": self.fact.fact_type,
            "field_name": self.field_name,
            "is_authoritative": self.is_authoritative,
            "support_edge_ids": list(self.support_edge_ids),
            "value_digest": self.value_digest,
            "version": self.fact.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdmittedSubmissionFact":
        if not isinstance(value, Mapping):
            raise TypeError("AdmittedSubmissionFact must be a mapping")
        fact_raw = value.get("fact") or {}
        fact = (
            fact_raw
            if isinstance(fact_raw, SubmissionFact)
            else SubmissionFact.from_dict(fact_raw)
        )
        return cls(
            fact=fact,
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256", ""),
            value_digest=value.get("value_digest"),
            field_name=value.get("field_name"),
            is_authoritative=bool(value.get("is_authoritative", False)),
            support_edge_ids=tuple(value.get("support_edge_ids") or ()),
            counter_edge_ids=tuple(value.get("counter_edge_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    """Affected document version reconstructed from admitted evidence."""

    artifact_id: str
    content_sha256: str
    version_label: str
    fact_ids: tuple[str, ...]
    claim_numbers: tuple[str, ...]
    span_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "version_label",
            _require_str(self.version_label, "version_label", max_len=128),
        )
        object.__setattr__(
            self, "fact_ids", _tuple_of_str(self.fact_ids, "fact_ids", max_items=512)
        )
        object.__setattr__(
            self,
            "claim_numbers",
            _tuple_of_str(self.claim_numbers, "claim_numbers", max_items=256),
        )
        object.__setattr__(
            self, "span_ids", _tuple_of_str(self.span_ids, "span_ids", max_items=1024)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "claim_numbers": list(self.claim_numbers),
            "content_sha256": self.content_sha256,
            "fact_ids": list(self.fact_ids),
            "span_ids": list(self.span_ids),
            "version_label": self.version_label,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentVersionRecord":
        if not isinstance(value, Mapping):
            raise TypeError("DocumentVersionRecord must be a mapping")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256", ""),
            version_label=value.get("version_label", "1"),
            fact_ids=tuple(value.get("fact_ids") or ()),
            claim_numbers=tuple(value.get("claim_numbers") or ()),
            span_ids=tuple(value.get("span_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class CounterEvidenceCandidate:
    """Optional explicit counter-evidence binding for a fact."""

    candidate_id: str
    against_fact_id: str
    span_id: str
    artifact_id: str
    content_sha256: str | None = None
    relation_note: str | None = None
    is_summary: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self,
            "against_fact_id",
            _identifier(self.against_fact_id, "against_fact_id"),
        )
        object.__setattr__(self, "span_id", _identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "relation_note",
            _optional_str(self.relation_note, "relation_note", max_len=256),
        )
        if not isinstance(self.is_summary, bool):
            raise TypeError("is_summary must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "against_fact_id": self.against_fact_id,
            "artifact_id": self.artifact_id,
            "candidate_id": self.candidate_id,
            "content_sha256": self.content_sha256,
            "is_summary": self.is_summary,
            "relation_note": self.relation_note,
            "span_id": self.span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterEvidenceCandidate":
        if not isinstance(value, Mapping):
            raise TypeError("CounterEvidenceCandidate must be a mapping")
        return cls(
            candidate_id=value.get("candidate_id", ""),
            against_fact_id=value.get("against_fact_id", ""),
            span_id=value.get("span_id", ""),
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256"),
            relation_note=value.get("relation_note"),
            is_summary=bool(value.get("is_summary", False)),
        )


@dataclass(frozen=True, slots=True)
class SubmissionEvidenceInput:
    """Inputs for submission fact admission and evidence mapping."""

    package_id: str
    facts: tuple[EnrichedSubmissionFact | SubmissionFact, ...] = ()
    spans: tuple[ExtractedSpan, ...] = ()
    # artifact_id -> content_sha256 (authoritative version registry)
    artifact_versions: Mapping[str, str] = field(default_factory=dict)
    # Optional version labels: artifact_id -> label
    artifact_version_labels: Mapping[str, str] = field(default_factory=dict)
    invalid_span_ids: tuple[str, ...] = ()
    stale_span_ids: tuple[str, ...] = ()
    # Expected content digests that must match registry when provided.
    expected_content_sha256_by_artifact: Mapping[str, str] = field(default_factory=dict)
    summary_fact_ids: tuple[str, ...] = ()
    counter_candidates: tuple[CounterEvidenceCandidate, ...] = ()
    claim_versions: tuple[ClaimVersion, ...] = ()
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = field(default_factory=dict)
    analysis_id: str | None = None
    matter_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        if not isinstance(self.facts, tuple):
            object.__setattr__(self, "facts", tuple(self.facts))
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        versions: dict[str, str] = {}
        for k, v in dict(self.artifact_versions or {}).items():
            aid = _identifier(str(k), "artifact_versions.key")
            versions[aid] = _require_sha256(v, "artifact_versions.value")
        object.__setattr__(self, "artifact_versions", MappingProxyType(versions))
        labels_v: dict[str, str] = {}
        for k, v in dict(self.artifact_version_labels or {}).items():
            aid = _identifier(str(k), "artifact_version_labels.key")
            labels_v[aid] = _require_str(str(v), "artifact_version_labels.value", max_len=128)
        object.__setattr__(
            self, "artifact_version_labels", MappingProxyType(labels_v)
        )
        object.__setattr__(
            self,
            "invalid_span_ids",
            _tuple_of_str(self.invalid_span_ids, "invalid_span_ids", max_items=2048),
        )
        object.__setattr__(
            self,
            "stale_span_ids",
            _tuple_of_str(self.stale_span_ids, "stale_span_ids", max_items=2048),
        )
        expected: dict[str, str] = {}
        for k, v in dict(self.expected_content_sha256_by_artifact or {}).items():
            aid = _identifier(str(k), "expected_content_sha256_by_artifact.key")
            expected[aid] = _require_sha256(
                v, "expected_content_sha256_by_artifact.value"
            )
        object.__setattr__(
            self, "expected_content_sha256_by_artifact", MappingProxyType(expected)
        )
        object.__setattr__(
            self,
            "summary_fact_ids",
            _tuple_of_str(self.summary_fact_ids, "summary_fact_ids", max_items=512),
        )
        if not isinstance(self.counter_candidates, tuple):
            object.__setattr__(
                self, "counter_candidates", tuple(self.counter_candidates)
            )
        if not isinstance(self.claim_versions, tuple):
            object.__setattr__(self, "claim_versions", tuple(self.claim_versions))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )


@dataclass(frozen=True, slots=True)
class SubmissionEvidenceMap:
    """Admitted facts plus exact support/counter-evidence edges."""

    schema_version: str
    map_id: str
    package_id: str
    disposition: EvidenceDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    admitted_facts: tuple[AdmittedSubmissionFact, ...]
    support_edges: tuple[EvidenceEdge, ...]
    counter_edges: tuple[EvidenceEdge, ...]
    excluded: tuple[ExcludedEvidence, ...]
    document_versions: tuple[DocumentVersionRecord, ...]
    claim_versions: tuple[ClaimVersion, ...]
    spans: tuple[ExtractedSpan, ...]
    artifact_bindings: tuple[ArtifactVersionBinding, ...]
    parser_versions: Mapping[str, str]
    labels: Mapping[str, str]
    analysis_id: str | None = None
    matter_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SUBMISSION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                "SubmissionEvidenceMap.schema_version must be "
                f"{SUBMISSION_EVIDENCE_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "map_id", _identifier(self.map_id, "map_id"))
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(EvidenceDisposition, self.disposition, "disposition"),
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
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        for attr in (
            "admitted_facts",
            "support_edges",
            "counter_edges",
            "excluded",
            "document_versions",
            "claim_versions",
            "spans",
            "artifact_bindings",
        ):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))
        object.__setattr__(
            self,
            "parser_versions",
            _frozen_str_map(self.parser_versions, "parser_versions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    # ---- Query helpers ----

    @property
    def is_empty(self) -> bool:
        return (
            not self.admitted_facts
            and not self.support_edges
            and not self.counter_edges
        )

    def edge_by_id(self, edge_id: str) -> EvidenceEdge | None:
        for edge in self.support_edges:
            if edge.edge_id == edge_id:
                return edge
        for edge in self.counter_edges:
            if edge.edge_id == edge_id:
                return edge
        return None

    def admitted_fact_by_id(self, fact_id: str) -> AdmittedSubmissionFact | None:
        for fact in self.admitted_facts:
            if fact.fact_id == fact_id:
                return fact
        return None

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def artifact_binding(self, artifact_id: str) -> ArtifactVersionBinding | None:
        for binding in self.artifact_bindings:
            if binding.artifact_id == artifact_id:
                return binding
        return None

    def support_edges_for_fact(self, fact_id: str) -> tuple[EvidenceEdge, ...]:
        return tuple(e for e in self.support_edges if e.fact_id == fact_id)

    def counter_edges_for_fact(self, fact_id: str) -> tuple[EvidenceEdge, ...]:
        return tuple(e for e in self.counter_edges if e.fact_id == fact_id)

    def resolve_edge(
        self, edge_id: str
    ) -> tuple[EvidenceEdge, ExtractedSpan, ArtifactVersionBinding] | None:
        """Round-trip an edge to its span and artifact version binding."""
        edge = self.edge_by_id(edge_id)
        if edge is None:
            return None
        span = self.span_by_id(edge.span_id)
        if span is None:
            return None
        binding = self.artifact_binding(edge.artifact_id)
        if binding is None:
            return None
        if span.artifact_id != edge.artifact_id:
            return None
        if binding.content_sha256 != edge.content_sha256:
            return None
        return edge, span, binding

    def all_edges_round_trip(self) -> bool:
        """True iff every support/counter edge resolves to its version/span."""
        for edge in (*self.support_edges, *self.counter_edges):
            resolved = self.resolve_edge(edge.edge_id)
            if resolved is None:
                return False
            r_edge, r_span, r_binding = resolved
            if r_edge.round_trip_key() != edge.round_trip_key():
                return False
            if r_span.span_id != edge.span_id:
                return False
            if r_binding.content_sha256 != edge.content_sha256:
                return False
        return True

    def fact_catalog_for_support_map(self) -> dict[str, dict[str, Any]]:
        """Build a SupportMapBuilder-compatible fact catalog from admitted facts."""
        catalog: dict[str, dict[str, Any]] = {}
        for admitted in self.admitted_facts:
            support_ids = [
                e.span_id for e in self.support_edges_for_fact(admitted.fact_id)
            ]
            catalog[admitted.fact_id] = {
                "predicate": (
                    f"{admitted.fact.fact_type}"
                    + (f":{admitted.field_name}" if admitted.field_name else "")
                ),
                "status": "supported" if support_ids else "alleged",
                "source_ids": support_ids,
                "attributes": {
                    "artifact_id": admitted.artifact_id,
                    "content_sha256": admitted.content_sha256,
                    "fact_type": admitted.fact.fact_type,
                    "version": admitted.fact.version,
                    "value_digest": admitted.value_digest,
                    "is_authoritative": admitted.is_authoritative,
                    "evidence_span_id": admitted.fact.evidence_span_id,
                    "counter_edge_ids": list(admitted.counter_edge_ids),
                    "support_edge_ids": list(admitted.support_edge_ids),
                },
            }
        return catalog

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_facts": [f.to_dict() for f in self.admitted_facts],
            "analysis_id": self.analysis_id,
            "artifact_bindings": [b.to_dict() for b in self.artifact_bindings],
            "claim_versions": [c.to_dict() for c in self.claim_versions],
            "classification": self.classification.value,
            "counter_edges": [e.to_dict() for e in self.counter_edges],
            "disposition": self.disposition.value,
            "document_versions": [d.to_dict() for d in self.document_versions],
            "excluded": [x.to_dict() for x in self.excluded],
            "labels": dict(self.labels),
            "map_id": self.map_id,
            "matter_id": self.matter_id,
            "package_id": self.package_id,
            "parser_versions": dict(self.parser_versions),
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "spans": [s.to_dict() for s in self.spans],
            "support_edges": [e.to_dict() for e in self.support_edges],
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers, digests, and edge keys only — never body text."""
        return {
            "admitted_fact_count": len(self.admitted_facts),
            "admitted_facts": [f.public_projection() for f in self.admitted_facts],
            "analysis_id": self.analysis_id,
            "artifact_bindings": [b.to_dict() for b in self.artifact_bindings],
            "classification": self.classification.value,
            "counter_edge_count": len(self.counter_edges),
            "counter_edge_ids": [e.edge_id for e in self.counter_edges],
            "disposition": self.disposition.value,
            "document_version_count": len(self.document_versions),
            "excluded": [
                {
                    "exclusion_id": x.exclusion_id,
                    "fact_id": x.fact_id,
                    "reason_codes": list(x.reason_codes),
                }
                for x in self.excluded
            ],
            "excluded_count": len(self.excluded),
            "map_id": self.map_id,
            "matter_id": self.matter_id,
            "package_id": self.package_id,
            "parser_versions": dict(self.parser_versions),
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_ids": [s.span_id for s in self.spans],
            "support_edge_count": len(self.support_edges),
            "support_edge_ids": [e.edge_id for e in self.support_edges],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionEvidenceMap":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionEvidenceMap must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SUBMISSION_EVIDENCE_SCHEMA_VERSION
            ),
            map_id=value.get("map_id", ""),
            package_id=value.get("package_id", ""),
            disposition=value.get("disposition", EvidenceDisposition.EMPTY.value),
            review_state=value.get("review_state", ReviewState.NOT_REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            admitted_facts=tuple(
                f
                if isinstance(f, AdmittedSubmissionFact)
                else AdmittedSubmissionFact.from_dict(f)
                for f in (value.get("admitted_facts") or ())
            ),
            support_edges=tuple(
                e if isinstance(e, EvidenceEdge) else EvidenceEdge.from_dict(e)
                for e in (value.get("support_edges") or ())
            ),
            counter_edges=tuple(
                e if isinstance(e, EvidenceEdge) else EvidenceEdge.from_dict(e)
                for e in (value.get("counter_edges") or ())
            ),
            excluded=tuple(
                x if isinstance(x, ExcludedEvidence) else ExcludedEvidence.from_dict(x)
                for x in (value.get("excluded") or ())
            ),
            document_versions=tuple(
                d
                if isinstance(d, DocumentVersionRecord)
                else DocumentVersionRecord.from_dict(d)
                for d in (value.get("document_versions") or ())
            ),
            claim_versions=tuple(
                c if isinstance(c, ClaimVersion) else ClaimVersion.from_dict(c)
                for c in (value.get("claim_versions") or ())
            ),
            spans=tuple(
                s if isinstance(s, ExtractedSpan) else ExtractedSpan.from_dict(s)
                for s in (value.get("spans") or ())
            ),
            artifact_bindings=tuple(
                b
                if isinstance(b, ArtifactVersionBinding)
                else ArtifactVersionBinding.from_dict(b)
                for b in (value.get("artifact_bindings") or ())
            ),
            parser_versions=value.get("parser_versions") or {},
            labels=value.get("labels") or {},
            analysis_id=value.get("analysis_id"),
            matter_id=value.get("matter_id"),
        )


# ---------------------------------------------------------------------------
# SupportMap adapter
# ---------------------------------------------------------------------------


class PatentSupportMapAdapter:
    """Typed adapter from admitted submission evidence to SupportMap structures.

    Does not own deontic rule compilation; it only projects exact admitted
    facts/edges into the reusable SupportMap catalog and entry shapes.
    """

    def __init__(self, *, builder: SupportMapBuilder | None = None) -> None:
        self._builder = builder or SupportMapBuilder()

    def to_fact_catalog(
        self, evidence_map: SubmissionEvidenceMap
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(evidence_map, SubmissionEvidenceMap):
            raise TypeError("evidence_map must be SubmissionEvidenceMap")
        return evidence_map.fact_catalog_for_support_map()

    def to_support_facts(
        self, evidence_map: SubmissionEvidenceMap
    ) -> tuple[SupportFact, ...]:
        catalog = self.to_fact_catalog(evidence_map)
        facts: list[SupportFact] = []
        for fact_id, entry in catalog.items():
            facts.append(
                SupportFact(
                    fact_id=fact_id,
                    predicate=str(entry.get("predicate") or fact_id),
                    status=str(entry.get("status") or "alleged"),
                    source_ids=list(entry.get("source_ids") or []),
                    attributes=dict(entry.get("attributes") or {}),
                )
            )
        return tuple(facts)

    def to_motion_support_map(
        self,
        evidence_map: SubmissionEvidenceMap,
        *,
        rule_id_prefix: str = "submission-fact",
    ) -> MotionSupportMap:
        """Project each admitted fact as a SupportMapEntry (rule-centered view).

        When a deontic graph is unavailable, each admitted fact becomes its own
        entry so downstream compliance can bind requirements later without
        inventing support from empty input.
        """
        if not isinstance(evidence_map, SubmissionEvidenceMap):
            raise TypeError("evidence_map must be SubmissionEvidenceMap")
        entries: list[SupportMapEntry] = []
        for admitted in evidence_map.admitted_facts:
            support_span_ids = [
                e.span_id
                for e in evidence_map.support_edges_for_fact(admitted.fact_id)
            ]
            counter_span_ids = [
                e.span_id
                for e in evidence_map.counter_edges_for_fact(admitted.fact_id)
            ]
            support_fact = SupportFact(
                fact_id=admitted.fact_id,
                predicate=(
                    f"{admitted.fact.fact_type}"
                    + (f":{admitted.field_name}" if admitted.field_name else "")
                ),
                status="supported" if support_span_ids else "alleged",
                source_ids=list(support_span_ids),
                attributes={
                    "artifact_id": admitted.artifact_id,
                    "content_sha256": admitted.content_sha256,
                    "version": admitted.fact.version,
                    "counter_source_ids": list(counter_span_ids),
                    "is_authoritative": admitted.is_authoritative,
                },
            )
            entries.append(
                SupportMapEntry(
                    rule_id=f"{rule_id_prefix}:{admitted.fact_id}",
                    target_id=admitted.fact_id,
                    target_label=admitted.fact.fact_type,
                    modality="assertion",
                    predicate=support_fact.predicate,
                    active=True,
                    facts=[support_fact],
                    filings=[],
                    authority_ids=[],
                    evidence_ids=list(support_span_ids) + list(counter_span_ids),
                )
            )
        return MotionSupportMap(entries=entries)

    def build_from_deontic_graph(
        self,
        evidence_map: SubmissionEvidenceMap,
        graph: Any,
        *,
        filing_map: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        only_active: bool = True,
    ) -> MotionSupportMap:
        """Delegate to SupportMapBuilder with the admitted fact catalog."""
        catalog = self.to_fact_catalog(evidence_map)
        return self._builder.build_from_deontic_graph(
            graph,
            fact_catalog=catalog,
            filing_map=filing_map,
            only_active=only_active,
        )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class SubmissionEvidenceBuilder:
    """Admit validated submission facts and map exact support/counter edges."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        support_adapter: PatentSupportMapAdapter | None = None,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory
        self._support_adapter = support_adapter or PatentSupportMapAdapter()

    @property
    def support_adapter(self) -> PatentSupportMapAdapter:
        return self._support_adapter

    def build_from_analysis(
        self,
        analysis: SubmissionAnalysisResult,
        *,
        artifact_versions: Mapping[str, str],
        artifact_version_labels: Mapping[str, str] | None = None,
        invalid_span_ids: Sequence[str] = (),
        stale_span_ids: Sequence[str] = (),
        expected_content_sha256_by_artifact: Mapping[str, str] | None = None,
        summary_fact_ids: Sequence[str] = (),
        counter_candidates: Sequence[CounterEvidenceCandidate | Mapping[str, Any]] = (),
    ) -> SubmissionEvidenceMap:
        """Build an evidence map from a PATLAW-033 analysis result."""
        if not isinstance(analysis, SubmissionAnalysisResult):
            raise TypeError("analysis must be SubmissionAnalysisResult")
        counters = tuple(
            c
            if isinstance(c, CounterEvidenceCandidate)
            else CounterEvidenceCandidate.from_dict(c)
            for c in counter_candidates
        )
        inp = SubmissionEvidenceInput(
            package_id=analysis.package_id,
            facts=tuple(analysis.facts),
            spans=tuple(analysis.spans),
            artifact_versions=dict(artifact_versions),
            artifact_version_labels=dict(artifact_version_labels or {}),
            invalid_span_ids=tuple(invalid_span_ids),
            stale_span_ids=tuple(stale_span_ids),
            expected_content_sha256_by_artifact=dict(
                expected_content_sha256_by_artifact or {}
            ),
            summary_fact_ids=tuple(summary_fact_ids),
            counter_candidates=counters,
            claim_versions=tuple(analysis.claim_versions),
            classification=analysis.classification,
            labels=dict(analysis.labels),
            analysis_id=analysis.analysis_id,
            matter_id=analysis.matter_id,
        )
        return self.build(inp)

    def build(
        self,
        source: SubmissionEvidenceInput
        | SubmissionAnalysisResult
        | Mapping[str, Any],
        *,
        artifact_versions: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> SubmissionEvidenceMap:
        if isinstance(source, SubmissionAnalysisResult):
            if artifact_versions is None:
                raise SubmissionEvidenceError(
                    "artifact_versions required when building from analysis",
                    code="missing_artifact_versions",
                )
            return self.build_from_analysis(
                source, artifact_versions=artifact_versions, **kwargs
            )
        if isinstance(source, Mapping):
            source = self._input_from_mapping(source)
        if not isinstance(source, SubmissionEvidenceInput):
            raise TypeError(
                "source must be SubmissionEvidenceInput, "
                "SubmissionAnalysisResult, or mapping"
            )
        return self._build(source)

    def _input_from_mapping(self, value: Mapping[str, Any]) -> SubmissionEvidenceInput:
        facts_raw = value.get("facts") or ()
        facts: list[EnrichedSubmissionFact | SubmissionFact] = []
        for f in facts_raw:
            if isinstance(f, (EnrichedSubmissionFact, SubmissionFact)):
                facts.append(f)
            elif isinstance(f, Mapping) and "fact" in f:
                facts.append(EnrichedSubmissionFact.from_dict(f))
            elif isinstance(f, Mapping):
                facts.append(SubmissionFact.from_dict(f))
            else:
                raise TypeError("facts entries must be mappings or fact records")
        spans = tuple(
            s if isinstance(s, ExtractedSpan) else ExtractedSpan.from_dict(s)
            for s in (value.get("spans") or ())
        )
        counters = tuple(
            c
            if isinstance(c, CounterEvidenceCandidate)
            else CounterEvidenceCandidate.from_dict(c)
            for c in (value.get("counter_candidates") or ())
        )
        claim_versions = tuple(
            c if isinstance(c, ClaimVersion) else ClaimVersion.from_dict(c)
            for c in (value.get("claim_versions") or ())
        )
        return SubmissionEvidenceInput(
            package_id=value.get("package_id", ""),
            facts=tuple(facts),
            spans=spans,
            artifact_versions=value.get("artifact_versions") or {},
            artifact_version_labels=value.get("artifact_version_labels") or {},
            invalid_span_ids=tuple(value.get("invalid_span_ids") or ()),
            stale_span_ids=tuple(value.get("stale_span_ids") or ()),
            expected_content_sha256_by_artifact=value.get(
                "expected_content_sha256_by_artifact"
            )
            or {},
            summary_fact_ids=tuple(value.get("summary_fact_ids") or ()),
            counter_candidates=counters,
            claim_versions=claim_versions,
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
            analysis_id=value.get("analysis_id"),
            matter_id=value.get("matter_id"),
        )

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}:{self._id_factory()}"

    def _unwrap_fact(
        self, raw: EnrichedSubmissionFact | SubmissionFact
    ) -> tuple[SubmissionFact, str | None, str | None, str | None, bool]:
        """Return (fact, artifact_id, value_digest, field_name, is_authoritative)."""
        if isinstance(raw, EnrichedSubmissionFact):
            return (
                raw.fact,
                raw.artifact_id,
                raw.value_digest,
                raw.field_name,
                raw.is_authoritative,
            )
        if isinstance(raw, SubmissionFact):
            return raw, None, None, None, False
        raise TypeError("fact must be EnrichedSubmissionFact or SubmissionFact")

    def _build(self, inp: SubmissionEvidenceInput) -> SubmissionEvidenceMap:
        map_id = self._new_id("evmap")
        reason_codes: list[str] = []
        warnings: list[str] = []
        excluded: list[ExcludedEvidence] = []
        support_edges: list[EvidenceEdge] = []
        counter_edges: list[EvidenceEdge] = []
        admitted: list[AdmittedSubmissionFact] = []

        span_by_id: dict[str, ExtractedSpan] = {}
        for span in inp.spans:
            if not isinstance(span, ExtractedSpan):
                raise TypeError("spans must be ExtractedSpan instances")
            if span.span_id in span_by_id:
                warnings.append(f"duplicate_span_id:{span.span_id}")
            span_by_id[span.span_id] = span

        invalid_ids = set(inp.invalid_span_ids)
        stale_ids = set(inp.stale_span_ids)
        summary_ids = set(inp.summary_fact_ids)

        # Empty submission: no implicit support.
        if not inp.facts:
            reason_codes.append(EvidenceReasonCode.EMPTY_NO_IMPLICIT_SUPPORT.value)
            if ExclusionReasonCode.EMPTY_SUBMISSION.value not in reason_codes:
                reason_codes.append(ExclusionReasonCode.EMPTY_SUBMISSION.value)
            return SubmissionEvidenceMap(
                schema_version=SUBMISSION_EVIDENCE_SCHEMA_VERSION,
                map_id=map_id,
                package_id=inp.package_id,
                disposition=EvidenceDisposition.EMPTY,
                review_state=(
                    ReviewState.REQUIRED
                    if requires_quarantine(inp.classification)
                    else ReviewState.NOT_REQUIRED
                ),
                classification=inp.classification,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                warnings=tuple(warnings),
                admitted_facts=(),
                support_edges=(),
                counter_edges=(),
                excluded=(),
                document_versions=(),
                claim_versions=tuple(inp.claim_versions),
                spans=tuple(inp.spans),
                artifact_bindings=self._bindings_from_registry(inp),
                parser_versions={"submission_evidence": PARSER_VERSION},
                labels=dict(inp.labels),
                analysis_id=inp.analysis_id,
                matter_id=inp.matter_id,
            )

        # First pass: attempt admission of each fact as support evidence.
        pending_counter_sources: list[
            tuple[SubmissionFact, str, str, str | None, str | None, bool]
        ] = []
        # (fact, artifact_id, content_sha256, value_digest, field_name, is_auth)

        field_groups: dict[str, list[str]] = {}  # field_key -> fact_ids (for ambiguity)

        for raw in inp.facts:
            fact, artifact_id, value_digest, field_name, is_authoritative = (
                self._unwrap_fact(raw)
            )
            span_id = fact.evidence_span_id
            reasons: list[str] = []

            # Summaries are never exact evidence.
            if fact.fact_id in summary_ids or fact.fact_type in _SUMMARY_FACT_TYPES:
                reasons.append(ExclusionReasonCode.SUMMARY_NOT_EVIDENCE.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=artifact_id,
                        reason_codes=tuple(reasons),
                        detail="summaries_are_not_exact_evidence",
                    )
                )
                continue

            # Extraction status gate.
            if fact.extraction_status in _EXCLUDED_EXTRACTION_STATUSES:
                reasons.append(ExclusionReasonCode.EXTRACTION_STATUS_EXCLUDED.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=artifact_id,
                        reason_codes=tuple(reasons),
                        detail=f"extraction_status={fact.extraction_status}",
                    )
                )
                continue

            # Resolve span.
            span = span_by_id.get(span_id)
            if span is None:
                reasons.append(ExclusionReasonCode.MISSING_SPAN.value)
                reasons.append(ExclusionReasonCode.FACT_SPAN_UNRESOLVED.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=artifact_id,
                        reason_codes=tuple(dict.fromkeys(reasons)),
                        detail="evidence_span_not_in_catalog",
                    )
                )
                continue

            if span_id in invalid_ids:
                reasons.append(ExclusionReasonCode.INVALID_SPAN.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=artifact_id or span.artifact_id,
                        reason_codes=tuple(reasons),
                        detail="span_marked_invalid",
                    )
                )
                continue

            if span_id in stale_ids:
                reasons.append(ExclusionReasonCode.STALE_SPAN.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=artifact_id or span.artifact_id,
                        reason_codes=tuple(reasons),
                        detail="span_marked_stale",
                    )
                )
                continue

            # Bind artifact identity: prefer enriched fact, else span.
            resolved_artifact = artifact_id or span.artifact_id
            if not resolved_artifact:
                reasons.append(ExclusionReasonCode.ARTIFACT_UNKNOWN.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=None,
                        reason_codes=tuple(reasons),
                        detail="no_artifact_id",
                    )
                )
                continue

            if span.artifact_id != resolved_artifact:
                reasons.append(ExclusionReasonCode.SPAN_ARTIFACT_MISMATCH.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=resolved_artifact,
                        reason_codes=tuple(reasons),
                        detail=(
                            f"span_artifact={span.artifact_id}"
                            f";fact_artifact={resolved_artifact}"
                        ),
                    )
                )
                continue

            # Artifact version binding is mandatory for admission.
            content_sha256 = inp.artifact_versions.get(resolved_artifact)
            if content_sha256 is None:
                reasons.append(ExclusionReasonCode.MISSING_ARTIFACT_VERSION.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=resolved_artifact,
                        reason_codes=tuple(reasons),
                        detail="artifact_not_in_version_registry",
                    )
                )
                continue

            expected = inp.expected_content_sha256_by_artifact.get(resolved_artifact)
            if expected is not None and expected != content_sha256:
                reasons.append(ExclusionReasonCode.ARTIFACT_VERSION_MISMATCH.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=resolved_artifact,
                        reason_codes=tuple(reasons),
                        detail="expected_content_sha256_mismatch",
                        content_sha256=content_sha256,
                    )
                )
                continue

            # Span must have character bounds for "exact" evidence.
            if span.char_start is None or span.char_end is None:
                reasons.append(ExclusionReasonCode.NO_EXACT_SPAN.value)
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=span_id,
                        artifact_id=resolved_artifact,
                        reason_codes=tuple(reasons),
                        detail="missing_char_bounds",
                        content_sha256=content_sha256,
                    )
                )
                continue

            # Track field groups for later ambiguity detection.
            if field_name:
                key = f"{field_name}@{resolved_artifact}@{fact.version}"
                field_groups.setdefault(key, []).append(fact.fact_id)

            # Mismatched extraction status is eligible as counter, not support.
            if fact.extraction_status == FactExtractionStatus.MISMATCHED.value:
                pending_counter_sources.append(
                    (
                        fact,
                        resolved_artifact,
                        content_sha256,
                        value_digest,
                        field_name,
                        is_authoritative,
                    )
                )
                continue

            # Admit support edge.
            edge = EvidenceEdge(
                edge_id=self._new_id("edge"),
                fact_id=fact.fact_id,
                span_id=span.span_id,
                artifact_id=resolved_artifact,
                content_sha256=content_sha256,
                role=EvidenceEdgeRole.SUPPORT,
                fact_type=fact.fact_type,
                fact_version=fact.version,
                page_index=span.page_index,
                char_start=span.char_start,
                char_end=span.char_end,
                text_digest=span.text_digest,
                field_name=field_name,
                relation_note="exact_support",
            )
            support_edges.append(edge)
            admitted.append(
                AdmittedSubmissionFact(
                    fact=fact,
                    artifact_id=resolved_artifact,
                    content_sha256=content_sha256,
                    value_digest=value_digest,
                    field_name=field_name,
                    is_authoritative=is_authoritative,
                    support_edge_ids=(edge.edge_id,),
                    counter_edge_ids=(),
                )
            )

        # Ambiguity: same field_name@artifact@version with multiple distinct
        # value digests among admitted support facts → exclude all in group.
        if field_groups:
            admitted_by_id = {a.fact_id: a for a in admitted}
            ambiguous_fact_ids: set[str] = set()
            for _key, fact_ids in field_groups.items():
                digests = {
                    admitted_by_id[fid].value_digest
                    for fid in fact_ids
                    if fid in admitted_by_id
                    and admitted_by_id[fid].value_digest is not None
                }
                if len(digests) > 1:
                    for fid in fact_ids:
                        if fid in admitted_by_id:
                            ambiguous_fact_ids.add(fid)

            if ambiguous_fact_ids:
                # Demote ambiguous admitted facts to excluded; drop their edges.
                remaining_admitted: list[AdmittedSubmissionFact] = []
                drop_edge_ids: set[str] = set()
                for a in admitted:
                    if a.fact_id in ambiguous_fact_ids:
                        drop_edge_ids.update(a.support_edge_ids)
                        excluded.append(
                            ExcludedEvidence(
                                exclusion_id=self._new_id("excl"),
                                fact_id=a.fact_id,
                                evidence_span_id=a.fact.evidence_span_id,
                                artifact_id=a.artifact_id,
                                reason_codes=(
                                    ExclusionReasonCode.AMBIGUOUS_EVIDENCE.value,
                                    ExclusionReasonCode.DUPLICATE_FACT_AMBIGUOUS.value,
                                ),
                                detail="conflicting_value_digests_same_field_version",
                                content_sha256=a.content_sha256,
                            )
                        )
                    else:
                        remaining_admitted.append(a)
                admitted = remaining_admitted
                support_edges = [
                    e for e in support_edges if e.edge_id not in drop_edge_ids
                ]

        # Process mismatched facts as counter-evidence against matching admitted
        # facts (same field_name when available; otherwise same fact_type+claims).
        admitted_index = list(admitted)
        for (
            fact,
            resolved_artifact,
            content_sha256,
            value_digest,
            field_name,
            is_authoritative,
        ) in pending_counter_sources:
            span = span_by_id[fact.evidence_span_id]
            targets = self._counter_targets(
                admitted_index, field_name=field_name, fact=fact
            )
            if not targets:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=fact.fact_id,
                        evidence_span_id=fact.evidence_span_id,
                        artifact_id=resolved_artifact,
                        reason_codes=(
                            ExclusionReasonCode.COUNTER_CANDIDATE_INVALID.value,
                        ),
                        detail="mismatched_fact_no_support_target",
                        content_sha256=content_sha256,
                    )
                )
                continue
            for target in targets:
                edge = EvidenceEdge(
                    edge_id=self._new_id("edge"),
                    fact_id=target.fact_id,
                    span_id=span.span_id,
                    artifact_id=resolved_artifact,
                    content_sha256=content_sha256,
                    role=EvidenceEdgeRole.COUNTER,
                    fact_type=fact.fact_type,
                    fact_version=fact.version,
                    page_index=span.page_index,
                    char_start=span.char_start,
                    char_end=span.char_end,
                    text_digest=span.text_digest,
                    field_name=field_name,
                    relation_note=f"counter_from:{fact.fact_id}",
                )
                counter_edges.append(edge)
                # Rewrite admitted fact with new counter edge id.
                self._attach_counter_edge(admitted, target.fact_id, edge.edge_id)

        # Explicit counter candidates.
        for candidate in inp.counter_candidates:
            if candidate.is_summary:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(ExclusionReasonCode.SUMMARY_NOT_EVIDENCE.value,),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                    )
                )
                continue
            target = next(
                (a for a in admitted if a.fact_id == candidate.against_fact_id),
                None,
            )
            if target is None:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(
                            ExclusionReasonCode.COUNTER_CANDIDATE_INVALID.value,
                        ),
                        detail=f"no_admitted_target:{candidate.candidate_id}",
                    )
                )
                continue
            span = span_by_id.get(candidate.span_id)
            if span is None:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(ExclusionReasonCode.MISSING_SPAN.value,),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                    )
                )
                continue
            if candidate.span_id in invalid_ids:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(ExclusionReasonCode.INVALID_SPAN.value,),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                    )
                )
                continue
            if candidate.span_id in stale_ids:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(ExclusionReasonCode.STALE_SPAN.value,),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                    )
                )
                continue
            if span.artifact_id != candidate.artifact_id:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(
                            ExclusionReasonCode.SPAN_ARTIFACT_MISMATCH.value,
                        ),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                    )
                )
                continue
            content_sha256 = (
                candidate.content_sha256
                or inp.artifact_versions.get(candidate.artifact_id)
            )
            if content_sha256 is None:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(
                            ExclusionReasonCode.MISSING_ARTIFACT_VERSION.value,
                        ),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                    )
                )
                continue
            if span.char_start is None or span.char_end is None:
                excluded.append(
                    ExcludedEvidence(
                        exclusion_id=self._new_id("excl"),
                        fact_id=candidate.against_fact_id,
                        evidence_span_id=candidate.span_id,
                        artifact_id=candidate.artifact_id,
                        reason_codes=(ExclusionReasonCode.NO_EXACT_SPAN.value,),
                        detail=f"counter_candidate:{candidate.candidate_id}",
                        content_sha256=content_sha256,
                    )
                )
                continue
            edge = EvidenceEdge(
                edge_id=self._new_id("edge"),
                fact_id=target.fact_id,
                span_id=span.span_id,
                artifact_id=candidate.artifact_id,
                content_sha256=content_sha256,
                role=EvidenceEdgeRole.COUNTER,
                fact_type=target.fact.fact_type,
                fact_version=target.fact.version,
                page_index=span.page_index,
                char_start=span.char_start,
                char_end=span.char_end,
                text_digest=span.text_digest,
                field_name=target.field_name,
                relation_note=candidate.relation_note
                or f"explicit_counter:{candidate.candidate_id}",
            )
            counter_edges.append(edge)
            self._attach_counter_edge(admitted, target.fact_id, edge.edge_id)

        # Document / claim version reconstruction from admitted evidence.
        document_versions = self._reconstruct_document_versions(admitted, support_edges, inp)
        claim_versions = tuple(inp.claim_versions)

        if admitted:
            reason_codes.append(EvidenceReasonCode.FACTS_ADMITTED.value)
        if support_edges:
            reason_codes.append(EvidenceReasonCode.SUPPORT_EDGES_MAPPED.value)
        if counter_edges:
            reason_codes.append(EvidenceReasonCode.COUNTER_EDGES_MAPPED.value)
        if excluded:
            reason_codes.append(EvidenceReasonCode.EXCLUSIONS_RECORDED.value)
        if document_versions:
            reason_codes.append(EvidenceReasonCode.DOCUMENT_VERSIONS_BOUND.value)
        if claim_versions:
            reason_codes.append(EvidenceReasonCode.CLAIM_VERSIONS_RECONSTRUCTED.value)

        disposition, review_state = self._disposition(
            admitted=admitted,
            excluded=excluded,
            support_edges=support_edges,
            classification=inp.classification,
            input_fact_count=len(inp.facts),
        )
        if review_state in (ReviewState.REQUIRED, ReviewState.PENDING):
            reason_codes.append(EvidenceReasonCode.REVIEW_REQUIRED.value)

        # Retain only spans referenced by edges (plus all input spans for RT).
        referenced_span_ids = {
            e.span_id for e in (*support_edges, *counter_edges)
        }
        # Keep full catalog for round-trip of edges; also keep admitted fact spans.
        retained_spans = tuple(inp.spans)

        result = SubmissionEvidenceMap(
            schema_version=SUBMISSION_EVIDENCE_SCHEMA_VERSION,
            map_id=map_id,
            package_id=inp.package_id,
            disposition=disposition,
            review_state=review_state,
            classification=inp.classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            admitted_facts=tuple(admitted),
            support_edges=tuple(support_edges),
            counter_edges=tuple(counter_edges),
            excluded=tuple(excluded),
            document_versions=tuple(document_versions),
            claim_versions=claim_versions,
            spans=retained_spans,
            artifact_bindings=self._bindings_from_registry(inp),
            parser_versions={"submission_evidence": PARSER_VERSION},
            labels=dict(inp.labels),
            analysis_id=inp.analysis_id,
            matter_id=inp.matter_id,
        )

        # Invariant: every edge must round-trip; fail closed if not.
        if not result.all_edges_round_trip():
            raise SubmissionEvidenceError(
                "internal invariant: evidence edge failed artifact/span round-trip",
                code="edge_round_trip_failed",
            )

        # Silence unused (referenced_span_ids kept for future pruning option).
        _ = referenced_span_ids
        return result

    def _bindings_from_registry(
        self, inp: SubmissionEvidenceInput
    ) -> tuple[ArtifactVersionBinding, ...]:
        bindings: list[ArtifactVersionBinding] = []
        for artifact_id, digest in sorted(inp.artifact_versions.items()):
            bindings.append(
                ArtifactVersionBinding(
                    artifact_id=artifact_id,
                    content_sha256=digest,
                    version_label=inp.artifact_version_labels.get(artifact_id),
                )
            )
        return tuple(bindings)

    def _counter_targets(
        self,
        admitted: Sequence[AdmittedSubmissionFact],
        *,
        field_name: str | None,
        fact: SubmissionFact,
    ) -> list[AdmittedSubmissionFact]:
        if field_name:
            matches = [a for a in admitted if a.field_name == field_name]
            if matches:
                return matches
        # Fall back: same fact_type and overlapping affected claims.
        claims = set(fact.affected_claims)
        matches = []
        for a in admitted:
            if a.fact.fact_type != fact.fact_type:
                continue
            if claims and claims.isdisjoint(set(a.fact.affected_claims)):
                continue
            matches.append(a)
        return matches

    def _attach_counter_edge(
        self,
        admitted: list[AdmittedSubmissionFact],
        fact_id: str,
        edge_id: str,
    ) -> None:
        for i, a in enumerate(admitted):
            if a.fact_id == fact_id:
                admitted[i] = AdmittedSubmissionFact(
                    fact=a.fact,
                    artifact_id=a.artifact_id,
                    content_sha256=a.content_sha256,
                    value_digest=a.value_digest,
                    field_name=a.field_name,
                    is_authoritative=a.is_authoritative,
                    support_edge_ids=a.support_edge_ids,
                    counter_edge_ids=a.counter_edge_ids + (edge_id,),
                )
                return

    def _reconstruct_document_versions(
        self,
        admitted: Sequence[AdmittedSubmissionFact],
        support_edges: Sequence[EvidenceEdge],
        inp: SubmissionEvidenceInput,
    ) -> list[DocumentVersionRecord]:
        by_artifact: dict[str, dict[str, Any]] = {}
        edges_by_fact = {e.fact_id: e for e in support_edges}
        for a in admitted:
            rec = by_artifact.setdefault(
                a.artifact_id,
                {
                    "content_sha256": a.content_sha256,
                    "version_label": inp.artifact_version_labels.get(
                        a.artifact_id, a.fact.version
                    ),
                    "fact_ids": [],
                    "claim_numbers": set(),
                    "span_ids": set(),
                },
            )
            rec["fact_ids"].append(a.fact_id)
            for claim in a.fact.affected_claims:
                rec["claim_numbers"].add(claim)
            edge = edges_by_fact.get(a.fact_id)
            if edge is not None:
                rec["span_ids"].add(edge.span_id)
            else:
                rec["span_ids"].add(a.fact.evidence_span_id)
        out: list[DocumentVersionRecord] = []
        for artifact_id, rec in sorted(by_artifact.items()):
            out.append(
                DocumentVersionRecord(
                    artifact_id=artifact_id,
                    content_sha256=rec["content_sha256"],
                    version_label=str(rec["version_label"]),
                    fact_ids=tuple(rec["fact_ids"]),
                    claim_numbers=tuple(sorted(rec["claim_numbers"])),
                    span_ids=tuple(sorted(rec["span_ids"])),
                )
            )
        return out

    def _disposition(
        self,
        *,
        admitted: Sequence[AdmittedSubmissionFact],
        excluded: Sequence[ExcludedEvidence],
        support_edges: Sequence[EvidenceEdge],
        classification: DisclosureClassification,
        input_fact_count: int,
    ) -> tuple[EvidenceDisposition, ReviewState]:
        if requires_quarantine(classification):
            return EvidenceDisposition.REVIEW, ReviewState.REQUIRED
        if not admitted and not support_edges:
            if input_fact_count > 0:
                # All candidates excluded → partial/review, not implicit empty pass.
                return EvidenceDisposition.REVIEW, ReviewState.REQUIRED
            return EvidenceDisposition.EMPTY, ReviewState.NOT_REQUIRED
        if excluded:
            return EvidenceDisposition.PARTIAL, ReviewState.NOT_REQUIRED
        return EvidenceDisposition.MAPPED, ReviewState.NOT_REQUIRED


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------


def build_submission_evidence_map(
    source: SubmissionEvidenceInput
    | SubmissionAnalysisResult
    | Mapping[str, Any],
    *,
    artifact_versions: Mapping[str, str] | None = None,
    id_factory: Callable[[], str] | None = None,
    **kwargs: Any,
) -> SubmissionEvidenceMap:
    """Build a submission evidence map (convenience wrapper)."""
    return SubmissionEvidenceBuilder(id_factory=id_factory).build(
        source, artifact_versions=artifact_versions, **kwargs
    )


def admit_submission_facts(
    facts: Sequence[EnrichedSubmissionFact | SubmissionFact | Mapping[str, Any]],
    spans: Sequence[ExtractedSpan | Mapping[str, Any]],
    *,
    package_id: str,
    artifact_versions: Mapping[str, str],
    invalid_span_ids: Sequence[str] = (),
    stale_span_ids: Sequence[str] = (),
    summary_fact_ids: Sequence[str] = (),
    counter_candidates: Sequence[CounterEvidenceCandidate | Mapping[str, Any]] = (),
    claim_versions: Sequence[ClaimVersion | Mapping[str, Any]] = (),
    classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_USER,
    id_factory: Callable[[], str] | None = None,
    **kwargs: Any,
) -> SubmissionEvidenceMap:
    """Admit facts against a span catalog and artifact version registry."""
    coerced_facts: list[EnrichedSubmissionFact | SubmissionFact] = []
    for f in facts:
        if isinstance(f, (EnrichedSubmissionFact, SubmissionFact)):
            coerced_facts.append(f)
        elif isinstance(f, Mapping) and "fact" in f:
            coerced_facts.append(EnrichedSubmissionFact.from_dict(f))
        elif isinstance(f, Mapping):
            coerced_facts.append(SubmissionFact.from_dict(f))
        else:
            raise TypeError("unsupported fact type")
    coerced_spans = tuple(
        s if isinstance(s, ExtractedSpan) else ExtractedSpan.from_dict(s)
        for s in spans
    )
    counters = tuple(
        c
        if isinstance(c, CounterEvidenceCandidate)
        else CounterEvidenceCandidate.from_dict(c)
        for c in counter_candidates
    )
    claims = tuple(
        c if isinstance(c, ClaimVersion) else ClaimVersion.from_dict(c)
        for c in claim_versions
    )
    inp = SubmissionEvidenceInput(
        package_id=package_id,
        facts=tuple(coerced_facts),
        spans=coerced_spans,
        artifact_versions=dict(artifact_versions),
        invalid_span_ids=tuple(invalid_span_ids),
        stale_span_ids=tuple(stale_span_ids),
        summary_fact_ids=tuple(summary_fact_ids),
        counter_candidates=counters,
        claim_versions=claims,
        classification=_coerce_classification(classification),
        **{
            k: v
            for k, v in kwargs.items()
            if k
            in {
                "artifact_version_labels",
                "expected_content_sha256_by_artifact",
                "labels",
                "analysis_id",
                "matter_id",
            }
        },
    )
    return SubmissionEvidenceBuilder(id_factory=id_factory).build(inp)


__all__ = [
    "PARSER_VERSION",
    "SUBMISSION_EVIDENCE_INTERFACE",
    "SUBMISSION_EVIDENCE_SCHEMA_VERSION",
    "AdmittedSubmissionFact",
    "ArtifactVersionBinding",
    "CounterEvidenceCandidate",
    "DocumentVersionRecord",
    "EvidenceDisposition",
    "EvidenceEdge",
    "EvidenceEdgeRole",
    "EvidenceReasonCode",
    "ExcludedEvidence",
    "ExclusionReasonCode",
    "PatentSupportMapAdapter",
    "SubmissionEvidenceBuilder",
    "SubmissionEvidenceError",
    "SubmissionEvidenceInput",
    "SubmissionEvidenceMap",
    "admit_submission_facts",
    "build_submission_evidence_map",
    "sha256_hex",
]
