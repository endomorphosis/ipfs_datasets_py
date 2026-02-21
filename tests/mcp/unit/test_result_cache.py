"""Unit tests for ipfs_datasets_py.mcp_server.mcplusplus.result_cache.

Covers MemoryCacheBackend and ResultCache (get, put, invalidate, stats, TTL,
eviction) without any external dependencies.
"""
from __future__ import annotations

import asyncio
import time
import pytest

from ipfs_datasets_py.mcp_server.mcplusplus.result_cache import (
    MemoryCacheBackend,
    ResultCache,
    EvictionPolicy,
    CacheEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(key: str = "k1", value: object = "v1", ttl: float | None = None) -> CacheEntry:
    now = time.time()
    return CacheEntry(
        key=key,
        value=value,
        created_at=now,
        last_accessed=now,
        access_count=0,
        ttl=ttl,
        size_bytes=len(str(value).encode()),
    )


def _run(coro):  # noqa: ANN001
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# MemoryCacheBackend
# ---------------------------------------------------------------------------

class TestMemoryCacheBackendBasic:
    def test_get_miss_returns_none(self):
        backend = MemoryCacheBackend()
        result = _run(backend.get("nonexistent"))
        assert result is None

    def test_put_then_get_hit(self):
        backend = MemoryCacheBackend()
        entry = _make_entry("k1", "value1")
        _run(backend.put(entry))
        result = _run(backend.get("k1"))
        assert result is not None
        assert result.value == "value1"

    def test_delete_removes_entry(self):
        backend = MemoryCacheBackend()
        _run(backend.put(_make_entry("k1")))
        deleted = _run(backend.delete("k1"))
        assert deleted is True
        assert _run(backend.get("k1")) is None

    def test_delete_nonexistent_returns_false(self):
        backend = MemoryCacheBackend()
        assert _run(backend.delete("nope")) is False

    def test_clear_removes_all(self):
        backend = MemoryCacheBackend()
        _run(backend.put(_make_entry("k1")))
        _run(backend.put(_make_entry("k2")))
        count = _run(backend.clear())
        assert count == 2
        assert _run(backend.get("k1")) is None

    def test_eviction_on_max_size(self):
        backend = MemoryCacheBackend(max_size=2)
        _run(backend.put(_make_entry("k1", "v1")))
        _run(backend.put(_make_entry("k2", "v2")))
        # Adding k3 should evict the oldest entry (k1)
        _run(backend.put(_make_entry("k3", "v3")))
        stats = _run(backend.get_stats())
        assert stats["size"] == 2

    def test_get_stats_keys(self):
        backend = MemoryCacheBackend()
        stats = _run(backend.get_stats())
        assert "backend" in stats
        assert "size" in stats
        assert stats["backend"] == "memory"


# ---------------------------------------------------------------------------
# ResultCache
# ---------------------------------------------------------------------------

class TestResultCacheGetPut:
    def setup_method(self):
        self.cache = ResultCache(
            backend=MemoryCacheBackend(),
            default_ttl=60.0,
        )

    def test_get_miss_returns_none(self):
        result = _run(self.cache.get("task_1"))
        assert result is None

    def test_put_then_get_returns_value(self):
        _run(self.cache.put("task_1", {"result": "ok"}))
        result = _run(self.cache.get("task_1"))
        assert result == {"result": "ok"}

    def test_put_with_inputs_is_deterministic(self):
        inputs = {"a": 1, "b": 2}
        _run(self.cache.put("task_1", "v1", inputs=inputs))
        result = _run(self.cache.get("task_1", inputs=inputs))
        assert result == "v1"

    def test_different_inputs_produce_different_keys(self):
        _run(self.cache.put("task_1", "v1", inputs={"a": 1}))
        result = _run(self.cache.get("task_1", inputs={"a": 2}))
        assert result is None

    def test_put_overwrites_existing(self):
        _run(self.cache.put("task_1", "old"))
        _run(self.cache.put("task_1", "new"))
        result = _run(self.cache.get("task_1"))
        assert result == "new"


class TestResultCacheInvalidate:
    def setup_method(self):
        self.cache = ResultCache(backend=MemoryCacheBackend())

    def test_invalidate_removes_entry(self):
        _run(self.cache.put("task_1", "v1"))
        _run(self.cache.invalidate("task_1"))
        assert _run(self.cache.get("task_1")) is None

    def test_invalidate_nonexistent_does_not_raise(self):
        _run(self.cache.invalidate("nonexistent"))  # Should not raise

    def test_clear_removes_all_entries(self):
        _run(self.cache.put("t1", "v1"))
        _run(self.cache.put("t2", "v2"))
        count = _run(self.cache.clear())
        assert count >= 2  # May have more from other tests; ensure >= 2
        assert _run(self.cache.get("t1")) is None


class TestResultCacheTTL:
    def test_expired_entry_returns_none(self):
        cache = ResultCache(backend=MemoryCacheBackend(), default_ttl=0.01)
        _run(cache.put("task_x", "value"))
        time.sleep(0.05)  # Let it expire
        result = _run(cache.get("task_x"))
        assert result is None

    def test_unexpired_entry_is_returned(self):
        cache = ResultCache(backend=MemoryCacheBackend(), default_ttl=60.0)
        _run(cache.put("task_y", "still_valid"))
        result = _run(cache.get("task_y"))
        assert result == "still_valid"


class TestResultCacheStats:
    def setup_method(self):
        self.cache = ResultCache(backend=MemoryCacheBackend())

    def test_hit_rate_zero_on_empty(self):
        assert self.cache.hit_rate == 0.0

    def test_hits_and_misses_tracked(self):
        _run(self.cache.put("t1", "v1"))
        _run(self.cache.get("t1"))   # hit
        _run(self.cache.get("t2"))   # miss
        assert self.cache.hits >= 1
        assert self.cache.misses >= 1

    def test_hit_rate_between_0_and_1(self):
        _run(self.cache.put("t1", "v1"))
        _run(self.cache.get("t1"))
        _run(self.cache.get("missing"))
        rate = self.cache.hit_rate
        assert 0.0 <= rate <= 1.0

    def test_get_stats_returns_dict(self):
        stats = _run(self.cache.get_stats())
        assert isinstance(stats, dict)
        assert "hits" in stats
        assert "misses" in stats
