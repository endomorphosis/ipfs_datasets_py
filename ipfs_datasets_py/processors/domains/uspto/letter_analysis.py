"""Extract and analyze USPTO deficiency / office-action letters.

Pipeline
--------
1. Read PDF bytes (or plain text).
2. Extract native text via :class:`PdfOcrBridge`; if pages are image-only,
   run **local** Tesseract OCR (never remote).
3. Feed text to :class:`OfficeActionProcessor` for rejections, objections,
   claim ranges, and response-period instructions.
4. Emit a compact operator summary (structured fields + short surfaces).

Full document body is not written to ordinary logs. Optional full text may be
saved under the revision case directory (mode 0600) when explicitly requested.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    utc_now_iso,
)

LETTER_ANALYSIS_SCHEMA: Final = "patlaw-letter-analysis-v1"

_MONTHS_RE = re.compile(
    r"(?i)\b(?P<n>\d{1,2})\s*(?:calendar\s+)?months?\b"
)
_DAYS_RE = re.compile(r"(?i)\b(?P<n>\d{1,3})\s*days?\b")
_SSP_RE = re.compile(
    r"(?i)shortened\s+statutory\s+period|period\s+for\s+reply|time\s+period\s+for\s+reply"
)


class LetterAnalysisError(PortfolioAutomationError):
    """Fail-closed letter analysis error."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_tesseract_backend() -> Any:
    """Build a local Tesseract OCR backend for PdfOcrBridge, or raise."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise LetterAnalysisError(
            "pytesseract and Pillow required for OCR of image-only USPTO PDFs "
            "(pip install pytesseract Pillow); system tesseract binary also required",
            code="ocr_deps_missing",
        ) from exc

    from ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge import (
        OcrProviderKind,
        RecordingOcrBackend,
    )

    def _ocr(image_bytes: bytes, page_index: int) -> Mapping[str, Any]:
        if not image_bytes:
            return {
                "text": "",
                "confidence": 0.0,
                "status": "empty_image",
                "engine": "tesseract",
                "word_boxes": [],
            }
        img = Image.open(io.BytesIO(image_bytes))
        # Prefer English; USPTO letters are English.
        text = pytesseract.image_to_string(img, lang="eng")
        conf = 0.75
        try:
            data = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.DICT)
            confs = [
                int(c)
                for c in data.get("conf", [])
                if str(c).lstrip("-").isdigit() and int(c) >= 0
            ]
            if confs:
                conf = max(0.0, min(1.0, (sum(confs) / len(confs)) / 100.0))
        except Exception:
            pass
        return {
            "text": text or "",
            "confidence": conf,
            "status": "ok" if (text or "").strip() else "empty_ocr",
            "engine": "tesseract",
            "word_boxes": [],
            "page_index": page_index,
        }

    return RecordingOcrBackend(
        name="tesseract-local",
        kind=OcrProviderKind.LOCAL,
        callable=_ocr,
    )


def extract_text_from_pdf(
    path: Path,
    *,
    force_ocr: bool = False,
    max_pages: int = 40,
    classification: DisclosureClassification | str = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    ),
) -> dict[str, Any]:
    """Extract text from a USPTO letter PDF (native layer, then local OCR)."""
    from ipfs_datasets_py.processors.domains.uspto.pdf_ocr_bridge import (
        PdfOcrBridge,
        PdfOcrBridgeBounds,
        PdfOcrBridgeInput,
    )

    pdf_path = Path(path).expanduser().resolve()
    if not pdf_path.is_file():
        raise LetterAnalysisError(f"PDF not found: {pdf_path}", code="missing_pdf")
    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise LetterAnalysisError("not a PDF file", code="not_pdf")

    digest = sha256_bytes(data)
    bounds = PdfOcrBridgeBounds(max_pages=int(max_pages))

    # First pass: native text only (no OCR backend).
    bridge_native = PdfOcrBridge(bounds=bounds)
    result = bridge_native.process(
        PdfOcrBridgeInput(
            artifact_id=f"art:letter:{digest[:16]}",
            content_bytes=data,
            classification=classification,
            content_sha256=digest,
            filename=pdf_path.name,
            source_cid=f"cid:local:{digest[:24]}",
            force_ocr=False,
            labels={"source_path_name": pdf_path.name},
        )
    )
    text = (result.full_text or "").strip()
    ocr_used = False
    ocr_error = None

    need_ocr = force_ocr or len(text) < 80 or any(
        code in {str(c) for c in result.reason_codes}
        for code in ("image_only_page", "ocr_unavailable", "ocr_needed")
    ) or "image_only" in " ".join(str(c) for c in result.reason_codes)

    # reason codes may be enums
    reason_vals = {getattr(c, "value", str(c)) for c in result.reason_codes}
    if force_ocr or len(text) < 80 or "image_only_page" in reason_vals:
        need_ocr = True

    if need_ocr:
        try:
            backend = make_tesseract_backend()
            bridge_ocr = PdfOcrBridge(bounds=bounds, ocr_backend=backend)
            result = bridge_ocr.process(
                PdfOcrBridgeInput(
                    artifact_id=f"art:letter:{digest[:16]}",
                    content_bytes=data,
                    classification=classification,
                    content_sha256=digest,
                    filename=pdf_path.name,
                    source_cid=f"cid:local:{digest[:24]}",
                    force_ocr=True,
                    labels={"source_path_name": pdf_path.name, "ocr": "tesseract"},
                )
            )
            text = (result.full_text or "").strip()
            ocr_used = True
        except LetterAnalysisError as exc:
            ocr_error = f"{exc.code}:{exc}"
        except Exception as exc:  # noqa: BLE001
            ocr_error = f"{type(exc).__name__}:{exc}"

    return {
        "path": str(pdf_path),
        "content_sha256": digest,
        "page_count": int(getattr(result, "page_count", 0) or 0),
        "disposition": str(
            getattr(getattr(result, "disposition", None), "value", result.disposition)
        ),
        "reason_codes": [
            getattr(c, "value", str(c)) for c in (result.reason_codes or ())
        ],
        "ocr_used": ocr_used,
        "ocr_error": ocr_error,
        "text": text,
        "text_len": len(text),
        "text_digest": sha256_bytes(text.encode("utf-8")) if text else "",
        "extraction_ok": bool(text and len(text) >= 40),
    }


def extract_text_from_path(path: Path, **kwargs: Any) -> dict[str, Any]:
    """Extract text from PDF or UTF-8/Latin-1 text file."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise LetterAnalysisError(f"file not found: {p}", code="missing_file")
    if p.suffix.lower() == ".pdf" or p.read_bytes()[:4] == b"%PDF":
        return extract_text_from_pdf(p, **kwargs)
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    digest = sha256_bytes(raw)
    return {
        "path": str(p),
        "content_sha256": digest,
        "page_count": 1,
        "disposition": "text_file",
        "reason_codes": ["plain_text"],
        "ocr_used": False,
        "ocr_error": None,
        "text": text.strip(),
        "text_len": len(text.strip()),
        "text_digest": sha256_bytes(text.strip().encode("utf-8")),
        "extraction_ok": bool(text.strip()),
    }


