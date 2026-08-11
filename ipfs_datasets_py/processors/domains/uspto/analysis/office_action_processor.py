"""Parse USPTO office actions and government instructions (PATLAW-032).

Sections office actions / notices and extracts claim ranges, objections,
rejections, cited references, form paragraphs, fees/forms, informalities,
response instructions, alternatives, exceptions, and uncompiled language.

Design invariants
-----------------
* Every candidate points at an exact :class:`ExtractedSpan` (or a span minted
  from a validated extraction page) — never free-floating text.
* Claim ranges and legal citations retain ambiguity rather than silently
  collapsing multi-candidate or open-ended surfaces.
* Rescinded / reissued action lifecycle is first-class; rescinded requirements
  are retained but marked inactive.
* Malformed actions are represented explicitly (disposition + reason codes).
* Model-origin candidates **never** enter the verified layer without
  deterministic span validation. Authority resolution is out of scope here
  (reuse citation *parsing* only; no as-of verification).

Document body text is never written to logs or exception messages.
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
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    GovernmentRequirement,
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
    CitationFamily,
    CitationMatchKind,
    ParsedCitation,
    parse_patent_citations,
)

OFFICE_ACTION_SCHEMA_VERSION: Final = "uspto.office-action-analysis.v1"
OFFICE_ACTION_INTERFACE: Final = "OfficeActionProcessor@1"
OFFICE_ACTION_RULESET_VERSION: Final = "office-action-rules@1"

DEFAULT_MAX_CHARS: Final = 2_000_000
DEFAULT_MAX_CANDIDATES: Final = 4096
DEFAULT_MAX_SECTIONS: Final = 256
DEFAULT_MAX_MODEL_CANDIDATES: Final = 512

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Regex libraries (deterministic section / instruction extractors)
# ---------------------------------------------------------------------------

# Section headers commonly found in USPTO office actions / notices.
_SECTION_HEADER_RE = re.compile(
    r"(?im)^[ \t]*"
    r"(?:"
    r"(?P<header>UNITED STATES PATENT AND TRADEMARK OFFICE|"
    r"Office Action Summary|"
    r"Detailed Action|"
    r"Notice of Non-Compliant Amendment|"
    r"Notice of Allowance|"
    r"Examiner'?s? Amendment|"
    r"Interview Summary|"
    r"Conclusion)"
    r"|(?P<claim_rej>Claim Rejections?\s*[-–—]?\s*35\s*U\.?\s*S\.?\s*C\.?\s*§?\s*\d+[A-Za-z()]*)"
    r"|(?P<claim_obj>Claim Objections?)"
    r"|(?P<draw_obj>Drawing Objections?)"
    r"|(?P<spec_obj>Specification Objections?)"
    r"|(?P<inform>Claim Informalities|Informalities)"
    r"|(?P<allow>Allowable Subject Matter)"
    r"|(?P<response>Response to Arguments|Response Period|Period for Reply|"
    r"Conclusion and Response)"
    r"|(?P<cited>Notice of References Cited|Relevant Prior Art|Cited References)"
    r"|(?P<fee>Fee(?:s)? (?:Due|Required|Information)|Required Fees?)"
    r")"
    r"[ \t]*$"
)

# Claim range surfaces. Ambiguity is retained via ClaimRangeAmbiguity.
_CLAIM_RANGE_RE = re.compile(
    r"(?i)\b(?P<label>claims?|claim\s*nos?\.?)\s+"
    r"(?P<body>"
    r"(?:about\s+|approximately\s+|roughly\s+)?"
    r"(?:"
    r"\d+(?:\s*[-–—to]+\s*\d+)?"
    r"(?:\s*,\s*\d+(?:\s*[-–—to]+\s*\d+)?)*"
    r"(?:\s*,?\s*(?:and|&)\s*\d+(?:\s*[-–—to]+\s*\d+)?)?"
    r"|all"
    r"|the\s+remaining"
    r"|pending"
    r")"
    r")"
)

_SINGLE_CLAIM_RE = re.compile(r"(?i)\bclaim\s+(?P<n>\d+)\b")

_REJECTION_LEAD_RE = re.compile(
    r"(?im)^[ \t]*"
    r"(?:"
    r"(?P<head>Claims?\s+[\d,\s\-–—and&to]+?\s+are?\s+rejected\b|"
    r"Claim\s+\d+\s+is\s+rejected\b|"
    r"Claims?\s+[\d,\s\-–—and&to]+?\s+(?:stand|stands)\s+rejected\b)"
    r".{0,400}?"
    r")"
)

_OBJECTION_LEAD_RE = re.compile(
    r"(?im)^[ \t]*"
    r"(?:"
    r"Claims?\s+[\d,\s\-–—and&to]+?\s+are?\s+objected\b|"
    r"Claim\s+\d+\s+is\s+objected\b|"
    r"The\s+(?:drawings?|specification|abstract|title)\s+(?:is|are)\s+objected\b"
    r").{0,300}"
)

_INFORMALITY_RE = re.compile(
    r"(?im)^[ \t]*(?:Claims?\s+[\d,\s\-–—and&to]+?\s+(?:contain|contains)\s+"
    r"(?:the\s+following\s+)?informalit(?:y|ies)\b|"
    r"The\s+following\s+informalit(?:y|ies)\b).{0,300}"
)

_RESPONSE_INSTRUCTION_RE = re.compile(
    r"(?is)"
    r"(?:"
    r"(?:A\s+)?(?:shortened\s+)?statutory\s+period\s+for\s+(?:reply|response)\s+"
    r"(?:is|to)\s+(?:set\s+to\s+)?expire\s+(?:in\s+)?(?P<period>\d+\s+months?)"
    r"|Applicant\s+(?:is|are)\s+(?:required|invited|urged)\s+to\s+(?P<require>.{10,200}?)"
    r"(?:\.|$)"
    r"|This\s+action\s+is\s+(?:made\s+)?final\b"
    r"|This\s+(?:is\s+a\s+)?non-?final\s+(?:office\s+)?action\b"
    r"|Applicant\s+must\s+(?:traverse|respond|amend|submit)\b.{0,200}"
    r")"
)

_ALTERNATIVE_RE = re.compile(
    r"(?i)\b(?:in\s+the\s+alternative|alternatively|either\b.{1,80}?\bor\b|"
    r"applicant\s+may\s+(?:either|choose|elect))\b.{0,160}"
)

_EXCEPTION_RE = re.compile(
    r"(?i)\b(?:except(?:ion|ing)?|unless|provided\s+that|subject\s+to|"
    r"without\s+prejudice|contingent\s+upon)\b.{0,160}"
)

_PRIOR_ART_RE = re.compile(
    r"(?:"
    r"\bU\.?\s*S\.?\s*(?:Patent(?:\s+Application)?\s*)?(?:Pub(?:lication)?\.?\s*)?"
    r"(?:No\.?\s*)?(?P<uspat>\d[\d, ]{4,12}(?:\s*[A-Z]\d)?)\b"
    r"|\b(?P<pgpub>US\s*\d{4}/\d{7}\s*[A-Z]\d)\b"
    r"|\b(?P<npl>(?:Non-?Patent\s+Literature|NPL)\s*[:\-]?\s*[^\n]{5,80})"
    r")",
    re.IGNORECASE,
)

_MAILING_DATE_RE = re.compile(
    r"(?i)\b(?:Mailing\s+Date|Date\s+Mailed|Notification\s+Date)\s*[:\-]?\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
)

_APPLICATION_NO_RE = re.compile(
    r"(?i)\bApplication\s*(?:No\.?|Number)\s*[:\-]?\s*"
    r"(?P<app>\d{2}/\d{3},\d{3}|\d{8})"
)

_RESCIND_RE = re.compile(
    r"(?i)\b(?:this\s+office\s+action\s+(?:is\s+)?rescinded|"
    r"office\s+action\s+mailed\s+.{0,40}\s+is\s+(?:hereby\s+)?rescinded|"
    r"the\s+previous\s+office\s+action\s+is\s+(?:hereby\s+)?withdrawn)\b"
)

_REISSUE_RE = re.compile(
    r"(?i)\b(?:reissued?\s+office\s+action|this\s+action\s+supersedes|"
    r"replaces\s+the\s+(?:office\s+)?action\s+mailed)\b"
)

_FINALITY_RE = re.compile(
    r"(?i)\b(?:this\s+action\s+is\s+(?:made\s+)?final|"
    r"final\s+office\s+action|final\s+rejection)\b"
)
_NONFINAL_RE = re.compile(
    r"(?i)\b(?:non-?\s*final\s+(?:office\s+)?action|"
    r"this\s+action\s+is\s+non-?\s*final)\b"
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class OfficeActionKind(str, Enum):
    NON_FINAL_REJECTION = "non_final_rejection"
    FINAL_REJECTION = "final_rejection"
    EX_PARTE_QUAYLE = "ex_parte_quayle"
    NOTICE_OF_ALLOWANCE = "notice_of_allowance"
    NOTICE = "notice"
    INTERVIEW_SUMMARY = "interview_summary"
    EXAMINER_AMENDMENT = "examiner_amendment"
    REISSUED_ACTION = "reissued_action"
    RESCINDED_ACTION = "rescinded_action"
    MALFORMED = "malformed"
    UNKNOWN = "unknown"


class ActionLifecycleStatus(str, Enum):
    ACTIVE = "active"
    RESCINDED = "rescinded"
    SUPERSEDED = "superseded"
    REISSUED = "reissued"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


class SectionKind(str, Enum):
    HEADER = "header"
    SUMMARY = "summary"
    DETAILED_ACTION = "detailed_action"
    CLAIM_REJECTION = "claim_rejection"
    CLAIM_OBJECTION = "claim_objection"
    DRAWING_OBJECTION = "drawing_objection"
    SPECIFICATION_OBJECTION = "specification_objection"
    INFORMALITY = "informality"
    ALLOWABLE_SUBJECT_MATTER = "allowable_subject_matter"
    RESPONSE_INSTRUCTION = "response_instruction"
    CITED_REFERENCES = "cited_references"
    FEE_OR_FORM = "fee_or_form"
    INTERVIEW_SUMMARY = "interview_summary"
    CONCLUSION = "conclusion"
    UNCOMPILED = "uncompiled"
    OTHER = "other"


class CandidateKind(str, Enum):
    CLAIM_RANGE = "claim_range"
    REJECTION = "rejection"
    OBJECTION = "objection"
    INFORMALITY = "informality"
    CITATION = "citation"
    PRIOR_ART = "prior_art"
    FORM_PARAGRAPH = "form_paragraph"
    FEE = "fee"
    FORM = "form"
    RESPONSE_INSTRUCTION = "response_instruction"
    ALTERNATIVE = "alternative"
    EXCEPTION = "exception"
    UNCOMPILED_LANGUAGE = "uncompiled_language"
    SECTION = "section"
    LIFECYCLE = "lifecycle"
    OTHER = "other"


class EvidenceLayer(str, Enum):
    """Evidence layer for analysis candidates.

    * ``candidate`` — model or provisional extraction; not verified.
    * ``deterministic`` — rule-based extraction; not yet span-validated.
    * ``verified`` — passed deterministic span validation only.
    """

    CANDIDATE = "candidate"
    DETERMINISTIC = "deterministic"
    VERIFIED = "verified"


class CandidateOrigin(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    CITATION_PARSER = "citation_parser"
    MODEL = "model"
    LIFECYCLE_METADATA = "lifecycle_metadata"
    SPAN_INJECTION = "span_injection"
    OTHER = "other"


class ClaimRangeAmbiguity(str, Enum):
    """How claim-range surface text should be interpreted."""

    EXACT = "exact"
    MULTI_SEGMENT = "multi_segment"
    OPEN_ENDED = "open_ended"
    UNRESOLVED = "unresolved"
    CONFLICTING = "conflicting"


class AnalysisDisposition(str, Enum):
    ANALYZED = "analyzed"
    REVIEW = "review"
    MALFORMED = "malformed"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class OfficeActionReasonCode(str, Enum):
    SECTIONS_EXTRACTED = "sections_extracted"
    CLAIM_RANGES_EXTRACTED = "claim_ranges_extracted"
    REJECTIONS_EXTRACTED = "rejections_extracted"
    OBJECTIONS_EXTRACTED = "objections_extracted"
    CITATIONS_EXTRACTED = "citations_extracted"
    FORM_PARAGRAPHS_EXTRACTED = "form_paragraphs_extracted"
    RESPONSE_INSTRUCTIONS_EXTRACTED = "response_instructions_extracted"
    UNCOMPILED_LANGUAGE = "uncompiled_language"
    AMBIGUOUS_CLAIM_RANGE = "ambiguous_claim_range"
    AMBIGUOUS_CITATION = "ambiguous_citation"
    LIFECYCLE_RESCINDED = "lifecycle_rescinded"
    LIFECYCLE_REISSUED = "lifecycle_reissued"
    LIFECYCLE_SUPERSEDED = "lifecycle_superseded"
    MALFORMED_ACTION = "malformed_action"
    EMPTY_TEXT = "empty_text"
    MISSING_SPANS = "missing_spans"
    SPAN_MISMATCH = "span_mismatch"
    MODEL_CANDIDATE_HELD = "model_candidate_held"
    MODEL_CANDIDATE_BLOCKED_FROM_VERIFIED = "model_candidate_blocked_from_verified"
    DETERMINISTIC_VALIDATION_PASSED = "deterministic_validation_passed"
    DETERMINISTIC_VALIDATION_FAILED = "deterministic_validation_failed"
    REQUIREMENTS_EMITTED = "requirements_emitted"
    LOW_CONFIDENCE = "low_confidence"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    OVERSIZE_TEXT = "oversize_text"
    CANDIDATE_LIMIT = "candidate_limit"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class OfficeActionAnalysisError(ValueError):
    """Bounded analysis failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "office_action_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text).encode("utf-8"))


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
    if number != number or number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0.0, 1.0]")
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


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError(
        f"classification must be DisclosureClassification or str, got {type(value).__name__}"
    )


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(
        _require_str(item, f"{field}[{i}]", max_len=2048) for i, item in enumerate(value)
    )


