"""
Batch 333: Distributed Cache & Memoization System
==================================================

Implements caching and memoization for optimization,
with support for distributed scenarios and invalidation.

Goal: Provide:
- In-memory caching with TTL support
- Memoization for expensive computations
- Cache statistics and metrics
- Multi-level caching strategy
"""

import pytest
import time
from typing import Dict, Any, Optional, Callable, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import hashlib


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class CacheLevel(Enum):
    """Cache hierarchy levels."""
    L1 = "l1"  # In-memory, fastest
    L2 = "l2"  # Process-level cache
    L3 = "l3"  # Distributed cache


@dataclass
class CacheEntry:
    """A single cache entry."""
    key: str
    value: Any
    created_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    ttl_seconds: Optional[float] = None
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl_seconds is None:
            return False
        elapsed = time.time() - self.created_at
        return elapsed > self.ttl_seconds
    
    def update_access(self):
        """Update access tracking."""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheStatistics:
    """Cache performance statistics."""
    total_hits: int = 0
    total_misses: int = 0
    total_evictions: int = 0
    total_invalidations: int = 0
    
    def hit_rate(self) -> float:
        """Get cache hit rate (0.0-1.0)."""
        total = self.total_hits + self.total_misses
        if total == 0:
            return 0.0
        return self.total_hits / total
    
    def efficiency_score(self) -> float:
        """Estimate cache efficiency."""
        # Hit rate weighted by access patterns
        return self.hit_rate()


# ============================================================================
# CACHE IMPLEMENTATIONS
# ============================================================================

class SimpleCache:
    """Simple in-memory cache without eviction."""
    
    def __init__(self, max_size: int = 1000):
        """Initialize cache.
        
        Args:
            max_size: Maximum cache entries
        """
        self.max_size = max_size
        self.cache: Dict[str, CacheEntry] = {}
        self.stats = CacheStatistics()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None
        """
        if key in self.cache:
            entry = self.cache[key]
            
            if entry.is_expired():
                del self.cache[key]
                self.stats.total_misses += 1
                return None
            
            entry.update_access()
            self.stats.total_hits += 1
            return entry.value
        
        self.stats.total_misses += 1
        return None
    
    def put(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds
        """
        now = time.time()
        
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=now,
            last_accessed=now,
            ttl_seconds=ttl_seconds,
        )
        
        self.cache[key] = entry
    
    def invalidate(self, key: str) -> bool:
        """Invalidate cache entry.
        
        Args:
            key: Key to invalidate
            
        Returns:
            True if entry was invalidated
        """
        if key in self.cache:
            del self.cache[key]
            self.stats.total_invalidations += 1
            return True
        return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        clear_count = len(self.cache)
        self.cache.clear()
        self.stats.total_evictions += clear_count
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)