def _parse_period_months_from_surfaces(surfaces: list[str]) -> int | None:
    blob = "\n".join(surfaces)
    if not blob:
        return None
    # Prefer explicit month counts near reply language
    for m in _MONTHS_RE.finditer(blob):
        n = int(m.group("n"))
        if 1 <= n <= 6:
            return n
    # Days → approximate months only if SSP context
    if _SSP_RE.search(blob):
        for m in _DAYS_RE.finditer(blob):
            n = int(m.group("n"))
            if n >= 28:
                return max(1, round(n / 30))
    return None


def summarize_office_action(
    text: str,
    *,
    artifact_id: str = "art:letter",
    mailing_date: str | None = None,
    document_kind: str | None = None,
    application_number: str | None = None,
) -> dict[str, Any]:
    """Run OfficeActionProcessor and return a compact operator summary."""
    from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
        CandidateKind,
        OfficeActionInput,
        OfficeActionProcessor,
    )

    if not (text or "").strip():
        return {
            "ok": False,
            "error": "empty_text",
            "action_kind": "unknown",
            "rejections": [],
            "objections": [],
            "claim_ranges": [],
            "response_instructions": [],
            "citations": [],
            "sections": [],
            "period_months_from_text": None,
            "requirements": [],
        }

    labels: dict[str, str] = {}
    if application_number:
        labels["application_number"] = str(application_number)
    processor = OfficeActionProcessor()
    result = processor.analyze(
        OfficeActionInput(
            artifact_id=artifact_id[:200] or "art:letter",
            text=text,
            mailing_date=mailing_date,
            document_kind=document_kind,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            labels=labels,
        )
    )

    rejections: list[str] = []
    objections: list[str] = []
    claim_ranges: list[str] = []
    response_instructions: list[str] = []
    citations: list[str] = []
    sections: list[str] = []

    for cand in result.candidates:
        kind = cand.kind
        kind_v = kind.value if hasattr(kind, "value") else str(kind)
        surface = (getattr(cand, "surface_text", None) or "").strip()
        if not surface:
            continue
        # Cap surface length for summary (operator-local; still not full body dump)
        surface_short = surface if len(surface) <= 400 else surface[:397] + "…"
        if kind_v == CandidateKind.REJECTION.value or kind_v == "rejection":
            rejections.append(surface_short)
        elif kind_v == CandidateKind.OBJECTION.value or kind_v == "objection":
            objections.append(surface_short)
        elif kind_v == CandidateKind.CLAIM_RANGE.value or kind_v == "claim_range":
            claim_ranges.append(surface_short)
        elif (
            kind_v == CandidateKind.RESPONSE_INSTRUCTION.value
            or kind_v == "response_instruction"
        ):
            response_instructions.append(surface_short)
        elif kind_v in {
            CandidateKind.CITATION.value,
            CandidateKind.PRIOR_ART.value,
            "citation",
            "prior_art",
        }:
            citations.append(surface_short)
        elif kind_v == CandidateKind.SECTION.value or kind_v == "section":
            sections.append(surface_short)

    reqs: list[dict[str, Any]] = []
    for req in result.requirements:
        reqs.append(
            {
                "requirement_type": getattr(req, "requirement_type", None)
                or getattr(req, "kind", None),
                "requirement_id": getattr(req, "requirement_id", None),
                "review_state": str(
                    getattr(getattr(req, "review_state", None), "value", "")
                ),
            }
        )

    period = _parse_period_months_from_surfaces(
        response_instructions + rejections[:3] + sections
    )
    # Also scan whole text for "3 months" near reply language
    if period is None:
        period = _parse_period_months_from_surfaces([text[:8000]])

    action_kind = (
        result.action_kind.value
        if hasattr(result.action_kind, "value")
        else str(result.action_kind)
    )
    disposition = (
        result.disposition.value
        if hasattr(result.disposition, "value")
        else str(result.disposition)
    )

    return {
        "ok": True,
        "action_kind": action_kind,
        "disposition": disposition,
        "reason_codes": [
            getattr(c, "value", str(c)) for c in (result.reason_codes or ())
        ],
        "mailing_date": result.mailing_date,
        "sections": sections[:40],
        "claim_ranges": claim_ranges[:40],
        "rejections": rejections[:40],
        "objections": objections[:40],
        "response_instructions": response_instructions[:20],
        "citations": citations[:40],
        "requirements": reqs[:40],
        "period_months_from_text": period,
        "text_digest": result.text_digest,
        "analysis_id": result.analysis_id,
        "candidate_count": len(result.candidates),
    }


