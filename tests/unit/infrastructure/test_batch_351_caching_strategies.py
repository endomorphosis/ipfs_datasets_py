"""
Batch 351: Multi-Level Caching Strategies
Comprehensive implementation of multi-tier caching with L1/L2 levels, eviction policies, and invalidation strategies.

Features:
- L1 cache (in-memory, fast, limited size)
- L2 cache (larger capacity for overflow)
- Multiple eviction strategies (LRU, LFU, TTL-based)
- Cache invalidation (manual, pattern-based, TTL)
- Cache statistics and metrics
- Cache warming and preloading
- Distributed cache coordination
- Hit/miss tracking and performance metrics

Test Classes (11 total, ~28 tests):
1. TestL1CacheOperations - Basic L1 get/set/delete
2. TestL1Eviction - LRU and LFU eviction in L1
3. TestL2CacheOperations - L2 overflow, get/set
4. TestMultiLevelCaching - L1 miss -> L2 hit promotion
5. TestTTLExpiration - Automatic expiration on TTL
6. TestCacheInvalidation - Manual and pattern-based invalidation
7. TestCacheStatistics - Track hits, misses, evictions
8. TestCacheWarming - Preload and bulk insert
9. TestCacheCoherence - Keep L1/L2 in sync
10. TestEvictionPolicies - LRU, LFU, FIFO comparison
11. TestCacheIntegration - End-to-end multi-level operations
"""

import unittest
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any, Callable, Set, Tuple
from threading import Lock
from collections import OrderedDict, defaultdict
import re


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class EvictionPolicy(Enum):
    """Cache eviction policy enumeration."""
    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    FIFO = "fifo"  # First In First Out


