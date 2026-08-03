"""Resolve and validate patent-law citations and quotations.

Parses and resolves 35 U.S.C., 37 C.F.R., Federal Register, MPEP,
form-paragraph, form, fee, and Examination Guide references against the
temporal authority graph (PATLAW-016), then compares quoted text to the
exact temporal source span.

Design invariants (PATLAW-017 / source-authority policy):

* Exact and ambiguous citations always produce **typed** results — never a
  bare string or untyped dict.
* Quote mismatch exposes **both** the quoted span and the source span.
* Unresolved version or missing source identity never becomes
  ``VerificationState.VERIFIED``.
* Authority tier is independent of relevance and confidence scores; tier
  ranking never elevates guidance over statute/regulation via score math.
* Composition only: reuses PATLAW-016 as-of resolution and PATLAW-011
  authority tiers; does not rewrite the temporal graph or connectors.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    SCHEMA_VERSION as AUTHORITY_REGISTRY_SCHEMA_VERSION,
    AsOfQuery,
    AsOfResolution,
    AsOfViewRole,
    AuthoritySpan,
    AuthorityTextNode,
    AuthorityViewKind,
    PatentTemporalAuthorityGraph,
    ResolutionStatus,
    resolve_as_of,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    VerificationState,
    _require_non_empty_str,
    canonical_json_dumps,
    reject_hard_coded_latest,
)


SCHEMA_VERSION = "patent-citation-resolver-v1"

# Whitespace and soft-hyphen normalization for quote comparison.
_WS_RE = re.compile(r"\s+")
_SOFT_HYPHEN = "\u00ad"
_QUOTE_STRIP_CHARS = "\"'“”‘’«»"


# ---------------------------------------------------------------------------
# Errors and enums
# ---------------------------------------------------------------------------


class PatentCitationResolverError(ValueError):
    """Base error for patent citation resolution failures."""


class CitationFamily(str, Enum):
    """Closed set of patent-law citation families handled by this resolver."""

    USC = "usc"
    CFR = "cfr"
    FEDERAL_REGISTER = "federal_register"
    MPEP = "mpep"
    FORM_PARAGRAPH = "form_paragraph"
    FORM = "form"
    FEE = "fee"
    EXAMINATION_GUIDE = "examination_guide"
    PUBLIC_LAW = "public_law"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> "CitationFamily":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "uscode": cls.USC,
            "u_s_c": cls.USC,
            "statute": cls.USC,
            "c_f_r": cls.CFR,
            "regulation": cls.CFR,
            "fr": cls.FEDERAL_REGISTER,
            "fed_reg": cls.FEDERAL_REGISTER,
            "fedreg": cls.FEDERAL_REGISTER,
            "federalregister": cls.FEDERAL_REGISTER,
            "mpep_section": cls.MPEP,
            "fp": cls.FORM_PARAGRAPH,
            "formparagraph": cls.FORM_PARAGRAPH,
            "pto_form": cls.FORM,
            "uspto_form": cls.FORM,
            "fee_schedule": cls.FEE,
            "fees": cls.FEE,
            "exam_guide": cls.EXAMINATION_GUIDE,
            "examinationguide": cls.EXAMINATION_GUIDE,
            "guide": cls.EXAMINATION_GUIDE,
            "pl": cls.PUBLIC_LAW,
            "pub_l": cls.PUBLIC_LAW,
            "publiclaw": cls.PUBLIC_LAW,
        }
        if text in aliases:
            return aliases[text]
        for family in cls:
            if family.value == text or family.name.lower() == text:
                return family
        raise PatentCitationResolverError(f"unsupported citation family: {value!r}")


class CitationMatchKind(str, Enum):
    """Typed outcome of parsing / candidate selection for a citation."""

    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    PARTIAL = "partial"

    @classmethod
    def coerce(cls, value: Any) -> "CitationMatchKind":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        raise PatentCitationResolverError(f"unsupported citation match kind: {value!r}")


class QuoteMatchStatus(str, Enum):
    """Outcome of comparing a quotation to a source span."""

    MATCH = "match"
    MISMATCH = "mismatch"
    NO_QUOTE = "no_quote"
    NO_SOURCE = "no_source"
    SOURCE_UNRESOLVED = "source_unresolved"

    @classmethod
    def coerce(cls, value: Any) -> "QuoteMatchStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for status in cls:
            if status.value == text or status.name.lower() == text:
                return status
        raise PatentCitationResolverError(f"unsupported quote match status: {value!r}")


class CitationDiagnosticCode(str, Enum):
    """Typed diagnostics for citation resolution and quote validation."""

    EXACT_MATCH = "exact_match"
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"
    UNRESOLVED_CITATION = "unresolved_citation"
    UNRESOLVED_VERSION = "unresolved_version"
    UNRESOLVED_SOURCE = "unresolved_source"
    AS_OF_UNKNOWN = "as_of_unknown"
    QUOTE_MATCH = "quote_match"
    QUOTE_MISMATCH = "quote_mismatch"
    QUOTE_NO_SOURCE = "quote_no_source"
    HARD_CODED_LATEST = "hard_coded_latest"
    TIER_INDEPENDENT_OF_SCORE = "tier_independent_of_score"
    VERIFICATION_BLOCKED = "verification_blocked"
    PARSE_EMPTY = "parse_empty"
    MULTIPLE_FAMILIES = "multiple_families"


# ---------------------------------------------------------------------------
# Citation regex patterns (patent-focused; compose with generic extractors)
# ---------------------------------------------------------------------------

# 35 U.S.C. § 102(a)(1) — capture optional subsections after the base section.
_USC_RE = re.compile(
    r"(?P<raw>"
    r"(?P<title>\d+)\s*"
    r"U\.?\s*S\.?\s*C\.?(?:A\.?)?\s*"
    r"(?:§+|section|sec\.?)?\s*"
    r"(?P<section>\d+[A-Za-z0-9\-]*)"
    r"(?P<subsections>(?:\s*\([a-z0-9]+\))*)"
    r")",
    re.IGNORECASE,
)

# 37 C.F.R. § 1.56(a) — title + dotted section with optional parentheticals.
_CFR_RE = re.compile(
    r"(?P<raw>"
    r"(?P<title>\d+)\s*"
    r"C\.?\s*F\.?\s*R\.?\s*"
    r"(?:§+|section|sec\.?)?\s*"
    r"(?P<section>\d+(?:\.\d+[A-Za-z0-9\-]*)*)"
    r"(?P<subsections>(?:\s*\([a-z0-9]+\))*)"
    r")",
    re.IGNORECASE,
)

# 87 FR 12345 / 87 Fed. Reg. 12345
_FR_RE = re.compile(
    r"(?P<raw>"
    r"(?P<volume>\d+)\s+"
    r"(?:FR|Fed\.?\s+Reg\.?|Fed\.?\s+Register|Federal\s+Register)\s+"
    r"(?P<page>\d+)"
    r")",
    re.IGNORECASE,
)

# MPEP § 2106.04(a) / MPEP 2106
_MPEP_RE = re.compile(
    r"(?P<raw>"
    r"M\.?\s*P\.?\s*E\.?\s*P\.?\s*"
    r"(?:§+|section|sec\.?)?\s*"
    r"(?P<section>\d+[A-Za-z0-9.\-]*)"
    r"(?P<subsections>(?:\s*\([a-z0-9]+\))*)?"
    r")",
    re.IGNORECASE,
)

# Form paragraph FP 7.05 / ¶7.05 / form paragraph 7.05.01
_FORM_PARAGRAPH_RE = re.compile(
    r"(?P<raw>"
    r"(?:form\s*paragraph|FP|¶)\s*[#:]?\s*"
    r"(?P<fp>\d+(?:\.\d+)*)"
    r")",
    re.IGNORECASE,
)

# PTO/SB/08a, Form AIA/01, USPTO Form SB/08
_FORM_RE = re.compile(
    r"(?P<raw>"
    r"(?:(?:USPTO|PTO)\s+)?(?:Form\s+)?"
    r"(?P<form_id>"
    r"(?:PTO|SB|AIA|PTOL|PCT)(?:/[A-Za-z0-9]+)+"
    r"|(?:PTO|SB|AIA|PTOL)-\d+[A-Za-z]?"
    r")"
    r")",
    re.IGNORECASE,
)

# Fee code 1201 / fee 1.16(a) / 37 CFR 1.16(a) fee — prefer explicit fee markers.
_FEE_RE = re.compile(
    r"(?P<raw>"
    r"(?:fee\s*(?:code)?|fee\s*schedule)\s*[#:]?\s*"
    r"(?P<code>[A-Za-z0-9.\-]+(?:\([a-z0-9]+\))?)"
    r")",
    re.IGNORECASE,
)

# Examination Guide 1-22 / Exam. Guide 02-2019
_EXAM_GUIDE_RE = re.compile(
    r"(?P<raw>"
    r"(?:Examination|Exam\.?)\s+Guide\s+"
    r"(?P<guide_id>[A-Za-z0-9.\-/]+)"
    r")",
    re.IGNORECASE,
)

# Pub. L. 112-29
_PUBLIC_LAW_RE = re.compile(
    r"(?P<raw>"
    r"(?:Pub\.?\s*L\.?|P\.?\s*L\.?|Public\s+Law)\s+"
    r"(?:No\.?\s*)?"
    r"(?P<congress>\d+)-(?P<law>\d+)"
    r")",
    re.IGNORECASE,
)

# Optional edition/version tags near citations: (9th ed. Rev. 07.2022), (2018)
_EDITION_NEAR_RE = re.compile(
    r"\((?P<edition>"
    r"(?:\d+(?:st|nd|rd|th)\s+ed\.?(?:\s*,?\s*Rev\.?\s*[\d.]+)?)|"
    r"(?:ed(?:ition)?\.?\s*[\w.\-]+)|"
    r"(?:rev(?:ision)?\.?\s*[\w.\-]+)|"
    r"\d{4}"
    r")\)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clamp_score(value: Any, *, default: float = 0.0) -> float:
    """Clamp relevance/confidence into [0.0, 1.0] without affecting tier."""

    if value is None:
        return float(default)
    try:
        score = float(value)
    except (TypeError, ValueError):
        return float(default)
    if score != score:  # NaN
        return float(default)
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _parse_optional_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    raise PatentCitationResolverError(f"invalid date: {value!r}")


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def normalize_quote_text(text: str, *, collapse_ws: bool = True) -> str:
    """Normalize quote text for comparison (Unicode NFKC, soft hyphens, WS)."""

    if text is None:
        return ""
    cleaned = unicodedata.normalize("NFKC", str(text))
    cleaned = cleaned.replace(_SOFT_HYPHEN, "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    if collapse_ws:
        cleaned = _WS_RE.sub(" ", cleaned).strip()
    else:
        cleaned = cleaned.strip()
    # Strip matching outer quotation marks only.
    if len(cleaned) >= 2 and cleaned[0] in _QUOTE_STRIP_CHARS and cleaned[-1] in _QUOTE_STRIP_CHARS:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _parentheticals_to_suffix(subsections: Optional[str]) -> str:
    if not subsections:
        return ""
    parts = re.findall(r"\(([a-z0-9]+)\)", subsections, flags=re.IGNORECASE)
    if not parts:
        return ""
    return "".join(f"({p.lower()})" for p in parts)


def citation_key_for_usc(
    title: str | int,
    section: str,
    *,
    subsections: Optional[str] = None,
) -> str:
    """Build a stable citation key, e.g. ``35-usc-102(a)(1)``."""

    sec = str(section).strip()
    suffix = _parentheticals_to_suffix(subsections)
    return f"{int(title)}-usc-{sec}{suffix}".lower()


def citation_key_for_cfr(
    title: str | int,
    section: str,
    *,
    subsections: Optional[str] = None,
) -> str:
    """Build a stable citation key, e.g. ``37-cfr-1.56``."""

    sec = str(section).strip()
    suffix = _parentheticals_to_suffix(subsections)
    return f"{int(title)}-cfr-{sec}{suffix}".lower()


def citation_key_for_fr(volume: str | int, page: str | int) -> str:
    return f"{int(volume)}-fr-{int(page)}"


def citation_key_for_mpep(section: str, *, subsections: Optional[str] = None) -> str:
    sec = str(section).strip().lstrip("§").strip()
    sec = re.sub(r"\s+", "", sec)
    suffix = _parentheticals_to_suffix(subsections)
    return f"mpep-{sec}{suffix}".lower()


def citation_key_for_form_paragraph(fp: str) -> str:
    token = str(fp).strip().lstrip("#¶").strip()
    token = re.sub(r"^(?:fp|form\s*paragraph)\s*[#:]?\s*", "", token, flags=re.I)
    return f"fp-{token}".lower()


def citation_key_for_form(form_id: str) -> str:
    token = re.sub(r"\s+", "", str(form_id).strip()).upper().replace("_", "/")
    return f"form-{token.lower()}"


def citation_key_for_fee(code: str) -> str:
    token = str(code).strip().lower()
    return f"fee-{token}"


def citation_key_for_exam_guide(guide_id: str) -> str:
    token = str(guide_id).strip().lower().replace(" ", "-")
    return f"exam-guide-{token}"


def citation_key_for_public_law(congress: str | int, law: str | int) -> str:
    return f"pl-{int(congress)}-{int(law)}"


def default_authority_tier_for_family(family: CitationFamily | str) -> AuthorityTier:
    """Map citation family to the *default* authority tier (not a score).

    Statute / regulation families map to official tiers; guidance families map
    to ``GUIDANCE``. This is independent of relevance and confidence.
    """

    fam = CitationFamily.coerce(family)
    if fam is CitationFamily.USC or fam is CitationFamily.PUBLIC_LAW:
        return AuthorityTier.OFFICIAL_BASE
    if fam is CitationFamily.CFR:
        return AuthorityTier.OFFICIAL_BASE
    if fam is CitationFamily.FEDERAL_REGISTER:
        return AuthorityTier.OFFICIAL_CHANGE
    if fam in (
        CitationFamily.MPEP,
        CitationFamily.FORM_PARAGRAPH,
        CitationFamily.FORM,
        CitationFamily.FEE,
        CitationFamily.EXAMINATION_GUIDE,
    ):
        return AuthorityTier.GUIDANCE
    return AuthorityTier.CANDIDATE


def _edition_from_neighborhood(text: str, start: int, end: int) -> Optional[str]:
    window = text[max(0, start - 8) : min(len(text), end + 48)]
    match = _EDITION_NEAR_RE.search(window)
    if not match:
        return None
    edition = match.group("edition").strip()
    try:
        reject_hard_coded_latest(edition, field_name="edition")
    except Exception:
        return None
    return edition


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextSpan:
    """Character span into a host document or source artifact."""

    start: int
    end: int
    text: str
    artifact_sha256: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or self.start < 0:
            raise PatentCitationResolverError("start must be a non-negative int")
        if not isinstance(self.end, int) or self.end < self.start:
            raise PatentCitationResolverError("end must be an int >= start")
        object.__setattr__(self, "text", str(self.text) if self.text is not None else "")
        if self.artifact_sha256 is not None:
            sha = str(self.artifact_sha256).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise PatentCitationResolverError(
                    "artifact_sha256 must be a lowercase 64-char hex SHA-256"
                )
            object.__setattr__(self, "artifact_sha256", sha)
        if self.section is not None:
            object.__setattr__(
                self, "section", _require_non_empty_str(self.section, "section")
            )
        if not isinstance(self.metadata, Mapping):
            raise PatentCitationResolverError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "end": self.end,
            "line_end": self.line_end,
            "line_start": self.line_start,
            "metadata": _deep_sorted(self.metadata),
            "page": self.page,
            "section": self.section,
            "start": self.start,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TextSpan":
        if not isinstance(value, Mapping):
            raise PatentCitationResolverError("text span must be a mapping")
        return cls(
            start=int(value.get("start") or value.get("start_offset") or 0),
            end=int(value.get("end") or value.get("end_offset") or 0),
            text=str(value.get("text") or value.get("quote") or ""),
            artifact_sha256=value.get("artifact_sha256"),
            section=value.get("section"),
            page=value.get("page"),
            line_start=value.get("line_start"),
            line_end=value.get("line_end"),
            metadata=value.get("metadata") or {},
        )

    @classmethod
    def from_authority_span(
        cls,
        span: AuthoritySpan | Mapping[str, Any] | None,
        *,
        fallback_text: Optional[str] = None,
    ) -> Optional["TextSpan"]:
        if span is None:
            return None
        if isinstance(span, Mapping):
            span = AuthoritySpan.from_dict(span)
        if not isinstance(span, AuthoritySpan):
            raise PatentCitationResolverError("span must be AuthoritySpan or mapping")
        text = span.quote if span.quote is not None else (fallback_text or "")
        start = 0 if span.start_offset is None else span.start_offset
        end = start + len(text) if span.end_offset is None else span.end_offset
        if end < start:
            end = start + len(text)
        return cls(
            start=start,
            end=end,
            text=text,
            artifact_sha256=span.artifact_sha256,
            section=span.section,
            page=span.page,
            line_start=span.line_start,
            line_end=span.line_end,
            metadata=dict(span.metadata),
        )


@dataclass(frozen=True, slots=True)
class ParsedCitation:
    """A typed parse of one patent-law citation occurrence.

    ``match_kind`` is ``exact`` when the surface form uniquely identifies a
    citation key; ``ambiguous`` when multiple keys/candidates remain; and
    ``unresolved`` when the family cannot be determined.
    """

    raw_text: str
    family: CitationFamily
    match_kind: CitationMatchKind
    citation_key: Optional[str] = None
    normalized_text: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    subsections: Optional[str] = None
    volume: Optional[str] = None
    page: Optional[str] = None
    form_id: Optional[str] = None
    fee_code: Optional[str] = None
    guide_id: Optional[str] = None
    edition: Optional[str] = None
    version: Optional[str] = None
    start_pos: int = 0
    end_pos: int = 0
    # Scoring fields — deliberately separate from authority_tier.
    confidence: float = 0.0
    relevance: float = 0.0
    # Default tier expectation for the family (not derived from scores).
    authority_tier: Optional[AuthorityTier] = None
    candidate_keys: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "raw_text", _require_non_empty_str(self.raw_text, "raw_text")
        )
        object.__setattr__(self, "family", CitationFamily.coerce(self.family))
        object.__setattr__(self, "match_kind", CitationMatchKind.coerce(self.match_kind))
        object.__setattr__(self, "confidence", _clamp_score(self.confidence))
        object.__setattr__(self, "relevance", _clamp_score(self.relevance))
        if self.authority_tier is not None and not isinstance(
            self.authority_tier, AuthorityTier
        ):
            text = str(self.authority_tier).strip().lower().replace("_", "-")
            matched = None
            for tier in AuthorityTier:
                if tier.value == text:
                    matched = tier
                    break
            if matched is None:
                raise PatentCitationResolverError(
                    f"unknown authority_tier: {self.authority_tier!r}"
                )
            object.__setattr__(self, "authority_tier", matched)
        if self.edition is not None:
            reject_hard_coded_latest(self.edition, field_name="edition")
        if self.version is not None:
            reject_hard_coded_latest(self.version, field_name="version")
        keys = tuple(
            _require_non_empty_str(str(k), "candidate_key")
            for k in (self.candidate_keys or ())
        )
        object.__setattr__(self, "candidate_keys", keys)
        if not isinstance(self.metadata, Mapping):
            raise PatentCitationResolverError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_exact(self) -> bool:
        return self.match_kind is CitationMatchKind.EXACT

    @property
    def is_ambiguous(self) -> bool:
        return self.match_kind is CitationMatchKind.AMBIGUOUS

    @property
    def is_unresolved(self) -> bool:
        return self.match_kind is CitationMatchKind.UNRESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tier": (
                None if self.authority_tier is None else self.authority_tier.value
            ),
            "candidate_keys": list(self.candidate_keys),
            "citation_key": self.citation_key,
            "confidence": self.confidence,
            "edition": self.edition,
            "end_pos": self.end_pos,
            "family": self.family.value,
            "fee_code": self.fee_code,
            "form_id": self.form_id,
            "guide_id": self.guide_id,
            "match_kind": self.match_kind.value,
            "metadata": _deep_sorted(self.metadata),
            "normalized_text": self.normalized_text,
            "page": self.page,
            "raw_text": self.raw_text,
            "relevance": self.relevance,
            "section": self.section,
            "start_pos": self.start_pos,
            "subsections": self.subsections,
            "title": self.title,
            "version": self.version,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParsedCitation":
        if not isinstance(value, Mapping):
            raise PatentCitationResolverError("parsed citation must be a mapping")
        return cls(
            raw_text=str(value.get("raw_text") or value.get("text") or ""),
            family=value.get("family") or CitationFamily.UNKNOWN,
            match_kind=value.get("match_kind") or CitationMatchKind.UNRESOLVED,
            citation_key=value.get("citation_key"),
            normalized_text=value.get("normalized_text"),
            title=value.get("title"),
            section=value.get("section"),
            subsections=value.get("subsections"),
            volume=value.get("volume"),
            page=value.get("page"),
            form_id=value.get("form_id"),
            fee_code=value.get("fee_code"),
            guide_id=value.get("guide_id"),
            edition=value.get("edition"),
            version=value.get("version"),
            start_pos=int(value.get("start_pos") or 0),
            end_pos=int(value.get("end_pos") or 0),
            confidence=value.get("confidence", 0.0),
            relevance=value.get("relevance", 0.0),
            authority_tier=value.get("authority_tier"),
            candidate_keys=tuple(value.get("candidate_keys") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class QuoteComparison:
    """Result of comparing a quoted fragment to an exact source span.

    On mismatch, **both** :attr:`quoted_span` and :attr:`source_span` are
    populated so reviewers can inspect the divergence without re-querying.
    """

    status: QuoteMatchStatus
    quoted_span: Optional[TextSpan] = None
    source_span: Optional[TextSpan] = None
    normalized_quoted: Optional[str] = None
    normalized_source: Optional[str] = None
    match_ratio: float = 0.0
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", QuoteMatchStatus.coerce(self.status))
        object.__setattr__(self, "match_ratio", _clamp_score(self.match_ratio))
        if self.status is QuoteMatchStatus.MISMATCH:
            if self.quoted_span is None or self.source_span is None:
                raise PatentCitationResolverError(
                    "quote mismatch must expose both quoted_span and source_span"
                )

    @property
    def is_match(self) -> bool:
        return self.status is QuoteMatchStatus.MATCH

    @property
    def is_mismatch(self) -> bool:
        return self.status is QuoteMatchStatus.MISMATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "match_ratio": self.match_ratio,
            "normalized_quoted": self.normalized_quoted,
            "normalized_source": self.normalized_source,
            "quoted_span": None if self.quoted_span is None else self.quoted_span.to_dict(),
            "source_span": None if self.source_span is None else self.source_span.to_dict(),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuoteComparison":
        if not isinstance(value, Mapping):
            raise PatentCitationResolverError("quote comparison must be a mapping")
        qs = value.get("quoted_span")
        ss = value.get("source_span")
        return cls(
            status=value.get("status") or QuoteMatchStatus.NO_QUOTE,
            quoted_span=None if qs is None else TextSpan.from_dict(qs),
            source_span=None if ss is None else TextSpan.from_dict(ss),
            normalized_quoted=value.get("normalized_quoted"),
            normalized_source=value.get("normalized_source"),
            match_ratio=value.get("match_ratio", 0.0),
            detail=value.get("detail"),
        )


@dataclass(frozen=True, slots=True)
class CitationDiagnostic:
    """Typed diagnostic attached to a citation resolution."""

    code: CitationDiagnosticCode
    message: str
    severity: str = "info"
    field_path: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, CitationDiagnosticCode):
            text = str(self.code).strip().lower()
            matched = None
            for code in CitationDiagnosticCode:
                if code.value == text or code.name.lower() == text:
                    matched = code
                    break
            if matched is None:
                raise PatentCitationResolverError(
                    f"unknown citation diagnostic code: {self.code!r}"
                )
            object.__setattr__(self, "code", matched)
        object.__setattr__(
            self, "message", _require_non_empty_str(self.message, "message")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "field_path": self.field_path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class CitationResolutionResult:
    """Typed result of resolving one patent-law citation (exact or ambiguous).

    ``authority_tier`` reflects the governing source tier from the temporal
    graph (or the family default). ``confidence`` and ``relevance`` are
    independent scoring fields and must not be used to invent a higher tier.
    """

    parsed: ParsedCitation
    match_kind: CitationMatchKind
    verification_state: VerificationState
    authority_tier: Optional[AuthorityTier] = None
    confidence: float = 0.0
    relevance: float = 0.0
    selected_node_id: Optional[str] = None
    selected_citation_key: Optional[str] = None
    selected_version: Optional[str] = None
    selected_edition: Optional[str] = None
    selected_span: Optional[AuthoritySpan] = None
    as_of_resolution: Optional[AsOfResolution] = None
    quote_comparison: Optional[QuoteComparison] = None
    candidate_node_ids: tuple[str, ...] = ()
    candidate_citation_keys: tuple[str, ...] = ()
    diagnostics: tuple[CitationDiagnostic, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.parsed, ParsedCitation):
            raise PatentCitationResolverError("parsed must be ParsedCitation")
        object.__setattr__(self, "match_kind", CitationMatchKind.coerce(self.match_kind))
        object.__setattr__(self, "confidence", _clamp_score(self.confidence))
        object.__setattr__(self, "relevance", _clamp_score(self.relevance))
        if not isinstance(self.verification_state, VerificationState):
            text = str(self.verification_state).strip().lower().replace("-", "_")
            matched = None
            for state in VerificationState:
                if state.value == text or state.name.lower() == text:
                    matched = state
                    break
            if matched is None:
                raise PatentCitationResolverError(
                    f"unknown verification_state: {self.verification_state!r}"
                )
            object.__setattr__(self, "verification_state", matched)
        if self.authority_tier is not None and not isinstance(
            self.authority_tier, AuthorityTier
        ):
            text = str(self.authority_tier).strip().lower().replace("_", "-")
            matched = None
            for tier in AuthorityTier:
                if tier.value == text:
                    matched = tier
                    break
            if matched is None:
                raise PatentCitationResolverError(
                    f"unknown authority_tier: {self.authority_tier!r}"
                )
            object.__setattr__(self, "authority_tier", matched)
        # Fail-closed: unresolved version/source must never be verified.
        if (
            self.verification_state is VerificationState.VERIFIED
            and not self._source_and_version_resolved()
        ):
            raise PatentCitationResolverError(
                "verification_state=verified is forbidden when version or source "
                "is unresolved"
            )

    def _source_and_version_resolved(self) -> bool:
        if self.match_kind is CitationMatchKind.UNRESOLVED:
            return False
        if self.match_kind is CitationMatchKind.AMBIGUOUS:
            return False
        if self.selected_node_id is None:
            return False
        if self.selected_version is None and self.selected_edition is None:
            return False
        if self.as_of_resolution is not None and not self.as_of_resolution.is_resolved:
            return False
        return True

    @property
    def is_exact(self) -> bool:
        return self.match_kind is CitationMatchKind.EXACT

    @property
    def is_ambiguous(self) -> bool:
        return self.match_kind is CitationMatchKind.AMBIGUOUS

    @property
    def is_verified(self) -> bool:
        return self.verification_state is VerificationState.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_resolution": (
                None
                if self.as_of_resolution is None
                else self.as_of_resolution.to_dict()
            ),
            "authority_tier": (
                None if self.authority_tier is None else self.authority_tier.value
            ),
            "candidate_citation_keys": list(self.candidate_citation_keys),
            "candidate_node_ids": list(self.candidate_node_ids),
            "confidence": self.confidence,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "match_kind": self.match_kind.value,
            "parsed": self.parsed.to_dict(),
            "quote_comparison": (
                None if self.quote_comparison is None else self.quote_comparison.to_dict()
            ),
            "relevance": self.relevance,
            "schema_version": self.schema_version,
            "selected_citation_key": self.selected_citation_key,
            "selected_edition": self.selected_edition,
            "selected_node_id": self.selected_node_id,
            "selected_span": (
                None if self.selected_span is None else self.selected_span.to_dict()
            ),
            "selected_version": self.selected_version,
            "verification_state": self.verification_state.value,
        }


# ---------------------------------------------------------------------------
# Quote comparison
# ---------------------------------------------------------------------------


def _token_set_ratio(a: str, b: str) -> float:
    """Lightweight token Jaccard used only as a diagnostic ratio, not a tier."""

    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return float(inter) / float(union) if union else 0.0


def compare_quote_to_source(
    quoted: str | TextSpan | None,
    source: str | TextSpan | AuthoritySpan | AuthorityTextNode | None,
    *,
    require_exact: bool = True,
    min_ratio: float = 1.0,
) -> QuoteComparison:
    """Compare a quotation against an exact temporal source span.

    On :class:`QuoteMatchStatus.MISMATCH`, both spans are always present.
    """

    if quoted is None or (isinstance(quoted, str) and not str(quoted).strip()):
        return QuoteComparison(
            status=QuoteMatchStatus.NO_QUOTE,
            detail="no quotation supplied",
        )

    if isinstance(quoted, TextSpan):
        quoted_span = quoted
        quoted_text = quoted.text
    else:
        quoted_text = str(quoted)
        quoted_span = TextSpan(start=0, end=len(quoted_text), text=quoted_text)

    source_span: Optional[TextSpan] = None
    source_text: Optional[str] = None

    if source is None:
        return QuoteComparison(
            status=QuoteMatchStatus.NO_SOURCE,
            quoted_span=quoted_span,
            detail="no source span available",
        )
    if isinstance(source, AuthorityTextNode):
        if source.span is not None:
            source_span = TextSpan.from_authority_span(
                source.span, fallback_text=source.text_excerpt
            )
        if source_span is None and source.text_excerpt is not None:
            source_span = TextSpan(
                start=0,
                end=len(source.text_excerpt),
                text=source.text_excerpt,
                section=source.citation,
                artifact_sha256=(
                    source.official_artifact.artifact_sha256
                    if source.official_artifact is not None
                    else (
                        source.derived_presentation.artifact_sha256
                        if source.derived_presentation is not None
                        else None
                    )
                ),
            )
        source_text = None if source_span is None else source_span.text
    elif isinstance(source, AuthoritySpan):
        source_span = TextSpan.from_authority_span(source)
        source_text = None if source_span is None else source_span.text
    elif isinstance(source, TextSpan):
        source_span = source
        source_text = source.text
    else:
        source_text = str(source)
        source_span = TextSpan(start=0, end=len(source_text), text=source_text)

    if source_span is None or source_text is None or not str(source_text).strip():
        return QuoteComparison(
            status=QuoteMatchStatus.NO_SOURCE,
            quoted_span=quoted_span,
            detail="source span empty",
        )

    norm_q = normalize_quote_text(quoted_text)
    norm_s = normalize_quote_text(source_text)
    ratio = 1.0 if norm_q == norm_s else _token_set_ratio(norm_q, norm_s)

    if require_exact:
        matched = norm_q == norm_s or (norm_q and norm_q in norm_s)
    else:
        matched = ratio >= float(min_ratio)

    if matched:
        return QuoteComparison(
            status=QuoteMatchStatus.MATCH,
            quoted_span=quoted_span,
            source_span=source_span,
            normalized_quoted=norm_q,
            normalized_source=norm_s,
            match_ratio=1.0 if norm_q == norm_s or norm_q in norm_s else ratio,
            detail="quoted text matches source span",
        )

    # Mismatch: both spans required.
    return QuoteComparison(
        status=QuoteMatchStatus.MISMATCH,
        quoted_span=quoted_span,
        source_span=source_span,
        normalized_quoted=norm_q,
        normalized_source=norm_s,
        match_ratio=ratio,
        detail="quoted text does not match source span",
    )


def compute_verification_state(
    *,
    match_kind: CitationMatchKind,
    version: Optional[str],
    edition: Optional[str],
    source_node: Optional[AuthorityTextNode],
    as_of: Optional[AsOfResolution],
    quote: Optional[QuoteComparison],
    node_verification: Optional[VerificationState] = None,
) -> VerificationState:
    """Derive verification state with fail-closed rules.

    Unresolved version or source never becomes ``VERIFIED``. Quote mismatch
    and as-of conflicts also block verification.
    """

    if match_kind in (CitationMatchKind.UNRESOLVED, CitationMatchKind.AMBIGUOUS):
        return VerificationState.UNVERIFIED
    if source_node is None:
        return VerificationState.UNVERIFIED
    if version is None and edition is None:
        return VerificationState.UNVERIFIED
    if as_of is not None and as_of.status is not ResolutionStatus.RESOLVED:
        if as_of.competing_sources:
            return VerificationState.CONFLICT
        return VerificationState.UNVERIFIED
    if quote is not None and quote.status is QuoteMatchStatus.MISMATCH:
        return VerificationState.CONFLICT
    if quote is not None and quote.status in (
        QuoteMatchStatus.NO_SOURCE,
        QuoteMatchStatus.SOURCE_UNRESOLVED,
    ):
        return VerificationState.UNVERIFIED

    base = node_verification or source_node.verification_state
    if base is VerificationState.VERIFIED:
        # Only promote when version/source and (if present) quote are sound.
        if quote is None or quote.status is QuoteMatchStatus.MATCH:
            return VerificationState.VERIFIED
        if quote.status is QuoteMatchStatus.NO_QUOTE:
            return VerificationState.VERIFIED
        return VerificationState.UNVERIFIED
    return base


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _make_parsed(
    *,
    raw: str,
    family: CitationFamily,
    match_kind: CitationMatchKind,
    citation_key: Optional[str],
    start: int,
    end: int,
    confidence: float,
    **fields: Any,
) -> ParsedCitation:
    tier = fields.pop("authority_tier", None)
    if tier is None:
        tier = default_authority_tier_for_family(family)
    return ParsedCitation(
        raw_text=raw,
        family=family,
        match_kind=match_kind,
        citation_key=citation_key,
        normalized_text=fields.pop("normalized_text", raw.strip()),
        start_pos=start,
        end_pos=end,
        confidence=confidence,
        relevance=fields.pop("relevance", confidence),
        authority_tier=tier,
        **fields,
    )


def parse_patent_citations(text: str) -> tuple[ParsedCitation, ...]:
    """Parse patent-law citations from *text* into typed :class:`ParsedCitation`.

    Overlapping matches prefer the longer / more specific family (e.g. form
    paragraph over a bare fee code). Results are ordered by ``start_pos``.
    """

    if text is None or not str(text).strip():
        return ()

    host = str(text)
    candidates: list[ParsedCitation] = []

    for match in _USC_RE.finditer(host):
        title = match.group("title")
        section = match.group("section")
        subs = match.group("subsections") or ""
        key = citation_key_for_usc(title, section, subsections=subs)
        edition = _edition_from_neighborhood(host, match.start(), match.end())
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.USC,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                title=str(int(title)),
                section=section,
                subsections=subs.strip() or None,
                edition=edition,
                normalized_text=f"{int(title)} U.S.C. § {section}{subs.strip()}",
            )
        )

    for match in _CFR_RE.finditer(host):
        title = match.group("title")
        section = match.group("section")
        subs = match.group("subsections") or ""
        key = citation_key_for_cfr(title, section, subsections=subs)
        edition = _edition_from_neighborhood(host, match.start(), match.end())
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.CFR,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                title=str(int(title)),
                section=section,
                subsections=subs.strip() or None,
                edition=edition,
                normalized_text=f"{int(title)} C.F.R. § {section}{subs.strip()}",
            )
        )

    for match in _FR_RE.finditer(host):
        volume = match.group("volume")
        page = match.group("page")
        key = citation_key_for_fr(volume, page)
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.FEDERAL_REGISTER,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.92,
                volume=str(int(volume)),
                page=str(int(page)),
                normalized_text=f"{int(volume)} FR {int(page)}",
            )
        )

    for match in _MPEP_RE.finditer(host):
        section = match.group("section")
        subs = match.group("subsections") or ""
        key = citation_key_for_mpep(section, subsections=subs)
        edition = _edition_from_neighborhood(host, match.start(), match.end())
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.MPEP,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.9,
                section=section,
                subsections=subs.strip() or None,
                edition=edition,
                normalized_text=f"MPEP § {section}{subs.strip()}",
            )
        )

    for match in _FORM_PARAGRAPH_RE.finditer(host):
        fp = match.group("fp")
        key = citation_key_for_form_paragraph(fp)
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.FORM_PARAGRAPH,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.9,
                section=fp,
                form_id=fp,
                normalized_text=f"FP {fp}",
            )
        )

    for match in _FORM_RE.finditer(host):
        form_id = match.group("form_id")
        key = citation_key_for_form(form_id)
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.FORM,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.88,
                form_id=form_id.upper(),
                normalized_text=form_id.upper(),
            )
        )

    for match in _FEE_RE.finditer(host):
        code = match.group("code")
        key = citation_key_for_fee(code)
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.FEE,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.85,
                fee_code=code,
                section=code,
                normalized_text=f"fee {code}",
            )
        )

    for match in _EXAM_GUIDE_RE.finditer(host):
        guide_id = match.group("guide_id")
        key = citation_key_for_exam_guide(guide_id)
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.EXAMINATION_GUIDE,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.88,
                guide_id=guide_id,
                section=guide_id,
                normalized_text=f"Examination Guide {guide_id}",
            )
        )

    for match in _PUBLIC_LAW_RE.finditer(host):
        congress = match.group("congress")
        law = match.group("law")
        key = citation_key_for_public_law(congress, law)
        candidates.append(
            _make_parsed(
                raw=match.group("raw"),
                family=CitationFamily.PUBLIC_LAW,
                match_kind=CitationMatchKind.EXACT,
                citation_key=key,
                start=match.start(),
                end=match.end(),
                confidence=0.93,
                volume=str(int(congress)),
                page=str(int(law)),
                normalized_text=f"Pub. L. {int(congress)}-{int(law)}",
            )
        )

    if not candidates:
        return ()

    # Resolve overlaps: keep non-overlapping, prefer longer spans then higher confidence.
    ordered = sorted(
        candidates,
        key=lambda c: (c.start_pos, -(c.end_pos - c.start_pos), -c.confidence),
    )
    accepted: list[ParsedCitation] = []
    for cit in ordered:
        if any(
            not (cit.end_pos <= prev.start_pos or cit.start_pos >= prev.end_pos)
            for prev in accepted
        ):
            # Overlap — keep existing (already preferred by sort when tied on start).
            # If the new one is strictly longer, replace the overlapping prior.
            replaced = False
            for i, prev in enumerate(accepted):
                overlaps = not (
                    cit.end_pos <= prev.start_pos or cit.start_pos >= prev.end_pos
                )
                if not overlaps:
                    continue
                cit_len = cit.end_pos - cit.start_pos
                prev_len = prev.end_pos - prev.start_pos
                if cit_len > prev_len or (
                    cit_len == prev_len and cit.confidence > prev.confidence
                ):
                    accepted[i] = cit
                    replaced = True
                break
            if not replaced:
                continue
        else:
            accepted.append(cit)

    accepted.sort(key=lambda c: (c.start_pos, c.end_pos))
    return tuple(accepted)


def parse_citation(text: str) -> ParsedCitation:
    """Parse a single citation string into a typed result.

    When the surface form yields multiple distinct keys, the result is typed
    ``ambiguous`` with ``candidate_keys`` populated. When nothing is recognized,
    the result is typed ``unresolved``.
    """

    host = str(text or "").strip()
    if not host:
        return ParsedCitation(
            raw_text="(empty)",
            family=CitationFamily.UNKNOWN,
            match_kind=CitationMatchKind.UNRESOLVED,
            confidence=0.0,
            relevance=0.0,
            authority_tier=AuthorityTier.CANDIDATE,
            metadata={"empty": True},
        )

    found = parse_patent_citations(host)
    if not found:
        return ParsedCitation(
            raw_text=host,
            family=CitationFamily.UNKNOWN,
            match_kind=CitationMatchKind.UNRESOLVED,
            confidence=0.0,
            relevance=0.0,
            authority_tier=AuthorityTier.CANDIDATE,
            metadata={"parse": "no_match"},
        )

    # If the input is essentially one citation, return it; if multiple distinct
    # keys appear, surface ambiguity.
    keys = []
    for c in found:
        if c.citation_key and c.citation_key not in keys:
            keys.append(c.citation_key)

    if len(found) == 1:
        return found[0]

    if len(keys) == 1:
        # Same key repeated — exact.
        primary = found[0]
        return replace(primary, candidate_keys=tuple(keys))

    # Multiple distinct citations in one string → ambiguous typed result.
    primary = found[0]
    return replace(
        primary,
        match_kind=CitationMatchKind.AMBIGUOUS,
        candidate_keys=tuple(keys),
        confidence=min(0.7, primary.confidence),
        metadata={
            **dict(primary.metadata),
            "all_raw": [c.raw_text for c in found],
            "families": [c.family.value for c in found],
        },
    )


# ---------------------------------------------------------------------------
# Resolution against temporal authority graph
# ---------------------------------------------------------------------------


def _nodes_matching_key(
    graph: PatentTemporalAuthorityGraph,
    citation_key: str,
) -> tuple[AuthorityTextNode, ...]:
    exact = list(graph.nodes_for_citation(citation_key))
    if exact:
        return exact
    # Prefix / family-key softening for partial anchors (e.g. 35-usc-102 matches
    # nodes keyed 35-usc-102(a) when the citation omits subsections).
    prefix = citation_key.rstrip()
    soft: list[AuthorityTextNode] = []
    for node in graph.nodes:
        if node.citation_key == prefix:
            soft.append(node)
        elif node.citation_key.startswith(prefix + "(") or node.citation_key.startswith(
            prefix + "-"
        ):
            soft.append(node)
        elif prefix.startswith(node.citation_key + "(") or prefix.startswith(
            node.citation_key + "-"
        ):
            soft.append(node)
    return tuple(soft)


def _unique_keys(nodes: Sequence[AuthorityTextNode]) -> tuple[str, ...]:
    seen: list[str] = []
    for n in nodes:
        if n.citation_key not in seen:
            seen.append(n.citation_key)
    return tuple(seen)


def resolve_citation(
    citation: str | ParsedCitation,
    *,
    graph: Optional[PatentTemporalAuthorityGraph] = None,
    as_of: Optional[date | str | AsOfQuery] = None,
    quoted_text: Optional[str | TextSpan] = None,
    view_role: AsOfViewRole | str = AsOfViewRole.AS_OF,
    view_kind: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL,
    include_guidance: bool = True,
    include_proposed: bool = False,
    include_future: bool = False,
    include_withdrawn: bool = False,
    require_exact_quote: bool = True,
    relevance: Optional[float] = None,
    confidence: Optional[float] = None,
) -> CitationResolutionResult:
    """Resolve one citation against the temporal authority graph.

    Returns a typed :class:`CitationResolutionResult` for both exact and
    ambiguous outcomes. Authority tier is taken from the selected source node
    (or family default) and is **never** computed from relevance/confidence.
    """

    parsed = (
        citation
        if isinstance(citation, ParsedCitation)
        else parse_citation(str(citation))
    )

    # Caller-supplied scores override parse defaults without touching tier.
    conf = (
        _clamp_score(confidence)
        if confidence is not None
        else parsed.confidence
    )
    rel = _clamp_score(relevance) if relevance is not None else parsed.relevance

    diagnostics: list[CitationDiagnostic] = []

    if parsed.match_kind is CitationMatchKind.UNRESOLVED or not parsed.citation_key:
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.UNRESOLVED_CITATION,
                message="citation could not be parsed into a known patent-law family",
                severity="warning",
            )
        )
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                message="unresolved citation cannot become verified",
                severity="info",
            )
        )
        return CitationResolutionResult(
            parsed=parsed,
            match_kind=CitationMatchKind.UNRESOLVED,
            verification_state=VerificationState.UNVERIFIED,
            authority_tier=parsed.authority_tier
            or default_authority_tier_for_family(parsed.family),
            confidence=conf,
            relevance=rel,
            diagnostics=tuple(diagnostics),
        )

    if graph is None:
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.UNRESOLVED_SOURCE,
                message="no temporal authority graph supplied; source unresolved",
                severity="warning",
            )
        )
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                message="unresolved source cannot become verified",
                severity="info",
            )
        )
        match_kind = (
            CitationMatchKind.AMBIGUOUS
            if parsed.match_kind is CitationMatchKind.AMBIGUOUS
            else CitationMatchKind.UNRESOLVED
        )
        # Parsed form may be exact as a surface key, but without a source it
        # remains unresolved for verification purposes.
        if parsed.is_exact and parsed.citation_key:
            match_kind = CitationMatchKind.UNRESOLVED
        return CitationResolutionResult(
            parsed=parsed,
            match_kind=match_kind,
            verification_state=VerificationState.UNVERIFIED,
            authority_tier=parsed.authority_tier
            or default_authority_tier_for_family(parsed.family),
            confidence=conf,
            relevance=rel,
            selected_citation_key=parsed.citation_key,
            candidate_citation_keys=parsed.candidate_keys or (
                (parsed.citation_key,) if parsed.citation_key else ()
            ),
            diagnostics=tuple(diagnostics),
        )

    # Ambiguous multi-key parse without further disambiguation.
    if parsed.match_kind is CitationMatchKind.AMBIGUOUS and len(parsed.candidate_keys) > 1:
        all_nodes: list[AuthorityTextNode] = []
        for key in parsed.candidate_keys:
            all_nodes.extend(_nodes_matching_key(graph, key))
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.AMBIGUOUS_CANDIDATES,
                message=(
                    f"citation is ambiguous across keys: "
                    f"{', '.join(parsed.candidate_keys)}"
                ),
                severity="warning",
            )
        )
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                message="ambiguous citation cannot become verified",
                severity="info",
            )
        )
        return CitationResolutionResult(
            parsed=parsed,
            match_kind=CitationMatchKind.AMBIGUOUS,
            verification_state=VerificationState.UNVERIFIED,
            authority_tier=parsed.authority_tier
            or default_authority_tier_for_family(parsed.family),
            confidence=min(conf, 0.7),
            relevance=rel,
            candidate_node_ids=tuple(n.node_id for n in all_nodes),
            candidate_citation_keys=parsed.candidate_keys,
            diagnostics=tuple(diagnostics),
        )

    matching = _nodes_matching_key(graph, parsed.citation_key)
    keys = _unique_keys(matching)

    # Soft-match produced multiple citation keys → ambiguous.
    if len(keys) > 1:
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.AMBIGUOUS_CANDIDATES,
                message=(
                    f"citation key {parsed.citation_key!r} matches multiple keys: "
                    f"{', '.join(keys)}"
                ),
                severity="warning",
            )
        )
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                message="ambiguous key expansion cannot become verified",
                severity="info",
            )
        )
        return CitationResolutionResult(
            parsed=parsed,
            match_kind=CitationMatchKind.AMBIGUOUS,
            verification_state=VerificationState.UNVERIFIED,
            authority_tier=parsed.authority_tier
            or default_authority_tier_for_family(parsed.family),
            confidence=min(conf, 0.7),
            relevance=rel,
            selected_citation_key=parsed.citation_key,
            candidate_node_ids=tuple(n.node_id for n in matching),
            candidate_citation_keys=keys,
            diagnostics=tuple(diagnostics),
        )

    if not matching:
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.UNRESOLVED_SOURCE,
                message=(
                    f"no authority nodes for citation key {parsed.citation_key!r}"
                ),
                severity="warning",
            )
        )
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                message="missing source cannot become verified",
                severity="info",
            )
        )
        return CitationResolutionResult(
            parsed=parsed,
            match_kind=CitationMatchKind.UNRESOLVED,
            verification_state=VerificationState.UNVERIFIED,
            authority_tier=parsed.authority_tier
            or default_authority_tier_for_family(parsed.family),
            confidence=conf * 0.5,
            relevance=rel,
            selected_citation_key=parsed.citation_key,
            candidate_citation_keys=(parsed.citation_key,),
            diagnostics=tuple(diagnostics),
        )

    # Build as-of query when a date is available; otherwise pick the sole node
    # or surface ambiguity among concurrent nodes.
    as_of_result: Optional[AsOfResolution] = None
    selected: Optional[AuthorityTextNode] = None

    query: Optional[AsOfQuery] = None
    if isinstance(as_of, AsOfQuery):
        query = replace(
            as_of,
            citation_key=as_of.citation_key or parsed.citation_key,
        )
    elif as_of is not None:
        as_of_date = _parse_optional_date(as_of)
        if as_of_date is not None:
            query = AsOfQuery(
                as_of=as_of_date,
                citation_key=parsed.citation_key,
                view_role=view_role,
                view_kind=view_kind,
                include_guidance=include_guidance,
                include_proposed=include_proposed,
                include_future=include_future,
                include_withdrawn=include_withdrawn,
            )

    if query is not None:
        as_of_result = resolve_as_of(graph, query)
        if as_of_result.is_resolved and as_of_result.selected_node_id:
            selected = graph.node_by_id.get(as_of_result.selected_node_id)
        elif as_of_result.competing_sources:
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.AS_OF_UNKNOWN,
                    message="as-of resolution returned competing sources",
                    severity="warning",
                )
            )
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.AMBIGUOUS_CANDIDATES,
                    message="competing temporal sources — typed as ambiguous",
                    severity="warning",
                )
            )
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                    message="unresolved temporal conflict cannot become verified",
                    severity="info",
                )
            )
            return CitationResolutionResult(
                parsed=parsed,
                match_kind=CitationMatchKind.AMBIGUOUS,
                verification_state=VerificationState.CONFLICT,
                authority_tier=(
                    as_of_result.authority_tier
                    or parsed.authority_tier
                    or default_authority_tier_for_family(parsed.family)
                ),
                confidence=min(conf, 0.6),
                relevance=rel,
                as_of_resolution=as_of_result,
                selected_citation_key=parsed.citation_key,
                candidate_node_ids=tuple(
                    c.node_id for c in as_of_result.competing_sources
                ),
                candidate_citation_keys=(parsed.citation_key,),
                diagnostics=tuple(diagnostics),
            )
        else:
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.AS_OF_UNKNOWN,
                    message="as-of resolution did not select a node",
                    severity="warning",
                )
            )
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.UNRESOLVED_VERSION,
                    message="version not resolved for as-of date",
                    severity="warning",
                )
            )
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                    message="unresolved version cannot become verified",
                    severity="info",
                )
            )
            return CitationResolutionResult(
                parsed=parsed,
                match_kind=CitationMatchKind.UNRESOLVED,
                verification_state=VerificationState.UNVERIFIED,
                authority_tier=parsed.authority_tier
                or default_authority_tier_for_family(parsed.family),
                confidence=conf * 0.5,
                relevance=rel,
                as_of_resolution=as_of_result,
                selected_citation_key=parsed.citation_key,
                candidate_node_ids=tuple(n.node_id for n in matching),
                candidate_citation_keys=(parsed.citation_key,),
                diagnostics=tuple(diagnostics),
            )
    else:
        # No as-of date: exact only if a single node, else ambiguous.
        if len(matching) == 1:
            selected = matching[0]
        else:
            # Prefer verified official nodes if exactly one, else ambiguous.
            verified_official = [
                n
                for n in matching
                if n.verification_state is VerificationState.VERIFIED
                and n.authority_tier
                in (AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE)
            ]
            if len(verified_official) == 1:
                selected = verified_official[0]
            else:
                diagnostics.append(
                    CitationDiagnostic(
                        code=CitationDiagnosticCode.AMBIGUOUS_CANDIDATES,
                        message=(
                            f"{len(matching)} nodes for {parsed.citation_key!r} "
                            "without as-of date"
                        ),
                        severity="warning",
                    )
                )
                diagnostics.append(
                    CitationDiagnostic(
                        code=CitationDiagnosticCode.UNRESOLVED_VERSION,
                        message="version selection requires an as-of date",
                        severity="warning",
                    )
                )
                diagnostics.append(
                    CitationDiagnostic(
                        code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                        message="unresolved version cannot become verified",
                        severity="info",
                    )
                )
                return CitationResolutionResult(
                    parsed=parsed,
                    match_kind=CitationMatchKind.AMBIGUOUS,
                    verification_state=VerificationState.UNVERIFIED,
                    authority_tier=parsed.authority_tier
                    or default_authority_tier_for_family(parsed.family),
                    confidence=min(conf, 0.7),
                    relevance=rel,
                    selected_citation_key=parsed.citation_key,
                    candidate_node_ids=tuple(n.node_id for n in matching),
                    candidate_citation_keys=(parsed.citation_key,),
                    diagnostics=tuple(diagnostics),
                )

    assert selected is not None

    selected_version = selected.version
    selected_edition = selected.edition
    if selected_version is None and selected_edition is None:
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.UNRESOLVED_VERSION,
                message=f"selected node {selected.node_id!r} has no version/edition",
                severity="warning",
            )
        )

    quote_cmp: Optional[QuoteComparison] = None
    if quoted_text is not None:
        quote_cmp = compare_quote_to_source(
            quoted_text,
            selected,
            require_exact=require_exact_quote,
        )
        if quote_cmp.status is QuoteMatchStatus.MATCH:
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.QUOTE_MATCH,
                    message="quoted text matches source span",
                    severity="info",
                )
            )
        elif quote_cmp.status is QuoteMatchStatus.MISMATCH:
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.QUOTE_MISMATCH,
                    message="quoted text does not match source span; both spans exposed",
                    severity="error",
                    field_path="quote_comparison",
                )
            )
        elif quote_cmp.status is QuoteMatchStatus.NO_SOURCE:
            diagnostics.append(
                CitationDiagnostic(
                    code=CitationDiagnosticCode.QUOTE_NO_SOURCE,
                    message="no source span available for quote comparison",
                    severity="warning",
                )
            )

    verification = compute_verification_state(
        match_kind=CitationMatchKind.EXACT,
        version=selected_version,
        edition=selected_edition,
        source_node=selected,
        as_of=as_of_result,
        quote=quote_cmp,
        node_verification=selected.verification_state,
    )
    if verification is not VerificationState.VERIFIED and (
        selected_version is None and selected_edition is None
    ):
        diagnostics.append(
            CitationDiagnostic(
                code=CitationDiagnosticCode.VERIFICATION_BLOCKED,
                message="unresolved version cannot become verified",
                severity="info",
            )
        )

    # Authority tier comes from the selected node — never from scores.
    tier = selected.authority_tier
    diagnostics.append(
        CitationDiagnostic(
            code=CitationDiagnosticCode.TIER_INDEPENDENT_OF_SCORE,
            message=(
                f"authority_tier={tier.value} independent of "
                f"confidence={conf:.3f} relevance={rel:.3f}"
            ),
            severity="info",
            field_path="authority_tier",
        )
    )
    diagnostics.append(
        CitationDiagnostic(
            code=CitationDiagnosticCode.EXACT_MATCH,
            message=f"resolved exactly to node {selected.node_id}",
            severity="info",
        )
    )

    span = selected.span
    if as_of_result is not None and as_of_result.selected_span is not None:
        span = as_of_result.selected_span

    return CitationResolutionResult(
        parsed=parsed,
        match_kind=CitationMatchKind.EXACT,
        verification_state=verification,
        authority_tier=tier,
        confidence=conf,
        relevance=rel,
        selected_node_id=selected.node_id,
        selected_citation_key=selected.citation_key,
        selected_version=selected_version,
        selected_edition=selected_edition,
        selected_span=span,
        as_of_resolution=as_of_result,
        quote_comparison=quote_cmp,
        candidate_node_ids=(selected.node_id,),
        candidate_citation_keys=(selected.citation_key,),
        diagnostics=tuple(diagnostics),
    )


def resolve_citations_in_text(
    text: str,
    *,
    graph: Optional[PatentTemporalAuthorityGraph] = None,
    as_of: Optional[date | str | AsOfQuery] = None,
    **kwargs: Any,
) -> tuple[CitationResolutionResult, ...]:
    """Parse all patent-law citations in *text* and resolve each."""

    parsed = parse_patent_citations(text)
    return tuple(
        resolve_citation(p, graph=graph, as_of=as_of, **kwargs) for p in parsed
    )


# ---------------------------------------------------------------------------
# High-level resolver object
# ---------------------------------------------------------------------------


class PatentCitationResolver:
    """Parse, resolve, and quote-validate patent-law citations.

    Compose with a :class:`PatentTemporalAuthorityGraph` for as-of selection.
    Authority tier is always taken from the graph node (or family default) and
    is never derived from relevance or confidence.
    """

    def __init__(
        self,
        graph: Optional[PatentTemporalAuthorityGraph] = None,
        *,
        default_as_of: Optional[date | str] = None,
        view_role: AsOfViewRole | str = AsOfViewRole.AS_OF,
        view_kind: AuthorityViewKind | str = AuthorityViewKind.OFFICIAL,
        include_guidance: bool = True,
        require_exact_quote: bool = True,
    ) -> None:
        self.graph = graph
        self.default_as_of = (
            None if default_as_of is None else _parse_optional_date(default_as_of)
        )
        self.view_role = AsOfViewRole.coerce(view_role)
        self.view_kind = AuthorityViewKind.coerce(view_kind)
        self.include_guidance = bool(include_guidance)
        self.require_exact_quote = bool(require_exact_quote)

    def parse(self, text: str) -> tuple[ParsedCitation, ...]:
        return parse_patent_citations(text)

    def parse_one(self, text: str) -> ParsedCitation:
        return parse_citation(text)

    def resolve(
        self,
        citation: str | ParsedCitation,
        *,
        as_of: Optional[date | str | AsOfQuery] = None,
        quoted_text: Optional[str | TextSpan] = None,
        relevance: Optional[float] = None,
        confidence: Optional[float] = None,
        graph: Optional[PatentTemporalAuthorityGraph] = None,
        **kwargs: Any,
    ) -> CitationResolutionResult:
        return resolve_citation(
            citation,
            graph=graph if graph is not None else self.graph,
            as_of=as_of if as_of is not None else self.default_as_of,
            quoted_text=quoted_text,
            view_role=kwargs.get("view_role", self.view_role),
            view_kind=kwargs.get("view_kind", self.view_kind),
            include_guidance=kwargs.get("include_guidance", self.include_guidance),
            require_exact_quote=kwargs.get(
                "require_exact_quote", self.require_exact_quote
            ),
            relevance=relevance,
            confidence=confidence,
            include_proposed=kwargs.get("include_proposed", False),
            include_future=kwargs.get("include_future", False),
            include_withdrawn=kwargs.get("include_withdrawn", False),
        )

    def resolve_text(
        self,
        text: str,
        *,
        as_of: Optional[date | str | AsOfQuery] = None,
        **kwargs: Any,
    ) -> tuple[CitationResolutionResult, ...]:
        return resolve_citations_in_text(
            text,
            graph=kwargs.pop("graph", self.graph),
            as_of=as_of if as_of is not None else self.default_as_of,
            view_role=kwargs.pop("view_role", self.view_role),
            view_kind=kwargs.pop("view_kind", self.view_kind),
            include_guidance=kwargs.pop("include_guidance", self.include_guidance),
            require_exact_quote=kwargs.pop(
                "require_exact_quote", self.require_exact_quote
            ),
            **kwargs,
        )

    def validate_quote(
        self,
        quoted: str | TextSpan | None,
        source: str | TextSpan | AuthoritySpan | AuthorityTextNode | None,
        *,
        require_exact: Optional[bool] = None,
    ) -> QuoteComparison:
        return compare_quote_to_source(
            quoted,
            source,
            require_exact=(
                self.require_exact_quote if require_exact is None else require_exact
            ),
        )


# ---------------------------------------------------------------------------
# Public re-exports for tests / composition
# ---------------------------------------------------------------------------

__all__ = [
    "SCHEMA_VERSION",
    "AUTHORITY_REGISTRY_SCHEMA_VERSION",
    "PatentCitationResolverError",
    "CitationFamily",
    "CitationMatchKind",
    "QuoteMatchStatus",
    "CitationDiagnosticCode",
    "TextSpan",
    "ParsedCitation",
    "QuoteComparison",
    "CitationDiagnostic",
    "CitationResolutionResult",
    "PatentCitationResolver",
    "parse_patent_citations",
    "parse_citation",
    "resolve_citation",
    "resolve_citations_in_text",
    "compare_quote_to_source",
    "compute_verification_state",
    "normalize_quote_text",
    "default_authority_tier_for_family",
    "citation_key_for_usc",
    "citation_key_for_cfr",
    "citation_key_for_fr",
    "citation_key_for_mpep",
    "citation_key_for_form_paragraph",
    "citation_key_for_form",
    "citation_key_for_fee",
    "citation_key_for_exam_guide",
    "citation_key_for_public_law",
]
