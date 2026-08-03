"""Produce reproducible prior-art plans and claim charts (PATLAW-094).

Builds reviewable prior-art search plans and source-linked claim charts from
public claim text and hybrid retrieval hits. The module records exact dated
queries, ranks, cutoffs, and coverage gaps. It never asserts novelty,
obviousness, or patentability.

Design invariants
-----------------
* Filing, priority, and search dates are always explicit on every plan/report.
* Every claim-chart entry joins to at least one source CID and exact span.
* Generated limitations and keywords are always *candidates* (never source
  authority, never dispositive).
* Foreign-patent and NPL coverage gaps remain visible whenever those corpora
  were not searched (or were only partially covered).
* Output always carries a non-advice disclaimer and refuses patentability
  conclusion fields.
* Body text of unlicensed NPL is never reproduced; only identifiers/citations
  and gap notices are retained.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from .hybrid_retrieval import (
    HybridSearchRequest,
    HybridSearchResult,
    PatentHybridRetriever,
    apply_pre_ranking_filters,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeProvenance,
    PreRankingFilters,
    RankedHit,
    SourceLink,
    SourceSpan,
    assert_authority_claim_allowed,
    canonical_json as contracts_canonical_json,
)

# ---------------------------------------------------------------------------
# Versions / interface / disclaimers
# ---------------------------------------------------------------------------

PRIOR_ART_SCHEMA_VERSION: Final = "patent.prior_art.v1"
PRIOR_ART_INTERFACE: Final = "PriorArtPlanner@1"
PRIOR_ART_RULESET_VERSION: Final = "prior-art-rules@1"

OUTPUT_KIND_PRIOR_ART_PLAN: Final = "prior_art_search_plan"
OUTPUT_KIND_CLAIM_CHART: Final = "claim_chart"
OUTPUT_KIND_PRIOR_ART_REPORT: Final = "prior_art_report"

PRIOR_ART_DISCLAIMER: Final = (
    "This artifact is a reproducible prior-art search plan and/or source-linked "
    "claim chart for human review. Generated limitations and keywords are "
    "candidates only. Foreign-patent and non-patent literature (NPL) coverage "
    "gaps remain visible when those corpora were not searched. This output is "
    "not a novelty, obviousness, or patentability determination, not legal "
    "advice, not an IDS filing, and not a substitute for a licensed search."
)

# Conclusion keys that must never appear as asserted outcomes.
_FORBIDDEN_CONCLUSION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anticipates",
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
        "unpatentable",
    }
)

_FORBIDDEN_CONCLUSION_PHRASES: Final[tuple[str, ...]] = (
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

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_CID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9+=/_-]{7,255}\Z")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Claim-language splitters for deterministic limitation candidates.
_LIMITATION_SPLIT_RE = re.compile(
    r"\s*(?:,\s*and\s+|;\s*|\s+wherein\s+|\s+comprising\s+|\s+including\s+|"
    r"\s+characterized\s+by\s+)\s*",
    re.IGNORECASE,
)
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "of",
        "on",
        "or",
        "said",
        "the",
        "to",
        "with",
        "wherein",
        "comprising",
        "including",
        "method",
        "system",
        "apparatus",
        "device",
        "claim",
        "claims",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-/]{1,63}")
_CPC_IPC_RE = re.compile(
    r"\b([A-HY]\d{2}[A-Z]?\s*\d{1,4}/\d{2,6})\b", re.IGNORECASE
)

DEFAULT_RANK_CUTOFF: Final = 10
DEFAULT_MAX_LIMITATIONS: Final = 64
DEFAULT_MAX_KEYWORDS: Final = 64
DEFAULT_MAX_QUERIES: Final = 128
DEFAULT_MAX_CHART_ENTRIES: Final = 256
DEFAULT_MAX_QUERY_LOGS: Final = 256
DEFAULT_MAX_GAPS: Final = 64
DEFAULT_MAX_PASSAGE_CHARS: Final = 512

# Default fixture relative to repository tests/fixtures tree.
_GOLDEN_RELATIVE: Final = Path("tests/fixtures/patent/prior_art/golden_claim_chart.json")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PriorArtError(ValueError):
    """Base error for prior-art planner / claim-chart failures."""


class MissingTemporalAnchorError(PriorArtError):
    """Raised when filing, priority, or search dates are missing."""


class ChartSourceCitationError(PriorArtError):
    """Raised when a chart entry lacks a source CID and exact span."""


class PatentabilityConclusionError(PriorArtError):
    """Raised when a plan/report attempts a patentability conclusion."""


class CoverageGapVisibilityError(PriorArtError):
    """Raised when required foreign-patent / NPL gaps are not visible."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SearchCorpus(str, Enum):
    """Corpora that may be searched or recorded as gaps."""

    US_PATENTS = "us_patents"
    US_PUBLICATIONS = "us_publications"
    FOREIGN_PATENTS = "foreign_patents"
    NPL = "npl"


class QueryFamily(str, Enum):
    """Kind of prior-art query recorded in the plan / dated log."""

    KEYWORD = "keyword"
    CLASSIFICATION_CPC = "classification_cpc"
    CLASSIFICATION_IPC = "classification_ipc"
    CLAIM_LIMITATION = "claim_limitation"
    CITATION_EXPANSION = "citation_expansion"
    FAMILY_EXPANSION = "family_expansion"


class CoverageGapKind(str, Enum):
    """Visible coverage gaps that must not be silently closed."""

    FOREIGN_PATENT = "foreign_patent"
    NPL = "npl"
    UNSEARCHED_CORPUS = "unsearched_corpus"
    PARTIAL_COVERAGE = "partial_coverage"
    DATE_UNAVAILABLE = "date_unavailable"
    OTHER = "other"


class MaterialRole(str, Enum):
    """Whether material is generated (candidate) or source-bound."""

    CANDIDATE = "candidate"
    SOURCE_BOUND = "source_bound"


