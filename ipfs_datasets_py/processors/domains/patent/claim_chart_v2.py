"""Source-quoted claim charts with versioned reviewer dispositions (PATLAW-151).

Aligns accepted claim limitations with exact patent/NPL source spans, records
supporting and contradictory passages, ranks, and versioned reviewer
dispositions. Coverage gaps remain prominent. Every chart cell either links
claim **and** evidence spans or explicitly records ``not_found`` / ``unknown``.

Design invariants
-----------------
* Every cell binds a claim span; evidence spans are required unless the cell
  status is ``not_found`` or ``unknown``.
* Coverage gaps (foreign-patent, NPL, named unsearched sources) remain visible
  and are never silently closed.
* Reviewer changes are append-only versioned records (content digests).
* Outputs never claim an exhaustive search, novelty, obviousness, or
  patentability, and never auto-file an IDS.
* Unlicensed NPL body text is not reproduced; identifiers and gap notices only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .prior_art import (
    CoverageGap,
    CoverageGapKind,
    PriorArtError,
    SearchCorpus,
    default_coverage_gaps,
    default_foreign_patent_gap,
    default_npl_gap,
)
from .prior_art_coverage import (
    NamedCoverageGap,
    PriorArtCoverageDeclaration,
)
from .retrieval_contracts import SourceLink, SourceSpan
from .search_journal import JournalHit, make_source_link

# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------

CLAIM_CHART_V2_SCHEMA_VERSION: Final = "patent.claim_chart.v2"
CLAIM_CHART_V2_INTERFACE: Final = "ClaimChartV2@1"
CLAIM_CHART_V2_CODE_VERSION: Final = "1.0.0"

OUTPUT_KIND_CLAIM_CHART_V2: Final = "claim_chart_v2"
OUTPUT_KIND_CHART_CELL_V2: Final = "claim_chart_cell_v2"
OUTPUT_KIND_REVIEWER_CHANGE: Final = "claim_chart_reviewer_change_v2"
OUTPUT_KIND_COVERAGE_ACK: Final = "prior_art_coverage_acknowledgement_v2"
OUTPUT_KIND_PRIOR_ART_REVIEW: Final = "prior_art_review_package_v2"

CLAIM_CHART_V2_DISCLAIMER: Final = (
    "This artifact is a source-quoted claim chart for human review. Every cell "
    "links claim and evidence spans or explicitly records not_found/unknown. "
    "Coverage gaps remain prominent and are never treated as closed. This is "
    "not an exhaustive search, not a novelty, obviousness, or patentability "
    "determination, not legal advice, not an IDS filing, and not a substitute "
    "for a licensed search or counsel judgment."
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

DEFAULT_MAX_CELLS: Final = 512
DEFAULT_MAX_PASSAGES: Final = 32
DEFAULT_MAX_PASSAGE_CHARS: Final = 512
DEFAULT_MAX_REVIEWER_VERSIONS: Final = 256
DEFAULT_MAX_GAPS: Final = 128

_FORBIDDEN_CONCLUSION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anticipates",
        "exhaustive_search",
        "is_exhaustive",
        "is_novel",
        "is_obvious",
        "novelty",
        "novelty_conclusion",
        "obviousness",
        "obviousness_conclusion",
        "patentability",
        "patentability_conclusion",
        "patentable",
        "renders_obvious",
        "search_exhaustive",
        "unpatentable",
    }
)

_FORBIDDEN_CONCLUSION_PHRASES: Final[tuple[str, ...]] = (
    "exhaustive search",
    "search is complete",
    "search is exhaustive",
    "is novel",
    "is obvious",
    "is patentable",
    "is unpatentable",
    "novelty conclusion",
    "obviousness conclusion",
    "patentability conclusion",
    "anticipates claim",
    "renders claim obvious",
)

_EXHAUSTIVE_CLAIM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "exhaustive_search",
        "is_exhaustive",
        "search_exhaustive",
        "claims_exhaustive_search",
        "exhaustive",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ClaimChartV2Error(PriorArtError):
    """Base error for claim-chart v2 failures."""

    code: str = "claim_chart_v2_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class CellSpanError(ClaimChartV2Error):
    """Raised when a cell lacks required claim/evidence span linkage."""

    code = "cell_span_invalid"


class CoverageGapProminenceError(ClaimChartV2Error):
    """Raised when required coverage gaps are missing or not prominent."""

    code = "coverage_gap_not_prominent"


class ExhaustiveSearchClaimError(ClaimChartV2Error):
    """Raised when an artifact claims an exhaustive search."""

    code = "exhaustive_search_claimed"


class ReviewerVersionError(ClaimChartV2Error):
    """Raised on invalid reviewer-change versioning."""

    code = "reviewer_version_invalid"


class PatentabilityConclusionError(ClaimChartV2Error):
    """Raised when a chart asserts patentability conclusions."""

    code = "patentability_conclusion"


class CoverageAcknowledgementError(ClaimChartV2Error):
    """Raised when coverage acknowledgement is invalid or missing."""

    code = "coverage_acknowledgement_invalid"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CellStatus(str, Enum):
    """Disposition of one limitation × reference chart cell."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class PassagePolarity(str, Enum):
    """Whether a passage is offered as supporting or contradictory evidence."""

    SUPPORTING = "supporting"
    CONTRADICTORY = "contradictory"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class ReviewerDisposition(str, Enum):
    """Human disposition applied to a chart cell (not a legal conclusion)."""

    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    MARK_NOT_FOUND = "mark_not_found"
    MARK_UNKNOWN = "mark_unknown"
    FLAG_FOR_IDS = "flag_for_ids"
    DEFERRED = "deferred"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    import json

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid(value: Any, *, prefix: str = "bafybeigclaimchart") -> str:
    return f"{prefix}{content_digest(value)[:48]}"


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


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _iso_date(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=32)
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} must be YYYY-MM-DD, got {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _positive_int(value: Any, field: str) -> int:
    number = _nonneg_int(value, field)
    if number < 1:
        raise ValueError(f"{field} must be >= 1")
    return number


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be a finite float")
    return number


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


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


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _coerce_span(value: Any, field: str) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        return SourceSpan.from_dict(value)
    raise TypeError(f"{field} must be SourceSpan or mapping")


def _tuple_of_source_links(
    value: Any, field: str, *, max_items: int = 32, require: bool = False
) -> tuple[SourceLink, ...]:
    if value is None:
        links: tuple[SourceLink, ...] = ()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) > max_items:
            raise ValueError(f"{field} exceeds max items {max_items}")
        out: list[SourceLink] = []
        for i, item in enumerate(value):
            if isinstance(item, SourceLink):
                out.append(item)
            elif isinstance(item, Mapping):
                out.append(SourceLink.from_dict(item))
            else:
                raise TypeError(f"{field}[{i}] must be SourceLink or mapping")
        links = tuple(out)
    else:
        raise TypeError(f"{field} must be a sequence of SourceLink/mappings")
    if require and not links:
        raise CellSpanError(f"{field} must be non-empty")
    return links


def _assert_no_forbidden_keys(metadata: Mapping[str, str], label: str) -> None:
    for key in metadata:
        lowered = key.lower()
        if lowered in _FORBIDDEN_CONCLUSION_KEYS or lowered in _EXHAUSTIVE_CLAIM_KEYS:
            raise PatentabilityConclusionError(
                f"{label} metadata must not assert conclusion key {key!r}"
            )
        for phrase in _FORBIDDEN_CONCLUSION_PHRASES:
            if phrase in metadata[key].lower():
                raise PatentabilityConclusionError(
                    f"{label} metadata value must not assert {phrase!r}"
                )


