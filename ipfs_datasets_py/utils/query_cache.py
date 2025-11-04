#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Query Cache Module

This module provides a lightweight, configurable caching mechanism for CLI tool queries.
It implements TTL-based caching with automatic expiration and fallback mechanisms.

Features:
- In-memory caching using cachetools
- Configurable cache size and TTL
- Thread-safe operations
- Cache hit/miss statistics
- Automatic cache eviction
- Error handling with fallback

Example:
    >>> cache = QueryCache(maxsize=100, ttl=300)
    >>> cache.get("key")  # Returns None if not found
    >>> cache.set("key", "value")
    >>> cache.get("key")  # Returns "value"
"""

import logging
import hashlib
import json
from typing import Any, Optional, Dict, Callable
from functools import wraps
from threading import RLock
from cachetools import TTLCache

logger = logging.getLogger(__name__)


class QueryCache:
    """
    Thread-safe TTL-based cache for query results.

    Provides automatic expiration of cache entries based on time-to-live (TTL)
    and maximum cache size. Includes statistics tracking for monitoring cache
    effectiveness.

    Attributes:
        maxsize (int): Maximum number of entries in the cache
        ttl (int): Time-to-live in seconds for cache entries
        cache (TTLCache): Underlying cachetools TTLCache instance
        lock (RLock): Reentrant lock for thread-safe operations
        stats (Dict): Cache statistics (hits, misses, sets, evictions)

    Example:
        >>> cache = QueryCache(maxsize=100, ttl=300)
        >>> cache.set("query_key", {"result": "data"})
        >>> result = cache.get("query_key")
        >>> stats = cache.get_stats()
        >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
    """

    def __init__(self, maxsize: int = 100, ttl: int = 300):
        """
        Initialize query cache.

        Args:
            maxsize: Maximum number of entries in the cache (default: 100)
            ttl: Time-to-live in seconds for cache entries (default: 300)

        Raises:
            ValueError: If maxsize < 1 or ttl < 1
        """
        if maxsize < 1:
            raise ValueError(f"maxsize must be at least 1, got {maxsize}")
        if ttl < 1:
            raise ValueError(f"ttl must be at least 1 second, got {ttl}")

        self.maxsize = maxsize
        self.ttl = ttl
        self.cache = TTLCache(maxsize=maxsize, ttl=ttl)
        self.lock = RLock()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "evictions": 0,
            "errors": 0
        }

        logger.info(f"Initialized QueryCache with maxsize={maxsize}, ttl={ttl}s")

    def _make_key(self, key: Any) -> str:
        """
        Create a cache key from various input types.

        Handles strings, lists, dicts, and other types by converting to
        a consistent string representation and optionally hashing.

        Args:
            key: Input key (string, list, dict, or other hashable type)

        Returns:
            String cache key
        """
        if isinstance(key, str):
            return key

        # Convert complex types to JSON for consistent hashing
        try:
            if isinstance(key, (list, dict)):
                key_str = json.dumps(key, sort_keys=True)
            else:
                key_str = str(key)

            # Hash long keys to keep cache keys manageable
            if len(key_str) > 200:
                return hashlib.sha256(key_str.encode()).hexdigest()

            return key_str
        except Exception as e:
            logger.warning(f"Failed to create cache key: {e}, using str() fallback")
            return str(key)

    def get(self, key: Any) -> Optional[Any]:
        """
        Get a value from the cache.

        Args:
            key: Cache key (string, list, dict, or other hashable type)

        Returns:
            Cached value or None if not found or expired
        """
        cache_key = self._make_key(key)

        try:
            with self.lock:
                if cache_key in self.cache:
                    self.stats["hits"] += 1
                    value = self.cache[cache_key]
                    logger.debug(f"Cache HIT for key: {cache_key[:50]}...")
                    return value
                else:
                    self.stats["misses"] += 1
                    logger.debug(f"Cache MISS for key: {cache_key[:50]}...")
                    return None
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache get error: {e}")
            return None

    def set(self, key: Any, value: Any) -> bool:
        """
        Set a value in the cache.

        Args:
            key: Cache key (string, list, dict, or other hashable type)
            value: Value to cache

        Returns:
            True if successfully cached, False on error
        """
        cache_key = self._make_key(key)

        try:
            with self.lock:
                # Track evictions when cache is full
                if len(self.cache) >= self.maxsize and cache_key not in self.cache:
                    self.stats["evictions"] += 1

                self.cache[cache_key] = value
                self.stats["sets"] += 1
                logger.debug(f"Cache SET for key: {cache_key[:50]}...")
                return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache set error: {e}")
            return False

    def delete(self, key: Any) -> bool:
        """
        Delete a value from the cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key was present and deleted, False otherwise
        """
        cache_key = self._make_key(key)

        try:
            with self.lock:
                if cache_key in self.cache:
                    del self.cache[cache_key]
                    logger.debug(f"Cache DELETE for key: {cache_key[:50]}...")
                    return True
                return False
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache delete error: {e}")
            return False

    def clear(self) -> None:
        """Clear all entries from the cache."""
        try:
            with self.lock:
                self.cache.clear()
                logger.info("Cache cleared")
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Cache clear error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics including:
            - hits: Number of cache hits
            - misses: Number of cache misses
            - sets: Number of cache sets
            - evictions: Number of cache evictions
            - errors: Number of cache errors
            - size: Current cache size
            - maxsize: Maximum cache size
            - ttl: Cache TTL in seconds
            - hit_rate: Cache hit rate (0.0 - 1.0)
        """
        with self.lock:
            total_requests = self.stats["hits"] + self.stats["misses"]
            hit_rate = self.stats["hits"] / total_requests if total_requests > 0 else 0.0

            return {
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "sets": self.stats["sets"],
                "evictions": self.stats["evictions"],
                "errors": self.stats["errors"],
                "size": len(self.cache),
                "maxsize": self.maxsize,
                "ttl": self.ttl,
                "hit_rate": hit_rate
            }

    def reset_stats(self) -> None:
        """Reset cache statistics to zero."""
        with self.lock:
            self.stats = {
                "hits": 0,
                "misses": 0,
                "sets": 0,
                "evictions": 0,
                "errors": 0
            }
            logger.info("Cache statistics reset")


def cached_query(cache: QueryCache, key_func: Optional[Callable] = None):
    """
    Decorator for caching query results.

    Automatically caches function results based on the function arguments.
    Provides transparent caching with fallback on errors.

    Args:
        cache: QueryCache instance to use
        key_func: Optional function to generate cache key from function args.
                 If None, uses all args as the key.

    Returns:
        Decorated function with caching

    Example:
        >>> cache = QueryCache(maxsize=50, ttl=60)
        >>> @cached_query(cache)
        ... def expensive_query(param1, param2):
        ...     # Expensive operation
        ...     return result
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                try:
                    cache_key = key_func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Failed to generate cache key: {e}")
                    cache_key = None
            else:
                # Use function name and all arguments as key
                cache_key = {
                    "func": func.__name__,
                    "args": args,
                    "kwargs": kwargs
                }

            # Try to get from cache
            if cache_key is not None:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    return cached_result

            # Execute function
            try:
                result = func(*args, **kwargs)

                # Cache the result
                if cache_key is not None and result is not None:
                    cache.set(cache_key, result)

                return result
            except Exception as e:
                logger.error(f"Query execution error: {e}")
                raise

        return wrapper
    return decorator
