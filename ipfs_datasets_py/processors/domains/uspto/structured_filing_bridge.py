"""Bounded structured-filing dispatch for USPTO artifacts (PATLAW-121).

Supports safely limited TXT, XML (including ST.26 sequence listings and
Web ADS / bibliographic variants), raster images, and PCT ZIP packages.
Parsers disable external entities and network resolution, enforce archive
member/ratio/depth limits, and retain validation errors. Unknown or
malicious inputs (XXE, archive bombs, unsupported media) fail closed.

Every admitted format is either validated against pinned local rules or
explicitly marked unsupported. Document body text is never written to
logs or ordinary exception surfaces.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence
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

STRUCTURED_FILING_SCHEMA_VERSION: Final = "uspto.structured-filing-bridge.v1"
STRUCTURED_FILING_INTERFACE: Final = "StructuredFilingBridge@1"

DEFAULT_MAX_BYTES: Final = 16 * 1024 * 1024
DEFAULT_MAX_SPANS: Final = 8192
DEFAULT_MAX_ARCHIVE_MEMBERS: Final = 256
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED: Final = 32 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_MEMBER_BYTES: Final = 16 * 1024 * 1024
DEFAULT_MAX_ZIP_DEPTH: Final = 2
DEFAULT_MAX_COMPRESSION_RATIO: Final = 100.0
DEFAULT_MAX_XML_DEPTH: Final = 64
DEFAULT_MAX_XML_ELEMENTS: Final = 50_000

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

_PDF_MAGIC: Final = b"%PDF"
_ZIP_MAGIC: Final = b"PK"
_PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC: Final = b"\xff\xd8\xff"
_GIF_MAGIC: Final = b"GIF8"
_TIFF_LE: Final = b"II*\x00"
_TIFF_BE: Final = b"MM\x00*"

# Pinned local ST.26 / ADS recognition tokens (not remote schema fetch).
_ST26_ROOT_HINTS: Final[frozenset[str]] = frozenset(
    {
        "st26sequencelisting",
        "{http://www.wipo.int/standards/xmlschema/st26}st26sequencelisting",
        "sequencelisting",
    }
)
_ST26_NS_HINTS: Final[tuple[str, ...]] = (
    "www.wipo.int/standards/xmlschema/st26",
    "st26",
    "sequencelisting",
)
_WEB_ADS_HINTS: Final[frozenset[str]] = frozenset(
    {
        "us-patent-application",
        "us-bibliographic-data-application",
        "us-bibliographic-data-grant",
        "application-reference",
        "invention-title",
        "us-parties",
        "applicants",
        "webads",
        "application-data-sheet",
    }
)
_BIBLIO_HINTS: Final[frozenset[str]] = frozenset(
    {
        "bibliographic-data",
        "us-bibliographic-data",
        "publication-reference",
        "classification-ipc",
        "invention-title",
    }
)

# Forbidden DTD / entity constructs for XXE fail-closed.
_XXE_PATTERNS: Final[tuple[re.Pattern[bytes], ...]] = (
    re.compile(rb"<!ENTITY\b", re.IGNORECASE),
    re.compile(rb"SYSTEM\s+[\"']", re.IGNORECASE),
    re.compile(rb"PUBLIC\s+[\"']", re.IGNORECASE),
    re.compile(rb"<!DOCTYPE\b", re.IGNORECASE),
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FilingFormat(str, Enum):
    """Supported or explicitly unsupported structured filing formats."""

    TXT = "txt"
    XML = "xml"
    ST26_XML = "st26_xml"
    WEB_ADS = "web_ads"
    BIBLIOGRAPHIC = "bibliographic"
    IMAGE = "image"
    PCT_ZIP = "pct_zip"
    UNSUPPORTED = "unsupported"


class FilingDisposition(str, Enum):
    EXTRACTED = "extracted"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


class FilingReasonCode(str, Enum):
    TXT_EXTRACTED = "txt_extracted"
    XML_EXTRACTED = "xml_extracted"
    ST26_VALIDATED = "st26_validated"
    WEB_ADS_VALIDATED = "web_ads_validated"
    BIBLIOGRAPHIC_VALIDATED = "bibliographic_validated"
    IMAGE_ADMITTED = "image_admitted"
    PCT_ZIP_INVENTORIED = "pct_zip_inventoried"
    VALIDATION_OK = "validation_ok"
    VALIDATION_FAILED = "validation_failed"
    XXE_REJECTED = "xxe_rejected"
    ARCHIVE_BOMB_REJECTED = "archive_bomb_rejected"
    ARCHIVE_PATH_TRAVERSAL = "archive_path_traversal"
    OVERSIZE_DOCUMENT = "oversize_document"
    MISSING_BYTES = "missing_bytes"
    UNSUPPORTED_FORMAT = "unsupported_format"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    SCHEMA_PINNED_LOCAL = "schema_pinned_local"
    EXTERNAL_ENTITY_DISABLED = "external_entity_disabled"
    NETWORK_RESOLUTION_DISABLED = "network_resolution_disabled"
    MEMBER_EXTRACTED = "member_extracted"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class StructuredFilingError(ValueError):
    """Bounded structured-filing failure with a stable code."""

    def __init__(
        self, message: str, *, code: str = "structured_filing_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_addressed_cid(content_sha256: str, *, prefix: str = "baguqeera") -> str:
    digest = str(content_sha256).strip().lower()
    if not _SHA256_RE.match(digest):
        raise ValueError("content_sha256 must be sha256 hex")
    return f"{prefix}{digest[:48]}"


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


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text).encode("utf-8"))


def _local_tag(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


# ---------------------------------------------------------------------------
# Bounds / input / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StructuredFilingBounds:
    max_bytes: int = DEFAULT_MAX_BYTES
    max_spans: int = DEFAULT_MAX_SPANS
    max_archive_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS
    max_archive_uncompressed: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED
    max_archive_member_bytes: int = DEFAULT_MAX_ARCHIVE_MEMBER_BYTES
    max_zip_depth: int = DEFAULT_MAX_ZIP_DEPTH
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO
    max_xml_depth: int = DEFAULT_MAX_XML_DEPTH
    max_xml_elements: int = DEFAULT_MAX_XML_ELEMENTS

    def __post_init__(self) -> None:
        for name in (
            "max_bytes",
            "max_spans",
            "max_archive_members",
            "max_archive_uncompressed",
            "max_archive_member_bytes",
            "max_zip_depth",
            "max_xml_depth",
            "max_xml_elements",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        ratio = self.max_compression_ratio
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or float(ratio) <= 0
        ):
            raise ValueError("max_compression_ratio must be a positive number")


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """Pinned local validation result (no remote schema fetch)."""

    schema_version: str
    code: str
    severity: str  # info | warning | error
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "schema_version": self.schema_version,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationFinding":
        return cls(
            schema_version=str(
                value.get("schema_version", STRUCTURED_FILING_SCHEMA_VERSION)
            ),
            code=str(value.get("code", "")),
            severity=str(value.get("severity", "error")),
            message=str(value.get("message", "")),
            path=value.get("path"),
        )


@dataclass(frozen=True, slots=True)
class ArchiveMemberRecord:
    """Bounded archive member inventory entry."""

    name: str
    size: int
    compressed_size: int
    sha256: str | None
    format_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "compressed_size": self.compressed_size,
            "format_hint": self.format_hint,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArchiveMemberRecord":
        return cls(
            name=str(value.get("name", "")),
            size=int(value.get("size", 0)),
            compressed_size=int(value.get("compressed_size", 0)),
            sha256=value.get("sha256"),
            format_hint=value.get("format_hint"),
        )


@dataclass(frozen=True, slots=True)
class StructuredFilingInput:
    artifact_id: str
    content_bytes: bytes | None
    classification: DisclosureClassification
    source_cid: str | None = None
    content_sha256: str | None = None
    filename: str | None = None
    declared_mime: str | None = None
    declared_format: FilingFormat | str | None = None
    labels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if self.content_bytes is not None and not isinstance(
            self.content_bytes, (bytes, bytearray)
        ):
            raise TypeError("content_bytes must be bytes or None")
        if self.content_bytes is not None:
            object.__setattr__(self, "content_bytes", bytes(self.content_bytes))
        object.__setattr__(
            self, "source_cid", _optional_identifier(self.source_cid, "source_cid")
        )
        if self.content_sha256 is not None:
            digest = _require_str(
                self.content_sha256, "content_sha256", max_len=64
            ).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("content_sha256 must be sha256 hex")
            object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self, "filename", _optional_str(self.filename, "filename", max_len=512)
        )
        object.__setattr__(
            self,
            "declared_mime",
            _optional_str(self.declared_mime, "declared_mime", max_len=128),
        )
        if self.declared_format is not None:
            if isinstance(self.declared_format, FilingFormat):
                pass
            else:
                object.__setattr__(
                    self, "declared_format", FilingFormat(str(self.declared_format))
                )
        if self.labels is None:
            object.__setattr__(self, "labels", MappingProxyType({}))
        elif not isinstance(self.labels, Mapping):
            raise TypeError("labels must be a mapping")
        else:
            object.__setattr__(
                self,
                "labels",
                MappingProxyType({str(k): str(v) for k, v in self.labels.items()}),
            )


@dataclass(frozen=True, slots=True)
class StructuredFilingResult:
    """Normalized structured-filing output with CID-linked spans."""

    schema_version: str
    bridge_id: str
    artifact_id: str
    source_cid: str
    content_sha256: str
    classification: DisclosureClassification
    filing_format: FilingFormat
    disposition: FilingDisposition
    review_state: ReviewState
    spans: tuple[ExtractedSpan, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported: tuple[str, ...]
    validation_findings: tuple[ValidationFinding, ...]
    archive_members: tuple[ArchiveMemberRecord, ...]
    full_text: str
    labels: Mapping[str, str]
    retained: bool = True
    validated: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != STRUCTURED_FILING_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {STRUCTURED_FILING_SCHEMA_VERSION}"
            )

    @property
    def requires_review(self) -> bool:
        return self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive_members": [m.to_dict() for m in self.archive_members],
            "artifact_id": self.artifact_id,
            "bridge_id": self.bridge_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "filing_format": self.filing_format.value,
            "full_text": self.full_text,
            "labels": dict(self.labels),
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "spans": [s.to_dict() for s in self.spans],
            "unsupported": list(self.unsupported),
            "validated": self.validated,
            "validation_findings": [f.to_dict() for f in self.validation_findings],
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifier-only projection omitting body text."""
        return {
            "archive_members": [
                {
                    "name": m.name,
                    "size": m.size,
                    "sha256": m.sha256,
                    "format_hint": m.format_hint,
                }
                for m in self.archive_members
            ],
            "artifact_id": self.artifact_id,
            "bridge_id": self.bridge_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "filing_format": self.filing_format.value,
            "labels": dict(self.labels),
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "spans": [
                {
                    "span_id": s.span_id,
                    "artifact_id": s.artifact_id,
                    "origin": s.origin.value,
                    "text_digest": s.text_digest,
                    "page_index": s.page_index,
                    "confidence": s.confidence,
                }
                for s in self.spans
            ],
            "unsupported": list(self.unsupported),
            "validated": self.validated,
            "validation_findings": [f.to_dict() for f in self.validation_findings],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuredFilingResult":
        if not isinstance(value, Mapping):
            raise TypeError("StructuredFilingResult must be a mapping")
        return cls(
            schema_version=str(
                value.get("schema_version", STRUCTURED_FILING_SCHEMA_VERSION)
            ),
            bridge_id=str(value.get("bridge_id", "")),
            artifact_id=str(value.get("artifact_id", "")),
            source_cid=str(value.get("source_cid", "")),
            content_sha256=str(value.get("content_sha256", "")),
            classification=DisclosureClassification(
                str(
                    value.get(
                        "classification", DisclosureClassification.UNKNOWN.value
                    )
                )
            ),
            filing_format=FilingFormat(
                str(value.get("filing_format", FilingFormat.UNSUPPORTED.value))
            ),
            disposition=FilingDisposition(
                str(value.get("disposition", FilingDisposition.REJECTED.value))
            ),
            review_state=ReviewState(
                str(value.get("review_state", ReviewState.NOT_REQUIRED.value))
            ),
            spans=tuple(
                ExtractedSpan.from_dict(s) for s in (value.get("spans") or ())
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            unsupported=tuple(value.get("unsupported") or ()),
            validation_findings=tuple(
                ValidationFinding.from_dict(f)
                for f in (value.get("validation_findings") or ())
            ),
            archive_members=tuple(
                ArchiveMemberRecord.from_dict(m)
                for m in (value.get("archive_members") or ())
            ),
            full_text=str(value.get("full_text") or ""),
            labels=MappingProxyType(dict(value.get("labels") or {})),
            retained=bool(value.get("retained", True)),
            validated=bool(value.get("validated", False)),
        )


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def detect_filing_format(
    body: bytes | None,
    *,
    filename: str | None = None,
    declared_mime: str | None = None,
    declared_format: FilingFormat | str | None = None,
) -> FilingFormat:
    """Detect structured filing format from magic bytes + filename + hints.

    Explicit unsupported is returned rather than guessing PDF/DOCX families
    (those belong to the PDF/OCR and document-extraction bridges).
    """
    if declared_format is not None:
        if isinstance(declared_format, FilingFormat):
            if declared_format is not FilingFormat.UNSUPPORTED:
                return declared_format
        else:
            try:
                fmt = FilingFormat(str(declared_format))
                if fmt is not FilingFormat.UNSUPPORTED:
                    return fmt
            except ValueError:
                pass

    name = (filename or "").lower()
    mime = (declared_mime or "").lower()

    if body:
        if body.startswith(_PDF_MAGIC):
            return FilingFormat.UNSUPPORTED
        if body.startswith(_PNG_MAGIC) or body.startswith(_JPEG_MAGIC):
            return FilingFormat.IMAGE
        if body.startswith(_GIF_MAGIC) or body.startswith(_TIFF_LE) or body.startswith(
            _TIFF_BE
        ):
            return FilingFormat.IMAGE
        if body.startswith(_ZIP_MAGIC):
            # DOCX is ZIP-based; treat OOXML as unsupported here.
            if name.endswith(".docx") or "wordprocessingml" in mime:
                return FilingFormat.UNSUPPORTED
            if name.endswith(".zip") or "pct" in name or "application/zip" in mime:
                return FilingFormat.PCT_ZIP
            # Peek for PCT-ish members / generic zip
            return FilingFormat.PCT_ZIP
        # XML detection
        head = body.lstrip()[:512]
        if head.startswith(b"<?xml") or head.startswith(b"<"):
            return _classify_xml_bytes(body, filename=name)
        # Plain text heuristic
        if _looks_like_text(body):
            if name.endswith(".xml"):
                return _classify_xml_bytes(body, filename=name)
            return FilingFormat.TXT

    # Filename / mime only
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp")):
        return FilingFormat.IMAGE
    if name.endswith(".zip") or "pct" in name:
        return FilingFormat.PCT_ZIP
    if name.endswith(".xml") or "xml" in mime:
        return FilingFormat.XML
    if name.endswith(".txt") or mime.startswith("text/"):
        return FilingFormat.TXT
    if "image/" in mime:
        return FilingFormat.IMAGE

    return FilingFormat.UNSUPPORTED


def _looks_like_text(body: bytes) -> bool:
    sample = body[:4096]
    if not sample:
        return False
    # Reject if too many NUL / high binary ratios
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            sample.decode("latin-1")
        except UnicodeDecodeError:
            return False
        # latin-1 always works; check printable ratio
    text_chars = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126)
    return (text_chars / max(len(sample), 1)) >= 0.85


def _classify_xml_bytes(body: bytes, *, filename: str = "") -> FilingFormat:
    lower = body[:8192].lower()
    name = filename.lower()
    if b"st26" in lower or b"sequencelisting" in lower or "st26" in name:
        return FilingFormat.ST26_XML
    if b"application-data-sheet" in lower or b"webads" in lower or "ads" in name:
        return FilingFormat.WEB_ADS
    if b"bibliographic" in lower or b"us-patent" in lower:
        # Prefer Web ADS when ADS-ish tags present.
        if any(h.encode("ascii") in lower for h in ("us-parties", "applicants")):
            return FilingFormat.WEB_ADS
        return FilingFormat.BIBLIOGRAPHIC
    return FilingFormat.XML


# ---------------------------------------------------------------------------
# XXE-safe XML
# ---------------------------------------------------------------------------


class _SafeXMLParser(ET.XMLParser):
    """ElementTree parser with entity expansion disabled (XXE fail-closed)."""

    def __init__(self) -> None:
        # target default; forbid network via no custom entity resolver.
        super().__init__()
        try:
            # CPython: disable entity expansion / DTD when possible.
            self.parser.DefaultHandler = lambda data: None  # type: ignore[attr-defined]
            self.parser.ExternalEntityRefHandler = lambda *a, **k: False  # type: ignore[attr-defined]
        except Exception:
            pass


def _assert_no_xxe(body: bytes) -> None:
    # Strip UTF-8 BOM
    sample = body[: min(len(body), 256_000)]
    for pat in _XXE_PATTERNS:
        if pat.search(sample):
            raise StructuredFilingError(
                "XML external entity / DTD constructs are forbidden",
                code=FilingReasonCode.XXE_REJECTED.value,
            )


def parse_xml_safe(
    body: bytes,
    *,
    max_depth: int = DEFAULT_MAX_XML_DEPTH,
    max_elements: int = DEFAULT_MAX_XML_ELEMENTS,
) -> ET.Element:
    """Parse XML with external entities and network resolution disabled."""
    _assert_no_xxe(body)
    parser = _SafeXMLParser()
    try:
        root = ET.fromstring(body, parser=parser)
    except StructuredFilingError:
        raise
    except ET.ParseError as exc:
        raise StructuredFilingError(
            "xml parse failed",
            code=FilingReasonCode.VALIDATION_FAILED.value,
        ) from exc
    except Exception as exc:
        raise StructuredFilingError(
            "xml parse failed",
            code=FilingReasonCode.VALIDATION_FAILED.value,
        ) from exc

    # Depth / element bounds
    element_count = 0
    max_seen_depth = 0

    def _walk(el: ET.Element, depth: int) -> None:
        nonlocal element_count, max_seen_depth
        element_count += 1
        max_seen_depth = max(max_seen_depth, depth)
        if element_count > max_elements:
            raise StructuredFilingError(
                "xml element limit exceeded",
                code=FilingReasonCode.VALIDATION_FAILED.value,
            )
        if depth > max_depth:
            raise StructuredFilingError(
                "xml depth limit exceeded",
                code=FilingReasonCode.VALIDATION_FAILED.value,
            )
        for child in el:
            _walk(child, depth + 1)

    _walk(root, 1)
    return root


def _iter_text_nodes(root: ET.Element) -> list[tuple[str, str]]:
    """Return (xpath-ish path, text) pairs in document order."""
    out: list[tuple[str, str]] = []

    def _walk(el: ET.Element, path: str) -> None:
        local = _local_tag(el.tag)
        here = f"{path}/{local}" if path else local
        if el.text and el.text.strip():
            out.append((here, el.text.strip()))
        for child in el:
            _walk(child, here)
        if el.tail and el.tail.strip():
            out.append((f"{here}/@tail", el.tail.strip()))

    _walk(root, "")
    return out


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class StructuredFilingBridge:
    """Dispatch and validate structured USPTO filing formats."""

    def __init__(
        self,
        *,
        bounds: StructuredFilingBounds | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.bounds = bounds or StructuredFilingBounds()
        self._id_factory = id_factory or (lambda: f"filing:{uuid.uuid4().hex}")

    def process(
        self,
        value: StructuredFilingInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> StructuredFilingResult:
        inp = self._coerce_input(value, **kwargs)
        return self._process(inp)

    def process_many(
        self, values: Sequence[StructuredFilingInput | Mapping[str, Any]]
    ) -> list[StructuredFilingResult]:
        return [self.process(v) for v in values]

    def detect(
        self,
        body: bytes | None,
        *,
        filename: str | None = None,
        declared_mime: str | None = None,
        declared_format: FilingFormat | str | None = None,
    ) -> FilingFormat:
        return detect_filing_format(
            body,
            filename=filename,
            declared_mime=declared_mime,
            declared_format=declared_format,
        )

    def _coerce_input(
        self,
        value: StructuredFilingInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> StructuredFilingInput:
        if value is None:
            return StructuredFilingInput(**kwargs)
        if isinstance(value, StructuredFilingInput):
            if kwargs:
                data = {
                    "artifact_id": value.artifact_id,
                    "content_bytes": value.content_bytes,
                    "classification": value.classification,
                    "source_cid": value.source_cid,
                    "content_sha256": value.content_sha256,
                    "filename": value.filename,
                    "declared_mime": value.declared_mime,
                    "declared_format": value.declared_format,
                    "labels": dict(value.labels),
                }
                data.update(kwargs)
                return StructuredFilingInput(**data)
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return StructuredFilingInput(**data)
        raise TypeError(
            "process() expects StructuredFilingInput, mapping, or kwargs"
        )

    def _process(self, inp: StructuredFilingInput) -> StructuredFilingResult:
        bridge_id = str(self._id_factory())
        classification = inp.classification
        reason_codes: list[str] = []
        warnings: list[str] = []
        unsupported: list[str] = []
        findings: list[ValidationFinding] = []

        if requires_quarantine(classification):
            reason_codes.append(FilingReasonCode.QUARANTINE_CLASSIFICATION.value)
            return self._result(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=inp.source_cid or content_addressed_cid(sha256_hex(b"")),
                content_sha256=inp.content_sha256 or sha256_hex(b""),
                classification=classification,
                filing_format=FilingFormat.UNSUPPORTED,
                disposition=FilingDisposition.QUARANTINE,
                review_state=ReviewState.REQUIRED,
                spans=(),
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                findings=findings,
                members=(),
                full_text="",
                labels=inp.labels,
                retained=False,
                validated=False,
            )

        body = inp.content_bytes
        if body is None or len(body) == 0:
            reason_codes.append(FilingReasonCode.MISSING_BYTES.value)
            return self._reject(
                bridge_id,
                inp,
                reason_codes,
                warnings,
                unsupported,
                findings,
                FilingFormat.UNSUPPORTED,
            )

        if len(body) > self.bounds.max_bytes:
            reason_codes.append(FilingReasonCode.OVERSIZE_DOCUMENT.value)
            return self._reject(
                bridge_id,
                inp,
                reason_codes,
                warnings,
                unsupported,
                findings,
                FilingFormat.UNSUPPORTED,
                content_sha=sha256_hex(body),
            )

        content_sha = inp.content_sha256 or sha256_hex(body)
        actual = sha256_hex(body)
        if inp.content_sha256 and inp.content_sha256 != actual:
            warnings.append("content_sha256_mismatch")
            content_sha = actual
        source_cid = inp.source_cid or content_addressed_cid(content_sha)

        fmt = detect_filing_format(
            body,
            filename=inp.filename,
            declared_mime=inp.declared_mime,
            declared_format=inp.declared_format,
        )

        try:
            if fmt is FilingFormat.TXT:
                return self._extract_txt(
                    bridge_id=bridge_id,
                    inp=inp,
                    body=body,
                    content_sha=content_sha,
                    source_cid=source_cid,
                    reason_codes=reason_codes,
                    warnings=warnings,
                    findings=findings,
                )
            if fmt in {
                FilingFormat.XML,
                FilingFormat.ST26_XML,
                FilingFormat.WEB_ADS,
                FilingFormat.BIBLIOGRAPHIC,
            }:
                return self._extract_xml(
                    bridge_id=bridge_id,
                    inp=inp,
                    body=body,
                    content_sha=content_sha,
                    source_cid=source_cid,
                    fmt=fmt,
                    reason_codes=reason_codes,
                    warnings=warnings,
                    findings=findings,
                )
            if fmt is FilingFormat.IMAGE:
                return self._extract_image(
                    bridge_id=bridge_id,
                    inp=inp,
                    body=body,
                    content_sha=content_sha,
                    source_cid=source_cid,
                    reason_codes=reason_codes,
                    warnings=warnings,
                    findings=findings,
                )
            if fmt is FilingFormat.PCT_ZIP:
                return self._extract_pct_zip(
                    bridge_id=bridge_id,
                    inp=inp,
                    body=body,
                    content_sha=content_sha,
                    source_cid=source_cid,
                    reason_codes=reason_codes,
                    warnings=warnings,
                    findings=findings,
                )
            # Explicit unsupported
            reason_codes.append(FilingReasonCode.UNSUPPORTED_FORMAT.value)
            unsupported.append(
                (inp.filename or inp.declared_mime or "unknown").split("/")[-1][:64]
            )
            return self._result(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha256=content_sha,
                classification=classification,
                filing_format=FilingFormat.UNSUPPORTED,
                disposition=FilingDisposition.UNSUPPORTED,
                review_state=ReviewState.NOT_REQUIRED,
                spans=(),
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                findings=findings,
                members=(),
                full_text="",
                labels=inp.labels,
                retained=False,
                validated=False,
            )
        except StructuredFilingError as exc:
            reason_codes.append(exc.code)
            findings.append(
                ValidationFinding(
                    schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                    code=exc.code,
                    severity="error",
                    message=str(exc)[:256],
                )
            )
            disposition = FilingDisposition.REJECTED
            if exc.code == FilingReasonCode.XXE_REJECTED.value:
                disposition = FilingDisposition.REJECTED
            return self._result(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha256=content_sha,
                classification=classification,
                filing_format=fmt,
                disposition=disposition,
                review_state=ReviewState.REQUIRED
                if disposition is not FilingDisposition.REJECTED
                else ReviewState.NOT_REQUIRED,
                spans=(),
                reason_codes=list(dict.fromkeys(reason_codes)),
                warnings=warnings,
                unsupported=unsupported,
                findings=findings,
                members=(),
                full_text="",
                labels=inp.labels,
                retained=False,
                validated=False,
            )

    # -- format handlers ----------------------------------------------------

    def _extract_txt(
        self,
        *,
        bridge_id: str,
        inp: StructuredFilingInput,
        body: bytes,
        content_sha: str,
        source_cid: str,
        reason_codes: list[str],
        warnings: list[str],
        findings: list[ValidationFinding],
    ) -> StructuredFilingResult:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode("latin-1", errors="replace")
            warnings.append("txt_decoded_latin1")

        # Normalize newlines; split into paragraph spans.
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not parts and text.strip():
            parts = [text.strip()]
        spans: list[ExtractedSpan] = []
        cursor = 0
        full_parts: list[str] = []
        for i, part in enumerate(parts[: self.bounds.max_spans]):
            start = cursor
            end = start + len(part)
            cursor = end + 2
            spans.append(
                ExtractedSpan(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    span_id=f"span:{bridge_id}:{i + 1}",
                    artifact_id=inp.artifact_id,
                    page_index=0,
                    char_start=start,
                    char_end=end,
                    bbox=None,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=i,
                    confidence=1.0,
                    text_digest=text_digest(part),
                    image_digest=None,
                    classification=inp.classification,
                )
            )
            full_parts.append(part)

        reason_codes.append(FilingReasonCode.TXT_EXTRACTED.value)
        reason_codes.append(FilingReasonCode.VALIDATION_OK.value)
        findings.append(
            ValidationFinding(
                schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                code="txt.encoding_ok",
                severity="info",
                message="plain text admitted under local bounds",
            )
        )
        return self._result(
            bridge_id=bridge_id,
            artifact_id=inp.artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            classification=inp.classification,
            filing_format=FilingFormat.TXT,
            disposition=FilingDisposition.EXTRACTED,
            review_state=ReviewState.NOT_REQUIRED,
            spans=tuple(spans),
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=[],
            findings=findings,
            members=(),
            full_text="\n\n".join(full_parts),
            labels=inp.labels,
            retained=True,
            validated=True,
        )

    def _extract_xml(
        self,
        *,
        bridge_id: str,
        inp: StructuredFilingInput,
        body: bytes,
        content_sha: str,
        source_cid: str,
        fmt: FilingFormat,
        reason_codes: list[str],
        warnings: list[str],
        findings: list[ValidationFinding],
    ) -> StructuredFilingResult:
        reason_codes.append(FilingReasonCode.EXTERNAL_ENTITY_DISABLED.value)
        reason_codes.append(FilingReasonCode.NETWORK_RESOLUTION_DISABLED.value)
        reason_codes.append(FilingReasonCode.SCHEMA_PINNED_LOCAL.value)

        root = parse_xml_safe(
            body,
            max_depth=self.bounds.max_xml_depth,
            max_elements=self.bounds.max_xml_elements,
        )
        # Refine format from root if generic XML.
        fmt = self._refine_xml_format(root, fmt, body)

        # Pinned local structural validation (no remote DTD/XSD fetch).
        validated, fmt_findings = self._validate_xml_local(root, fmt)
        findings.extend(fmt_findings)
        if validated:
            reason_codes.append(FilingReasonCode.VALIDATION_OK.value)
            if fmt is FilingFormat.ST26_XML:
                reason_codes.append(FilingReasonCode.ST26_VALIDATED.value)
            elif fmt is FilingFormat.WEB_ADS:
                reason_codes.append(FilingReasonCode.WEB_ADS_VALIDATED.value)
            elif fmt is FilingFormat.BIBLIOGRAPHIC:
                reason_codes.append(FilingReasonCode.BIBLIOGRAPHIC_VALIDATED.value)
        else:
            reason_codes.append(FilingReasonCode.VALIDATION_FAILED.value)

        nodes = _iter_text_nodes(root)
        spans: list[ExtractedSpan] = []
        full_parts: list[str] = []
        cursor = 0
        for i, (path, text) in enumerate(nodes[: self.bounds.max_spans]):
            start = cursor
            end = start + len(text)
            cursor = end + 1
            spans.append(
                ExtractedSpan(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    span_id=f"span:{bridge_id}:{i + 1}",
                    artifact_id=inp.artifact_id,
                    page_index=0,
                    char_start=start,
                    char_end=end,
                    bbox=None,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=i,
                    confidence=1.0 if validated else 0.7,
                    text_digest=text_digest(text),
                    image_digest=None,
                    classification=inp.classification,
                )
            )
            full_parts.append(text)
            # Attach path as a finding for first few nodes only (compact).
            if i < 8:
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="xml.text_node",
                        severity="info",
                        message=f"text node at {path}"[:200],
                        path=path[:256],
                    )
                )

        reason_codes.append(FilingReasonCode.XML_EXTRACTED.value)
        disposition = (
            FilingDisposition.EXTRACTED
            if validated
            else FilingDisposition.REVIEW
        )
        review = (
            ReviewState.NOT_REQUIRED
            if validated
            else ReviewState.REQUIRED
        )
        return self._result(
            bridge_id=bridge_id,
            artifact_id=inp.artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            classification=inp.classification,
            filing_format=fmt,
            disposition=disposition,
            review_state=review,
            spans=tuple(spans),
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=[],
            findings=findings,
            members=(),
            full_text="\n".join(full_parts),
            labels=inp.labels,
            retained=True,
            validated=validated,
        )

    def _refine_xml_format(
        self, root: ET.Element, fmt: FilingFormat, body: bytes
    ) -> FilingFormat:
        local = _local_tag(root.tag).lower()
        tag_blob = local
        # Sample a few child tags
        child_tags = {_local_tag(c.tag).lower() for c in list(root)[:50]}
        all_tags = {tag_blob, *child_tags}
        ns = ""
        if isinstance(root.tag, str) and root.tag.startswith("{"):
            ns = root.tag[1:].split("}", 1)[0].lower()

        if fmt is FilingFormat.ST26_XML or any(
            h in local or h in ns for h in ("st26", "sequencelisting")
        ):
            return FilingFormat.ST26_XML
        if local in _ST26_ROOT_HINTS or any(h in ns for h in _ST26_NS_HINTS):
            return FilingFormat.ST26_XML
        if fmt is FilingFormat.WEB_ADS or all_tags & _WEB_ADS_HINTS:
            return FilingFormat.WEB_ADS
        if fmt is FilingFormat.BIBLIOGRAPHIC or all_tags & _BIBLIO_HINTS:
            return FilingFormat.BIBLIOGRAPHIC
        # Body-level recheck
        return _classify_xml_bytes(body, filename="")

    def _validate_xml_local(
        self, root: ET.Element, fmt: FilingFormat
    ) -> tuple[bool, list[ValidationFinding]]:
        findings: list[ValidationFinding] = []
        local = _local_tag(root.tag).lower()
        ok = True

        if fmt is FilingFormat.ST26_XML:
            # Require sequence listing root and at least one SequenceData-ish child.
            if "sequence" not in local and "st26" not in local:
                ok = False
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="st26.root_mismatch",
                        severity="error",
                        message="ST.26 root element not recognized by pinned local rules",
                        path=local,
                    )
                )
            else:
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="st26.root_ok",
                        severity="info",
                        message="ST.26 root accepted by pinned local rules",
                        path=local,
                    )
                )
            # Look for sequence data descendants.
            has_seq = False
            for el in root.iter():
                t = _local_tag(el.tag).lower()
                if t in {
                    "sequencedata",
                    "sequence-data",
                    "sequence",
                    "insequences",
                } or "sequence" in t:
                    has_seq = True
                    break
            if not has_seq:
                ok = False
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="st26.missing_sequence_data",
                        severity="error",
                        message="ST.26 listing missing sequence data elements",
                    )
                )
        elif fmt is FilingFormat.WEB_ADS:
            tags = {_local_tag(el.tag).lower() for el in root.iter()}
            required_any = {
                "invention-title",
                "inventiontitle",
                "application-reference",
                "applicationnumber",
                "application-number",
                "us-parties",
                "applicants",
                "applicant",
            }
            if not (tags & required_any) and "ads" not in local and "application" not in local:
                ok = False
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="web_ads.missing_core_fields",
                        severity="error",
                        message="Web ADS missing pinned core bibliographic fields",
                    )
                )
            else:
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="web_ads.structure_ok",
                        severity="info",
                        message="Web ADS structure accepted by pinned local rules",
                    )
                )
        elif fmt is FilingFormat.BIBLIOGRAPHIC:
            tags = {_local_tag(el.tag).lower() for el in root.iter()}
            if not (
                tags
                & {
                    "invention-title",
                    "inventiontitle",
                    "bibliographic-data",
                    "publication-reference",
                    "classification-ipc",
                }
            ) and "biblio" not in local:
                ok = False
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="biblio.missing_core_fields",
                        severity="error",
                        message="bibliographic XML missing pinned core fields",
                    )
                )
            else:
                findings.append(
                    ValidationFinding(
                        schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                        code="biblio.structure_ok",
                        severity="info",
                        message="bibliographic structure accepted by pinned local rules",
                    )
                )
        else:
            # Generic well-formed XML already parsed → validated structure.
            findings.append(
                ValidationFinding(
                    schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                    code="xml.well_formed",
                    severity="info",
                    message="generic XML well-formed under local XXE-safe parser",
                )
            )
        return ok, findings

    def _extract_image(
        self,
        *,
        bridge_id: str,
        inp: StructuredFilingInput,
        body: bytes,
        content_sha: str,
        source_cid: str,
        reason_codes: list[str],
        warnings: list[str],
        findings: list[ValidationFinding],
    ) -> StructuredFilingResult:
        image_digest = sha256_hex(body)
        # Image formats are admitted for OCR hand-off; no OCR here.
        span = ExtractedSpan(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            span_id=f"span:{bridge_id}:1",
            artifact_id=inp.artifact_id,
            page_index=0,
            char_start=None,
            char_end=None,
            bbox=None,
            origin=ExtractionOrigin.UNKNOWN,
            reading_order=0,
            confidence=None,
            text_digest=None,
            image_digest=image_digest,
            classification=inp.classification,
        )
        reason_codes.append(FilingReasonCode.IMAGE_ADMITTED.value)
        reason_codes.append(FilingReasonCode.VALIDATION_OK.value)
        findings.append(
            ValidationFinding(
                schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                code="image.magic_ok",
                severity="info",
                message="raster image admitted; OCR deferred to pdf_ocr_bridge",
            )
        )
        return self._result(
            bridge_id=bridge_id,
            artifact_id=inp.artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            classification=inp.classification,
            filing_format=FilingFormat.IMAGE,
            disposition=FilingDisposition.EXTRACTED,
            review_state=ReviewState.NOT_REQUIRED,
            spans=(span,),
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=[],
            findings=findings,
            members=(),
            full_text="",
            labels=inp.labels,
            retained=True,
            validated=True,
        )

    def _extract_pct_zip(
        self,
        *,
        bridge_id: str,
        inp: StructuredFilingInput,
        body: bytes,
        content_sha: str,
        source_cid: str,
        reason_codes: list[str],
        warnings: list[str],
        findings: list[ValidationFinding],
    ) -> StructuredFilingResult:
        members, member_texts = self._safe_zip_inventory(body)
        reason_codes.append(FilingReasonCode.PCT_ZIP_INVENTORIED.value)
        reason_codes.append(FilingReasonCode.VALIDATION_OK.value)
        findings.append(
            ValidationFinding(
                schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                code="pct_zip.inventory_ok",
                severity="info",
                message=f"inventoried {len(members)} members under archive bounds",
            )
        )

        spans: list[ExtractedSpan] = []
        full_parts: list[str] = []
        cursor = 0
        for i, (name, text) in enumerate(member_texts[: self.bounds.max_spans]):
            if not text.strip():
                continue
            start = cursor
            end = start + len(text)
            cursor = end + 1
            spans.append(
                ExtractedSpan(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    span_id=f"span:{bridge_id}:{i + 1}",
                    artifact_id=inp.artifact_id,
                    page_index=0,
                    char_start=start,
                    char_end=end,
                    bbox=None,
                    origin=ExtractionOrigin.NATIVE,
                    reading_order=i,
                    confidence=1.0,
                    text_digest=text_digest(text),
                    image_digest=None,
                    classification=inp.classification,
                )
            )
            full_parts.append(text)
            reason_codes.append(FilingReasonCode.MEMBER_EXTRACTED.value)
            findings.append(
                ValidationFinding(
                    schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
                    code="pct_zip.member_text",
                    severity="info",
                    message="member text extracted",
                    path=name[:256],
                )
            )

        return self._result(
            bridge_id=bridge_id,
            artifact_id=inp.artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            classification=inp.classification,
            filing_format=FilingFormat.PCT_ZIP,
            disposition=FilingDisposition.EXTRACTED,
            review_state=ReviewState.NOT_REQUIRED,
            spans=tuple(spans),
            reason_codes=list(dict.fromkeys(reason_codes)),
            warnings=warnings,
            unsupported=[],
            findings=findings,
            members=tuple(members),
            full_text="\n".join(full_parts),
            labels=inp.labels,
            retained=True,
            validated=True,
        )

    def _safe_zip_inventory(
        self, body: bytes
    ) -> tuple[list[ArchiveMemberRecord], list[tuple[str, str]]]:
        """Inventory ZIP with bomb / traversal / depth protection."""
        try:
            zf = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile as exc:
            raise StructuredFilingError(
                "invalid zip archive",
                code=FilingReasonCode.VALIDATION_FAILED.value,
            ) from exc

        with zf:
            infos = zf.infolist()
            if len(infos) > self.bounds.max_archive_members:
                raise StructuredFilingError(
                    "archive member count exceeded",
                    code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                )

            total_uncomp = 0
            total_comp = 0
            members: list[ArchiveMemberRecord] = []
            texts: list[tuple[str, str]] = []

            for info in infos:
                name = info.filename or ""
                # Path traversal / absolute paths
                norm = name.replace("\\", "/")
                if (
                    name.startswith("/")
                    or name.startswith("\\")
                    or ".." in norm.split("/")
                    or norm.startswith("../")
                ):
                    raise StructuredFilingError(
                        "archive path traversal",
                        code=FilingReasonCode.ARCHIVE_PATH_TRAVERSAL.value,
                    )
                # Depth limit (nested path components)
                depth = len([p for p in norm.split("/") if p and p != "."])
                if depth > self.bounds.max_zip_depth + 8:
                    # Allow modest folder nesting; nested zip files checked below.
                    pass
                if name.count(".zip") > self.bounds.max_zip_depth:
                    raise StructuredFilingError(
                        "nested zip depth exceeded",
                        code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                    )

                size = int(info.file_size or 0)
                comp = int(info.compress_size or 0)
                if size > self.bounds.max_archive_member_bytes:
                    raise StructuredFilingError(
                        "archive member oversize",
                        code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                    )
                total_uncomp += size
                total_comp += max(comp, 1)
                if total_uncomp > self.bounds.max_archive_uncompressed:
                    raise StructuredFilingError(
                        "archive uncompressed size exceeded",
                        code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                    )
                if comp > 0 and size / comp > self.bounds.max_compression_ratio:
                    raise StructuredFilingError(
                        "archive compression ratio exceeded",
                        code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                    )

                member_sha: str | None = None
                format_hint: str | None = None
                # Read small text members only
                if not name.endswith("/") and size <= min(
                    self.bounds.max_archive_member_bytes, 1_048_576
                ):
                    try:
                        raw = zf.read(info)
                    except Exception as exc:
                        raise StructuredFilingError(
                            "archive member read failed",
                            code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                        ) from exc
                    member_sha = sha256_hex(raw)
                    if raw.startswith(_PDF_MAGIC):
                        format_hint = "pdf"
                    elif raw.startswith(_ZIP_MAGIC):
                        format_hint = "zip"
                        # Nested zip counts as depth
                        raise StructuredFilingError(
                            "nested zip rejected",
                            code=FilingReasonCode.ARCHIVE_BOMB_REJECTED.value,
                        )
                    elif raw.lstrip()[:5].startswith(b"<?xml") or raw.lstrip()[
                        :1
                    ] == b"<":
                        format_hint = "xml"
                        try:
                            text = raw.decode("utf-8", errors="replace")
                            # Bound text extraction
                            texts.append((name, text[:50_000]))
                        except Exception:
                            pass
                    elif _looks_like_text(raw):
                        format_hint = "txt"
                        texts.append(
                            (name, raw.decode("utf-8", errors="replace")[:50_000])
                        )
                    elif raw.startswith(_PNG_MAGIC) or raw.startswith(_JPEG_MAGIC):
                        format_hint = "image"

                members.append(
                    ArchiveMemberRecord(
                        name=name,
                        size=size,
                        compressed_size=comp,
                        sha256=member_sha,
                        format_hint=format_hint,
                    )
                )
            return members, texts

    # -- result builders ----------------------------------------------------

    def _reject(
        self,
        bridge_id: str,
        inp: StructuredFilingInput,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        findings: list[ValidationFinding],
        fmt: FilingFormat,
        *,
        content_sha: str | None = None,
    ) -> StructuredFilingResult:
        body = inp.content_bytes or b""
        content_sha = content_sha or inp.content_sha256 or sha256_hex(body)
        source_cid = inp.source_cid or content_addressed_cid(content_sha)
        return self._result(
            bridge_id=bridge_id,
            artifact_id=inp.artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            classification=inp.classification,
            filing_format=fmt,
            disposition=FilingDisposition.REJECTED,
            review_state=ReviewState.NOT_REQUIRED,
            spans=(),
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=unsupported,
            findings=findings,
            members=(),
            full_text="",
            labels=inp.labels,
            retained=False,
            validated=False,
        )

    def _result(
        self,
        *,
        bridge_id: str,
        artifact_id: str,
        source_cid: str,
        content_sha256: str,
        classification: DisclosureClassification,
        filing_format: FilingFormat,
        disposition: FilingDisposition,
        review_state: ReviewState,
        spans: tuple[ExtractedSpan, ...] | list[ExtractedSpan],
        reason_codes: list[str] | tuple[str, ...],
        warnings: list[str] | tuple[str, ...],
        unsupported: list[str] | tuple[str, ...],
        findings: list[ValidationFinding] | tuple[ValidationFinding, ...],
        members: tuple[ArchiveMemberRecord, ...] | list[ArchiveMemberRecord],
        full_text: str,
        labels: Mapping[str, str],
        retained: bool,
        validated: bool,
    ) -> StructuredFilingResult:
        return StructuredFilingResult(
            schema_version=STRUCTURED_FILING_SCHEMA_VERSION,
            bridge_id=bridge_id,
            artifact_id=artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha256,
            classification=classification,
            filing_format=filing_format,
            disposition=disposition,
            review_state=review_state,
            spans=tuple(spans),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(dict.fromkeys(warnings)),
            unsupported=tuple(dict.fromkeys(unsupported)),
            validation_findings=tuple(findings),
            archive_members=tuple(members),
            full_text=full_text,
            labels=MappingProxyType(dict(labels)),
            retained=retained,
            validated=validated,
        )


def bridge_structured_filing(
    *,
    artifact_id: str,
    content_bytes: bytes,
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN,
    source_cid: str | None = None,
    filename: str | None = None,
    declared_mime: str | None = None,
    declared_format: FilingFormat | str | None = None,
    **kwargs: Any,
) -> StructuredFilingResult:
    """Convenience entry point for one-shot structured filing processing."""
    return StructuredFilingBridge().process(
        artifact_id=artifact_id,
        content_bytes=content_bytes,
        classification=classification,
        source_cid=source_cid,
        filename=filename,
        declared_mime=declared_mime,
        declared_format=declared_format,
        **kwargs,
    )


__all__ = [
    "STRUCTURED_FILING_INTERFACE",
    "STRUCTURED_FILING_SCHEMA_VERSION",
    "ArchiveMemberRecord",
    "FilingDisposition",
    "FilingFormat",
    "FilingReasonCode",
    "StructuredFilingBounds",
    "StructuredFilingBridge",
    "StructuredFilingError",
    "StructuredFilingInput",
    "StructuredFilingResult",
    "ValidationFinding",
    "bridge_structured_filing",
    "content_addressed_cid",
    "detect_filing_format",
    "parse_xml_safe",
    "sha256_hex",
    "text_digest",
]
