"""
Tests for proof caching system.

Tests cover:
- Basic cache operations (get/put/invalidate)
- LRU eviction policy
- TTL expiration
- Statistics and monitoring
- Performance characteristics
"""

import pytest
import time
from ipfs_datasets_py.logic.integration.proof_cache import (
    ProofCache,
    CachedProof,
    get_global_cache,
)


class TestCachedProof:
    """Test CachedProof dataclass."""

    def test_cached_proof_creation(self):
        """
        GIVEN: CachedProof parameters
        WHEN: Creating cached proof
        THEN: Should create valid object
        """
        cached = CachedProof(
            formula_hash="abc123",
            prover="z3",
            result_data={"status": "success"},
            timestamp=time.time()
        )
        
        assert cached.formula_hash == "abc123"
        assert cached.prover == "z3"
        assert cached.ttl == 3600  # default

    def test_is_expired_fresh(self):
        """
        GIVEN: Freshly cached proof
        WHEN: Checking expiration
        THEN: Should not be expired
        """
        cached = CachedProof(
            formula_hash="test",
            prover="test",
            result_data={},
            timestamp=time.time(),
            ttl=3600
        )
        
        assert not cached.is_expired()

    def test_is_expired_old(self):
        """
        GIVEN: Old cached proof (>TTL)
        WHEN: Checking expiration
        THEN: Should be expired
        """
        cached = CachedProof(
            formula_hash="test",
            prover="test",
            result_data={},
            timestamp=time.time() - 7200,  # 2 hours ago
            ttl=3600  # 1 hour TTL
        )
        
        assert cached.is_expired()

    def test_is_expired_never_expires(self):
        """
        GIVEN: Cached proof with TTL=0
        WHEN: Checking expiration
        THEN: Should never expire
        """
        cached = CachedProof(
            formula_hash="test",
            prover="test",
            result_data={},
            timestamp=time.time() - 10000,  # Very old
            ttl=0  # Never expires
        )
        
        assert not cached.is_expired()

    def test_to_dict(self):
        """
        GIVEN: CachedProof instance
        WHEN: Converting to dict
        THEN: Should serialize properly
        """
        cached = CachedProof(
            formula_hash="test",
            prover="z3",
            result_data={"proof": True},
            timestamp=123.456
        )
        
        d = cached.to_dict()
        
        assert isinstance(d, dict)
        assert d["formula_hash"] == "test"
        assert d["prover"] == "z3"

    def test_from_dict(self):
        """
        GIVEN: Dictionary representation
        WHEN: Creating CachedProof from dict
        THEN: Should deserialize properly
        """
        data = {
            "formula_hash": "test",
            "prover": "z3",
            "result_data": {"proof": True},
            "timestamp": 123.456,
            "ttl": 3600,
            "hit_count": 5,
            "metadata": {}
        }
        
        cached = CachedProof.from_dict(data)
        
        assert cached.formula_hash == "test"
        assert cached.hit_count == 5


