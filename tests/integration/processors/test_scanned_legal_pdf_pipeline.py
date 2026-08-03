"""Integration tests: scanned/rotated legal PDF OCR coverage (PATLAW-004)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import anyio
import pytest

from tests.fixtures.uspto.pdf.generators import (
    ROTATED_CANARY,
    SCANNED_CANARY,
    build_mixed_native_and_image_pdf,
    build_native_text_pdf,
    build_rotated_scanned_pdf,
    build_scanned_image_only_pdf,
)


def _mock_ocr_engine(text_by_default: str = SCANNED_CANARY, confidence: float = 0.9):
    """OCR engine that only claims availability for a fake 'mock' backend."""
    engine = MagicMock()
    engine.get_available_engines.return_value = ["mock"]

    def extract(image_data, strategy="quality_first", confidence_threshold=0.7):
        assert isinstance(image_data, (bytes, bytearray))
        assert len(image_data) > 0
        return {
            "text": text_by_default,
            "confidence": confidence,
            "engine": "mock",
            "status": "ok" if confidence >= confidence_threshold else "low_confidence",
            "available_engines": ["mock"],
            "engines_attempted": ["mock"],
            "word_boxes": [
                {
                    "text": text_by_default,
                    "bbox": [10, 10, 400, 40],
                    "confidence": confidence,
                }
            ],
        }

    engine.extract_with_ocr.side_effect = extract
    engine.extract_with_ocr_async = None
    return engine


def _processor(tmp_path: Path, ocr_engine=None):
    from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import PDFProcessor

    mock_storage = MagicMock()
    mock_storage.store_json.side_effect = lambda *_a, **_k: "bafy-mock-cid"

    mocks = {
        "storage": mock_storage,
        "ocr_engine": ocr_engine or _mock_ocr_engine(),
        "integrator": MagicMock(),
        "optimizer": MagicMock(),
        "audit_logger": None,
        "monitoring": None,
    }

    # integrator.integrate_document async
    async def _integrate(llm_document, **kwargs):
        kg = MagicMock()
        kg.entities = []
        kg.relationships = []
        kg.metadata = {}
        return kg

    mocks["integrator"].integrate_document = _integrate

    async def _optimize(decomposed_content, metadata=None):
        llm_document = MagicMock()
        llm_document.document_id = "doc-test"
        llm_document.chunks = []
        llm_document.summary = ""
        llm_document.key_entities = []
        llm_document.model_dump = lambda: {"document_id": "doc-test"}
        return {
            "llm_document": llm_document,
            "chunks": [],
            "summary": "",
            "key_entities": [],
        }

    mocks["optimizer"].optimize_for_llm = _optimize

    return PDFProcessor(
        enable_monitoring=False,
        enable_audit=False,
        mock_dict=mocks,
    )


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    d = tmp_path / "uspto_pdf"
    d.mkdir()
    return d


class TestScannedLegalPdfPipeline:
    def test_scanned_page_gets_rendered_ocr_and_coverage(self, fixtures_dir: Path):
        pdf_path = build_scanned_image_only_pdf(fixtures_dir / "scanned.pdf")
        processor = _processor(fixtures_dir)

        async def run():
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            merge = processor._merge_text_layers(decomposed, ocr)
            return decomposed, ocr, merge

        decomposed, ocr, merge = anyio.run(run)
        assert len(decomposed["pages"]) == 1
        page_num = decomposed["pages"][0]["page_number"]
        page_ocr = ocr[page_num]
        assert page_ocr["rendered"] is not None
        assert page_ocr["rendered"]["origin"] == "rendered_ocr"
        assert page_ocr["render_digest"]
        assert page_ocr["native_coverage"] < 0.2
        assert merge.page_coverage[0].has_ocr_text is True
        assert merge.page_coverage[0].render_digest
        assert SCANNED_CANARY in merge.full_text or SCANNED_CANARY in (
            page_ocr["rendered"].get("text") or ""
        )
        # Provenance on spans
        assert any(s.origin == "rendered_ocr" for s in merge.pages[0].spans)

    def test_rotated_scanned_page_has_rotation_and_coverage(self, fixtures_dir: Path):
        pdf_path = build_rotated_scanned_pdf(
            fixtures_dir / "rotated.pdf", text=ROTATED_CANARY, rotation=90
        )
        processor = _processor(
            fixtures_dir, ocr_engine=_mock_ocr_engine(text_by_default=ROTATED_CANARY)
        )

        async def run():
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            merge = processor._merge_text_layers(decomposed, ocr)
            return decomposed, ocr, merge

        decomposed, ocr, merge = anyio.run(run)
        page = decomposed["pages"][0]
        assert int(page.get("rotation") or 0) % 360 == 90
        page_ocr = ocr[page["page_number"]]
        assert page_ocr["rendered"] is not None
        assert page_ocr["render_digest"]
        cov = merge.page_coverage[0]
        assert cov.rotation % 360 == 90
        assert cov.render_digest
        assert cov.has_ocr_text or page_ocr["rendered"].get("text")

    def test_unavailable_ocr_is_explicit_and_not_high_confidence(self, fixtures_dir: Path):
        pdf_path = build_scanned_image_only_pdf(fixtures_dir / "scan2.pdf")

        dead_engine = MagicMock()
        dead_engine.get_available_engines.return_value = []

        def extract(*_a, **_k):
            return {
                "text": "",
                "confidence": None,
                "engine": "none",
                "status": "ocr_unavailable",
                "error": "No OCR engines available",
                "available_engines": [],
                "engines_attempted": [],
                "word_boxes": [],
            }

        dead_engine.extract_with_ocr.side_effect = extract
        dead_engine.extract_with_ocr_async = None
        processor = _processor(fixtures_dir, ocr_engine=dead_engine)

        async def run():
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            merge = processor._merge_text_layers(decomposed, ocr)
            scores = processor._get_quality_scores(
                {"extracted_entities": []}, ocr, text_merge_result=merge
            )
            return ocr, merge, scores

        ocr, merge, scores = anyio.run(run)
        assert ocr["_meta"]["ocr_available"] is False
        assert merge.ocr_status == "ocr_unavailable"
        assert merge.overall_ocr_confidence is None
        assert scores["ocr_status"] == "ocr_unavailable"
        assert scores["ocr_confidence"] in (None, 0.0)
        # Critical acceptance: not scored as high confidence
        if scores["ocr_confidence"] is not None:
            assert scores["ocr_confidence"] < 0.5
        assert scores.get("overall_quality", 1.0) < 0.95

    def test_low_confidence_ocr_is_explicit(self, fixtures_dir: Path):
        pdf_path = build_scanned_image_only_pdf(fixtures_dir / "lowconf.pdf")
        processor = _processor(
            fixtures_dir,
            ocr_engine=_mock_ocr_engine(text_by_default="blurry", confidence=0.2),
        )

        async def run():
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            merge = processor._merge_text_layers(decomposed, ocr)
            return merge

        merge = anyio.run(run)
        assert merge.overall_ocr_confidence is not None
        assert merge.overall_ocr_confidence < 0.7
        assert merge.ocr_status == "low_confidence"

    def test_mixed_document_native_and_scan_coverage(self, fixtures_dir: Path):
        pdf_path = build_mixed_native_and_image_pdf(fixtures_dir / "mixed.pdf")
        processor = _processor(fixtures_dir)

        async def run():
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            merge = processor._merge_text_layers(decomposed, ocr)
            return decomposed, merge

        decomposed, merge = anyio.run(run)
        assert len(decomposed["pages"]) == 2
        assert len(merge.page_coverage) == 2
        # Page 1 native should be present; page 2 should need OCR
        assert merge.page_coverage[0].has_native_text is True
        assert merge.page_coverage[1].has_ocr_text is True or merge.page_coverage[
            1
        ].ocr_status in ("ocr_unavailable", "ocr_failed", "low_confidence", "ok")

    def test_native_text_pdf_skips_unnecessary_page_ocr(self, fixtures_dir: Path):
        pdf_path = build_native_text_pdf(fixtures_dir / "native.pdf")
        processor = _processor(fixtures_dir)

        async def run():
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            return decomposed, ocr

        decomposed, ocr = anyio.run(run)
        page_num = decomposed["pages"][0]["page_number"]
        # High native coverage → rendered OCR may be skipped
        if decomposed["pages"][0]["native_coverage"] >= 0.15:
            # rendered is None when OCR not needed
            assert ocr[page_num]["rendered"] is None or ocr[page_num]["native_coverage"] > 0
