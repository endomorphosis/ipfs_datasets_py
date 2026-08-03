"""
PATLAW-007: PDFProcessorAdapter must delegate to the real PDF pipeline.

Acceptance:
  - Adapter output contains actual fixture text and page provenance
  - Placeholder strings are impossible
  - Partial and error states propagate
  - Private content is not logged
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import anyio
import pytest

from ipfs_datasets_py.processors.adapters.pdf_adapter import PDFProcessorAdapter
from ipfs_datasets_py.processors.protocol import ProcessingStatus
from tests.fixtures.uspto.pdf.generators import (
    CONFIDENTIAL_CANARY,
    NATIVE_CANARY,
    SCANNED_CANARY,
    build_confidential_scanned_pdf,
    build_mixed_native_and_image_pdf,
    build_native_text_pdf,
    build_scanned_image_only_pdf,
)


# ---------------------------------------------------------------------------
# Helpers: real specialized pipeline with injectable OCR / storage mocks
# ---------------------------------------------------------------------------


def _mock_ocr_engine(
    text_by_default: str = SCANNED_CANARY,
    confidence: float = 0.9,
    available: Optional[list[str]] = None,
):
    engine = MagicMock()
    engines = list(available) if available is not None else ["mock"]
    engine.get_available_engines.return_value = engines

    def extract(image_data, strategy="quality_first", confidence_threshold=0.7):
        if not engines:
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
        status = "ok" if confidence >= confidence_threshold else "low_confidence"
        return {
            "text": text_by_default,
            "confidence": confidence,
            "engine": "mock",
            "status": status,
            "available_engines": engines,
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


class _MockKnowledgeGraph:
    """Minimal GraphRAG knowledge graph for pipeline stage 8."""

    def __init__(self, document_id: str = "doc-adapter-test"):
        self.document_id = document_id
        self.entities = []
        self.relationships = []
        self.metadata = {}
        self.chunks = []


def _make_llm_document(summary: str = ""):
    """Build a real LLMDocument so isinstance checks in the pipeline pass."""
    from ipfs_datasets_py.processors.llm_optimizer import LLMDocument

    return LLMDocument(
        document_id="doc-adapter-test",
        title="Adapter Test PDF",
        chunks=[],
        summary=summary or "",
        key_entities=[],
        processing_metadata={"source": "pdf_adapter_test"},
        document_embedding=None,
    )


def _real_pipeline_processor(
    *,
    ocr_engine=None,
    canary_in_optimize: Optional[str] = None,
):
    """Construct specialized PDFProcessor with safe mocks (no network ML)."""
    from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import (
        PDFProcessor,
    )

    # Mock storage: page nodes may contain non-JSON image bytes; we only need
    # CID-shaped returns so the pipeline can finish and expose text_merge.
    storage = MagicMock()
    _cid_counter = {"n": 0}

    def _store_json(_obj):
        _cid_counter["n"] += 1
        return f"bafy-mock-cid-{_cid_counter['n']}"

    storage.store_json.side_effect = _store_json
    storage.store.side_effect = lambda *_a, **_k: f"bafy-mock-bytes-{_cid_counter['n']}"

    async def _integrate_document(llm_document, **kwargs):
        doc_id = getattr(llm_document, "document_id", None) or "doc-adapter-test"
        return _MockKnowledgeGraph(document_id=doc_id)

    integrator = MagicMock()
    integrator.integrate_document = _integrate_document

    async def _optimize_for_llm(decomposed_content, metadata=None):
        # process_pdf's _optimize_for_llm / GraphRAG stages require a real
        # LLMDocument instance (isinstance check against pydantic model).
        return _make_llm_document(summary=canary_in_optimize or "")

    optimizer = MagicMock()
    optimizer.optimize_for_llm = _optimize_for_llm
    optimizer.embedding_model = "mock-embedding-model"

    processor = PDFProcessor(
        enable_monitoring=False,
        enable_audit=False,
        mock_dict={
            "storage": storage,
            "ocr_engine": ocr_engine or _mock_ocr_engine(),
            "integrator": integrator,
            "optimizer": optimizer,
            "audit_logger": None,
            "monitoring": None,
        },
    )
    # Skip QueryEngine (requires real IPLDStorage); text merge already done.
    async def _noop_query_interface(*_a, **_k):
        return None

    processor._setup_query_interface = _noop_query_interface  # type: ignore[method-assign]
    return processor


def _run(coro):
    return anyio.run(lambda: coro)


def _capture_logging():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    # Also attach to adapter / specialized loggers
    for name in (
        "ipfs_datasets_py.processors.adapters.pdf_adapter",
        "ipfs_datasets_py.processors.specialized.pdf.pdf_processor",
        "ipfs_datasets_py.processors.specialized.pdf",
    ):
        logging.getLogger(name).setLevel(logging.DEBUG)
        logging.getLogger(name).addHandler(handler)
    return stream, handler, previous_level


def _release_logging(stream, handler, previous_level):
    root = logging.getLogger()
    root.removeHandler(handler)
    root.setLevel(previous_level)
    for name in (
        "ipfs_datasets_py.processors.adapters.pdf_adapter",
        "ipfs_datasets_py.processors.specialized.pdf.pdf_processor",
        "ipfs_datasets_py.processors.specialized.pdf",
    ):
        logging.getLogger(name).removeHandler(handler)
    return stream.getvalue()


# ---------------------------------------------------------------------------
# can_process
# ---------------------------------------------------------------------------


class TestCanProcess:
    def test_accepts_pdf_extension(self):
        adapter = PDFProcessorAdapter(processor=MagicMock())

        async def run():
            return await adapter.can_process("office_action.pdf")

        assert _run(run()) is True

    def test_rejects_non_pdf(self, tmp_path: Path):
        adapter = PDFProcessorAdapter(processor=MagicMock())
        txt = tmp_path / "note.txt"
        txt.write_text("not a pdf")

        async def run():
            return await adapter.can_process(txt)

        assert _run(run()) is False


# ---------------------------------------------------------------------------
# Real fixture text + page provenance
# ---------------------------------------------------------------------------


class TestRealFixtureTextAndProvenance:
    def test_native_pdf_returns_fixture_text_and_page_provenance(
        self, tmp_path: Path
    ):
        pdf_path = build_native_text_pdf(tmp_path / "native.pdf")
        processor = _real_pipeline_processor()
        adapter = PDFProcessorAdapter(processor=processor)

        async def run():
            return await adapter.process(pdf_path)

        result = _run(run())

        assert result.metadata.status in (
            ProcessingStatus.SUCCESS,
            ProcessingStatus.PARTIAL,
        )
        text = result.content.get("text") or ""
        assert NATIVE_CANARY in text, (
            f"Expected fixture canary in extracted text; got {text[:200]!r}"
        )
        # Historical placeholder must be impossible
        assert not text.startswith("PDF content from ")
        assert f"PDF content from {pdf_path}" not in text

        pages = result.content.get("pages") or []
        assert len(pages) >= 1
        page0 = pages[0]
        assert page0.get("page") is not None
        assert NATIVE_CANARY in (page0.get("text") or "") or NATIVE_CANARY in text

        # Span / coverage provenance
        spans = page0.get("spans") or []
        coverage = page0.get("coverage") or {}
        assert spans or coverage, "Expected page span or coverage provenance"
        if spans:
            assert any(
                isinstance(s, dict) and s.get("origin") for s in spans
            ), "Spans must carry origin provenance"
        if coverage:
            assert coverage.get("page") is not None or "has_native_text" in coverage

        provenance = result.content.get("provenance") or {}
        assert provenance, "Document-level provenance must be present"
        page_coverage = result.content.get("page_coverage") or []
        assert page_coverage, "page_coverage receipts required"

    def test_mixed_pdf_preserves_per_page_provenance(self, tmp_path: Path):
        pdf_path = build_mixed_native_and_image_pdf(tmp_path / "mixed.pdf")
        processor = _real_pipeline_processor(
            ocr_engine=_mock_ocr_engine(text_by_default=SCANNED_CANARY)
        )
        adapter = PDFProcessorAdapter(processor=processor)

        async def run():
            return await adapter.process(pdf_path)

        result = _run(run())
        pages = result.content.get("pages") or []
        assert len(pages) == 2

        text = result.content.get("text") or ""
        assert NATIVE_CANARY in text or any(
            NATIVE_CANARY in (p.get("text") or "") for p in pages
        )
        # Scanned canary may appear via OCR merge on page 2
        joined = text + "\n".join(p.get("text") or "" for p in pages)
        assert NATIVE_CANARY in joined or SCANNED_CANARY in joined

        for p in pages:
            assert p.get("page") is not None
            cov = p.get("coverage") or {}
            # Each page should have a coverage receipt or spans
            assert cov or p.get("spans") is not None

    def test_placeholder_string_impossible_even_if_pipeline_empty(
        self, tmp_path: Path
    ):
        """Adapter must never synthesize the historical placeholder string."""
        # Fake processor that returns success with empty merge — adapter may
        # mark PARTIAL but must not invent "PDF content from …"
        fake = MagicMock()

        async def process_pdf(path, metadata=None):
            return {
                "status": "success",
                "document_id": "empty-doc",
                "stages_completed": ["PDF validated and analyzed"],
                "text_merge": {
                    "full_text": "",
                    "pages": [],
                    "page_coverage": [],
                    "overall_coverage": 0.0,
                    "overall_ocr_confidence": None,
                    "ocr_status": "empty",
                    "warnings": ["no_extractable_text"],
                    "provenance": {"page_count": 0},
                },
                "page_coverage": [],
                "processing_metadata": {
                    "pipeline_version": "2.0",
                    "quality_scores": {
                        "ocr_status": "empty",
                        "overall_quality": 0.0,
                    },
                },
            }

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)
        pdf_path = tmp_path / "ghost.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 empty")

        async def run():
            return await adapter.process(pdf_path)

        result = _run(run())
        text = result.content.get("text") or ""
        assert text == "" or not text.startswith("PDF content from ")
        assert f"PDF content from {pdf_path}" not in text
        assert "PDF content from " not in text
        assert result.metadata.status in (
            ProcessingStatus.PARTIAL,
            ProcessingStatus.FAILED,
        )


# ---------------------------------------------------------------------------
# Partial and error state propagation
# ---------------------------------------------------------------------------


class TestPartialAndErrorPropagation:
    def test_pipeline_error_status_propagates_as_failed(self, tmp_path: Path):
        fake = MagicMock()

        async def process_pdf(path, metadata=None):
            return {
                "status": "error",
                "error": "simulated_pipeline_failure",
                "message": "simulated_pipeline_failure",
                "stages_completed": ["PDF validated and analyzed"],
                "pdf_path": str(path),
            }

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)

        async def run():
            return await adapter.process(tmp_path / "missing.pdf")

        result = _run(run())
        assert result.metadata.status == ProcessingStatus.FAILED
        assert result.has_errors()
        assert any("simulated_pipeline_failure" in e for e in result.metadata.errors)
        assert result.extra.get("pipeline_status") == "error"
        # No placeholder text on failure
        assert not (result.content.get("text") or "").startswith("PDF content from ")

    def test_exception_from_pipeline_is_failed(self, tmp_path: Path):
        fake = MagicMock()

        async def process_pdf(path, metadata=None):
            raise FileNotFoundError(str(path))

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)

        async def run():
            return await adapter.process(tmp_path / "nope.pdf")

        result = _run(run())
        assert result.metadata.status == ProcessingStatus.FAILED
        assert result.has_errors()
        assert "FileNotFoundError" in (result.content.get("error") or "")

    def test_unavailable_ocr_propagates_as_partial(self, tmp_path: Path):
        pdf_path = build_scanned_image_only_pdf(tmp_path / "scan.pdf")
        dead_ocr = _mock_ocr_engine(available=[])
        processor = _real_pipeline_processor(ocr_engine=dead_ocr)
        adapter = PDFProcessorAdapter(processor=processor)

        async def run():
            return await adapter.process(pdf_path)

        result = _run(run())
        # Scanned page with no OCR → partial (or failed if pipeline errors)
        assert result.metadata.status in (
            ProcessingStatus.PARTIAL,
            ProcessingStatus.FAILED,
        )
        if result.metadata.status == ProcessingStatus.PARTIAL:
            # Warnings / ocr_status must surface
            ocr_status = result.content.get("ocr_status")
            warnings = result.metadata.warnings or []
            assert (
                ocr_status in ("ocr_unavailable", "empty", "ocr_failed", "low_confidence")
                or any("ocr" in w.lower() for w in warnings)
                or result.content.get("page_coverage")
            )
            # Provenance still present even when OCR unavailable
            assert (
                result.content.get("page_coverage") is not None
                or result.content.get("pages") is not None
            )

    def test_low_confidence_ocr_is_partial(self):
        """Unit-level conversion: low_confidence ocr_status → PARTIAL."""
        fake = MagicMock()

        async def process_pdf(path, metadata=None):
            return {
                "status": "success",
                "document_id": "low-conf",
                "stages_completed": ["OCR"],
                "text_merge": {
                    "full_text": "blurry text",
                    "pages": [
                        {
                            "page": 1,
                            "text": "blurry text",
                            "spans": [
                                {
                                    "text": "blurry text",
                                    "page": 1,
                                    "origin": "rendered_ocr",
                                    "confidence": 0.2,
                                }
                            ],
                            "coverage": {
                                "page": 1,
                                "ocr_status": "low_confidence",
                                "ocr_confidence": 0.2,
                                "has_ocr_text": True,
                            },
                            "selected_origins": ["rendered_ocr"],
                        }
                    ],
                    "page_coverage": [
                        {
                            "page": 1,
                            "ocr_status": "low_confidence",
                            "ocr_confidence": 0.2,
                            "has_ocr_text": True,
                        }
                    ],
                    "overall_coverage": 0.1,
                    "overall_ocr_confidence": 0.2,
                    "ocr_status": "low_confidence",
                    "warnings": ["low_confidence"],
                    "provenance": {"page_count": 1},
                },
                "processing_metadata": {
                    "pipeline_version": "2.0",
                    "quality_scores": {
                        "ocr_status": "low_confidence",
                        "ocr_confidence": 0.2,
                        "overall_quality": 0.2,
                    },
                },
            }

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)

        async def run():
            return await adapter.process("/tmp/low.pdf")

        result = _run(run())
        assert result.metadata.status == ProcessingStatus.PARTIAL
        assert result.content["ocr_status"] == "low_confidence"
        assert result.content["text"] == "blurry text"
        assert result.content["pages"][0]["spans"][0]["origin"] == "rendered_ocr"


# ---------------------------------------------------------------------------
# Private content is not logged
# ---------------------------------------------------------------------------


class TestPrivateContentNotLogged:
    def test_adapter_logs_do_not_contain_confidential_body(self, tmp_path: Path):
        pdf_path = build_confidential_scanned_pdf(tmp_path / "private.pdf")
        processor = _real_pipeline_processor(
            ocr_engine=_mock_ocr_engine(text_by_default=CONFIDENTIAL_CANARY),
            canary_in_optimize=CONFIDENTIAL_CANARY,
        )
        adapter = PDFProcessorAdapter(processor=processor)

        stream, handler, prev = _capture_logging()
        try:

            async def run():
                return await adapter.process(pdf_path)

            result = _run(run())
        finally:
            log_output = _release_logging(stream, handler, prev)

        # Result may contain the text in content (that's the product);
        # ordinary logs must not.
        assert CONFIDENTIAL_CANARY not in log_output, (
            f"Confidential canary leaked into logs:\n{log_output[:2000]}"
        )
        # Path-only logging is fine
        assert result is not None

    def test_error_path_does_not_log_body_text(self, tmp_path: Path):
        fake = MagicMock()

        async def process_pdf(path, metadata=None):
            # Simulate failure after "seeing" private text without returning it
            raise RuntimeError("stage_failed")

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)

        stream, handler, prev = _capture_logging()
        try:

            async def run():
                return await adapter.process(tmp_path / "x.pdf")

            result = _run(run())
        finally:
            log_output = _release_logging(stream, handler, prev)

        assert result.metadata.status == ProcessingStatus.FAILED
        # Error log should mention type, not fabricate private body
        assert CONFIDENTIAL_CANARY not in log_output
        assert "RuntimeError" in log_output or "failed" in log_output.lower()


# ---------------------------------------------------------------------------
# Conversion unit tests (no heavy deps)
# ---------------------------------------------------------------------------


class TestConversionContract:
    def test_success_with_full_merge_maps_to_success(self):
        fake = MagicMock()

        async def process_pdf(path, metadata=None):
            return {
                "status": "success",
                "document_id": "doc-1",
                "ipld_cid": "bafy-test",
                "entities_count": 0,
                "relationships_count": 0,
                "extracted_entities": [],
                "extracted_relationships": [],
                "stages_completed": ["PDF validated", "OCR", "merge"],
                "pdf_info": {"page_count": 1, "file_size": 100},
                "text_merge": {
                    "full_text": NATIVE_CANARY,
                    "pages": [
                        {
                            "page": 1,
                            "text": NATIVE_CANARY,
                            "spans": [
                                {
                                    "text": NATIVE_CANARY,
                                    "page": 1,
                                    "origin": "native",
                                    "char_start": 0,
                                    "char_end": len(NATIVE_CANARY),
                                    "bbox": [72, 72, 400, 90],
                                }
                            ],
                            "coverage": {
                                "page": 1,
                                "has_native_text": True,
                                "has_ocr_text": False,
                                "ocr_status": "ocr_not_needed",
                                "origins_present": ["native"],
                            },
                            "selected_origins": ["native"],
                        }
                    ],
                    "page_coverage": [
                        {
                            "page": 1,
                            "has_native_text": True,
                            "ocr_status": "ocr_not_needed",
                        }
                    ],
                    "overall_coverage": 0.8,
                    "overall_ocr_confidence": None,
                    "ocr_status": "ocr_not_needed",
                    "warnings": [],
                    "provenance": {
                        "page_count": 1,
                        "pages_with_native": 1,
                        "pages_with_ocr": 0,
                    },
                },
                "page_coverage": [
                    {
                        "page": 1,
                        "has_native_text": True,
                        "ocr_status": "ocr_not_needed",
                    }
                ],
                "processing_metadata": {
                    "pipeline_version": "2.0",
                    "processing_time": 0.01,
                    "quality_scores": {
                        "ocr_status": "ocr_not_needed",
                        "overall_quality": 0.9,
                    },
                },
            }

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)

        async def run():
            return await adapter.process("/tmp/good.pdf")

        result = _run(run())
        assert result.metadata.status == ProcessingStatus.SUCCESS
        assert result.content["text"] == NATIVE_CANARY
        assert result.content["pages"][0]["spans"][0]["origin"] == "native"
        assert result.content["provenance"]["page_count"] == 1
        assert result.extra["document_id"] == "doc-1"
        assert result.is_successful()

    def test_refuses_explicit_placeholder_full_text(self):
        fake = MagicMock()
        source = "/tmp/placeholder.pdf"

        async def process_pdf(path, metadata=None):
            return {
                "status": "success",
                "text_merge": {
                    "full_text": f"PDF content from {path}",
                    "pages": [],
                    "page_coverage": [],
                    "overall_coverage": 0,
                    "overall_ocr_confidence": None,
                    "ocr_status": "ok",
                    "warnings": [],
                    "provenance": {},
                },
                "stages_completed": [],
                "processing_metadata": {},
            }

        fake.process_pdf = process_pdf
        adapter = PDFProcessorAdapter(processor=fake)

        async def run():
            return await adapter.process(source)

        result = _run(run())
        # Conversion raises → caught by process() → FAILED
        assert result.metadata.status == ProcessingStatus.FAILED
        assert result.has_errors()
        assert "placeholder" in (result.content.get("error") or "").lower() or any(
            "placeholder" in e.lower() for e in result.metadata.errors
        )
