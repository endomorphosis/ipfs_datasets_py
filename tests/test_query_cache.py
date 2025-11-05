#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Query Cache Module

Comprehensive tests for the query caching functionality including
cache hit/miss scenarios, TTL behavior, eviction, and error handling.
"""

import time
import pytest
from ipfs_datasets_py.utils.query_cache import QueryCache, cached_query


class TestQueryCache:
    """Test suite for QueryCache class."""

    def test_cache_initialization(self):
        """
        GIVEN cache parameters
        WHEN creating a QueryCache instance
        THEN it should initialize with correct attributes
        """
        cache = QueryCache(maxsize=50, ttl=120)

        assert cache.maxsize == 50
        assert cache.ttl == 120
        assert len(cache.cache) == 0

    def test_cache_invalid_maxsize(self):
        """
        GIVEN invalid maxsize parameter
        WHEN creating a QueryCache instance
        THEN it should raise ValueError
        """
        with pytest.raises(ValueError, match="maxsize must be at least 1"):
            QueryCache(maxsize=0, ttl=100)

    def test_cache_invalid_ttl(self):
        """
        GIVEN invalid ttl parameter
        WHEN creating a QueryCache instance
        THEN it should raise ValueError
        """
        with pytest.raises(ValueError, match="ttl must be at least 1 second"):
            QueryCache(maxsize=10, ttl=0)

    def test_cache_set_and_get(self):
        """
        GIVEN a cache instance
        WHEN setting and getting a value
        THEN it should store and retrieve the value correctly
        """
        cache = QueryCache(maxsize=10, ttl=60)

        key = "test_key"
        value = {"data": "test_value"}

        # Set value
        result = cache.set(key, value)
        assert result is True

        # Get value
        retrieved = cache.get(key)
        assert retrieved == value

    def test_cache_miss(self):
        """
        GIVEN a cache instance
        WHEN getting a non-existent key
        THEN it should return None
        """
        cache = QueryCache(maxsize=10, ttl=60)

        result = cache.get("non_existent_key")
        assert result is None

    def test_cache_with_list_key(self):
        """
        GIVEN a cache instance
        WHEN using a list as a key
        THEN it should handle it correctly
        """
        cache = QueryCache(maxsize=10, ttl=60)

        key = ["command", "arg1", "arg2"]
        value = "result"

        cache.set(key, value)
        retrieved = cache.get(key)

        assert retrieved == value

    def test_cache_with_dict_key(self):
        """
        GIVEN a cache instance
        WHEN using a dict as a key
        THEN it should handle it correctly
        """
        cache = QueryCache(maxsize=10, ttl=60)

        key = {"command": "gh", "args": ["repo", "list"]}
        value = ["repo1", "repo2"]

        cache.set(key, value)
        retrieved = cache.get(key)

        assert retrieved == value

    def test_cache_delete(self):
        """
        GIVEN a cache with stored values
        WHEN deleting a key
        THEN it should remove the value
        """
        cache = QueryCache(maxsize=10, ttl=60)

        cache.set("key", "value")
        assert cache.get("key") == "value"

        deleted = cache.delete("key")
        assert deleted is True
        assert cache.get("key") is None

    def test_cache_delete_nonexistent(self):
        """
        GIVEN a cache instance
        WHEN deleting a non-existent key
        THEN it should return False
        """
        cache = QueryCache(maxsize=10, ttl=60)

        deleted = cache.delete("non_existent")
        assert deleted is False

    def test_cache_clear(self):
        """
        GIVEN a cache with multiple entries
        WHEN clearing the cache
        THEN it should remove all entries
        """
        cache = QueryCache(maxsize=10, ttl=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None
        assert len(cache.cache) == 0

    def test_cache_ttl_expiration(self):
        """
        GIVEN a cache with short TTL
        WHEN waiting for TTL to expire
        THEN entries should be removed automatically
        """
        cache = QueryCache(maxsize=10, ttl=1)  # 1 second TTL

        cache.set("key", "value")
        assert cache.get("key") == "value"

        # Wait for TTL to expire
        time.sleep(1.1)

        # Entry should be expired
        assert cache.get("key") is None

    def test_cache_maxsize_eviction(self):
        """
        GIVEN a cache with limited size
        WHEN adding more entries than maxsize
        THEN it should evict old entries
        """
        cache = QueryCache(maxsize=3, ttl=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Cache is full, adding new entry should evict
        cache.set("key4", "value4")

        # At least one value should still be accessible
        assert cache.get("key4") == "value4"

        # Total size should not exceed maxsize
        stats = cache.get_stats()
        assert stats["size"] <= 3
        assert stats["evictions"] > 0

    def test_cache_stats_hits_and_misses(self):
        """
        GIVEN a cache with some operations
        WHEN checking statistics
        THEN it should track hits and misses correctly
        """
        cache = QueryCache(maxsize=10, ttl=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Generate hits
        cache.get("key1")
        cache.get("key1")
        cache.get("key2")

        # Generate misses
        cache.get("non_existent1")
        cache.get("non_existent2")

        stats = cache.get_stats()

        assert stats["hits"] == 3
        assert stats["misses"] == 2
        assert stats["sets"] == 2
        assert stats["hit_rate"] == 3 / 5  # 3 hits out of 5 total requests

    def test_cache_stats_hit_rate(self):
        """
        GIVEN a cache with operations
        WHEN calculating hit rate
        THEN it should be correct
        """
        cache = QueryCache(maxsize=10, ttl=60)

        cache.set("key", "value")

        # 80% hit rate: 4 hits, 1 miss
        cache.get("key")
        cache.get("key")
        cache.get("key")
        cache.get("key")
        cache.get("miss")

        stats = cache.get_stats()
        assert abs(stats["hit_rate"] - 0.8) < 0.01

    def test_cache_reset_stats(self):
        """
        GIVEN a cache with statistics
        WHEN resetting statistics
        THEN all counters should be zero
        """
        cache = QueryCache(maxsize=10, ttl=60)

        cache.set("key", "value")
        cache.get("key")
        cache.get("miss")

        cache.reset_stats()

        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["sets"] == 0

    def test_cache_long_key_hashing(self):
        """
        GIVEN a cache instance
        WHEN using a very long key
        THEN it should hash it for efficiency
        """
        cache = QueryCache(maxsize=10, ttl=60)

        # Create a very long key
        long_key = "a" * 300
        value = "test_value"

        cache.set(long_key, value)
        retrieved = cache.get(long_key)

        assert retrieved == value


class TestCachedQueryDecorator:
    """Test suite for cached_query decorator."""

    def test_cached_query_basic(self):
        """
        GIVEN a function decorated with cached_query
        WHEN calling the function multiple times
        THEN it should cache the result
        """
        cache = QueryCache(maxsize=10, ttl=60)
        call_count = [0]

        @cached_query(cache)
        def test_func(x, y):
            call_count[0] += 1
            return x + y

        # First call - should execute function
        result1 = test_func(1, 2)
        assert result1 == 3
        assert call_count[0] == 1

        # Second call with same args - should use cache
        result2 = test_func(1, 2)
        assert result2 == 3
        assert call_count[0] == 1  # Function not called again

        stats = cache.get_stats()
        assert stats["hits"] == 1

    def test_cached_query_different_args(self):
        """
        GIVEN a cached function
        WHEN calling with different arguments
        THEN it should not use cache
        """
        cache = QueryCache(maxsize=10, ttl=60)
        call_count = [0]

        @cached_query(cache)
        def test_func(x, y):
            call_count[0] += 1
            return x + y

        result1 = test_func(1, 2)
        result2 = test_func(3, 4)

        assert result1 == 3
        assert result2 == 7
        assert call_count[0] == 2  # Both calls executed

    def test_cached_query_with_kwargs(self):
        """
        GIVEN a cached function with kwargs
        WHEN calling with kwargs
        THEN it should cache correctly
        """
        cache = QueryCache(maxsize=10, ttl=60)
        call_count = [0]

        @cached_query(cache)
        def test_func(x, y=10):
            call_count[0] += 1
            return x + y

        result1 = test_func(5, y=15)
        result2 = test_func(5, y=15)

        assert result1 == 20
        assert result2 == 20
        assert call_count[0] == 1  # Second call used cache

    def test_cached_query_custom_key_func(self):
        """
        GIVEN a cached function with custom key function
        WHEN calling the function
        THEN it should use the custom key
        """
        cache = QueryCache(maxsize=10, ttl=60)
        call_count = [0]

        def make_key(x, y):
            return f"sum_{x}_{y}"

        @cached_query(cache, key_func=make_key)
        def test_func(x, y):
            call_count[0] += 1
            return x + y

        result1 = test_func(1, 2)
        result2 = test_func(1, 2)

        assert result1 == 3
        assert result2 == 3
        assert call_count[0] == 1

    def test_cached_query_error_fallback(self):
        """
        GIVEN a cached function that raises an error
        WHEN the function is called
        THEN it should propagate the error
        """
        cache = QueryCache(maxsize=10, ttl=60)

        @cached_query(cache)
        def test_func(x):
            if x < 0:
                raise ValueError("Negative value")
            return x * 2

        # Should work normally
        result = test_func(5)
        assert result == 10

        # Should raise error
        with pytest.raises(ValueError, match="Negative value"):
            test_func(-1)

    def test_cached_query_none_result(self):
        """
        GIVEN a cached function that returns None
        WHEN the function is called
        THEN None should not be cached (to allow retries)
        """
        cache = QueryCache(maxsize=10, ttl=60)
        call_count = [0]

        @cached_query(cache)
        def test_func(x):
            call_count[0] += 1
            if x == 0:
                return None
            return x * 2

        result1 = test_func(0)
        result2 = test_func(0)

        assert result1 is None
        assert result2 is None
        assert call_count[0] == 2  # Both calls executed (None not cached)


class TestCacheThreadSafety:
    """Test suite for cache thread-safety."""

    def test_cache_concurrent_access(self):
        """
        GIVEN a cache instance
        WHEN multiple threads access it concurrently
        THEN it should handle operations safely
        """
        import threading

        cache = QueryCache(maxsize=100, ttl=60)
        errors = []

        def worker(thread_id):
            try:
                for i in range(10):
                    key = f"thread_{thread_id}_key_{i}"
                    value = f"value_{i}"
                    cache.set(key, value)
                    retrieved = cache.get(key)
                    assert retrieved == value
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
