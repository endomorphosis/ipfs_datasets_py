"""Layout-aware office-action semantics v2 (PATLAW-129).

Expands governed, source-anchored parsing across USPTO communication families
while distinguishing **candidate** extraction from **admitted** facts.

Design invariants
-----------------
* Every semantic field points at exact supporting :class:`ExtractedSpan`
  provenance (one or more page-anchored spans for cross-page continuations).
* Named communication families are first-class; unknown/missing/ambiguous
  content stays ``unknown`` / ``review_required`` rather than guessed.
* Deterministic rules validate identifiers, dates, and citations and flag
  contradictions (including document-code drift).
* Model-origin fields remain candidates until deterministic admission.
* Document body text is never written to logs or exception messages.

Compatibility
-------------
v1 :mod:`office_action_processor` contracts remain available for claim-range
and citation parsing reuse. This module owns the v2 family/admission surface.
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

from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    ClaimRangeAmbiguity,
    parse_claim_range_surface,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.identifiers import (
    IdentifierStatus,
    normalize_application_number,
)
from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
    CitationMatchKind,
    parse_patent_citations,
)

SEMANTICS_V2_SCHEMA_VERSION: Final = "uspto.office-action-semantics.v2"
SEMANTICS_V2_INTERFACE: Final = "OfficeActionSemanticsV2@1"
SEMANTICS_V2_RULESET_VERSION: Final = "office-action-semantics-v2-rules@1"

DEFAULT_MAX_CHARS: Final = 2_000_000
DEFAULT_MAX_FIELDS: Final = 4096
DEFAULT_MAX_PAGES: Final = 512
DEFAULT_MAX_MODEL_FIELDS: Final = 512
DEFAULT_MAX_SPANS: Final = 8192

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CommunicationFamily(str, Enum):
    """Named USPTO office-action / notice communication families (v2)."""

    MISSING_PARTS = "missing_parts"
    OMITTED_ITEMS = "omitted_items"
    NO_FILING_DATE = "no_filing_date"
    RESTRICTION_ELECTION = "restriction_election"
    EX_PARTE_QUAYLE = "ex_parte_quayle"
    ADVISORY_ACTION = "advisory_action"
    SEQUENCE_COMPLIANCE = "sequence_compliance"
    ALLOWANCE_ISSUE_FEE = "allowance_issue_fee"
    APPEAL_PRE_APPEAL = "appeal_pre_appeal"
    PETITION = "petition"
    RESCINDED_REISSUED = "rescinded_reissued"
    NON_FINAL = "non_final"
    FINAL = "final"
    UNKNOWN = "unknown"


# All named gold-fixture families (excludes unknown).
NAMED_COMMUNICATION_FAMILIES: Final[tuple[CommunicationFamily, ...]] = (
    CommunicationFamily.MISSING_PARTS,
    CommunicationFamily.OMITTED_ITEMS,
    CommunicationFamily.NO_FILING_DATE,
    CommunicationFamily.RESTRICTION_ELECTION,
    CommunicationFamily.EX_PARTE_QUAYLE,
    CommunicationFamily.ADVISORY_ACTION,
    CommunicationFamily.SEQUENCE_COMPLIANCE,
    CommunicationFamily.ALLOWANCE_ISSUE_FEE,
    CommunicationFamily.APPEAL_PRE_APPEAL,
    CommunicationFamily.PETITION,
    CommunicationFamily.RESCINDED_REISSUED,
    CommunicationFamily.NON_FINAL,
    CommunicationFamily.FINAL,
)


class SemanticFieldKind(str, Enum):
    HEADER = "header"
    MAILING_DATE = "mailing_date"
    NOTIFICATION_DATE = "notification_date"
    RESPONSE_PERIOD = "response_period"
    EXAMINER_CONTACT = "examiner_contact"
    APPLICATION_NUMBER = "application_number"
    CLAIM_GROUPING = "claim_grouping"
    OBJECTION = "objection"
    REJECTION = "rejection"
    ALLOWANCE = "allowance"
    REQUIREMENT = "requirement"
    STATUTORY_CITATION = "statutory_citation"
    REGULATORY_CITATION = "regulatory_citation"
    FORM = "form"
    ATTACHMENT = "attachment"
    SIGNATURE = "signature"
    TABLE = "table"
    CROSS_PAGE_CONTINUATION = "cross_page_continuation"
    DOCUMENT_CODE = "document_code"
    LIFECYCLE = "lifecycle"
    OTHER = "other"


class AdmissionState(str, Enum):
    """Admission layer for semantic fields.

    * ``candidate`` — extracted or model-proposed; not admitted.
    * ``admitted`` — passed deterministic validation with span provenance.
    * ``rejected`` — failed deterministic checks.
    * ``review_required`` — missing, unknown-family, ambiguous, or contradictory.
    """

    CANDIDATE = "candidate"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    REVIEW_REQUIRED = "review_required"


class FieldOrigin(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    CITATION_PARSER = "citation_parser"
    IDENTIFIER_NORMALIZER = "identifier_normalizer"
    MODEL = "model"
    METADATA = "metadata"
    LAYOUT = "layout"
    OTHER = "other"


class SemanticsDisposition(str, Enum):
    ANALYZED = "analyzed"
    REVIEW = "review"
    MALFORMED = "malformed"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class ContradictionKind(str, Enum):
    DOCUMENT_CODE_DRIFT = "document_code_drift"
    DATE_CONFLICT = "date_conflict"
    IDENTIFIER_CONFLICT = "identifier_conflict"
    CITATION_CONFLICT = "citation_conflict"
    FAMILY_AMBIGUITY = "family_ambiguity"
    SPAN_MISMATCH = "span_mismatch"
    OTHER = "other"


class SemanticsReasonCode(str, Enum):
    FAMILY_DETECTED = "family_detected"
    FAMILY_UNKNOWN = "family_unknown"
    FAMILY_AMBIGUOUS = "family_ambiguous"
    FIELDS_EXTRACTED = "fields_extracted"
    SPANS_BOUND = "spans_bound"
    CROSS_PAGE_CONTINUATION = "cross_page_continuation"
    DOCUMENT_CODE_DRIFT = "document_code_drift"
    IDENTIFIER_VALIDATED = "identifier_validated"
    IDENTIFIER_INVALID = "identifier_invalid"
    DATE_VALIDATED = "date_validated"
    DATE_INVALID = "date_invalid"
    CITATION_VALIDATED = "citation_validated"
    CITATION_AMBIGUOUS = "citation_ambiguous"
    CONTRADICTION_FLAGGED = "contradiction_flagged"
    MODEL_CANDIDATE_HELD = "model_candidate_held"
    MODEL_CANDIDATE_ADMITTED = "model_candidate_admitted"
    MODEL_CANDIDATE_BLOCKED = "model_candidate_blocked"
    ADMISSION_PASSED = "admission_passed"
    ADMISSION_FAILED = "admission_failed"
    NOISY_SCAN = "noisy_scan"
    MISSING_CONTENT = "missing_content"
    EMPTY_TEXT = "empty_text"
    OVERSIZE_TEXT = "oversize_text"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    REVIEW_REQUIRED = "review_required"
    FIELD_LIMIT = "field_limit"
    COVERING_SPAN_MINTED = "covering_span_minted"


# ---------------------------------------------------------------------------
# Regex libraries
# ---------------------------------------------------------------------------

_APPLICATION_NO_RE = re.compile(
    r"(?i)\bApplication\s*(?:No\.?|Number)\s*[:\-]?\s*"
    r"(?P<app>\d{2}/\d{3},\d{3}|\d{2}/\d{6}|\d{8})"
)

_MAILING_DATE_RE = re.compile(
    r"(?i)\b(?:Mailing\s+Date|Date\s+Mailed)\s*[:\-]?\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
)

_NOTIFICATION_DATE_RE = re.compile(
    r"(?i)\b(?:Notification\s+Date|Notice\s+Date)\s*[:\-]?\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
)

_RESPONSE_PERIOD_RE = re.compile(
    r"(?is)"
    r"(?:A\s+)?(?:shortened\s+)?statutory\s+period\s+for\s+(?:reply|response)\s+"
    r"(?:is|to)\s+(?:set\s+to\s+)?expire\s+(?:in\s+)?(?P<period>\d+\s+months?)"
    r"(?:\s+from\s+the\s+(?:mailing|notification)\s+date)?"
    r"|Response\s+period\s*[:\-]?\s*(?P<period2>\d+\s+months?)"
    r"|Applicant\s+must\s+respond\s+within\s+(?P<period3>\d+\s+months?)"
)

_EXAMINER_CONTACT_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    r"Examiner\s*[:\-]?\s*(?P<name>[A-Za-z][A-Za-z .'\-]{1,80})"
    r"|Primary\s+Examiner\s*[:\-]?\s*(?P<name2>[A-Za-z][A-Za-z .'\-]{1,80})"
    r"|Art\s+Unit\s*[:\-]?\s*(?P<art>\d{4})"
    r"|Telephone\s*(?:No\.?|Number)?\s*[:\-]?\s*(?P<phone>[\d\-(). ]{7,20})"
    r")"
)

_CLAIM_GROUP_RE = re.compile(
    r"(?i)\b(?P<label>claims?|claim\s*nos?\.?)\s+"
    r"(?P<body>"
    r"(?:about\s+|approximately\s+|roughly\s+)?"
    r"(?:"
    r"\d+(?:\s*[-–—to]+\s*\d+)?"
    r"(?:\s*,\s*\d+(?:\s*[-–—to]+\s*\d+)?)*"
    r"(?:\s*,?\s*(?:and|&)\s*\d+(?:\s*[-–—to]+\s*\d+)?)?"
    r"|all|the\s+remaining|pending"
    r")"
    r")"
)

_REJECTION_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    r"Claims?\s+[\d,\s\-–—and&to]+?\s+are?\s+rejected\b|"
    r"Claim\s+\d+\s+is\s+rejected\b|"
    r"Claims?\s+[\d,\s\-–—and&to]+?\s+(?:stand|stands)\s+rejected\b"
    r").{0,400}"
)

_OBJECTION_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    r"Claims?\s+[\d,\s\-–—and&to]+?\s+are?\s+objected\b|"
    r"Claim\s+\d+\s+is\s+objected\b|"
    r"The\s+(?:drawings?|specification|abstract|title)\s+(?:is|are)\s+objected\b"
    r").{0,300}"
)

_ALLOWANCE_RE = re.compile(
    r"(?i)\b(?:"
    r"claims?\s+[\d,\s\-–—and&to]+\s+(?:are|is)\s+allowed\b|"
    r"allowable\s+subject\s+matter\b|"
    r"notice\s+of\s+allowance\b|"
    r"application\s+is\s+allowed\b"
    r").{0,200}"
)

_REQUIREMENT_RE = re.compile(
    r"(?i)\b(?:"
    r"applicant\s+is\s+(?:required|invited|urged)\s+to\b|"
    r"a\s+complete\s+response\s+is\s+required\b|"
    r"election\s+is\s+required\b|"
    r"must\s+be\s+(?:submitted|filed|provided)\b|"
    r"missing\s+parts?\b|"
    r"omitted\s+items?\b"
    r").{0,220}"
)

_STATUTORY_RE = re.compile(
    r"(?i)\b35\s*U\.?\s*S\.?\s*C\.?\s*§?\s*\d+[A-Za-z()]*"
)

_REGULATORY_RE = re.compile(
    r"(?i)\b37\s*C\.?\s*F\.?\s*R\.?\s*§?\s*[\d.]+[A-Za-z()]*"
    r"|\bMPEP\s*§?\s*[\d.]+"
)

_FORM_RE = re.compile(
    r"(?i)\b(?:"
    r"form\s+paragraph\s+[\d.]+|"
    r"Form\s+PTO/?[A-Z0-9/]+|"
    r"PTO/?SB/?\d+|"
    r"fee\s+code\s+\d+"
    r")\b"
)

_ATTACHMENT_RE = re.compile(
    r"(?i)\b(?:"
    r"attachment(?:s)?\s*[:\-]|attached\s+(?:is|are|hereto)|"
    r"see\s+attached\s+(?:form|sheet|listing|PTO)|"
    r"enclosure(?:s)?\s*[:\-]"
    r").{0,120}"
)

_SIGNATURE_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    r"/s/\s*[A-Za-z].{0,60}|"
    r"Respectfully\s+submitted,|"
    r"Signature\s*[:\-]\s*.{0,60}|"
    r"Electronically\s+signed\b"
    r")"
)

_TABLE_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    r"(?:Claim|Group|Invention)\s*(?:No\.?)?\s*\|\s*.+|"
    r"\|?\s*Claim\s*\|\s*Status\s*\||"
    r"Group\s+[IVXLC]+\s*[-–—:]\s*claims?\s+\d"
    r")"
)

_HEADER_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    r"UNITED STATES PATENT AND TRADEMARK OFFICE|"
    r"Office Action Summary|"
    r"Notice of (?:Allowance|Missing Parts|Non-Compliant Amendment)|"
    r"Advisory Action|"
    r"Ex parte Quayle|"
    r"Requirement for Restriction|"
    r"Election of Species|"
    r"Sequence Listing|"
    r"Pre-Appeal Brief|"
    r"Decision on Petition|"
    r"Detailed Action"
    r")[ \t]*$"
)

_CONTINUATION_MARK_RE = re.compile(
    r"(?i)\b(?:"
    r"continued\s+on\s+(?:the\s+)?next\s+page|"
    r"\(continued\)|"
    r"see\s+continuation|"
    r"cont(?:inued)?\.\s*$"
    r")"
)

# Family detection cues (ordered; first decisive match wins when exclusive).
_FAMILY_CUE_RULES: Final[
    tuple[tuple[CommunicationFamily, tuple[str, ...], float], ...]
] = (
    (
        CommunicationFamily.RESCINDED_REISSUED,
        (
            "reissued office action",
            "this action supersedes",
            "previous office action is hereby withdrawn",
            "office action is hereby rescinded",
            "this office action is rescinded",
        ),
        0.95,
    ),
    (
        CommunicationFamily.EX_PARTE_QUAYLE,
        ("ex parte quayle", "this action is an ex parte quayle"),
        0.95,
    ),
    (
        CommunicationFamily.ADVISORY_ACTION,
        ("advisory action", "this is an advisory action", "entry of the amendment"),
        0.9,
    ),
    (
        CommunicationFamily.ALLOWANCE_ISSUE_FEE,
        (
            "notice of allowance",
            "issue fee",
            "application is allowed",
            "pay the issue fee",
        ),
        0.95,
    ),
    (
        CommunicationFamily.RESTRICTION_ELECTION,
        (
            "requirement for restriction",
            "restriction requirement",
            "election of species",
            "election is required",
            "traverse the restriction",
        ),
        0.95,
    ),
    (
        CommunicationFamily.MISSING_PARTS,
        (
            "notice of missing parts",
            "missing parts",
            "application papers are incomplete",
        ),
        0.9,
    ),
    (
        CommunicationFamily.OMITTED_ITEMS,
        ("notice of omitted items", "omitted items", "items were omitted"),
        0.9,
    ),
    (
        CommunicationFamily.NO_FILING_DATE,
        (
            "notice of no filing date",
            "no filing date",
            "filing date has not been accorded",
            "not accorded a filing date",
        ),
        0.95,
    ),
    (
        CommunicationFamily.SEQUENCE_COMPLIANCE,
        (
            "sequence listing",
            "st.26",
            "sequence compliance",
            "crf sequence",
            "sequence listing is non-compliant",
        ),
        0.9,
    ),
    (
        CommunicationFamily.APPEAL_PRE_APPEAL,
        (
            "pre-appeal brief",
            "preappeal",
            "notice of appeal",
            "appeal conference",
            "board of appeals",
            "ex parte appeal",
        ),
        0.9,
    ),
    (
        CommunicationFamily.PETITION,
        (
            "decision on petition",
            "petition under",
            "petition is granted",
            "petition is dismissed",
            "petition is denied",
        ),
        0.9,
    ),
    (
        CommunicationFamily.FINAL,
        (
            "this action is made final",
            "this action is final",
            "final office action",
            "final rejection",
        ),
        0.9,
    ),
    (
        CommunicationFamily.NON_FINAL,
        (
            "non-final office action",
            "nonfinal office action",
            "this is a non-final",
            "this action is non-final",
            "non-final rejection",
        ),
        0.9,
    ),
)

_NOISY_SCAN_RE = re.compile(
    r"(?:[|]{3,}|@{3,}|\?{4,}|[^\x09\x0a\x0d\x20-\x7e]{8,}|"
    r"(?:illegible|unreadable|ocr\s+failure|garbled))"
    r"|(?:[A-Za-z]{1,2}\s){12,}"
)

_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_US_DATE_RE = re.compile(r"\A(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\Z")
_MONTH_DATE_RE = re.compile(
    r"\A(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\Z",
    re.I,
)
_MONTH_MAP: Final[Mapping[str, int]] = MappingProxyType(
    {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
)


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class OfficeActionSemanticsV2Error(ValueError):
    """Bounded semantics failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "semantics_v2_error") -> None:
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


