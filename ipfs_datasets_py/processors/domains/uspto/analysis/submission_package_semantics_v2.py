"""Submission-package semantics v2 (PATLAW-133).

Governed, source-anchored parsing of USPTO application submission packages
while distinguishing **candidate** extraction from **admitted** facts.

Design invariants
-----------------
* Every normalized fact cites an exact document/page/span **or** a
  structured-field anchor (never filenames/document codes alone).
* Receipt kinds (transmission attempt, Electronic Submission Receipt,
  payment receipt, official/corrected Filing Receipt, first ODP appearance)
  keep distinct content hashes and legal/operational effect codes.
* Rendering kinds (submitted DOCX, converted/auxiliary/split PDFs, feedback)
  are first-class and never substituted for one another.
* Inventory and internal-content discrepancies are reported explicitly.
* Model/candidate associations remain confidence-scored and reviewable.
* Document body text is never written to logs or exception messages.

Compatibility
-------------
v1 :mod:`submission_processor` contracts remain available for claim/receipt
extraction reuse. This module owns the multi-document package semantics
surface (inventory, cross-document links, receipt/rendering distinction,
admission layering).
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
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.identifiers import (
    IdentifierStatus,
    normalize_application_number,
)

SEMANTICS_V2_SCHEMA_VERSION: Final = "uspto.submission-package-semantics.v2"
SEMANTICS_V2_INTERFACE: Final = "SubmissionPackageSemanticsV2@1"
SEMANTICS_V2_RULESET_VERSION: Final = "submission-package-semantics-v2-rules@1"

DEFAULT_MAX_CHARS: Final = 2_000_000
DEFAULT_MAX_DOCS: Final = 256
DEFAULT_MAX_FACTS: Final = 8192
DEFAULT_MAX_SPANS: Final = 16384
DEFAULT_MAX_PAGES: Final = 512
DEFAULT_MAX_MODEL_ASSOC: Final = 512
DEFAULT_MAX_CANDIDATES: Final = 1024

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ApplicationType(str, Enum):
    """Application-type-specific package profile."""

    UTILITY = "utility"
    DESIGN = "design"
    PLANT = "plant"
    UNKNOWN = "unknown"


class PackageProfile(str, Enum):
    """Gold-fixture / observed package completeness profile."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    DUPLICATE = "duplicate"
    INCONSISTENT = "inconsistent"
    SCANNED = "scanned"
    CONVERSION_WARNING = "conversion_warning"
    UNKNOWN = "unknown"


class DocumentRole(str, Enum):
    """Role of a document inside a submission package."""

    CLAIMS = "claims"
    AMENDMENT = "amendment"
    REMARKS = "remarks"
    SPECIFICATION = "specification"
    DRAWINGS = "drawings"
    ADS = "ads"
    BIBLIOGRAPHIC = "bibliographic"
    DECLARATION = "declaration"
    CERTIFICATION = "certification"
    FORM = "form"
    FEE = "fee"
    SEQUENCE_LISTING = "sequence_listing"
    ATTACHMENT = "attachment"
    TRANSMISSION_ATTEMPT = "transmission_attempt"
    ELECTRONIC_SUBMISSION_RECEIPT = "electronic_submission_receipt"
    PAYMENT_RECEIPT = "payment_receipt"
    OFFICIAL_FILING_RECEIPT = "official_filing_receipt"
    CORRECTED_FILING_RECEIPT = "corrected_filing_receipt"
    FIRST_ODP_APPEARANCE = "first_odp_appearance"
    SUBMITTED_DOCX = "submitted_docx"
    CONVERTED_PDF = "converted_pdf"
    AUXILIARY_PDF = "auxiliary_pdf"
    SPLIT_PDF = "split_pdf"
    FEEDBACK_DOCUMENT = "feedback_document"
    REPLACEMENT_PAGES = "replacement_pages"
    INVENTORY_MANIFEST = "inventory_manifest"
    OTHER = "other"
    UNKNOWN = "unknown"


class ReceiptKind(str, Enum):
    """Distinct receipt / appearance evidence with non-substitutable effects."""

    TRANSMISSION_ATTEMPT = "transmission_attempt"
    ELECTRONIC_SUBMISSION_RECEIPT = "electronic_submission_receipt"
    PAYMENT_RECEIPT = "payment_receipt"
    OFFICIAL_FILING_RECEIPT = "official_filing_receipt"
    CORRECTED_FILING_RECEIPT = "corrected_filing_receipt"
    FIRST_ODP_APPEARANCE = "first_odp_appearance"


# Stable legal/operational effect codes — never shared across receipt kinds.
RECEIPT_EFFECT_CODES: Final[Mapping[ReceiptKind, str]] = MappingProxyType(
    {
        ReceiptKind.TRANSMISSION_ATTEMPT: "effect:transmission_attempted",
        ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT: "effect:electronic_submission_acknowledged",
        ReceiptKind.PAYMENT_RECEIPT: "effect:fee_payment_recorded",
        ReceiptKind.OFFICIAL_FILING_RECEIPT: "effect:official_filing_receipt_issued",
        ReceiptKind.CORRECTED_FILING_RECEIPT: "effect:corrected_filing_receipt_issued",
        ReceiptKind.FIRST_ODP_APPEARANCE: "effect:first_public_odp_appearance",
    }
)


class RenderingKind(str, Enum):
    """Distinct renderings of package content — never interchangeable."""

    SUBMITTED_DOCX = "submitted_docx"
    CONVERTED_PDF = "converted_pdf"
    AUXILIARY_PDF = "auxiliary_pdf"
    SPLIT_PDF = "split_pdf"
    FEEDBACK_DOCUMENT = "feedback_document"
    NATIVE_TEXT = "native_text"
    SCANNED_IMAGE = "scanned_image"
    OTHER = "other"


RENDERING_EFFECT_CODES: Final[Mapping[RenderingKind, str]] = MappingProxyType(
    {
        RenderingKind.SUBMITTED_DOCX: "effect:authoritative_submitted_docx",
        RenderingKind.CONVERTED_PDF: "effect:uspto_converted_pdf",
        RenderingKind.AUXILIARY_PDF: "effect:auxiliary_pdf_rendering",
        RenderingKind.SPLIT_PDF: "effect:split_pdf_part",
        RenderingKind.FEEDBACK_DOCUMENT: "effect:uspto_feedback_document",
        RenderingKind.NATIVE_TEXT: "effect:native_text_rendering",
        RenderingKind.SCANNED_IMAGE: "effect:scanned_image_rendering",
        RenderingKind.OTHER: "effect:other_rendering",
    }
)


class FactKind(str, Enum):
    """Typed normalized facts emitted by package semantics v2."""

    PACKAGE_INVENTORY = "package_inventory"
    BIBLIOGRAPHIC = "bibliographic"
    ADS_FIELD = "ads_field"
    BENEFIT_CLAIM = "benefit_claim"
    CLAIM = "claim"
    AMENDMENT = "amendment"
    SPECIFICATION = "specification"
    DRAWING = "drawing"
    ARGUMENT = "argument"
    DECLARATION = "declaration"
    SIGNATURE_PRESENCE = "signature_presence"
    CERTIFICATION = "certification"
    FORM = "form"
    FEE_ASSERTION = "fee_assertion"
    SEQUENCE_LISTING = "sequence_listing"
    ATTACHMENT = "attachment"
    REPLACEMENT_PAGE = "replacement_page"
    RECEIPT = "receipt"
    RENDERING = "rendering"
    WARNING = "warning"
    ERROR = "error"
    CROSS_DOCUMENT_LINK = "cross_document_link"
    OTHER = "other"


class AnchorKind(str, Enum):
    DOCUMENT_PAGE_SPAN = "document_page_span"
    STRUCTURED_FIELD = "structured_field"


class AdmissionState(str, Enum):
    CANDIDATE = "candidate"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    REVIEW_REQUIRED = "review_required"