class TestProofCacheBasicOperations:
    """Test basic cache operations."""

    def test_cache_initialization(self):
        """
        GIVEN: ProofCache parameters
        WHEN: Creating cache
        THEN: Should initialize with correct settings
        """
        cache = ProofCache(max_size=100, default_ttl=1800)
        
        assert cache.max_size == 100
        assert cache.default_ttl == 1800
        assert len(cache._cache) == 0

    def test_put_and_get(self):
        """
        GIVEN: Empty cache
        WHEN: Putting then getting proof
        THEN: Should retrieve cached proof
        """
        cache = ProofCache(max_size=10)
        formula = "P → Q"
        prover = "z3"
        result = {"status": "success", "proof": "..."}
        
        cache.put(formula, prover, result)
        retrieved = cache.get(formula, prover)
        
        assert retrieved is not None
        assert retrieved["status"] == "success"

    def test_get_miss(self):
        """
        GIVEN: Empty cache
        WHEN: Getting non-existent proof
        THEN: Should return None
        """
        cache = ProofCache()
        
        result = cache.get("nonexistent", "z3")
        
        assert result is None

    def test_put_updates_statistics(self):
        """
        GIVEN: Cache with statistics
        WHEN: Putting proof
        THEN: Should update stats
        """
        cache = ProofCache()
        
        cache.put("P", "z3", {"result": "ok"})
        stats = cache.get_statistics()
        
        assert stats["total_puts"] == 1
        assert stats["size"] == 1

    def test_get_updates_statistics(self):
        """
        GIVEN: Cache with cached proof
        WHEN: Getting proof (hit)
        THEN: Should update hit statistics
        """
        cache = ProofCache()
        cache.put("P", "z3", {"result": "ok"})
        
        cache.get("P", "z3")  # Hit
        cache.get("Q", "z3")  # Miss
        
        stats = cache.get_statistics()
        
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_hit_rate_calculation(self):
        """
        GIVEN: Cache with hits and misses
        WHEN: Getting statistics
        THEN: Should calculate hit rate correctly
        """
        cache = ProofCache()
        cache.put("P", "z3", {"result": "ok"})
        
        cache.get("P", "z3")  # Hit
        cache.get("P", "z3")  # Hit
        cache.get("Q", "z3")  # Miss
        cache.get("R", "z3")  # Miss
        
        stats = cache.get_statistics()
        
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5

    def test_invalidate(self):
        """
        GIVEN: Cache with cached proof
        WHEN: Invalidating proof
        THEN: Should remove from cache
        """
        cache = ProofCache()
        cache.put("P", "z3", {"result": "ok"})
        
        result = cache.invalidate("P", "z3")
        
        assert result is True
        assert cache.get("P", "z3") is None

    def test_invalidate_nonexistent(self):
        """
        GIVEN: Empty cache
        WHEN: Invalidating non-existent proof
        THEN: Should return False
        """
        cache = ProofCache()
        
        result = cache.invalidate("nonexistent", "z3")
        
        assert result is False

    def test_clear(self):
        """
        GIVEN: Cache with multiple entries
        WHEN: Clearing cache
        THEN: Should remove all entries
        """
        cache = ProofCache()
        cache.put("P", "z3", {"result": "ok"})
        cache.put("Q", "lean", {"result": "ok"})
        cache.put("R", "coq", {"result": "ok"})
        
        count = cache.clear()
        
        assert count == 3
        assert len(cache._cache) == 0


class TestLRUEviction:
    """Test LRU eviction policy."""

    def test_eviction_on_capacity(self):
        """
        GIVEN: Cache at max capacity
        WHEN: Adding new proof
        THEN: Should evict oldest entry
        """
        cache = ProofCache(max_size=3)
        
        cache.put("P", "z3", {"result": "1"})
        cache.put("Q", "z3", {"result": "2"})
        cache.put("R", "z3", {"result": "3"})
        
        # Cache is full, adding new entry should evict "P"
        cache.put("S", "z3", {"result": "4"})
        
        assert cache.get("P", "z3") is None  # Evicted
        assert cache.get("S", "z3") is not None  # New entry
        
        stats = cache.get_statistics()
        assert stats["evictions"] == 1

    def test_lru_order_maintained(self):
        """
        GIVEN: Cache with multiple entries
        WHEN: Accessing entries
        THEN: Should maintain LRU order
        """
        cache = ProofCache(max_size=3)
        
        cache.put("P", "z3", {"result": "1"})
        cache.put("Q", "z3", {"result": "2"})
        cache.put("R", "z3", {"result": "3"})
        
        # Access "P" to make it recently used
        cache.get("P", "z3")
        
        # Add new entry - should evict "Q" (oldest unused)
        cache.put("S", "z3", {"result": "4"})
        
        assert cache.get("P", "z3") is not None  # Still cached
        assert cache.get("Q", "z3") is None  # Evicted

    def test_multiple_evictions(self):
        """
        GIVEN: Cache with limited capacity
        WHEN: Adding many entries
        THEN: Should evict multiple oldest entries
        """
        cache = ProofCache(max_size=2)
        
        for i in range(5):
            cache.put(f"P{i}", "z3", {"result": str(i)})
        
        stats = cache.get_statistics()
        
        assert stats["evictions"] == 3  # Evicted 3 to maintain size=2
        assert stats["size"] == 2


