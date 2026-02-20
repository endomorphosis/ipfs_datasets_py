"""Phase 7 performance-optimisation tests.

Tests cover:
- ToolCategory schema-result caching (get_tool_schema, cache_info, clear_schema_cache)
- P2PServiceManager connection pooling (acquire, release, clear, get_pool_stats)

Test format: GIVEN-WHEN-THEN
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_category_with_tool():
    """Return a pre-populated ToolCategory with one synchronous tool."""
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import ToolCategory

    def my_tool(param: str, count: int = 1) -> str:
        """Return param repeated count times."""
        return param * count

    cat = ToolCategory("test_cat", Path("/tmp/fake"))
    cat._discovered = True
    cat._tools = {"my_tool": my_tool}
    cat._tool_metadata = {
        "my_tool": {
            "name": "my_tool",
            "category": "test_cat",
            "description": "Return param repeated count times.",
            "signature": str(inspect.signature(my_tool)),
        }
    }
    return cat


# ─── ToolCategory schema caching ──────────────────────────────────────────────

class TestToolCategorySchemaCaching:
    """Tests for Phase 7 schema-result caching in ToolCategory."""

    def test_initial_cache_is_empty(self):
        """
        GIVEN: A freshly created ToolCategory
        WHEN: cache_info is called before any schema lookups
        THEN: hits=0, misses=0, size=0
        """
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import ToolCategory

        # GIVEN / WHEN
        cat = ToolCategory("cat", Path("/tmp"))

        # THEN
        info = cat.cache_info()
        assert info["hits"] == 0
        assert info["misses"] == 0
        assert info["size"] == 0

    def test_first_call_populates_cache(self):
        """
        GIVEN: A ToolCategory with one tool
        WHEN: get_tool_schema is called for the first time
        THEN: schema is returned and miss counter increments, cache size = 1
        """
        # GIVEN
        cat = _make_category_with_tool()

        # WHEN
        schema = cat.get_tool_schema("my_tool")

        # THEN
        assert schema is not None
        assert schema["name"] == "my_tool"
        info = cat.cache_info()
        assert info["misses"] == 1
        assert info["hits"] == 0
        assert info["size"] == 1

    def test_second_call_hits_cache(self):
        """
        GIVEN: A schema already cached for a tool
        WHEN: get_tool_schema is called a second time for the same tool
        THEN: same dict is returned, hit counter increments, miss stays at 1
        """
        # GIVEN
        cat = _make_category_with_tool()
        first = cat.get_tool_schema("my_tool")  # populates cache

        # WHEN
        second = cat.get_tool_schema("my_tool")

        # THEN
        assert second is first  # same dict object from cache
        info = cat.cache_info()
        assert info["hits"] == 1
        assert info["misses"] == 1

    def test_clear_schema_cache_resets_state(self):
        """
        GIVEN: A ToolCategory with a populated schema cache
        WHEN: clear_schema_cache is called
        THEN: cache is empty and counters reset to 0
        """
        # GIVEN
        cat = _make_category_with_tool()
        cat.get_tool_schema("my_tool")  # populate

        # WHEN
        cat.clear_schema_cache()

        # THEN
        info = cat.cache_info()
        assert info["size"] == 0
        assert info["hits"] == 0
        assert info["misses"] == 0

    def test_after_clear_next_call_is_a_miss(self):
        """
        GIVEN: A cleared schema cache
        WHEN: get_tool_schema is called again
        THEN: miss increments and cache is re-populated
        """
        # GIVEN
        cat = _make_category_with_tool()
        cat.get_tool_schema("my_tool")
        cat.clear_schema_cache()

        # WHEN
        schema = cat.get_tool_schema("my_tool")

        # THEN
        assert schema is not None
        assert cat.cache_info()["misses"] == 1
        assert cat.cache_info()["size"] == 1

    def test_unknown_tool_is_not_cached(self):
        """
        GIVEN: A category that does not have 'ghost_tool'
        WHEN: get_tool_schema("ghost_tool") is called
        THEN: None is returned and cache size stays 0
        """
        # GIVEN
        cat = _make_category_with_tool()

        # WHEN
        result = cat.get_tool_schema("ghost_tool")

        # THEN
        assert result is None
        assert cat.cache_info()["size"] == 0


# ─── P2PServiceManager connection pooling ─────────────────────────────────────

class TestP2PConnectionPool:
    """Tests for Phase 7 P2P connection pooling in P2PServiceManager."""

    def _mgr(self, **kw):
        from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager
        return P2PServiceManager(enabled=False, **kw)

    def test_initial_pool_stats_are_zero(self):
        """
        GIVEN: A freshly created P2PServiceManager
        WHEN: get_pool_stats is called
        THEN: size=0, hits=0, misses=0, hit_rate=None
        """
        # GIVEN / WHEN
        mgr = self._mgr()

        # THEN
        stats = mgr.get_pool_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] is None
        assert stats["max_size"] == 10

    def test_acquire_miss_when_pool_empty(self):
        """
        GIVEN: An empty connection pool
        WHEN: acquire_connection is called for any peer
        THEN: returns None and increments miss counter
        """
        # GIVEN
        mgr = self._mgr()

        # WHEN
        conn = mgr.acquire_connection("QmPeer1")

        # THEN
        assert conn is None
        stats = mgr.get_pool_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_release_then_acquire_same_peer(self):
        """
        GIVEN: A connection released for peer QmPeer2
        WHEN: acquire_connection is called for QmPeer2
        THEN: the same connection object is returned and hit counter increments
        """
        # GIVEN
        mgr = self._mgr()
        mock_conn = MagicMock(name="connection")
        accepted = mgr.release_connection("QmPeer2", mock_conn)
        assert accepted is True

        # WHEN
        retrieved = mgr.acquire_connection("QmPeer2")

        # THEN
        assert retrieved is mock_conn
        stats = mgr.get_pool_stats()
        assert stats["hits"] == 1
        assert stats["size"] == 0  # connection was removed from pool

    def test_pool_max_size_enforced(self):
        """
        GIVEN: A pool already at max_size (2 for this test)
        WHEN: a third connection is released
        THEN: returns False and pool stays at 2
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager
        mgr = P2PServiceManager(enabled=False)
        mgr._pool_max_size = 2

        mgr.release_connection("QmA", MagicMock())
        mgr.release_connection("QmB", MagicMock())

        # WHEN
        result = mgr.release_connection("QmC", MagicMock())

        # THEN
        assert result is False
        assert mgr.get_pool_stats()["size"] == 2

    def test_clear_connection_pool(self):
        """
        GIVEN: A pool with 3 connections and non-zero counters
        WHEN: clear_connection_pool is called
        THEN: pool is empty and counters reset; returns count of evicted connections
        """
        # GIVEN
        mgr = self._mgr()
        mgr.release_connection("QmA", MagicMock())
        mgr.release_connection("QmB", MagicMock())
        mgr.release_connection("QmC", MagicMock())
        mgr.acquire_connection("QmX")  # add a miss

        # WHEN
        evicted = mgr.clear_connection_pool()

        # THEN
        assert evicted == 3
        stats = mgr.get_pool_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_hit_rate_calculation(self):
        """
        GIVEN: 3 hits and 1 miss
        WHEN: get_pool_stats is called
        THEN: hit_rate is 0.75
        """
        # GIVEN
        mgr = self._mgr()
        for i in range(3):
            peer = f"QmPeer{i}"
            mgr.release_connection(peer, MagicMock())
            mgr.acquire_connection(peer)  # hit

        mgr.acquire_connection("QmMiss")  # miss

        # WHEN
        stats = mgr.get_pool_stats()

        # THEN
        assert stats["hits"] == 3
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.75)

    def test_release_none_returns_false(self):
        """
        GIVEN: A None connection
        WHEN: release_connection is called with None
        THEN: returns False and pool stays empty
        """
        # GIVEN
        mgr = self._mgr()

        # WHEN
        result = mgr.release_connection("QmPeer1", None)

        # THEN
        assert result is False
        assert mgr.get_pool_stats()["size"] == 0

    def test_get_capabilities_includes_pool_max_size(self):
        """
        GIVEN: A P2PServiceManager
        WHEN: get_capabilities is called
        THEN: 'connection_pool_max_size' key is present with correct value
        """
        # GIVEN / WHEN
        mgr = self._mgr()
        caps = mgr.get_capabilities()

        # THEN
        assert "connection_pool_max_size" in caps
        assert caps["connection_pool_max_size"] == 10
