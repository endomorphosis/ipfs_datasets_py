"""Unit tests for vector store management fail-closed behavior.

These tests ensure unimplemented backends return an explicit error response,
rather than returning `None` (which is hard for callers to diagnose).
"""

import pytest


@pytest.mark.anyio
async def test_search_vector_index_qdrant_unimplemented_returns_error():
    from ipfs_datasets_py.mcp_server.tools.vector_tools.vector_store_management import (
        search_vector_index,
    )

    result = await search_vector_index(index_name="idx", query="hello", backend="qdrant")
    assert result["status"] == "error"
    assert result["backend"] == "qdrant"


@pytest.mark.anyio
async def test_search_vector_index_elasticsearch_unimplemented_returns_error():
    from ipfs_datasets_py.mcp_server.tools.vector_tools.vector_store_management import (
        search_vector_index,
    )

    result = await search_vector_index(index_name="idx", query="hello", backend="elasticsearch")
    assert result["status"] == "error"
    assert result["backend"] == "elasticsearch"