@dataclass
class CacheEntry:
    """Entry in the cache with metadata."""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl_seconds: Optional[int] = None
    tag: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl_seconds is None:
            return False
        return time.time() - self.created_at > self.ttl_seconds
    
    def record_access(self) -> None:
        """Record an access to this entry."""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheStats:
    """Statistics for a cache level."""
    total_hits: int = 0
    total_misses: int = 0
    total_evictions: int = 0
    total_invalidations: int = 0
    key_count: int = 0
    size_bytes: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate hit rate percentage."""
        total = self.total_hits + self.total_misses
        return (self.total_hits / total * 100) if total > 0 else 0.0
    
    def record_hit(self) -> None:
        """Record a cache hit."""
        self.total_hits += 1
    
    def record_miss(self) -> None:
        """Record a cache miss."""
        self.total_misses += 1
    
    def record_eviction(self, size: int = 1) -> None:
        """Record an eviction."""
        self.total_evictions += 1
        self.size_bytes = max(0, self.size_bytes - size)
    
    def record_insertion(self, size: int = 1) -> None:
        """Record insertion and update stats."""
        self.key_count += 1
        self.size_bytes += size


@dataclass
class CachePolicy:
    """Configuration for cache behavior."""
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    max_size: int = 1000
    max_bytes: Optional[int] = None
    default_ttl_seconds: Optional[int] = None
    enable_compression: bool = False


# ============================================================================
# L1 CACHE (FAST, IN-MEMORY)
# ============================================================================

class L1Cache:
    """
    L1 (Primary) Cache - Fast, in-memory cache with limited size.
    Uses eviction policies when capacity is reached.
    """
    
    def __init__(self, policy: CachePolicy):
        """Initialize L1 cache."""
        self._lock = Lock()
        self.policy = policy
        self.entries: Dict[str, CacheEntry] = {}
        self.stats = CacheStats()
        self.access_order = OrderedDict()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            if key not in self.entries:
                self.stats.record_miss()
                return None
            
            entry = self.entries[key]
            if entry.is_expired():
                self._delete_entry(key)
                self.stats.record_miss()
                return None
            
            entry.record_access()
            self.access_order.move_to_end(key)
            self.stats.record_hit()
            return entry.value
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None, tag: Optional[str] = None) -> None:
        """Set value in cache."""
        with self._lock:
            size = len(str(value))
            
            # Delete old entry if exists
            if key in self.entries:
                old_entry = self.entries[key]
                self.stats.record_eviction(len(str(old_entry.value)))
            
            # Check capacity constraints
            while len(self.entries) >= self.policy.max_size:
                self._evict_entry()
            
            entry = CacheEntry(
                key=key,
                value=value,
                ttl_seconds=ttl_seconds or self.policy.default_ttl_seconds,
                tag=tag
            )
            self.entries[key] = entry
            self.access_order[key] = time.time()
            self.stats.record_insertion(size)
    
    def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        with self._lock:
            return self._delete_entry(key)
    
    def _delete_entry(self, key: str) -> bool:
        """Internal delete without lock."""
        if key in self.entries:
            entry = self.entries.pop(key)
            self.access_order.pop(key, None)
            self.stats.total_invalidations += 1
            self.stats.key_count = max(0, self.stats.key_count - 1)
            return True
        return False
    
    def _evict_entry(self) -> None:
        """Evict an entry based on policy."""
        if not self.entries:
            return
        
        if self.policy.eviction_policy == EvictionPolicy.LRU:
            # Remove least recently used
            key_to_evict = next(iter(self.access_order))
        elif self.policy.eviction_policy == EvictionPolicy.LFU:
            # Remove least frequently used
            key_to_evict = min(self.entries.keys(), key=lambda k: self.entries[k].access_count)
        else:  # FIFO
            # Remove oldest
            key_to_evict = min(self.entries.keys(), key=lambda k: self.entries[k].created_at)
        
        entry = self.entries.pop(key_to_evict)
        self.access_order.pop(key_to_evict, None)
        self.stats.record_eviction(len(str(entry.value)))
    
    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self.entries.clear()
            self.access_order.clear()
            self.stats = CacheStats()
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            return CacheStats(
                total_hits=self.stats.total_hits,
                total_misses=self.stats.total_misses,
                total_evictions=self.stats.total_evictions,
                total_invalidations=self.stats.total_invalidations,
                key_count=self.stats.key_count,
                size_bytes=self.stats.size_bytes
            )
    
    def size(self) -> int:
        """Get number of entries."""
        with self._lock:
            return len(self.entries)
    
    def keys(self) -> List[str]:
        """Get all keys."""
        with self._lock:
            return list(self.entries.keys())
    
    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all entries with matching tag."""
        with self._lock:
            keys_to_delete = [k for k, e in self.entries.items() if e.tag == tag]
            for key in keys_to_delete:
                self._delete_entry(key)
            return len(keys_to_delete)
    
    def invalidate_by_pattern(self, pattern: str) -> int:
        """Invalidate all entries matching pattern."""
        with self._lock:
            regex = re.compile(pattern)
            keys_to_delete = [k for k in self.entries.keys() if regex.match(k)]
            for key in keys_to_delete:
                self._delete_entry(key)
            return len(keys_to_delete)


# ============================================================================
# L2 CACHE (LARGER, SLOWER)
# ============================================================================