def _tuple_of_int(value: Any, field: str, *, max_items: int = 256) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of ints")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[int] = []
    for i, item in enumerate(value):
        out.append(_nonneg_int(item, f"{field}[{i}]"))
    return tuple(out)


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


def parse_calendar_date(surface: str) -> tuple[str | None, list[str]]:
    """Parse a date surface to ISO ``YYYY-MM-DD`` when deterministic.

    Returns ``(iso_or_none, issue_codes)``. Ambiguous or invalid surfaces do
    not invent a date.
    """
    text = _normalize_ws(surface or "")
    if not text:
        return None, ["empty_date"]

    if _ISO_DATE_RE.match(text):
        try:
            date.fromisoformat(text)
            return text, []
        except ValueError:
            return None, ["invalid_iso_date"]

    m = _US_DATE_RE.match(text)
    if m:
        month, day, year_s = int(m.group(1)), int(m.group(2)), m.group(3)
        year = int(year_s)
        if year < 100:
            year += 2000 if year < 70 else 1900
        try:
            return date(year, month, day).isoformat(), []
        except ValueError:
            return None, ["invalid_us_date"]

    m2 = _MONTH_DATE_RE.match(text)
    if m2:
        mon = _MONTH_MAP.get(m2.group("mon")[:3].lower())
        if mon is None:
            return None, ["unknown_month"]
        try:
            return date(
                int(m2.group("year")), mon, int(m2.group("day"))
            ).isoformat(), []
        except ValueError:
            return None, ["invalid_month_date"]

    return None, ["unrecognized_date_format"]


def detect_noisy_scan(text: str, *, ocr_confidence: float | None = None) -> bool:
    """Heuristic noisy-scan detector for OCR garbage and low confidence."""
    if ocr_confidence is not None and ocr_confidence < 0.55:
        return True
    if not text or not text.strip():
        return False
    if _NOISY_SCAN_RE.search(text):
        return True
    # High ratio of non-alnum characters suggests OCR garbage.
    sample = text[:4000]
    if len(sample) >= 40:
        alnum = sum(1 for ch in sample if ch.isalnum() or ch.isspace())
        if alnum / max(len(sample), 1) < 0.55:
            return True
    return False


# ---------------------------------------------------------------------------
# Value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticsBounds:
    max_chars: int = DEFAULT_MAX_CHARS
    max_fields: int = DEFAULT_MAX_FIELDS
    max_pages: int = DEFAULT_MAX_PAGES
    max_model_fields: int = DEFAULT_MAX_MODEL_FIELDS
    max_spans: int = DEFAULT_MAX_SPANS

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_chars", _nonneg_int(self.max_chars, "max_chars"))
        object.__setattr__(self, "max_fields", _nonneg_int(self.max_fields, "max_fields"))
        object.__setattr__(self, "max_pages", _nonneg_int(self.max_pages, "max_pages"))
        object.__setattr__(
            self,
            "max_model_fields",
            _nonneg_int(self.max_model_fields, "max_model_fields"),
        )
        object.__setattr__(self, "max_spans", _nonneg_int(self.max_spans, "max_spans"))


@dataclass(frozen=True, slots=True)
class LayoutPage:
    """One layout/OCR page product from a checkpointed document job."""

    page_index: int
    text: str
    spans: tuple[ExtractedSpan, ...] = ()
    span_texts: Mapping[str, str] = MappingProxyType({})
    origin: ExtractionOrigin | str = ExtractionOrigin.UNKNOWN
    ocr_confidence: float | None = None
    image_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "page_index", _nonneg_int(self.page_index, "page_index")
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
                max_items=DEFAULT_MAX_SPANS,
                allow_empty_values=True,
                max_value_len=DEFAULT_MAX_CHARS,
            ),
        )
        object.__setattr__(
            self, "origin", _coerce_enum(ExtractionOrigin, self.origin, "origin")
        )
        object.__setattr__(
            self,
            "ocr_confidence",
            _optional_float_01(self.ocr_confidence, "ocr_confidence"),
        )
        if self.image_digest is not None:
            digest = _require_str(self.image_digest, "image_digest", max_len=64).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("image_digest must be sha256 hex")
            object.__setattr__(self, "image_digest", digest)


