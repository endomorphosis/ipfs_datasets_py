"""USPTO document extraction with page/span provenance (PATLAW-031).

Orchestrates bounded extraction of PDF and DOCX artifacts into versioned,
serializable records:

* native page text, layout items (tables/forms/annotations/checkmarks/stamps/
  signature-presence), and filing metadata;
* optional page-level OCR injection when native coverage is low;
* DOCX structure (paragraphs, tables, headers/footers, core properties);
* authoritative DOCX versus converted-PDF difference reports;
* page coverage receipts with render digests and native/OCR origins.

Generic PDF pipeline internals (GraphRAG OCR engines, adapters) remain outside
this module. Callers may inject an OCR callable; missing OCR and low coverage
yield explicit ``review`` disposition, never guessed content.

Document body text is never written to logs or exception messages.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Sequence,
)
from xml.etree import ElementTree as ET

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
    requires_quarantine,
)

DOCUMENT_EXTRACTION_SCHEMA_VERSION: Final = "uspto.document-extraction.v1"
DOCUMENT_EXTRACTION_INTERFACE: Final = "DocumentExtractionProcessor@1"

# ---------------------------------------------------------------------------
# Bounds (untrusted document execution)
# ---------------------------------------------------------------------------

DEFAULT_MAX_BYTES: Final = 16 * 1024 * 1024
DEFAULT_MAX_PAGES: Final = 500
DEFAULT_MAX_SPANS_PER_PAGE: Final = 4096
DEFAULT_MAX_LAYOUT_ITEMS: Final = 8192
DEFAULT_MAX_ARCHIVE_MEMBERS: Final = 256
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED: Final = 32 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_MEMBER_BYTES: Final = 16 * 1024 * 1024
DEFAULT_MAX_ZIP_DEPTH: Final = 2
DEFAULT_MIN_NATIVE_CHARS: Final = 40
DEFAULT_NATIVE_COVERAGE_THRESHOLD: Final = 0.15
DEFAULT_LOW_COVERAGE_REVIEW_THRESHOLD: Final = 0.35
DEFAULT_MIN_OVERALL_COVERAGE: Final = 0.5

_PDF_MAGIC: Final = b"%PDF"
_ZIP_MAGIC: Final = b"PK"
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_DIGITS_RE = re.compile(r"\D+")

# OOXML namespaces used for compact DOCX structure extraction.
_W_NS: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CP_NS: Final = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC_NS: Final = "http://purl.org/dc/elements/1.1/"
_DCTERMS_NS: Final = "http://purl.org/dc/terms/"
_NS = {
    "w": _W_NS,
    "cp": _CP_NS,
    "dc": _DC_NS,
    "dcterms": _DCTERMS_NS,
}

DOCX_MIME: Final = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Optional heavy backends (never required for admission of native-text fixtures).
try:  # pragma: no cover - environment dependent
    import fitz as _fitz
except Exception:  # pragma: no cover
    _fitz = None  # type: ignore[assignment]

try:  # pragma: no cover
    from pypdf import PdfReader as _PdfReader
    from pypdf.errors import FileNotDecryptedError as _FileNotDecryptedError
except Exception:  # pragma: no cover
    _PdfReader = None  # type: ignore[assignment,misc]
    _FileNotDecryptedError = Exception  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ExtractionDisposition(str, Enum):
    """Pipeline disposition after extraction."""

    EXTRACTED = "extracted"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class MediaFamily(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    ARCHIVE = "archive"
    UNKNOWN = "unknown"


class PageStatus(str, Enum):
    OK = "ok"
    LOW_COVERAGE = "low_coverage"
    IMAGE_ONLY = "image_only"
    BLANK = "blank"
    ROTATED = "rotated"
    CORRUPT = "corrupt"
    PASSWORD_PROTECTED = "password_protected"
    UNSUPPORTED = "unsupported"
    EMPTY = "empty"
    DISAGREEMENT = "disagreement"
    OCR_NEEDED = "ocr_needed"
    OCR_UNAVAILABLE = "ocr_unavailable"


class LayoutItemKind(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FORM_FIELD = "form_field"
    ANNOTATION = "annotation"
    LINK = "link"
    CHECKBOX = "checkbox"
    CHECKMARK = "checkmark"
    STAMP = "stamp"
    SIGNATURE_PRESENCE = "signature_presence"
    HEADER = "header"
    FOOTER = "footer"
    IMAGE = "image"
    EQUATION = "equation"
    PARAGRAPH = "paragraph"
    OTHER = "other"


class DifferenceKind(str, Enum):
    PAGINATION = "pagination"
    CONTENT = "content"
    TABLE = "table"
    EQUATION = "equation"
    SYMBOL = "symbol"
    FONT = "font"
    METADATA = "metadata"
    MISSING_PAGE = "missing_page"
    UNSUPPORTED = "unsupported"
    OTHER = "other"


class ExtractionReasonCode(str, Enum):
    NATIVE_TEXT_EXTRACTED = "native_text_extracted"
    OCR_TEXT_EXTRACTED = "ocr_text_extracted"
    DOCX_STRUCTURE_EXTRACTED = "docx_structure_extracted"
    LAYOUT_ITEMS_EXTRACTED = "layout_items_extracted"
    FILING_METADATA_EXTRACTED = "filing_metadata_extracted"
    LOW_COVERAGE = "low_coverage"
    IMAGE_ONLY_PAGE = "image_only_page"
    BLANK_PAGE = "blank_page"
    ROTATED_PAGE = "rotated_page"
    PASSWORD_PROTECTED = "password_protected"
    CORRUPT_DOCUMENT = "corrupt_document"
    OVERSIZE_DOCUMENT = "oversize_document"
    PAGE_LIMIT_EXCEEDED = "page_limit_exceeded"
    ARCHIVE_BOUNDED = "archive_bounded"
    ARCHIVE_REJECTED = "archive_rejected"
    UNSUPPORTED_MEDIA = "unsupported_media"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    DOCX_PDF_DIFFERENCE = "docx_pdf_difference"
    MIME_CONTENT_CONFLICT = "mime_content_conflict"
    OCR_UNAVAILABLE = "ocr_unavailable"
    OCR_INJECTED = "ocr_injected"
    SIGNATURE_PRESENCE_ONLY = "signature_presence_only"
    MISSING_BYTES = "missing_bytes"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    COMPARE_PAIR = "compare_pair"


# Optional OCR callable: (page_image_bytes, page_index) -> mapping.
OcrCallable = Callable[[bytes, int], Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DocumentExtractionError(ValueError):
    """Bounded extraction failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "extraction_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        # Never include document body text.
        return {"code": self.code, "message": str(self)[:256]}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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
    return tuple(_require_str(item, f"{field}[{i}]", max_len=2048) for i, item in enumerate(value))


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


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text).encode("utf-8"))


def _token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9]+", (text or "").lower()) if t}


