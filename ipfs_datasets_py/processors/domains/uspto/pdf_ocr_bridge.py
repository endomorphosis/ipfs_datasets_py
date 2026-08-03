"""USPTO bridge to the specialized PDF/OCR stack (PATLAW-121).

Routes born-digital PDFs through native layout/text extraction and
image-only or low-confidence pages through a configurable local OCR
backend. Emits deterministic :class:`ExtractedSpan` records linked to
source CID/page/bounds. OCR is confidence-gated and resumable via
page-level checkpoints. Corrupt, encrypted, and unsupported PDFs fail
closed.

Private material never reaches unauthorized remote OCR/model providers
and never persists as plaintext on disk. Ordinary logs and audit payloads
carry identifiers and reason codes only — never document body text.

This module owns the USPTO-to-specialized-PDF adapter surface only; it does
not fork generic PDF processors or alter encrypted artifact stores.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    Protocol,
    Sequence,
    runtime_checkable,
)

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
    is_private_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    UsptoPrivacyPolicy,
    DEFAULT_PRIVACY_POLICY,
)

# Prefer specialized text-layer helpers when available; fall back locally.
try:  # pragma: no cover - environment dependent import path
    from ipfs_datasets_py.processors.specialized.pdf.text_layer_merge import (
        DEFAULT_LOW_CONFIDENCE_THRESHOLD as _TL_LOW_CONF,
        DEFAULT_MIN_NATIVE_CHARS as _TL_MIN_CHARS,
        DEFAULT_NATIVE_COVERAGE_THRESHOLD as _TL_COV_THRESH,
        estimate_native_char_coverage as _tl_estimate_coverage,
        normalize_bbox as _tl_normalize_bbox,
        should_run_page_ocr as _tl_should_run_ocr,
    )
except Exception:  # pragma: no cover
    _TL_LOW_CONF = 0.7
    _TL_MIN_CHARS = 40
    _TL_COV_THRESH = 0.15
    _tl_estimate_coverage = None  # type: ignore[assignment]
    _tl_normalize_bbox = None  # type: ignore[assignment]
    _tl_should_run_ocr = None  # type: ignore[assignment]

try:  # pragma: no cover
    import fitz as _fitz
except Exception:  # pragma: no cover
    _fitz = None  # type: ignore[assignment]

try:  # pragma: no cover
    from pypdf import PdfReader as _PdfReader
    from pypdf.errors import FileNotDecryptedError as _FileNotDecryptedError
except Exception:  # pragma: no cover
    _PdfReader = None  # type: ignore[assignment,misc]
    _FileNotDecryptedError = Exception  # type: ignore[misc,assignment]


PDF_OCR_BRIDGE_SCHEMA_VERSION: Final = "uspto.pdf-ocr-bridge.v1"
PDF_OCR_BRIDGE_INTERFACE: Final = "PdfOcrBridge@1"
PARSER_DIGEST_SEED: Final = "uspto.pdf-ocr-bridge.parser.v1"

DEFAULT_MAX_BYTES: Final = 16 * 1024 * 1024
DEFAULT_MAX_PAGES: Final = 500
DEFAULT_MAX_SPANS_PER_PAGE: Final = 4096
DEFAULT_MIN_NATIVE_CHARS: Final = int(_TL_MIN_CHARS) if _TL_MIN_CHARS else 40
DEFAULT_NATIVE_COVERAGE_THRESHOLD: Final = (
    float(_TL_COV_THRESH) if _TL_COV_THRESH else 0.15
)
DEFAULT_OCR_CONFIDENCE_THRESHOLD: Final = (
    float(_TL_LOW_CONF) if _TL_LOW_CONF else 0.7
)
DEFAULT_RENDER_DPI: Final = 150

_PDF_MAGIC: Final = b"%PDF"
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class BridgeDisposition(str, Enum):
    """Pipeline disposition after bridge processing."""

    EXTRACTED = "extracted"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class PageBridgeStatus(str, Enum):
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
    OCR_LOW_CONFIDENCE = "ocr_low_confidence"
    OCR_APPLIED = "ocr_applied"
    CHECKPOINTED = "checkpointed"


class BridgeReasonCode(str, Enum):
    NATIVE_TEXT_EXTRACTED = "native_text_extracted"
    OCR_TEXT_EXTRACTED = "ocr_text_extracted"
    OCR_FALLBACK_APPLIED = "ocr_fallback_applied"
    OCR_CONFIDENCE_GATED = "ocr_confidence_gated"
    OCR_UNAVAILABLE = "ocr_unavailable"
    OCR_RESUMED = "ocr_resumed"
    LOW_COVERAGE = "low_coverage"
    IMAGE_ONLY_PAGE = "image_only_page"
    BLANK_PAGE = "blank_page"
    ROTATED_PAGE = "rotated_page"
    PASSWORD_PROTECTED = "password_protected"
    CORRUPT_DOCUMENT = "corrupt_document"
    OVERSIZE_DOCUMENT = "oversize_document"
    PAGE_LIMIT_EXCEEDED = "page_limit_exceeded"
    UNSUPPORTED_MEDIA = "unsupported_media"
    MISSING_BYTES = "missing_bytes"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    REMOTE_OCR_DENIED = "remote_ocr_denied"
    PROVIDER_CALL_RECORDED = "provider_call_recorded"
    CHECKPOINT_HIT = "checkpoint_hit"
    LAYOUT_ITEMS_EXTRACTED = "layout_items_extracted"
    SIGNATURE_PRESENCE = "signature_presence"
    TABLE_DETECTED = "table_detected"


class OcrProviderKind(str, Enum):
    """Where OCR computation runs."""

    LOCAL = "local"
    REMOTE = "remote"
    NONE = "none"
    INJECTED = "injected"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class PdfOcrBridgeError(ValueError):
    """Bounded bridge failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "pdf_ocr_bridge_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        # Never include document body text.
        return {"code": self.code, "message": str(self)[:256]}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_addressed_cid(content_sha256: str, *, prefix: str = "baguqeera") -> str:
    """Deterministic synthetic CID from content digest (not a real multihash encode).

    Bridges use this when callers omit an upstream private CID so every span
    remains linked to an immutable content identifier.
    """
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


def estimate_native_char_coverage(
    text: str,
    *,
    page_width: float = 0.0,
    page_height: float = 0.0,
    min_chars: int = DEFAULT_MIN_NATIVE_CHARS,
) -> float:
    if _tl_estimate_coverage is not None:
        return float(
            _tl_estimate_coverage(
                text,
                page_width=page_width,
                page_height=page_height,
                min_chars=min_chars,
            )
        )
    cleaned = _normalize_ws(text)
    if not cleaned:
        return 0.0
    n = len(cleaned)
    if page_width > 0 and page_height > 0:
        capacity = max(min_chars, (page_width * page_height) / 180.0)
        return max(0.0, min(1.0, n / capacity))
    return max(0.0, min(1.0, n / float(max(min_chars * 2, 1))))


def should_run_page_ocr(
    native_text: str,
    *,
    coverage: float | None = None,
    coverage_threshold: float = DEFAULT_NATIVE_COVERAGE_THRESHOLD,
    min_chars: int = DEFAULT_MIN_NATIVE_CHARS,
    force: bool = False,
) -> bool:
    if _tl_should_run_ocr is not None:
        return bool(
            _tl_should_run_ocr(
                native_text,
                coverage=coverage,
                coverage_threshold=coverage_threshold,
                min_chars=min_chars,
                force=force,
            )
        )
    if force:
        return True
    if coverage is None:
        coverage = estimate_native_char_coverage(native_text, min_chars=min_chars)
    if coverage < coverage_threshold:
        return True
    if len(_normalize_ws(native_text)) < min_chars:
        return True
    return False


def normalize_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if _tl_normalize_bbox is not None:
        result = _tl_normalize_bbox(bbox)
        if result is None:
            return None
        return (float(result[0]), float(result[1]), float(result[2]), float(result[3]))
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
            return normalize_bbox(bbox["bbox"])
        return None
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError):
            return None
    return None


def parser_digest(
    *,
    schema_version: str = PDF_OCR_BRIDGE_SCHEMA_VERSION,
    extra: Mapping[str, str] | None = None,
) -> str:
    """Immutable digest identifying bridge parser configuration for resume keys."""
    payload = {
        "seed": PARSER_DIGEST_SEED,
        "schema_version": schema_version,
        "extra": dict(extra or {}),
    }
    return sha256_hex(canonical_json(payload))


# ---------------------------------------------------------------------------
# OCR backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class OcrBackend(Protocol):
    """Local or injected OCR backend.

    Implementations must not log or persist document image/text contents.
    """

    kind: OcrProviderKind
    name: str

    def ocr_page(
        self,
        image_bytes: bytes,
        *,
        page_index: int,
        artifact_id: str,
    ) -> Mapping[str, Any]:
        """Return ``{text, confidence, status, word_boxes?, engine?}``."""
        ...


# Callable form used by tests and lightweight injectors.
OcrCallable = Callable[[bytes, int], Mapping[str, Any]]


