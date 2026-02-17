"""
Tests for MCP++ Result Caching System (Phase 4.4)

Tests TTL expiration, cache backends, eviction policies, and invalidation.
"""

import pytest
import asyncio
import time
from pathlib import Path
import tempfile
import shutil

from ipfs_datasets_py.mcp_server.mcplusplus.result_cache import (
    CacheEntry,
    MemoryCacheBackend,
    DiskCacheBackend,
    ResultCache,
    EvictionPolicy
)


# Tests

class TestCacheEntry:
    """Test CacheEntry dataclass."""
    
    def test_entry_creation(self):
        """Test creating a cache entry."""
        entry = CacheEntry(
            key='test',
            value={'data': 'test'},
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=3600.0,
            size_bytes=1024
        )
        
        assert entry.key == 'test'
        assert entry.value == {'data': 'test'}
        assert entry.ttl == 3600.0
        assert entry.size_bytes == 1024
    
    def test_age_calculation(self):
        """Test entry age calculation."""
        entry = CacheEntry(
            key='test',
            value='test',
            created_at=time.time() - 10,
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        
        assert entry.age_seconds >= 10
    
    def test_expiration_check(self):
        """Test expiration checking."""
        # Not expired
        entry1 = CacheEntry(
            key='test1',
            value='test',
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=3600.0,
            size_bytes=100
        )
        assert entry1.is_expired is False
        
        # Expired
        entry2 = CacheEntry(
            key='test2',
            value='test',
            created_at=time.time() - 10,
            last_accessed=time.time(),
            access_count=0,
            ttl=1.0,
            size_bytes=100
        )
        assert entry2.is_expired is True
    
    def test_access_tracking(self):
        """Test access tracking."""
        entry = CacheEntry(
            key='test',
            value='test',
            created_at=time.time(),
            last_accessed=time.time() - 5,
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        
        initial_last_accessed = entry.last_accessed
        
        entry.access()
        
        assert entry.access_count == 1
        assert entry.last_accessed > initial_last_accessed


@pytest.mark.asyncio
class TestMemoryCacheBackend:
    """Test MemoryCacheBackend class."""
    
    async def test_backend_initialization(self):
        """Test backend initialization."""
        backend = MemoryCacheBackend(max_size=100, max_memory_mb=10.0)
        
        assert backend.max_size == 100
        assert backend.max_memory_bytes == 10 * 1024 * 1024
    
    async def test_put_and_get(self):
        """Test putting and getting entries."""
        backend = MemoryCacheBackend()
        
        entry = CacheEntry(
            key='test',
            value={'data': 'test'},
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        
        await backend.put(entry)
        retrieved = await backend.get('test')
        
        assert retrieved is not None
        assert retrieved.key == 'test'
        assert retrieved.value == {'data': 'test'}
    
    async def test_get_nonexistent(self):
        """Test getting nonexistent entry."""
        backend = MemoryCacheBackend()
        
        result = await backend.get('nonexistent')
        assert result is None
    
    async def test_delete(self):
        """Test deleting entries."""
        backend = MemoryCacheBackend()
        
        entry = CacheEntry(
            key='test',
            value='test',
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        
        await backend.put(entry)
        assert await backend.get('test') is not None
        
        deleted = await backend.delete('test')
        assert deleted is True
        assert await backend.get('test') is None
    
    async def test_clear(self):
        """Test clearing all entries."""
        backend = MemoryCacheBackend()
        
        for i in range(5):
            entry = CacheEntry(
                key=f'test{i}',
                value=f'test{i}',
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=0,
                ttl=None,
                size_bytes=100
            )
            await backend.put(entry)
        
        count = await backend.clear()
        assert count == 5
        
        stats = await backend.get_stats()
        assert stats['size'] == 0
    
    async def test_size_eviction(self):
        """Test eviction when size limit exceeded."""
        backend = MemoryCacheBackend(max_size=3)
        
        # Add 4 entries (should evict oldest)
        for i in range(4):
            entry = CacheEntry(
                key=f'test{i}',
                value=f'test{i}',
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=0,
                ttl=None,
                size_bytes=100
            )
            await backend.put(entry)
            await asyncio.sleep(0.01)  # Ensure different timestamps
        
        # First entry should be evicted
        result = await backend.get('test0')
        assert result is None
        
        # Others should still be there
        assert await backend.get('test1') is not None
        assert await backend.get('test2') is not None
        assert await backend.get('test3') is not None
    
    async def test_lru_ordering(self):
        """Test LRU ordering (most recently accessed)."""
        backend = MemoryCacheBackend(max_size=3)
        
        # Add 3 entries
        for i in range(3):
            entry = CacheEntry(
                key=f'test{i}',
                value=f'test{i}',
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=0,
                ttl=None,
                size_bytes=100
            )
            await backend.put(entry)
        
        # Access test0 (moves it to end)
        await backend.get('test0')
        
        # Add new entry (should evict test1, not test0)
        entry = CacheEntry(
            key='test3',
            value='test3',
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        await backend.put(entry)
        
        # test0 should still be there
        assert await backend.get('test0') is not None
        # test1 should be evicted
        assert await backend.get('test1') is None
    
    async def test_stats(self):
        """Test statistics collection."""
        backend = MemoryCacheBackend(max_size=10)
        
        for i in range(3):
            entry = CacheEntry(
                key=f'test{i}',
                value=f'test{i}',
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=0,
                ttl=None,
                size_bytes=100
            )
            await backend.put(entry)
        
        stats = await backend.get_stats()
        
        assert stats['backend'] == 'memory'
        assert stats['size'] == 3
        assert stats['max_size'] == 10
        assert stats['total_bytes'] == 300


@pytest.mark.asyncio
class TestDiskCacheBackend:
    """Test DiskCacheBackend class."""
    
    @pytest.fixture
    async def temp_cache_dir(self):
        """Create temporary cache directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    async def test_backend_initialization(self, temp_cache_dir):
        """Test backend initialization."""
        backend = DiskCacheBackend(temp_cache_dir, max_size=100)
        
        assert backend.cache_dir == temp_cache_dir
        assert backend.max_size == 100
        assert temp_cache_dir.exists()
    
    async def test_put_and_get(self, temp_cache_dir):
        """Test putting and getting entries."""
        backend = DiskCacheBackend(temp_cache_dir)
        
        entry = CacheEntry(
            key='test',
            value={'data': 'test'},
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        
        await backend.put(entry)
        
        # Give it time to write
        await asyncio.sleep(0.1)
        
        retrieved = await backend.get('test')
        
        assert retrieved is not None
        assert retrieved.key == 'test'
        assert retrieved.value == {'data': 'test'}
    
    async def test_persistence(self, temp_cache_dir):
        """Test that entries persist across backend instances."""
        # Create first backend and add entry
        backend1 = DiskCacheBackend(temp_cache_dir)
        entry = CacheEntry(
            key='test',
            value='test',
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        await backend1.put(entry)
        await asyncio.sleep(0.1)
        
        # Create new backend with same directory
        backend2 = DiskCacheBackend(temp_cache_dir)
        await asyncio.sleep(0.1)  # Give time to load index
        
        retrieved = await backend2.get('test')
        assert retrieved is not None
        assert retrieved.value == 'test'
    
    async def test_delete(self, temp_cache_dir):
        """Test deleting entries."""
        backend = DiskCacheBackend(temp_cache_dir)
        
        entry = CacheEntry(
            key='test',
            value='test',
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=None,
            size_bytes=100
        )
        
        await backend.put(entry)
        await asyncio.sleep(0.1)
        
        deleted = await backend.delete('test')
        assert deleted is True
        
        result = await backend.get('test')
        assert result is None
    
    async def test_clear(self, temp_cache_dir):
        """Test clearing all entries."""
        backend = DiskCacheBackend(temp_cache_dir)
        
        for i in range(3):
            entry = CacheEntry(
                key=f'test{i}',
                value=f'test{i}',
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=0,
                ttl=None,
                size_bytes=100
            )
            await backend.put(entry)
        
        await asyncio.sleep(0.1)
        
        count = await backend.clear()
        assert count == 3
    
    async def test_stats(self, temp_cache_dir):
        """Test statistics collection."""
        backend = DiskCacheBackend(temp_cache_dir, max_size=10)
        
        for i in range(3):
            entry = CacheEntry(
                key=f'test{i}',
                value=f'test{i}',
                created_at=time.time(),
                last_accessed=time.time(),
                access_count=0,
                ttl=None,
                size_bytes=100
            )
            await backend.put(entry)
        
        await asyncio.sleep(0.1)
        
        stats = await backend.get_stats()
        
        assert stats['backend'] == 'disk'
        assert stats['size'] == 3
        assert stats['cache_dir'] == str(temp_cache_dir)


@pytest.mark.asyncio
class TestResultCache:
    """Test ResultCache class."""
    
    async def test_cache_initialization(self):
        """Test cache initialization."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend, default_ttl=3600.0)
        
        assert cache.backend == backend
        assert cache.default_ttl == 3600.0
    
    async def test_put_and_get(self):
        """Test caching and retrieving results."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        await cache.put('task1', {'result': 'data'})
        result = await cache.get('task1')
        
        assert result == {'result': 'data'}
    
    async def test_cache_miss(self):
        """Test cache miss."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        result = await cache.get('nonexistent')
        assert result is None
    
    async def test_ttl_expiration(self):
        """Test TTL expiration."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend, default_ttl=0.5)
        
        await cache.put('temp', {'result': 'temporary'})
        
        # Should be cached
        result = await cache.get('temp')
        assert result == {'result': 'temporary'}
        
        # Wait for expiration
        await asyncio.sleep(0.6)
        
        # Should be expired
        result = await cache.get('temp')
        assert result is None
    
    async def test_custom_ttl(self):
        """Test custom TTL per entry."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend, default_ttl=10.0)
        
        await cache.put('short', {'result': 'short'}, ttl=0.5)
        await cache.put('long', {'result': 'long'}, ttl=10.0)
        
        # Wait for short to expire
        await asyncio.sleep(0.6)
        
        assert await cache.get('short') is None
        assert await cache.get('long') == {'result': 'long'}
    
    async def test_invalidate(self):
        """Test cache invalidation."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        await cache.put('task1', {'result': 'data'})
        assert await cache.get('task1') is not None
        
        invalidated = await cache.invalidate('task1')
        assert invalidated is True
        assert await cache.get('task1') is None
    
    async def test_clear(self):
        """Test clearing cache."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        await cache.put('task1', {'result': '1'})
        await cache.put('task2', {'result': '2'})
        
        count = await cache.clear()
        assert count == 2
        assert await cache.get('task1') is None
        assert await cache.get('task2') is None
    
    async def test_hit_rate(self):
        """Test hit rate calculation."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        await cache.put('task1', {'result': '1'})
        
        # 2 hits
        await cache.get('task1')
        await cache.get('task1')
        
        # 1 miss
        await cache.get('task2')
        
        # Hit rate should be 2/3
        assert abs(cache.hit_rate - (2/3)) < 0.01
    
    async def test_input_based_caching(self):
        """Test caching based on inputs."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        # Same task, different inputs
        await cache.put('task1', {'result': 'A'}, inputs={'param': 1})
        await cache.put('task1', {'result': 'B'}, inputs={'param': 2})
        
        # Should get different results
        result_a = await cache.get('task1', inputs={'param': 1})
        result_b = await cache.get('task1', inputs={'param': 2})
        
        assert result_a == {'result': 'A'}
        assert result_b == {'result': 'B'}
    
    async def test_stats(self):
        """Test statistics collection."""
        backend = MemoryCacheBackend()
        cache = ResultCache(backend)
        
        await cache.put('task1', {'result': '1'})
        await cache.get('task1')  # Hit
        await cache.get('task2')  # Miss
        
        stats = await cache.get_stats()
        
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert stats['hit_rate'] == 0.5


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