class FieldOrigin(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL = "model"
    METADATA = "metadata"
    LAYOUT = "layout"
    INVENTORY = "inventory"
    STRUCTURED = "structured"
    OTHER = "other"


class PackageDisposition(str, Enum):
    ANALYZED = "analyzed"
    PARTIAL = "partial"
    REVIEW = "review"
    MALFORMED = "malformed"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class DiscrepancyKind(str, Enum):
    INVENTORY_MISSING = "inventory_missing"
    INVENTORY_EXTRA = "inventory_extra"
    INVENTORY_DUPLICATE = "inventory_duplicate"
    CONTENT_MISMATCH = "content_mismatch"
    IDENTIFIER_CONFLICT = "identifier_conflict"
    RENDERING_DIVERGENCE = "rendering_divergence"
    CONVERSION_WARNING = "conversion_warning"
    RECEIPT_HASH_COLLISION = "receipt_hash_collision"
    MISSING_SPAN = "missing_span"
    OTHER = "other"


class PackageReasonCode(str, Enum):
    PACKAGE_INVENTORY_BUILT = "package_inventory_built"
    FACTS_EXTRACTED = "facts_extracted"
    SPANS_BOUND = "spans_bound"
    RECEIPTS_DISTINGUISHED = "receipts_distinguished"
    RENDERINGS_DISTINGUISHED = "renderings_distinguished"
    DISCREPANCIES_REPORTED = "discrepancies_reported"
    CANDIDATE_ASSOCIATIONS_HELD = "candidate_associations_held"
    ADMISSION_PASSED = "admission_passed"
    ADMISSION_FAILED = "admission_failed"
    INVENTORY_GAP = "inventory_gap"
    DUPLICATE_DOCUMENTS = "duplicate_documents"
    INCONSISTENT_CONTENT = "inconsistent_content"
    NOISY_SCAN = "noisy_scan"
    CONVERSION_WARNING = "conversion_warning"
    SIGNATURE_PRESENCE_ONLY = "signature_presence_only"
    SEQUENCE_LISTING_APPLICABLE = "sequence_listing_applicable"
    SEQUENCE_LISTING_NOT_APPLICABLE = "sequence_listing_not_applicable"
    MODEL_CANDIDATE_HELD = "model_candidate_held"
    CROSS_DOCUMENT_LINKS = "cross_document_links"
    EMPTY_PACKAGE = "empty_package"
    OVERSIZE_PACKAGE = "oversize_package"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    REVIEW_REQUIRED = "review_required"
    COVERING_SPAN_MINTED = "covering_span_minted"


# ---------------------------------------------------------------------------
# Regex libraries
# ---------------------------------------------------------------------------

# Line-anchored so "provisional application number …" benefit claims do not
# collide with the package application number field.
_APPLICATION_NO_RE = re.compile(
    r"(?im)^[ \t]*Application\s*(?:No\.?|Number)\s*[:\-]?\s*"
    r"(?P<app>\d{2}/\d{3},\d{3}|\d{2}/\d{6}|\d{8})"
)
_CONFIRMATION_RE = re.compile(
    r"(?i)\bConfirmation\s*(?:No\.?|Number)\s*[:\-]?\s*(?P<conf>\d{4,5})"
)
_DOCKET_RE = re.compile(
    r"(?i)\b(?:Attorney\s+)?Docket\s*(?:No\.?|Number)?\s*[:\-]?\s*"
    r"(?P<docket>[A-Za-z0-9][A-Za-z0-9._\-/]{1,64})"
)
_CLAIM_RE = re.compile(
    r"(?im)^[ \t]*(?:Claim\s+)?(?P<num>\d+)\s*"
    r"(?:\((?P<status>currently\s+amended|original|previously\s+presented|"
    r"canceled|withdrawn|new)\)\s*)?[:.\-]?\s*(?P<body>.{10,500})"
)
_AMENDMENT_RE = re.compile(
    r"(?i)\b(?:"
    r"please\s+amend\s+claim\s+\d+|"
    r"amendments?\s+to\s+the\s+claims|"
    r"currently\s+amended|"
    r"preliminary\s+amendment|"
    r"replacement\s+sheets?"
    r")\b"
)
_REMARKS_RE = re.compile(
    r"(?i)\b(?:"
    r"remarks\b|"
    r"respectfully\s+traverse|"
    r"applicants?\s+respectfully\s+(?:submit|argue|request)|"
    r"in\s+response\s+to\s+the\s+(?:rejection|office\s+action)"
    r")\b"
)
_ARGUMENT_MAP_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:traverse|rebut|distinguish|argue)\s+(?:the\s+)?"
    r"(?:rejection|objection|requirement)|"
    r"claims?\s+\d+(?:\s*[-–—]\s*\d+)?\s+"
    r"(?:are|is)\s+(?:patentable|allowable|not\s+anticipated)|"
    r"under\s+35\s*U\.?\s*S\.?\s*C\.?\s*§?\s*\d+"
    r").{0,200}"
)
_SPEC_RE = re.compile(
    r"(?i)\b(?:"
    r"field\s+of\s+(?:the\s+)?invention|"
    r"background\s+of\s+(?:the\s+)?invention|"
    r"brief\s+description\s+of\s+(?:the\s+)?drawings|"
    r"detailed\s+description|"
    r"what\s+is\s+claimed\s+is|"
    r"title\s+of\s+(?:the\s+)?invention"
    r")\b"
)
_DRAWING_RE = re.compile(
    r"(?i)\b(?:"
    r"FIG\.?\s*\d+[A-Za-z]?|"
    r"figure\s+\d+[A-Za-z]?|"
    r"sheet\s+\d+\s+of\s+\d+|"
    r"drawing\s+sheet"
    r")\b"
)
_ADS_RE = re.compile(
    r"(?i)\b(?:"
    r"application\s+data\s+sheet|"
    r"inventor\s+information|"
    r"applicant\s+information|"
    r"correspondence\s+information|"
    r"domestic\s+benefit|"
    r"foreign\s+priority|"
    r"entity\s+status"
    r")\b"
)
_BENEFIT_RE = re.compile(
    r"(?i)\b(?:"
    r"claims?\s+(?:the\s+)?benefit\s+of|"
    r"priority\s+(?:is\s+)?claimed|"
    r"continuation(?:-in-part)?\s+of|"
    r"divisional\s+of|"
    r"provisional\s+application\s+(?:no\.?|number)"
    r").{0,120}"
)
_DECLARATION_RE = re.compile(
    r"(?i)\b(?:"
    r"declaration\s+under\s+37|"
    r"inventor(?:'s)?\s+oath|"
    r"37\s*C\.?\s*F\.?\s*R\.?\s*§?\s*1\.63|"
    r"I\s+hereby\s+declare"
    r")\b"
)
_CERTIFICATION_RE = re.compile(
    r"(?i)\b(?:"
    r"certif(?:y|ication)\b|"
    r"I\s+certify\s+that|"
    r"small\s+entity\s+status|"
    r"micro\s+entity"
    r")\b"
)
_FORM_RE = re.compile(
    r"(?i)\b(?:"
    r"Form\s+PTO/?[A-Z0-9/]+|"
    r"PTO/?SB/?\d+|"
    r"PTO/?AIA/?\d+|"
    r"ADS\s+form"
    r")\b"
)
_FEE_RE = re.compile(
    r"(?i)\b(?:"
    r"fee\s+code\s*[:\-]?\s*\d+|"
    r"basic\s+filing\s+fee|"
    r"amount\s*(?:paid|due)?\s*[:\-]?\s*\$?\d|"
    r"payment\s+of\s+(?:the\s+)?(?:filing|search|examination)\s+fee"
    r")\b"
)
_SEQUENCE_RE = re.compile(
    r"(?i)\b(?:"
    r"sequence\s+listing|"
    r"ST\.?\s*26|"
    r"CRF\s+sequence|"
    r"nucleotide\s+and/or\s+amino\s+acid"
    r")\b"
)
_ATTACHMENT_RE = re.compile(
    r"(?i)\b(?:"
    r"attachment(?:s)?\s*[:\-]|attached\s+(?:is|are|hereto)|"
    r"enclosure(?:s)?\s*[:\-]|"
    r"see\s+attached"
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
_REPLACEMENT_PAGE_RE = re.compile(
    r"(?i)\b(?:"
    r"replacement\s+(?:sheet|page)s?|"
    r"please\s+replace\s+(?:sheet|page)|"
    r"substitute\s+specification"
    r")\b"
)
_CONVERSION_WARN_RE = re.compile(
    r"(?i)\b(?:"
    r"conversion\s+warning|"
    r"docx\s+to\s+pdf\s+conversion|"
    r"document\s+converted\s+with\s+warnings?|"
    r"formatting\s+(?:may\s+have\s+)?changed|"
    r"equation\s+(?:not\s+)?preserved|"
    r"feedback\s+document"
    r")\b"
)
_RECEIPT_CUE_RULES: Final[
    tuple[tuple[ReceiptKind, tuple[str, ...], float], ...]
] = (
    (
        ReceiptKind.CORRECTED_FILING_RECEIPT,
        (
            "corrected filing receipt",
            "corrected filing receipt issued",
            "this corrects the filing receipt",
        ),
        0.95,
    ),
    (
        ReceiptKind.OFFICIAL_FILING_RECEIPT,
        (
            "filing receipt",
            "official filing receipt",
            "filing date accorded",
            "your application has been accorded",
        ),
        0.9,
    ),
    (
        ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT,
        (
            "electronic acknowledgement receipt",
            "electronic acknowledgment receipt",
            "electronic submission receipt",
            "acknowledgement receipt",
            "acknowledgment receipt",
            "receipt id:",
        ),
        0.9,
    ),
    (
        ReceiptKind.PAYMENT_RECEIPT,
        (
            "payment receipt",
            "fee payment receipt",
            "payment confirmation",
            "amount paid",
            "transaction id",
        ),
        0.9,
    ),
    (
        ReceiptKind.TRANSMISSION_ATTEMPT,
        (
            "transmission attempt",
            "upload started",
            "submission transmission",
            "attempting to submit",
            "transmission status",
        ),
        0.85,
    ),
    (
        ReceiptKind.FIRST_ODP_APPEARANCE,
        (
            "first odp appearance",
            "first appeared in odp",
            "patent file wrapper",
            "publicly available via odp",
            "odp document inventory",
        ),
        0.85,
    ),
)
_NOISY_SCAN_RE = re.compile(
    r"(?:[|]{3,}|@{3,}|\?{4,}|[^\x09\x0a\x0d\x20-\x7e]{8,}|"
    r"(?:illegible|unreadable|ocr\s+failure|garbled))"
    r"|(?:[A-Za-z]{1,2}\s){12,}"
)
_STATUTORY_RE = re.compile(r"(?i)\b35\s*U\.?\s*S\.?\s*C\.?\s*§?\s*\d+[A-Za-z()]*")

_ROLE_TO_RECEIPT: Final[Mapping[DocumentRole, ReceiptKind]] = MappingProxyType(
    {
        DocumentRole.TRANSMISSION_ATTEMPT: ReceiptKind.TRANSMISSION_ATTEMPT,
        DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT: ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT,
        DocumentRole.PAYMENT_RECEIPT: ReceiptKind.PAYMENT_RECEIPT,
        DocumentRole.OFFICIAL_FILING_RECEIPT: ReceiptKind.OFFICIAL_FILING_RECEIPT,
        DocumentRole.CORRECTED_FILING_RECEIPT: ReceiptKind.CORRECTED_FILING_RECEIPT,
        DocumentRole.FIRST_ODP_APPEARANCE: ReceiptKind.FIRST_ODP_APPEARANCE,
    }
)

_ROLE_TO_RENDERING: Final[Mapping[DocumentRole, RenderingKind]] = MappingProxyType(
    {
        DocumentRole.SUBMITTED_DOCX: RenderingKind.SUBMITTED_DOCX,
        DocumentRole.CONVERTED_PDF: RenderingKind.CONVERTED_PDF,
        DocumentRole.AUXILIARY_PDF: RenderingKind.AUXILIARY_PDF,
        DocumentRole.SPLIT_PDF: RenderingKind.SPLIT_PDF,
        DocumentRole.FEEDBACK_DOCUMENT: RenderingKind.FEEDBACK_DOCUMENT,
    }
)

# Roles typically required for a "complete" utility package (soft checklist).
_UTILITY_CORE_ROLES: Final[frozenset[DocumentRole]] = frozenset(
    {
        DocumentRole.SPECIFICATION,
        DocumentRole.CLAIMS,
        DocumentRole.DRAWINGS,
        DocumentRole.ADS,
        DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT,
    }
)


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class SubmissionPackageSemanticsV2Error(ValueError):
    """Bounded package-semantics failure with a stable machine-readable code."""

    def __init__(
        self, message: str, *, code: str = "package_semantics_v2_error"
    ) -> None:
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


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
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
        f"classification must be DisclosureClassification or str, "
        f"got {type(value).__name__}"
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
    return tuple(_nonneg_int(item, f"{field}[{i}]") for i, item in enumerate(value))


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


def detect_noisy_scan(text: str, *, ocr_confidence: float | None = None) -> bool:
    if ocr_confidence is not None and ocr_confidence < 0.55:
        return True
    if not text or not text.strip():
        return False
    if _NOISY_SCAN_RE.search(text):
        return True
    sample = text[:4000]
    if len(sample) >= 40:
        alnum = sum(1 for ch in sample if ch.isalnum() or ch.isspace())
        if alnum / max(len(sample), 1) < 0.55:
            return True
    return False


def detect_receipt_kind(
    text: str,
    *,
    declared_role: DocumentRole | str | None = None,
) -> tuple[ReceiptKind | None, float | None, list[str]]:
    """Detect receipt kind from content; role is a soft hint, never sufficient alone."""
    notes: list[str] = []
    scores: dict[ReceiptKind, float] = {}
    lower = (text or "").lower()

    for kind, cues, weight in _RECEIPT_CUE_RULES:
        hits = sum(1 for c in cues if c in lower)
        if hits:
            scores[kind] = scores.get(kind, 0.0) + weight * min(1.0, 0.5 + 0.25 * hits)

    role: DocumentRole | None = None
    if declared_role is not None:
        role = (
            declared_role
            if isinstance(declared_role, DocumentRole)
            else DocumentRole(str(declared_role))
        )
        mapped = _ROLE_TO_RECEIPT.get(role)
        if mapped is not None:
            # Role alone is never sufficient: only boost existing content score
            # or mark as candidate when content is empty.
            if scores:
                scores[mapped] = scores.get(mapped, 0.0) + 0.2
                notes.append(f"role_hint:{role.value}")
            elif not (text or "").strip():
                notes.append("role_without_content_insufficient")
                return None, None, notes

    if not scores:
        return None, None, ["no_receipt_cues"]

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].value))
    best, score = ranked[0]
    return best, min(1.0, score), notes


def receipt_effect_code(kind: ReceiptKind | str) -> str:
    k = kind if isinstance(kind, ReceiptKind) else ReceiptKind(str(kind))
    return RECEIPT_EFFECT_CODES[k]


def rendering_effect_code(kind: RenderingKind | str) -> str:
    k = kind if isinstance(kind, RenderingKind) else RenderingKind(str(kind))
    return RENDERING_EFFECT_CODES[k]


