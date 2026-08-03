"""Versioned immutable USPTO value contracts.

These records form the shared serialization boundary for USPTO foundation
work. They intentionally contain no provider I/O, storage backends, or
package-level re-exports. Schema changes must be additive and versioned.

Every persistent record supports deterministic JSON round-trips via
``to_dict`` / ``from_dict`` and ``canonical_json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

CONTRACTS_SCHEMA_VERSION: Final = "uspto.contracts.v1"
CONTRACTS_INTERFACE: Final = "UsptoValueContracts@1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")


class DisclosureClassification(str, Enum):
    """Publication / confidentiality classification for USPTO artifacts.

    Unknown is a first-class value that must quarantine, never default to public.
    """

    PUBLIC_OFFICIAL = "public_official"
    PUBLIC_USER = "public_user"
    CONFIDENTIAL_APPLICATION = "confidential_application"
    PRIVILEGED_WORK_PRODUCT = "privileged_work_product"
    RESTRICTED_EXPORT_REVIEW = "restricted_export_review"
    CREDENTIAL_OR_PAYMENT = "credential_or_payment"
    UNKNOWN = "unknown"


class AssessmentStatus(str, Enum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"


class ReviewState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    REQUIRED = "required"
    COMPLETE = "complete"


class ExtractionOrigin(str, Enum):
    NATIVE = "native"
    OCR = "ocr"
    MERGED = "merged"
    METADATA = "metadata"
    UNKNOWN = "unknown"


class MatterEventKind(str, Enum):
    FILING = "filing"
    STATUS = "status"
    TRANSACTION = "transaction"
    DOCUMENT = "document"
    RESPONSE = "response"
    ALLOWANCE = "allowance"
    ABANDONMENT = "abandonment"
    APPEAL = "appeal"
    GRANT = "grant"
    OTHER = "other"


class AuthorityRelation(str, Enum):
    AUTHORITATIVE_ORIGINAL = "authoritative_original"
    DERIVATIVE = "derivative"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"
    UNKNOWN = "unknown"


# Most restrictive first. Used when merging classifications across inputs.
_CLASSIFICATION_RESTRICTIVENESS: Final[tuple[DisclosureClassification, ...]] = (
    DisclosureClassification.CREDENTIAL_OR_PAYMENT,
    DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
    DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
    DisclosureClassification.CONFIDENTIAL_APPLICATION,
    DisclosureClassification.UNKNOWN,
    DisclosureClassification.PUBLIC_USER,
    DisclosureClassification.PUBLIC_OFFICIAL,
)

_PUBLIC_CLASSIFICATIONS: Final[frozenset[DisclosureClassification]] = frozenset(
    {
        DisclosureClassification.PUBLIC_OFFICIAL,
        DisclosureClassification.PUBLIC_USER,
    }
)

_PRIVATE_CLASSIFICATIONS: Final[frozenset[DisclosureClassification]] = frozenset(
    {
        DisclosureClassification.CONFIDENTIAL_APPLICATION,
        DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
        DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
        DisclosureClassification.CREDENTIAL_OR_PAYMENT,
    }
)


def is_public_classification(value: DisclosureClassification | str) -> bool:
    return _coerce_classification(value) in _PUBLIC_CLASSIFICATIONS


def is_private_classification(value: DisclosureClassification | str) -> bool:
    return _coerce_classification(value) in _PRIVATE_CLASSIFICATIONS


def requires_quarantine(value: DisclosureClassification | str) -> bool:
    """Unknown (and only unknown by default) must quarantine before dispatch."""
    return _coerce_classification(value) is DisclosureClassification.UNKNOWN


def most_restrictive_classification(
    values: Iterable[DisclosureClassification | str],
) -> DisclosureClassification:
    """Return the most restrictive classification among *values*.

    Empty input fails closed to UNKNOWN.
    """
    seen: list[DisclosureClassification] = []
    for raw in values:
        seen.append(_coerce_classification(raw))
    if not seen:
        return DisclosureClassification.UNKNOWN
    rank = {c: i for i, c in enumerate(_CLASSIFICATION_RESTRICTIVENESS)}
    return min(seen, key=lambda c: rank[c])


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for contract round-trip equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


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


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


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


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    number = float(value)
    if number != number or number < 0.0 or number > 1.0:  # NaN check
        raise ValueError(f"{field} must be in [0.0, 1.0]")
    return number


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"unknown disclosure classification: {value!r}; quarantining requires "
                f"explicit {DisclosureClassification.UNKNOWN.value!r}"
            ) from exc
    raise TypeError(
        f"classification must be DisclosureClassification or str, got {type(value).__name__}"
    )


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        out.append(_require_str(item, f"{field}[{i}]", max_len=2048))
    return tuple(out)


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


@dataclass(frozen=True, slots=True)
class ApplicationIdentity:
    """Normalized USPTO application / publication / patent identifiers."""

    schema_version: str
    application_number: str | None
    publication_number: str | None
    patent_number: str | None
    source: str
    confidence: float | None
    unresolved_ambiguity: bool
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"ApplicationIdentity.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self,
            "publication_number",
            _optional_str(self.publication_number, "publication_number", max_len=64),
        )
        object.__setattr__(
            self,
            "patent_number",
            _optional_str(self.patent_number, "patent_number", max_len=64),
        )
        if not any(
            (self.application_number, self.publication_number, self.patent_number)
        ):
            raise ValueError(
                "ApplicationIdentity requires at least one of application_number, "
                "publication_number, patent_number"
            )
        object.__setattr__(self, "source", _require_str(self.source, "source", max_len=256))
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        if not isinstance(self.unresolved_ambiguity, bool):
            raise TypeError("unresolved_ambiguity must be bool")
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=32))

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "confidence": self.confidence,
            "notes": list(self.notes),
            "patent_number": self.patent_number,
            "publication_number": self.publication_number,
            "schema_version": self.schema_version,
            "source": self.source,
            "unresolved_ambiguity": self.unresolved_ambiguity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationIdentity":
        value = _mapping(value, "ApplicationIdentity")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "application_number",
                    "publication_number",
                    "patent_number",
                    "source",
                    "confidence",
                    "unresolved_ambiguity",
                    "notes",
                }
            ),
            "ApplicationIdentity",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            application_number=value.get("application_number"),
            publication_number=value.get("publication_number"),
            patent_number=value.get("patent_number"),
            source=value.get("source", ""),
            confidence=value.get("confidence"),
            unresolved_ambiguity=bool(value.get("unresolved_ambiguity", False)),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """Sanitized retrieval receipt for an upstream source interaction."""

    schema_version: str
    receipt_id: str
    endpoint: str
    retrieval_utc: str
    response_status: int
    upstream_id: str | None
    last_modified: str | None
    request_digest: str
    response_digest: str | None
    cache_hit: bool
    retry_count: int
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"SourceReceipt.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "endpoint", _require_str(self.endpoint, "endpoint", max_len=2048)
        )
        # ISO-8601 UTC string; keep as opaque validated non-empty text.
        object.__setattr__(
            self,
            "retrieval_utc",
            _require_str(self.retrieval_utc, "retrieval_utc", max_len=64),
        )
        if isinstance(self.response_status, bool) or not isinstance(
            self.response_status, int
        ):
            raise TypeError("response_status must be int")
        if self.response_status < 0 or self.response_status > 599:
            raise ValueError("response_status must be in 0..599")
        object.__setattr__(
            self, "upstream_id", _optional_str(self.upstream_id, "upstream_id", max_len=256)
        )
        object.__setattr__(
            self,
            "last_modified",
            _optional_str(self.last_modified, "last_modified", max_len=128),
        )
        object.__setattr__(
            self, "request_digest", _sha256_hex(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "response_digest",
            _optional_sha256_hex(self.response_digest, "response_digest"),
        )
        if not isinstance(self.cache_hit, bool):
            raise TypeError("cache_hit must be bool")
        object.__setattr__(self, "retry_count", _nonneg_int(self.retry_count, "retry_count"))
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_hit": self.cache_hit,
            "endpoint": self.endpoint,
            "last_modified": self.last_modified,
            "metadata": dict(self.metadata),
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "response_status": self.response_status,
            "retrieval_utc": self.retrieval_utc,
            "retry_count": self.retry_count,
            "schema_version": self.schema_version,
            "upstream_id": self.upstream_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceReceipt":
        value = _mapping(value, "SourceReceipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "receipt_id",
                    "endpoint",
                    "retrieval_utc",
                    "response_status",
                    "upstream_id",
                    "last_modified",
                    "request_digest",
                    "response_digest",
                    "cache_hit",
                    "retry_count",
                    "metadata",
                }
            ),
            "SourceReceipt",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            receipt_id=value.get("receipt_id", ""),
            endpoint=value.get("endpoint", ""),
            retrieval_utc=value.get("retrieval_utc", ""),
            response_status=value.get("response_status", 0),
            upstream_id=value.get("upstream_id"),
            last_modified=value.get("last_modified"),
            request_digest=value.get("request_digest", ""),
            response_digest=value.get("response_digest"),
            cache_hit=bool(value.get("cache_hit", False)),
            retry_count=value.get("retry_count", 0),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ExtractedSpan:
    """Page/character/bounding-box anchored span from an artifact."""

    schema_version: str
    span_id: str
    artifact_id: str
    page_index: int | None
    char_start: int | None
    char_end: int | None
    bbox: tuple[float, float, float, float] | None
    origin: ExtractionOrigin
    reading_order: int | None
    confidence: float | None
    text_digest: str | None
    image_digest: str | None
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"ExtractedSpan.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "span_id", _identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
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
            object.__setattr__(self, "char_end", _nonneg_int(self.char_end, "char_end"))
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be >= char_start")
        if self.bbox is not None:
            if (
                not isinstance(self.bbox, Sequence)
                or isinstance(self.bbox, (str, bytes))
                or len(self.bbox) != 4
            ):
                raise TypeError("bbox must be a 4-tuple of floats")
            coords = tuple(float(x) for x in self.bbox)
            object.__setattr__(self, "bbox", coords)
        object.__setattr__(
            self, "origin", _coerce_enum(ExtractionOrigin, self.origin, "origin")
        )
        if self.reading_order is not None:
            object.__setattr__(
                self, "reading_order", _nonneg_int(self.reading_order, "reading_order")
            )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "text_digest", _optional_sha256_hex(self.text_digest, "text_digest")
        )
        object.__setattr__(
            self, "image_digest", _optional_sha256_hex(self.image_digest, "image_digest")
        )
        object.__setattr__(
            self,
            "classification",
            _coerce_classification(self.classification),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "char_end": self.char_end,
            "char_start": self.char_start,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "image_digest": self.image_digest,
            "origin": self.origin.value,
            "page_index": self.page_index,
            "reading_order": self.reading_order,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExtractedSpan":
        value = _mapping(value, "ExtractedSpan")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "span_id",
                    "artifact_id",
                    "page_index",
                    "char_start",
                    "char_end",
                    "bbox",
                    "origin",
                    "reading_order",
                    "confidence",
                    "text_digest",
                    "image_digest",
                    "classification",
                }
            ),
            "ExtractedSpan",
        )
        bbox_raw = value.get("bbox")
        bbox: tuple[float, float, float, float] | None
        if bbox_raw is None:
            bbox = None
        else:
            bbox = (
                float(bbox_raw[0]),
                float(bbox_raw[1]),
                float(bbox_raw[2]),
                float(bbox_raw[3]),
            )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            span_id=value.get("span_id", ""),
            artifact_id=value.get("artifact_id", ""),
            page_index=value.get("page_index"),
            char_start=value.get("char_start"),
            char_end=value.get("char_end"),
            bbox=bbox,
            origin=value.get("origin", ExtractionOrigin.UNKNOWN.value),
            reading_order=value.get("reading_order"),
            confidence=value.get("confidence"),
            text_digest=value.get("text_digest"),
            image_digest=value.get("image_digest"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class GovernmentRequirement:
    """Instruction or requirement extracted from an office action or form."""

    schema_version: str
    requirement_id: str
    instruction_text_digest: str
    source_span_id: str
    requirement_type: str
    affected_claims: tuple[str, ...]
    legal_citations: tuple[str, ...]
    applicability_conditions: tuple[str, ...]
    proposed_date_rule: str | None
    exceptions: tuple[str, ...]
    parser_confidence: float | None
    review_state: ReviewState
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"GovernmentRequirement.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "requirement_id", _identifier(self.requirement_id, "requirement_id")
        )
        object.__setattr__(
            self,
            "instruction_text_digest",
            _sha256_hex(self.instruction_text_digest, "instruction_text_digest"),
        )
        object.__setattr__(
            self, "source_span_id", _identifier(self.source_span_id, "source_span_id")
        )
        object.__setattr__(
            self,
            "requirement_type",
            _require_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self,
            "affected_claims",
            _tuple_of_str(self.affected_claims, "affected_claims", max_items=256),
        )
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=128),
        )
        object.__setattr__(
            self,
            "applicability_conditions",
            _tuple_of_str(
                self.applicability_conditions, "applicability_conditions", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "proposed_date_rule",
            _optional_str(self.proposed_date_rule, "proposed_date_rule", max_len=256),
        )
        object.__setattr__(
            self, "exceptions", _tuple_of_str(self.exceptions, "exceptions", max_items=64)
        )
        object.__setattr__(
            self,
            "parser_confidence",
            _optional_float_01(self.parser_confidence, "parser_confidence"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_claims": list(self.affected_claims),
            "applicability_conditions": list(self.applicability_conditions),
            "classification": self.classification.value,
            "exceptions": list(self.exceptions),
            "instruction_text_digest": self.instruction_text_digest,
            "legal_citations": list(self.legal_citations),
            "parser_confidence": self.parser_confidence,
            "proposed_date_rule": self.proposed_date_rule,
            "requirement_id": self.requirement_id,
            "requirement_type": self.requirement_type,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_span_id": self.source_span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GovernmentRequirement":
        value = _mapping(value, "GovernmentRequirement")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "requirement_id",
                    "instruction_text_digest",
                    "source_span_id",
                    "requirement_type",
                    "affected_claims",
                    "legal_citations",
                    "applicability_conditions",
                    "proposed_date_rule",
                    "exceptions",
                    "parser_confidence",
                    "review_state",
                    "classification",
                }
            ),
            "GovernmentRequirement",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            requirement_id=value.get("requirement_id", ""),
            instruction_text_digest=value.get("instruction_text_digest", ""),
            source_span_id=value.get("source_span_id", ""),
            requirement_type=value.get("requirement_type", ""),
            affected_claims=tuple(value.get("affected_claims") or ()),
            legal_citations=tuple(value.get("legal_citations") or ()),
            applicability_conditions=tuple(value.get("applicability_conditions") or ()),
            proposed_date_rule=value.get("proposed_date_rule"),
            exceptions=tuple(value.get("exceptions") or ()),
            parser_confidence=value.get("parser_confidence"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class SubmissionFact:
    """Evidence-backed submission fact with span provenance only (no raw text)."""

    schema_version: str
    fact_id: str
    evidence_span_id: str
    fact_type: str
    affected_claims: tuple[str, ...]
    version: str
    extraction_status: str
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"SubmissionFact.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(
            self, "evidence_span_id", _identifier(self.evidence_span_id, "evidence_span_id")
        )
        object.__setattr__(
            self, "fact_type", _require_str(self.fact_type, "fact_type", max_len=128)
        )
        object.__setattr__(
            self,
            "affected_claims",
            _tuple_of_str(self.affected_claims, "affected_claims", max_items=256),
        )
        object.__setattr__(
            self, "version", _require_str(self.version, "version", max_len=64)
        )
        object.__setattr__(
            self,
            "extraction_status",
            _require_str(self.extraction_status, "extraction_status", max_len=64),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_claims": list(self.affected_claims),
            "classification": self.classification.value,
            "evidence_span_id": self.evidence_span_id,
            "extraction_status": self.extraction_status,
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionFact":
        value = _mapping(value, "SubmissionFact")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "fact_id",
                    "evidence_span_id",
                    "fact_type",
                    "affected_claims",
                    "version",
                    "extraction_status",
                    "classification",
                }
            ),
            "SubmissionFact",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            fact_id=value.get("fact_id", ""),
            evidence_span_id=value.get("evidence_span_id", ""),
            fact_type=value.get("fact_type", ""),
            affected_claims=tuple(value.get("affected_claims") or ()),
            version=value.get("version", "1"),
            extraction_status=value.get("extraction_status", "unknown"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class RequirementAssessment:
    """Fail-closed assessment of a government requirement against submission facts."""

    schema_version: str
    assessment_id: str
    requirement_id: str
    status: AssessmentStatus
    evidence_span_ids: tuple[str, ...]
    counter_evidence_span_ids: tuple[str, ...]
    authority_snapshot_id: str | None
    proof_result: str | None
    confidence: float | None
    reasons: tuple[str, ...]
    required_human_action: str | None
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"RequirementAssessment.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "assessment_id", _identifier(self.assessment_id, "assessment_id")
        )
        object.__setattr__(
            self, "requirement_id", _identifier(self.requirement_id, "requirement_id")
        )
        object.__setattr__(
            self, "status", _coerce_enum(AssessmentStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "evidence_span_ids",
            _tuple_of_str(self.evidence_span_ids, "evidence_span_ids", max_items=256),
        )
        object.__setattr__(
            self,
            "counter_evidence_span_ids",
            _tuple_of_str(
                self.counter_evidence_span_ids,
                "counter_evidence_span_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self,
            "authority_snapshot_id",
            _optional_identifier(self.authority_snapshot_id, "authority_snapshot_id"),
        )
        object.__setattr__(
            self,
            "proof_result",
            _optional_str(self.proof_result, "proof_result", max_len=128),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=64)
        )
        object.__setattr__(
            self,
            "required_human_action",
            _optional_str(
                self.required_human_action, "required_human_action", max_len=512
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if self.status is AssessmentStatus.UNKNOWN and not self.required_human_action:
            object.__setattr__(
                self,
                "required_human_action",
                "review_unknown_assessment",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "authority_snapshot_id": self.authority_snapshot_id,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "counter_evidence_span_ids": list(self.counter_evidence_span_ids),
            "evidence_span_ids": list(self.evidence_span_ids),
            "proof_result": self.proof_result,
            "reasons": list(self.reasons),
            "required_human_action": self.required_human_action,
            "requirement_id": self.requirement_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementAssessment":
        value = _mapping(value, "RequirementAssessment")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "assessment_id",
                    "requirement_id",
                    "status",
                    "evidence_span_ids",
                    "counter_evidence_span_ids",
                    "authority_snapshot_id",
                    "proof_result",
                    "confidence",
                    "reasons",
                    "required_human_action",
                    "classification",
                }
            ),
            "RequirementAssessment",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            assessment_id=value.get("assessment_id", ""),
            requirement_id=value.get("requirement_id", ""),
            status=value.get("status", AssessmentStatus.UNKNOWN.value),
            evidence_span_ids=tuple(value.get("evidence_span_ids") or ()),
            counter_evidence_span_ids=tuple(
                value.get("counter_evidence_span_ids") or ()
            ),
            authority_snapshot_id=value.get("authority_snapshot_id"),
            proof_result=value.get("proof_result"),
            confidence=value.get("confidence"),
            reasons=tuple(value.get("reasons") or ()),
            required_human_action=value.get("required_human_action"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateDeadline:
    """Computed candidate deadline with explicit assumptions and uncertainty."""

    schema_version: str
    deadline_id: str
    event_basis: str
    rule_chain: tuple[str, ...]
    calendar: str
    time_zone: str
    entity_status_assumption: str | None
    extension_assumption: str | None
    candidate_utc: str
    uncertainty: str
    reviewer_confirmation: ReviewState
    classification: DisclosureClassification

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"CandidateDeadline.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "deadline_id", _identifier(self.deadline_id, "deadline_id")
        )
        object.__setattr__(
            self, "event_basis", _require_str(self.event_basis, "event_basis", max_len=256)
        )
        object.__setattr__(
            self, "rule_chain", _tuple_of_str(self.rule_chain, "rule_chain", max_items=32)
        )
        object.__setattr__(
            self, "calendar", _require_str(self.calendar, "calendar", max_len=64)
        )
        object.__setattr__(
            self, "time_zone", _require_str(self.time_zone, "time_zone", max_len=64)
        )
        object.__setattr__(
            self,
            "entity_status_assumption",
            _optional_str(
                self.entity_status_assumption, "entity_status_assumption", max_len=128
            ),
        )
        object.__setattr__(
            self,
            "extension_assumption",
            _optional_str(self.extension_assumption, "extension_assumption", max_len=128),
        )
        object.__setattr__(
            self,
            "candidate_utc",
            _require_str(self.candidate_utc, "candidate_utc", max_len=64),
        )
        object.__setattr__(
            self, "uncertainty", _require_str(self.uncertainty, "uncertainty", max_len=256)
        )
        object.__setattr__(
            self,
            "reviewer_confirmation",
            _coerce_enum(ReviewState, self.reviewer_confirmation, "reviewer_confirmation"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "calendar": self.calendar,
            "candidate_utc": self.candidate_utc,
            "classification": self.classification.value,
            "deadline_id": self.deadline_id,
            "entity_status_assumption": self.entity_status_assumption,
            "event_basis": self.event_basis,
            "extension_assumption": self.extension_assumption,
            "reviewer_confirmation": self.reviewer_confirmation.value,
            "rule_chain": list(self.rule_chain),
            "schema_version": self.schema_version,
            "time_zone": self.time_zone,
            "uncertainty": self.uncertainty,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateDeadline":
        value = _mapping(value, "CandidateDeadline")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "deadline_id",
                    "event_basis",
                    "rule_chain",
                    "calendar",
                    "time_zone",
                    "entity_status_assumption",
                    "extension_assumption",
                    "candidate_utc",
                    "uncertainty",
                    "reviewer_confirmation",
                    "classification",
                }
            ),
            "CandidateDeadline",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            deadline_id=value.get("deadline_id", ""),
            event_basis=value.get("event_basis", ""),
            rule_chain=tuple(value.get("rule_chain") or ()),
            calendar=value.get("calendar", "US-federal"),
            time_zone=value.get("time_zone", "America/New_York"),
            entity_status_assumption=value.get("entity_status_assumption"),
            extension_assumption=value.get("extension_assumption"),
            candidate_utc=value.get("candidate_utc", ""),
            uncertainty=value.get("uncertainty", "unknown"),
            reviewer_confirmation=value.get(
                "reviewer_confirmation", ReviewState.REQUIRED.value
            ),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
        )


@dataclass(frozen=True, slots=True)
class MatterEvent:
    """Matter lifecycle event with source and temporal semantics."""

    schema_version: str
    event_id: str
    matter_id: str
    kind: MatterEventKind
    event_utc: str
    source_receipt_id: str | None
    description_digest: str | None
    related_artifact_ids: tuple[str, ...]
    classification: DisclosureClassification
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"MatterEvent.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(MatterEventKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "event_utc", _require_str(self.event_utc, "event_utc", max_len=64)
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self,
            "description_digest",
            _optional_sha256_hex(self.description_digest, "description_digest"),
        )
        object.__setattr__(
            self,
            "related_artifact_ids",
            _tuple_of_str(
                self.related_artifact_ids, "related_artifact_ids", max_items=256
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "description_digest": self.description_digest,
            "event_id": self.event_id,
            "event_utc": self.event_utc,
            "kind": self.kind.value,
            "matter_id": self.matter_id,
            "metadata": dict(self.metadata),
            "related_artifact_ids": list(self.related_artifact_ids),
            "schema_version": self.schema_version,
            "source_receipt_id": self.source_receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatterEvent":
        value = _mapping(value, "MatterEvent")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "event_id",
                    "matter_id",
                    "kind",
                    "event_utc",
                    "source_receipt_id",
                    "description_digest",
                    "related_artifact_ids",
                    "classification",
                    "metadata",
                }
            ),
            "MatterEvent",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            event_id=value.get("event_id", ""),
            matter_id=value.get("matter_id", ""),
            kind=value.get("kind", MatterEventKind.OTHER.value),
            event_utc=value.get("event_utc", ""),
            source_receipt_id=value.get("source_receipt_id"),
            description_digest=value.get("description_digest"),
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class AnalysisBundle:
    """Immutable analysis package: input/output manifests and validation receipts."""

    schema_version: str
    bundle_id: str
    input_artifact_ids: tuple[str, ...]
    output_artifact_ids: tuple[str, ...]
    warning_codes: tuple[str, ...]
    unsupported_checks: tuple[str, ...]
    model_versions: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    validation_receipt_ids: tuple[str, ...]
    classification: DisclosureClassification
    review_state: ReviewState

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CONTRACTS_SCHEMA_VERSION:
            raise ValueError(
                f"AnalysisBundle.schema_version must be {CONTRACTS_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, "bundle_id"))
        object.__setattr__(
            self,
            "input_artifact_ids",
            _tuple_of_str(self.input_artifact_ids, "input_artifact_ids", max_items=512),
        )
        object.__setattr__(
            self,
            "output_artifact_ids",
            _tuple_of_str(self.output_artifact_ids, "output_artifact_ids", max_items=512),
        )
        object.__setattr__(
            self,
            "warning_codes",
            _tuple_of_str(self.warning_codes, "warning_codes", max_items=256),
        )
        object.__setattr__(
            self,
            "unsupported_checks",
            _tuple_of_str(self.unsupported_checks, "unsupported_checks", max_items=256),
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
                self.validation_receipt_ids, "validation_receipt_ids", max_items=128
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "review_state", _coerce_enum(ReviewState, self.review_state, "review_state")
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "classification": self.classification.value,
            "input_artifact_ids": list(self.input_artifact_ids),
            "model_versions": dict(self.model_versions),
            "output_artifact_ids": list(self.output_artifact_ids),
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "unsupported_checks": list(self.unsupported_checks),
            "validation_receipt_ids": list(self.validation_receipt_ids),
            "warning_codes": list(self.warning_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisBundle":
        value = _mapping(value, "AnalysisBundle")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "bundle_id",
                    "input_artifact_ids",
                    "output_artifact_ids",
                    "warning_codes",
                    "unsupported_checks",
                    "model_versions",
                    "ruleset_versions",
                    "validation_receipt_ids",
                    "classification",
                    "review_state",
                }
            ),
            "AnalysisBundle",
        )
        return cls(
            schema_version=value.get("schema_version", CONTRACTS_SCHEMA_VERSION),
            bundle_id=value.get("bundle_id", ""),
            input_artifact_ids=tuple(value.get("input_artifact_ids") or ()),
            output_artifact_ids=tuple(value.get("output_artifact_ids") or ()),
            warning_codes=tuple(value.get("warning_codes") or ()),
            unsupported_checks=tuple(value.get("unsupported_checks") or ()),
            model_versions=value.get("model_versions") or {},
            ruleset_versions=value.get("ruleset_versions") or {},
            validation_receipt_ids=tuple(value.get("validation_receipt_ids") or ()),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
        )


__all__ = [
    "CONTRACTS_INTERFACE",
    "CONTRACTS_SCHEMA_VERSION",
    "AnalysisBundle",
    "ApplicationIdentity",
    "AssessmentStatus",
    "AuthorityRelation",
    "CandidateDeadline",
    "DisclosureClassification",
    "ExtractedSpan",
    "ExtractionOrigin",
    "GovernmentRequirement",
    "MatterEvent",
    "MatterEventKind",
    "RequirementAssessment",
    "ReviewState",
    "SourceReceipt",
    "SubmissionFact",
    "canonical_json",
    "is_private_classification",
    "is_public_classification",
    "most_restrictive_classification",
    "requires_quarantine",
]
