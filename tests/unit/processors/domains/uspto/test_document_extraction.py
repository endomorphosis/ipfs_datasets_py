"""Unit tests for USPTO document extraction processor (PATLAW-031)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractionOrigin,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.document_extraction_processor import (
    DOCUMENT_EXTRACTION_SCHEMA_VERSION,
    ArtifactDifference,
    DifferenceKind,
    DocumentExtractionInput,
    DocumentExtractionProcessor,
    DocumentExtractionResult,
    ExtractionBounds,
    ExtractionDisposition,
    ExtractionReasonCode,
    LayoutItemKind,
    MediaFamily,
    PageStatus,
    detect_media_family,
    estimate_native_char_coverage,
    extract_document,
    sha256_hex,
    text_similarity,
)
from tests.fixtures.uspto.documents.generators import (
    DOCX_CANARY,
    NATIVE_CANARY,
    RECEIPT_CANARY,
    SCANNED_CANARY,
    build_corrupt_pdf,
    build_docx_application,
    build_native_pdf_with_metadata,
    build_oversize_bytes,
    build_password_pdf,
    build_plain_archive,
    build_scanned_image_only_pdf,
    build_zip_bomb_like,
    fixture_manifest,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "uspto" / "documents"
)
RECIPE_PATH = FIXTURE_DIR / "document_extraction_recipe.json"


def _processor(**kwargs) -> DocumentExtractionProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"extract:test:{counter['n']:04d}"

    return DocumentExtractionProcessor(id_factory=_ids, **kwargs)


def _assert_round_trip(result: DocumentExtractionResult) -> None:
    first = result.to_dict()
    restored = DocumentExtractionResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    # public projection must omit body text
    public = result.public_projection()
    assert "full_text" not in public
    assert "page_texts" not in public
    blob = json.dumps(public)
    # Canaries must not appear in public projection even if present in result.
    assert NATIVE_CANARY not in blob
    assert SCANNED_CANARY not in blob


def _assert_span_provenance(result: DocumentExtractionResult) -> None:
    assert result.page_count >= 1
    assert result.page_coverage
    assert len(result.page_coverage) == result.page_count
    for cov in result.page_coverage:
        assert cov.artifact_id == result.artifact_id
        assert cov.page_index is not None
        assert cov.render_digest
        assert len(cov.render_digest) == 64
        assert cov.schema_version == DOCUMENT_EXTRACTION_SCHEMA_VERSION
    assert result.spans, "every extracted page must yield provenance spans when text exists or OCR injected"
    for span in result.spans:
        assert span.schema_version == CONTRACTS_SCHEMA_VERSION
        assert span.artifact_id == result.artifact_id
        assert span.span_id
        assert span.origin in ExtractionOrigin
        assert span.text_digest
        # page/character/bbox provenance anchors (bbox optional for DOCX)
        assert span.page_index is not None or result.media_family is MediaFamily.DOCX
    for item in result.layout_items:
        assert item.artifact_id == result.artifact_id
        assert item.item_id
        # layout items must point at a span when they share a page with text
        if item.page_index is not None and result.spans:
            # either explicit span_id or same-page coverage exists
            assert item.span_id is None or result.span_by_id(item.span_id) is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_detect_media_family() -> None:
    pdf = build_native_pdf_with_metadata()
    docx = build_docx_application()
    archive = build_plain_archive()
    assert detect_media_family(pdf) is MediaFamily.PDF
    assert detect_media_family(docx) is MediaFamily.DOCX
    assert detect_media_family(archive) is MediaFamily.ARCHIVE
    assert detect_media_family(b"not-a-doc") is MediaFamily.UNKNOWN
    assert (
        detect_media_family(None, declared_mime="application/pdf", filename="x.pdf")
        is MediaFamily.PDF
    )


def test_estimate_coverage_and_similarity() -> None:
    assert estimate_native_char_coverage("") == 0.0
    assert estimate_native_char_coverage("a" * 200) > 0.5
    assert text_similarity("hello world", "hello world") == 1.0
    assert text_similarity("hello world", "goodbye moon") < 0.5
    assert text_similarity("", "") == 1.0


def test_recipe_file_present() -> None:
    assert RECIPE_PATH.is_file()
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    assert recipe["schema_version"] == "uspto.document-extraction-recipe.v1"
    assert len(recipe["cases"]) >= 6


def test_fixture_manifest(tmp_path: Path) -> None:
    manifest = fixture_manifest(tmp_path / "docs")
    assert "files" in manifest
    assert (tmp_path / "docs" / "native_metadata.pdf").is_file()
    assert (tmp_path / "docs" / "application.docx").is_file()


# ---------------------------------------------------------------------------
# Native PDF extraction + provenance
# ---------------------------------------------------------------------------


def test_native_pdf_extraction_with_provenance() -> None:
    pdf = build_native_pdf_with_metadata()
    proc = _processor()
    result = proc.extract(
        DocumentExtractionInput(
            artifact_id="art:native-1",
            content_bytes=pdf,
            declared_mime="application/pdf",
            filename="native.pdf",
            classification=DisclosureClassification.PUBLIC_USER,
            content_sha256=sha256_hex(pdf),
            labels={"fixture": "native_pdf"},
        )
    )
    assert result.media_family is MediaFamily.PDF
    assert result.content_sha256 == sha256_hex(pdf)
    assert result.retained is True
    assert result.disposition in (
        ExtractionDisposition.EXTRACTED,
        ExtractionDisposition.REVIEW,
    )
    assert result.page_count == 1
    assert NATIVE_CANARY in result.full_text
    assert result.page_texts["0"]
    _assert_span_provenance(result)
    # At least one native origin span
    assert any(s.origin is ExtractionOrigin.NATIVE for s in result.spans)
    # Bounding boxes present for PDF native spans
    assert any(s.bbox is not None for s in result.spans)
    # Filing metadata heuristics
    names = {f.field_name for f in result.filing_metadata}
    assert "application_number" in names or any(
        f.field_name.startswith("pdf.") for f in result.filing_metadata
    )
    # Page coverage
    cov = result.page_coverage[0]
    assert cov.has_native_text is True
    assert cov.native_coverage > 0.0
    assert cov.render_digest
    _assert_round_trip(result)
    # Convenience wrapper
    again = extract_document(
        artifact_id="art:native-2",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert again.page_count == 1


def test_scanned_pdf_low_coverage_requires_review_without_ocr() -> None:
    pdf = build_scanned_image_only_pdf()
    result = _processor().extract(
        artifact_id="art:scan-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.page_count == 1
    cov = result.page_coverage[0]
    assert cov.has_native_text is False or cov.native_coverage < 0.2
    assert result.disposition is ExtractionDisposition.REVIEW
    assert result.review_state is ReviewState.REQUIRED
    assert ExtractionReasonCode.LOW_COVERAGE.value in result.reason_codes or (
        ExtractionReasonCode.OCR_UNAVAILABLE.value in result.reason_codes
        or ExtractionReasonCode.IMAGE_ONLY_PAGE.value in result.reason_codes
    )
    # Every page still has a coverage receipt + render digest
    assert cov.render_digest
    assert cov.artifact_id == "art:scan-1"


def test_scanned_pdf_ocr_injection_provenance() -> None:
    pdf = build_scanned_image_only_pdf()

    def fake_ocr(image_bytes: bytes, page_index: int):
        assert page_index == 0
        # image may be empty if pixmap failed; still return OCR text
        return {
            "text": SCANNED_CANARY,
            "confidence": 0.91,
            "status": "ok",
            "render_digest": sha256_hex(b"render-scan-1"),
            "word_boxes": [
                {
                    "text": SCANNED_CANARY,
                    "bbox": [10.0, 10.0, 400.0, 40.0],
                    "confidence": 0.91,
                }
            ],
        }

    result = _processor(ocr_callable=fake_ocr).extract(
        DocumentExtractionInput(
            artifact_id="art:scan-ocr-1",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            force_ocr=True,
        )
    )
    assert SCANNED_CANARY in result.full_text
    assert any(s.origin is ExtractionOrigin.OCR for s in result.spans)
    ocr_spans = [s for s in result.spans if s.origin is ExtractionOrigin.OCR]
    assert ocr_spans
    assert ocr_spans[0].bbox is not None
    assert ocr_spans[0].confidence == pytest.approx(0.91)
    assert result.page_coverage[0].has_ocr_text is True
    assert result.page_coverage[0].render_digest == sha256_hex(b"render-scan-1")
    assert ExtractionReasonCode.OCR_TEXT_EXTRACTED.value in result.reason_codes
    _assert_span_provenance(result)
    _assert_round_trip(result)


def test_ocr_by_page_map_without_callable() -> None:
    pdf = build_scanned_image_only_pdf()
    result = _processor().extract(
        DocumentExtractionInput(
            artifact_id="art:scan-map-1",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
            ocr_by_page={
                0: {
                    "text": SCANNED_CANARY,
                    "confidence": 0.8,
                    "status": "ok",
                    "word_boxes": [
                        {"text": SCANNED_CANARY, "bbox": [1, 2, 3, 4], "confidence": 0.8}
                    ],
                }
            },
        )
    )
    assert SCANNED_CANARY in result.full_text
    assert result.page_coverage[0].has_ocr_text is True


# ---------------------------------------------------------------------------
# DOCX structure
# ---------------------------------------------------------------------------


def test_docx_structure_and_metadata() -> None:
    docx = build_docx_application()
    result = _processor().extract(
        DocumentExtractionInput(
            artifact_id="art:docx-1",
            content_bytes=docx,
            declared_mime=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename="application.docx",
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.media_family is MediaFamily.DOCX
    assert result.disposition in (
        ExtractionDisposition.EXTRACTED,
        ExtractionDisposition.REVIEW,
    )
    assert DOCX_CANARY in result.full_text
    assert result.page_count >= 1
    kinds = {i.kind for i in result.layout_items}
    assert LayoutItemKind.PARAGRAPH in kinds
    assert LayoutItemKind.TABLE in kinds
    # Core properties / filing metadata
    meta_names = {f.field_name for f in result.filing_metadata}
    assert "docx.title" in meta_names or "application_number" in meta_names
    assert ExtractionReasonCode.DOCX_STRUCTURE_EXTRACTED.value in result.reason_codes
    # Provenance on every span
    for span in result.spans:
        assert span.artifact_id == "art:docx-1"
        assert span.text_digest
        assert span.origin is ExtractionOrigin.NATIVE
    for item in result.layout_items:
        assert item.artifact_id == "art:docx-1"
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# DOCX vs PDF differences
# ---------------------------------------------------------------------------


def test_docx_pdf_compare_emits_differences_and_review() -> None:
    docx = build_docx_application(include_equation_marker=True)
    pdf = build_native_pdf_with_metadata()
    result = _processor().extract(
        DocumentExtractionInput(
            artifact_id="art:orig-docx-1",
            content_bytes=docx,
            declared_mime=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            classification=DisclosureClassification.PUBLIC_USER,
            related_artifact_id="art:uspto-pdf-1",
            compare_content_bytes=pdf,
            compare_declared_mime="application/pdf",
            compare_filename="converted.pdf",
        )
    )
    assert result.differences, "DOCX/PDF pair must emit explicit differences"
    assert ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value in result.reason_codes
    assert result.requires_review is True
    assert result.review_state is ReviewState.REQUIRED
    for diff in result.differences:
        assert isinstance(diff, ArtifactDifference)
        assert diff.docx_artifact_id or diff.pdf_artifact_id
        assert diff.kind in DifferenceKind
        assert diff.reason_codes
    # compare API on two prior results
    docx_only = _processor().extract(
        artifact_id="art:docx-only",
        content_bytes=docx,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    pdf_only = _processor().extract(
        artifact_id="art:pdf-only",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    diffs = _processor().compare_docx_pdf(
        docx_result=docx_only, pdf_result=pdf_only
    )
    assert diffs
    _assert_round_trip(result)


# ---------------------------------------------------------------------------
# Bounded failure cases
# ---------------------------------------------------------------------------


def test_password_protected_pdf_rejected() -> None:
    pdf = build_password_pdf()
    result = _processor().extract(
        artifact_id="art:pw-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition in (
        ExtractionDisposition.REJECTED,
        ExtractionDisposition.QUARANTINE,
    )
    assert ExtractionReasonCode.PASSWORD_PROTECTED.value in result.reason_codes
    assert result.page_count == 0
    assert result.retained is True
    assert result.requires_review is True


def test_corrupt_pdf_rejected() -> None:
    result = _processor().extract(
        artifact_id="art:corrupt-1",
        content_bytes=build_corrupt_pdf(),
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is ExtractionDisposition.REJECTED
    assert ExtractionReasonCode.CORRUPT_DOCUMENT.value in result.reason_codes
    assert result.retained is True


def test_oversize_document_rejected() -> None:
    bounds = ExtractionBounds(max_bytes=64)
    body = build_oversize_bytes(128)
    result = _processor(bounds=bounds).extract(
        artifact_id="art:big-1",
        content_bytes=body,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is ExtractionDisposition.REJECTED
    assert ExtractionReasonCode.OVERSIZE_DOCUMENT.value in result.reason_codes


def test_missing_bytes_rejected() -> None:
    result = _processor().extract(
        artifact_id="art:empty-1",
        content_bytes=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is ExtractionDisposition.REJECTED
    assert ExtractionReasonCode.MISSING_BYTES.value in result.reason_codes


def test_archive_bounded_inventory_only() -> None:
    archive = build_plain_archive()
    result = _processor().extract(
        artifact_id="art:zip-1",
        content_bytes=archive,
        filename="bundle.zip",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.media_family is MediaFamily.ARCHIVE
    assert result.disposition is ExtractionDisposition.REVIEW
    assert ExtractionReasonCode.ARCHIVE_BOUNDED.value in result.reason_codes
    assert result.unsupported_features
    assert any(
        i.attributes.get("role") == "archive_member_inventory"
        for i in result.layout_items
    )
    # No full nested extract text
    assert result.full_text == ""
    assert result.page_count == 0


def test_archive_member_count_rejected() -> None:
    bounds = ExtractionBounds(max_archive_members=3)
    body = build_zip_bomb_like(member_count=10, member_size=16)
    result = _processor(bounds=bounds).extract(
        artifact_id="art:zip-many",
        content_bytes=body,
        filename="many.zip",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is ExtractionDisposition.REJECTED
    assert ExtractionReasonCode.ARCHIVE_REJECTED.value in result.reason_codes


def test_unknown_classification_quarantines() -> None:
    pdf = build_native_pdf_with_metadata()
    result = _processor().extract(
        artifact_id="art:unknown-class",
        content_bytes=pdf,
        classification=DisclosureClassification.UNKNOWN,
    )
    assert result.disposition is ExtractionDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert ExtractionReasonCode.QUARANTINE_CLASSIFICATION.value in result.reason_codes


def test_unsupported_media_rejected() -> None:
    result = _processor().extract(
        artifact_id="art:bin-1",
        content_bytes=b"\x00\x01\x02\x03not-a-document",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.disposition is ExtractionDisposition.REJECTED
    assert ExtractionReasonCode.UNSUPPORTED_MEDIA.value in result.reason_codes


# ---------------------------------------------------------------------------
# Layout items, signature presence, logging hygiene
# ---------------------------------------------------------------------------


def test_layout_items_have_artifact_provenance() -> None:
    pdf = build_native_pdf_with_metadata()
    result = _processor().extract(
        artifact_id="art:layout-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    # Even without form widgets, pages/text layout should exist via spans;
    # image/table detection is best-effort.
    for item in result.layout_items:
        assert item.schema_version == DOCUMENT_EXTRACTION_SCHEMA_VERSION
        assert item.artifact_id == "art:layout-1"
        assert item.kind in LayoutItemKind
        assert item.origin in ExtractionOrigin


def test_no_document_text_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    pdf = build_native_pdf_with_metadata()
    with caplog.at_level(logging.DEBUG):
        result = _processor().extract(
            artifact_id="art:log-1",
            content_bytes=pdf,
            classification=DisclosureClassification.PUBLIC_USER,
        )
    assert NATIVE_CANARY in result.full_text
    joined = "\n".join(r.message for r in caplog.records)
    assert NATIVE_CANARY not in joined
    assert RECEIPT_CANARY not in joined


def test_extract_many_and_page_limit() -> None:
    pdf = build_native_pdf_with_metadata()
    docx = build_docx_application()
    results = _processor().extract_many(
        [
            {
                "artifact_id": "art:m1",
                "content_bytes": pdf,
                "classification": DisclosureClassification.PUBLIC_USER.value,
            },
            {
                "artifact_id": "art:m2",
                "content_bytes": docx,
                "classification": DisclosureClassification.PUBLIC_USER.value,
            },
        ]
    )
    assert len(results) == 2
    assert results[0].media_family is MediaFamily.PDF
    assert results[1].media_family is MediaFamily.DOCX

    # page limit bound must be a positive int
    with pytest.raises(ValueError):
        ExtractionBounds(max_pages=0)


def test_mime_conflict_warning() -> None:
    pdf = build_native_pdf_with_metadata()
    result = _processor().extract(
        artifact_id="art:mime-1",
        content_bytes=pdf,
        declared_mime=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        classification=DisclosureClassification.PUBLIC_USER,
    )
    # Magic wins as PDF; conflict is explicit.
    assert result.media_family is MediaFamily.PDF
    assert (
        ExtractionReasonCode.MIME_CONTENT_CONFLICT.value in result.reason_codes
        or "declared_mime_conflicts_with_magic" in result.warnings
    )


def test_difference_and_coverage_serialization() -> None:
    diff = ArtifactDifference(
        schema_version=DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        difference_id="diff:1",
        kind=DifferenceKind.PAGINATION,
        status="disagreement",
        docx_artifact_id="art:d",
        pdf_artifact_id="art:p",
        docx_page=1,
        pdf_page=2,
        field=None,
        element="equation_1",
        reason_codes=(ExtractionReasonCode.DOCX_PDF_DIFFERENCE.value,),
        detail="pagination drift",
    )
    restored = ArtifactDifference.from_dict(diff.to_dict())
    assert restored == diff


def test_every_extracted_item_has_provenance_on_native_fixture() -> None:
    """Acceptance: every page and extracted item has artifact/page/char/bbox provenance."""
    pdf = build_native_pdf_with_metadata()
    result = _processor().extract(
        artifact_id="art:accept-1",
        content_bytes=pdf,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    assert result.pages
    for page in result.pages:
        assert page.coverage.artifact_id == result.artifact_id
        assert page.coverage.page_index == page.page_index
        assert page.coverage.render_digest
        for sid in page.span_ids:
            span = result.span_by_id(sid)
            assert span is not None
            assert span.page_index == page.page_index
            assert span.char_start is not None
            assert span.char_end is not None
            assert span.char_end >= span.char_start
    for item in result.layout_items:
        assert item.artifact_id == result.artifact_id
    for field in result.filing_metadata:
        assert field.value_digest
        assert field.field_name
    # Differences and unsupported are always lists (possibly empty) — explicit.
    assert isinstance(result.differences, tuple)
    assert isinstance(result.unsupported_features, tuple)
