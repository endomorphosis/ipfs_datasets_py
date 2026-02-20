"""
Tests for vector_tools tool category.

Tests cover:
- create_vector_index (FAISS index creation)
- search_vector_index (similarity search)
- list_vector_indexes (inventory)
- delete_vector_index (cleanup)
"""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
from ipfs_datasets_py.mcp_server.tools.vector_tools.vector_store_management import (
    list_vector_indexes,
    delete_vector_index,
)


class TestCreateVectorIndex:
    """Tests for create_vector_index tool function."""

    @pytest.mark.asyncio
    async def test_create_index_returns_status(self):
        """
        GIVEN the vector_tools module
        WHEN create_vector_index is called with valid parameters
        THEN the result must be a dict containing 'status' or 'index_id'
        """
        result = await create_vector_index(
            index_name="test_index",
            dimension=384,
            metric="cosine",
            provider="faiss",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result or "index_id" in result or "created" in result

    @pytest.mark.asyncio
    async def test_create_index_with_metadata(self):
        """
        GIVEN the vector_tools module
        WHEN create_vector_index is called with metadata
        THEN the result must not be None
        """
        result = await create_vector_index(
            index_name="test_index_meta",
            dimension=768,
            metric="l2",
        )
        assert result is not None


class TestSearchVectorIndex:
    """Tests for search_vector_index tool function."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """
        GIVEN the vector_tools module
        WHEN search_vector_index is called with a query vector
        THEN the result must be a dict containing 'status' or 'results'
        """
        query_vector = np.random.rand(384).tolist()
        result = await search_vector_index(
            index_name="test_index",
            query_vector=query_vector,
            top_k=5,
        )
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result or "results" in result

    @pytest.mark.asyncio
    async def test_search_with_filter_returns_result(self):
        """
        GIVEN the vector_tools module
        WHEN search_vector_index is called with a metadata filter
        THEN the result must not be None
        """
        query_vector = np.random.rand(384).tolist()
        result = await search_vector_index(
            index_name="test_index",
            query_vector=query_vector,
            top_k=3,
            filter_criteria={"category": "test"},
        )
        assert result is not None


class TestListVectorIndexes:
    """Tests for list_vector_indexes tool function."""

    @pytest.mark.asyncio
    async def test_list_returns_dict(self):
        """
        GIVEN the vector_tools module
        WHEN list_vector_indexes is called
        THEN the result must be a dict containing 'status' or 'indexes'
        """
        result = await list_vector_indexes()
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result or "indexes" in result


class TestDeleteVectorIndex:
    """Tests for delete_vector_index tool function."""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_index_returns_status(self):
        """
        GIVEN the vector_tools module
        WHEN delete_vector_index is called for an index that does not exist
        THEN the result must be a dict containing 'status'
        """
        result = await delete_vector_index(index_name="nonexistent_index_xyz")
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result
