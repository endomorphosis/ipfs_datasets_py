"""Unit tests for P2PServiceManager connection pool.

Tests acquire_connection, release_connection, clear_connection_pool, and
get_pool_stats without requiring a live P2P network — the pool is purely
in-memory/dict-based.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(pool_max_size: int = 5) -> P2PServiceManager:
    """Return a fresh P2PServiceManager with the given pool size."""
    mgr = P2PServiceManager(enabled=False)
    mgr._pool_max_size = pool_max_size
    mgr._connection_pool.clear()
    mgr._pool_hits = 0
    mgr._pool_misses = 0
    return mgr


class _FakeConn:
    """Minimal fake connection object."""

    def __init__(self, peer_id: str = "peer-1") -> None:
        self.peer_id = peer_id


# ---------------------------------------------------------------------------
# acquire_connection
# ---------------------------------------------------------------------------

class TestAcquireConnection:
    def test_acquire_miss_returns_none(self):
        mgr = _make_manager()
        conn = mgr.acquire_connection("peer-abc")
        assert conn is None

    def test_acquire_hit_returns_pooled_connection(self):
        mgr = _make_manager()
        fake = _FakeConn("peer-1")
        mgr._connection_pool["peer-1"] = fake
        result = mgr.acquire_connection("peer-1")
        assert result is fake

    def test_acquire_removes_from_pool(self):
        mgr = _make_manager()
        mgr._connection_pool["peer-1"] = _FakeConn()
        mgr.acquire_connection("peer-1")
        assert "peer-1" not in mgr._connection_pool

    def test_acquire_increments_hit_counter(self):
        mgr = _make_manager()
        mgr._connection_pool["peer-1"] = _FakeConn()
        mgr.acquire_connection("peer-1")
        assert mgr._pool_hits == 1

    def test_acquire_miss_increments_miss_counter(self):
        mgr = _make_manager()
        mgr.acquire_connection("no-such-peer")
        assert mgr._pool_misses == 1


# ---------------------------------------------------------------------------
# release_connection
# ---------------------------------------------------------------------------

class TestReleaseConnection:
    def test_release_adds_to_pool(self):
        mgr = _make_manager()
        conn = _FakeConn("peer-2")
        accepted = mgr.release_connection("peer-2", conn)
        assert accepted is True
        assert "peer-2" in mgr._connection_pool

    def test_release_none_returns_false(self):
        mgr = _make_manager()
        accepted = mgr.release_connection("peer-2", None)
        assert accepted is False

    def test_release_over_capacity_returns_false(self):
        mgr = _make_manager(pool_max_size=2)
        mgr.release_connection("p1", _FakeConn("p1"))
        mgr.release_connection("p2", _FakeConn("p2"))
        # Pool is now full; third release should be rejected
        accepted = mgr.release_connection("p3", _FakeConn("p3"))
        assert accepted is False
        assert len(mgr._connection_pool) == 2

    def test_release_and_reacquire_round_trip(self):
        mgr = _make_manager()
        conn = _FakeConn("peer-rt")
        mgr.release_connection("peer-rt", conn)
        result = mgr.acquire_connection("peer-rt")
        assert result is conn


# ---------------------------------------------------------------------------
# clear_connection_pool
# ---------------------------------------------------------------------------

class TestClearConnectionPool:
    def test_clear_returns_count_of_evicted(self):
        mgr = _make_manager()
        mgr._connection_pool["p1"] = _FakeConn("p1")
        mgr._connection_pool["p2"] = _FakeConn("p2")
        count = mgr.clear_connection_pool()
        assert count == 2

    def test_clear_empties_pool(self):
        mgr = _make_manager()
        mgr._connection_pool["p1"] = _FakeConn("p1")
        mgr.clear_connection_pool()
        assert len(mgr._connection_pool) == 0

    def test_clear_resets_hit_miss_counters(self):
        mgr = _make_manager()
        mgr._pool_hits = 5
        mgr._pool_misses = 3
        mgr.clear_connection_pool()
        assert mgr._pool_hits == 0
        assert mgr._pool_misses == 0

    def test_clear_empty_pool_returns_zero(self):
        mgr = _make_manager()
        count = mgr.clear_connection_pool()
        assert count == 0


# ---------------------------------------------------------------------------
# get_pool_stats
# ---------------------------------------------------------------------------

class TestGetPoolStats:
    def test_stats_has_required_keys(self):
        mgr = _make_manager()
        stats = mgr.get_pool_stats()
        for key in ("size", "max_size", "hits", "misses", "hit_rate"):
            assert key in stats

    def test_hit_rate_none_when_no_attempts(self):
        mgr = _make_manager()
        stats = mgr.get_pool_stats()
        assert stats["hit_rate"] is None

    def test_hit_rate_computed_after_attempts(self):
        mgr = _make_manager()
        mgr._connection_pool["p1"] = _FakeConn("p1")
        mgr.acquire_connection("p1")   # hit
        mgr.acquire_connection("p2")   # miss
        stats = mgr.get_pool_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.5)

    def test_size_reflects_pool_length(self):
        mgr = _make_manager()
        mgr._connection_pool["p1"] = _FakeConn("p1")
        stats = mgr.get_pool_stats()
        assert stats["size"] == 1
        assert stats["max_size"] == 5
