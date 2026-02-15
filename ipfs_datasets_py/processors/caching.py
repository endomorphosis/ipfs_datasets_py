"""
Smart caching system for processors.

This module provides an intelligent caching system with TTL, size-based eviction,
and multiple eviction policies (LRU, LFU, FIFO).
"""

from __future__ import annotations

import sys
import logging
from enum import Enum
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import OrderedDict

logger = logging.getLogger(__name__)


class EvictionPolicy(Enum):
    """
    Cache eviction policies.
    
    - LRU: Least Recently Used - evict entries not accessed recently
    - LFU: Least Frequently Used - evict entries accessed least often
    - FIFO: First In First Out - evict oldest entries
    """
    LRU = "lru"
    LFU = "lfu"
    FIFO = "fifo"


@dataclass
class CacheEntry:
    """
    Cache entry with metadata.
    
    Attributes:
        key: Cache key
        value: Cached value
        created_at: When entry was created
        last_accessed: When entry was last accessed
        access_count: Number of times accessed
        size_bytes: Approximate size in bytes
    """
    key: str
    value: Any
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    size_bytes: int = 0
    
    def update_access(self):
        """Update access metadata."""
        self.last_accessed = datetime.now()
        self.access_count += 1


@dataclass
class CacheStatistics:
    """
    Cache statistics.
    
    Attributes:
        hits: Number of cache hits
        misses: Number of cache misses
        evictions: Number of evictions
        total_size_bytes: Current cache size in bytes
        entry_count: Current number of entries
    """
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size_bytes: int = 0
    entry_count: int = 0
    
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'hits': self.hits,
            'misses': self.misses,
            'evictions': self.evictions,
            'total_size_bytes': self.total_size_bytes,
            'entry_count': self.entry_count,
            'hit_rate': self.hit_rate()
        }


