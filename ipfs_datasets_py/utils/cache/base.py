"""Base cache abstractions for unified caching infrastructure.

This module provides abstract base classes for implementing different cache backends
with consistent interfaces across local, distributed, and specialized caches.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional, List
from threading import RLock


class CacheBackend(Enum):
    """Supported cache backend types."""
    MEMORY = "memory"
    FILE = "file"
    REDIS = "redis"
    P2P = "p2p"


@dataclass
class CacheEntry:
    """Base cache entry with metadata.
    
    Attributes:
        key: Unique cache key
        value: Cached value
        created_at: Creation timestamp
        expires_at: Expiration timestamp
        access_count: Number of times accessed
        last_accessed: Last access timestamp
        metadata: Additional metadata
    """
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(minutes=5))
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired.
        
        Returns:
            True if expired, False otherwise
        """
        return datetime.now() > self.expires_at
    
    def touch(self) -> None:
        """Update access metadata."""
        self.access_count += 1
        self.last_accessed = datetime.now()


@dataclass
class CacheStats:
    """Cache statistics.
    
    Attributes:
        hits: Number of cache hits
        misses: Number of cache misses
        sets: Number of set operations
        evictions: Number of evictions
        errors: Number of errors
        size: Current cache size
        hit_rate: Cache hit rate (0.0 to 1.0)
    """
    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0
    errors: int = 0
    size: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate.
        
        Returns:
            Hit rate between 0.0 and 1.0
        """
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class BaseCache(ABC):
    """Abstract base class for cache implementations.
    
    Provides common interface for all cache backends with thread-safe operations,
    statistics tracking, and consistent behavior.
    """
    
    def __init__(
        self,
        maxsize: int = 1000,
        default_ttl: int = 300,
        name: Optional[str] = None
    ):
        """Initialize base cache.
        
        Args:
            maxsize: Maximum number of entries (default: 1000)
            default_ttl: Default TTL in seconds (default: 300)
            name: Optional cache name for logging
        """
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self.name = name or self.__class__.__name__
        self._lock = RLock()
        self._stats = CacheStats()
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        pass
    
    @abstractmethod
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        **metadata
    ) -> None:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default_ttl if None)
            **metadata: Additional metadata to store
        """
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False if not found
        """
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries."""
        pass
    
    @abstractmethod
    def size(self) -> int:
        """Get current cache size.
        
        Returns:
            Number of entries in cache
        """
        pass
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if exists and not expired, False otherwise
        """
        return self.get(key) is not None
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics.
        
        Returns:
            Current cache statistics
        """
        with self._lock:
            self._stats.size = self.size()
            return self._stats
    
    def _record_hit(self) -> None:
        """Record cache hit."""
        with self._lock:
            self._stats.hits += 1
    
    def _record_miss(self) -> None:
        """Record cache miss."""
        with self._lock:
            self._stats.misses += 1
    
    def _record_set(self) -> None:
        """Record cache set."""
        with self._lock:
            self._stats.sets += 1
    
    def _record_eviction(self) -> None:
        """Record cache eviction."""
        with self._lock:
            self._stats.evictions += 1
    
    def _record_error(self) -> None:
        """Record cache error."""
        with self._lock:
            self._stats.errors += 1


class DistributedCache(BaseCache):
    """Abstract base for distributed cache implementations.
    
    Extends BaseCache with methods for distributed operations like broadcasting
    and peer synchronization.
    """
    
    @abstractmethod
    def broadcast(self, key: str, value: Any, **metadata) -> None:
        """Broadcast cache entry to peers.
        
        Args:
            key: Cache key
            value: Value to broadcast
            **metadata: Additional metadata
        """
        pass
    
    @abstractmethod
    def sync_with_peers(self, max_age: Optional[int] = None) -> int:
        """Synchronize cache with peers.
        
        Args:
            max_age: Only sync entries younger than this (seconds)
            
        Returns:
            Number of entries synchronized
        """
        pass
    
    @abstractmethod
    def get_peer_count(self) -> int:
        """Get number of connected peers.
        
        Returns:
            Number of active peers
        """
        pass
