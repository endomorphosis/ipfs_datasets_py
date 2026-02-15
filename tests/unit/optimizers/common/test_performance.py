"""Tests for optimizer performance utilities."""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from ipfs_datasets_py.optimizers.common.performance import (
    CacheEntry,
    LLMCache,
    cached_llm_call,
    ParallelValidator,
    PerformanceMetrics,
    profile_optimizer,
    BatchFileProcessor,
    get_global_cache,
)


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""
    
    def test_cache_entry_creation(self):
        """Test creating cache entry."""
        entry = CacheEntry(
            key="test_key",
            value="test_value",
            timestamp=datetime.now(),
            ttl=3600,
        )
        
        assert entry.key == "test_key"
        assert entry.value == "test_value"
        assert entry.ttl == 3600
        assert entry.hit_count == 0
    
    def test_cache_entry_expiration(self):
        """Test cache entry expiration."""
        # Not expired
        entry = CacheEntry(
            key="test",
            value="value",
            timestamp=datetime.now(),
            ttl=3600,
        )
        assert not entry.is_expired()
        
        # Expired
        old_time = datetime.now() - timedelta(hours=2)
        entry_expired = CacheEntry(
            key="test",
            value="value",
            timestamp=old_time,
            ttl=3600,
        )
        assert entry_expired.is_expired()
        
        # Never expires (ttl=0)
        entry_permanent = CacheEntry(
            key="test",
            value="value",
            timestamp=old_time,
            ttl=0,
        )
        assert not entry_permanent.is_expired()
    
    def test_cache_entry_serialization(self):
        """Test cache entry serialization."""
        entry = CacheEntry(
            key="test",
            value={"result": "data"},
            timestamp=datetime.now(),
            ttl=3600,
            metadata={"source": "test"},
        )
        
        # To dict
        data = entry.to_dict()
        assert data["key"] == "test"
        assert data["value"] == {"result": "data"}
        assert "timestamp" in data
        
        # From dict
        restored = CacheEntry.from_dict(data)
        assert restored.key == entry.key
        assert restored.value == entry.value
        assert restored.ttl == entry.ttl


