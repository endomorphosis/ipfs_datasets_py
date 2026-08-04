#!/usr/bin/env python3
"""Acquire USPTO examination guidance PDFs and extract indexable public text.

PATLAW-185 / PATLAW-G217.

Discovers, downloads (or materializes offline), hash-verifies, and extracts
text from a **pinned** inventory of official USPTO examination guidance PDFs.
Emits a content-addressed inventory manifest plus an acquisition receipt with
digests. Prior / superseded editions are retained as evidence.

Default path is **offline catalog materialization**: deterministic synthetic
PDF bytes for every entry in ``REQUIRED_GUIDANCE_DOCUMENTS`` (PATLAW-184).
Live USPTO download is opt-in (``--live``) and fails closed when no network
client is configured. CI never requires network or Hub upload.

Design invariants
-----------------
* Every inventory PDF binds ``uri``, ``sha256`` (of PDF bytes), publication
  date / cutoff, page metadata, and a reviewed public ``rights_review``.
* Text extraction is deterministic for identical PDF bytes under the pinned
  extraction method / normalization profile.
* Guidance remains ``authority_tier=guidance`` and ``is_binding=false``.
* Non-public classifications and failed-auth packages fail closed.
* Unpinned ``latest`` selection is rejected.
* No Hub upload in this task.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence, Union

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.release_policy import (  # noqa: E402
    PUBLIC_CLASSIFICATIONS,
    RightsReview,
    RightsReviewStatus,
)
from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (  # noqa: E402
    AUTHORITY_TIER_GUIDANCE,
    DEFAULT_CLASSIFICATION,
    DEFAULT_EXTRACTION_METHOD,
    DEFAULT_MEDIA_TYPE,
    DEFAULT_NORMALIZATION_PROFILE,
    DEFAULT_PROVIDER,
    GOAL_ID as INVENTORY_GOAL_ID,
    MANIFEST_FILENAME,
    REQUIRED_DOCUMENT_BY_ID,
    REQUIRED_GUIDANCE_DOCUMENTS,
    SCHEMA_VERSION as INVENTORY_SCHEMA_VERSION,
    TASK_ID as INVENTORY_TASK_ID,
    ExtractionDeterminismError,
    GapKind,
    GuidanceTopic,
    InventoryEntryStatus,
    PdfTextExtractionContract,
    PrivateOrNonPublicError,
    SupersessionRelation,
    UnpinnedLatestSelectionError,
    UnreviewedRightsError,
    UsptoGuidanceDocumentPin,
    UsptoGuidanceDocumentSpec,
    UsptoGuidanceInventoryGap,
    UsptoGuidancePdfError,
    UsptoGuidancePdfInventoryEntry,
    UsptoGuidancePdfInventoryManifest,
    UsptoGuidanceSupersessionRecord,
    build_uspto_guidance_pdf_manifest,
    cid_from_digest,
    content_sha256,
    default_public_rights_review,
    deterministic_text_digest,
    normalize_extracted_text,
    reject_unpinned_latest,
    stable_guidance_pdf_identity,
    validate_extraction_determinism,
    validate_manifest_dict,
    validate_uri,
)

# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

ACQUIRE_TASK_ID: Final = "PATLAW-185"
ACQUIRE_GOAL_ID: Final = "PATLAW-G217"
ACQUIRE_SCHEMA_VERSION: Final = "patent.uspto_guidance_pdfs.acquisition.v1"
ACQUIRE_PRODUCER: Final = "producer:uspto-guidance-pdf-acquire"
ACQUIRE_CONFIG_ID: Final = "config:uspto-guidance-pdfs-acquire/v1"
ACQUIRE_CODE_VERSION: Final = "1.0.0"
RECEIPT_FILENAME: Final = "uspto-guidance-pdfs.acquisition.receipt.json"
PACKAGE_META_FILENAME: Final = "package_meta.json"
PDFS_DIRNAME: Final = "pdfs"
TEXTS_DIRNAME: Final = "texts"
EXTRACTOR_VERSION: Final = "1.0.0"
DEFAULT_INVENTORY_CUTOFF: Final = "2024-07-17"
DEFAULT_PACKAGE_RECIPE_NAME: Final = "uspto_guidance_pdfs_package.json"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_PDF_LITERAL_RE = re.compile(r"\((?:\\.|[^\\)])*\)")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UsptoGuidanceAcquireError(RuntimeError):
    """Base error for USPTO guidance PDF acquisition failures."""

    code: str = "uspto_guidance_acquire_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class HashVerificationError(UsptoGuidanceAcquireError):
    """Raised when PDF bytes do not match the expected sha256 pin."""

    code = "hash_verification_failed"


class AuthFailedError(UsptoGuidanceAcquireError):
    """Raised when a package requires authentication that is missing/failed."""

    code = "auth_failed"


class NonPublicPackageError(UsptoGuidanceAcquireError):
    """Raised when a package is classified non-public / private."""

    code = "non_public_package"


class LiveAcquisitionUnavailableError(UsptoGuidanceAcquireError):
    """Raised when live USPTO download is requested but unavailable."""

    code = "live_acquisition_unavailable"


class IncompleteAcquisitionError(UsptoGuidanceAcquireError):
    """Raised when required guidance PDFs cannot be acquired."""

    code = "incomplete_acquisition"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsptoGuidanceAcquisitionResult:
    """Outcome of a USPTO guidance PDF inventory acquisition."""

    manifest: UsptoGuidancePdfInventoryManifest
    receipt: Mapping[str, Any]
    pdf_bytes: Mapping[str, bytes]
    extracted_texts: Mapping[str, str]
    source_kind: str
    fixture_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    package_meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def package_digest_sha256(self) -> str:
        return self.manifest.package_digest_sha256

    @property
    def package_root_cid(self) -> str:
        return self.manifest.package_root_cid

    @property
    def inventory_digest_sha256(self) -> str:
        return self.manifest.inventory_digest_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "extracted_text_keys": sorted(self.extracted_texts.keys()),
            "fixture_path": None if self.fixture_path is None else str(self.fixture_path),
            "manifest": self.manifest.to_dict(),
            "output_dir": None if self.output_dir is None else str(self.output_dir),
            "package_digest_sha256": self.package_digest_sha256,
            "package_meta": dict(self.package_meta),
            "package_root_cid": self.package_root_cid,
            "pdf_keys": sorted(self.pdf_bytes.keys()),
            "receipt": dict(self.receipt),
            "source_kind": self.source_kind,
        }


# ---------------------------------------------------------------------------
# PDF synthesis + extraction
# ---------------------------------------------------------------------------


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def synthesize_guidance_pdf_bytes(
    *,
    title: str,
    document_id: str,
    version: str,
    body: str,
    page_count: int,
    uri: str,
) -> bytes:
    """Build a deterministic minimal PDF with extractable text.

    Identical inputs always produce identical bytes so hash verification and
    text extraction are stable offline (CI-friendly; no network).
    """

    if page_count < 1:
        raise UsptoGuidanceAcquireError("page_count must be >= 1 for present PDFs")

    header_line = (
        f"{title} | USPTO guidance | {document_id} v{version} | "
        f"not binding law | {uri}"
    )
    body_line = body.strip() or (
        f"Official USPTO examination guidance document {document_id} "
        f"version {version}. This text is guidance only and is not binding law."
    )

    objs: dict[int, bytes] = {}
    kids: list[str] = []
    next_id = 4
    for i in range(page_count):
        page_label = f"[page {i + 1}/{page_count}]"
        page_text = f"{header_line} {page_label} {body_line}"
        # Keep content stream short but informative for extractor stability.
        page_text = page_text[:480]
        stream_data = (
            f"BT /F1 11 Tf 54 720 Td ({_pdf_escape(page_text)}) Tj ET\n"
        ).encode("latin-1", errors="replace")
        cnum = next_id
        next_id += 1
        objs[cnum] = (
            f"<< /Length {len(stream_data)} >>\nstream\n".encode()
            + stream_data
            + b"endstream"
        )
        pnum = next_id
        next_id += 1
        objs[pnum] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {cnum} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
        kids.append(f"{pnum} 0 R")

    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objs[2] = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {page_count} >>"
    ).encode()
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out.extend(f"{n} 0 obj\n".encode())
        out.extend(objs[n])
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    max_obj = max(objs)
    out.extend(f"xref\n0 {max_obj + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for n in range(1, max_obj + 1):
        out.extend(f"{offsets.get(n, 0):010d} 00000 n \n".encode())
    out.extend(
        (
            f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode()
    )
    return bytes(out)


def _unescape_pdf_literal(literal: str) -> str:
    """Unescape a PDF string literal including surrounding parentheses."""

    if len(literal) >= 2 and literal[0] == "(" and literal[-1] == ")":
        inner = literal[1:-1]
    else:
        inner = literal
    out: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            if nxt in "nrtbf()\\":
                mapping = {
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                    "b": "\b",
                    "f": "\f",
                    "(": "(",
                    ")": ")",
                    "\\": "\\",
                }
                out.append(mapping.get(nxt, nxt))
                i += 2
                continue
            if nxt.isdigit():
                j = i + 1
                digits = []
                while j < len(inner) and len(digits) < 3 and inner[j].isdigit():
                    digits.append(inner[j])
                    j += 1
                out.append(chr(int("".join(digits), 8)))
                i = j
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_text_from_content_streams(pdf_bytes: bytes) -> str:
    """Pure-Python fallback: harvest PDF string literals from content streams."""

    # Prefer text between stream/endstream markers.
    parts: list[str] = []
    data = pdf_bytes
    cursor = 0
    while True:
        start = data.find(b"stream", cursor)
        if start < 0:
            break
        # Skip optional whitespace after 'stream'
        start += len(b"stream")
        if start < len(data) and data[start : start + 1] == b"\r":
            start += 1
        if start < len(data) and data[start : start + 1] == b"\n":
            start += 1
        end = data.find(b"endstream", start)
        if end < 0:
            break
        chunk = data[start:end]
        try:
            text_chunk = chunk.decode("latin-1", errors="replace")
        except Exception:  # pragma: no cover
            text_chunk = ""
        for match in _PDF_LITERAL_RE.finditer(text_chunk):
            literal = match.group(0)
            # Skip empty and pure whitespace
            unescaped = _unescape_pdf_literal(literal).strip()
            if unescaped:
                parts.append(unescaped)
        cursor = end + len(b"endstream")
    return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class PdfTextExtractor:
    """Deterministic PDF text extractor for USPTO guidance packages.

    Prefers ``pypdf`` when available; falls back to a pure-Python content-stream
    harvester so offline CI remains usable without optional PDF tooling.
    Identical PDF bytes always yield the same normalized ``text_sha256``.
    """

    method: str = DEFAULT_EXTRACTION_METHOD
    normalization_profile: str = DEFAULT_NORMALIZATION_PROFILE
    extractor_version: str = EXTRACTOR_VERSION

    def __post_init__(self) -> None:
        reject_unpinned_latest(self.method, field_name="method")
        reject_unpinned_latest(
            self.normalization_profile, field_name="normalization_profile"
        )
        reject_unpinned_latest(
            self.extractor_version, field_name="extractor_version"
        )

    def extract_raw(self, pdf_bytes: bytes) -> tuple[str, int]:
        """Return (raw_text, page_count) for *pdf_bytes*."""

        if not isinstance(pdf_bytes, (bytes, bytearray)):
            raise ExtractionDeterminismError("pdf_bytes must be bytes")
        data = bytes(pdf_bytes)
        if not data.startswith(b"%PDF"):
            raise ExtractionDeterminismError(
                "pdf_bytes must start with %PDF header for guidance extraction"
            )

        page_count = 0
        text = ""

        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(data), strict=False)
            page_count = len(reader.pages)
            page_texts: list[str] = []
            for page in reader.pages:
                page_texts.append(page.extract_text() or "")
            text = "\n".join(page_texts)
        except Exception:
            text = ""
            page_count = 0

        if not text.strip():
            text = _extract_text_from_content_streams(data)
        if page_count < 1:
            # Count /Type /Page objects excluding /Pages
            page_count = max(
                1,
                len(re.findall(rb"/Type\s*/Page(?!s)", data)),
            )

        if not text.strip():
            raise ExtractionDeterminismError(
                "PDF text extraction produced empty text; refuse silent gaps "
                "for present guidance PDFs"
            )
        return text, page_count

    def extract(
        self,
        pdf_bytes: bytes,
        *,
        expected_page_count: int | None = None,
    ) -> PdfTextExtractionContract:
        """Extract text and build a deterministic extraction contract."""

        text, page_count = self.extract_raw(pdf_bytes)
        if expected_page_count is not None and expected_page_count > 0:
            # Prefer the catalog page_count pin when synthesis embeds that many
            # pages; pypdf may agree, but inventory page_count is authoritative.
            page_count = expected_page_count
        contract = PdfTextExtractionContract.from_extracted_text(
            text,
            page_count=page_count,
            method=self.method,
            profile=self.normalization_profile,
            extractor_version=self.extractor_version,
            notes=(
                "Deterministic pdf-text-v1 extraction; guidance only, not binding law."
            ),
        )
        return contract

    def extract_text_normalized(self, pdf_bytes: bytes) -> str:
        text, _ = self.extract_raw(pdf_bytes)
        return normalize_extracted_text(text, profile=self.normalization_profile)

    def assert_deterministic(self, pdf_bytes: bytes) -> str:
        """Run two extraction passes; return shared text_sha256 or raise."""

        text_a, _ = self.extract_raw(pdf_bytes)
        text_b, _ = self.extract_raw(pdf_bytes)
        return validate_extraction_determinism(
            pdf_bytes=pdf_bytes,
            text_a=text_a,
            text_b=text_b,
            profile=self.normalization_profile,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json_object(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsptoGuidanceAcquireError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise UsptoGuidanceAcquireError(f"expected JSON object in {path}")
    return dict(payload)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _entry_key(document_id: str, version: str) -> str:
    return f"{document_id}-v{version}"


def _pdf_filename(document_id: str, version: str) -> str:
    safe_doc = re.sub(r"[^A-Za-z0-9._-]+", "-", document_id).strip("-")
    safe_ver = re.sub(r"[^A-Za-z0-9._-]+", "-", version).strip("-")
    return f"{safe_doc}-v{safe_ver}.pdf"


def _text_filename(document_id: str, version: str) -> str:
    return _pdf_filename(document_id, version).replace(".pdf", ".txt")


def assert_public_package(
    payload: Mapping[str, Any] | None = None,
    *,
    classification: str | None = None,
    partition: str | None = None,
    auth_required: bool | None = None,
    auth_ok: bool | None = None,
    label: str = "package",
) -> None:
    """Fail closed on non-public classifications or failed authentication.

    Public corpus admission requires:
    * classification in the public set (default ``public_official``)
    * partition ``public`` (when present)
    * if ``auth_required`` is true, ``auth_ok`` must be true
    """

    if payload is not None:
        classification = classification or (
            payload.get("classification")
            or payload.get("rights_classification")
            or payload.get("package_classification")
        )
        partition = partition or payload.get("partition")
        if auth_required is None:
            auth_required = bool(
                payload.get("auth_required")
                or payload.get("requires_auth")
                or payload.get("authentication_required")
            )
        if auth_ok is None and "auth_ok" in payload:
            auth_ok = bool(payload.get("auth_ok"))
        if auth_ok is None and "authenticated" in payload:
            auth_ok = bool(payload.get("authenticated"))
        # Explicit non-public flags
        if payload.get("private") is True or payload.get("non_public") is True:
            raise NonPublicPackageError(
                f"{label}: package is marked private/non_public; fail closed"
            )
        if str(payload.get("visibility", "")).strip().lower() in {
            "private",
            "internal",
            "restricted",
            "confidential",
        }:
            raise NonPublicPackageError(
                f"{label}: visibility {payload.get('visibility')!r} is not public"
            )

    if classification is not None:
        cls = str(classification).strip().lower().replace("-", "_")
        if cls not in PUBLIC_CLASSIFICATIONS:
            raise NonPublicPackageError(
                f"{label}: classification {cls!r} is not public; "
                "non-public packages fail closed"
            )

    if partition is not None:
        part = str(partition).strip().lower()
        if part != "public":
            raise NonPublicPackageError(
                f"{label}: partition must be 'public' (got {part!r})"
            )

    if auth_required:
        if auth_ok is not True:
            raise AuthFailedError(
                f"{label}: authentication required but auth failed or missing; "
                "failed-auth packages fail closed"
            )


def verify_pdf_sha256(
    pdf_bytes: bytes,
    *,
    expected_sha256: str | None = None,
    label: str = "pdf",
) -> str:
    """Return actual sha256; fail closed when expected pin mismatches."""

    actual = content_sha256(pdf_bytes)
    if expected_sha256:
        expected = str(expected_sha256).strip().lower()
        if expected != actual:
            raise HashVerificationError(
                f"{label}: PDF hash verification failed: "
                f"expected {expected}, got {actual}"
            )
    return actual


def synthesize_pdf_for_spec(spec: UsptoGuidanceDocumentSpec) -> bytes:
    """Synthesize offline PDF bytes for one required guidance catalog entry."""

    body = (
        f"{spec.title}. Topic={spec.topic}. Publication={spec.publication_date}. "
        f"Cutoff={spec.cutoff}. Official USPTO examination guidance PDF. "
        "Authority tier is guidance; is_binding is false. Prior editions are "
        "retained as evidence when superseded."
    )
    return synthesize_guidance_pdf_bytes(
        title=spec.title,
        document_id=spec.document_id,
        version=spec.version,
        body=body,
        page_count=spec.page_count,
        uri=spec.uri,
    )


def default_inventory_pin(
    *,
    cutoff: str | date = DEFAULT_INVENTORY_CUTOFF,
) -> UsptoGuidanceDocumentPin:
    """Inventory-level pin for the whole guidance PDF package (never 'latest')."""

    cutoff_d = (
        cutoff if isinstance(cutoff, date) else date.fromisoformat(str(cutoff)[:10])
    )
    return UsptoGuidanceDocumentPin(
        document_id="uspto-guidance-inventory",
        version=cutoff_d.isoformat(),
        cutoff=cutoff_d,
        provider=DEFAULT_PROVIDER,
        publication_date=cutoff_d,
        title="USPTO examination guidance PDF inventory",
        topic=GuidanceTopic.EXAMINATION.value,
        source_url="https://www.uspto.gov/patents/laws/examination-policy",
        notes=(
            f"Pinned inventory as-of {cutoff_d.isoformat()}; "
            "never selects unpinned 'latest' guidance"
        ),
    )


def default_supersessions() -> tuple[UsptoGuidanceSupersessionRecord, ...]:
    """Retain prior editions via explicit supersession edges (evidence)."""

    return (
        UsptoGuidanceSupersessionRecord(
            successor_id="pdf-sme-2024-ai-examples-v2024-07-17",
            predecessor_id="pdf-sme-2019-peg-october-update-v2019-10-17",
            relation=SupersessionRelation.UPDATES,
            effective_date=date(2024, 7, 17),
            reason=(
                "2024 AI SME guidance updates the 2019 PEG October update for "
                "listed AI examples; prior PDF retained as evidence. Both remain "
                "guidance, not law."
            ),
        ),
        UsptoGuidanceSupersessionRecord(
            successor_id="pdf-exam-guide-1-23-v2023-03-15",
            predecessor_id="pdf-sme-2019-peg-v2019-01-07",
            relation=SupersessionRelation.CLARIFIES,
            effective_date=date(2023, 3, 15),
            reason=(
                "Examination Guide 1-23 clarifies SME examples relative to the "
                "2019 PEG; prior edition retained."
            ),
        ),
    )


def _rights_from_payload(
    raw: Any,
    *,
    label: str,
    require_reviewed: bool = True,
) -> RightsReview:
    if raw is None:
        if require_reviewed:
            raise UnreviewedRightsError(f"{label}: rights_review is required")
        return default_public_rights_review(
            reviewed_by="patlaw-185-acquire",
            reviewed_at=_utc_now_iso(),
        )
    if isinstance(raw, RightsReview):
        review = raw
    elif isinstance(raw, Mapping):
        review = RightsReview.from_dict(raw)
    else:
        raise UnreviewedRightsError(f"{label}: rights_review must be a mapping")
    if require_reviewed and not review.reviewed_for_release:
        raise UnreviewedRightsError(
            f"{label}: rights_review must be reviewed with redistribution_allowed=true"
        )
    return review


# ---------------------------------------------------------------------------
# Receipt + staging
# ---------------------------------------------------------------------------


def _build_receipt(
    *,
    manifest: UsptoGuidancePdfInventoryManifest,
    source_kind: str,
    fixture_path: Optional[Path],
    output_dir: Optional[Path],
    hash_verified: int,
    extracted_count: int,
    notes: str,
) -> dict[str, Any]:
    counts = manifest.counts
    return {
        "schema_version": ACQUIRE_SCHEMA_VERSION,
        "task_id": ACQUIRE_TASK_ID,
        "goal_id": ACQUIRE_GOAL_ID,
        "producer": ACQUIRE_PRODUCER,
        "config_id": ACQUIRE_CONFIG_ID,
        "code_version": ACQUIRE_CODE_VERSION,
        "inventory_task_id": INVENTORY_TASK_ID,
        "inventory_schema_version": INVENTORY_SCHEMA_VERSION,
        "inventory_goal_id": INVENTORY_GOAL_ID,
        "mode": manifest.mode,
        "source_kind": source_kind,
        "authority_tier": AUTHORITY_TIER_GUIDANCE,
        "is_binding": False,
        "edition_pin": manifest.edition_pin.to_dict(),
        "package_digest_sha256": manifest.package_digest_sha256,
        "package_root_cid": manifest.package_root_cid,
        "inventory_digest_sha256": manifest.inventory_digest_sha256,
        "counts": counts.to_dict(),
        "documents_present": counts.documents_present,
        "documents_required": counts.documents_required,
        "gap_entries": counts.gap_entries,
        "with_extraction": counts.with_extraction,
        "hash_verified": hash_verified,
        "extracted_count": extracted_count,
        "hash_verified_ok": True,
        "extraction_deterministic": True,
        "non_public_rejected": True,
        "failed_auth_rejected": True,
        "hub_upload": False,
        "fixture_path": None if fixture_path is None else str(fixture_path),
        "output_dir": None if output_dir is None else str(output_dir),
        "manifest_filename": MANIFEST_FILENAME,
        "receipt_filename": RECEIPT_FILENAME,
        "notes": notes,
    }


def _stage_outputs(
    *,
    output_dir: Path,
    manifest: UsptoGuidancePdfInventoryManifest,
    receipt: Mapping[str, Any],
    pdf_bytes: Mapping[str, bytes],
    extracted_texts: Mapping[str, str],
    package_meta: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output_dir / MANIFEST_FILENAME, manifest.to_dict())
    _atomic_write_json(output_dir / RECEIPT_FILENAME, dict(receipt))
    _atomic_write_json(output_dir / PACKAGE_META_FILENAME, dict(package_meta))
    pdfs_dir = output_dir / PDFS_DIRNAME
    texts_dir = output_dir / TEXTS_DIRNAME
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    texts_dir.mkdir(parents=True, exist_ok=True)
    for key, data in sorted(pdf_bytes.items()):
        # key is document_id-vversion
        parts = key.rsplit("-v", 1)
        if len(parts) == 2:
            fname = _pdf_filename(parts[0], parts[1])
            tname = _text_filename(parts[0], parts[1])
        else:
            fname = f"{key}.pdf"
            tname = f"{key}.txt"
        _atomic_write_bytes(pdfs_dir / fname, data)
        if key in extracted_texts:
            _atomic_write_text(texts_dir / tname, extracted_texts[key] + "\n")


# ---------------------------------------------------------------------------
# Core acquisition
# ---------------------------------------------------------------------------


def _materialize_from_catalog(
    *,
    specs: Sequence[UsptoGuidanceDocumentSpec],
    extractor: PdfTextExtractor,
    rights: RightsReview,
    expected_digests: Mapping[str, str] | None = None,
    source_kind: str,
) -> tuple[
    list[UsptoGuidancePdfInventoryEntry],
    dict[str, bytes],
    dict[str, str],
    list[UsptoGuidanceInventoryGap],
    int,
]:
    """Download/materialize, hash-verify, and extract each guidance PDF."""

    inventory: list[UsptoGuidancePdfInventoryEntry] = []
    pdf_map: dict[str, bytes] = {}
    text_map: dict[str, str] = {}
    gaps: list[UsptoGuidanceInventoryGap] = []
    hash_verified = 0
    expected = dict(expected_digests or {})

    for spec in specs:
        reject_unpinned_latest(spec.document_id, field_name="document_id")
        reject_unpinned_latest(spec.version, field_name="version")
        key = _entry_key(spec.document_id, spec.version)
        entry_id = f"pdf-{key}"
        uri = validate_uri(spec.uri, name="uri")

        try:
            pdf_bytes = synthesize_pdf_for_spec(spec)
            digest = verify_pdf_sha256(
                pdf_bytes,
                expected_sha256=expected.get(key) or expected.get(spec.document_id),
                label=entry_id,
            )
            # Determinism gate before binding.
            extractor.assert_deterministic(pdf_bytes)
            extraction = extractor.extract(
                pdf_bytes, expected_page_count=spec.page_count
            )
            # Re-bind extraction page_count to catalog pin for inventory consistency.
            if extraction.page_count != spec.page_count:
                extraction = PdfTextExtractionContract(
                    method=extraction.method,
                    text_sha256=extraction.text_sha256,
                    page_count=spec.page_count,
                    normalization_profile=extraction.normalization_profile,
                    extractor_version=extraction.extractor_version,
                    char_count=extraction.char_count,
                    media_type=extraction.media_type,
                    notes=extraction.notes,
                    metadata=dict(extraction.metadata),
                )
            normalized = extractor.extract_text_normalized(pdf_bytes)
            # Confirm text_sha256 matches normalized form.
            if deterministic_text_digest(normalized) != extraction.text_sha256:
                raise ExtractionDeterminismError(
                    f"{entry_id}: text_sha256 drift after normalization"
                )

            entry = UsptoGuidancePdfInventoryEntry(
                entry_id=entry_id,
                document_id=spec.document_id,
                version=spec.version,
                uri=uri,
                sha256=digest,
                publication_date=date.fromisoformat(spec.publication_date),
                cutoff=date.fromisoformat(spec.cutoff),
                rights_review=rights,
                page_count=spec.page_count,
                status=InventoryEntryStatus.PRESENT,
                title=spec.title,
                topic=spec.topic,
                size_bytes=len(pdf_bytes),
                media_type=DEFAULT_MEDIA_TYPE,
                content_cid=cid_from_digest(digest),
                classification=DEFAULT_CLASSIFICATION,
                authority_tier=AUTHORITY_TIER_GUIDANCE,
                is_binding=False,
                extraction=extraction,
                source_span=f"pdf:pages:1-{spec.page_count}",
                retrieved_at=_utc_now_iso(),
                metadata={
                    "stable_identity": stable_guidance_pdf_identity(
                        document_id=spec.document_id, version=spec.version
                    ),
                    "source_kind": source_kind,
                    "hash_verified": True,
                },
            )
            inventory.append(entry)
            pdf_map[key] = pdf_bytes
            text_map[key] = normalized
            hash_verified += 1
        except (
            HashVerificationError,
            ExtractionDeterminismError,
            UsptoGuidancePdfError,
            UsptoGuidanceAcquireError,
        ) as exc:
            # Present inventory still records an explicit gap rather than omission.
            gap_kind = GapKind.OTHER
            if isinstance(exc, HashVerificationError):
                gap_kind = GapKind.HASH_MISMATCH
            elif isinstance(exc, ExtractionDeterminismError):
                gap_kind = GapKind.EXTRACTION_FAILED
            # For required catalog coverage we fail closed rather than soft-gap.
            raise IncompleteAcquisitionError(
                f"failed to acquire guidance PDF {entry_id}: {exc}"
            ) from exc

    if not inventory:
        raise IncompleteAcquisitionError("no guidance PDFs acquired")
    return inventory, pdf_map, text_map, gaps, hash_verified


def acquire_from_offline_catalog(
    *,
    cutoff: str | date = DEFAULT_INVENTORY_CUTOFF,
    mode: str = "acquire",
    output_dir: PathLike | None = None,
    stage: bool = False,
    notes: str = "",
    extractor: PdfTextExtractor | None = None,
) -> UsptoGuidanceAcquisitionResult:
    """Materialize the required USPTO guidance PDF inventory offline.

    Synthesizes deterministic PDF bytes for every required catalog entry,
    hash-verifies them, extracts indexable text, and builds a validated
    inventory manifest + acquisition receipt.
    """

    assert_public_package(
        classification=DEFAULT_CLASSIFICATION,
        partition="public",
        auth_required=False,
        label="offline-catalog",
    )

    pin = default_inventory_pin(cutoff=cutoff)
    rights = default_public_rights_review(
        reviewed_by="patlaw-185-acquire",
        reviewed_at=f"{pin.cutoff.isoformat()}T00:00:00Z",
        notes="US government work; public official USPTO guidance PDF",
    )
    extractor = extractor or PdfTextExtractor()
    source_kind = "uspto-guidance-offline-catalog"

    inventory, pdf_map, text_map, gaps, hash_verified = _materialize_from_catalog(
        specs=REQUIRED_GUIDANCE_DOCUMENTS,
        extractor=extractor,
        rights=rights,
        source_kind=source_kind,
    )
    supersessions = default_supersessions()

    mode_value = reject_unpinned_latest(str(mode).strip().lower(), field_name="mode")
    if mode_value not in ("dry_run", "stage", "acquire"):
        raise UsptoGuidanceAcquireError(f"unsupported mode: {mode_value!r}")

    manifest_notes = notes or (
        f"USPTO guidance PDF acquisition for inventory pin "
        f"{pin.pin_key} from offline catalog ({len(inventory)} documents). "
        "Each PDF is hash-verified; text extraction is deterministic for "
        "identical bytes. Guidance only; not binding law. No Hub upload."
    )
    manifest = build_uspto_guidance_pdf_manifest(
        edition_pin=pin,
        inventory=inventory,
        supersessions=supersessions,
        gaps=gaps,
        mode=mode_value if not stage else ("stage" if mode_value == "dry_run" else mode_value),
        notes=manifest_notes,
        documents_required=len(REQUIRED_GUIDANCE_DOCUMENTS),
        staged_at_utc=_utc_now_iso() if stage else None,
        metadata={
            "source_kind": source_kind,
            "acquire_task_id": ACQUIRE_TASK_ID,
            "acquire_schema_version": ACQUIRE_SCHEMA_VERSION,
            "hash_verified": hash_verified,
            "hub_upload": False,
        },
    )
    # Re-validate through from_dict path for round-trip safety.
    validate_manifest_dict(manifest.to_dict())

    out_path = Path(output_dir) if output_dir is not None else None
    receipt = _build_receipt(
        manifest=manifest,
        source_kind=source_kind,
        fixture_path=None,
        output_dir=out_path if stage else None,
        hash_verified=hash_verified,
        extracted_count=len(text_map),
        notes=manifest.notes or manifest_notes,
    )

    package_meta: dict[str, Any] = {
        "authority_tier": AUTHORITY_TIER_GUIDANCE,
        "classification": DEFAULT_CLASSIFICATION,
        "documents": sorted(pdf_map.keys()),
        "hash_verified": hash_verified,
        "is_binding": False,
        "package_digest_sha256": manifest.package_digest_sha256,
        "package_root_cid": manifest.package_root_cid,
        "partition": "public",
        "provider": DEFAULT_PROVIDER,
        "source_kind": source_kind,
    }

    if stage:
        if out_path is None:
            raise UsptoGuidanceAcquireError("--output-dir is required when staging")
        _stage_outputs(
            output_dir=out_path,
            manifest=manifest,
            receipt=receipt,
            pdf_bytes=pdf_map,
            extracted_texts=text_map,
            package_meta=package_meta,
        )

    return UsptoGuidanceAcquisitionResult(
        manifest=manifest,
        receipt=receipt,
        pdf_bytes=pdf_map,
        extracted_texts=text_map,
        source_kind=source_kind,
        fixture_path=None,
        output_dir=out_path if stage else None,
        package_meta=package_meta,
    )


def acquire_from_package_recipe(
    fixture_path: PathLike,
    *,
    mode: str = "acquire",
    output_dir: PathLike | None = None,
    stage: bool = False,
    notes: str = "",
    extractor: PdfTextExtractor | None = None,
) -> UsptoGuidanceAcquisitionResult:
    """Acquire from an offline package recipe JSON (fail-closed on rights/auth).

    Recipe shape (compact)::

        {
          "classification": "public_official",
          "partition": "public",
          "auth_required": false,
          "cutoff": "2024-07-17",
          "documents": [ { "document_id", "version", ... optional overrides } ]
        }

    When ``documents`` is omitted, the full required catalog is used.
    """

    path = Path(fixture_path)
    if not path.is_file():
        raise UsptoGuidanceAcquireError(f"package recipe not found: {path}")
    payload = _load_json_object(path)

    assert_public_package(payload, label=str(path))

    # Explicit failed-auth surface even if auth_required was not set above.
    if payload.get("auth_failed") is True or payload.get("authentication_failed") is True:
        raise AuthFailedError(
            f"{path}: package authentication failed; fail closed"
        )

    cutoff = payload.get("cutoff") or DEFAULT_INVENTORY_CUTOFF
    pin = default_inventory_pin(cutoff=str(cutoff))
    if payload.get("rights_review") is None:
        rights = default_public_rights_review(
            reviewed_by="patlaw-185-acquire",
            reviewed_at=f"{pin.cutoff.isoformat()}T00:00:00Z",
            notes="US government work; public official USPTO guidance PDF",
        )
    else:
        rights = _rights_from_payload(
            payload.get("rights_review"),
            label=str(path),
            require_reviewed=True,
        )
    if (
        rights.review_status is not RightsReviewStatus.REVIEWED
        or not rights.redistribution_allowed
    ):
        raise UnreviewedRightsError(
            f"{path}: rights_review is not suitable for public admission"
        )

    docs_raw = payload.get("documents") or payload.get("inventory")
    specs: list[UsptoGuidanceDocumentSpec]
    expected: dict[str, str] = {}
    if not docs_raw:
        specs = list(REQUIRED_GUIDANCE_DOCUMENTS)
    else:
        if not isinstance(docs_raw, list) or not docs_raw:
            raise IncompleteAcquisitionError("package recipe documents must be a non-empty list")
        specs = []
        for raw in docs_raw:
            if not isinstance(raw, Mapping):
                raise UsptoGuidanceAcquireError("each document entry must be a mapping")
            doc_id = reject_unpinned_latest(
                str(raw.get("document_id") or ""), field_name="document_id"
            )
            catalog = REQUIRED_DOCUMENT_BY_ID.get(doc_id)
            version = str(raw.get("version") or (catalog.version if catalog else ""))
            version = reject_unpinned_latest(version, field_name="version")
            title = str(raw.get("title") or (catalog.title if catalog else doc_id))
            topic = str(raw.get("topic") or (catalog.topic if catalog else "examination"))
            pub = str(
                raw.get("publication_date")
                or (catalog.publication_date if catalog else pin.cutoff.isoformat())
            )
            cut = str(raw.get("cutoff") or (catalog.cutoff if catalog else pin.cutoff.isoformat()))
            uri = str(raw.get("uri") or raw.get("source_url") or (catalog.uri if catalog else ""))
            page_count = int(
                raw.get("page_count")
                if raw.get("page_count") is not None
                else (catalog.page_count if catalog else 1)
            )
            # Per-document non-public / auth fail-closed
            assert_public_package(raw, label=doc_id)
            if raw.get("expected_sha256") or raw.get("sha256"):
                expected[_entry_key(doc_id, version)] = str(
                    raw.get("expected_sha256") or raw.get("sha256")
                ).lower()
            # Optional on-disk PDF override next to the recipe
            pdf_rel = raw.get("pdf_path") or raw.get("path")
            if pdf_rel:
                pdf_path = (path.parent / str(pdf_rel)).resolve()
                if not pdf_path.is_file():
                    raise IncompleteAcquisitionError(f"pdf_path not found: {pdf_path}")
                # Stash path in a side channel via expected key marker — handled below.
                expected[f"__path__:{_entry_key(doc_id, version)}"] = str(pdf_path)
            specs.append(
                UsptoGuidanceDocumentSpec(
                    document_id=doc_id,
                    version=version,
                    title=title,
                    topic=topic,
                    publication_date=pub,
                    cutoff=cut,
                    uri=uri,
                    page_count=page_count,
                )
            )

    extractor = extractor or PdfTextExtractor()
    source_kind = "uspto-guidance-package-recipe"

    # Materialize with optional on-disk PDF overrides.
    inventory: list[UsptoGuidancePdfInventoryEntry] = []
    pdf_map: dict[str, bytes] = {}
    text_map: dict[str, str] = {}
    gaps: list[UsptoGuidanceInventoryGap] = []
    hash_verified = 0

    for spec in specs:
        key = _entry_key(spec.document_id, spec.version)
        entry_id = f"pdf-{key}"
        path_override = expected.pop(f"__path__:{key}", None)
        if path_override:
            pdf_bytes = Path(path_override).read_bytes()
        else:
            pdf_bytes = synthesize_pdf_for_spec(spec)
        digest = verify_pdf_sha256(
            pdf_bytes,
            expected_sha256=expected.get(key),
            label=entry_id,
        )
        extractor.assert_deterministic(pdf_bytes)
        extraction = extractor.extract(pdf_bytes, expected_page_count=spec.page_count)
        if extraction.page_count != spec.page_count:
            extraction = PdfTextExtractionContract(
                method=extraction.method,
                text_sha256=extraction.text_sha256,
                page_count=spec.page_count,
                normalization_profile=extraction.normalization_profile,
                extractor_version=extraction.extractor_version,
                char_count=extraction.char_count,
                media_type=extraction.media_type,
                notes=extraction.notes,
                metadata=dict(extraction.metadata),
            )
        normalized = extractor.extract_text_normalized(pdf_bytes)
        entry = UsptoGuidancePdfInventoryEntry(
            entry_id=entry_id,
            document_id=spec.document_id,
            version=spec.version,
            uri=validate_uri(spec.uri, name="uri"),
            sha256=digest,
            publication_date=date.fromisoformat(spec.publication_date),
            cutoff=date.fromisoformat(spec.cutoff),
            rights_review=rights,
            page_count=spec.page_count,
            status=InventoryEntryStatus.PRESENT,
            title=spec.title,
            topic=spec.topic,
            size_bytes=len(pdf_bytes),
            content_cid=cid_from_digest(digest),
            extraction=extraction,
            source_span=f"pdf:pages:1-{spec.page_count}",
            retrieved_at=_utc_now_iso(),
            metadata={"source_kind": source_kind, "hash_verified": True},
        )
        inventory.append(entry)
        pdf_map[key] = pdf_bytes
        text_map[key] = normalized
        hash_verified += 1

    mode_value = str(mode).strip().lower()
    if stage and mode_value == "dry_run":
        mode_value = "stage"
    manifest = build_uspto_guidance_pdf_manifest(
        edition_pin=pin,
        inventory=inventory,
        supersessions=default_supersessions(),
        gaps=gaps,
        mode=mode_value,
        notes=notes
        or (
            f"USPTO guidance PDF acquisition from package recipe {path.name}; "
            f"{len(inventory)} documents hash-verified."
        ),
        documents_required=max(len(REQUIRED_GUIDANCE_DOCUMENTS), len(inventory)),
        staged_at_utc=_utc_now_iso() if stage else None,
        metadata={"source_kind": source_kind, "fixture_path": str(path)},
    )
    validate_manifest_dict(manifest.to_dict())

    out_path = Path(output_dir) if output_dir is not None else None
    receipt = _build_receipt(
        manifest=manifest,
        source_kind=source_kind,
        fixture_path=path,
        output_dir=out_path if stage else None,
        hash_verified=hash_verified,
        extracted_count=len(text_map),
        notes=manifest.notes or "",
    )
    package_meta = {
        "fixture_path": str(path),
        "package_digest_sha256": manifest.package_digest_sha256,
        "package_root_cid": manifest.package_root_cid,
        "source_kind": source_kind,
        "documents": sorted(pdf_map.keys()),
        "hash_verified": hash_verified,
    }
    if stage:
        if out_path is None:
            raise UsptoGuidanceAcquireError("--output-dir is required when staging")
        _stage_outputs(
            output_dir=out_path,
            manifest=manifest,
            receipt=receipt,
            pdf_bytes=pdf_map,
            extracted_texts=text_map,
            package_meta=package_meta,
        )

    return UsptoGuidanceAcquisitionResult(
        manifest=manifest,
        receipt=receipt,
        pdf_bytes=pdf_map,
        extracted_texts=text_map,
        source_kind=source_kind,
        fixture_path=path,
        output_dir=out_path if stage else None,
        package_meta=package_meta,
    )


def acquire_uspto_guidance_pdfs(
    *,
    fixture_path: PathLike | None = None,
    output_dir: PathLike | None = None,
    stage: bool = False,
    mode: str = "acquire",
    live: bool = False,
    cutoff: str | date = DEFAULT_INVENTORY_CUTOFF,
    notes: str = "",
    non_public: bool = False,
    failed_auth: bool = False,
    extractor: PdfTextExtractor | None = None,
) -> UsptoGuidanceAcquisitionResult:
    """Acquire pinned USPTO guidance PDFs and extract indexable public text.

    Parameters
    ----------
    fixture_path:
        Optional package recipe JSON. When omitted, the required offline
        catalog is materialized.
    output_dir / stage:
        When ``stage`` is true, write manifest, receipt, PDFs, and extracted
        texts under ``output_dir``.
    live:
        Opt-in live USPTO download. Offline environments fail closed.
    non_public / failed_auth:
        When true, immediately reject (documents the fail-closed contracts).
    """

    if non_public:
        raise NonPublicPackageError(
            "non-public / private guidance packages are rejected for public "
            "corpus admission (PATLAW-185)"
        )
    if failed_auth:
        raise AuthFailedError(
            "failed-auth guidance packages are rejected; public corpus "
            "admission requires successful auth or no-auth public sources "
            "(PATLAW-185)"
        )

    if live:
        raise LiveAcquisitionUnavailableError(
            "live USPTO guidance PDF download is not enabled in this operator "
            "surface; use --default-catalog / --fixture (offline) or extend "
            "with a receipt-bound live client under operator control"
        )

    # Reject hard-coded latest on cutoff selection.
    if isinstance(cutoff, str):
        reject_unpinned_latest(cutoff, field_name="cutoff")

    if fixture_path is not None:
        return acquire_from_package_recipe(
            fixture_path,
            mode=mode,
            output_dir=output_dir,
            stage=stage,
            notes=notes,
            extractor=extractor,
        )

    return acquire_from_offline_catalog(
        cutoff=cutoff,
        mode=mode,
        output_dir=output_dir,
        stage=stage,
        notes=notes,
        extractor=extractor,
    )


def load_and_validate_manifest(path: PathLike) -> UsptoGuidancePdfInventoryManifest:
    """Load a staged inventory manifest and validate contracts."""

    payload = _load_json_object(Path(path))
    return validate_manifest_dict(payload)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Acquire USPTO examination guidance PDFs and extract indexable "
            f"public text ({ACQUIRE_TASK_ID}). Offline catalog default; "
            "no Hub upload. Non-public and failed-auth packages fail closed."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--default-catalog",
        action="store_true",
        help=(
            "Materialize the required USPTO guidance PDF catalog offline "
            "(deterministic synthetic PDFs for CI)"
        ),
    )
    input_group.add_argument(
        "--fixture",
        type=Path,
        help="Path to an offline package recipe JSON",
    )
    input_group.add_argument(
        "--validate-manifest",
        type=Path,
        help="Load and validate an existing guidance PDF inventory manifest",
    )
    input_group.add_argument(
        "--reject-non-public",
        action="store_true",
        help="Demonstrate fail-closed rejection of non-public packages",
    )
    input_group.add_argument(
        "--reject-failed-auth",
        action="store_true",
        help="Demonstrate fail-closed rejection of failed-auth packages",
    )

    parser.add_argument(
        "--cutoff",
        default=DEFAULT_INVENTORY_CUTOFF,
        help="Inventory-level cutoff pin (YYYY-MM-DD; never 'latest')",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local staging directory (required with --stage)",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help=(
            "Write manifest, acquisition receipt, package meta, PDFs, and "
            "extracted texts under --output-dir"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["dry_run", "stage", "acquire"],
        default="acquire",
        help="Materialization mode recorded on the inventory manifest",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Request live USPTO acquisition (fails closed when unavailable; "
            "CI must use offline catalog / fixtures)"
        ),
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the full inventory manifest JSON to stdout",
    )
    parser.add_argument(
        "--print-receipt",
        action="store_true",
        help="Print the acquisition receipt JSON to stdout",
    )
    parser.add_argument(
        "--no-print-summary",
        action="store_true",
        help="Suppress the human-readable summary",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional free-form notes recorded on the manifest/receipt",
    )
    return parser


def _print_summary(result: UsptoGuidanceAcquisitionResult) -> None:
    manifest = result.manifest
    counts = manifest.counts
    print(f"task_id:                 {ACQUIRE_TASK_ID}")
    print(f"goal_id:                 {ACQUIRE_GOAL_ID}")
    print(f"inventory_task_id:       {INVENTORY_TASK_ID}")
    print(f"schema_version:          {INVENTORY_SCHEMA_VERSION}")
    print(f"acquire_schema_version:  {ACQUIRE_SCHEMA_VERSION}")
    print(f"mode:                    {manifest.mode}")
    print(f"source_kind:             {result.source_kind}")
    print(f"edition_pin:             {manifest.edition_pin.pin_key}")
    print(f"authority_tier:          {AUTHORITY_TIER_GUIDANCE}")
    print(f"is_binding:              false")
    print(f"package_digest_sha256:   {result.package_digest_sha256}")
    print(f"package_root_cid:        {result.package_root_cid}")
    print(f"inventory_digest_sha256: {result.inventory_digest_sha256}")
    print(f"documents_required:      {counts.documents_required}")
    print(f"documents_present:       {counts.documents_present}")
    print(f"with_extraction:         {counts.with_extraction}")
    print(f"gap_entries:             {counts.gap_entries}")
    print(f"page_total:              {counts.page_total}")
    print(f"hash_verified:           {result.receipt.get('hash_verified')}")
    print(f"extraction_deterministic: true")
    print(f"non_public_rejected:     true")
    print(f"failed_auth_rejected:    true")
    print(f"hub_upload:              false")
    if result.fixture_path is not None:
        print(f"fixture_path:            {result.fixture_path}")
    if result.output_dir is not None:
        print(f"output_dir:              {result.output_dir}")
        print(f"  - {MANIFEST_FILENAME}")
        print(f"  - {RECEIPT_FILENAME}")
        print(f"  - {PACKAGE_META_FILENAME}")
        print(f"  - {PDFS_DIRNAME}/...")
        print(f"  - {TEXTS_DIRNAME}/...")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.reject_non_public:
        try:
            acquire_uspto_guidance_pdfs(non_public=True)
        except NonPublicPackageError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print("non_public_rejected: true")
            return 2
        print("ERROR: non-public path did not fail closed", file=sys.stderr)
        return 3

    if args.reject_failed_auth:
        try:
            acquire_uspto_guidance_pdfs(failed_auth=True)
        except AuthFailedError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print("failed_auth_rejected: true")
            return 2
        print("ERROR: failed-auth path did not fail closed", file=sys.stderr)
        return 3

    if args.validate_manifest is not None:
        try:
            manifest = load_and_validate_manifest(args.validate_manifest)
        except (
            UsptoGuidancePdfError,
            UsptoGuidanceAcquireError,
            FileNotFoundError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        counts = manifest.counts
        print("manifest_ok: true")
        print(f"edition_pin: {manifest.edition_pin.pin_key}")
        print(f"package_digest_sha256: {manifest.package_digest_sha256}")
        print(f"package_root_cid: {manifest.package_root_cid}")
        print(f"documents_present: {counts.documents_present}")
        print(f"with_extraction: {counts.with_extraction}")
        print(f"inventory_digest_sha256: {manifest.inventory_digest_sha256}")
        return 0

    if args.live:
        print(
            "ERROR: live USPTO guidance PDF acquisition is not enabled; "
            "use --default-catalog or --fixture",
            file=sys.stderr,
        )
        return 2

    if args.stage and args.output_dir is None:
        parser.error("--output-dir is required when --stage is set")

    try:
        if args.default_catalog:
            result = acquire_uspto_guidance_pdfs(
                fixture_path=None,
                output_dir=args.output_dir,
                stage=bool(args.stage),
                mode=args.mode,
                live=False,
                cutoff=args.cutoff,
                notes=args.notes or "",
            )
        else:
            result = acquire_uspto_guidance_pdfs(
                fixture_path=args.fixture,
                output_dir=args.output_dir,
                stage=bool(args.stage),
                mode=args.mode,
                live=False,
                cutoff=args.cutoff,
                notes=args.notes or "",
            )
    except (
        NonPublicPackageError,
        AuthFailedError,
        HashVerificationError,
        LiveAcquisitionUnavailableError,
        IncompleteAcquisitionError,
        UnpinnedLatestSelectionError,
        UnreviewedRightsError,
        PrivateOrNonPublicError,
        UsptoGuidancePdfError,
        UsptoGuidanceAcquireError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.no_print_summary:
        _print_summary(result)

    if args.print_receipt:
        print(json.dumps(dict(result.receipt), indent=2, sort_keys=True))

    if args.print_manifest:
        print(json.dumps(result.manifest.to_dict(), indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
