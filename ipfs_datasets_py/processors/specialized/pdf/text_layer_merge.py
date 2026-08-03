"""
Native / rendered-OCR / embedded-image text layer merge with provenance.

Merges PDF text sources without naive concatenation-duplication while preserving
page, bounding-box, origin, confidence, and coverage signals required by the
patent-legal document foundation pipeline (PATLAW-004 / PATLAW-G012).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

# Span / page origins
ORIGIN_NATIVE = "native"
ORIGIN_RENDERED_OCR = "rendered_ocr"
ORIGIN_EMBEDDED_IMAGE_OCR = "embedded_image_ocr"

# Page / OCR status codes (explicit; never implied as high confidence)
STATUS_OK = "ok"
STATUS_LOW_COVERAGE = "low_coverage"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_OCR_UNAVAILABLE = "ocr_unavailable"
STATUS_OCR_FAILED = "ocr_failed"
STATUS_OCR_NOT_NEEDED = "ocr_not_needed"
STATUS_EMPTY = "empty"
STATUS_DISAGREEMENT = "disagreement"

# Defaults (override via merge kwargs)
DEFAULT_NATIVE_COVERAGE_THRESHOLD = 0.15  # chars per page-area unit proxy
DEFAULT_MIN_NATIVE_CHARS = 40
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_DEDUP_SIMILARITY = 0.92

BBox = Tuple[float, float, float, float]


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _fingerprint(text: str) -> str:
    return hashlib.sha256(_normalize_ws(text).lower().encode("utf-8")).hexdigest()


def _token_set(text: str) -> set:
    return {t for t in re.findall(r"[A-Za-z0-9]+", (text or "").lower()) if t}


def text_similarity(a: str, b: str) -> float:
    """Jaccard similarity over alphanumeric tokens; 1.0 for equal empty strings."""
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
    """
    Estimate how much readable native text a page has.

    Returns a value in [0.0, 1.0]. Empty/whitespace text is 0.0. When page
    geometry is unknown, coverage is based on a soft character budget.
    """
    cleaned = _normalize_ws(text)
    if not cleaned:
        return 0.0
    n = len(cleaned)
    if page_width > 0 and page_height > 0:
        # Rough printable-capacity proxy (~chars per page for legal letter size).
        capacity = max(min_chars, (page_width * page_height) / 180.0)
        return max(0.0, min(1.0, n / capacity))
    # Soft ramp: min_chars → ~0.5, 4x min_chars → 1.0
    return max(0.0, min(1.0, n / float(max(min_chars * 2, 1))))


def should_run_page_ocr(
    native_text: str,
    *,
    coverage: Optional[float] = None,
    coverage_threshold: float = DEFAULT_NATIVE_COVERAGE_THRESHOLD,
    min_chars: int = DEFAULT_MIN_NATIVE_CHARS,
    force: bool = False,
) -> bool:
    """Return True when page-level OCR is warranted for low native coverage."""
    if force:
        return True
    if coverage is None:
        coverage = estimate_native_char_coverage(native_text, min_chars=min_chars)
    if coverage < coverage_threshold:
        return True
    if len(_normalize_ws(native_text)) < min_chars:
        return True
    return False


def normalize_bbox(bbox: Any) -> Optional[BBox]:
    """Normalize bbox sequences / mappings into (x0, y0, x1, y1)."""
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


@dataclass
class TextSpan:
    """A single provenance-bearing text span from one extraction origin."""

    text: str
    page: int
    origin: str = ORIGIN_NATIVE
    bbox: Optional[BBox] = None
    confidence: Optional[float] = None
    engine: Optional[str] = None
    reading_order: int = 0
    char_start: int = 0
    char_end: int = 0
    render_digest: Optional[str] = None
    image_index: Optional[int] = None
    status: str = STATUS_OK
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.bbox is not None:
            d["bbox"] = list(self.bbox)
        return d


@dataclass
class PageCoverageReceipt:
    """Per-page coverage and provenance receipt."""

    page: int
    native_char_count: int = 0
    ocr_char_count: int = 0
    merged_char_count: int = 0
    native_coverage: float = 0.0
    coverage_ratio: float = 0.0
    has_native_text: bool = False
    has_ocr_text: bool = False
    rotation: int = 0
    status: str = STATUS_EMPTY
    ocr_status: str = STATUS_OCR_NOT_NEEDED
    ocr_confidence: Optional[float] = None
    origins_present: List[str] = field(default_factory=list)
    disagreement: bool = False
    disagreement_score: float = 0.0
    render_digest: Optional[str] = None
    available_engines: List[str] = field(default_factory=list)
    engines_attempted: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PageMergeResult:
    """Merged text layers for a single page."""

    page: int
    text: str
    spans: List[TextSpan]
    coverage: PageCoverageReceipt
    selected_origins: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "text": self.text,
            "spans": [s.to_dict() for s in self.spans],
            "coverage": self.coverage.to_dict(),
            "selected_origins": list(self.selected_origins),
        }


@dataclass
class DocumentMergeResult:
    """Document-level merge of all page layers."""

    pages: List[PageMergeResult]
    full_text: str
    page_coverage: List[PageCoverageReceipt]
    overall_coverage: float
    overall_ocr_confidence: Optional[float]
    ocr_status: str
    warnings: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages": [p.to_dict() for p in self.pages],
            "full_text": self.full_text,
            "page_coverage": [c.to_dict() for c in self.page_coverage],
            "overall_coverage": self.overall_coverage,
            "overall_ocr_confidence": self.overall_ocr_confidence,
            "ocr_status": self.ocr_status,
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }


def _spans_from_native_blocks(
    page: int,
    text_blocks: Sequence[Mapping[str, Any]],
) -> List[TextSpan]:
    spans: List[TextSpan] = []
    order = 0
    for block in text_blocks or []:
        content = block.get("content") or block.get("text") or ""
        if not isinstance(content, str) or not content.strip():
            continue
        spans.append(
            TextSpan(
                text=content.strip(),
                page=page,
                origin=ORIGIN_NATIVE,
                bbox=normalize_bbox(block.get("bbox") or block.get("position")),
                confidence=1.0 if block.get("confidence") is None else float(block["confidence"]),
                engine="native",
                reading_order=order,
                status=STATUS_OK,
            )
        )
        order += 1
    return spans


def _spans_from_ocr_payload(
    page: int,
    ocr_payload: Mapping[str, Any],
    *,
    origin: str,
    default_image_index: Optional[int] = None,
) -> Tuple[List[TextSpan], Dict[str, Any]]:
    """Convert an OCR engine / page result into spans + status metadata."""
    meta: Dict[str, Any] = {
        "status": ocr_payload.get("status") or STATUS_OK,
        "engine": ocr_payload.get("engine") or ocr_payload.get("engine_used"),
        "confidence": ocr_payload.get("confidence"),
        "available_engines": list(ocr_payload.get("available_engines") or []),
        "engines_attempted": list(ocr_payload.get("engines_attempted") or []),
        "error": ocr_payload.get("error"),
        "render_digest": ocr_payload.get("render_digest"),
    }
    status = meta["status"]
    conf = meta["confidence"]
    if status in (STATUS_OCR_UNAVAILABLE, "unavailable"):
        meta["status"] = STATUS_OCR_UNAVAILABLE
        meta["confidence"] = None if conf is None else conf
        return [], meta
    if status in (STATUS_OCR_FAILED, "failed") or ocr_payload.get("engine") in ("none", "failed"):
        if not (ocr_payload.get("text") or "").strip():
            meta["status"] = STATUS_OCR_FAILED
            return [], meta

    text = (ocr_payload.get("text") or "").strip()
    engine = meta["engine"]
    render_digest = meta["render_digest"]
    image_index = ocr_payload.get("image_index", default_image_index)

    spans: List[TextSpan] = []
    word_boxes = ocr_payload.get("word_boxes") or ocr_payload.get("text_blocks") or []
    if word_boxes:
        for i, wb in enumerate(word_boxes):
            if not isinstance(wb, Mapping):
                continue
            wtext = (wb.get("text") or "").strip()
            if not wtext:
                continue
            wconf = wb.get("confidence")
            if wconf is not None:
                try:
                    wconf = float(wconf)
                    # Tesseract often uses 0-100
                    if wconf > 1.0:
                        wconf = wconf / 100.0
                except (TypeError, ValueError):
                    wconf = conf
            else:
                wconf = conf if conf is None else float(conf)
            spans.append(
                TextSpan(
                    text=wtext,
                    page=page,
                    origin=origin,
                    bbox=normalize_bbox(wb.get("bbox") or wb.get("box") or wb.get("position")),
                    confidence=wconf,
                    engine=engine,
                    reading_order=i,
                    render_digest=render_digest,
                    image_index=image_index,
                    status=STATUS_LOW_CONFIDENCE
                    if (wconf is not None and wconf < DEFAULT_LOW_CONFIDENCE_THRESHOLD)
                    else STATUS_OK,
                )
            )
    elif text:
        conf_f = None if conf is None else float(conf)
        if conf_f is not None and conf_f > 1.0:
            conf_f = conf_f / 100.0
        spans.append(
            TextSpan(
                text=text,
                page=page,
                origin=origin,
                bbox=normalize_bbox(ocr_payload.get("bbox")),
                confidence=conf_f,
                engine=engine,
                reading_order=0,
                render_digest=render_digest,
                image_index=image_index,
                status=STATUS_LOW_CONFIDENCE
                if (conf_f is not None and conf_f < DEFAULT_LOW_CONFIDENCE_THRESHOLD)
                else STATUS_OK,
            )
        )

    if conf is not None:
        try:
            conf_f = float(conf)
            if conf_f > 1.0:
                conf_f = conf_f / 100.0
            meta["confidence"] = conf_f
            if conf_f < DEFAULT_LOW_CONFIDENCE_THRESHOLD and spans:
                meta["status"] = STATUS_LOW_CONFIDENCE
        except (TypeError, ValueError):
            meta["confidence"] = None
    elif not spans and meta["status"] == STATUS_OK:
        meta["status"] = STATUS_EMPTY

    return spans, meta


def _assign_char_offsets(spans: List[TextSpan], separator: str = "\n") -> str:
    """Assign char_start/char_end over concatenated span text; return full text."""
    parts: List[str] = []
    cursor = 0
    for i, span in enumerate(spans):
        if i > 0:
            cursor += len(separator)
        span.char_start = cursor
        span.char_end = cursor + len(span.text)
        cursor = span.char_end
        parts.append(span.text)
    return separator.join(parts)


def _dedupe_spans(
    spans: Sequence[TextSpan],
    *,
    similarity_threshold: float = DEFAULT_DEDUP_SIMILARITY,
) -> List[TextSpan]:
    """
    Drop near-duplicate spans across origins, preferring native over OCR.

    Origin priority: native > rendered_ocr > embedded_image_ocr.
    """
    priority = {
        ORIGIN_NATIVE: 0,
        ORIGIN_RENDERED_OCR: 1,
        ORIGIN_EMBEDDED_IMAGE_OCR: 2,
    }
    ordered = sorted(
        spans,
        key=lambda s: (priority.get(s.origin, 9), s.reading_order, -(s.confidence or 0.0)),
    )
    kept: List[TextSpan] = []
    for span in ordered:
        if not span.text.strip():
            continue
        dup = False
        for existing in kept:
            if text_similarity(span.text, existing.text) >= similarity_threshold:
                # Prefer keeping the earlier (higher priority) span.
                dup = True
                # Record disagreement when different origins disagree slightly.
                if (
                    span.origin != existing.origin
                    and text_similarity(span.text, existing.text) < 0.995
                    and _normalize_ws(span.text).lower() != _normalize_ws(existing.text).lower()
                ):
                    existing.metadata.setdefault("alternate_origins", []).append(
                        {
                            "origin": span.origin,
                            "engine": span.engine,
                            "confidence": span.confidence,
                            "text_fingerprint": _fingerprint(span.text),
                        }
                    )
                break
        if not dup:
            kept.append(span)
    # Stable reading order by page geometry then original order
    kept.sort(key=lambda s: (s.reading_order, s.origin))
    return kept


def merge_page_layers(
    page: int,
    *,
    native_blocks: Optional[Sequence[Mapping[str, Any]]] = None,
    native_text: Optional[str] = None,
    rendered_ocr: Optional[Mapping[str, Any]] = None,
    embedded_image_ocr: Optional[Sequence[Mapping[str, Any]]] = None,
    page_width: float = 0.0,
    page_height: float = 0.0,
    rotation: int = 0,
    render_digest: Optional[str] = None,
    coverage_threshold: float = DEFAULT_NATIVE_COVERAGE_THRESHOLD,
    min_native_chars: int = DEFAULT_MIN_NATIVE_CHARS,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    dedup_similarity: float = DEFAULT_DEDUP_SIMILARITY,
    available_engines: Optional[Sequence[str]] = None,
) -> PageMergeResult:
    """
    Merge native, rendered-page OCR, and embedded-image OCR for one page.

    Returns merged text, provenance spans, and a coverage receipt. Missing OCR
    is never treated as high confidence.
    """
    native_spans = _spans_from_native_blocks(page, native_blocks or [])
    if not native_spans and native_text and native_text.strip():
        native_spans = [
            TextSpan(
                text=native_text.strip(),
                page=page,
                origin=ORIGIN_NATIVE,
                confidence=1.0,
                engine="native",
                reading_order=0,
            )
        ]

    native_joined = "\n".join(s.text for s in native_spans)
    native_coverage = estimate_native_char_coverage(
        native_joined,
        page_width=page_width,
        page_height=page_height,
        min_chars=min_native_chars,
    )

    all_spans: List[TextSpan] = list(native_spans)
    ocr_meta_list: List[Dict[str, Any]] = []
    ocr_confidences: List[float] = []
    engines_attempted: List[str] = []
    available = list(available_engines or [])
    warnings: List[str] = []
    ocr_status = STATUS_OCR_NOT_NEEDED
    page_render_digest = render_digest

    if rendered_ocr is not None:
        r_spans, r_meta = _spans_from_ocr_payload(
            page, rendered_ocr, origin=ORIGIN_RENDERED_OCR
        )
        all_spans.extend(r_spans)
        ocr_meta_list.append(r_meta)
        if r_meta.get("render_digest"):
            page_render_digest = r_meta["render_digest"]
        if r_meta.get("confidence") is not None:
            ocr_confidences.append(float(r_meta["confidence"]))
        engines_attempted.extend(r_meta.get("engines_attempted") or [])
        if r_meta.get("engine"):
            engines_attempted.append(str(r_meta["engine"]))
        if r_meta.get("available_engines"):
            available = list(dict.fromkeys(available + list(r_meta["available_engines"])))
        ocr_status = r_meta.get("status") or ocr_status

    for img_ocr in embedded_image_ocr or []:
        e_spans, e_meta = _spans_from_ocr_payload(
            page,
            img_ocr,
            origin=ORIGIN_EMBEDDED_IMAGE_OCR,
            default_image_index=img_ocr.get("image_index"),
        )
        all_spans.extend(e_spans)
        ocr_meta_list.append(e_meta)
        if e_meta.get("confidence") is not None:
            ocr_confidences.append(float(e_meta["confidence"]))
        engines_attempted.extend(e_meta.get("engines_attempted") or [])
        if e_meta.get("engine"):
            engines_attempted.append(str(e_meta["engine"]))
        if e_meta.get("available_engines"):
            available = list(dict.fromkeys(available + list(e_meta["available_engines"])))
        # Prefer more severe statuses
        st = e_meta.get("status")
        if st == STATUS_OCR_UNAVAILABLE:
            ocr_status = STATUS_OCR_UNAVAILABLE
        elif st == STATUS_OCR_FAILED and ocr_status not in (
            STATUS_OCR_UNAVAILABLE,
            STATUS_LOW_CONFIDENCE,
        ):
            ocr_status = STATUS_OCR_FAILED
        elif st == STATUS_LOW_CONFIDENCE and ocr_status not in (STATUS_OCR_UNAVAILABLE,):
            ocr_status = STATUS_LOW_CONFIDENCE
        elif st == STATUS_OK and ocr_status == STATUS_OCR_NOT_NEEDED:
            ocr_status = STATUS_OK

    # Dedupe across layers
    merged_spans = _dedupe_spans(all_spans, similarity_threshold=dedup_similarity)
    merged_text = _assign_char_offsets(merged_spans)

    ocr_text_parts = [
        s.text
        for s in merged_spans
        if s.origin in (ORIGIN_RENDERED_OCR, ORIGIN_EMBEDDED_IMAGE_OCR)
    ]
    ocr_joined = "\n".join(ocr_text_parts)

    # Disagreement: both native and OCR present but not near-identical
    disagreement = False
    disagreement_score = 0.0
    if native_joined.strip() and ocr_joined.strip():
        sim = text_similarity(native_joined, ocr_joined)
        disagreement_score = round(1.0 - sim, 4)
        if sim < 0.85:
            disagreement = True
            warnings.append("native_ocr_disagreement")

    avg_ocr_conf: Optional[float]
    if ocr_confidences:
        avg_ocr_conf = sum(ocr_confidences) / len(ocr_confidences)
        if avg_ocr_conf < low_confidence_threshold:
            ocr_status = STATUS_LOW_CONFIDENCE
            warnings.append("low_ocr_confidence")
    else:
        avg_ocr_conf = None
        # OCR was requested/provided but produced no confidence
        if rendered_ocr is not None or (embedded_image_ocr):
            if ocr_status == STATUS_OCR_NOT_NEEDED:
                if any(
                    (m.get("status") == STATUS_OCR_UNAVAILABLE)
                    for m in ocr_meta_list
                ):
                    ocr_status = STATUS_OCR_UNAVAILABLE
                elif not ocr_joined:
                    ocr_status = STATUS_OCR_FAILED
        # Critical: missing OCR confidence is never high
        # leave as None

    if ocr_status == STATUS_OCR_UNAVAILABLE:
        warnings.append("ocr_unavailable")

    origins_present = sorted({s.origin for s in merged_spans})
    coverage_ratio = estimate_native_char_coverage(
        merged_text,
        page_width=page_width,
        page_height=page_height,
        min_chars=min_native_chars,
    )

    if not merged_text.strip():
        page_status = STATUS_EMPTY
    elif disagreement:
        page_status = STATUS_DISAGREEMENT
    elif coverage_ratio < coverage_threshold or native_coverage < coverage_threshold:
        if ocr_status == STATUS_OCR_UNAVAILABLE:
            page_status = STATUS_OCR_UNAVAILABLE
        elif ocr_status == STATUS_LOW_CONFIDENCE:
            page_status = STATUS_LOW_CONFIDENCE
        else:
            page_status = STATUS_LOW_COVERAGE
    elif ocr_status == STATUS_LOW_CONFIDENCE:
        page_status = STATUS_LOW_CONFIDENCE
    else:
        page_status = STATUS_OK

    receipt = PageCoverageReceipt(
        page=page,
        native_char_count=len(native_joined),
        ocr_char_count=len(ocr_joined),
        merged_char_count=len(merged_text),
        native_coverage=round(native_coverage, 4),
        coverage_ratio=round(coverage_ratio, 4),
        has_native_text=bool(native_joined.strip()),
        has_ocr_text=bool(ocr_joined.strip()),
        rotation=int(rotation or 0),
        status=page_status,
        ocr_status=ocr_status,
        ocr_confidence=None if avg_ocr_conf is None else round(avg_ocr_conf, 4),
        origins_present=origins_present,
        disagreement=disagreement,
        disagreement_score=disagreement_score,
        render_digest=page_render_digest,
        available_engines=list(dict.fromkeys(available)),
        engines_attempted=list(dict.fromkeys(engines_attempted)),
        warnings=warnings,
        provenance={
            "page": page,
            "rotation": int(rotation or 0),
            "render_digest": page_render_digest,
            "span_count": len(merged_spans),
            "origins": origins_present,
            "native_coverage": round(native_coverage, 4),
            "ocr_status": ocr_status,
            # Explicit: absence of confidence is not success
            "ocr_confidence_present": avg_ocr_conf is not None,
        },
    )

    return PageMergeResult(
        page=page,
        text=merged_text,
        spans=merged_spans,
        coverage=receipt,
        selected_origins=origins_present,
    )


def merge_document_layers(
    page_inputs: Sequence[Mapping[str, Any]],
    *,
    coverage_threshold: float = DEFAULT_NATIVE_COVERAGE_THRESHOLD,
    min_native_chars: int = DEFAULT_MIN_NATIVE_CHARS,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    available_engines: Optional[Sequence[str]] = None,
) -> DocumentMergeResult:
    """
    Merge per-page layer inputs into a document-level result.

    Each page_input mapping may include:
      page, native_blocks, native_text, rendered_ocr, embedded_image_ocr,
      page_width, page_height, rotation, render_digest
    """
    page_results: List[PageMergeResult] = []
    warnings: List[str] = []
    confidences: List[float] = []

    for raw in page_inputs:
        page_no = int(raw.get("page") or raw.get("page_number") or 0)
        result = merge_page_layers(
            page_no,
            native_blocks=raw.get("native_blocks") or raw.get("text_blocks"),
            native_text=raw.get("native_text"),
            rendered_ocr=raw.get("rendered_ocr"),
            embedded_image_ocr=raw.get("embedded_image_ocr") or raw.get("image_ocr"),
            page_width=float(raw.get("page_width") or 0.0),
            page_height=float(raw.get("page_height") or 0.0),
            rotation=int(raw.get("rotation") or 0),
            render_digest=raw.get("render_digest"),
            coverage_threshold=coverage_threshold,
            min_native_chars=min_native_chars,
            low_confidence_threshold=low_confidence_threshold,
            available_engines=available_engines or raw.get("available_engines"),
        )
        page_results.append(result)
        warnings.extend(result.coverage.warnings)
        if result.coverage.ocr_confidence is not None:
            confidences.append(result.coverage.ocr_confidence)

    coverages = [p.coverage for p in page_results]
    if coverages:
        overall_coverage = sum(c.coverage_ratio for c in coverages) / len(coverages)
    else:
        overall_coverage = 0.0

    # Document OCR status: most severe explicit state wins
    severity = {
        STATUS_OCR_UNAVAILABLE: 5,
        STATUS_OCR_FAILED: 4,
        STATUS_LOW_CONFIDENCE: 3,
        STATUS_LOW_COVERAGE: 2,
        STATUS_DISAGREEMENT: 2,
        STATUS_EMPTY: 1,
        STATUS_OK: 0,
        STATUS_OCR_NOT_NEEDED: 0,
    }
    ocr_status = STATUS_OCR_NOT_NEEDED
    best_sev = -1
    for c in coverages:
        sev = severity.get(c.ocr_status, 0)
        if sev > best_sev:
            best_sev = sev
            ocr_status = c.ocr_status

    if confidences:
        overall_ocr_confidence: Optional[float] = round(
            sum(confidences) / len(confidences), 4
        )
    else:
        # Missing OCR confidence is explicit None — never a high default
        overall_ocr_confidence = None
        if any(
            c.ocr_status
            in (STATUS_OCR_UNAVAILABLE, STATUS_OCR_FAILED, STATUS_LOW_CONFIDENCE)
            for c in coverages
        ):
            pass  # keep None
        elif any(c.has_ocr_text for c in coverages):
            # OCR text present without confidence still not high
            overall_ocr_confidence = None
            warnings.append("ocr_confidence_missing")

    full_text = "\n\n".join(p.text for p in page_results if p.text.strip())

    return DocumentMergeResult(
        pages=page_results,
        full_text=full_text,
        page_coverage=coverages,
        overall_coverage=round(overall_coverage, 4),
        overall_ocr_confidence=overall_ocr_confidence,
        ocr_status=ocr_status,
        warnings=list(dict.fromkeys(warnings)),
        provenance={
            "page_count": len(page_results),
            "pages_with_native": sum(1 for c in coverages if c.has_native_text),
            "pages_with_ocr": sum(1 for c in coverages if c.has_ocr_text),
            "ocr_status": ocr_status,
            "ocr_confidence_present": overall_ocr_confidence is not None,
        },
    )


def quality_scores_from_merge(
    merge_result: DocumentMergeResult,
    *,
    entity_confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Derive quality scores that never treat missing OCR as high confidence.
    """
    text_quality = float(merge_result.overall_coverage)
    ocr_conf = merge_result.overall_ocr_confidence  # may be None
    ocr_status = merge_result.ocr_status

    if ocr_conf is None:
        # Explicit non-scores for unavailable / not-run OCR
        if ocr_status in (STATUS_OCR_UNAVAILABLE, STATUS_OCR_FAILED):
            ocr_score = 0.0
        elif ocr_status == STATUS_OCR_NOT_NEEDED:
            ocr_score = None  # not applicable
        else:
            ocr_score = 0.0
    else:
        ocr_score = float(ocr_conf)

    if entity_confidence is None:
        ent_score: Optional[float] = None
    else:
        ent_score = float(entity_confidence)

    # Weighted overall: only average available components
    components: List[Tuple[float, float]] = [(text_quality, 0.5)]
    if ocr_score is not None:
        components.append((ocr_score, 0.3))
    if ent_score is not None:
        components.append((ent_score, 0.2))
    weight_sum = sum(w for _, w in components) or 1.0
    overall = sum(v * w for v, w in components) / weight_sum

    return {
        "text_extraction_quality": round(text_quality, 3),
        "ocr_confidence": None if ocr_score is None else round(ocr_score, 3),
        "ocr_status": ocr_status,
        "entity_extraction_confidence": None
        if ent_score is None
        else round(ent_score, 3),
        "overall_quality": round(overall, 3),
        "page_coverage": [c.to_dict() for c in merge_result.page_coverage],
        "overall_coverage": merge_result.overall_coverage,
    }


__all__ = [
    "ORIGIN_NATIVE",
    "ORIGIN_RENDERED_OCR",
    "ORIGIN_EMBEDDED_IMAGE_OCR",
    "STATUS_OK",
    "STATUS_LOW_COVERAGE",
    "STATUS_LOW_CONFIDENCE",
    "STATUS_OCR_UNAVAILABLE",
    "STATUS_OCR_FAILED",
    "STATUS_OCR_NOT_NEEDED",
    "STATUS_EMPTY",
    "STATUS_DISAGREEMENT",
    "TextSpan",
    "PageCoverageReceipt",
    "PageMergeResult",
    "DocumentMergeResult",
    "estimate_native_char_coverage",
    "should_run_page_ocr",
    "text_similarity",
    "normalize_bbox",
    "merge_page_layers",
    "merge_document_layers",
    "quality_scores_from_merge",
]