# ---------------------------------------------------------------------------
# Helpers (mirrors retrieval_contracts style)
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """SHA-256 hex digest of canonical JSON (no ``sha256:`` prefix)."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def _cid(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _CID_RE.match(text):
        raise ValueError(f"{field} is not a valid content identifier: {text!r}")
    return text


def _iso_date(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=32)
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} must be ISO calendar date YYYY-MM-DD, got {text!r}")
    return text


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
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
        raise TypeError(f"{field} must be float, got {type(value).__name__}")
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


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=2048) for i, item in enumerate(value))


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


def _schema_pinned(value: Any, expected: str, label: str) -> str:
    text = _require_str(value, f"{label}.schema_version", max_len=64)
    if text != expected:
        raise ValueError(f"{label}.schema_version must be {expected}, got {text!r}")
    return text


def _require_bool_true(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be bool")
    if not value:
        raise ValueError(f"{field} must be True")
    return True


def _tuple_of_source_links(value: Any, field: str, *, max_items: int = 32) -> tuple[SourceLink, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of SourceLink/mappings")
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
    return tuple(out)


def _assert_no_forbidden_keys(metadata: Mapping[str, str], label: str) -> None:
    for key in metadata:
        lowered = key.lower()
        if lowered in _FORBIDDEN_CONCLUSION_KEYS:
            raise PatentabilityConclusionError(
                f"{label} metadata must not assert patentability conclusion key {key!r}"
            )
        for phrase in _FORBIDDEN_CONCLUSION_PHRASES:
            if phrase in metadata[key].lower():
                raise PatentabilityConclusionError(
                    f"{label} metadata value must not assert {phrase!r}"
                )


def assert_no_patentability_conclusions(payload: Mapping[str, Any] | object) -> None:
    """Fail closed if a serialized plan/report carries patentability conclusions.

    Accepts a mapping (``to_dict`` output) or any object with ``to_dict``.
    """
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
                        f"forbidden patentability conclusion field at {path}/{key_s}"
                    )
                if isinstance(value, str):
                    lower_val = value.lower()
                    for phrase in _FORBIDDEN_CONCLUSION_PHRASES:
                        if phrase in lower_val:
                            raise PatentabilityConclusionError(
                                f"forbidden patentability phrase {phrase!r} at {path}/{key_s}"
                            )
                _walk(value, f"{path}/{key_s}")
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(payload, "$")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimLimitationCandidate:
    """One generated (candidate) claim limitation for review — never dispositive."""

    limitation_id: str
    claim_number: int
    text: str
    is_candidate: bool = True
    role: MaterialRole = MaterialRole.CANDIDATE
    authority_claim: AuthorityClaim = AuthorityClaim.NONE
    provenance: EdgeProvenance = EdgeProvenance.CANDIDATE
    ordinal: int = 1
    source_claim_span: SourceSpan | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

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
            self, "is_candidate", _require_bool_true(self.is_candidate, "is_candidate")
        )
        object.__setattr__(
            self, "role", _coerce_enum(MaterialRole, self.role, "role")
        )
        if self.role is not MaterialRole.CANDIDATE:
            raise ValueError("ClaimLimitationCandidate.role must be candidate")
        object.__setattr__(
            self,
            "authority_claim",
            _coerce_enum(AuthorityClaim, self.authority_claim, "authority_claim"),
        )
        object.__setattr__(
            self,
            "provenance",
            _coerce_enum(EdgeProvenance, self.provenance, "provenance"),
        )
        # Generated limitations cannot claim source authority.
        claim = assert_authority_claim_allowed(self.provenance, self.authority_claim)
        object.__setattr__(self, "authority_claim", claim)
        if self.authority_claim is AuthorityClaim.SOURCE_BOUND:
            raise PatentabilityConclusionError(
                "limitation candidates cannot claim source authority"
            )
        object.__setattr__(self, "ordinal", _positive_int(self.ordinal, "ordinal"))
        if self.source_claim_span is not None and not isinstance(
            self.source_claim_span, SourceSpan
        ):
            if isinstance(self.source_claim_span, Mapping):
                object.__setattr__(
                    self, "source_claim_span", SourceSpan.from_dict(self.source_claim_span)
                )
            else:
                raise TypeError("source_claim_span must be SourceSpan, mapping, or None")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimLimitationCandidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "claim_number": self.claim_number,
            "is_candidate": True,
            "limitation_id": self.limitation_id,
            "metadata": dict(self.metadata),
            "ordinal": self.ordinal,
            "provenance": self.provenance.value,
            "role": self.role.value,
            "source_claim_span": (
                None if self.source_claim_span is None else self.source_claim_span.to_dict()
            ),
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimLimitationCandidate":
        value = _mapping(value, "ClaimLimitationCandidate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority_claim",
                    "claim_number",
                    "is_candidate",
                    "limitation_id",
                    "metadata",
                    "ordinal",
                    "provenance",
                    "role",
                    "source_claim_span",
                    "text",
                }
            ),
            "ClaimLimitationCandidate",
        )
        span_raw = value.get("source_claim_span")
        span = (
            None
            if span_raw is None
            else (
                span_raw
                if isinstance(span_raw, SourceSpan)
                else SourceSpan.from_dict(span_raw)
            )
        )
        return cls(
            limitation_id=value.get("limitation_id", ""),
            claim_number=int(value.get("claim_number") or 0),
            text=value.get("text", ""),
            is_candidate=bool(value.get("is_candidate", True)),
            role=value.get("role", MaterialRole.CANDIDATE.value),
            authority_claim=value.get("authority_claim", AuthorityClaim.NONE.value),
            provenance=value.get("provenance", EdgeProvenance.CANDIDATE.value),
            ordinal=int(value.get("ordinal") or 1),
            source_claim_span=span,
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class KeywordCandidate:
    """One generated keyword / classification token candidate for query construction."""

    keyword_id: str
    text: str
    is_candidate: bool = True
    role: MaterialRole = MaterialRole.CANDIDATE
    authority_claim: AuthorityClaim = AuthorityClaim.NONE
    provenance: EdgeProvenance = EdgeProvenance.CANDIDATE
    kind: str = "keyword"
    related_limitation_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "keyword_id", _identifier(self.keyword_id, "keyword_id"))
        object.__setattr__(self, "text", _require_str(self.text, "text", max_len=512))
        object.__setattr__(
            self, "is_candidate", _require_bool_true(self.is_candidate, "is_candidate")
        )
        object.__setattr__(
            self, "role", _coerce_enum(MaterialRole, self.role, "role")
        )
        if self.role is not MaterialRole.CANDIDATE:
            raise ValueError("KeywordCandidate.role must be candidate")
        object.__setattr__(
            self,
            "authority_claim",
            _coerce_enum(AuthorityClaim, self.authority_claim, "authority_claim"),
        )
        object.__setattr__(
            self,
            "provenance",
            _coerce_enum(EdgeProvenance, self.provenance, "provenance"),
        )
        claim = assert_authority_claim_allowed(self.provenance, self.authority_claim)
        object.__setattr__(self, "authority_claim", claim)
        if self.authority_claim is AuthorityClaim.SOURCE_BOUND:
            raise PatentabilityConclusionError(
                "keyword candidates cannot claim source authority"
            )
        object.__setattr__(self, "kind", _require_str(self.kind, "kind", max_len=64))
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "KeywordCandidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "is_candidate": True,
            "keyword_id": self.keyword_id,
            "kind": self.kind,
            "metadata": dict(self.metadata),
            "provenance": self.provenance.value,
            "related_limitation_ids": list(self.related_limitation_ids),
            "role": self.role.value,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KeywordCandidate":
        value = _mapping(value, "KeywordCandidate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority_claim",
                    "is_candidate",
                    "keyword_id",
                    "kind",
                    "metadata",
                    "provenance",
                    "related_limitation_ids",
                    "role",
                    "text",
                }
            ),
            "KeywordCandidate",
        )
        return cls(
            keyword_id=value.get("keyword_id", ""),
            text=value.get("text", ""),
            is_candidate=bool(value.get("is_candidate", True)),
            role=value.get("role", MaterialRole.CANDIDATE.value),
            authority_claim=value.get("authority_claim", AuthorityClaim.NONE.value),
            provenance=value.get("provenance", EdgeProvenance.CANDIDATE.value),
            kind=value.get("kind", "keyword"),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SearchQuerySpec:
    """One planned query (keyword, classification, expansion) before execution."""

    query_id: str
    query_text: str
    family: QueryFamily
    intended_corpora: tuple[SearchCorpus, ...]
    rank_cutoff: int = DEFAULT_RANK_CUTOFF
    classification_codes: tuple[str, ...] = ()
    related_limitation_ids: tuple[str, ...] = ()
    related_keyword_ids: tuple[str, ...] = ()
    seed_document_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "query_text", _require_str(self.query_text, "query_text", max_len=4096)
        )
        object.__setattr__(
            self, "family", _coerce_enum(QueryFamily, self.family, "family")
        )
        corpora = self.intended_corpora or ()
        if not isinstance(corpora, Sequence) or isinstance(corpora, (str, bytes)):
            raise TypeError("intended_corpora must be a sequence of SearchCorpus")
        coerced = tuple(
            _coerce_enum(SearchCorpus, c, f"intended_corpora[{i}]")
            for i, c in enumerate(corpora)
        )
        if not coerced:
            raise ValueError("intended_corpora must be non-empty")
        object.__setattr__(self, "intended_corpora", coerced)
        object.__setattr__(
            self, "rank_cutoff", _positive_int(self.rank_cutoff, "rank_cutoff")
        )
        object.__setattr__(
            self,
            "classification_codes",
            _tuple_of_str(self.classification_codes, "classification_codes", max_items=32),
        )
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "related_keyword_ids",
            _tuple_of_str(self.related_keyword_ids, "related_keyword_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "seed_document_ids",
            _tuple_of_str(self.seed_document_ids, "seed_document_ids", max_items=64),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "SearchQuerySpec")

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification_codes": list(self.classification_codes),
            "family": self.family.value,
            "intended_corpora": [c.value for c in self.intended_corpora],
            "metadata": dict(self.metadata),
            "query_id": self.query_id,
            "query_text": self.query_text,
            "rank_cutoff": self.rank_cutoff,
            "related_keyword_ids": list(self.related_keyword_ids),
            "related_limitation_ids": list(self.related_limitation_ids),
            "seed_document_ids": list(self.seed_document_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SearchQuerySpec":
        value = _mapping(value, "SearchQuerySpec")
        _reject_unknown(
            value,
            frozenset(
                {
                    "classification_codes",
                    "family",
                    "intended_corpora",
                    "metadata",
                    "query_id",
                    "query_text",
                    "rank_cutoff",
                    "related_keyword_ids",
                    "related_limitation_ids",
                    "seed_document_ids",
                }
            ),
            "SearchQuerySpec",
        )
        return cls(
            query_id=value.get("query_id", ""),
            query_text=value.get("query_text", ""),
            family=value.get("family", QueryFamily.KEYWORD.value),
            intended_corpora=tuple(value.get("intended_corpora") or ()),
            rank_cutoff=int(value.get("rank_cutoff") or DEFAULT_RANK_CUTOFF),
            classification_codes=tuple(value.get("classification_codes") or ()),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            related_keyword_ids=tuple(value.get("related_keyword_ids") or ()),
            seed_document_ids=tuple(value.get("seed_document_ids") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """A coverage gap that remains visible on plans and reports."""

    gap_id: str
    kind: CoverageGapKind
    description: str
    corpus: SearchCorpus | None = None
    remains_visible: bool = True
    searched: bool = False
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(CoverageGapKind, self.kind, "kind")
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=2048),
        )
        if self.corpus is not None:
            object.__setattr__(
                self, "corpus", _coerce_enum(SearchCorpus, self.corpus, "corpus")
            )
        object.__setattr__(
            self,
            "remains_visible",
            _require_bool_true(self.remains_visible, "remains_visible"),
        )
        if not isinstance(self.searched, bool):
            raise TypeError("searched must be bool")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "CoverageGap")

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": None if self.corpus is None else self.corpus.value,
            "description": self.description,
            "gap_id": self.gap_id,
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "remains_visible": True,
            "searched": self.searched,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGap":
        value = _mapping(value, "CoverageGap")
        _reject_unknown(
            value,
            frozenset(
                {
                    "corpus",
                    "description",
                    "gap_id",
                    "kind",
                    "metadata",
                    "remains_visible",
                    "searched",
                }
            ),
            "CoverageGap",
        )
        return cls(
            gap_id=value.get("gap_id", ""),
            kind=value.get("kind", CoverageGapKind.OTHER.value),
            description=value.get("description", ""),
            corpus=value.get("corpus"),
            remains_visible=bool(value.get("remains_visible", True)),
            searched=bool(value.get("searched", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class RankedPassageHit:
    """One ranked hit recorded in a dated query log (with source citation)."""

    document_id: str
    rank: int
    score: float
    source_links: tuple[SourceLink, ...]
    passage_excerpt: str | None = None
    family: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        object.__setattr__(self, "score", _finite_float(self.score, "score"))
        links = _tuple_of_source_links(self.source_links, "source_links")
        if not links:
            raise ChartSourceCitationError(
                f"ranked hit {self.document_id} must cite at least one source link"
            )
        _require_source_cid_and_span(links, label=f"hit:{self.document_id}")
        object.__setattr__(self, "source_links", links)
        excerpt = _optional_str(
            self.passage_excerpt, "passage_excerpt", max_len=DEFAULT_MAX_PASSAGE_CHARS
        )
        object.__setattr__(self, "passage_excerpt", excerpt)
        object.__setattr__(
            self, "family", _optional_str(self.family, "family", max_len=64)
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "RankedPassageHit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "family": self.family,
            "metadata": dict(self.metadata),
            "passage_excerpt": self.passage_excerpt,
            "rank": self.rank,
            "score": self.score,
            "source_links": [link.to_dict() for link in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RankedPassageHit":
        value = _mapping(value, "RankedPassageHit")
        _reject_unknown(
            value,
            frozenset(
                {
                    "document_id",
                    "family",
                    "metadata",
                    "passage_excerpt",
                    "rank",
                    "score",
                    "source_links",
                }
            ),
            "RankedPassageHit",
        )
        return cls(
            document_id=value.get("document_id", ""),
            rank=int(value.get("rank") or 0),
            score=float(value.get("score") or 0.0),
            source_links=tuple(value.get("source_links") or ()),
            passage_excerpt=value.get("passage_excerpt"),
            family=value.get("family"),
            metadata=value.get("metadata") or {},
        )


def _require_source_cid_and_span(
    links: Sequence[SourceLink], *, label: str
) -> None:
    """Every chart/log entry must join to source CID and at least one span."""
    if not links:
        raise ChartSourceCitationError(f"{label} missing source links")
    has_cid = False
    has_span = False
    for link in links:
        if link.source_cid:
            has_cid = True
        if link.span is not None:
            has_span = True
    if not has_cid:
        raise ChartSourceCitationError(f"{label} missing source CID")
    if not has_span:
        raise ChartSourceCitationError(f"{label} missing source span")


@dataclass(frozen=True, slots=True)
class DatedQueryLog:
    """Exact dated query log: query text, search time, ranks, cutoff, corpus."""

    log_id: str
    query_id: str
    query_text: str
    search_date_utc: str
    family: QueryFamily
    corpus: SearchCorpus
    rank_cutoff: int
    hits: tuple[RankedPassageHit, ...] = ()
    filters: PreRankingFilters | None = None
    related_limitation_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "log_id", _identifier(self.log_id, "log_id"))
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "query_text", _require_str(self.query_text, "query_text", max_len=4096)
        )
        object.__setattr__(
            self, "search_date_utc", _iso_utc(self.search_date_utc, "search_date_utc")
        )
        object.__setattr__(
            self, "family", _coerce_enum(QueryFamily, self.family, "family")
        )
        object.__setattr__(
            self, "corpus", _coerce_enum(SearchCorpus, self.corpus, "corpus")
        )
        object.__setattr__(
            self, "rank_cutoff", _positive_int(self.rank_cutoff, "rank_cutoff")
        )
        hits_raw = self.hits or ()
        if not isinstance(hits_raw, Sequence) or isinstance(hits_raw, (str, bytes)):
            raise TypeError("hits must be a sequence of RankedPassageHit")
        if len(hits_raw) > DEFAULT_MAX_CHART_ENTRIES:
            raise ValueError(f"hits exceeds max items {DEFAULT_MAX_CHART_ENTRIES}")
        parsed: list[RankedPassageHit] = []
        for i, item in enumerate(hits_raw):
            if isinstance(item, RankedPassageHit):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(RankedPassageHit.from_dict(item))
            else:
                raise TypeError(f"hits[{i}] must be RankedPassageHit or mapping")
            if parsed[-1].rank > self.rank_cutoff:
                # Keep hit but surface that it is past the planned cutoff.
                pass
        object.__setattr__(self, "hits", tuple(parsed))
        if self.filters is not None and not isinstance(self.filters, PreRankingFilters):
            if isinstance(self.filters, Mapping):
                object.__setattr__(
                    self, "filters", PreRankingFilters.from_dict(self.filters)
                )
            else:
                raise TypeError("filters must be PreRankingFilters, mapping, or None")
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "DatedQueryLog")

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus.value,
            "family": self.family.value,
            "filters": None if self.filters is None else self.filters.to_dict(),
            "hits": [h.to_dict() for h in self.hits],
            "log_id": self.log_id,
            "metadata": dict(self.metadata),
            "query_id": self.query_id,
            "query_text": self.query_text,
            "rank_cutoff": self.rank_cutoff,
            "related_limitation_ids": list(self.related_limitation_ids),
            "search_date_utc": self.search_date_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DatedQueryLog":
        value = _mapping(value, "DatedQueryLog")
        _reject_unknown(
            value,
            frozenset(
                {
                    "corpus",
                    "family",
                    "filters",
                    "hits",
                    "log_id",
                    "metadata",
                    "query_id",
                    "query_text",
                    "rank_cutoff",
                    "related_limitation_ids",
                    "search_date_utc",
                }
            ),
            "DatedQueryLog",
        )
        filters_raw = value.get("filters")
        filters = (
            None
            if filters_raw is None
            else (
                filters_raw
                if isinstance(filters_raw, PreRankingFilters)
                else PreRankingFilters.from_dict(filters_raw)
            )
        )
        return cls(
            log_id=value.get("log_id", ""),
            query_id=value.get("query_id", ""),
            query_text=value.get("query_text", ""),
            search_date_utc=value.get("search_date_utc", ""),
            family=value.get("family", QueryFamily.KEYWORD.value),
            corpus=value.get("corpus", SearchCorpus.US_PATENTS.value),
            rank_cutoff=int(value.get("rank_cutoff") or DEFAULT_RANK_CUTOFF),
            hits=tuple(value.get("hits") or ()),
            filters=filters,
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ClaimChartEntry:
    """One source-linked claim-chart cell (limitation × prior-art document)."""

    entry_id: str
    claim_number: int
    limitation_id: str
    document_id: str
    rank: int
    score: float
    source_links: tuple[SourceLink, ...]
    query_id: str | None = None
    log_id: str | None = None
    passage_excerpt: str | None = None
    role: MaterialRole = MaterialRole.SOURCE_BOUND
    authority_claim: AuthorityClaim = AuthorityClaim.SOURCE_BOUND
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _identifier(self.entry_id, "entry_id"))
        object.__setattr__(
            self, "claim_number", _positive_int(self.claim_number, "claim_number")
        )
        object.__setattr__(
            self, "limitation_id", _identifier(self.limitation_id, "limitation_id")
        )
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        object.__setattr__(self, "score", _finite_float(self.score, "score"))
        links = _tuple_of_source_links(self.source_links, "source_links")
        _require_source_cid_and_span(links, label=f"chart entry {self.entry_id}")
        object.__setattr__(self, "source_links", links)
        object.__setattr__(
            self, "query_id", _optional_str(self.query_id, "query_id", max_len=256)
        )
        object.__setattr__(
            self, "log_id", _optional_str(self.log_id, "log_id", max_len=256)
        )
        object.__setattr__(
            self,
            "passage_excerpt",
            _optional_str(
                self.passage_excerpt, "passage_excerpt", max_len=DEFAULT_MAX_PASSAGE_CHARS
            ),
        )
        object.__setattr__(
            self, "role", _coerce_enum(MaterialRole, self.role, "role")
        )
        object.__setattr__(
            self,
            "authority_claim",
            _coerce_enum(AuthorityClaim, self.authority_claim, "authority_claim"),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimChartEntry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "claim_number": self.claim_number,
            "document_id": self.document_id,
            "entry_id": self.entry_id,
            "limitation_id": self.limitation_id,
            "log_id": self.log_id,
            "metadata": dict(self.metadata),
            "passage_excerpt": self.passage_excerpt,
            "query_id": self.query_id,
            "rank": self.rank,
            "role": self.role.value,
            "score": self.score,
            "source_links": [link.to_dict() for link in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimChartEntry":
        value = _mapping(value, "ClaimChartEntry")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority_claim",
                    "claim_number",
                    "document_id",
                    "entry_id",
                    "limitation_id",
                    "log_id",
                    "metadata",
                    "passage_excerpt",
                    "query_id",
                    "rank",
                    "role",
                    "score",
                    "source_links",
                }
            ),
            "ClaimChartEntry",
        )
        return cls(
            entry_id=value.get("entry_id", ""),
            claim_number=int(value.get("claim_number") or 0),
            limitation_id=value.get("limitation_id", ""),
            document_id=value.get("document_id", ""),
            rank=int(value.get("rank") or 0),
            score=float(value.get("score") or 0.0),
            source_links=tuple(value.get("source_links") or ()),
            query_id=value.get("query_id"),
            log_id=value.get("log_id"),
            passage_excerpt=value.get("passage_excerpt"),
            role=value.get("role", MaterialRole.SOURCE_BOUND.value),
            authority_claim=value.get(
                "authority_claim", AuthorityClaim.SOURCE_BOUND.value
            ),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ClaimChart:
    """Source-linked claim chart; never asserts patentability."""

    schema_version: str
    chart_id: str
    subject_id: str
    filing_date: str
    priority_date: str
    search_date_utc: str
    entries: tuple[ClaimChartEntry, ...]
    limitations: tuple[ClaimLimitationCandidate, ...] = ()
    coverage_gaps: tuple[CoverageGap, ...] = ()
    output_kind: str = OUTPUT_KIND_CLAIM_CHART
    disclaimer: str = PRIOR_ART_DISCLAIMER
    plan_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(self.schema_version, PRIOR_ART_SCHEMA_VERSION, "ClaimChart"),
        )
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
        entries = _coerce_entries(self.entries, "entries")
        object.__setattr__(self, "entries", entries)
        for entry in entries:
            _require_source_cid_and_span(
                entry.source_links, label=f"chart entry {entry.entry_id}"
            )
        object.__setattr__(
            self, "limitations", _coerce_limitations(self.limitations, "limitations")
        )
        object.__setattr__(
            self, "coverage_gaps", _coerce_gaps(self.coverage_gaps, "coverage_gaps")
        )
        _assert_required_coverage_gaps_visible(self.coverage_gaps, label="ClaimChart")
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_CLAIM_CHART:
            raise ValueError(
                f"ClaimChart.output_kind must be {OUTPUT_KIND_CLAIM_CHART!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        if "patentability" not in self.disclaimer.lower():
            raise ValueError("disclaimer must state that patentability is not determined")
        object.__setattr__(
            self, "plan_id", _optional_str(self.plan_id, "plan_id", max_len=256)
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimChart")
        assert_no_patentability_conclusions(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_id": self.chart_id,
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "disclaimer": self.disclaimer,
            "entries": [e.to_dict() for e in self.entries],
            "filing_date": self.filing_date,
            "limitations": [lim.to_dict() for lim in self.limitations],
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "plan_id": self.plan_id,
            "priority_date": self.priority_date,
            "schema_version": self.schema_version,
            "search_date_utc": self.search_date_utc,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimChart":
        value = _mapping(value, "ClaimChart")
        _reject_unknown(
            value,
            frozenset(
                {
                    "chart_id",
                    "coverage_gaps",
                    "disclaimer",
                    "entries",
                    "filing_date",
                    "limitations",
                    "metadata",
                    "output_kind",
                    "plan_id",
                    "priority_date",
                    "schema_version",
                    "search_date_utc",
                    "subject_id",
                }
            ),
            "ClaimChart",
        )
        return cls(
            schema_version=value.get("schema_version", PRIOR_ART_SCHEMA_VERSION),
            chart_id=value.get("chart_id", ""),
            subject_id=value.get("subject_id", ""),
            filing_date=value.get("filing_date", ""),
            priority_date=value.get("priority_date", ""),
            search_date_utc=value.get("search_date_utc", ""),
            entries=tuple(value.get("entries") or ()),
            limitations=tuple(value.get("limitations") or ()),
            coverage_gaps=tuple(value.get("coverage_gaps") or ()),
            output_kind=value.get("output_kind", OUTPUT_KIND_CLAIM_CHART),
            disclaimer=value.get("disclaimer", PRIOR_ART_DISCLAIMER),
            plan_id=value.get("plan_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PriorArtSearchPlan:
    """Reproducible prior-art search plan with explicit temporal anchors."""

    schema_version: str
    plan_id: str
    subject_id: str
    filing_date: str
    priority_date: str
    search_date_utc: str
    claims: tuple[Mapping[str, Any], ...]
    limitations: tuple[ClaimLimitationCandidate, ...]
    keywords: tuple[KeywordCandidate, ...]
    queries: tuple[SearchQuerySpec, ...]
    intended_corpora: tuple[SearchCorpus, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    output_kind: str = OUTPUT_KIND_PRIOR_ART_PLAN
    disclaimer: str = PRIOR_ART_DISCLAIMER
    ruleset_version: str = PRIOR_ART_RULESET_VERSION
    rank_cutoff: int = DEFAULT_RANK_CUTOFF
    filters: PreRankingFilters | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, PRIOR_ART_SCHEMA_VERSION, "PriorArtSearchPlan"
            ),
        )
        object.__setattr__(self, "plan_id", _identifier(self.plan_id, "plan_id"))
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
        claims = self.claims or ()
        if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
            raise TypeError("claims must be a sequence of mappings")
        if not claims:
            raise ValueError("claims must be non-empty")
        normalized_claims: list[Mapping[str, Any]] = []
        for i, claim in enumerate(claims):
            if not isinstance(claim, Mapping):
                raise TypeError(f"claims[{i}] must be a mapping")
            claim_number = _positive_int(claim.get("claim_number"), f"claims[{i}].claim_number")
            claim_text = _require_str(
                claim.get("claim_text"), f"claims[{i}].claim_text", max_len=200_000
            )
            normalized_claims.append(
                MappingProxyType(
                    {
                        "claim_number": claim_number,
                        "claim_text": claim_text,
                        **(
                            {
                                "claim_kind": _require_str(
                                    claim["claim_kind"], "claim_kind", max_len=64
                                )
                            }
                            if claim.get("claim_kind")
                            else {}
                        ),
                    }
                )
            )
        object.__setattr__(self, "claims", tuple(normalized_claims))
        limitations = _coerce_limitations(self.limitations, "limitations")
        if not all(lim.is_candidate for lim in limitations):
            raise ValueError("all limitations must be candidates")
        object.__setattr__(self, "limitations", limitations)
        keywords = _coerce_keywords(self.keywords, "keywords")
        if not all(kw.is_candidate for kw in keywords):
            raise ValueError("all keywords must be candidates")
        object.__setattr__(self, "keywords", keywords)
        object.__setattr__(self, "queries", _coerce_queries(self.queries, "queries"))
        corpora = self.intended_corpora or ()
        if not isinstance(corpora, Sequence) or isinstance(corpora, (str, bytes)):
            raise TypeError("intended_corpora must be a sequence")
        coerced_corpora = tuple(
            _coerce_enum(SearchCorpus, c, f"intended_corpora[{i}]")
            for i, c in enumerate(corpora)
        )
        if not coerced_corpora:
            raise ValueError("intended_corpora must be non-empty")
        object.__setattr__(self, "intended_corpora", coerced_corpora)
        gaps = _coerce_gaps(self.coverage_gaps, "coverage_gaps")
        object.__setattr__(self, "coverage_gaps", gaps)
        _assert_required_coverage_gaps_visible(gaps, label="PriorArtSearchPlan")
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_PRIOR_ART_PLAN:
            raise ValueError(
                f"PriorArtSearchPlan.output_kind must be {OUTPUT_KIND_PRIOR_ART_PLAN!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        if "patentability" not in self.disclaimer.lower():
            raise ValueError("disclaimer must state that patentability is not determined")
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        object.__setattr__(
            self, "rank_cutoff", _positive_int(self.rank_cutoff, "rank_cutoff")
        )
        if self.filters is not None and not isinstance(self.filters, PreRankingFilters):
            if isinstance(self.filters, Mapping):
                object.__setattr__(
                    self, "filters", PreRankingFilters.from_dict(self.filters)
                )
            else:
                raise TypeError("filters must be PreRankingFilters, mapping, or None")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "PriorArtSearchPlan")
        assert_no_patentability_conclusions(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [dict(c) for c in self.claims],
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "disclaimer": self.disclaimer,
            "filing_date": self.filing_date,
            "filters": None if self.filters is None else self.filters.to_dict(),
            "intended_corpora": [c.value for c in self.intended_corpora],
            "keywords": [k.to_dict() for k in self.keywords],
            "limitations": [lim.to_dict() for lim in self.limitations],
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "plan_id": self.plan_id,
            "priority_date": self.priority_date,
            "queries": [q.to_dict() for q in self.queries],
            "rank_cutoff": self.rank_cutoff,
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "search_date_utc": self.search_date_utc,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PriorArtSearchPlan":
        value = _mapping(value, "PriorArtSearchPlan")
        _reject_unknown(
            value,
            frozenset(
                {
                    "claims",
                    "coverage_gaps",
                    "disclaimer",
                    "filing_date",
                    "filters",
                    "intended_corpora",
                    "keywords",
                    "limitations",
                    "metadata",
                    "output_kind",
                    "plan_id",
                    "priority_date",
                    "queries",
                    "rank_cutoff",
                    "ruleset_version",
                    "schema_version",
                    "search_date_utc",
                    "subject_id",
                }
            ),
            "PriorArtSearchPlan",
        )
        filters_raw = value.get("filters")
        filters = (
            None
            if filters_raw is None
            else (
                filters_raw
                if isinstance(filters_raw, PreRankingFilters)
                else PreRankingFilters.from_dict(filters_raw)
            )
        )
        return cls(
            schema_version=value.get("schema_version", PRIOR_ART_SCHEMA_VERSION),
            plan_id=value.get("plan_id", ""),
            subject_id=value.get("subject_id", ""),
            filing_date=value.get("filing_date", ""),
            priority_date=value.get("priority_date", ""),
            search_date_utc=value.get("search_date_utc", ""),
            claims=tuple(value.get("claims") or ()),
            limitations=tuple(value.get("limitations") or ()),
            keywords=tuple(value.get("keywords") or ()),
            queries=tuple(value.get("queries") or ()),
            intended_corpora=tuple(value.get("intended_corpora") or ()),
            coverage_gaps=tuple(value.get("coverage_gaps") or ()),
            output_kind=value.get("output_kind", OUTPUT_KIND_PRIOR_ART_PLAN),
            disclaimer=value.get("disclaimer", PRIOR_ART_DISCLAIMER),
            ruleset_version=value.get("ruleset_version", PRIOR_ART_RULESET_VERSION),
            rank_cutoff=int(value.get("rank_cutoff") or DEFAULT_RANK_CUTOFF),
            filters=filters,
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PriorArtReport:
    """Combined plan + dated query logs + claim chart for human review."""

    schema_version: str
    report_id: str
    plan: PriorArtSearchPlan
    query_logs: tuple[DatedQueryLog, ...]
    chart: ClaimChart
    coverage_gaps: tuple[CoverageGap, ...]
    output_kind: str = OUTPUT_KIND_PRIOR_ART_REPORT
    disclaimer: str = PRIOR_ART_DISCLAIMER
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, PRIOR_ART_SCHEMA_VERSION, "PriorArtReport"
            ),
        )
        object.__setattr__(
            self, "report_id", _identifier(self.report_id, "report_id")
        )
        if not isinstance(self.plan, PriorArtSearchPlan):
            if isinstance(self.plan, Mapping):
                object.__setattr__(
                    self, "plan", PriorArtSearchPlan.from_dict(self.plan)
                )
            else:
                raise TypeError("plan must be PriorArtSearchPlan or mapping")
        object.__setattr__(
            self, "query_logs", _coerce_query_logs(self.query_logs, "query_logs")
        )
        if not isinstance(self.chart, ClaimChart):
            if isinstance(self.chart, Mapping):
                object.__setattr__(self, "chart", ClaimChart.from_dict(self.chart))
            else:
                raise TypeError("chart must be ClaimChart or mapping")
        gaps = _coerce_gaps(self.coverage_gaps, "coverage_gaps")
        object.__setattr__(self, "coverage_gaps", gaps)
        _assert_required_coverage_gaps_visible(gaps, label="PriorArtReport")
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_PRIOR_ART_REPORT:
            raise ValueError(
                f"PriorArtReport.output_kind must be {OUTPUT_KIND_PRIOR_ART_REPORT!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "PriorArtReport")
        # Temporal anchors must agree across plan and chart.
        if self.plan.filing_date != self.chart.filing_date:
            raise MissingTemporalAnchorError(
                "plan.filing_date and chart.filing_date must match"
            )
        if self.plan.priority_date != self.chart.priority_date:
            raise MissingTemporalAnchorError(
                "plan.priority_date and chart.priority_date must match"
            )
        if self.plan.search_date_utc != self.chart.search_date_utc:
            raise MissingTemporalAnchorError(
                "plan.search_date_utc and chart.search_date_utc must match"
            )
        assert_no_patentability_conclusions(self.to_dict())

    @property
    def filing_date(self) -> str:
        return self.plan.filing_date

    @property
    def priority_date(self) -> str:
        return self.plan.priority_date

    @property
    def search_date_utc(self) -> str:
        return self.plan.search_date_utc

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart": self.chart.to_dict(),
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "disclaimer": self.disclaimer,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "plan": self.plan.to_dict(),
            "query_logs": [log.to_dict() for log in self.query_logs],
            "report_id": self.report_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PriorArtReport":
        value = _mapping(value, "PriorArtReport")
        _reject_unknown(
            value,
            frozenset(
                {
                    "chart",
                    "coverage_gaps",
                    "disclaimer",
                    "metadata",
                    "output_kind",
                    "plan",
                    "query_logs",
                    "report_id",
                    "schema_version",
                }
            ),
            "PriorArtReport",
        )
        return cls(
            schema_version=value.get("schema_version", PRIOR_ART_SCHEMA_VERSION),
            report_id=value.get("report_id", ""),
            plan=value.get("plan") or {},
            query_logs=tuple(value.get("query_logs") or ()),
            chart=value.get("chart") or {},
            coverage_gaps=tuple(value.get("coverage_gaps") or ()),
            output_kind=value.get("output_kind", OUTPUT_KIND_PRIOR_ART_REPORT),
            disclaimer=value.get("disclaimer", PRIOR_ART_DISCLAIMER),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Coercion helpers for nested sequences
# ---------------------------------------------------------------------------


def _coerce_limitations(
    value: Any, field: str
) -> tuple[ClaimLimitationCandidate, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > DEFAULT_MAX_LIMITATIONS:
        raise ValueError(f"{field} exceeds max items {DEFAULT_MAX_LIMITATIONS}")
    out: list[ClaimLimitationCandidate] = []
    for i, item in enumerate(value):
        if isinstance(item, ClaimLimitationCandidate):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ClaimLimitationCandidate.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be ClaimLimitationCandidate or mapping")
    return tuple(out)


def _coerce_keywords(value: Any, field: str) -> tuple[KeywordCandidate, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > DEFAULT_MAX_KEYWORDS:
        raise ValueError(f"{field} exceeds max items {DEFAULT_MAX_KEYWORDS}")
    out: list[KeywordCandidate] = []
    for i, item in enumerate(value):
        if isinstance(item, KeywordCandidate):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(KeywordCandidate.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be KeywordCandidate or mapping")
    return tuple(out)


def _coerce_queries(value: Any, field: str) -> tuple[SearchQuerySpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > DEFAULT_MAX_QUERIES:
        raise ValueError(f"{field} exceeds max items {DEFAULT_MAX_QUERIES}")
    out: list[SearchQuerySpec] = []
    for i, item in enumerate(value):
        if isinstance(item, SearchQuerySpec):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(SearchQuerySpec.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be SearchQuerySpec or mapping")
    return tuple(out)


def _coerce_gaps(value: Any, field: str) -> tuple[CoverageGap, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > DEFAULT_MAX_GAPS:
        raise ValueError(f"{field} exceeds max items {DEFAULT_MAX_GAPS}")
    out: list[CoverageGap] = []
    for i, item in enumerate(value):
        if isinstance(item, CoverageGap):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(CoverageGap.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be CoverageGap or mapping")
    return tuple(out)


def _coerce_entries(value: Any, field: str) -> tuple[ClaimChartEntry, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > DEFAULT_MAX_CHART_ENTRIES:
        raise ValueError(f"{field} exceeds max items {DEFAULT_MAX_CHART_ENTRIES}")
    out: list[ClaimChartEntry] = []
    for i, item in enumerate(value):
        if isinstance(item, ClaimChartEntry):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ClaimChartEntry.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be ClaimChartEntry or mapping")
    return tuple(out)


def _coerce_query_logs(value: Any, field: str) -> tuple[DatedQueryLog, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > DEFAULT_MAX_QUERY_LOGS:
        raise ValueError(f"{field} exceeds max items {DEFAULT_MAX_QUERY_LOGS}")
    out: list[DatedQueryLog] = []
    for i, item in enumerate(value):
        if isinstance(item, DatedQueryLog):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(DatedQueryLog.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be DatedQueryLog or mapping")
    return tuple(out)


def _assert_required_coverage_gaps_visible(
    gaps: Sequence[CoverageGap], *, label: str
) -> None:
    """Foreign-patent and NPL gaps must remain visible on every plan/chart/report."""
    kinds = {g.kind for g in gaps if g.remains_visible}
    missing: list[str] = []
    if CoverageGapKind.FOREIGN_PATENT not in kinds:
        missing.append(CoverageGapKind.FOREIGN_PATENT.value)
    if CoverageGapKind.NPL not in kinds:
        missing.append(CoverageGapKind.NPL.value)
    if missing:
        raise CoverageGapVisibilityError(
            f"{label} must keep foreign-patent and NPL coverage gaps visible; "
            f"missing: {', '.join(missing)}"
        )
    for gap in gaps:
        if gap.kind in (CoverageGapKind.FOREIGN_PATENT, CoverageGapKind.NPL):
            if not gap.remains_visible:
                raise CoverageGapVisibilityError(
                    f"{label} gap {gap.gap_id} ({gap.kind.value}) must remain visible"
                )


# ---------------------------------------------------------------------------
# Default gap constructors
# ---------------------------------------------------------------------------


def default_foreign_patent_gap(*, searched: bool = False) -> CoverageGap:
    return CoverageGap(
        gap_id="gap:foreign-patent",
        kind=CoverageGapKind.FOREIGN_PATENT,
        description=(
            "Foreign-patent corpus was not searched (or only partially covered). "
            "This gap remains visible and must not be treated as a complete search."
        ),
        corpus=SearchCorpus.FOREIGN_PATENTS,
        remains_visible=True,
        searched=searched,
    )


def default_npl_gap(*, searched: bool = False) -> CoverageGap:
    return CoverageGap(
        gap_id="gap:npl",
        kind=CoverageGapKind.NPL,
        description=(
            "Non-patent literature (NPL) corpus was not searched (or only partially "
            "covered). Unlicensed NPL body text is not reproduced. This gap remains "
            "visible and must not be treated as a complete search."
        ),
        corpus=SearchCorpus.NPL,
        remains_visible=True,
        searched=searched,
    )


def default_coverage_gaps(
    *,
    searched_corpora: Sequence[SearchCorpus | str] = (),
) -> tuple[CoverageGap, ...]:
    """Build the mandatory foreign-patent + NPL gap pair (plus unsearched extras)."""
    searched = {
        _coerce_enum(SearchCorpus, c, "searched_corpora") for c in searched_corpora
    }
    gaps = [
        default_foreign_patent_gap(
            searched=SearchCorpus.FOREIGN_PATENTS in searched
        ),
        default_npl_gap(searched=SearchCorpus.NPL in searched),
    ]
    # If foreign/NPL were marked searched but are still only partial by policy,
    # keep them visible (already remains_visible=True).
    return tuple(gaps)


# ---------------------------------------------------------------------------
# Decomposition / keyword / plan builders
# ---------------------------------------------------------------------------


def decompose_claim_limitations(
    claim_text: str,
    *,
    claim_number: int = 1,
    claim_source_span: SourceSpan | None = None,
    max_limitations: int = DEFAULT_MAX_LIMITATIONS,
) -> tuple[ClaimLimitationCandidate, ...]:
    """Deterministically decompose claim text into *candidate* limitations.

    Splits on common claim-language delimiters (comprising / wherein / ;).
    All outputs are candidates: they never claim source authority and never
    assert patentability.
    """
    text = _require_str(claim_text, "claim_text", max_len=200_000)
    claim_number = _positive_int(claim_number, "claim_number")
    # Strip leading claim number prefix if present.
    cleaned = re.sub(r"^\s*\d+\.\s*", "", text).strip()
    parts = [p.strip(" .") for p in _LIMITATION_SPLIT_RE.split(cleaned) if p and p.strip()]
    if not parts:
        parts = [cleaned]
    # Re-attach leading "A method" style preamble as first limitation if split
    # dropped empty segments; ensure uniqueness and non-empty.
    limitations: list[ClaimLimitationCandidate] = []
    offset = 0
    for ordinal, part in enumerate(parts, start=1):
        if ordinal > max_limitations:
            break
        if not part:
            continue
        # Best-effort span within original claim_text.
        idx = text.find(part, offset)
        if idx < 0:
            idx = offset
        span = SourceSpan(start=idx, end=idx + len(part), unit="char")
        if claim_source_span is not None:
            # Offset relative span into absolute claim span when provided.
            span = SourceSpan(
                start=claim_source_span.start + span.start,
                end=claim_source_span.start + span.end,
                unit=claim_source_span.unit,
            )
        offset = idx + len(part)
        limitations.append(
            ClaimLimitationCandidate(
                limitation_id=f"lim:c{claim_number}-{ordinal}",
                claim_number=claim_number,
                text=part,
                is_candidate=True,
                role=MaterialRole.CANDIDATE,
                authority_claim=AuthorityClaim.NONE,
                provenance=EdgeProvenance.CANDIDATE,
                ordinal=ordinal,
                source_claim_span=span,
                metadata={"generator": "deterministic_split"},
            )
        )
    if not limitations:
        limitations.append(
            ClaimLimitationCandidate(
                limitation_id=f"lim:c{claim_number}-1",
                claim_number=claim_number,
                text=cleaned or text,
                is_candidate=True,
                ordinal=1,
                source_claim_span=claim_source_span,
                metadata={"generator": "passthrough"},
            )
        )
    return tuple(limitations)


def extract_keyword_candidates(
    texts: Sequence[str],
    *,
    classifications: Sequence[str] = (),
    related_limitation_ids: Sequence[str] = (),
    max_keywords: int = DEFAULT_MAX_KEYWORDS,
) -> tuple[KeywordCandidate, ...]:
    """Extract keyword and classification *candidates* for query construction."""
    tokens: list[str] = []
    for raw in texts:
        if not raw:
            continue
        for match in _TOKEN_RE.findall(str(raw)):
            token = match.lower()
            if token in _STOPWORDS:
                continue
            if len(token) < 3:
                continue
            tokens.append(token)
        for match in _CPC_IPC_RE.findall(str(raw)):
            tokens.append(re.sub(r"\s+", "", match).upper())

    for code in classifications:
        code_s = str(code).strip()
        if code_s:
            tokens.append(re.sub(r"\s+", "", code_s).upper())

    # Deterministic unique preserve order.
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
        if len(ordered) >= max_keywords:
            break

    related = tuple(related_limitation_ids)
    keywords: list[KeywordCandidate] = []
    for i, token in enumerate(ordered, start=1):
        kind = "classification" if _CPC_IPC_RE.search(token) or "/" in token else "keyword"
        keywords.append(
            KeywordCandidate(
                keyword_id=f"kw:{i}",
                text=token,
                is_candidate=True,
                role=MaterialRole.CANDIDATE,
                authority_claim=AuthorityClaim.NONE,
                provenance=EdgeProvenance.CANDIDATE,
                kind=kind,
                related_limitation_ids=related,
                metadata={"generator": "token_extract"},
            )
        )
    return tuple(keywords)


def build_search_queries(
    *,
    limitations: Sequence[ClaimLimitationCandidate],
    keywords: Sequence[KeywordCandidate],
    classifications: Sequence[str] = (),
    rank_cutoff: int = DEFAULT_RANK_CUTOFF,
    intended_corpora: Sequence[SearchCorpus | str] = (
        SearchCorpus.US_PATENTS,
        SearchCorpus.US_PUBLICATIONS,
    ),
) -> tuple[SearchQuerySpec, ...]:
    """Construct keyword and classification query specs from candidates."""
    corpora = tuple(
        _coerce_enum(SearchCorpus, c, "intended_corpora") for c in intended_corpora
    )
    if not corpora:
        corpora = (SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS)
    # U.S.-only default: never silently include foreign/NPL as searched.
    us_only = tuple(
        c
        for c in corpora
        if c in (SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS)
    )
    if not us_only:
        us_only = (SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS)

    queries: list[SearchQuerySpec] = []
    qn = 0

    # Limitation-level queries (candidate text).
    for lim in limitations:
        qn += 1
        queries.append(
            SearchQuerySpec(
                query_id=f"q-lim-{qn}",
                query_text=lim.text,
                family=QueryFamily.CLAIM_LIMITATION,
                intended_corpora=us_only,
                rank_cutoff=rank_cutoff,
                related_limitation_ids=(lim.limitation_id,),
                metadata={"source": "limitation_candidate"},
            )
        )

    # Keyword queries (batch top keywords into a few combined queries).
    kw_terms = [k.text for k in keywords if k.kind == "keyword"]
    if kw_terms:
        qn += 1
        # Combined keyword query for efficiency; still candidate-derived.
        combined = " ".join(kw_terms[:12])
        queries.append(
            SearchQuerySpec(
                query_id=f"q-kw-{qn}",
                query_text=combined,
                family=QueryFamily.KEYWORD,
                intended_corpora=us_only,
                rank_cutoff=rank_cutoff,
                related_keyword_ids=tuple(k.keyword_id for k in keywords if k.kind == "keyword")[
                    :12
                ],
                related_limitation_ids=tuple(
                    sorted(
                        {
                            rid
                            for k in keywords
                            for rid in k.related_limitation_ids
                        }
                    )
                ),
                metadata={"source": "keyword_candidates"},
            )
        )

    # Classification queries.
    class_codes = [
        re.sub(r"\s+", "", str(c)).upper()
        for c in classifications
        if str(c).strip()
    ]
    class_codes.extend(
        k.text for k in keywords if k.kind == "classification"
    )
    # Dedupe preserve order.
    seen_codes: set[str] = set()
    unique_codes: list[str] = []
    for code in class_codes:
        if code in seen_codes:
            continue
        seen_codes.add(code)
        unique_codes.append(code)
    for code in unique_codes:
        qn += 1
        family = (
            QueryFamily.CLASSIFICATION_IPC
            if code[:1].upper() in "ABCDEFGHY" and code[1:3].isdigit()
            else QueryFamily.CLASSIFICATION_CPC
        )
        # Prefer CPC family for G/H codes used in U.S. practice; keep IPC when marked.
        if code[0].upper() in "ABCDEFGHY":
            family = QueryFamily.CLASSIFICATION_CPC
        queries.append(
            SearchQuerySpec(
                query_id=f"q-class-{qn}",
                query_text=code,
                family=family,
                intended_corpora=us_only,
                rank_cutoff=rank_cutoff,
                classification_codes=(code,),
                metadata={"source": "classification_candidate"},
            )
        )

    return tuple(queries[:DEFAULT_MAX_QUERIES])


def build_prior_art_search_plan(
    *,
    subject_id: str,
    filing_date: str,
    priority_date: str,
    search_date_utc: str,
    claims: Sequence[Mapping[str, Any]],
    classifications: Sequence[str] = (),
    plan_id: str | None = None,
    rank_cutoff: int = DEFAULT_RANK_CUTOFF,
    intended_corpora: Sequence[SearchCorpus | str] = (
        SearchCorpus.US_PATENTS,
        SearchCorpus.US_PUBLICATIONS,
    ),
    filters: PreRankingFilters | None = None,
    citation_seed_document_ids: Sequence[str] = (),
    family_seed_document_ids: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
) -> PriorArtSearchPlan:
    """Build a reproducible prior-art search plan from claim text.

    Filing, priority, and search dates are mandatory. Limitations and keywords
    are always candidates. Foreign-patent and NPL gaps are always recorded as
    visible.
    """
    if not filing_date or not priority_date or not search_date_utc:
        raise MissingTemporalAnchorError(
            "filing_date, priority_date, and search_date_utc are required"
        )

    claim_list = list(claims)
    if not claim_list:
        raise PriorArtError("at least one claim is required")

    all_limitations: list[ClaimLimitationCandidate] = []
    all_texts: list[str] = []
    for claim in claim_list:
        if not isinstance(claim, Mapping):
            raise TypeError("each claim must be a mapping with claim_number and claim_text")
        cnum = int(claim["claim_number"])
        ctext = str(claim["claim_text"])
        all_texts.append(ctext)
        all_limitations.extend(
            decompose_claim_limitations(ctext, claim_number=cnum)
        )

    keywords = extract_keyword_candidates(
        all_texts,
        classifications=classifications,
        related_limitation_ids=tuple(lim.limitation_id for lim in all_limitations),
    )
    queries = list(
        build_search_queries(
            limitations=all_limitations,
            keywords=keywords,
            classifications=classifications,
            rank_cutoff=rank_cutoff,
            intended_corpora=intended_corpora,
        )
    )

    # Citation / family expansion query stubs (U.S. corpus only).
    us_corpora = (
        SearchCorpus.US_PATENTS,
        SearchCorpus.US_PUBLICATIONS,
    )
    if citation_seed_document_ids:
        queries.append(
            SearchQuerySpec(
                query_id="q-cite-expand",
                query_text=" ".join(str(d) for d in citation_seed_document_ids),
                family=QueryFamily.CITATION_EXPANSION,
                intended_corpora=us_corpora,
                rank_cutoff=rank_cutoff,
                seed_document_ids=tuple(str(d) for d in citation_seed_document_ids),
                metadata={"source": "citation_expansion"},
            )
        )
    if family_seed_document_ids:
        queries.append(
            SearchQuerySpec(
                query_id="q-family-expand",
                query_text=" ".join(str(d) for d in family_seed_document_ids),
                family=QueryFamily.FAMILY_EXPANSION,
                intended_corpora=us_corpora,
                rank_cutoff=rank_cutoff,
                seed_document_ids=tuple(str(d) for d in family_seed_document_ids),
                metadata={"source": "family_expansion"},
            )
        )

    corpora = tuple(
        _coerce_enum(SearchCorpus, c, "intended_corpora") for c in intended_corpora
    )
    gaps = default_coverage_gaps(searched_corpora=corpora)

    # Identity of plan from stable coordinates (not wall clock beyond search_date).
    identity = {
        "claims": [
            {
                "claim_number": int(c["claim_number"]),
                "claim_text": str(c["claim_text"]),
            }
            for c in claim_list
        ],
        "filing_date": filing_date,
        "priority_date": priority_date,
        "search_date_utc": search_date_utc,
        "subject_id": subject_id,
    }
    digest = content_digest(identity)[:16]
    resolved_plan_id = plan_id or f"plan:prior-art:{digest}"

    return PriorArtSearchPlan(
        schema_version=PRIOR_ART_SCHEMA_VERSION,
        plan_id=resolved_plan_id,
        subject_id=subject_id,
        filing_date=filing_date,
        priority_date=priority_date,
        search_date_utc=search_date_utc,
        claims=tuple(claim_list),
        limitations=tuple(all_limitations),
        keywords=keywords,
        queries=tuple(queries),
        intended_corpora=corpora or us_corpora,
        coverage_gaps=gaps,
        rank_cutoff=rank_cutoff,
        filters=filters,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Execution: dated logs + claim chart from hybrid retrieval
# ---------------------------------------------------------------------------


def _hit_to_ranked_passage(
    hit: RankedHit,
    *,
    passage_excerpt: str | None = None,
) -> RankedPassageHit:
    links = hit.source_links
    # Ensure spans exist; if a link lacks span, synthesize a zero-width span at 0
    # only when source already has span from index — otherwise fail closed.
    _require_source_cid_and_span(links, label=f"retrieval hit {hit.document_id}")
    return RankedPassageHit(
        document_id=hit.document_id,
        rank=hit.rank,
        score=hit.score,
        source_links=links,
        passage_excerpt=passage_excerpt,
        family=hit.family.value if hasattr(hit.family, "value") else str(hit.family),
        metadata=dict(hit.metadata),
    )


def record_dated_query_log(
    query: SearchQuerySpec,
    hits: Sequence[RankedHit | RankedPassageHit | Mapping[str, Any]],
    *,
    search_date_utc: str,
    corpus: SearchCorpus | str = SearchCorpus.US_PATENTS,
    filters: PreRankingFilters | None = None,
    log_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> DatedQueryLog:
    """Record an exact dated query log with ranks, cutoff, and source-linked hits."""
    corpus_e = _coerce_enum(SearchCorpus, corpus, "corpus")
    parsed_hits: list[RankedPassageHit] = []
    for item in hits:
        if isinstance(item, RankedPassageHit):
            if item.rank <= query.rank_cutoff:
                parsed_hits.append(item)
        elif isinstance(item, RankedHit):
            if item.rank <= query.rank_cutoff:
                parsed_hits.append(_hit_to_ranked_passage(item))
        elif isinstance(item, Mapping):
            rp = RankedPassageHit.from_dict(item)
            if rp.rank <= query.rank_cutoff:
                parsed_hits.append(rp)
        else:
            raise TypeError("hits items must be RankedHit, RankedPassageHit, or mapping")
    # Sort by rank for determinism.
    parsed_hits.sort(key=lambda h: (h.rank, h.document_id))
    return DatedQueryLog(
        log_id=log_id or f"log:{query.query_id}",
        query_id=query.query_id,
        query_text=query.query_text,
        search_date_utc=search_date_utc,
        family=query.family,
        corpus=corpus_e,
        rank_cutoff=query.rank_cutoff,
        hits=tuple(parsed_hits),
        filters=filters,
        related_limitation_ids=query.related_limitation_ids,
        metadata=metadata or {},
    )


def build_claim_chart_entries_from_logs(
    *,
    query_logs: Sequence[DatedQueryLog],
    limitations: Sequence[ClaimLimitationCandidate],
    max_entries: int = DEFAULT_MAX_CHART_ENTRIES,
) -> tuple[ClaimChartEntry, ...]:
    """Project dated query logs into source-linked claim-chart entries."""
    lim_by_id = {lim.limitation_id: lim for lim in limitations}
    # Fallback: if a log has no related limitations, map to all limitations.
    entries: list[ClaimChartEntry] = []
    seen: set[tuple[str, str, str]] = set()  # limitation, document, query
    for log in query_logs:
        related = log.related_limitation_ids or tuple(lim_by_id.keys())
        if not related and limitations:
            related = (limitations[0].limitation_id,)
        for hit in log.hits:
            for lim_id in related:
                lim = lim_by_id.get(lim_id)
                claim_number = lim.claim_number if lim is not None else 1
                key = (lim_id, hit.document_id, log.query_id)
                if key in seen:
                    continue
                seen.add(key)
                entry_id = f"entry:{lim_id}:{hit.document_id}:{log.query_id}"
                # Compact entry id if too long.
                if len(entry_id) > 200:
                    entry_id = f"entry:{content_digest(list(key))[:24]}"
                entries.append(
                    ClaimChartEntry(
                        entry_id=entry_id,
                        claim_number=claim_number,
                        limitation_id=lim_id,
                        document_id=hit.document_id,
                        rank=hit.rank,
                        score=hit.score,
                        source_links=hit.source_links,
                        query_id=log.query_id,
                        log_id=log.log_id,
                        passage_excerpt=hit.passage_excerpt,
                        role=MaterialRole.SOURCE_BOUND,
                        authority_claim=AuthorityClaim.SOURCE_BOUND,
                    )
                )
                if len(entries) >= max_entries:
                    return tuple(entries)
    return tuple(entries)


def build_claim_chart(
    *,
    subject_id: str,
    filing_date: str,
    priority_date: str,
    search_date_utc: str,
    entries: Sequence[ClaimChartEntry | Mapping[str, Any]],
    limitations: Sequence[ClaimLimitationCandidate | Mapping[str, Any]] = (),
    coverage_gaps: Sequence[CoverageGap | Mapping[str, Any]] | None = None,
    plan_id: str | None = None,
    chart_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> ClaimChart:
    """Construct a claim chart; every entry must cite source CID/span."""
    gaps: tuple[CoverageGap, ...]
    if coverage_gaps is None:
        gaps = default_coverage_gaps()
    else:
        gaps = _coerce_gaps(coverage_gaps, "coverage_gaps")

    parsed_entries = _coerce_entries(entries, "entries")
    for entry in parsed_entries:
        _require_source_cid_and_span(
            entry.source_links, label=f"chart entry {entry.entry_id}"
        )

    identity = {
        "entries": [e.to_dict() for e in parsed_entries],
        "filing_date": filing_date,
        "priority_date": priority_date,
        "search_date_utc": search_date_utc,
        "subject_id": subject_id,
    }
    digest = content_digest(identity)[:16]
    return ClaimChart(
        schema_version=PRIOR_ART_SCHEMA_VERSION,
        chart_id=chart_id or f"chart:prior-art:{digest}",
        subject_id=subject_id,
        filing_date=filing_date,
        priority_date=priority_date,
        search_date_utc=search_date_utc,
        entries=parsed_entries,
        limitations=_coerce_limitations(limitations, "limitations"),
        coverage_gaps=gaps,
        plan_id=plan_id,
        metadata=metadata or {},
    )


def execute_prior_art_plan(
    plan: PriorArtSearchPlan,
    *,
    retriever: PatentHybridRetriever | None = None,
    search_fn: Callable[[SearchQuerySpec, PreRankingFilters], HybridSearchResult]
    | None = None,
    filters: PreRankingFilters | None = None,
    report_id: str | None = None,
    corpora_for_logs: Sequence[SearchCorpus | str] = (SearchCorpus.US_PATENTS,),
) -> PriorArtReport:
    """Execute a plan against hybrid retrieval and produce a PriorArtReport.

    Either *retriever* or *search_fn* must be provided. Filters from the plan
    (or argument) are applied before search. Foreign-patent and NPL gaps from
    the plan remain visible on the report.
    """
    if retriever is None and search_fn is None:
        raise PriorArtError("execute_prior_art_plan requires retriever or search_fn")

    base_filters = filters or plan.filters
    if base_filters is None:
        raise PriorArtError(
            "PreRankingFilters are required (plan.filters or filters argument)"
        )
    applied = (
        base_filters
        if base_filters.applied
        else apply_pre_ranking_filters(base_filters)
    )

    logs: list[DatedQueryLog] = []
    log_corpora = [
        _coerce_enum(SearchCorpus, c, "corpora_for_logs") for c in corpora_for_logs
    ] or [SearchCorpus.US_PATENTS]

    for query in plan.queries:
        if search_fn is not None:
            result = search_fn(query, applied)
        else:
            assert retriever is not None
            request = HybridSearchRequest(
                query_id=query.query_id,
                query=query.query_text,
                filters=applied,
                top_k=query.rank_cutoff,
                seed_document_ids=query.seed_document_ids,
                query_disclosure=DisclosureClass.PUBLIC_USER,
            )
            result = retriever.search(request)

        hits = result.fused_hits if isinstance(result, HybridSearchResult) else ()
        # One log per intended U.S. corpus for reproducibility of corpus label.
        primary_corpus = log_corpora[0]
        # Prefer US patents if query intended that corpus.
        for intended in query.intended_corpora:
            if intended in log_corpora:
                primary_corpus = intended  # type: ignore[assignment]
                break
            if intended in (SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS):
                primary_corpus = intended  # type: ignore[assignment]
                break

        logs.append(
            record_dated_query_log(
                query,
                hits,
                search_date_utc=plan.search_date_utc,
                corpus=primary_corpus,
                filters=applied,
                log_id=f"log:{plan.plan_id}:{query.query_id}",
            )
        )

    entries = build_claim_chart_entries_from_logs(
        query_logs=logs,
        limitations=plan.limitations,
    )
    chart = build_claim_chart(
        subject_id=plan.subject_id,
        filing_date=plan.filing_date,
        priority_date=plan.priority_date,
        search_date_utc=plan.search_date_utc,
        entries=entries,
        limitations=plan.limitations,
        coverage_gaps=plan.coverage_gaps,
        plan_id=plan.plan_id,
    )

    # Merge plan gaps (always retain foreign + NPL visibility).
    gaps = plan.coverage_gaps
    report = PriorArtReport(
        schema_version=PRIOR_ART_SCHEMA_VERSION,
        report_id=report_id or f"report:{plan.plan_id}",
        plan=plan,
        query_logs=tuple(logs),
        chart=chart,
        coverage_gaps=gaps,
    )
    return report


def assert_chart_entries_cite_sources(chart: ClaimChart | Mapping[str, Any]) -> None:
    """Raise if any chart entry lacks source CID + span."""
    if isinstance(chart, Mapping):
        chart = ClaimChart.from_dict(chart)
    for entry in chart.entries:
        _require_source_cid_and_span(
            entry.source_links, label=f"chart entry {entry.entry_id}"
        )


# ---------------------------------------------------------------------------
# Golden fixture helpers
# ---------------------------------------------------------------------------


def default_golden_claim_chart_path() -> Path:
    """Return the repository path of the golden claim-chart fixture."""
    # Walk up from this file to the repository root (…/ipfs_datasets_py/… → root).
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / _GOLDEN_RELATIVE
        if candidate.is_file():
            return candidate
    # Fallback: relative to CWD (tests often run from repo root).
    return Path(_GOLDEN_RELATIVE)


def load_golden_claim_chart(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the golden claim-chart fixture as a dict (envelope)."""
    target = Path(path) if path is not None else default_golden_claim_chart_path()
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise PriorArtError("golden claim chart must be a JSON object")
    return dict(payload)


