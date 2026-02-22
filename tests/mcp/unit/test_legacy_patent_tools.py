"""
Session 38 — tests for legacy_mcp_tools/patent_dataset_mcp_tools.py.

The module is a DEPRECATED legacy tool that raises DeprecationWarning on import.
All 5 async functions try to import and use patent_engine.  We mock that engine
to prevent real USPTO network calls while still exercising all code paths.
"""
import asyncio
import sys
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Build a minimal mock of ipfs_datasets_py.processors.legal_scrapers.patent_engine
# so import-guarded try/except paths execute the happy path.
# ---------------------------------------------------------------------------
def _build_patent_engine_stub():
    from dataclasses import dataclass, field
    from typing import Any, List, Optional

    @dataclass
    class PatentSearchCriteria:
        keywords: Optional[List[str]] = None
        inventor_name: Optional[str] = None
        assignee_name: Optional[str] = None
        patent_number: Optional[str] = None
        date_from: Optional[str] = None
        date_to: Optional[str] = None
        cpc_classification: Optional[List[str]] = None
        limit: int = 100
        offset: int = 0

    @dataclass
    class Patent:
        title: str = "Test Patent"
        patent_number: str = "US123"
        abstract: str = "Abstract"
        inventors: List[str] = field(default_factory=list)
        assignees: List[str] = field(default_factory=list)

    class USPTOPatentScraper:
        def __init__(self, rate_limit_delay=1.0):
            self.rate_limit_delay = rate_limit_delay

    class PatentDatasetBuilder:
        def __init__(self, scraper):
            self.scraper = scraper

        async def build_dataset_async(self, criteria, output_format="json", output_path=None):
            return {"status": "success", "patents": [], "metadata": {}}

    def search_patents_by_keyword(keywords, limit=100, rate_limit_delay=1.0):
        return [Patent()]

    def search_patents_by_inventor(inventor_name, limit=100, rate_limit_delay=1.0):
        return [Patent()]

    def search_patents_by_assignee(assignee_name, limit=100, rate_limit_delay=1.0):
        return [Patent()]

    stub = MagicMock()
    stub.PatentSearchCriteria = PatentSearchCriteria
    stub.USPTOPatentScraper = USPTOPatentScraper
    stub.PatentDatasetBuilder = PatentDatasetBuilder
    stub.search_patents_by_keyword = search_patents_by_keyword
    stub.search_patents_by_inventor = search_patents_by_inventor
    stub.search_patents_by_assignee = search_patents_by_assignee
    stub.Patent = Patent
    return stub


_PATENT_ENGINE_STUB = _build_patent_engine_stub()

# Inject the stub into sys.modules so import statements inside patent_dataset_mcp_tools
# succeed without real patents being fetched.
sys.modules.setdefault(
    "ipfs_datasets_py.processors.legal_scrapers.patent_engine",
    _PATENT_ENGINE_STUB,
)

# anyio.to_thread.run_sync must also be stubbed to avoid blocking the asyncio loop.
# We patch it globally before importing the module under test.
import anyio.to_thread as _anyio_thread

_orig_run_sync = _anyio_thread.run_sync


async def _fake_run_sync(fn, *args, **kwargs):
    return fn(*args)


_anyio_thread.run_sync = _fake_run_sync

# Now import the module under test (DeprecationWarning is suppressed here).
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools import patent_dataset_mcp_tools as _mod


class TestLegacyPatentDeprecationWarning(unittest.TestCase):
    """The module emits DeprecationWarning at import time."""

    def test_deprecation_warning_emitted_on_reload(self):
        import importlib
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.reload(_mod)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertGreater(len(dep_warnings), 0)

    def test_deprecation_message_mentions_legal_dataset_tools(self):
        import importlib
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.reload(_mod)
            msgs = " ".join(str(x.message) for x in w if issubclass(x.category, DeprecationWarning))
            self.assertIn("legal_dataset_tools", msgs)


class TestScrapeUsptoPatents(unittest.TestCase):

    def test_returns_dict(self):
        result = _run(_mod.scrape_uspto_patents())
        self.assertIsInstance(result, dict)

    def test_has_status_key(self):
        result = _run(_mod.scrape_uspto_patents())
        self.assertIn("status", result)

    def test_has_patents_key(self):
        result = _run(_mod.scrape_uspto_patents())
        self.assertIn("patents", result)

    def test_keywords_param_accepted(self):
        result = _run(_mod.scrape_uspto_patents(keywords=["machine learning"]))
        self.assertIsInstance(result, dict)

    def test_limit_param_accepted(self):
        result = _run(_mod.scrape_uspto_patents(limit=10))
        self.assertIsInstance(result, dict)


class TestSearchPatentsByKeyword(unittest.TestCase):

    def test_returns_dict(self):
        result = _run(_mod.search_patents_by_keyword(keywords=["AI"]))
        self.assertIsInstance(result, dict)

    def test_has_status_key(self):
        result = _run(_mod.search_patents_by_keyword(keywords=["blockchain"]))
        self.assertIn("status", result)

    def test_has_patents_key(self):
        result = _run(_mod.search_patents_by_keyword(keywords=["data"]))
        self.assertIn("patents", result)


class TestSearchPatentsByInventor(unittest.TestCase):

    def test_returns_dict(self):
        result = _run(_mod.search_patents_by_inventor(inventor_name="Tesla"))
        self.assertIsInstance(result, dict)

    def test_has_status_key(self):
        result = _run(_mod.search_patents_by_inventor(inventor_name="Tesla"))
        self.assertIn("status", result)


class TestSearchPatentsByAssignee(unittest.TestCase):

    def test_returns_dict(self):
        result = _run(_mod.search_patents_by_assignee(assignee_name="Google"))
        self.assertIsInstance(result, dict)

    def test_has_status_key(self):
        result = _run(_mod.search_patents_by_assignee(assignee_name="Apple"))
        self.assertIn("status", result)


class TestBuildPatentDataset(unittest.TestCase):

    def test_returns_dict(self):
        result = _run(_mod.build_patent_dataset())
        self.assertIsInstance(result, dict)

    def test_has_status_key(self):
        result = _run(_mod.build_patent_dataset())
        self.assertIn("status", result)

    def test_search_criteria_param_accepted(self):
        result = _run(_mod.build_patent_dataset(
            search_criteria={"keywords": ["neural network"], "limit": 5}
        ))
        self.assertIsInstance(result, dict)

    def test_graphrag_format_false_accepted(self):
        result = _run(_mod.build_patent_dataset(graphrag_format=False))
        self.assertIsInstance(result, dict)

    def test_graphrag_format_true_adds_metadata(self):
        result = _run(_mod.build_patent_dataset(graphrag_format=True))
        # When engine returns success, graphrag_metadata should be added
        # (engine stub returns {"status": "success", ...})
        self.assertIn("graphrag_metadata", result)


class TestPatentToolsList(unittest.TestCase):

    def test_tools_list_is_non_empty(self):
        self.assertGreater(len(_mod.PATENT_DATASET_MCP_TOOLS), 0)

    def test_tools_list_contains_callables(self):
        for fn in _mod.PATENT_DATASET_MCP_TOOLS:
            self.assertTrue(callable(fn), f"{fn} should be callable")

    def test_all_five_tools_listed(self):
        self.assertEqual(len(_mod.PATENT_DATASET_MCP_TOOLS), 5)


if __name__ == "__main__":
    unittest.main()