def analyze_letter_file(
    path: Path,
    *,
    mailing_date: str | None = None,
    document_kind: str | None = None,
    application_number: str | None = None,
    force_ocr: bool = False,
    max_pages: int = 40,
    save_text_path: Path | None = None,
) -> dict[str, Any]:
    """Full pipeline: extract text from file → office-action summary."""
    extraction = extract_text_from_path(
        path, force_ocr=force_ocr, max_pages=max_pages
    )
    summary = summarize_office_action(
        extraction.get("text") or "",
        artifact_id=f"art:letter:{extraction.get('content_sha256', '')[:16]}",
        mailing_date=mailing_date,
        document_kind=document_kind,
        application_number=application_number,
    )
    if save_text_path is not None and extraction.get("text"):
        sp = Path(save_text_path)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(extraction["text"], encoding="utf-8")
        try:
            sp.chmod(0o600)
        except OSError:
            pass

    # Do not embed full text in the returned summary by default.
    out = {
        "schema": LETTER_ANALYSIS_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "source_path": extraction.get("path"),
        "content_sha256": extraction.get("content_sha256"),
        "extraction": {
            k: v
            for k, v in extraction.items()
            if k != "text"  # strip body from default payload
        },
        "analysis": summary,
        "suggested_response_roles": _suggest_roles(summary),
        "disclaimer": (
            "Letter analysis is decision support only — not legal advice. "
            "Verify claim rejections and reply periods on the face of the "
            "USPTO paper. OCR may introduce errors."
        ),
    }
    if save_text_path is not None:
        out["saved_text_path"] = str(save_text_path)
    return out


def _suggest_roles(summary: Mapping[str, Any]) -> list[str]:
    roles = ["remarks", "amendment_transmittal"]
    if summary.get("rejections") or summary.get("claim_ranges"):
        roles.insert(0, "amended_claims")
    if any("draw" in str(s).lower() for s in summary.get("objections") or []):
        roles.append("amended_drawings")
    if any("spec" in str(s).lower() for s in summary.get("objections") or []):
        roles.append("amended_specification")
    if summary.get("action_kind") in {
        "notice_of_allowance",
        "notice",
    }:
        roles = ["fee_transmittal", "other"]
    return roles


@dataclass
class LetterAnalysisBundle:
    """Optional container for tests."""

    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.summary)


def write_letter_analysis(summary: Mapping[str, Any], dest: Path) -> Path:
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


__all__ = [
    "LETTER_ANALYSIS_SCHEMA",
    "LetterAnalysisError",
    "LetterAnalysisBundle",
    "analyze_letter_file",
    "extract_text_from_path",
    "extract_text_from_pdf",
    "make_tesseract_backend",
    "sha256_bytes",
    "summarize_office_action",
    "write_letter_analysis",
]