def parse_golden_claim_chart(
    path: str | Path | Mapping[str, Any] | None = None,
) -> tuple[PriorArtSearchPlan, ClaimChart, PriorArtReport | None]:
    """Parse golden fixture into plan, chart, and optional report."""
    if isinstance(path, Mapping):
        payload = dict(path)
    else:
        payload = load_golden_claim_chart(path)

    plan = PriorArtSearchPlan.from_dict(payload["plan"])
    chart = ClaimChart.from_dict(payload["chart"])
    report = None
    if payload.get("report") is not None:
        report = PriorArtReport.from_dict(payload["report"])
    return plan, chart, report


def build_golden_claim_chart_envelope(
    *,
    plan: PriorArtSearchPlan,
    chart: ClaimChart,
    report: PriorArtReport | None = None,
) -> dict[str, Any]:
    """Serialize a deterministic golden envelope (plan + chart [+ report])."""
    envelope: dict[str, Any] = {
        "schema_version": PRIOR_ART_SCHEMA_VERSION,
        "fixture_id": "golden-prior-art-claim-chart",
        "disclaimer": PRIOR_ART_DISCLAIMER,
        "plan": plan.to_dict(),
        "chart": chart.to_dict(),
    }
    if report is not None:
        envelope["report"] = report.to_dict()
    assert_no_patentability_conclusions(envelope)
    return envelope


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


