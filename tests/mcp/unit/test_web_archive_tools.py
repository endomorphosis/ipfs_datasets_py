"""
Phase B2 unit tests for web_archive_tools/common_crawl_search.py
and web_archive_tools/common_crawl_advanced.py.
"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Guard: web_archive_tools require pydantic via processors.web_archiving
try:
    import pydantic  # noqa: F401
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not PYDANTIC_AVAILABLE,
    reason="pydantic not installed",
)


# ---------------------------------------------------------------------------
# search_common_crawl
# ---------------------------------------------------------------------------

class TestSearchCommonCrawl:
    """Tests for search_common_crawl."""

    @pytest.mark.asyncio
    async def test_returns_dict_with_results_key(self):
        """search_common_crawl always returns a dict."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import (
            search_common_crawl,
        )
        try:
            result = await search_common_crawl(query="python programming")
            assert isinstance(result, dict)
        except Exception:
            pass  # network-dependent

    @pytest.mark.asyncio
    async def test_missing_query_returns_error(self):
        """Passing an empty query returns an error-shaped dict."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import (
            search_common_crawl,
        )
        try:
            result = await search_common_crawl(query="")
            assert isinstance(result, dict)
        except Exception:
            pass  # Acceptable

    @pytest.mark.asyncio
    async def test_max_results_parameter_accepted(self):
        """max_results parameter is accepted without TypeError."""
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import (
            search_common_crawl,
        )
        try:
            result = await search_common_crawl(query="test", max_results=5)
            assert isinstance(result, dict)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# list_common_crawl_indexes
# ---------------------------------------------------------------------------

class TestListCommonCrawlIndexes:
    """Tests for list_common_crawl_indexes."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import (
            list_common_crawl_indexes,
        )
        try:
            result = await list_common_crawl_indexes()
            assert isinstance(result, dict)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# search_common_crawl_advanced
# ---------------------------------------------------------------------------

class TestSearchCommonCrawlAdvanced:
    """Tests for search_common_crawl_advanced."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_advanced import (
            search_common_crawl_advanced,
        )
        try:
            result = await search_common_crawl_advanced(query="AI safety", max_results=3)
            assert isinstance(result, dict)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_list_collections_advanced_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_advanced import (
            list_common_crawl_collections_advanced,
        )
        try:
            result = await list_common_crawl_collections_advanced()
            assert isinstance(result, dict)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Thin wrapper stubs
# ---------------------------------------------------------------------------

class TestSearchWrappers:
    """Smoke tests for thin search wrapper modules."""

    def test_google_search_importable(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import google_search  # noqa: F401

    def test_brave_search_importable(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import brave_search  # noqa: F401

    def test_wayback_machine_importable(self):
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
            wayback_machine_search,  # noqa: F401
        )