def _frozen_str_map(
    value: Any,
    field: str,
    *,
    max_items: int = 64,
    allow_empty_values: bool = False,
    max_value_len: int = 2048,
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
        if not isinstance(raw, str):
            raise TypeError(f"{field}[{k}] must be str")
        if not raw and not allow_empty_values:
            raise ValueError(f"{field}[{k}] must be non-empty")
        if len(raw) > max_value_len:
            raise ValueError(f"{field}[{k}] exceeds max length {max_value_len}")
        out[k] = raw
    return MappingProxyType(out)


# ---------------------------------------------------------------------------
# Claim-range parsing (ambiguity-preserving)
# ---------------------------------------------------------------------------


def parse_claim_range_surface(surface: str) -> tuple[tuple[str, ...], ClaimRangeAmbiguity]:
    """Parse a claim-range surface into tokens while retaining ambiguity.

    Returns ``(claim_tokens, ambiguity)`` where claim_tokens are individual
    claim numbers as strings when resolvable. Open-ended or unresolved surfaces
    return empty tokens with an explicit ambiguity flag — never a silent guess.
    """
    text = _normalize_ws(surface or "")
    if not text:
        return (), ClaimRangeAmbiguity.UNRESOLVED

    lower = text.lower()
    # Strip leading "claim(s)" labels for body analysis.
    body = re.sub(r"(?i)^claims?\s*(?:nos?\.?)?\s*", "", lower).strip()
    body = re.sub(r"(?i)^claim\s+", "", body).strip()

    if re.search(r"\b(all|pending|remaining)\b", body):
        return (), ClaimRangeAmbiguity.OPEN_ENDED
    if re.search(r"\b(about|approximately|roughly|or so|ish)\b", body):
        return (), ClaimRangeAmbiguity.OPEN_ENDED
    if "?" in body or "…" in body or "..." in body:
        return (), ClaimRangeAmbiguity.UNRESOLVED

    # Normalize separators.
    cleaned = body.replace("–", "-").replace("—", "-")
    cleaned = re.sub(r"\bto\b", "-", cleaned)
    cleaned = re.sub(r"\band\b|&", ",", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)

    if not cleaned or not re.search(r"\d", cleaned):
        return (), ClaimRangeAmbiguity.UNRESOLVED

    tokens: list[str] = []
    segments = [s for s in cleaned.split(",") if s]
    multi = len(segments) > 1 or any("-" in s for s in segments)

    for seg in segments:
        if not seg:
            continue
        if "-" in seg:
            parts = seg.split("-", 1)
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                return (), ClaimRangeAmbiguity.UNRESOLVED
            start_n, end_n = int(parts[0]), int(parts[1])
            if start_n > end_n or end_n - start_n > 500:
                return (), ClaimRangeAmbiguity.CONFLICTING
            for n in range(start_n, end_n + 1):
                tokens.append(str(n))
        else:
            if not seg.isdigit():
                return (), ClaimRangeAmbiguity.UNRESOLVED
            tokens.append(str(int(seg)))

    if not tokens:
        return (), ClaimRangeAmbiguity.UNRESOLVED

    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            ordered.append(t)

    if multi:
        return tuple(ordered), ClaimRangeAmbiguity.MULTI_SEGMENT
    return tuple(ordered), ClaimRangeAmbiguity.EXACT


def _section_kind_from_match(match: re.Match[str]) -> SectionKind:
    if match.group("header"):
        label = match.group("header").lower()
        if "interview" in label:
            return SectionKind.INTERVIEW_SUMMARY
        if "summary" in label:
            return SectionKind.SUMMARY
        if "detailed" in label:
            return SectionKind.DETAILED_ACTION
        if "conclusion" in label:
            return SectionKind.CONCLUSION
        if "allowance" in label or "examiner" in label:
            return SectionKind.ALLOWABLE_SUBJECT_MATTER
        return SectionKind.HEADER
    if match.group("claim_rej"):
        return SectionKind.CLAIM_REJECTION
    if match.group("claim_obj"):
        return SectionKind.CLAIM_OBJECTION
    if match.group("draw_obj"):
        return SectionKind.DRAWING_OBJECTION
    if match.group("spec_obj"):
        return SectionKind.SPECIFICATION_OBJECTION
    if match.group("inform"):
        return SectionKind.INFORMALITY
    if match.group("allow"):
        return SectionKind.ALLOWABLE_SUBJECT_MATTER
    if match.group("response"):
        return SectionKind.RESPONSE_INSTRUCTION
    if match.group("cited"):
        return SectionKind.CITED_REFERENCES
    if match.group("fee"):
        return SectionKind.FEE_OR_FORM
    return SectionKind.OTHER


def _rejection_type_from_text(text: str) -> str:
    lower = text.lower()
    # Prefer more specific statutory anchors.
    m = re.search(
        r"35\s*u\.?\s*s\.?\s*c\.?\s*§?\s*(\d+)\s*(\([a-z0-9]+\))*",
        lower,
        re.I,
    )
    if m:
        section = m.group(1)
        subs = (m.group(2) or "").replace(" ", "")
        if section == "102":
            return f"rejection_102{subs}"
        if section == "103":
            return f"rejection_103{subs}"
        if section == "101":
            return f"rejection_101{subs}"
        if section == "112":
            if "(a)" in subs or "written description" in lower or "enablement" in lower:
                if "enablement" in lower:
                    return "rejection_112_enablement"
                if "written description" in lower:
                    return "rejection_112_written_description"
                return "rejection_112a"
            if "(b)" in subs or "indefinite" in lower:
                return "rejection_112b"
            return f"rejection_112{subs}"
        return f"rejection_{section}{subs}"
    if "obvious" in lower:
        return "rejection_103"
    if "anticipated" in lower or "anticipation" in lower:
        return "rejection_102"
    if "indefinite" in lower:
        return "rejection_112b"
    if "enablement" in lower:
        return "rejection_112_enablement"
    if "written description" in lower:
        return "rejection_112_written_description"
    return "rejection"


# ---------------------------------------------------------------------------
# Value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBounds:
    max_chars: int = DEFAULT_MAX_CHARS
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_sections: int = DEFAULT_MAX_SECTIONS
    max_model_candidates: int = DEFAULT_MAX_MODEL_CANDIDATES

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_chars", _nonneg_int(self.max_chars, "max_chars"))
        object.__setattr__(
            self, "max_candidates", _nonneg_int(self.max_candidates, "max_candidates")
        )
        object.__setattr__(
            self, "max_sections", _nonneg_int(self.max_sections, "max_sections")
        )
        object.__setattr__(
            self,
            "max_model_candidates",
            _nonneg_int(self.max_model_candidates, "max_model_candidates"),
        )


@dataclass(frozen=True, slots=True)
class ActionLifecycleRecord:
    """Lifecycle status of an office action (active / rescinded / reissued)."""

    schema_version: str
    action_id: str
    status: ActionLifecycleStatus
    mailing_date: str | None
    supersedes_action_id: str | None
    content_sha256: str | None
    source_span_id: str | None
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != OFFICE_ACTION_SCHEMA_VERSION:
            raise ValueError(
                "ActionLifecycleRecord.schema_version must be "
                f"{OFFICE_ACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(
            self, "status", _coerce_enum(ActionLifecycleStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "supersedes_action_id",
            _optional_identifier(self.supersedes_action_id, "supersedes_action_id"),
        )
        if self.content_sha256 is not None:
            digest = _require_str(self.content_sha256, "content_sha256", max_len=64).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("content_sha256 must be sha256 hex")
            object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "content_sha256": self.content_sha256,
            "mailing_date": self.mailing_date,
            "notes": list(self.notes),
            "schema_version": self.schema_version,
            "source_span_id": self.source_span_id,
            "status": self.status.value,
            "supersedes_action_id": self.supersedes_action_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActionLifecycleRecord":
        if not isinstance(value, Mapping):
            raise TypeError("ActionLifecycleRecord must be a mapping")
        return cls(
            schema_version=value.get("schema_version", OFFICE_ACTION_SCHEMA_VERSION),
            action_id=value.get("action_id", ""),
            status=value.get("status", ActionLifecycleStatus.UNKNOWN.value),
            mailing_date=value.get("mailing_date"),
            supersedes_action_id=value.get("supersedes_action_id"),
            content_sha256=value.get("content_sha256"),
            source_span_id=value.get("source_span_id"),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class SectionRecord:
    """A section of an office action with span provenance."""

    schema_version: str
    section_id: str
    kind: SectionKind
    title: str
    source_span_id: str
    char_start: int
    char_end: int
    text_digest: str
    reading_order: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "section_id", _identifier(self.section_id, "section_id"))
        object.__setattr__(self, "kind", _coerce_enum(SectionKind, self.kind, "kind"))
        object.__setattr__(
            self, "title", _require_str(self.title, "title", max_len=512)
        )
        object.__setattr__(
            self, "source_span_id", _identifier(self.source_span_id, "source_span_id")
        )
        object.__setattr__(
            self, "char_start", _nonneg_int(self.char_start, "char_start")
        )
        object.__setattr__(self, "char_end", _nonneg_int(self.char_end, "char_end"))
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        digest = _require_str(self.text_digest, "text_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(self, "text_digest", digest)
        object.__setattr__(
            self, "reading_order", _nonneg_int(self.reading_order, "reading_order")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_end": self.char_end,
            "char_start": self.char_start,
            "kind": self.kind.value,
            "reading_order": self.reading_order,
            "schema_version": self.schema_version,
            "section_id": self.section_id,
            "source_span_id": self.source_span_id,
            "text_digest": self.text_digest,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SectionRecord":
        if not isinstance(value, Mapping):
            raise TypeError("SectionRecord must be a mapping")
        return cls(
            schema_version=value.get("schema_version", OFFICE_ACTION_SCHEMA_VERSION),
            section_id=value.get("section_id", ""),
            kind=value.get("kind", SectionKind.OTHER.value),
            title=value.get("title", ""),
            source_span_id=value.get("source_span_id", ""),
            char_start=int(value.get("char_start", 0)),
            char_end=int(value.get("char_end", 0)),
            text_digest=value.get("text_digest", ""),
            reading_order=int(value.get("reading_order", 0)),
        )


@dataclass(frozen=True, slots=True)
class AnalysisCandidate:
    """A span-bound extraction candidate with explicit evidence layer.

    Model-origin candidates remain at ``EvidenceLayer.CANDIDATE`` until
    :func:`deterministically_validate_candidate` promotes them.
    """

    schema_version: str
    candidate_id: str
    kind: CandidateKind
    layer: EvidenceLayer
    origin: CandidateOrigin
    source_span_id: str
    text_digest: str
    surface_text: str
    confidence: float | None
    ambiguity: str | None
    claim_tokens: tuple[str, ...]
    legal_citations: tuple[str, ...]
    citation_keys: tuple[str, ...]
    citation_match_kind: str | None
    requirement_type: str | None
    alternatives: tuple[str, ...]
    exceptions: tuple[str, ...]
    labels: Mapping[str, str]
    validation_receipt_id: str | None
    review_state: ReviewState

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "kind", _coerce_enum(CandidateKind, self.kind, "kind"))
        object.__setattr__(
            self, "layer", _coerce_enum(EvidenceLayer, self.layer, "layer")
        )
        object.__setattr__(
            self, "origin", _coerce_enum(CandidateOrigin, self.origin, "origin")
        )
        object.__setattr__(
            self, "source_span_id", _identifier(self.source_span_id, "source_span_id")
        )
        digest = _require_str(self.text_digest, "text_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(self, "text_digest", digest)
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        if len(self.surface_text) > 8000:
            raise ValueError("surface_text exceeds max length 8000")
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "ambiguity", _optional_str(self.ambiguity, "ambiguity", max_len=64)
        )
        object.__setattr__(
            self,
            "claim_tokens",
            _tuple_of_str(self.claim_tokens, "claim_tokens", max_items=256),
        )
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
            "citation_match_kind",
            _optional_str(self.citation_match_kind, "citation_match_kind", max_len=64),
        )
        object.__setattr__(
            self,
            "requirement_type",
            _optional_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self,
            "alternatives",
            _tuple_of_str(self.alternatives, "alternatives", max_items=32),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_str(self.exceptions, "exceptions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "validation_receipt_id",
            _optional_identifier(self.validation_receipt_id, "validation_receipt_id"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        # Fail closed: model origin can never already be verified.
        if (
            self.origin is CandidateOrigin.MODEL
            and self.layer is EvidenceLayer.VERIFIED
            and self.validation_receipt_id is None
        ):
            raise ValueError(
                "model candidates cannot enter verified layer without "
                "deterministic validation receipt"
            )

    @property
    def is_verified(self) -> bool:
        return self.layer is EvidenceLayer.VERIFIED

    @property
    def is_model_origin(self) -> bool:
        return self.origin is CandidateOrigin.MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternatives": list(self.alternatives),
            "ambiguity": self.ambiguity,
            "candidate_id": self.candidate_id,
            "citation_keys": list(self.citation_keys),
            "citation_match_kind": self.citation_match_kind,
            "claim_tokens": list(self.claim_tokens),
            "confidence": self.confidence,
            "exceptions": list(self.exceptions),
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "layer": self.layer.value,
            "legal_citations": list(self.legal_citations),
            "origin": self.origin.value,
            "requirement_type": self.requirement_type,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_span_id": self.source_span_id,
            "surface_text": self.surface_text,
            "text_digest": self.text_digest,
            "validation_receipt_id": self.validation_receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisCandidate":
        if not isinstance(value, Mapping):
            raise TypeError("AnalysisCandidate must be a mapping")
        return cls(
            schema_version=value.get("schema_version", OFFICE_ACTION_SCHEMA_VERSION),
            candidate_id=value.get("candidate_id", ""),
            kind=value.get("kind", CandidateKind.OTHER.value),
            layer=value.get("layer", EvidenceLayer.CANDIDATE.value),
            origin=value.get("origin", CandidateOrigin.OTHER.value),
            source_span_id=value.get("source_span_id", ""),
            text_digest=value.get("text_digest", ""),
            surface_text=str(value.get("surface_text") or ""),
            confidence=value.get("confidence"),
            ambiguity=value.get("ambiguity"),
            claim_tokens=tuple(value.get("claim_tokens") or ()),
            legal_citations=tuple(value.get("legal_citations") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            citation_match_kind=value.get("citation_match_kind"),
            requirement_type=value.get("requirement_type"),
            alternatives=tuple(value.get("alternatives") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            labels=value.get("labels") or {},
            validation_receipt_id=value.get("validation_receipt_id"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
        )


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    """Receipt proving deterministic span validation of a candidate."""

    schema_version: str
    receipt_id: str
    candidate_id: str
    source_span_id: str
    passed: bool
    checks: tuple[str, ...]
    failure_reasons: tuple[str, ...]
    ruleset_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "source_span_id", _identifier(self.source_span_id, "source_span_id")
        )
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be bool")
        object.__setattr__(
            self, "checks", _tuple_of_str(self.checks, "checks", max_items=32)
        )
        object.__setattr__(
            self,
            "failure_reasons",
            _tuple_of_str(self.failure_reasons, "failure_reasons", max_items=32),
        )
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "checks": list(self.checks),
            "failure_reasons": list(self.failure_reasons),
            "passed": self.passed,
            "receipt_id": self.receipt_id,
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "source_span_id": self.source_span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("ValidationReceipt must be a mapping")
        return cls(
            schema_version=value.get("schema_version", OFFICE_ACTION_SCHEMA_VERSION),
            receipt_id=value.get("receipt_id", ""),
            candidate_id=value.get("candidate_id", ""),
            source_span_id=value.get("source_span_id", ""),
            passed=bool(value.get("passed", False)),
            checks=tuple(value.get("checks") or ()),
            failure_reasons=tuple(value.get("failure_reasons") or ()),
            ruleset_version=value.get(
                "ruleset_version", OFFICE_ACTION_RULESET_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelCandidateInput:
    """External (model) candidate held out of the verified layer by default."""

    kind: CandidateKind | str
    surface_text: str
    source_span_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    confidence: float | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    claim_tokens: tuple[str, ...] = ()
    legal_citations: tuple[str, ...] = ()
    requirement_type: str | None = None


@dataclass(frozen=True, slots=True)
class OfficeActionInput:
    """Inputs for office-action analysis.

    Prefer providing spans from PATLAW-031 extraction. When only full text is
    available, a covering span is minted so every candidate still has a span id.
    """

    artifact_id: str
    text: str
    spans: tuple[ExtractedSpan, ...] = ()
    # Optional map span_id -> surface text for digest checks.
    span_texts: Mapping[str, str] = MappingProxyType({})
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    action_id: str | None = None
    lifecycle: tuple[ActionLifecycleRecord, ...] = ()
    model_candidates: tuple[ModelCandidateInput, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})
    mailing_date: str | None = None
    document_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans or ()))
        object.__setattr__(
            self,
            "span_texts",
            _frozen_str_map(
                self.span_texts,
                "span_texts",
                max_items=DEFAULT_MAX_CANDIDATES,
                allow_empty_values=True,
                max_value_len=DEFAULT_MAX_CHARS,
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        if not isinstance(self.lifecycle, tuple):
            object.__setattr__(self, "lifecycle", tuple(self.lifecycle or ()))
        if not isinstance(self.model_candidates, tuple):
            object.__setattr__(
                self, "model_candidates", tuple(self.model_candidates or ())
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "document_kind",
            _optional_str(self.document_kind, "document_kind", max_len=128),
        )


@dataclass(frozen=True, slots=True)
class OfficeActionResult:
    """Full office-action analysis outcome with layered candidates."""

    schema_version: str
    analysis_id: str
    artifact_id: str
    action_id: str
    action_kind: OfficeActionKind
    disposition: AnalysisDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    sections: tuple[SectionRecord, ...]
    candidates: tuple[AnalysisCandidate, ...]
    validation_receipts: tuple[ValidationReceipt, ...]
    requirements: tuple[GovernmentRequirement, ...]
    lifecycle: tuple[ActionLifecycleRecord, ...]
    spans: tuple[ExtractedSpan, ...]
    mailing_date: str | None
    application_number: str | None
    labels: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    model_versions: Mapping[str, str]
    text_digest: str
    retained: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != OFFICE_ACTION_SCHEMA_VERSION:
            raise ValueError(
                "OfficeActionResult.schema_version must be "
                f"{OFFICE_ACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(
            self,
            "action_kind",
            _coerce_enum(OfficeActionKind, self.action_kind, "action_kind"),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(AnalysisDisposition, self.disposition, "disposition"),
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
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        if not isinstance(self.sections, tuple):
            object.__setattr__(self, "sections", tuple(self.sections))
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if not isinstance(self.validation_receipts, tuple):
            object.__setattr__(
                self, "validation_receipts", tuple(self.validation_receipts)
            )
        if not isinstance(self.requirements, tuple):
            object.__setattr__(self, "requirements", tuple(self.requirements))
        if not isinstance(self.lifecycle, tuple):
            object.__setattr__(self, "lifecycle", tuple(self.lifecycle))
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=16),
        )
        object.__setattr__(
            self,
            "model_versions",
            _frozen_str_map(self.model_versions, "model_versions", max_items=16),
        )
        digest = _require_str(self.text_digest, "text_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(self, "text_digest", digest)
        if not isinstance(self.retained, bool):
            raise TypeError("retained must be bool")
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)
        # Invariant: no model candidate in verified without receipt.
        for cand in self.candidates:
            if (
                cand.origin is CandidateOrigin.MODEL
                and cand.layer is EvidenceLayer.VERIFIED
                and not cand.validation_receipt_id
            ):
                raise ValueError(
                    "model candidates never enter verified layer without "
                    "deterministic validation"
                )

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            AnalysisDisposition.REVIEW,
            AnalysisDisposition.MALFORMED,
            AnalysisDisposition.QUARANTINE,
            AnalysisDisposition.REJECTED,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def candidates_by_layer(self, layer: EvidenceLayer | str) -> tuple[AnalysisCandidate, ...]:
        target = _coerce_enum(EvidenceLayer, layer, "layer")
        return tuple(c for c in self.candidates if c.layer is target)

    def candidates_by_kind(self, kind: CandidateKind | str) -> tuple[AnalysisCandidate, ...]:
        target = _coerce_enum(CandidateKind, kind, "kind")
        return tuple(c for c in self.candidates if c.kind is target)

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def candidate_by_id(self, candidate_id: str) -> AnalysisCandidate | None:
        for cand in self.candidates:
            if cand.candidate_id == candidate_id:
                return cand
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind.value,
            "analysis_id": self.analysis_id,
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "candidates": [c.to_dict() for c in self.candidates],
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "labels": dict(self.labels),
            "lifecycle": [x.to_dict() for x in self.lifecycle],
            "mailing_date": self.mailing_date,
            "model_versions": dict(self.model_versions),
            "reason_codes": list(self.reason_codes),
            "requirements": [r.to_dict() for r in self.requirements],
            "retained": self.retained,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "sections": [s.to_dict() for s in self.sections],
            "spans": [s.to_dict() for s in self.spans],
            "text_digest": self.text_digest,
            "validation_receipts": [v.to_dict() for v in self.validation_receipts],
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — never body text or surface strings."""
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind.value,
            "analysis_id": self.analysis_id,
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "candidate_count": len(self.candidates),
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "lifecycle_count": len(self.lifecycle),
            "mailing_date": self.mailing_date,
            "reason_codes": list(self.reason_codes),
            "requirement_count": len(self.requirements),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "section_count": len(self.sections),
            "span_count": len(self.spans),
            "text_digest": self.text_digest,
            "verified_candidate_count": sum(
                1 for c in self.candidates if c.layer is EvidenceLayer.VERIFIED
            ),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OfficeActionResult":
        if not isinstance(value, Mapping):
            raise TypeError("OfficeActionResult must be a mapping")
        return cls(
            schema_version=value.get("schema_version", OFFICE_ACTION_SCHEMA_VERSION),
            analysis_id=value.get("analysis_id", ""),
            artifact_id=value.get("artifact_id", ""),
            action_id=value.get("action_id", ""),
            action_kind=value.get("action_kind", OfficeActionKind.UNKNOWN.value),
            disposition=value.get("disposition", AnalysisDisposition.REVIEW.value),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            sections=tuple(
                SectionRecord.from_dict(s) for s in (value.get("sections") or ())
            ),
            candidates=tuple(
                AnalysisCandidate.from_dict(c)
                for c in (value.get("candidates") or ())
            ),
            validation_receipts=tuple(
                ValidationReceipt.from_dict(v)
                for v in (value.get("validation_receipts") or ())
            ),
            requirements=tuple(
                GovernmentRequirement.from_dict(r)
                for r in (value.get("requirements") or ())
            ),
            lifecycle=tuple(
                ActionLifecycleRecord.from_dict(x)
                for x in (value.get("lifecycle") or ())
            ),
            spans=tuple(
                ExtractedSpan.from_dict(s) for s in (value.get("spans") or ())
            ),
            mailing_date=value.get("mailing_date"),
            application_number=value.get("application_number"),
            labels=value.get("labels") or {},
            ruleset_versions=value.get("ruleset_versions") or {},
            model_versions=value.get("model_versions") or {},
            text_digest=value.get("text_digest", ""),
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Deterministic span validation (gate into verified layer)
# ---------------------------------------------------------------------------


def deterministically_validate_candidate(
    candidate: AnalysisCandidate,
    *,
    spans: Mapping[str, ExtractedSpan] | Sequence[ExtractedSpan],
    span_texts: Mapping[str, str] | None = None,
    full_text: str | None = None,
    receipt_id: str | None = None,
    ruleset_version: str = OFFICE_ACTION_RULESET_VERSION,
) -> tuple[AnalysisCandidate, ValidationReceipt]:
    """Validate a candidate against exact spans; promote to verified only on pass.

    Model-origin candidates are treated identically for span checks — there is
    no shortcut into the verified layer. Failures leave the candidate at
    ``CANDIDATE`` (or ``DETERMINISTIC`` if already deterministic) with a failed
    receipt.
    """
    span_index: dict[str, ExtractedSpan]
    if isinstance(spans, Mapping):
        span_index = dict(spans)
    else:
        span_index = {s.span_id: s for s in spans}

    checks: list[str] = []
    failures: list[str] = []
    rid = receipt_id or f"val:{uuid.uuid4().hex[:16]}"

    span = span_index.get(candidate.source_span_id)
    if span is None:
        failures.append("missing_source_span")
    else:
        checks.append("source_span_present")
        if span.char_start is not None and span.char_end is not None:
            if span.char_end < span.char_start:
                failures.append("invalid_span_char_range")
            else:
                checks.append("span_char_range_ordered")
        if span.text_digest:
            checks.append("span_has_text_digest")

    # Surface text digest must match declared text_digest.
    surface_digest = _text_digest(candidate.surface_text)
    if surface_digest != candidate.text_digest:
        failures.append("surface_text_digest_mismatch")
    else:
        checks.append("surface_text_digest_match")

    # If span text is available, surface must be a substring (or equal digest).
    span_text_map = dict(span_texts or {})
    if span is not None and candidate.source_span_id in span_text_map:
        host = span_text_map[candidate.source_span_id]
        if candidate.surface_text and candidate.surface_text not in host:
            # Allow whitespace-normalized containment.
            if _normalize_ws(candidate.surface_text) not in _normalize_ws(host):
                failures.append("surface_not_in_span_text")
            else:
                checks.append("surface_in_span_text_normalized")
        else:
            checks.append("surface_in_span_text")
    elif full_text is not None and candidate.surface_text:
        if candidate.surface_text in full_text or _normalize_ws(
            candidate.surface_text
        ) in _normalize_ws(full_text):
            checks.append("surface_in_full_text")
        else:
            # Still allow if span digest matches surface (minted covering span).
            if span is not None and span.text_digest == candidate.text_digest:
                checks.append("surface_matches_span_digest")
            else:
                failures.append("surface_not_located_in_text")

    # Non-empty surface for most kinds (uncompiled may be short markers).
    if not candidate.surface_text.strip():
        failures.append("empty_surface_text")
    else:
        checks.append("non_empty_surface")

    passed = not failures
    receipt = ValidationReceipt(
        schema_version=OFFICE_ACTION_SCHEMA_VERSION,
        receipt_id=rid,
        candidate_id=candidate.candidate_id,
        source_span_id=candidate.source_span_id,
        passed=passed,
        checks=tuple(checks),
        failure_reasons=tuple(failures),
        ruleset_version=ruleset_version,
    )

    if passed:
        promoted = AnalysisCandidate(
            schema_version=candidate.schema_version,
            candidate_id=candidate.candidate_id,
            kind=candidate.kind,
            layer=EvidenceLayer.VERIFIED,
            origin=candidate.origin,
            source_span_id=candidate.source_span_id,
            text_digest=candidate.text_digest,
            surface_text=candidate.surface_text,
            confidence=candidate.confidence,
            ambiguity=candidate.ambiguity,
            claim_tokens=candidate.claim_tokens,
            legal_citations=candidate.legal_citations,
            citation_keys=candidate.citation_keys,
            citation_match_kind=candidate.citation_match_kind,
            requirement_type=candidate.requirement_type,
            alternatives=candidate.alternatives,
            exceptions=candidate.exceptions,
            labels=dict(candidate.labels),
            validation_receipt_id=receipt.receipt_id,
            review_state=ReviewState.NOT_REQUIRED
            if candidate.origin is not CandidateOrigin.MODEL
            else ReviewState.PENDING,
        )
        return promoted, receipt

    # Keep model candidates in CANDIDATE; deterministic stay deterministic.
    hold_layer = (
        EvidenceLayer.CANDIDATE
        if candidate.origin is CandidateOrigin.MODEL
        else (
            candidate.layer
            if candidate.layer is not EvidenceLayer.VERIFIED
            else EvidenceLayer.DETERMINISTIC
        )
    )
    held = AnalysisCandidate(
        schema_version=candidate.schema_version,
        candidate_id=candidate.candidate_id,
        kind=candidate.kind,
        layer=hold_layer,
        origin=candidate.origin,
        source_span_id=candidate.source_span_id,
        text_digest=candidate.text_digest,
        surface_text=candidate.surface_text,
        confidence=candidate.confidence,
        ambiguity=candidate.ambiguity,
        claim_tokens=candidate.claim_tokens,
        legal_citations=candidate.legal_citations,
        citation_keys=candidate.citation_keys,
        citation_match_kind=candidate.citation_match_kind,
        requirement_type=candidate.requirement_type,
        alternatives=candidate.alternatives,
        exceptions=candidate.exceptions,
        labels=dict(candidate.labels),
        validation_receipt_id=receipt.receipt_id,
        review_state=ReviewState.REQUIRED,
    )
    return held, receipt


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class OfficeActionProcessor:
    """Section and extract government instructions from office actions."""

    def __init__(
        self,
        *,
        bounds: AnalysisBounds | None = None,
        id_factory: Callable[[], str] | None = None,
        auto_validate: bool = True,
    ) -> None:
        self.bounds = bounds or AnalysisBounds()
        self._id_factory = id_factory or (lambda: f"oa:{uuid.uuid4().hex}")
        self.auto_validate = bool(auto_validate)

    def analyze(
        self,
        value: OfficeActionInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> OfficeActionResult:
        inp = self._coerce_input(value, **kwargs)
        return self._analyze(inp)

    def analyze_many(
        self, values: Iterable[OfficeActionInput | Mapping[str, Any]]
    ) -> list[OfficeActionResult]:
        return [self.analyze(v) for v in values]

    def _coerce_input(
        self,
        value: OfficeActionInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> OfficeActionInput:
        if value is None:
            return OfficeActionInput(**kwargs)
        if isinstance(value, OfficeActionInput):
            if kwargs:
                raise TypeError("cannot mix OfficeActionInput with kwargs")
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            spans_raw = data.get("spans") or ()
            spans: list[ExtractedSpan] = []
            for s in spans_raw:
                if isinstance(s, ExtractedSpan):
                    spans.append(s)
                elif isinstance(s, Mapping):
                    spans.append(ExtractedSpan.from_dict(s))
            lifecycle_raw = data.get("lifecycle") or ()
            lifecycle: list[ActionLifecycleRecord] = []
            for item in lifecycle_raw:
                if isinstance(item, ActionLifecycleRecord):
                    lifecycle.append(item)
                elif isinstance(item, Mapping):
                    lifecycle.append(ActionLifecycleRecord.from_dict(item))
            model_raw = data.get("model_candidates") or ()
            model_cands: list[ModelCandidateInput] = []
            for item in model_raw:
                if isinstance(item, ModelCandidateInput):
                    model_cands.append(item)
                elif isinstance(item, Mapping):
                    model_cands.append(
                        ModelCandidateInput(
                            kind=item.get("kind", CandidateKind.OTHER.value),
                            surface_text=str(item.get("surface_text") or ""),
                            source_span_id=item.get("source_span_id"),
                            char_start=item.get("char_start"),
                            char_end=item.get("char_end"),
                            confidence=item.get("confidence"),
                            labels=item.get("labels") or {},
                            claim_tokens=tuple(item.get("claim_tokens") or ()),
                            legal_citations=tuple(item.get("legal_citations") or ()),
                            requirement_type=item.get("requirement_type"),
                        )
                    )
            return OfficeActionInput(
                artifact_id=data.get("artifact_id", ""),
                text=str(data.get("text") or ""),
                spans=tuple(spans),
                span_texts=data.get("span_texts") or {},
                classification=data.get(
                    "classification", DisclosureClassification.UNKNOWN.value
                ),
                action_id=data.get("action_id"),
                lifecycle=tuple(lifecycle),
                model_candidates=tuple(model_cands),
                labels=data.get("labels") or {},
                mailing_date=data.get("mailing_date"),
                document_kind=data.get("document_kind"),
            )
        raise TypeError(
            f"unsupported input type: {type(value).__name__}; "
            "expected OfficeActionInput or mapping"
        )

    def _analyze(self, inp: OfficeActionInput) -> OfficeActionResult:
        analysis_id = self._id_factory()
        reason_codes: list[str] = []
        warnings: list[str] = []
        classification = inp.classification

        if requires_quarantine(classification):
            reason_codes.append(OfficeActionReasonCode.QUARANTINE_CLASSIFICATION.value)

        text = inp.text or ""
        if len(text) > self.bounds.max_chars:
            reason_codes.append(OfficeActionReasonCode.OVERSIZE_TEXT.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                disposition=AnalysisDisposition.REJECTED,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes + [OfficeActionReasonCode.OVERSIZE_TEXT.value],
                warnings=("text exceeds analysis bounds",),
                action_kind=OfficeActionKind.MALFORMED,
            )

        if not text.strip():
            reason_codes.append(OfficeActionReasonCode.EMPTY_TEXT.value)
            reason_codes.append(OfficeActionReasonCode.MALFORMED_ACTION.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                disposition=AnalysisDisposition.MALFORMED,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=("empty office action text",),
                action_kind=OfficeActionKind.MALFORMED,
            )

        spans, span_texts, minted = self._ensure_spans(inp, analysis_id)
        if minted:
            reason_codes.append(OfficeActionReasonCode.MISSING_SPANS.value)
            warnings.append("covering span minted from full text")

        span_index = {s.span_id: s for s in spans}
        covering_span_id = self._covering_span_id(spans, text, span_texts)

        # --- lifecycle ---
        lifecycle = self._resolve_lifecycle(inp, covering_span_id, text, reason_codes)

        # --- kind ---
        action_kind = self._detect_kind(text, inp.document_kind, lifecycle)

        # --- sections ---
        sections, section_cands = self._extract_sections(
            text=text,
            analysis_id=analysis_id,
            covering_span_id=covering_span_id,
            span_index=span_index,
        )
        if sections:
            reason_codes.append(OfficeActionReasonCode.SECTIONS_EXTRACTED.value)

        candidates: list[AnalysisCandidate] = list(section_cands)

        # --- claim ranges ---
        claim_cands = self._extract_claim_ranges(
            text, analysis_id, covering_span_id, span_index
        )
        if claim_cands:
            reason_codes.append(OfficeActionReasonCode.CLAIM_RANGES_EXTRACTED.value)
            if any(
                c.ambiguity
                and c.ambiguity
                != ClaimRangeAmbiguity.EXACT.value
                for c in claim_cands
            ):
                reason_codes.append(OfficeActionReasonCode.AMBIGUOUS_CLAIM_RANGE.value)
        candidates.extend(claim_cands)

        # --- rejections / objections / informalities ---
        rej_cands = self._extract_rejections(text, analysis_id, covering_span_id)
        if rej_cands:
            reason_codes.append(OfficeActionReasonCode.REJECTIONS_EXTRACTED.value)
        candidates.extend(rej_cands)

        obj_cands = self._extract_objections(text, analysis_id, covering_span_id)
        if obj_cands:
            reason_codes.append(OfficeActionReasonCode.OBJECTIONS_EXTRACTED.value)
        candidates.extend(obj_cands)

        inf_cands = self._extract_informalities(text, analysis_id, covering_span_id)
        candidates.extend(inf_cands)

        # --- citations (parse only; no authority assertion) ---
        cit_cands = self._extract_citations(text, analysis_id, covering_span_id)
        if cit_cands:
            reason_codes.append(OfficeActionReasonCode.CITATIONS_EXTRACTED.value)
            if any(
                c.citation_match_kind
                in (
                    CitationMatchKind.AMBIGUOUS.value,
                    CitationMatchKind.UNRESOLVED.value,
                    CitationMatchKind.PARTIAL.value,
                )
                for c in cit_cands
            ):
                reason_codes.append(OfficeActionReasonCode.AMBIGUOUS_CITATION.value)
        candidates.extend(cit_cands)

        # form paragraphs / fees / forms are citation families; also prior art refs
        if any(c.kind is CandidateKind.FORM_PARAGRAPH for c in cit_cands):
            reason_codes.append(OfficeActionReasonCode.FORM_PARAGRAPHS_EXTRACTED.value)

        prior_cands = self._extract_prior_art(text, analysis_id, covering_span_id)
        candidates.extend(prior_cands)

        # --- response instructions / alternatives / exceptions ---
        resp_cands = self._extract_response_instructions(
            text, analysis_id, covering_span_id
        )
        if resp_cands:
            reason_codes.append(
                OfficeActionReasonCode.RESPONSE_INSTRUCTIONS_EXTRACTED.value
            )
        candidates.extend(resp_cands)

        alt_cands = self._extract_pattern_candidates(
            text,
            analysis_id,
            covering_span_id,
            pattern=_ALTERNATIVE_RE,
            kind=CandidateKind.ALTERNATIVE,
            confidence=0.7,
        )
        candidates.extend(alt_cands)

        exc_cands = self._extract_pattern_candidates(
            text,
            analysis_id,
            covering_span_id,
            pattern=_EXCEPTION_RE,
            kind=CandidateKind.EXCEPTION,
            confidence=0.65,
        )
        candidates.extend(exc_cands)

        # --- uncompiled residual language ---
        uncompiled = self._extract_uncompiled(
            text, analysis_id, covering_span_id, candidates
        )
        if uncompiled:
            reason_codes.append(OfficeActionReasonCode.UNCOMPILED_LANGUAGE.value)
        candidates.extend(uncompiled)

        # --- model candidates (held out of verified by default) ---
        model_cands, model_warnings = self._ingest_model_candidates(
            inp, analysis_id, covering_span_id, span_index
        )
        if model_cands:
            reason_codes.append(OfficeActionReasonCode.MODEL_CANDIDATE_HELD.value)
        warnings.extend(model_warnings)
        candidates.extend(model_cands)

        # Bound candidates.
        if len(candidates) > self.bounds.max_candidates:
            reason_codes.append(OfficeActionReasonCode.CANDIDATE_LIMIT.value)
            warnings.append("candidate list truncated to analysis bounds")
            candidates = candidates[: self.bounds.max_candidates]

        # --- deterministic validation / promotion ---
        receipts: list[ValidationReceipt] = []
        final_candidates: list[AnalysisCandidate] = []
        if self.auto_validate:
            for cand in candidates:
                # Model candidates: validate but never skip the gate.
                promoted, receipt = deterministically_validate_candidate(
                    cand,
                    spans=span_index,
                    span_texts=span_texts,
                    full_text=text,
                    receipt_id=f"val:{analysis_id}:{len(receipts)+1:04d}",
                )
                receipts.append(receipt)
                if (
                    cand.origin is CandidateOrigin.MODEL
                    and promoted.layer is EvidenceLayer.VERIFIED
                ):
                    # Allowed only because validation receipt is attached.
                    reason_codes.append(
                        OfficeActionReasonCode.DETERMINISTIC_VALIDATION_PASSED.value
                    )
                elif (
                    cand.origin is CandidateOrigin.MODEL
                    and promoted.layer is not EvidenceLayer.VERIFIED
                ):
                    reason_codes.append(
                        OfficeActionReasonCode.MODEL_CANDIDATE_BLOCKED_FROM_VERIFIED.value
                    )
                elif receipt.passed:
                    reason_codes.append(
                        OfficeActionReasonCode.DETERMINISTIC_VALIDATION_PASSED.value
                    )
                else:
                    reason_codes.append(
                        OfficeActionReasonCode.DETERMINISTIC_VALIDATION_FAILED.value
                    )
                final_candidates.append(promoted)
        else:
            final_candidates = candidates

        # Deduplicate reason codes while preserving order.
        reason_codes = list(dict.fromkeys(reason_codes))

        # --- GovernmentRequirement emission (verified instruction-like only) ---
        requirements = self._emit_requirements(
            analysis_id=analysis_id,
            candidates=final_candidates,
            lifecycle=lifecycle,
            classification=classification,
        )
        if requirements:
            reason_codes.append(OfficeActionReasonCode.REQUIREMENTS_EMITTED.value)
            reason_codes = list(dict.fromkeys(reason_codes))

        mailing = inp.mailing_date
        if not mailing:
            m = _MAILING_DATE_RE.search(text)
            if m:
                mailing = m.group("date")

        app_no = None
        am = _APPLICATION_NO_RE.search(text)
        if am:
            app_no = am.group("app")

        disposition, review_state = self._disposition(
            action_kind=action_kind,
            lifecycle=lifecycle,
            candidates=final_candidates,
            classification=classification,
            reason_codes=reason_codes,
        )

        return OfficeActionResult(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            analysis_id=analysis_id,
            artifact_id=inp.artifact_id,
            action_id=inp.action_id or f"action:{analysis_id}",
            action_kind=action_kind,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(reason_codes),
            warnings=tuple(dict.fromkeys(warnings)),
            sections=tuple(sections[: self.bounds.max_sections]),
            candidates=tuple(final_candidates),
            validation_receipts=tuple(receipts),
            requirements=tuple(requirements),
            lifecycle=tuple(lifecycle),
            spans=tuple(spans),
            mailing_date=mailing,
            application_number=app_no,
            labels=dict(inp.labels),
            ruleset_versions={
                "office_action": OFFICE_ACTION_RULESET_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
            },
            model_versions={},
            text_digest=_text_digest(text),
            retained=True,
        )

    # -- span helpers -------------------------------------------------------

    def _ensure_spans(
        self, inp: OfficeActionInput, analysis_id: str
    ) -> tuple[list[ExtractedSpan], dict[str, str], bool]:
        spans = list(inp.spans)
        span_texts = dict(inp.span_texts)
        minted = False
        if not spans:
            minted = True
            span_id = f"span:{analysis_id}:cover"
            digest = _text_digest(inp.text)
            spans.append(
                ExtractedSpan(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    span_id=span_id,
                    artifact_id=inp.artifact_id,
                    page_index=0,
                    char_start=0,
                    char_end=len(inp.text),
                    bbox=None,
                    origin=ExtractionOrigin.UNKNOWN,
                    reading_order=0,
                    confidence=None,
                    text_digest=digest,
                    image_digest=None,
                    classification=inp.classification,
                )
            )
            span_texts[span_id] = inp.text
        else:
            # Ensure span_texts cover provided spans when possible.
            for span in spans:
                if span.span_id not in span_texts and span.char_start is not None:
                    end = span.char_end if span.char_end is not None else span.char_start
                    if 0 <= span.char_start <= end <= len(inp.text):
                        span_texts[span.span_id] = inp.text[span.char_start : end]
        return spans, span_texts, minted

    def _covering_span_id(
        self,
        spans: Sequence[ExtractedSpan],
        text: str,
        span_texts: Mapping[str, str],
    ) -> str:
        # Prefer a span that covers the full text; else first span.
        for span in spans:
            st = span_texts.get(span.span_id, "")
            if st == text or (
                span.char_start == 0
                and span.char_end is not None
                and span.char_end >= len(text)
            ):
                return span.span_id
        return spans[0].span_id

    # -- lifecycle / kind ---------------------------------------------------

    def _resolve_lifecycle(
        self,
        inp: OfficeActionInput,
        covering_span_id: str,
        text: str,
        reason_codes: list[str],
    ) -> list[ActionLifecycleRecord]:
        records = list(inp.lifecycle)
        if records:
            for rec in records:
                if rec.status is ActionLifecycleStatus.RESCINDED:
                    reason_codes.append(OfficeActionReasonCode.LIFECYCLE_RESCINDED.value)
                if rec.status is ActionLifecycleStatus.REISSUED:
                    reason_codes.append(OfficeActionReasonCode.LIFECYCLE_REISSUED.value)
                if rec.status is ActionLifecycleStatus.SUPERSEDED:
                    reason_codes.append(
                        OfficeActionReasonCode.LIFECYCLE_SUPERSEDED.value
                    )
            return records

        # Infer from text cues when metadata absent.
        # Prefer reissue when both reissue and rescind language appear (typical
        # reissued OA withdraws the prior action).
        status = ActionLifecycleStatus.ACTIVE
        notes: list[str] = []
        if _REISSUE_RE.search(text):
            status = ActionLifecycleStatus.REISSUED
            notes.append("inferred_reissue_language")
            reason_codes.append(OfficeActionReasonCode.LIFECYCLE_REISSUED.value)
            if _RESCIND_RE.search(text):
                notes.append("prior_action_withdrawn_language")
                reason_codes.append(OfficeActionReasonCode.LIFECYCLE_RESCINDED.value)
        elif _RESCIND_RE.search(text):
            status = ActionLifecycleStatus.RESCINDED
            notes.append("inferred_rescind_language")
            reason_codes.append(OfficeActionReasonCode.LIFECYCLE_RESCINDED.value)

        action_id = inp.action_id or f"action:{inp.artifact_id}"
        return [
            ActionLifecycleRecord(
                schema_version=OFFICE_ACTION_SCHEMA_VERSION,
                action_id=action_id,
                status=status,
                mailing_date=inp.mailing_date,
                supersedes_action_id=None,
                content_sha256=None,
                source_span_id=covering_span_id,
                notes=tuple(notes),
            )
        ]

    def _detect_kind(
        self,
        text: str,
        document_kind: str | None,
        lifecycle: Sequence[ActionLifecycleRecord],
    ) -> OfficeActionKind:
        # Prefer reissued/active instrument of record over historical rescinded.
        statuses = {rec.status for rec in lifecycle}
        if ActionLifecycleStatus.REISSUED in statuses:
            return OfficeActionKind.REISSUED_ACTION
        if ActionLifecycleStatus.RESCINDED in statuses and not (
            ActionLifecycleStatus.ACTIVE in statuses
            or ActionLifecycleStatus.REISSUED in statuses
        ):
            return OfficeActionKind.RESCINDED_ACTION
        if document_kind:
            dk = document_kind.lower().replace("-", "_").replace(" ", "_")
            for kind in OfficeActionKind:
                if kind.value == dk:
                    return kind
        lower = text.lower()
        if "notice of allowance" in lower:
            return OfficeActionKind.NOTICE_OF_ALLOWANCE
        if "interview summary" in lower:
            return OfficeActionKind.INTERVIEW_SUMMARY
        if "examiner's amendment" in lower or "examiner amendment" in lower:
            return OfficeActionKind.EXAMINER_AMENDMENT
        if _FINALITY_RE.search(text) and not _NONFINAL_RE.search(text):
            return OfficeActionKind.FINAL_REJECTION
        if _NONFINAL_RE.search(text) or "claim rejections" in lower or "claims" in lower:
            if "ex parte quayle" in lower:
                return OfficeActionKind.EX_PARTE_QUAYLE
            return OfficeActionKind.NON_FINAL_REJECTION
        if "notice" in lower:
            return OfficeActionKind.NOTICE
        return OfficeActionKind.UNKNOWN

    # -- extractors ---------------------------------------------------------

    def _make_candidate(
        self,
        *,
        analysis_id: str,
        seq: int,
        kind: CandidateKind,
        origin: CandidateOrigin,
        layer: EvidenceLayer,
        source_span_id: str,
        surface: str,
        confidence: float | None = None,
        ambiguity: str | None = None,
        claim_tokens: tuple[str, ...] = (),
        legal_citations: tuple[str, ...] = (),
        citation_keys: tuple[str, ...] = (),
        citation_match_kind: str | None = None,
        requirement_type: str | None = None,
        alternatives: tuple[str, ...] = (),
        exceptions: tuple[str, ...] = (),
        labels: Mapping[str, str] | None = None,
        review_state: ReviewState = ReviewState.PENDING,
    ) -> AnalysisCandidate:
        surface_clipped = surface if len(surface) <= 8000 else surface[:8000]
        return AnalysisCandidate(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            candidate_id=f"cand:{analysis_id}:{seq:04d}",
            kind=kind,
            layer=layer,
            origin=origin,
            source_span_id=source_span_id,
            text_digest=_text_digest(surface_clipped),
            surface_text=surface_clipped,
            confidence=confidence,
            ambiguity=ambiguity,
            claim_tokens=claim_tokens,
            legal_citations=legal_citations,
            citation_keys=citation_keys,
            citation_match_kind=citation_match_kind,
            requirement_type=requirement_type,
            alternatives=alternatives,
            exceptions=exceptions,
            labels=dict(labels or {}),
            validation_receipt_id=None,
            review_state=review_state,
        )

    def _extract_sections(
        self,
        *,
        text: str,
        analysis_id: str,
        covering_span_id: str,
        span_index: Mapping[str, ExtractedSpan],
    ) -> tuple[list[SectionRecord], list[AnalysisCandidate]]:
        matches = list(_SECTION_HEADER_RE.finditer(text))
        sections: list[SectionRecord] = []
        cands: list[AnalysisCandidate] = []
        if not matches:
            # Single uncompiled/other section covering whole text.
            sections.append(
                SectionRecord(
                    schema_version=OFFICE_ACTION_SCHEMA_VERSION,
                    section_id=f"sec:{analysis_id}:0001",
                    kind=SectionKind.OTHER,
                    title="(unsectioned)",
                    source_span_id=covering_span_id,
                    char_start=0,
                    char_end=len(text),
                    text_digest=_text_digest(text),
                    reading_order=0,
                )
            )
            return sections, cands

        # Build section ranges from header starts.
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            title = _normalize_ws(match.group(0))
            kind = _section_kind_from_match(match)
            section_id = f"sec:{analysis_id}:{i+1:04d}"
            body = text[start:end]
            sections.append(
                SectionRecord(
                    schema_version=OFFICE_ACTION_SCHEMA_VERSION,
                    section_id=section_id,
                    kind=kind,
                    title=title[:512],
                    source_span_id=covering_span_id,
                    char_start=start,
                    char_end=end,
                    text_digest=_text_digest(body),
                    reading_order=i,
                )
            )
            cands.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=1000 + i,
                    kind=CandidateKind.SECTION,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=title,
                    confidence=0.9,
                    labels={"section_id": section_id, "section_kind": kind.value},
                )
            )
        return sections, cands

    def _extract_claim_ranges(
        self,
        text: str,
        analysis_id: str,
        covering_span_id: str,
        span_index: Mapping[str, ExtractedSpan],
    ) -> list[AnalysisCandidate]:
        del span_index  # reserved for future page-local span mapping
        out: list[AnalysisCandidate] = []
        seen: set[tuple[int, int]] = set()
        for i, match in enumerate(_CLAIM_RANGE_RE.finditer(text)):
            key = (match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            surface = match.group(0)
            body = match.group("body")
            tokens, ambiguity = parse_claim_range_surface(f"claims {body}")
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=2000 + i,
                    kind=CandidateKind.CLAIM_RANGE,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=0.85 if ambiguity is ClaimRangeAmbiguity.EXACT else 0.55,
                    ambiguity=ambiguity.value,
                    claim_tokens=tokens,
                )
            )
        return out

    def _extract_rejections(
        self, text: str, analysis_id: str, covering_span_id: str
    ) -> list[AnalysisCandidate]:
        out: list[AnalysisCandidate] = []
        for i, match in enumerate(_REJECTION_LEAD_RE.finditer(text)):
            surface = _normalize_ws(match.group(0))
            # Expand window for statute cues.
            window = text[match.start() : min(len(text), match.end() + 240)]
            req_type = _rejection_type_from_text(window)
            claim_match = _CLAIM_RANGE_RE.search(surface) or _CLAIM_RANGE_RE.search(
                window[:120]
            )
            tokens: tuple[str, ...] = ()
            ambiguity: str | None = None
            if claim_match:
                tokens, amb = parse_claim_range_surface(claim_match.group(0))
                ambiguity = amb.value
            else:
                sm = _SINGLE_CLAIM_RE.search(surface)
                if sm:
                    tokens = (str(int(sm.group("n"))),)
                    ambiguity = ClaimRangeAmbiguity.EXACT.value
            # Citations within window (parse only).
            cites = parse_patent_citations(window)
            legal = tuple(
                c.normalized_text or c.raw_text
                for c in cites
                if c.family in (CitationFamily.USC, CitationFamily.CFR, CitationFamily.MPEP)
            )
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=3000 + i,
                    kind=CandidateKind.REJECTION,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=0.8,
                    ambiguity=ambiguity,
                    claim_tokens=tokens,
                    legal_citations=legal[:16],
                    requirement_type=req_type,
                )
            )
        return out

    def _extract_objections(
        self, text: str, analysis_id: str, covering_span_id: str
    ) -> list[AnalysisCandidate]:
        out: list[AnalysisCandidate] = []
        for i, match in enumerate(_OBJECTION_LEAD_RE.finditer(text)):
            surface = _normalize_ws(match.group(0))
            tokens: tuple[str, ...] = ()
            ambiguity: str | None = None
            cm = _CLAIM_RANGE_RE.search(surface)
            if cm:
                tokens, amb = parse_claim_range_surface(cm.group(0))
                ambiguity = amb.value
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=4000 + i,
                    kind=CandidateKind.OBJECTION,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=0.78,
                    ambiguity=ambiguity,
                    claim_tokens=tokens,
                    requirement_type="objection",
                )
            )
        return out

    def _extract_informalities(
        self, text: str, analysis_id: str, covering_span_id: str
    ) -> list[AnalysisCandidate]:
        out: list[AnalysisCandidate] = []
        for i, match in enumerate(_INFORMALITY_RE.finditer(text)):
            surface = _normalize_ws(match.group(0))
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=4500 + i,
                    kind=CandidateKind.INFORMALITY,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=0.75,
                    requirement_type="informality",
                )
            )
        return out

    def _extract_citations(
        self, text: str, analysis_id: str, covering_span_id: str
    ) -> list[AnalysisCandidate]:
        """Parse citation candidates without asserting authority (PATLAW-017 reuse)."""
        out: list[AnalysisCandidate] = []
        parsed: tuple[ParsedCitation, ...] = parse_patent_citations(text)
        for i, cit in enumerate(parsed):
            kind = CandidateKind.CITATION
            if cit.family is CitationFamily.FORM_PARAGRAPH:
                kind = CandidateKind.FORM_PARAGRAPH
            elif cit.family is CitationFamily.FEE:
                kind = CandidateKind.FEE
            elif cit.family is CitationFamily.FORM:
                kind = CandidateKind.FORM
            keys = ()
            if cit.citation_key:
                keys = (cit.citation_key,)
            elif cit.candidate_keys:
                keys = tuple(cit.candidate_keys)
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=5000 + i,
                    kind=kind,
                    origin=CandidateOrigin.CITATION_PARSER,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=cit.raw_text,
                    confidence=cit.confidence,
                    ambiguity=cit.match_kind.value,
                    legal_citations=(cit.normalized_text or cit.raw_text,),
                    citation_keys=keys,
                    citation_match_kind=cit.match_kind.value,
                    labels={
                        "citation_family": cit.family.value,
                        "start_pos": str(cit.start_pos),
                        "end_pos": str(cit.end_pos),
                    },
                )
            )
        return out

    def _extract_prior_art(
        self, text: str, analysis_id: str, covering_span_id: str
    ) -> list[AnalysisCandidate]:
        out: list[AnalysisCandidate] = []
        for i, match in enumerate(_PRIOR_ART_RE.finditer(text)):
            surface = _normalize_ws(match.group(0))
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=5500 + i,
                    kind=CandidateKind.PRIOR_ART,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=0.7,
                    labels={"prior_art_raw": surface[:128]},
                )
            )
        return out

    def _extract_response_instructions(
        self, text: str, analysis_id: str, covering_span_id: str
    ) -> list[AnalysisCandidate]:
        out: list[AnalysisCandidate] = []
        for i, match in enumerate(_RESPONSE_INSTRUCTION_RE.finditer(text)):
            surface = _normalize_ws(match.group(0))
            labels: dict[str, str] = {}
            if match.groupdict().get("period"):
                labels["response_period"] = match.group("period")
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=6000 + i,
                    kind=CandidateKind.RESPONSE_INSTRUCTION,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=0.82,
                    requirement_type="response_instruction",
                    labels=labels,
                )
            )
        return out

    def _extract_pattern_candidates(
        self,
        text: str,
        analysis_id: str,
        covering_span_id: str,
        *,
        pattern: re.Pattern[str],
        kind: CandidateKind,
        confidence: float,
        seq_base: int | None = None,
    ) -> list[AnalysisCandidate]:
        base = seq_base if seq_base is not None else (
            7000 if kind is CandidateKind.ALTERNATIVE else 7500
        )
        out: list[AnalysisCandidate] = []
        for i, match in enumerate(pattern.finditer(text)):
            surface = _normalize_ws(match.group(0))
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=base + i,
                    kind=kind,
                    origin=CandidateOrigin.DETERMINISTIC_RULE,
                    layer=EvidenceLayer.DETERMINISTIC,
                    source_span_id=covering_span_id,
                    surface=surface,
                    confidence=confidence,
                )
            )
        return out

    def _extract_uncompiled(
        self,
        text: str,
        analysis_id: str,
        covering_span_id: str,
        existing: Sequence[AnalysisCandidate],
    ) -> list[AnalysisCandidate]:
        """Mark residual paragraphs not covered by known instruction patterns.

        Unsupported language remains an explicit uncompiled item rather than
        being dropped (plan §11 / acceptance).
        """
        covered: set[str] = set()
        for cand in existing:
            if cand.surface_text:
                covered.add(_normalize_ws(cand.surface_text)[:80])

        out: list[AnalysisCandidate] = []
        # Split into paragraphs; flag long prose without rejection/citation cues
        # that also wasn't captured above.
        paragraphs = re.split(r"\n\s*\n", text)
        seq = 0
        for para in paragraphs:
            surface = _normalize_ws(para)
            if len(surface) < 40:
                continue
            head = surface[:80]
            if any(head.startswith(c[:40]) or c[:40] in surface for c in covered if c):
                continue
            lower = surface.lower()
            # Skip pure headers already sectioned.
            if _SECTION_HEADER_RE.match(para.strip()):
                continue
            # Known compiled cues — skip.
            if any(
                k in lower
                for k in (
                    "are rejected",
                    "is rejected",
                    "are objected",
                    "form paragraph",
                    "35 u.s.c",
                    "37 c.f.r",
                    "statutory period",
                )
            ):
                continue
            # Residual narrative / examiner commentary.
            if re.search(
                r"(?i)\b(?:see\s+also|for\s+example|note\s+that|"
                r"the\s+examiner\s+(?:notes|observes)|it\s+is\s+noted)\b",
                surface,
            ) or len(surface) > 120:
                out.append(
                    self._make_candidate(
                        analysis_id=analysis_id,
                        seq=8000 + seq,
                        kind=CandidateKind.UNCOMPILED_LANGUAGE,
                        origin=CandidateOrigin.DETERMINISTIC_RULE,
                        layer=EvidenceLayer.DETERMINISTIC,
                        source_span_id=covering_span_id,
                        surface=surface[:2000],
                        confidence=0.4,
                        ambiguity="uncompiled",
                        requirement_type="uncompiled",
                        review_state=ReviewState.REQUIRED,
                    )
                )
                seq += 1
                if seq >= 32:
                    break
        return out

    def _ingest_model_candidates(
        self,
        inp: OfficeActionInput,
        analysis_id: str,
        covering_span_id: str,
        span_index: Mapping[str, ExtractedSpan],
    ) -> tuple[list[AnalysisCandidate], list[str]]:
        out: list[AnalysisCandidate] = []
        warnings: list[str] = []
        limit = self.bounds.max_model_candidates
        for i, raw in enumerate(inp.model_candidates[:limit]):
            span_id = raw.source_span_id or covering_span_id
            if span_id not in span_index and span_id != covering_span_id:
                warnings.append(f"model_candidate_unknown_span:{i}")
                span_id = covering_span_id
            kind = _coerce_enum(CandidateKind, raw.kind, "kind")
            out.append(
                self._make_candidate(
                    analysis_id=analysis_id,
                    seq=9000 + i,
                    kind=kind,  # type: ignore[arg-type]
                    origin=CandidateOrigin.MODEL,
                    layer=EvidenceLayer.CANDIDATE,  # never verified pre-validation
                    source_span_id=span_id,
                    surface=raw.surface_text,
                    confidence=raw.confidence,
                    claim_tokens=tuple(raw.claim_tokens or ()),
                    legal_citations=tuple(raw.legal_citations or ()),
                    requirement_type=raw.requirement_type,
                    labels=dict(raw.labels or {}),
                    review_state=ReviewState.REQUIRED,
                )
            )
        if len(inp.model_candidates) > limit:
            warnings.append("model_candidates_truncated")
        return out, warnings

    def _emit_requirements(
        self,
        *,
        analysis_id: str,
        candidates: Sequence[AnalysisCandidate],
        lifecycle: Sequence[ActionLifecycleRecord],
        classification: DisclosureClassification,
    ) -> list[GovernmentRequirement]:
        """Emit GovernmentRequirement only from verified instruction candidates.

        Rescinded lifecycle attaches applicability condition so downstream
        compilers do not treat them as active demands.
        """
        # Only mark requirements inactive when the *primary* action is inactive.
        # A reissued OA may list a rescinded predecessor without itself being inactive.
        statuses = {r.status for r in lifecycle}
        primary_inactive = False
        if ActionLifecycleStatus.REISSUED in statuses or ActionLifecycleStatus.ACTIVE in statuses:
            primary_inactive = False
        elif statuses and statuses <= {
            ActionLifecycleStatus.RESCINDED,
            ActionLifecycleStatus.SUPERSEDED,
            ActionLifecycleStatus.WITHDRAWN,
            ActionLifecycleStatus.UNKNOWN,
        }:
            primary_inactive = any(
                r.status
                in (
                    ActionLifecycleStatus.RESCINDED,
                    ActionLifecycleStatus.SUPERSEDED,
                    ActionLifecycleStatus.WITHDRAWN,
                )
                for r in lifecycle
            )
        active_rescinded = primary_inactive
        requirements: list[GovernmentRequirement] = []
        instruction_kinds = {
            CandidateKind.REJECTION,
            CandidateKind.OBJECTION,
            CandidateKind.INFORMALITY,
            CandidateKind.RESPONSE_INSTRUCTION,
            CandidateKind.FEE,
            CandidateKind.FORM,
        }
        seq = 0
        for cand in candidates:
            if cand.layer is not EvidenceLayer.VERIFIED:
                continue
            if cand.kind not in instruction_kinds:
                continue
            if cand.kind is CandidateKind.UNCOMPILED_LANGUAGE:
                continue
            seq += 1
            applicability: list[str] = []
            exceptions = list(cand.exceptions)
            if active_rescinded:
                applicability.append("action_lifecycle_inactive")
                exceptions.append("rescinded_or_superseded_action")
            # Alternatives become applicability notes, not silent drops.
            for alt in cand.alternatives:
                applicability.append(f"alternative:{_text_digest(alt)[:12]}")

            req_type = cand.requirement_type or cand.kind.value
            requirements.append(
                GovernmentRequirement(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    requirement_id=f"req:{analysis_id}:{seq:04d}",
                    instruction_text_digest=cand.text_digest,
                    source_span_id=cand.source_span_id,
                    requirement_type=req_type,
                    affected_claims=cand.claim_tokens,
                    legal_citations=cand.legal_citations,
                    applicability_conditions=tuple(applicability),
                    proposed_date_rule=(
                        "37_cfr_1.134_non_final_response"
                        if cand.kind is CandidateKind.RESPONSE_INSTRUCTION
                        else None
                    ),
                    exceptions=tuple(exceptions),
                    parser_confidence=cand.confidence,
                    review_state=ReviewState.PENDING
                    if cand.ambiguity
                    and cand.ambiguity
                    not in (
                        ClaimRangeAmbiguity.EXACT.value,
                        CitationMatchKind.EXACT.value,
                        None,
                    )
                    else (
                        ReviewState.REQUIRED
                        if active_rescinded
                        else ReviewState.PENDING
                    ),
                    classification=classification,
                )
            )
        return requirements

    def _disposition(
        self,
        *,
        action_kind: OfficeActionKind,
        lifecycle: Sequence[ActionLifecycleRecord],
        candidates: Sequence[AnalysisCandidate],
        classification: DisclosureClassification,
        reason_codes: Sequence[str],
    ) -> tuple[AnalysisDisposition, ReviewState]:
        if requires_quarantine(classification):
            return AnalysisDisposition.QUARANTINE, ReviewState.REQUIRED
        if action_kind is OfficeActionKind.MALFORMED:
            return AnalysisDisposition.MALFORMED, ReviewState.REQUIRED
        if OfficeActionReasonCode.MALFORMED_ACTION.value in reason_codes:
            return AnalysisDisposition.MALFORMED, ReviewState.REQUIRED
        if any(
            r.status is ActionLifecycleStatus.RESCINDED for r in lifecycle
        ) or action_kind is OfficeActionKind.RESCINDED_ACTION:
            return AnalysisDisposition.REVIEW, ReviewState.REQUIRED
        if any(
            c.kind is CandidateKind.UNCOMPILED_LANGUAGE for c in candidates
        ) or any(
            c.layer is not EvidenceLayer.VERIFIED and c.origin is CandidateOrigin.MODEL
            for c in candidates
        ):
            return AnalysisDisposition.REVIEW, ReviewState.REQUIRED
        if any(
            c.ambiguity
            in (
                ClaimRangeAmbiguity.UNRESOLVED.value,
                ClaimRangeAmbiguity.OPEN_ENDED.value,
                ClaimRangeAmbiguity.CONFLICTING.value,
                CitationMatchKind.AMBIGUOUS.value,
                CitationMatchKind.UNRESOLVED.value,
            )
            for c in candidates
            if c.ambiguity
        ):
            return AnalysisDisposition.REVIEW, ReviewState.PENDING
        if not any(c.kind is CandidateKind.REJECTION for c in candidates) and (
            action_kind
            in (
                OfficeActionKind.NON_FINAL_REJECTION,
                OfficeActionKind.FINAL_REJECTION,
            )
        ):
            return AnalysisDisposition.REVIEW, ReviewState.PENDING
        return AnalysisDisposition.ANALYZED, ReviewState.NOT_REQUIRED

    def _terminal(
        self,
        *,
        analysis_id: str,
        inp: OfficeActionInput,
        disposition: AnalysisDisposition,
        review_state: ReviewState,
        reason_codes: Sequence[str],
        warnings: Sequence[str],
        action_kind: OfficeActionKind,
    ) -> OfficeActionResult:
        digest = _text_digest(inp.text or "")
        return OfficeActionResult(
            schema_version=OFFICE_ACTION_SCHEMA_VERSION,
            analysis_id=analysis_id,
            artifact_id=inp.artifact_id,
            action_id=inp.action_id or f"action:{analysis_id}",
            action_kind=action_kind,
            disposition=disposition,
            review_state=review_state,
            classification=inp.classification,
            reason_codes=tuple(reason_codes),
            warnings=tuple(warnings),
            sections=(),
            candidates=(),
            validation_receipts=(),
            requirements=(),
            lifecycle=tuple(inp.lifecycle),
            spans=tuple(inp.spans),
            mailing_date=inp.mailing_date,
            application_number=None,
            labels=dict(inp.labels),
            ruleset_versions={"office_action": OFFICE_ACTION_RULESET_VERSION},
            model_versions={},
            text_digest=digest if _SHA256_RE.match(digest) else sha256_hex(""),
            retained=disposition is not AnalysisDisposition.REJECTED,
        )


def extract_office_action(
    value: OfficeActionInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> OfficeActionResult:
    """Module-level convenience wrapper around :class:`OfficeActionProcessor`."""
    return OfficeActionProcessor().analyze(value, **kwargs)


__all__ = [
    "OFFICE_ACTION_INTERFACE",
    "OFFICE_ACTION_RULESET_VERSION",
    "OFFICE_ACTION_SCHEMA_VERSION",
    "ActionLifecycleRecord",
    "ActionLifecycleStatus",
    "AnalysisBounds",
    "AnalysisCandidate",
    "AnalysisDisposition",
    "CandidateKind",
    "CandidateOrigin",
    "ClaimRangeAmbiguity",
    "EvidenceLayer",
    "ModelCandidateInput",
    "OfficeActionAnalysisError",
    "OfficeActionInput",
    "OfficeActionKind",
    "OfficeActionProcessor",
    "OfficeActionReasonCode",
    "OfficeActionResult",
    "SectionKind",
    "SectionRecord",
    "ValidationReceipt",
    "deterministically_validate_candidate",
    "extract_office_action",
    "parse_claim_range_surface",
    "sha256_hex",
]