class TestTTLExpiration:
    """Test time-to-live expiration."""

    def test_expired_entry_removed_on_get(self):
        """
        GIVEN: Cache with expired entry
        WHEN: Getting expired proof
        THEN: Should return None and remove entry
        """
        cache = ProofCache()
        
        # Add entry with very short TTL
        cache.put("P", "z3", {"result": "ok"}, ttl=1)
        
        # Wait for expiration
        time.sleep(1.1)
        
        result = cache.get("P", "z3")
        
        assert result is None
        
        stats = cache.get_statistics()
        assert stats["expirations"] == 1

    def test_cleanup_expired(self):
        """
        GIVEN: Cache with some expired entries
        WHEN: Running cleanup
        THEN: Should remove expired entries
        """
        cache = ProofCache()
        
        cache.put("P", "z3", {"result": "1"}, ttl=1)
        cache.put("Q", "z3", {"result": "2"}, ttl=3600)  # Won't expire
        cache.put("R", "z3", {"result": "3"}, ttl=1)
        
        time.sleep(1.1)
        
        removed = cache.cleanup_expired()
        
        assert removed == 2
        assert cache.get("Q", "z3") is not None  # Still cached

    def test_custom_ttl(self):
        """
        GIVEN: Proof with custom TTL
        WHEN: Caching proof
        THEN: Should use custom TTL
        """
        cache = ProofCache(default_ttl=3600)
        
        cache.put("P", "z3", {"result": "ok"}, ttl=7200)
        
        # Get the cached entry to check TTL
        key = cache._make_key("P", "z3")
        cached = cache._cache[key]
        
        assert cached.ttl == 7200


class TestCacheStatistics:
    """Test cache statistics and monitoring."""

    def test_get_statistics_structure(self):
        """
        GIVEN: Cache instance
        WHEN: Getting statistics
        THEN: Should return complete stats dictionary
        """
        cache = ProofCache()
        
        stats = cache.get_statistics()
        
        assert "size" in stats
        assert "max_size" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
        assert "evictions" in stats
        assert "expirations" in stats
        assert "total_puts" in stats

    def test_get_cached_entries(self):
        """
        GIVEN: Cache with entries
        WHEN: Getting cached entries list
        THEN: Should return entry summaries
        """
        cache = ProofCache()
        cache.put("P", "z3", {"result": "1"})
        cache.put("Q", "lean", {"result": "2"})
        
        entries = cache.get_cached_entries()
        
        assert len(entries) == 2
        assert all("prover" in e for e in entries)
        assert all("timestamp" in e for e in entries)

    def test_hit_count_tracking(self):
        """
        GIVEN: Cached proof
        WHEN: Accessing multiple times
        THEN: Should track hit count
        """
        cache = ProofCache()
        cache.put("P", "z3", {"result": "ok"})
        
        # Access 3 times
        cache.get("P", "z3")
        cache.get("P", "z3")
        cache.get("P", "z3")
        
        entries = cache.get_cached_entries()
        
        assert entries[0]["hit_count"] == 3


class TestCacheResize:
    """Test cache resizing functionality."""

    def test_resize_larger(self):
        """
        GIVEN: Cache with some entries
        WHEN: Increasing capacity
        THEN: Should maintain all entries
        """
        cache = ProofCache(max_size=5)
        for i in range(5):
            cache.put(f"P{i}", "z3", {"result": str(i)})
        
        cache.resize(10)
        
        assert cache.max_size == 10
        assert len(cache._cache) == 5

    def test_resize_smaller(self):
        """
        GIVEN: Cache with many entries
        WHEN: Decreasing capacity
        THEN: Should evict oldest entries
        """
        cache = ProofCache(max_size=5)
        for i in range(5):
            cache.put(f"P{i}", "z3", {"result": str(i)})
        
        cache.resize(3)
        
        assert cache.max_size == 3
        assert len(cache._cache) == 3
        
        stats = cache.get_statistics()
        assert stats["evictions"] == 2


class TestGlobalCache:
    """Test global cache singleton."""

    def test_get_global_cache(self):
        """
        GIVEN: No global cache exists
        WHEN: Getting global cache
        THEN: Should create and return singleton instance
        """
        cache1 = get_global_cache()
        cache2 = get_global_cache()
        
        assert cache1 is cache2  # Same instance

    def test_global_cache_persists_data(self):
        """
        GIVEN: Global cache with data
        WHEN: Getting global cache again
        THEN: Should maintain cached data
        """
        cache1 = get_global_cache()
        cache1.put("test", "z3", {"result": "ok"})
        
        cache2 = get_global_cache()
        result = cache2.get("test", "z3")
        
        assert result is not None
        assert result["result"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
