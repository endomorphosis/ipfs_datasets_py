"""Unit tests for text_layer_merge (PATLAW-004)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.specialized.pdf.text_layer_merge import (
    ORIGIN_EMBEDDED_IMAGE_OCR,
    ORIGIN_NATIVE,
    ORIGIN_RENDERED_OCR,
    STATUS_LOW_CONFIDENCE,
    STATUS_OCR_NOT_NEEDED,
    STATUS_OCR_UNAVAILABLE,
    STATUS_OK,
    estimate_native_char_coverage,
    merge_document_layers,
    merge_page_layers,
    quality_scores_from_merge,
    should_run_page_ocr,
    text_similarity,
)


class TestCoverageHelpers:
    def test_empty_text_has_zero_coverage(self):
        assert estimate_native_char_coverage("") == 0.0
        assert estimate_native_char_coverage("   \n  ") == 0.0

    def test_rich_text_has_high_coverage(self):
        text = "word " * 200
        assert estimate_native_char_coverage(text) >= 0.5

    def test_should_run_page_ocr_for_sparse_native(self):
        assert should_run_page_ocr("") is True
        assert should_run_page_ocr("ok") is True
        rich = "paragraph content " * 40
        assert should_run_page_ocr(rich, coverage=0.9) is False

    def test_text_similarity_identical(self):
        assert text_similarity("Hello World", "hello world") == 1.0


class TestMergePageLayers:
    def test_native_only_page_provenance(self):
        result = merge_page_layers(
            1,
            native_blocks=[
                {"content": "Claim 1. A method comprising…", "bbox": [10, 10, 200, 30]},
                {"content": "wherein the widget is red.", "bbox": [10, 40, 200, 60]},
            ],
        )
        assert result.page == 1
        assert "Claim 1" in result.text
        assert result.coverage.has_native_text is True
        assert result.coverage.has_ocr_text is False
        assert ORIGIN_NATIVE in result.coverage.origins_present
        assert result.coverage.ocr_status == STATUS_OCR_NOT_NEEDED
        assert all(s.origin == ORIGIN_NATIVE for s in result.spans)
        assert all(s.bbox is not None for s in result.spans)
        assert result.spans[0].char_start == 0
        assert result.spans[0].char_end > 0

    def test_rendered_ocr_for_scanned_page_has_coverage_and_provenance(self):
        result = merge_page_layers(
            2,
            native_blocks=[],
            rendered_ocr={
                "text": "SYNTHETIC-SCANNED-OFFICE-ACTION-REQ-112",
                "confidence": 0.91,
                "engine": "tesseract",
                "status": "ok",
                "render_digest": "abc123",
                "word_boxes": [
                    {
                        "text": "SYNTHETIC-SCANNED-OFFICE-ACTION-REQ-112",
                        "bbox": [20, 20, 400, 40],
                        "confidence": 0.91,
                    }
                ],
            },
            rotation=90,
            render_digest="abc123",
        )
        assert result.coverage.has_ocr_text is True
        assert result.coverage.rotation == 90
        assert result.coverage.render_digest == "abc123"
        assert ORIGIN_RENDERED_OCR in result.coverage.origins_present
        assert result.coverage.ocr_confidence == pytest.approx(0.91)
        assert result.coverage.provenance["ocr_confidence_present"] is True
        assert any(s.origin == ORIGIN_RENDERED_OCR for s in result.spans)

    def test_unavailable_ocr_is_explicit_not_high_confidence(self):
        result = merge_page_layers(
            3,
            native_blocks=[],
            rendered_ocr={
                "text": "",
                "confidence": None,
                "engine": "none",
                "status": "ocr_unavailable",
                "error": "No OCR engines available",
                "available_engines": [],
            },
            available_engines=[],
        )
        assert result.coverage.ocr_status == STATUS_OCR_UNAVAILABLE
        assert result.coverage.ocr_confidence is None
        assert result.coverage.provenance["ocr_confidence_present"] is False
        assert "ocr_unavailable" in result.coverage.warnings

    def test_low_confidence_ocr_is_explicit(self):
        result = merge_page_layers(
            4,
            native_blocks=[],
            rendered_ocr={
                "text": "blurry text",
                "confidence": 0.35,
                "engine": "tesseract",
                "status": "low_confidence",
            },
        )
        assert result.coverage.ocr_status == STATUS_LOW_CONFIDENCE
        assert result.coverage.ocr_confidence == pytest.approx(0.35)
        assert result.coverage.ocr_confidence < 0.7

    def test_dedupes_near_duplicate_native_and_ocr(self):
        result = merge_page_layers(
            5,
            native_blocks=[{"content": "The quick brown fox", "bbox": [0, 0, 100, 10]}],
            rendered_ocr={
                "text": "The quick brown fox",
                "confidence": 0.88,
                "engine": "tesseract",
                "status": "ok",
            },
        )
        # Should keep native preference and not double the phrase in merged text
        assert result.text.count("quick brown fox") == 1
        assert ORIGIN_NATIVE in result.selected_origins

    def test_embedded_image_ocr_origin(self):
        result = merge_page_layers(
            6,
            native_blocks=[{"content": "Header native", "bbox": [0, 0, 50, 10]}],
            embedded_image_ocr=[
                {
                    "text": "Figure caption OCR",
                    "confidence": 0.8,
                    "engine": "tesseract",
                    "image_index": 0,
                    "bbox": [10, 200, 300, 220],
                    "status": "ok",
                }
            ],
        )
        origins = {s.origin for s in result.spans}
        assert ORIGIN_NATIVE in origins
        assert ORIGIN_EMBEDDED_IMAGE_OCR in origins


class TestDocumentMergeAndQuality:
    def test_document_merge_overall_coverage(self):
        doc = merge_document_layers(
            [
                {
                    "page": 1,
                    "native_blocks": [
                        {"content": "Page one native content " * 10, "bbox": [0, 0, 1, 1]}
                    ],
                },
                {
                    "page": 2,
                    "native_blocks": [],
                    "rendered_ocr": {
                        "text": "scanned page two",
                        "confidence": 0.85,
                        "engine": "tesseract",
                        "status": "ok",
                        "render_digest": "d2",
                    },
                    "rotation": 180,
                },
            ]
        )
        assert len(doc.pages) == 2
        assert doc.overall_coverage > 0
        assert doc.page_coverage[1].rotation == 180
        assert doc.page_coverage[1].render_digest == "d2"
        assert doc.overall_ocr_confidence == pytest.approx(0.85)

    def test_missing_ocr_not_scored_as_high_confidence(self):
        doc = merge_document_layers(
            [
                {
                    "page": 1,
                    "native_blocks": [],
                    "rendered_ocr": {
                        "text": "",
                        "confidence": None,
                        "engine": "none",
                        "status": "ocr_unavailable",
                        "available_engines": [],
                    },
                }
            ]
        )
        scores = quality_scores_from_merge(doc)
        assert scores["ocr_confidence"] in (None, 0.0)
        assert scores["ocr_status"] == STATUS_OCR_UNAVAILABLE
        # Must not look like a healthy high-confidence extraction
        if scores["ocr_confidence"] is not None:
            assert scores["ocr_confidence"] < 0.5
        assert scores["overall_quality"] < 0.95

    def test_ocr_not_needed_does_not_inject_fake_confidence(self):
        doc = merge_document_layers(
            [
                {
                    "page": 1,
                    "native_blocks": [
                        {"content": "Plenty of native selectable text " * 20}
                    ],
                }
            ]
        )
        scores = quality_scores_from_merge(doc)
        assert scores["ocr_status"] == STATUS_OCR_NOT_NEEDED
        assert scores["ocr_confidence"] is None