class SmartCache:
    """
    Intelligent cache with TTL, size limits, and configurable eviction.
    
    Features:
    - TTL (time-to-live) expiration
    - Size-based eviction with configurable policies
    - Access tracking for LRU/LFU
    - Statistics collection
    - Cache pre-warming support
    
    Example:
        >>> cache = SmartCache(max_size_mb=100, ttl_seconds=3600, eviction_policy="lru")
        >>> cache.put("key1", result1)
        >>> result = cache.get("key1")
        >>> stats = cache.get_statistics()
        >>> print(f"Hit rate: {stats.hit_rate():.2%}")
    """
    
    def __init__(
        self,
        max_size_mb: int = 100,
        ttl_seconds: int = 3600,
        eviction_policy: str = "lru"
    ):
        """
        Initialize smart cache.
        
        Args:
            max_size_mb: Maximum cache size in megabytes
            ttl_seconds: Time-to-live in seconds (0 = no expiration)
            eviction_policy: Eviction policy ("lru", "lfu", or "fifo")
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.ttl = timedelta(seconds=ttl_seconds) if ttl_seconds > 0 else None
        
        try:
            self.eviction_policy = EvictionPolicy(eviction_policy.lower())
        except ValueError:
            logger.warning(f"Invalid eviction policy '{eviction_policy}', defaulting to LRU")
            self.eviction_policy = EvictionPolicy.LRU
        
        self._cache: dict[str, CacheEntry] = {}
        self._access_order: OrderedDict[str, None] = OrderedDict()  # For LRU
        self._stats = CacheStatistics()
        
        logger.info(
            f"SmartCache initialized: "
            f"max_size={max_size_mb}MB, "
            f"ttl={ttl_seconds}s, "
            f"eviction={self.eviction_policy.value}"
        )
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        if key not in self._cache:
            self._stats.misses += 1
            return None
        
        entry = self._cache[key]
        
        # Check TTL
        if self.ttl and datetime.now() - entry.created_at > self.ttl:
            logger.debug(f"Cache entry expired: {key}")
            self._remove_entry(key)
            self._stats.misses += 1
            return None
        
        # Update access metadata
        entry.update_access()
        
        # Update LRU order
        if self.eviction_policy == EvictionPolicy.LRU:
            self._access_order.move_to_end(key)
        
        self._stats.hits += 1
        return entry.value
    
    def put(self, key: str, value: Any) -> None:
        """
        Add value to cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        # Calculate size
        size = sys.getsizeof(value)
        
        # If this key already exists, remove old entry first
        if key in self._cache:
            self._remove_entry(key)
        
        # Evict entries if needed to make space
        while (self._stats.total_size_bytes + size > self.max_size_bytes and 
               self._stats.entry_count > 0):
            self._evict_one()
        
        # If single entry is too large, don't cache it
        if size > self.max_size_bytes:
            logger.warning(
                f"Entry too large to cache: {size} bytes > {self.max_size_bytes} bytes"
            )
            return
        
        # Create and add entry
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=0,
            size_bytes=size
        )
        
        self._cache[key] = entry
        self._access_order[key] = None
        self._stats.total_size_bytes += size
        self._stats.entry_count += 1
        
        logger.debug(
            f"Cached entry: {key} ({size} bytes, "
            f"cache now {self._stats.entry_count} entries, "
            f"{self._stats.total_size_bytes / (1024*1024):.2f} MB)"
        )
    
    def _remove_entry(self, key: str) -> None:
        """Remove entry from cache."""
        if key in self._cache:
            entry = self._cache.pop(key)
            self._access_order.pop(key, None)
            self._stats.total_size_bytes -= entry.size_bytes
            self._stats.entry_count -= 1
    
    def _evict_one(self) -> None:
        """Evict one entry based on policy."""
        if not self._cache:
            return
        
        if self.eviction_policy == EvictionPolicy.LRU:
            # Evict least recently accessed
            key_to_evict = next(iter(self._access_order))
        
        elif self.eviction_policy == EvictionPolicy.LFU:
            # Evict least frequently accessed
            key_to_evict = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].access_count
            )
        
        else:  # FIFO
            # Evict oldest (first created)
            key_to_evict = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].created_at
            )
        
        logger.debug(f"Evicting entry: {key_to_evict} (policy={self.eviction_policy.value})")
        self._remove_entry(key_to_evict)
        self._stats.evictions += 1
    
    def clear(self) -> None:
        """Clear all cache entries."""
        count = self._stats.entry_count
        self._cache.clear()
        self._access_order.clear()
        self._stats.total_size_bytes = 0
        self._stats.entry_count = 0
        logger.info(f"Cache cleared: {count} entries removed")
    
    def remove(self, key: str) -> bool:
        """
        Remove specific entry from cache.
        
        Args:
            key: Cache key to remove
            
        Returns:
            True if entry was removed, False if not found
        """
        if key in self._cache:
            self._remove_entry(key)
            return True
        return False
    
    def has_key(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        if key not in self._cache:
            return False
        
        entry = self._cache[key]
        if self.ttl and datetime.now() - entry.created_at > self.ttl:
            self._remove_entry(key)
            return False
        
        return True
    
    def get_statistics(self) -> CacheStatistics:
        """
        Get cache statistics.
        
        Returns:
            CacheStatistics object
        """
        return self._stats
    
    def prewarm(self, entries: dict[str, Any]) -> None:
        """
        Pre-warm cache with entries.
        
        Args:
            entries: Dictionary of key-value pairs to cache
        """
        logger.info(f"Pre-warming cache with {len(entries)} entries...")
        for key, value in entries.items():
            self.put(key, value)
        logger.info(
            f"Cache pre-warmed: {self._stats.entry_count} entries, "
            f"{self._stats.total_size_bytes / (1024*1024):.2f} MB"
        )
    
    def cleanup_expired(self) -> int:
        """
        Remove expired entries.
        
        Returns:
            Number of entries removed
        """
        if not self.ttl:
            return 0
        
        expired_keys = []
        now = datetime.now()
        
        for key, entry in self._cache.items():
            if now - entry.created_at > self.ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            self._remove_entry(key)
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired entries")
        
        return len(expired_keys)
    
    def get_size_mb(self) -> float:
        """Get current cache size in megabytes."""
        return self._stats.total_size_bytes / (1024 * 1024)
    
    def get_usage_percent(self) -> float:
        """Get cache usage as percentage of max size."""
        if self.max_size_bytes == 0:
            return 0.0
        return (self._stats.total_size_bytes / self.max_size_bytes) * 100