__all__ = [
    "PRIOR_ART_DISCLAIMER",
    "PRIOR_ART_INTERFACE",
    "PRIOR_ART_RULESET_VERSION",
    "PRIOR_ART_SCHEMA_VERSION",
    "OUTPUT_KIND_CLAIM_CHART",
    "OUTPUT_KIND_PRIOR_ART_PLAN",
    "OUTPUT_KIND_PRIOR_ART_REPORT",
    "AuthorityClaim",
    "ChartSourceCitationError",
    "ClaimChart",
    "ClaimChartEntry",
    "ClaimLimitationCandidate",
    "CoverageGap",
    "CoverageGapKind",
    "CoverageGapVisibilityError",
    "DatedQueryLog",
    "KeywordCandidate",
    "MaterialRole",
    "MissingTemporalAnchorError",
    "PatentabilityConclusionError",
    "PriorArtError",
    "PriorArtReport",
    "PriorArtSearchPlan",
    "QueryFamily",
    "RankedPassageHit",
    "SearchCorpus",
    "SearchQuerySpec",
    "assert_chart_entries_cite_sources",
    "assert_no_patentability_conclusions",
    "build_claim_chart",
    "build_claim_chart_entries_from_logs",
    "build_golden_claim_chart_envelope",
    "build_prior_art_search_plan",
    "build_search_queries",
    "canonical_json",
    "content_digest",
    "contracts_canonical_json",
    "decompose_claim_limitations",
    "default_coverage_gaps",
    "default_foreign_patent_gap",
    "default_golden_claim_chart_path",
    "default_npl_gap",
    "execute_prior_art_plan",
    "extract_keyword_candidates",
    "load_golden_claim_chart",
    "parse_golden_claim_chart",
    "record_dated_query_log",
    "RETRIEVAL_CONTRACTS_SCHEMA_VERSION",
]