# ---------------------------------------------------------------------------
# Value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticsBounds:
    max_chars: int = DEFAULT_MAX_CHARS
    max_docs: int = DEFAULT_MAX_DOCS
    max_facts: int = DEFAULT_MAX_FACTS
    max_spans: int = DEFAULT_MAX_SPANS
    max_pages: int = DEFAULT_MAX_PAGES
    max_model_assoc: int = DEFAULT_MAX_MODEL_ASSOC
    max_candidates: int = DEFAULT_MAX_CANDIDATES

    def __post_init__(self) -> None:
        for name in (
            "max_chars",
            "max_docs",
            "max_facts",
            "max_spans",
            "max_pages",
            "max_model_assoc",
            "max_candidates",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ProvenanceAnchor:
    """Exact document/page/span **or** structured-field provenance."""

    schema_version: str
    anchor_id: str
    kind: AnchorKind
    document_id: str
    page_index: int | None = None
    span_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    structured_field_path: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "anchor_id", _identifier(self.anchor_id, "anchor_id"))
        object.__setattr__(self, "kind", _coerce_enum(AnchorKind, self.kind, "kind"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        if self.page_index is not None:
            object.__setattr__(
                self, "page_index", _nonneg_int(self.page_index, "page_index")
            )
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        if self.char_start is not None:
            object.__setattr__(
                self, "char_start", _nonneg_int(self.char_start, "char_start")
            )
        if self.char_end is not None:
            object.__setattr__(self, "char_end", _nonneg_int(self.char_end, "char_end"))
        object.__setattr__(
            self,
            "structured_field_path",
            _optional_str(
                self.structured_field_path, "structured_field_path", max_len=512
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        if self.kind is AnchorKind.DOCUMENT_PAGE_SPAN:
            if not self.span_id:
                raise ValueError("document_page_span anchor requires span_id")
        elif self.kind is AnchorKind.STRUCTURED_FIELD:
            if not self.structured_field_path:
                raise ValueError(
                    "structured_field anchor requires structured_field_path"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "char_end": self.char_end,
            "char_start": self.char_start,
            "document_id": self.document_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "page_index": self.page_index,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "structured_field_path": self.structured_field_path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProvenanceAnchor":
        if not isinstance(value, Mapping):
            raise TypeError("ProvenanceAnchor must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            anchor_id=value.get("anchor_id", ""),
            kind=value.get("kind", AnchorKind.DOCUMENT_PAGE_SPAN.value),
            document_id=value.get("document_id", ""),
            page_index=value.get("page_index"),
            span_id=value.get("span_id"),
            char_start=value.get("char_start"),
            char_end=value.get("char_end"),
            structured_field_path=value.get("structured_field_path"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class PackageDocumentInput:
    """One document (or structured artifact) in a submission package."""

    document_id: str
    role: DocumentRole | str
    text: str = ""
    spans: tuple[ExtractedSpan, ...] = ()
    span_texts: Mapping[str, str] = MappingProxyType({})
    structured_fields: Mapping[str, str] = MappingProxyType({})
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    media_type: str | None = None
    rendering_kind: RenderingKind | str | None = None
    page_count: int | None = None
    ocr_confidence: float | None = None
    content_digest: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    # Declared inventory role from manifest (may differ from content).
    inventory_role: DocumentRole | str | None = None
    filename_hint: str | None = None  # never sufficient as semantic evidence alone

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "role", _coerce_enum(DocumentRole, self.role, "role"))
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
            self,
            "structured_fields",
            _frozen_str_map(
                self.structured_fields,
                "structured_fields",
                max_items=256,
                allow_empty_values=True,
                max_value_len=4096,
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "media_type", _optional_str(self.media_type, "media_type", max_len=128)
        )
        if self.rendering_kind is not None:
            object.__setattr__(
                self,
                "rendering_kind",
                _coerce_enum(RenderingKind, self.rendering_kind, "rendering_kind"),
            )
        if self.page_count is not None:
            object.__setattr__(
                self, "page_count", _nonneg_int(self.page_count, "page_count")
            )
        object.__setattr__(
            self,
            "ocr_confidence",
            _optional_float_01(self.ocr_confidence, "ocr_confidence"),
        )
        if self.content_digest is not None:
            digest = _require_str(self.content_digest, "content_digest", max_len=64).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("content_digest must be sha256 hex")
            object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        if self.inventory_role is not None:
            object.__setattr__(
                self,
                "inventory_role",
                _coerce_enum(DocumentRole, self.inventory_role, "inventory_role"),
            )
        object.__setattr__(
            self,
            "filename_hint",
            _optional_str(self.filename_hint, "filename_hint", max_len=512),
        )


@dataclass(frozen=True, slots=True)
class ModelAssociationInput:
    """External model candidate association held out of the admitted layer."""

    kind: FactKind | str
    surface_text: str
    source_document_id: str | None = None
    source_span_ids: tuple[str, ...] = ()
    structured_field_path: str | None = None
    confidence: float | None = None
    related_fact_kinds: tuple[str, ...] = ()
    related_claim_tokens: tuple[str, ...] = ()
    related_citation_keys: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})
    normalized_value: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """Declared or observed package inventory entry."""

    schema_version: str
    entry_id: str
    document_id: str
    role: DocumentRole
    source: str  # "declared" | "observed" | "manifest"
    present: bool
    content_digest: str | None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "entry_id", _identifier(self.entry_id, "entry_id"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "role", _coerce_enum(DocumentRole, self.role, "role"))
        object.__setattr__(
            self, "source", _require_str(self.source, "source", max_len=32)
        )
        if not isinstance(self.present, bool):
            raise TypeError("present must be bool")
        if self.content_digest is not None:
            digest = _require_str(
                self.content_digest, "content_digest", max_len=64
            ).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("content_digest must be sha256 hex")
            object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "document_id": self.document_id,
            "entry_id": self.entry_id,
            "labels": dict(self.labels),
            "present": self.present,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InventoryEntry":
        if not isinstance(value, Mapping):
            raise TypeError("InventoryEntry must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            entry_id=value.get("entry_id", ""),
            document_id=value.get("document_id", ""),
            role=value.get("role", DocumentRole.UNKNOWN.value),
            source=value.get("source", "observed"),
            present=bool(value.get("present", True)),
            content_digest=value.get("content_digest"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DiscrepancyRecord:
    schema_version: str
    discrepancy_id: str
    kind: DiscrepancyKind
    message_code: str
    document_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self, "discrepancy_id", _identifier(self.discrepancy_id, "discrepancy_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(DiscrepancyKind, self.kind, "kind")
        )
        object.__setattr__(
            self,
            "message_code",
            _require_str(self.message_code, "message_code", max_len=128),
        )
        object.__setattr__(
            self,
            "document_ids",
            _tuple_of_str(self.document_ids, "document_ids", max_items=32),
        )
        object.__setattr__(
            self, "fact_ids", _tuple_of_str(self.fact_ids, "fact_ids", max_items=32)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "discrepancy_id": self.discrepancy_id,
            "document_ids": list(self.document_ids),
            "fact_ids": list(self.fact_ids),
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "message_code": self.message_code,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscrepancyRecord":
        if not isinstance(value, Mapping):
            raise TypeError("DiscrepancyRecord must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            discrepancy_id=value.get("discrepancy_id", ""),
            kind=value.get("kind", DiscrepancyKind.OTHER.value),
            message_code=value.get("message_code", "discrepancy"),
            document_ids=tuple(value.get("document_ids") or ()),
            fact_ids=tuple(value.get("fact_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    schema_version: str
    receipt_id: str
    fact_id: str
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
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
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
            "fact_id": self.fact_id,
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
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            receipt_id=value.get("receipt_id", ""),
            fact_id=value.get("fact_id", ""),
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
class ReceiptEvidence:
    """One distinguished receipt/appearance with unique hash and effect."""

    schema_version: str
    evidence_id: str
    kind: ReceiptKind
    document_id: str
    content_digest: str
    effect_code: str
    confidence: float | None
    anchor_ids: tuple[str, ...]
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(self, "kind", _coerce_enum(ReceiptKind, self.kind, "kind"))
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        digest = _require_str(self.content_digest, "content_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("content_digest must be sha256 hex")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self,
            "effect_code",
            _require_str(self.effect_code, "effect_code", max_len=128),
        )
        expected = RECEIPT_EFFECT_CODES[self.kind]
        if self.effect_code != expected:
            raise ValueError(
                f"effect_code for {self.kind.value} must be {expected}, "
                f"got {self.effect_code}"
            )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "anchor_ids", _tuple_of_str(self.anchor_ids, "anchor_ids", max_items=32)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_ids": list(self.anchor_ids),
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "document_id": self.document_id,
            "effect_code": self.effect_code,
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReceiptEvidence":
        if not isinstance(value, Mapping):
            raise TypeError("ReceiptEvidence must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            evidence_id=value.get("evidence_id", ""),
            kind=value.get("kind", ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT.value),
            document_id=value.get("document_id", ""),
            content_digest=value.get("content_digest", ""),
            effect_code=value.get("effect_code", ""),
            confidence=value.get("confidence"),
            anchor_ids=tuple(value.get("anchor_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class RenderingEvidence:
    """One distinguished rendering with unique hash and effect."""

    schema_version: str
    evidence_id: str
    kind: RenderingKind
    document_id: str
    content_digest: str
    effect_code: str
    media_type: str | None
    related_document_ids: tuple[str, ...]
    anchor_ids: tuple[str, ...]
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(RenderingKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        digest = _require_str(self.content_digest, "content_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("content_digest must be sha256 hex")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self,
            "effect_code",
            _require_str(self.effect_code, "effect_code", max_len=128),
        )
        expected = RENDERING_EFFECT_CODES[self.kind]
        if self.effect_code != expected:
            raise ValueError(
                f"effect_code for {self.kind.value} must be {expected}, "
                f"got {self.effect_code}"
            )
        object.__setattr__(
            self, "media_type", _optional_str(self.media_type, "media_type", max_len=128)
        )
        object.__setattr__(
            self,
            "related_document_ids",
            _tuple_of_str(
                self.related_document_ids, "related_document_ids", max_items=32
            ),
        )
        object.__setattr__(
            self, "anchor_ids", _tuple_of_str(self.anchor_ids, "anchor_ids", max_items=32)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_ids": list(self.anchor_ids),
            "content_digest": self.content_digest,
            "document_id": self.document_id,
            "effect_code": self.effect_code,
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "media_type": self.media_type,
            "related_document_ids": list(self.related_document_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RenderingEvidence":
        if not isinstance(value, Mapping):
            raise TypeError("RenderingEvidence must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            evidence_id=value.get("evidence_id", ""),
            kind=value.get("kind", RenderingKind.OTHER.value),
            document_id=value.get("document_id", ""),
            content_digest=value.get("content_digest", ""),
            effect_code=value.get("effect_code", ""),
            media_type=value.get("media_type"),
            related_document_ids=tuple(value.get("related_document_ids") or ()),
            anchor_ids=tuple(value.get("anchor_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    """Confidence-scored, anchor-bound semantic fact (candidate until admitted)."""

    schema_version: str
    fact_id: str
    kind: FactKind
    admission: AdmissionState
    origin: FieldOrigin
    document_id: str
    anchor_ids: tuple[str, ...]
    text_digest: str
    surface_text: str
    confidence: float | None
    normalized_value: str | None
    claim_tokens: tuple[str, ...]
    citation_keys: tuple[str, ...]
    related_document_ids: tuple[str, ...]
    labels: Mapping[str, str]
    admission_receipt_id: str | None
    review_state: ReviewState
    page_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(self, "kind", _coerce_enum(FactKind, self.kind, "kind"))
        object.__setattr__(
            self, "admission", _coerce_enum(AdmissionState, self.admission, "admission")
        )
        object.__setattr__(
            self, "origin", _coerce_enum(FieldOrigin, self.origin, "origin")
        )
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        anchors = _tuple_of_str(self.anchor_ids, "anchor_ids", max_items=64)
        if not anchors:
            raise ValueError("anchor_ids must be non-empty")
        object.__setattr__(self, "anchor_ids", anchors)
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
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        object.__setattr__(
            self,
            "related_document_ids",
            _tuple_of_str(
                self.related_document_ids, "related_document_ids", max_items=32
            ),
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
        object.__setattr__(
            self,
            "page_indices",
            _tuple_of_int(self.page_indices, "page_indices", max_items=64),
        )
        if (
            self.origin is FieldOrigin.MODEL
            and self.admission is AdmissionState.ADMITTED
            and self.admission_receipt_id is None
        ):
            raise ValueError(
                "model facts cannot enter admitted state without "
                "deterministic admission receipt"
            )

    @property
    def is_admitted(self) -> bool:
        return self.admission is AdmissionState.ADMITTED

    @property
    def is_model_origin(self) -> bool:
        return self.origin is FieldOrigin.MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value,
            "admission_receipt_id": self.admission_receipt_id,
            "anchor_ids": list(self.anchor_ids),
            "citation_keys": list(self.citation_keys),
            "claim_tokens": list(self.claim_tokens),
            "confidence": self.confidence,
            "document_id": self.document_id,
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "normalized_value": self.normalized_value,
            "origin": self.origin.value,
            "page_indices": list(self.page_indices),
            "related_document_ids": list(self.related_document_ids),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "surface_text": self.surface_text,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedFact":
        if not isinstance(value, Mapping):
            raise TypeError("NormalizedFact must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            fact_id=value.get("fact_id", ""),
            kind=value.get("kind", FactKind.OTHER.value),
            admission=value.get("admission", AdmissionState.CANDIDATE.value),
            origin=value.get("origin", FieldOrigin.OTHER.value),
            document_id=value.get("document_id", ""),
            anchor_ids=tuple(value.get("anchor_ids") or ()),
            text_digest=value.get("text_digest", ""),
            surface_text=str(value.get("surface_text") or ""),
            confidence=value.get("confidence"),
            normalized_value=value.get("normalized_value"),
            claim_tokens=tuple(value.get("claim_tokens") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            related_document_ids=tuple(value.get("related_document_ids") or ()),
            labels=value.get("labels") or {},
            admission_receipt_id=value.get("admission_receipt_id"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            page_indices=tuple(value.get("page_indices") or ()),
        )


@dataclass(frozen=True, slots=True)
class CandidateAssociation:
    """Confidence-scored, reviewable association (never auto-admitted)."""

    schema_version: str
    association_id: str
    kind: FactKind
    confidence: float | None
    origin: FieldOrigin
    document_id: str | None
    anchor_ids: tuple[str, ...]
    related_fact_ids: tuple[str, ...]
    related_claim_tokens: tuple[str, ...]
    related_citation_keys: tuple[str, ...]
    surface_text: str
    text_digest: str
    review_state: ReviewState
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self, "association_id", _identifier(self.association_id, "association_id")
        )
        object.__setattr__(self, "kind", _coerce_enum(FactKind, self.kind, "kind"))
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "origin", _coerce_enum(FieldOrigin, self.origin, "origin")
        )
        object.__setattr__(
            self,
            "document_id",
            _optional_identifier(self.document_id, "document_id"),
        )
        object.__setattr__(
            self, "anchor_ids", _tuple_of_str(self.anchor_ids, "anchor_ids", max_items=32)
        )
        object.__setattr__(
            self,
            "related_fact_ids",
            _tuple_of_str(self.related_fact_ids, "related_fact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "related_claim_tokens",
            _tuple_of_str(
                self.related_claim_tokens, "related_claim_tokens", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "related_citation_keys",
            _tuple_of_str(
                self.related_citation_keys, "related_citation_keys", max_items=64
            ),
        )
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        if len(self.surface_text) > 8000:
            raise ValueError("surface_text exceeds max length 8000")
        digest = _require_str(self.text_digest, "text_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(self, "text_digest", digest)
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_ids": list(self.anchor_ids),
            "association_id": self.association_id,
            "confidence": self.confidence,
            "document_id": self.document_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "origin": self.origin.value,
            "related_citation_keys": list(self.related_citation_keys),
            "related_claim_tokens": list(self.related_claim_tokens),
            "related_fact_ids": list(self.related_fact_ids),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "surface_text": self.surface_text,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateAssociation":
        if not isinstance(value, Mapping):
            raise TypeError("CandidateAssociation must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            association_id=value.get("association_id", ""),
            kind=value.get("kind", FactKind.OTHER.value),
            confidence=value.get("confidence"),
            origin=value.get("origin", FieldOrigin.MODEL.value),
            document_id=value.get("document_id"),
            anchor_ids=tuple(value.get("anchor_ids") or ()),
            related_fact_ids=tuple(value.get("related_fact_ids") or ()),
            related_claim_tokens=tuple(value.get("related_claim_tokens") or ()),
            related_citation_keys=tuple(value.get("related_citation_keys") or ()),
            surface_text=str(value.get("surface_text") or ""),
            text_digest=value.get("text_digest", ""),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class SubmissionPackageInput:
    """Multi-document package input for v2 semantics."""

    package_id: str
    documents: tuple[PackageDocumentInput, ...]
    matter_id: str | None = None
    application_type: ApplicationType | str = ApplicationType.UNKNOWN
    expected_application_number: str | None = None
    expected_inventory_roles: tuple[str, ...] = ()
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    model_associations: tuple[ModelAssociationInput, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        if not isinstance(self.documents, tuple):
            object.__setattr__(self, "documents", tuple(self.documents or ()))
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "application_type",
            _coerce_enum(ApplicationType, self.application_type, "application_type"),
        )
        object.__setattr__(
            self,
            "expected_application_number",
            _optional_str(
                self.expected_application_number,
                "expected_application_number",
                max_len=64,
            ),
        )
        object.__setattr__(
            self,
            "expected_inventory_roles",
            _tuple_of_str(
                self.expected_inventory_roles,
                "expected_inventory_roles",
                max_items=64,
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.model_associations, tuple):
            object.__setattr__(
                self, "model_associations", tuple(self.model_associations or ())
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )


@dataclass(frozen=True, slots=True)
class SubmissionPackageSemanticsResult:
    """Full package semantics outcome with admission and discrepancy layers."""

    schema_version: str
    analysis_id: str
    package_id: str
    matter_id: str | None
    application_type: ApplicationType
    package_profile: PackageProfile
    disposition: PackageDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    application_number: str | None
    inventory: tuple[InventoryEntry, ...]
    facts: tuple[NormalizedFact, ...]
    anchors: tuple[ProvenanceAnchor, ...]
    receipts: tuple[ReceiptEvidence, ...]
    renderings: tuple[RenderingEvidence, ...]
    discrepancies: tuple[DiscrepancyRecord, ...]
    candidate_associations: tuple[CandidateAssociation, ...]
    admission_receipts: tuple[AdmissionReceipt, ...]
    spans: tuple[ExtractedSpan, ...]
    document_ids: tuple[str, ...]
    labels: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    package_digest: str
    retained: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SEMANTICS_V2_SCHEMA_VERSION:
            raise ValueError(
                "SubmissionPackageSemanticsResult.schema_version must be "
                f"{SEMANTICS_V2_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "application_type",
            _coerce_enum(ApplicationType, self.application_type, "application_type"),
        )
        object.__setattr__(
            self,
            "package_profile",
            _coerce_enum(PackageProfile, self.package_profile, "package_profile"),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(PackageDisposition, self.disposition, "disposition"),
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
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        for attr in (
            "inventory",
            "facts",
            "anchors",
            "receipts",
            "renderings",
            "discrepancies",
            "candidate_associations",
            "admission_receipts",
            "spans",
        ):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val or ()))
        object.__setattr__(
            self,
            "document_ids",
            _tuple_of_str(self.document_ids, "document_ids", max_items=DEFAULT_MAX_DOCS),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=16),
        )
        digest = _require_str(self.package_digest, "package_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("package_digest must be sha256 hex")
        object.__setattr__(self, "package_digest", digest)
        if not isinstance(self.retained, bool):
            raise TypeError("retained must be bool")
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)
        # Receipt hashes and effects must remain distinct across kinds.
        effect_by_digest: dict[str, str] = {}
        for r in self.receipts:
            if r.content_digest in effect_by_digest:
                if effect_by_digest[r.content_digest] != r.effect_code:
                    raise ValueError(
                        "receipt content_digest collision across distinct effects"
                    )
            effect_by_digest[r.content_digest] = r.effect_code
        kind_effects = {r.kind: r.effect_code for r in self.receipts}
        for kind, code in kind_effects.items():
            if code != RECEIPT_EFFECT_CODES[kind]:
                raise ValueError(f"receipt effect drift for {kind.value}")
        for fact in self.facts:
            if (
                fact.origin is FieldOrigin.MODEL
                and fact.admission is AdmissionState.ADMITTED
                and not fact.admission_receipt_id
            ):
                raise ValueError(
                    "model facts never enter admitted state without "
                    "deterministic admission"
                )

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            PackageDisposition.REVIEW,
            PackageDisposition.MALFORMED,
            PackageDisposition.QUARANTINE,
            PackageDisposition.REJECTED,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def facts_by_kind(self, kind: FactKind | str) -> tuple[NormalizedFact, ...]:
        target = _coerce_enum(FactKind, kind, "kind")
        return tuple(f for f in self.facts if f.kind is target)

    def facts_by_admission(
        self, state: AdmissionState | str
    ) -> tuple[NormalizedFact, ...]:
        target = _coerce_enum(AdmissionState, state, "state")
        return tuple(f for f in self.facts if f.admission is target)

    def receipts_by_kind(self, kind: ReceiptKind | str) -> tuple[ReceiptEvidence, ...]:
        target = _coerce_enum(ReceiptKind, kind, "kind")
        return tuple(r for r in self.receipts if r.kind is target)

    def renderings_by_kind(
        self, kind: RenderingKind | str
    ) -> tuple[RenderingEvidence, ...]:
        target = _coerce_enum(RenderingKind, kind, "kind")
        return tuple(r for r in self.renderings if r.kind is target)

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def anchor_by_id(self, anchor_id: str) -> ProvenanceAnchor | None:
        for anchor in self.anchors:
            if anchor.anchor_id == anchor_id:
                return anchor
        return None

    def fact_by_id(self, fact_id: str) -> NormalizedFact | None:
        for fact in self.facts:
            if fact.fact_id == fact_id:
                return fact
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission_receipts": [r.to_dict() for r in self.admission_receipts],
            "analysis_id": self.analysis_id,
            "anchors": [a.to_dict() for a in self.anchors],
            "application_number": self.application_number,
            "application_type": self.application_type.value,
            "candidate_associations": [
                c.to_dict() for c in self.candidate_associations
            ],
            "classification": self.classification.value,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "disposition": self.disposition.value,
            "document_ids": list(self.document_ids),
            "facts": [f.to_dict() for f in self.facts],
            "inventory": [i.to_dict() for i in self.inventory],
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "package_digest": self.package_digest,
            "package_id": self.package_id,
            "package_profile": self.package_profile.value,
            "reason_codes": list(self.reason_codes),
            "receipts": [r.to_dict() for r in self.receipts],
            "renderings": [r.to_dict() for r in self.renderings],
            "retained": self.retained,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "spans": [s.to_dict() for s in self.spans],
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — never body text or surface strings."""
        return {
            "admitted_fact_count": sum(
                1 for f in self.facts if f.admission is AdmissionState.ADMITTED
            ),
            "analysis_id": self.analysis_id,
            "application_number": self.application_number,
            "application_type": self.application_type.value,
            "candidate_association_count": len(self.candidate_associations),
            "classification": self.classification.value,
            "discrepancy_count": len(self.discrepancies),
            "disposition": self.disposition.value,
            "document_count": len(self.document_ids),
            "fact_count": len(self.facts),
            "inventory_count": len(self.inventory),
            "matter_id": self.matter_id,
            "package_digest": self.package_digest,
            "package_id": self.package_id,
            "package_profile": self.package_profile.value,
            "reason_codes": list(self.reason_codes),
            "receipt_count": len(self.receipts),
            "receipt_kinds": sorted({r.kind.value for r in self.receipts}),
            "rendering_count": len(self.renderings),
            "rendering_kinds": sorted({r.kind.value for r in self.renderings}),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_count": len(self.spans),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionPackageSemanticsResult":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionPackageSemanticsResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTICS_V2_SCHEMA_VERSION
            ),
            analysis_id=value.get("analysis_id", ""),
            package_id=value.get("package_id", ""),
            matter_id=value.get("matter_id"),
            application_type=value.get(
                "application_type", ApplicationType.UNKNOWN.value
            ),
            package_profile=value.get(
                "package_profile", PackageProfile.UNKNOWN.value
            ),
            disposition=value.get(
                "disposition", PackageDisposition.REVIEW.value
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            application_number=value.get("application_number"),
            inventory=tuple(
                InventoryEntry.from_dict(i) for i in (value.get("inventory") or ())
            ),
            facts=tuple(
                NormalizedFact.from_dict(f) for f in (value.get("facts") or ())
            ),
            anchors=tuple(
                ProvenanceAnchor.from_dict(a) for a in (value.get("anchors") or ())
            ),
            receipts=tuple(
                ReceiptEvidence.from_dict(r) for r in (value.get("receipts") or ())
            ),
            renderings=tuple(
                RenderingEvidence.from_dict(r)
                for r in (value.get("renderings") or ())
            ),
            discrepancies=tuple(
                DiscrepancyRecord.from_dict(d)
                for d in (value.get("discrepancies") or ())
            ),
            candidate_associations=tuple(
                CandidateAssociation.from_dict(c)
                for c in (value.get("candidate_associations") or ())
            ),
            admission_receipts=tuple(
                AdmissionReceipt.from_dict(r)
                for r in (value.get("admission_receipts") or ())
            ),
            spans=tuple(
                ExtractedSpan.from_dict(s) for s in (value.get("spans") or ())
            ),
            document_ids=tuple(value.get("document_ids") or ()),
            labels=value.get("labels") or {},
            ruleset_versions=value.get("ruleset_versions") or {},
            package_digest=value.get("package_digest", ""),
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Deterministic admission
# ---------------------------------------------------------------------------


def admit_normalized_fact(
    fact: NormalizedFact,
    *,
    anchors: Mapping[str, ProvenanceAnchor] | Sequence[ProvenanceAnchor],
    spans: Mapping[str, ExtractedSpan] | Sequence[ExtractedSpan] | None = None,
    span_texts: Mapping[str, str] | None = None,
    document_texts: Mapping[str, str] | None = None,
    receipt_id: str | None = None,
    ruleset_version: str = SEMANTICS_V2_RULESET_VERSION,
    force_review: bool = False,
) -> tuple[NormalizedFact, AdmissionReceipt]:
    """Validate a fact against exact anchors; admit only on deterministic pass."""
    if isinstance(anchors, Mapping):
        anchor_index = dict(anchors)
    else:
        anchor_index = {a.anchor_id: a for a in anchors}

    span_index: dict[str, ExtractedSpan] = {}
    if spans is not None:
        if isinstance(spans, Mapping):
            span_index = dict(spans)
        else:
            span_index = {s.span_id: s for s in spans}

    checks: list[str] = []
    failures: list[str] = []
    rid = receipt_id or f"adm:{uuid.uuid4().hex[:16]}"

    if not fact.anchor_ids:
        failures.append("missing_anchors")
    else:
        checks.append("anchors_declared")
        for aid in fact.anchor_ids:
            anchor = anchor_index.get(aid)
            if anchor is None:
                failures.append(f"missing_anchor:{aid}")
                continue
            checks.append(f"anchor_present:{aid}")
            if anchor.kind is AnchorKind.DOCUMENT_PAGE_SPAN:
                if not anchor.span_id:
                    failures.append(f"span_anchor_missing_span_id:{aid}")
                elif span_index and anchor.span_id not in span_index:
                    failures.append(f"missing_span:{anchor.span_id}")
                else:
                    checks.append(f"span_bound:{anchor.span_id or aid}")
            elif anchor.kind is AnchorKind.STRUCTURED_FIELD:
                if not anchor.structured_field_path:
                    failures.append(f"structured_path_missing:{aid}")
                else:
                    checks.append(f"structured_field:{anchor.structured_field_path}")

    surface_digest = _text_digest(fact.surface_text)
    if surface_digest != fact.text_digest:
        failures.append("surface_text_digest_mismatch")
    else:
        checks.append("surface_text_digest_match")

    st = span_texts or {}
    docs = document_texts or {}
    surface_norm = _normalize_ws(fact.surface_text)
    if surface_norm and st:
        # Soft: surface appears in any related span text or document text.
        found = any(
            surface_norm.lower() in _normalize_ws(txt).lower() for txt in st.values()
        )
        if not found and fact.document_id in docs:
            found = surface_norm.lower() in _normalize_ws(docs[fact.document_id]).lower()
        if found:
            checks.append("surface_in_source")
        elif len(surface_norm) >= 24 and fact.origin is not FieldOrigin.STRUCTURED:
            failures.append("surface_not_found_in_source")
        else:
            checks.append("surface_short_or_structured_soft")
    else:
        checks.append("source_text_unavailable_or_empty")

    if fact.kind is FactKind.SIGNATURE_PRESENCE:
        # Never retain reusable signing material as normalized value.
        if fact.normalized_value and re.search(
            r"/s/|private\s*key|pkcs|certificate\s*blob",
            fact.normalized_value,
            re.I,
        ):
            failures.append("signature_material_not_allowed")
        else:
            checks.append("signature_presence_only")

    if force_review:
        failures.append("force_review")

    passed = not failures
    if passed:
        state = AdmissionState.ADMITTED
        review = ReviewState.NOT_REQUIRED
    elif any(
        f.startswith("missing_") or f.endswith("digest_mismatch") or f.startswith("invalid_")
        for f in failures
    ):
        state = AdmissionState.REJECTED
        review = ReviewState.REQUIRED
    else:
        state = (
            AdmissionState.CANDIDATE
            if fact.origin is FieldOrigin.MODEL
            else AdmissionState.REVIEW_REQUIRED
        )
        review = ReviewState.REQUIRED

    if fact.origin is FieldOrigin.MODEL and not passed:
        state = AdmissionState.CANDIDATE
        review = ReviewState.REQUIRED

    receipt = AdmissionReceipt(
        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
        receipt_id=rid,
        fact_id=fact.fact_id,
        passed=passed,
        checks=tuple(dict.fromkeys(checks)),
        failures=tuple(dict.fromkeys(failures)),
        ruleset_version=ruleset_version,
        admitted_state=state,
    )
    promoted = NormalizedFact(
        schema_version=fact.schema_version,
        fact_id=fact.fact_id,
        kind=fact.kind,
        admission=state,
        origin=fact.origin,
        document_id=fact.document_id,
        anchor_ids=fact.anchor_ids,
        text_digest=fact.text_digest,
        surface_text=fact.surface_text,
        confidence=fact.confidence,
        normalized_value=fact.normalized_value,
        claim_tokens=fact.claim_tokens,
        citation_keys=fact.citation_keys,
        related_document_ids=fact.related_document_ids,
        labels=fact.labels,
        admission_receipt_id=rid,
        review_state=review,
        page_indices=fact.page_indices,
    )
    return promoted, receipt


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class SubmissionPackageSemanticsV2:
    """Parse multi-document submission packages into span-bound semantics v2."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        bounds: SemanticsBounds | None = None,
    ) -> None:
        self._id_factory = id_factory or (lambda: f"sps2:{uuid.uuid4().hex[:16]}")
        self.bounds = bounds or SemanticsBounds()

    def analyze(
        self, package: SubmissionPackageInput
    ) -> SubmissionPackageSemanticsResult:
        analysis_id = self._id_factory()
        classification = (
            package.classification
            if isinstance(package.classification, DisclosureClassification)
            else _coerce_classification(package.classification)
        )
        app_type = (
            package.application_type
            if isinstance(package.application_type, ApplicationType)
            else ApplicationType(str(package.application_type))
        )

        reason_codes: list[str] = []
        warnings: list[str] = []
        discrepancies: list[DiscrepancyRecord] = []

        if requires_quarantine(classification):
            reason_codes.append(PackageReasonCode.QUARANTINE_CLASSIFICATION.value)

        docs = list(package.documents[: self.bounds.max_docs])
        if not docs:
            return self._empty_result(
                analysis_id=analysis_id,
                package=package,
                classification=classification,
                app_type=app_type,
                reason_codes=[PackageReasonCode.EMPTY_PACKAGE.value],
            )

        # Materialize spans / digests per document.
        spans: list[ExtractedSpan] = []
        span_texts: dict[str, str] = {}
        document_texts: dict[str, str] = {}
        content_digests: dict[str, str] = {}
        anchors: list[ProvenanceAnchor] = []
        cover_anchor_by_doc: dict[str, str] = {}
        minted = False

        total_chars = 0
        for doc in docs:
            text = doc.text or ""
            total_chars += len(text)
            if total_chars > self.bounds.max_chars:
                reason_codes.append(PackageReasonCode.OVERSIZE_PACKAGE.value)
                warnings.append("oversize_package_truncated")
                break
            digest = doc.content_digest or _text_digest(
                text
                if text
                else canonical_json(dict(doc.structured_fields))
            )
            content_digests[doc.document_id] = digest
            document_texts[doc.document_id] = text

            doc_spans = list(doc.spans)
            for s in doc_spans:
                spans.append(s)
            for sid, txt in doc.span_texts.items():
                span_texts[sid] = txt

            if text and not doc_spans:
                sid = f"span:{analysis_id}:{doc.document_id}:cover"
                cover = ExtractedSpan(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    span_id=sid,
                    artifact_id=doc.document_id,
                    page_index=0,
                    char_start=0,
                    char_end=len(text),
                    bbox=None,
                    origin=(
                        ExtractionOrigin.OCR
                        if doc.ocr_confidence is not None
                        else ExtractionOrigin.NATIVE
                    ),
                    reading_order=0,
                    confidence=doc.ocr_confidence,
                    text_digest=_text_digest(text),
                    image_digest=None,
                    classification=doc.classification
                    if isinstance(doc.classification, DisclosureClassification)
                    else _coerce_classification(doc.classification),
                )
                spans.append(cover)
                span_texts[sid] = text
                doc_spans = [cover]
                minted = True

            if doc_spans:
                cover_span = doc_spans[0]
                aid = f"anc:{analysis_id}:{doc.document_id}:cover"
                anchors.append(
                    ProvenanceAnchor(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        anchor_id=aid,
                        kind=AnchorKind.DOCUMENT_PAGE_SPAN,
                        document_id=doc.document_id,
                        page_index=cover_span.page_index,
                        span_id=cover_span.span_id,
                        char_start=cover_span.char_start,
                        char_end=cover_span.char_end,
                    )
                )
                cover_anchor_by_doc[doc.document_id] = aid
            elif doc.structured_fields:
                # Structured-only artifact (e.g. payment receipt fields).
                first_key = next(iter(doc.structured_fields))
                aid = f"anc:{analysis_id}:{doc.document_id}:sf:{first_key}"
                anchors.append(
                    ProvenanceAnchor(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        anchor_id=aid,
                        kind=AnchorKind.STRUCTURED_FIELD,
                        document_id=doc.document_id,
                        structured_field_path=first_key,
                    )
                )
                cover_anchor_by_doc[doc.document_id] = aid
            else:
                # Empty document still gets a structured package-inventory path.
                aid = f"anc:{analysis_id}:{doc.document_id}:inventory"
                anchors.append(
                    ProvenanceAnchor(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        anchor_id=aid,
                        kind=AnchorKind.STRUCTURED_FIELD,
                        document_id=doc.document_id,
                        structured_field_path=f"package.inventory.{doc.document_id}",
                    )
                )
                cover_anchor_by_doc[doc.document_id] = aid

        if minted:
            reason_codes.append(PackageReasonCode.COVERING_SPAN_MINTED.value)
        reason_codes.append(PackageReasonCode.SPANS_BOUND.value)

        # Inventory.
        inventory, inv_discrepancies = self._build_inventory(
            analysis_id=analysis_id,
            docs=docs,
            content_digests=content_digests,
            expected_roles=package.expected_inventory_roles,
            cover_anchor_by_doc=cover_anchor_by_doc,
        )
        discrepancies.extend(inv_discrepancies)
        reason_codes.append(PackageReasonCode.PACKAGE_INVENTORY_BUILT.value)
        if inv_discrepancies:
            reason_codes.append(PackageReasonCode.DISCREPANCIES_REPORTED.value)

        facts: list[NormalizedFact] = []
        receipt_evidences: list[ReceiptEvidence] = []
        rendering_evidences: list[RenderingEvidence] = []
        candidates: list[CandidateAssociation] = []

        # Inventory facts (structured anchors).
        for entry in inventory:
            anchor_id = cover_anchor_by_doc.get(entry.document_id)
            if not anchor_id:
                continue
            surface = f"inventory:{entry.role.value}:{entry.document_id}"
            facts.append(
                self._make_fact(
                    fact_id=self._id_factory(),
                    kind=FactKind.PACKAGE_INVENTORY,
                    document_id=entry.document_id,
                    surface=surface,
                    anchor_ids=(anchor_id,),
                    origin=FieldOrigin.INVENTORY,
                    confidence=1.0,
                    normalized=entry.role.value,
                    labels={"source": entry.source, "present": str(entry.present)},
                )
            )

        # Per-document extraction.
        noisy_any = False
        conversion_any = False
        for doc in docs:
            role = (
                doc.role
                if isinstance(doc.role, DocumentRole)
                else DocumentRole(str(doc.role))
            )
            text = document_texts.get(doc.document_id, "")
            cover = cover_anchor_by_doc[doc.document_id]
            digest = content_digests[doc.document_id]

            if detect_noisy_scan(text, ocr_confidence=doc.ocr_confidence):
                noisy_any = True
                noisy_labels: dict[str, str] = {}
                if doc.ocr_confidence is not None:
                    noisy_labels["ocr_confidence"] = f"{doc.ocr_confidence:.4f}"
                facts.append(
                    self._make_fact(
                        fact_id=self._id_factory(),
                        kind=FactKind.WARNING,
                        document_id=doc.document_id,
                        surface="noisy_scan_detected",
                        anchor_ids=(cover,),
                        origin=FieldOrigin.LAYOUT,
                        confidence=0.7,
                        normalized="noisy_scan",
                        labels=noisy_labels,
                    )
                )

            # Structured fields → structured anchors + facts.
            for path, value in doc.structured_fields.items():
                aid = f"anc:{analysis_id}:{doc.document_id}:sf:{sha256_hex(path)[:12]}"
                anchors.append(
                    ProvenanceAnchor(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        anchor_id=aid,
                        kind=AnchorKind.STRUCTURED_FIELD,
                        document_id=doc.document_id,
                        structured_field_path=path,
                    )
                )
                kind = self._fact_kind_for_structured_path(path, role)
                facts.append(
                    self._make_fact(
                        fact_id=self._id_factory(),
                        kind=kind,
                        document_id=doc.document_id,
                        surface=f"{path}={value}"[:8000],
                        anchor_ids=(aid,),
                        origin=FieldOrigin.STRUCTURED,
                        confidence=0.95,
                        normalized=value[:512] if value else None,
                        labels={"structured_path": path},
                    )
                )

            # Receipt detection (content-first).
            receipt_kind, rconf, rnotes = detect_receipt_kind(text, declared_role=role)
            if receipt_kind is None and role in _ROLE_TO_RECEIPT and doc.structured_fields:
                # Structured payment/ack fields may establish receipt kind with path evidence.
                if any(
                    "amount" in k.lower() or "payment" in k.lower() or "fee" in k.lower()
                    for k in doc.structured_fields
                ):
                    receipt_kind = ReceiptKind.PAYMENT_RECEIPT
                    rconf = 0.85
                    rnotes.append("structured_payment_fields")
                elif any(
                    "receipt" in k.lower() or "ack" in k.lower() for k in doc.structured_fields
                ):
                    receipt_kind = ReceiptKind.ELECTRONIC_SUBMISSION_RECEIPT
                    rconf = 0.85
                    rnotes.append("structured_ack_fields")

            if receipt_kind is not None:
                effect = receipt_effect_code(receipt_kind)
                # Domain-separate digests so kinds never share a hash even if
                # synthetic text overlaps (production content already differs).
                receipt_digest = sha256_hex(
                    f"receipt:{receipt_kind.value}:{digest}".encode("utf-8")
                )
                re_id = self._id_factory()
                receipt_labels: dict[str, str] = {}
                if rnotes:
                    receipt_labels["notes"] = ",".join(rnotes)[:200]
                receipt_evidences.append(
                    ReceiptEvidence(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        evidence_id=re_id,
                        kind=receipt_kind,
                        document_id=doc.document_id,
                        content_digest=receipt_digest,
                        effect_code=effect,
                        confidence=rconf,
                        anchor_ids=(cover,),
                        labels=receipt_labels,
                    )
                )
                facts.append(
                    self._make_fact(
                        fact_id=self._id_factory(),
                        kind=FactKind.RECEIPT,
                        document_id=doc.document_id,
                        surface=f"receipt:{receipt_kind.value}",
                        anchor_ids=(cover,),
                        origin=FieldOrigin.DETERMINISTIC_RULE,
                        confidence=rconf,
                        normalized=receipt_kind.value,
                        labels={
                            "effect_code": effect,
                            "content_digest": receipt_digest,
                        },
                    )
                )

            # Rendering distinction.
            rendering = doc.rendering_kind
            if rendering is None:
                rendering = _ROLE_TO_RENDERING.get(role)
            if rendering is None and doc.media_type:
                mt = doc.media_type.lower()
                if "wordprocessingml" in mt or mt.endswith("docx"):
                    rendering = RenderingKind.SUBMITTED_DOCX
                elif mt == "application/pdf":
                    rendering = RenderingKind.CONVERTED_PDF
                elif mt.startswith("image/"):
                    rendering = RenderingKind.SCANNED_IMAGE
            if rendering is not None:
                if not isinstance(rendering, RenderingKind):
                    rendering = RenderingKind(str(rendering))
                rend_digest = sha256_hex(
                    f"rendering:{rendering.value}:{digest}".encode("utf-8")
                )
                effect = rendering_effect_code(rendering)
                related: list[str] = []
                # Link DOCX ↔ converted PDF by package co-presence.
                if rendering is RenderingKind.SUBMITTED_DOCX:
                    for other in docs:
                        other_role = (
                            other.role
                            if isinstance(other.role, DocumentRole)
                            else DocumentRole(str(other.role))
                        )
                        if other_role is DocumentRole.CONVERTED_PDF or (
                            other.rendering_kind
                            and str(other.rendering_kind)
                            == RenderingKind.CONVERTED_PDF.value
                        ):
                            related.append(other.document_id)
                rendering_evidences.append(
                    RenderingEvidence(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        evidence_id=self._id_factory(),
                        kind=rendering,
                        document_id=doc.document_id,
                        content_digest=rend_digest,
                        effect_code=effect,
                        media_type=doc.media_type,
                        related_document_ids=tuple(related),
                        anchor_ids=(cover,),
                    )
                )
                facts.append(
                    self._make_fact(
                        fact_id=self._id_factory(),
                        kind=FactKind.RENDERING,
                        document_id=doc.document_id,
                        surface=f"rendering:{rendering.value}",
                        anchor_ids=(cover,),
                        origin=FieldOrigin.METADATA
                        if doc.rendering_kind or doc.media_type
                        else FieldOrigin.DETERMINISTIC_RULE,
                        confidence=0.9,
                        normalized=rendering.value,
                        related_document_ids=tuple(related),
                        labels={
                            "effect_code": effect,
                            "content_digest": rend_digest,
                        },
                    )
                )

            if text and _CONVERSION_WARN_RE.search(text):
                conversion_any = True
                facts.append(
                    self._make_fact(
                        fact_id=self._id_factory(),
                        kind=FactKind.WARNING,
                        document_id=doc.document_id,
                        surface="conversion_warning",
                        anchor_ids=(cover,),
                        origin=FieldOrigin.DETERMINISTIC_RULE,
                        confidence=0.85,
                        normalized="conversion_warning",
                    )
                )
            if role is DocumentRole.FEEDBACK_DOCUMENT or (
                rendering is not None
                and (
                    rendering is RenderingKind.FEEDBACK_DOCUMENT
                    if isinstance(rendering, RenderingKind)
                    else str(rendering) == RenderingKind.FEEDBACK_DOCUMENT.value
                )
            ):
                conversion_any = True

            # Text field extraction.
            if text:
                facts.extend(
                    self._extract_text_facts(
                        doc_id=doc.document_id,
                        role=role,
                        text=text,
                        cover_anchor_id=cover,
                        analysis_id=analysis_id,
                        anchors=anchors,
                        span_texts=span_texts,
                        spans=spans,
                    )
                )

        if receipt_evidences:
            reason_codes.append(PackageReasonCode.RECEIPTS_DISTINGUISHED.value)
            # Ensure distinct hashes across receipt kinds present.
            digests = [r.content_digest for r in receipt_evidences]
            if len(digests) != len(set(digests)) and len(
                {r.kind for r in receipt_evidences}
            ) > 1:
                discrepancies.append(
                    DiscrepancyRecord(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        discrepancy_id=self._id_factory(),
                        kind=DiscrepancyKind.RECEIPT_HASH_COLLISION,
                        message_code="receipt_content_digest_collision",
                        document_ids=tuple(
                            r.document_id for r in receipt_evidences
                        ),
                        fact_ids=(),
                    )
                )
            # Distinct effects across kinds.
            effect_set = {r.effect_code for r in receipt_evidences}
            kind_set = {r.kind for r in receipt_evidences}
            if len(effect_set) < len(kind_set):
                warnings.append("receipt_effect_collision")

        if rendering_evidences:
            reason_codes.append(PackageReasonCode.RENDERINGS_DISTINGUISHED.value)

        # Cross-document content consistency (application numbers, DOCX/PDF).
        content_disc = self._cross_document_checks(
            docs=docs,
            document_texts=document_texts,
            content_digests=content_digests,
            expected_app=package.expected_application_number,
            facts=facts,
        )
        discrepancies.extend(content_disc)
        if content_disc:
            reason_codes.append(PackageReasonCode.DISCREPANCIES_REPORTED.value)
            if any(
                d.kind
                in (
                    DiscrepancyKind.CONTENT_MISMATCH,
                    DiscrepancyKind.IDENTIFIER_CONFLICT,
                    DiscrepancyKind.RENDERING_DIVERGENCE,
                )
                for d in content_disc
            ):
                reason_codes.append(PackageReasonCode.INCONSISTENT_CONTENT.value)

        if any(d.kind is DiscrepancyKind.INVENTORY_DUPLICATE for d in discrepancies):
            reason_codes.append(PackageReasonCode.DUPLICATE_DOCUMENTS.value)
        if any(
            d.kind
            in (DiscrepancyKind.INVENTORY_MISSING, DiscrepancyKind.INVENTORY_EXTRA)
            for d in discrepancies
        ):
            reason_codes.append(PackageReasonCode.INVENTORY_GAP.value)

        if noisy_any:
            reason_codes.append(PackageReasonCode.NOISY_SCAN.value)
        if conversion_any:
            reason_codes.append(PackageReasonCode.CONVERSION_WARNING.value)
            if not any(
                d.kind is DiscrepancyKind.CONVERSION_WARNING for d in discrepancies
            ):
                discrepancies.append(
                    DiscrepancyRecord(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        discrepancy_id=self._id_factory(),
                        kind=DiscrepancyKind.CONVERSION_WARNING,
                        message_code="conversion_warning_present",
                        document_ids=tuple(
                            d.document_id
                            for d in docs
                            if DocumentRole(
                                d.role if isinstance(d.role, DocumentRole) else str(d.role)
                            )
                            in (
                                DocumentRole.FEEDBACK_DOCUMENT,
                                DocumentRole.CONVERTED_PDF,
                            )
                            or _CONVERSION_WARN_RE.search(d.text or "")
                        ),
                        fact_ids=(),
                    )
                )

        # Signature presence reason.
        if any(f.kind is FactKind.SIGNATURE_PRESENCE for f in facts):
            reason_codes.append(PackageReasonCode.SIGNATURE_PRESENCE_ONLY.value)

        # Sequence listing applicability.
        seq_facts = [f for f in facts if f.kind is FactKind.SEQUENCE_LISTING]
        if seq_facts:
            reason_codes.append(PackageReasonCode.SEQUENCE_LISTING_APPLICABLE.value)
        elif app_type is ApplicationType.UTILITY:
            # Explicit non-applicability only when package complete enough.
            reason_codes.append(PackageReasonCode.SEQUENCE_LISTING_NOT_APPLICABLE.value)

        # Cross-document argument links.
        arg_facts = [f for f in facts if f.kind is FactKind.ARGUMENT]
        claim_facts = [f for f in facts if f.kind is FactKind.CLAIM]
        if arg_facts and claim_facts:
            for arg in arg_facts[:32]:
                related_claims = [
                    c.fact_id
                    for c in claim_facts
                    if c.document_id != arg.document_id
                    or set(c.claim_tokens) & set(arg.claim_tokens)
                ][:8]
                if related_claims:
                    # Emit link fact with multi-doc related ids.
                    cover = cover_anchor_by_doc.get(arg.document_id)
                    if cover:
                        facts.append(
                            self._make_fact(
                                fact_id=self._id_factory(),
                                kind=FactKind.CROSS_DOCUMENT_LINK,
                                document_id=arg.document_id,
                                surface=f"argument_to_claims:{arg.fact_id}",
                                anchor_ids=(cover,),
                                origin=FieldOrigin.DETERMINISTIC_RULE,
                                confidence=0.7,
                                related_document_ids=tuple(
                                    {
                                        c.document_id
                                        for c in claim_facts
                                        if c.fact_id in related_claims
                                    }
                                ),
                                labels={
                                    "from_fact": arg.fact_id,
                                    "to_facts": ",".join(related_claims)[:200],
                                },
                            )
                        )
            reason_codes.append(PackageReasonCode.CROSS_DOCUMENT_LINKS.value)

        # Model associations remain candidates / reviewable.
        for ma in package.model_associations[: self.bounds.max_model_assoc]:
            kind = (
                ma.kind
                if isinstance(ma.kind, FactKind)
                else FactKind(str(ma.kind))
            )
            doc_id = ma.source_document_id or (
                docs[0].document_id if docs else package.package_id
            )
            anchor_ids: list[str] = []
            if ma.source_span_ids:
                for sid in ma.source_span_ids:
                    aid = f"anc:{analysis_id}:model:{sid}"
                    anchors.append(
                        ProvenanceAnchor(
                            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                            anchor_id=aid,
                            kind=AnchorKind.DOCUMENT_PAGE_SPAN,
                            document_id=doc_id,
                            span_id=sid,
                            page_index=0,
                        )
                    )
                    anchor_ids.append(aid)
            elif ma.structured_field_path:
                aid = f"anc:{analysis_id}:model:sf:{sha256_hex(ma.structured_field_path)[:12]}"
                anchors.append(
                    ProvenanceAnchor(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        anchor_id=aid,
                        kind=AnchorKind.STRUCTURED_FIELD,
                        document_id=doc_id,
                        structured_field_path=ma.structured_field_path,
                    )
                )
                anchor_ids.append(aid)
            else:
                anchor_ids.append(
                    cover_anchor_by_doc.get(doc_id, anchors[0].anchor_id if anchors else "")
                )
            surface = ma.surface_text[:8000]
            dig = _text_digest(surface)
            # Related facts by kind/claims.
            related_fact_ids = [
                f.fact_id
                for f in facts
                if f.kind.value in (ma.related_fact_kinds or ())
                or set(f.claim_tokens) & set(ma.related_claim_tokens or ())
            ][:16]
            cand = CandidateAssociation(
                schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                association_id=self._id_factory(),
                kind=kind,
                confidence=ma.confidence,
                origin=FieldOrigin.MODEL,
                document_id=doc_id,
                anchor_ids=tuple(a for a in anchor_ids if a),
                related_fact_ids=tuple(related_fact_ids),
                related_claim_tokens=tuple(ma.related_claim_tokens or ()),
                related_citation_keys=tuple(ma.related_citation_keys or ()),
                surface_text=surface,
                text_digest=dig,
                review_state=ReviewState.REQUIRED,
                labels=dict(ma.labels or {}),
            )
            candidates.append(cand)
            # Also emit as candidate fact (never auto-admitted).
            if cand.anchor_ids:
                facts.append(
                    NormalizedFact(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        fact_id=self._id_factory(),
                        kind=kind,
                        admission=AdmissionState.CANDIDATE,
                        origin=FieldOrigin.MODEL,
                        document_id=doc_id,
                        anchor_ids=cand.anchor_ids,
                        text_digest=dig,
                        surface_text=surface,
                        confidence=ma.confidence,
                        normalized_value=ma.normalized_value,
                        claim_tokens=tuple(ma.related_claim_tokens or ()),
                        citation_keys=tuple(ma.related_citation_keys or ()),
                        related_document_ids=(),
                        labels=dict(ma.labels or {}),
                        admission_receipt_id=None,
                        review_state=ReviewState.REQUIRED,
                    )
                )
        if candidates:
            reason_codes.append(PackageReasonCode.CANDIDATE_ASSOCIATIONS_HELD.value)
            reason_codes.append(PackageReasonCode.MODEL_CANDIDATE_HELD.value)

        # Cap facts.
        if len(facts) > self.bounds.max_facts:
            facts = facts[: self.bounds.max_facts]
            warnings.append("fact_limit_truncated")

        # Admit facts.
        anchor_index = {a.anchor_id: a for a in anchors}
        span_index = {s.span_id: s for s in spans}
        final_facts: list[NormalizedFact] = []
        admission_receipts: list[AdmissionReceipt] = []
        for fact in facts:
            if fact.origin is FieldOrigin.MODEL and fact.admission is AdmissionState.CANDIDATE:
                # Still run admission checks for audit, but model stays candidate on fail.
                promoted, receipt = admit_normalized_fact(
                    fact,
                    anchors=anchor_index,
                    spans=span_index,
                    span_texts=span_texts,
                    document_texts=document_texts,
                    receipt_id=self._id_factory(),
                )
                # Force model non-admitted unless checks pass AND we keep receipt.
                if promoted.admission is AdmissionState.ADMITTED:
                    # Model may be admitted only with receipt (already set).
                    pass
                final_facts.append(promoted)
                admission_receipts.append(receipt)
            else:
                promoted, receipt = admit_normalized_fact(
                    fact,
                    anchors=anchor_index,
                    spans=span_index,
                    span_texts=span_texts,
                    document_texts=document_texts,
                    receipt_id=self._id_factory(),
                )
                final_facts.append(promoted)
                admission_receipts.append(receipt)

        if any(f.admission is AdmissionState.ADMITTED for f in final_facts):
            reason_codes.append(PackageReasonCode.ADMISSION_PASSED.value)
        if any(
            f.admission in (AdmissionState.REJECTED, AdmissionState.REVIEW_REQUIRED)
            for f in final_facts
        ):
            reason_codes.append(PackageReasonCode.ADMISSION_FAILED.value)
        reason_codes.append(PackageReasonCode.FACTS_EXTRACTED.value)

        # Application number.
        app_no = package.expected_application_number
        for f in final_facts:
            if f.kind is FactKind.BIBLIOGRAPHIC and f.normalized_value:
                if re.search(r"\d{2}/", f.normalized_value) or re.search(
                    r"\d{8}", f.normalized_value
                ):
                    app_no = f.normalized_value
                    break
        if not app_no:
            for doc in docs:
                m = _APPLICATION_NO_RE.search(doc.text or "")
                if m:
                    try:
                        norm = normalize_application_number(m.group("app"))
                        app_no = (
                            norm.display
                            if norm.status is IdentifierStatus.RESOLVED
                            else m.group("app")
                        )
                    except Exception:  # noqa: BLE001
                        app_no = m.group("app")
                    break

        package_profile = self._infer_profile(
            docs=docs,
            discrepancies=discrepancies,
            noisy=noisy_any,
            conversion=conversion_any,
            inventory=inventory,
            app_type=app_type,
        )

        disposition, review_state = self._disposition(
            classification=classification,
            discrepancies=discrepancies,
            final_facts=final_facts,
            noisy=noisy_any,
            profile=package_profile,
            candidates=candidates,
        )
        if disposition is PackageDisposition.REVIEW or review_state is ReviewState.REQUIRED:
            reason_codes.append(PackageReasonCode.REVIEW_REQUIRED.value)

        # Package digest over document digests (ordered).
        pkg_material = "|".join(
            f"{d.document_id}:{content_digests.get(d.document_id, '')}" for d in docs
        )
        package_digest = sha256_hex(pkg_material.encode("utf-8"))

        reason_codes = list(dict.fromkeys(reason_codes))

        return SubmissionPackageSemanticsResult(
            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
            analysis_id=analysis_id,
            package_id=package.package_id,
            matter_id=package.matter_id,
            application_type=app_type,
            package_profile=package_profile,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(reason_codes),
            warnings=tuple(dict.fromkeys(warnings)),
            application_number=app_no,
            inventory=tuple(inventory),
            facts=tuple(final_facts),
            anchors=tuple(anchors),
            receipts=tuple(receipt_evidences),
            renderings=tuple(rendering_evidences),
            discrepancies=tuple(discrepancies),
            candidate_associations=tuple(candidates[: self.bounds.max_candidates]),
            admission_receipts=tuple(admission_receipts),
            spans=tuple(spans[: self.bounds.max_spans]),
            document_ids=tuple(d.document_id for d in docs),
            labels=dict(package.labels),
            ruleset_versions={
                "semantics_v2": SEMANTICS_V2_RULESET_VERSION,
                "interface": SEMANTICS_V2_INTERFACE,
            },
            package_digest=package_digest,
            retained=True,
        )

    # --- helpers ---

    def _empty_result(
        self,
        *,
        analysis_id: str,
        package: SubmissionPackageInput,
        classification: DisclosureClassification,
        app_type: ApplicationType,
        reason_codes: list[str],
    ) -> SubmissionPackageSemanticsResult:
        disposition = PackageDisposition.MALFORMED
        review = ReviewState.REQUIRED
        if requires_quarantine(classification):
            disposition = PackageDisposition.QUARANTINE
        return SubmissionPackageSemanticsResult(
            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
            analysis_id=analysis_id,
            package_id=package.package_id,
            matter_id=package.matter_id,
            application_type=app_type,
            package_profile=PackageProfile.UNKNOWN,
            disposition=disposition,
            review_state=review,
            classification=classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=(),
            application_number=package.expected_application_number,
            inventory=(),
            facts=(),
            anchors=(),
            receipts=(),
            renderings=(),
            discrepancies=(),
            candidate_associations=(),
            admission_receipts=(),
            spans=(),
            document_ids=(),
            labels=dict(package.labels),
            ruleset_versions={
                "semantics_v2": SEMANTICS_V2_RULESET_VERSION,
                "interface": SEMANTICS_V2_INTERFACE,
            },
            package_digest=sha256_hex(package.package_id.encode("utf-8")),
            retained=True,
        )

    def _make_fact(
        self,
        *,
        fact_id: str,
        kind: FactKind,
        document_id: str,
        surface: str,
        anchor_ids: tuple[str, ...],
        origin: FieldOrigin,
        confidence: float | None,
        normalized: str | None = None,
        claim_tokens: tuple[str, ...] = (),
        citation_keys: tuple[str, ...] = (),
        related_document_ids: tuple[str, ...] = (),
        labels: Mapping[str, str] | None = None,
        page_indices: tuple[int, ...] = (),
    ) -> NormalizedFact:
        surface_capped = surface if len(surface) <= 8000 else surface[:8000]
        return NormalizedFact(
            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
            fact_id=fact_id,
            kind=kind,
            admission=AdmissionState.CANDIDATE,
            origin=origin,
            document_id=document_id,
            anchor_ids=anchor_ids,
            text_digest=_text_digest(surface_capped),
            surface_text=surface_capped,
            confidence=confidence,
            normalized_value=normalized,
            claim_tokens=claim_tokens,
            citation_keys=citation_keys,
            related_document_ids=related_document_ids,
            labels=labels or {},
            admission_receipt_id=None,
            review_state=ReviewState.PENDING,
            page_indices=page_indices,
        )

    def _fact_kind_for_structured_path(
        self, path: str, role: DocumentRole
    ) -> FactKind:
        pl = path.lower()
        if "amount" in pl or "fee" in pl or "payment" in pl:
            return FactKind.FEE_ASSERTION
        if "receipt" in pl or "ack" in pl:
            return FactKind.RECEIPT
        if role is DocumentRole.PAYMENT_RECEIPT:
            return FactKind.FEE_ASSERTION
        if role is DocumentRole.ELECTRONIC_SUBMISSION_RECEIPT:
            return FactKind.RECEIPT
        return FactKind.OTHER

    def _build_inventory(
        self,
        *,
        analysis_id: str,
        docs: Sequence[PackageDocumentInput],
        content_digests: Mapping[str, str],
        expected_roles: Sequence[str],
        cover_anchor_by_doc: Mapping[str, str],
    ) -> tuple[list[InventoryEntry], list[DiscrepancyRecord]]:
        inventory: list[InventoryEntry] = []
        discrepancies: list[DiscrepancyRecord] = []
        role_counts: dict[DocumentRole, list[str]] = {}

        for doc in docs:
            role = (
                doc.role
                if isinstance(doc.role, DocumentRole)
                else DocumentRole(str(doc.role))
            )
            inv_role = doc.inventory_role or role
            if not isinstance(inv_role, DocumentRole):
                inv_role = DocumentRole(str(inv_role))
            inv_labels: dict[str, str] = {"content_role": role.value}
            if doc.filename_hint:
                inv_labels["filename_hint"] = doc.filename_hint[:64]
            inventory.append(
                InventoryEntry(
                    schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                    entry_id=self._id_factory(),
                    document_id=doc.document_id,
                    role=inv_role,
                    source="observed",
                    present=True,
                    content_digest=content_digests.get(doc.document_id),
                    labels=inv_labels,
                )
            )
            role_counts.setdefault(role, []).append(doc.document_id)
            # Inventory vs content role mismatch.
            if inv_role is not role:
                discrepancies.append(
                    DiscrepancyRecord(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        discrepancy_id=self._id_factory(),
                        kind=DiscrepancyKind.INVENTORY_EXTRA,
                        message_code="inventory_role_content_mismatch",
                        document_ids=(doc.document_id,),
                        fact_ids=(),
                        labels={
                            "inventory_role": inv_role.value,
                            "content_role": role.value,
                        },
                    )
                )

        for role, ids in role_counts.items():
            if len(ids) > 1 and role not in (
                DocumentRole.ATTACHMENT,
                DocumentRole.OTHER,
                DocumentRole.SPLIT_PDF,
            ):
                discrepancies.append(
                    DiscrepancyRecord(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        discrepancy_id=self._id_factory(),
                        kind=DiscrepancyKind.INVENTORY_DUPLICATE,
                        message_code=f"duplicate_role:{role.value}",
                        document_ids=tuple(ids),
                        fact_ids=(),
                    )
                )

        observed_roles = {e.role.value for e in inventory}
        for expected in expected_roles:
            if expected not in observed_roles:
                discrepancies.append(
                    DiscrepancyRecord(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        discrepancy_id=self._id_factory(),
                        kind=DiscrepancyKind.INVENTORY_MISSING,
                        message_code=f"missing_expected_role:{expected}",
                        document_ids=(),
                        fact_ids=(),
                        labels={"expected_role": expected},
                    )
                )
                inventory.append(
                    InventoryEntry(
                        schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                        entry_id=self._id_factory(),
                        document_id=f"missing:{expected}",
                        role=DocumentRole(expected)
                        if expected in {r.value for r in DocumentRole}
                        else DocumentRole.UNKNOWN,
                        source="declared",
                        present=False,
                        content_digest=None,
                        labels={"expected": "true"},
                    )
                )

        return inventory, discrepancies

    def _extract_text_facts(
        self,
        *,
        doc_id: str,
        role: DocumentRole,
        text: str,
        cover_anchor_id: str,
        analysis_id: str,
        anchors: list[ProvenanceAnchor],
        span_texts: dict[str, str],
        spans: list[ExtractedSpan],
    ) -> list[NormalizedFact]:
        facts: list[NormalizedFact] = []
        pages = (0,)

        def add(
            kind: FactKind,
            surface: str,
            *,
            confidence: float,
            origin: FieldOrigin = FieldOrigin.DETERMINISTIC_RULE,
            normalized: str | None = None,
            claim_tokens: tuple[str, ...] = (),
            citation_keys: tuple[str, ...] = (),
            char_start: int | None = None,
            char_end: int | None = None,
            labels: Mapping[str, str] | None = None,
        ) -> None:
            # Mint a tighter span anchor when char range known.
            anchor_id = cover_anchor_id
            if char_start is not None and char_end is not None:
                sid = f"span:{analysis_id}:{doc_id}:{kind.value}:{char_start}"
                if sid not in {s.span_id for s in spans}:
                    span = ExtractedSpan(
                        schema_version=CONTRACTS_SCHEMA_VERSION,
                        span_id=sid,
                        artifact_id=doc_id,
                        page_index=0,
                        char_start=char_start,
                        char_end=char_end,
                        bbox=None,
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=char_start,
                        confidence=confidence,
                        text_digest=_text_digest(surface),
                        image_digest=None,
                        classification=DisclosureClassification.PUBLIC_USER,
                    )
                    spans.append(span)
                    span_texts[sid] = surface
                aid = f"anc:{analysis_id}:{doc_id}:{kind.value}:{char_start}"
                if aid not in {a.anchor_id for a in anchors}:
                    anchors.append(
                        ProvenanceAnchor(
                            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                            anchor_id=aid,
                            kind=AnchorKind.DOCUMENT_PAGE_SPAN,
                            document_id=doc_id,
                            page_index=0,
                            span_id=sid,
                            char_start=char_start,
                            char_end=char_end,
                        )
                    )
                anchor_id = aid
            facts.append(
                self._make_fact(
                    fact_id=self._id_factory(),
                    kind=kind,
                    document_id=doc_id,
                    surface=surface,
                    anchor_ids=(anchor_id,),
                    origin=origin,
                    confidence=confidence,
                    normalized=normalized,
                    claim_tokens=claim_tokens,
                    citation_keys=citation_keys,
                    labels=labels,
                    page_indices=pages,
                )
            )

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
                FactKind.BIBLIOGRAPHIC,
                m.group(0),
                confidence=0.95,
                origin=FieldOrigin.DETERMINISTIC_RULE,
                normalized=display,
                char_start=m.start(),
                char_end=m.end(),
                labels={"field": "application_number"},
            )

        for m in _CONFIRMATION_RE.finditer(text):
            add(
                FactKind.BIBLIOGRAPHIC,
                m.group(0),
                confidence=0.9,
                normalized=m.group("conf"),
                char_start=m.start(),
                char_end=m.end(),
                labels={"field": "confirmation_number"},
            )

        for m in _DOCKET_RE.finditer(text):
            add(
                FactKind.BIBLIOGRAPHIC,
                m.group(0),
                confidence=0.85,
                normalized=m.group("docket"),
                char_start=m.start(),
                char_end=m.end(),
                labels={"field": "attorney_docket"},
            )

        for m in _ADS_RE.finditer(text):
            add(
                FactKind.ADS_FIELD,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _BENEFIT_RE.finditer(text):
            add(
                FactKind.BENEFIT_CLAIM,
                m.group(0)[:500],
                confidence=0.8,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _CLAIM_RE.finditer(text):
            num = m.group("num")
            status = m.group("status")
            add(
                FactKind.CLAIM,
                m.group(0)[:500],
                confidence=0.9,
                normalized=num,
                claim_tokens=(num,),
                char_start=m.start(),
                char_end=min(m.end(), m.start() + 500),
                labels={"claim_status": (status or "unknown").lower()},
            )

        for m in _AMENDMENT_RE.finditer(text):
            add(
                FactKind.AMENDMENT,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _ARGUMENT_MAP_RE.finditer(text):
            surface = m.group(0)[:400]
            cites = tuple(_STATUTORY_RE.findall(surface))
            claim_toks = tuple(re.findall(r"\bclaims?\s+(\d+)", surface, re.I))
            add(
                FactKind.ARGUMENT,
                surface,
                confidence=0.75,
                claim_tokens=claim_toks,
                citation_keys=cites,
                char_start=m.start(),
                char_end=min(m.end(), m.start() + 400),
            )

        if _REMARKS_RE.search(text) and role in (
            DocumentRole.REMARKS,
            DocumentRole.AMENDMENT,
            DocumentRole.OTHER,
        ):
            m = _REMARKS_RE.search(text)
            if m:
                add(
                    FactKind.ARGUMENT,
                    m.group(0),
                    confidence=0.7,
                    char_start=m.start(),
                    char_end=m.end(),
                    labels={"section": "remarks"},
                )

        for m in _SPEC_RE.finditer(text):
            add(
                FactKind.SPECIFICATION,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _DRAWING_RE.finditer(text):
            add(
                FactKind.DRAWING,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _DECLARATION_RE.finditer(text):
            add(
                FactKind.DECLARATION,
                m.group(0),
                confidence=0.9,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _CERTIFICATION_RE.finditer(text):
            add(
                FactKind.CERTIFICATION,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _FORM_RE.finditer(text):
            add(
                FactKind.FORM,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _FEE_RE.finditer(text):
            add(
                FactKind.FEE_ASSERTION,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _SEQUENCE_RE.finditer(text):
            add(
                FactKind.SEQUENCE_LISTING,
                m.group(0),
                confidence=0.9,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _ATTACHMENT_RE.finditer(text):
            add(
                FactKind.ATTACHMENT,
                m.group(0)[:200],
                confidence=0.75,
                char_start=m.start(),
                char_end=min(m.end(), m.start() + 200),
            )

        for m in _REPLACEMENT_PAGE_RE.finditer(text):
            add(
                FactKind.REPLACEMENT_PAGE,
                m.group(0),
                confidence=0.85,
                char_start=m.start(),
                char_end=m.end(),
            )

        for m in _SIGNATURE_RE.finditer(text):
            # Presence only — strip any /s/ material from normalized value.
            add(
                FactKind.SIGNATURE_PRESENCE,
                "signature_present",
                confidence=0.9,
                normalized="present",
                char_start=m.start(),
                char_end=m.end(),
                labels={"presence": "present"},
            )

        # Role-driven soft facts when content cues are thin but role is semantic
        # (still requires span anchor — never filename alone).
        if role is DocumentRole.DRAWINGS and not any(
            f.kind is FactKind.DRAWING for f in facts
        ):
            add(FactKind.DRAWING, "drawings_document", confidence=0.5, labels={"role_soft": "true"})
        if role is DocumentRole.SPECIFICATION and not any(
            f.kind is FactKind.SPECIFICATION for f in facts
        ):
            add(
                FactKind.SPECIFICATION,
                "specification_document",
                confidence=0.5,
                labels={"role_soft": "true"},
            )

        return facts

    def _cross_document_checks(
        self,
        *,
        docs: Sequence[PackageDocumentInput],
        document_texts: Mapping[str, str],
        content_digests: Mapping[str, str],
        expected_app: str | None,
        facts: Sequence[NormalizedFact],
    ) -> list[DiscrepancyRecord]:
        out: list[DiscrepancyRecord] = []
        apps: dict[str, list[str]] = {}
        for doc in docs:
            text = document_texts.get(doc.document_id, "")
            for m in _APPLICATION_NO_RE.finditer(text):
                apps.setdefault(m.group("app"), []).append(doc.document_id)
        if len(apps) > 1:
            out.append(
                DiscrepancyRecord(
                    schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                    discrepancy_id=self._id_factory(),
                    kind=DiscrepancyKind.IDENTIFIER_CONFLICT,
                    message_code="application_number_conflict",
                    document_ids=tuple(
                        dict.fromkeys(i for ids in apps.values() for i in ids)
                    ),
                    fact_ids=(),
                    labels={"values": ",".join(sorted(apps.keys()))[:200]},
                )
            )
        if expected_app:
            found = set(apps.keys())
            if found and expected_app not in found:
                # Also accept normalized forms loosely.
                if not any(expected_app.replace(",", "") in a.replace(",", "") for a in found):
                    out.append(
                        DiscrepancyRecord(
                            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                            discrepancy_id=self._id_factory(),
                            kind=DiscrepancyKind.IDENTIFIER_CONFLICT,
                            message_code="expected_application_number_mismatch",
                            document_ids=tuple(
                                dict.fromkeys(i for ids in apps.values() for i in ids)
                            ),
                            fact_ids=(),
                            labels={
                                "expected": expected_app,
                                "found": ",".join(sorted(found))[:200],
                            },
                        )
                    )

        # DOCX vs converted PDF content divergence.
        docx_ids = [
            d.document_id
            for d in docs
            if (
                (d.role if isinstance(d.role, DocumentRole) else DocumentRole(str(d.role)))
                is DocumentRole.SUBMITTED_DOCX
            )
            or (
                d.rendering_kind
                and str(d.rendering_kind) == RenderingKind.SUBMITTED_DOCX.value
            )
        ]
        pdf_ids = [
            d.document_id
            for d in docs
            if (
                (d.role if isinstance(d.role, DocumentRole) else DocumentRole(str(d.role)))
                is DocumentRole.CONVERTED_PDF
            )
            or (
                d.rendering_kind
                and str(d.rendering_kind) == RenderingKind.CONVERTED_PDF.value
            )
        ]
        for did in docx_ids:
            for pid in pdf_ids:
                if content_digests.get(did) != content_digests.get(pid):
                    out.append(
                        DiscrepancyRecord(
                            schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                            discrepancy_id=self._id_factory(),
                            kind=DiscrepancyKind.RENDERING_DIVERGENCE,
                            message_code="docx_pdf_content_divergence",
                            document_ids=(did, pid),
                            fact_ids=(),
                            labels={
                                "docx_digest": content_digests.get(did, "")[:16],
                                "pdf_digest": content_digests.get(pid, "")[:16],
                            },
                        )
                    )
                    # Also internal content mismatch if claim-like lines differ.
                    dt = _normalize_ws(document_texts.get(did, ""))
                    pt = _normalize_ws(document_texts.get(pid, ""))
                    if dt and pt and dt != pt:
                        out.append(
                            DiscrepancyRecord(
                                schema_version=SEMANTICS_V2_SCHEMA_VERSION,
                                discrepancy_id=self._id_factory(),
                                kind=DiscrepancyKind.CONTENT_MISMATCH,
                                message_code="internal_content_mismatch",
                                document_ids=(did, pid),
                                fact_ids=(),
                            )
                        )
        return out

    def _infer_profile(
        self,
        *,
        docs: Sequence[PackageDocumentInput],
        discrepancies: Sequence[DiscrepancyRecord],
        noisy: bool,
        conversion: bool,
        inventory: Sequence[InventoryEntry],
        app_type: ApplicationType,
    ) -> PackageProfile:
        kinds = {d.kind for d in discrepancies}
        if DiscrepancyKind.INVENTORY_DUPLICATE in kinds:
            return PackageProfile.DUPLICATE
        # Conversion packages routinely diverge DOCX↔PDF; that is the conversion
        # profile, not a generic inconsistency.
        if conversion or DiscrepancyKind.CONVERSION_WARNING in kinds:
            return PackageProfile.CONVERSION_WARNING
        if noisy:
            return PackageProfile.SCANNED
        if kinds & {
            DiscrepancyKind.CONTENT_MISMATCH,
            DiscrepancyKind.IDENTIFIER_CONFLICT,
            DiscrepancyKind.RENDERING_DIVERGENCE,
        }:
            return PackageProfile.INCONSISTENT
        if DiscrepancyKind.INVENTORY_MISSING in kinds:
            return PackageProfile.PARTIAL
        roles = {
            (
                d.role
                if isinstance(d.role, DocumentRole)
                else DocumentRole(str(d.role))
            )
            for d in docs
        }
        if app_type is ApplicationType.UTILITY and _UTILITY_CORE_ROLES <= roles:
            return PackageProfile.COMPLETE
        if len(docs) >= 4 and DocumentRole.CLAIMS in roles:
            return PackageProfile.COMPLETE
        if len(docs) <= 2 or DocumentRole.CLAIMS not in roles:
            return PackageProfile.PARTIAL
        return PackageProfile.COMPLETE

    def _disposition(
        self,
        *,
        classification: DisclosureClassification,
        discrepancies: Sequence[DiscrepancyRecord],
        final_facts: Sequence[NormalizedFact],
        noisy: bool,
        profile: PackageProfile,
        candidates: Sequence[CandidateAssociation],
    ) -> tuple[PackageDisposition, ReviewState]:
        if requires_quarantine(classification):
            return PackageDisposition.QUARANTINE, ReviewState.REQUIRED
        if profile in (
            PackageProfile.INCONSISTENT,
            PackageProfile.DUPLICATE,
            PackageProfile.SCANNED,
            PackageProfile.CONVERSION_WARNING,
        ):
            return PackageDisposition.REVIEW, ReviewState.REQUIRED
        if any(
            d.kind
            in (
                DiscrepancyKind.IDENTIFIER_CONFLICT,
                DiscrepancyKind.CONTENT_MISMATCH,
                DiscrepancyKind.RECEIPT_HASH_COLLISION,
            )
            for d in discrepancies
        ):
            return PackageDisposition.REVIEW, ReviewState.REQUIRED
        if noisy:
            return PackageDisposition.REVIEW, ReviewState.REQUIRED
        if profile is PackageProfile.PARTIAL:
            return PackageDisposition.PARTIAL, ReviewState.PENDING
        if candidates:
            # Candidates held but package may still be analyzed.
            return PackageDisposition.ANALYZED, ReviewState.PENDING
        if final_facts:
            return PackageDisposition.ANALYZED, ReviewState.NOT_REQUIRED
        return PackageDisposition.REVIEW, ReviewState.REQUIRED


def extract_submission_package_semantics_v2(
    package: SubmissionPackageInput,
    *,
    id_factory: Callable[[], str] | None = None,
    bounds: SemanticsBounds | None = None,
) -> SubmissionPackageSemanticsResult:
    """Convenience entrypoint for package semantics v2 analysis."""
    return SubmissionPackageSemanticsV2(
        id_factory=id_factory, bounds=bounds
    ).analyze(package)


__all__ = [
    "SEMANTICS_V2_SCHEMA_VERSION",
    "SEMANTICS_V2_INTERFACE",
    "SEMANTICS_V2_RULESET_VERSION",
    "RECEIPT_EFFECT_CODES",
    "RENDERING_EFFECT_CODES",
    "AdmissionReceipt",
    "AdmissionState",
    "AnchorKind",
    "ApplicationType",
    "CandidateAssociation",
    "DiscrepancyKind",
    "DiscrepancyRecord",
    "DocumentRole",
    "FactKind",
    "FieldOrigin",
    "InventoryEntry",
    "ModelAssociationInput",
    "NormalizedFact",
    "PackageDisposition",
    "PackageDocumentInput",
    "PackageProfile",
    "PackageReasonCode",
    "ProvenanceAnchor",
    "ReceiptEvidence",
    "ReceiptKind",
    "RenderingEvidence",
    "RenderingKind",
    "SemanticsBounds",
    "SubmissionPackageInput",
    "SubmissionPackageSemanticsResult",
    "SubmissionPackageSemanticsV2",
    "SubmissionPackageSemanticsV2Error",
    "admit_normalized_fact",
    "detect_noisy_scan",
    "detect_receipt_kind",
    "extract_submission_package_semantics_v2",
    "receipt_effect_code",
    "rendering_effect_code",
    "sha256_hex",
]