@dataclass
class RecordingOcrBackend:
    """Test/production recorder that wraps a local OCR callable.

    Records provider metadata only (no body text) so private integration
    tests can prove zero unauthorized remote calls.
    """

    name: str = "recording-local"
    kind: OcrProviderKind = OcrProviderKind.LOCAL
    callable: OcrCallable | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def ocr_page(
        self,
        image_bytes: bytes,
        *,
        page_index: int,
        artifact_id: str,
    ) -> Mapping[str, Any]:
        record = {
            "backend": self.name,
            "kind": self.kind.value,
            "page_index": page_index,
            "artifact_id": artifact_id,
            "image_sha256": sha256_hex(image_bytes) if image_bytes else None,
            "image_size": len(image_bytes) if image_bytes else 0,
        }
        self.calls.append(record)
        if self.callable is None:
            return {
                "text": "",
                "confidence": None,
                "status": "ocr_unavailable",
                "engine": self.name,
                "word_boxes": [],
            }
        payload = self.callable(image_bytes, page_index)
        if not isinstance(payload, Mapping):
            raise TypeError("OCR callable must return a mapping")
        return payload


@dataclass
class DeniedRemoteOcrBackend:
    """Fail-closed remote OCR stub — always denies without transmitting bytes."""

    name: str = "remote-denied"
    kind: OcrProviderKind = OcrProviderKind.REMOTE
    calls: list[dict[str, Any]] = field(default_factory=list)

    def ocr_page(
        self,
        image_bytes: bytes,
        *,
        page_index: int,
        artifact_id: str,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "backend": self.name,
                "kind": self.kind.value,
                "page_index": page_index,
                "artifact_id": artifact_id,
                "denied": True,
                # Deliberately do NOT record image bytes or digests of private pages
                # when the route is unauthorized — only the denial event.
            }
        )
        raise PrivacyBoundaryError(
            "remote OCR denied for private material",
            code="remote_ocr_denied",
            classification=None,
            sink=PublicSink.REMOTE_PROMPT.value,
            content_kind=ContentKind.DOCUMENT_BYTES.value,
        )