def assert_no_patentability_conclusions(payload: Mapping[str, Any] | object) -> None:
    """Fail closed if a serialized chart carries patentability conclusions."""
    if not isinstance(payload, Mapping):
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()  # type: ignore[assignment]
        else:
            raise TypeError("payload must be a mapping or expose to_dict()")
    assert isinstance(payload, Mapping)

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_s = str(key)
                lowered = key_s.lower()
                if lowered in _FORBIDDEN_CONCLUSION_KEYS:
                    raise PatentabilityConclusionError(
                        f"forbidden conclusion field at {path}/{key_s}"
                    )
                if isinstance(value, str):
                    lower_val = value.lower()
                    for phrase in _FORBIDDEN_CONCLUSION_PHRASES:
                        if phrase in lower_val and key_s != "disclaimer":
                            raise PatentabilityConclusionError(
                                f"forbidden phrase {phrase!r} at {path}/{key_s}"
                            )
                _walk(value, f"{path}/{key_s}")
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(payload, "$")


def assert_no_exhaustive_search_claim(payload: Mapping[str, Any] | object) -> None:
    """Fail closed if any artifact claims an exhaustive / complete search."""
    if not isinstance(payload, Mapping):
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()  # type: ignore[assignment]
        else:
            raise TypeError("payload must be a mapping or expose to_dict()")
    assert isinstance(payload, Mapping)

    # Explicit flags must be False / absent.
    for key in (
        "claims_exhaustive_search",
        "exhaustive_search",
        "is_exhaustive",
        "search_exhaustive",
    ):
        if key in payload and payload[key] is not False:
            raise ExhaustiveSearchClaimError(
                f"output must not claim exhaustive search via {key}={payload[key]!r}"
            )

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_s = str(key)
                lowered = key_s.lower()
                if lowered in _EXHAUSTIVE_CLAIM_KEYS and value not in (False, None, 0):
                    if key_s == "disclaimer":
                        continue
                    raise ExhaustiveSearchClaimError(
                        f"exhaustive-search claim at {path}/{key_s}"
                    )
                if isinstance(value, str) and key_s != "disclaimer":
                    lower_val = value.lower()
                    for phrase in (
                        "exhaustive search",
                        "search is exhaustive",
                        "search is complete and exhaustive",
                    ):
                        if phrase in lower_val:
                            raise ExhaustiveSearchClaimError(
                                f"exhaustive-search phrase {phrase!r} at {path}/{key_s}"
                            )
                _walk(value, f"{path}/{key_s}")
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(payload, "$")


def _require_source_cid_and_span(
    links: Sequence[SourceLink], *, label: str
) -> None:
    if not links:
        raise CellSpanError(f"{label} missing source links")
    has_cid = False
    has_span = False
    for link in links:
        if link.source_cid:
            has_cid = True
        if link.span is not None:
            has_span = True
    if not has_cid:
        raise CellSpanError(f"{label} missing source CID")
    if not has_span:
        raise CellSpanError(f"{label} missing source span")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuotedEvidencePassage:
    """One source-quoted (or identifier-only) evidence passage for a cell.

    Body text is optional and must never carry unlicensed NPL content.
    """

    passage_id: str
    source_links: tuple[SourceLink, ...]
    polarity: PassagePolarity = PassagePolarity.UNKNOWN
    quoted_text: str | None = None
    rank: int | None = None
    score: float | None = None
    query_id: str | None = None
    document_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "passage_id", _identifier(self.passage_id, "passage_id")
        )
        links = _tuple_of_source_links(self.source_links, "source_links", require=True)
        _require_source_cid_and_span(links, label=f"passage {self.passage_id}")
        object.__setattr__(self, "source_links", links)
        object.__setattr__(
            self,
            "polarity",
            _coerce_enum(PassagePolarity, self.polarity, "polarity"),
        )
        object.__setattr__(
            self,
            "quoted_text",
            _optional_str(
                self.quoted_text, "quoted_text", max_len=DEFAULT_MAX_PASSAGE_CHARS
            ),
        )
        if self.rank is not None:
            object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        if self.score is not None:
            object.__setattr__(self, "score", _finite_float(self.score, "score"))
        object.__setattr__(
            self, "query_id", _optional_str(self.query_id, "query_id", max_len=256)
        )
        object.__setattr__(
            self,
            "document_id",
            _optional_str(self.document_id, "document_id", max_len=256),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "QuotedEvidencePassage")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "metadata": dict(self.metadata),
            "passage_id": self.passage_id,
            "polarity": self.polarity.value,
            "query_id": self.query_id,
            "quoted_text": self.quoted_text,
            "rank": self.rank,
            "score": self.score,
            "source_links": [link.to_dict() for link in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuotedEvidencePassage":
        value = _mapping(value, "QuotedEvidencePassage")
        return cls(
            passage_id=value.get("passage_id", ""),
            source_links=tuple(value.get("source_links") or ()),
            polarity=value.get("polarity", PassagePolarity.UNKNOWN.value),
            quoted_text=value.get("quoted_text"),
            rank=value.get("rank"),
            score=value.get("score"),
            query_id=value.get("query_id"),
            document_id=value.get("document_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ReviewerChangeVersion:
    """One versioned natural-person change to a chart cell disposition.

    Append-only: each version carries a content digest and optional previous
    version digest so reviewer history is reproducible.
    """

    change_id: str
    cell_id: str
    version: int
    reviewer_id: str
    changed_at_utc: str
    disposition: ReviewerDisposition
    notes: str | None = None
    previous_version_digest: str | None = None
    content_digest: str | None = None
    is_natural_person: bool = True
    output_kind: str = OUTPUT_KIND_REVIEWER_CHANGE
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", _identifier(self.change_id, "change_id"))
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(
            self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id")
        )
        object.__setattr__(
            self, "changed_at_utc", _iso_utc(self.changed_at_utc, "changed_at_utc")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ReviewerDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=4096)
        )
        object.__setattr__(
            self,
            "previous_version_digest",
            _optional_str(
                self.previous_version_digest, "previous_version_digest", max_len=64
            ),
        )
        if not isinstance(self.is_natural_person, bool):
            raise TypeError("is_natural_person must be bool")
        if not self.is_natural_person:
            raise ReviewerVersionError(
                "reviewer changes must be attributed to a natural person "
                f"(change {self.change_id})"
            )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_REVIEWER_CHANGE:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_REVIEWER_CHANGE!r}"
            )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ReviewerChangeVersion")
        # Compute content digest from identity fields (excluding content_digest).
        identity = {
            "cell_id": self.cell_id,
            "change_id": self.change_id,
            "changed_at_utc": self.changed_at_utc,
            "disposition": self.disposition.value,
            "is_natural_person": True,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "previous_version_digest": self.previous_version_digest,
            "reviewer_id": self.reviewer_id,
            "version": self.version,
        }
        digest = content_digest(identity)
        provided = _optional_str(self.content_digest, "content_digest", max_len=64)
        if provided is not None and provided.lower() != digest:
            raise ReviewerVersionError(
                f"content_digest mismatch for change {self.change_id}"
            )
        object.__setattr__(self, "content_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "change_id": self.change_id,
            "changed_at_utc": self.changed_at_utc,
            "content_digest": self.content_digest,
            "disposition": self.disposition.value,
            "is_natural_person": True,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "output_kind": self.output_kind,
            "previous_version_digest": self.previous_version_digest,
            "reviewer_id": self.reviewer_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewerChangeVersion":
        value = _mapping(value, "ReviewerChangeVersion")
        return cls(
            change_id=value.get("change_id", ""),
            cell_id=value.get("cell_id", ""),
            version=int(value.get("version") or 0),
            reviewer_id=value.get("reviewer_id", ""),
            changed_at_utc=value.get("changed_at_utc", ""),
            disposition=value.get(
                "disposition", ReviewerDisposition.UNREVIEWED.value
            ),
            notes=value.get("notes"),
            previous_version_digest=value.get("previous_version_digest"),
            content_digest=value.get("content_digest"),
            is_natural_person=bool(value.get("is_natural_person", True)),
            output_kind=value.get("output_kind", OUTPUT_KIND_REVIEWER_CHANGE),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ClaimChartCellV2:
    """One source-quoted chart cell: claim span × evidence spans (or status).

    Acceptance: every cell links claim and evidence spans **or** says
    ``not_found`` / ``unknown``.
    """

    cell_id: str
    limitation_id: str
    claim_number: int
    claim_span: SourceSpan
    status: CellStatus
    document_id: str | None = None
    evidence_links: tuple[SourceLink, ...] = ()
    supporting_passages: tuple[QuotedEvidencePassage, ...] = ()
    contradictory_passages: tuple[QuotedEvidencePassage, ...] = ()
    rank: int | None = None
    score: float | None = None
    query_id: str | None = None
    limitation_text: str | None = None
    claim_version_id: str | None = None
    claim_version_digest: str | None = None
    disposition: ReviewerDisposition = ReviewerDisposition.UNREVIEWED
    reviewer_history: tuple[ReviewerChangeVersion, ...] = ()
    output_kind: str = OUTPUT_KIND_CHART_CELL_V2
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        object.__setattr__(
            self, "limitation_id", _identifier(self.limitation_id, "limitation_id")
        )
        object.__setattr__(
            self, "claim_number", _positive_int(self.claim_number, "claim_number")
        )
        object.__setattr__(
            self, "claim_span", _coerce_span(self.claim_span, "claim_span")
        )
        object.__setattr__(
            self, "status", _coerce_enum(CellStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "document_id",
            _optional_str(self.document_id, "document_id", max_len=256),
        )
        links = _tuple_of_source_links(self.evidence_links, "evidence_links")
        object.__setattr__(self, "evidence_links", links)

        supporting = _coerce_passages(
            self.supporting_passages, "supporting_passages"
        )
        contradictory = _coerce_passages(
            self.contradictory_passages, "contradictory_passages"
        )
        if len(supporting) + len(contradictory) > DEFAULT_MAX_PASSAGES:
            raise ClaimChartV2Error(
                f"cell {self.cell_id} exceeds max passages {DEFAULT_MAX_PASSAGES}"
            )
        object.__setattr__(self, "supporting_passages", supporting)
        object.__setattr__(self, "contradictory_passages", contradictory)

        if self.rank is not None:
            object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        if self.score is not None:
            object.__setattr__(self, "score", _finite_float(self.score, "score"))
        object.__setattr__(
            self, "query_id", _optional_str(self.query_id, "query_id", max_len=256)
        )
        object.__setattr__(
            self,
            "limitation_text",
            _optional_str(self.limitation_text, "limitation_text", max_len=20_000),
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _optional_str(self.claim_version_id, "claim_version_id", max_len=256),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _optional_str(
                self.claim_version_digest, "claim_version_digest", max_len=64
            ),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ReviewerDisposition, self.disposition, "disposition"),
        )
        history = _coerce_reviewer_history(self.reviewer_history, "reviewer_history")
        if len(history) > DEFAULT_MAX_REVIEWER_VERSIONS:
            raise ReviewerVersionError(
                f"reviewer_history exceeds max {DEFAULT_MAX_REVIEWER_VERSIONS}"
            )
        _assert_reviewer_history_versioned(history, cell_id=self.cell_id)
        object.__setattr__(self, "reviewer_history", history)
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_CHART_CELL_V2:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_CHART_CELL_V2!r}"
            )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimChartCellV2")
        _assert_cell_span_contract(self)

    def current_reviewer_version(self) -> int:
        if not self.reviewer_history:
            return 0
        return max(h.version for h in self.reviewer_history)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "claim_number": self.claim_number,
            "claim_span": self.claim_span.to_dict(),
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "contradictory_passages": [p.to_dict() for p in self.contradictory_passages],
            "disposition": self.disposition.value,
            "document_id": self.document_id,
            "evidence_links": [link.to_dict() for link in self.evidence_links],
            "limitation_id": self.limitation_id,
            "limitation_text": self.limitation_text,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "query_id": self.query_id,
            "rank": self.rank,
            "reviewer_history": [h.to_dict() for h in self.reviewer_history],
            "score": self.score,
            "status": self.status.value,
            "supporting_passages": [p.to_dict() for p in self.supporting_passages],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimChartCellV2":
        value = _mapping(value, "ClaimChartCellV2")
        return cls(
            cell_id=value.get("cell_id", ""),
            limitation_id=value.get("limitation_id", ""),
            claim_number=int(value.get("claim_number") or 0),
            claim_span=value.get("claim_span") or {"start": 0, "end": 0},
            status=value.get("status", CellStatus.UNKNOWN.value),
            document_id=value.get("document_id"),
            evidence_links=tuple(value.get("evidence_links") or ()),
            supporting_passages=tuple(value.get("supporting_passages") or ()),
            contradictory_passages=tuple(value.get("contradictory_passages") or ()),
            rank=value.get("rank"),
            score=value.get("score"),
            query_id=value.get("query_id"),
            limitation_text=value.get("limitation_text"),
            claim_version_id=value.get("claim_version_id"),
            claim_version_digest=value.get("claim_version_digest"),
            disposition=value.get(
                "disposition", ReviewerDisposition.UNREVIEWED.value
            ),
            reviewer_history=tuple(value.get("reviewer_history") or ()),
            output_kind=value.get("output_kind", OUTPUT_KIND_CHART_CELL_V2),
            metadata=value.get("metadata") or {},
        )


