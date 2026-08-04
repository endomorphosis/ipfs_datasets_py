"""Security: private PDF body must not reach disclosure sinks (PATLAW-004)."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock

import anyio
import pytest

from tests.fixtures.uspto.pdf.generators import (
    CONFIDENTIAL_CANARY,
    build_confidential_scanned_pdf,
    build_native_text_pdf,
)


def _capture_logging():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return stream, handler, previous_level


def _release_logging(stream, handler, previous_level):
    root = logging.getLogger()
    root.removeHandler(handler)
    root.setLevel(previous_level)
    return stream.getvalue()


def _processor_with_ocr(canary: str = CONFIDENTIAL_CANARY):
    from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import PDFProcessor

    mock_storage = MagicMock()
    mock_storage.store_json.side_effect = lambda *_a, **_k: "bafy-mock-cid"

    ocr = MagicMock()
    ocr.get_available_engines.return_value = ["mock"]

    def extract(image_data, strategy="quality_first", confidence_threshold=0.7):
        return {
            "text": canary,
            "confidence": 0.9,
            "engine": "mock",
            "status": "ok",
            "available_engines": ["mock"],
            "engines_attempted": ["mock"],
            "word_boxes": [],
        }

    ocr.extract_with_ocr.side_effect = extract
    ocr.extract_with_ocr_async = None

    async def _integrate(llm_document, **kwargs):
        kg = MagicMock()
        kg.entities = []
        kg.relationships = []
        kg.metadata = {}
        return kg

    async def _optimize(decomposed_content, metadata=None):
        llm_document = MagicMock()
        llm_document.document_id = "private-doc"
        llm_document.chunks = [{"text": canary}]
        llm_document.summary = canary
        llm_document.key_entities = []
        llm_document.model_dump = lambda: {
            "document_id": "private-doc",
            "summary": canary,
            "chunks": [{"text": canary}],
        }
        return {
            "llm_document": llm_document,
            "chunks": llm_document.chunks,
            "summary": canary,
            "key_entities": [],
        }

    integrator = MagicMock()
    integrator.integrate_document = _integrate
    optimizer = MagicMock()
    optimizer.optimize_for_llm = _optimize

    return PDFProcessor(
        enable_monitoring=False,
        enable_audit=False,
        mock_dict={
            "storage": mock_storage,
            "ocr_engine": ocr,
            "integrator": integrator,
            "optimizer": optimizer,
            "audit_logger": None,
            "monitoring": None,
        },
    )


class TestPrivatePdfNonDisclosure:
    def test_pipeline_does_not_write_debug_content_files_to_cwd(
        self, tmp_path: Path, monkeypatch
    ):
        """DEBUG level must not dump document body into CWD debug JSON files."""
        monkeypatch.chdir(tmp_path)
        pdf_path = build_confidential_scanned_pdf(tmp_path / "confidential.pdf")
        processor = _processor_with_ocr()
        # Force logger to DEBUG — historical bug wrote pdf_processing_results_*.json
        processor.logger.setLevel(logging.DEBUG)

        before = set(tmp_path.iterdir())

        async def run():
            # Exercise stages that previously dumped content
            decomposed = await processor._decompose_pdf(pdf_path)
            ocr = await processor._process_ocr(decomposed)
            merge = processor._merge_text_layers(decomposed, ocr)
            return merge

        anyio.run(run)

        after = set(tmp_path.iterdir())
        new_files = [p for p in (after - before) if p.is_file()]
        debug_dumps = [
            p
            for p in new_files
            if p.name.startswith("pdf_processing_results_") and p.suffix == ".json"
        ]
        assert debug_dumps == [], f"Unexpected debug dumps: {debug_dumps}"

        # No working-directory file should contain the confidential canary
        for p in tmp_path.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix == ".pdf":
                continue  # fixture itself is allowed
            try:
                data = p.read_bytes()
            except Exception:
                continue
            assert CONFIDENTIAL_CANARY.encode() not in data, (
                f"Confidential canary found in working-directory file {p}"
            )

    def test_stdout_and_logs_omit_document_body(self, tmp_path: Path, capsys):
        pdf_path = build_confidential_scanned_pdf(tmp_path / "private.pdf")
        processor = _processor_with_ocr()
        log_stream, handler, prev = _capture_logging()
        try:
            async def run():
                decomposed = await processor._decompose_pdf(pdf_path)
                ocr = await processor._process_ocr(decomposed)
                merge = processor._merge_text_layers(decomposed, ocr)
                scores = processor._get_quality_scores(
                    {"extracted_entities": []}, ocr, text_merge_result=merge
                )
                # Validate path logging does not echo body
                info = await processor._validate_and_analyze_pdf(pdf_path)
                return merge, scores, info

            merge, scores, info = anyio.run(run)
        finally:
            log_text = _release_logging(log_stream, handler, prev)

        captured = capsys.readouterr()
        stdout = captured.out or ""
        stderr = captured.err or ""

        assert CONFIDENTIAL_CANARY not in stdout
        assert CONFIDENTIAL_CANARY not in stderr
        assert CONFIDENTIAL_CANARY not in log_text

        # Merge result may hold text for callers — that is in-process data, not a sink.
        # Ensure quality scores / pdf_info do not embed body.
        assert CONFIDENTIAL_CANARY not in str(scores)
        assert CONFIDENTIAL_CANARY not in str(info)

    def test_validation_messages_do_not_print_full_pdf_info(
        self, tmp_path: Path, capsys
    ):
        """Historical bug: print(pdf_info) on validation success/failure."""
        pdf_path = build_native_text_pdf(
            tmp_path / "native.pdf", text=CONFIDENTIAL_CANARY
        )
        processor = _processor_with_ocr()
        log_stream, handler, prev = _capture_logging()
        try:
            anyio.run(processor._validate_and_analyze_pdf, pdf_path)
        finally:
            log_text = _release_logging(log_stream, handler, prev)

        captured = capsys.readouterr()
        combined = (captured.out or "") + (captured.err or "") + log_text
        assert CONFIDENTIAL_CANARY not in combined
        # Must not pprint full structure with content
        assert "decomposed_content:" not in combined
        assert "ocr_results:" not in combined

    def test_ocr_engine_unavailable_status_not_logged_as_document_text(
        self, tmp_path: Path, capsys
    ):
        from ipfs_datasets_py.processors.specialized.pdf.ocr_engine import MultiEngineOCR

        MultiEngineOCR.reset_instance()
        # Force empty engine registry
        ocr = MultiEngineOCR.__new__(MultiEngineOCR)
        ocr.engines = {}
        ocr.unavailable_engines = {"tesseract": "not_available"}
        ocr.logger = logging.getLogger("test.ocr")
        ocr._multi_ocr_initialized = True

        # Minimal PNG
        from PIL import Image
        import io as _io

        buf = _io.BytesIO()
        Image.new("RGB", (16, 16), "white").save(buf, format="PNG")
        result = ocr.extract_with_ocr(buf.getvalue())
        assert result["status"] == "ocr_unavailable"
        assert result["confidence"] is None

        captured = capsys.readouterr()
        assert CONFIDENTIAL_CANARY not in (captured.out or "")