# ---------------------------------------------------------------------------
# Config / checkpoints / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PdfOcrBridgeBounds:
    """Execution bounds for untrusted PDF processing."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_pages: int = DEFAULT_MAX_PAGES
    max_spans_per_page: int = DEFAULT_MAX_SPANS_PER_PAGE
    min_native_chars: int = DEFAULT_MIN_NATIVE_CHARS
    native_coverage_threshold: float = DEFAULT_NATIVE_COVERAGE_THRESHOLD
    ocr_confidence_threshold: float = DEFAULT_OCR_CONFIDENCE_THRESHOLD
    render_dpi: int = DEFAULT_RENDER_DPI
    low_coverage_review_threshold: float = 0.35

    def __post_init__(self) -> None:
        for name in (
            "max_bytes",
            "max_pages",
            "max_spans_per_page",
            "min_native_chars",
            "render_dpi",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        for name in (
            "native_coverage_threshold",
            "ocr_confidence_threshold",
            "low_coverage_review_threshold",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not (0.0 <= float(value) <= 1.0)
            ):
                raise ValueError(f"{name} must be in [0.0, 1.0]")


@dataclass(frozen=True, slots=True)
class PdfOcrBridgePolicy:
    """Governed OCR routing policy."""

    allow_remote_ocr_for_private: bool = False
    allow_remote_ocr_for_public: bool = False
    require_local_ocr_default: bool = True
    persist_plaintext: bool = False
    privacy: UsptoPrivacyPolicy = field(default_factory=lambda: DEFAULT_PRIVACY_POLICY)

    def __post_init__(self) -> None:
        for name in (
            "allow_remote_ocr_for_private",
            "allow_remote_ocr_for_public",
            "require_local_ocr_default",
            "persist_plaintext",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")


@dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    """Safe audit of an OCR provider interaction (no body text)."""

    schema_version: str
    call_id: str
    backend: str
    kind: OcrProviderKind
    page_index: int | None
    artifact_id: str
    authorized: bool
    outcome: str
    image_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authorized": self.authorized,
            "backend": self.backend,
            "call_id": self.call_id,
            "image_sha256": self.image_sha256,
            "kind": self.kind.value,
            "outcome": self.outcome,
            "page_index": self.page_index,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCallRecord":
        return cls(
            schema_version=str(
                value.get("schema_version", PDF_OCR_BRIDGE_SCHEMA_VERSION)
            ),
            call_id=str(value.get("call_id", "")),
            backend=str(value.get("backend", "")),
            kind=OcrProviderKind(str(value.get("kind", OcrProviderKind.NONE.value))),
            page_index=value.get("page_index"),
            artifact_id=str(value.get("artifact_id", "")),
            authorized=bool(value.get("authorized", False)),
            outcome=str(value.get("outcome", "")),
            image_sha256=value.get("image_sha256"),
        )


@dataclass(frozen=True, slots=True)
class PageCoverageReceipt:
    """Per-page coverage + provenance receipt for bridge consumers."""

    schema_version: str
    page_index: int
    artifact_id: str
    source_cid: str
    native_char_count: int
    ocr_char_count: int
    merged_char_count: int
    native_coverage: float
    coverage_ratio: float
    has_native_text: bool
    has_ocr_text: bool
    rotation: int
    status: PageBridgeStatus
    ocr_status: str
    ocr_confidence: float | None
    origins_present: tuple[str, ...]
    disagreement: bool
    render_digest: str | None
    page_width: float | None
    page_height: float | None
    checkpoint_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "checkpoint_key": self.checkpoint_key,
            "coverage_ratio": self.coverage_ratio,
            "disagreement": self.disagreement,
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
            "source_cid": self.source_cid,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageCoverageReceipt":
        return cls(
            schema_version=str(
                value.get("schema_version", PDF_OCR_BRIDGE_SCHEMA_VERSION)
            ),
            page_index=int(value.get("page_index", 0)),
            artifact_id=str(value.get("artifact_id", "")),
            source_cid=str(value.get("source_cid", "")),
            native_char_count=int(value.get("native_char_count", 0)),
            ocr_char_count=int(value.get("ocr_char_count", 0)),
            merged_char_count=int(value.get("merged_char_count", 0)),
            native_coverage=float(value.get("native_coverage", 0.0)),
            coverage_ratio=float(value.get("coverage_ratio", 0.0)),
            has_native_text=bool(value.get("has_native_text", False)),
            has_ocr_text=bool(value.get("has_ocr_text", False)),
            rotation=int(value.get("rotation", 0)),
            status=PageBridgeStatus(str(value.get("status", PageBridgeStatus.EMPTY.value))),
            ocr_status=str(value.get("ocr_status", "not_needed")),
            ocr_confidence=value.get("ocr_confidence"),
            origins_present=tuple(value.get("origins_present") or ()),
            disagreement=bool(value.get("disagreement", False)),
            render_digest=value.get("render_digest"),
            page_width=value.get("page_width"),
            page_height=value.get("page_height"),
            checkpoint_key=value.get("checkpoint_key"),
        )


@dataclass(frozen=True, slots=True)
class LayoutSignal:
    """Compact layout/signature/table signal retained from native extraction."""

    schema_version: str
    item_id: str
    artifact_id: str
    kind: str
    page_index: int | None
    bbox: tuple[float, float, float, float] | None
    span_id: str | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "confidence": self.confidence,
            "item_id": self.item_id,
            "kind": self.kind,
            "page_index": self.page_index,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LayoutSignal":
        bbox_raw = value.get("bbox")
        bbox = None
        if bbox_raw is not None:
            bbox = (
                float(bbox_raw[0]),
                float(bbox_raw[1]),
                float(bbox_raw[2]),
                float(bbox_raw[3]),
            )
        return cls(
            schema_version=str(
                value.get("schema_version", PDF_OCR_BRIDGE_SCHEMA_VERSION)
            ),
            item_id=str(value.get("item_id", "")),
            artifact_id=str(value.get("artifact_id", "")),
            kind=str(value.get("kind", "other")),
            page_index=value.get("page_index"),
            bbox=bbox,
            span_id=value.get("span_id"),
            confidence=value.get("confidence"),
        )


@dataclass(frozen=True, slots=True)
class PageCheckpoint:
    """Resumable page-level OCR/extraction checkpoint.

    Stores digests and structured span contracts only — never raw page
    image bytes or free-form plaintext blobs on disk.
    """

    schema_version: str
    checkpoint_key: str
    artifact_id: str
    source_cid: str
    content_sha256: str
    parser_digest: str
    page_index: int
    status: PageBridgeStatus
    ocr_status: str
    ocr_confidence: float | None
    span_dicts: tuple[Mapping[str, Any], ...]
    page_text_digest: str | None
    render_digest: str | None
    native_coverage: float
    completed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "checkpoint_key": self.checkpoint_key,
            "completed": self.completed,
            "content_sha256": self.content_sha256,
            "native_coverage": self.native_coverage,
            "ocr_confidence": self.ocr_confidence,
            "ocr_status": self.ocr_status,
            "page_index": self.page_index,
            "page_text_digest": self.page_text_digest,
            "parser_digest": self.parser_digest,
            "render_digest": self.render_digest,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "span_dicts": [dict(s) for s in self.span_dicts],
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageCheckpoint":
        spans_raw = value.get("span_dicts") or ()
        return cls(
            schema_version=str(
                value.get("schema_version", PDF_OCR_BRIDGE_SCHEMA_VERSION)
            ),
            checkpoint_key=str(value.get("checkpoint_key", "")),
            artifact_id=str(value.get("artifact_id", "")),
            source_cid=str(value.get("source_cid", "")),
            content_sha256=str(value.get("content_sha256", "")),
            parser_digest=str(value.get("parser_digest", "")),
            page_index=int(value.get("page_index", 0)),
            status=PageBridgeStatus(
                str(value.get("status", PageBridgeStatus.EMPTY.value))
            ),
            ocr_status=str(value.get("ocr_status", "not_needed")),
            ocr_confidence=value.get("ocr_confidence"),
            span_dicts=tuple(dict(s) for s in spans_raw),
            page_text_digest=value.get("page_text_digest"),
            render_digest=value.get("render_digest"),
            native_coverage=float(value.get("native_coverage", 0.0)),
            completed=bool(value.get("completed", False)),
        )


class CheckpointStore:
    """In-memory or directory-backed checkpoint store.

    When writing to disk, only JSON of digests/span contracts is persisted —
    never full page images or free-text bodies. ``persist_plaintext=False``
    (default) refuses any attempt to write free-text page bodies to disk.

    An optional process-local OCR payload cache (not written to disk) lets a
    resume skip expensive OCR backend calls while still reconstituting spans
    for the same content/parser digest.
    """

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        persist_plaintext: bool = False,
    ) -> None:
        self._directory = Path(directory) if directory is not None else None
        self._persist_plaintext = bool(persist_plaintext)
        self._memory: dict[str, PageCheckpoint] = {}
        # Process-local only — never serialized to disk when plaintext denied.
        self._ocr_payload_cache: dict[str, Mapping[str, Any]] = {}
        self._page_text_cache: dict[str, str] = {}
        if self._directory is not None:
            self._directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path | None:
        return self._directory

    @property
    def persist_plaintext(self) -> bool:
        return self._persist_plaintext

    def checkpoint_key(
        self,
        *,
        content_sha256: str,
        parser_digest_value: str,
        page_index: int,
    ) -> str:
        raw = f"{content_sha256}:{parser_digest_value}:{page_index}"
        return sha256_hex(raw)

    def get(self, key: str) -> PageCheckpoint | None:
        if key in self._memory:
            return self._memory[key]
        if self._directory is None:
            return None
        path = self._directory / f"{key}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Disk artifacts must never carry plaintext page bodies.
            if not self._persist_plaintext:
                raw_text = json.dumps(data)
                if '"text":' in raw_text and re.search(
                    r'"text"\s*:\s*"[^"]+"', raw_text
                ):
                    # Allow text_digest keys only.
                    if re.search(r'"text"\s*:\s*"(?!digest)', raw_text):
                        # Strip any accidental text fields before load.
                        if isinstance(data.get("span_dicts"), list):
                            for s in data["span_dicts"]:
                                if isinstance(s, dict):
                                    s.pop("text", None)
                        data.pop("page_text", None)
            cp = PageCheckpoint.from_dict(data)
            self._memory[key] = cp
            return cp
        except Exception:
            return None

    def put(
        self,
        checkpoint: PageCheckpoint,
        *,
        ocr_payload: Mapping[str, Any] | None = None,
        page_text: str | None = None,
    ) -> None:
        # Refuse accidental plaintext page body keys if present in span dicts.
        if not self._persist_plaintext:
            for span in checkpoint.span_dicts:
                if "text" in span and span.get("text"):
                    raise PdfOcrBridgeError(
                        "refusing to persist span plaintext",
                        code="plaintext_persistence_denied",
                    )
        self._memory[checkpoint.checkpoint_key] = checkpoint
        if ocr_payload is not None:
            # Keep process-local only (never written below when plaintext denied).
            self._ocr_payload_cache[checkpoint.checkpoint_key] = dict(ocr_payload)
        if page_text is not None:
            self._page_text_cache[checkpoint.checkpoint_key] = page_text
        if self._directory is None:
            return
        path = self._directory / f"{checkpoint.checkpoint_key}.json"
        tmp = path.with_suffix(".tmp")
        payload = checkpoint.to_dict()
        # Never write ocr_payload / page_text to disk under default policy.
        if self._persist_plaintext:
            if page_text is not None:
                payload["page_text"] = page_text
        tmp.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(path)

    def get_ocr_payload(self, key: str) -> Mapping[str, Any] | None:
        return self._ocr_payload_cache.get(key)

    def get_page_text(self, key: str) -> str | None:
        return self._page_text_cache.get(key)

    def keys(self) -> frozenset[str]:
        keys = set(self._memory)
        if self._directory is not None:
            for p in self._directory.glob("*.json"):
                keys.add(p.stem)
        return frozenset(keys)

    def disk_files(self) -> list[Path]:
        if self._directory is None:
            return []
        return list(self._directory.glob("*.json"))

    def clear_memory(self) -> None:
        self._memory.clear()
        self._ocr_payload_cache.clear()
        self._page_text_cache.clear()


@dataclass(frozen=True, slots=True)
class PdfOcrBridgeInput:
    """Input envelope for the PDF/OCR bridge."""

    artifact_id: str
    content_bytes: bytes | None
    classification: DisclosureClassification
    source_cid: str | None = None
    content_sha256: str | None = None
    filename: str | None = None
    declared_mime: str | None = None
    force_ocr: bool = False
    ocr_by_page: Mapping[int, Mapping[str, Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    labels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if self.content_bytes is not None and not isinstance(self.content_bytes, (bytes, bytearray)):
            raise TypeError("content_bytes must be bytes or None")
        if self.content_bytes is not None:
            object.__setattr__(self, "content_bytes", bytes(self.content_bytes))
        object.__setattr__(
            self, "source_cid", _optional_identifier(self.source_cid, "source_cid")
        )
        if self.content_sha256 is not None:
            digest = _require_str(self.content_sha256, "content_sha256", max_len=64).lower()
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
        if not isinstance(self.force_ocr, bool):
            raise TypeError("force_ocr must be bool")
        if self.ocr_by_page is None:
            object.__setattr__(self, "ocr_by_page", MappingProxyType({}))
        elif not isinstance(self.ocr_by_page, Mapping):
            raise TypeError("ocr_by_page must be a mapping")
        else:
            frozen = {}
            for k, v in self.ocr_by_page.items():
                if isinstance(k, bool) or not isinstance(k, int) or k < 0:
                    raise TypeError("ocr_by_page keys must be non-negative ints")
                if not isinstance(v, Mapping):
                    raise TypeError("ocr_by_page values must be mappings")
                frozen[k] = dict(v)
            object.__setattr__(self, "ocr_by_page", MappingProxyType(frozen))
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
class PdfOcrBridgeResult:
    """Normalized bridge output with spans linked to source CID/page/bounds."""

    schema_version: str
    bridge_id: str
    artifact_id: str
    source_cid: str
    content_sha256: str
    classification: DisclosureClassification
    disposition: BridgeDisposition
    review_state: ReviewState
    page_count: int
    spans: tuple[ExtractedSpan, ...]
    page_coverage: tuple[PageCoverageReceipt, ...]
    layout_signals: tuple[LayoutSignal, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported: tuple[str, ...]
    provider_calls: tuple[ProviderCallRecord, ...]
    parser_digest: str
    page_texts: Mapping[str, str]
    full_text: str
    labels: Mapping[str, str]
    retained: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != PDF_OCR_BRIDGE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {PDF_OCR_BRIDGE_SCHEMA_VERSION}"
            )

    @property
    def requires_review(self) -> bool:
        return self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def span_by_id(self, span_id: str) -> ExtractedSpan | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "bridge_id": self.bridge_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "full_text": self.full_text,
            "labels": dict(self.labels),
            "layout_signals": [x.to_dict() for x in self.layout_signals],
            "page_count": self.page_count,
            "page_coverage": [c.to_dict() for c in self.page_coverage],
            "page_texts": dict(self.page_texts),
            "parser_digest": self.parser_digest,
            "provider_calls": [p.to_dict() for p in self.provider_calls],
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "spans": [s.to_dict() for s in self.spans],
            "unsupported": list(self.unsupported),
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifier-only projection — omits body text and page texts."""
        return {
            "artifact_id": self.artifact_id,
            "bridge_id": self.bridge_id,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "labels": dict(self.labels),
            "layout_signals": [
                {
                    "item_id": x.item_id,
                    "kind": x.kind,
                    "page_index": x.page_index,
                    "span_id": x.span_id,
                }
                for x in self.layout_signals
            ],
            "page_count": self.page_count,
            "page_coverage": [
                {
                    "page_index": c.page_index,
                    "status": c.status.value,
                    "ocr_status": c.ocr_status,
                    "native_coverage": c.native_coverage,
                    "has_native_text": c.has_native_text,
                    "has_ocr_text": c.has_ocr_text,
                    "render_digest": c.render_digest,
                    "source_cid": c.source_cid,
                }
                for c in self.page_coverage
            ],
            "parser_digest": self.parser_digest,
            "provider_calls": [p.to_dict() for p in self.provider_calls],
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "spans": [
                {
                    "span_id": s.span_id,
                    "artifact_id": s.artifact_id,
                    "page_index": s.page_index,
                    "origin": s.origin.value,
                    "confidence": s.confidence,
                    "text_digest": s.text_digest,
                    "bbox": list(s.bbox) if s.bbox is not None else None,
                    "reading_order": s.reading_order,
                }
                for s in self.spans
            ],
            "unsupported": list(self.unsupported),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PdfOcrBridgeResult":
        if not isinstance(value, Mapping):
            raise TypeError("PdfOcrBridgeResult must be a mapping")
        return cls(
            schema_version=str(
                value.get("schema_version", PDF_OCR_BRIDGE_SCHEMA_VERSION)
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
            disposition=BridgeDisposition(
                str(value.get("disposition", BridgeDisposition.REJECTED.value))
            ),
            review_state=ReviewState(
                str(value.get("review_state", ReviewState.NOT_REQUIRED.value))
            ),
            page_count=int(value.get("page_count", 0)),
            spans=tuple(
                ExtractedSpan.from_dict(s) for s in (value.get("spans") or ())
            ),
            page_coverage=tuple(
                PageCoverageReceipt.from_dict(c)
                for c in (value.get("page_coverage") or ())
            ),
            layout_signals=tuple(
                LayoutSignal.from_dict(x)
                for x in (value.get("layout_signals") or ())
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            unsupported=tuple(value.get("unsupported") or ()),
            provider_calls=tuple(
                ProviderCallRecord.from_dict(p)
                for p in (value.get("provider_calls") or ())
            ),
            parser_digest=str(value.get("parser_digest", "")),
            page_texts=MappingProxyType(dict(value.get("page_texts") or {})),
            full_text=str(value.get("full_text") or ""),
            labels=MappingProxyType(dict(value.get("labels") or {})),
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Internal page builder
# ---------------------------------------------------------------------------


@dataclass
class _SpanBuilder:
    text: str
    origin: ExtractionOrigin
    page_index: int
    reading_order: int
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None
    image_digest: str | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class _PageState:
    page_index: int
    width: float = 0.0
    height: float = 0.0
    rotation: int = 0
    native_text: str = ""
    ocr_text: str = ""
    render_digest: str | None = None
    ocr_status: str = "not_needed"
    ocr_confidence: float | None = None
    status: PageBridgeStatus = PageBridgeStatus.OK
    spans: list[_SpanBuilder] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)
    disagreement: bool = False
    checkpoint_key: str | None = None
    from_checkpoint: bool = False


# ---------------------------------------------------------------------------
# Bridge implementation
# ---------------------------------------------------------------------------


class PdfOcrBridge:
    """Bridge USPTO PDF artifacts to native extraction + governed local OCR.

    Parameters
    ----------
    bounds:
        Size/page/OCR thresholds.
    policy:
        Remote OCR and plaintext persistence policy (fail-closed defaults).
    ocr_backend:
        Optional local/injected OCR backend. When omitted, page OCR is
        marked unavailable unless ``ocr_by_page`` payloads are supplied.
    checkpoint_store:
        Optional resumable checkpoint store.
    specialized_processor:
        Optional specialized ``PDFProcessor`` (or compatible) for advanced
        pipeline delegation. When provided, native decomposition may be
        sourced from it; unit tests typically leave this ``None`` and use
        the lightweight pymupdf path.
    id_factory:
        Deterministic-friendly id factory for bridge/span identifiers.
    """

    def __init__(
        self,
        *,
        bounds: PdfOcrBridgeBounds | None = None,
        policy: PdfOcrBridgePolicy | None = None,
        ocr_backend: OcrBackend | OcrCallable | None = None,
        checkpoint_store: CheckpointStore | None = None,
        specialized_processor: Any | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.bounds = bounds or PdfOcrBridgeBounds()
        self.policy = policy or PdfOcrBridgePolicy()
        self._ocr_backend = self._normalize_backend(ocr_backend)
        self.checkpoint_store = checkpoint_store or CheckpointStore(
            persist_plaintext=self.policy.persist_plaintext
        )
        self._specialized = specialized_processor
        self._id_factory = id_factory or (lambda: f"pdfocr:{uuid.uuid4().hex}")
        self._provider_calls: list[ProviderCallRecord] = []

    @staticmethod
    def _normalize_backend(
        backend: OcrBackend | OcrCallable | None,
    ) -> OcrBackend | None:
        if backend is None:
            return None
        if isinstance(backend, OcrBackend) or (
            hasattr(backend, "ocr_page") and hasattr(backend, "kind")
        ):
            return backend  # type: ignore[return-value]
        if callable(backend):
            return RecordingOcrBackend(
                name="injected-callable",
                kind=OcrProviderKind.INJECTED,
                callable=backend,  # type: ignore[arg-type]
            )
        raise TypeError("ocr_backend must be OcrBackend, callable, or None")

    # -- public API ---------------------------------------------------------

    def process(
        self,
        value: PdfOcrBridgeInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> PdfOcrBridgeResult:
        """Process one PDF artifact through native + gated OCR paths."""
        inp = self._coerce_input(value, **kwargs)
        self._provider_calls = []
        return self._process(inp)

    def process_many(
        self, values: Sequence[PdfOcrBridgeInput | Mapping[str, Any]]
    ) -> list[PdfOcrBridgeResult]:
        return [self.process(v) for v in values]

    @property
    def last_provider_calls(self) -> tuple[ProviderCallRecord, ...]:
        return tuple(self._provider_calls)

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: PdfOcrBridgeInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> PdfOcrBridgeInput:
        if value is None:
            return PdfOcrBridgeInput(**kwargs)
        if isinstance(value, PdfOcrBridgeInput):
            if kwargs:
                data = {
                    "artifact_id": value.artifact_id,
                    "content_bytes": value.content_bytes,
                    "classification": value.classification,
                    "source_cid": value.source_cid,
                    "content_sha256": value.content_sha256,
                    "filename": value.filename,
                    "declared_mime": value.declared_mime,
                    "force_ocr": value.force_ocr,
                    "ocr_by_page": dict(value.ocr_by_page),
                    "labels": dict(value.labels),
                }
                data.update(kwargs)
                return PdfOcrBridgeInput(**data)
            return value
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return PdfOcrBridgeInput(**data)
        raise TypeError("process() expects PdfOcrBridgeInput, mapping, or kwargs")

    # -- main ---------------------------------------------------------------

    def _process(self, inp: PdfOcrBridgeInput) -> PdfOcrBridgeResult:
        bridge_id = str(self._id_factory())
        classification = inp.classification
        reason_codes: list[str] = []
        warnings: list[str] = []
        unsupported: list[str] = []
        pdigest = parser_digest(
            extra={
                "ocr_confidence_threshold": f"{self.bounds.ocr_confidence_threshold:.4f}",
                "native_coverage_threshold": f"{self.bounds.native_coverage_threshold:.4f}",
            }
        )

        if requires_quarantine(classification):
            reason_codes.append(BridgeReasonCode.QUARANTINE_CLASSIFICATION.value)
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=inp.source_cid or content_addressed_cid(sha256_hex(b"")),
                content_sha256=inp.content_sha256 or sha256_hex(b""),
                classification=classification,
                disposition=BridgeDisposition.QUARANTINE,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                parser_digest_value=pdigest,
            )

        body = inp.content_bytes
        if body is None or len(body) == 0:
            reason_codes.append(BridgeReasonCode.MISSING_BYTES.value)
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=inp.source_cid or content_addressed_cid(sha256_hex(b"")),
                content_sha256=inp.content_sha256 or sha256_hex(b""),
                classification=classification,
                disposition=BridgeDisposition.REJECTED,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                parser_digest_value=pdigest,
            )

        if len(body) > self.bounds.max_bytes:
            reason_codes.append(BridgeReasonCode.OVERSIZE_DOCUMENT.value)
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=inp.source_cid
                or content_addressed_cid(sha256_hex(body)),
                content_sha256=sha256_hex(body),
                classification=classification,
                disposition=BridgeDisposition.REJECTED,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                parser_digest_value=pdigest,
            )

        content_sha = inp.content_sha256 or sha256_hex(body)
        actual_sha = sha256_hex(body)
        if inp.content_sha256 and inp.content_sha256 != actual_sha:
            warnings.append("content_sha256_mismatch")
            content_sha = actual_sha

        source_cid = inp.source_cid or content_addressed_cid(content_sha)

        if not body.startswith(_PDF_MAGIC):
            # Allow declared PDF with bad magic only as unsupported fail-closed.
            reason_codes.append(BridgeReasonCode.UNSUPPORTED_MEDIA.value)
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha256=content_sha,
                classification=classification,
                disposition=BridgeDisposition.REJECTED,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=["non_pdf_magic"],
                labels=inp.labels,
                parser_digest_value=pdigest,
            )

        # Encrypted / password-protected detection (fail closed).
        if self._is_encrypted(body):
            reason_codes.append(BridgeReasonCode.PASSWORD_PROTECTED.value)
            logger.info(
                "pdf_ocr_bridge password-protected artifact_id=%s",
                inp.artifact_id,
            )
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha256=content_sha,
                classification=classification,
                disposition=BridgeDisposition.REJECTED,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                parser_digest_value=pdigest,
                page_status=PageBridgeStatus.PASSWORD_PROTECTED,
            )

        try:
            pages, layout = self._extract_native_pages(
                body,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha=content_sha,
                parser_digest_value=pdigest,
                classification=classification,
                force_ocr=inp.force_ocr,
                ocr_by_page=inp.ocr_by_page,
                reason_codes=reason_codes,
                warnings=warnings,
            )
        except PdfOcrBridgeError as exc:
            reason_codes.append(exc.code)
            logger.info(
                "pdf_ocr_bridge fail-closed artifact_id=%s code=%s",
                inp.artifact_id,
                exc.code,
            )
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha256=content_sha,
                classification=classification,
                disposition=BridgeDisposition.REJECTED,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                parser_digest_value=pdigest,
            )
        except Exception as exc:  # pragma: no cover - defensive
            reason_codes.append(BridgeReasonCode.CORRUPT_DOCUMENT.value)
            logger.info(
                "pdf_ocr_bridge corrupt artifact_id=%s err=%s",
                inp.artifact_id,
                type(exc).__name__,
            )
            return self._finalize_reject(
                bridge_id=bridge_id,
                artifact_id=inp.artifact_id,
                source_cid=source_cid,
                content_sha256=content_sha,
                classification=classification,
                disposition=BridgeDisposition.REJECTED,
                reason_codes=reason_codes,
                warnings=warnings,
                unsupported=unsupported,
                labels=inp.labels,
                parser_digest_value=pdigest,
            )

        return self._finalize_success(
            bridge_id=bridge_id,
            artifact_id=inp.artifact_id,
            source_cid=source_cid,
            content_sha=content_sha,
            classification=classification,
            pages=pages,
            layout=layout,
            reason_codes=reason_codes,
            warnings=warnings,
            unsupported=unsupported,
            labels=inp.labels,
            parser_digest_value=pdigest,
        )

    # -- encryption / magic -------------------------------------------------

    def _is_encrypted(self, body: bytes) -> bool:
        if _fitz is not None:
            try:
                doc = _fitz.open(stream=body, filetype="pdf")
                try:
                    if bool(getattr(doc, "is_encrypted", False) or doc.needs_pass):
                        return True
                finally:
                    doc.close()
            except Exception:
                pass
        if _PdfReader is not None:
            try:
                reader = _PdfReader(io.BytesIO(body), strict=False)
                if bool(getattr(reader, "is_encrypted", False)):
                    # Try empty password; still encrypted → protected.
                    try:
                        ok = reader.decrypt("")  # type: ignore[attr-defined]
                        if not ok:
                            return True
                        # Some versions return int
                        if isinstance(ok, int) and ok == 0:
                            return True
                    except _FileNotDecryptedError:
                        return True
                    except Exception:
                        return True
            except Exception:
                pass
        # Heuristic: Encrypt dictionary present without successful open later.
        if b"/Encrypt" in body[: min(len(body), 256_000)]:
            # Defer to open failure path; only flag when we cannot open cleanly.
            if _fitz is None and _PdfReader is None:
                return True
        return False

    # -- native + OCR extraction --------------------------------------------

    def _extract_native_pages(
        self,
        body: bytes,
        *,
        artifact_id: str,
        source_cid: str,
        content_sha: str,
        parser_digest_value: str,
        classification: DisclosureClassification,
        force_ocr: bool,
        ocr_by_page: Mapping[int, Mapping[str, Any]],
        reason_codes: list[str],
        warnings: list[str],
    ) -> tuple[list[_PageState], list[LayoutSignal]]:
        if _fitz is None:
            raise PdfOcrBridgeError(
                "pymupdf unavailable",
                code=BridgeReasonCode.UNSUPPORTED_MEDIA.value,
            )

        try:
            doc = _fitz.open(stream=body, filetype="pdf")
        except Exception as exc:
            raise PdfOcrBridgeError(
                "corrupt pdf",
                code=BridgeReasonCode.CORRUPT_DOCUMENT.value,
            ) from exc

        try:
            if bool(getattr(doc, "is_encrypted", False) or doc.needs_pass):
                raise PdfOcrBridgeError(
                    "password protected",
                    code=BridgeReasonCode.PASSWORD_PROTECTED.value,
                )
            page_count = int(doc.page_count)
            if page_count <= 0:
                raise PdfOcrBridgeError(
                    "empty pdf",
                    code=BridgeReasonCode.CORRUPT_DOCUMENT.value,
                )
            if page_count > self.bounds.max_pages:
                raise PdfOcrBridgeError(
                    "page limit exceeded",
                    code=BridgeReasonCode.PAGE_LIMIT_EXCEEDED.value,
                )

            pages: list[_PageState] = []
            layout: list[LayoutSignal] = []
            layout_seq = 0

            for page_index in range(page_count):
                # Checkpoint resume: skip OCR provider calls when completed.
                cp_key = self.checkpoint_store.checkpoint_key(
                    content_sha256=content_sha,
                    parser_digest_value=parser_digest_value,
                    page_index=page_index,
                )
                existing = self.checkpoint_store.get(cp_key)
                resume_ocr_payload: Mapping[str, Any] | None = None
                resumed = False
                if existing is not None and existing.completed:
                    reason_codes.append(BridgeReasonCode.CHECKPOINT_HIT.value)
                    reason_codes.append(BridgeReasonCode.OCR_RESUMED.value)
                    resume_ocr_payload = self.checkpoint_store.get_ocr_payload(cp_key)
                    resumed = True
                    # Fall through to re-extract native geometry cheaply, then
                    # re-apply cached OCR payload without calling the backend.

                page = doc.load_page(page_index)
                rect = page.rect
                rotation = int(page.rotation or 0)
                state = _PageState(
                    page_index=page_index,
                    width=float(rect.width),
                    height=float(rect.height),
                    rotation=rotation,
                    checkpoint_key=cp_key,
                    from_checkpoint=resumed,
                )
                if existing is not None and existing.render_digest:
                    state.render_digest = existing.render_digest
                    state.ocr_status = existing.ocr_status
                    state.ocr_confidence = existing.ocr_confidence

                # Native text blocks with geometry.
                blocks = page.get_text("dict") or {}
                reading_order = 0
                native_parts: list[str] = []
                for block in blocks.get("blocks") or []:
                    if block.get("type", 0) != 0:
                        continue
                    for line in block.get("lines") or []:
                        line_text_parts: list[str] = []
                        for span in line.get("spans") or []:
                            text = (span.get("text") or "").strip()
                            if not text:
                                continue
                            line_text_parts.append(text)
                            bbox = normalize_bbox(span.get("bbox"))
                            state.spans.append(
                                _SpanBuilder(
                                    text=text,
                                    origin=ExtractionOrigin.NATIVE,
                                    page_index=page_index,
                                    reading_order=reading_order,
                                    bbox=bbox,
                                    confidence=1.0,
                                )
                            )
                            reading_order += 1
                            if len(state.spans) >= self.bounds.max_spans_per_page:
                                warnings.append("max_spans_per_page_truncated")
                                break
                        if line_text_parts:
                            native_parts.append(" ".join(line_text_parts))
                        if len(state.spans) >= self.bounds.max_spans_per_page:
                            break
                    if len(state.spans) >= self.bounds.max_spans_per_page:
                        break

                # Fallback plain text if dict extraction empty but page has text.
                plain = (page.get_text("text") or "").strip()
                if not native_parts and plain:
                    native_parts.append(plain)
                    state.spans.append(
                        _SpanBuilder(
                            text=plain,
                            origin=ExtractionOrigin.NATIVE,
                            page_index=page_index,
                            reading_order=0,
                            bbox=(0.0, 0.0, state.width, state.height),
                            confidence=1.0,
                        )
                    )
                    reading_order = 1

                state.native_text = "\n".join(native_parts)
                if state.native_text.strip():
                    state.origins.append(ExtractionOrigin.NATIVE.value)
                    reason_codes.append(BridgeReasonCode.NATIVE_TEXT_EXTRACTED.value)

                # Layout signals: tables (heuristic), images, signatures/stamps.
                images = page.get_images(full=True) or []
                for img_i, _img in enumerate(images):
                    layout_seq += 1
                    layout.append(
                        LayoutSignal(
                            schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
                            item_id=f"layout:{artifact_id}:{layout_seq}",
                            artifact_id=artifact_id,
                            kind="image",
                            page_index=page_index,
                            bbox=None,
                            confidence=None,
                        )
                    )

                # Signature / stamp annotation heuristics.
                try:
                    for annot in page.annots() or []:
                        layout_seq += 1
                        kind = "annotation"
                        info = annot.info or {}
                        subtype = (annot.type[1] if annot.type else "") or ""
                        content_l = str(info.get("content") or "").lower()
                        if "sign" in content_l or subtype.lower() in {
                            "widget",
                            "ink",
                        }:
                            kind = "signature_presence"
                            reason_codes.append(
                                BridgeReasonCode.SIGNATURE_PRESENCE.value
                            )
                        if "stamp" in content_l or subtype.lower() == "stamp":
                            kind = "stamp"
                        layout.append(
                            LayoutSignal(
                                schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
                                item_id=f"layout:{artifact_id}:{layout_seq}",
                                artifact_id=artifact_id,
                                kind=kind,
                                page_index=page_index,
                                bbox=normalize_bbox(annot.rect),
                                confidence=None,
                            )
                        )
                except Exception:
                    pass

                # Table heuristic: look for multi-column line patterns in native text.
                if "|" in state.native_text or "\t" in state.native_text:
                    layout_seq += 1
                    layout.append(
                        LayoutSignal(
                            schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
                            item_id=f"layout:{artifact_id}:{layout_seq}",
                            artifact_id=artifact_id,
                            kind="table",
                            page_index=page_index,
                            bbox=None,
                            confidence=0.5,
                        )
                    )
                    reason_codes.append(BridgeReasonCode.TABLE_DETECTED.value)

                if layout:
                    reason_codes.append(BridgeReasonCode.LAYOUT_ITEMS_EXTRACTED.value)

                native_cov = estimate_native_char_coverage(
                    state.native_text,
                    page_width=state.width,
                    page_height=state.height,
                    min_chars=self.bounds.min_native_chars,
                )

                if rotation and rotation % 360 != 0:
                    state.status = PageBridgeStatus.ROTATED
                    reason_codes.append(BridgeReasonCode.ROTATED_PAGE.value)

                needs_ocr = should_run_page_ocr(
                    state.native_text,
                    coverage=native_cov,
                    coverage_threshold=self.bounds.native_coverage_threshold,
                    min_chars=self.bounds.min_native_chars,
                    force=force_ocr,
                )
                # Image-heavy + low text → OCR
                if not needs_ocr and images and native_cov < 0.25:
                    needs_ocr = True

                if not state.native_text.strip() and images:
                    state.status = PageBridgeStatus.IMAGE_ONLY
                    reason_codes.append(BridgeReasonCode.IMAGE_ONLY_PAGE.value)
                    needs_ocr = True
                elif not state.native_text.strip() and not images:
                    state.status = PageBridgeStatus.BLANK
                    reason_codes.append(BridgeReasonCode.BLANK_PAGE.value)

                # When resuming, inject cached OCR payload into ocr_by_page so
                # the backend is never re-invoked for this page.
                effective_ocr_by_page: dict[int, Mapping[str, Any]] = dict(ocr_by_page)
                if resumed and resume_ocr_payload is not None:
                    effective_ocr_by_page[page_index] = resume_ocr_payload

                if needs_ocr:
                    self._apply_ocr(
                        doc=doc,
                        page=page,
                        state=state,
                        artifact_id=artifact_id,
                        classification=classification,
                        ocr_by_page=effective_ocr_by_page,
                        force=force_ocr or needs_ocr,
                        reason_codes=reason_codes,
                        warnings=warnings,
                        reading_order_start=reading_order,
                        skip_backend=resumed and resume_ocr_payload is not None,
                    )
                else:
                    if not resumed:
                        state.ocr_status = "not_needed"

                if (
                    native_cov < self.bounds.low_coverage_review_threshold
                    and state.status
                    in (PageBridgeStatus.OK, PageBridgeStatus.ROTATED)
                    and not state.ocr_text.strip()
                ):
                    state.status = PageBridgeStatus.LOW_COVERAGE
                    reason_codes.append(BridgeReasonCode.LOW_COVERAGE.value)

                # Persist checkpoint (span contracts only, no plaintext text field).
                self._write_page_checkpoint(
                    state=state,
                    artifact_id=artifact_id,
                    source_cid=source_cid,
                    content_sha=content_sha,
                    parser_digest_value=parser_digest_value,
                    native_coverage=native_cov,
                )
                pages.append(state)

            return pages, layout
        finally:
            doc.close()

    def _page_from_checkpoint(self, cp: PageCheckpoint) -> _PageState:
        state = _PageState(
            page_index=cp.page_index,
            render_digest=cp.render_digest,
            ocr_status=cp.ocr_status,
            ocr_confidence=cp.ocr_confidence,
            status=cp.status,
            checkpoint_key=cp.checkpoint_key,
            from_checkpoint=True,
            native_text="",  # reconstructed from span digests only in finalize
        )
        # Reconstruct spans from contracts; text is not stored — use empty
        # placeholder keyed by digest so finalize still emits ExtractedSpan rows.
        for i, sd in enumerate(cp.span_dicts):
            origin_raw = str(sd.get("origin", ExtractionOrigin.UNKNOWN.value))
            try:
                origin = ExtractionOrigin(origin_raw)
            except ValueError:
                origin = ExtractionOrigin.UNKNOWN
            bbox = None
            if sd.get("bbox") is not None:
                bbox = normalize_bbox(sd.get("bbox"))
            # Checkpoint stores digests only; text recovery requires re-extract.
            # Mark page for re-hydration note via empty text + digest.
            text_placeholder = ""
            state.spans.append(
                _SpanBuilder(
                    text=text_placeholder,
                    origin=origin,
                    page_index=cp.page_index,
                    reading_order=int(sd.get("reading_order") or i),
                    bbox=bbox,
                    confidence=sd.get("confidence"),
                    image_digest=sd.get("image_digest") or cp.render_digest,
                    char_start=sd.get("char_start"),
                    char_end=sd.get("char_end"),
                )
            )
            if origin.value not in state.origins:
                state.origins.append(origin.value)
            if origin is ExtractionOrigin.OCR:
                state.ocr_text = state.ocr_text or ""  # digest-only resume
            if origin is ExtractionOrigin.NATIVE:
                state.native_text = state.native_text or ""
        # Attach digest map on state via first span metadata path: store digests
        # in image_digest field already; page_text_digest on checkpoint used later.
        state._checkpoint_span_dicts = list(cp.span_dicts)  # type: ignore[attr-defined]
        state._page_text_digest = cp.page_text_digest  # type: ignore[attr-defined]
        return state

    def _apply_ocr(
        self,
        *,
        doc: Any,
        page: Any,
        state: _PageState,
        artifact_id: str,
        classification: DisclosureClassification,
        ocr_by_page: Mapping[int, Mapping[str, Any]],
        force: bool,
        reason_codes: list[str],
        warnings: list[str],
        reading_order_start: int,
        skip_backend: bool = False,
    ) -> None:
        page_index = state.page_index
        payload: Mapping[str, Any] | None = ocr_by_page.get(page_index)
        applied_payload_for_cache: Mapping[str, Any] | None = None

        # Render page for OCR / digest even when payload is pre-supplied.
        # On resume with cached payload + existing render digest, skip re-render.
        image_bytes = b""
        if not (skip_backend and state.render_digest and payload is not None):
            try:
                zoom = max(1.0, float(self.bounds.render_dpi) / 72.0)
                mat = _fitz.Matrix(zoom, zoom)
                # Honor rotation for scanned pages.
                pix = page.get_pixmap(matrix=mat, alpha=False)
                image_bytes = pix.tobytes("png")
                state.render_digest = sha256_hex(image_bytes)
            except Exception:
                warnings.append("page_render_failed")
                if not state.render_digest:
                    state.render_digest = sha256_hex(
                        f"unrendered:{artifact_id}:{page_index}".encode("utf-8")
                    )

        if (
            payload is None
            and not skip_backend
            and self._ocr_backend is not None
            and force
        ):
            # Authorize provider route.
            authorized, deny_reason = self._authorize_ocr_route(
                classification=classification,
                backend=self._ocr_backend,
            )
            if not authorized:
                reason_codes.append(BridgeReasonCode.REMOTE_OCR_DENIED.value)
                self._record_provider_call(
                    backend=getattr(self._ocr_backend, "name", "unknown"),
                    kind=getattr(
                        self._ocr_backend, "kind", OcrProviderKind.NONE
                    ),
                    page_index=page_index,
                    artifact_id=artifact_id,
                    authorized=False,
                    outcome=deny_reason or "denied",
                    image_sha256=None,
                )
                state.ocr_status = "ocr_denied"
                state.status = PageBridgeStatus.OCR_UNAVAILABLE
                reason_codes.append(BridgeReasonCode.OCR_UNAVAILABLE.value)
                return
            try:
                payload = self._ocr_backend.ocr_page(
                    image_bytes,
                    page_index=page_index,
                    artifact_id=artifact_id,
                )
                applied_payload_for_cache = dict(payload) if payload else None
                self._record_provider_call(
                    backend=getattr(self._ocr_backend, "name", "local"),
                    kind=getattr(
                        self._ocr_backend, "kind", OcrProviderKind.LOCAL
                    ),
                    page_index=page_index,
                    artifact_id=artifact_id,
                    authorized=True,
                    outcome="ok",
                    image_sha256=sha256_hex(image_bytes) if image_bytes else None,
                )
                reason_codes.append(BridgeReasonCode.PROVIDER_CALL_RECORDED.value)
            except PrivacyBoundaryError:
                reason_codes.append(BridgeReasonCode.REMOTE_OCR_DENIED.value)
                self._record_provider_call(
                    backend=getattr(self._ocr_backend, "name", "remote"),
                    kind=OcrProviderKind.REMOTE,
                    page_index=page_index,
                    artifact_id=artifact_id,
                    authorized=False,
                    outcome="privacy_boundary",
                    image_sha256=None,
                )
                state.ocr_status = "ocr_denied"
                state.status = PageBridgeStatus.OCR_UNAVAILABLE
                reason_codes.append(BridgeReasonCode.OCR_UNAVAILABLE.value)
                return
            except Exception:
                warnings.append("ocr_backend_failed")
                self._record_provider_call(
                    backend=getattr(self._ocr_backend, "name", "local"),
                    kind=getattr(
                        self._ocr_backend, "kind", OcrProviderKind.LOCAL
                    ),
                    page_index=page_index,
                    artifact_id=artifact_id,
                    authorized=True,
                    outcome="error",
                    image_sha256=sha256_hex(image_bytes) if image_bytes else None,
                )
                state.ocr_status = "ocr_failed"
                state.status = PageBridgeStatus.OCR_UNAVAILABLE
                reason_codes.append(BridgeReasonCode.OCR_UNAVAILABLE.value)
                return

        if payload is None:
            state.ocr_status = "ocr_unavailable"
            if state.status in (
                PageBridgeStatus.IMAGE_ONLY,
                PageBridgeStatus.LOW_COVERAGE,
                PageBridgeStatus.OK,
                PageBridgeStatus.ROTATED,
                PageBridgeStatus.BLANK,
            ):
                # Preserve image_only if already set.
                if state.status is not PageBridgeStatus.IMAGE_ONLY:
                    state.status = PageBridgeStatus.OCR_UNAVAILABLE
            reason_codes.append(BridgeReasonCode.OCR_UNAVAILABLE.value)
            return

        if applied_payload_for_cache is None and payload is not None:
            applied_payload_for_cache = dict(payload)
        # Stash for checkpoint put (process-local resume cache).
        state._ocr_payload_for_cache = applied_payload_for_cache  # type: ignore[attr-defined]

        text = str(payload.get("text") or "")
        confidence = payload.get("confidence")
        try:
            confidence_f = (
                float(confidence) if confidence is not None else None
            )
        except (TypeError, ValueError):
            confidence_f = None
        if confidence_f is not None:
            confidence_f = max(0.0, min(1.0, confidence_f))
        status = str(payload.get("status") or "ok")
        word_boxes = payload.get("word_boxes") or payload.get("text_blocks") or []
        if payload.get("render_digest"):
            state.render_digest = str(payload["render_digest"])

        # Confidence gate.
        if (
            confidence_f is not None
            and confidence_f < self.bounds.ocr_confidence_threshold
        ):
            state.ocr_status = "low_confidence"
            state.ocr_confidence = confidence_f
            state.status = PageBridgeStatus.OCR_LOW_CONFIDENCE
            reason_codes.append(BridgeReasonCode.OCR_CONFIDENCE_GATED.value)
            # Still retain text but mark for review — do not invent content.
            if not text.strip():
                return
        elif status in {"ocr_unavailable", "ocr_failed", "empty"}:
            state.ocr_status = status
            state.ocr_confidence = confidence_f
            state.status = PageBridgeStatus.OCR_UNAVAILABLE
            reason_codes.append(BridgeReasonCode.OCR_UNAVAILABLE.value)
            return
        else:
            state.ocr_status = "ok"
            state.ocr_confidence = confidence_f
            if state.status in (
                PageBridgeStatus.IMAGE_ONLY,
                PageBridgeStatus.LOW_COVERAGE,
                PageBridgeStatus.OCR_NEEDED,
                PageBridgeStatus.OK,
                PageBridgeStatus.ROTATED,
            ):
                state.status = PageBridgeStatus.OCR_APPLIED

        state.ocr_text = text
        if text.strip():
            state.origins.append(ExtractionOrigin.OCR.value)
            reason_codes.append(BridgeReasonCode.OCR_TEXT_EXTRACTED.value)
            reason_codes.append(BridgeReasonCode.OCR_FALLBACK_APPLIED.value)

        # Span construction from word boxes or full text.
        order = reading_order_start
        if isinstance(word_boxes, Sequence) and word_boxes and not isinstance(
            word_boxes, (str, bytes)
        ):
            for wb in word_boxes:
                if not isinstance(wb, Mapping):
                    continue
                wtext = str(wb.get("text") or "").strip()
                if not wtext:
                    continue
                wb_conf = wb.get("confidence", confidence_f)
                try:
                    wb_conf_f = float(wb_conf) if wb_conf is not None else confidence_f
                except (TypeError, ValueError):
                    wb_conf_f = confidence_f
                if (
                    wb_conf_f is not None
                    and wb_conf_f < self.bounds.ocr_confidence_threshold
                ):
                    # Skip low-confidence word boxes individually.
                    reason_codes.append(BridgeReasonCode.OCR_CONFIDENCE_GATED.value)
                    continue
                state.spans.append(
                    _SpanBuilder(
                        text=wtext,
                        origin=ExtractionOrigin.OCR,
                        page_index=page_index,
                        reading_order=order,
                        bbox=normalize_bbox(wb.get("bbox")),
                        confidence=wb_conf_f,
                        image_digest=state.render_digest,
                    )
                )
                order += 1
                if len(state.spans) >= self.bounds.max_spans_per_page:
                    break
        elif text.strip():
            state.spans.append(
                _SpanBuilder(
                    text=text.strip(),
                    origin=ExtractionOrigin.OCR,
                    page_index=page_index,
                    reading_order=order,
                    bbox=(0.0, 0.0, state.width or 0.0, state.height or 0.0),
                    confidence=confidence_f,
                    image_digest=state.render_digest,
                )
            )

        # Native/OCR disagreement signal.
        if state.native_text.strip() and state.ocr_text.strip():
            native_norm = _normalize_ws(state.native_text).lower()
            ocr_norm = _normalize_ws(state.ocr_text).lower()
            if native_norm and ocr_norm and native_norm != ocr_norm:
                # Token overlap
                nt = set(re.findall(r"[A-Za-z0-9]+", native_norm))
                ot = set(re.findall(r"[A-Za-z0-9]+", ocr_norm))
                if nt and ot:
                    jaccard = len(nt & ot) / len(nt | ot)
                    if jaccard < 0.5:
                        state.disagreement = True
                        state.status = PageBridgeStatus.DISAGREEMENT

    def _authorize_ocr_route(
        self,
        *,
        classification: DisclosureClassification,
        backend: OcrBackend,
    ) -> tuple[bool, str | None]:
        kind = getattr(backend, "kind", OcrProviderKind.LOCAL)
        if isinstance(kind, str):
            try:
                kind = OcrProviderKind(kind)
            except ValueError:
                kind = OcrProviderKind.NONE
        if kind in (OcrProviderKind.LOCAL, OcrProviderKind.INJECTED, OcrProviderKind.NONE):
            return True, None
        if kind is OcrProviderKind.REMOTE:
            private = is_private_classification(classification)
            if private and not self.policy.allow_remote_ocr_for_private:
                return False, "remote_ocr_denied_private"
            if not private and not self.policy.allow_remote_ocr_for_public:
                return False, "remote_ocr_denied_public"
            # Privacy policy remote prompt check.
            decision = self.policy.privacy.evaluate_sink(
                classification,
                PublicSink.REMOTE_PROMPT,
                ContentKind.DOCUMENT_BYTES,
            )
            if hasattr(decision, "allowed") and not decision.allowed:
                return False, "privacy_policy_denied_remote"
            return True, None
        return False, "unknown_provider_kind"

    def _record_provider_call(
        self,
        *,
        backend: str,
        kind: OcrProviderKind | str,
        page_index: int | None,
        artifact_id: str,
        authorized: bool,
        outcome: str,
        image_sha256: str | None,
    ) -> None:
        if isinstance(kind, str):
            try:
                kind = OcrProviderKind(kind)
            except ValueError:
                kind = OcrProviderKind.NONE
        self._provider_calls.append(
            ProviderCallRecord(
                schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
                call_id=f"call:{uuid.uuid4().hex[:16]}",
                backend=str(backend),
                kind=kind,
                page_index=page_index,
                artifact_id=artifact_id,
                authorized=authorized,
                outcome=outcome,
                image_sha256=image_sha256,
            )
        )

    def _write_page_checkpoint(
        self,
        *,
        state: _PageState,
        artifact_id: str,
        source_cid: str,
        content_sha: str,
        parser_digest_value: str,
        native_coverage: float,
    ) -> None:
        if state.checkpoint_key is None:
            return
        # Span contracts without plaintext text field.
        span_dicts: list[dict[str, Any]] = []
        cursor = 0
        page_text_parts: list[str] = []
        for i, sb in enumerate(
            sorted(state.spans, key=lambda s: s.reading_order)
        ):
            start = cursor
            end = start + len(sb.text)
            cursor = end + 1
            page_text_parts.append(sb.text)
            span_dicts.append(
                {
                    "origin": sb.origin.value,
                    "page_index": sb.page_index,
                    "reading_order": sb.reading_order,
                    "bbox": list(sb.bbox) if sb.bbox is not None else None,
                    "confidence": sb.confidence,
                    "text_digest": text_digest(sb.text) if sb.text else None,
                    "image_digest": sb.image_digest or state.render_digest,
                    "char_start": start,
                    "char_end": end,
                    # deliberately no "text" key — fail closed on plaintext persist
                }
            )
        page_text = "\n".join(page_text_parts)
        cp = PageCheckpoint(
            schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
            checkpoint_key=state.checkpoint_key,
            artifact_id=artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            parser_digest=parser_digest_value,
            page_index=state.page_index,
            status=state.status,
            ocr_status=state.ocr_status,
            ocr_confidence=state.ocr_confidence,
            span_dicts=tuple(span_dicts),
            page_text_digest=text_digest(page_text) if page_text else None,
            render_digest=state.render_digest,
            native_coverage=native_coverage,
            completed=True,
        )
        ocr_payload = getattr(state, "_ocr_payload_for_cache", None)
        try:
            self.checkpoint_store.put(
                cp,
                ocr_payload=ocr_payload,
                page_text=page_text if page_text else None,
            )
        except PdfOcrBridgeError:
            raise
        except Exception:
            # Checkpoint failures must not fail extraction; warn only.
            pass

    # -- finalize -----------------------------------------------------------

    def _finalize_success(
        self,
        *,
        bridge_id: str,
        artifact_id: str,
        source_cid: str,
        content_sha: str,
        classification: DisclosureClassification,
        pages: list[_PageState],
        layout: list[LayoutSignal],
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        parser_digest_value: str,
    ) -> PdfOcrBridgeResult:
        spans: list[ExtractedSpan] = []
        coverages: list[PageCoverageReceipt] = []
        page_texts: dict[str, str] = {}
        full_parts: list[str] = []
        span_seq = 0
        needs_review = False

        for state in pages:
            # Prefer live span text; for pure checkpoint resume without text,
            # emit digest-only spans (char offsets from checkpoint).
            checkpoint_span_dicts: list[Mapping[str, Any]] | None = getattr(
                state, "_checkpoint_span_dicts", None
            )
            ordered = sorted(state.spans, key=lambda s: s.reading_order)
            cursor = 0
            rebuilt: list[str] = []

            if state.from_checkpoint and checkpoint_span_dicts:
                for sd in checkpoint_span_dicts:
                    span_seq += 1
                    span_id = f"span:{bridge_id}:{span_seq}"
                    origin_raw = str(sd.get("origin", ExtractionOrigin.UNKNOWN.value))
                    try:
                        origin = ExtractionOrigin(origin_raw)
                    except ValueError:
                        origin = ExtractionOrigin.UNKNOWN
                    bbox = normalize_bbox(sd.get("bbox"))
                    spans.append(
                        ExtractedSpan(
                            schema_version=CONTRACTS_SCHEMA_VERSION,
                            span_id=span_id,
                            artifact_id=artifact_id,
                            page_index=state.page_index,
                            char_start=sd.get("char_start"),
                            char_end=sd.get("char_end"),
                            bbox=bbox,
                            origin=origin,
                            reading_order=sd.get("reading_order"),
                            confidence=sd.get("confidence"),
                            text_digest=sd.get("text_digest"),
                            image_digest=sd.get("image_digest") or state.render_digest,
                            classification=classification,
                        )
                    )
                page_text = ""  # body not rehydrated from digest-only checkpoint
                page_texts[str(state.page_index)] = page_text
            else:
                for sb in ordered:
                    text = sb.text
                    if sb.char_start is None:
                        start = cursor
                        end = start + len(text)
                        cursor = end + 1
                    else:
                        start = sb.char_start
                        end = (
                            sb.char_end
                            if sb.char_end is not None
                            else start + len(text)
                        )
                        cursor = max(cursor, end + 1)
                    span_seq += 1
                    span_id = f"span:{bridge_id}:{span_seq}"
                    spans.append(
                        ExtractedSpan(
                            schema_version=CONTRACTS_SCHEMA_VERSION,
                            span_id=span_id,
                            artifact_id=artifact_id,
                            page_index=state.page_index,
                            char_start=start,
                            char_end=end,
                            bbox=sb.bbox,
                            origin=sb.origin,
                            reading_order=sb.reading_order,
                            confidence=sb.confidence,
                            text_digest=text_digest(text) if text else None,
                            image_digest=sb.image_digest or state.render_digest,
                            classification=classification,
                        )
                    )
                    rebuilt.append(text)
                page_text = (
                    state.native_text
                    if state.native_text.strip() and not state.ocr_text.strip()
                    else (
                        "\n".join(p for p in [state.native_text, state.ocr_text] if p.strip())
                        if state.native_text.strip() and state.ocr_text.strip()
                        else (state.ocr_text or state.native_text or "\n".join(rebuilt))
                    )
                )
                # Prefer ordered span rebuild when available.
                if rebuilt:
                    page_text = "\n".join(rebuilt)
                page_texts[str(state.page_index)] = page_text
                if page_text:
                    full_parts.append(page_text)

            native_count = len(_normalize_ws(state.native_text))
            ocr_count = len(_normalize_ws(state.ocr_text))
            merged_count = len(_normalize_ws(page_text))
            native_cov = estimate_native_char_coverage(
                state.native_text,
                page_width=state.width or 0.0,
                page_height=state.height or 0.0,
                min_chars=self.bounds.min_native_chars,
            )
            coverage_ratio = estimate_native_char_coverage(
                page_text,
                page_width=state.width or 0.0,
                page_height=state.height or 0.0,
                min_chars=self.bounds.min_native_chars,
            )
            status = state.status
            if (
                coverage_ratio < self.bounds.low_coverage_review_threshold
                and status is PageBridgeStatus.OK
            ):
                status = PageBridgeStatus.LOW_COVERAGE
                needs_review = True

            if status in {
                PageBridgeStatus.LOW_COVERAGE,
                PageBridgeStatus.IMAGE_ONLY,
                PageBridgeStatus.OCR_UNAVAILABLE,
                PageBridgeStatus.OCR_LOW_CONFIDENCE,
                PageBridgeStatus.DISAGREEMENT,
                PageBridgeStatus.OCR_NEEDED,
                PageBridgeStatus.PASSWORD_PROTECTED,
                PageBridgeStatus.CORRUPT,
            }:
                needs_review = True

            coverages.append(
                PageCoverageReceipt(
                    schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
                    page_index=state.page_index,
                    artifact_id=artifact_id,
                    source_cid=source_cid,
                    native_char_count=native_count,
                    ocr_char_count=ocr_count,
                    merged_char_count=merged_count,
                    native_coverage=native_cov,
                    coverage_ratio=coverage_ratio,
                    has_native_text=bool(state.native_text.strip()),
                    has_ocr_text=bool(state.ocr_text.strip()),
                    rotation=state.rotation,
                    status=status,
                    ocr_status=state.ocr_status,
                    ocr_confidence=state.ocr_confidence,
                    origins_present=tuple(dict.fromkeys(state.origins or [])),
                    disagreement=state.disagreement,
                    render_digest=state.render_digest,
                    page_width=state.width or None,
                    page_height=state.height or None,
                    checkpoint_key=state.checkpoint_key,
                )
            )

        # Deduplicate reason codes preserving order.
        seen: set[str] = set()
        unique_reasons: list[str] = []
        for r in reason_codes:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)

        if needs_review:
            disposition = BridgeDisposition.REVIEW
            review_state = ReviewState.REQUIRED
        else:
            disposition = BridgeDisposition.EXTRACTED
            review_state = ReviewState.NOT_REQUIRED

        # Link layout signals to first span on same page.
        span_by_page: dict[int, str] = {}
        for s in spans:
            if s.page_index is not None and s.page_index not in span_by_page:
                span_by_page[s.page_index] = s.span_id
        fixed_layout: list[LayoutSignal] = []
        for item in layout:
            if item.span_id is None and item.page_index is not None:
                sid = span_by_page.get(item.page_index)
                if sid is not None:
                    fixed_layout.append(
                        LayoutSignal(
                            schema_version=item.schema_version,
                            item_id=item.item_id,
                            artifact_id=item.artifact_id,
                            kind=item.kind,
                            page_index=item.page_index,
                            bbox=item.bbox,
                            span_id=sid,
                            confidence=item.confidence,
                        )
                    )
                    continue
            fixed_layout.append(item)

        return PdfOcrBridgeResult(
            schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
            bridge_id=bridge_id,
            artifact_id=artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha,
            classification=classification,
            disposition=disposition,
            review_state=review_state,
            page_count=len(pages),
            spans=tuple(spans),
            page_coverage=tuple(coverages),
            layout_signals=tuple(fixed_layout),
            reason_codes=tuple(unique_reasons),
            warnings=tuple(dict.fromkeys(warnings)),
            unsupported=tuple(dict.fromkeys(unsupported)),
            provider_calls=tuple(self._provider_calls),
            parser_digest=parser_digest_value,
            page_texts=MappingProxyType(page_texts),
            full_text="\n\n".join(full_parts),
            labels=MappingProxyType(dict(labels)),
            retained=True,
        )

    def _finalize_reject(
        self,
        *,
        bridge_id: str,
        artifact_id: str,
        source_cid: str,
        content_sha256: str,
        classification: DisclosureClassification,
        disposition: BridgeDisposition,
        reason_codes: list[str],
        warnings: list[str],
        unsupported: list[str],
        labels: Mapping[str, str],
        parser_digest_value: str,
        page_status: PageBridgeStatus | None = None,
    ) -> PdfOcrBridgeResult:
        review = (
            ReviewState.REQUIRED
            if disposition
            in (BridgeDisposition.REVIEW, BridgeDisposition.QUARANTINE)
            else ReviewState.NOT_REQUIRED
        )
        return PdfOcrBridgeResult(
            schema_version=PDF_OCR_BRIDGE_SCHEMA_VERSION,
            bridge_id=bridge_id,
            artifact_id=artifact_id,
            source_cid=source_cid,
            content_sha256=content_sha256,
            classification=classification,
            disposition=disposition,
            review_state=review,
            page_count=0,
            spans=(),
            page_coverage=(),
            layout_signals=(),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(dict.fromkeys(warnings)),
            unsupported=tuple(dict.fromkeys(unsupported)),
            provider_calls=tuple(self._provider_calls),
            parser_digest=parser_digest_value,
            page_texts=MappingProxyType({}),
            full_text="",
            labels=MappingProxyType(dict(labels)),
            retained=False,
        )


