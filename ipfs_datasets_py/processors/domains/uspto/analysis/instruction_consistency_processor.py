"""Compare government instructions to applicable authority (PATLAW-045).

Produces a comparison packet for each instruction span:

```text
examiner/instruction span
  -> cited and independently resolved authority, exact version
  -> applicability facts and assumptions
  -> consistent / potential inconsistency / unknown
  -> counter-source spans and human-review question
```

Design invariants
-----------------
* A **potential inconsistency** is always reproducible from exact source
  spans and authority versions (instruction span + authority span/version).
* Competing authorities and unresolved uncertainty are **shown**, never
  collapsed into a silent pick.
* Model summaries are **never** substituted for government instruction text
  or governing authority text — only exact surfaces / digests / source
  excerpts appear.
* No output **declares unlawful conduct**. Status values are only
  ``consistent``, ``potential_inconsistency``, or ``unknown``. The module
  never emits a legality determination or an "examiner unlawful" label.
* Comparison owns instruction/authority reasoning only; source and proof
  records are immutable inputs.

Document body text is never written to logs or exception messages.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    GovernmentRequirement,
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    AnalysisCandidate,
    CandidateKind,
    OfficeActionResult,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    CompiledPredicate,
    RequirementCompilationResult,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    AuthoritySpan,
    AuthorityTextNode,
    PatentTemporalAuthorityGraph,
)
from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
    CitationMatchKind,
    CitationResolutionResult,
    PatentCitationResolver,
    QuoteComparison,
    QuoteMatchStatus,
    TextSpan,
    compare_quote_to_source,
    parse_patent_citations,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

INSTRUCTION_CONSISTENCY_SCHEMA_VERSION: Final = "uspto.instruction-consistency.v1"
INSTRUCTION_CONSISTENCY_INTERFACE: Final = "InstructionConsistencyProcessor@1"
INSTRUCTION_CONSISTENCY_RULESET_VERSION: Final = "instruction-consistency-rules@1"

OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON: Final = (
    "instruction_authority_comparison"
)

NOT_UNLAWFUL_DETERMINATION_DISCLAIMER: Final = (
    "This output is a review-only comparison of government instruction spans "
    "to independently resolved authority text at exact versions. It may flag "
    "a reproducible potential inconsistency for human review. It does not "
    "declare any person, examiner, or agency action unlawful, does not state "
    "a conclusive legal opinion, and is not a filing, docket, or compliance "
    "determination."
)

DEFAULT_MAX_COMPARISONS: Final = 4096
DEFAULT_MAX_SURFACE: Final = 8000
DEFAULT_MAX_EXCERPT: Final = 4000

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# Quoted fragments the examiner attributes to governing text (exact surfaces).
_QUOTED_FRAGMENT_RE = re.compile(
    r"[\"\u201c](?P<body>[^\"\u201d]{8,800})[\"\u201d]"
)

# Labels / codes that would declare unlawful conduct — hard reject if present
# as outcome language. Used for fail-closed sanitization of free-form labels.
_FORBIDDEN_UNLAWFUL_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "unlawful",
        "illegal",
        "examiner_unlawful",
        "examiner_illegal",
        "unlawful_conduct",
        "criminal",
        "malfeasance",
        "ultra_vires_declaration",
        "declares_unlawful",
        "is_unlawful",
    }
)

# Keys that would substitute a model summary for government/governing text.
_FORBIDDEN_SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "model_summary",
        "llm_summary",
        "ai_summary",
        "generated_summary",
        "summary_substituted_for_instruction",
        "summary_substituted_for_authority",
        "paraphrase_as_authority",
        "paraphrase_as_instruction",
    }
)

_INSTRUCTION_CANDIDATE_KINDS: Final[frozenset[CandidateKind]] = frozenset(
    {
        CandidateKind.REJECTION,
        CandidateKind.OBJECTION,
        CandidateKind.INFORMALITY,
        CandidateKind.RESPONSE_INSTRUCTION,
        CandidateKind.FEE,
        CandidateKind.FORM,
        CandidateKind.FORM_PARAGRAPH,
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ConsistencyStatus(str, Enum):
    """Per-instruction comparison status.

    Closed set — never ``unlawful`` / ``illegal``.
    """

    CONSISTENT = "consistent"
    POTENTIAL_INCONSISTENCY = "potential_inconsistency"
    UNKNOWN = "unknown"


class ConsistencyDisposition(str, Enum):
    """Top-level analysis disposition."""

    COMPARED = "compared"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    EMPTY = "empty"
    REJECTED = "rejected"


class ConsistencyReasonCode(str, Enum):
    COMPARISONS_EMITTED = "comparisons_emitted"
    STATUS_CONSISTENT = "status_consistent"
    STATUS_POTENTIAL_INCONSISTENCY = "status_potential_inconsistency"
    STATUS_UNKNOWN = "status_unknown"
    AUTHORITY_RESOLVED = "authority_resolved"
    AUTHORITY_UNRESOLVED = "authority_unresolved"
    AUTHORITY_AMBIGUOUS = "authority_ambiguous"
    AUTHORITY_COMPETING = "authority_competing"
    QUOTE_MATCH = "quote_match"
    QUOTE_MISMATCH = "quote_mismatch"
    QUOTE_NO_SOURCE = "quote_no_source"
    QUOTE_NO_QUOTE = "quote_no_quote"
    MISSING_SPAN = "missing_span"
    MISSING_VERSION = "missing_version"
    NO_AUTHORITY_GRAPH = "no_authority_graph"
    NO_CITATIONS = "no_citations"
    AS_OF_UNKNOWN = "as_of_unknown"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    NOT_UNLAWFUL_DETERMINATION = "not_unlawful_determination"
    NO_MODEL_SUMMARY_SUBSTITUTION = "no_model_summary_substitution"
    EXACT_SPANS_RETAINED = "exact_spans_retained"
    EMPTY_INPUT = "empty_input"
    QUARANTINED = "quarantined"
    COMPARISON_LIMIT = "comparison_limit"
    APPLICABILITY_RECORDED = "applicability_recorded"
    ASSUMPTIONS_RECORDED = "assumptions_recorded"
    FORBIDDEN_LABEL_STRIPPED = "forbidden_label_stripped"
    SPAN_INDEX_MISS = "span_index_miss"
    INDEPENDENT_RESOLUTION = "independent_resolution"


class InstructionConsistencyError(ValueError):
    """Raised for invalid comparison inputs (never logs document body)."""

    def __init__(
        self, message: str, *, code: str = "instruction_consistency_error"
    ) -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text))


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


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be float or None") from exc
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"{field} must be in [0, 1]")
    return f


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    for member in enum_cls:
        if member.value == text or member.name == text or member.name.lower() == text.lower():
            return member
    raise ValueError(f"{field} has unknown value: {value!r}")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    return _coerce_enum(  # type: ignore[return-value]
        DisclosureClassification, value, "classification"
    )


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    out: list[str] = []
    for i, item in enumerate(value):
        if i >= max_items:
            break
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if text:
            out.append(text[:512])
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 32
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    out: dict[str, str] = {}
    for i, (k, v) in enumerate(sorted(value.items(), key=lambda kv: str(kv[0]))):
        if i >= max_items:
            break
        key = str(k).strip()
        if not key:
            continue
        if not isinstance(v, str):
            v = str(v)
        out[key[:128]] = v.strip()[:512]
    return MappingProxyType(out)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len]


def contains_forbidden_unlawful_token(text: str | None) -> bool:
    """Return True if *text* contains a closed-set unlawful-conduct token."""
    if not text:
        return False
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    for token in _FORBIDDEN_UNLAWFUL_TOKENS:
        if token in lowered:
            return True
    # Phrase forms.
    raw = text.lower()
    if "unlawful conduct" in raw or "declares unlawful" in raw:
        return True
    if "examiner is unlawful" in raw or "examiner unlawful" in raw:
        return True
    return False


def sanitize_labels(labels: Mapping[str, str] | None) -> tuple[Mapping[str, str], tuple[str, ...]]:
    """Strip forbidden summary/unlawful keys; return cleaned map + reason codes."""
    if not labels:
        return MappingProxyType({}), ()
    cleaned: dict[str, str] = {}
    reasons: list[str] = []
    for key, value in labels.items():
        k = str(key).strip().lower()
        if k in _FORBIDDEN_SUMMARY_KEYS or k in _FORBIDDEN_UNLAWFUL_TOKENS:
            reasons.append(ConsistencyReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        if contains_forbidden_unlawful_token(k) or contains_forbidden_unlawful_token(value):
            reasons.append(ConsistencyReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        cleaned[str(key).strip()[:128]] = str(value).strip()[:512]
    return MappingProxyType(cleaned), tuple(dict.fromkeys(reasons))


def extract_quoted_fragments(surface: str) -> tuple[str, ...]:
    """Extract exact quoted fragments from instruction surface text."""
    if not surface:
        return ()
    found: list[str] = []
    for m in _QUOTED_FRAGMENT_RE.finditer(surface):
        body = _normalize_ws(m.group("body"))
        if body and body not in found:
            found.append(body)
    return tuple(found[:8])


def build_human_review_question(
    *,
    instruction_span_id: str,
    citation_surfaces: Sequence[str],
    authority_versions: Sequence[str],
    authority_node_ids: Sequence[str],
    status: ConsistencyStatus,
) -> str:
    """Deterministic human-review question (not a model summary of the law)."""
    cites = ", ".join(citation_surfaces[:4]) if citation_surfaces else "unresolved citation"
    versions = ", ".join(authority_versions[:4]) if authority_versions else "version unknown"
    nodes = ", ".join(authority_node_ids[:4]) if authority_node_ids else "node unknown"
    if status is ConsistencyStatus.POTENTIAL_INCONSISTENCY:
        return (
            f"Human review required: does instruction span {instruction_span_id} "
            f"correctly reflect governing text for {cites} at version(s) {versions} "
            f"(authority node(s) {nodes})? Compare the exact instruction surface "
            f"to the exact authority span(s); do not treat this flag as a finding "
            f"of unlawful conduct."
        )
    if status is ConsistencyStatus.UNKNOWN:
        return (
            f"Human review required: authority or applicability is incomplete for "
            f"instruction span {instruction_span_id} ({cites}; {versions}). "
            f"Resolve competing sources, missing versions, or missing spans before "
            f"any legal conclusion. This is not a determination of unlawful conduct."
        )
    return (
        f"Optional review: instruction span {instruction_span_id} appears consistent "
        f"with resolved authority for {cites} at version(s) {versions} "
        f"(node(s) {nodes}). Confirm as-of applicability if material."
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBounds:
    max_comparisons: int = DEFAULT_MAX_COMPARISONS
    max_surface: int = DEFAULT_MAX_SURFACE
    max_excerpt: int = DEFAULT_MAX_EXCERPT

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_comparisons",
            _nonneg_int(self.max_comparisons, "max_comparisons"),
        )
        object.__setattr__(
            self, "max_surface", _nonneg_int(self.max_surface, "max_surface")
        )
        object.__setattr__(
            self, "max_excerpt", _nonneg_int(self.max_excerpt, "max_excerpt")
        )
        if self.max_comparisons == 0:
            object.__setattr__(self, "max_comparisons", DEFAULT_MAX_COMPARISONS)
        if self.max_surface == 0:
            object.__setattr__(self, "max_surface", DEFAULT_MAX_SURFACE)
        if self.max_excerpt == 0:
            object.__setattr__(self, "max_excerpt", DEFAULT_MAX_EXCERPT)


@dataclass(frozen=True, slots=True)
class ExactTextSpanRef:
    """Exact source span reference with optional body text.

    Body text is the government or governing excerpt itself — never a model
    paraphrase. When body is omitted, ``text_digest`` still anchors identity.
    """

    span_id: str | None
    artifact_id: str | None
    text: str
    text_digest: str
    start_offset: int | None
    end_offset: int | None
    artifact_sha256: str | None
    section: str | None
    role: str  # "instruction" | "authority" | "quoted_attribution" | "counter"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        object.__setattr__(
            self,
            "artifact_id",
            _optional_identifier(self.artifact_id, "artifact_id"),
        )
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        object.__setattr__(self, "text", _truncate(self.text, DEFAULT_MAX_EXCERPT))
        digest = self.text_digest
        if not digest or not _SHA256_RE.match(str(digest).lower()):
            digest = _text_digest(self.text) if self.text else sha256_hex("")
        object.__setattr__(self, "text_digest", str(digest).lower())
        if self.start_offset is not None:
            object.__setattr__(
                self,
                "start_offset",
                _nonneg_int(self.start_offset, "start_offset"),
            )
        if self.end_offset is not None:
            object.__setattr__(
                self, "end_offset", _nonneg_int(self.end_offset, "end_offset")
            )
        if self.artifact_sha256 is not None:
            object.__setattr__(
                self,
                "artifact_sha256",
                _sha256_hex_field(self.artifact_sha256, "artifact_sha256"),
            )
        object.__setattr__(
            self, "section", _optional_str(self.section, "section", max_len=256)
        )
        object.__setattr__(
            self, "role", _require_str(self.role, "role", max_len=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "end_offset": self.end_offset,
            "role": self.role,
            "section": self.section,
            "span_id": self.span_id,
            "start_offset": self.start_offset,
            "text": self.text,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactTextSpanRef":
        if not isinstance(value, Mapping):
            raise TypeError("ExactTextSpanRef must be a mapping")
        return cls(
            span_id=value.get("span_id"),
            artifact_id=value.get("artifact_id"),
            text=str(value.get("text") or ""),
            text_digest=str(value.get("text_digest") or ""),
            start_offset=value.get("start_offset"),
            end_offset=value.get("end_offset"),
            artifact_sha256=value.get("artifact_sha256"),
            section=value.get("section"),
            role=str(value.get("role") or "instruction"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityResolutionDetail:
    """Independently resolved authority with exact version and source text."""

    citation_surface: str
    citation_key: str | None
    match_kind: str
    node_id: str | None
    version: str | None
    edition: str | None
    authority_tier: str | None
    verification_state: str | None
    authority_text_excerpt: str
    authority_span: ExactTextSpanRef | None
    is_binding: bool | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "citation_surface",
            _require_str(self.citation_surface, "citation_surface", max_len=512),
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(
            self, "match_kind", _require_str(self.match_kind, "match_kind", max_len=64)
        )
        object.__setattr__(
            self, "node_id", _optional_identifier(self.node_id, "node_id")
        )
        object.__setattr__(
            self, "version", _optional_str(self.version, "version", max_len=128)
        )
        object.__setattr__(
            self, "edition", _optional_str(self.edition, "edition", max_len=128)
        )
        object.__setattr__(
            self,
            "authority_tier",
            _optional_str(self.authority_tier, "authority_tier", max_len=64),
        )
        object.__setattr__(
            self,
            "verification_state",
            _optional_str(self.verification_state, "verification_state", max_len=64),
        )
        if not isinstance(self.authority_text_excerpt, str):
            raise TypeError("authority_text_excerpt must be str")
        object.__setattr__(
            self,
            "authority_text_excerpt",
            _truncate(self.authority_text_excerpt, DEFAULT_MAX_EXCERPT),
        )
        if self.authority_span is not None and not isinstance(
            self.authority_span, ExactTextSpanRef
        ):
            raise TypeError("authority_span must be ExactTextSpanRef or None")
        if self.is_binding is not None and not isinstance(self.is_binding, bool):
            raise TypeError("is_binding must be bool or None")
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=32)
        )

    @property
    def has_exact_version(self) -> bool:
        return bool(self.version or self.edition)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_span": (
                None if self.authority_span is None else self.authority_span.to_dict()
            ),
            "authority_text_excerpt": self.authority_text_excerpt,
            "authority_tier": self.authority_tier,
            "citation_key": self.citation_key,
            "citation_surface": self.citation_surface,
            "edition": self.edition,
            "is_binding": self.is_binding,
            "match_kind": self.match_kind,
            "node_id": self.node_id,
            "reasons": list(self.reasons),
            "verification_state": self.verification_state,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityResolutionDetail":
        if not isinstance(value, Mapping):
            raise TypeError("AuthorityResolutionDetail must be a mapping")
        span_raw = value.get("authority_span")
        return cls(
            citation_surface=str(value.get("citation_surface") or ""),
            citation_key=value.get("citation_key"),
            match_kind=str(value.get("match_kind") or CitationMatchKind.UNRESOLVED.value),
            node_id=value.get("node_id"),
            version=value.get("version"),
            edition=value.get("edition"),
            authority_tier=value.get("authority_tier"),
            verification_state=value.get("verification_state"),
            authority_text_excerpt=str(value.get("authority_text_excerpt") or ""),
            authority_span=(
                None
                if span_raw is None
                else ExactTextSpanRef.from_dict(span_raw)
            ),
            is_binding=value.get("is_binding"),
            reasons=tuple(value.get("reasons") or ()),
        )


@dataclass(frozen=True, slots=True)
class CompetingAuthorityDetail:
    """One competing authority when resolution is ambiguous/conflicted."""

    node_id: str
    citation_key: str | None
    citation: str | None
    version: str | None
    edition: str | None
    authority_tier: str | None
    authority_text_excerpt: str
    reason: str
    content_fingerprint: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _identifier(self.node_id, "node_id")
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(
            self, "citation", _optional_str(self.citation, "citation", max_len=512)
        )
        object.__setattr__(
            self, "version", _optional_str(self.version, "version", max_len=128)
        )
        object.__setattr__(
            self, "edition", _optional_str(self.edition, "edition", max_len=128)
        )
        object.__setattr__(
            self,
            "authority_tier",
            _optional_str(self.authority_tier, "authority_tier", max_len=64),
        )
        if not isinstance(self.authority_text_excerpt, str):
            raise TypeError("authority_text_excerpt must be str")
        object.__setattr__(
            self,
            "authority_text_excerpt",
            _truncate(self.authority_text_excerpt, DEFAULT_MAX_EXCERPT),
        )
        object.__setattr__(
            self, "reason", _require_str(self.reason, "reason", max_len=256)
        )
        object.__setattr__(
            self,
            "content_fingerprint",
            _optional_str(
                self.content_fingerprint, "content_fingerprint", max_len=128
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_text_excerpt": self.authority_text_excerpt,
            "authority_tier": self.authority_tier,
            "citation": self.citation,
            "citation_key": self.citation_key,
            "content_fingerprint": self.content_fingerprint,
            "edition": self.edition,
            "node_id": self.node_id,
            "reason": self.reason,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompetingAuthorityDetail":
        if not isinstance(value, Mapping):
            raise TypeError("CompetingAuthorityDetail must be a mapping")
        return cls(
            node_id=str(value.get("node_id") or ""),
            citation_key=value.get("citation_key"),
            citation=value.get("citation"),
            version=value.get("version"),
            edition=value.get("edition"),
            authority_tier=value.get("authority_tier"),
            authority_text_excerpt=str(value.get("authority_text_excerpt") or ""),
            reason=str(value.get("reason") or "competing"),
            content_fingerprint=value.get("content_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class QuoteComparisonDetail:
    """Exact quote comparison between attributed text and authority source.

    On mismatch both quoted and source spans are always present so the
    potential inconsistency is reproducible without a model summary.
    """

    status: str
    quoted_span: ExactTextSpanRef | None
    source_span: ExactTextSpanRef | None
    match_ratio: float | None
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _require_str(self.status, "status", max_len=64)
        )
        if self.quoted_span is not None and not isinstance(
            self.quoted_span, ExactTextSpanRef
        ):
            raise TypeError("quoted_span must be ExactTextSpanRef or None")
        if self.source_span is not None and not isinstance(
            self.source_span, ExactTextSpanRef
        ):
            raise TypeError("source_span must be ExactTextSpanRef or None")
        if self.status == QuoteMatchStatus.MISMATCH.value:
            if self.quoted_span is None or self.source_span is None:
                raise ValueError(
                    "quote mismatch must expose both quoted_span and source_span"
                )
        object.__setattr__(
            self, "match_ratio", _optional_float_01(self.match_ratio, "match_ratio")
        )
        object.__setattr__(
            self, "detail", _require_str(self.detail, "detail", max_len=512)
        )
        if contains_forbidden_unlawful_token(self.detail):
            raise ValueError(
                "quote comparison detail must not declare unlawful conduct"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "match_ratio": self.match_ratio,
            "quoted_span": (
                None if self.quoted_span is None else self.quoted_span.to_dict()
            ),
            "source_span": (
                None if self.source_span is None else self.source_span.to_dict()
            ),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuoteComparisonDetail":
        if not isinstance(value, Mapping):
            raise TypeError("QuoteComparisonDetail must be a mapping")
        qs = value.get("quoted_span")
        ss = value.get("source_span")
        return cls(
            status=str(value.get("status") or QuoteMatchStatus.NO_QUOTE.value),
            quoted_span=None if qs is None else ExactTextSpanRef.from_dict(qs),
            source_span=None if ss is None else ExactTextSpanRef.from_dict(ss),
            match_ratio=value.get("match_ratio"),
            detail=str(value.get("detail") or "quote comparison"),
        )


@dataclass(frozen=True, slots=True)
class InstructionSourceInput:
    """One government instruction span to compare against authority."""

    source_id: str
    source_span_id: str
    instruction_surface_text: str
    instruction_text_digest: str | None = None
    legal_citations: tuple[str, ...] = ()
    citation_keys: tuple[str, ...] = ()
    quoted_authority_text: str | None = None
    quoted_authority_span_id: str | None = None
    requirement_type: str | None = None
    applicability_conditions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    artifact_id: str | None = None
    action_id: str | None = None
    confidence: float | None = None
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "source_span_id",
            _identifier(self.source_span_id, "source_span_id"),
        )
        if not isinstance(self.instruction_surface_text, str):
            raise TypeError("instruction_surface_text must be str")
        surface = _truncate(self.instruction_surface_text, DEFAULT_MAX_SURFACE)
        object.__setattr__(self, "instruction_surface_text", surface)
        digest = self.instruction_text_digest
        if not digest or not _SHA256_RE.match(str(digest).lower()):
            digest = _text_digest(surface)
        object.__setattr__(self, "instruction_text_digest", str(digest).lower())
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=64),
        )
        object.__setattr__(
            self,
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        object.__setattr__(
            self,
            "quoted_authority_text",
            _optional_str(
                self.quoted_authority_text,
                "quoted_authority_text",
                max_len=DEFAULT_MAX_EXCERPT,
            ),
        )
        object.__setattr__(
            self,
            "quoted_authority_span_id",
            _optional_identifier(
                self.quoted_authority_span_id, "quoted_authority_span_id"
            ),
        )
        object.__setattr__(
            self,
            "requirement_type",
            _optional_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self,
            "applicability_conditions",
            _tuple_of_str(
                self.applicability_conditions,
                "applicability_conditions",
                max_items=64,
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _tuple_of_str(self.assumptions, "assumptions", max_items=64),
        )
        object.__setattr__(
            self,
            "artifact_id",
            _optional_identifier(self.artifact_id, "artifact_id"),
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_labels(
            dict(self.labels) if self.labels is not None else {}
        )
        object.__setattr__(self, "labels", cleaned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "applicability_conditions": list(self.applicability_conditions),
            "artifact_id": self.artifact_id,
            "assumptions": list(self.assumptions),
            "citation_keys": list(self.citation_keys),
            "classification": self.classification.value,
            "confidence": self.confidence,
            "instruction_surface_text": self.instruction_surface_text,
            "instruction_text_digest": self.instruction_text_digest,
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "quoted_authority_span_id": self.quoted_authority_span_id,
            "quoted_authority_text": self.quoted_authority_text,
            "requirement_type": self.requirement_type,
            "source_id": self.source_id,
            "source_span_id": self.source_span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InstructionSourceInput":
        if not isinstance(value, Mapping):
            raise TypeError("InstructionSourceInput must be a mapping")
        # Reject model-summary substitution for the instruction body.
        for forbidden in _FORBIDDEN_SUMMARY_KEYS:
            if forbidden in value and value.get("instruction_surface_text") is None:
                raise InstructionConsistencyError(
                    "model summary cannot substitute for government instruction text",
                    code="model_summary_forbidden",
                )
        return cls(
            source_id=str(value.get("source_id") or ""),
            source_span_id=str(value.get("source_span_id") or ""),
            instruction_surface_text=str(
                value.get("instruction_surface_text") or ""
            ),
            instruction_text_digest=value.get("instruction_text_digest"),
            legal_citations=tuple(value.get("legal_citations") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            quoted_authority_text=value.get("quoted_authority_text"),
            quoted_authority_span_id=value.get("quoted_authority_span_id"),
            requirement_type=value.get("requirement_type"),
            applicability_conditions=tuple(
                value.get("applicability_conditions") or ()
            ),
            assumptions=tuple(value.get("assumptions") or ()),
            artifact_id=value.get("artifact_id"),
            action_id=value.get("action_id"),
            confidence=value.get("confidence"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )

    @classmethod
    def from_compiled_predicate(
        cls, pred: CompiledPredicate, *, artifact_id: str | None = None
    ) -> "InstructionSourceInput":
        applicability = list(pred.applicability.conditions)
        assumptions: list[str] = []
        if pred.authority.state is not None:
            assumptions.append(f"authority_state:{pred.authority.state.value}")
        if pred.applicability.state is not None:
            assumptions.append(
                f"applicability_state:{pred.applicability.state.value}"
            )
        return cls(
            source_id=pred.predicate_id,
            source_span_id=pred.source_span_id,
            instruction_surface_text=pred.surface_text,
            instruction_text_digest=pred.instruction_text_digest,
            legal_citations=pred.legal_citations,
            citation_keys=tuple(pred.authority.citation_keys),
            requirement_type=pred.requirement_type,
            applicability_conditions=tuple(applicability),
            assumptions=tuple(assumptions),
            artifact_id=artifact_id,
            classification=pred.classification,
            confidence=pred.parser_confidence,
            labels=dict(pred.labels),
        )

    @classmethod
    def from_government_requirement(
        cls,
        req: GovernmentRequirement,
        *,
        surface_text: str = "",
        artifact_id: str | None = None,
    ) -> "InstructionSourceInput":
        return cls(
            source_id=req.requirement_id,
            source_span_id=req.source_span_id,
            instruction_surface_text=surface_text,
            instruction_text_digest=req.instruction_text_digest,
            legal_citations=req.legal_citations,
            requirement_type=req.requirement_type,
            applicability_conditions=req.applicability_conditions,
            assumptions=(),
            artifact_id=artifact_id,
            classification=req.classification,
            confidence=req.parser_confidence,
        )

    @classmethod
    def from_analysis_candidate(
        cls,
        cand: AnalysisCandidate,
        *,
        artifact_id: str | None = None,
        action_id: str | None = None,
        classification: DisclosureClassification = DisclosureClassification.UNKNOWN,
    ) -> "InstructionSourceInput":
        return cls(
            source_id=cand.candidate_id,
            source_span_id=cand.source_span_id,
            instruction_surface_text=cand.surface_text or "",
            instruction_text_digest=cand.text_digest,
            legal_citations=cand.legal_citations,
            citation_keys=cand.citation_keys,
            requirement_type=cand.requirement_type,
            applicability_conditions=(),
            assumptions=tuple(f"exception:{e}" for e in cand.exceptions[:8]),
            artifact_id=artifact_id,
            action_id=action_id,
            classification=classification,
            confidence=cand.confidence,
            labels=dict(cand.labels),
        )


@dataclass(frozen=True, slots=True)
class ConsistencyComparisonEntry:
    """One instruction → authority comparison packet."""

    schema_version: str
    comparison_id: str
    source_id: str
    instruction_span_id: str
    instruction_surface_text: str
    instruction_text_digest: str
    status: ConsistencyStatus
    authority_resolutions: tuple[AuthorityResolutionDetail, ...]
    competing_authorities: tuple[CompetingAuthorityDetail, ...]
    quote_comparisons: tuple[QuoteComparisonDetail, ...]
    applicability_facts: tuple[str, ...]
    assumptions: tuple[str, ...]
    human_review_question: str
    reason_codes: tuple[str, ...]
    counter_source_spans: tuple[ExactTextSpanRef, ...]
    authority_versions: tuple[str, ...]
    authority_node_ids: tuple[str, ...]
    citation_surfaces: tuple[str, ...]
    requires_human_review: bool
    declares_unlawful_conduct: bool
    is_model_summary_substitution: bool
    review_state: ReviewState
    classification: DisclosureClassification
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != INSTRUCTION_CONSISTENCY_SCHEMA_VERSION:
            raise ValueError(
                "ConsistencyComparisonEntry.schema_version must be "
                f"{INSTRUCTION_CONSISTENCY_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "comparison_id", _identifier(self.comparison_id, "comparison_id")
        )
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "instruction_span_id",
            _identifier(self.instruction_span_id, "instruction_span_id"),
        )
        if not isinstance(self.instruction_surface_text, str):
            raise TypeError("instruction_surface_text must be str")
        object.__setattr__(
            self,
            "instruction_surface_text",
            _truncate(self.instruction_surface_text, DEFAULT_MAX_SURFACE),
        )
        object.__setattr__(
            self,
            "instruction_text_digest",
            _sha256_hex_field(
                self.instruction_text_digest, "instruction_text_digest"
            ),
        )
        object.__setattr__(
            self, "status", _coerce_enum(ConsistencyStatus, self.status, "status")
        )
        if not isinstance(self.authority_resolutions, tuple):
            object.__setattr__(
                self, "authority_resolutions", tuple(self.authority_resolutions)
            )
        if not isinstance(self.competing_authorities, tuple):
            object.__setattr__(
                self, "competing_authorities", tuple(self.competing_authorities)
            )
        if not isinstance(self.quote_comparisons, tuple):
            object.__setattr__(
                self, "quote_comparisons", tuple(self.quote_comparisons)
            )
        if not isinstance(self.counter_source_spans, tuple):
            object.__setattr__(
                self, "counter_source_spans", tuple(self.counter_source_spans)
            )
        object.__setattr__(
            self,
            "applicability_facts",
            _tuple_of_str(
                self.applicability_facts, "applicability_facts", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _tuple_of_str(self.assumptions, "assumptions", max_items=64),
        )
        object.__setattr__(
            self,
            "human_review_question",
            _require_str(
                self.human_review_question, "human_review_question", max_len=2048
            ),
        )
        if contains_forbidden_unlawful_token(self.human_review_question):
            # Rewrite rather than allow unlawful declaration.
            object.__setattr__(
                self,
                "human_review_question",
                build_human_review_question(
                    instruction_span_id=self.instruction_span_id,
                    citation_surfaces=self.citation_surfaces,
                    authority_versions=self.authority_versions,
                    authority_node_ids=self.authority_node_ids,
                    status=self.status,  # type: ignore[arg-type]
                ),
            )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_versions",
            _tuple_of_str(
                self.authority_versions, "authority_versions", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "authority_node_ids",
            _tuple_of_str(
                self.authority_node_ids, "authority_node_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "citation_surfaces",
            _tuple_of_str(
                self.citation_surfaces, "citation_surfaces", max_items=64
            ),
        )
        object.__setattr__(
            self, "requires_human_review", bool(self.requires_human_review)
        )
        if not isinstance(self.declares_unlawful_conduct, bool):
            raise TypeError("declares_unlawful_conduct must be bool")
        if self.declares_unlawful_conduct:
            raise ValueError(
                "declares_unlawful_conduct must be False — this module never "
                "declares unlawful conduct"
            )
        if not isinstance(self.is_model_summary_substitution, bool):
            raise TypeError("is_model_summary_substitution must be bool")
        if self.is_model_summary_substitution:
            raise ValueError(
                "is_model_summary_substitution must be False — model summaries "
                "are never substituted for government or governing text"
            )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_labels(
            dict(self.labels) if self.labels is not None else {}
        )
        object.__setattr__(self, "labels", cleaned)

        # Potential inconsistency must be reproducible from exact spans/versions.
        if self.status is ConsistencyStatus.POTENTIAL_INCONSISTENCY:
            has_instruction_anchor = bool(
                self.instruction_span_id and self.instruction_text_digest
            )
            has_authority_anchor = bool(
                self.authority_versions
                or self.authority_node_ids
                or any(
                    q.source_span is not None for q in self.quote_comparisons
                )
                or self.counter_source_spans
            )
            if not has_instruction_anchor or not has_authority_anchor:
                raise ValueError(
                    "potential_inconsistency requires reproducible instruction "
                    "and authority anchors (span/version)"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicability_facts": list(self.applicability_facts),
            "assumptions": list(self.assumptions),
            "authority_node_ids": list(self.authority_node_ids),
            "authority_resolutions": [
                a.to_dict() for a in self.authority_resolutions
            ],
            "authority_versions": list(self.authority_versions),
            "citation_surfaces": list(self.citation_surfaces),
            "classification": self.classification.value,
            "comparison_id": self.comparison_id,
            "competing_authorities": [
                c.to_dict() for c in self.competing_authorities
            ],
            "counter_source_spans": [
                s.to_dict() for s in self.counter_source_spans
            ],
            "declares_unlawful_conduct": False,
            "human_review_question": self.human_review_question,
            "instruction_span_id": self.instruction_span_id,
            "instruction_surface_text": self.instruction_surface_text,
            "instruction_text_digest": self.instruction_text_digest,
            "is_model_summary_substitution": False,
            "labels": dict(self.labels),
            "quote_comparisons": [q.to_dict() for q in self.quote_comparisons],
            "reason_codes": list(self.reason_codes),
            "requires_human_review": self.requires_human_review,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConsistencyComparisonEntry":
        if not isinstance(value, Mapping):
            raise TypeError("ConsistencyComparisonEntry must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
            ),
            comparison_id=str(value.get("comparison_id") or ""),
            source_id=str(value.get("source_id") or ""),
            instruction_span_id=str(value.get("instruction_span_id") or ""),
            instruction_surface_text=str(
                value.get("instruction_surface_text") or ""
            ),
            instruction_text_digest=str(
                value.get("instruction_text_digest") or ""
            ),
            status=value.get("status", ConsistencyStatus.UNKNOWN.value),
            authority_resolutions=tuple(
                AuthorityResolutionDetail.from_dict(a)
                for a in (value.get("authority_resolutions") or ())
            ),
            competing_authorities=tuple(
                CompetingAuthorityDetail.from_dict(c)
                for c in (value.get("competing_authorities") or ())
            ),
            quote_comparisons=tuple(
                QuoteComparisonDetail.from_dict(q)
                for q in (value.get("quote_comparisons") or ())
            ),
            applicability_facts=tuple(value.get("applicability_facts") or ()),
            assumptions=tuple(value.get("assumptions") or ()),
            human_review_question=str(
                value.get("human_review_question") or "Human review required."
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            counter_source_spans=tuple(
                ExactTextSpanRef.from_dict(s)
                for s in (value.get("counter_source_spans") or ())
            ),
            authority_versions=tuple(value.get("authority_versions") or ()),
            authority_node_ids=tuple(value.get("authority_node_ids") or ()),
            citation_surfaces=tuple(value.get("citation_surfaces") or ()),
            requires_human_review=bool(value.get("requires_human_review", True)),
            declares_unlawful_conduct=bool(
                value.get("declares_unlawful_conduct", False)
            ),
            is_model_summary_substitution=bool(
                value.get("is_model_summary_substitution", False)
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class InstructionConsistencyInput:
    """Input packet for instruction/authority consistency analysis."""

    artifact_id: str
    instructions: tuple[InstructionSourceInput, ...] = ()
    spans: tuple[ExtractedSpan, ...] = ()
    span_texts: Mapping[str, str] = MappingProxyType({})
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    as_of: str | date | None = None
    analysis_id: str | None = None
    matter_id: str | None = None
    mailing_date: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.instructions, tuple):
            object.__setattr__(self, "instructions", tuple(self.instructions))
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        if self.span_texts is None:
            object.__setattr__(self, "span_texts", MappingProxyType({}))
        elif not isinstance(self.span_texts, MappingProxyType):
            cleaned: dict[str, str] = {}
            for k, v in dict(self.span_texts).items():
                key = str(k).strip()
                if key and isinstance(v, str):
                    cleaned[key] = _truncate(v, DEFAULT_MAX_SURFACE)
            object.__setattr__(self, "span_texts", MappingProxyType(cleaned))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if isinstance(self.as_of, date):
            object.__setattr__(self, "as_of", self.as_of.isoformat())
        else:
            object.__setattr__(
                self, "as_of", _optional_str(self.as_of, "as_of", max_len=32)
            )
        object.__setattr__(
            self,
            "analysis_id",
            _optional_identifier(self.analysis_id, "analysis_id"),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=32),
        )
        cleaned, _ = sanitize_labels(
            dict(self.labels) if self.labels is not None else {}
        )
        object.__setattr__(self, "labels", cleaned)


@dataclass(frozen=True, slots=True)
class InstructionConsistencyResult:
    """Deterministic, versioned instruction/authority comparison outcome.

    Always declares ``output_kind`` as instruction/authority comparison and
    carries the non-unlawful disclaimer. Never a conclusive legality label.
    """

    schema_version: str
    analysis_id: str
    source_artifact_id: str
    matter_id: str | None
    disposition: ConsistencyDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    output_kind: str
    disclaimer: str
    declares_unlawful_conduct: bool
    is_model_summary_substitution: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    comparisons: tuple[ConsistencyComparisonEntry, ...]
    consistent_count: int
    potential_inconsistency_count: int
    unknown_count: int
    ruleset_versions: Mapping[str, str]
    authority_graph_id: str | None
    as_of: str | None
    labels: Mapping[str, str]
    text_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != INSTRUCTION_CONSISTENCY_SCHEMA_VERSION:
            raise ValueError(
                "InstructionConsistencyResult.schema_version must be "
                f"{INSTRUCTION_CONSISTENCY_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self,
            "source_artifact_id",
            _identifier(self.source_artifact_id, "source_artifact_id"),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ConsistencyDisposition, self.disposition, "disposition"),
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
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON:
            raise ValueError(
                "output_kind must be "
                f"{OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        disc_l = self.disclaimer.lower()
        if "unlawful" not in disc_l and "not declare" not in disc_l:
            raise ValueError(
                "disclaimer must state that this does not declare unlawful conduct"
            )
        if not isinstance(self.declares_unlawful_conduct, bool):
            raise TypeError("declares_unlawful_conduct must be bool")
        if self.declares_unlawful_conduct:
            raise ValueError(
                "declares_unlawful_conduct must be False — never declare "
                "unlawful conduct"
            )
        if not isinstance(self.is_model_summary_substitution, bool):
            raise TypeError("is_model_summary_substitution must be bool")
        if self.is_model_summary_substitution:
            raise ValueError(
                "is_model_summary_substitution must be False"
            )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        if not isinstance(self.comparisons, tuple):
            object.__setattr__(self, "comparisons", tuple(self.comparisons))
        for entry in self.comparisons:
            if not isinstance(entry, ConsistencyComparisonEntry):
                raise TypeError(
                    "comparisons must be ConsistencyComparisonEntry instances"
                )
            if entry.declares_unlawful_conduct:
                raise ValueError(
                    "comparison entry must not declare unlawful conduct"
                )
            if entry.is_model_summary_substitution:
                raise ValueError(
                    "comparison entry must not use model summary substitution"
                )
        object.__setattr__(
            self,
            "consistent_count",
            _nonneg_int(self.consistent_count, "consistent_count"),
        )
        object.__setattr__(
            self,
            "potential_inconsistency_count",
            _nonneg_int(
                self.potential_inconsistency_count,
                "potential_inconsistency_count",
            ),
        )
        object.__setattr__(
            self, "unknown_count", _nonneg_int(self.unknown_count, "unknown_count")
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "authority_graph_id",
            _optional_identifier(self.authority_graph_id, "authority_graph_id"),
        )
        object.__setattr__(
            self, "as_of", _optional_str(self.as_of, "as_of", max_len=32)
        )
        cleaned, _ = sanitize_labels(
            dict(self.labels) if self.labels is not None else {}
        )
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self, "text_digest", _sha256_hex_field(self.text_digest, "text_digest")
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            ConsistencyDisposition.REVIEW,
            ConsistencyDisposition.UNKNOWN,
            ConsistencyDisposition.QUARANTINE,
            ConsistencyDisposition.PARTIAL,
            ConsistencyDisposition.REJECTED,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def comparisons_by_status(
        self, status: ConsistencyStatus | str
    ) -> tuple[ConsistencyComparisonEntry, ...]:
        st = _coerce_enum(ConsistencyStatus, status, "status")
        return tuple(c for c in self.comparisons if c.status is st)

    def potential_inconsistencies(self) -> tuple[ConsistencyComparisonEntry, ...]:
        return self.comparisons_by_status(ConsistencyStatus.POTENTIAL_INCONSISTENCY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "as_of": self.as_of,
            "authority_graph_id": self.authority_graph_id,
            "classification": self.classification.value,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "consistent_count": self.consistent_count,
            "declares_unlawful_conduct": False,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "is_model_summary_substitution": False,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "potential_inconsistency_count": self.potential_inconsistency_count,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "source_artifact_id": self.source_artifact_id,
            "text_digest": self.text_digest,
            "unknown_count": self.unknown_count,
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — no instruction/authority body text."""
        return {
            "analysis_id": self.analysis_id,
            "as_of": self.as_of,
            "authority_graph_id": self.authority_graph_id,
            "classification": self.classification.value,
            "comparison_count": len(self.comparisons),
            "comparison_ids": [c.comparison_id for c in self.comparisons],
            "consistent_count": self.consistent_count,
            "declares_unlawful_conduct": False,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "is_model_summary_substitution": False,
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "potential_inconsistency_count": self.potential_inconsistency_count,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "source_artifact_id": self.source_artifact_id,
            "text_digest": self.text_digest,
            "unknown_count": self.unknown_count,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InstructionConsistencyResult":
        if not isinstance(value, Mapping):
            raise TypeError("InstructionConsistencyResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
            ),
            analysis_id=str(value.get("analysis_id") or ""),
            source_artifact_id=str(value.get("source_artifact_id") or ""),
            matter_id=value.get("matter_id"),
            disposition=value.get(
                "disposition", ConsistencyDisposition.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON
            ),
            disclaimer=value.get(
                "disclaimer", NOT_UNLAWFUL_DETERMINATION_DISCLAIMER
            ),
            declares_unlawful_conduct=bool(
                value.get("declares_unlawful_conduct", False)
            ),
            is_model_summary_substitution=bool(
                value.get("is_model_summary_substitution", False)
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            comparisons=tuple(
                ConsistencyComparisonEntry.from_dict(c)
                for c in (value.get("comparisons") or ())
            ),
            consistent_count=int(value.get("consistent_count", 0)),
            potential_inconsistency_count=int(
                value.get("potential_inconsistency_count", 0)
            ),
            unknown_count=int(value.get("unknown_count", 0)),
            ruleset_versions=value.get("ruleset_versions") or {},
            authority_graph_id=value.get("authority_graph_id"),
            as_of=value.get("as_of"),
            labels=value.get("labels") or {},
            text_digest=str(value.get("text_digest") or sha256_hex("")),
        )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class InstructionConsistencyProcessor:
    """Compare instruction spans to independently resolved authority.

    Parameters
    ----------
    graph:
        Optional temporal authority graph for as-of citation resolution.
    citation_resolver:
        Optional preconfigured :class:`PatentCitationResolver`.
    id_factory:
        Deterministic ID factory for tests.
    bounds:
        Safety bounds on output size.
    """

    def __init__(
        self,
        *,
        graph: PatentTemporalAuthorityGraph | None = None,
        citation_resolver: PatentCitationResolver | None = None,
        id_factory: Callable[[], str] | None = None,
        bounds: AnalysisBounds | None = None,
    ) -> None:
        self.graph = graph
        if citation_resolver is not None:
            self.resolver = citation_resolver
        else:
            self.resolver = PatentCitationResolver(graph=graph)
        self._id_factory = id_factory or (
            lambda: f"icons:{uuid.uuid4().hex[:12]}"
        )
        self.bounds = bounds or AnalysisBounds()

    # -- public API ---------------------------------------------------------

    def compare(
        self,
        value: (
            InstructionConsistencyInput
            | RequirementCompilationResult
            | OfficeActionResult
            | Mapping[str, Any]
            | None
        ) = None,
        /,
        **kwargs: Any,
    ) -> InstructionConsistencyResult:
        """Compare instructions to applicable authority."""
        inp = self._coerce_input(value, **kwargs)
        return self._compare(inp)

    def compare_many(
        self, values: Sequence[Any]
    ) -> tuple[InstructionConsistencyResult, ...]:
        return tuple(self.compare(v) for v in values)

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: Any,
        **kwargs: Any,
    ) -> InstructionConsistencyInput:
        if value is None and not kwargs:
            raise InstructionConsistencyError(
                "comparison input is required", code="missing_input"
            )
        if isinstance(value, InstructionConsistencyInput):
            return value
        if isinstance(value, RequirementCompilationResult):
            instructions = tuple(
                InstructionSourceInput.from_compiled_predicate(
                    p, artifact_id=value.source_artifact_id
                )
                for p in value.predicates
            )
            as_of = kwargs.get("as_of") or value.as_of
            return InstructionConsistencyInput(
                artifact_id=value.source_artifact_id,
                instructions=instructions,
                classification=value.classification,
                as_of=as_of,
                analysis_id=value.compilation_id,
                labels=dict(value.labels),
            )
        if isinstance(value, OfficeActionResult):
            instructions = tuple(
                InstructionSourceInput.from_analysis_candidate(
                    c,
                    artifact_id=value.artifact_id,
                    action_id=value.action_id,
                    classification=value.classification,
                )
                for c in value.candidates
                if c.kind in _INSTRUCTION_CANDIDATE_KINDS
            )
            return InstructionConsistencyInput(
                artifact_id=value.artifact_id,
                instructions=instructions,
                spans=value.spans,
                classification=value.classification,
                as_of=kwargs.get("as_of") or value.mailing_date,
                analysis_id=value.analysis_id,
                mailing_date=value.mailing_date,
                labels=dict(value.labels),
            )
        if isinstance(value, Mapping):
            merged = dict(value)
            merged.update(kwargs)
            return self._from_mapping(merged)
        if kwargs:
            return self._coerce_input(kwargs)
        raise InstructionConsistencyError(
            f"unsupported comparison input type: {type(value).__name__}",
            code="invalid_input_type",
        )

    def _from_mapping(self, merged: Mapping[str, Any]) -> InstructionConsistencyInput:
        # Accept nested compiled/office-action results.
        if "predicates" in merged and "source_artifact_id" in merged:
            try:
                compiled = RequirementCompilationResult.from_dict(merged)
                return self._coerce_input(compiled)
            except Exception:
                pass
        if "candidates" in merged and "artifact_id" in merged:
            try:
                oa = OfficeActionResult.from_dict(merged)
                return self._coerce_input(oa)
            except Exception:
                pass

        raw_instructions = merged.get("instructions") or ()
        instructions: list[InstructionSourceInput] = []
        for item in raw_instructions:
            if isinstance(item, InstructionSourceInput):
                instructions.append(item)
            elif isinstance(item, Mapping):
                instructions.append(InstructionSourceInput.from_dict(item))
            elif isinstance(item, CompiledPredicate):
                instructions.append(
                    InstructionSourceInput.from_compiled_predicate(item)
                )
            elif isinstance(item, AnalysisCandidate):
                instructions.append(
                    InstructionSourceInput.from_analysis_candidate(item)
                )

        spans_raw = merged.get("spans") or ()
        spans: list[ExtractedSpan] = []
        for s in spans_raw:
            if isinstance(s, ExtractedSpan):
                spans.append(s)
            elif isinstance(s, Mapping):
                spans.append(ExtractedSpan.from_dict(s))

        span_texts = merged.get("span_texts") or {}
        return InstructionConsistencyInput(
            artifact_id=str(merged.get("artifact_id") or "artifact:unknown"),
            instructions=tuple(instructions),
            spans=tuple(spans),
            span_texts=span_texts,
            classification=merged.get(
                "classification", DisclosureClassification.UNKNOWN
            ),
            as_of=merged.get("as_of"),
            analysis_id=merged.get("analysis_id"),
            matter_id=merged.get("matter_id"),
            mailing_date=merged.get("mailing_date"),
            labels=merged.get("labels") or {},
        )

    # -- core compare -------------------------------------------------------

    def _compare(self, inp: InstructionConsistencyInput) -> InstructionConsistencyResult:
        analysis_id = inp.analysis_id or self._id_factory()
        reason_codes: list[str] = [
            ConsistencyReasonCode.NOT_UNLAWFUL_DETERMINATION.value,
            ConsistencyReasonCode.NO_MODEL_SUMMARY_SUBSTITUTION.value,
        ]
        warnings: list[str] = []
        classification = inp.classification

        if requires_quarantine(classification):
            reason_codes.append(ConsistencyReasonCode.QUARANTINED.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                disposition=ConsistencyDisposition.QUARANTINE,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=warnings,
                classification=classification,
            )

        graph = self.graph or getattr(self.resolver, "graph", None)
        graph_id = getattr(graph, "graph_id", None) if graph is not None else None
        if graph is None:
            reason_codes.append(ConsistencyReasonCode.NO_AUTHORITY_GRAPH.value)
            warnings.append("no_authority_graph")

        as_of = inp.as_of or inp.mailing_date
        if as_of is None and graph is not None:
            reason_codes.append(ConsistencyReasonCode.AS_OF_UNKNOWN.value)
            warnings.append("as_of_unknown")

        span_ids = {s.span_id for s in inp.spans}
        span_by_id = {s.span_id: s for s in inp.spans}

        comparisons: list[ConsistencyComparisonEntry] = []
        seq = 0
        for source in inp.instructions:
            if seq >= self.bounds.max_comparisons:
                reason_codes.append(ConsistencyReasonCode.COMPARISON_LIMIT.value)
                warnings.append("comparison_limit")
                break
            seq += 1
            entry = self._compare_one(
                analysis_id=analysis_id,
                seq=seq,
                source=source,
                graph=graph,
                as_of=as_of,
                span_ids=span_ids,
                span_by_id=span_by_id,
                span_texts=inp.span_texts,
                classification=classification,
            )
            comparisons.append(entry)
            reason_codes.extend(entry.reason_codes)

        if not comparisons:
            reason_codes.append(ConsistencyReasonCode.EMPTY_INPUT.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                disposition=ConsistencyDisposition.EMPTY,
                review_state=ReviewState.PENDING,
                reason_codes=reason_codes,
                warnings=warnings,
                classification=classification,
            )

        reason_codes.append(ConsistencyReasonCode.COMPARISONS_EMITTED.value)
        reason_codes.append(ConsistencyReasonCode.EXACT_SPANS_RETAINED.value)

        consistent_count = sum(
            1 for c in comparisons if c.status is ConsistencyStatus.CONSISTENT
        )
        pot_count = sum(
            1
            for c in comparisons
            if c.status is ConsistencyStatus.POTENTIAL_INCONSISTENCY
        )
        unknown_count = sum(
            1 for c in comparisons if c.status is ConsistencyStatus.UNKNOWN
        )

        disposition, review_state = self._disposition(
            comparisons=comparisons, classification=classification
        )
        if pot_count or unknown_count:
            reason_codes.append(
                ConsistencyReasonCode.HUMAN_REVIEW_REQUIRED.value
            )

        # Stable unique reason codes, order-preserving.
        reason_codes = list(dict.fromkeys(reason_codes))

        text_digest = self._content_digest(comparisons)
        as_of_str = (
            as_of.isoformat()
            if isinstance(as_of, date)
            else (str(as_of) if as_of else None)
        )

        return InstructionConsistencyResult(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            analysis_id=analysis_id,
            source_artifact_id=inp.artifact_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            output_kind=OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON,
            disclaimer=NOT_UNLAWFUL_DETERMINATION_DISCLAIMER,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            reason_codes=tuple(reason_codes),
            warnings=tuple(dict.fromkeys(warnings)),
            comparisons=tuple(comparisons),
            consistent_count=consistent_count,
            potential_inconsistency_count=pot_count,
            unknown_count=unknown_count,
            ruleset_versions={
                "instruction_consistency": INSTRUCTION_CONSISTENCY_RULESET_VERSION,
                "instruction_consistency_processor": (
                    INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
                ),
                "contracts": CONTRACTS_SCHEMA_VERSION,
            },
            authority_graph_id=graph_id if isinstance(graph_id, str) else None,
            as_of=as_of_str,
            labels=dict(inp.labels),
            text_digest=text_digest,
        )

    def _compare_one(
        self,
        *,
        analysis_id: str,
        seq: int,
        source: InstructionSourceInput,
        graph: PatentTemporalAuthorityGraph | None,
        as_of: str | date | None,
        span_ids: set[str],
        span_by_id: Mapping[str, ExtractedSpan],
        span_texts: Mapping[str, str],
        classification: DisclosureClassification,
    ) -> ConsistencyComparisonEntry:
        comparison_id = f"cmp:{analysis_id}:{seq:04d}"
        local_reasons: list[str] = []
        resolutions: list[AuthorityResolutionDetail] = []
        competing: list[CompetingAuthorityDetail] = []
        quotes: list[QuoteComparisonDetail] = []
        counter_spans: list[ExactTextSpanRef] = []

        surface = source.instruction_surface_text[
            : self.bounds.max_surface
        ]
        digest = source.instruction_text_digest or _text_digest(surface)

        # Prefer exact span text from index when available (government text).
        if source.source_span_id in span_texts:
            indexed = span_texts[source.source_span_id]
            if indexed and _text_digest(indexed) == digest:
                surface = indexed[: self.bounds.max_surface]
            elif indexed:
                # Indexed body differs; keep source surface but note uncertainty.
                local_reasons.append(ConsistencyReasonCode.SPAN_INDEX_MISS.value)
        elif span_ids and source.source_span_id not in span_ids:
            local_reasons.append(ConsistencyReasonCode.SPAN_INDEX_MISS.value)

        # Collect citation targets.
        targets = list(source.legal_citations)
        if not targets:
            try:
                parsed = parse_patent_citations(surface)
                for p in parsed:
                    if p.surface:
                        targets.append(p.surface)
            except Exception:
                pass
        if not targets and source.citation_keys:
            targets = list(source.citation_keys)

        if not targets:
            local_reasons.append(ConsistencyReasonCode.NO_CITATIONS.value)

        # Quotes the examiner attributes to authority (exact, not model summary).
        quote_texts: list[str] = []
        if source.quoted_authority_text:
            quote_texts.append(source.quoted_authority_text)
        for frag in extract_quoted_fragments(surface):
            if frag not in quote_texts:
                quote_texts.append(frag)

        # Independent resolution of each citation.
        any_exact = False
        any_unresolved = False
        any_ambiguous = False
        any_missing_version = False
        any_quote_mismatch = False
        any_quote_match = False
        any_competing = False

        if graph is None and not targets:
            any_unresolved = True
            local_reasons.append(ConsistencyReasonCode.NO_AUTHORITY_GRAPH.value)
        elif graph is None:
            any_unresolved = True
            local_reasons.append(ConsistencyReasonCode.NO_AUTHORITY_GRAPH.value)
            for t in targets[:32]:
                resolutions.append(
                    AuthorityResolutionDetail(
                        citation_surface=t,
                        citation_key=None,
                        match_kind=CitationMatchKind.UNRESOLVED.value,
                        node_id=None,
                        version=None,
                        edition=None,
                        authority_tier=None,
                        verification_state=None,
                        authority_text_excerpt="",
                        authority_span=None,
                        is_binding=None,
                        reasons=("no_authority_graph",),
                    )
                )
        else:
            local_reasons.append(
                ConsistencyReasonCode.INDEPENDENT_RESOLUTION.value
            )
            for target in targets[:32]:
                quote_for_resolve = quote_texts[0] if quote_texts else None
                try:
                    result = self.resolver.resolve(
                        target,
                        as_of=as_of,
                        quoted_text=quote_for_resolve,
                        graph=graph,
                    )
                except Exception as exc:
                    any_unresolved = True
                    resolutions.append(
                        AuthorityResolutionDetail(
                            citation_surface=target,
                            citation_key=None,
                            match_kind=CitationMatchKind.UNRESOLVED.value,
                            node_id=None,
                            version=None,
                            edition=None,
                            authority_tier=None,
                            verification_state=None,
                            authority_text_excerpt="",
                            authority_span=None,
                            is_binding=None,
                            reasons=(f"resolve_error:{type(exc).__name__}",),
                        )
                    )
                    local_reasons.append(
                        ConsistencyReasonCode.AUTHORITY_UNRESOLVED.value
                    )
                    continue

                detail, comp_list, quote_detail = self._detail_from_resolution(
                    target=target,
                    result=result,
                    graph=graph,
                    quote_texts=quote_texts,
                    quoted_span_id=source.quoted_authority_span_id,
                )
                resolutions.append(detail)
                competing.extend(comp_list)
                if quote_detail is not None:
                    quotes.append(quote_detail)

                if detail.match_kind == CitationMatchKind.EXACT.value:
                    any_exact = True
                    local_reasons.append(
                        ConsistencyReasonCode.AUTHORITY_RESOLVED.value
                    )
                elif detail.match_kind == CitationMatchKind.AMBIGUOUS.value:
                    any_ambiguous = True
                    local_reasons.append(
                        ConsistencyReasonCode.AUTHORITY_AMBIGUOUS.value
                    )
                else:
                    any_unresolved = True
                    local_reasons.append(
                        ConsistencyReasonCode.AUTHORITY_UNRESOLVED.value
                    )

                if not detail.has_exact_version and detail.node_id:
                    any_missing_version = True
                    local_reasons.append(
                        ConsistencyReasonCode.MISSING_VERSION.value
                    )

                if comp_list:
                    any_competing = True
                    local_reasons.append(
                        ConsistencyReasonCode.AUTHORITY_COMPETING.value
                    )

                if quote_detail is not None:
                    if quote_detail.status == QuoteMatchStatus.MISMATCH.value:
                        any_quote_mismatch = True
                        local_reasons.append(
                            ConsistencyReasonCode.QUOTE_MISMATCH.value
                        )
                        if quote_detail.source_span is not None:
                            counter_spans.append(quote_detail.source_span)
                        if quote_detail.quoted_span is not None:
                            counter_spans.append(quote_detail.quoted_span)
                    elif quote_detail.status == QuoteMatchStatus.MATCH.value:
                        any_quote_match = True
                        local_reasons.append(
                            ConsistencyReasonCode.QUOTE_MATCH.value
                        )
                    elif quote_detail.status == QuoteMatchStatus.NO_SOURCE.value:
                        local_reasons.append(
                            ConsistencyReasonCode.QUOTE_NO_SOURCE.value
                        )
                    elif quote_detail.status == QuoteMatchStatus.NO_QUOTE.value:
                        local_reasons.append(
                            ConsistencyReasonCode.QUOTE_NO_QUOTE.value
                        )

        # Additional quote comparisons against resolved nodes when not already done.
        if quote_texts and resolutions and not quotes:
            for qt in quote_texts:
                for res in resolutions:
                    if not res.authority_text_excerpt and res.authority_span is None:
                        continue
                    source_for_cmp: str | ExactTextSpanRef | None
                    if res.authority_span is not None and res.authority_span.text:
                        source_for_cmp = res.authority_span.text
                    else:
                        source_for_cmp = res.authority_text_excerpt or None
                    if not source_for_cmp:
                        continue
                    qcmp = compare_quote_to_source(qt, source_for_cmp)
                    qd = self._quote_detail_from_comparison(
                        qcmp,
                        quoted_span_id=source.quoted_authority_span_id,
                        authority_node_id=res.node_id,
                        authority_sha=(
                            res.authority_span.artifact_sha256
                            if res.authority_span
                            else None
                        ),
                    )
                    quotes.append(qd)
                    if qd.status == QuoteMatchStatus.MISMATCH.value:
                        any_quote_mismatch = True
                        local_reasons.append(
                            ConsistencyReasonCode.QUOTE_MISMATCH.value
                        )
                        if qd.source_span is not None:
                            counter_spans.append(qd.source_span)
                        if qd.quoted_span is not None:
                            counter_spans.append(qd.quoted_span)
                    elif qd.status == QuoteMatchStatus.MATCH.value:
                        any_quote_match = True
                        local_reasons.append(
                            ConsistencyReasonCode.QUOTE_MATCH.value
                        )
                    break  # one comparison per quote is enough

        # Status decision (fail-closed, never unlawful).
        if any_quote_mismatch:
            status = ConsistencyStatus.POTENTIAL_INCONSISTENCY
            local_reasons.append(
                ConsistencyReasonCode.STATUS_POTENTIAL_INCONSISTENCY.value
            )
        elif any_competing and any_ambiguous:
            # Competing authorities with ambiguity: show them, status unknown
            # unless quote already mismatched.
            status = ConsistencyStatus.UNKNOWN
            local_reasons.append(ConsistencyReasonCode.STATUS_UNKNOWN.value)
        elif any_unresolved or any_missing_version or (
            not any_exact and not resolutions
        ):
            status = ConsistencyStatus.UNKNOWN
            local_reasons.append(ConsistencyReasonCode.STATUS_UNKNOWN.value)
        elif any_ambiguous and not any_exact:
            status = ConsistencyStatus.UNKNOWN
            local_reasons.append(ConsistencyReasonCode.STATUS_UNKNOWN.value)
        elif any_exact and (not quote_texts or any_quote_match or not quotes):
            # Exact resolution; no quote to contradict, or quotes matched.
            # If quotes exist but none compared (empty authority text), unknown.
            if quote_texts and not quotes and not any_quote_match:
                status = ConsistencyStatus.UNKNOWN
                local_reasons.append(ConsistencyReasonCode.STATUS_UNKNOWN.value)
            else:
                status = ConsistencyStatus.CONSISTENT
                local_reasons.append(
                    ConsistencyReasonCode.STATUS_CONSISTENT.value
                )
        else:
            status = ConsistencyStatus.UNKNOWN
            local_reasons.append(ConsistencyReasonCode.STATUS_UNKNOWN.value)

        # Competing with different content fingerprints can elevate to
        # potential_inconsistency when two exact versions disagree on text
        # and the instruction attributes one of them via quote mismatch path
        # already handled. When instruction has no quote but competing nodes
        # differ, remain unknown (uncertainty shown via competing_authorities).

        authority_versions = tuple(
            dict.fromkeys(
                v
                for r in resolutions
                for v in (r.version, r.edition)
                if v
            )
        )
        authority_node_ids = tuple(
            dict.fromkeys(r.node_id for r in resolutions if r.node_id)
        )
        citation_surfaces = tuple(
            dict.fromkeys(r.citation_surface for r in resolutions if r.citation_surface)
            or targets
        )

        # For potential_inconsistency without counter spans yet, attach
        # authority spans so the flag remains reproducible.
        if (
            status is ConsistencyStatus.POTENTIAL_INCONSISTENCY
            and not counter_spans
        ):
            for r in resolutions:
                if r.authority_span is not None:
                    counter_spans.append(r.authority_span)
                elif r.authority_text_excerpt:
                    counter_spans.append(
                        ExactTextSpanRef(
                            span_id=r.node_id,
                            artifact_id=None,
                            text=r.authority_text_excerpt,
                            text_digest=_text_digest(r.authority_text_excerpt),
                            start_offset=0,
                            end_offset=len(r.authority_text_excerpt),
                            artifact_sha256=None,
                            section=r.citation_key,
                            role="counter",
                        )
                    )

        # Ensure potential_inconsistency always has authority version/node.
        if status is ConsistencyStatus.POTENTIAL_INCONSISTENCY:
            if not authority_versions and not authority_node_ids:
                # Cannot claim potential inconsistency without authority anchor.
                status = ConsistencyStatus.UNKNOWN
                local_reasons.append(ConsistencyReasonCode.STATUS_UNKNOWN.value)
                local_reasons.append(ConsistencyReasonCode.MISSING_VERSION.value)

        applicability_facts = list(source.applicability_conditions)
        if as_of is not None:
            as_of_s = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
            applicability_facts.append(f"as_of:{as_of_s}")
        if graph is not None:
            applicability_facts.append(
                f"authority_graph:{getattr(graph, 'graph_id', 'present')}"
            )
        if applicability_facts:
            local_reasons.append(
                ConsistencyReasonCode.APPLICABILITY_RECORDED.value
            )

        assumptions = list(source.assumptions)
        if not as_of:
            assumptions.append("as_of_not_provided")
        if graph is None:
            assumptions.append("authority_graph_absent")
        if assumptions:
            local_reasons.append(ConsistencyReasonCode.ASSUMPTIONS_RECORDED.value)

        requires_review = status is not ConsistencyStatus.CONSISTENT
        review_state = (
            ReviewState.REQUIRED
            if requires_review
            else ReviewState.NOT_REQUIRED
        )
        if requires_review:
            local_reasons.append(
                ConsistencyReasonCode.HUMAN_REVIEW_REQUIRED.value
            )

        human_q = build_human_review_question(
            instruction_span_id=source.source_span_id,
            citation_surfaces=citation_surfaces,
            authority_versions=authority_versions,
            authority_node_ids=authority_node_ids,
            status=status,
        )

        # Deduplicate reasons.
        local_reasons = list(dict.fromkeys(local_reasons))

        # Deduplicate counter spans by digest.
        seen_digests: set[str] = set()
        unique_counters: list[ExactTextSpanRef] = []
        for cs in counter_spans:
            if cs.text_digest in seen_digests:
                continue
            seen_digests.add(cs.text_digest)
            unique_counters.append(cs)

        return ConsistencyComparisonEntry(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            comparison_id=comparison_id,
            source_id=source.source_id,
            instruction_span_id=source.source_span_id,
            instruction_surface_text=surface,
            instruction_text_digest=digest,
            status=status,
            authority_resolutions=tuple(resolutions),
            competing_authorities=tuple(competing),
            quote_comparisons=tuple(quotes),
            applicability_facts=tuple(applicability_facts),
            assumptions=tuple(assumptions),
            human_review_question=human_q,
            reason_codes=tuple(local_reasons),
            counter_source_spans=tuple(unique_counters),
            authority_versions=authority_versions,
            authority_node_ids=authority_node_ids,
            citation_surfaces=tuple(citation_surfaces),
            requires_human_review=requires_review,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            review_state=review_state,
            classification=source.classification
            if source.classification is not DisclosureClassification.UNKNOWN
            else classification,
            labels=dict(source.labels),
        )

    def _detail_from_resolution(
        self,
        *,
        target: str,
        result: CitationResolutionResult,
        graph: PatentTemporalAuthorityGraph,
        quote_texts: Sequence[str],
        quoted_span_id: str | None,
    ) -> tuple[
        AuthorityResolutionDetail,
        list[CompetingAuthorityDetail],
        QuoteComparisonDetail | None,
    ]:
        node: AuthorityTextNode | None = None
        node_id = result.selected_node_id
        if node_id and hasattr(graph, "node_by_id"):
            node = graph.node_by_id.get(node_id)
        if node is None and node_id:
            for n in getattr(graph, "nodes", ()):
                if getattr(n, "node_id", None) == node_id:
                    node = n
                    break

        excerpt = ""
        auth_span: ExactTextSpanRef | None = None
        is_binding: bool | None = None
        if node is not None:
            excerpt = (node.text_excerpt or "")[: self.bounds.max_excerpt]
            is_binding = bool(node.is_binding)
            if node.span is not None and isinstance(node.span, AuthoritySpan):
                quote = node.span.quote or excerpt
                start = (
                    0
                    if node.span.start_offset is None
                    else node.span.start_offset
                )
                end = (
                    start + len(quote)
                    if node.span.end_offset is None
                    else node.span.end_offset
                )
                sha = node.span.artifact_sha256
                if sha is None and node.official_artifact is not None:
                    sha = node.official_artifact.artifact_sha256
                auth_span = ExactTextSpanRef(
                    span_id=node.node_id,
                    artifact_id=None,
                    text=quote[: self.bounds.max_excerpt],
                    text_digest=_text_digest(quote) if quote else sha256_hex(""),
                    start_offset=start,
                    end_offset=end,
                    artifact_sha256=sha,
                    section=node.span.section or node.citation_key,
                    role="authority",
                )
            elif excerpt:
                auth_span = ExactTextSpanRef(
                    span_id=node.node_id,
                    artifact_id=None,
                    text=excerpt,
                    text_digest=_text_digest(excerpt),
                    start_offset=0,
                    end_offset=len(excerpt),
                    artifact_sha256=(
                        node.official_artifact.artifact_sha256
                        if node.official_artifact is not None
                        else None
                    ),
                    section=node.citation_key,
                    role="authority",
                )

        reasons: list[str] = []
        for d in result.diagnostics or ():
            code = getattr(d, "code", None)
            if code is not None:
                reasons.append(
                    code.value if hasattr(code, "value") else str(code)
                )

        detail = AuthorityResolutionDetail(
            citation_surface=target,
            citation_key=result.selected_citation_key
            or (result.parsed.citation_key if result.parsed else None),
            match_kind=result.match_kind.value
            if hasattr(result.match_kind, "value")
            else str(result.match_kind),
            node_id=node_id,
            version=result.selected_version,
            edition=result.selected_edition,
            authority_tier=(
                result.authority_tier.value
                if result.authority_tier is not None
                and hasattr(result.authority_tier, "value")
                else (
                    str(result.authority_tier)
                    if result.authority_tier is not None
                    else None
                )
            ),
            verification_state=(
                result.verification_state.value
                if result.verification_state is not None
                and hasattr(result.verification_state, "value")
                else (
                    str(result.verification_state)
                    if result.verification_state is not None
                    else None
                )
            ),
            authority_text_excerpt=excerpt,
            authority_span=auth_span,
            is_binding=is_binding,
            reasons=tuple(dict.fromkeys(reasons)),
        )

        competing: list[CompetingAuthorityDetail] = []
        as_of_res = result.as_of_resolution
        if as_of_res is not None:
            for c in as_of_res.competing_sources or ():
                cnode = None
                if hasattr(graph, "node_by_id"):
                    cnode = graph.node_by_id.get(c.node_id)
                c_excerpt = ""
                if cnode is not None:
                    c_excerpt = (cnode.text_excerpt or "")[: self.bounds.max_excerpt]
                competing.append(
                    CompetingAuthorityDetail(
                        node_id=c.node_id,
                        citation_key=getattr(cnode, "citation_key", None)
                        if cnode
                        else None,
                        citation=c.citation,
                        version=c.version,
                        edition=getattr(cnode, "edition", None) if cnode else None,
                        authority_tier=(
                            c.authority_tier.value
                            if hasattr(c.authority_tier, "value")
                            else str(c.authority_tier)
                        ),
                        authority_text_excerpt=c_excerpt,
                        reason=c.reason or "competing",
                        content_fingerprint=c.content_fingerprint,
                    )
                )
            # Also surface candidate node ids when ambiguous.
            for cid in result.candidate_node_ids or ():
                if cid == node_id:
                    continue
                if any(x.node_id == cid for x in competing):
                    continue
                cnode = (
                    graph.node_by_id.get(cid)
                    if hasattr(graph, "node_by_id")
                    else None
                )
                if cnode is None:
                    continue
                competing.append(
                    CompetingAuthorityDetail(
                        node_id=cnode.node_id,
                        citation_key=cnode.citation_key,
                        citation=cnode.citation,
                        version=cnode.version,
                        edition=cnode.edition,
                        authority_tier=(
                            cnode.authority_tier.value
                            if hasattr(cnode.authority_tier, "value")
                            else str(cnode.authority_tier)
                        ),
                        authority_text_excerpt=(cnode.text_excerpt or "")[
                            : self.bounds.max_excerpt
                        ],
                        reason="candidate",
                        content_fingerprint=getattr(
                            cnode, "content_fingerprint", None
                        ),
                    )
                )

        quote_detail: QuoteComparisonDetail | None = None
        if result.quote_comparison is not None:
            quote_detail = self._quote_detail_from_comparison(
                result.quote_comparison,
                quoted_span_id=quoted_span_id,
                authority_node_id=node_id,
                authority_sha=(
                    auth_span.artifact_sha256 if auth_span is not None else None
                ),
            )
        elif quote_texts and (excerpt or auth_span is not None):
            source_text = (
                auth_span.text
                if auth_span is not None and auth_span.text
                else excerpt
            )
            qcmp = compare_quote_to_source(quote_texts[0], source_text)
            quote_detail = self._quote_detail_from_comparison(
                qcmp,
                quoted_span_id=quoted_span_id,
                authority_node_id=node_id,
                authority_sha=(
                    auth_span.artifact_sha256 if auth_span is not None else None
                ),
            )

        return detail, competing, quote_detail

    def _quote_detail_from_comparison(
        self,
        qcmp: QuoteComparison,
        *,
        quoted_span_id: str | None,
        authority_node_id: str | None,
        authority_sha: str | None,
    ) -> QuoteComparisonDetail:
        quoted_ref: ExactTextSpanRef | None = None
        source_ref: ExactTextSpanRef | None = None

        if qcmp.quoted_span is not None:
            qs = qcmp.quoted_span
            quoted_ref = ExactTextSpanRef(
                span_id=quoted_span_id,
                artifact_id=None,
                text=qs.text or "",
                text_digest=_text_digest(qs.text or ""),
                start_offset=qs.start,
                end_offset=qs.end,
                artifact_sha256=qs.artifact_sha256,
                section=qs.section,
                role="quoted_attribution",
            )
        elif qcmp.normalized_quoted:
            quoted_ref = ExactTextSpanRef(
                span_id=quoted_span_id,
                artifact_id=None,
                text=qcmp.normalized_quoted,
                text_digest=_text_digest(qcmp.normalized_quoted),
                start_offset=0,
                end_offset=len(qcmp.normalized_quoted),
                artifact_sha256=None,
                section=None,
                role="quoted_attribution",
            )

        if qcmp.source_span is not None:
            ss = qcmp.source_span
            source_ref = ExactTextSpanRef(
                span_id=authority_node_id,
                artifact_id=None,
                text=ss.text or "",
                text_digest=_text_digest(ss.text or ""),
                start_offset=ss.start,
                end_offset=ss.end,
                artifact_sha256=ss.artifact_sha256 or authority_sha,
                section=ss.section,
                role="authority",
            )
        elif qcmp.normalized_source:
            source_ref = ExactTextSpanRef(
                span_id=authority_node_id,
                artifact_id=None,
                text=qcmp.normalized_source,
                text_digest=_text_digest(qcmp.normalized_source),
                start_offset=0,
                end_offset=len(qcmp.normalized_source),
                artifact_sha256=authority_sha,
                section=None,
                role="authority",
            )

        status = (
            qcmp.status.value
            if hasattr(qcmp.status, "value")
            else str(qcmp.status)
        )
        # Ensure mismatch always has both spans (acceptance / QuoteComparison).
        if status == QuoteMatchStatus.MISMATCH.value:
            if quoted_ref is None:
                quoted_ref = ExactTextSpanRef(
                    span_id=quoted_span_id,
                    artifact_id=None,
                    text=qcmp.normalized_quoted or "",
                    text_digest=_text_digest(qcmp.normalized_quoted or ""),
                    start_offset=0,
                    end_offset=len(qcmp.normalized_quoted or ""),
                    artifact_sha256=None,
                    section=None,
                    role="quoted_attribution",
                )
            if source_ref is None:
                source_ref = ExactTextSpanRef(
                    span_id=authority_node_id,
                    artifact_id=None,
                    text=qcmp.normalized_source or "",
                    text_digest=_text_digest(qcmp.normalized_source or ""),
                    start_offset=0,
                    end_offset=len(qcmp.normalized_source or ""),
                    artifact_sha256=authority_sha,
                    section=None,
                    role="authority",
                )

        detail = qcmp.detail or "quote comparison"
        # Sanitize any accidental unlawful language in upstream detail.
        if contains_forbidden_unlawful_token(detail):
            detail = "quoted text does not match source span; both spans exposed"

        return QuoteComparisonDetail(
            status=status,
            quoted_span=quoted_ref,
            source_span=source_ref,
            match_ratio=qcmp.match_ratio,
            detail=detail,
        )

    def _disposition(
        self,
        *,
        comparisons: Sequence[ConsistencyComparisonEntry],
        classification: DisclosureClassification,
    ) -> tuple[ConsistencyDisposition, ReviewState]:
        if requires_quarantine(classification):
            return ConsistencyDisposition.QUARANTINE, ReviewState.REQUIRED
        if not comparisons:
            return ConsistencyDisposition.EMPTY, ReviewState.PENDING
        statuses = {c.status for c in comparisons}
        if ConsistencyStatus.POTENTIAL_INCONSISTENCY in statuses:
            return ConsistencyDisposition.REVIEW, ReviewState.REQUIRED
        if ConsistencyStatus.UNKNOWN in statuses:
            if ConsistencyStatus.CONSISTENT in statuses:
                return ConsistencyDisposition.PARTIAL, ReviewState.REQUIRED
            return ConsistencyDisposition.UNKNOWN, ReviewState.REQUIRED
        return ConsistencyDisposition.COMPARED, ReviewState.NOT_REQUIRED

    def _content_digest(
        self, comparisons: Sequence[ConsistencyComparisonEntry]
    ) -> str:
        payload = {
            "comparisons": [
                {
                    "id": c.comparison_id,
                    "instruction_digest": c.instruction_text_digest,
                    "status": c.status.value,
                    "versions": list(c.authority_versions),
                    "nodes": list(c.authority_node_ids),
                }
                for c in comparisons
            ],
            "schema": INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            "ruleset": INSTRUCTION_CONSISTENCY_RULESET_VERSION,
        }
        return sha256_hex(canonical_json(payload))

    def _terminal(
        self,
        *,
        analysis_id: str,
        inp: InstructionConsistencyInput,
        disposition: ConsistencyDisposition,
        review_state: ReviewState,
        reason_codes: Sequence[str],
        warnings: Sequence[str],
        classification: DisclosureClassification,
    ) -> InstructionConsistencyResult:
        as_of = inp.as_of or inp.mailing_date
        as_of_str = (
            as_of.isoformat()
            if isinstance(as_of, date)
            else (str(as_of) if as_of else None)
        )
        graph = self.graph or getattr(self.resolver, "graph", None)
        graph_id = getattr(graph, "graph_id", None) if graph is not None else None
        return InstructionConsistencyResult(
            schema_version=INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            analysis_id=analysis_id,
            source_artifact_id=inp.artifact_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            output_kind=OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON,
            disclaimer=NOT_UNLAWFUL_DETERMINATION_DISCLAIMER,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            comparisons=(),
            consistent_count=0,
            potential_inconsistency_count=0,
            unknown_count=0,
            ruleset_versions={
                "instruction_consistency": INSTRUCTION_CONSISTENCY_RULESET_VERSION,
                "instruction_consistency_processor": (
                    INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
                ),
                "contracts": CONTRACTS_SCHEMA_VERSION,
            },
            authority_graph_id=graph_id if isinstance(graph_id, str) else None,
            as_of=as_of_str,
            labels=dict(inp.labels),
            text_digest=sha256_hex(""),
        )