class TestLLMCache:
    """Tests for LLMCache."""
    
    def test_cache_initialization(self):
        """Test cache initialization."""
        cache = LLMCache(max_size=100, default_ttl=1800)
        
        assert cache.max_size == 100
        assert cache.default_ttl == 1800
        assert len(cache._cache) == 0
    
    def test_cache_set_get(self):
        """Test basic cache set/get operations."""
        cache = LLMCache()
        
        # Set value
        cache.set("prompt1", "result1")
        
        # Get value
        result = cache.get("prompt1")
        assert result == "result1"
        
        # Get non-existent
        result = cache.get("nonexistent")
        assert result is None
    
    def test_cache_with_kwargs(self):
        """Test cache with different kwargs."""
        cache = LLMCache()
        
        # Same prompt, different kwargs
        cache.set("prompt1", "result1", temperature=0.7)
        cache.set("prompt1", "result2", temperature=0.9)
        
        result1 = cache.get("prompt1", temperature=0.7)
        result2 = cache.get("prompt1", temperature=0.9)
        
        assert result1 == "result1"
        assert result2 == "result2"
    
    def test_cache_ttl_expiration(self):
        """Test cache TTL expiration."""
        cache = LLMCache(default_ttl=1)
        
        cache.set("prompt1", "result1")
        
        # Should exist immediately
        result = cache.get("prompt1")
        assert result == "result1"
        
        # Wait for expiration
        time.sleep(1.5)
        
        # Should be expired
        result = cache.get("prompt1")
        assert result is None
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction policy."""
        cache = LLMCache(max_size=2)
        
        cache.set("prompt1", "result1")
        cache.set("prompt2", "result2")
        cache.set("prompt3", "result3")  # Should evict prompt1
        
        assert cache.get("prompt1") is None
        assert cache.get("prompt2") == "result2"
        assert cache.get("prompt3") == "result3"
    
    def test_cache_hit_count(self):
        """Test cache hit counting."""
        cache = LLMCache()
        
        cache.set("prompt1", "result1")
        
        # Multiple gets
        cache.get("prompt1")
        cache.get("prompt1")
        cache.get("prompt1")
        
        # Check hit count in entry
        entry = cache._cache[cache._compute_key("prompt1")]
        assert entry.hit_count == 3
    
    def test_cache_stats(self):
        """Test cache statistics."""
        cache = LLMCache()
        
        cache.set("prompt1", "result1")
        cache.set("prompt2", "result2")
        
        cache.get("prompt1")  # Hit
        cache.get("prompt1")  # Hit
        cache.get("prompt3")  # Miss
        
        stats = cache.get_stats()
        assert stats["size"] == 2
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 2/3
    
    def test_cache_clear(self):
        """Test cache clear."""
        cache = LLMCache()
        
        cache.set("prompt1", "result1")
        cache.set("prompt2", "result2")
        cache.get("prompt1")
        
        cache.clear()
        
        assert len(cache._cache) == 0
        assert cache._hits == 0
        assert cache._misses == 0


class TestCachedLLMCall:
    """Tests for cached_llm_call decorator."""
    
    def test_decorator_caching(self):
        """Test decorator caches function calls."""
        cache = LLMCache()
        call_count = 0
        
        @cached_llm_call(cache=cache)
        def mock_llm(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"
        
        # First call - should execute
        result1 = mock_llm("prompt1")
        assert result1 == "result_1"
        assert call_count == 1
        
        # Second call - should use cache
        result2 = mock_llm("prompt1")
        assert result2 == "result_1"
        assert call_count == 1  # Not incremented
        
        # Different prompt - should execute
        result3 = mock_llm("prompt2")
        assert result3 == "result_2"
        assert call_count == 2


class TestParallelValidator:
    """Tests for ParallelValidator."""
    
    def test_parallel_validator_sync(self):
        """Test parallel validation (sync)."""
        validator = ParallelValidator(max_workers=2)
        
        def validate1(code):
            time.sleep(0.1)
            return "syntax_ok"
        
        def validate2(code):
            time.sleep(0.1)
            return "types_ok"
        
        start = time.time()
        results = validator.run_sync([validate1, validate2], "code")
        duration = time.time() - start
        
        # Should be parallel (< 0.15s instead of 0.2s)
        assert duration < 0.15
        assert len(results) == 2
        assert all(success for success, _ in results)
        
        validator.shutdown()
    
    @pytest.mark.asyncio
    async def test_parallel_validator_async(self):
        """Test parallel validation (async)."""
        validator = ParallelValidator(max_workers=2)
        
        async def validate1(code):
            await asyncio.sleep(0.1)
            return "syntax_ok"
        
        async def validate2(code):
            await asyncio.sleep(0.1)
            return "types_ok"
        
        start = time.time()
        results = await validator.run_async([validate1, validate2], "code")
        duration = time.time() - start
        
        # Should be parallel
        assert duration < 0.15
        assert len(results) == 2
        
        validator.shutdown()
    
    def test_parallel_validator_error_handling(self):
        """Test error handling in parallel validation."""
        validator = ParallelValidator()
        
        def validate_ok(code):
            return "ok"
        
        def validate_fail(code):
            raise ValueError("Test error")
        
        results = validator.run_sync([validate_ok, validate_fail], "code")
        
        assert len(results) == 2
        assert results[0] == (True, "ok")
        assert results[1][0] is False
        
        validator.shutdown()


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics."""
    
    def test_metrics_creation(self):
        """Test metrics creation."""
        metrics = PerformanceMetrics(
            operation="optimize",
            duration=1.23,
            cache_hits=10,
            cache_misses=5,
        )
        
        assert metrics.operation == "optimize"
        assert metrics.duration == 1.23
        assert metrics.cache_hits == 10
        assert metrics.cache_misses == 5


class TestProfileOptimizer:
    """Tests for profile_optimizer decorator."""
    
    def test_profiler_basic(self, capsys):
        """Test profiler measures execution time."""
        @profile_optimizer
        def slow_function():
            time.sleep(0.1)
            return "result"
        
        result = slow_function()
        
        assert result == "result"
        
        captured = capsys.readouterr()
        assert "slow_function" in captured.out


class TestBatchFileProcessor:
    """Tests for BatchFileProcessor."""
    
    def test_batch_read(self):
        """Test batch file reading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            paths = []
            for i in range(3):
                path = Path(tmpdir) / f"file{i}.txt"
                path.write_text(f"content{i}")
                paths.append(path)
            
            processor = BatchFileProcessor(batch_size=2)
            results = processor.read_batch(paths)
            
            assert len(results) == 3
            assert results[0] == "content0"
            assert results[1] == "content1"
            assert results[2] == "content2"
    
    def test_batch_write(self):
        """Test batch file writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = [
                Path(tmpdir) / "file1.txt",
                Path(tmpdir) / "file2.txt",
            ]
            contents = ["content1", "content2"]
            
            processor = BatchFileProcessor()
            results = processor.write_batch(paths, contents)
            
            assert all(results)
            assert paths[0].read_text() == "content1"
            assert paths[1].read_text() == "content2"


class TestGlobalCache:
    """Tests for global cache instance."""
    
    def test_get_global_cache(self):
        """Test getting global cache instance."""
        cache1 = get_global_cache()
        cache2 = get_global_cache()
        
        # Should be same instance
        assert cache1 is cache2
        
        # Should be functional
        cache1.set("test", "value")
        assert cache2.get("test") == "value"
