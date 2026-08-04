"""Decompose claims into reviewed limitations and search plans (PATLAW-149).

Versions claim text, proposes atomic limitations with exact claim spans,
synonyms, concepts, CPC/IPC candidates, date/jurisdiction filters, and query
families. Candidate origin and confidence are retained. Explicit reviewer
acceptance is required before execution readiness.

Design invariants
-----------------
* Every limitation and query maps to exact claim spans and a claim version.
* Claim amendments (new claim-version content digest) invalidate stale plans.
* Ambiguous constructions remain alternatives until a human selects one.
* Model/deterministic candidates are never promoted without deterministic
  coverage checks **and** human review.
* Filing, priority, search, and jurisdiction anchors are user-supplied; this
  module never invents an invention date or patentability conclusion.
* Output always carries a non-advice disclaimer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .retrieval_contracts import SourceSpan

# ---------------------------------------------------------------------------
# Versions / interface / disclaimers
# ---------------------------------------------------------------------------

CLAIM_SEARCH_PLANNER_SCHEMA_VERSION: Final = "patent.claim_search_planner.v2"
CLAIM_SEARCH_PLANNER_INTERFACE: Final = "ClaimSearchPlanner@2"
CLAIM_SEARCH_PLANNER_RULESET_VERSION: Final = "claim-search-planner-rules@2"

OUTPUT_KIND_CLAIM_SEARCH_PLAN: Final = "claim_search_plan_v2"
OUTPUT_KIND_CLAIM_VERSION: Final = "claim_version_v2"
OUTPUT_KIND_REVIEWER_ACCEPTANCE: Final = "claim_search_plan_acceptance_v2"

CLAIM_SEARCH_PLANNER_DISCLAIMER: Final = (
    "This artifact versions claim text and proposes candidate limitations, "
    "synonyms, concepts, classifications, and query families for human review. "
    "Candidates retain origin and confidence and are not source authority. "
    "Ambiguous constructions remain alternatives until explicitly selected. "
    "Filing, priority, search, and jurisdiction anchors must be supplied by the "
    "user; this module never invents or infers an invention-date field. This "
    "output is not a novelty, obviousness, or patentability determination, not "
    "legal advice, not an IDS filing, and not executable search authorization "
    "until a natural person accepts the plan against the current claim version."
)

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
    "date of invention determined",
    "inferred invention date equals",
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_LIMITATION_SPLIT_RE = re.compile(
    r"\s*(?:,\s*and\s+|;\s*|\s+wherein\s+|\s+comprising\s+|\s+including\s+|"
    r"\s+characterized\s+by\s+)\s*",
    re.IGNORECASE,
)
_AMBIGUOUS_OR_RE = re.compile(
    r"\b(?:and/or|or\s+optionally|optionally)\b|\b\w+\s+or\s+\w+\b",
    re.IGNORECASE,
)
_MEANS_PLUS_FUNCTION_RE = re.compile(
    r"\bmeans\s+for\b|\bstep\s+for\b|\bconfigured\s+to\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-/]{1,63}")
_CPC_IPC_RE = re.compile(
    r"\b([A-HY]\d{2}[A-Z]?\s*\d{1,4}/\d{2,6})\b", re.IGNORECASE
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
        "means",
        "configured",
    }
)

# Lightweight synonym table for deterministic candidate proposals (not legal synonymy).
_SYNONYM_TABLE: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "encoding": ("encode", "encoder", "coded"),
        "retrieval": ("retrieve", "retrieving", "search"),
        "indexes": ("indexing", "index", "indexed"),
        "documents": ("document", "records", "files"),
        "network": ("networking", "communications", "comm"),
        "processor": ("processing unit", "cpu", "controller"),
        "memory": ("storage", "store", "storage medium"),
        "wireless": ("radio", "rf", "cellular"),
        "display": ("screen", "ui", "user interface"),
    }
)

DEFAULT_MAX_LIMITATIONS: Final = 64
DEFAULT_MAX_QUERIES: Final = 128
DEFAULT_MAX_SYNONYMS: Final = 64
DEFAULT_MAX_CONCEPTS: Final = 64
DEFAULT_MAX_CLASSIFICATIONS: Final = 32
DEFAULT_MAX_CONSTRUCTIONS: Final = 32
DEFAULT_RANK_CUTOFF: Final = 10
DEFAULT_DETERMINISTIC_CONFIDENCE: Final = 0.72
DEFAULT_SYNONYM_CONFIDENCE: Final = 0.45
DEFAULT_CONCEPT_CONFIDENCE: Final = 0.55
DEFAULT_CLASSIFICATION_CONFIDENCE: Final = 0.60
DEFAULT_MODEL_CANDIDATE_CONFIDENCE: Final = 0.40


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ClaimSearchPlannerError(ValueError):
    """Base error for claim search planner failures."""

    code: str = "claim_search_planner_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class MissingTemporalAnchorError(ClaimSearchPlannerError):
    """Raised when required user-supplied dates are missing."""

    code = "missing_temporal_anchor"


class InventedDateError(ClaimSearchPlannerError):
    """Raised when an invention date is invented or inferred."""

    code = "invented_date"


class ClaimSpanError(ClaimSearchPlannerError):
    """Raised when a limitation or query lacks an exact claim span."""

    code = "claim_span_required"


class ClaimVersionMismatchError(ClaimSearchPlannerError):
    """Raised when plan bindings no longer match the claim version."""

    code = "claim_version_mismatch"


class StalePlanError(ClaimSearchPlannerError):
    """Raised when an amended claim version invalidates a plan."""

    code = "stale_plan"


class UnreviewedCandidateError(ClaimSearchPlannerError):
    """Raised when unreviewed candidates are promoted or executed."""

    code = "unreviewed_candidate"


class OmittedLimitationError(ClaimSearchPlannerError):
    """Raised when claim coverage omits required limitation spans."""

    code = "omitted_limitation"


class PatentabilityConclusionError(ClaimSearchPlannerError):
    """Raised when a plan attempts a patentability conclusion."""

    code = "patentability_conclusion"


class PlanNotExecutableError(ClaimSearchPlannerError):
    """Raised when execution is requested without acceptance on current version."""

    code = "plan_not_executable"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CandidateOrigin(str, Enum):
    """How a candidate limitation, synonym, concept, or query was produced."""

    DETERMINISTIC_SPLIT = "deterministic_split"
    SYNONYM_EXPAND = "synonym_expand"
    CONCEPT_EXTRACT = "concept_extract"
    CLASSIFICATION_HINT = "classification_hint"
    MODEL_PROPOSAL = "model_proposal"
    HUMAN_SUPPLIED = "human_supplied"
    QUERY_FAMILY = "query_family"


class ReviewStatus(str, Enum):
    """Review disposition for candidates and plans."""

    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ALTERNATIVE = "alternative"


class QueryFamily(str, Enum):
    """Kind of planned query."""

    KEYWORD = "keyword"
    CLASSIFICATION_CPC = "classification_cpc"
    CLASSIFICATION_IPC = "classification_ipc"
    CLAIM_LIMITATION = "claim_limitation"
    CONCEPT = "concept"
    SYNONYM = "synonym"
    CONSTRUCTION_ALTERNATIVE = "construction_alternative"


class ClassificationScheme(str, Enum):
    CPC = "cpc"
    IPC = "ipc"


class ClaimKind(str, Enum):
    INDEPENDENT = "independent"
    DEPENDENT = "dependent"
    UNKNOWN = "unknown"


class PlanExecutionState(str, Enum):
    """Whether a plan may be handed to a search runtime."""

    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    ACCEPTED = "accepted"
    INVALIDATED = "invalidated"
    EXECUTABLE = "executable"


# ---------------------------------------------------------------------------
# Helpers
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


def text_sha256(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


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


def _slug_id_fragment(value: str, *, max_len: int = 48) -> str:
    """Sanitize free text into an identifier-safe fragment (no spaces)."""
    cleaned = re.sub(r"[^A-Za-z0-9._:/=+\-]+", "-", value.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = text_sha256(value)[:12]
    return cleaned[:max_len]


def _iso_date(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=32)
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} must be ISO calendar date YYYY-MM-DD, got {text!r}")
    return text


def _optional_iso_date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _iso_date(value, field)


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _iso_utc(value, field)


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


def _confidence(value: Any, field: str = "confidence") -> float:
    number = _finite_float(value, field)
    if number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0, 1], got {number}")
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


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be bool")
    return value


def _coerce_span(value: Any, field: str) -> SourceSpan:
    if isinstance(value, SourceSpan):
        span = value
    elif isinstance(value, Mapping):
        span = SourceSpan.from_dict(value)
    else:
        raise TypeError(f"{field} must be SourceSpan or mapping")
    if span.end <= span.start:
        raise ClaimSpanError(f"{field} must be a non-empty span (end > start)")
    return span


def _optional_span(value: Any, field: str) -> SourceSpan | None:
    if value is None:
        return None
    return _coerce_span(value, field)


def _assert_no_forbidden_keys(metadata: Mapping[str, str], label: str) -> None:
    for key in metadata:
        lowered = key.lower()
        if lowered in _FORBIDDEN_CONCLUSION_KEYS:
            raise PatentabilityConclusionError(
                f"{label} metadata must not assert forbidden key {key!r}"
            )
        for phrase in _FORBIDDEN_CONCLUSION_PHRASES:
            if phrase in metadata[key].lower():
                raise PatentabilityConclusionError(
                    f"{label} metadata value must not assert {phrase!r}"
                )


def assert_no_patentability_conclusions(payload: Mapping[str, Any] | object) -> None:
    """Fail closed if a serialized plan carries patentability conclusions."""
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
                        f"forbidden field at {path}/{key_s}"
                    )
                if isinstance(value, str):
                    lower_val = value.lower()
                    for phrase in _FORBIDDEN_CONCLUSION_PHRASES:
                        if phrase in lower_val:
                            raise PatentabilityConclusionError(
                                f"forbidden phrase {phrase!r} at {path}/{key_s}"
                            )
                _walk(value, f"{path}/{key_s}")
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(payload, "$")


def assert_no_invented_dates(payload: Mapping[str, Any] | object) -> None:
    """Fail closed if an invention date is present (never invented by this module)."""
    if not isinstance(payload, Mapping):
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()  # type: ignore[assignment]
        else:
            raise TypeError("payload must be a mapping or expose to_dict()")
    assert isinstance(payload, Mapping)

    banned = frozenset(
        {
            "invention_date",
            "inferred_invention_date",
            "invented_date",
            "invention_date_utc",
            "date_of_invention",
        }
    )

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_s = str(key)
                if key_s.lower() in banned:
                    raise InventedDateError(
                        f"invention date field forbidden at {path}/{key_s}; "
                        "user must supply filing/priority/search dates only"
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
class VersionedClaim:
    """One claim within a versioned claim set."""

    claim_number: int
    claim_text: str
    claim_kind: ClaimKind = ClaimKind.UNKNOWN
    depends_on: tuple[int, ...] = ()
    text_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "claim_number", _positive_int(self.claim_number, "claim_number")
        )
        object.__setattr__(
            self, "claim_text", _require_str(self.claim_text, "claim_text", max_len=200_000)
        )
        object.__setattr__(
            self, "claim_kind", _coerce_enum(ClaimKind, self.claim_kind, "claim_kind")
        )
        deps = self.depends_on or ()
        if not isinstance(deps, Sequence) or isinstance(deps, (str, bytes)):
            raise TypeError("depends_on must be a sequence of ints")
        coerced_deps = tuple(
            _positive_int(d, f"depends_on[{i}]") for i, d in enumerate(deps)
        )
        object.__setattr__(self, "depends_on", coerced_deps)
        digest = text_sha256(self.claim_text)
        provided = _optional_str(self.text_sha256, "text_sha256", max_len=64)
        if provided is not None and provided.lower() != digest:
            raise ValueError("text_sha256 does not match claim_text")
        object.__setattr__(self, "text_sha256", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_kind": self.claim_kind.value,
            "claim_number": self.claim_number,
            "claim_text": self.claim_text,
            "depends_on": list(self.depends_on),
            "text_sha256": self.text_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VersionedClaim":
        value = _mapping(value, "VersionedClaim")
        return cls(
            claim_number=int(value.get("claim_number") or 0),
            claim_text=value.get("claim_text", ""),
            claim_kind=value.get("claim_kind", ClaimKind.UNKNOWN.value),
            depends_on=tuple(value.get("depends_on") or ()),
            text_sha256=value.get("text_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ClaimVersion:
    """Immutable versioned claim set. Amendments produce a new version."""

    schema_version: str
    claim_version_id: str
    subject_id: str
    version: int
    claims: tuple[VersionedClaim, ...]
    content_sha256: str
    as_of_utc: str | None = None
    amendment_of: str | None = None
    output_kind: str = OUTPUT_KIND_CLAIM_VERSION
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version, CLAIM_SEARCH_PLANNER_SCHEMA_VERSION, "ClaimVersion"
            ),
        )
        object.__setattr__(
            self, "claim_version_id", _identifier(self.claim_version_id, "claim_version_id")
        )
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        claims = self.claims or ()
        if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
            raise TypeError("claims must be a sequence")
        if not claims:
            raise ValueError("claims must be non-empty")
        parsed: list[VersionedClaim] = []
        for i, item in enumerate(claims):
            if isinstance(item, VersionedClaim):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(VersionedClaim.from_dict(item))
            else:
                raise TypeError(f"claims[{i}] must be VersionedClaim or mapping")
        object.__setattr__(self, "claims", tuple(parsed))
        expected = claim_set_content_sha256(self.claims)
        provided = _require_str(self.content_sha256, "content_sha256", max_len=64).lower()
        if provided != expected:
            raise ValueError(
                "content_sha256 does not match claim set identity; "
                f"expected {expected}, got {provided}"
            )
        object.__setattr__(self, "content_sha256", expected)
        object.__setattr__(
            self, "as_of_utc", _optional_iso_utc(self.as_of_utc, "as_of_utc")
        )
        object.__setattr__(
            self, "amendment_of", _optional_str(self.amendment_of, "amendment_of", max_len=256)
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_CLAIM_VERSION:
            raise ValueError(
                f"ClaimVersion.output_kind must be {OUTPUT_KIND_CLAIM_VERSION!r}"
            )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimVersion")

    def claim_by_number(self, claim_number: int) -> VersionedClaim:
        for claim in self.claims:
            if claim.claim_number == claim_number:
                return claim
        raise KeyError(f"claim_number {claim_number} not in claim version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment_of": self.amendment_of,
            "as_of_utc": self.as_of_utc,
            "claim_version_id": self.claim_version_id,
            "claims": [c.to_dict() for c in self.claims],
            "content_sha256": self.content_sha256,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimVersion":
        value = _mapping(value, "ClaimVersion")
        return cls(
            schema_version=value.get(
                "schema_version", CLAIM_SEARCH_PLANNER_SCHEMA_VERSION
            ),
            claim_version_id=value.get("claim_version_id", ""),
            subject_id=value.get("subject_id", ""),
            version=int(value.get("version") or 0),
            claims=tuple(value.get("claims") or ()),
            content_sha256=value.get("content_sha256", ""),
            as_of_utc=value.get("as_of_utc"),
            amendment_of=value.get("amendment_of"),
            output_kind=value.get("output_kind", OUTPUT_KIND_CLAIM_VERSION),
            metadata=value.get("metadata") or {},
        )


def claim_set_content_sha256(claims: Sequence[VersionedClaim | Mapping[str, Any]]) -> str:
    """Content identity of a claim set (order-stable by claim_number)."""
    normalized: list[dict[str, Any]] = []
    for item in claims:
        if isinstance(item, VersionedClaim):
            claim = item
        elif isinstance(item, Mapping):
            claim = VersionedClaim.from_dict(item)
        else:
            raise TypeError("claims items must be VersionedClaim or mapping")
        normalized.append(
            {
                "claim_kind": claim.claim_kind.value,
                "claim_number": claim.claim_number,
                "claim_text": claim.claim_text,
                "depends_on": list(claim.depends_on),
            }
        )
    normalized.sort(key=lambda c: c["claim_number"])
    return content_digest(normalized)


def version_claims(
    *,
    subject_id: str,
    claims: Sequence[Mapping[str, Any] | VersionedClaim],
    version: int = 1,
    claim_version_id: str | None = None,
    as_of_utc: str | None = None,
    amendment_of: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> ClaimVersion:
    """Build an immutable claim version from claim mappings or objects."""
    parsed: list[VersionedClaim] = []
    for i, item in enumerate(claims):
        if isinstance(item, VersionedClaim):
            parsed.append(item)
        elif isinstance(item, Mapping):
            parsed.append(VersionedClaim.from_dict(item))
        else:
            raise TypeError(f"claims[{i}] must be VersionedClaim or mapping")
    if not parsed:
        raise ClaimSearchPlannerError("at least one claim is required")
    digest = claim_set_content_sha256(parsed)
    resolved_id = claim_version_id or f"claim-ver:{subject_id}:v{version}:{digest[:16]}"
    return ClaimVersion(
        schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
        claim_version_id=resolved_id,
        subject_id=subject_id,
        version=version,
        claims=tuple(parsed),
        content_sha256=digest,
        as_of_utc=as_of_utc,
        amendment_of=amendment_of,
        metadata=metadata or {},
    )


@dataclass(frozen=True, slots=True)
class LimitationCandidate:
    """Atomic claim limitation candidate bound to exact claim span + version.

    Remains a candidate until a human accepts it. Never source authority.
    """

    limitation_id: str
    claim_version_id: str
    claim_version_digest: str
    claim_number: int
    text: str
    claim_span: SourceSpan
    ordinal: int
    origin: CandidateOrigin = CandidateOrigin.DETERMINISTIC_SPLIT
    confidence: float = DEFAULT_DETERMINISTIC_CONFIDENCE
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    is_candidate: bool = True
    construction_group_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "limitation_id", _identifier(self.limitation_id, "limitation_id")
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        digest = _require_str(
            self.claim_version_digest, "claim_version_digest", max_len=64
        ).lower()
        if len(digest) != 64:
            raise ValueError("claim_version_digest must be 64-char sha256 hex")
        object.__setattr__(self, "claim_version_digest", digest)
        object.__setattr__(
            self, "claim_number", _positive_int(self.claim_number, "claim_number")
        )
        object.__setattr__(
            self, "text", _require_str(self.text, "text", max_len=20_000)
        )
        object.__setattr__(self, "claim_span", _coerce_span(self.claim_span, "claim_span"))
        object.__setattr__(self, "ordinal", _positive_int(self.ordinal, "ordinal"))
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(
            self,
            "review_status",
            _coerce_enum(ReviewStatus, self.review_status, "review_status"),
        )
        is_cand = _require_bool(self.is_candidate, "is_candidate")
        if self.review_status is ReviewStatus.ACCEPTED:
            if is_cand:
                raise UnreviewedCandidateError(
                    "accepted limitations must set is_candidate=False only via "
                    "reviewer acceptance helpers"
                )
        else:
            if not is_cand:
                raise UnreviewedCandidateError(
                    "non-accepted limitations must remain is_candidate=True; "
                    "do not promote without review"
                )
        object.__setattr__(self, "is_candidate", is_cand)
        object.__setattr__(
            self,
            "construction_group_id",
            _optional_str(self.construction_group_id, "construction_group_id", max_len=256),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "LimitationCandidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_number": self.claim_number,
            "claim_span": self.claim_span.to_dict(),
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "confidence": self.confidence,
            "construction_group_id": self.construction_group_id,
            "is_candidate": self.is_candidate,
            "limitation_id": self.limitation_id,
            "metadata": dict(self.metadata),
            "ordinal": self.ordinal,
            "origin": self.origin.value,
            "review_status": self.review_status.value,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LimitationCandidate":
        value = _mapping(value, "LimitationCandidate")
        return cls(
            limitation_id=value.get("limitation_id", ""),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            claim_number=int(value.get("claim_number") or 0),
            text=value.get("text", ""),
            claim_span=value.get("claim_span") or {},
            ordinal=int(value.get("ordinal") or 1),
            origin=value.get("origin", CandidateOrigin.DETERMINISTIC_SPLIT.value),
            confidence=float(
                value.get("confidence")
                if value.get("confidence") is not None
                else DEFAULT_DETERMINISTIC_CONFIDENCE
            ),
            review_status=value.get("review_status", ReviewStatus.CANDIDATE.value),
            is_candidate=bool(value.get("is_candidate", True)),
            construction_group_id=value.get("construction_group_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ConstructionAlternative:
    """Ambiguous claim construction that remains an alternative until selected."""

    construction_id: str
    claim_version_id: str
    claim_version_digest: str
    claim_number: int
    claim_span: SourceSpan
    source_text: str
    readings: tuple[str, ...]
    origin: CandidateOrigin = CandidateOrigin.DETERMINISTIC_SPLIT
    confidence: float = DEFAULT_DETERMINISTIC_CONFIDENCE
    remains_alternative: bool = True
    selected_reading: str | None = None
    review_status: ReviewStatus = ReviewStatus.ALTERNATIVE
    related_limitation_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "construction_id", _identifier(self.construction_id, "construction_id")
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        digest = _require_str(
            self.claim_version_digest, "claim_version_digest", max_len=64
        ).lower()
        object.__setattr__(self, "claim_version_digest", digest)
        object.__setattr__(
            self, "claim_number", _positive_int(self.claim_number, "claim_number")
        )
        object.__setattr__(self, "claim_span", _coerce_span(self.claim_span, "claim_span"))
        object.__setattr__(
            self, "source_text", _require_str(self.source_text, "source_text", max_len=20_000)
        )
        readings = _tuple_of_str(self.readings, "readings", max_items=16)
        if len(readings) < 2:
            raise ValueError("ConstructionAlternative.readings must have at least 2 items")
        object.__setattr__(self, "readings", readings)
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        remains = _require_bool(self.remains_alternative, "remains_alternative")
        selected = _optional_str(self.selected_reading, "selected_reading", max_len=20_000)
        status = _coerce_enum(ReviewStatus, self.review_status, "review_status")
        if selected is not None:
            if selected not in readings:
                raise ValueError("selected_reading must be one of readings")
            if remains:
                raise ValueError(
                    "selected constructions must set remains_alternative=False"
                )
            if status is not ReviewStatus.ACCEPTED:
                raise UnreviewedCandidateError(
                    "selected construction must have review_status=accepted"
                )
        else:
            if not remains:
                raise ValueError(
                    "unselected constructions must remain alternatives "
                    "(remains_alternative=True)"
                )
            if status not in (ReviewStatus.ALTERNATIVE, ReviewStatus.CANDIDATE, ReviewStatus.REJECTED):
                raise ValueError(
                    "unselected construction review_status must be alternative/candidate/rejected"
                )
        object.__setattr__(self, "remains_alternative", remains)
        object.__setattr__(self, "selected_reading", selected)
        object.__setattr__(self, "review_status", status)
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ConstructionAlternative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_number": self.claim_number,
            "claim_span": self.claim_span.to_dict(),
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "confidence": self.confidence,
            "construction_id": self.construction_id,
            "metadata": dict(self.metadata),
            "origin": self.origin.value,
            "readings": list(self.readings),
            "related_limitation_ids": list(self.related_limitation_ids),
            "remains_alternative": self.remains_alternative,
            "review_status": self.review_status.value,
            "selected_reading": self.selected_reading,
            "source_text": self.source_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConstructionAlternative":
        value = _mapping(value, "ConstructionAlternative")
        return cls(
            construction_id=value.get("construction_id", ""),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            claim_number=int(value.get("claim_number") or 0),
            claim_span=value.get("claim_span") or {},
            source_text=value.get("source_text", ""),
            readings=tuple(value.get("readings") or ()),
            origin=value.get("origin", CandidateOrigin.DETERMINISTIC_SPLIT.value),
            confidence=float(
                value.get("confidence")
                if value.get("confidence") is not None
                else DEFAULT_DETERMINISTIC_CONFIDENCE
            ),
            remains_alternative=bool(value.get("remains_alternative", True)),
            selected_reading=value.get("selected_reading"),
            review_status=value.get("review_status", ReviewStatus.ALTERNATIVE.value),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SynonymCandidate:
    """Synonym expansion candidate tied to a limitation and claim version."""

    synonym_id: str
    term: str
    synonym: str
    claim_version_id: str
    claim_version_digest: str
    related_limitation_ids: tuple[str, ...]
    claim_spans: tuple[SourceSpan, ...]
    origin: CandidateOrigin = CandidateOrigin.SYNONYM_EXPAND
    confidence: float = DEFAULT_SYNONYM_CONFIDENCE
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    is_candidate: bool = True
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "synonym_id", _identifier(self.synonym_id, "synonym_id"))
        object.__setattr__(self, "term", _require_str(self.term, "term", max_len=256))
        object.__setattr__(
            self, "synonym", _require_str(self.synonym, "synonym", max_len=256)
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _require_str(self.claim_version_digest, "claim_version_digest", max_len=64).lower(),
        )
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        spans = self.claim_spans or ()
        if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes)):
            raise TypeError("claim_spans must be a sequence")
        if not spans:
            raise ClaimSpanError("SynonymCandidate.claim_spans must be non-empty")
        object.__setattr__(
            self,
            "claim_spans",
            tuple(_coerce_span(s, f"claim_spans[{i}]") for i, s in enumerate(spans)),
        )
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(
            self,
            "review_status",
            _coerce_enum(ReviewStatus, self.review_status, "review_status"),
        )
        is_cand = _require_bool(self.is_candidate, "is_candidate")
        if self.review_status is ReviewStatus.ACCEPTED and is_cand:
            raise UnreviewedCandidateError(
                "accepted synonyms must set is_candidate=False via acceptance helpers"
            )
        if self.review_status is not ReviewStatus.ACCEPTED and not is_cand:
            raise UnreviewedCandidateError(
                "non-accepted synonyms must remain is_candidate=True"
            )
        object.__setattr__(self, "is_candidate", is_cand)
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "SynonymCandidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_spans": [s.to_dict() for s in self.claim_spans],
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "confidence": self.confidence,
            "is_candidate": self.is_candidate,
            "metadata": dict(self.metadata),
            "origin": self.origin.value,
            "related_limitation_ids": list(self.related_limitation_ids),
            "review_status": self.review_status.value,
            "synonym": self.synonym,
            "synonym_id": self.synonym_id,
            "term": self.term,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SynonymCandidate":
        value = _mapping(value, "SynonymCandidate")
        return cls(
            synonym_id=value.get("synonym_id", ""),
            term=value.get("term", ""),
            synonym=value.get("synonym", ""),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            claim_spans=tuple(value.get("claim_spans") or ()),
            origin=value.get("origin", CandidateOrigin.SYNONYM_EXPAND.value),
            confidence=float(
                value.get("confidence")
                if value.get("confidence") is not None
                else DEFAULT_SYNONYM_CONFIDENCE
            ),
            review_status=value.get("review_status", ReviewStatus.CANDIDATE.value),
            is_candidate=bool(value.get("is_candidate", True)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ConceptCandidate:
    """Concept token candidate derived from claim limitation text."""

    concept_id: str
    concept: str
    claim_version_id: str
    claim_version_digest: str
    related_limitation_ids: tuple[str, ...]
    claim_spans: tuple[SourceSpan, ...]
    origin: CandidateOrigin = CandidateOrigin.CONCEPT_EXTRACT
    confidence: float = DEFAULT_CONCEPT_CONFIDENCE
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    is_candidate: bool = True
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "concept_id", _identifier(self.concept_id, "concept_id"))
        object.__setattr__(
            self, "concept", _require_str(self.concept, "concept", max_len=256)
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _require_str(self.claim_version_digest, "claim_version_digest", max_len=64).lower(),
        )
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        spans = self.claim_spans or ()
        if not spans:
            raise ClaimSpanError("ConceptCandidate.claim_spans must be non-empty")
        object.__setattr__(
            self,
            "claim_spans",
            tuple(_coerce_span(s, f"claim_spans[{i}]") for i, s in enumerate(spans)),
        )
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(
            self,
            "review_status",
            _coerce_enum(ReviewStatus, self.review_status, "review_status"),
        )
        is_cand = _require_bool(self.is_candidate, "is_candidate")
        if self.review_status is ReviewStatus.ACCEPTED and is_cand:
            raise UnreviewedCandidateError(
                "accepted concepts must set is_candidate=False via acceptance helpers"
            )
        if self.review_status is not ReviewStatus.ACCEPTED and not is_cand:
            raise UnreviewedCandidateError(
                "non-accepted concepts must remain is_candidate=True"
            )
        object.__setattr__(self, "is_candidate", is_cand)
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ConceptCandidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_spans": [s.to_dict() for s in self.claim_spans],
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "concept": self.concept,
            "concept_id": self.concept_id,
            "confidence": self.confidence,
            "is_candidate": self.is_candidate,
            "metadata": dict(self.metadata),
            "origin": self.origin.value,
            "related_limitation_ids": list(self.related_limitation_ids),
            "review_status": self.review_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConceptCandidate":
        value = _mapping(value, "ConceptCandidate")
        return cls(
            concept_id=value.get("concept_id", ""),
            concept=value.get("concept", ""),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            claim_spans=tuple(value.get("claim_spans") or ()),
            origin=value.get("origin", CandidateOrigin.CONCEPT_EXTRACT.value),
            confidence=float(
                value.get("confidence")
                if value.get("confidence") is not None
                else DEFAULT_CONCEPT_CONFIDENCE
            ),
            review_status=value.get("review_status", ReviewStatus.CANDIDATE.value),
            is_candidate=bool(value.get("is_candidate", True)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ClassificationCandidate:
    """CPC/IPC classification candidate with origin/confidence."""

    classification_id: str
    code: str
    scheme: ClassificationScheme
    claim_version_id: str
    claim_version_digest: str
    related_limitation_ids: tuple[str, ...]
    claim_spans: tuple[SourceSpan, ...]
    origin: CandidateOrigin = CandidateOrigin.CLASSIFICATION_HINT
    confidence: float = DEFAULT_CLASSIFICATION_CONFIDENCE
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    is_candidate: bool = True
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "classification_id",
            _identifier(self.classification_id, "classification_id"),
        )
        code = re.sub(
            r"\s+", "", _require_str(self.code, "code", max_len=64)
        ).upper()
        object.__setattr__(self, "code", code)
        object.__setattr__(
            self, "scheme", _coerce_enum(ClassificationScheme, self.scheme, "scheme")
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _require_str(self.claim_version_digest, "claim_version_digest", max_len=64).lower(),
        )
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        spans = self.claim_spans or ()
        if not spans:
            raise ClaimSpanError("ClassificationCandidate.claim_spans must be non-empty")
        object.__setattr__(
            self,
            "claim_spans",
            tuple(_coerce_span(s, f"claim_spans[{i}]") for i, s in enumerate(spans)),
        )
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(
            self,
            "review_status",
            _coerce_enum(ReviewStatus, self.review_status, "review_status"),
        )
        is_cand = _require_bool(self.is_candidate, "is_candidate")
        if self.review_status is ReviewStatus.ACCEPTED and is_cand:
            raise UnreviewedCandidateError(
                "accepted classifications must set is_candidate=False via acceptance helpers"
            )
        if self.review_status is not ReviewStatus.ACCEPTED and not is_cand:
            raise UnreviewedCandidateError(
                "non-accepted classifications must remain is_candidate=True"
            )
        object.__setattr__(self, "is_candidate", is_cand)
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClassificationCandidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_spans": [s.to_dict() for s in self.claim_spans],
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "classification_id": self.classification_id,
            "code": self.code,
            "confidence": self.confidence,
            "is_candidate": self.is_candidate,
            "metadata": dict(self.metadata),
            "origin": self.origin.value,
            "related_limitation_ids": list(self.related_limitation_ids),
            "review_status": self.review_status.value,
            "scheme": self.scheme.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClassificationCandidate":
        value = _mapping(value, "ClassificationCandidate")
        return cls(
            classification_id=value.get("classification_id", ""),
            code=value.get("code", ""),
            scheme=value.get("scheme", ClassificationScheme.CPC.value),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            claim_spans=tuple(value.get("claim_spans") or ()),
            origin=value.get("origin", CandidateOrigin.CLASSIFICATION_HINT.value),
            confidence=float(
                value.get("confidence")
                if value.get("confidence") is not None
                else DEFAULT_CLASSIFICATION_CONFIDENCE
            ),
            review_status=value.get("review_status", ReviewStatus.CANDIDATE.value),
            is_candidate=bool(value.get("is_candidate", True)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SearchFilterSpec:
    """User-supplied date/jurisdiction filters for planned queries.

    Never contains an invention date. Filing/priority/search anchors are
    optional at filter construction but required for executable plans.
    """

    jurisdictions: tuple[str, ...] = ()
    filing_date: str | None = None
    priority_date: str | None = None
    search_date_utc: str | None = None
    corpus_cutoff: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "jurisdictions",
            _tuple_of_str(self.jurisdictions, "jurisdictions", max_items=32),
        )
        object.__setattr__(
            self, "filing_date", _optional_iso_date(self.filing_date, "filing_date")
        )
        object.__setattr__(
            self, "priority_date", _optional_iso_date(self.priority_date, "priority_date")
        )
        object.__setattr__(
            self,
            "search_date_utc",
            _optional_iso_utc(self.search_date_utc, "search_date_utc"),
        )
        cutoff = _optional_str(self.corpus_cutoff, "corpus_cutoff", max_len=64)
        if cutoff is not None and not (
            _ISO_DATE_RE.match(cutoff) or _ISO_UTC_RE.match(cutoff)
        ):
            raise ValueError(
                f"corpus_cutoff must be YYYY-MM-DD or ISO-8601 UTC, got {cutoff!r}"
            )
        object.__setattr__(self, "corpus_cutoff", cutoff)
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "SearchFilterSpec")
        # Hard fail on invented invention-date keys in metadata.
        assert_no_invented_dates({"metadata": dict(self.metadata)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_cutoff": self.corpus_cutoff,
            "filing_date": self.filing_date,
            "jurisdictions": list(self.jurisdictions),
            "metadata": dict(self.metadata),
            "priority_date": self.priority_date,
            "search_date_utc": self.search_date_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SearchFilterSpec":
        value = _mapping(value, "SearchFilterSpec")
        # Reject invention date fields at admission.
        assert_no_invented_dates(value)
        return cls(
            jurisdictions=tuple(value.get("jurisdictions") or ()),
            filing_date=value.get("filing_date"),
            priority_date=value.get("priority_date"),
            search_date_utc=value.get("search_date_utc"),
            corpus_cutoff=value.get("corpus_cutoff"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PlannedQuery:
    """One planned search query bound to claim version + exact claim spans."""

    query_id: str
    query_text: str
    family: QueryFamily
    claim_version_id: str
    claim_version_digest: str
    claim_spans: tuple[SourceSpan, ...]
    related_limitation_ids: tuple[str, ...]
    origin: CandidateOrigin = CandidateOrigin.QUERY_FAMILY
    confidence: float = DEFAULT_DETERMINISTIC_CONFIDENCE
    review_status: ReviewStatus = ReviewStatus.CANDIDATE
    is_candidate: bool = True
    classification_codes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    rank_cutoff: int = DEFAULT_RANK_CUTOFF
    filters: SearchFilterSpec | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "query_text", _require_str(self.query_text, "query_text", max_len=8192)
        )
        object.__setattr__(
            self, "family", _coerce_enum(QueryFamily, self.family, "family")
        )
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _require_str(self.claim_version_digest, "claim_version_digest", max_len=64).lower(),
        )
        spans = self.claim_spans or ()
        if not spans:
            raise ClaimSpanError("PlannedQuery.claim_spans must be non-empty")
        object.__setattr__(
            self,
            "claim_spans",
            tuple(_coerce_span(s, f"claim_spans[{i}]") for i, s in enumerate(spans)),
        )
        object.__setattr__(
            self,
            "related_limitation_ids",
            _tuple_of_str(
                self.related_limitation_ids, "related_limitation_ids", max_items=64
            ),
        )
        if not self.related_limitation_ids:
            raise ClaimSpanError(
                "PlannedQuery.related_limitation_ids must map to at least one limitation"
            )
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(
            self,
            "review_status",
            _coerce_enum(ReviewStatus, self.review_status, "review_status"),
        )
        is_cand = _require_bool(self.is_candidate, "is_candidate")
        if self.review_status is ReviewStatus.ACCEPTED and is_cand:
            raise UnreviewedCandidateError(
                "accepted queries must set is_candidate=False via acceptance helpers"
            )
        if self.review_status is not ReviewStatus.ACCEPTED and not is_cand:
            raise UnreviewedCandidateError(
                "non-accepted queries must remain is_candidate=True"
            )
        object.__setattr__(self, "is_candidate", is_cand)
        object.__setattr__(
            self,
            "classification_codes",
            _tuple_of_str(
                self.classification_codes, "classification_codes", max_items=32
            ),
        )
        object.__setattr__(
            self, "keywords", _tuple_of_str(self.keywords, "keywords", max_items=64)
        )
        object.__setattr__(
            self, "rank_cutoff", _positive_int(self.rank_cutoff, "rank_cutoff")
        )
        if self.filters is not None and not isinstance(self.filters, SearchFilterSpec):
            if isinstance(self.filters, Mapping):
                object.__setattr__(self, "filters", SearchFilterSpec.from_dict(self.filters))
            else:
                raise TypeError("filters must be SearchFilterSpec, mapping, or None")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "PlannedQuery")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_spans": [s.to_dict() for s in self.claim_spans],
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "classification_codes": list(self.classification_codes),
            "confidence": self.confidence,
            "family": self.family.value,
            "filters": None if self.filters is None else self.filters.to_dict(),
            "is_candidate": self.is_candidate,
            "keywords": list(self.keywords),
            "metadata": dict(self.metadata),
            "origin": self.origin.value,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "rank_cutoff": self.rank_cutoff,
            "related_limitation_ids": list(self.related_limitation_ids),
            "review_status": self.review_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannedQuery":
        value = _mapping(value, "PlannedQuery")
        return cls(
            query_id=value.get("query_id", ""),
            query_text=value.get("query_text", ""),
            family=value.get("family", QueryFamily.KEYWORD.value),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            claim_spans=tuple(value.get("claim_spans") or ()),
            related_limitation_ids=tuple(value.get("related_limitation_ids") or ()),
            origin=value.get("origin", CandidateOrigin.QUERY_FAMILY.value),
            confidence=float(
                value.get("confidence")
                if value.get("confidence") is not None
                else DEFAULT_DETERMINISTIC_CONFIDENCE
            ),
            review_status=value.get("review_status", ReviewStatus.CANDIDATE.value),
            is_candidate=bool(value.get("is_candidate", True)),
            classification_codes=tuple(value.get("classification_codes") or ()),
            keywords=tuple(value.get("keywords") or ()),
            rank_cutoff=int(value.get("rank_cutoff") or DEFAULT_RANK_CUTOFF),
            filters=value.get("filters"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ReviewerAcceptance:
    """Explicit natural-person acceptance bound to a claim version digest."""

    acceptance_id: str
    plan_id: str
    claim_version_id: str
    claim_version_digest: str
    plan_digest: str
    reviewer_id: str
    accepted_at_utc: str
    accepted_limitation_ids: tuple[str, ...]
    accepted_query_ids: tuple[str, ...]
    selected_constructions: Mapping[str, str] = MappingProxyType({})
    accepted_synonym_ids: tuple[str, ...] = ()
    accepted_concept_ids: tuple[str, ...] = ()
    accepted_classification_ids: tuple[str, ...] = ()
    output_kind: str = OUTPUT_KIND_REVIEWER_ACCEPTANCE
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "acceptance_id", _identifier(self.acceptance_id, "acceptance_id")
        )
        object.__setattr__(self, "plan_id", _identifier(self.plan_id, "plan_id"))
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _require_str(self.claim_version_digest, "claim_version_digest", max_len=64).lower(),
        )
        object.__setattr__(
            self,
            "plan_digest",
            _require_str(self.plan_digest, "plan_digest", max_len=64).lower(),
        )
        object.__setattr__(
            self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id")
        )
        object.__setattr__(
            self, "accepted_at_utc", _iso_utc(self.accepted_at_utc, "accepted_at_utc")
        )
        object.__setattr__(
            self,
            "accepted_limitation_ids",
            _tuple_of_str(
                self.accepted_limitation_ids, "accepted_limitation_ids", max_items=256
            ),
        )
        if not self.accepted_limitation_ids:
            raise ValueError("accepted_limitation_ids must be non-empty")
        object.__setattr__(
            self,
            "accepted_query_ids",
            _tuple_of_str(self.accepted_query_ids, "accepted_query_ids", max_items=256),
        )
        if not self.accepted_query_ids:
            raise ValueError("accepted_query_ids must be non-empty")
        if not isinstance(self.selected_constructions, Mapping):
            raise TypeError("selected_constructions must be a mapping")
        selected = {
            _require_str(k, "selected_constructions.key", max_len=256): _require_str(
                v, f"selected_constructions[{k}]", max_len=20_000
            )
            for k, v in self.selected_constructions.items()
        }
        object.__setattr__(
            self, "selected_constructions", MappingProxyType(dict(sorted(selected.items())))
        )
        object.__setattr__(
            self,
            "accepted_synonym_ids",
            _tuple_of_str(self.accepted_synonym_ids, "accepted_synonym_ids", max_items=256),
        )
        object.__setattr__(
            self,
            "accepted_concept_ids",
            _tuple_of_str(self.accepted_concept_ids, "accepted_concept_ids", max_items=256),
        )
        object.__setattr__(
            self,
            "accepted_classification_ids",
            _tuple_of_str(
                self.accepted_classification_ids,
                "accepted_classification_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_REVIEWER_ACCEPTANCE:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_REVIEWER_ACCEPTANCE!r}"
            )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ReviewerAcceptance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_id": self.acceptance_id,
            "accepted_at_utc": self.accepted_at_utc,
            "accepted_classification_ids": list(self.accepted_classification_ids),
            "accepted_concept_ids": list(self.accepted_concept_ids),
            "accepted_limitation_ids": list(self.accepted_limitation_ids),
            "accepted_query_ids": list(self.accepted_query_ids),
            "accepted_synonym_ids": list(self.accepted_synonym_ids),
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "plan_digest": self.plan_digest,
            "plan_id": self.plan_id,
            "reviewer_id": self.reviewer_id,
            "selected_constructions": dict(self.selected_constructions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewerAcceptance":
        value = _mapping(value, "ReviewerAcceptance")
        return cls(
            acceptance_id=value.get("acceptance_id", ""),
            plan_id=value.get("plan_id", ""),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            plan_digest=value.get("plan_digest", ""),
            reviewer_id=value.get("reviewer_id", ""),
            accepted_at_utc=value.get("accepted_at_utc", ""),
            accepted_limitation_ids=tuple(value.get("accepted_limitation_ids") or ()),
            accepted_query_ids=tuple(value.get("accepted_query_ids") or ()),
            selected_constructions=value.get("selected_constructions") or {},
            accepted_synonym_ids=tuple(value.get("accepted_synonym_ids") or ()),
            accepted_concept_ids=tuple(value.get("accepted_concept_ids") or ()),
            accepted_classification_ids=tuple(
                value.get("accepted_classification_ids") or ()
            ),
            output_kind=value.get("output_kind", OUTPUT_KIND_REVIEWER_ACCEPTANCE),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ClaimSearchPlan:
    """Reviewed claim-search plan bound to a claim version.

    Starts as draft/review-required. Execution requires reviewer acceptance
    against the same claim_version_digest. Amendments invalidate the plan.
    """

    schema_version: str
    plan_id: str
    subject_id: str
    claim_version_id: str
    claim_version_digest: str
    limitations: tuple[LimitationCandidate, ...]
    queries: tuple[PlannedQuery, ...]
    constructions: tuple[ConstructionAlternative, ...] = ()
    synonyms: tuple[SynonymCandidate, ...] = ()
    concepts: tuple[ConceptCandidate, ...] = ()
    classifications: tuple[ClassificationCandidate, ...] = ()
    filters: SearchFilterSpec | None = None
    execution_state: PlanExecutionState = PlanExecutionState.REVIEW_REQUIRED
    invalidated: bool = False
    invalidation_reason: str | None = None
    acceptance: ReviewerAcceptance | None = None
    output_kind: str = OUTPUT_KIND_CLAIM_SEARCH_PLAN
    disclaimer: str = CLAIM_SEARCH_PLANNER_DISCLAIMER
    ruleset_version: str = CLAIM_SEARCH_PLANNER_RULESET_VERSION
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _schema_pinned(
                self.schema_version,
                CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
                "ClaimSearchPlan",
            ),
        )
        object.__setattr__(self, "plan_id", _identifier(self.plan_id, "plan_id"))
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "claim_version_id",
            _identifier(self.claim_version_id, "claim_version_id"),
        )
        object.__setattr__(
            self,
            "claim_version_digest",
            _require_str(self.claim_version_digest, "claim_version_digest", max_len=64).lower(),
        )
        object.__setattr__(
            self,
            "limitations",
            _coerce_sequence(
                self.limitations, LimitationCandidate, "limitations", max_items=DEFAULT_MAX_LIMITATIONS
            ),
        )
        if not self.limitations:
            raise ValueError("limitations must be non-empty")
        object.__setattr__(
            self,
            "queries",
            _coerce_sequence(
                self.queries, PlannedQuery, "queries", max_items=DEFAULT_MAX_QUERIES
            ),
        )
        if not self.queries:
            raise ValueError("queries must be non-empty")
        object.__setattr__(
            self,
            "constructions",
            _coerce_sequence(
                self.constructions,
                ConstructionAlternative,
                "constructions",
                max_items=DEFAULT_MAX_CONSTRUCTIONS,
            ),
        )
        object.__setattr__(
            self,
            "synonyms",
            _coerce_sequence(
                self.synonyms, SynonymCandidate, "synonyms", max_items=DEFAULT_MAX_SYNONYMS
            ),
        )
        object.__setattr__(
            self,
            "concepts",
            _coerce_sequence(
                self.concepts, ConceptCandidate, "concepts", max_items=DEFAULT_MAX_CONCEPTS
            ),
        )
        object.__setattr__(
            self,
            "classifications",
            _coerce_sequence(
                self.classifications,
                ClassificationCandidate,
                "classifications",
                max_items=DEFAULT_MAX_CLASSIFICATIONS,
            ),
        )
        if self.filters is not None and not isinstance(self.filters, SearchFilterSpec):
            if isinstance(self.filters, Mapping):
                object.__setattr__(self, "filters", SearchFilterSpec.from_dict(self.filters))
            else:
                raise TypeError("filters must be SearchFilterSpec, mapping, or None")
        object.__setattr__(
            self,
            "execution_state",
            _coerce_enum(PlanExecutionState, self.execution_state, "execution_state"),
        )
        object.__setattr__(
            self, "invalidated", _require_bool(self.invalidated, "invalidated")
        )
        object.__setattr__(
            self,
            "invalidation_reason",
            _optional_str(self.invalidation_reason, "invalidation_reason", max_len=1024),
        )
        if self.acceptance is not None and not isinstance(
            self.acceptance, ReviewerAcceptance
        ):
            if isinstance(self.acceptance, Mapping):
                object.__setattr__(
                    self, "acceptance", ReviewerAcceptance.from_dict(self.acceptance)
                )
            else:
                raise TypeError("acceptance must be ReviewerAcceptance, mapping, or None")
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_CLAIM_SEARCH_PLAN:
            raise ValueError(
                f"ClaimSearchPlan.output_kind must be {OUTPUT_KIND_CLAIM_SEARCH_PLAN!r}"
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
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "ClaimSearchPlan")

        # Cross-field integrity.
        _assert_plan_bindings(self)
        assert_no_patentability_conclusions(self.to_dict())
        assert_no_invented_dates(self.to_dict())

        if self.invalidated and self.execution_state is PlanExecutionState.EXECUTABLE:
            raise StalePlanError("invalidated plans cannot be executable")
        if (
            self.execution_state is PlanExecutionState.EXECUTABLE
            and self.acceptance is None
        ):
            raise UnreviewedCandidateError(
                "executable plans require reviewer acceptance"
            )

    def plan_digest(self) -> str:
        """Content digest excluding acceptance/execution mutation fields."""
        payload = self.to_dict()
        payload.pop("acceptance", None)
        payload.pop("execution_state", None)
        payload.pop("invalidated", None)
        payload.pop("invalidation_reason", None)
        return content_digest(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance": None if self.acceptance is None else self.acceptance.to_dict(),
            "claim_version_digest": self.claim_version_digest,
            "claim_version_id": self.claim_version_id,
            "classifications": [c.to_dict() for c in self.classifications],
            "concepts": [c.to_dict() for c in self.concepts],
            "constructions": [c.to_dict() for c in self.constructions],
            "disclaimer": self.disclaimer,
            "execution_state": self.execution_state.value,
            "filters": None if self.filters is None else self.filters.to_dict(),
            "invalidated": self.invalidated,
            "invalidation_reason": self.invalidation_reason,
            "limitations": [lim.to_dict() for lim in self.limitations],
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "plan_id": self.plan_id,
            "queries": [q.to_dict() for q in self.queries],
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "synonyms": [s.to_dict() for s in self.synonyms],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimSearchPlan":
        value = _mapping(value, "ClaimSearchPlan")
        return cls(
            schema_version=value.get(
                "schema_version", CLAIM_SEARCH_PLANNER_SCHEMA_VERSION
            ),
            plan_id=value.get("plan_id", ""),
            subject_id=value.get("subject_id", ""),
            claim_version_id=value.get("claim_version_id", ""),
            claim_version_digest=value.get("claim_version_digest", ""),
            limitations=tuple(value.get("limitations") or ()),
            queries=tuple(value.get("queries") or ()),
            constructions=tuple(value.get("constructions") or ()),
            synonyms=tuple(value.get("synonyms") or ()),
            concepts=tuple(value.get("concepts") or ()),
            classifications=tuple(value.get("classifications") or ()),
            filters=value.get("filters"),
            execution_state=value.get(
                "execution_state", PlanExecutionState.REVIEW_REQUIRED.value
            ),
            invalidated=bool(value.get("invalidated", False)),
            invalidation_reason=value.get("invalidation_reason"),
            acceptance=value.get("acceptance"),
            output_kind=value.get("output_kind", OUTPUT_KIND_CLAIM_SEARCH_PLAN),
            disclaimer=value.get("disclaimer", CLAIM_SEARCH_PLANNER_DISCLAIMER),
            ruleset_version=value.get(
                "ruleset_version", CLAIM_SEARCH_PLANNER_RULESET_VERSION
            ),
            metadata=value.get("metadata") or {},
        )


def _coerce_sequence(
    value: Any,
    cls: type[Any],
    field: str,
    *,
    max_items: int,
) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[Any] = []
    for i, item in enumerate(value):
        if isinstance(item, cls):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(cls.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be {cls.__name__} or mapping")
    return tuple(out)


def _assert_plan_bindings(plan: ClaimSearchPlan) -> None:
    """Every limitation and query must bind to the plan claim version and spans."""
    vid = plan.claim_version_id
    digest = plan.claim_version_digest
    lim_ids = {lim.limitation_id for lim in plan.limitations}
    for lim in plan.limitations:
        if lim.claim_version_id != vid or lim.claim_version_digest != digest:
            raise ClaimVersionMismatchError(
                f"limitation {lim.limitation_id} claim version binding mismatch"
            )
        if lim.claim_span.end <= lim.claim_span.start:
            raise ClaimSpanError(f"limitation {lim.limitation_id} has empty claim span")
    for query in plan.queries:
        if query.claim_version_id != vid or query.claim_version_digest != digest:
            raise ClaimVersionMismatchError(
                f"query {query.query_id} claim version binding mismatch"
            )
        if not query.claim_spans:
            raise ClaimSpanError(f"query {query.query_id} missing claim spans")
        for rid in query.related_limitation_ids:
            if rid not in lim_ids:
                raise OmittedLimitationError(
                    f"query {query.query_id} references unknown limitation {rid}"
                )
    for group in (
        plan.synonyms,
        plan.concepts,
        plan.classifications,
        plan.constructions,
    ):
        for item in group:
            item_vid = getattr(item, "claim_version_id")
            item_digest = getattr(item, "claim_version_digest")
            if item_vid != vid or item_digest != digest:
                raise ClaimVersionMismatchError(
                    f"{type(item).__name__} claim version binding mismatch"
                )


# ---------------------------------------------------------------------------
# Decomposition / candidate builders
# ---------------------------------------------------------------------------


def decompose_limitations(
    claim_version: ClaimVersion,
    *,
    max_limitations: int = DEFAULT_MAX_LIMITATIONS,
) -> tuple[LimitationCandidate, ...]:
    """Deterministically decompose versioned claims into atomic limitations.

    Every limitation carries exact char span into the claim text and the claim
    version id/digest. All outputs are candidates.
    """
    limitations: list[LimitationCandidate] = []
    global_ordinal = 0
    for claim in claim_version.claims:
        text = claim.claim_text
        cleaned = re.sub(r"^\s*\d+\.\s*", "", text).strip()
        parts = [
            p.strip(" .")
            for p in _LIMITATION_SPLIT_RE.split(cleaned)
            if p and p.strip()
        ]
        if not parts:
            parts = [cleaned or text]
        offset = 0
        for local_ordinal, part in enumerate(parts, start=1):
            if not part:
                continue
            global_ordinal += 1
            if global_ordinal > max_limitations:
                break
            idx = text.find(part, offset)
            if idx < 0:
                # Fall back to cleaned-text coordinates if prefix strip shifted.
                idx = text.find(part)
            if idx < 0:
                idx = offset
            span = SourceSpan(start=idx, end=idx + len(part), unit="char")
            # Verify span text matches.
            if text[span.start : span.end] != part:
                # Align by re-search whole text once more for exact match.
                exact = text.find(part)
                if exact >= 0:
                    span = SourceSpan(start=exact, end=exact + len(part), unit="char")
            offset = span.end
            limitations.append(
                LimitationCandidate(
                    limitation_id=f"lim:v{claim_version.version}:c{claim.claim_number}-{local_ordinal}",
                    claim_version_id=claim_version.claim_version_id,
                    claim_version_digest=claim_version.content_sha256,
                    claim_number=claim.claim_number,
                    text=part,
                    claim_span=span,
                    ordinal=local_ordinal,
                    origin=CandidateOrigin.DETERMINISTIC_SPLIT,
                    confidence=DEFAULT_DETERMINISTIC_CONFIDENCE,
                    review_status=ReviewStatus.CANDIDATE,
                    is_candidate=True,
                    metadata={"generator": "deterministic_split"},
                )
            )
        if global_ordinal >= max_limitations:
            break
    if not limitations:
        raise ClaimSearchPlannerError("decomposition produced no limitations")
    return tuple(limitations)


def detect_ambiguous_constructions(
    claim_version: ClaimVersion,
    limitations: Sequence[LimitationCandidate],
) -> tuple[ConstructionAlternative, ...]:
    """Detect ambiguous constructions; leave them as alternatives."""
    constructions: list[ConstructionAlternative] = []
    n = 0
    for lim in limitations:
        if lim.claim_version_id != claim_version.claim_version_id:
            continue
        text = lim.text
        readings: list[str] = []
        if _AMBIGUOUS_OR_RE.search(text):
            # Split simple "A or B" style phrases into alternative readings.
            or_parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
            if len(or_parts) >= 2:
                readings = [p.strip(" ,;.") for p in or_parts if p.strip()]
            if "and/or" in text.lower():
                readings = list(
                    dict.fromkeys(
                        readings
                        + [
                            text.replace("and/or", "and"),
                            text.replace("and/or", "or"),
                        ]
                    )
                )
        if _MEANS_PLUS_FUNCTION_RE.search(text):
            readings = list(
                dict.fromkeys(
                    readings
                    + [
                        text,
                        re.sub(
                            r"\bmeans\s+for\b",
                            "structure that performs",
                            text,
                            flags=re.IGNORECASE,
                        ),
                    ]
                )
            )
        # Deduplicate and require ≥2 distinct readings.
        unique = tuple(dict.fromkeys(r for r in readings if r))
        if len(unique) < 2:
            continue
        n += 1
        if n > DEFAULT_MAX_CONSTRUCTIONS:
            break
        constructions.append(
            ConstructionAlternative(
                construction_id=f"const:{lim.limitation_id}",
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                claim_number=lim.claim_number,
                claim_span=lim.claim_span,
                source_text=text,
                readings=unique[:8],
                origin=CandidateOrigin.DETERMINISTIC_SPLIT,
                confidence=DEFAULT_DETERMINISTIC_CONFIDENCE,
                remains_alternative=True,
                selected_reading=None,
                review_status=ReviewStatus.ALTERNATIVE,
                related_limitation_ids=(lim.limitation_id,),
                metadata={"detector": "ambiguous_or_or_means"},
            )
        )
    return tuple(constructions)


def propose_synonyms(
    claim_version: ClaimVersion,
    limitations: Sequence[LimitationCandidate],
    *,
    max_synonyms: int = DEFAULT_MAX_SYNONYMS,
) -> tuple[SynonymCandidate, ...]:
    """Propose synonym candidates from a deterministic table (not legal synonymy)."""
    out: list[SynonymCandidate] = []
    n = 0
    for lim in limitations:
        tokens = [t.lower() for t in _TOKEN_RE.findall(lim.text)]
        for token in tokens:
            if token in _STOPWORDS:
                continue
            for syn in _SYNONYM_TABLE.get(token, ()):
                n += 1
                if n > max_synonyms:
                    return tuple(out)
                out.append(
                    SynonymCandidate(
                        synonym_id=(
                            f"syn:{lim.limitation_id}:"
                            f"{_slug_id_fragment(token)}:{_slug_id_fragment(syn)}"
                        ),
                        term=token,
                        synonym=syn,
                        claim_version_id=claim_version.claim_version_id,
                        claim_version_digest=claim_version.content_sha256,
                        related_limitation_ids=(lim.limitation_id,),
                        claim_spans=(lim.claim_span,),
                        origin=CandidateOrigin.SYNONYM_EXPAND,
                        confidence=DEFAULT_SYNONYM_CONFIDENCE,
                        review_status=ReviewStatus.CANDIDATE,
                        is_candidate=True,
                        metadata={"generator": "synonym_table"},
                    )
                )
    return tuple(out)


def propose_concepts(
    claim_version: ClaimVersion,
    limitations: Sequence[LimitationCandidate],
    *,
    max_concepts: int = DEFAULT_MAX_CONCEPTS,
) -> tuple[ConceptCandidate, ...]:
    """Extract concept token candidates from limitation text."""
    out: list[ConceptCandidate] = []
    seen: set[str] = set()
    n = 0
    for lim in limitations:
        for token in _TOKEN_RE.findall(lim.text):
            concept = token.lower()
            if concept in _STOPWORDS or len(concept) < 3:
                continue
            key = f"{lim.limitation_id}:{concept}"
            if key in seen:
                continue
            seen.add(key)
            n += 1
            if n > max_concepts:
                return tuple(out)
            out.append(
                ConceptCandidate(
                    concept_id=f"concept:{lim.limitation_id}:{concept}",
                    concept=concept,
                    claim_version_id=claim_version.claim_version_id,
                    claim_version_digest=claim_version.content_sha256,
                    related_limitation_ids=(lim.limitation_id,),
                    claim_spans=(lim.claim_span,),
                    origin=CandidateOrigin.CONCEPT_EXTRACT,
                    confidence=DEFAULT_CONCEPT_CONFIDENCE,
                    review_status=ReviewStatus.CANDIDATE,
                    is_candidate=True,
                    metadata={"generator": "token_extract"},
                )
            )
    return tuple(out)


def propose_classifications(
    claim_version: ClaimVersion,
    limitations: Sequence[LimitationCandidate],
    *,
    seed_codes: Sequence[str] = (),
    max_classifications: int = DEFAULT_MAX_CLASSIFICATIONS,
) -> tuple[ClassificationCandidate, ...]:
    """Propose CPC/IPC candidates from claim text and user-supplied seed codes."""
    out: list[ClassificationCandidate] = []
    seen: set[str] = set()
    n = 0

    def _add(
        code: str,
        *,
        lim: LimitationCandidate | None,
        origin: CandidateOrigin,
        confidence: float,
    ) -> None:
        nonlocal n
        normalized = re.sub(r"\s+", "", code).upper()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        n += 1
        if n > max_classifications:
            return
        scheme = ClassificationScheme.CPC
        spans = (lim.claim_span,) if lim is not None else (
            limitations[0].claim_span if limitations else SourceSpan(start=0, end=1)
        )
        related = (lim.limitation_id,) if lim is not None else tuple(
            x.limitation_id for x in limitations[:1]
        )
        if not related and limitations:
            related = (limitations[0].limitation_id,)
        if not related:
            return
        out.append(
            ClassificationCandidate(
                classification_id=f"cls:{normalized}",
                code=normalized,
                scheme=scheme,
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                related_limitation_ids=related,
                claim_spans=spans if isinstance(spans, tuple) else (spans,),
                origin=origin,
                confidence=confidence,
                review_status=ReviewStatus.CANDIDATE,
                is_candidate=True,
                metadata={"generator": "classification_hint"},
            )
        )

    for lim in limitations:
        for match in _CPC_IPC_RE.findall(lim.text):
            _add(
                match,
                lim=lim,
                origin=CandidateOrigin.CLASSIFICATION_HINT,
                confidence=DEFAULT_CLASSIFICATION_CONFIDENCE,
            )
            if n >= max_classifications:
                return tuple(out)

    for code in seed_codes:
        if str(code).strip():
            _add(
                str(code),
                lim=limitations[0] if limitations else None,
                origin=CandidateOrigin.HUMAN_SUPPLIED,
                confidence=0.85,
            )
            if n >= max_classifications:
                break
    return tuple(out)


def build_planned_queries(
    claim_version: ClaimVersion,
    limitations: Sequence[LimitationCandidate],
    *,
    synonyms: Sequence[SynonymCandidate] = (),
    concepts: Sequence[ConceptCandidate] = (),
    classifications: Sequence[ClassificationCandidate] = (),
    constructions: Sequence[ConstructionAlternative] = (),
    filters: SearchFilterSpec | None = None,
    rank_cutoff: int = DEFAULT_RANK_CUTOFF,
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> tuple[PlannedQuery, ...]:
    """Build query families mapped to exact claim spans and version."""
    queries: list[PlannedQuery] = []
    qn = 0

    def _append(query: PlannedQuery) -> None:
        nonlocal qn
        if len(queries) >= max_queries:
            return
        queries.append(query)

    for lim in limitations:
        qn += 1
        _append(
            PlannedQuery(
                query_id=f"q-lim-{qn}",
                query_text=lim.text,
                family=QueryFamily.CLAIM_LIMITATION,
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                claim_spans=(lim.claim_span,),
                related_limitation_ids=(lim.limitation_id,),
                origin=CandidateOrigin.QUERY_FAMILY,
                confidence=lim.confidence,
                review_status=ReviewStatus.CANDIDATE,
                is_candidate=True,
                keywords=tuple(
                    t.lower()
                    for t in _TOKEN_RE.findall(lim.text)
                    if t.lower() not in _STOPWORDS
                )[:12],
                rank_cutoff=rank_cutoff,
                filters=filters,
                metadata={"source": "limitation_candidate"},
            )
        )

    # Concept queries (batch per limitation top concepts).
    concepts_by_lim: dict[str, list[ConceptCandidate]] = {}
    for c in concepts:
        for rid in c.related_limitation_ids:
            concepts_by_lim.setdefault(rid, []).append(c)
    for lim in limitations:
        group = concepts_by_lim.get(lim.limitation_id, [])[:6]
        if not group:
            continue
        qn += 1
        _append(
            PlannedQuery(
                query_id=f"q-concept-{qn}",
                query_text=" ".join(c.concept for c in group),
                family=QueryFamily.CONCEPT,
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                claim_spans=(lim.claim_span,),
                related_limitation_ids=(lim.limitation_id,),
                origin=CandidateOrigin.CONCEPT_EXTRACT,
                confidence=DEFAULT_CONCEPT_CONFIDENCE,
                review_status=ReviewStatus.CANDIDATE,
                is_candidate=True,
                keywords=tuple(c.concept for c in group),
                rank_cutoff=rank_cutoff,
                filters=filters,
                metadata={"source": "concept_candidates"},
            )
        )

    # Synonym queries.
    for syn in synonyms[:24]:
        qn += 1
        _append(
            PlannedQuery(
                query_id=f"q-syn-{qn}",
                query_text=f"{syn.term} OR {syn.synonym}",
                family=QueryFamily.SYNONYM,
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                claim_spans=syn.claim_spans,
                related_limitation_ids=syn.related_limitation_ids,
                origin=CandidateOrigin.SYNONYM_EXPAND,
                confidence=syn.confidence,
                review_status=ReviewStatus.CANDIDATE,
                is_candidate=True,
                keywords=(syn.term, syn.synonym),
                rank_cutoff=rank_cutoff,
                filters=filters,
                metadata={"source": "synonym_candidate", "synonym_id": syn.synonym_id},
            )
        )

    # Classification queries.
    for cls in classifications:
        qn += 1
        family = (
            QueryFamily.CLASSIFICATION_IPC
            if cls.scheme is ClassificationScheme.IPC
            else QueryFamily.CLASSIFICATION_CPC
        )
        _append(
            PlannedQuery(
                query_id=f"q-class-{qn}",
                query_text=cls.code,
                family=family,
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                claim_spans=cls.claim_spans,
                related_limitation_ids=cls.related_limitation_ids,
                origin=cls.origin,
                confidence=cls.confidence,
                review_status=ReviewStatus.CANDIDATE,
                is_candidate=True,
                classification_codes=(cls.code,),
                rank_cutoff=rank_cutoff,
                filters=filters,
                metadata={"source": "classification_candidate"},
            )
        )

    # Construction alternative queries (still alternatives / candidates).
    for const in constructions:
        for reading in const.readings:
            qn += 1
            _append(
                PlannedQuery(
                    query_id=f"q-const-{qn}",
                    query_text=reading,
                    family=QueryFamily.CONSTRUCTION_ALTERNATIVE,
                    claim_version_id=claim_version.claim_version_id,
                    claim_version_digest=claim_version.content_sha256,
                    claim_spans=(const.claim_span,),
                    related_limitation_ids=const.related_limitation_ids,
                    origin=CandidateOrigin.QUERY_FAMILY,
                    confidence=const.confidence,
                    review_status=ReviewStatus.ALTERNATIVE,
                    is_candidate=True,
                    rank_cutoff=rank_cutoff,
                    filters=filters,
                    metadata={
                        "source": "construction_alternative",
                        "construction_id": const.construction_id,
                    },
                )
            )

    if not queries:
        raise ClaimSearchPlannerError("no queries could be planned from limitations")
    return tuple(queries[:max_queries])


def build_claim_search_plan(
    *,
    claim_version: ClaimVersion,
    filing_date: str,
    priority_date: str,
    search_date_utc: str,
    jurisdictions: Sequence[str] = ("US",),
    classifications: Sequence[str] = (),
    plan_id: str | None = None,
    rank_cutoff: int = DEFAULT_RANK_CUTOFF,
    corpus_cutoff: str | None = None,
    metadata: Mapping[str, str] | None = None,
    model_candidates: Sequence[Mapping[str, Any]] = (),
) -> ClaimSearchPlan:
    """Build a draft claim-search plan from a versioned claim set.

    Dates and jurisdictions are mandatory user inputs. Model candidates are
    admitted only as unreviewed candidates with MODEL_PROPOSAL origin.
    """
    if not filing_date or not priority_date or not search_date_utc:
        raise MissingTemporalAnchorError(
            "filing_date, priority_date, and search_date_utc are required user inputs"
        )
    filters = SearchFilterSpec(
        jurisdictions=tuple(jurisdictions) if jurisdictions else ("US",),
        filing_date=filing_date,
        priority_date=priority_date,
        search_date_utc=search_date_utc,
        corpus_cutoff=corpus_cutoff or search_date_utc[:10],
    )
    limitations = list(decompose_limitations(claim_version))
    # Admit model candidates without promotion.
    for i, raw in enumerate(model_candidates):
        if not isinstance(raw, Mapping):
            raise TypeError(f"model_candidates[{i}] must be a mapping")
        text = _require_str(raw.get("text"), f"model_candidates[{i}].text", max_len=20_000)
        claim_number = _positive_int(
            int(raw.get("claim_number") or 1), f"model_candidates[{i}].claim_number"
        )
        claim = claim_version.claim_by_number(claim_number)
        idx = claim.claim_text.find(text)
        if idx < 0:
            # Model candidates still need a span; refuse free-floating text that
            # cannot be located in the claim (fail closed on invented spans).
            raise ClaimSpanError(
                f"model candidate text not found in claim {claim_number}; "
                "cannot invent claim spans"
            )
        span = SourceSpan(start=idx, end=idx + len(text), unit="char")
        conf = float(
            raw.get("confidence")
            if raw.get("confidence") is not None
            else DEFAULT_MODEL_CANDIDATE_CONFIDENCE
        )
        limitations.append(
            LimitationCandidate(
                limitation_id=f"lim:model:{claim_number}:{i+1}",
                claim_version_id=claim_version.claim_version_id,
                claim_version_digest=claim_version.content_sha256,
                claim_number=claim_number,
                text=text,
                claim_span=span,
                ordinal=1000 + i,
                origin=CandidateOrigin.MODEL_PROPOSAL,
                confidence=conf,
                review_status=ReviewStatus.CANDIDATE,
                is_candidate=True,
                metadata={"generator": "model_proposal"},
            )
        )

    lim_tuple = tuple(limitations)
    constructions = detect_ambiguous_constructions(claim_version, lim_tuple)
    synonyms = propose_synonyms(claim_version, lim_tuple)
    concepts = propose_concepts(claim_version, lim_tuple)
    class_cands = propose_classifications(
        claim_version, lim_tuple, seed_codes=classifications
    )
    queries = build_planned_queries(
        claim_version,
        lim_tuple,
        synonyms=synonyms,
        concepts=concepts,
        classifications=class_cands,
        constructions=constructions,
        filters=filters,
        rank_cutoff=rank_cutoff,
    )

    identity = {
        "claim_version_digest": claim_version.content_sha256,
        "claim_version_id": claim_version.claim_version_id,
        "filing_date": filing_date,
        "priority_date": priority_date,
        "search_date_utc": search_date_utc,
        "subject_id": claim_version.subject_id,
    }
    digest = content_digest(identity)[:16]
    resolved_plan_id = plan_id or f"plan:claim-search:{digest}"

    plan = ClaimSearchPlan(
        schema_version=CLAIM_SEARCH_PLANNER_SCHEMA_VERSION,
        plan_id=resolved_plan_id,
        subject_id=claim_version.subject_id,
        claim_version_id=claim_version.claim_version_id,
        claim_version_digest=claim_version.content_sha256,
        limitations=lim_tuple,
        queries=queries,
        constructions=constructions,
        synonyms=synonyms,
        concepts=concepts,
        classifications=class_cands,
        filters=filters,
        execution_state=PlanExecutionState.REVIEW_REQUIRED,
        invalidated=False,
        metadata=metadata or {},
    )
    assert_limitations_cover_claims(plan, claim_version)
    return plan


# ---------------------------------------------------------------------------
# Coverage / negative guards / amendment invalidation / acceptance
# ---------------------------------------------------------------------------


def assert_limitations_cover_claims(
    plan: ClaimSearchPlan,
    claim_version: ClaimVersion,
    *,
    min_coverage_ratio: float = 0.5,
) -> None:
    """Ensure limitations cover substantial claim text; fail on omitted coverage.

    Requires every claim to have ≥1 limitation whose span is inside the claim
    text, and that union coverage meets ``min_coverage_ratio`` of non-space
    claim characters (deterministic floor against silent omission).
    """
    if plan.claim_version_id != claim_version.claim_version_id:
        raise ClaimVersionMismatchError("plan/claim_version id mismatch")
    if plan.claim_version_digest != claim_version.content_sha256:
        raise ClaimVersionMismatchError("plan/claim_version digest mismatch")

    lims_by_claim: dict[int, list[LimitationCandidate]] = {}
    for lim in plan.limitations:
        lims_by_claim.setdefault(lim.claim_number, []).append(lim)

    for claim in claim_version.claims:
        claim_lims = lims_by_claim.get(claim.claim_number, [])
        if not claim_lims:
            raise OmittedLimitationError(
                f"claim {claim.claim_number} has no limitations in the plan"
            )
        text = claim.claim_text
        covered = [False] * len(text)
        for lim in claim_lims:
            span = lim.claim_span
            if span.start >= len(text) or span.end > len(text):
                raise ClaimSpanError(
                    f"limitation {lim.limitation_id} span out of bounds for claim "
                    f"{claim.claim_number}"
                )
            excerpt = text[span.start : span.end]
            if excerpt != lim.text and lim.text not in text:
                raise ClaimSpanError(
                    f"limitation {lim.limitation_id} text does not match claim span"
                )
            for i in range(span.start, span.end):
                covered[i] = True
        nonspace = [i for i, ch in enumerate(text) if not ch.isspace()]
        if not nonspace:
            continue
        hit = sum(1 for i in nonspace if covered[i])
        ratio = hit / len(nonspace)
        if ratio + 1e-9 < min_coverage_ratio:
            raise OmittedLimitationError(
                f"claim {claim.claim_number} limitation coverage {ratio:.2f} "
                f"below required {min_coverage_ratio:.2f}"
            )


def assert_candidates_not_promoted(plan: ClaimSearchPlan) -> None:
    """Negative guard: unreviewed candidates must not be marked accepted/executable."""
    if plan.execution_state is PlanExecutionState.EXECUTABLE and plan.acceptance is None:
        raise UnreviewedCandidateError("executable without acceptance")
    for lim in plan.limitations:
        if lim.review_status is ReviewStatus.ACCEPTED and lim.is_candidate:
            raise UnreviewedCandidateError(
                f"limitation {lim.limitation_id} marked accepted but still candidate"
            )
        if (
            lim.review_status is ReviewStatus.ACCEPTED
            and plan.acceptance is None
            and not plan.invalidated
        ):
            raise UnreviewedCandidateError(
                f"limitation {lim.limitation_id} accepted without plan acceptance record"
            )
    for query in plan.queries:
        if query.review_status is ReviewStatus.ACCEPTED and query.is_candidate:
            raise UnreviewedCandidateError(
                f"query {query.query_id} marked accepted but still candidate"
            )
        if (
            query.review_status is ReviewStatus.ACCEPTED
            and plan.acceptance is None
            and not plan.invalidated
        ):
            raise UnreviewedCandidateError(
                f"query {query.query_id} accepted without plan acceptance record"
            )
    for const in plan.constructions:
        if not const.remains_alternative and const.selected_reading is None:
            raise UnreviewedCandidateError(
                f"construction {const.construction_id} collapsed without selection"
            )
        if (
            const.selected_reading is not None
            and const.review_status is not ReviewStatus.ACCEPTED
        ):
            raise UnreviewedCandidateError(
                f"construction {const.construction_id} selected without acceptance"
            )


def is_plan_stale(plan: ClaimSearchPlan, current: ClaimVersion) -> bool:
    """True when the plan is bound to a superseded claim version digest."""
    if plan.invalidated:
        return True
    if plan.claim_version_id != current.claim_version_id:
        return True
    if plan.claim_version_digest != current.content_sha256:
        return True
    return False


def invalidate_plan_if_amended(
    plan: ClaimSearchPlan,
    current: ClaimVersion,
    *,
    reason: str | None = None,
) -> ClaimSearchPlan:
    """Return a plan marked invalidated when claim version no longer matches.

    Amendments produce a new ClaimVersion; any prior plan bound to the old
    digest becomes non-executable.
    """
    if not is_plan_stale(plan, current):
        return plan
    reason_s = reason or (
        f"claim version amended: plan bound to "
        f"{plan.claim_version_id}/{plan.claim_version_digest[:12]}… "
        f"current is {current.claim_version_id}/{current.content_sha256[:12]}…"
    )
    return ClaimSearchPlan(
        schema_version=plan.schema_version,
        plan_id=plan.plan_id,
        subject_id=plan.subject_id,
        claim_version_id=plan.claim_version_id,
        claim_version_digest=plan.claim_version_digest,
        limitations=plan.limitations,
        queries=plan.queries,
        constructions=plan.constructions,
        synonyms=plan.synonyms,
        concepts=plan.concepts,
        classifications=plan.classifications,
        filters=plan.filters,
        execution_state=PlanExecutionState.INVALIDATED,
        invalidated=True,
        invalidation_reason=reason_s,
        acceptance=None,
        output_kind=plan.output_kind,
        disclaimer=plan.disclaimer,
        ruleset_version=plan.ruleset_version,
        metadata=dict(plan.metadata),
    )


def apply_reviewer_acceptance(
    plan: ClaimSearchPlan,
    *,
    reviewer_id: str,
    accepted_at_utc: str,
    accepted_limitation_ids: Sequence[str] | None = None,
    accepted_query_ids: Sequence[str] | None = None,
    selected_constructions: Mapping[str, str] | None = None,
    accepted_synonym_ids: Sequence[str] | None = None,
    accepted_concept_ids: Sequence[str] | None = None,
    accepted_classification_ids: Sequence[str] | None = None,
    current_claim_version: ClaimVersion | None = None,
    acceptance_id: str | None = None,
) -> ClaimSearchPlan:
    """Promote selected candidates only after explicit reviewer acceptance.

    If ``current_claim_version`` is provided and does not match the plan
    binding, raises :class:`StalePlanError` instead of accepting.
    """
    if plan.invalidated:
        raise StalePlanError("cannot accept an invalidated plan")
    if current_claim_version is not None and is_plan_stale(plan, current_claim_version):
        raise StalePlanError(
            "cannot accept plan against amended claim version; rebuild the plan"
        )
    if plan.filters is None:
        raise MissingTemporalAnchorError(
            "plan filters with user-supplied dates are required for acceptance"
        )
    if not (
        plan.filters.filing_date
        and plan.filters.priority_date
        and plan.filters.search_date_utc
    ):
        raise MissingTemporalAnchorError(
            "filing_date, priority_date, and search_date_utc required for acceptance"
        )

    lim_ids = {lim.limitation_id for lim in plan.limitations}
    query_ids = {q.query_id for q in plan.queries}
    accepted_lims = tuple(
        accepted_limitation_ids
        if accepted_limitation_ids is not None
        else sorted(lim_ids)
    )
    accepted_qs = tuple(
        accepted_query_ids if accepted_query_ids is not None else sorted(query_ids)
    )
    for lid in accepted_lims:
        if lid not in lim_ids:
            raise OmittedLimitationError(f"acceptance references unknown limitation {lid}")
    for qid in accepted_qs:
        if qid not in query_ids:
            raise ClaimSearchPlannerError(f"acceptance references unknown query {qid}")
    if not accepted_lims or not accepted_qs:
        raise UnreviewedCandidateError("acceptance must cover ≥1 limitation and ≥1 query")

    selections = dict(selected_constructions or {})
    const_ids = {c.construction_id: c for c in plan.constructions}
    for cid, reading in selections.items():
        if cid not in const_ids:
            raise ClaimSearchPlannerError(f"unknown construction {cid}")
        if reading not in const_ids[cid].readings:
            raise ClaimSearchPlannerError(
                f"selected reading not among alternatives for {cid}"
            )

    # Unselected constructions remain alternatives.
    new_constructions: list[ConstructionAlternative] = []
    for const in plan.constructions:
        if const.construction_id in selections:
            new_constructions.append(
                ConstructionAlternative(
                    construction_id=const.construction_id,
                    claim_version_id=const.claim_version_id,
                    claim_version_digest=const.claim_version_digest,
                    claim_number=const.claim_number,
                    claim_span=const.claim_span,
                    source_text=const.source_text,
                    readings=const.readings,
                    origin=const.origin,
                    confidence=const.confidence,
                    remains_alternative=False,
                    selected_reading=selections[const.construction_id],
                    review_status=ReviewStatus.ACCEPTED,
                    related_limitation_ids=const.related_limitation_ids,
                    metadata=dict(const.metadata),
                )
            )
        else:
            # Keep as alternative — do not collapse.
            new_constructions.append(const)

    accepted_lim_set = set(accepted_lims)
    new_limitations = tuple(
        LimitationCandidate(
            limitation_id=lim.limitation_id,
            claim_version_id=lim.claim_version_id,
            claim_version_digest=lim.claim_version_digest,
            claim_number=lim.claim_number,
            text=lim.text,
            claim_span=lim.claim_span,
            ordinal=lim.ordinal,
            origin=lim.origin,
            confidence=lim.confidence,
            review_status=(
                ReviewStatus.ACCEPTED
                if lim.limitation_id in accepted_lim_set
                else lim.review_status
            ),
            is_candidate=lim.limitation_id not in accepted_lim_set,
            construction_group_id=lim.construction_group_id,
            metadata=dict(lim.metadata),
        )
        for lim in plan.limitations
    )

    accepted_q_set = set(accepted_qs)
    new_queries = tuple(
        PlannedQuery(
            query_id=q.query_id,
            query_text=q.query_text,
            family=q.family,
            claim_version_id=q.claim_version_id,
            claim_version_digest=q.claim_version_digest,
            claim_spans=q.claim_spans,
            related_limitation_ids=q.related_limitation_ids,
            origin=q.origin,
            confidence=q.confidence,
            review_status=(
                ReviewStatus.ACCEPTED
                if q.query_id in accepted_q_set
                else q.review_status
            ),
            is_candidate=q.query_id not in accepted_q_set,
            classification_codes=q.classification_codes,
            keywords=q.keywords,
            rank_cutoff=q.rank_cutoff,
            filters=q.filters,
            metadata=dict(q.metadata),
        )
        for q in plan.queries
    )

    syn_set = set(accepted_synonym_ids or ())
    new_synonyms = tuple(
        SynonymCandidate(
            synonym_id=s.synonym_id,
            term=s.term,
            synonym=s.synonym,
            claim_version_id=s.claim_version_id,
            claim_version_digest=s.claim_version_digest,
            related_limitation_ids=s.related_limitation_ids,
            claim_spans=s.claim_spans,
            origin=s.origin,
            confidence=s.confidence,
            review_status=(
                ReviewStatus.ACCEPTED if s.synonym_id in syn_set else s.review_status
            ),
            is_candidate=s.synonym_id not in syn_set,
            metadata=dict(s.metadata),
        )
        for s in plan.synonyms
    )
    concept_set = set(accepted_concept_ids or ())
    new_concepts = tuple(
        ConceptCandidate(
            concept_id=c.concept_id,
            concept=c.concept,
            claim_version_id=c.claim_version_id,
            claim_version_digest=c.claim_version_digest,
            related_limitation_ids=c.related_limitation_ids,
            claim_spans=c.claim_spans,
            origin=c.origin,
            confidence=c.confidence,
            review_status=(
                ReviewStatus.ACCEPTED if c.concept_id in concept_set else c.review_status
            ),
            is_candidate=c.concept_id not in concept_set,
            metadata=dict(c.metadata),
        )
        for c in plan.concepts
    )
    cls_set = set(accepted_classification_ids or ())
    new_classifications = tuple(
        ClassificationCandidate(
            classification_id=c.classification_id,
            code=c.code,
            scheme=c.scheme,
            claim_version_id=c.claim_version_id,
            claim_version_digest=c.claim_version_digest,
            related_limitation_ids=c.related_limitation_ids,
            claim_spans=c.claim_spans,
            origin=c.origin,
            confidence=c.confidence,
            review_status=(
                ReviewStatus.ACCEPTED
                if c.classification_id in cls_set
                else c.review_status
            ),
            is_candidate=c.classification_id not in cls_set,
            metadata=dict(c.metadata),
        )
        for c in plan.classifications
    )

    # Build interim plan for digest (without acceptance).
    interim = ClaimSearchPlan(
        schema_version=plan.schema_version,
        plan_id=plan.plan_id,
        subject_id=plan.subject_id,
        claim_version_id=plan.claim_version_id,
        claim_version_digest=plan.claim_version_digest,
        limitations=new_limitations,
        queries=new_queries,
        constructions=tuple(new_constructions),
        synonyms=new_synonyms,
        concepts=new_concepts,
        classifications=new_classifications,
        filters=plan.filters,
        execution_state=PlanExecutionState.ACCEPTED,
        invalidated=False,
        acceptance=None,
        output_kind=plan.output_kind,
        disclaimer=plan.disclaimer,
        ruleset_version=plan.ruleset_version,
        metadata=dict(plan.metadata),
    )
    plan_digest = interim.plan_digest()
    acceptance = ReviewerAcceptance(
        acceptance_id=acceptance_id
        or f"accept:{plan.plan_id}:{content_digest({'r': reviewer_id, 't': accepted_at_utc})[:12]}",
        plan_id=plan.plan_id,
        claim_version_id=plan.claim_version_id,
        claim_version_digest=plan.claim_version_digest,
        plan_digest=plan_digest,
        reviewer_id=reviewer_id,
        accepted_at_utc=accepted_at_utc,
        accepted_limitation_ids=accepted_lims,
        accepted_query_ids=accepted_qs,
        selected_constructions=selections,
        accepted_synonym_ids=tuple(syn_set),
        accepted_concept_ids=tuple(concept_set),
        accepted_classification_ids=tuple(cls_set),
    )
    accepted_plan = ClaimSearchPlan(
        schema_version=interim.schema_version,
        plan_id=interim.plan_id,
        subject_id=interim.subject_id,
        claim_version_id=interim.claim_version_id,
        claim_version_digest=interim.claim_version_digest,
        limitations=interim.limitations,
        queries=interim.queries,
        constructions=interim.constructions,
        synonyms=interim.synonyms,
        concepts=interim.concepts,
        classifications=interim.classifications,
        filters=interim.filters,
        execution_state=PlanExecutionState.EXECUTABLE,
        invalidated=False,
        acceptance=acceptance,
        output_kind=interim.output_kind,
        disclaimer=interim.disclaimer,
        ruleset_version=interim.ruleset_version,
        metadata=dict(interim.metadata),
    )
    assert_candidates_not_promoted(accepted_plan)
    return accepted_plan


def assert_plan_execution_ready(
    plan: ClaimSearchPlan,
    *,
    current_claim_version: ClaimVersion | None = None,
) -> None:
    """Fail closed unless plan is accepted, not stale, and dates are present."""
    if plan.invalidated or plan.execution_state is PlanExecutionState.INVALIDATED:
        raise StalePlanError(
            plan.invalidation_reason or "plan is invalidated by claim amendment"
        )
    if current_claim_version is not None and is_plan_stale(plan, current_claim_version):
        raise StalePlanError("plan is stale relative to current claim version")
    if plan.execution_state is not PlanExecutionState.EXECUTABLE:
        raise PlanNotExecutableError(
            f"plan execution_state is {plan.execution_state.value}, not executable"
        )
    if plan.acceptance is None:
        raise UnreviewedCandidateError("execution requires reviewer acceptance")
    if plan.acceptance.claim_version_digest != plan.claim_version_digest:
        raise ClaimVersionMismatchError(
            "acceptance claim_version_digest does not match plan"
        )
    if plan.filters is None or not (
        plan.filters.filing_date
        and plan.filters.priority_date
        and plan.filters.search_date_utc
    ):
        raise MissingTemporalAnchorError(
            "executable plan requires user-supplied filing/priority/search dates"
        )
    # Accepted limitations/queries must not still be candidates.
    accepted_lims = set(plan.acceptance.accepted_limitation_ids)
    for lim in plan.limitations:
        if lim.limitation_id in accepted_lims:
            if lim.is_candidate or lim.review_status is not ReviewStatus.ACCEPTED:
                raise UnreviewedCandidateError(
                    f"accepted limitation {lim.limitation_id} not fully promoted"
                )
    accepted_qs = set(plan.acceptance.accepted_query_ids)
    for query in plan.queries:
        if query.query_id in accepted_qs:
            if query.is_candidate or query.review_status is not ReviewStatus.ACCEPTED:
                raise UnreviewedCandidateError(
                    f"accepted query {query.query_id} not fully promoted"
                )
    assert_no_invented_dates(plan)
    assert_no_patentability_conclusions(plan)


def executable_queries(
    plan: ClaimSearchPlan,
    *,
    current_claim_version: ClaimVersion | None = None,
) -> tuple[PlannedQuery, ...]:
    """Return accepted queries only after execution-readiness checks pass."""
    assert_plan_execution_ready(plan, current_claim_version=current_claim_version)
    assert plan.acceptance is not None
    accepted = set(plan.acceptance.accepted_query_ids)
    return tuple(q for q in plan.queries if q.query_id in accepted)


def admit_model_candidate_limitation(
    claim_version: ClaimVersion,
    *,
    claim_number: int,
    text: str,
    confidence: float = DEFAULT_MODEL_CANDIDATE_CONFIDENCE,
    limitation_id: str | None = None,
) -> LimitationCandidate:
    """Admit a model-proposed limitation as an unreviewed candidate only.

    The text must occur in the claim (exact span); no invented spans.
    """
    claim = claim_version.claim_by_number(claim_number)
    idx = claim.claim_text.find(text)
    if idx < 0:
        raise ClaimSpanError(
            "model candidate text not found in claim; cannot invent claim spans"
        )
    return LimitationCandidate(
        limitation_id=limitation_id or f"lim:model:c{claim_number}:{text_sha256(text)[:10]}",
        claim_version_id=claim_version.claim_version_id,
        claim_version_digest=claim_version.content_sha256,
        claim_number=claim_number,
        text=text,
        claim_span=SourceSpan(start=idx, end=idx + len(text), unit="char"),
        ordinal=1,
        origin=CandidateOrigin.MODEL_PROPOSAL,
        confidence=confidence,
        review_status=ReviewStatus.CANDIDATE,
        is_candidate=True,
        metadata={"generator": "model_proposal"},
    )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "CLAIM_SEARCH_PLANNER_DISCLAIMER",
    "CLAIM_SEARCH_PLANNER_INTERFACE",
    "CLAIM_SEARCH_PLANNER_RULESET_VERSION",
    "CLAIM_SEARCH_PLANNER_SCHEMA_VERSION",
    "OUTPUT_KIND_CLAIM_SEARCH_PLAN",
    "OUTPUT_KIND_CLAIM_VERSION",
    "OUTPUT_KIND_REVIEWER_ACCEPTANCE",
    "CandidateOrigin",
    "ClaimKind",
    "ClaimSearchPlan",
    "ClaimSearchPlannerError",
    "ClaimSpanError",
    "ClaimVersion",
    "ClaimVersionMismatchError",
    "ClassificationCandidate",
    "ClassificationScheme",
    "ConceptCandidate",
    "ConstructionAlternative",
    "InventedDateError",
    "LimitationCandidate",
    "MissingTemporalAnchorError",
    "OmittedLimitationError",
    "PatentabilityConclusionError",
    "PlanExecutionState",
    "PlanNotExecutableError",
    "PlannedQuery",
    "QueryFamily",
    "ReviewStatus",
    "ReviewerAcceptance",
    "SearchFilterSpec",
    "StalePlanError",
    "SynonymCandidate",
    "UnreviewedCandidateError",
    "VersionedClaim",
    "admit_model_candidate_limitation",
    "apply_reviewer_acceptance",
    "assert_candidates_not_promoted",
    "assert_limitations_cover_claims",
    "assert_no_invented_dates",
    "assert_no_patentability_conclusions",
    "assert_plan_execution_ready",
    "build_claim_search_plan",
    "build_planned_queries",
    "canonical_json",
    "claim_set_content_sha256",
    "content_digest",
    "decompose_limitations",
    "detect_ambiguous_constructions",
    "executable_queries",
    "invalidate_plan_if_amended",
    "is_plan_stale",
    "propose_classifications",
    "propose_concepts",
    "propose_synonyms",
    "text_sha256",
    "version_claims",
]