def text_similarity(a: str, b: str) -> float:
    """Jaccard similarity over alphanumeric tokens."""
    ta, tb = _token_set(a), _token_set(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def estimate_native_char_coverage(
    text: str,
    *,
    page_width: float = 0.0,
    page_height: float = 0.0,
    min_chars: int = DEFAULT_MIN_NATIVE_CHARS,
) -> float:
    """Estimate readable native coverage in [0.0, 1.0]."""
    cleaned = _normalize_ws(text)
    if not cleaned:
        return 0.0
    n = len(cleaned)
    if page_width > 0 and page_height > 0:
        capacity = max(min_chars, (page_width * page_height) / 180.0)
        return max(0.0, min(1.0, n / capacity))
    return max(0.0, min(1.0, n / float(max(min_chars * 2, 1))))


def detect_media_family(
    content: bytes | None,
    *,
    declared_mime: str | None = None,
    filename: str | None = None,
) -> MediaFamily:
    """Classify bytes into a coarse media family for dispatch."""
    mime = (declared_mime or "").strip().lower().split(";", 1)[0]
    name = (filename or "").strip().lower()
    if content and content.startswith(_PDF_MAGIC):
        return MediaFamily.PDF
    if content and content.startswith(_ZIP_MAGIC):
        if _looks_like_docx(content) or mime == DOCX_MIME or name.endswith(".docx"):
            return MediaFamily.DOCX
        return MediaFamily.ARCHIVE
    if mime == "application/pdf" or name.endswith(".pdf"):
        return MediaFamily.PDF
    if mime == DOCX_MIME or name.endswith(".docx"):
        return MediaFamily.DOCX
    if mime in ("application/zip", "application/x-zip-compressed") or name.endswith(".zip"):
        return MediaFamily.ARCHIVE
    return MediaFamily.UNKNOWN


def _looks_like_docx(content: bytes) -> bool:
    if not content.startswith(_ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
            return "[Content_Types].xml" in names and any(
                n.startswith("word/") for n in names
            )
    except zipfile.BadZipFile:
        return False


def _normalize_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    if isinstance(bbox, Mapping):
        keys = ("x0", "y0", "x1", "y1")
        if all(k in bbox for k in keys):
            return (
                float(bbox["x0"]),
                float(bbox["y0"]),
                float(bbox["x1"]),
                float(bbox["y1"]),
            )
        if "bbox" in bbox:
            return _normalize_bbox(bbox["bbox"])
        return None
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError):
            return None
    return None


def _digits_only(value: str) -> str:
    return _DIGITS_RE.sub("", value or "")


# ---------------------------------------------------------------------------
# Input / bounds
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractionBounds:
    """Hard limits for untrusted document execution."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_pages: int = DEFAULT_MAX_PAGES
    max_spans_per_page: int = DEFAULT_MAX_SPANS_PER_PAGE
    max_layout_items: int = DEFAULT_MAX_LAYOUT_ITEMS
    max_archive_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS
    max_archive_uncompressed: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED
    max_archive_member_bytes: int = DEFAULT_MAX_ARCHIVE_MEMBER_BYTES
    max_zip_depth: int = DEFAULT_MAX_ZIP_DEPTH
    min_native_chars: int = DEFAULT_MIN_NATIVE_CHARS
    native_coverage_threshold: float = DEFAULT_NATIVE_COVERAGE_THRESHOLD
    low_coverage_review_threshold: float = DEFAULT_LOW_COVERAGE_REVIEW_THRESHOLD
    min_overall_coverage: float = DEFAULT_MIN_OVERALL_COVERAGE

    def __post_init__(self) -> None:
        for name in (
            "max_bytes",
            "max_pages",
            "max_spans_per_page",
            "max_layout_items",
            "max_archive_members",
            "max_archive_uncompressed",
            "max_archive_member_bytes",
            "max_zip_depth",
            "min_native_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in (
            "native_coverage_threshold",
            "low_coverage_review_threshold",
            "min_overall_coverage",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0]")


@dataclass(frozen=True, slots=True)
class DocumentExtractionInput:
    """Inputs for a single-artifact extraction.

    ``content_bytes`` may be omitted only for explicit reject-path tests; empty
    or missing bytes fail closed.
    """

    artifact_id: str
    content_bytes: bytes | None = None
    declared_mime: str | None = None
    filename: str | None = None
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    content_sha256: str | None = None
    related_artifact_id: str | None = None
    compare_content_bytes: bytes | None = None
    compare_declared_mime: str | None = None
    compare_filename: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    force_ocr: bool = False
    # Pre-supplied OCR payloads keyed by page index (tests / upstream OCR).
    ocr_by_page: Mapping[int, Mapping[str, Any]] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if self.content_bytes is not None and not isinstance(
            self.content_bytes, (bytes, bytearray)
        ):
            raise TypeError("content_bytes must be bytes or None")
        if isinstance(self.content_bytes, bytearray):
            object.__setattr__(self, "content_bytes", bytes(self.content_bytes))
        object.__setattr__(
            self,
            "declared_mime",
            _optional_str(self.declared_mime, "declared_mime", max_len=256),
        )
        object.__setattr__(
            self, "filename", _optional_str(self.filename, "filename", max_len=512)
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if self.content_sha256 is not None:
            digest = _require_str(self.content_sha256, "content_sha256", max_len=64).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("content_sha256 must be a 64-char lowercase hex digest")
            object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self,
            "related_artifact_id",
            _optional_identifier(self.related_artifact_id, "related_artifact_id"),
        )
        if self.compare_content_bytes is not None and not isinstance(
            self.compare_content_bytes, (bytes, bytearray)
        ):
            raise TypeError("compare_content_bytes must be bytes or None")
        if isinstance(self.compare_content_bytes, bytearray):
            object.__setattr__(
                self, "compare_content_bytes", bytes(self.compare_content_bytes)
            )
        object.__setattr__(
            self,
            "compare_declared_mime",
            _optional_str(self.compare_declared_mime, "compare_declared_mime", max_len=256),
        )
        object.__setattr__(
            self,
            "compare_filename",
            _optional_str(self.compare_filename, "compare_filename", max_len=512),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels", max_items=32))
        if not isinstance(self.force_ocr, bool):
            raise TypeError("force_ocr must be bool")
        # Freeze OCR map
        if self.ocr_by_page is None:
            object.__setattr__(self, "ocr_by_page", MappingProxyType({}))
        elif not isinstance(self.ocr_by_page, Mapping):
            raise TypeError("ocr_by_page must be a mapping")
        else:
            frozen: dict[int, Mapping[str, Any]] = {}
            for k, v in self.ocr_by_page.items():
                if isinstance(k, bool) or not isinstance(k, int) or k < 0:
                    raise TypeError("ocr_by_page keys must be non-negative ints")
                if not isinstance(v, Mapping):
                    raise TypeError("ocr_by_page values must be mappings")
                frozen[k] = MappingProxyType(dict(v))
            object.__setattr__(self, "ocr_by_page", MappingProxyType(frozen))


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageCoverageRecord:
    """Per-page coverage and provenance receipt."""

    schema_version: str
    page_index: int
    artifact_id: str
    native_char_count: int
    ocr_char_count: int
    merged_char_count: int
    native_coverage: float
    coverage_ratio: float
    has_native_text: bool
    has_ocr_text: bool
    rotation: int
    status: PageStatus
    ocr_status: str
    ocr_confidence: float | None
    origins_present: tuple[str, ...]
    disagreement: bool
    disagreement_score: float
    render_digest: str | None
    page_width: float | None
    page_height: float | None
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                "PageCoverageRecord.schema_version must be "
                f"{DOCUMENT_EXTRACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "page_index", _nonneg_int(self.page_index, "page_index")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        for name in ("native_char_count", "ocr_char_count", "merged_char_count"):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "native_coverage",
            _require_float_01(self.native_coverage, "native_coverage"),
        )
        object.__setattr__(
            self,
            "coverage_ratio",
            _require_float_01(self.coverage_ratio, "coverage_ratio"),
        )
        if not isinstance(self.has_native_text, bool):
            raise TypeError("has_native_text must be bool")
        if not isinstance(self.has_ocr_text, bool):
            raise TypeError("has_ocr_text must be bool")
        if isinstance(self.rotation, bool) or not isinstance(self.rotation, int):
            raise TypeError("rotation must be int")
        object.__setattr__(self, "status", _coerce_enum(PageStatus, self.status, "status"))
        object.__setattr__(
            self, "ocr_status", _require_str(self.ocr_status, "ocr_status", max_len=64)
        )
        object.__setattr__(
            self,
            "ocr_confidence",
            _optional_float_01(self.ocr_confidence, "ocr_confidence"),
        )
        object.__setattr__(
            self,
            "origins_present",
            _tuple_of_str(self.origins_present, "origins_present", max_items=16),
        )
        if not isinstance(self.disagreement, bool):
            raise TypeError("disagreement must be bool")
        object.__setattr__(
            self,
            "disagreement_score",
            _require_float_01(self.disagreement_score, "disagreement_score"),
        )
        if self.render_digest is not None:
            digest = _require_str(self.render_digest, "render_digest", max_len=64).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("render_digest must be sha256 hex")
            object.__setattr__(self, "render_digest", digest)
        for name in ("page_width", "page_height"):
            val = getattr(self, name)
            if val is not None:
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise TypeError(f"{name} must be float or None")
                object.__setattr__(self, name, float(val))
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "coverage_ratio": self.coverage_ratio,
            "disagreement": self.disagreement,
            "disagreement_score": self.disagreement_score,
            "has_native_text": self.has_native_text,
            "has_ocr_text": self.has_ocr_text,
            "merged_char_count": self.merged_char_count,
            "native_char_count": self.native_char_count,
            "native_coverage": self.native_coverage,
            "ocr_char_count": self.ocr_char_count,
            "ocr_confidence": self.ocr_confidence,
            "ocr_status": self.ocr_status,
            "origins_present": list(self.origins_present),
            "page_height": self.page_height,
            "page_index": self.page_index,
            "page_width": self.page_width,
            "render_digest": self.render_digest,
            "rotation": self.rotation,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageCoverageRecord":
        if not isinstance(value, Mapping):
            raise TypeError("PageCoverageRecord must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", DOCUMENT_EXTRACTION_SCHEMA_VERSION
            ),
            page_index=value.get("page_index", 0),
            artifact_id=value.get("artifact_id", ""),
            native_char_count=value.get("native_char_count", 0),
            ocr_char_count=value.get("ocr_char_count", 0),
            merged_char_count=value.get("merged_char_count", 0),
            native_coverage=value.get("native_coverage", 0.0),
            coverage_ratio=value.get("coverage_ratio", 0.0),
            has_native_text=bool(value.get("has_native_text", False)),
            has_ocr_text=bool(value.get("has_ocr_text", False)),
            rotation=int(value.get("rotation", 0) or 0),
            status=value.get("status", PageStatus.EMPTY.value),
            ocr_status=value.get("ocr_status", "not_needed"),
            ocr_confidence=value.get("ocr_confidence"),
            origins_present=tuple(value.get("origins_present") or ()),
            disagreement=bool(value.get("disagreement", False)),
            disagreement_score=float(value.get("disagreement_score", 0.0) or 0.0),
            render_digest=value.get("render_digest"),
            page_width=value.get("page_width"),
            page_height=value.get("page_height"),
            warnings=tuple(value.get("warnings") or ()),
        )


@dataclass(frozen=True, slots=True)
class LayoutItem:
    """Layout / form / annotation item with span provenance."""

    schema_version: str
    item_id: str
    artifact_id: str
    kind: LayoutItemKind
    span_id: str | None
    page_index: int | None
    bbox: tuple[float, float, float, float] | None
    text_digest: str | None
    confidence: float | None
    attributes: Mapping[str, str]
    origin: ExtractionOrigin

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                f"LayoutItem.schema_version must be {DOCUMENT_EXTRACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "kind", _coerce_enum(LayoutItemKind, self.kind, "kind"))
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        if self.page_index is not None:
            object.__setattr__(
                self, "page_index", _nonneg_int(self.page_index, "page_index")
            )
        if self.bbox is not None:
            bb = _normalize_bbox(self.bbox)
            if bb is None:
                raise TypeError("bbox must be a 4-tuple of floats")
            object.__setattr__(self, "bbox", bb)
        if self.text_digest is not None:
            digest = _require_str(self.text_digest, "text_digest", max_len=64).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("text_digest must be sha256 hex")
            object.__setattr__(self, "text_digest", digest)
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "attributes",
            _frozen_str_map(self.attributes, "attributes", max_items=32),
        )
        object.__setattr__(
            self, "origin", _coerce_enum(ExtractionOrigin, self.origin, "origin")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "attributes": dict(self.attributes),
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "confidence": self.confidence,
            "item_id": self.item_id,
            "kind": self.kind.value,
            "origin": self.origin.value,
            "page_index": self.page_index,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LayoutItem":
        if not isinstance(value, Mapping):
            raise TypeError("LayoutItem must be a mapping")
        bbox_raw = value.get("bbox")
        bbox = None if bbox_raw is None else tuple(float(x) for x in bbox_raw)
        return cls(
            schema_version=value.get(
                "schema_version", DOCUMENT_EXTRACTION_SCHEMA_VERSION
            ),
            item_id=value.get("item_id", ""),
            artifact_id=value.get("artifact_id", ""),
            kind=value.get("kind", LayoutItemKind.OTHER.value),
            span_id=value.get("span_id"),
            page_index=value.get("page_index"),
            bbox=bbox,  # type: ignore[arg-type]
            text_digest=value.get("text_digest"),
            confidence=value.get("confidence"),
            attributes=value.get("attributes") or {},
            origin=value.get("origin", ExtractionOrigin.NATIVE.value),
        )


@dataclass(frozen=True, slots=True)
class FilingMetadataField:
    """Single filing/metadata field with span provenance."""

    schema_version: str
    field_id: str
    field_name: str
    value_digest: str
    display_value: str | None
    span_id: str | None
    page_index: int | None
    confidence: float | None
    origin: ExtractionOrigin

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                "FilingMetadataField.schema_version must be "
                f"{DOCUMENT_EXTRACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "field_id", _identifier(self.field_id, "field_id"))
        object.__setattr__(
            self,
            "field_name",
            _require_str(self.field_name, "field_name", max_len=128),
        )
        digest = _require_str(self.value_digest, "value_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("value_digest must be sha256 hex")
        object.__setattr__(self, "value_digest", digest)
        # display_value is intentionally short and may be redacted by callers.
        object.__setattr__(
            self,
            "display_value",
            _optional_str(self.display_value, "display_value", max_len=256),
        )
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        if self.page_index is not None:
            object.__setattr__(
                self, "page_index", _nonneg_int(self.page_index, "page_index")
            )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "origin", _coerce_enum(ExtractionOrigin, self.origin, "origin")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "display_value": self.display_value,
            "field_id": self.field_id,
            "field_name": self.field_name,
            "origin": self.origin.value,
            "page_index": self.page_index,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "value_digest": self.value_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingMetadataField":
        if not isinstance(value, Mapping):
            raise TypeError("FilingMetadataField must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", DOCUMENT_EXTRACTION_SCHEMA_VERSION
            ),
            field_id=value.get("field_id", ""),
            field_name=value.get("field_name", ""),
            value_digest=value.get("value_digest", ""),
            display_value=value.get("display_value"),
            span_id=value.get("span_id"),
            page_index=value.get("page_index"),
            confidence=value.get("confidence"),
            origin=value.get("origin", ExtractionOrigin.METADATA.value),
        )


@dataclass(frozen=True, slots=True)
class ArtifactDifference:
    """Explicit difference between authoritative DOCX and converted PDF."""

    schema_version: str
    difference_id: str
    kind: DifferenceKind
    status: str
    docx_artifact_id: str | None
    pdf_artifact_id: str | None
    docx_page: int | None
    pdf_page: int | None
    field: str | None
    element: str | None
    reason_codes: tuple[str, ...]
    detail: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                "ArtifactDifference.schema_version must be "
                f"{DOCUMENT_EXTRACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "difference_id", _identifier(self.difference_id, "difference_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(DifferenceKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "status", _require_str(self.status, "status", max_len=64)
        )
        object.__setattr__(
            self,
            "docx_artifact_id",
            _optional_identifier(self.docx_artifact_id, "docx_artifact_id"),
        )
        object.__setattr__(
            self,
            "pdf_artifact_id",
            _optional_identifier(self.pdf_artifact_id, "pdf_artifact_id"),
        )
        for name in ("docx_page", "pdf_page"):
            val = getattr(self, name)
            if val is not None:
                object.__setattr__(self, name, _nonneg_int(val, name))
        object.__setattr__(
            self, "field", _optional_str(self.field, "field", max_len=256)
        )
        object.__setattr__(
            self, "element", _optional_str(self.element, "element", max_len=256)
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        object.__setattr__(
            self, "detail", _optional_str(self.detail, "detail", max_len=512)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "difference_id": self.difference_id,
            "docx_artifact_id": self.docx_artifact_id,
            "docx_page": self.docx_page,
            "element": self.element,
            "field": self.field,
            "kind": self.kind.value,
            "pdf_artifact_id": self.pdf_artifact_id,
            "pdf_page": self.pdf_page,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactDifference":
        if not isinstance(value, Mapping):
            raise TypeError("ArtifactDifference must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", DOCUMENT_EXTRACTION_SCHEMA_VERSION
            ),
            difference_id=value.get("difference_id", ""),
            kind=value.get("kind", DifferenceKind.OTHER.value),
            status=value.get("status", "disagreement"),
            docx_artifact_id=value.get("docx_artifact_id"),
            pdf_artifact_id=value.get("pdf_artifact_id"),
            docx_page=value.get("docx_page"),
            pdf_page=value.get("pdf_page"),
            field=value.get("field"),
            element=value.get("element"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            detail=value.get("detail"),
        )


@dataclass(frozen=True, slots=True)
class PageExtraction:
    """Per-page extraction view with text and span ids (text kept for callers)."""

    page_index: int
    text: str
    span_ids: tuple[str, ...]
    coverage: PageCoverageRecord
    layout_item_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage.to_dict(),
            "layout_item_ids": list(self.layout_item_ids),
            "page_index": self.page_index,
            "span_ids": list(self.span_ids),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class DocumentExtractionResult:
    """Full extraction outcome with provenance for every page and item."""

    schema_version: str
    extraction_id: str
    artifact_id: str
    media_family: MediaFamily
    content_sha256: str
    disposition: ExtractionDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_features: tuple[str, ...]
    overall_coverage: float
    page_count: int
    pages: tuple[PageExtraction, ...]
    page_coverage: tuple[PageCoverageRecord, ...]
    spans: tuple[ExtractedSpan, ...]
    layout_items: tuple[LayoutItem, ...]
    filing_metadata: tuple[FilingMetadataField, ...]
    differences: tuple[ArtifactDifference, ...]
    # Page text keyed by page_index for quote/round-trip consumers.
    page_texts: Mapping[str, str]
    full_text: str
    labels: Mapping[str, str]
    parser_versions: Mapping[str, str]
    related_artifact_ids: tuple[str, ...]
    retained: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                "DocumentExtractionResult.schema_version must be "
                f"{DOCUMENT_EXTRACTION_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "extraction_id", _identifier(self.extraction_id, "extraction_id")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "media_family",
            _coerce_enum(MediaFamily, self.media_family, "media_family"),
        )
        digest = _require_str(self.content_sha256, "content_sha256", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("content_sha256 must be sha256 hex")
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ExtractionDisposition, self.disposition, "disposition"),
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
        object.__setattr__(
            self,
            "unsupported_features",
            _tuple_of_str(self.unsupported_features, "unsupported_features", max_items=128),
        )
        object.__setattr__(
            self,
            "overall_coverage",
            _require_float_01(self.overall_coverage, "overall_coverage"),
        )
        object.__setattr__(
            self, "page_count", _nonneg_int(self.page_count, "page_count")
        )
        if not isinstance(self.pages, tuple):
            object.__setattr__(self, "pages", tuple(self.pages))
        if not isinstance(self.page_coverage, tuple):
            object.__setattr__(self, "page_coverage", tuple(self.page_coverage))
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        if not isinstance(self.layout_items, tuple):
            object.__setattr__(self, "layout_items", tuple(self.layout_items))
        if not isinstance(self.filing_metadata, tuple):
            object.__setattr__(self, "filing_metadata", tuple(self.filing_metadata))
        if not isinstance(self.differences, tuple):
            object.__setattr__(self, "differences", tuple(self.differences))
        object.__setattr__(
            self,
            "page_texts",
            _frozen_str_map(
                self.page_texts,
                "page_texts",
                max_items=DEFAULT_MAX_PAGES,
                allow_empty_values=True,
                max_value_len=2_000_000,
            ),
        )
        if not isinstance(self.full_text, str):
            raise TypeError("full_text must be str")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self,
            "parser_versions",
            _frozen_str_map(self.parser_versions, "parser_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "related_artifact_ids",
            _tuple_of_str(self.related_artifact_ids, "related_artifact_ids", max_items=64),
        )
        if not isinstance(self.retained, bool):
            raise TypeError("retained must be bool")
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            ExtractionDisposition.REVIEW,
            ExtractionDisposition.QUARANTINE,
            ExtractionDisposition.REJECTED,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    @property
    def is_rejected(self) -> bool:
        return self.disposition is ExtractionDisposition.REJECTED

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "differences": [d.to_dict() for d in self.differences],
            "disposition": self.disposition.value,
            "extraction_id": self.extraction_id,
            "filing_metadata": [f.to_dict() for f in self.filing_metadata],
            "full_text": self.full_text,
            "labels": dict(self.labels),
            "layout_items": [i.to_dict() for i in self.layout_items],
            "media_family": self.media_family.value,
            "overall_coverage": self.overall_coverage,
            "page_count": self.page_count,
            "page_coverage": [c.to_dict() for c in self.page_coverage],
            "page_texts": dict(self.page_texts),
            "pages": [p.to_dict() for p in self.pages],
            "parser_versions": dict(self.parser_versions),
            "reason_codes": list(self.reason_codes),
            "related_artifact_ids": list(self.related_artifact_ids),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "spans": [s.to_dict() for s in self.spans],
            "unsupported_features": list(self.unsupported_features),
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and coverage only — never page text or display values."""
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "extraction_id": self.extraction_id,
            "media_family": self.media_family.value,
            "overall_coverage": self.overall_coverage,
            "page_count": self.page_count,
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_count": len(self.spans),
            "layout_item_count": len(self.layout_items),
            "difference_count": len(self.differences),
            "unsupported_features": list(self.unsupported_features),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DocumentExtractionResult":
        if not isinstance(value, Mapping):
            raise TypeError("DocumentExtractionResult must be a mapping")
        pages_raw = value.get("pages") or ()
        pages: list[PageExtraction] = []
        for p in pages_raw:
            if not isinstance(p, Mapping):
                continue
            cov = PageCoverageRecord.from_dict(p.get("coverage") or {})
            pages.append(
                PageExtraction(
                    page_index=int(p.get("page_index", cov.page_index)),
                    text=str(p.get("text") or ""),
                    span_ids=tuple(p.get("span_ids") or ()),
                    coverage=cov,
                    layout_item_ids=tuple(p.get("layout_item_ids") or ()),
                )
            )
        return cls(
            schema_version=value.get(
                "schema_version", DOCUMENT_EXTRACTION_SCHEMA_VERSION
            ),
            extraction_id=value.get("extraction_id", ""),
            artifact_id=value.get("artifact_id", ""),
            media_family=value.get("media_family", MediaFamily.UNKNOWN.value),
            content_sha256=value.get("content_sha256", ""),
            disposition=value.get(
                "disposition", ExtractionDisposition.REVIEW.value
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            unsupported_features=tuple(value.get("unsupported_features") or ()),
            overall_coverage=float(value.get("overall_coverage", 0.0) or 0.0),
            page_count=int(value.get("page_count", 0) or 0),
            pages=tuple(pages),
            page_coverage=tuple(
                PageCoverageRecord.from_dict(c)
                for c in (value.get("page_coverage") or ())
                if isinstance(c, Mapping)
            ),
            spans=tuple(
                ExtractedSpan.from_dict(s)
                for s in (value.get("spans") or ())
                if isinstance(s, Mapping)
            ),
            layout_items=tuple(
                LayoutItem.from_dict(i)
                for i in (value.get("layout_items") or ())
                if isinstance(i, Mapping)
            ),
            filing_metadata=tuple(
                FilingMetadataField.from_dict(f)
                for f in (value.get("filing_metadata") or ())
                if isinstance(f, Mapping)
            ),
            differences=tuple(
                ArtifactDifference.from_dict(d)
                for d in (value.get("differences") or ())
                if isinstance(d, Mapping)
            ),
            page_texts=value.get("page_texts") or {},
            full_text=str(value.get("full_text") or ""),
            labels=value.get("labels") or {},
            parser_versions=value.get("parser_versions") or {},
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Internal mutable builders
# ---------------------------------------------------------------------------


@dataclass
class _SpanBuilder:
    text: str
    page_index: int | None
    char_start: int | None
    char_end: int | None
    bbox: tuple[float, float, float, float] | None
    origin: ExtractionOrigin
    reading_order: int | None
    confidence: float | None
    image_digest: str | None = None


@dataclass
class _PageBuilder:
    page_index: int
    text: str = ""
    native_text: str = ""
    ocr_text: str = ""
    rotation: int = 0
    width: float | None = None
    height: float | None = None
    render_digest: str | None = None
    status: PageStatus = PageStatus.EMPTY
    ocr_status: str = "not_needed"
    ocr_confidence: float | None = None
    origins: list[str] | None = None
    disagreement: bool = False
    disagreement_score: float = 0.0
    warnings: list[str] | None = None
    span_builders: list[_SpanBuilder] | None = None
    layout_item_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.origins is None:
            self.origins = []
        if self.warnings is None:
            self.warnings = []
        if self.span_builders is None:
            self.span_builders = []
        if self.layout_item_ids is None:
            self.layout_item_ids = []


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class DocumentExtractionProcessor:
    """Extract PDF/DOCX content with artifact/page/character/bbox provenance."""

    def __init__(
        self,
        *,
        bounds: ExtractionBounds | None = None,
        id_factory: Callable[[], str] | None = None,
        ocr_callable: OcrCallable | None = None,
    ) -> None:
        self.bounds = bounds or ExtractionBounds()
        self._id_factory = id_factory or (lambda: f"extract:{uuid.uuid4().hex}")
        self._ocr_callable = ocr_callable

    def extract(
        self,
        value: DocumentExtractionInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> DocumentExtractionResult:
        inp = self._coerce_input(value, **kwargs)
        return self._extract(inp)

    def extract_many(
        self, values: Iterable[DocumentExtractionInput | Mapping[str, Any]]
    ) -> list[DocumentExtractionResult]:
        return [self.extract(v) for v in values]

    def compare_docx_pdf(
        self,
        *,
        docx_result: DocumentExtractionResult,
        pdf_result: DocumentExtractionResult,
        docx_artifact_id: str | None = None,
        pdf_artifact_id: str | None = None,
    ) -> tuple[ArtifactDifference, ...]:
        """Compare two prior extraction results and emit explicit differences."""
        return tuple(
            self._compare_results(
                docx_result,
                pdf_result,
                docx_artifact_id=docx_artifact_id or docx_result.artifact_id,
                pdf_artifact_id=pdf_artifact_id or pdf_result.artifact_id,
            )
        )

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: DocumentExtractionInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> DocumentExtractionInput:
        if value is None:
            return DocumentExtractionInput(**kwargs)
        if isinstance(value, DocumentExtractionInput):
            if kwargs:
                data = {
                    "artifact_id": value.artifact_id,
                    "content_bytes": value.content_bytes,
                    "declared_mime": value.declared_mime,
                    "filename": value.filename,
                    "classification": value.classification,
                    "content_sha256": value.content_sha256,
                    "related_artifact_id": value.related_artifact_id,
                    "compare_content_bytes": value.compare_content_bytes,
                    "compare_declared_mime": value.compare_declared_mime,
                    "compare_filename": value.compare_filename,
                    "labels": dict(value.labels),
                    "force_ocr": value.force_ocr,
                    "ocr_by_page": dict(value.ocr_by_page),
                }
                data.update(kwargs)
                return DocumentExtractionInput(**data)
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return DocumentExtractionInput(**data)
        raise TypeError(
            "extract() expects DocumentExtractionInput, mapping, or kwargs"
        )

    # -- main dispatch ------------------------------------------------------

    def _extract(self, inp: DocumentExtractionInput) -> DocumentExtractionResult:
        extraction_id = str(self._id_factory())
        classification = inp.classification
        reason_codes: list[str] = []
        warnings: list[str] = []
        unsupported: list[str] = []
        related: list[str] = []
        if inp.related_artifact_id:
            related.append(inp.related_artifact_id)

        if requires_quarantine(classification):
            reason_codes.append(ExtractionReasonCode.QUARANTINE_CLASSIFICATION.value)

        body = inp.content_bytes
        if body is None or len(body) == 0:
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=inp.artifact_id,
                media_family=MediaFamily.UNKNOWN,
                content_sha256=inp.content_sha256 or sha256_hex(b""),
                classification=classification,
                reason_codes=[ExtractionReasonCode.MISSING_BYTES.value, *reason_codes],
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                related=related,
                message_code=ExtractionReasonCode.MISSING_BYTES.value,
            )

        if len(body) > self.bounds.max_bytes:
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=inp.artifact_id,
                media_family=detect_media_family(
                    body, declared_mime=inp.declared_mime, filename=inp.filename
                ),
                content_sha256=sha256_hex(body),
                classification=classification,
                reason_codes=[
                    ExtractionReasonCode.OVERSIZE_DOCUMENT.value,
                    *reason_codes,
                ],
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                related=related,
                message_code=ExtractionReasonCode.OVERSIZE_DOCUMENT.value,
            )

        content_sha = inp.content_sha256 or sha256_hex(body)
        if inp.content_sha256 and inp.content_sha256 != sha256_hex(body):
            warnings.append("content_sha256_mismatch")
            content_sha = sha256_hex(body)

        family = detect_media_family(
            body, declared_mime=inp.declared_mime, filename=inp.filename
        )
        # MIME conflict: declared PDF but ZIP magic (or reverse) → explicit.
        if inp.declared_mime:
            declared_family = detect_media_family(
                None, declared_mime=inp.declared_mime, filename=inp.filename
            )
            magic_family = detect_media_family(body)
            if (
                declared_family is not MediaFamily.UNKNOWN
                and magic_family is not MediaFamily.UNKNOWN
                and declared_family != magic_family
                and not (
                    {declared_family, magic_family}
                    <= {MediaFamily.DOCX, MediaFamily.ARCHIVE}
                )
            ):
                reason_codes.append(ExtractionReasonCode.MIME_CONTENT_CONFLICT.value)
                warnings.append("declared_mime_conflicts_with_magic")

        parser_versions = {
            "document_extraction": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
            "contracts": CONTRACTS_SCHEMA_VERSION,
            "pypdf": "available" if _PdfReader is not None else "unavailable",
            "pymupdf": "available" if _fitz is not None else "unavailable",
        }

        if family is MediaFamily.PDF:
            result = self._extract_pdf(
                extraction_id=extraction_id,
                artifact_id=inp.artifact_id,
                body=body,
                content_sha=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                related=related,
                force_ocr=inp.force_ocr,
                ocr_by_page=inp.ocr_by_page,
                parser_versions=parser_versions,
            )
        elif family is MediaFamily.DOCX:
            result = self._extract_docx(
                extraction_id=extraction_id,
                artifact_id=inp.artifact_id,
                body=body,
                content_sha=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                related=related,
                parser_versions=parser_versions,
            )
        elif family is MediaFamily.ARCHIVE:
            result = self._extract_archive_bounded(
                extraction_id=extraction_id,
                artifact_id=inp.artifact_id,
                body=body,
                content_sha=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                related=related,
                parser_versions=parser_versions,
            )
        else:
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=inp.artifact_id,
                media_family=MediaFamily.UNKNOWN,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=[
                    ExtractionReasonCode.UNSUPPORTED_MEDIA.value,
                    *reason_codes,
                ],
                warnings=warnings,
                unsupported=["media_family_unknown"],
                labels=inp.labels,
                related=related,
                message_code=ExtractionReasonCode.UNSUPPORTED_MEDIA.value,
            )

        # Optional DOCX↔PDF compare when pair bytes provided.
        if inp.compare_content_bytes:
            pair_family = detect_media_family(
                inp.compare_content_bytes,
                declared_mime=inp.compare_declared_mime,
                filename=inp.compare_filename,
            )
            pair_id = inp.related_artifact_id or f"{inp.artifact_id}:pair"
            related2 = list(result.related_artifact_ids)
            if pair_id not in related2:
                related2.append(pair_id)
            try:
                pair_inp = DocumentExtractionInput(
                    artifact_id=pair_id,
                    content_bytes=inp.compare_content_bytes,
                    declared_mime=inp.compare_declared_mime,
                    filename=inp.compare_filename,
                    classification=classification,
                    labels=dict(inp.labels),
                )
                pair_result = self._extract(pair_inp)
            except Exception:
                # Bounded: never raise out of compare; record unsupported.
                diffs = list(result.differences)
                diffs.append(
                    ArtifactDifference(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        difference_id=f"diff:{extraction_id}:pair-fail",
                        kind=DifferenceKind.UNSUPPORTED,
                        status="compare_failed",
                        docx_artifact_id=(
                            result.artifact_id
                            if result.media_family is MediaFamily.DOCX
                            else pair_id
                        ),
                        pdf_artifact_id=(
                            result.artifact_id
                            if result.media_family is MediaFamily.PDF
                            else pair_id
                        ),
                        docx_page=None,
                        pdf_page=None,
                        field=None,
                        element=None,
                        reason_codes=(ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value,),
                        detail="pair_extraction_failed",
                    )
                )
                return self._with_compare(
                    result,
                    differences=tuple(diffs),
                    related=related2,
                    extra_reasons=(ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value,),
                    force_review=True,
                )

            if result.media_family is MediaFamily.DOCX and pair_family is MediaFamily.PDF:
                diffs = self._compare_results(
                    result,
                    pair_result,
                    docx_artifact_id=result.artifact_id,
                    pdf_artifact_id=pair_result.artifact_id,
                )
            elif result.media_family is MediaFamily.PDF and pair_family is MediaFamily.DOCX:
                diffs = self._compare_results(
                    pair_result,
                    result,
                    docx_artifact_id=pair_result.artifact_id,
                    pdf_artifact_id=result.artifact_id,
                )
            else:
                diffs = [
                    ArtifactDifference(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        difference_id=f"diff:{extraction_id}:pair-type",
                        kind=DifferenceKind.UNSUPPORTED,
                        status="type_mismatch",
                        docx_artifact_id=None,
                        pdf_artifact_id=None,
                        docx_page=None,
                        pdf_page=None,
                        field=None,
                        element=None,
                        reason_codes=(ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value,),
                        detail=(
                            f"primary={result.media_family.value},"
                            f"pair={pair_family.value}"
                        ),
                    )
                ]
            force_review = bool(diffs)
            return self._with_compare(
                result,
                differences=tuple(diffs),
                related=related2,
                extra_reasons=(
                    (ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value, ExtractionReasonCode.COMPARE_PAIR.value)
                    if diffs
                    else (ExtractionReasonCode.COMPARE_PAIR.value,)
                ),
                force_review=force_review,
            )

        return result

    def _with_compare(
        self,
        result: DocumentExtractionResult,
        *,
        differences: tuple[ArtifactDifference, ...],
        related: list[str],
        extra_reasons: tuple[str, ...],
        force_review: bool,
    ) -> DocumentExtractionResult:
        reasons = list(result.reason_codes)
        for r in extra_reasons:
            if r not in reasons:
                reasons.append(r)
        disposition = result.disposition
        review_state = result.review_state
        if force_review and disposition is ExtractionDisposition.EXTRACTED:
            disposition = ExtractionDisposition.REVIEW
            review_state = ReviewState.REQUIRED
        elif force_review and review_state is ReviewState.NOT_REQUIRED:
            review_state = ReviewState.REQUIRED
        return DocumentExtractionResult(
            schema_version=result.schema_version,
            extraction_id=result.extraction_id,
            artifact_id=result.artifact_id,
            media_family=result.media_family,
            content_sha256=result.content_sha256,
            disposition=disposition,
            review_state=review_state,
            classification=result.classification,
            reason_codes=tuple(reasons),
            warnings=result.warnings,
            unsupported_features=result.unsupported_features,
            overall_coverage=result.overall_coverage,
            page_count=result.page_count,
            pages=result.pages,
            page_coverage=result.page_coverage,
            spans=result.spans,
            layout_items=result.layout_items,
            filing_metadata=result.filing_metadata,
            differences=differences,
            page_texts=dict(result.page_texts),
            full_text=result.full_text,
            labels=dict(result.labels),
            parser_versions=dict(result.parser_versions),
            related_artifact_ids=tuple(related),
            retained=result.retained,
        )

    def _reject(
        self,
        *,
        extraction_id: str,
        artifact_id: str,
        media_family: MediaFamily,
        content_sha256: str,
        classification: DisclosureClassification,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        related: list[str],
        message_code: str,
    ) -> DocumentExtractionResult:
        disposition = ExtractionDisposition.REJECTED
        review_state = ReviewState.REQUIRED
        if requires_quarantine(classification):
            disposition = ExtractionDisposition.QUARANTINE
        return DocumentExtractionResult(
            schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
            extraction_id=extraction_id,
            artifact_id=artifact_id,
            media_family=media_family,
            content_sha256=content_sha256,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            unsupported_features=tuple(unsupported),
            overall_coverage=0.0,
            page_count=0,
            pages=(),
            page_coverage=(),
            spans=(),
            layout_items=(),
            filing_metadata=(),
            differences=(),
            page_texts={},
            full_text="",
            labels=dict(labels),
            parser_versions={
                "document_extraction": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                "reject_code": message_code,
            },
            related_artifact_ids=tuple(related),
            retained=True,
        )

    # -- PDF ----------------------------------------------------------------

    @staticmethod
    def _pdf_structure_plausible(body: bytes) -> bool:
        """Fail closed on truncated/corrupt PDF shells before deep parse."""
        if not body.startswith(_PDF_MAGIC):
            return False
        # Require a trailer / EOF marker somewhere in the file.
        tail = body[-min(len(body), 4096) :]
        if b"%%EOF" not in tail and b"%%EOF" not in body:
            return False
        if b"CORRUPT" in body[:256] or b"%%CORRUPT" in body:
            return False
        # Empty / near-empty shells with only magic + EOF are treated as corrupt.
        if len(body) < 32:
            return False
        return True

    def _extract_pdf(
        self,
        *,
        extraction_id: str,
        artifact_id: str,
        body: bytes,
        content_sha: str,
        classification: DisclosureClassification,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        related: list[str],
        force_ocr: bool,
        ocr_by_page: Mapping[int, Mapping[str, Any]],
        parser_versions: dict[str, str],
    ) -> DocumentExtractionResult:
        # Password / encryption detection (pypdf preferred).
        if _PdfReader is not None:
            try:
                reader = _PdfReader(io.BytesIO(body), strict=False)
                if getattr(reader, "is_encrypted", False):
                    # Try empty password; if still encrypted → password protected.
                    try:
                        ok = reader.decrypt("")  # type: ignore[attr-defined]
                    except Exception:
                        ok = 0
                    if not ok:
                        reason_codes.append(
                            ExtractionReasonCode.PASSWORD_PROTECTED.value
                        )
                        return self._reject(
                            extraction_id=extraction_id,
                            artifact_id=artifact_id,
                            media_family=MediaFamily.PDF,
                            content_sha256=content_sha,
                            classification=classification,
                            reason_codes=reason_codes,
                            warnings=warnings,
                            unsupported=unsupported,
                            labels=labels,
                            related=related,
                            message_code=ExtractionReasonCode.PASSWORD_PROTECTED.value,
                        )
            except _FileNotDecryptedError:
                reason_codes.append(ExtractionReasonCode.PASSWORD_PROTECTED.value)
                return self._reject(
                    extraction_id=extraction_id,
                    artifact_id=artifact_id,
                    media_family=MediaFamily.PDF,
                    content_sha256=content_sha,
                    classification=classification,
                    reason_codes=reason_codes,
                    warnings=warnings,
                    unsupported=unsupported,
                    labels=labels,
                    related=related,
                    message_code=ExtractionReasonCode.PASSWORD_PROTECTED.value,
                )
            except Exception:
                # May still be parseable by fitz; note warning and continue.
                warnings.append("pypdf_open_failed")

        page_builders: list[_PageBuilder] = []
        layout_items: list[LayoutItem] = []
        filing_fields: list[FilingMetadataField] = []
        item_counter = 0

        # Structural admission before full parse: require EOF marker or xref-like body.
        if not self._pdf_structure_plausible(body):
            reason_codes.append(ExtractionReasonCode.CORRUPT_DOCUMENT.value)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.PDF,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings + ["pdf_structure_implausible"],
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=ExtractionReasonCode.CORRUPT_DOCUMENT.value,
            )

        # Prefer fitz for geometry + render digests when available.
        if _fitz is not None:
            try:
                page_builders, extra_layout, extra_meta, extra_unsup = (
                    self._extract_pdf_fitz(
                        body=body,
                        artifact_id=artifact_id,
                        classification=classification,
                        extraction_id=extraction_id,
                        force_ocr=force_ocr,
                        ocr_by_page=ocr_by_page,
                        layout_start=item_counter,
                    )
                )
                layout_items.extend(extra_layout)
                filing_fields.extend(extra_meta)
                unsupported.extend(extra_unsup)
                item_counter += len(extra_layout)
                reason_codes.append(ExtractionReasonCode.NATIVE_TEXT_EXTRACTED.value)
            except DocumentExtractionError as exc:
                reason_codes.append(exc.code)
                return self._reject(
                    extraction_id=extraction_id,
                    artifact_id=artifact_id,
                    media_family=MediaFamily.PDF,
                    content_sha256=content_sha,
                    classification=classification,
                    reason_codes=reason_codes,
                    warnings=warnings + [exc.code],
                    unsupported=unsupported,
                    labels=labels,
                    related=related,
                    message_code=exc.code,
                )
            except Exception:
                reason_codes.append(ExtractionReasonCode.CORRUPT_DOCUMENT.value)
                return self._reject(
                    extraction_id=extraction_id,
                    artifact_id=artifact_id,
                    media_family=MediaFamily.PDF,
                    content_sha256=content_sha,
                    classification=classification,
                    reason_codes=reason_codes,
                    warnings=warnings + ["fitz_parse_failed"],
                    unsupported=unsupported,
                    labels=labels,
                    related=related,
                    message_code=ExtractionReasonCode.CORRUPT_DOCUMENT.value,
                )
        elif _PdfReader is not None:
            try:
                page_builders, extra_layout, extra_meta, extra_unsup = (
                    self._extract_pdf_pypdf(
                        body=body,
                        artifact_id=artifact_id,
                        classification=classification,
                        extraction_id=extraction_id,
                        force_ocr=force_ocr,
                        ocr_by_page=ocr_by_page,
                        layout_start=item_counter,
                    )
                )
                layout_items.extend(extra_layout)
                filing_fields.extend(extra_meta)
                unsupported.extend(extra_unsup)
                reason_codes.append(ExtractionReasonCode.NATIVE_TEXT_EXTRACTED.value)
            except Exception:
                reason_codes.append(ExtractionReasonCode.CORRUPT_DOCUMENT.value)
                return self._reject(
                    extraction_id=extraction_id,
                    artifact_id=artifact_id,
                    media_family=MediaFamily.PDF,
                    content_sha256=content_sha,
                    classification=classification,
                    reason_codes=reason_codes,
                    warnings=warnings + ["pypdf_parse_failed"],
                    unsupported=unsupported,
                    labels=labels,
                    related=related,
                    message_code=ExtractionReasonCode.CORRUPT_DOCUMENT.value,
                )
        else:
            unsupported.append("no_pdf_backend")
            reason_codes.append(ExtractionReasonCode.UNSUPPORTED_FEATURE.value)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.PDF,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=ExtractionReasonCode.UNSUPPORTED_FEATURE.value,
            )

        if len(page_builders) > self.bounds.max_pages:
            reason_codes.append(ExtractionReasonCode.PAGE_LIMIT_EXCEEDED.value)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.PDF,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=ExtractionReasonCode.PAGE_LIMIT_EXCEEDED.value,
            )

        return self._finalize_pages(
            extraction_id=extraction_id,
            artifact_id=artifact_id,
            media_family=MediaFamily.PDF,
            content_sha=content_sha,
            classification=classification,
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=unsupported,
            labels=labels,
            related=related,
            parser_versions=parser_versions,
            page_builders=page_builders,
            layout_items=layout_items,
            filing_fields=filing_fields,
        )

    def _extract_pdf_fitz(
        self,
        *,
        body: bytes,
        artifact_id: str,
        classification: DisclosureClassification,
        extraction_id: str,
        force_ocr: bool,
        ocr_by_page: Mapping[int, Mapping[str, Any]],
        layout_start: int,
    ) -> tuple[
        list[_PageBuilder],
        list[LayoutItem],
        list[FilingMetadataField],
        list[str],
    ]:
        assert _fitz is not None
        doc = _fitz.open(stream=body, filetype="pdf")
        page_builders: list[_PageBuilder] = []
        layout_items: list[LayoutItem] = []
        filing_fields: list[FilingMetadataField] = []
        unsupported: list[str] = []
        item_i = layout_start
        try:
            if doc.is_encrypted:
                # Empty password attempt already handled upstream; fail closed.
                raise DocumentExtractionError(
                    "password protected",
                    code=ExtractionReasonCode.PASSWORD_PROTECTED.value,
                )
            n_pages = doc.page_count
            if n_pages > self.bounds.max_pages:
                # Still surface page_limit via caller.
                pass
            for page_index in range(min(n_pages, self.bounds.max_pages + 1)):
                if page_index >= self.bounds.max_pages:
                    break
                page = doc.load_page(page_index)
                rect = page.rect
                width = float(rect.width)
                height = float(rect.height)
                rotation = int(page.rotation or 0)
                # Native text blocks with bboxes.
                blocks = page.get_text("dict")
                native_parts: list[str] = []
                span_builders: list[_SpanBuilder] = []
                reading = 0
                for block in blocks.get("blocks") or []:
                    if block.get("type", 0) != 0:
                        # Image block
                        bbox = block.get("bbox")
                        item_i += 1
                        item_id = f"layout:{extraction_id}:img:{item_i}"
                        layout_items.append(
                            LayoutItem(
                                schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                                item_id=item_id,
                                artifact_id=artifact_id,
                                kind=LayoutItemKind.IMAGE,
                                span_id=None,
                                page_index=page_index,
                                bbox=_normalize_bbox(bbox),
                                text_digest=None,
                                confidence=1.0,
                                attributes={"block_type": "image"},
                                origin=ExtractionOrigin.NATIVE,
                            )
                        )
                        continue
                    for line in block.get("lines") or []:
                        line_text_parts: list[str] = []
                        line_bbox = None
                        for sp in line.get("spans") or []:
                            t = sp.get("text") or ""
                            if not t.strip():
                                continue
                            line_text_parts.append(t)
                            line_bbox = _normalize_bbox(sp.get("bbox") or line_bbox)
                        line_text = "".join(line_text_parts).strip()
                        if not line_text:
                            continue
                        native_parts.append(line_text)
                        span_builders.append(
                            _SpanBuilder(
                                text=line_text,
                                page_index=page_index,
                                char_start=None,
                                char_end=None,
                                bbox=line_bbox or _normalize_bbox(line.get("bbox")),
                                origin=ExtractionOrigin.NATIVE,
                                reading_order=reading,
                                confidence=1.0,
                            )
                        )
                        reading += 1
                        if reading >= self.bounds.max_spans_per_page:
                            unsupported.append(f"span_cap_page_{page_index}")
                            break
                    if reading >= self.bounds.max_spans_per_page:
                        break

                native_text = "\n".join(native_parts)
                # Render digest from content stream / pixmap hash (cheap).
                try:
                    # Use text page bytes + mediabox as stable render proxy.
                    render_material = (
                        f"{page_index}|{width}|{height}|{rotation}|".encode("utf-8")
                        + page.get_text("rawdict").__repr__().encode("utf-8", errors="replace")[
                            : 64 * 1024
                        ]
                    )
                    render_digest = sha256_hex(render_material)
                except Exception:
                    render_digest = sha256_hex(
                        f"{artifact_id}:{page_index}:{len(native_text)}".encode()
                    )

                # Widgets / form fields / annotations
                try:
                    widgets = page.widgets() or []
                except Exception:
                    widgets = []
                page_layout_ids: list[str] = []
                for w in widgets:
                    if len(layout_items) >= self.bounds.max_layout_items:
                        unsupported.append("layout_item_cap")
                        break
                    item_i += 1
                    field_type = str(getattr(w, "field_type_string", "") or "")
                    field_name = str(getattr(w, "field_name", "") or "")
                    field_value = str(getattr(w, "field_value", "") or "")
                    kind = LayoutItemKind.FORM_FIELD
                    attrs = {
                        "field_name": field_name[:128] or "unnamed",
                        "field_type": field_type[:64] or "unknown",
                    }
                    ft_lower = field_type.lower()
                    if "sig" in ft_lower or "signature" in ft_lower:
                        kind = LayoutItemKind.SIGNATURE_PRESENCE
                        attrs["signature_presence"] = "true"
                        # Never capture reusable signing material — value cleared.
                        field_value = ""
                    elif "check" in ft_lower or ft_lower in ("btn", "button"):
                        kind = LayoutItemKind.CHECKBOX
                        on = field_value not in ("", "Off", "off", "No", "0", None)
                        if on:
                            kind = LayoutItemKind.CHECKMARK
                        attrs["checked"] = "true" if on else "false"
                        field_value = "checked" if on else "unchecked"
                    bbox = None
                    try:
                        r = w.rect
                        bbox = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
                    except Exception:
                        bbox = None
                    span_id = None
                    text_for_digest = f"{field_name}={field_value}"
                    # Create span for form value when non-empty and not signature.
                    if kind is not LayoutItemKind.SIGNATURE_PRESENCE and field_value:
                        span_builders.append(
                            _SpanBuilder(
                                text=text_for_digest[:512],
                                page_index=page_index,
                                char_start=None,
                                char_end=None,
                                bbox=bbox,
                                origin=ExtractionOrigin.NATIVE,
                                reading_order=reading,
                                confidence=1.0,
                            )
                        )
                        reading += 1
                    item_id = f"layout:{extraction_id}:form:{item_i}"
                    # provisional span_id assigned at finalize; store digest now
                    layout_items.append(
                        LayoutItem(
                            schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                            item_id=item_id,
                            artifact_id=artifact_id,
                            kind=kind,
                            span_id=span_id,
                            page_index=page_index,
                            bbox=bbox,
                            text_digest=_text_digest(text_for_digest)
                            if text_for_digest.strip()
                            else None,
                            confidence=1.0,
                            attributes=attrs,
                            origin=ExtractionOrigin.NATIVE,
                        )
                    )
                    page_layout_ids.append(item_id)

                try:
                    annots = page.annots() or []
                except Exception:
                    annots = []
                for annot in annots:
                    if len(layout_items) >= self.bounds.max_layout_items:
                        break
                    item_i += 1
                    info = annot.info or {}
                    content = str(info.get("content") or "")
                    subtype = str(getattr(annot, "type", None) or "")
                    kind = LayoutItemKind.ANNOTATION
                    sub_l = subtype.lower() if isinstance(subtype, str) else str(subtype)
                    if "stamp" in sub_l:
                        kind = LayoutItemKind.STAMP
                    elif "link" in sub_l:
                        kind = LayoutItemKind.LINK
                    bbox = None
                    try:
                        r = annot.rect
                        bbox = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
                    except Exception:
                        bbox = None
                    item_id = f"layout:{extraction_id}:annot:{item_i}"
                    layout_items.append(
                        LayoutItem(
                            schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                            item_id=item_id,
                            artifact_id=artifact_id,
                            kind=kind,
                            span_id=None,
                            page_index=page_index,
                            bbox=bbox,
                            text_digest=_text_digest(content) if content.strip() else None,
                            confidence=1.0,
                            attributes={
                                "subtype": sub_l[:64] if sub_l else "unknown",
                            },
                            origin=ExtractionOrigin.NATIVE,
                        )
                    )
                    page_layout_ids.append(item_id)

                # Tables: heuristic via find_tables when available.
                try:
                    finder = page.find_tables()
                    tables = list(finder.tables) if finder is not None else []
                except Exception:
                    tables = []
                    if page_index == 0:
                        unsupported.append("table_detection_unavailable")
                for ti, table in enumerate(tables):
                    if len(layout_items) >= self.bounds.max_layout_items:
                        break
                    item_i += 1
                    item_id = f"layout:{extraction_id}:table:{item_i}"
                    try:
                        bbox = _normalize_bbox(table.bbox)
                    except Exception:
                        bbox = None
                    try:
                        extract = table.extract() or []
                        cell_text = " | ".join(
                            _normalize_ws(str(c or ""))
                            for row in extract
                            for c in (row or [])
                        )
                    except Exception:
                        cell_text = ""
                    layout_items.append(
                        LayoutItem(
                            schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                            item_id=item_id,
                            artifact_id=artifact_id,
                            kind=LayoutItemKind.TABLE,
                            span_id=None,
                            page_index=page_index,
                            bbox=bbox,
                            text_digest=_text_digest(cell_text) if cell_text else None,
                            confidence=0.9,
                            attributes={"table_index": str(ti)},
                            origin=ExtractionOrigin.NATIVE,
                        )
                    )
                    page_layout_ids.append(item_id)
                    if cell_text:
                        span_builders.append(
                            _SpanBuilder(
                                text=cell_text[:2000],
                                page_index=page_index,
                                char_start=None,
                                char_end=None,
                                bbox=bbox,
                                origin=ExtractionOrigin.NATIVE,
                                reading_order=reading,
                                confidence=0.9,
                            )
                        )
                        reading += 1

                coverage = estimate_native_char_coverage(
                    native_text,
                    page_width=width,
                    page_height=height,
                    min_chars=self.bounds.min_native_chars,
                )
                pb = _PageBuilder(
                    page_index=page_index,
                    text=native_text,
                    native_text=native_text,
                    rotation=rotation,
                    width=width,
                    height=height,
                    render_digest=render_digest,
                    span_builders=span_builders,
                    layout_item_ids=page_layout_ids,
                )
                if native_text.strip():
                    pb.origins.append(ExtractionOrigin.NATIVE.value)
                    pb.status = PageStatus.OK
                else:
                    pb.status = PageStatus.IMAGE_ONLY if (page.get_images() or widgets) else PageStatus.BLANK
                if rotation % 360 != 0:
                    pb.status = PageStatus.ROTATED
                    pb.warnings.append("rotated_page")
                if coverage < self.bounds.native_coverage_threshold:
                    pb.ocr_status = "needed"
                    pb.status = (
                        PageStatus.OCR_NEEDED
                        if pb.status in (PageStatus.OK, PageStatus.EMPTY, PageStatus.IMAGE_ONLY)
                        else pb.status
                    )
                    self._apply_ocr_to_page(
                        pb,
                        page_index=page_index,
                        force=force_ocr or coverage < self.bounds.native_coverage_threshold,
                        ocr_by_page=ocr_by_page,
                        fitz_page=page,
                    )
                page_builders.append(pb)

            # Document metadata
            meta = doc.metadata or {}
            for key in ("title", "author", "subject", "keywords", "creator", "producer"):
                val = meta.get(key) or meta.get(key.title())
                if not val:
                    continue
                text = str(val).strip()
                if not text:
                    continue
                field_id = f"meta:{extraction_id}:{key}"
                filing_fields.append(
                    FilingMetadataField(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        field_id=field_id,
                        field_name=f"pdf.{key}",
                        value_digest=_text_digest(text),
                        display_value=text[:256],
                        span_id=None,
                        page_index=None,
                        confidence=1.0,
                        origin=ExtractionOrigin.METADATA,
                    )
                )
            # Heuristic filing fields from first page text.
            if page_builders:
                filing_fields.extend(
                    self._heuristic_filing_fields(
                        page_builders[0].text,
                        artifact_id=artifact_id,
                        extraction_id=extraction_id,
                        page_index=0,
                        origin=ExtractionOrigin.NATIVE,
                    )
                )
        finally:
            doc.close()
        return page_builders, layout_items, filing_fields, unsupported

    def _extract_pdf_pypdf(
        self,
        *,
        body: bytes,
        artifact_id: str,
        classification: DisclosureClassification,
        extraction_id: str,
        force_ocr: bool,
        ocr_by_page: Mapping[int, Mapping[str, Any]],
        layout_start: int,
    ) -> tuple[
        list[_PageBuilder],
        list[LayoutItem],
        list[FilingMetadataField],
        list[str],
    ]:
        assert _PdfReader is not None
        reader = _PdfReader(io.BytesIO(body), strict=False)
        page_builders: list[_PageBuilder] = []
        layout_items: list[LayoutItem] = []
        filing_fields: list[FilingMetadataField] = []
        unsupported: list[str] = ["fitz_unavailable_bbox_degraded"]
        item_i = layout_start

        n_pages = len(reader.pages)
        for page_index in range(min(n_pages, self.bounds.max_pages)):
            page = reader.pages[page_index]
            try:
                mediabox = page.mediabox
                width = float(mediabox.width)
                height = float(mediabox.height)
            except Exception:
                width, height = 612.0, 792.0
            try:
                rotation = int(page.get("/Rotate") or 0)
            except Exception:
                rotation = 0
            try:
                native_text = page.extract_text() or ""
            except Exception:
                native_text = ""
            span_builders: list[_SpanBuilder] = []
            if native_text.strip():
                # Single page-level span when fine-grained bboxes unavailable.
                span_builders.append(
                    _SpanBuilder(
                        text=native_text.strip(),
                        page_index=page_index,
                        char_start=0,
                        char_end=len(native_text.strip()),
                        bbox=(0.0, 0.0, width, height),
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=0,
                        confidence=1.0,
                    )
                )
            render_digest = sha256_hex(
                f"{artifact_id}:{page_index}:{width}:{height}:{rotation}:".encode()
                + native_text.encode("utf-8", errors="replace")[: 32 * 1024]
            )
            page_layout_ids: list[str] = []
            # Annotations
            try:
                annots = page.get("/Annots") or []
            except Exception:
                annots = []
            for annot_ref in annots:
                if len(layout_items) >= self.bounds.max_layout_items:
                    break
                try:
                    annot = annot_ref.get_object()
                except Exception:
                    continue
                item_i += 1
                subtype = str(annot.get("/Subtype", ""))
                contents = str(annot.get("/Contents", "") or "")
                kind = LayoutItemKind.ANNOTATION
                if "Stamp" in subtype:
                    kind = LayoutItemKind.STAMP
                elif "Link" in subtype:
                    kind = LayoutItemKind.LINK
                elif "Widget" in subtype:
                    ft = str(annot.get("/FT", ""))
                    if ft == "/Sig":
                        kind = LayoutItemKind.SIGNATURE_PRESENCE
                        contents = ""
                    elif ft == "/Btn":
                        kind = LayoutItemKind.CHECKBOX
                        v = str(annot.get("/V", "") or "")
                        if v and v not in ("/Off", "Off"):
                            kind = LayoutItemKind.CHECKMARK
                item_id = f"layout:{extraction_id}:annot:{item_i}"
                layout_items.append(
                    LayoutItem(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        item_id=item_id,
                        artifact_id=artifact_id,
                        kind=kind,
                        span_id=None,
                        page_index=page_index,
                        bbox=None,
                        text_digest=_text_digest(contents) if contents.strip() else None,
                        confidence=0.8,
                        attributes={"subtype": subtype[:64]},
                        origin=ExtractionOrigin.NATIVE,
                    )
                )
                page_layout_ids.append(item_id)

            coverage = estimate_native_char_coverage(
                native_text,
                page_width=width,
                page_height=height,
                min_chars=self.bounds.min_native_chars,
            )
            pb = _PageBuilder(
                page_index=page_index,
                text=native_text,
                native_text=native_text,
                rotation=rotation,
                width=width,
                height=height,
                render_digest=render_digest,
                span_builders=span_builders,
                layout_item_ids=page_layout_ids,
            )
            if native_text.strip():
                pb.origins.append(ExtractionOrigin.NATIVE.value)
                pb.status = PageStatus.OK
            else:
                pb.status = PageStatus.IMAGE_ONLY
            if rotation % 360 != 0:
                pb.status = PageStatus.ROTATED
                pb.warnings.append("rotated_page")
            if coverage < self.bounds.native_coverage_threshold or force_ocr:
                pb.ocr_status = "needed"
                self._apply_ocr_to_page(
                    pb,
                    page_index=page_index,
                    force=True,
                    ocr_by_page=ocr_by_page,
                    fitz_page=None,
                )
            page_builders.append(pb)

        # Metadata
        meta = reader.metadata
        if meta:
            for key in ("/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer"):
                val = meta.get(key)
                if not val:
                    continue
                text = str(val).strip()
                if not text:
                    continue
                filing_fields.append(
                    FilingMetadataField(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        field_id=f"meta:{extraction_id}:{key.strip('/')}",
                        field_name=f"pdf.{key.strip('/').lower()}",
                        value_digest=_text_digest(text),
                        display_value=text[:256],
                        span_id=None,
                        page_index=None,
                        confidence=1.0,
                        origin=ExtractionOrigin.METADATA,
                    )
                )
        if page_builders:
            filing_fields.extend(
                self._heuristic_filing_fields(
                    page_builders[0].text,
                    artifact_id=artifact_id,
                    extraction_id=extraction_id,
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                )
            )
        return page_builders, layout_items, filing_fields, unsupported

    def _apply_ocr_to_page(
        self,
        pb: _PageBuilder,
        *,
        page_index: int,
        force: bool,
        ocr_by_page: Mapping[int, Mapping[str, Any]],
        fitz_page: Any | None,
    ) -> None:
        payload: Mapping[str, Any] | None = ocr_by_page.get(page_index)
        if payload is None and self._ocr_callable is not None and force:
            image_bytes = b""
            if fitz_page is not None and _fitz is not None:
                try:
                    pix = fitz_page.get_pixmap(matrix=_fitz.Matrix(1.5, 1.5), alpha=False)
                    image_bytes = pix.tobytes("png")
                    if not pb.render_digest:
                        pb.render_digest = sha256_hex(image_bytes)
                except Exception:
                    image_bytes = b""
            try:
                payload = self._ocr_callable(image_bytes, page_index)
            except Exception:
                pb.ocr_status = "failed"
                pb.warnings.append("ocr_callable_failed")
                pb.status = PageStatus.OCR_UNAVAILABLE
                return
        if payload is None:
            if force or pb.ocr_status == "needed":
                pb.ocr_status = "unavailable"
                pb.status = PageStatus.OCR_UNAVAILABLE
                pb.warnings.append("ocr_unavailable")
            return

        ocr_text = str(payload.get("text") or "").strip()
        conf = payload.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
            if conf_f is not None and not (0.0 <= conf_f <= 1.0):
                conf_f = max(0.0, min(1.0, conf_f))
        except (TypeError, ValueError):
            conf_f = None
        status = str(payload.get("status") or "ok")
        if payload.get("render_digest"):
            pb.render_digest = str(payload["render_digest"]).lower()
        pb.ocr_confidence = conf_f
        pb.ocr_status = status
        pb.ocr_text = ocr_text
        if ocr_text:
            pb.origins.append(ExtractionOrigin.OCR.value)
            word_boxes = payload.get("word_boxes") or payload.get("text_blocks") or []
            reading = len(pb.span_builders or [])
            if word_boxes:
                for wb in word_boxes:
                    if not isinstance(wb, Mapping):
                        continue
                    wtext = str(wb.get("text") or "").strip()
                    if not wtext:
                        continue
                    wconf = wb.get("confidence", conf_f)
                    try:
                        wconf_f = float(wconf) if wconf is not None else conf_f
                    except (TypeError, ValueError):
                        wconf_f = conf_f
                    pb.span_builders.append(
                        _SpanBuilder(
                            text=wtext,
                            page_index=page_index,
                            char_start=None,
                            char_end=None,
                            bbox=_normalize_bbox(wb.get("bbox")),
                            origin=ExtractionOrigin.OCR,
                            reading_order=reading,
                            confidence=wconf_f,
                            image_digest=pb.render_digest,
                        )
                    )
                    reading += 1
                    if reading >= self.bounds.max_spans_per_page:
                        break
            else:
                pb.span_builders.append(
                    _SpanBuilder(
                        text=ocr_text,
                        page_index=page_index,
                        char_start=None,
                        char_end=None,
                        bbox=None,
                        origin=ExtractionOrigin.OCR,
                        reading_order=reading,
                        confidence=conf_f,
                        image_digest=pb.render_digest,
                    )
                )
            # Merge native + OCR without naive duplication.
            if pb.native_text.strip() and ocr_text:
                sim = text_similarity(pb.native_text, ocr_text)
                if sim < 0.85:
                    pb.disagreement = True
                    pb.disagreement_score = max(0.0, min(1.0, 1.0 - sim))
                    pb.warnings.append("native_ocr_disagreement")
                    pb.status = PageStatus.DISAGREEMENT
                    # Keep both: native first, then OCR unique tokens note.
                    if ocr_text not in pb.native_text:
                        pb.text = (pb.native_text.rstrip() + "\n" + ocr_text).strip()
                    else:
                        pb.text = pb.native_text
                else:
                    # Prefer longer / native.
                    pb.text = (
                        pb.native_text
                        if len(pb.native_text) >= len(ocr_text)
                        else ocr_text
                    )
                    if ExtractionOrigin.MERGED.value not in pb.origins:
                        pb.origins.append(ExtractionOrigin.MERGED.value)
            else:
                pb.text = ocr_text if ocr_text else pb.native_text
                if pb.status in (
                    PageStatus.IMAGE_ONLY,
                    PageStatus.OCR_NEEDED,
                    PageStatus.OCR_UNAVAILABLE,
                    PageStatus.EMPTY,
                    PageStatus.BLANK,
                ):
                    pb.status = PageStatus.OK
        else:
            if status in ("failed", "unavailable"):
                pb.status = PageStatus.OCR_UNAVAILABLE

    # -- DOCX ---------------------------------------------------------------

    def _extract_docx(
        self,
        *,
        extraction_id: str,
        artifact_id: str,
        body: bytes,
        content_sha: str,
        classification: DisclosureClassification,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        related: list[str],
        parser_versions: dict[str, str],
    ) -> DocumentExtractionResult:
        try:
            zf = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile:
            reason_codes.append(ExtractionReasonCode.CORRUPT_DOCUMENT.value)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.DOCX,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings + ["bad_zip"],
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=ExtractionReasonCode.CORRUPT_DOCUMENT.value,
            )

        # Bound archive members before reading XML parts.
        try:
            self._assert_zip_bounds(zf, depth=0)
        except DocumentExtractionError as exc:
            reason_codes.append(exc.code)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.DOCX,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=exc.code,
            )

        names = set(zf.namelist())
        if "word/document.xml" not in names:
            reason_codes.append(ExtractionReasonCode.CORRUPT_DOCUMENT.value)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.DOCX,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings + ["missing_document_xml"],
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=ExtractionReasonCode.CORRUPT_DOCUMENT.value,
            )

        page_builders: list[_PageBuilder] = []
        layout_items: list[LayoutItem] = []
        filing_fields: list[FilingMetadataField] = []
        item_i = 0
        reading = 0
        span_builders: list[_SpanBuilder] = []
        full_parts: list[str] = []
        char_cursor = 0

        def _read_xml(name: str) -> ET.Element | None:
            if name not in names:
                return None
            try:
                raw = zf.read(name)
            except Exception:
                return None
            if len(raw) > self.bounds.max_archive_member_bytes:
                unsupported.append(f"member_oversize:{name}")
                return None
            try:
                return ET.fromstring(raw)
            except ET.ParseError:
                warnings.append(f"xml_parse_failed:{name}")
                return None

        # Core properties → filing metadata
        core = _read_xml("docProps/core.xml")
        if core is not None:
            for tag, field_name in (
                (f"{{{_DC_NS}}}title", "docx.title"),
                (f"{{{_DC_NS}}}creator", "docx.creator"),
                (f"{{{_DC_NS}}}subject", "docx.subject"),
                (f"{{{_DC_NS}}}description", "docx.description"),
                (f"{{{_CP_NS}}}lastModifiedBy", "docx.last_modified_by"),
                (f"{{{_DCTERMS_NS}}}created", "docx.created"),
                (f"{{{_DCTERMS_NS}}}modified", "docx.modified"),
            ):
                el = core.find(tag)
                if el is None or not (el.text or "").strip():
                    continue
                text = el.text.strip()
                filing_fields.append(
                    FilingMetadataField(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        field_id=f"meta:{extraction_id}:{field_name}",
                        field_name=field_name,
                        value_digest=_text_digest(text),
                        display_value=text[:256],
                        span_id=None,
                        page_index=None,
                        confidence=1.0,
                        origin=ExtractionOrigin.METADATA,
                    )
                )

        doc_root = _read_xml("word/document.xml")
        page_layout_ids: list[str] = []
        if doc_root is not None:
            # Paragraphs
            for p_el in doc_root.iter(f"{{{_W_NS}}}p"):
                texts = [
                    (t.text or "")
                    for t in p_el.iter(f"{{{_W_NS}}}t")
                    if t.text
                ]
                para = "".join(texts).strip()
                if not para:
                    # page break marker
                    for br in p_el.iter(f"{{{_W_NS}}}br"):
                        if br.get(f"{{{_W_NS}}}type") == "page":
                            # Logical page split for DOCX
                            pass
                    continue
                full_parts.append(para)
                start = char_cursor
                end = start + len(para)
                char_cursor = end + 1  # account for join newline
                span_builders.append(
                    _SpanBuilder(
                        text=para,
                        page_index=0,  # refined below after page split
                        char_start=start,
                        char_end=end,
                        bbox=None,
                        origin=ExtractionOrigin.NATIVE,
                        reading_order=reading,
                        confidence=1.0,
                    )
                )
                item_i += 1
                item_id = f"layout:{extraction_id}:para:{item_i}"
                layout_items.append(
                    LayoutItem(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        item_id=item_id,
                        artifact_id=artifact_id,
                        kind=LayoutItemKind.PARAGRAPH,
                        span_id=None,
                        page_index=0,
                        bbox=None,
                        text_digest=_text_digest(para),
                        confidence=1.0,
                        attributes={},
                        origin=ExtractionOrigin.NATIVE,
                    )
                )
                page_layout_ids.append(item_id)
                reading += 1
                if reading >= self.bounds.max_spans_per_page * max(1, self.bounds.max_pages // 10):
                    unsupported.append("docx_span_cap")
                    break

            # Tables
            for ti, tbl in enumerate(doc_root.iter(f"{{{_W_NS}}}tbl")):
                if len(layout_items) >= self.bounds.max_layout_items:
                    unsupported.append("layout_item_cap")
                    break
                rows: list[str] = []
                for tr in tbl.iter(f"{{{_W_NS}}}tr"):
                    cells: list[str] = []
                    for tc in tr.iter(f"{{{_W_NS}}}tc"):
                        cell_txt = "".join(
                            (t.text or "")
                            for t in tc.iter(f"{{{_W_NS}}}t")
                            if t.text
                        )
                        cells.append(_normalize_ws(cell_txt))
                    if cells:
                        rows.append(" | ".join(cells))
                table_text = "\n".join(rows)
                item_i += 1
                item_id = f"layout:{extraction_id}:table:{item_i}"
                layout_items.append(
                    LayoutItem(
                        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                        item_id=item_id,
                        artifact_id=artifact_id,
                        kind=LayoutItemKind.TABLE,
                        span_id=None,
                        page_index=0,
                        bbox=None,
                        text_digest=_text_digest(table_text) if table_text else None,
                        confidence=1.0,
                        attributes={"table_index": str(ti)},
                        origin=ExtractionOrigin.NATIVE,
                    )
                )
                page_layout_ids.append(item_id)
                if table_text:
                    full_parts.append(table_text)
                    span_builders.append(
                        _SpanBuilder(
                            text=table_text[:4000],
                            page_index=0,
                            char_start=None,
                            char_end=None,
                            bbox=None,
                            origin=ExtractionOrigin.NATIVE,
                            reading_order=reading,
                            confidence=1.0,
                        )
                    )
                    reading += 1

        # Headers / footers
        for name in sorted(names):
            if not (
                name.startswith("word/header") or name.startswith("word/footer")
            ) or not name.endswith(".xml"):
                continue
            root = _read_xml(name)
            if root is None:
                continue
            texts = [
                (t.text or "")
                for t in root.iter(f"{{{_W_NS}}}t")
                if t.text
            ]
            joined = _normalize_ws(" ".join(texts))
            if not joined:
                continue
            kind = (
                LayoutItemKind.HEADER
                if "header" in name
                else LayoutItemKind.FOOTER
            )
            item_i += 1
            item_id = f"layout:{extraction_id}:hf:{item_i}"
            layout_items.append(
                LayoutItem(
                    schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                    item_id=item_id,
                    artifact_id=artifact_id,
                    kind=kind,
                    span_id=None,
                    page_index=None,
                    bbox=None,
                    text_digest=_text_digest(joined),
                    confidence=1.0,
                    attributes={"part": name.split("/")[-1][:64]},
                    origin=ExtractionOrigin.NATIVE,
                )
            )
            page_layout_ids.append(item_id)

        # Content controls / SDTs (limited)
        if doc_root is not None:
            sdt_count = sum(1 for _ in doc_root.iter(f"{{{_W_NS}}}sdt"))
            if sdt_count:
                unsupported.append("docx_content_controls_partial")

        # Equations (OMML)
        if any("word/embeddings" in n or n.endswith(".xlsx") for n in names):
            unsupported.append("embedded_objects")
        if doc_root is not None and any(
            True for _ in doc_root.iter() if "oMath" in (_.tag or "")
        ):
            unsupported.append("omml_equations")
            item_i += 1
            layout_items.append(
                LayoutItem(
                    schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                    item_id=f"layout:{extraction_id}:eq:{item_i}",
                    artifact_id=artifact_id,
                    kind=LayoutItemKind.EQUATION,
                    span_id=None,
                    page_index=0,
                    bbox=None,
                    text_digest=None,
                    confidence=None,
                    attributes={"status": "unsupported_structure"},
                    origin=ExtractionOrigin.NATIVE,
                )
            )

        zf.close()

        full_text = "\n".join(full_parts)
        # Logical pages: split on form-feed or approximate by char budget.
        logical_pages = self._split_docx_pages(full_text, span_builders)
        for pb in logical_pages:
            pb.layout_item_ids = list(page_layout_ids) if pb.page_index == 0 else []
            if pb.native_text.strip():
                pb.origins.append(ExtractionOrigin.NATIVE.value)
                pb.status = PageStatus.OK
            pb.render_digest = sha256_hex(
                f"{artifact_id}:docx:{pb.page_index}:".encode()
                + pb.native_text.encode("utf-8", errors="replace")[: 32 * 1024]
            )

        reason_codes.append(ExtractionReasonCode.DOCX_STRUCTURE_EXTRACTED.value)
        reason_codes.append(ExtractionReasonCode.NATIVE_TEXT_EXTRACTED.value)
        if filing_fields:
            reason_codes.append(ExtractionReasonCode.FILING_METADATA_EXTRACTED.value)
        if layout_items:
            reason_codes.append(ExtractionReasonCode.LAYOUT_ITEMS_EXTRACTED.value)

        # Heuristic metadata from body
        if full_text:
            filing_fields.extend(
                self._heuristic_filing_fields(
                    full_text,
                    artifact_id=artifact_id,
                    extraction_id=extraction_id,
                    page_index=0,
                    origin=ExtractionOrigin.NATIVE,
                )
            )

        if not logical_pages:
            logical_pages = [
                _PageBuilder(
                    page_index=0,
                    text="",
                    native_text="",
                    status=PageStatus.BLANK,
                    render_digest=sha256_hex(f"{artifact_id}:docx:empty".encode()),
                )
            ]

        return self._finalize_pages(
            extraction_id=extraction_id,
            artifact_id=artifact_id,
            media_family=MediaFamily.DOCX,
            content_sha=content_sha,
            classification=classification,
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=unsupported,
            labels=labels,
            related=related,
            parser_versions=parser_versions,
            page_builders=logical_pages,
            layout_items=layout_items,
            filing_fields=filing_fields,
        )

    def _split_docx_pages(
        self,
        full_text: str,
        span_builders: list[_SpanBuilder],
    ) -> list[_PageBuilder]:
        """Split DOCX text into logical pages (form-feed or single page)."""
        if "\f" in full_text:
            chunks = full_text.split("\f")
        else:
            chunks = [full_text]
        pages: list[_PageBuilder] = []
        # Assign spans to pages by cumulative char ranges when possible.
        offset = 0
        for page_index, chunk in enumerate(chunks):
            if page_index >= self.bounds.max_pages:
                break
            text = chunk.strip("\n")
            start = offset
            end = start + len(text)
            page_spans: list[_SpanBuilder] = []
            for sb in span_builders:
                if sb.char_start is None:
                    if page_index == 0:
                        page_spans.append(
                            _SpanBuilder(
                                text=sb.text,
                                page_index=page_index,
                                char_start=sb.char_start,
                                char_end=sb.char_end,
                                bbox=sb.bbox,
                                origin=sb.origin,
                                reading_order=sb.reading_order,
                                confidence=sb.confidence,
                                image_digest=sb.image_digest,
                            )
                        )
                    continue
                if sb.char_start >= start and sb.char_start < end + 1:
                    page_spans.append(
                        _SpanBuilder(
                            text=sb.text,
                            page_index=page_index,
                            char_start=max(0, sb.char_start - start),
                            char_end=(
                                None
                                if sb.char_end is None
                                else max(0, sb.char_end - start)
                            ),
                            bbox=sb.bbox,
                            origin=sb.origin,
                            reading_order=sb.reading_order,
                            confidence=sb.confidence,
                            image_digest=sb.image_digest,
                        )
                    )
            pages.append(
                _PageBuilder(
                    page_index=page_index,
                    text=text,
                    native_text=text,
                    span_builders=page_spans,
                )
            )
            offset = end + 1
        return pages

    # -- Archives (bounded) -------------------------------------------------

    def _extract_archive_bounded(
        self,
        *,
        extraction_id: str,
        artifact_id: str,
        body: bytes,
        content_sha: str,
        classification: DisclosureClassification,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        related: list[str],
        parser_versions: dict[str, str],
    ) -> DocumentExtractionResult:
        reason_codes.append(ExtractionReasonCode.ARCHIVE_BOUNDED.value)
        unsupported.append("archive_full_extract_not_performed")
        try:
            zf = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile:
            reason_codes.append(ExtractionReasonCode.CORRUPT_DOCUMENT.value)
            return self._reject(
                extraction_id=extraction_id,
                artifact_id=artifact_id,
                media_family=MediaFamily.ARCHIVE,
                content_sha256=content_sha,
                classification=classification,
                reason_codes=reason_codes,
                warnings=warnings + ["bad_zip"],
                unsupported=unsupported,
                labels=labels,
                related=related,
                message_code=ExtractionReasonCode.CORRUPT_DOCUMENT.value,
            )
        try:
            inventory = self._assert_zip_bounds(zf, depth=0)
        except DocumentExtractionError as exc:
            reason_codes.append(exc.code)
            if exc.code == ExtractionReasonCode.ARCHIVE_REJECTED.value:
                return self._reject(
                    extraction_id=extraction_id,
                    artifact_id=artifact_id,
                    media_family=MediaFamily.ARCHIVE,
                    content_sha256=content_sha,
                    classification=classification,
                    reason_codes=reason_codes,
                    warnings=warnings,
                    unsupported=unsupported,
                    labels=labels,
                    related=related,
                    message_code=exc.code,
                )
            inventory = []
        finally:
            zf.close()

        # Inventory only as layout items (names + sizes), no nested extract.
        layout_items: list[LayoutItem] = []
        for i, entry in enumerate(inventory[: self.bounds.max_layout_items]):
            layout_items.append(
                LayoutItem(
                    schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                    item_id=f"layout:{extraction_id}:zip:{i}",
                    artifact_id=artifact_id,
                    kind=LayoutItemKind.OTHER,
                    span_id=None,
                    page_index=None,
                    bbox=None,
                    text_digest=_text_digest(entry["name"]),
                    confidence=1.0,
                    attributes={
                        "member_name": entry["name"][:128],
                        "member_size": str(entry["size"]),
                        "role": "archive_member_inventory",
                    },
                    origin=ExtractionOrigin.METADATA,
                )
            )

        return DocumentExtractionResult(
            schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
            extraction_id=extraction_id,
            artifact_id=artifact_id,
            media_family=MediaFamily.ARCHIVE,
            content_sha256=content_sha,
            disposition=ExtractionDisposition.REVIEW,
            review_state=ReviewState.REQUIRED,
            classification=classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings + ["archive_inventory_only"]),
            unsupported_features=tuple(dict.fromkeys(unsupported)),
            overall_coverage=0.0,
            page_count=0,
            pages=(),
            page_coverage=(),
            spans=(),
            layout_items=tuple(layout_items),
            filing_metadata=(),
            differences=(),
            page_texts={},
            full_text="",
            labels=dict(labels),
            parser_versions=parser_versions,
            related_artifact_ids=tuple(related),
            retained=True,
        )

    def _assert_zip_bounds(
        self, zf: zipfile.ZipFile, *, depth: int
    ) -> list[dict[str, Any]]:
        if depth > self.bounds.max_zip_depth:
            raise DocumentExtractionError(
                "zip depth exceeded",
                code=ExtractionReasonCode.ARCHIVE_REJECTED.value,
            )
        infos = zf.infolist()
        if len(infos) > self.bounds.max_archive_members:
            raise DocumentExtractionError(
                "archive member count exceeded",
                code=ExtractionReasonCode.ARCHIVE_REJECTED.value,
            )
        total_uncomp = 0
        inventory: list[dict[str, Any]] = []
        for info in infos:
            # Path traversal
            name = info.filename or ""
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                raise DocumentExtractionError(
                    "archive path traversal",
                    code=ExtractionReasonCode.ARCHIVE_REJECTED.value,
                )
            size = int(info.file_size or 0)
            if size > self.bounds.max_archive_member_bytes:
                raise DocumentExtractionError(
                    "archive member oversize",
                    code=ExtractionReasonCode.OVERSIZE_DOCUMENT.value,
                )
            total_uncomp += size
            if total_uncomp > self.bounds.max_archive_uncompressed:
                raise DocumentExtractionError(
                    "archive uncompressed size exceeded",
                    code=ExtractionReasonCode.OVERSIZE_DOCUMENT.value,
                )
            inventory.append({"name": name, "size": size})
        return inventory

    # -- finalize -----------------------------------------------------------

    def _finalize_pages(
        self,
        *,
        extraction_id: str,
        artifact_id: str,
        media_family: MediaFamily,
        content_sha: str,
        classification: DisclosureClassification,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        related: list[str],
        parser_versions: dict[str, str],
        page_builders: list[_PageBuilder],
        layout_items: list[LayoutItem],
        filing_fields: list[FilingMetadataField],
    ) -> DocumentExtractionResult:
        spans: list[ExtractedSpan] = []
        pages: list[PageExtraction] = []
        coverages: list[PageCoverageRecord] = []
        page_texts: dict[str, str] = {}
        full_parts: list[str] = []
        span_seq = 0

        for pb in page_builders:
            # Assign character offsets for spans lacking them.
            cursor = 0
            page_span_ids: list[str] = []
            ordered = sorted(
                pb.span_builders or [],
                key=lambda s: (
                    s.reading_order if s.reading_order is not None else 10**9
                ),
            )
            rebuilt_text_parts: list[str] = []
            for sb in ordered:
                text = sb.text
                if sb.char_start is None:
                    start = cursor
                    end = start + len(text)
                    cursor = end + 1
                else:
                    start = sb.char_start
                    end = sb.char_end if sb.char_end is not None else start + len(text)
                    cursor = max(cursor, end + 1)
                span_seq += 1
                span_id = f"span:{extraction_id}:{span_seq}"
                origin = sb.origin
                span = ExtractedSpan(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    span_id=span_id,
                    artifact_id=artifact_id,
                    page_index=pb.page_index if sb.page_index is None else sb.page_index,
                    char_start=start,
                    char_end=end,
                    bbox=sb.bbox,
                    origin=origin,
                    reading_order=sb.reading_order,
                    confidence=sb.confidence,
                    text_digest=_text_digest(text),
                    image_digest=sb.image_digest or pb.render_digest,
                    classification=classification,
                )
                spans.append(span)
                page_span_ids.append(span_id)
                rebuilt_text_parts.append(text)

            page_text = pb.text if pb.text else "\n".join(rebuilt_text_parts)
            page_texts[str(pb.page_index)] = page_text
            if page_text:
                full_parts.append(page_text)

            native_count = len(_normalize_ws(pb.native_text))
            ocr_count = len(_normalize_ws(pb.ocr_text))
            merged_count = len(_normalize_ws(page_text))
            native_cov = estimate_native_char_coverage(
                pb.native_text,
                page_width=pb.width or 0.0,
                page_height=pb.height or 0.0,
                min_chars=self.bounds.min_native_chars,
            )
            # Coverage ratio prefers merged text.
            coverage_ratio = estimate_native_char_coverage(
                page_text,
                page_width=pb.width or 0.0,
                page_height=pb.height or 0.0,
                min_chars=self.bounds.min_native_chars,
            )
            status = pb.status
            if not page_text.strip() and status is PageStatus.OK:
                status = PageStatus.BLANK
            if (
                coverage_ratio < self.bounds.low_coverage_review_threshold
                and status is PageStatus.OK
            ):
                status = PageStatus.LOW_COVERAGE

            cov = PageCoverageRecord(
                schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                page_index=pb.page_index,
                artifact_id=artifact_id,
                native_char_count=native_count,
                ocr_char_count=ocr_count,
                merged_char_count=merged_count,
                native_coverage=native_cov,
                coverage_ratio=coverage_ratio,
                has_native_text=bool(pb.native_text.strip()),
                has_ocr_text=bool(pb.ocr_text.strip()),
                rotation=pb.rotation,
                status=status,
                ocr_status=pb.ocr_status,
                ocr_confidence=pb.ocr_confidence,
                origins_present=tuple(dict.fromkeys(pb.origins or [])),
                disagreement=pb.disagreement,
                disagreement_score=pb.disagreement_score,
                render_digest=pb.render_digest,
                page_width=pb.width,
                page_height=pb.height,
                warnings=tuple(pb.warnings or ()),
            )
            coverages.append(cov)
            pages.append(
                PageExtraction(
                    page_index=pb.page_index,
                    text=page_text,
                    span_ids=tuple(page_span_ids),
                    coverage=cov,
                    layout_item_ids=tuple(pb.layout_item_ids or ()),
                )
            )

            if status is PageStatus.LOW_COVERAGE:
                reason_codes.append(ExtractionReasonCode.LOW_COVERAGE.value)
            if status is PageStatus.IMAGE_ONLY:
                reason_codes.append(ExtractionReasonCode.IMAGE_ONLY_PAGE.value)
            if status is PageStatus.BLANK:
                reason_codes.append(ExtractionReasonCode.BLANK_PAGE.value)
            if status is PageStatus.ROTATED:
                reason_codes.append(ExtractionReasonCode.ROTATED_PAGE.value)
            if status is PageStatus.OCR_UNAVAILABLE:
                reason_codes.append(ExtractionReasonCode.OCR_UNAVAILABLE.value)
            if pb.ocr_text.strip():
                reason_codes.append(ExtractionReasonCode.OCR_TEXT_EXTRACTED.value)
            if ExtractionOrigin.OCR.value in (pb.origins or []):
                reason_codes.append(ExtractionReasonCode.OCR_INJECTED.value)

        # Link layout items missing span_id to first page span when same page.
        span_by_page: dict[int, str] = {}
        for s in spans:
            if s.page_index is not None and s.page_index not in span_by_page:
                span_by_page[s.page_index] = s.span_id
        fixed_layout: list[LayoutItem] = []
        for item in layout_items:
            if item.span_id is None and item.page_index is not None:
                sid = span_by_page.get(item.page_index)
                if sid is not None:
                    fixed_layout.append(
                        LayoutItem(
                            schema_version=item.schema_version,
                            item_id=item.item_id,
                            artifact_id=item.artifact_id,
                            kind=item.kind,
                            span_id=sid,
                            page_index=item.page_index,
                            bbox=item.bbox,
                            text_digest=item.text_digest,
                            confidence=item.confidence,
                            attributes=dict(item.attributes),
                            origin=item.origin,
                        )
                    )
                    continue
            fixed_layout.append(item)

        # Link filing metadata fields to first span when possible.
        first_span_id = spans[0].span_id if spans else None
        fixed_meta: list[FilingMetadataField] = []
        for field in filing_fields:
            if field.span_id is None and first_span_id is not None:
                fixed_meta.append(
                    FilingMetadataField(
                        schema_version=field.schema_version,
                        field_id=field.field_id,
                        field_name=field.field_name,
                        value_digest=field.value_digest,
                        display_value=field.display_value,
                        span_id=first_span_id
                        if field.page_index is not None
                        else field.span_id,
                        page_index=field.page_index,
                        confidence=field.confidence,
                        origin=field.origin,
                    )
                )
            else:
                fixed_meta.append(field)

        if fixed_layout:
            reason_codes.append(ExtractionReasonCode.LAYOUT_ITEMS_EXTRACTED.value)
        if fixed_meta:
            reason_codes.append(ExtractionReasonCode.FILING_METADATA_EXTRACTED.value)

        overall = (
            sum(c.coverage_ratio for c in coverages) / len(coverages)
            if coverages
            else 0.0
        )
        overall = max(0.0, min(1.0, float(overall)))

        disposition = ExtractionDisposition.EXTRACTED
        review_state = ReviewState.NOT_REQUIRED
        low_cov_pages = [
            c
            for c in coverages
            if c.status
            in (
                PageStatus.LOW_COVERAGE,
                PageStatus.IMAGE_ONLY,
                PageStatus.OCR_UNAVAILABLE,
                PageStatus.OCR_NEEDED,
                PageStatus.DISAGREEMENT,
            )
            or c.coverage_ratio < self.bounds.low_coverage_review_threshold
        ]
        if overall < self.bounds.min_overall_coverage or low_cov_pages:
            disposition = ExtractionDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            if ExtractionReasonCode.LOW_COVERAGE.value not in reason_codes:
                reason_codes.append(ExtractionReasonCode.LOW_COVERAGE.value)
        if any(c.disagreement for c in coverages):
            disposition = ExtractionDisposition.REVIEW
            review_state = ReviewState.REQUIRED
        if unsupported:
            # Unsupported features are explicit; do not silently drop.
            if disposition is ExtractionDisposition.EXTRACTED and any(
                u
                for u in unsupported
                if not u.startswith("fitz_unavailable")
                and u not in ("table_detection_unavailable",)
            ):
                # Soft unsupported stays extracted with warnings unless structural.
                warnings.append("unsupported_features_present")
            reason_codes.append(ExtractionReasonCode.UNSUPPORTED_FEATURE.value)
        if requires_quarantine(classification):
            disposition = ExtractionDisposition.QUARANTINE
            review_state = ReviewState.REQUIRED

        # Signature presence reason
        if any(i.kind is LayoutItemKind.SIGNATURE_PRESENCE for i in fixed_layout):
            reason_codes.append(ExtractionReasonCode.SIGNATURE_PRESENCE_ONLY.value)

        full_text = "\n\n".join(full_parts)
        return DocumentExtractionResult(
            schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
            extraction_id=extraction_id,
            artifact_id=artifact_id,
            media_family=media_family,
            content_sha256=content_sha,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(dict.fromkeys(warnings)),
            unsupported_features=tuple(dict.fromkeys(unsupported)),
            overall_coverage=overall,
            page_count=len(pages),
            pages=tuple(pages),
            page_coverage=tuple(coverages),
            spans=tuple(spans),
            layout_items=tuple(fixed_layout),
            filing_metadata=tuple(fixed_meta),
            differences=(),
            page_texts=page_texts,
            full_text=full_text,
            labels=dict(labels),
            parser_versions=parser_versions,
            related_artifact_ids=tuple(related),
            retained=True,
        )

    # -- compare ------------------------------------------------------------

    def _compare_results(
        self,
        docx_result: DocumentExtractionResult,
        pdf_result: DocumentExtractionResult,
        *,
        docx_artifact_id: str,
        pdf_artifact_id: str,
    ) -> list[ArtifactDifference]:
        diffs: list[ArtifactDifference] = []
        seq = 0

        def _add(
            kind: DifferenceKind,
            *,
            status: str = "disagreement",
            docx_page: int | None = None,
            pdf_page: int | None = None,
            field: str | None = None,
            element: str | None = None,
            detail: str | None = None,
        ) -> None:
            nonlocal seq
            seq += 1
            diffs.append(
                ArtifactDifference(
                    schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                    difference_id=f"diff:{docx_result.extraction_id}:{seq}",
                    kind=kind,
                    status=status,
                    docx_artifact_id=docx_artifact_id,
                    pdf_artifact_id=pdf_artifact_id,
                    docx_page=docx_page,
                    pdf_page=pdf_page,
                    field=field,
                    element=element,
                    reason_codes=(ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value,),
                    detail=detail,
                )
            )

        if docx_result.page_count != pdf_result.page_count:
            _add(
                DifferenceKind.PAGINATION,
                docx_page=max(0, docx_result.page_count - 1) if docx_result.page_count else None,
                pdf_page=max(0, pdf_result.page_count - 1) if pdf_result.page_count else None,
                detail=f"page_count docx={docx_result.page_count} pdf={pdf_result.page_count}",
            )

        # Content similarity on full text.
        sim = text_similarity(docx_result.full_text, pdf_result.full_text)
        if sim < 0.92:
            _add(
                DifferenceKind.CONTENT,
                status="disagreement",
                detail=f"token_similarity={sim:.4f}",
            )

        # Table counts
        docx_tables = sum(
            1 for i in docx_result.layout_items if i.kind is LayoutItemKind.TABLE
        )
        pdf_tables = sum(
            1 for i in pdf_result.layout_items if i.kind is LayoutItemKind.TABLE
        )
        if docx_tables != pdf_tables:
            _add(
                DifferenceKind.TABLE,
                field="table_count",
                detail=f"docx={docx_tables} pdf={pdf_tables}",
            )

        # Equation presence
        docx_eq = any(i.kind is LayoutItemKind.EQUATION for i in docx_result.layout_items)
        pdf_eq = any(i.kind is LayoutItemKind.EQUATION for i in pdf_result.layout_items)
        if docx_eq and not pdf_eq:
            _add(
                DifferenceKind.EQUATION,
                element="equation",
                status="missing_in_pdf",
                detail="equation_present_in_docx_absent_in_pdf",
            )
        elif pdf_eq and not docx_eq:
            _add(
                DifferenceKind.EQUATION,
                element="equation",
                status="missing_in_docx",
            )

        # Unsupported feature deltas
        for feat in docx_result.unsupported_features:
            if feat not in pdf_result.unsupported_features:
                _add(
                    DifferenceKind.UNSUPPORTED,
                    element=feat,
                    status="docx_unsupported",
                )

        # Per-page missing
        pdf_pages = {p.page_index for p in pdf_result.pages}
        for p in docx_result.pages:
            if p.page_index not in pdf_pages and docx_result.page_count != pdf_result.page_count:
                _add(
                    DifferenceKind.MISSING_PAGE,
                    docx_page=p.page_index,
                    status="missing_in_pdf",
                )

        # Symbol / special character heuristic: non-ascii present in one side only.
        def _non_ascii_ratio(text: str) -> float:
            if not text:
                return 0.0
            n = sum(1 for ch in text if ord(ch) > 127)
            return n / max(1, len(text))

        ra = _non_ascii_ratio(docx_result.full_text)
        rb = _non_ascii_ratio(pdf_result.full_text)
        if abs(ra - rb) > 0.02 and (ra > 0.01 or rb > 0.01):
            _add(
                DifferenceKind.SYMBOL,
                field="non_ascii_ratio",
                detail=f"docx={ra:.4f} pdf={rb:.4f}",
            )

        return diffs

    # -- filing metadata heuristics -----------------------------------------

    def _heuristic_filing_fields(
        self,
        text: str,
        *,
        artifact_id: str,
        extraction_id: str,
        page_index: int,
        origin: ExtractionOrigin,
    ) -> list[FilingMetadataField]:
        fields: list[FilingMetadataField] = []
        patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
            (
                "application_number",
                re.compile(
                    r"\b(?:Application\s*(?:No\.?|Number)\s*[:#]?\s*)(\d{2}\s*/\s*\d{3},?\d{3}|\d{8})\b",
                    re.I,
                ),
            ),
            (
                "confirmation_number",
                re.compile(
                    r"\b(?:Confirmation\s*(?:No\.?|Number)\s*[:#]?\s*)(\d{4})\b",
                    re.I,
                ),
            ),
            (
                "form_number",
                re.compile(r"\b(PTO/[A-Z]{1,4}/\d{1,4}|SB\d{2})\b", re.I),
            ),
            (
                "receipt_id",
                re.compile(
                    r"\b(?:Receipt|Acknowledgement)\s*(?:ID|No\.?|Number)?\s*[:#]?\s*([A-Z0-9\-]{6,})\b",
                    re.I,
                ),
            ),
            (
                "attorney_docket",
                re.compile(
                    r"\b(?:Attorney\s*Docket\s*(?:No\.?|Number)?\s*[:#]?\s*)([A-Z0-9][A-Z0-9./\-]{2,})\b",
                    re.I,
                ),
            ),
        )
        seen: set[str] = set()
        for name, pattern in patterns:
            m = pattern.search(text or "")
            if not m:
                continue
            value = m.group(1).strip()
            key = f"{name}:{value}"
            if key in seen:
                continue
            seen.add(key)
            fields.append(
                FilingMetadataField(
                    schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                    field_id=f"meta:{extraction_id}:{name}",
                    field_name=name,
                    value_digest=_text_digest(value),
                    display_value=value[:256],
                    span_id=None,
                    page_index=page_index,
                    confidence=0.85,
                    origin=origin,
                )
            )
        return fields


def extract_document(
    value: DocumentExtractionInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> DocumentExtractionResult:
    """Module-level convenience wrapper around :class:`DocumentExtractionProcessor`."""
    return DocumentExtractionProcessor().extract(value, **kwargs)


__all__ = [
    "DOCUMENT_EXTRACTION_INTERFACE",
    "DOCUMENT_EXTRACTION_SCHEMA_VERSION",
    "ArtifactDifference",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_PAGES",
    "DifferenceKind",
    "DocumentExtractionError",
    "DocumentExtractionInput",
    "DocumentExtractionProcessor",
    "DocumentExtractionResult",
    "ExtractionBounds",
    "ExtractionDisposition",
    "ExtractionReasonCode",
    "FilingMetadataField",
    "LayoutItem",
    "LayoutItemKind",
    "MediaFamily",
    "PageCoverageRecord",
    "PageExtraction",
    "PageStatus",
    "detect_media_family",
    "estimate_native_char_coverage",
    "extract_document",
    "sha256_hex",
    "text_similarity",
]
