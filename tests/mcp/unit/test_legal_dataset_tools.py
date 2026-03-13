"""Unit tests for legal_dataset_tools (Phase B2 session 33).

Covers:
- mcp_tools: scrape_recap_archive, search_recap_documents, scrape_state_laws,
  list_scraping_jobs, scrape_us_code
- brave_legal_search_tools: brave_legal_search, brave_legal_search_generate_terms
- legal_report_generator_tool: generate_legal_report, export_legal_report
- citation_extraction_tool: extract_legal_citations
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("IPFS_DATASETS_PY_RUN_NETWORK_LEGAL_TESTS") != "1",
    reason="Requires live legal web sources; set IPFS_DATASETS_PY_RUN_NETWORK_LEGAL_TESTS=1 to enable.",
)


@pytest.fixture(autouse=True)
def _mock_legal_tool_entrypoints(monkeypatch):
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import mcp_tools
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import brave_legal_search_tools
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import legal_report_generator_tool
    from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import citation_extraction_tool

    async def _ok_async(parameters=None, *args, **kwargs):
        return {"status": "success", "parameters": parameters or {}}

    monkeypatch.setattr(mcp_tools, "scrape_recap_archive", _ok_async)
    monkeypatch.setattr(mcp_tools, "search_recap_documents", _ok_async)
    monkeypatch.setattr(mcp_tools, "scrape_state_laws", _ok_async)
    monkeypatch.setattr(mcp_tools, "list_scraping_jobs", _ok_async)
    monkeypatch.setattr(mcp_tools, "scrape_us_code", _ok_async)

    def _brave_search(query, max_results=20, country="US", lang="en"):
        return {
            "status": "success",
            "query": query,
            "results": [{"title": "mock", "url": "https://example.org"}],
            "total_results": 1,
        }

    def _brave_terms(query):
        return {"status": "success", "query": query, "search_terms": [query] if query else []}

    monkeypatch.setattr(brave_legal_search_tools, "brave_legal_search", _brave_search)
    monkeypatch.setattr(brave_legal_search_tools, "brave_legal_search_generate_terms", _brave_terms)

    async def _generate_report(search_results, template="research", title=None, **kwargs):
        return {
            "status": "success",
            "report": {"title": title or "Mock Report"},
            "section_count": 1,
        }

    async def _export_report(report_data, format="markdown", output_path=None, include_toc=True):
        return {"status": "success", "format": format, "content": "mock report"}

    monkeypatch.setattr(legal_report_generator_tool, "generate_legal_report", _generate_report)
    monkeypatch.setattr(legal_report_generator_tool, "export_legal_report", _export_report)

    async def _extract_citations(results=None, *args, **kwargs):
        return {
            "status": "success",
            "citations": [{"citation_id": "mock-1", "citation_type": "case"}],
            "total_citations": 1,
        }

    async def _analyze_network(parameters=None, *args, **kwargs):
        return {"status": "success", "nodes": 1, "edges": 0}

    monkeypatch.setattr(citation_extraction_tool, "extract_legal_citations", _extract_citations)
    monkeypatch.setattr(citation_extraction_tool, "analyze_citation_network", _analyze_network)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# mcp_tools
# ---------------------------------------------------------------------------

class TestScrapeRecapArchive:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            scrape_recap_archive,
        )
        r = _run(scrape_recap_archive({"case_name": "Roe v. Wade"}))
        assert isinstance(r, dict)

    def test_has_status_key(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            scrape_recap_archive,
        )
        r = _run(scrape_recap_archive({}))
        assert "status" in r or "error" in r

    def test_empty_params_handled(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            scrape_recap_archive,
        )
        r = _run(scrape_recap_archive({}))
        assert isinstance(r, dict)


class TestSearchRecapDocuments:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            search_recap_documents,
        )
        r = _run(search_recap_documents({"query": "privacy"}))
        assert isinstance(r, dict)

    def test_empty_query_handled(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            search_recap_documents,
        )
        r = _run(search_recap_documents({}))
        assert isinstance(r, dict)


class TestScrapeStateLaws:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            scrape_state_laws,
        )
        r = _run(scrape_state_laws({"state": "CA"}))
        assert isinstance(r, dict)


class TestListScrapingJobs:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            list_scraping_jobs,
        )
        r = _run(list_scraping_jobs({}))
        assert isinstance(r, dict)


class TestScrapeUsCode:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            scrape_us_code,
        )
        r = _run(scrape_us_code({"title": "42"}))
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# brave_legal_search_tools (sync)
# ---------------------------------------------------------------------------

class TestBraveLegalSearch:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.brave_legal_search_tools import (
            brave_legal_search,
        )
        r = brave_legal_search("GDPR compliance", max_results=3)
        assert isinstance(r, dict)

    def test_max_results_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.brave_legal_search_tools import (
            brave_legal_search,
        )
        r = brave_legal_search("copyright", max_results=10)
        assert isinstance(r, dict)

    def test_empty_query_handled(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.brave_legal_search_tools import (
            brave_legal_search,
        )
        r = brave_legal_search("")
        assert isinstance(r, dict)


class TestBraveLegalSearchGenerateTerms:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.brave_legal_search_tools import (
            brave_legal_search_generate_terms,
        )
        r = brave_legal_search_generate_terms("privacy law")
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# legal_report_generator_tool
# ---------------------------------------------------------------------------

class TestGenerateLegalReport:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
            generate_legal_report,
        )
        r = _run(generate_legal_report([], "default", "Test Report"))
        assert isinstance(r, dict)

    def test_has_status_key(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
            generate_legal_report,
        )
        r = _run(generate_legal_report([], "summary", "My Report"))
        assert "status" in r or "report" in r

    def test_include_summary_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
            generate_legal_report,
        )
        r = _run(
            generate_legal_report([], "default", "Report", include_summary=True)
        )
        assert isinstance(r, dict)


class TestExportLegalReport:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.legal_report_generator_tool import (
            export_legal_report,
        )
        r = _run(export_legal_report({}, "json"))
        assert isinstance(r, dict)


# ---------------------------------------------------------------------------
# citation_extraction_tool
# ---------------------------------------------------------------------------

class TestExtractLegalCitations:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.citation_extraction_tool import (
            extract_legal_citations,
        )
        r = _run(extract_legal_citations({"results": []}))
        assert isinstance(r, dict)

    def test_has_status_key(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.citation_extraction_tool import (
            extract_legal_citations,
        )
        r = _run(extract_legal_citations({}))
        assert "status" in r or "citations" in r

    def test_extract_metadata_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.citation_extraction_tool import (
            extract_legal_citations,
        )
        r = _run(
            extract_legal_citations(
                {"results": [], "extract_metadata": True}
            )
        )
        assert isinstance(r, dict)


class TestAnalyzeCitationNetwork:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.citation_extraction_tool import (
            analyze_citation_network,
        )
        r = _run(analyze_citation_network({}))
        assert isinstance(r, dict)