def compare_instructions(
    value: (
        InstructionConsistencyInput
        | RequirementCompilationResult
        | OfficeActionResult
        | Mapping[str, Any]
        | None
    ) = None,
    /,
    **kwargs: Any,
) -> InstructionConsistencyResult:
    """Module-level convenience wrapper around :class:`InstructionConsistencyProcessor`."""
    graph = kwargs.pop("graph", None)
    citation_resolver = kwargs.pop("citation_resolver", None)
    id_factory = kwargs.pop("id_factory", None)
    bounds = kwargs.pop("bounds", None)
    return InstructionConsistencyProcessor(
        graph=graph,
        citation_resolver=citation_resolver,
        id_factory=id_factory,
        bounds=bounds,
    ).compare(value, **kwargs)


def sources_from_requirement_compilation(
    result: RequirementCompilationResult,
) -> tuple[InstructionSourceInput, ...]:
    """Project compiled predicates into instruction sources."""
    return tuple(
        InstructionSourceInput.from_compiled_predicate(
            p, artifact_id=result.source_artifact_id
        )
        for p in result.predicates
    )


def sources_from_office_action(
    result: OfficeActionResult,
) -> tuple[InstructionSourceInput, ...]:
    """Project office-action instruction candidates into instruction sources."""
    return tuple(
        InstructionSourceInput.from_analysis_candidate(
            c,
            artifact_id=result.artifact_id,
            action_id=result.action_id,
            classification=result.classification,
        )
        for c in result.candidates
        if c.kind in _INSTRUCTION_CANDIDATE_KINDS
    )


__all__ = [
    "INSTRUCTION_CONSISTENCY_INTERFACE",
    "INSTRUCTION_CONSISTENCY_RULESET_VERSION",
    "INSTRUCTION_CONSISTENCY_SCHEMA_VERSION",
    "NOT_UNLAWFUL_DETERMINATION_DISCLAIMER",
    "OUTPUT_KIND_INSTRUCTION_AUTHORITY_COMPARISON",
    "AnalysisBounds",
    "AuthorityResolutionDetail",
    "CompetingAuthorityDetail",
    "ConsistencyComparisonEntry",
    "ConsistencyDisposition",
    "ConsistencyReasonCode",
    "ConsistencyStatus",
    "ExactTextSpanRef",
    "InstructionConsistencyError",
    "InstructionConsistencyInput",
    "InstructionConsistencyProcessor",
    "InstructionConsistencyResult",
    "InstructionSourceInput",
    "QuoteComparisonDetail",
    "build_human_review_question",
    "compare_instructions",
    "contains_forbidden_unlawful_token",
    "extract_quoted_fragments",
    "sanitize_labels",
    "sha256_hex",
    "sources_from_office_action",
    "sources_from_requirement_compilation",
]
