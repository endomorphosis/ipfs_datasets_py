"""Local TTL-based cache implementation.

This module provides a thread-safe, TTL-based local cache implementation
that consolidates functionality from the old query_cache.py module.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from cachetools import TTLCache

from .base import BaseCache, CacheEntry, CacheStats

logger = logging.getLogger(__name__)


class LocalCache(BaseCache):
    """Thread-safe TTL-based local cache.
    
    Consolidates functionality from utils/query_cache.py with enhanced features:
    - Automatic expiration based on TTL
    - Thread-safe operations
    - Statistics tracking
    - Flexible key generation
    
    Example:
        >>> cache = LocalCache(maxsize=100, default_ttl=300)
        >>> cache.set("key", {"data": "value"})
        >>> result = cache.get("key")
        >>> stats = cache.get_stats()
        >>> print(f"Hit rate: {stats.hit_rate:.2%}")
    """
    
    def __init__(
        self,
        maxsize: int = 1000,
        default_ttl: int = 300,
        name: Optional[str] = None
    ):
        """Initialize local cache.
        
        Args:
            maxsize: Maximum number of entries (default: 1000)
            default_ttl: Default TTL in seconds (default: 300)
            name: Optional cache name for logging
            
        Raises:
            ValueError: If maxsize < 1 or default_ttl < 1
        """
        if maxsize < 1:
            raise ValueError(f"maxsize must be at least 1, got {maxsize}")
        if default_ttl < 1:
            raise ValueError(f"default_ttl must be at least 1, got {default_ttl}")
        
        super().__init__(maxsize=maxsize, default_ttl=default_ttl, name=name)
        self._cache = TTLCache(maxsize=maxsize, ttl=default_ttl)
        logger.info(f"Initialized {self.name} with maxsize={maxsize}, ttl={default_ttl}s")
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            try:
                if key in self._cache:
                    entry: CacheEntry = self._cache[key]
                    if not entry.is_expired():
                        entry.touch()
                        self._record_hit()
                        return entry.value
                    else:
                        # Remove expired entry
                        del self._cache[key]
                        self._record_eviction()
                
                self._record_miss()
                return None
                
            except Exception as e:
                logger.error(f"Error getting key {key}: {e}")
                self._record_error()
                return None
    
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
            ttl: Time-to-live in seconds. If None, uses default_ttl.
                 Note: If ttl > default_ttl, the entry may be evicted by the
                 underlying TTLCache before the custom TTL expires. For best
                 results, use ttl <= default_ttl.
            **metadata: Additional metadata to store
        """
        with self._lock:
            try:
                ttl_seconds = ttl if ttl is not None else self.default_ttl
                
                # Warn if TTL exceeds default (may cause premature eviction)
                if ttl_seconds > self.default_ttl:
                    logger.warning(
                        f"TTL {ttl_seconds}s exceeds default_ttl {self.default_ttl}s. "
                        f"Entry may be evicted early by underlying TTLCache."
                    )
                
                expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
                
                entry = CacheEntry(
                    key=key,
                    value=value,
                    expires_at=expires_at,
                    metadata=metadata
                )
                
                # Check if we need to evict
                if len(self._cache) >= self.maxsize and key not in self._cache:
                    self._record_eviction()
                
                self._cache[key] = entry
                self._record_set()
                
            except Exception as e:
                logger.error(f"Error setting key {key}: {e}")
                self._record_error()
    
    def delete(self, key: str) -> bool:
        """Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            try:
                if key in self._cache:
                    del self._cache[key]
                    return True
                return False
            except Exception as e:
                logger.error(f"Error deleting key {key}: {e}")
                self._record_error()
                return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            logger.info(f"Cleared {self.name} cache")
    
    def size(self) -> int:
        """Get current cache size.
        
        Returns:
            Number of entries in cache
        """
        with self._lock:
            return len(self._cache)
    
    def make_key(self, *args, **kwargs) -> str:
        """Generate cache key from arguments.
        
        Supports strings, lists, dicts, and other types by converting to
        a consistent string representation and hashing if needed.
        
        Args:
            *args: Positional arguments to include in key
            **kwargs: Keyword arguments to include in key
            
        Returns:
            Cache key string
        """
        if len(args) == 1 and not kwargs and isinstance(args[0], str):
            return args[0]
        
        # Build key from args and kwargs
        parts = []
        for arg in args:
            if isinstance(arg, (str, int, float, bool)):
                parts.append(str(arg))
            elif isinstance(arg, (list, tuple)):
                parts.append(json.dumps(arg, sort_keys=True))
            elif isinstance(arg, dict):
                parts.append(json.dumps(arg, sort_keys=True))
            else:
                parts.append(str(arg))
        
        for k, v in sorted(kwargs.items()):
            parts.append(f"{k}={v}")
        
        key_str = ":".join(parts)
        
        # Hash long keys
        if len(key_str) > 200:
            return hashlib.sha256(key_str.encode()).hexdigest()
        
        return key_str


# Backward compatibility alias
class QueryCache(LocalCache):
    """Backward compatibility alias for LocalCache.
    
    DEPRECATED: Use LocalCache instead.
    This alias exists for compatibility with old code using QueryCache.
    """
    
    def __init__(self, maxsize: int = 100, ttl: int = 300):
        """Initialize QueryCache (LocalCache).
        
        Args:
            maxsize: Maximum number of entries
            ttl: Time-to-live in seconds
        """
        import warnings
        warnings.warn(
            "QueryCache is deprecated. Use LocalCache instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(maxsize=maxsize, default_ttl=ttl, name="QueryCache")