@dataclass(frozen=True, slots=True)
class ModelFieldInput:
    """External model field held out of the admitted layer by default."""

    kind: SemanticFieldKind | str
    surface_text: str
    source_span_ids: tuple[str, ...] = ()
    char_start: int | None = None
    char_end: int | None = None
    page_indices: tuple[int, ...] = ()
    confidence: float | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    normalized_value: str | None = None


@dataclass(frozen=True, slots=True)
class ContradictionRecord:
    """A deterministic contradiction between fields or metadata."""

    schema_version: str
    contradiction_id: str
    kind: ContradictionKind
    message_code: str
    field_ids: tuple[str, ...]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self,
            "contradiction_id",
            _identifier(self.contradiction_id, "contradiction_id"),
        )
        object.__setattr__(
            self, "kind", _coerce_enum(ContradictionKind, self.kind, "kind")
        )
        object.__setattr__(
            self,
            "message_code",
            _require_str(self.message_code, "message_code", max_len=128),
        )
        object.__setattr__(
            self, "field_ids", _tuple_of_str(self.field_ids, "field_ids", max_items=32)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "field_ids": list(self.field_ids),
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "message_code": self.message_code,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContradictionRecord":
        if not isinstance(value, Mapping):
            raise TypeError("ContradictionRecord must be a mapping")
        return cls(
            schema_version=value.get("schema_version", SEMANTICS_V2_SCHEMA_VERSION),
            contradiction_id=value.get("contradiction_id", ""),
            kind=value.get("kind", ContradictionKind.OTHER.value),
            message_code=value.get("message_code", "contradiction"),
            field_ids=tuple(value.get("field_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    """Receipt proving deterministic admission of a semantic field."""

    schema_version: str
    receipt_id: str
    field_id: str
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]
    ruleset_version: str
    admitted_state: AdmissionState

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "field_id", _identifier(self.field_id, "field_id"))
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be bool")
        object.__setattr__(
            self, "checks", _tuple_of_str(self.checks, "checks", max_items=64)
        )
        object.__setattr__(
            self, "failures", _tuple_of_str(self.failures, "failures", max_items=64)
        )
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        object.__setattr__(
            self,
            "admitted_state",
            _coerce_enum(AdmissionState, self.admitted_state, "admitted_state"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_state": self.admitted_state.value,
            "checks": list(self.checks),
            "failures": list(self.failures),
            "field_id": self.field_id,
            "passed": self.passed,
            "receipt_id": self.receipt_id,
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdmissionReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("AdmissionReceipt must be a mapping")
        return cls(
            schema_version=value.get("schema_version", SEMANTICS_V2_SCHEMA_VERSION),
            receipt_id=value.get("receipt_id", ""),
            field_id=value.get("field_id", ""),
            passed=bool(value.get("passed", False)),
            checks=tuple(value.get("checks") or ()),
            failures=tuple(value.get("failures") or ()),
            ruleset_version=value.get(
                "ruleset_version", SEMANTICS_V2_RULESET_VERSION
            ),
            admitted_state=value.get(
                "admitted_state", AdmissionState.CANDIDATE.value
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticField:
    """A confidence-scored, span-bound semantic field (candidate until admitted)."""

    schema_version: str
    field_id: str
    kind: SemanticFieldKind
    admission: AdmissionState
    origin: FieldOrigin
    source_span_ids: tuple[str, ...]
    page_indices: tuple[int, ...]
    text_digest: str
    surface_text: str
    confidence: float | None
    normalized_value: str | None
    claim_tokens: tuple[str, ...]
    claim_ambiguity: str | None
    citation_keys: tuple[str, ...]
    citation_match_kind: str | None
    labels: Mapping[str, str]
    admission_receipt_id: str | None
    review_state: ReviewState
    char_start: int | None = None
    char_end: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "field_id", _identifier(self.field_id, "field_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(SemanticFieldKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "admission", _coerce_enum(AdmissionState, self.admission, "admission")
        )
        object.__setattr__(
            self, "origin", _coerce_enum(FieldOrigin, self.origin, "origin")
        )
        spans = _tuple_of_str(self.source_span_ids, "source_span_ids", max_items=64)
        if not spans:
            raise ValueError("source_span_ids must be non-empty")
        object.__setattr__(self, "source_span_ids", spans)
        object.__setattr__(
            self,
            "page_indices",
            _tuple_of_int(self.page_indices, "page_indices", max_items=64),
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
            self,
            "normalized_value",
            _optional_str(self.normalized_value, "normalized_value", max_len=512),
        )
        object.__setattr__(
            self,
            "claim_tokens",
            _tuple_of_str(self.claim_tokens, "claim_tokens", max_items=256),
        )
        object.__setattr__(
            self,
            "claim_ambiguity",
            _optional_str(self.claim_ambiguity, "claim_ambiguity", max_len=64),
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
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "admission_receipt_id",
            _optional_identifier(self.admission_receipt_id, "admission_receipt_id"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
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
        # Fail closed: model origin cannot already be admitted without receipt.
        if (
            self.origin is FieldOrigin.MODEL
            and self.admission is AdmissionState.ADMITTED
            and self.admission_receipt_id is None
        ):
            raise ValueError(
                "model fields cannot enter admitted state without "
                "deterministic admission receipt"
            )

    @property
    def is_admitted(self) -> bool:
        return self.admission is AdmissionState.ADMITTED

    @property
    def is_model_origin(self) -> bool:
        return self.origin is FieldOrigin.MODEL

    @property
    def is_cross_page(self) -> bool:
        return len(set(self.page_indices)) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value,
            "admission_receipt_id": self.admission_receipt_id,
            "char_end": self.char_end,
            "char_start": self.char_start,
            "citation_keys": list(self.citation_keys),
            "citation_match_kind": self.citation_match_kind,
            "claim_ambiguity": self.claim_ambiguity,
            "claim_tokens": list(self.claim_tokens),
            "confidence": self.confidence,
            "field_id": self.field_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "normalized_value": self.normalized_value,
            "origin": self.origin.value,
            "page_indices": list(self.page_indices),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_span_ids": list(self.source_span_ids),
            "surface_text": self.surface_text,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticField":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticField must be a mapping")
        return cls(
            schema_version=value.get("schema_version", SEMANTICS_V2_SCHEMA_VERSION),
            field_id=value.get("field_id", ""),
            kind=value.get("kind", SemanticFieldKind.OTHER.value),
            admission=value.get("admission", AdmissionState.CANDIDATE.value),
            origin=value.get("origin", FieldOrigin.OTHER.value),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
            page_indices=tuple(value.get("page_indices") or ()),
            text_digest=value.get("text_digest", ""),
            surface_text=str(value.get("surface_text") or ""),
            confidence=value.get("confidence"),
            normalized_value=value.get("normalized_value"),
            claim_tokens=tuple(value.get("claim_tokens") or ()),
            claim_ambiguity=value.get("claim_ambiguity"),
            citation_keys=tuple(value.get("citation_keys") or ()),
            citation_match_kind=value.get("citation_match_kind"),
            labels=value.get("labels") or {},
            admission_receipt_id=value.get("admission_receipt_id"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            char_start=value.get("char_start"),
            char_end=value.get("char_end"),
        )


@dataclass(frozen=True, slots=True)
class OfficeActionSemanticsInput:
    """Layout-aware input for v2 office-action semantics.

    Prefer providing pages with validated spans from the checkpointed document
    job (PATLAW-125). Full-text-only inputs mint covering spans so every field
    still has provenance.
    """

    artifact_id: str
    pages: tuple[LayoutPage, ...] = ()
    # Convenience: single concatenated text when pages are not yet structured.
    text: str = ""
    spans: tuple[ExtractedSpan, ...] = ()
    span_texts: Mapping[str, str] = MappingProxyType({})
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    document_code: str | None = None
    mailing_date: str | None = None
    action_id: str | None = None
    model_fields: tuple[ModelFieldInput, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.pages, tuple):
            object.__setattr__(self, "pages", tuple(self.pages or ()))
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
                max_items=DEFAULT_MAX_SPANS,
                allow_empty_values=True,
                max_value_len=DEFAULT_MAX_CHARS,
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "document_code",
            _optional_str(self.document_code, "document_code", max_len=64),
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        if not isinstance(self.model_fields, tuple):
            object.__setattr__(self, "model_fields", tuple(self.model_fields or ()))
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )


@dataclass(frozen=True, slots=True)
class OfficeActionSemanticsResult:
    """Full layout-aware semantics outcome with admission layering."""

    schema_version: str
    analysis_id: str
    artifact_id: str
    action_id: str
    family: CommunicationFamily
    family_confidence: float | None
    disposition: SemanticsDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    fields: tuple[SemanticField, ...]
    contradictions: tuple[ContradictionRecord, ...]
    admission_receipts: tuple[AdmissionReceipt, ...]
    spans: tuple[ExtractedSpan, ...]
    page_count: int
    document_code: str | None
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
        if self.schema_version != SEMANTICS_V2_SCHEMA_VERSION:
            raise ValueError(
                "OfficeActionSemanticsResult.schema_version must be "
                f"{SEMANTICS_V2_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(
            self, "family", _coerce_enum(CommunicationFamily, self.family, "family")
        )
        object.__setattr__(
            self,
            "family_confidence",
            _optional_float_01(self.family_confidence, "family_confidence"),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(SemanticsDisposition, self.disposition, "disposition"),
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
        if not isinstance(self.fields, tuple):
            object.__setattr__(self, "fields", tuple(self.fields))
        if not isinstance(self.contradictions, tuple):
            object.__setattr__(self, "contradictions", tuple(self.contradictions))
        if not isinstance(self.admission_receipts, tuple):
            object.__setattr__(
                self, "admission_receipts", tuple(self.admission_receipts)
            )
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        object.__setattr__(
            self, "page_count", _nonneg_int(self.page_count, "page_count")
        )
        object.__setattr__(
            self,
            "document_code",
            _optional_str(self.document_code, "document_code", max_len=64),
        )
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
        for field in self.fields:
            if (
                field.origin is FieldOrigin.MODEL
                and field.admission is AdmissionState.ADMITTED
                and not field.admission_receipt_id
            ):
                raise ValueError(
                    "model fields never enter admitted state without "
                    "deterministic admission"
                )

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            SemanticsDisposition.REVIEW,
            SemanticsDisposition.MALFORMED,
            SemanticsDisposition.QUARANTINE,
            SemanticsDisposition.REJECTED,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def fields_by_kind(
        self, kind: SemanticFieldKind | str
    ) -> tuple[SemanticField, ...]:
        target = _coerce_enum(SemanticFieldKind, kind, "kind")
        return tuple(f for f in self.fields if f.kind is target)

    def fields_by_admission(
        self, state: AdmissionState | str
    ) -> tuple[SemanticField, ...]:
        target = _coerce_enum(AdmissionState, state, "state")
        return tuple(f for f in self.fields if f.admission is target)

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def field_by_id(self, field_id: str) -> SemanticField | None:
        for field in self.fields:
            if field.field_id == field_id:
                return field
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "admission_receipts": [r.to_dict() for r in self.admission_receipts],
            "analysis_id": self.analysis_id,
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "contradictions": [c.to_dict() for c in self.contradictions],
            "disposition": self.disposition.value,
            "document_code": self.document_code,
            "family": self.family.value,
            "family_confidence": self.family_confidence,
            "fields": [f.to_dict() for f in self.fields],
            "labels": dict(self.labels),
            "mailing_date": self.mailing_date,
            "model_versions": dict(self.model_versions),
            "page_count": self.page_count,
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "spans": [s.to_dict() for s in self.spans],
            "text_digest": self.text_digest,
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — never body text or surface strings."""
        return {
            "action_id": self.action_id,
            "admitted_field_count": sum(
                1 for f in self.fields if f.admission is AdmissionState.ADMITTED
            ),
            "analysis_id": self.analysis_id,
            "application_number": self.application_number,
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "contradiction_count": len(self.contradictions),
            "disposition": self.disposition.value,
            "document_code": self.document_code,
            "family": self.family.value,
            "family_confidence": self.family_confidence,
            "field_count": len(self.fields),
            "mailing_date": self.mailing_date,
            "page_count": self.page_count,
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_count": len(self.spans),
            "text_digest": self.text_digest,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OfficeActionSemanticsResult":
        if not isinstance(value, Mapping):
            raise TypeError("OfficeActionSemanticsResult must be a mapping")
        return cls(
            schema_version=value.get("schema_version", SEMANTICS_V2_SCHEMA_VERSION),
            analysis_id=value.get("analysis_id", ""),
            artifact_id=value.get("artifact_id", ""),
            action_id=value.get("action_id", ""),
            family=value.get("family", CommunicationFamily.UNKNOWN.value),
            family_confidence=value.get("family_confidence"),
            disposition=value.get(
                "disposition", SemanticsDisposition.REVIEW.value
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            fields=tuple(
                SemanticField.from_dict(f) for f in (value.get("fields") or ())
            ),
            contradictions=tuple(
                ContradictionRecord.from_dict(c)
                for c in (value.get("contradictions") or ())
            ),
            admission_receipts=tuple(
                AdmissionReceipt.from_dict(r)
                for r in (value.get("admission_receipts") or ())
            ),
            spans=tuple(
                ExtractedSpan.from_dict(s) for s in (value.get("spans") or ())
            ),
            page_count=int(value.get("page_count", 0)),
            document_code=value.get("document_code"),
            mailing_date=value.get("mailing_date"),
            application_number=value.get("application_number"),
            labels=value.get("labels") or {},
            ruleset_versions=value.get("ruleset_versions") or {},
            model_versions=value.get("model_versions") or {},
            text_digest=value.get("text_digest", ""),
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Deterministic admission
# ---------------------------------------------------------------------------


def admit_semantic_field(
    field: SemanticField,
    *,
    spans: Mapping[str, ExtractedSpan] | Sequence[ExtractedSpan],
    span_texts: Mapping[str, str] | None = None,
    full_text: str | None = None,
    receipt_id: str | None = None,
    ruleset_version: str = SEMANTICS_V2_RULESET_VERSION,
    force_review: bool = False,
) -> tuple[SemanticField, AdmissionReceipt]:
    """Validate a field against exact spans; admit only on deterministic pass.

    Model-origin fields are treated identically for span/value checks — there
    is no shortcut into the admitted layer.
    """
    span_index: dict[str, ExtractedSpan]
    if isinstance(spans, Mapping):
        span_index = dict(spans)
    else:
        span_index = {s.span_id: s for s in spans}

    checks: list[str] = []
    failures: list[str] = []
    rid = receipt_id or f"adm:{uuid.uuid4().hex[:16]}"

    if not field.source_span_ids:
        failures.append("missing_source_spans")
    else:
        checks.append("source_spans_declared")
        for sid in field.source_span_ids:
            span = span_index.get(sid)
            if span is None:
                failures.append(f"missing_source_span:{sid}")
            else:
                checks.append(f"source_span_present:{sid}")
                if span.char_start is not None and span.char_end is not None:
                    if span.char_end < span.char_start:
                        failures.append(f"invalid_span_char_range:{sid}")
                    else:
                        checks.append(f"span_char_range_ordered:{sid}")

    surface_digest = _text_digest(field.surface_text)
    if surface_digest != field.text_digest:
        failures.append("surface_text_digest_mismatch")
    else:
        checks.append("surface_text_digest_match")

    # Optional: surface must appear in span text or full text when available.
    st = span_texts or {}
    if st and field.source_span_ids:
        joined = " ".join(st.get(sid, "") for sid in field.source_span_ids)
        surface_norm = _normalize_ws(field.surface_text)
        if surface_norm and joined:
            if surface_norm.lower() in _normalize_ws(joined).lower():
                checks.append("surface_in_span_texts")
            elif full_text and surface_norm.lower() in _normalize_ws(full_text).lower():
                checks.append("surface_in_full_text")
            else:
                # Soft check: short labels may be normalized; only hard-fail long.
                if len(surface_norm) >= 24:
                    failures.append("surface_not_found_in_spans")
                else:
                    checks.append("surface_short_label_soft")
        else:
            checks.append("span_texts_unavailable")
    elif full_text and field.surface_text:
        if _normalize_ws(field.surface_text).lower() in _normalize_ws(full_text).lower():
            checks.append("surface_in_full_text")
        elif len(_normalize_ws(field.surface_text)) >= 24:
            failures.append("surface_not_found_in_full_text")
        else:
            checks.append("surface_short_label_soft")

    # Kind-specific deterministic validation.
    kind_issues = _validate_field_value(field)
    for issue in kind_issues:
        if issue.startswith("ok:"):
            checks.append(issue)
        else:
            failures.append(issue)

    if force_review:
        failures.append("force_review")

    passed = not failures
    if passed:
        state = AdmissionState.ADMITTED
        review = ReviewState.NOT_REQUIRED
    elif any(
        f.startswith("missing_source")
        or f.endswith("digest_mismatch")
        or f.startswith("invalid_")
        for f in failures
    ):
        state = AdmissionState.REJECTED
        review = ReviewState.REQUIRED
    else:
        # Ambiguous value / soft issues → review, remain non-admitted.
        state = (
            AdmissionState.REVIEW_REQUIRED
            if field.origin is not FieldOrigin.MODEL
            else AdmissionState.CANDIDATE
        )
        if field.origin is FieldOrigin.MODEL:
            state = AdmissionState.CANDIDATE
        review = ReviewState.REQUIRED

    # Model origin: even on pass, admission is allowed only with this receipt.
    # On fail, model stays candidate.
    if field.origin is FieldOrigin.MODEL and not passed:
        state = AdmissionState.CANDIDATE
        review = ReviewState.REQUIRED

    receipt = AdmissionReceipt(
        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
        receipt_id=rid,
        field_id=field.field_id,
        passed=passed,
        checks=tuple(dict.fromkeys(checks)),
        failures=tuple(dict.fromkeys(failures)),
        ruleset_version=ruleset_version,
        admitted_state=state,
    )
    promoted = SemanticField(
        schema_version=field.schema_version,
        field_id=field.field_id,
        kind=field.kind,
        admission=state,
        origin=field.origin,
        source_span_ids=field.source_span_ids,
        page_indices=field.page_indices,
        text_digest=field.text_digest,
        surface_text=field.surface_text,
        confidence=field.confidence,
        normalized_value=field.normalized_value,
        claim_tokens=field.claim_tokens,
        claim_ambiguity=field.claim_ambiguity,
        citation_keys=field.citation_keys,
        citation_match_kind=field.citation_match_kind,
        labels=field.labels,
        admission_receipt_id=rid,
        review_state=review,
        char_start=field.char_start,
        char_end=field.char_end,
    )
    return promoted, receipt


def _validate_field_value(field: SemanticField) -> list[str]:
    """Return check/failure tokens for kind-specific value validation."""
    issues: list[str] = []
    kind = field.kind
    surface = field.surface_text
    normalized = field.normalized_value

    if kind in (SemanticFieldKind.MAILING_DATE, SemanticFieldKind.NOTIFICATION_DATE):
        target = normalized or surface
        # Prefer extracting a date token from a longer surface.
        m = re.search(
            r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})",
            target,
            re.I,
        )
        token = m.group(1) if m else target
        iso, date_issues = parse_calendar_date(token)
        if iso:
            issues.append("ok:date_parsed")
            if normalized and normalized != iso and not re.match(r"\d{4}-\d{2}-\d{2}", normalized or ""):
                # normalized may be the period string; only conflict on dual ISO.
                pass
            if field.normalized_value and _ISO_DATE_RE.match(field.normalized_value):
                if field.normalized_value != iso:
                    issues.append("date_normalized_conflict")
        else:
            issues.extend(date_issues or ["date_unparsed"])

    elif kind is SemanticFieldKind.APPLICATION_NUMBER:
        token = normalized or surface
        m = re.search(r"(\d{2}/\d{3},\d{3}|\d{2}/\d{6}|\d{8})", token)
        app = m.group(1) if m else token
        try:
            result = normalize_application_number(app)
        except Exception:  # noqa: BLE001 — fail closed to invalid
            issues.append("identifier_exception")
            return issues
        if result.status is IdentifierStatus.RESOLVED:
            issues.append("ok:identifier_resolved")
        elif result.status is IdentifierStatus.AMBIGUOUS:
            issues.append("identifier_ambiguous")
        else:
            issues.append("identifier_invalid")

    elif kind in (
        SemanticFieldKind.STATUTORY_CITATION,
        SemanticFieldKind.REGULATORY_CITATION,
    ):
        parsed = parse_patent_citations(surface)
        if parsed:
            issues.append("ok:citation_parsed")
            ambiguous = any(
                getattr(p, "match_kind", None)
                in (
                    CitationMatchKind.AMBIGUOUS,
                    CitationMatchKind.UNRESOLVED,
                    CitationMatchKind.PARTIAL,
                )
                or (
                    isinstance(getattr(p, "match_kind", None), str)
                    and p.match_kind  # type: ignore[attr-defined]
                    in ("ambiguous", "unresolved", "partial")
                )
                for p in parsed
            )
            if ambiguous:
                issues.append("citation_ambiguous")
        elif _STATUTORY_RE.search(surface) or _REGULATORY_RE.search(surface):
            issues.append("ok:citation_surface_pattern")
        else:
            issues.append("citation_unparsed")

    elif kind is SemanticFieldKind.CLAIM_GROUPING:
        tokens, amb = parse_claim_range_surface(surface)
        if amb is ClaimRangeAmbiguity.CONFLICTING:
            issues.append("claim_range_conflicting")
        elif amb is ClaimRangeAmbiguity.UNRESOLVED:
            issues.append("claim_range_unresolved")
        elif amb is ClaimRangeAmbiguity.OPEN_ENDED:
            issues.append("ok:claim_range_open_ended_retained")
        else:
            issues.append("ok:claim_range_parsed")
            if field.claim_tokens and tokens and set(field.claim_tokens) != set(tokens):
                issues.append("claim_tokens_conflict")

    elif kind is SemanticFieldKind.RESPONSE_PERIOD:
        if re.search(r"\d+\s+months?", surface, re.I) or (
            normalized and re.search(r"\d+", normalized)
        ):
            issues.append("ok:response_period")
        else:
            issues.append("response_period_unparsed")

    else:
        if surface.strip():
            issues.append("ok:nonempty_surface")
        else:
            issues.append("empty_surface")

    return issues


# ---------------------------------------------------------------------------
# Family detection
# ---------------------------------------------------------------------------


def detect_communication_family(
    text: str,
    *,
    document_code: str | None = None,
) -> tuple[CommunicationFamily, float | None, list[str], list[CommunicationFamily]]:
    """Detect communication family from content (+ optional document code).

    Returns ``(family, confidence, reason_notes, alternate_families)``.
    Ambiguous multi-family cues yield the highest-scoring family with
    alternates listed; unknown content yields ``UNKNOWN``.
    """
    lower = (text or "").lower()
    scores: dict[CommunicationFamily, float] = {}
    notes: list[str] = []

    for family, cues, weight in _FAMILY_CUE_RULES:
        hits = sum(1 for c in cues if c in lower)
        if hits:
            scores[family] = scores.get(family, 0.0) + weight * min(1.0, 0.5 + 0.25 * hits)

    code_family = family_for_document_code(document_code)
    if code_family is not None and code_family is not CommunicationFamily.UNKNOWN:
        scores[code_family] = scores.get(code_family, 0.0) + 0.35
        notes.append(f"document_code:{document_code}")

    if not scores:
        return CommunicationFamily.UNKNOWN, None, ["no_family_cues"], []

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].value))
    best_family, best_score = ranked[0]
    alternates = [f for f, s in ranked[1:] if s >= best_score * 0.85 and s >= 0.7]

    # Cap confidence to [0, 1].
    confidence = min(1.0, best_score)

    # If code and content strongly disagree, keep content winner but note drift.
    if (
        code_family is not None
        and code_family is not CommunicationFamily.UNKNOWN
        and code_family is not best_family
        and scores.get(code_family, 0.0) < best_score * 0.9
    ):
        notes.append("document_code_content_disagreement")
        confidence = min(confidence, 0.75)

    if alternates:
        notes.append("ambiguous_family_cues")
        confidence = min(confidence, 0.7)

    return best_family, confidence, notes, alternates


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class OfficeActionSemanticsV2:
    """Parse layout-aware office-action semantics across named families."""

    def __init__(
        self,
        *,
        bounds: SemanticsBounds | None = None,
        id_factory: Callable[[], str] | None = None,
        auto_admit: bool = True,
    ) -> None:
        self.bounds = bounds or SemanticsBounds()
        self._id_factory = id_factory or (lambda: f"oas2:{uuid.uuid4().hex}")
        self.auto_admit = bool(auto_admit)

    def analyze(
        self,
        value: OfficeActionSemanticsInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> OfficeActionSemanticsResult:
        inp = self._coerce_input(value, **kwargs)
        return self._analyze(inp)

    def analyze_many(
        self, values: Iterable[OfficeActionSemanticsInput | Mapping[str, Any]]
    ) -> list[OfficeActionSemanticsResult]:
        return [self.analyze(v) for v in values]

    def _coerce_input(
        self,
        value: OfficeActionSemanticsInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> OfficeActionSemanticsInput:
        if value is None:
            return OfficeActionSemanticsInput(**kwargs)
        if isinstance(value, OfficeActionSemanticsInput):
            if kwargs:
                raise TypeError("cannot mix OfficeActionSemanticsInput with kwargs")
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            pages = self._coerce_pages(data.get("pages") or ())
            spans = self._coerce_spans(data.get("spans") or ())
            model_fields = self._coerce_model_fields(data.get("model_fields") or ())
            return OfficeActionSemanticsInput(
                artifact_id=data.get("artifact_id", ""),
                pages=pages,
                text=str(data.get("text") or ""),
                spans=spans,
                span_texts=data.get("span_texts") or {},
                classification=data.get(
                    "classification", DisclosureClassification.UNKNOWN.value
                ),
                document_code=data.get("document_code"),
                mailing_date=data.get("mailing_date"),
                action_id=data.get("action_id"),
                model_fields=model_fields,
                labels=data.get("labels") or {},
            )
        raise TypeError(
            f"unsupported input type: {type(value).__name__}; "
            "expected OfficeActionSemanticsInput or mapping"
        )

    def _coerce_pages(self, raw: Any) -> tuple[LayoutPage, ...]:
        if not raw:
            return ()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise TypeError("pages must be a sequence")
        pages: list[LayoutPage] = []
        for item in raw:
            if isinstance(item, LayoutPage):
                pages.append(item)
            elif isinstance(item, Mapping):
                spans = self._coerce_spans(item.get("spans") or ())
                pages.append(
                    LayoutPage(
                        page_index=int(item.get("page_index", 0)),
                        text=str(item.get("text") or ""),
                        spans=spans,
                        span_texts=item.get("span_texts") or {},
                        origin=item.get("origin", ExtractionOrigin.UNKNOWN.value),
                        ocr_confidence=item.get("ocr_confidence"),
                        image_digest=item.get("image_digest"),
                    )
                )
            else:
                raise TypeError("pages items must be LayoutPage or mapping")
        return tuple(pages)

    def _coerce_spans(self, raw: Any) -> tuple[ExtractedSpan, ...]:
        if not raw:
            return ()
        spans: list[ExtractedSpan] = []
        for s in raw:
            if isinstance(s, ExtractedSpan):
                spans.append(s)
            elif isinstance(s, Mapping):
                spans.append(ExtractedSpan.from_dict(s))
            else:
                raise TypeError("spans items must be ExtractedSpan or mapping")
        return tuple(spans)

    def _coerce_model_fields(self, raw: Any) -> tuple[ModelFieldInput, ...]:
        if not raw:
            return ()
        out: list[ModelFieldInput] = []
        for item in raw:
            if isinstance(item, ModelFieldInput):
                out.append(item)
            elif isinstance(item, Mapping):
                span_ids = item.get("source_span_ids") or ()
                if isinstance(span_ids, str):
                    span_ids = (span_ids,)
                pages = item.get("page_indices") or ()
                out.append(
                    ModelFieldInput(
                        kind=item.get("kind", SemanticFieldKind.OTHER.value),
                        surface_text=str(item.get("surface_text") or ""),
                        source_span_ids=tuple(span_ids),
                        char_start=item.get("char_start"),
                        char_end=item.get("char_end"),
                        page_indices=tuple(pages),
                        confidence=item.get("confidence"),
                        labels=item.get("labels") or {},
                        normalized_value=item.get("normalized_value"),
                    )
                )
            else:
                raise TypeError("model_fields items must be ModelFieldInput or mapping")
        return tuple(out)

    def _analyze(self, inp: OfficeActionSemanticsInput) -> OfficeActionSemanticsResult:
        analysis_id = self._id_factory()
        reason_codes: list[str] = []
        warnings: list[str] = []
        classification = inp.classification

        if requires_quarantine(classification):
            reason_codes.append(SemanticsReasonCode.QUARANTINE_CLASSIFICATION.value)

        pages, full_text, spans, span_texts, page_count, minted = self._materialize_layout(
            inp, analysis_id
        )
        if minted:
            reason_codes.append(SemanticsReasonCode.COVERING_SPAN_MINTED.value)
            warnings.append("covering span(s) minted from page/full text")

        if len(full_text) > self.bounds.max_chars:
            reason_codes.append(SemanticsReasonCode.OVERSIZE_TEXT.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                full_text=full_text[:0],
                spans=spans,
                page_count=page_count,
                disposition=SemanticsDisposition.REJECTED,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=("text exceeds analysis bounds",),
                family=CommunicationFamily.UNKNOWN,
            )

        if not full_text.strip():
            reason_codes.append(SemanticsReasonCode.EMPTY_TEXT.value)
            reason_codes.append(SemanticsReasonCode.MISSING_CONTENT.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                full_text=full_text,
                spans=spans,
                page_count=page_count,
                disposition=SemanticsDisposition.MALFORMED,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=("empty office action text",),
                family=CommunicationFamily.UNKNOWN,
            )

        noisy = detect_noisy_scan(
            full_text,
            ocr_confidence=self._min_ocr_confidence(pages),
        )
        if noisy:
            reason_codes.append(SemanticsReasonCode.NOISY_SCAN.value)
            warnings.append("noisy_scan_detected")

        family, family_conf, family_notes, alternates = detect_communication_family(
            full_text, document_code=inp.document_code
        )
        if family is CommunicationFamily.UNKNOWN:
            reason_codes.append(SemanticsReasonCode.FAMILY_UNKNOWN.value)
        else:
            reason_codes.append(SemanticsReasonCode.FAMILY_DETECTED.value)
        if alternates or "ambiguous_family_cues" in family_notes:
            reason_codes.append(SemanticsReasonCode.FAMILY_AMBIGUOUS.value)
        for note in family_notes:
            if note not in warnings and note.startswith("document_code"):
                warnings.append(note)

        span_index = {s.span_id: s for s in spans}
        covering_by_page = self._covering_span_ids(spans, pages, full_text, span_texts)

        fields: list[SemanticField] = []
        field_counter = 0

        def _next_field_id() -> str:
            nonlocal field_counter
            field_counter += 1
            return f"fld:{analysis_id}:{field_counter:04d}"

        # Document code field (metadata).
        if inp.document_code:
            sid = covering_by_page.get(0) or next(iter(span_index), "span:missing")
            fields.append(
                self._make_field(
                    field_id=_next_field_id(),
                    kind=SemanticFieldKind.DOCUMENT_CODE,
                    surface=inp.document_code,
                    span_ids=(sid,),
                    page_indices=(0,),
                    origin=FieldOrigin.METADATA,
                    confidence=1.0,
                    normalized=inp.document_code.strip().upper(),
                    labels={"source": "input_document_code"},
                )
            )

        # Per-page + whole-document extraction.
        global_offset = 0
        page_offsets: list[tuple[int, int, int]] = []  # page_index, start, end
        for page in pages:
            start = global_offset
            end = start + len(page.text)
            page_offsets.append((page.page_index, start, end))
            # Extract from page text with page-local coords, then shift.
            page_span_id = covering_by_page.get(page.page_index) or next(
                iter(span_index), "span:missing"
            )
            page_fields = self._extract_fields_from_text(
                text=page.text,
                page_index=page.page_index,
                covering_span_id=page_span_id,
                span_index=span_index,
                id_factory=_next_field_id,
                char_offset=0,
            )
            fields.extend(page_fields)
            # Page separator for multi-page join.
            global_offset = end + (1 if page is not pages[-1] else 0)

        # Cross-page continuations.
        cont_fields = self._detect_cross_page_continuations(
            pages=pages,
            covering_by_page=covering_by_page,
            id_factory=_next_field_id,
        )
        if cont_fields:
            reason_codes.append(SemanticsReasonCode.CROSS_PAGE_CONTINUATION.value)
        fields.extend(cont_fields)

        # Model fields (held as candidates).
        model_fields, model_warnings = self._ingest_model_fields(
            inp, covering_by_page, span_index, _next_field_id
        )
        if model_fields:
            reason_codes.append(SemanticsReasonCode.MODEL_CANDIDATE_HELD.value)
        warnings.extend(model_warnings)
        fields.extend(model_fields)

        if fields:
            reason_codes.append(SemanticsReasonCode.FIELDS_EXTRACTED.value)
            reason_codes.append(SemanticsReasonCode.SPANS_BOUND.value)

        if len(fields) > self.bounds.max_fields:
            reason_codes.append(SemanticsReasonCode.FIELD_LIMIT.value)
            warnings.append("field list truncated to analysis bounds")
            fields = fields[: self.bounds.max_fields]

        # Deterministic admission.
        receipts: list[AdmissionReceipt] = []
        final_fields: list[SemanticField] = []
        if self.auto_admit:
            for field in fields:
                force_review = noisy and field.origin is not FieldOrigin.METADATA
                promoted, receipt = admit_semantic_field(
                    field,
                    spans=span_index,
                    span_texts=span_texts,
                    full_text=full_text,
                    receipt_id=f"adm:{analysis_id}:{len(receipts)+1:04d}",
                    force_review=False,
                )
                # Noisy scans: keep admitted deterministic values but mark review.
                if noisy and promoted.admission is AdmissionState.ADMITTED:
                    promoted = SemanticField(
                        schema_version=promoted.schema_version,
                        field_id=promoted.field_id,
                        kind=promoted.kind,
                        admission=promoted.admission,
                        origin=promoted.origin,
                        source_span_ids=promoted.source_span_ids,
                        page_indices=promoted.page_indices,
                        text_digest=promoted.text_digest,
                        surface_text=promoted.surface_text,
                        confidence=promoted.confidence,
                        normalized_value=promoted.normalized_value,
                        claim_tokens=promoted.claim_tokens,
                        claim_ambiguity=promoted.claim_ambiguity,
                        citation_keys=promoted.citation_keys,
                        citation_match_kind=promoted.citation_match_kind,
                        labels=dict(promoted.labels) | {"noisy_scan": "true"},
                        admission_receipt_id=promoted.admission_receipt_id,
                        review_state=ReviewState.REQUIRED,
                        char_start=promoted.char_start,
                        char_end=promoted.char_end,
                    )
                receipts.append(receipt)
                if field.origin is FieldOrigin.MODEL:
                    if promoted.admission is AdmissionState.ADMITTED:
                        reason_codes.append(
                            SemanticsReasonCode.MODEL_CANDIDATE_ADMITTED.value
                        )
                    else:
                        reason_codes.append(
                            SemanticsReasonCode.MODEL_CANDIDATE_BLOCKED.value
                        )
                elif receipt.passed:
                    reason_codes.append(SemanticsReasonCode.ADMISSION_PASSED.value)
                else:
                    reason_codes.append(SemanticsReasonCode.ADMISSION_FAILED.value)
                final_fields.append(promoted)
                # Silence unused.
                del force_review
        else:
            final_fields = fields

        # Contradictions: document-code drift, date, identifier, citation.
        contradictions = self._flag_contradictions(
            analysis_id=analysis_id,
            fields=final_fields,
            family=family,
            document_code=inp.document_code,
            alternates=alternates,
            family_notes=family_notes,
        )
        if contradictions:
            reason_codes.append(SemanticsReasonCode.CONTRADICTION_FLAGGED.value)
            if any(
                c.kind is ContradictionKind.DOCUMENT_CODE_DRIFT for c in contradictions
            ):
                reason_codes.append(SemanticsReasonCode.DOCUMENT_CODE_DRIFT.value)

        # Aggregate identifier/date/citation reason codes from fields.
        for f in final_fields:
            if f.kind is SemanticFieldKind.APPLICATION_NUMBER:
                if f.admission is AdmissionState.ADMITTED:
                    reason_codes.append(SemanticsReasonCode.IDENTIFIER_VALIDATED.value)
                elif f.admission in (
                    AdmissionState.REJECTED,
                    AdmissionState.REVIEW_REQUIRED,
                ):
                    reason_codes.append(SemanticsReasonCode.IDENTIFIER_INVALID.value)
            if f.kind in (
                SemanticFieldKind.MAILING_DATE,
                SemanticFieldKind.NOTIFICATION_DATE,
            ):
                if f.admission is AdmissionState.ADMITTED:
                    reason_codes.append(SemanticsReasonCode.DATE_VALIDATED.value)
                elif f.admission is AdmissionState.REJECTED:
                    reason_codes.append(SemanticsReasonCode.DATE_INVALID.value)
            if f.kind in (
                SemanticFieldKind.STATUTORY_CITATION,
                SemanticFieldKind.REGULATORY_CITATION,
            ):
                if f.citation_match_kind in (
                    CitationMatchKind.AMBIGUOUS.value,
                    CitationMatchKind.UNRESOLVED.value,
                    CitationMatchKind.PARTIAL.value,
                    "ambiguous",
                    "unresolved",
                    "partial",
                ):
                    reason_codes.append(SemanticsReasonCode.CITATION_AMBIGUOUS.value)
                elif f.admission is AdmissionState.ADMITTED:
                    reason_codes.append(SemanticsReasonCode.CITATION_VALIDATED.value)

        reason_codes = list(dict.fromkeys(reason_codes))

        mailing = inp.mailing_date
        if not mailing:
            for f in final_fields:
                if f.kind is SemanticFieldKind.MAILING_DATE and f.normalized_value:
                    mailing = f.normalized_value
                    break
            if not mailing:
                m = _MAILING_DATE_RE.search(full_text)
                if m:
                    iso, _ = parse_calendar_date(m.group("date"))
                    mailing = iso or m.group("date")

        app_no = None
        for f in final_fields:
            if f.kind is SemanticFieldKind.APPLICATION_NUMBER and f.normalized_value:
                app_no = f.normalized_value
                break
        if not app_no:
            am = _APPLICATION_NO_RE.search(full_text)
            if am:
                try:
                    norm = normalize_application_number(am.group("app"))
                    if norm.status is IdentifierStatus.RESOLVED:
                        app_no = norm.display
                    else:
                        app_no = am.group("app")
                except Exception:  # noqa: BLE001
                    app_no = am.group("app")

        disposition, review_state = self._disposition(
            family=family,
            family_confidence=family_conf,
            fields=final_fields,
            contradictions=contradictions,
            classification=classification,
            noisy=noisy,
            alternates=alternates,
            reason_codes=reason_codes,
        )
        if disposition is SemanticsDisposition.REVIEW or review_state is ReviewState.REQUIRED:
            reason_codes.append(SemanticsReasonCode.REVIEW_REQUIRED.value)
            reason_codes = list(dict.fromkeys(reason_codes))

        return OfficeActionSemanticsResult(
            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
            analysis_id=analysis_id,
            artifact_id=inp.artifact_id,
            action_id=inp.action_id or f"action:{analysis_id}",
            family=family,
            family_confidence=family_conf,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(reason_codes),
            warnings=tuple(dict.fromkeys(warnings)),
            fields=tuple(final_fields),
            contradictions=tuple(contradictions),
            admission_receipts=tuple(receipts),
            spans=tuple(spans),
            page_count=page_count,
            document_code=inp.document_code,
            mailing_date=mailing,
            application_number=app_no,
            labels=dict(inp.labels),
            ruleset_versions={
                "semantics_v2": SEMANTICS_V2_RULESET_VERSION,
                "interface": SEMANTICS_V2_INTERFACE,
            },
            model_versions={},
            text_digest=_text_digest(full_text),
            retained=True,
        )

    # --- layout materialization ---

    def _materialize_layout(
        self, inp: OfficeActionSemanticsInput, analysis_id: str
    ) -> tuple[
        tuple[LayoutPage, ...],
        str,
        tuple[ExtractedSpan, ...],
        dict[str, str],
        int,
        bool,
    ]:
        minted = False
        spans: list[ExtractedSpan] = list(inp.spans)
        span_texts: dict[str, str] = dict(inp.span_texts)

        if inp.pages:
            pages = list(inp.pages[: self.bounds.max_pages])
            # Collect page spans.
            for page in pages:
                for s in page.spans:
                    spans.append(s)
                for sid, txt in page.span_texts.items():
                    span_texts[sid] = txt
            # Ensure each page has at least one covering span.
            for page in pages:
                page_spans = [s for s in spans if s.page_index == page.page_index]
                if not page_spans and page.text:
                    sid = f"span:{analysis_id}:p{page.page_index}:cover"
                    cover = ExtractedSpan(
                        schema_version=CONTRACTS_SCHEMA_VERSION,
                        span_id=sid,
                        artifact_id=inp.artifact_id,
                        page_index=page.page_index,
                        char_start=0,
                        char_end=len(page.text),
                        bbox=None,
                        origin=page.origin
                        if isinstance(page.origin, ExtractionOrigin)
                        else ExtractionOrigin(str(page.origin)),
                        reading_order=page.page_index,
                        confidence=page.ocr_confidence,
                        text_digest=_text_digest(page.text),
                        image_digest=page.image_digest,
                        classification=inp.classification
                        if isinstance(inp.classification, DisclosureClassification)
                        else _coerce_classification(inp.classification),
                    )
                    spans.append(cover)
                    span_texts[sid] = page.text
                    minted = True
            full_text = "\n".join(p.text for p in pages)
            page_count = len(pages)
            return tuple(pages), full_text, tuple(spans), span_texts, page_count, minted

        # Fall back to flat text.
        text = inp.text or ""
        if text and not spans:
            sid = f"span:{analysis_id}:cover"
            cover = ExtractedSpan(
                schema_version=CONTRACTS_SCHEMA_VERSION,
                span_id=sid,
                artifact_id=inp.artifact_id,
                page_index=0,
                char_start=0,
                char_end=len(text),
                bbox=None,
                origin=ExtractionOrigin.UNKNOWN,
                reading_order=0,
                confidence=None,
                text_digest=_text_digest(text),
                image_digest=None,
                classification=inp.classification
                if isinstance(inp.classification, DisclosureClassification)
                else _coerce_classification(inp.classification),
            )
            spans.append(cover)
            span_texts[sid] = text
            minted = True
        page = LayoutPage(
            page_index=0,
            text=text,
            spans=tuple(spans),
            span_texts=span_texts,
            origin=ExtractionOrigin.UNKNOWN,
        )
        return (page,), text, tuple(spans), span_texts, 1 if text else 0, minted

    def _min_ocr_confidence(self, pages: Sequence[LayoutPage]) -> float | None:
        confs = [p.ocr_confidence for p in pages if p.ocr_confidence is not None]
        if not confs:
            return None
        return min(confs)

    def _covering_span_ids(
        self,
        spans: Sequence[ExtractedSpan],
        pages: Sequence[LayoutPage],
        full_text: str,
        span_texts: Mapping[str, str],
    ) -> dict[int, str]:
        by_page: dict[int, str] = {}
        for span in spans:
            if span.page_index is None:
                continue
            existing = by_page.get(span.page_index)
            if existing is None:
                by_page[span.page_index] = span.span_id
                continue
            # Prefer wider covering spans.
            cur = next(s for s in spans if s.span_id == existing)
            cur_w = (cur.char_end or 0) - (cur.char_start or 0)
            new_w = (span.char_end or 0) - (span.char_start or 0)
            if new_w > cur_w:
                by_page[span.page_index] = span.span_id
        if not by_page and spans:
            by_page[0] = spans[0].span_id
        return by_page

    # --- field extraction ---

    def _make_field(
        self,
        *,
        field_id: str,
        kind: SemanticFieldKind,
        surface: str,
        span_ids: tuple[str, ...],
        page_indices: tuple[int, ...],
        origin: FieldOrigin,
        confidence: float | None,
        normalized: str | None = None,
        claim_tokens: tuple[str, ...] = (),
        claim_ambiguity: str | None = None,
        citation_keys: tuple[str, ...] = (),
        citation_match_kind: str | None = None,
        labels: Mapping[str, str] | None = None,
        char_start: int | None = None,
        char_end: int | None = None,
        admission: AdmissionState = AdmissionState.CANDIDATE,
        review_state: ReviewState = ReviewState.PENDING,
    ) -> SemanticField:
        surface_capped = surface if len(surface) <= 8000 else surface[:8000]
        return SemanticField(
            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
            field_id=field_id,
            kind=kind,
            admission=admission,
            origin=origin,
            source_span_ids=span_ids,
            page_indices=page_indices,
            text_digest=_text_digest(surface_capped),
            surface_text=surface_capped,
            confidence=confidence,
            normalized_value=normalized,
            claim_tokens=claim_tokens,
            claim_ambiguity=claim_ambiguity,
            citation_keys=citation_keys,
            citation_match_kind=citation_match_kind,
            labels=labels or {},
            admission_receipt_id=None,
            review_state=review_state,
            char_start=char_start,
            char_end=char_end,
        )

    def _extract_fields_from_text(
        self,
        *,
        text: str,
        page_index: int,
        covering_span_id: str,
        span_index: Mapping[str, ExtractedSpan],
        id_factory: Callable[[], str],
        char_offset: int,
    ) -> list[SemanticField]:
        fields: list[SemanticField] = []
        pages = (page_index,)

        def add(
            kind: SemanticFieldKind,
            match: re.Match[str],
            *,
            confidence: float,
            origin: FieldOrigin = FieldOrigin.DETERMINISTIC_RULE,
            normalized: str | None = None,
            **extra: Any,
        ) -> None:
            start = match.start() + char_offset
            end = match.end() + char_offset
            surface = match.group(0)
            # Prefer a tighter span if one contains this range.
            sid = self._best_span_for_range(
                span_index, page_index, match.start(), match.end(), covering_span_id
            )
            fields.append(
                self._make_field(
                    field_id=id_factory(),
                    kind=kind,
                    surface=surface,
                    span_ids=(sid,),
                    page_indices=pages,
                    origin=origin,
                    confidence=confidence,
                    normalized=normalized,
                    char_start=start,
                    char_end=end,
                    **extra,
                )
            )

        for m in _HEADER_RE.finditer(text):
            add(SemanticFieldKind.HEADER, m, confidence=0.95)

        for m in _MAILING_DATE_RE.finditer(text):
            iso, _ = parse_calendar_date(m.group("date"))
            add(
                SemanticFieldKind.MAILING_DATE,
                m,
                confidence=0.9,
                normalized=iso or m.group("date"),
            )

        for m in _NOTIFICATION_DATE_RE.finditer(text):
            iso, _ = parse_calendar_date(m.group("date"))
            add(
                SemanticFieldKind.NOTIFICATION_DATE,
                m,
                confidence=0.9,
                normalized=iso or m.group("date"),
            )

        for m in _RESPONSE_PERIOD_RE.finditer(text):
            period = m.group("period") or m.group("period2") or m.group("period3")
            add(
                SemanticFieldKind.RESPONSE_PERIOD,
                m,
                confidence=0.85,
                normalized=_normalize_ws(period) if period else None,
            )

        for m in _EXAMINER_CONTACT_RE.finditer(text):
            add(SemanticFieldKind.EXAMINER_CONTACT, m, confidence=0.8)

        for m in _APPLICATION_NO_RE.finditer(text):
            app = m.group("app")
            try:
                norm = normalize_application_number(app)
                display = (
                    norm.display
                    if norm.status is IdentifierStatus.RESOLVED
                    else app
                )
            except Exception:  # noqa: BLE001
                display = app
            add(
                SemanticFieldKind.APPLICATION_NUMBER,
                m,
                confidence=0.9,
                origin=FieldOrigin.IDENTIFIER_NORMALIZER,
                normalized=display,
            )

        for m in _CLAIM_GROUP_RE.finditer(text):
            surface = m.group(0)
            tokens, amb = parse_claim_range_surface(surface)
            add(
                SemanticFieldKind.CLAIM_GROUPING,
                m,
                confidence=0.8 if amb is ClaimRangeAmbiguity.EXACT else 0.6,
                claim_tokens=tokens,
                claim_ambiguity=amb.value,
            )

        for m in _REJECTION_RE.finditer(text):
            add(SemanticFieldKind.REJECTION, m, confidence=0.85)

        for m in _OBJECTION_RE.finditer(text):
            add(SemanticFieldKind.OBJECTION, m, confidence=0.8)

        for m in _ALLOWANCE_RE.finditer(text):
            add(SemanticFieldKind.ALLOWANCE, m, confidence=0.85)

        for m in _REQUIREMENT_RE.finditer(text):
            add(SemanticFieldKind.REQUIREMENT, m, confidence=0.8)

        for m in _STATUTORY_RE.finditer(text):
            keys: tuple[str, ...] = ()
            match_kind: str | None = None
            try:
                parsed = parse_patent_citations(m.group(0))
                if parsed:
                    keys = tuple(
                        getattr(p, "citation_key", None)
                        or getattr(p, "normalized", None)
                        or m.group(0)
                        for p in parsed
                    )
                    mk = getattr(parsed[0], "match_kind", None)
                    match_kind = mk.value if isinstance(mk, Enum) else (
                        str(mk) if mk else None
                    )
            except Exception:  # noqa: BLE001
                pass
            add(
                SemanticFieldKind.STATUTORY_CITATION,
                m,
                confidence=0.85,
                origin=FieldOrigin.CITATION_PARSER,
                citation_keys=keys,
                citation_match_kind=match_kind,
            )

        for m in _REGULATORY_RE.finditer(text):
            add(
                SemanticFieldKind.REGULATORY_CITATION,
                m,
                confidence=0.8,
                origin=FieldOrigin.CITATION_PARSER,
            )

        for m in _FORM_RE.finditer(text):
            add(SemanticFieldKind.FORM, m, confidence=0.75)

        for m in _ATTACHMENT_RE.finditer(text):
            add(SemanticFieldKind.ATTACHMENT, m, confidence=0.7)

        for m in _SIGNATURE_RE.finditer(text):
            add(SemanticFieldKind.SIGNATURE, m, confidence=0.7)

        for m in _TABLE_RE.finditer(text):
            add(SemanticFieldKind.TABLE, m, confidence=0.7)

        return fields

    def _best_span_for_range(
        self,
        span_index: Mapping[str, ExtractedSpan],
        page_index: int,
        start: int,
        end: int,
        fallback: str,
    ) -> str:
        best_id = fallback
        best_width: int | None = None
        for sid, span in span_index.items():
            if span.page_index not in (None, page_index):
                continue
            if span.char_start is None or span.char_end is None:
                continue
            if span.char_start <= start and span.char_end >= end:
                width = span.char_end - span.char_start
                if best_width is None or width < best_width:
                    best_width = width
                    best_id = sid
        return best_id

    def _detect_cross_page_continuations(
        self,
        *,
        pages: Sequence[LayoutPage],
        covering_by_page: Mapping[int, str],
        id_factory: Callable[[], str],
    ) -> list[SemanticField]:
        if len(pages) < 2:
            return []
        fields: list[SemanticField] = []
        ordered = sorted(pages, key=lambda p: p.page_index)
        for i in range(len(ordered) - 1):
            cur, nxt = ordered[i], ordered[i + 1]
            mark = _CONTINUATION_MARK_RE.search(cur.text)
            # Also treat split mid-sentence: current ends mid-word-ish / next continues section.
            soft = False
            if not mark and cur.text.rstrip() and nxt.text.lstrip():
                tail = cur.text.rstrip()[-40:]
                head = nxt.text.lstrip()[:40]
                if tail.endswith(("-", "—", ",")) or (
                    not tail.endswith((".", "!", "?", ":"))
                    and head[:1].islower()
                ):
                    soft = True
                # Explicit shared section title continuation.
                if re.search(r"(?i)claim rejections?", tail) and re.search(
                    r"(?i)^(?:continued|claims?\s+\d)", head
                ):
                    soft = True
            if not mark and not soft:
                continue
            surface = (
                mark.group(0)
                if mark
                else f"[cross-page p{cur.page_index}->p{nxt.page_index}]"
            )
            sid_a = covering_by_page.get(cur.page_index)
            sid_b = covering_by_page.get(nxt.page_index)
            if not sid_a or not sid_b:
                continue
            fields.append(
                self._make_field(
                    field_id=id_factory(),
                    kind=SemanticFieldKind.CROSS_PAGE_CONTINUATION,
                    surface=surface,
                    span_ids=(sid_a, sid_b),
                    page_indices=(cur.page_index, nxt.page_index),
                    origin=FieldOrigin.LAYOUT,
                    confidence=0.85 if mark else 0.65,
                    labels={
                        "from_page": str(cur.page_index),
                        "to_page": str(nxt.page_index),
                    },
                )
            )
        return fields

    def _ingest_model_fields(
        self,
        inp: OfficeActionSemanticsInput,
        covering_by_page: Mapping[int, str],
        span_index: Mapping[str, ExtractedSpan],
        id_factory: Callable[[], str],
    ) -> tuple[list[SemanticField], list[str]]:
        out: list[SemanticField] = []
        warnings: list[str] = []
        limit = self.bounds.max_model_fields
        for i, mf in enumerate(inp.model_fields[:limit]):
            kind = (
                mf.kind
                if isinstance(mf.kind, SemanticFieldKind)
                else SemanticFieldKind(str(mf.kind))
            )
            span_ids = tuple(mf.source_span_ids) if mf.source_span_ids else ()
            if not span_ids:
                # Attach covering span; still a candidate until admitted.
                fallback = covering_by_page.get(0) or next(iter(span_index), None)
                if fallback is None:
                    warnings.append(f"model_field_{i}_dropped_no_span")
                    continue
                span_ids = (fallback,)
                warnings.append(f"model_field_{i}_covering_span_attached")
            # Validate span ids exist.
            missing = [s for s in span_ids if s not in span_index]
            if missing:
                warnings.append(f"model_field_{i}_unknown_spans")
            pages = tuple(mf.page_indices) if mf.page_indices else (0,)
            out.append(
                self._make_field(
                    field_id=id_factory(),
                    kind=kind,
                    surface=mf.surface_text,
                    span_ids=span_ids,
                    page_indices=pages,
                    origin=FieldOrigin.MODEL,
                    confidence=mf.confidence,
                    normalized=mf.normalized_value,
                    labels=dict(mf.labels) | {"model_held": "true"},
                    char_start=mf.char_start,
                    char_end=mf.char_end,
                    admission=AdmissionState.CANDIDATE,
                    review_state=ReviewState.PENDING,
                )
            )
        if len(inp.model_fields) > limit:
            warnings.append("model_fields_truncated")
        return out, warnings

    def _flag_contradictions(
        self,
        *,
        analysis_id: str,
        fields: Sequence[SemanticField],
        family: CommunicationFamily,
        document_code: str | None,
        alternates: Sequence[CommunicationFamily],
        family_notes: Sequence[str],
    ) -> list[ContradictionRecord]:
        out: list[ContradictionRecord] = []
        n = 0

        def add(
            kind: ContradictionKind,
            message_code: str,
            field_ids: Sequence[str],
            **labels: str,
        ) -> None:
            nonlocal n
            n += 1
            out.append(
                ContradictionRecord(
                    schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                    contradiction_id=f"ctr:{analysis_id}:{n:04d}",
                    kind=kind,
                    message_code=message_code,
                    field_ids=tuple(field_ids),
                    labels=labels,
                )
            )

        code_family = family_for_document_code(document_code)
        if (
            code_family is not None
            and code_family is not CommunicationFamily.UNKNOWN
            and family is not CommunicationFamily.UNKNOWN
            and code_family is not family
        ):
            code_fields = [
                f.field_id
                for f in fields
                if f.kind is SemanticFieldKind.DOCUMENT_CODE
            ]
            add(
                ContradictionKind.DOCUMENT_CODE_DRIFT,
                "document_code_family_mismatch",
                code_fields,
                document_code=document_code or "",
                code_family=code_family.value,
                content_family=family.value,
            )

        if "document_code_content_disagreement" in family_notes:
            if not any(c.kind is ContradictionKind.DOCUMENT_CODE_DRIFT for c in out):
                add(
                    ContradictionKind.DOCUMENT_CODE_DRIFT,
                    "document_code_content_disagreement",
                    (),
                    document_code=document_code or "",
                    content_family=family.value,
                )

        if alternates:
            add(
                ContradictionKind.FAMILY_AMBIGUITY,
                "multiple_family_cues",
                (),
                primary=family.value,
                alternates=",".join(a.value for a in alternates),
            )

        # Date conflicts: multiple distinct normalized mailing dates.
        mailing_vals = {
            f.normalized_value
            for f in fields
            if f.kind is SemanticFieldKind.MAILING_DATE and f.normalized_value
        }
        if len(mailing_vals) > 1:
            ids = [
                f.field_id
                for f in fields
                if f.kind is SemanticFieldKind.MAILING_DATE and f.normalized_value
            ]
            add(
                ContradictionKind.DATE_CONFLICT,
                "multiple_mailing_dates",
                ids,
                values=",".join(sorted(mailing_vals)),
            )

        # Identifier conflicts: multiple distinct app numbers.
        app_vals = {
            f.normalized_value
            for f in fields
            if f.kind is SemanticFieldKind.APPLICATION_NUMBER and f.normalized_value
        }
        if len(app_vals) > 1:
            ids = [
                f.field_id
                for f in fields
                if f.kind is SemanticFieldKind.APPLICATION_NUMBER and f.normalized_value
            ]
            add(
                ContradictionKind.IDENTIFIER_CONFLICT,
                "multiple_application_numbers",
                ids,
                values=",".join(sorted(app_vals)),
            )

        return out

    def _disposition(
        self,
        *,
        family: CommunicationFamily,
        family_confidence: float | None,
        fields: Sequence[SemanticField],
        contradictions: Sequence[ContradictionRecord],
        classification: DisclosureClassification,
        noisy: bool,
        alternates: Sequence[CommunicationFamily],
        reason_codes: Sequence[str],
    ) -> tuple[SemanticsDisposition, ReviewState]:
        if requires_quarantine(classification):
            return SemanticsDisposition.QUARANTINE, ReviewState.REQUIRED

        if SemanticsReasonCode.EMPTY_TEXT.value in reason_codes:
            return SemanticsDisposition.MALFORMED, ReviewState.REQUIRED

        needs_review = False
        if family is CommunicationFamily.UNKNOWN:
            needs_review = True
        if alternates:
            needs_review = True
        if family_confidence is not None and family_confidence < 0.6:
            needs_review = True
        if noisy:
            needs_review = True
        if contradictions:
            needs_review = True
        if any(f.admission is AdmissionState.REVIEW_REQUIRED for f in fields):
            needs_review = True
        if any(
            f.origin is FieldOrigin.MODEL and f.admission is not AdmissionState.ADMITTED
            for f in fields
        ):
            needs_review = True

        if needs_review:
            return SemanticsDisposition.REVIEW, ReviewState.REQUIRED
        return SemanticsDisposition.ANALYZED, ReviewState.NOT_REQUIRED

    def _terminal(
        self,
        *,
        analysis_id: str,
        inp: OfficeActionSemanticsInput,
        full_text: str,
        spans: Sequence[ExtractedSpan],
        page_count: int,
        disposition: SemanticsDisposition,
        review_state: ReviewState,
        reason_codes: Sequence[str],
        warnings: Sequence[str],
        family: CommunicationFamily,
    ) -> OfficeActionSemanticsResult:
        return OfficeActionSemanticsResult(
            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
            analysis_id=analysis_id,
            artifact_id=inp.artifact_id,
            action_id=inp.action_id or f"action:{analysis_id}",
            family=family,
            family_confidence=None,
            disposition=disposition,
            review_state=review_state,
            classification=inp.classification
            if isinstance(inp.classification, DisclosureClassification)
            else _coerce_classification(inp.classification),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            fields=(),
            contradictions=(),
            admission_receipts=(),
            spans=tuple(spans),
            page_count=page_count,
            document_code=inp.document_code,
            mailing_date=inp.mailing_date,
            application_number=None,
            labels=dict(inp.labels),
            ruleset_versions={
                "semantics_v2": SEMANTICS_V2_RULESET_VERSION,
                "interface": SEMANTICS_V2_INTERFACE,
            },
            model_versions={},
            text_digest=_text_digest(full_text) if full_text else sha256_hex(""),
            retained=True,
        )


def extract_office_action_semantics_v2(
    value: OfficeActionSemanticsInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> OfficeActionSemanticsResult:
    """Module-level convenience entry point."""
    return OfficeActionSemanticsV2().analyze(value, **kwargs)


# Document-code → expected family (drift detection).
_CODE_TO_FAMILY: Final[Mapping[str, CommunicationFamily]] = MappingProxyType(
    {
        "CTNF": CommunicationFamily.NON_FINAL,
        "CTFR": CommunicationFamily.FINAL,
        "CTAV": CommunicationFamily.ADVISORY_ACTION,
        "CTRS": CommunicationFamily.RESTRICTION_ELECTION,
        "CTMS": CommunicationFamily.MISSING_PARTS,
        "NOA": CommunicationFamily.ALLOWANCE_ISSUE_FEE,
        "NOAR": CommunicationFamily.ALLOWANCE_ISSUE_FEE,
        "EXIN": CommunicationFamily.EX_PARTE_QUAYLE,
        "OA": CommunicationFamily.UNKNOWN,
        "NRES": CommunicationFamily.RESTRICTION_ELECTION,
        "APPE": CommunicationFamily.APPEAL_PRE_APPEAL,
    }
)


def family_for_document_code(document_code: str | None) -> CommunicationFamily | None:
    """Map a USPTO document code to a communication family, if known."""
    if not document_code:
        return None
    code = document_code.strip().upper()
    return _CODE_TO_FAMILY.get(code)