class LRUCache(SimpleCache):
    """Least Recently Used cache with eviction."""
    
    def put(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store value with LRU eviction.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live
        """
        # Check if need to evict
        if key not in self.cache and len(self.cache) >= self.max_size:
            # Evict least recently used
            lru_key = min(
                self.cache.keys(),
                key=lambda k: self.cache[k].last_accessed
            )
            del self.cache[lru_key]
            self.stats.total_evictions += 1
        
        super().put(key, value, ttl_seconds)


class TTLCache(SimpleCache):
    """Cache with automatic TTL-based expiration."""
    
    def cleanup_expired(self) -> int:
        """Remove expired entries.
        
        Returns:
            Number of entries removed
        """
        expired_keys = [
            key for key, entry in self.cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self.cache[key]
        
        self.stats.total_evictions += len(expired_keys)
        return len(expired_keys)


# ============================================================================
# MEMOIZATION
# ============================================================================

class Memoizer:
    """Memoization decorator for expensive functions."""
    
    def __init__(self, cache: Optional[SimpleCache] = None,
                 ttl_seconds: Optional[float] = None):
        """Initialize memoizer.
        
        Args:
            cache: Cache to use (creates new if None)
            ttl_seconds: TTL for cached values
        """
        self.cache = cache or SimpleCache()
        self.ttl_seconds = ttl_seconds
        self.function_call_counts = {}
    
    def memoize(self, func: Callable) -> Callable:
        """Create memoized version of function.
        
        Args:
            func: Function to memoize
            
        Returns:
            Memoized function
        """
        func_name = func.__name__
        self.function_call_counts[func_name] = 0
        
        def memoized(*args, **kwargs):
            # Create cache key from function name and arguments
            key = self._make_cache_key(func_name, args, kwargs)
            
            # Try cache first
            cached = self.cache.get(key)
            if cached is not None:
                return cached
            
            # Call function and cache result
            result = func(*args, **kwargs)
            self.cache.put(key, result, self.ttl_seconds)
            
            self.function_call_counts[func_name] += 1
            
            return result
        
        return memoized
    
    def _make_cache_key(self, func_name: str, args: Tuple, kwargs: Dict) -> str:
        """Create cache key from function and arguments.
        
        Args:
            func_name: Function name
            args: Positional arguments
            kwargs: Keyword arguments
            
        Returns:
            Cache key string
        """
        # Create string representation of arguments
        arg_str = f"{func_name}:{args}:{sorted(kwargs.items())}"
        
        # Hash for shorter key
        hash_obj = hashlib.md5(arg_str.encode())
        return hash_obj.hexdigest()


class CacheManager:
    """Manages multiple cache levels."""
    
    def __init__(self):
        """Initialize cache manager."""
        self.caches: Dict[CacheLevel, SimpleCache] = {
            CacheLevel.L1: SimpleCache(max_size=100),    # Small, fast
            CacheLevel.L2: LRUCache(max_size=10000),     # Medium
            CacheLevel.L3: TTLCache(max_size=100000),    # Large
        }
    
    def get(self, key: str, level: CacheLevel = CacheLevel.L1) -> Optional[Any]:
        """Get from specific cache level.
        
        Args:
            key: Cache key
            level: Cache level
            
        Returns:
            Cached value or None
        """
        return self.caches[level].get(key)
    
    def put(self, key: str, value: Any,
            level: CacheLevel = CacheLevel.L1,
            ttl_seconds: Optional[float] = None) -> None:
        """Store in specific cache level.
        
        Args:
            key: Cache key
            value: Value to cache
            level: Cache level
            ttl_seconds: TTL in seconds
        """
        self.caches[level].put(key, value, ttl_seconds)
    
    def get_with_fallback(self, key: str) -> Optional[Any]:
        """Get from cache with multi-level fallback.
        
        Args:
            key: Cache key
            
        Returns:
            Value from L1, L2, or L3 in that order
        """
        # Try L1 (fastest)
        value = self.caches[CacheLevel.L1].get(key)
        if value is not None:
            return value
        
        # Try L2
        value = self.caches[CacheLevel.L2].get(key)
        if value is not None:
            # Promote to L1
            self.caches[CacheLevel.L1].put(key, value)
            return value
        
        # Try L3
        value = self.caches[CacheLevel.L3].get(key)
        if value is not None:
            # Promote to L1 and L2
            self.caches[CacheLevel.L1].put(key, value)
            self.caches[CacheLevel.L2].put(key, value)
            return value
        
        return None
    
    def get_statistics(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics from all cache levels.
        
        Returns:
            Dict of stats by cache level
        """
        return {
            level.value: {
                "size": cache.size(),
                "hits": cache.stats.total_hits,
                "misses": cache.stats.total_misses,
                "hit_rate": cache.stats.hit_rate(),
                "evictions": cache.stats.total_evictions,
            }
            for level, cache in self.caches.items()
        }


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestCacheEntry:
    """Test CacheEntry."""
    
    def test_entry_not_expired(self):
        """Test non-expired entry."""
        entry = CacheEntry("key", "value", created_at=time.time(), ttl_seconds=10.0)
        assert not entry.is_expired()
    
    def test_entry_expired(self):
        """Test expired entry."""
        entry = CacheEntry(
            "key", "value",
            created_at=time.time() - 20,
            ttl_seconds=10.0
        )
        assert entry.is_expired()
    
    def test_access_tracking(self):
        """Test access tracking."""
        entry = CacheEntry("key", "value")
        
        initial_count = entry.access_count
        entry.update_access()
        
        assert entry.access_count == initial_count + 1


class TestSimpleCache:
    """Test simple cache."""
    
    def test_basic_put_get(self):
        """Test basic cache operations."""
        cache = SimpleCache()
        
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"
    
    def test_cache_miss(self):
        """Test cache miss."""
        cache = SimpleCache()
        
        assert cache.get("nonexistent") is None
    
    def test_cache_statistics(self):
        """Test cache statistics."""
        cache = SimpleCache()
        
        cache.put("key", "value")
        cache.get("key")  # Hit
        cache.get("key")  # Hit
        cache.get("missing")  # Miss
        
        assert cache.stats.total_hits == 2
        assert cache.stats.total_misses == 1
        assert cache.stats.hit_rate() > 0.5
    
    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = SimpleCache()
        
        cache.put("key", "value", ttl_seconds=0.1)
        assert cache.get("key") == "value"
        
        time.sleep(0.2)
        assert cache.get("key") is None
    
    def test_invalidation(self):
        """Test cache invalidation."""
        cache = SimpleCache()
        
        cache.put("key", "value")
        assert cache.invalidate("key")
        assert cache.get("key") is None
    
    def test_clear(self):
        """Test clearing cache."""
        cache = SimpleCache()
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        cache.clear()
        
        assert cache.size() == 0


class TestLRUCache:
    """Test LRU cache."""
    
    def test_lru_eviction(self):
        """Test LRU eviction."""
        cache = LRUCache(max_size=3)
        
        cache.put("key1", "value1")
        time.sleep(0.01)
        cache.put("key2", "value2")
        time.sleep(0.01)
        cache.put("key3", "value3")
        
        # Access key1 to make it recent
        cache.get("key1")
        
        # Add key4, should evict key2 (least recently used)
        cache.put("key4", "value4")
        
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"


class TestTTLCache:
    """Test TTL cache."""
    
    def test_cleanup_expired(self):
        """Test cleaning up expired entries."""
        cache = TTLCache()
        
        cache.put("key1", "value1", ttl_seconds=0.1)
        cache.put("key2", "value2", ttl_seconds=1.0)  # Won't expire
        
        time.sleep(0.2)
        
        removed = cache.cleanup_expired()
        
        assert removed == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"


class TestMemoizer:
    """Test memoization."""
    
    def test_basic_memoization(self):
        """Test basic memoization."""
        cache = SimpleCache()
        memoizer = Memoizer(cache)
        
        call_count = 0
        
        @memoizer.memoize
        def expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        # First call
        result1 = expensive_func(5)
        assert result1 == 10
        assert call_count == 1
        
        # Second call (from cache)
        result2 = expensive_func(5)
        assert result2 == 10
        assert call_count == 1  # Not incremented
    
    def test_memoization_with_different_args(self):
        """Test memoization with different arguments."""
        memoizer = Memoizer()
        
        call_count = 0
        
        @memoizer.memoize
        def func(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        func(1, 2)
        func(1, 2)  # Same args, from cache
        func(2, 3)  # Different args
        
        assert call_count == 2
    
    def test_memoization_with_ttl(self):
        """Test memoization with TTL."""
        memoizer = Memoizer(ttl_seconds=0.1)
        
        call_count = 0
        
        @memoizer.memoize
        def func():
            nonlocal call_count
            call_count += 1
            return "result"
        
        func()
        assert call_count == 1
        
        time.sleep(0.2)
        func()  # TTL expired, called again
        assert call_count == 2


class TestCacheManager:
    """Test cache manager."""
    
    def test_multi_level_put_get(self):
        """Test putting and getting from different levels."""
        manager = CacheManager()
        
        manager.put("key1", "value1", CacheLevel.L1)
        manager.put("key2", "value2", CacheLevel.L2)
        manager.put("key3", "value3", CacheLevel.L3)
        
        assert manager.get("key1", CacheLevel.L1) == "value1"
        assert manager.get("key2", CacheLevel.L2) == "value2"
        assert manager.get("key3", CacheLevel.L3) == "value3"
    
    def test_fallback_lookup(self):
        """Test multi-level fallback."""
        manager = CacheManager()
        
        # Put in L3 only
        manager.put("key", "value", CacheLevel.L3)
        
        # Get with fallback should find it
        value = manager.get_with_fallback("key")
        assert value == "value"
        
        # Now should be in L1 and L2 too
        assert manager.get("key", CacheLevel.L1) == "value"
        assert manager.get("key", CacheLevel.L2) == "value"
    
    def test_statistics(self):
        """Test statistics collection."""
        manager = CacheManager()
        
        manager.put("key", "value", CacheLevel.L1)
        manager.get("key", CacheLevel.L1)
        
        stats = manager.get_statistics()
        
        assert "l1" in stats
        assert stats["l1"]["size"] == 1
        assert stats["l1"]["hits"] >= 1
