"""
Phase B2: Unit tests for search_tools tool category.

Tests cover:
- semantic_search: keyword/embedding search with mock service
- similarity_search: vector similarity lookup
- faceted_search: filtered/faceted search
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    """Tests for semantic_search tool function."""

    @pytest.mark.asyncio
    async def test_semantic_search_returns_dict(self):
        """
        GIVEN a valid query string
        WHEN semantic_search is called
        THEN result must be a dict with 'results' key.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            semantic_search,
        )
        result = await semantic_search("machine learning")
        assert isinstance(result, dict)
        assert "results" in result

    @pytest.mark.asyncio
    async def test_semantic_search_respects_top_k(self):
        """
        GIVEN a query with top_k=2
        WHEN semantic_search is called
        THEN the results list must contain at most 2 items.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            semantic_search,
        )
        result = await semantic_search("neural networks", top_k=2)
        assert isinstance(result.get("results"), list)
        assert len(result["results"]) <= 2

    @pytest.mark.asyncio
    async def test_semantic_search_result_items_have_id(self):
        """
        GIVEN a valid query
        WHEN semantic_search is called
        THEN each result item must have a non-empty 'id' field.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            semantic_search,
        )
        result = await semantic_search("deep learning", top_k=3)
        for item in result.get("results", []):
            assert "id" in item
            assert item["id"]  # non-empty

    @pytest.mark.asyncio
    async def test_semantic_search_empty_query_returns_dict(self):
        """
        GIVEN an empty query string
        WHEN semantic_search is called
        THEN result must be a dict (possibly error dict, but not raise).
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            semantic_search,
        )
        result = await semantic_search("")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# similarity_search
# ---------------------------------------------------------------------------


class TestSimilaritySearch:
    """Tests for similarity_search tool function."""

    @pytest.mark.asyncio
    async def test_similarity_search_returns_dict(self):
        """
        GIVEN a reference embedding vector
        WHEN similarity_search is called
        THEN result must be a dict with 'results' key.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            similarity_search,
        )
        result = await similarity_search([0.1, 0.2, 0.3], top_k=3)
        assert isinstance(result, dict)
        assert "results" in result

    @pytest.mark.asyncio
    async def test_similarity_search_result_items_have_id(self):
        """
        GIVEN a valid embedding
        WHEN similarity_search is called
        THEN result items must have a non-empty 'id' field.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            similarity_search,
        )
        result = await similarity_search([0.5, 0.5], top_k=2)
        for item in result.get("results", []):
            assert "id" in item

    @pytest.mark.asyncio
    async def test_similarity_search_dimension_recorded(self):
        """
        GIVEN a 4-dimensional embedding
        WHEN similarity_search is called
        THEN the result should record embedding_dimension=4.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            similarity_search,
        )
        result = await similarity_search([0.1, 0.2, 0.3, 0.4], top_k=2)
        assert result.get("embedding_dimension") == 4


# ---------------------------------------------------------------------------
# faceted_search
# ---------------------------------------------------------------------------


class TestFacetedSearch:
    """Tests for faceted_search tool function."""

    @pytest.mark.asyncio
    async def test_faceted_search_returns_dict(self):
        """
        GIVEN a query and facets
        WHEN faceted_search is called
        THEN result must be a dict with 'results' key.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            faceted_search,
        )
        result = await faceted_search("climate change", facets={"topic": "environment"})
        assert isinstance(result, dict)
        assert "results" in result

    @pytest.mark.asyncio
    async def test_faceted_search_contains_facet_counts(self):
        """
        GIVEN a query with facets
        WHEN faceted_search is called
        THEN result should contain 'facet_counts' key.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            faceted_search,
        )
        result = await faceted_search("energy", facets={"category": "physics"})
        assert "facet_counts" in result

    @pytest.mark.asyncio
    async def test_faceted_search_no_facets(self):
        """
        GIVEN a query without facets
        WHEN faceted_search is called
        THEN result must still be a dict with 'results' key.
        """
        from ipfs_datasets_py.mcp_server.tools.search_tools.search_tools import (
            faceted_search,
        )
        result = await faceted_search("quantum physics")
        assert isinstance(result, dict)
        assert "results" in result
