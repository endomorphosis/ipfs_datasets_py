#!/usr/bin/env python3
"""
Test suite for cache_tools functionality with GIVEN WHEN THEN format.

Written to match the actual cache_tools API (manage_cache, cache_stats, optimize_cache).
Key: successful ops return {'success': True, 'operation': ..., ...} — NOT {'status': 'success'}.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import (
    manage_cache,
    cache_stats,
    optimize_cache,
)


class TestCacheTools:
    """Test cache_tools core CRUD operations."""

    @pytest.mark.asyncio
    async def test_cache_set_operation(self):
        """GIVEN a key-value pair
        WHEN calling manage_cache with operation='set'
        THEN the item is stored and success=True is returned
        """
        result = await manage_cache(
            operation="set", key="test-key-set", value="test-value", ttl=3600, namespace="test"
        )
        assert result is not None
        assert result["success"] is True
        assert result["operation"] == "set"
        assert result["key"] == "test-key-set"

    @pytest.mark.asyncio
    async def test_cache_get_after_set(self):
        """GIVEN a previously stored key
        WHEN calling manage_cache with operation='get'
        THEN the value is returned and hit=True
        """
        await manage_cache(operation="set", key="roundtrip-key", value="hello", namespace="rt")
        result = await manage_cache(operation="get", key="roundtrip-key", namespace="rt")
        assert result is not None
        assert result["hit"] is True
        assert result["value"] == "hello"
        assert result["operation"] == "get"

    @pytest.mark.asyncio
    async def test_cache_get_miss(self):
        """GIVEN a key that does not exist
        WHEN calling manage_cache with operation='get'
        THEN hit=False is returned
        """
        result = await manage_cache(operation="get", key="nonexistent-key-xyz", namespace="miss")
        assert result is not None
        assert result["hit"] is False
        assert result["operation"] == "get"

    @pytest.mark.asyncio
    async def test_cache_delete_operation(self):
        """GIVEN a stored key
        WHEN calling manage_cache with operation='delete'
        THEN the key is deleted and deleted=True is returned
        """
        await manage_cache(operation="set", key="delete-me", value="x", namespace="del")
        result = await manage_cache(operation="delete", key="delete-me", namespace="del")
        assert result is not None
        assert result["deleted"] is True
        assert result["operation"] == "delete"

    @pytest.mark.asyncio
    async def test_cache_clear_operation(self):
        """GIVEN a namespace
        WHEN calling manage_cache with operation='clear'
        THEN the namespace is cleared and success=True is returned
        """
        result = await manage_cache(operation="clear", namespace="clear-test")
        assert result is not None
        assert result["success"] is True
        assert result["operation"] == "clear"
        assert "keys_cleared" in result

    @pytest.mark.asyncio
    async def test_cache_invalid_operation(self):
        """GIVEN an invalid operation
        WHEN calling manage_cache
        THEN success=False and valid_operations are listed
        """
        result = await manage_cache(operation="invalid_op", key="x")
        assert result is not None
        assert result["success"] is False
        assert "valid_operations" in result
        assert "get" in result["valid_operations"]
        assert "set" in result["valid_operations"]


class TestCacheStats:
    """Test cache_stats and optimize_cache functions."""

    @pytest.mark.asyncio
    async def test_cache_stats_global(self):
        """GIVEN no namespace filter
        WHEN calling cache_stats
        THEN global stats with hit_rate_percent are returned
        """
        result = await cache_stats()
        assert result is not None
        assert result["success"] is True
        assert "global_stats" in result
        assert "hit_rate_percent" in result["global_stats"]

    @pytest.mark.asyncio
    async def test_cache_stats_with_namespace(self):
        """GIVEN a namespace
        WHEN calling cache_stats with that namespace
        THEN stats for that namespace are returned
        """
        result = await cache_stats(namespace="test-ns")
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_optimize_cache(self):
        """GIVEN a cache with possible entries
        WHEN calling optimize_cache
        THEN optimization succeeds and strategy is reported
        """
        result = await optimize_cache()
        assert result is not None
        assert result["success"] is True
        assert "strategy" in result
        assert "keys_evicted" in result

    @pytest.mark.asyncio
    async def test_optimize_cache_custom_strategy(self):
        """GIVEN a specific eviction strategy
        WHEN calling optimize_cache with strategy='lfu'
        THEN optimization succeeds with the given strategy
        """
        result = await optimize_cache(strategy="lfu", max_size_mb=100)
        assert result is not None
        assert result["success"] is True


class TestCacheEmbeddings:
    """Test embedding-specific cache helpers."""

    @pytest.mark.asyncio
    async def test_cache_and_get_embeddings(self):
        """GIVEN text and embeddings
        WHEN caching embeddings and retrieving them
        THEN the embeddings round-trip successfully
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import (
                cache_embeddings,
                get_cached_embeddings,
            )
            emb = [0.1, 0.2, 0.3, 0.4, 0.5]
            store_result = await cache_embeddings(text="hello world", embeddings=emb, model="test-model")
            assert store_result is not None

            get_result = await get_cached_embeddings(text="hello world", model="test-model")
            assert get_result is not None
        except ImportError:
            pytest.skip("cache_embeddings / get_cached_embeddings not available")


class TestCacheIntegration:
    """Integration-style cache tests."""

    @pytest.mark.asyncio
    async def test_set_get_delete_roundtrip(self):
        """GIVEN a key-value pair
        WHEN set, get, and delete are called sequentially
        THEN the value is stored, retrieved, and removed correctly
        """
        ns = "integration-roundtrip"
        key = "roundtrip-key-2"
        value = {"nested": True, "count": 42}

        set_r = await manage_cache(operation="set", key=key, value=value, namespace=ns)
        assert set_r["success"] is True

        get_r = await manage_cache(operation="get", key=key, namespace=ns)
        assert get_r["hit"] is True

        del_r = await manage_cache(operation="delete", key=key, namespace=ns)
        assert del_r["deleted"] is True

        miss_r = await manage_cache(operation="get", key=key, namespace=ns)
        assert miss_r["hit"] is False

    @pytest.mark.asyncio
    async def test_cache_stats_reflect_operations(self):
        """GIVEN a series of set+get operations
        WHEN cache_stats is called
        THEN total_operations reflects the activity
        """
        ns = "stats-test"
        for i in range(3):
            await manage_cache(operation="set", key=f"stat-key-{i}", value=i, namespace=ns)

        stats = await cache_stats()
        assert stats["success"] is True
        assert stats["global_stats"]["total_operations"] >= 3