def bridge_pdf(
    *,
    artifact_id: str,
    content_bytes: bytes,
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN,
    source_cid: str | None = None,
    ocr_backend: OcrBackend | OcrCallable | None = None,
    force_ocr: bool = False,
    ocr_by_page: Mapping[int, Mapping[str, Any]] | None = None,
    checkpoint_store: CheckpointStore | None = None,
    **kwargs: Any,
) -> PdfOcrBridgeResult:
    """Convenience entry point for one-shot PDF bridge processing."""
    bridge = PdfOcrBridge(
        ocr_backend=ocr_backend,
        checkpoint_store=checkpoint_store,
    )
    return bridge.process(
        artifact_id=artifact_id,
        content_bytes=content_bytes,
        classification=classification,
        source_cid=source_cid,
        force_ocr=force_ocr,
        ocr_by_page=ocr_by_page or {},
        **kwargs,
    )


__all__ = [
    "PDF_OCR_BRIDGE_INTERFACE",
    "PDF_OCR_BRIDGE_SCHEMA_VERSION",
    "BridgeDisposition",
    "BridgeReasonCode",
    "CheckpointStore",
    "DeniedRemoteOcrBackend",
    "LayoutSignal",
    "OcrBackend",
    "OcrCallable",
    "OcrProviderKind",
    "PageBridgeStatus",
    "PageCheckpoint",
    "PageCoverageReceipt",
    "PdfOcrBridge",
    "PdfOcrBridgeBounds",
    "PdfOcrBridgeError",
    "PdfOcrBridgeInput",
    "PdfOcrBridgePolicy",
    "PdfOcrBridgeResult",
    "ProviderCallRecord",
    "RecordingOcrBackend",
    "bridge_pdf",
    "content_addressed_cid",
    "estimate_native_char_coverage",
    "parser_digest",
    "sha256_hex",
    "should_run_page_ocr",
    "text_digest",
]
