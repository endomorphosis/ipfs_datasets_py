"""
Bounded cache implementation with TTL and LRU eviction for logic converters.

This module provides a production-ready cache with:
- TTL (time-to-live) expiration
- LRU (Least Recently Used) eviction
- Maximum size limits
- Thread-safety
- Comprehensive statistics
"""

import time
import threading
from collections import OrderedDict
from typing import Any, Dict, Generic, Optional, TypeVar
from dataclasses import dataclass

T = TypeVar('T')


@dataclass
class CacheEntry(Generic[T]):
    """Entry in the cache with value and timestamp."""
    value: T
    timestamp: float
    access_count: int = 0
    
    def is_expired(self, ttl: float) -> bool:
        """Check if entry has expired based on TTL."""
        if ttl <= 0:  # TTL of 0 means no expiration
            return False
        return time.time() - self.timestamp > ttl
    
    def touch(self) -> None:
        """Update access count when entry is accessed."""
        self.access_count += 1


class BoundedCache(Generic[T]):
    """
    Thread-safe bounded cache with TTL and LRU eviction.
    
    Features:
    - Maximum size limit (prevents unbounded growth)
    - TTL-based expiration (prevents stale entries)
    - LRU eviction policy (when max size exceeded)
    - Thread-safe operations (RLock for concurrent access)
    - Comprehensive statistics
    
    Example:
        ```python
        # Create cache with 1000 max entries and 1 hour TTL
        cache = BoundedCache(maxsize=1000, ttl=3600)
        
        # Store value
        cache.set("key1", "value1")
        
        # Retrieve value
        value = cache.get("key1")  # Returns "value1"
        
        # Get statistics
        stats = cache.get_stats()
        print(f"Hit rate: {stats['hit_rate']:.1%}")
        ```
    """
    
    def __init__(self, maxsize: int = 1000, ttl: float = 3600):
        """
        Initialize bounded cache.
        
        Args:
            maxsize: Maximum number of entries (default: 1000, 0 = unlimited)
            ttl: Time-to-live in seconds (default: 3600, 0 = no expiration)
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        
        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
    
    def get(self, key: str) -> Optional[T]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value if exists and not expired, None otherwise
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            
            # Check expiration
            if entry.is_expired(self.ttl):
                self._cache.pop(key)
                self._expirations += 1
                self._misses += 1
                return None
            
            # Move to end (mark as recently used)
            self._cache.move_to_end(key)
            entry.touch()
            self._hits += 1
            
            return entry.value
    
    def set(self, key: str, value: T) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            # If key exists, update it and move to end
            if key in self._cache:
                self._cache[key] = CacheEntry(value, time.time())
                self._cache.move_to_end(key)
                return
            
            # If at capacity, evict least recently used
            if self.maxsize > 0 and len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)  # Remove oldest (least recently used)
                self._evictions += 1
            
            # Add new entry
            self._cache[key] = CacheEntry(value, time.time())
    
    def clear(self) -> None:
        """Clear all entries from cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0
    
    def remove(self, key: str) -> bool:
        """
        Remove specific key from cache.
        
        Args:
            key: Cache key to remove
            
        Returns:
            True if key was removed, False if not found
        """
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
                return True
            return False
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            if self.ttl <= 0:
                return 0
            
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired(self.ttl)
            ]
            
            for key in expired_keys:
                self._cache.pop(key)
                self._expirations += 1
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics including:
            - size: Current number of entries
            - maxsize: Maximum allowed entries
            - ttl: Time-to-live in seconds
            - hits: Number of cache hits
            - misses: Number of cache misses
            - evictions: Number of LRU evictions
            - expirations: Number of TTL expirations
            - hit_rate: Cache hit rate (0-1)
            - total_requests: Total get requests
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "ttl": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "hit_rate": hit_rate,
                "total_requests": total_requests
            }
    
    def __len__(self) -> int:
        """Get current cache size."""
        return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache (not expired)."""
        with self._lock:
            if key not in self._cache:
                return False
            entry = self._cache[key]
            if entry.is_expired(self.ttl):
                self._cache.pop(key)
                self._expirations += 1
                return False
            return True
