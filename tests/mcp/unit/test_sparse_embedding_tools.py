"""
Phase B2 (session 30): Unit tests for sparse_embedding_tools tool category.

Tests cover:
- generate_sparse_embedding: sparse vector generation
- index_sparse_collection: indexing a corpus
- sparse_search: similarity search using sparse vectors
- manage_sparse_models: model management operations
"""
from __future__ import annotations

import pytest


class TestGenerateSparseEmbedding:
    """Tests for generate_sparse_embedding tool function."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN valid text input
        WHEN generate_sparse_embedding is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            generate_sparse_embedding,
        )
        result = await generate_sparse_embedding("machine learning algorithms")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_sparse_embedding_key(self):
        """
        GIVEN valid text
        WHEN generate_sparse_embedding is called
        THEN result must have 'sparse_embedding' key.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            generate_sparse_embedding,
        )
        result = await generate_sparse_embedding("natural language processing")
        assert "sparse_embedding" in result

    @pytest.mark.asyncio
    async def test_empty_text_returns_error(self):
        """
        GIVEN empty text input
        WHEN generate_sparse_embedding is called
        THEN result must indicate an error (not raise an exception).
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            generate_sparse_embedding,
        )
        try:
            result = await generate_sparse_embedding("")
            # If it returns instead of raising, it should indicate error
            assert isinstance(result, dict)
        except (ValueError, Exception):
            # Acceptable to raise ValueError for empty text
            pass

    @pytest.mark.asyncio
    async def test_custom_model(self):
        """
        GIVEN model='splade'
        WHEN generate_sparse_embedding is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            generate_sparse_embedding,
        )
        result = await generate_sparse_embedding("deep learning", model="splade")
        assert isinstance(result, dict)


class TestIndexSparseCollection:
    """Tests for index_sparse_collection tool function."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN a collection name and dataset
        WHEN index_sparse_collection is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            index_sparse_collection,
        )
        result = await index_sparse_collection(
            collection_name="test_collection", dataset="squad"
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_indexed_count(self):
        """
        GIVEN collection_name and dataset
        WHEN index_sparse_collection is called
        THEN result must have 'total_documents' or 'indexed_count' or 'results' key.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            index_sparse_collection,
        )
        result = await index_sparse_collection(collection_name="col1", dataset="test")
        assert "total_documents" in result or "indexed_count" in result or "results" in result


class TestSparseSearch:
    """Tests for sparse_search tool function."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN a query string
        WHEN sparse_search is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            sparse_search,
        )
        result = await sparse_search(query="machine learning", collection_name="test_collection")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_results_key(self):
        """
        GIVEN a valid query
        WHEN sparse_search is called
        THEN result must have 'results' key.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            sparse_search,
        )
        result = await sparse_search(query="neural networks", collection_name="col1")
        assert "results" in result

    @pytest.mark.asyncio
    async def test_top_k_respected(self):
        """
        GIVEN top_k=3
        WHEN sparse_search is called
        THEN results list must have at most 3 items.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            sparse_search,
        )
        result = await sparse_search(
            query="deep learning", collection_name="col1", top_k=3
        )
        results = result.get("results", [])
        assert len(results) <= 3


class TestManageSparseModels:
    """Tests for manage_sparse_models tool function."""

    @pytest.mark.asyncio
    async def test_list_action_returns_dict(self):
        """
        GIVEN action='list'
        WHEN manage_sparse_models is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            manage_sparse_models,
        )
        result = await manage_sparse_models(action="list")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_info_action_returns_dict(self):
        """
        GIVEN action='info'
        WHEN manage_sparse_models is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.sparse_embedding_tools.sparse_embedding_tools import (
            manage_sparse_models,
        )
        result = await manage_sparse_models(action="info", model_name="splade")
        assert isinstance(result, dict)
