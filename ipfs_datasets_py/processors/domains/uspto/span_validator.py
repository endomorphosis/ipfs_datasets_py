"""USPTO span coverage, readability, and disagreement validation (PATLAW-034).

Validates extraction provenance before any semantic consumer may rely on spans:

* span bounds (page index, character offsets, optional bbox geometry);
* source hashes (text digests, render digests, artifact content digests);
* complete page coverage (every page index accounted for);
* reading-order consistency within a page;
* native/OCR discrepancy retention (disagreement is never silently dropped);
* quote round-trip (char offsets re-hash to the stored text_digest);
* minimum readability / coverage policy (low quality → unknown/review);
* semantic citation binding (no fact/assessment may cite a missing or
  mismatched artifact version).

Document body text is never written to logs or exception messages.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Sequence,
)

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    SubmissionFact,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    DOCUMENT_EXTRACTION_SCHEMA_VERSION,
    DocumentExtractionResult,
    ExtractionDisposition,
    MediaFamily,
    PageCoverageRecord,
    PageStatus,
    text_similarity,
)

SPAN_VALIDATOR_SCHEMA_VERSION: Final = "uspto.span-validator.v1"
SPAN_VALIDATOR_INTERFACE: Final = "SpanValidator@1"

# ---------------------------------------------------------------------------
# Defaults (policy)
# ---------------------------------------------------------------------------

DEFAULT_MIN_COVERAGE_RATIO: Final = 0.35
DEFAULT_MIN_OVERALL_COVERAGE: Final = 0.5
DEFAULT_MIN_READABILITY: Final = 0.25
DEFAULT_MIN_QUOTE_SIMILARITY: Final = 1.0  # exact digest match for round-trip
DEFAULT_DISAGREEMENT_REVIEW_SCORE: Final = 0.15
DEFAULT_MAX_FINDINGS: Final = 512
DEFAULT_MAX_CITATIONS: Final = 1024
DEFAULT_MIN_NATIVE_CHARS: Final = 40

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SpanValidationDisposition(str, Enum):
    """Outcome of span assurance validation."""

    VALID = "valid"
    REVIEW = "review"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class FindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SpanValidationReasonCode(str, Enum):
    SPAN_BOUNDS_OK = "span_bounds_ok"
    SPAN_BOUNDS_INVALID = "span_bounds_invalid"
    STALE_SPAN = "stale_span"
    TEXT_DIGEST_MISMATCH = "text_digest_mismatch"
    RENDER_DIGEST_MISSING = "render_digest_missing"
    PAGE_COVERAGE_COMPLETE = "page_coverage_complete"
    UNACCOUNTED_PAGE = "unaccounted_page"
    DUPLICATE_PAGE_INDEX = "duplicate_page_index"
    READING_ORDER_OK = "reading_order_ok"
    READING_ORDER_INCONSISTENT = "reading_order_inconsistent"
    DISAGREEMENT_RETAINED = "disagreement_retained"
    DISAGREEMENT_DROPPED = "disagreement_dropped"
    QUOTE_ROUND_TRIP_OK = "quote_round_trip_ok"
    QUOTE_ROUND_TRIP_FAILED = "quote_round_trip_failed"
    LOW_READABILITY = "low_readability"
    LOW_COVERAGE = "low_coverage"
    COVERAGE_POLICY_MET = "coverage_policy_met"
    ARTIFACT_VERSION_MISMATCH = "artifact_version_mismatch"
    ARTIFACT_VERSION_MISSING = "artifact_version_missing"
    CITATION_SPAN_MISSING = "citation_span_missing"
    CITATION_ARTIFACT_MISMATCH = "citation_artifact_mismatch"
    CITATION_ADMITTED = "citation_admitted"
    CITATION_REJECTED = "citation_rejected"
    SPAN_ARTIFACT_MISMATCH = "span_artifact_mismatch"
    DUPLICATE_SPAN_ID = "duplicate_span_id"
    LAYOUT_SPAN_DANGLING = "layout_span_dangling"
    METADATA_SPAN_DANGLING = "metadata_span_dangling"
    BBOX_OUT_OF_BOUNDS = "bbox_out_of_bounds"
    EMPTY_EXTRACTION = "empty_extraction"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    CONTENT_DIGEST_MISMATCH = "content_digest_mismatch"
    ORIGIN_COVERAGE_INCONSISTENT = "origin_coverage_inconsistent"
    VALIDATION_PASSED = "validation_passed"


class CitationAdmission(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SpanValidationError(ValueError):
    """Bounded validation failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "span_validation_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        # Never include document body text.
        return {"code": self.code, "message": str(self)[:256]}


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
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _sha256_hex_field(value, field)


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _require_float_01(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float")
    number = float(value)
    if number != number or number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0.0, 1.0]")
    return number


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _require_float_01(value, field)


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
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


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=512) for i, item in enumerate(value))