def _coerce_passages(
    value: Any, field: str
) -> tuple[QuotedEvidencePassage, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[QuotedEvidencePassage] = []
    for i, item in enumerate(value):
        if isinstance(item, QuotedEvidencePassage):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(QuotedEvidencePassage.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be QuotedEvidencePassage or mapping")
    return tuple(out)


def _coerce_reviewer_history(
    value: Any, field: str
) -> tuple[ReviewerChangeVersion, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[ReviewerChangeVersion] = []
    for i, item in enumerate(value):
        if isinstance(item, ReviewerChangeVersion):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ReviewerChangeVersion.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be ReviewerChangeVersion or mapping")
    return tuple(sorted(out, key=lambda h: h.version))


def _assert_reviewer_history_versioned(
    history: Sequence[ReviewerChangeVersion], *, cell_id: str
) -> None:
    if not history:
        return
    versions = [h.version for h in history]
    if versions != sorted(versions):
        raise ReviewerVersionError(f"cell {cell_id} reviewer_history not ordered")
    if len(set(versions)) != len(versions):
        raise ReviewerVersionError(f"cell {cell_id} duplicate reviewer versions")
    prev_digest: str | None = None
    for h in history:
        if h.cell_id != cell_id:
            raise ReviewerVersionError(
                f"history change {h.change_id} cell_id mismatch"
            )
        if h.version == 1:
            if h.previous_version_digest is not None:
                raise ReviewerVersionError(
                    f"version 1 of cell {cell_id} must not set previous_version_digest"
                )
        else:
            if h.previous_version_digest is None:
                raise ReviewerVersionError(
                    f"version {h.version} of cell {cell_id} requires previous_version_digest"
                )
            if prev_digest is not None and h.previous_version_digest != prev_digest:
                raise ReviewerVersionError(
                    f"version {h.version} of cell {cell_id} previous_version_digest mismatch"
                )
        prev_digest = h.content_digest


def _assert_cell_span_contract(cell: ClaimChartCellV2) -> None:
    """Every cell links claim + evidence spans or says not_found/unknown."""
    # Claim span is always required (validated in __post_init__ via SourceSpan).
    if cell.claim_span is None:
        raise CellSpanError(f"cell {cell.cell_id} missing claim_span")

    status = cell.status
    if status is CellStatus.FOUND:
        if not cell.document_id:
            raise CellSpanError(
                f"cell {cell.cell_id} status=found requires document_id"
            )
        # Evidence must come from evidence_links and/or passages.
        evidence_links = list(cell.evidence_links)
        for passage in (*cell.supporting_passages, *cell.contradictory_passages):
            evidence_links.extend(passage.source_links)
        if not evidence_links:
            raise CellSpanError(
                f"cell {cell.cell_id} status=found requires evidence spans"
            )
        _require_source_cid_and_span(
            evidence_links, label=f"cell {cell.cell_id} evidence"
        )
    elif status in (CellStatus.NOT_FOUND, CellStatus.UNKNOWN):
        # Explicit negative / unknown: claim span only; no silent "found".
        pass
    else:
        raise CellSpanError(f"cell {cell.cell_id} has unknown status {status!r}")


@dataclass(frozen=True, slots=True)
class CoverageGapAcknowledgement:
    """Signed human acknowledgement of searched sources and remaining gaps.

    Required before packaging a prior-art review as complete for handoff.
    Never asserts the search was exhaustive.
    """

    acknowledgement_id: str
    subject_id: str
    chart_id: str
    acknowledger_id: str
    acknowledged_at_utc: str
    searched_sources: tuple[str, ...]
    gap_ids_acknowledged: tuple[str, ...]
    acknowledges_gaps_remain_visible: bool = True
    acknowledges_search_not_exhaustive: bool = True
    signature: str | None = None
    coverage_declaration_id: str | None = None
    is_natural_person: bool = True
    output_kind: str = OUTPUT_KIND_COVERAGE_ACK
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "acknowledgement_id",
            _identifier(self.acknowledgement_id, "acknowledgement_id"),
        )
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(self, "chart_id", _identifier(self.chart_id, "chart_id"))
        object.__setattr__(
            self,
            "acknowledger_id",
            _identifier(self.acknowledger_id, "acknowledger_id"),
        )
        object.__setattr__(
            self,
            "acknowledged_at_utc",
            _iso_utc(self.acknowledged_at_utc, "acknowledged_at_utc"),
        )
        if not isinstance(self.searched_sources, Sequence) or isinstance(
            self.searched_sources, (str, bytes)
        ):
            raise TypeError("searched_sources must be a sequence of strings")
        sources = tuple(
            _require_str(s, f"searched_sources[{i}]", max_len=256)
            for i, s in enumerate(self.searched_sources)
        )
        object.__setattr__(self, "searched_sources", sources)
        if not isinstance(self.gap_ids_acknowledged, Sequence) or isinstance(
            self.gap_ids_acknowledged, (str, bytes)
        ):
            raise TypeError("gap_ids_acknowledged must be a sequence of strings")
        gaps = tuple(
            _identifier(g, f"gap_ids_acknowledged[{i}]")
            for i, g in enumerate(self.gap_ids_acknowledged)
        )
        if not gaps:
            raise CoverageAcknowledgementError(
                "gap_ids_acknowledged must be non-empty; coverage gaps must remain "
                "prominent and explicitly acknowledged"
            )
        object.__setattr__(self, "gap_ids_acknowledged", gaps)
        if self.acknowledges_gaps_remain_visible is not True:
            raise CoverageAcknowledgementError(
                "acknowledges_gaps_remain_visible must be True"
            )
        if self.acknowledges_search_not_exhaustive is not True:
            raise CoverageAcknowledgementError(
                "acknowledges_search_not_exhaustive must be True; "
                "no output may claim an exhaustive search"
            )
        object.__setattr__(
            self,
            "signature",
            _optional_str(self.signature, "signature", max_len=4096),
        )
        object.__setattr__(
            self,
            "coverage_declaration_id",
            _optional_str(
                self.coverage_declaration_id,
                "coverage_declaration_id",
                max_len=256,
            ),
        )
        if not isinstance(self.is_natural_person, bool):
            raise TypeError("is_natural_person must be bool")
        if not self.is_natural_person:
            raise CoverageAcknowledgementError(
                "coverage acknowledgement must be signed by a natural person"
            )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_COVERAGE_ACK:
            raise ValueError(f"output_kind must be {OUTPUT_KIND_COVERAGE_ACK!r}")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "CoverageGapAcknowledgement")

    @property
    def is_signed(self) -> bool:
        return bool(self.signature)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acknowledgement_id": self.acknowledgement_id,
            "acknowledged_at_utc": self.acknowledged_at_utc,
            "acknowledger_id": self.acknowledger_id,
            "acknowledges_gaps_remain_visible": True,
            "acknowledges_search_not_exhaustive": True,
            "chart_id": self.chart_id,
            "coverage_declaration_id": self.coverage_declaration_id,
            "gap_ids_acknowledged": list(self.gap_ids_acknowledged),
            "is_natural_person": True,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "searched_sources": list(self.searched_sources),
            "signature": self.signature,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGapAcknowledgement":
        value = _mapping(value, "CoverageGapAcknowledgement")
        return cls(
            acknowledgement_id=value.get("acknowledgement_id", ""),
            subject_id=value.get("subject_id", ""),
            chart_id=value.get("chart_id", ""),
            acknowledger_id=value.get("acknowledger_id", ""),
            acknowledged_at_utc=value.get("acknowledged_at_utc", ""),
            searched_sources=tuple(value.get("searched_sources") or ()),
            gap_ids_acknowledged=tuple(value.get("gap_ids_acknowledged") or ()),
            acknowledges_gaps_remain_visible=bool(
                value.get("acknowledges_gaps_remain_visible", True)
            ),
            acknowledges_search_not_exhaustive=bool(
                value.get("acknowledges_search_not_exhaustive", True)
            ),
            signature=value.get("signature"),
            coverage_declaration_id=value.get("coverage_declaration_id"),
            is_natural_person=bool(value.get("is_natural_person", True)),
            output_kind=value.get("output_kind", OUTPUT_KIND_COVERAGE_ACK),
            metadata=value.get("metadata") or {},
        )


def sign_coverage_acknowledgement(
    ack: CoverageGapAcknowledgement,
    *,
    signature: str,
) -> CoverageGapAcknowledgement:
    """Attach a natural-person signature to a coverage acknowledgement."""
    sig = _require_str(signature, "signature", max_len=4096)
    return CoverageGapAcknowledgement(
        acknowledgement_id=ack.acknowledgement_id,
        subject_id=ack.subject_id,
        chart_id=ack.chart_id,
        acknowledger_id=ack.acknowledger_id,
        acknowledged_at_utc=ack.acknowledged_at_utc,
        searched_sources=ack.searched_sources,
        gap_ids_acknowledged=ack.gap_ids_acknowledged,
        acknowledges_gaps_remain_visible=True,
        acknowledges_search_not_exhaustive=True,
        signature=sig,
        coverage_declaration_id=ack.coverage_declaration_id,
        is_natural_person=True,
        metadata=dict(ack.metadata),
    )


# ---------------------------------------------------------------------------
# Claim chart v2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimChartV2:
    """Source-quoted claim chart with prominent coverage gaps.

    Acceptance: every cell links claim/evidence spans or says not_found/unknown;
    coverage gaps remain prominent; reviewer changes are versioned; never claims
    exhaustive search or patentability.
    """

    schema_version: str
    chart_id: str
    subject_id: str
    filing_date: str
    priority_date: str
    search_date_utc: str
    cells: tuple[ClaimChartCellV2, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    named_coverage_gaps: tuple[NamedCoverageGap, ...] = ()
    plan_id: str | None = None
    claim_version_id: str | None = None
    claim_version_digest: str | None = None
    coverage_declaration_id: str | None = None
    coverage_acknowledgement: CoverageGapAcknowledgement | None = None
    claims_exhaustive_search: bool = False
    coverage_gaps_prominent: bool = True
    output_kind: str = OUTPUT_KIND_CLAIM_CHART_V2
    disclaimer: str = CLAIM_CHART_V2_DISCLAIMER
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        schema = _require_str(self.schema_version, "schema_version", max_len=64)
        if schema != CLAIM_CHART_V2_SCHEMA_VERSION:
            raise ClaimChartV2Error(
                f"schema_version must be {CLAIM_CHART_V2_SCHEMA_VERSION}, got {schema!r}"
            )
        object.__setattr__(self, "schema_version", schema)
        object.__setattr__(self, "chart_id", _identifier(self.chart_id, "chart_id"))
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self, "filing_date", _iso_date(self.filing_date, "filing_date")
        )
        object.__setattr__(
            self, "priority_date", _iso_date(self.priority_date, "priority_date")
        )
        object.__setattr__(
            self, "search_date_utc", _iso_utc(self.search_date_utc, "search_date_utc")
        )

        cells = _coerce_cells(self.cells, "cells")
        if len(cells) > DEFAULT_MAX_CELLS:
            raise ClaimChartV2Error(f"cells exceeds max {DEFAULT_MAX_CELLS}")
        object.__setattr__(self, "cells", cells)
        for cell in cells:
            _assert_cell_span_contract(cell)

        gaps = _coerce_coverage_gaps(self.coverage_gaps, "coverage_gaps")
        named = _coerce_named_gaps(self.named_coverage_gaps, "named_coverage_gaps")
        if len(gaps) + len(named) > DEFAULT_MAX_GAPS:
            raise CoverageGapProminenceError(
                f"coverage gaps exceed max {DEFAULT_MAX_GAPS}"
            )
        object.__setattr__(self, "coverage_gaps", gaps)
        object.__setattr__(self, "named_coverage_gaps", named)
        _assert_coverage_gaps_prominent(gaps, named)

        object.__setattr__(
            self, "plan_id", _optional_str(self.plan_id, "plan_id", max_len=256)
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _optional_str(self.claim_version_id, "claim_version_id", max_len=256),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _optional_str(
                self.claim_version_digest, "claim_version_digest", max_len=64
            ),
        )
        object.__setattr__(
            self,
            "coverage_declaration_id",
            _optional_str(
                self.coverage_declaration_id,
                "coverage_declaration_id",
                max_len=256,
            ),
        )

        if self.coverage_acknowledgement is not None:
            if isinstance(self.coverage_acknowledgement, Mapping):
                object.__setattr__(
                    self,
                    "coverage_acknowledgement",
                    CoverageGapAcknowledgement.from_dict(
                        self.coverage_acknowledgement
                    ),
                )
            elif not isinstance(
                self.coverage_acknowledgement, CoverageGapAcknowledgement
            ):
                raise TypeError(
                    "coverage_acknowledgement must be CoverageGapAcknowledgement, "
                    "mapping, or None"
                )
            ack = self.coverage_acknowledgement
            if ack.chart_id != self.chart_id:
                raise CoverageAcknowledgementError(
                    "coverage_acknowledgement.chart_id must match chart_id"
                )
            if ack.subject_id != self.subject_id:
                raise CoverageAcknowledgementError(
                    "coverage_acknowledgement.subject_id must match subject_id"
                )

        if self.claims_exhaustive_search is not False:
            raise ExhaustiveSearchClaimError(
                "claims_exhaustive_search must be False; no output may claim "
                "an exhaustive search"
            )
        object.__setattr__(self, "claims_exhaustive_search", False)

        if self.coverage_gaps_prominent is not True:
            raise CoverageGapProminenceError(
                "coverage_gaps_prominent must be True"
            )
        object.__setattr__(self, "coverage_gaps_prominent", True)

        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_CLAIM_CHART_V2:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_CLAIM_CHART_V2!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        lower_disc = self.disclaimer.lower()
        if "exhaustive" not in lower_disc and "not an exhaustive" not in lower_disc:
            # Require disclaimer to deny exhaustiveness.
            if "not an exhaustive search" not in lower_disc:
                raise ExhaustiveSearchClaimError(
                    "disclaimer must state that this is not an exhaustive search"
                )
        if "patentability" not in lower_disc:
            raise PatentabilityConclusionError(
                "disclaimer must state that patentability is not determined"
            )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimChartV2")
        assert_no_patentability_conclusions(self.to_dict())
        assert_no_exhaustive_search_claim(self.to_dict())

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    def cell_for_limitation(
        self, limitation_id: str
    ) -> tuple[ClaimChartCellV2, ...]:
        return tuple(c for c in self.cells if c.limitation_id == limitation_id)

    def not_found_cells(self) -> tuple[ClaimChartCellV2, ...]:
        return tuple(c for c in self.cells if c.status is CellStatus.NOT_FOUND)

    def unknown_cells(self) -> tuple[ClaimChartCellV2, ...]:
        return tuple(c for c in self.cells if c.status is CellStatus.UNKNOWN)

    def found_cells(self) -> tuple[ClaimChartCellV2, ...]:
        return tuple(c for c in self.cells if c.status is CellStatus.FOUND)

    def flagged_for_ids(self) -> tuple[ClaimChartCellV2, ...]:
        return tuple(
            c
            for c in self.cells
            if c.disposition is ReviewerDisposition.FLAG_FOR_IDS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cells": [c.to_dict() for c in self.cells],
            "chart_id": self.chart_id,
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "claims_exhaustive_search": False,
            "coverage_acknowledgement": (
                None
                if self.coverage_acknowledgement is None
                else self.coverage_acknowledgement.to_dict()
            ),
            "coverage_declaration_id": self.coverage_declaration_id,
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "coverage_gaps_prominent": True,
            "disclaimer": self.disclaimer,
            "filing_date": self.filing_date,
            "metadata": dict(self.metadata),
            "named_coverage_gaps": [g.to_dict() for g in self.named_coverage_gaps],
            "output_kind": self.output_kind,
            "plan_id": self.plan_id,
            "priority_date": self.priority_date,
            "schema_version": self.schema_version,
            "search_date_utc": self.search_date_utc,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimChartV2":
        value = _mapping(value, "ClaimChartV2")
        return cls(
            schema_version=value.get(
                "schema_version", CLAIM_CHART_V2_SCHEMA_VERSION
            ),
            chart_id=value.get("chart_id", ""),
            subject_id=value.get("subject_id", ""),
            filing_date=value.get("filing_date", ""),
            priority_date=value.get("priority_date", ""),
            search_date_utc=value.get("search_date_utc", ""),
            cells=tuple(value.get("cells") or ()),
            coverage_gaps=tuple(value.get("coverage_gaps") or ()),
            named_coverage_gaps=tuple(value.get("named_coverage_gaps") or ()),
            plan_id=value.get("plan_id"),
            claim_version_id=value.get("claim_version_id"),
            claim_version_digest=value.get("claim_version_digest"),
            coverage_declaration_id=value.get("coverage_declaration_id"),
            coverage_acknowledgement=value.get("coverage_acknowledgement"),
            claims_exhaustive_search=bool(
                value.get("claims_exhaustive_search", False)
            ),
            coverage_gaps_prominent=bool(
                value.get("coverage_gaps_prominent", True)
            ),
            output_kind=value.get("output_kind", OUTPUT_KIND_CLAIM_CHART_V2),
            disclaimer=value.get("disclaimer") or CLAIM_CHART_V2_DISCLAIMER,
            metadata=value.get("metadata") or {},
        )


def _coerce_cells(value: Any, field: str) -> tuple[ClaimChartCellV2, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[ClaimChartCellV2] = []
    for i, item in enumerate(value):
        if isinstance(item, ClaimChartCellV2):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ClaimChartCellV2.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be ClaimChartCellV2 or mapping")
    return tuple(out)


def _coerce_coverage_gaps(value: Any, field: str) -> tuple[CoverageGap, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[CoverageGap] = []
    for i, item in enumerate(value):
        if isinstance(item, CoverageGap):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(CoverageGap.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be CoverageGap or mapping")
    return tuple(out)


def _coerce_named_gaps(value: Any, field: str) -> tuple[NamedCoverageGap, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[NamedCoverageGap] = []
    for i, item in enumerate(value):
        if isinstance(item, NamedCoverageGap):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(NamedCoverageGap.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be NamedCoverageGap or mapping")
    return tuple(out)


def _assert_coverage_gaps_prominent(
    gaps: Sequence[CoverageGap],
    named: Sequence[NamedCoverageGap],
) -> None:
    """Foreign-patent and NPL gaps must remain visible/prominent."""
    kinds = {g.kind for g in gaps}
    corpora = {g.corpus for g in gaps if g.corpus is not None}
    named_corpora = {g.corpus for g in named if g.corpus is not None}

    has_foreign = (
        CoverageGapKind.FOREIGN_PATENT in kinds
        or SearchCorpus.FOREIGN_PATENTS in corpora
        or SearchCorpus.FOREIGN_PATENTS in named_corpora
    )
    has_npl = (
        CoverageGapKind.NPL in kinds
        or SearchCorpus.NPL in corpora
        or SearchCorpus.NPL in named_corpora
    )
    if not has_foreign:
        raise CoverageGapProminenceError(
            "foreign-patent coverage gap must remain prominent on the chart"
        )
    if not has_npl:
        raise CoverageGapProminenceError(
            "NPL coverage gap must remain prominent on the chart"
        )
    for g in gaps:
        if not g.remains_visible:
            raise CoverageGapProminenceError(
                f"coverage gap {g.gap_id} must remain_visible=True"
            )
    for g in named:
        if not g.remains_visible:
            raise CoverageGapProminenceError(
                f"named coverage gap {g.gap_id} must remain_visible=True"
            )


# ---------------------------------------------------------------------------
# Builders / mutators
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LimitationChartInput:
    """Minimal limitation surface accepted by :func:`build_claim_chart_v2`."""

    limitation_id: str
    claim_number: int
    text: str
    claim_span: SourceSpan
    claim_version_id: str | None = None
    claim_version_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "limitation_id", _identifier(self.limitation_id, "limitation_id")
        )
        object.__setattr__(
            self, "claim_number", _positive_int(self.claim_number, "claim_number")
        )
        object.__setattr__(
            self, "text", _require_str(self.text, "text", max_len=20_000)
        )
        object.__setattr__(
            self, "claim_span", _coerce_span(self.claim_span, "claim_span")
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _optional_str(self.claim_version_id, "claim_version_id", max_len=256),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _optional_str(
                self.claim_version_digest, "claim_version_digest", max_len=64
            ),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LimitationChartInput":
        value = _mapping(value, "LimitationChartInput")
        span_raw = value.get("claim_span") or value.get("source_claim_span")
        if span_raw is None:
            # Fallback: span over full text when only text is provided.
            text = str(value.get("text") or "")
            span_raw = {"start": 0, "end": max(len(text), 1), "unit": "char"}
        return cls(
            limitation_id=value.get("limitation_id", ""),
            claim_number=int(value.get("claim_number") or 0),
            text=value.get("text", ""),
            claim_span=span_raw,
            claim_version_id=value.get("claim_version_id"),
            claim_version_digest=value.get("claim_version_digest"),
        )

    @classmethod
    def coerce(cls, value: Any) -> "LimitationChartInput":
        if isinstance(value, LimitationChartInput):
            return value
        if isinstance(value, Mapping):
            return cls.from_mapping(value)
        # Duck-type LimitationCandidate / ClaimLimitationCandidate.
        if hasattr(value, "limitation_id") and hasattr(value, "claim_number"):
            span = getattr(value, "claim_span", None) or getattr(
                value, "source_claim_span", None
            )
            text = getattr(value, "text", "") or ""
            if span is None:
                span = SourceSpan(start=0, end=max(len(str(text)), 1), unit="char")
            return cls(
                limitation_id=value.limitation_id,
                claim_number=int(value.claim_number),
                text=str(text),
                claim_span=span,
                claim_version_id=getattr(value, "claim_version_id", None),
                claim_version_digest=getattr(value, "claim_version_digest", None),
            )
        raise TypeError(
            "limitation must be LimitationChartInput, mapping, or limitation-like"
        )


@dataclass(frozen=True, slots=True)
class EvidenceHitInput:
    """One ranked evidence hit to align against limitations."""

    document_id: str
    rank: int
    score: float
    source_links: tuple[SourceLink, ...]
    related_limitation_ids: tuple[str, ...] = ()
    passage_excerpt: str | None = None
    query_id: str | None = None
    polarity: PassagePolarity = PassagePolarity.SUPPORTING
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        object.__setattr__(self, "score", _finite_float(self.score, "score"))
        links = _tuple_of_source_links(
            self.source_links, "source_links", require=True
        )
        _require_source_cid_and_span(links, label=f"hit {self.document_id}")
        object.__setattr__(self, "source_links", links)
        if not isinstance(self.related_limitation_ids, Sequence) or isinstance(
            self.related_limitation_ids, (str, bytes)
        ):
            raise TypeError("related_limitation_ids must be a sequence")
        object.__setattr__(
            self,
            "related_limitation_ids",
            tuple(
                _identifier(x, f"related_limitation_ids[{i}]")
                for i, x in enumerate(self.related_limitation_ids)
            ),
        )
        object.__setattr__(
            self,
            "passage_excerpt",
            _optional_str(
                self.passage_excerpt,
                "passage_excerpt",
                max_len=DEFAULT_MAX_PASSAGE_CHARS,
            ),
        )
        object.__setattr__(
            self, "query_id", _optional_str(self.query_id, "query_id", max_len=256)
        )
        object.__setattr__(
            self,
            "polarity",
            _coerce_enum(PassagePolarity, self.polarity, "polarity"),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))

    @classmethod
    def from_journal_hit(
        cls,
        hit: JournalHit | Mapping[str, Any],
        *,
        related_limitation_ids: Sequence[str] = (),
        query_id: str | None = None,
        polarity: PassagePolarity | str = PassagePolarity.SUPPORTING,
    ) -> "EvidenceHitInput":
        if isinstance(hit, Mapping):
            hit = JournalHit.from_dict(hit)
        if not isinstance(hit, JournalHit):
            raise TypeError("hit must be JournalHit or mapping")
        return cls(
            document_id=hit.document_id,
            rank=hit.rank,
            score=hit.score,
            source_links=hit.source_links,
            related_limitation_ids=tuple(related_limitation_ids),
            passage_excerpt=hit.passage_excerpt,
            query_id=query_id,
            polarity=polarity,
            metadata=dict(hit.metadata),
        )


def build_claim_chart_v2(
    *,
    subject_id: str,
    filing_date: str,
    priority_date: str,
    search_date_utc: str,
    limitations: Sequence[Any],
    evidence_hits: Sequence[EvidenceHitInput | Mapping[str, Any] | JournalHit] = (),
    coverage_gaps: Sequence[CoverageGap | Mapping[str, Any]] | None = None,
    named_coverage_gaps: Sequence[NamedCoverageGap | Mapping[str, Any]] = (),
    plan_id: str | None = None,
    chart_id: str | None = None,
    claim_version_id: str | None = None,
    claim_version_digest: str | None = None,
    coverage_declaration: PriorArtCoverageDeclaration | None = None,
    coverage_acknowledgement: CoverageGapAcknowledgement | None = None,
    emit_not_found_for_unmatched: bool = True,
    metadata: Mapping[str, str] | None = None,
) -> ClaimChartV2:
    """Build a v2 claim chart aligning limitations with source-quoted evidence.

    Every limitation produces at least one cell. Limitations with no matching
    hits receive an explicit ``not_found`` cell when *emit_not_found_for_unmatched*
    is True (default), so coverage is never silent.
    """
    parsed_lims = [LimitationChartInput.coerce(item) for item in limitations]
    if not parsed_lims:
        raise ClaimChartV2Error("at least one limitation is required")

    parsed_hits: list[EvidenceHitInput] = []
    for item in evidence_hits:
        if isinstance(item, EvidenceHitInput):
            parsed_hits.append(item)
        elif isinstance(item, JournalHit):
            parsed_hits.append(EvidenceHitInput.from_journal_hit(item))
        elif isinstance(item, Mapping):
            if "source_links" in item and "document_id" in item:
                # Prefer EvidenceHitInput shape; fall back to JournalHit.
                try:
                    parsed_hits.append(
                        EvidenceHitInput(
                            document_id=item.get("document_id", ""),
                            rank=int(item.get("rank") or 1),
                            score=float(item.get("score") or 0.0),
                            source_links=tuple(item.get("source_links") or ()),
                            related_limitation_ids=tuple(
                                item.get("related_limitation_ids") or ()
                            ),
                            passage_excerpt=item.get("passage_excerpt"),
                            query_id=item.get("query_id"),
                            polarity=item.get(
                                "polarity", PassagePolarity.SUPPORTING.value
                            ),
                            metadata=item.get("metadata") or {},
                        )
                    )
                except (TypeError, ValueError):
                    parsed_hits.append(
                        EvidenceHitInput.from_journal_hit(
                            item,
                            related_limitation_ids=tuple(
                                item.get("related_limitation_ids") or ()
                            ),
                            query_id=item.get("query_id"),
                        )
                    )
            else:
                raise ClaimChartV2Error(
                    "evidence hit mapping must include document_id and source_links"
                )
        else:
            raise TypeError(
                "evidence_hits items must be EvidenceHitInput, JournalHit, or mapping"
            )

    lim_by_id = {lim.limitation_id: lim for lim in parsed_lims}
    cells: list[ClaimChartCellV2] = []
    matched_limitations: set[str] = set()

    for hit in parsed_hits:
        related = hit.related_limitation_ids or tuple(lim_by_id.keys())
        for lim_id in related:
            lim = lim_by_id.get(lim_id)
            if lim is None:
                continue
            matched_limitations.add(lim_id)
            passage = QuotedEvidencePassage(
                passage_id=f"pass:{lim_id}:{hit.document_id}:{hit.rank}",
                source_links=hit.source_links,
                polarity=hit.polarity,
                quoted_text=hit.passage_excerpt,
                rank=hit.rank,
                score=hit.score,
                query_id=hit.query_id,
                document_id=hit.document_id,
            )
            supporting = (
                (passage,)
                if hit.polarity
                in (PassagePolarity.SUPPORTING, PassagePolarity.NEUTRAL)
                else ()
            )
            contradictory = (
                (passage,) if hit.polarity is PassagePolarity.CONTRADICTORY else ()
            )
            # Neutral / unknown also go to supporting as default presentation.
            if hit.polarity is PassagePolarity.UNKNOWN:
                supporting = (passage,)
                contradictory = ()
            cell_id = f"cell:{lim_id}:{hit.document_id}:{hit.query_id or hit.rank}"
            if len(cell_id) > 200:
                cell_id = f"cell:{content_digest([lim_id, hit.document_id, hit.rank])[:24]}"
            cells.append(
                ClaimChartCellV2(
                    cell_id=cell_id,
                    limitation_id=lim.limitation_id,
                    claim_number=lim.claim_number,
                    claim_span=lim.claim_span,
                    status=CellStatus.FOUND,
                    document_id=hit.document_id,
                    evidence_links=hit.source_links,
                    supporting_passages=supporting,
                    contradictory_passages=contradictory,
                    rank=hit.rank,
                    score=hit.score,
                    query_id=hit.query_id,
                    limitation_text=lim.text,
                    claim_version_id=lim.claim_version_id or claim_version_id,
                    claim_version_digest=(
                        lim.claim_version_digest or claim_version_digest
                    ),
                )
            )

    if emit_not_found_for_unmatched:
        for lim in parsed_lims:
            if lim.limitation_id in matched_limitations:
                continue
            cells.append(
                ClaimChartCellV2(
                    cell_id=f"cell:{lim.limitation_id}:not_found",
                    limitation_id=lim.limitation_id,
                    claim_number=lim.claim_number,
                    claim_span=lim.claim_span,
                    status=CellStatus.NOT_FOUND,
                    document_id=None,
                    evidence_links=(),
                    limitation_text=lim.text,
                    claim_version_id=lim.claim_version_id or claim_version_id,
                    claim_version_digest=(
                        lim.claim_version_digest or claim_version_digest
                    ),
                    metadata={"reason": "no_matching_evidence_hit"},
                )
            )

    if coverage_gaps is None:
        if coverage_declaration is not None:
            gaps = coverage_declaration.to_prior_art_coverage_gaps()
        else:
            gaps = default_coverage_gaps()
    else:
        gaps = _coerce_coverage_gaps(coverage_gaps, "coverage_gaps")

    # Ensure foreign + NPL remain present even if caller omitted them.
    kinds = {g.kind for g in gaps}
    gap_list = list(gaps)
    if CoverageGapKind.FOREIGN_PATENT not in kinds:
        gap_list.insert(0, default_foreign_patent_gap())
    if CoverageGapKind.NPL not in kinds:
        gap_list.append(default_npl_gap())
    gaps = tuple(gap_list)

    named = _coerce_named_gaps(named_coverage_gaps, "named_coverage_gaps")
    if coverage_declaration is not None and not named:
        named = coverage_declaration.named_gaps

    identity = {
        "cells": [c.to_dict() for c in cells],
        "filing_date": filing_date,
        "priority_date": priority_date,
        "search_date_utc": search_date_utc,
        "subject_id": subject_id,
    }
    digest = content_digest(identity)[:16]
    decl_id = None
    if coverage_declaration is not None:
        decl_id = coverage_declaration.declaration_id

    return ClaimChartV2(
        schema_version=CLAIM_CHART_V2_SCHEMA_VERSION,
        chart_id=chart_id or f"chart:v2:{digest}",
        subject_id=subject_id,
        filing_date=filing_date,
        priority_date=priority_date,
        search_date_utc=search_date_utc,
        cells=tuple(cells),
        coverage_gaps=gaps,
        named_coverage_gaps=named,
        plan_id=plan_id,
        claim_version_id=claim_version_id,
        claim_version_digest=claim_version_digest,
        coverage_declaration_id=decl_id,
        coverage_acknowledgement=coverage_acknowledgement,
        claims_exhaustive_search=False,
        coverage_gaps_prominent=True,
        metadata=metadata or {},
    )


def apply_reviewer_disposition(
    chart: ClaimChartV2,
    *,
    cell_id: str,
    reviewer_id: str,
    disposition: ReviewerDisposition | str,
    changed_at_utc: str,
    notes: str | None = None,
    change_id: str | None = None,
    is_natural_person: bool = True,
    metadata: Mapping[str, str] | None = None,
) -> ClaimChartV2:
    """Append a versioned natural-person disposition change to a cell.

    Returns a new :class:`ClaimChartV2` (immutable update).
    """
    if not is_natural_person:
        raise ReviewerVersionError(
            "reviewer disposition changes require a natural person"
        )
    disp = _coerce_enum(ReviewerDisposition, disposition, "disposition")
    assert isinstance(disp, ReviewerDisposition)

    new_cells: list[ClaimChartCellV2] = []
    found = False
    for cell in chart.cells:
        if cell.cell_id != cell_id:
            new_cells.append(cell)
            continue
        found = True
        prev_version = cell.current_reviewer_version()
        next_version = prev_version + 1
        prev_digest = (
            cell.reviewer_history[-1].content_digest
            if cell.reviewer_history
            else None
        )
        change = ReviewerChangeVersion(
            change_id=change_id
            or f"chg:{cell_id}:v{next_version}:{content_digest([reviewer_id, changed_at_utc, disp.value])[:12]}",
            cell_id=cell.cell_id,
            version=next_version,
            reviewer_id=reviewer_id,
            changed_at_utc=changed_at_utc,
            disposition=disp,
            notes=notes,
            previous_version_digest=prev_digest,
            is_natural_person=True,
            metadata=metadata or {},
        )
        # Optionally update cell status when disposition forces not_found/unknown.
        new_status = cell.status
        if disp is ReviewerDisposition.MARK_NOT_FOUND:
            new_status = CellStatus.NOT_FOUND
        elif disp is ReviewerDisposition.MARK_UNKNOWN:
            new_status = CellStatus.UNKNOWN

        new_cells.append(
            ClaimChartCellV2(
                cell_id=cell.cell_id,
                limitation_id=cell.limitation_id,
                claim_number=cell.claim_number,
                claim_span=cell.claim_span,
                status=new_status,
                document_id=cell.document_id,
                evidence_links=cell.evidence_links,
                supporting_passages=cell.supporting_passages,
                contradictory_passages=cell.contradictory_passages,
                rank=cell.rank,
                score=cell.score,
                query_id=cell.query_id,
                limitation_text=cell.limitation_text,
                claim_version_id=cell.claim_version_id,
                claim_version_digest=cell.claim_version_digest,
                disposition=disp,
                reviewer_history=(*cell.reviewer_history, change),
                metadata=dict(cell.metadata),
            )
        )
    if not found:
        raise ClaimChartV2Error(f"cell_id {cell_id!r} not found on chart")

    # Rebuild FOUND cells that were marked not_found/unknown without forcing
    # evidence (status change already handled; evidence may remain for audit).
    # For MARK_NOT_FOUND / MARK_UNKNOWN we need cells that may still carry
    # evidence_links — _assert_cell_span_contract allows that for non-FOUND.
    # But if status becomes NOT_FOUND while document_id/evidence remain, that's OK.

    # Fix: when status is NOT_FOUND/UNKNOWN, ClaimChartCellV2 allows leftover
    # evidence. However if we set NOT_FOUND but keep status check for FOUND
    # requiring evidence — we're fine.
    # One issue: when MARK_NOT_FOUND on a FOUND cell, we still pass evidence —
    # allowed.

    return ClaimChartV2(
        schema_version=chart.schema_version,
        chart_id=chart.chart_id,
        subject_id=chart.subject_id,
        filing_date=chart.filing_date,
        priority_date=chart.priority_date,
        search_date_utc=chart.search_date_utc,
        cells=tuple(new_cells),
        coverage_gaps=chart.coverage_gaps,
        named_coverage_gaps=chart.named_coverage_gaps,
        plan_id=chart.plan_id,
        claim_version_id=chart.claim_version_id,
        claim_version_digest=chart.claim_version_digest,
        coverage_declaration_id=chart.coverage_declaration_id,
        coverage_acknowledgement=chart.coverage_acknowledgement,
        claims_exhaustive_search=False,
        coverage_gaps_prominent=True,
        disclaimer=chart.disclaimer,
        metadata=dict(chart.metadata),
    )


def attach_coverage_acknowledgement(
    chart: ClaimChartV2,
    acknowledgement: CoverageGapAcknowledgement,
) -> ClaimChartV2:
    """Attach a signed searched/gap acknowledgement to a chart."""
    if not acknowledgement.is_signed:
        raise CoverageAcknowledgementError(
            "coverage acknowledgement must be signed before attachment"
        )
    # Gap ids on the acknowledgement must cover chart gaps.
    chart_gap_ids = {g.gap_id for g in chart.coverage_gaps}
    chart_gap_ids.update(g.gap_id for g in chart.named_coverage_gaps)
    missing = chart_gap_ids - set(acknowledgement.gap_ids_acknowledged)
    if missing:
        raise CoverageAcknowledgementError(
            "acknowledgement must cover all prominent chart gaps; missing: "
            + ", ".join(sorted(missing))
        )
    return ClaimChartV2(
        schema_version=chart.schema_version,
        chart_id=chart.chart_id,
        subject_id=chart.subject_id,
        filing_date=chart.filing_date,
        priority_date=chart.priority_date,
        search_date_utc=chart.search_date_utc,
        cells=chart.cells,
        coverage_gaps=chart.coverage_gaps,
        named_coverage_gaps=chart.named_coverage_gaps,
        plan_id=chart.plan_id,
        claim_version_id=chart.claim_version_id,
        claim_version_digest=chart.claim_version_digest,
        coverage_declaration_id=chart.coverage_declaration_id,
        coverage_acknowledgement=acknowledgement,
        claims_exhaustive_search=False,
        coverage_gaps_prominent=True,
        disclaimer=chart.disclaimer,
        metadata=dict(chart.metadata),
    )


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def assert_cells_link_spans_or_status(
    chart: ClaimChartV2 | Mapping[str, Any],
) -> None:
    """Raise if any cell lacks claim/evidence spans without not_found/unknown."""
    if isinstance(chart, Mapping):
        chart = ClaimChartV2.from_dict(chart)
    if not chart.cells:
        raise CellSpanError("chart has no cells")
    for cell in chart.cells:
        _assert_cell_span_contract(cell)


def assert_coverage_gaps_prominent(
    chart: ClaimChartV2 | Mapping[str, Any],
) -> None:
    """Raise if foreign-patent / NPL (or named) gaps are not prominent."""
    if isinstance(chart, Mapping):
        chart = ClaimChartV2.from_dict(chart)
    if not chart.coverage_gaps_prominent:
        raise CoverageGapProminenceError("coverage_gaps_prominent is False")
    _assert_coverage_gaps_prominent(chart.coverage_gaps, chart.named_coverage_gaps)


def assert_reviewer_changes_versioned(
    chart: ClaimChartV2 | Mapping[str, Any],
) -> None:
    """Raise if any non-empty reviewer history is not properly versioned."""
    if isinstance(chart, Mapping):
        chart = ClaimChartV2.from_dict(chart)
    for cell in chart.cells:
        _assert_reviewer_history_versioned(
            cell.reviewer_history, cell_id=cell.cell_id
        )


def make_evidence_link(
    *,
    source_cid: str,
    artifact_id: str,
    start: int = 0,
    end: int = 1,
    source_receipt_id: str | None = None,
    authority_tier: str = "official-base",
) -> SourceLink:
    """Helper to build a span-bound evidence :class:`SourceLink`."""
    return make_source_link(
        source_cid=source_cid,
        artifact_id=artifact_id,
        start=start,
        end=end,
        source_receipt_id=source_receipt_id,
        authority_tier=authority_tier,
    )


__all__ = [
    "CLAIM_CHART_V2_CODE_VERSION",
    "CLAIM_CHART_V2_DISCLAIMER",
    "CLAIM_CHART_V2_INTERFACE",
    "CLAIM_CHART_V2_SCHEMA_VERSION",
    "OUTPUT_KIND_CHART_CELL_V2",
    "OUTPUT_KIND_CLAIM_CHART_V2",
    "OUTPUT_KIND_COVERAGE_ACK",
    "OUTPUT_KIND_PRIOR_ART_REVIEW",
    "OUTPUT_KIND_REVIEWER_CHANGE",
    "CellSpanError",
    "CellStatus",
    "ClaimChartCellV2",
    "ClaimChartV2",
    "ClaimChartV2Error",
    "CoverageAcknowledgementError",
    "CoverageGapAcknowledgement",
    "CoverageGapProminenceError",
    "EvidenceHitInput",
    "ExhaustiveSearchClaimError",
    "LimitationChartInput",
    "PassagePolarity",
    "PatentabilityConclusionError",
    "QuotedEvidencePassage",
    "ReviewerChangeVersion",
    "ReviewerDisposition",
    "ReviewerVersionError",
    "apply_reviewer_disposition",
    "assert_cells_link_spans_or_status",
    "assert_coverage_gaps_prominent",
    "assert_no_exhaustive_search_claim",
    "assert_no_patentability_conclusions",
    "assert_reviewer_changes_versioned",
    "attach_coverage_acknowledgement",
    "build_claim_chart_v2",
    "canonical_json",
    "content_cid",
    "content_digest",
    "make_evidence_link",
    "sign_coverage_acknowledgement",
]
