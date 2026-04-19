"""Query cache module - DEPRECATED.

This module is maintained for backward compatibility only.
Use ipfs_datasets_py.utils.cache.LocalCache instead.

The QueryCache class has been replaced by LocalCache from utils.cache,
which provides the same functionality with additional features:
- Better thread safety
- Statistics tracking
- TTL-based expiration
- Integration with GitHub cache
- P2P cache support (via P2PCache)

Migration Guide:
    Old code:
    >>> from ipfs_datasets_py.utils.query_cache import QueryCache
    >>> cache = QueryCache()
    
    New code:
    >>> from ipfs_datasets_py.utils.cache import LocalCache
    >>> cache = LocalCache()
"""

from functools import wraps
from typing import Any, Callable, Optional
import warnings

# Issue deprecation warning
warnings.warn(
    "ipfs_datasets_py.utils.query_cache is deprecated. "
    "Use ipfs_datasets_py.utils.cache.LocalCache instead. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new unified cache module
from .cache import LocalCache, CacheBackend, CacheEntry, CacheStats


class QueryCache(LocalCache):
    """Backward-compatible query cache facade.

    The old QueryCache API accepted arbitrary Python objects as keys, returned
    ``True`` from ``set()``, exposed ``ttl`` and ``cache`` attributes, returned
    statistics as dictionaries, and shipped a ``cached_query`` decorator. The
    unified LocalCache keeps the storage machinery; this facade preserves those
    legacy call shapes for older utilities such as DiscordChatExporter.
    """

    def __init__(self, maxsize: int = 100, ttl: int = 300):
        if ttl < 1:
            raise ValueError(f"ttl must be at least 1 second, got {ttl}")
        super().__init__(maxsize=maxsize, default_ttl=ttl, name="QueryCache")
        self.ttl = ttl

    @property
    def cache(self):
        """Expose the underlying cache for legacy tests and callers."""
        return self._cache

    def get(self, key: Any) -> Optional[Any]:
        return super().get(self.make_key(key))

    def set(self, key: Any, value: Any, ttl: Optional[int] = None, **metadata) -> bool:
        super().set(self.make_key(key), value, ttl=ttl, **metadata)
        return True

    def delete(self, key: Any) -> bool:
        return super().delete(self.make_key(key))

    def get_stats(self) -> dict[str, Any]:
        stats = super().get_stats()
        return {
            "hits": stats.hits,
            "misses": stats.misses,
            "sets": stats.sets,
            "evictions": stats.evictions,
            "errors": stats.errors,
            "size": stats.size,
            "hit_rate": stats.hit_rate,
        }

    def reset_stats(self) -> None:
        with self._lock:
            self._stats = CacheStats(size=self.size())


def cached_query(
    cache: QueryCache,
    key_func: Optional[Callable[..., Any]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Cache non-None function results in a QueryCache instance."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = key_func(*args, **kwargs) if key_func else cache.make_key(func.__name__, args, kwargs)
            cached = cache.get(key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            if result is not None:
                cache.set(key, result)
            return result

        return wrapper

    return decorator

__all__ = [
    'QueryCache',
    'cached_query',
    'CacheBackend',
    'CacheEntry',
    'CacheStats',
]