def _frozen_str_map(
    value: Any,
    field: str,
    *,
    max_items: int = 64,
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


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def text_digest(text: str) -> str:
    """SHA-256 of whitespace-normalized UTF-8 text (matches extraction)."""
    return sha256_hex(_normalize_ws(text).encode("utf-8"))


def estimate_readability(text: str) -> float:
    """Heuristic readability in [0.0, 1.0] for OCR/native text quality.

    High scores for alphanumeric, token-rich text; low for empty, symbolic, or
    highly repetitive garbage. Does not write body text anywhere.
    """
    cleaned = _normalize_ws(text)
    if not cleaned:
        return 0.0
    n = len(cleaned)
    alnum = len(_ALNUM_RE.findall(cleaned))
    alnum_ratio = alnum / float(n)
    tokens = _TOKEN_RE.findall(cleaned)
    if not tokens:
        return max(0.0, min(1.0, alnum_ratio * 0.2))
    unique_ratio = len(set(t.lower() for t in tokens)) / float(len(tokens))
    avg_len = sum(len(t) for t in tokens) / float(len(tokens))
    # Prefer tokens of length 2–14 (typical English/legal fragments).
    length_score = 1.0 if 2.0 <= avg_len <= 14.0 else max(0.0, 1.0 - abs(avg_len - 6.0) / 12.0)
    score = 0.45 * alnum_ratio + 0.35 * unique_ratio + 0.20 * length_score
    # Soft penalty for extremely short content.
    if n < 8:
        score *= n / 8.0
    return max(0.0, min(1.0, score))


def extract_quote(
    page_text: str,
    char_start: int | None,
    char_end: int | None,
) -> str | None:
    """Slice page text by character offsets; None when offsets are unusable."""
    if char_start is None or char_end is None:
        return None
    if char_start < 0 or char_end < char_start:
        return None
    if char_end > len(page_text):
        return None
    return page_text[char_start:char_end]


# ---------------------------------------------------------------------------
# Policy / input records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpanValidationPolicy:
    """Configurable thresholds for coverage and readability assurance."""

    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO
    min_overall_coverage: float = DEFAULT_MIN_OVERALL_COVERAGE
    min_readability: float = DEFAULT_MIN_READABILITY
    min_quote_similarity: float = DEFAULT_MIN_QUOTE_SIMILARITY
    disagreement_review_score: float = DEFAULT_DISAGREEMENT_REVIEW_SCORE
    max_findings: int = DEFAULT_MAX_FINDINGS
    max_citations: int = DEFAULT_MAX_CITATIONS
    min_native_chars: int = DEFAULT_MIN_NATIVE_CHARS
    require_render_digest: bool = True
    require_page_index_for_pdf: bool = True
    fail_on_dangling_layout_spans: bool = True
    fail_on_dangling_metadata_spans: bool = True
    # When True, missing expected content digest fails closed as INVALID.
    require_expected_content_digest: bool = False

    def __post_init__(self) -> None:
        for name in (
            "min_coverage_ratio",
            "min_overall_coverage",
            "min_readability",
            "min_quote_similarity",
            "disagreement_review_score",
        ):
            object.__setattr__(
                self, name, _require_float_01(getattr(self, name), name)
            )
        for name in ("max_findings", "max_citations", "min_native_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in (
            "require_render_digest",
            "require_page_index_for_pdf",
            "fail_on_dangling_layout_spans",
            "fail_on_dangling_metadata_spans",
            "require_expected_content_digest",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")


@dataclass(frozen=True, slots=True)
class SemanticCitation:
    """A semantic result that cites a span and must bind to an artifact version.

    Callers pass facts, assessments, or requirements as citations. Validation
    rejects any citation whose span is missing or whose artifact version does
    not match the extraction binding.
    """

    schema_version: str
    citation_id: str
    span_id: str
    artifact_id: str
    # Artifact version binding: content_sha256 of the extracted artifact.
    content_sha256: str | None
    # Optional free-form version label (e.g. parser/ruleset version).
    version: str | None
    kind: str
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SPAN_VALIDATOR_SCHEMA_VERSION:
            raise ValueError(
                f"SemanticCitation.schema_version must be {SPAN_VALIDATOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "citation_id", _identifier(self.citation_id, "citation_id")
        )
        object.__setattr__(self, "span_id", _identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "content_sha256", _optional_sha256(self.content_sha256, "content_sha256")
        )
        object.__setattr__(
            self, "version", _optional_str(self.version, "version", max_len=128)
        )
        object.__setattr__(
            self, "kind", _require_str(self.kind, "kind", max_len=64)
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "citation_id": self.citation_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "kind": self.kind,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticCitation":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticCitation must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SPAN_VALIDATOR_SCHEMA_VERSION
            ),
            citation_id=value.get("citation_id", ""),
            span_id=value.get("span_id", ""),
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256"),
            version=value.get("version"),
            kind=value.get("kind", "semantic"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )

    @classmethod
    def from_submission_fact(
        cls,
        fact: SubmissionFact | Mapping[str, Any],
        *,
        artifact_id: str,
        content_sha256: str | None,
        citation_id: str | None = None,
    ) -> "SemanticCitation":
        if isinstance(fact, Mapping):
            fact = SubmissionFact.from_dict(fact)
        return cls(
            schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
            citation_id=citation_id or f"cite:{fact.fact_id}",
            span_id=fact.evidence_span_id,
            artifact_id=artifact_id,
            content_sha256=content_sha256,
            version=fact.version,
            kind="submission_fact",
            classification=fact.classification,
        )


@dataclass(frozen=True, slots=True)
class SpanValidationInput:
    """Inputs for span assurance validation."""

    extraction: DocumentExtractionResult
    # Expected artifact content digest; mismatch → stale / version failure.
    expected_content_sha256: str | None = None
    # Semantic consumers that must resolve against validated spans.
    citations: tuple[SemanticCitation, ...] = ()
    # Optional known page texts override (rare; normally use extraction.page_texts).
    page_texts_override: Mapping[str, str] | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.extraction, DocumentExtractionResult):
            raise TypeError("extraction must be DocumentExtractionResult")
        object.__setattr__(
            self,
            "expected_content_sha256",
            _optional_sha256(self.expected_content_sha256, "expected_content_sha256"),
        )
        if not isinstance(self.citations, tuple):
            object.__setattr__(self, "citations", tuple(self.citations))
        for i, c in enumerate(self.citations):
            if not isinstance(c, SemanticCitation):
                raise TypeError(f"citations[{i}] must be SemanticCitation")
        if self.page_texts_override is not None:
            if not isinstance(self.page_texts_override, Mapping):
                raise TypeError("page_texts_override must be a mapping or None")
            frozen = {
                str(k): str(v) for k, v in self.page_texts_override.items()
            }
            object.__setattr__(
                self, "page_texts_override", MappingProxyType(frozen)
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpanValidationFinding:
    """A single machine-readable finding (identifiers only; no body text)."""

    schema_version: str
    finding_id: str
    reason_code: str
    severity: FindingSeverity
    message: str
    span_id: str | None
    page_index: int | None
    citation_id: str | None
    details: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SPAN_VALIDATOR_SCHEMA_VERSION:
            raise ValueError(
                "SpanValidationFinding.schema_version must be "
                f"{SPAN_VALIDATOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "finding_id", _identifier(self.finding_id, "finding_id")
        )
        object.__setattr__(
            self,
            "reason_code",
            _require_str(self.reason_code, "reason_code", max_len=128),
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_enum(FindingSeverity, self.severity, "severity"),
        )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=512)
        )
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        if self.page_index is not None:
            object.__setattr__(
                self, "page_index", _nonneg_int(self.page_index, "page_index")
            )
        object.__setattr__(
            self,
            "citation_id",
            _optional_identifier(self.citation_id, "citation_id"),
        )
        object.__setattr__(
            self, "details", _frozen_str_map(self.details, "details", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "details": dict(self.details),
            "finding_id": self.finding_id,
            "message": self.message,
            "page_index": self.page_index,
            "reason_code": self.reason_code,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "span_id": self.span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpanValidationFinding":
        if not isinstance(value, Mapping):
            raise TypeError("SpanValidationFinding must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SPAN_VALIDATOR_SCHEMA_VERSION
            ),
            finding_id=value.get("finding_id", ""),
            reason_code=value.get("reason_code", ""),
            severity=value.get("severity", FindingSeverity.INFO.value),
            message=value.get("message", "finding"),
            span_id=value.get("span_id"),
            page_index=value.get("page_index"),
            citation_id=value.get("citation_id"),
            details=value.get("details") or {},
        )


@dataclass(frozen=True, slots=True)
class CitationValidationRecord:
    """Admission decision for one semantic citation."""

    schema_version: str
    citation_id: str
    span_id: str
    artifact_id: str
    admission: CitationAdmission
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SPAN_VALIDATOR_SCHEMA_VERSION:
            raise ValueError(
                "CitationValidationRecord.schema_version must be "
                f"{SPAN_VALIDATOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "citation_id", _identifier(self.citation_id, "citation_id")
        )
        object.__setattr__(self, "span_id", _identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "admission",
            _coerce_enum(CitationAdmission, self.admission, "admission"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value,
            "artifact_id": self.artifact_id,
            "citation_id": self.citation_id,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "span_id": self.span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CitationValidationRecord":
        if not isinstance(value, Mapping):
            raise TypeError("CitationValidationRecord must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SPAN_VALIDATOR_SCHEMA_VERSION
            ),
            citation_id=value.get("citation_id", ""),
            span_id=value.get("span_id", ""),
            artifact_id=value.get("artifact_id", ""),
            admission=value.get("admission", CitationAdmission.UNKNOWN.value),
            reason_codes=tuple(value.get("reason_codes") or ()),
        )


@dataclass(frozen=True, slots=True)
class RetainedDisagreement:
    """Preserved native/OCR disagreement for a page (never dropped)."""

    schema_version: str
    page_index: int
    artifact_id: str
    disagreement_score: float
    origins_present: tuple[str, ...]
    coverage_status: str
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SPAN_VALIDATOR_SCHEMA_VERSION:
            raise ValueError(
                "RetainedDisagreement.schema_version must be "
                f"{SPAN_VALIDATOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "page_index", _nonneg_int(self.page_index, "page_index")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "disagreement_score",
            _require_float_01(self.disagreement_score, "disagreement_score"),
        )
        object.__setattr__(
            self,
            "origins_present",
            _tuple_of_str(self.origins_present, "origins_present", max_items=16),
        )
        object.__setattr__(
            self,
            "coverage_status",
            _require_str(self.coverage_status, "coverage_status", max_len=64),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "coverage_status": self.coverage_status,
            "disagreement_score": self.disagreement_score,
            "origins_present": list(self.origins_present),
            "page_index": self.page_index,
            "schema_version": self.schema_version,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetainedDisagreement":
        if not isinstance(value, Mapping):
            raise TypeError("RetainedDisagreement must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SPAN_VALIDATOR_SCHEMA_VERSION
            ),
            page_index=value.get("page_index", 0),
            artifact_id=value.get("artifact_id", ""),
            disagreement_score=float(value.get("disagreement_score", 0.0) or 0.0),
            origins_present=tuple(value.get("origins_present") or ()),
            coverage_status=value.get("coverage_status", "unknown"),
            warnings=tuple(value.get("warnings") or ()),
        )


@dataclass(frozen=True, slots=True)
class SpanValidationResult:
    """Full span-assurance outcome (identifiers only in public projection)."""

    schema_version: str
    validation_id: str
    extraction_id: str
    artifact_id: str
    content_sha256: str
    disposition: SpanValidationDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    findings: tuple[SpanValidationFinding, ...]
    retained_disagreements: tuple[RetainedDisagreement, ...]
    citation_records: tuple[CitationValidationRecord, ...]
    overall_coverage: float
    overall_readability: float
    page_count: int
    span_count: int
    accounted_pages: int
    unaccounted_pages: tuple[int, ...]
    invalid_span_ids: tuple[str, ...]
    stale_span_ids: tuple[str, ...]
    admitted_citation_ids: tuple[str, ...]
    rejected_citation_ids: tuple[str, ...]
    labels: Mapping[str, str]
    policy_snapshot: Mapping[str, str]
    retained: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SPAN_VALIDATOR_SCHEMA_VERSION:
            raise ValueError(
                "SpanValidationResult.schema_version must be "
                f"{SPAN_VALIDATOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "validation_id", _identifier(self.validation_id, "validation_id")
        )
        object.__setattr__(
            self, "extraction_id", _identifier(self.extraction_id, "extraction_id")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _sha256_hex_field(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(SpanValidationDisposition, self.disposition, "disposition"),
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
        if not isinstance(self.findings, tuple):
            object.__setattr__(self, "findings", tuple(self.findings))
        if not isinstance(self.retained_disagreements, tuple):
            object.__setattr__(
                self, "retained_disagreements", tuple(self.retained_disagreements)
            )
        if not isinstance(self.citation_records, tuple):
            object.__setattr__(
                self, "citation_records", tuple(self.citation_records)
            )
        object.__setattr__(
            self,
            "overall_coverage",
            _require_float_01(self.overall_coverage, "overall_coverage"),
        )
        object.__setattr__(
            self,
            "overall_readability",
            _require_float_01(self.overall_readability, "overall_readability"),
        )
        object.__setattr__(
            self, "page_count", _nonneg_int(self.page_count, "page_count")
        )
        object.__setattr__(
            self, "span_count", _nonneg_int(self.span_count, "span_count")
        )
        object.__setattr__(
            self, "accounted_pages", _nonneg_int(self.accounted_pages, "accounted_pages")
        )
        if not isinstance(self.unaccounted_pages, tuple):
            object.__setattr__(
                self,
                "unaccounted_pages",
                tuple(int(p) for p in self.unaccounted_pages),
            )
        object.__setattr__(
            self,
            "invalid_span_ids",
            _tuple_of_str(self.invalid_span_ids, "invalid_span_ids", max_items=1024),
        )
        object.__setattr__(
            self,
            "stale_span_ids",
            _tuple_of_str(self.stale_span_ids, "stale_span_ids", max_items=1024),
        )
        object.__setattr__(
            self,
            "admitted_citation_ids",
            _tuple_of_str(
                self.admitted_citation_ids, "admitted_citation_ids", max_items=1024
            ),
        )
        object.__setattr__(
            self,
            "rejected_citation_ids",
            _tuple_of_str(
                self.rejected_citation_ids, "rejected_citation_ids", max_items=1024
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "policy_snapshot",
            _frozen_str_map(self.policy_snapshot, "policy_snapshot", max_items=64),
        )
        if not isinstance(self.retained, bool):
            raise TypeError("retained must be bool")
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def is_valid(self) -> bool:
        return self.disposition is SpanValidationDisposition.VALID

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            SpanValidationDisposition.REVIEW,
            SpanValidationDisposition.UNKNOWN,
            SpanValidationDisposition.INVALID,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    @property
    def is_invalid(self) -> bool:
        return self.disposition is SpanValidationDisposition.INVALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "accounted_pages": self.accounted_pages,
            "admitted_citation_ids": list(self.admitted_citation_ids),
            "artifact_id": self.artifact_id,
            "citation_records": [c.to_dict() for c in self.citation_records],
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "extraction_id": self.extraction_id,
            "findings": [f.to_dict() for f in self.findings],
            "invalid_span_ids": list(self.invalid_span_ids),
            "labels": dict(self.labels),
            "overall_coverage": self.overall_coverage,
            "overall_readability": self.overall_readability,
            "page_count": self.page_count,
            "policy_snapshot": dict(self.policy_snapshot),
            "reason_codes": list(self.reason_codes),
            "rejected_citation_ids": list(self.rejected_citation_ids),
            "retained": self.retained,
            "retained_disagreements": [
                d.to_dict() for d in self.retained_disagreements
            ],
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_count": self.span_count,
            "stale_span_ids": list(self.stale_span_ids),
            "unaccounted_pages": list(self.unaccounted_pages),
            "validation_id": self.validation_id,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and policy outcomes only — never page or quote text."""
        return {
            "accounted_pages": self.accounted_pages,
            "admitted_citation_count": len(self.admitted_citation_ids),
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "extraction_id": self.extraction_id,
            "finding_count": len(self.findings),
            "invalid_span_count": len(self.invalid_span_ids),
            "overall_coverage": self.overall_coverage,
            "overall_readability": self.overall_readability,
            "page_count": self.page_count,
            "reason_codes": list(self.reason_codes),
            "rejected_citation_count": len(self.rejected_citation_ids),
            "retained": self.retained,
            "retained_disagreement_count": len(self.retained_disagreements),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_count": self.span_count,
            "stale_span_count": len(self.stale_span_ids),
            "unaccounted_page_count": len(self.unaccounted_pages),
            "validation_id": self.validation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpanValidationResult":
        if not isinstance(value, Mapping):
            raise TypeError("SpanValidationResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SPAN_VALIDATOR_SCHEMA_VERSION
            ),
            validation_id=value.get("validation_id", ""),
            extraction_id=value.get("extraction_id", ""),
            artifact_id=value.get("artifact_id", ""),
            content_sha256=value.get("content_sha256", "0" * 64),
            disposition=value.get(
                "disposition", SpanValidationDisposition.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            findings=tuple(
                SpanValidationFinding.from_dict(f)
                for f in (value.get("findings") or ())
            ),
            retained_disagreements=tuple(
                RetainedDisagreement.from_dict(d)
                for d in (value.get("retained_disagreements") or ())
            ),
            citation_records=tuple(
                CitationValidationRecord.from_dict(c)
                for c in (value.get("citation_records") or ())
            ),
            overall_coverage=float(value.get("overall_coverage", 0.0) or 0.0),
            overall_readability=float(value.get("overall_readability", 0.0) or 0.0),
            page_count=int(value.get("page_count", 0) or 0),
            span_count=int(value.get("span_count", 0) or 0),
            accounted_pages=int(value.get("accounted_pages", 0) or 0),
            unaccounted_pages=tuple(value.get("unaccounted_pages") or ()),
            invalid_span_ids=tuple(value.get("invalid_span_ids") or ()),
            stale_span_ids=tuple(value.get("stale_span_ids") or ()),
            admitted_citation_ids=tuple(value.get("admitted_citation_ids") or ()),
            rejected_citation_ids=tuple(value.get("rejected_citation_ids") or ()),
            labels=value.get("labels") or {},
            policy_snapshot=value.get("policy_snapshot") or {},
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class SpanValidator:
    """Validate extraction span provenance, coverage, and semantic citations."""

    def __init__(
        self,
        *,
        policy: SpanValidationPolicy | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.policy = policy or SpanValidationPolicy()
        self._id_factory = id_factory or (lambda: f"spanval:{uuid.uuid4().hex}")

    def validate(
        self,
        extraction: DocumentExtractionResult | SpanValidationInput | Mapping[str, Any],
        *,
        expected_content_sha256: str | None = None,
        citations: Sequence[SemanticCitation | Mapping[str, Any]] | None = None,
        page_texts_override: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> SpanValidationResult:
        """Run full span assurance and return a versioned result."""
        inp = self._coerce_input(
            extraction,
            expected_content_sha256=expected_content_sha256,
            citations=citations,
            page_texts_override=page_texts_override,
            labels=labels,
        )
        return self._validate(inp)

    def _coerce_input(
        self,
        extraction: DocumentExtractionResult | SpanValidationInput | Mapping[str, Any],
        *,
        expected_content_sha256: str | None,
        citations: Sequence[SemanticCitation | Mapping[str, Any]] | None,
        page_texts_override: Mapping[str, str] | None,
        labels: Mapping[str, str] | None,
    ) -> SpanValidationInput:
        if isinstance(extraction, SpanValidationInput):
            return extraction
        if isinstance(extraction, Mapping):
            # Allow either full input dict or raw extraction dict.
            if "extraction" in extraction:
                ex_raw = extraction["extraction"]
                if isinstance(ex_raw, DocumentExtractionResult):
                    ex = ex_raw
                else:
                    ex = DocumentExtractionResult.from_dict(ex_raw)  # type: ignore[arg-type]
                cite_raw = extraction.get("citations") or citations or ()
                return SpanValidationInput(
                    extraction=ex,
                    expected_content_sha256=extraction.get(
                        "expected_content_sha256", expected_content_sha256
                    ),
                    citations=tuple(self._coerce_citations(cite_raw)),
                    page_texts_override=extraction.get(
                        "page_texts_override", page_texts_override
                    ),
                    labels=extraction.get("labels") or labels or {},
                )
            ex = DocumentExtractionResult.from_dict(extraction)
        elif isinstance(extraction, DocumentExtractionResult):
            ex = extraction
        else:
            raise TypeError(
                "extraction must be DocumentExtractionResult, SpanValidationInput, "
                f"or mapping, got {type(extraction).__name__}"
            )
        return SpanValidationInput(
            extraction=ex,
            expected_content_sha256=expected_content_sha256,
            citations=tuple(self._coerce_citations(citations or ())),
            page_texts_override=page_texts_override,
            labels=labels or {},
        )

    def _coerce_citations(
        self, citations: Sequence[SemanticCitation | Mapping[str, Any]]
    ) -> list[SemanticCitation]:
        out: list[SemanticCitation] = []
        for i, c in enumerate(citations):
            if isinstance(c, SemanticCitation):
                out.append(c)
            elif isinstance(c, Mapping):
                out.append(SemanticCitation.from_dict(c))
            else:
                raise TypeError(
                    f"citations[{i}] must be SemanticCitation or mapping"
                )
            if len(out) > self.policy.max_citations:
                raise SpanValidationError(
                    "citation count exceeds policy max",
                    code="citation_limit",
                )
        return out

    def _new_finding_id(self, seq: int) -> str:
        return f"finding:{self._id_factory()}:{seq}"

    def _validate(self, inp: SpanValidationInput) -> SpanValidationResult:
        extraction = inp.extraction
        policy = self.policy
        validation_id = self._id_factory()
        findings: list[SpanValidationFinding] = []
        reason_codes: list[str] = []
        finding_seq = 0

        def add_finding(
            *,
            reason: SpanValidationReasonCode | str,
            severity: FindingSeverity,
            message: str,
            span_id: str | None = None,
            page_index: int | None = None,
            citation_id: str | None = None,
            details: Mapping[str, str] | None = None,
        ) -> None:
            nonlocal finding_seq
            if len(findings) >= policy.max_findings:
                return
            finding_seq += 1
            code = reason.value if isinstance(reason, SpanValidationReasonCode) else str(reason)
            findings.append(
                SpanValidationFinding(
                    schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
                    finding_id=self._new_finding_id(finding_seq),
                    reason_code=code,
                    severity=severity,
                    message=message,
                    span_id=span_id,
                    page_index=page_index,
                    citation_id=citation_id,
                    details=dict(details or {}),
                )
            )
            if code not in reason_codes:
                reason_codes.append(code)

        # ---- Schema / artifact version binding ----
        if extraction.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            add_finding(
                reason=SpanValidationReasonCode.SCHEMA_VERSION_MISMATCH,
                severity=FindingSeverity.CRITICAL,
                message="extraction schema_version does not match expected document extraction schema",
                details={
                    "got": extraction.schema_version,
                    "expected": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                },
            )

        if inp.expected_content_sha256 is not None:
            if extraction.content_sha256 != inp.expected_content_sha256:
                add_finding(
                    reason=SpanValidationReasonCode.CONTENT_DIGEST_MISMATCH,
                    severity=FindingSeverity.CRITICAL,
                    message="extraction content_sha256 does not match expected artifact version",
                    details={
                        "extraction_digest_prefix": extraction.content_sha256[:12],
                        "expected_digest_prefix": inp.expected_content_sha256[:12],
                    },
                )
        elif policy.require_expected_content_digest:
            add_finding(
                reason=SpanValidationReasonCode.ARTIFACT_VERSION_MISSING,
                severity=FindingSeverity.CRITICAL,
                message="expected artifact content digest is required by policy but missing",
            )

        # ---- Page coverage completeness ----
        page_count = extraction.page_count
        coverage_by_page: dict[int, PageCoverageRecord] = {}
        unaccounted: list[int] = []
        duplicate_pages: list[int] = []

        for cov in extraction.page_coverage:
            if cov.page_index in coverage_by_page:
                duplicate_pages.append(cov.page_index)
                add_finding(
                    reason=SpanValidationReasonCode.DUPLICATE_PAGE_INDEX,
                    severity=FindingSeverity.ERROR,
                    message="duplicate page_coverage entry for page_index",
                    page_index=cov.page_index,
                )
            coverage_by_page[cov.page_index] = cov
            if cov.artifact_id != extraction.artifact_id:
                add_finding(
                    reason=SpanValidationReasonCode.SPAN_ARTIFACT_MISMATCH,
                    severity=FindingSeverity.ERROR,
                    message="page_coverage artifact_id does not match extraction artifact_id",
                    page_index=cov.page_index,
                    details={"coverage_artifact_id": cov.artifact_id},
                )

        expected_indices = set(range(page_count)) if page_count > 0 else set()
        present_indices = set(coverage_by_page.keys())
        missing = sorted(expected_indices - present_indices)
        extra = sorted(present_indices - expected_indices)

        for idx in missing:
            unaccounted.append(idx)
            add_finding(
                reason=SpanValidationReasonCode.UNACCOUNTED_PAGE,
                severity=FindingSeverity.CRITICAL,
                message="page index has no page_coverage receipt",
                page_index=idx,
            )
        for idx in extra:
            # Coverage for a page outside declared page_count is also unaccounted.
            unaccounted.append(idx)
            add_finding(
                reason=SpanValidationReasonCode.UNACCOUNTED_PAGE,
                severity=FindingSeverity.ERROR,
                message="page_coverage index outside declared page_count",
                page_index=idx,
                details={"page_count": str(page_count)},
            )

        if not missing and not extra and not duplicate_pages:
            if page_count == 0 and not extraction.page_coverage:
                # Empty extraction (archive inventory / rejected) is accounted.
                reason_codes.append(
                    SpanValidationReasonCode.PAGE_COVERAGE_COMPLETE.value
                )
            elif page_count > 0:
                reason_codes.append(
                    SpanValidationReasonCode.PAGE_COVERAGE_COMPLETE.value
                )

        # ---- Page texts for quote round-trip ----
        page_texts: dict[str, str] = dict(extraction.page_texts)
        if inp.page_texts_override is not None:
            page_texts.update({str(k): str(v) for k, v in inp.page_texts_override.items()})

        # ---- Spans: bounds, digests, reading order, quote round-trip ----
        span_by_id: dict[str, ExtractedSpan] = {}
        invalid_span_ids: list[str] = []
        stale_span_ids: list[str] = []
        spans_by_page: dict[int, list[ExtractedSpan]] = {}
        page_readability: list[float] = []
        bounds_ok = True
        quote_ok_count = 0
        quote_checked = 0

        for span in extraction.spans:
            if span.span_id in span_by_id:
                add_finding(
                    reason=SpanValidationReasonCode.DUPLICATE_SPAN_ID,
                    severity=FindingSeverity.ERROR,
                    message="duplicate span_id in extraction",
                    span_id=span.span_id,
                )
                invalid_span_ids.append(span.span_id)
                bounds_ok = False
                continue
            span_by_id[span.span_id] = span

            if span.schema_version != CONTRACTS_SCHEMA_VERSION:
                add_finding(
                    reason=SpanValidationReasonCode.SCHEMA_VERSION_MISMATCH,
                    severity=FindingSeverity.ERROR,
                    message="span schema_version mismatch",
                    span_id=span.span_id,
                    details={"got": span.schema_version},
                )
                invalid_span_ids.append(span.span_id)
                bounds_ok = False

            if span.artifact_id != extraction.artifact_id:
                add_finding(
                    reason=SpanValidationReasonCode.SPAN_ARTIFACT_MISMATCH,
                    severity=FindingSeverity.CRITICAL,
                    message="span artifact_id does not match extraction artifact_id",
                    span_id=span.span_id,
                    details={"span_artifact_id": span.artifact_id},
                )
                invalid_span_ids.append(span.span_id)
                stale_span_ids.append(span.span_id)
                bounds_ok = False

            page_index = span.page_index
            if page_index is None:
                if (
                    policy.require_page_index_for_pdf
                    and extraction.media_family is MediaFamily.PDF
                ):
                    add_finding(
                        reason=SpanValidationReasonCode.SPAN_BOUNDS_INVALID,
                        severity=FindingSeverity.ERROR,
                        message="PDF span missing page_index",
                        span_id=span.span_id,
                    )
                    invalid_span_ids.append(span.span_id)
                    bounds_ok = False
            else:
                if page_count > 0 and (
                    page_index < 0 or page_index >= page_count
                ):
                    add_finding(
                        reason=SpanValidationReasonCode.SPAN_BOUNDS_INVALID,
                        severity=FindingSeverity.ERROR,
                        message="span page_index outside page_count",
                        span_id=span.span_id,
                        page_index=page_index,
                        details={"page_count": str(page_count)},
                    )
                    invalid_span_ids.append(span.span_id)
                    bounds_ok = False
                spans_by_page.setdefault(page_index, []).append(span)

            # Character bounds.
            cs, ce = span.char_start, span.char_end
            if cs is not None and ce is not None and ce < cs:
                add_finding(
                    reason=SpanValidationReasonCode.SPAN_BOUNDS_INVALID,
                    severity=FindingSeverity.ERROR,
                    message="span char_end is less than char_start",
                    span_id=span.span_id,
                    page_index=page_index,
                )
                invalid_span_ids.append(span.span_id)
                bounds_ok = False

            page_text = ""
            if page_index is not None:
                page_text = page_texts.get(str(page_index), "")

            if page_text and cs is not None and ce is not None:
                quote = extract_quote(page_text, cs, ce)
                if quote is None:
                    add_finding(
                        reason=SpanValidationReasonCode.SPAN_BOUNDS_INVALID,
                        severity=FindingSeverity.ERROR,
                        message="span character offsets out of page text bounds",
                        span_id=span.span_id,
                        page_index=page_index,
                        details={
                            "page_text_len": str(len(page_text)),
                            "char_start": str(cs),
                            "char_end": str(ce),
                        },
                    )
                    invalid_span_ids.append(span.span_id)
                    bounds_ok = False
                else:
                    quote_checked += 1
                    # Quote round-trip via digest (exact when policy requires).
                    actual_digest = text_digest(quote)
                    if span.text_digest is not None:
                        if actual_digest == span.text_digest:
                            quote_ok_count += 1
                        else:
                            # Soft path: similarity of quote vs itself is 1;
                            # compare token similarity of quote to page slice
                            # only as fallback when digests differ due to
                            # extraction using span builder text that was
                            # normalized differently from the page join.
                            # Primary rule: digest mismatch → stale.
                            sim = text_similarity(quote, quote)
                            # Re-check with full-span text if offsets land on
                            # reconstructed multi-span page text that may
                            # include separators not in the original span text.
                            # Still treat digest mismatch as stale.
                            add_finding(
                                reason=SpanValidationReasonCode.TEXT_DIGEST_MISMATCH,
                                severity=FindingSeverity.ERROR,
                                message="span text_digest does not match quote at character offsets",
                                span_id=span.span_id,
                                page_index=page_index,
                                details={
                                    "stored_digest_prefix": span.text_digest[:12],
                                    "quote_digest_prefix": actual_digest[:12],
                                    "similarity": f"{sim:.4f}",
                                },
                            )
                            stale_span_ids.append(span.span_id)
                            add_finding(
                                reason=SpanValidationReasonCode.STALE_SPAN,
                                severity=FindingSeverity.ERROR,
                                message="span is stale relative to current page text",
                                span_id=span.span_id,
                                page_index=page_index,
                            )
                            add_finding(
                                reason=SpanValidationReasonCode.QUOTE_ROUND_TRIP_FAILED,
                                severity=FindingSeverity.ERROR,
                                message="quote round-trip failed for span",
                                span_id=span.span_id,
                                page_index=page_index,
                            )
                    else:
                        # No stored digest: cannot prove round-trip.
                        add_finding(
                            reason=SpanValidationReasonCode.QUOTE_ROUND_TRIP_FAILED,
                            severity=FindingSeverity.WARNING,
                            message="span lacks text_digest; quote round-trip not provable",
                            span_id=span.span_id,
                            page_index=page_index,
                        )

            # BBox geometry against page dimensions when both available.
            if (
                span.bbox is not None
                and page_index is not None
                and page_index in coverage_by_page
            ):
                cov = coverage_by_page[page_index]
                if cov.page_width is not None and cov.page_height is not None:
                    x0, y0, x1, y1 = span.bbox
                    # Allow small floating-point slack; reject clearly outside.
                    slack = 2.0
                    if (
                        x1 + slack < 0
                        or y1 + slack < 0
                        or x0 - slack > cov.page_width
                        or y0 - slack > cov.page_height
                        or x1 < x0
                        or y1 < y0
                    ):
                        add_finding(
                            reason=SpanValidationReasonCode.BBOX_OUT_OF_BOUNDS,
                            severity=FindingSeverity.WARNING,
                            message="span bbox is outside page dimensions",
                            span_id=span.span_id,
                            page_index=page_index,
                        )

        if bounds_ok and extraction.spans:
            reason_codes.append(SpanValidationReasonCode.SPAN_BOUNDS_OK.value)
        if quote_checked > 0 and quote_ok_count == quote_checked:
            reason_codes.append(SpanValidationReasonCode.QUOTE_ROUND_TRIP_OK.value)

        # ---- Reading order consistency per page ----
        reading_order_ok = True
        for pidx, page_spans in spans_by_page.items():
            ordered = [
                s
                for s in page_spans
                if s.reading_order is not None
            ]
            if len(ordered) < 2:
                continue
            orders = [s.reading_order for s in ordered if s.reading_order is not None]
            # Detect non-monotonic char_start relative to reading_order when both set.
            sorted_by_order = sorted(
                ordered, key=lambda s: s.reading_order if s.reading_order is not None else 0
            )
            last_start: int | None = None
            for s in sorted_by_order:
                if s.char_start is None:
                    continue
                if last_start is not None and s.char_start < last_start:
                    reading_order_ok = False
                    add_finding(
                        reason=SpanValidationReasonCode.READING_ORDER_INCONSISTENT,
                        severity=FindingSeverity.WARNING,
                        message="reading_order conflicts with character offsets on page",
                        span_id=s.span_id,
                        page_index=pidx,
                    )
                    break
                last_start = s.char_start
            # Duplicate reading_order values (non-unique) are inconsistent.
            if len(orders) != len(set(orders)):
                reading_order_ok = False
                add_finding(
                    reason=SpanValidationReasonCode.READING_ORDER_INCONSISTENT,
                    severity=FindingSeverity.WARNING,
                    message="duplicate reading_order values on page",
                    page_index=pidx,
                )
        if reading_order_ok and extraction.spans:
            reason_codes.append(SpanValidationReasonCode.READING_ORDER_OK.value)

        # ---- Coverage / readability policy + disagreement retention ----
        retained_disagreements: list[RetainedDisagreement] = []
        low_coverage = False
        low_readability = False
        coverage_ratios: list[float] = []

        for pidx in range(page_count):
            cov = coverage_by_page.get(pidx)
            page_text = page_texts.get(str(pidx), "")
            readability = estimate_readability(page_text)
            page_readability.append(readability)
            if cov is not None:
                coverage_ratios.append(cov.coverage_ratio)
                if (
                    cov.coverage_ratio < policy.min_coverage_ratio
                    or cov.status
                    in (
                        PageStatus.LOW_COVERAGE,
                        PageStatus.IMAGE_ONLY,
                        PageStatus.OCR_NEEDED,
                        PageStatus.OCR_UNAVAILABLE,
                    )
                ):
                    low_coverage = True
                    add_finding(
                        reason=SpanValidationReasonCode.LOW_COVERAGE,
                        severity=FindingSeverity.WARNING,
                        message="page coverage below policy threshold or low-coverage status",
                        page_index=pidx,
                        details={
                            "coverage_ratio": f"{cov.coverage_ratio:.4f}",
                            "status": cov.status.value,
                        },
                    )
                if readability < policy.min_readability and page_text.strip():
                    low_readability = True
                    add_finding(
                        reason=SpanValidationReasonCode.LOW_READABILITY,
                        severity=FindingSeverity.WARNING,
                        message="page readability below policy threshold",
                        page_index=pidx,
                        details={"readability": f"{readability:.4f}"},
                    )
                elif not page_text.strip() and cov.status not in (
                    PageStatus.BLANK,
                    PageStatus.EMPTY,
                    PageStatus.IMAGE_ONLY,
                    PageStatus.PASSWORD_PROTECTED,
                    PageStatus.CORRUPT,
                    PageStatus.UNSUPPORTED,
                ):
                    # Empty text with non-blank status is low readability.
                    if cov.coverage_ratio < policy.min_coverage_ratio:
                        low_readability = True
                        add_finding(
                            reason=SpanValidationReasonCode.LOW_READABILITY,
                            severity=FindingSeverity.WARNING,
                            message="empty page text with insufficient coverage",
                            page_index=pidx,
                        )

                # Render digest presence for accounted pages.
                if policy.require_render_digest and cov.render_digest is None:
                    # Soft for blank/empty; harder for text pages.
                    if cov.status not in (
                        PageStatus.EMPTY,
                        PageStatus.BLANK,
                        PageStatus.UNSUPPORTED,
                    ):
                        add_finding(
                            reason=SpanValidationReasonCode.RENDER_DIGEST_MISSING,
                            severity=FindingSeverity.WARNING,
                            message="page coverage missing render_digest",
                            page_index=pidx,
                        )

                # Origin consistency: has_native_text vs origins_present.
                origins = set(cov.origins_present)
                if cov.has_native_text and ExtractionOrigin.NATIVE.value not in origins:
                    # Extraction may list "native" only after span finalize; soft.
                    if origins and ExtractionOrigin.NATIVE.value not in origins:
                        add_finding(
                            reason=SpanValidationReasonCode.ORIGIN_COVERAGE_INCONSISTENT,
                            severity=FindingSeverity.INFO,
                            message="has_native_text without native origin listed",
                            page_index=pidx,
                        )

                # Disagreement retention: never drop.
                if cov.disagreement or cov.status is PageStatus.DISAGREEMENT:
                    retained_disagreements.append(
                        RetainedDisagreement(
                            schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
                            page_index=pidx,
                            artifact_id=extraction.artifact_id,
                            disagreement_score=cov.disagreement_score,
                            origins_present=cov.origins_present,
                            coverage_status=cov.status.value,
                            warnings=cov.warnings,
                        )
                    )
                    add_finding(
                        reason=SpanValidationReasonCode.DISAGREEMENT_RETAINED,
                        severity=FindingSeverity.WARNING,
                        message="native/OCR disagreement retained for review",
                        page_index=pidx,
                        details={
                            "disagreement_score": f"{cov.disagreement_score:.4f}",
                        },
                    )
                elif (
                    ExtractionOrigin.NATIVE.value in origins
                    and ExtractionOrigin.OCR.value in origins
                    and not cov.disagreement
                    and cov.disagreement_score == 0.0
                ):
                    # Both origins present without disagreement flag is allowed
                    # (merged cleanly); no drop finding.
                    pass

                # Detect dropped disagreement: warnings mention disagreement but flag false.
                if (
                    not cov.disagreement
                    and any(
                        "disagreement" in w.lower() or "native_ocr" in w.lower()
                        for w in cov.warnings
                    )
                ):
                    add_finding(
                        reason=SpanValidationReasonCode.DISAGREEMENT_DROPPED,
                        severity=FindingSeverity.ERROR,
                        message="disagreement signal in warnings but disagreement flag is false",
                        page_index=pidx,
                    )
                    # Still retain for review.
                    retained_disagreements.append(
                        RetainedDisagreement(
                            schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
                            page_index=pidx,
                            artifact_id=extraction.artifact_id,
                            disagreement_score=max(
                                cov.disagreement_score,
                                policy.disagreement_review_score,
                            ),
                            origins_present=cov.origins_present,
                            coverage_status=cov.status.value,
                            warnings=cov.warnings + ("disagreement_flag_restored",),
                        )
                    )

        overall_coverage = (
            sum(coverage_ratios) / len(coverage_ratios) if coverage_ratios else 0.0
        )
        if extraction.overall_coverage > 0:
            # Prefer extraction's declared overall when present.
            overall_coverage = extraction.overall_coverage
        overall_coverage = max(0.0, min(1.0, float(overall_coverage)))

        overall_readability = (
            sum(page_readability) / len(page_readability) if page_readability else 0.0
        )
        overall_readability = max(0.0, min(1.0, float(overall_readability)))

        if overall_coverage < policy.min_overall_coverage:
            low_coverage = True
            add_finding(
                reason=SpanValidationReasonCode.LOW_COVERAGE,
                severity=FindingSeverity.WARNING,
                message="overall coverage below policy minimum",
                details={
                    "overall_coverage": f"{overall_coverage:.4f}",
                    "min_overall_coverage": f"{policy.min_overall_coverage:.4f}",
                },
            )

        if page_count > 0 and overall_readability < policy.min_readability:
            # Only force low_readability when there is non-blank content intent.
            non_blank = any(
                page_texts.get(str(i), "").strip()
                or (
                    coverage_by_page.get(i) is not None
                    and coverage_by_page[i].status
                    not in (PageStatus.BLANK, PageStatus.EMPTY)
                )
                for i in range(page_count)
            )
            if non_blank:
                low_readability = True
                if SpanValidationReasonCode.LOW_READABILITY.value not in reason_codes:
                    add_finding(
                        reason=SpanValidationReasonCode.LOW_READABILITY,
                        severity=FindingSeverity.WARNING,
                        message="overall readability below policy minimum",
                        details={
                            "overall_readability": f"{overall_readability:.4f}",
                            "min_readability": f"{policy.min_readability:.4f}",
                        },
                    )

        if not low_coverage and page_count > 0 and not unaccounted:
            reason_codes.append(SpanValidationReasonCode.COVERAGE_POLICY_MET.value)

        # ---- Layout / metadata dangling span references ----
        for item in extraction.layout_items:
            if item.span_id is not None and item.span_id not in span_by_id:
                sev = (
                    FindingSeverity.ERROR
                    if policy.fail_on_dangling_layout_spans
                    else FindingSeverity.WARNING
                )
                add_finding(
                    reason=SpanValidationReasonCode.LAYOUT_SPAN_DANGLING,
                    severity=sev,
                    message="layout item references missing span_id",
                    span_id=item.span_id,
                    page_index=item.page_index,
                    details={"item_id": item.item_id},
                )
        for field in extraction.filing_metadata:
            if field.span_id is not None and field.span_id not in span_by_id:
                sev = (
                    FindingSeverity.ERROR
                    if policy.fail_on_dangling_metadata_spans
                    else FindingSeverity.WARNING
                )
                add_finding(
                    reason=SpanValidationReasonCode.METADATA_SPAN_DANGLING,
                    severity=sev,
                    message="filing metadata references missing span_id",
                    span_id=field.span_id,
                    page_index=field.page_index,
                    details={"field_id": field.field_id},
                )

        # ---- Semantic citations ----
        citation_records: list[CitationValidationRecord] = []
        admitted: list[str] = []
        rejected: list[str] = []

        for cite in inp.citations:
            reasons: list[str] = []
            admission = CitationAdmission.ADMITTED

            if cite.span_id not in span_by_id:
                reasons.append(SpanValidationReasonCode.CITATION_SPAN_MISSING.value)
                admission = CitationAdmission.REJECTED
                add_finding(
                    reason=SpanValidationReasonCode.CITATION_SPAN_MISSING,
                    severity=FindingSeverity.CRITICAL,
                    message="semantic citation references missing span",
                    span_id=cite.span_id,
                    citation_id=cite.citation_id,
                )
            else:
                span = span_by_id[cite.span_id]
                if cite.artifact_id != extraction.artifact_id:
                    reasons.append(
                        SpanValidationReasonCode.CITATION_ARTIFACT_MISMATCH.value
                    )
                    admission = CitationAdmission.REJECTED
                    add_finding(
                        reason=SpanValidationReasonCode.CITATION_ARTIFACT_MISMATCH,
                        severity=FindingSeverity.CRITICAL,
                        message="semantic citation artifact_id does not match extraction",
                        span_id=cite.span_id,
                        citation_id=cite.citation_id,
                        details={
                            "citation_artifact_id": cite.artifact_id,
                            "extraction_artifact_id": extraction.artifact_id,
                        },
                    )
                if span.artifact_id != cite.artifact_id:
                    reasons.append(
                        SpanValidationReasonCode.SPAN_ARTIFACT_MISMATCH.value
                    )
                    admission = CitationAdmission.REJECTED
                    add_finding(
                        reason=SpanValidationReasonCode.SPAN_ARTIFACT_MISMATCH,
                        severity=FindingSeverity.CRITICAL,
                        message="cited span artifact_id does not match citation artifact_id",
                        span_id=cite.span_id,
                        citation_id=cite.citation_id,
                    )
                if cite.span_id in invalid_span_ids or cite.span_id in stale_span_ids:
                    reasons.append(SpanValidationReasonCode.STALE_SPAN.value)
                    admission = CitationAdmission.REJECTED
                    add_finding(
                        reason=SpanValidationReasonCode.CITATION_REJECTED,
                        severity=FindingSeverity.ERROR,
                        message="citation targets invalid or stale span",
                        span_id=cite.span_id,
                        citation_id=cite.citation_id,
                    )

            # Artifact version binding: content_sha256 must match extraction.
            if cite.content_sha256 is None:
                reasons.append(
                    SpanValidationReasonCode.ARTIFACT_VERSION_MISSING.value
                )
                admission = CitationAdmission.REJECTED
                add_finding(
                    reason=SpanValidationReasonCode.ARTIFACT_VERSION_MISSING,
                    severity=FindingSeverity.CRITICAL,
                    message="semantic citation missing artifact content version digest",
                    span_id=cite.span_id,
                    citation_id=cite.citation_id,
                )
            elif cite.content_sha256 != extraction.content_sha256:
                reasons.append(
                    SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH.value
                )
                admission = CitationAdmission.REJECTED
                add_finding(
                    reason=SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH,
                    severity=FindingSeverity.CRITICAL,
                    message="semantic citation artifact version does not match extraction content_sha256",
                    span_id=cite.span_id,
                    citation_id=cite.citation_id,
                    details={
                        "citation_digest_prefix": cite.content_sha256[:12],
                        "extraction_digest_prefix": extraction.content_sha256[:12],
                    },
                )

            # Also enforce expected binding when provided.
            if (
                inp.expected_content_sha256 is not None
                and cite.content_sha256 is not None
                and cite.content_sha256 != inp.expected_content_sha256
            ):
                if (
                    SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH.value
                    not in reasons
                ):
                    reasons.append(
                        SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH.value
                    )
                admission = CitationAdmission.REJECTED
                add_finding(
                    reason=SpanValidationReasonCode.ARTIFACT_VERSION_MISMATCH,
                    severity=FindingSeverity.CRITICAL,
                    message="semantic citation version does not match expected content digest",
                    span_id=cite.span_id,
                    citation_id=cite.citation_id,
                )

            if admission is CitationAdmission.ADMITTED:
                reasons.append(SpanValidationReasonCode.CITATION_ADMITTED.value)
                admitted.append(cite.citation_id)
                if SpanValidationReasonCode.CITATION_ADMITTED.value not in reason_codes:
                    reason_codes.append(
                        SpanValidationReasonCode.CITATION_ADMITTED.value
                    )
            else:
                if SpanValidationReasonCode.CITATION_REJECTED.value not in reasons:
                    reasons.append(SpanValidationReasonCode.CITATION_REJECTED.value)
                rejected.append(cite.citation_id)
                if SpanValidationReasonCode.CITATION_REJECTED.value not in reason_codes:
                    reason_codes.append(
                        SpanValidationReasonCode.CITATION_REJECTED.value
                    )

            citation_records.append(
                CitationValidationRecord(
                    schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
                    citation_id=cite.citation_id,
                    span_id=cite.span_id,
                    artifact_id=cite.artifact_id,
                    admission=admission,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            )

        # ---- Disposition ----
        has_critical = any(
            f.severity is FindingSeverity.CRITICAL for f in findings
        )
        has_error = any(f.severity is FindingSeverity.ERROR for f in findings)

        disposition = SpanValidationDisposition.VALID
        review_state = ReviewState.NOT_REQUIRED

        if unaccounted or invalid_span_ids or stale_span_ids or has_critical:
            disposition = SpanValidationDisposition.INVALID
            review_state = ReviewState.REQUIRED
        elif has_error or rejected:
            # Rejected citations with structural errors fail validation.
            if rejected:
                disposition = SpanValidationDisposition.INVALID
                review_state = ReviewState.REQUIRED
            else:
                disposition = SpanValidationDisposition.INVALID
                review_state = ReviewState.REQUIRED
        elif low_readability:
            # Low readability → unknown/review (never auto-valid).
            disposition = SpanValidationDisposition.UNKNOWN
            review_state = ReviewState.REQUIRED
            if SpanValidationReasonCode.LOW_READABILITY.value not in reason_codes:
                reason_codes.append(SpanValidationReasonCode.LOW_READABILITY.value)
        elif low_coverage or retained_disagreements:
            disposition = SpanValidationDisposition.REVIEW
            review_state = ReviewState.REQUIRED
        elif extraction.disposition in (
            ExtractionDisposition.REVIEW,
            ExtractionDisposition.QUARANTINE,
            ExtractionDisposition.REJECTED,
        ):
            # Mirror extraction review posture when spans themselves are clean.
            if extraction.disposition is ExtractionDisposition.REJECTED:
                disposition = SpanValidationDisposition.INVALID
            elif extraction.disposition is ExtractionDisposition.QUARANTINE:
                disposition = SpanValidationDisposition.UNKNOWN
            else:
                disposition = SpanValidationDisposition.REVIEW
            review_state = ReviewState.REQUIRED

        if requires_quarantine(extraction.classification):
            if disposition is SpanValidationDisposition.VALID:
                disposition = SpanValidationDisposition.UNKNOWN
            review_state = ReviewState.REQUIRED

        if disposition is SpanValidationDisposition.VALID and not findings:
            reason_codes.append(SpanValidationReasonCode.VALIDATION_PASSED.value)
        elif disposition is SpanValidationDisposition.VALID:
            if SpanValidationReasonCode.VALIDATION_PASSED.value not in reason_codes:
                reason_codes.append(SpanValidationReasonCode.VALIDATION_PASSED.value)

        if page_count == 0 and not extraction.spans:
            if SpanValidationReasonCode.EMPTY_EXTRACTION.value not in reason_codes:
                reason_codes.append(SpanValidationReasonCode.EMPTY_EXTRACTION.value)
            if disposition is SpanValidationDisposition.VALID:
                # Empty without pages is review, not a green validation.
                disposition = SpanValidationDisposition.REVIEW
                review_state = ReviewState.REQUIRED

        # Deduplicate id lists while preserving order.
        def _uniq(items: Iterable[str]) -> tuple[str, ...]:
            return tuple(dict.fromkeys(items))

        policy_snapshot = {
            "disagreement_review_score": f"{policy.disagreement_review_score:.4f}",
            "min_coverage_ratio": f"{policy.min_coverage_ratio:.4f}",
            "min_overall_coverage": f"{policy.min_overall_coverage:.4f}",
            "min_quote_similarity": f"{policy.min_quote_similarity:.4f}",
            "min_readability": f"{policy.min_readability:.4f}",
            "require_render_digest": str(policy.require_render_digest).lower(),
            "schema_version": SPAN_VALIDATOR_SCHEMA_VERSION,
        }

        return SpanValidationResult(
            schema_version=SPAN_VALIDATOR_SCHEMA_VERSION,
            validation_id=validation_id,
            extraction_id=extraction.extraction_id,
            artifact_id=extraction.artifact_id,
            content_sha256=extraction.content_sha256,
            disposition=disposition,
            review_state=review_state,
            classification=extraction.classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            findings=tuple(findings),
            retained_disagreements=tuple(retained_disagreements),
            citation_records=tuple(citation_records),
            overall_coverage=overall_coverage,
            overall_readability=overall_readability,
            page_count=page_count,
            span_count=len(extraction.spans),
            accounted_pages=len(coverage_by_page) - len(extra) if coverage_by_page else 0,
            unaccounted_pages=tuple(sorted(set(unaccounted))),
            invalid_span_ids=_uniq(invalid_span_ids),
            stale_span_ids=_uniq(stale_span_ids),
            admitted_citation_ids=_uniq(admitted),
            rejected_citation_ids=_uniq(rejected),
            labels=dict(inp.labels),
            policy_snapshot=policy_snapshot,
            retained=True,
        )


def validate_spans(
    extraction: DocumentExtractionResult | SpanValidationInput | Mapping[str, Any],
    *,
    expected_content_sha256: str | None = None,
    citations: Sequence[SemanticCitation | Mapping[str, Any]] | None = None,
    policy: SpanValidationPolicy | None = None,
    page_texts_override: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> SpanValidationResult:
    """Convenience wrapper around :class:`SpanValidator`."""
    return SpanValidator(policy=policy, id_factory=id_factory).validate(
        extraction,
        expected_content_sha256=expected_content_sha256,
        citations=citations,
        page_texts_override=page_texts_override,
        labels=labels,
    )


def admit_semantic_citations(
    extraction: DocumentExtractionResult,
    citations: Sequence[SemanticCitation | Mapping[str, Any]],
    *,
    policy: SpanValidationPolicy | None = None,
) -> SpanValidationResult:
    """Validate extraction and admit only citations with matching artifact version.

    Convenience for downstream parsers: fail-closed admission of facts that
    cite spans.
    """
    return validate_spans(
        extraction,
        expected_content_sha256=extraction.content_sha256,
        citations=citations,
        policy=policy,
    )


__all__ = [
    "SPAN_VALIDATOR_INTERFACE",
    "SPAN_VALIDATOR_SCHEMA_VERSION",
    "CitationAdmission",
    "CitationValidationRecord",
    "FindingSeverity",
    "RetainedDisagreement",
    "SemanticCitation",
    "SpanValidationDisposition",
    "SpanValidationError",
    "SpanValidationFinding",
    "SpanValidationInput",
    "SpanValidationPolicy",
    "SpanValidationReasonCode",
    "SpanValidationResult",
    "SpanValidator",
    "admit_semantic_citations",
    "estimate_readability",
    "extract_quote",
    "sha256_hex",
    "text_digest",
    "validate_spans",
]