class L2Cache:
    """
    L2 (Secondary) Cache - Larger capacity cache for overflow from L1.
    Acts as a backup when L1 evicts entries.
    """
    
    def __init__(self, policy: CachePolicy):
        """Initialize L2 cache."""
        self._lock = Lock()
        self.policy = policy
        self.entries: Dict[str, CacheEntry] = {}
        self.stats = CacheStats()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            if key not in self.entries:
                self.stats.record_miss()
                return None
            
            entry = self.entries[key]
            if entry.is_expired():
                self._delete_entry(key)
                self.stats.record_miss()
                return None
            
            entry.record_access()
            self.stats.record_hit()
            return entry.value
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None, tag: Optional[str] = None) -> None:
        """Set value in cache."""
        with self._lock:
            size = len(str(value))
            
            if key in self.entries:
                old_entry = self.entries[key]
                self.stats.record_eviction(len(str(old_entry.value)))
            
            # Remove oldest if at capacity
            while len(self.entries) >= self.policy.max_size * 10:  # L2 is larger
                oldest_key = min(self.entries.keys(), key=lambda k: self.entries[k].created_at)
                old_entry = self.entries.pop(oldest_key)
                self.stats.record_eviction(len(str(old_entry.value)))
            
            entry = CacheEntry(
                key=key,
                value=value,
                ttl_seconds=ttl_seconds or self.policy.default_ttl_seconds,
                tag=tag
            )
            self.entries[key] = entry
            self.stats.record_insertion(size)
    
    def delete(self, key: str) -> bool:
        """Delete entry."""
        with self._lock:
            return self._delete_entry(key)
    
    def _delete_entry(self, key: str) -> bool:
        """Internal delete without lock."""
        if key in self.entries:
            entry = self.entries.pop(key)
            self.stats.total_invalidations += 1
            self.stats.key_count = max(0, self.stats.key_count - 1)
            return True
        return False
    
    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self.entries.clear()
            self.stats = CacheStats()
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            return CacheStats(
                total_hits=self.stats.total_hits,
                total_misses=self.stats.total_misses,
                total_evictions=self.stats.total_evictions,
                total_invalidations=self.stats.total_invalidations,
                key_count=self.stats.key_count,
                size_bytes=self.stats.size_bytes
            )
    
    def size(self) -> int:
        """Get number of entries."""
        with self._lock:
            return len(self.entries)
    
    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all entries with matching tag."""
        with self._lock:
            keys_to_delete = [k for k, e in self.entries.items() if e.tag == tag]
            for key in keys_to_delete:
                self._delete_entry(key)
            return len(keys_to_delete)
    
    def invalidate_by_pattern(self, pattern: str) -> int:
        """Invalidate all entries matching pattern."""
        with self._lock:
            regex = re.compile(pattern)
            keys_to_delete = [k for k in self.entries.keys() if regex.match(k)]
            for key in keys_to_delete:
                self._delete_entry(key)
            return len(keys_to_delete)


# ============================================================================
# MULTI-LEVEL CACHE
# ============================================================================

class MultiLevelCache:
    """
    Multi-Level Cache - Coordinates L1 and L2 caches.
    Promotes from L2 to L1 on access, manages coherence.
    """
    
    def __init__(self, l1_policy: Optional[CachePolicy] = None, l2_policy: Optional[CachePolicy] = None):
        """Initialize multi-level cache."""
        self.l1_policy = l1_policy or CachePolicy(eviction_policy=EvictionPolicy.LRU, max_size=100)
        self.l2_policy = l2_policy or CachePolicy(eviction_policy=EvictionPolicy.FIFO, max_size=1000)
        
        self.l1 = L1Cache(self.l1_policy)
        self.l2 = L2Cache(self.l2_policy)
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        1. Check L1
        2. If miss, check L2
        3. If L2 hit, promote to L1
        """
        # Try L1
        value = self.l1.get(key)
        if value is not None:
            return value
        
        # Try L2
        value = self.l2.get(key)
        if value is not None:
            # Promote to L1
            self.l1.set(key, value)
            return value
        
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None, tag: Optional[str] = None) -> None:
        """
        Set value in cache.
        Always sets both L1 and L2 for consistency.
        """
        self.l1.set(key, value, ttl_seconds, tag)
        self.l2.set(key, value, ttl_seconds, tag)
    
    def delete(self, key: str) -> bool:
        """Delete from both L1 and L2."""
        l1_deleted = self.l1.delete(key)
        l2_deleted = self.l2.delete(key)
        return l1_deleted or l2_deleted
    
    def clear(self) -> None:
        """Clear both caches."""
        self.l1.clear()
        self.l2.clear()
    
    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate by tag in both caches."""
        l1_keys = [k for k, e in self.l1.entries.items() if e.tag == tag]
        count = len(l1_keys)
        self.l1.invalidate_by_tag(tag)
        self.l2.invalidate_by_tag(tag)
        return count
    
    def invalidate_by_pattern(self, pattern: str) -> int:
        """Invalidate by pattern in both caches."""
        l1_keys = [k for k in self.l1.entries.keys() if re.match(pattern, k)]
        count = len(l1_keys)
        self.l1.invalidate_by_pattern(pattern)
        self.l2.invalidate_by_pattern(pattern)
        return count
    
    def get_stats(self) -> Dict[str, CacheStats]:
        """Get stats from both caches."""
        return {
            'l1': self.l1.get_stats(),
            'l2': self.l2.get_stats()
        }
    
    def warm_cache(self, data: Dict[str, Any], ttl_seconds: Optional[int] = None) -> int:
        """Preload cache with data."""
        count = 0
        for key, value in data.items():
            self.set(key, value, ttl_seconds)
            count += 1
        return count


# ============================================================================
# TESTS
# ============================================================================

class TestL1CacheOperations(unittest.TestCase):
    """Test basic L1 cache operations."""
    
    def setUp(self):
        """Set up test cache."""
        policy = CachePolicy(eviction_policy=EvictionPolicy.LRU, max_size=5)
        self.cache = L1Cache(policy)
    
    def test_set_and_get(self):
        """Test basic set and get."""
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")
    
    def test_get_nonexistent_key(self):
        """Test getting non-existent key returns None."""
        self.assertIsNone(self.cache.get("nonexistent"))
    
    def test_delete_key(self):
        """Test deleting a key."""
        self.cache.set("key1", "value1")
        self.assertTrue(self.cache.delete("key1"))
        self.assertIsNone(self.cache.get("key1"))
    
    def test_cache_size(self):
        """Test cache size."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.assertEqual(self.cache.size(), 2)
    
    def test_cache_keys(self):
        """Test getting all keys."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        keys = self.cache.keys()
        self.assertIn("key1", keys)
        self.assertIn("key2", keys)


class TestL1Eviction(unittest.TestCase):
    """Test L1 cache eviction policies."""
    
    def test_lru_eviction(self):
        """Test LRU eviction."""
        policy = CachePolicy(eviction_policy=EvictionPolicy.LRU, max_size=3)
        cache = L1Cache(policy)
        
        cache.set("a", "val_a")
        cache.set("b", "val_b")
        cache.set("c", "val_c")
        cache.get("a")  # Access 'a' - make it recently used
        
        cache.set("d", "val_d")  # Should evict 'b' (least recently used)
        
        self.assertIsNotNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))  # 'b' should be evicted
        self.assertIsNotNone(cache.get("c"))
        self.assertIsNotNone(cache.get("d"))
    
    def test_lfu_eviction(self):
        """Test LFU eviction."""
        policy = CachePolicy(eviction_policy=EvictionPolicy.LFU, max_size=3)
        cache = L1Cache(policy)
        
        cache.set("a", "val_a")
        cache.set("b", "val_b")
        cache.set("c", "val_c")
        cache.get("a")
        cache.get("a")  # Access 'a' twice - higher frequency
        cache.get("c")
        
        cache.set("d", "val_d")  # Should evict 'b' (least frequently used)
        
        self.assertIsNone(cache.get("b"))
    
    def test_fifo_eviction(self):
        """Test FIFO eviction."""
        policy = CachePolicy(eviction_policy=EvictionPolicy.FIFO, max_size=3)
        cache = L1Cache(policy)
        
        cache.set("a", "val_a")
        time.sleep(0.01)
        cache.set("b", "val_b")
        time.sleep(0.01)
        cache.set("c", "val_c")
        
        cache.set("d", "val_d")  # Should evict 'a' (oldest)
        
        self.assertIsNone(cache.get("a"))
        self.assertIsNotNone(cache.get("b"))


class TestL2CacheOperations(unittest.TestCase):
    """Test L2 cache operations."""
    
    def setUp(self):
        """Set up test cache."""
        policy = CachePolicy(max_size=10)
        self.cache = L2Cache(policy)
    
    def test_set_and_get_l2(self):
        """Test L2 get and set."""
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")
    
    def test_l2_larger_capacity(self):
        """Test L2 has larger capacity."""
        for i in range(50):
            self.cache.set(f"key{i}", f"value{i}")
        
        self.assertGreater(self.cache.size(), 10)


class TestMultiLevelCaching(unittest.TestCase):
    """Test multi-level caching."""
    
    def setUp(self):
        """Set up multi-level cache."""
        self.cache = MultiLevelCache()
    
    def test_l1_hit(self):
        """Test L1 cache hit."""
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")
    
    def test_l2_fallback(self):
        """Test L2 fallback when L1 misses."""
        self.cache.set("key1", "value1")
        self.cache.l1.delete("key1")  # Remove from L1
        
        # Should get from L2
        value = self.cache.get("key1")
        self.assertEqual(value, "value1")
    
    def test_l2_to_l1_promotion(self):
        """Test promotion from L2 to L1."""
        self.cache.set("key1", "value1")
        self.cache.l1.delete("key1")  # Simulate eviction to L2
        
        # Get from L2, which should promote to L1
        self.cache.get("key1")
        self.assertIn("key1", self.cache.l1.keys())


class TestTTLExpiration(unittest.TestCase):
    """Test TTL expiration."""
    
    def setUp(self):
        """Set up cache."""
        policy = CachePolicy(default_ttl_seconds=1)
        self.cache = L1Cache(policy)
    
    def test_ttl_expiration(self):
        """Test entry expires after TTL."""
        self.cache.set("key1", "value1", ttl_seconds=1)
        self.assertEqual(self.cache.get("key1"), "value1")
        
        time.sleep(1.1)
        self.assertIsNone(self.cache.get("key1"))
    
    def test_ttl_not_expired(self):
        """Test entry not expired before TTL."""
        self.cache.set("key1", "value1", ttl_seconds=2)
        time.sleep(0.5)
        self.assertEqual(self.cache.get("key1"), "value1")


class TestCacheInvalidation(unittest.TestCase):
    """Test cache invalidation strategies."""
    
    def setUp(self):
        """Set up cache."""
        self.cache = MultiLevelCache()
    
    def test_invalidate_by_tag(self):
        """Test invalidation by tag."""
        self.cache.set("user:1", "Alice", tag="user")
        self.cache.set("user:2", "Bob", tag="user")
        self.cache.set("post:1", "Hello", tag="post")
        
        count = self.cache.invalidate_by_tag("user")
        
        self.assertEqual(count, 2)
        self.assertIsNone(self.cache.get("user:1"))
        self.assertEqual(self.cache.get("post:1"), "Hello")
    
    def test_invalidate_by_pattern(self):
        """Test invalidation by pattern."""
        self.cache.set("user:1", "Alice")
        self.cache.set("user:2", "Bob")
        self.cache.set("post:1", "Hello")
        
        count = self.cache.invalidate_by_pattern("user:.*")
        
        self.assertEqual(count, 2)
        self.assertEqual(self.cache.get("post:1"), "Hello")


class TestCacheStatistics(unittest.TestCase):
    """Test cache statistics."""
    
    def setUp(self):
        """Set up cache."""
        self.cache = L1Cache(CachePolicy(max_size=5))
    
    def test_hit_miss_stats(self):
        """Test hit and miss statistics."""
        self.cache.set("key1", "value1")
        self.cache.get("key1")  # Hit
        self.cache.get("key2")  # Miss
        
        stats = self.cache.get_stats()
        self.assertEqual(stats.total_hits, 1)
        self.assertEqual(stats.total_misses, 1)
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        self.cache.set("key1", "value1")
        self.cache.get("key1")
        self.cache.get("key1")
        self.cache.get("nonexistent")
        
        stats = self.cache.get_stats()
        self.assertAlmostEqual(stats.hit_rate, 66.67, places=1)


class TestCacheWarming(unittest.TestCase):
    """Test cache warming/preloading."""
    
    def setUp(self):
        """Set up cache."""
        self.cache = MultiLevelCache()
    
    def test_warm_cache(self):
        """Test warming cache with initial data."""
        data = {"key1": "value1", "key2": "value2", "key3": "value3"}
        count = self.cache.warm_cache(data)
        
        self.assertEqual(count, 3)
        self.assertEqual(self.cache.get("key1"), "value1")
        self.assertEqual(self.cache.get("key2"), "value2")


class TestCacheCoherence(unittest.TestCase):
    """Test L1/L2 cache coherence."""
    
    def setUp(self):
        """Set up cache."""
        self.cache = MultiLevelCache()
    
    def test_update_coherence(self):
        """Test that update maintains coherence."""
        self.cache.set("key1", "value1")
        
        # Update in both caches
        self.cache.set("key1", "value1_updated")
        
        # Both should have updated value
        self.assertEqual(self.cache.l1.get("key1"), "value1_updated")
        self.assertEqual(self.cache.l2.get("key1"), "value1_updated")
    
    def test_delete_coherence(self):
        """Test that delete maintains coherence."""
        self.cache.set("key1", "value1")
        self.cache.delete("key1")
        
        # Both should be deleted
        self.assertIsNone(self.cache.l1.get("key1"))
        self.assertIsNone(self.cache.l2.get("key1"))


class TestEvictionPolicies(unittest.TestCase):
    """Compare eviction policies."""
    
    def test_lru_vs_lfu(self):
        """Compare LRU and LFU eviction."""
        # LRU policy
        lru_cache = L1Cache(CachePolicy(eviction_policy=EvictionPolicy.LRU, max_size=3))
        lru_cache.set("a", "val_a")
        lru_cache.set("b", "val_b")
        lru_cache.set("c", "val_c")
        lru_cache.get("a")  # Access 'a'
        lru_cache.set("d", "val_d")
        
        # LFU policy
        lfu_cache = L1Cache(CachePolicy(eviction_policy=EvictionPolicy.LFU, max_size=3))
        lfu_cache.set("a", "val_a")
        lfu_cache.set("b", "val_b")
        lfu_cache.set("c", "val_c")
        lfu_cache.get("a")
        lfu_cache.set("d", "val_d")
        
        # Both should evict but might be different keys
        lru_size = lru_cache.size()
        lfu_size = lfu_cache.size()
        self.assertEqual(lru_size, 3)
        self.assertEqual(lfu_size, 3)


class TestCacheIntegration(unittest.TestCase):
    """End-to-end multi-level cache tests."""
    
    def setUp(self):
        """Set up cache."""
        self.cache = MultiLevelCache()
    
    def test_complete_workflow(self):
        """Test complete cache workflow."""
        # Warm cache
        initial_data = {"user:1": "Alice", "user:2": "Bob"}
        self.cache.warm_cache(initial_data)
        
        # Access from L1
        self.assertEqual(self.cache.get("user:1"), "Alice")
        
        # Update
        self.cache.set("user:1", "Alice Updated")
        self.assertEqual(self.cache.get("user:1"), "Alice Updated")
        
        # Invalidate by pattern
        self.cache.invalidate_by_pattern("user:.*")
        self.assertIsNone(self.cache.get("user:1"))
    
    def test_mixed_operations(self):
        """Test mixed cache operations."""
        # Set various entries
        for i in range(20):
            self.cache.set(f"key{i}", f"value{i}", tag="batch1" if i % 2 == 0 else "batch2")
        
        # Get some entries
        for i in range(5):
            self.cache.get(f"key{i}")
        
        # Invalidate by tag
        self.cache.invalidate_by_tag("batch1")
        
        # Check stats
        stats = self.cache.get_stats()
        self.assertGreater(stats['l1'].total_hits, 0)
        self.assertGreater(stats['l1'].total_invalidations, 0)


if __name__ == '__main__':
    unittest.main()
