"""USPTO artifact type and authority-role classification (PATLAW-030).

Classifies file-wrapper and filing artifacts before extraction/dispatch:

* document kinds (office actions, notices, submissions, DOCX/PDF conversions,
  declarations, forms, acknowledgements, payment receipts, citations, unknown);
* authoritative / derivative / supplemental roles with confidence, reasons, and
  source channels;
* conflict gates for MIME vs description vs content magic, and wrong matter ID.

Unknown artifacts are retained with an explicit ``unknown`` kind and review /
quarantine disposition — never silently dropped.

This module owns domain semantics only. Generic PDF parsing and disclosure
privacy policy remain inputs (see ``privacy`` / ``artifact_manifest``).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.identifiers import (
    IdentifierStatus,
    normalize_application_number,
)

DOCUMENT_CLASSIFIER_SCHEMA_VERSION: Final = "uspto.document-classifier.v1"
DOCUMENT_CLASSIFIER_INTERFACE: Final = "DocumentClassifier@1"

# Soft media probes (admission only — no full parse).
_PDF_MAGIC: Final = b"%PDF"
_ZIP_MAGIC: Final = b"PK"
_XML_PREFIXES: Final = (b"<?xml", b"<")
_HTML_PREFIXES: Final = (b"<!doctype html", b"<html")

# Compact application-number digits for matter-id comparison.
_DIGITS_RE = re.compile(r"\D+")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class UsptoDocumentKind(str, Enum):
    """Semantic document family for USPTO artifacts.

    ``UNKNOWN`` is first-class: retained and routed to review, never discarded.
    """

    OFFICE_ACTION = "office_action"
    NOTICE = "notice"
    SUBMISSION = "submission"
    DOCX_ORIGINAL = "docx_original"
    PDF_CONVERSION = "pdf_conversion"
    DECLARATION = "declaration"
    FORM = "form"
    ACKNOWLEDGEMENT = "acknowledgement"
    PAYMENT_RECEIPT = "payment_receipt"
    CITATION = "citation"
    UNKNOWN = "unknown"


class ArtifactAuthorityRole(str, Enum):
    """How an artifact relates to the matter evidence set.

    * ``authoritative`` — original government or filer instrument of record
    * ``derivative`` — conversion/render derived from an authoritative parent
    * ``supplemental`` — supporting/reference material (e.g. cited NPL)
    * ``unknown`` — role not established; review required
    """

    AUTHORITATIVE = "authoritative"
    DERIVATIVE = "derivative"
    SUPPLEMENTAL = "supplemental"
    UNKNOWN = "unknown"


class ClassificationDisposition(str, Enum):
    """Pipeline disposition after classification."""

    CLASSIFIED = "classified"
    REVIEW = "review"
    QUARANTINE = "quarantine"


class ClassificationSource(str, Enum):
    """Evidence channel that contributed to the classification."""

    DOCUMENT_CODE = "document_code"
    DESCRIPTION = "description"
    DECLARED_MIME = "declared_mime"
    CONTENT_MAGIC = "content_magic"
    CONTENT_TEXT = "content_text"
    FILENAME = "filename"
    PARENT_LINK = "parent_link"
    MATTER_ID = "matter_id"
    DIRECTION = "direction"
    LABEL = "label"
    DEFAULT = "default"


# Machine-readable reason codes (stable for tests and quarantine consumers).
class ClassificationReasonCode(str, Enum):
    MATCHED_DOCUMENT_CODE = "matched_document_code"
    MATCHED_DESCRIPTION = "matched_description"
    MATCHED_CONTENT_TEXT = "matched_content_text"
    MATCHED_FILENAME = "matched_filename"
    MATCHED_MIME = "matched_mime"
    DERIVATIVE_FROM_PARENT = "derivative_from_parent"
    CONVERSION_PAIR = "conversion_pair"
    SUPPLEMENTAL_CITATION = "supplemental_citation"
    UNKNOWN_ARTIFACT = "unknown_artifact"
    MIME_CONTENT_CONFLICT = "mime_content_conflict"
    DESCRIPTION_CONTENT_CONFLICT = "description_content_conflict"
    DESCRIPTION_MIME_CONFLICT = "description_mime_conflict"
    DOCUMENT_CODE_DESCRIPTION_CONFLICT = "document_code_description_conflict"
    MATTER_ID_MISMATCH = "matter_id_mismatch"
    MISSING_SIGNALS = "missing_signals"
    LOW_CONFIDENCE = "low_confidence"
    EXPLICIT_LABEL = "explicit_label"


# Document-code → kind (uppercase codes). Common ODP / Patent Center codes.
_CODE_TO_KIND: Final[Mapping[str, UsptoDocumentKind]] = MappingProxyType(
    {
        # Office actions
        "CTNF": UsptoDocumentKind.OFFICE_ACTION,
        "CTFR": UsptoDocumentKind.OFFICE_ACTION,
        "CTMS": UsptoDocumentKind.OFFICE_ACTION,
        "CTAV": UsptoDocumentKind.OFFICE_ACTION,
        "CTRS": UsptoDocumentKind.OFFICE_ACTION,
        "EXIN": UsptoDocumentKind.OFFICE_ACTION,
        "OA": UsptoDocumentKind.OFFICE_ACTION,
        "OA.EMAIL": UsptoDocumentKind.OFFICE_ACTION,
        # Notices
        "NOA": UsptoDocumentKind.NOTICE,
        "NOAR": UsptoDocumentKind.NOTICE,
        "NRES": UsptoDocumentKind.NOTICE,
        "NTC": UsptoDocumentKind.NOTICE,
        "ABN": UsptoDocumentKind.NOTICE,
        # Submissions / application parts
        "CLM": UsptoDocumentKind.SUBMISSION,
        "SPEC": UsptoDocumentKind.SUBMISSION,
        "ABST": UsptoDocumentKind.SUBMISSION,
        "DRW": UsptoDocumentKind.SUBMISSION,
        "DRW.": UsptoDocumentKind.SUBMISSION,
        "APPE": UsptoDocumentKind.SUBMISSION,
        "REM": UsptoDocumentKind.SUBMISSION,
        "AMSB": UsptoDocumentKind.SUBMISSION,
        "A...": UsptoDocumentKind.SUBMISSION,
        # DOCX original / converted PDF markers
        "APP.FILE.DOCX": UsptoDocumentKind.DOCX_ORIGINAL,
        "APP.FILE.PDF": UsptoDocumentKind.PDF_CONVERSION,
        "APPDOX": UsptoDocumentKind.DOCX_ORIGINAL,
        "APP.PDF": UsptoDocumentKind.PDF_CONVERSION,
        # Declarations / oaths
        "OATH": UsptoDocumentKind.DECLARATION,
        "DECL": UsptoDocumentKind.DECLARATION,
        "ADS": UsptoDocumentKind.FORM,
        # Forms
        "SB08": UsptoDocumentKind.FORM,
        "SB16": UsptoDocumentKind.FORM,
        "PTO/SB/08": UsptoDocumentKind.FORM,
        "WFEE": UsptoDocumentKind.PAYMENT_RECEIPT,
        "FEE": UsptoDocumentKind.PAYMENT_RECEIPT,
        "N417": UsptoDocumentKind.ACKNOWLEDGEMENT,
        "APP.FILE.REC": UsptoDocumentKind.ACKNOWLEDGEMENT,
        "EAR": UsptoDocumentKind.ACKNOWLEDGEMENT,
        "ACK": UsptoDocumentKind.ACKNOWLEDGEMENT,
        # Citations / IDS / NPL
        "IDS": UsptoDocumentKind.CITATION,
        "NPL": UsptoDocumentKind.CITATION,
        "892": UsptoDocumentKind.CITATION,
        "1449": UsptoDocumentKind.CITATION,
        "SRNT": UsptoDocumentKind.CITATION,
    }
)

# Description / content keyword → kind (lowercase substring match).
_DESCRIPTION_KIND_RULES: Final[tuple[tuple[tuple[str, ...], UsptoDocumentKind], ...]] = (
    (
        (
            "non-final rejection",
            "final rejection",
            "office action",
            "nonfinal rejection",
            "examiner",
            "ex parte",
        ),
        UsptoDocumentKind.OFFICE_ACTION,
    ),
    (
        (
            "notice of allowance",
            "notice of abandon",
            "notice of",
            "missing parts",
            "issue notification",
        ),
        UsptoDocumentKind.NOTICE,
    ),
    (
        (
            "electronic acknowledgement",
            "acknowledgment receipt",
            "acknowledgement receipt",
            "filing receipt",
            "e-filing acknowledgement",
        ),
        UsptoDocumentKind.ACKNOWLEDGEMENT,
    ),
    (
        ("payment receipt", "fee payment", "fee receipt", "credit card payment"),
        UsptoDocumentKind.PAYMENT_RECEIPT,
    ),
    (
        ("declaration", "oath or declaration", "inventor declaration", "37 cfr 1.63"),
        UsptoDocumentKind.DECLARATION,
    ),
    (
        ("information disclosure", "non-patent literature", "cited reference", "form 892"),
        UsptoDocumentKind.CITATION,
    ),
    (
        ("application data sheet", "form pto", "transmittal form", "sb/08", "sb08"),
        UsptoDocumentKind.FORM,
    ),
    (
        (
            "converted pdf",
            "uspto-generated pdf",
            "pdf conversion",
            "docx converted",
            "rendering of docx",
        ),
        UsptoDocumentKind.PDF_CONVERSION,
    ),
    (
        ("original docx", "authoritative docx", "docx application body", "filed docx"),
        UsptoDocumentKind.DOCX_ORIGINAL,
    ),
    (
        (
            "claims",
            "specification",
            "abstract",
            "drawings",
            "amendment",
            "remarks",
            "applicant response",
            "response to office action",
            "preliminary amendment",
        ),
        UsptoDocumentKind.SUBMISSION,
    ),
)

# Content-text cues that conflict with certain declared kinds.
_CONTENT_KIND_CUES: Final[tuple[tuple[tuple[str, ...], UsptoDocumentKind], ...]] = (
    (
        ("this office action", "claim rejection", "35 u.s.c. § 103", "35 u.s.c. 103"),
        UsptoDocumentKind.OFFICE_ACTION,
    ),
    (
        ("electronic acknowledgement receipt", "application number:", "receipt date:"),
        UsptoDocumentKind.ACKNOWLEDGEMENT,
    ),
    (
        ("payment of fees", "amount paid", "fee code"),
        UsptoDocumentKind.PAYMENT_RECEIPT,
    ),
    (
        ("i hereby declare", "declare under penalty", "declaration under 37"),
        UsptoDocumentKind.DECLARATION,
    ),
)

# Kinds whose typical media types are constrained (for conflict checks).
_KIND_EXPECTED_MEDIA: Final[Mapping[UsptoDocumentKind, frozenset[str]]] = MappingProxyType(
    {
        UsptoDocumentKind.DOCX_ORIGINAL: frozenset(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/zip",
            }
        ),
        UsptoDocumentKind.PDF_CONVERSION: frozenset({"application/pdf"}),
        UsptoDocumentKind.OFFICE_ACTION: frozenset(
            {"application/pdf", "application/xml", "text/html", "text/plain"}
        ),
        UsptoDocumentKind.ACKNOWLEDGEMENT: frozenset(
            {"application/pdf", "text/html", "text/plain", "application/xml"}
        ),
        UsptoDocumentKind.PAYMENT_RECEIPT: frozenset(
            {"application/pdf", "text/html", "text/plain"}
        ),
    }
)

_MIME_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "pdf": "application/pdf",
        "application/pdf": "application/pdf",
        "xml": "application/xml",
        "application/xml": "application/xml",
        "text/xml": "application/xml",
        "json": "application/json",
        "application/json": "application/json",
        "txt": "text/plain",
        "text/plain": "text/plain",
        "html": "text/html",
        "text/html": "text/html",
        "zip": "application/zip",
        "application/zip": "application/zip",
        "msword": "application/msword",
        "application/msword": "application/msword",
        "docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "application/octet-stream": "application/octet-stream",
    }
)

# Confidence floors / ceilings.
_CONF_CODE: Final = 0.92
_CONF_DESCRIPTION: Final = 0.78
_CONF_CONTENT: Final = 0.70
_CONF_FILENAME: Final = 0.55
_CONF_MIME_ONLY: Final = 0.40
_CONF_DEFAULT_UNKNOWN: Final = 0.15
_CONF_CONFLICT_CAP: Final = 0.35
_CONF_REVIEW_THRESHOLD: Final = 0.50


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DocumentClassifierError(ValueError):
    """Raised for invalid classifier inputs or records."""

    def __init__(self, message: str, *, code: str = "classifier_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    number = float(value)
    if number != number or number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0.0, 1.0]")
    return number


def _require_float_01(value: Any, field: str) -> float:
    number = _optional_float_01(value, field)
    if number is None:
        raise ValueError(f"{field} is required")
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


def _normalize_mime(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    # Strip parameters and map identifiers.
    base = raw.split(";", 1)[0].strip()
    if base in _MIME_ALIASES:
        return _MIME_ALIASES[base]
    upper = value.strip().upper()
    if upper in _MIME_ALIASES:
        return _MIME_ALIASES[upper]
    # Bare identifier like "PDF" / "DOCX"
    if upper.lower() in _MIME_ALIASES:
        return _MIME_ALIASES[upper.lower()]
    return base


def detect_media_from_bytes(content: bytes | None) -> str | None:
    """Return a best-effort media type from magic bytes, or None if empty/unknown."""
    if content is None or len(content) == 0:
        return None
    head = content[:16]
    if head.startswith(_PDF_MAGIC):
        return "application/pdf"
    if head.startswith(_ZIP_MAGIC):
        # DOCX is a ZIP package; callers with declared MIME may refine.
        # Probe for word/ document.xml path is out of scope (no full parse).
        return "application/zip"
    lower = content[:256].lstrip().lower()
    if any(lower.startswith(p) for p in _HTML_PREFIXES):
        return "text/html"
    if lower.startswith(b"<?xml") or (
        lower.startswith(b"<") and b"xmlns" in lower[:512]
    ):
        return "application/xml"
    # Printable-ish text
    sample = content[:256]
    if all(32 <= b < 127 or b in (9, 10, 13) for b in sample):
        return "text/plain"
    return "application/octet-stream"


def media_types_compatible(declared: str | None, detected: str | None) -> bool:
    """Return True when declared and detected media agree (or either is missing)."""
    d = _normalize_mime(declared)
    t = _normalize_mime(detected)
    if d is None or t is None:
        return True
    if d == t:
        return True
    # ZIP package may be DOCX; treat as compatible either way.
    docx = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    if {d, t} <= {docx, "application/zip"}:
        return True
    if d == "application/octet-stream" or t == "application/octet-stream":
        return True
    return False


def authority_role_to_relation(role: ArtifactAuthorityRole) -> AuthorityRelation:
    """Map classifier authority role onto :class:`AuthorityRelation` for manifests."""
    if role is ArtifactAuthorityRole.AUTHORITATIVE:
        return AuthorityRelation.AUTHORITATIVE_ORIGINAL
    if role is ArtifactAuthorityRole.DERIVATIVE:
        return AuthorityRelation.DERIVATIVE
    if role is ArtifactAuthorityRole.SUPPLEMENTAL:
        # Supplemental is not a superseding or derived-from link; leave unknown
        # on the manifest relation axis and keep the richer role on the result.
        return AuthorityRelation.UNKNOWN
    return AuthorityRelation.UNKNOWN


def _digits_only(value: str) -> str:
    return _DIGITS_RE.sub("", value)


def normalize_matter_key(value: str | None) -> str | None:
    """Normalize a matter / application id for equality checks.

    Uses identifier normalization when the value looks like an application
    number; otherwise falls back to digit-only comparison.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    # Strip common prefixes like "matter:" / "app:"
    for prefix in ("matter:", "app:", "application:", "uspto:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    try:
        ident = normalize_application_number(text, strict=False)
    except Exception:  # noqa: BLE001 — fail closed to digit compare
        ident = None
    if ident is not None and ident.status is IdentifierStatus.RESOLVED:
        return ident.compact
    digits = _digits_only(text)
    return digits or text.lower()


def _kind_from_document_code(code: str | None) -> UsptoDocumentKind | None:
    if not code:
        return None
    raw = code.strip().upper()
    if not raw:
        return None
    if raw in _CODE_TO_KIND:
        return _CODE_TO_KIND[raw]
    # Prefix families: CT*, N### notice-ish, SB*
    if raw.startswith("CT") and len(raw) <= 6:
        return UsptoDocumentKind.OFFICE_ACTION
    if raw.startswith("SB") or raw.startswith("PTO/"):
        return UsptoDocumentKind.FORM
    if raw.startswith("N") and raw[1:].isdigit():
        return UsptoDocumentKind.NOTICE
    return None


def _kind_from_text(text: str | None) -> tuple[UsptoDocumentKind | None, str | None]:
    if not text:
        return None, None
    lowered = _WS_RE.sub(" ", text.strip().lower())
    for keywords, kind in _DESCRIPTION_KIND_RULES:
        for kw in keywords:
            if kw in lowered:
                return kind, kw
    return None, None


def _kind_from_content_text(text: str | None) -> tuple[UsptoDocumentKind | None, str | None]:
    if not text:
        return None, None
    lowered = _WS_RE.sub(" ", text.strip().lower())
    # Cap scan size for safety.
    sample = lowered[:8000]
    for keywords, kind in _CONTENT_KIND_CUES:
        for kw in keywords:
            if kw in sample:
                return kind, kw
    # Fall back to description-style rules on content.
    return _kind_from_text(sample)


def _kind_from_filename(name: str | None) -> tuple[UsptoDocumentKind | None, str | None]:
    if not name:
        return None, None
    lowered = name.strip().lower()
    # Longer / more specific cues first (payment_receipt before bare "receipt").
    rules = (
        (("office_action", "office-action", "ctnf", "ctfr", "nonfinal", "final_rej"), UsptoDocumentKind.OFFICE_ACTION),
        (("notice_of_allowance", "noa_", "_noa", "notice_of"), UsptoDocumentKind.NOTICE),
        (("payment_receipt", "fee_receipt", "payment", "wfee"), UsptoDocumentKind.PAYMENT_RECEIPT),
        (("acknowledg", "ack_receipt", "filing_receipt", "n417", "_ear."), UsptoDocumentKind.ACKNOWLEDGEMENT),
        (("declaration", "oath"), UsptoDocumentKind.DECLARATION),
        (("ids", "npl", "citation"), UsptoDocumentKind.CITATION),
        (("converted", "uspto_pdf", "pdf_conversion"), UsptoDocumentKind.PDF_CONVERSION),
        ((".docx", "original_docx"), UsptoDocumentKind.DOCX_ORIGINAL),
        (("claims", "specification", "amendment", "remarks"), UsptoDocumentKind.SUBMISSION),
        (("form_", "sb08", "ads."), UsptoDocumentKind.FORM),
        (("notice",), UsptoDocumentKind.NOTICE),
        (("receipt",), UsptoDocumentKind.ACKNOWLEDGEMENT),
    )
    for keywords, kind in rules:
        for kw in keywords:
            if kw in lowered:
                return kind, kw
    return None, None


def _default_role_for_kind(kind: UsptoDocumentKind) -> ArtifactAuthorityRole:
    if kind is UsptoDocumentKind.PDF_CONVERSION:
        return ArtifactAuthorityRole.DERIVATIVE
    if kind is UsptoDocumentKind.CITATION:
        return ArtifactAuthorityRole.SUPPLEMENTAL
    if kind is UsptoDocumentKind.UNKNOWN:
        return ArtifactAuthorityRole.UNKNOWN
    # Office actions, notices, submissions, DOCX originals, declarations,
    # forms, acknowledgements, payment receipts are authoritative instruments.
    return ArtifactAuthorityRole.AUTHORITATIVE


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentClassificationInput:
    """Inputs available before / during admission for classification.

    All fields are optional so partial inventory metadata can still be
    classified. Empty / missing signals lower confidence; they never drop the
    artifact.
    """

    artifact_id: str | None = None
    document_code: str | None = None
    document_description: str | None = None
    declared_mime: str | None = None
    mime_type_identifier: str | None = None
    content_type: str | None = None
    content_bytes: bytes | None = None
    content_preview: str | None = None
    filename: str | None = None
    expected_matter_id: str | None = None
    observed_matter_id: str | None = None
    parent_artifact_ids: tuple[str, ...] = ()
    direction_category: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    explicit_kind: str | None = None
    explicit_authority_role: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _optional_str(self.artifact_id, "artifact_id", max_len=256)
        )
        object.__setattr__(
            self,
            "document_code",
            _optional_str(self.document_code, "document_code", max_len=64),
        )
        object.__setattr__(
            self,
            "document_description",
            _optional_str(self.document_description, "document_description", max_len=512),
        )
        object.__setattr__(
            self,
            "declared_mime",
            _optional_str(self.declared_mime, "declared_mime", max_len=256),
        )
        object.__setattr__(
            self,
            "mime_type_identifier",
            _optional_str(self.mime_type_identifier, "mime_type_identifier", max_len=64),
        )
        object.__setattr__(
            self,
            "content_type",
            _optional_str(self.content_type, "content_type", max_len=256),
        )
        if self.content_bytes is not None and not isinstance(self.content_bytes, (bytes, bytearray)):
            raise TypeError("content_bytes must be bytes or None")
        if isinstance(self.content_bytes, bytearray):
            object.__setattr__(self, "content_bytes", bytes(self.content_bytes))
        object.__setattr__(
            self,
            "content_preview",
            _optional_str(self.content_preview, "content_preview", max_len=16000),
        )
        object.__setattr__(
            self, "filename", _optional_str(self.filename, "filename", max_len=512)
        )
        object.__setattr__(
            self,
            "expected_matter_id",
            _optional_str(self.expected_matter_id, "expected_matter_id", max_len=128),
        )
        object.__setattr__(
            self,
            "observed_matter_id",
            _optional_str(self.observed_matter_id, "observed_matter_id", max_len=128),
        )
        object.__setattr__(
            self,
            "parent_artifact_ids",
            _tuple_of_str(self.parent_artifact_ids, "parent_artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "direction_category",
            _optional_str(self.direction_category, "direction_category", max_len=64),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels", max_items=32))
        object.__setattr__(
            self,
            "explicit_kind",
            _optional_str(self.explicit_kind, "explicit_kind", max_len=64),
        )
        object.__setattr__(
            self,
            "explicit_authority_role",
            _optional_str(self.explicit_authority_role, "explicit_authority_role", max_len=64),
        )


@dataclass(frozen=True, slots=True)
class DocumentClassification:
    """Classification outcome with confidence, reasons, and source channels.

    ``retained`` is always True for admitted classifier outputs: unknown and
    conflicting artifacts stay in the evidence set for quarantine/review.
    """

    schema_version: str
    document_kind: UsptoDocumentKind
    authority_role: ArtifactAuthorityRole
    authority_relation: AuthorityRelation
    confidence: float
    reasons: tuple[str, ...]
    sources: tuple[str, ...]
    disposition: ClassificationDisposition
    review_state: ReviewState
    reason_codes: tuple[str, ...]
    document_code: str | None
    declared_mime: str | None
    detected_media: str | None
    expected_matter_id: str | None
    observed_matter_id: str | None
    parent_artifact_ids: tuple[str, ...]
    related_artifact_ids: tuple[str, ...]
    labels: Mapping[str, str]
    retained: bool
    classification_id: str
    artifact_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_CLASSIFIER_SCHEMA_VERSION:
            raise ValueError(
                "DocumentClassification.schema_version must be "
                f"{DOCUMENT_CLASSIFIER_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self,
            "document_kind",
            _coerce_enum(UsptoDocumentKind, self.document_kind, "document_kind"),
        )
        object.__setattr__(
            self,
            "authority_role",
            _coerce_enum(ArtifactAuthorityRole, self.authority_role, "authority_role"),
        )
        object.__setattr__(
            self,
            "authority_relation",
            _coerce_enum(AuthorityRelation, self.authority_relation, "authority_relation"),
        )
        object.__setattr__(
            self, "confidence", _require_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=64)
        )
        object.__setattr__(
            self, "sources", _tuple_of_str(self.sources, "sources", max_items=32)
        )
        if not self.sources:
            raise ValueError("sources must include at least one classification source")
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ClassificationDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "document_code",
            _optional_str(self.document_code, "document_code", max_len=64),
        )
        object.__setattr__(
            self,
            "declared_mime",
            _optional_str(self.declared_mime, "declared_mime", max_len=256),
        )
        object.__setattr__(
            self,
            "detected_media",
            _optional_str(self.detected_media, "detected_media", max_len=256),
        )
        object.__setattr__(
            self,
            "expected_matter_id",
            _optional_str(self.expected_matter_id, "expected_matter_id", max_len=128),
        )
        object.__setattr__(
            self,
            "observed_matter_id",
            _optional_str(self.observed_matter_id, "observed_matter_id", max_len=128),
        )
        object.__setattr__(
            self,
            "parent_artifact_ids",
            _tuple_of_str(self.parent_artifact_ids, "parent_artifact_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "related_artifact_ids",
            _tuple_of_str(self.related_artifact_ids, "related_artifact_ids", max_items=64),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels", max_items=32))
        if not isinstance(self.retained, bool):
            raise TypeError("retained must be bool")
        if not self.retained:
            raise ValueError(
                "classifier must retain artifacts; silent drops are forbidden"
            )
        object.__setattr__(
            self,
            "classification_id",
            _require_str(self.classification_id, "classification_id", max_len=128),
        )
        object.__setattr__(
            self, "artifact_id", _optional_str(self.artifact_id, "artifact_id", max_len=256)
        )

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            ClassificationDisposition.REVIEW,
            ClassificationDisposition.QUARANTINE,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    @property
    def is_quarantined(self) -> bool:
        return self.disposition is ClassificationDisposition.QUARANTINE

    @property
    def is_unknown(self) -> bool:
        return self.document_kind is UsptoDocumentKind.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_relation": self.authority_relation.value,
            "authority_role": self.authority_role.value,
            "classification_id": self.classification_id,
            "confidence": self.confidence,
            "declared_mime": self.declared_mime,
            "detected_media": self.detected_media,
            "disposition": self.disposition.value,
            "document_code": self.document_code,
            "document_kind": self.document_kind.value,
            "expected_matter_id": self.expected_matter_id,
            "labels": dict(self.labels),
            "observed_matter_id": self.observed_matter_id,
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "related_artifact_ids": list(self.related_artifact_ids),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "sources": list(self.sources),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentClassification":
        if not isinstance(value, Mapping):
            raise TypeError("DocumentClassification must be a mapping")
        allowed = frozenset(
            {
                "schema_version",
                "document_kind",
                "authority_role",
                "authority_relation",
                "confidence",
                "reasons",
                "sources",
                "disposition",
                "review_state",
                "reason_codes",
                "document_code",
                "declared_mime",
                "detected_media",
                "expected_matter_id",
                "observed_matter_id",
                "parent_artifact_ids",
                "related_artifact_ids",
                "labels",
                "retained",
                "classification_id",
                "artifact_id",
            }
        )
        extra = sorted(set(value) - allowed)
        if extra:
            raise ValueError(
                f"DocumentClassification has unknown fields: {', '.join(extra)}"
            )
        return cls(
            schema_version=value.get(
                "schema_version", DOCUMENT_CLASSIFIER_SCHEMA_VERSION
            ),
            document_kind=value.get("document_kind", UsptoDocumentKind.UNKNOWN.value),
            authority_role=value.get(
                "authority_role", ArtifactAuthorityRole.UNKNOWN.value
            ),
            authority_relation=value.get(
                "authority_relation", AuthorityRelation.UNKNOWN.value
            ),
            confidence=value.get("confidence", 0.0),
            reasons=tuple(value.get("reasons") or ()),
            sources=tuple(value.get("sources") or ()),
            disposition=value.get(
                "disposition", ClassificationDisposition.REVIEW.value
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            reason_codes=tuple(value.get("reason_codes") or ()),
            document_code=value.get("document_code"),
            declared_mime=value.get("declared_mime"),
            detected_media=value.get("detected_media"),
            expected_matter_id=value.get("expected_matter_id"),
            observed_matter_id=value.get("observed_matter_id"),
            parent_artifact_ids=tuple(value.get("parent_artifact_ids") or ()),
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            labels=value.get("labels") or {},
            retained=bool(value.get("retained", True)),
            classification_id=value.get("classification_id", ""),
            artifact_id=value.get("artifact_id"),
        )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class DocumentClassifier:
    """Classify USPTO artifacts by kind and authority role.

    Deterministic, side-effect-free, and fail-closed: conflicts and unknown
    kinds yield review or quarantine while retaining the artifact.
    """

    def __init__(self, *, id_factory: Any | None = None) -> None:
        self._id_factory = id_factory or (lambda: f"classif:{uuid.uuid4().hex}")

    def classify(
        self,
        value: DocumentClassificationInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> DocumentClassification:
        """Classify one artifact.

        Accepts a :class:`DocumentClassificationInput`, a mapping, or keyword
        arguments matching the input fields.
        """
        inp = self._coerce_input(value, kwargs)
        return self._classify(inp)

    def classify_many(
        self, items: Sequence[DocumentClassificationInput | Mapping[str, Any]]
    ) -> tuple[DocumentClassification, ...]:
        return tuple(self.classify(item) for item in items)

    def link_conversion_pair(
        self,
        *,
        original: DocumentClassification,
        conversion: DocumentClassification,
        original_artifact_id: str,
        conversion_artifact_id: str,
    ) -> tuple[DocumentClassification, DocumentClassification]:
        """Return updated classifications linking DOCX original ↔ PDF conversion.

        The conversion becomes derivative of the original; both records remain
        retained. Does not mutate inputs.
        """
        if not original_artifact_id or not conversion_artifact_id:
            raise DocumentClassifierError(
                "both artifact ids are required to link a conversion pair",
                code="missing_artifact_id",
            )
        orig = DocumentClassification(
            schema_version=original.schema_version,
            document_kind=(
                UsptoDocumentKind.DOCX_ORIGINAL
                if original.document_kind is UsptoDocumentKind.UNKNOWN
                else original.document_kind
            ),
            authority_role=ArtifactAuthorityRole.AUTHORITATIVE,
            authority_relation=AuthorityRelation.AUTHORITATIVE_ORIGINAL,
            confidence=max(original.confidence, 0.85),
            reasons=original.reasons
            + (
                f"linked as authoritative parent of conversion {conversion_artifact_id}",
            ),
            sources=tuple(
                dict.fromkeys(
                    (*original.sources, ClassificationSource.PARENT_LINK.value)
                )
            ),
            disposition=original.disposition
            if original.disposition is not ClassificationDisposition.QUARANTINE
            else ClassificationDisposition.QUARANTINE,
            review_state=original.review_state,
            reason_codes=tuple(
                dict.fromkeys(
                    (
                        *original.reason_codes,
                        ClassificationReasonCode.CONVERSION_PAIR.value,
                    )
                )
            ),
            document_code=original.document_code,
            declared_mime=original.declared_mime,
            detected_media=original.detected_media,
            expected_matter_id=original.expected_matter_id,
            observed_matter_id=original.observed_matter_id,
            parent_artifact_ids=original.parent_artifact_ids,
            related_artifact_ids=tuple(
                dict.fromkeys((*original.related_artifact_ids, conversion_artifact_id))
            ),
            labels=dict(original.labels)
            | {
                "conversion_pair_role": "authoritative_original",
                "paired_artifact_id": conversion_artifact_id,
            },
            retained=True,
            classification_id=original.classification_id,
            artifact_id=original.artifact_id or original_artifact_id,
        )
        conv = DocumentClassification(
            schema_version=conversion.schema_version,
            document_kind=UsptoDocumentKind.PDF_CONVERSION,
            authority_role=ArtifactAuthorityRole.DERIVATIVE,
            authority_relation=AuthorityRelation.DERIVATIVE,
            confidence=max(conversion.confidence, 0.85),
            reasons=conversion.reasons
            + (
                f"derivative conversion of authoritative artifact {original_artifact_id}",
            ),
            sources=tuple(
                dict.fromkeys(
                    (*conversion.sources, ClassificationSource.PARENT_LINK.value)
                )
            ),
            disposition=conversion.disposition
            if conversion.disposition is not ClassificationDisposition.QUARANTINE
            else ClassificationDisposition.QUARANTINE,
            review_state=conversion.review_state,
            reason_codes=tuple(
                dict.fromkeys(
                    (
                        *conversion.reason_codes,
                        ClassificationReasonCode.CONVERSION_PAIR.value,
                        ClassificationReasonCode.DERIVATIVE_FROM_PARENT.value,
                    )
                )
            ),
            document_code=conversion.document_code,
            declared_mime=conversion.declared_mime,
            detected_media=conversion.detected_media,
            expected_matter_id=conversion.expected_matter_id,
            observed_matter_id=conversion.observed_matter_id,
            parent_artifact_ids=tuple(
                dict.fromkeys((*conversion.parent_artifact_ids, original_artifact_id))
            ),
            related_artifact_ids=tuple(
                dict.fromkeys((*conversion.related_artifact_ids, original_artifact_id))
            ),
            labels=dict(conversion.labels)
            | {
                "conversion_pair_role": "derivative_pdf",
                "paired_artifact_id": original_artifact_id,
            },
            retained=True,
            classification_id=conversion.classification_id,
            artifact_id=conversion.artifact_id or conversion_artifact_id,
        )
        return orig, conv

    # -- internals ---------------------------------------------------------

    def _coerce_input(
        self,
        value: DocumentClassificationInput | Mapping[str, Any] | None,
        kwargs: Mapping[str, Any],
    ) -> DocumentClassificationInput:
        if value is None:
            return DocumentClassificationInput(**kwargs)
        if isinstance(value, DocumentClassificationInput):
            if kwargs:
                raise DocumentClassifierError(
                    "cannot mix DocumentClassificationInput with kwargs",
                    code="invalid_input",
                )
            return value
        if isinstance(value, Mapping):
            merged = {**dict(value), **dict(kwargs)}
            # Map alternate keys commonly used by ODP inventory.
            if "documentCode" in merged and "document_code" not in merged:
                merged["document_code"] = merged.pop("documentCode")
            if (
                "documentCodeDescriptionText" in merged
                and "document_description" not in merged
            ):
                merged["document_description"] = merged.pop(
                    "documentCodeDescriptionText"
                )
            if (
                "mimeTypeIdentifier" in merged
                and "mime_type_identifier" not in merged
            ):
                merged["mime_type_identifier"] = merged.pop("mimeTypeIdentifier")
            # Drop unknown keys that are pure inventory noise when building input.
            allowed = {
                f.name for f in DocumentClassificationInput.__dataclass_fields__.values()  # type: ignore[attr-defined]
            }
            filtered = {k: v for k, v in merged.items() if k in allowed}
            return DocumentClassificationInput(**filtered)
        raise TypeError(
            "classify input must be DocumentClassificationInput, mapping, or kwargs"
        )

    def _resolve_declared_mime(self, inp: DocumentClassificationInput) -> str | None:
        for candidate in (
            inp.declared_mime,
            inp.content_type,
            inp.mime_type_identifier,
        ):
            normalized = _normalize_mime(candidate)
            if normalized is not None:
                return normalized
        return None

    def _classify(self, inp: DocumentClassificationInput) -> DocumentClassification:
        reasons: list[str] = []
        reason_codes: list[str] = []
        sources: list[str] = []
        conflicts: list[str] = []

        declared_mime = self._resolve_declared_mime(inp)
        detected_media = detect_media_from_bytes(inp.content_bytes)
        # If ZIP magic and declared DOCX, refine detected to DOCX for labels.
        if (
            detected_media == "application/zip"
            and declared_mime
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            detected_media = declared_mime

        if declared_mime is not None:
            sources.append(ClassificationSource.DECLARED_MIME.value)
        if detected_media is not None and inp.content_bytes is not None:
            sources.append(ClassificationSource.CONTENT_MAGIC.value)

        # --- kind candidates from each channel ---
        kind_code = _kind_from_document_code(inp.document_code)
        if kind_code is not None:
            sources.append(ClassificationSource.DOCUMENT_CODE.value)
            reasons.append(
                f"document_code {inp.document_code!r} maps to {kind_code.value}"
            )
            reason_codes.append(ClassificationReasonCode.MATCHED_DOCUMENT_CODE.value)

        kind_desc, desc_kw = _kind_from_text(inp.document_description)
        if kind_desc is not None:
            sources.append(ClassificationSource.DESCRIPTION.value)
            reasons.append(
                f"description keyword {desc_kw!r} maps to {kind_desc.value}"
            )
            reason_codes.append(ClassificationReasonCode.MATCHED_DESCRIPTION.value)

        kind_content, content_kw = _kind_from_content_text(inp.content_preview)
        if kind_content is not None:
            sources.append(ClassificationSource.CONTENT_TEXT.value)
            reasons.append(
                f"content cue {content_kw!r} maps to {kind_content.value}"
            )
            reason_codes.append(ClassificationReasonCode.MATCHED_CONTENT_TEXT.value)

        kind_file, file_kw = _kind_from_filename(inp.filename)
        if kind_file is not None:
            sources.append(ClassificationSource.FILENAME.value)
            reasons.append(f"filename cue {file_kw!r} maps to {kind_file.value}")
            reason_codes.append(ClassificationReasonCode.MATCHED_FILENAME.value)

        kind_label: UsptoDocumentKind | None = None
        if inp.explicit_kind:
            try:
                kind_label = UsptoDocumentKind(inp.explicit_kind.strip())
                sources.append(ClassificationSource.LABEL.value)
                reasons.append(f"explicit kind label {kind_label.value}")
                reason_codes.append(ClassificationReasonCode.EXPLICIT_LABEL.value)
            except ValueError:
                reasons.append(
                    f"unrecognized explicit_kind {inp.explicit_kind!r}; ignored"
                )

        label_kind_raw = inp.labels.get("document_kind") or inp.labels.get("kind")
        if kind_label is None and label_kind_raw:
            try:
                kind_label = UsptoDocumentKind(label_kind_raw.strip())
                sources.append(ClassificationSource.LABEL.value)
                reasons.append(f"label document_kind={kind_label.value}")
                reason_codes.append(ClassificationReasonCode.EXPLICIT_LABEL.value)
            except ValueError:
                pass

        # Priority: explicit label > document code > description > content > filename
        chosen: UsptoDocumentKind | None = None
        confidence = _CONF_DEFAULT_UNKNOWN
        if kind_label is not None:
            chosen = kind_label
            confidence = 0.95
        elif kind_code is not None:
            chosen = kind_code
            confidence = _CONF_CODE
        elif kind_desc is not None:
            chosen = kind_desc
            confidence = _CONF_DESCRIPTION
        elif kind_content is not None:
            chosen = kind_content
            confidence = _CONF_CONTENT
        elif kind_file is not None:
            chosen = kind_file
            confidence = _CONF_FILENAME
        else:
            chosen = UsptoDocumentKind.UNKNOWN
            confidence = _CONF_DEFAULT_UNKNOWN
            reasons.append("no document_code/description/content/filename match")
            reason_codes.append(ClassificationReasonCode.UNKNOWN_ARTIFACT.value)
            reason_codes.append(ClassificationReasonCode.MISSING_SIGNALS.value)

        # Parent-linked derivative hint
        if inp.parent_artifact_ids:
            sources.append(ClassificationSource.PARENT_LINK.value)
            if chosen is UsptoDocumentKind.UNKNOWN and detected_media == "application/pdf":
                chosen = UsptoDocumentKind.PDF_CONVERSION
                confidence = max(confidence, 0.60)
                reasons.append(
                    "parent link present with PDF media → treated as pdf_conversion"
                )
                reason_codes.append(
                    ClassificationReasonCode.DERIVATIVE_FROM_PARENT.value
                )

        # --- conflicts ---
        if not media_types_compatible(declared_mime, detected_media):
            conflicts.append(
                ClassificationReasonCode.MIME_CONTENT_CONFLICT.value
            )
            reasons.append(
                f"declared MIME {declared_mime!r} conflicts with content magic "
                f"{detected_media!r}"
            )

        # document_code vs description
        if (
            kind_code is not None
            and kind_desc is not None
            and kind_code is not kind_desc
        ):
            conflicts.append(
                ClassificationReasonCode.DOCUMENT_CODE_DESCRIPTION_CONFLICT.value
            )
            reasons.append(
                f"document_code kind {kind_code.value} conflicts with description "
                f"kind {kind_desc.value}"
            )

        # description/code vs content text
        primary_meta_kind = kind_code or kind_desc
        if (
            primary_meta_kind is not None
            and kind_content is not None
            and primary_meta_kind is not kind_content
        ):
            conflicts.append(
                ClassificationReasonCode.DESCRIPTION_CONTENT_CONFLICT.value
            )
            reasons.append(
                f"metadata kind {primary_meta_kind.value} conflicts with content "
                f"kind {kind_content.value}"
            )

        # kind vs expected media
        expected_media = _KIND_EXPECTED_MEDIA.get(chosen)
        media_for_kind = detected_media or declared_mime
        if expected_media is not None and media_for_kind is not None:
            if media_for_kind not in expected_media and not (
                media_for_kind == "application/zip"
                and "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                in expected_media
            ):
                conflicts.append(
                    ClassificationReasonCode.DESCRIPTION_MIME_CONFLICT.value
                )
                reasons.append(
                    f"kind {chosen.value} is inconsistent with media {media_for_kind!r}"
                )

        # matter ID check
        expected_key = normalize_matter_key(inp.expected_matter_id)
        observed_key = normalize_matter_key(inp.observed_matter_id)
        matter_mismatch = False
        if expected_key is not None and observed_key is not None:
            sources.append(ClassificationSource.MATTER_ID.value)
            if expected_key != observed_key:
                matter_mismatch = True
                conflicts.append(ClassificationReasonCode.MATTER_ID_MISMATCH.value)
                reasons.append(
                    f"expected matter {inp.expected_matter_id!r} "
                    f"(key={expected_key}) != observed {inp.observed_matter_id!r} "
                    f"(key={observed_key})"
                )

        if declared_mime is not None and chosen is not UsptoDocumentKind.UNKNOWN:
            if ClassificationSource.DECLARED_MIME.value in sources:
                reason_codes.append(ClassificationReasonCode.MATCHED_MIME.value)

        # --- authority role ---
        role = _default_role_for_kind(chosen)
        if inp.explicit_authority_role:
            try:
                role = ArtifactAuthorityRole(inp.explicit_authority_role.strip())
                sources.append(ClassificationSource.LABEL.value)
                reasons.append(f"explicit authority role {role.value}")
            except ValueError:
                reasons.append(
                    f"unrecognized explicit_authority_role "
                    f"{inp.explicit_authority_role!r}; using default"
                )
        elif inp.parent_artifact_ids and chosen is UsptoDocumentKind.PDF_CONVERSION:
            role = ArtifactAuthorityRole.DERIVATIVE
            reason_codes.append(ClassificationReasonCode.DERIVATIVE_FROM_PARENT.value)
        elif chosen is UsptoDocumentKind.CITATION:
            role = ArtifactAuthorityRole.SUPPLEMENTAL
            reason_codes.append(ClassificationReasonCode.SUPPLEMENTAL_CITATION.value)

        if inp.direction_category:
            sources.append(ClassificationSource.DIRECTION.value)

        # --- disposition ---
        quarantine = False
        review = False

        hard_conflict_codes = {
            ClassificationReasonCode.MIME_CONTENT_CONFLICT.value,
            ClassificationReasonCode.MATTER_ID_MISMATCH.value,
            ClassificationReasonCode.DOCUMENT_CODE_DESCRIPTION_CONFLICT.value,
            ClassificationReasonCode.DESCRIPTION_CONTENT_CONFLICT.value,
        }
        if any(c in hard_conflict_codes for c in conflicts):
            quarantine = True
        if ClassificationReasonCode.DESCRIPTION_MIME_CONFLICT.value in conflicts:
            review = True
        if chosen is UsptoDocumentKind.UNKNOWN:
            review = True
        if confidence < _CONF_REVIEW_THRESHOLD:
            review = True
            reason_codes.append(ClassificationReasonCode.LOW_CONFIDENCE.value)

        if conflicts:
            confidence = min(confidence, _CONF_CONFLICT_CAP)
            reason_codes.extend(conflicts)

        if quarantine:
            disposition = ClassificationDisposition.QUARANTINE
            review_state = ReviewState.REQUIRED
            reasons.append("disposition=quarantine due to conflicting signals")
        elif review:
            disposition = ClassificationDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            reasons.append("disposition=review (unknown, low confidence, or soft conflict)")
        else:
            disposition = ClassificationDisposition.CLASSIFIED
            review_state = ReviewState.NOT_REQUIRED

        if not sources:
            sources.append(ClassificationSource.DEFAULT.value)
            reasons.append("no classification sources available; defaulted to unknown")

        # De-dupe while preserving order
        sources_u = tuple(dict.fromkeys(sources))
        reason_codes_u = tuple(dict.fromkeys(reason_codes))
        reasons_u = tuple(dict.fromkeys(reasons))

        labels = dict(inp.labels)
        labels.setdefault("document_kind", chosen.value)
        labels.setdefault("authority_role", role.value)
        if declared_mime:
            labels.setdefault("declared_mime", declared_mime)
        if detected_media:
            labels.setdefault("detected_media", detected_media)

        return DocumentClassification(
            schema_version=DOCUMENT_CLASSIFIER_SCHEMA_VERSION,
            document_kind=chosen,
            authority_role=role,
            authority_relation=authority_role_to_relation(role),
            confidence=confidence,
            reasons=reasons_u,
            sources=sources_u,
            disposition=disposition,
            review_state=review_state,
            reason_codes=reason_codes_u,
            document_code=inp.document_code,
            declared_mime=declared_mime,
            detected_media=detected_media,
            expected_matter_id=inp.expected_matter_id,
            observed_matter_id=inp.observed_matter_id,
            parent_artifact_ids=inp.parent_artifact_ids,
            related_artifact_ids=(),
            labels=labels,
            retained=True,
            classification_id=str(self._id_factory()),
            artifact_id=inp.artifact_id,
        )


def classify_document(
    value: DocumentClassificationInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> DocumentClassification:
    """Module-level convenience wrapper around :class:`DocumentClassifier`."""
    return DocumentClassifier().classify(value, **kwargs)


__all__ = [
    "DOCUMENT_CLASSIFIER_INTERFACE",
    "DOCUMENT_CLASSIFIER_SCHEMA_VERSION",
    "ArtifactAuthorityRole",
    "ClassificationDisposition",
    "ClassificationReasonCode",
    "ClassificationSource",
    "DocumentClassification",
    "DocumentClassificationInput",
    "DocumentClassifier",
    "DocumentClassifierError",
    "UsptoDocumentKind",
    "authority_role_to_relation",
    "classify_document",
    "detect_media_from_bytes",
    "media_types_compatible",
    "normalize_matter_key",
]
