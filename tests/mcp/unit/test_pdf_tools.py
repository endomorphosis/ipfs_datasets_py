"""
Phase B2: Unit tests for pdf_tools tool category.

Tests cover:
- pdf_query_corpus: basic corpus query
- pdf_ingest_to_graphrag: ingest pipeline (no real PDF — expects graceful error)
- pdf_optimize_for_llm: LLM optimisation wrapper
- pdf_batch_process: batch processing wrapper
"""
from __future__ import annotations

import pytest


class TestPdfQueryCorpus:
    """Tests for pdf_query_corpus tool function."""

    @pytest.mark.asyncio
    async def test_query_corpus_returns_dict(self):
        """
        GIVEN a text query
        WHEN pdf_query_corpus is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus import (
            pdf_query_corpus,
        )
        result = await pdf_query_corpus(query="machine learning applications")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_query_corpus_empty_query(self):
        """
        GIVEN an empty query
        WHEN pdf_query_corpus is called
        THEN result must still be a dict (possibly error dict, not raise).
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus import (
            pdf_query_corpus,
        )
        result = await pdf_query_corpus(query="")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_query_corpus_returns_content_key(self):
        """
        GIVEN a valid query
        WHEN pdf_query_corpus is called
        THEN result must contain 'content' key.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus import (
            pdf_query_corpus,
        )
        result = await pdf_query_corpus(query="neural networks")
        assert "content" in result


class TestPdfIngestToGraphrag:
    """Tests for pdf_ingest_to_graphrag tool function."""

    @pytest.mark.asyncio
    async def test_ingest_missing_file_returns_error_dict(self):
        """
        GIVEN a path to a non-existent PDF
        WHEN pdf_ingest_to_graphrag is called
        THEN result must be a dict containing 'error' or 'success'=False.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import (
            pdf_ingest_to_graphrag,
        )
        result = await pdf_ingest_to_graphrag(pdf_source="/tmp/nonexistent.pdf")
        assert isinstance(result, dict)
        # Must not raise; must report the problem
        has_error = (
            "error" in result
            or result.get("success") is False
            or "message" in result
        )
        assert has_error

    @pytest.mark.asyncio
    async def test_ingest_missing_field_in_dict_source(self):
        """
        GIVEN a dict pdf_source with missing pdf_path
        WHEN pdf_ingest_to_graphrag is called
        THEN result must be a dict indicating validation error.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import (
            pdf_ingest_to_graphrag,
        )
        result = await pdf_ingest_to_graphrag(pdf_source={"title": "no path here"})
        assert isinstance(result, dict)
        has_error = (
            "error" in result
            or result.get("success") is False
            or "message" in result
        )
        assert has_error


class TestPdfOptimizeForLlm:
    """Tests for pdf_optimize_for_llm tool function."""

    @pytest.mark.asyncio
    async def test_optimize_returns_dict(self):
        """
        GIVEN a valid pdf_source parameter
        WHEN pdf_optimize_for_llm is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_optimize_for_llm import (
            pdf_optimize_for_llm,
        )
        result = await pdf_optimize_for_llm(pdf_source="/tmp/nonexistent.pdf")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_optimize_invalid_target_llm(self):
        """
        GIVEN an invalid target_llm value
        WHEN pdf_optimize_for_llm is called
        THEN result must be a dict containing 'error' key.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_optimize_for_llm import (
            pdf_optimize_for_llm,
        )
        result = await pdf_optimize_for_llm(
            pdf_source="/tmp/test.pdf", target_llm="invalid_model"
        )
        assert isinstance(result, dict)
        has_error = (
            "error" in result
            or result.get("success") is False
            or result.get("status") == "error"
        )
        assert has_error


class TestPdfBatchProcess:
    """Tests for pdf_batch_process tool function."""

    @pytest.mark.asyncio
    async def test_batch_empty_list_returns_dict(self):
        """
        GIVEN an empty pdf_sources list
        WHEN pdf_batch_process is called
        THEN result must be a dict (may be error or success).
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process import (
            pdf_batch_process,
        )
        result = await pdf_batch_process(pdf_sources=[])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_batch_nonexistent_file_returns_dict(self):
        """
        GIVEN a list with one non-existent PDF path
        WHEN pdf_batch_process is called
        THEN result must be a dict (graceful error handling).
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process import (
            pdf_batch_process,
        )
        result = await pdf_batch_process(pdf_sources=["/tmp/ghost.pdf"])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_batch_invalid_batch_size(self):
        """
        GIVEN batch_size=0 (invalid)
        WHEN pdf_batch_process is called
        THEN result must be a dict containing 'error' key.
        """
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process import (
            pdf_batch_process,
        )
        result = await pdf_batch_process(pdf_sources=["/tmp/a.pdf"], batch_size=0)
        assert isinstance(result, dict)
        has_error = (
            "error" in result
            or result.get("success") is False
            or result.get("status") == "error"
        )
        assert has_error
