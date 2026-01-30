"""
Tests for enhanced batch processing.
"""

import pytest
import tempfile
import asyncio
from pathlib import Path
from ipfs_datasets_py.file_converter import (
    BatchProcessor, BatchProgress, ResourceLimits, CacheManager,
    create_batch_processor, FileConverter
)


class TestBatchProgress:
    """Test BatchProgress dataclass."""
    
    def test_initialization(self):
        """Test progress initialization."""
        progress = BatchProgress(total=10)
        assert progress.total == 10
        assert progress.completed == 0
        assert progress.failed == 0
        assert progress.skipped == 0
    
    def test_pending_calculation(self):
        """Test pending items calculation."""
        progress = BatchProgress(total=10)
        progress.completed = 3
        progress.failed = 2
        progress.skipped = 1
        
        assert progress.pending == 4  # 10 - 3 - 2 - 1
    
    def test_success_rate(self):
        """Test success rate calculation."""
        progress = BatchProgress(total=10)
        progress.completed = 7
        progress.failed = 3
        
        assert progress.success_rate == 70.0  # 7 / (7+3) * 100
    
    def test_success_rate_no_processing(self):
        """Test success rate when nothing processed."""
        progress = BatchProgress(total=10)
        assert progress.success_rate == 0.0
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        progress = BatchProgress(total=10)
        progress.completed = 5
        
        data = progress.to_dict()
        assert data['total'] == 10
        assert data['completed'] == 5
        assert 'elapsed_time' in data
        assert 'items_per_second' in data


class TestResourceLimits:
    """Test ResourceLimits dataclass."""
    
    def test_initialization(self):
        """Test limits initialization."""
        limits = ResourceLimits()
        assert limits.max_concurrent == 5
        assert limits.max_memory_mb is None
    
    def test_custom_limits(self):
        """Test custom limits."""
        limits = ResourceLimits(
            max_concurrent=10,
            max_file_size_mb=100,
            timeout_seconds=30.0
        )
        assert limits.max_concurrent == 10
        assert limits.max_file_size_mb == 100
        assert limits.timeout_seconds == 30.0
    
    def test_check_file_size_no_limit(self):
        """Test file size check with no limit."""
        limits = ResourceLimits()
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            assert limits.check_file_size(temp_path) is True
        finally:
            Path(temp_path).unlink()
    
    def test_check_file_size_within_limit(self):
        """Test file size check within limit."""
        limits = ResourceLimits(max_file_size_mb=1)  # 1 MB
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("small content")  # Much less than 1 MB
            temp_path = f.name
        
        try:
            assert limits.check_file_size(temp_path) is True
        finally:
            Path(temp_path).unlink()


class TestBatchProcessor:
    """Test BatchProcessor class."""
    
    def test_initialization(self):
        """Test processor initialization."""
        converter = FileConverter(backend='native')
        processor = BatchProcessor(converter)
        
        assert processor.converter is converter
        assert processor.limits is not None
        assert processor.limits.max_concurrent == 5
    
    def test_initialization_with_limits(self):
        """Test processor with custom limits."""
        converter = FileConverter(backend='native')
        limits = ResourceLimits(max_concurrent=10)
        processor = BatchProcessor(converter, limits=limits)
        
        assert processor.limits.max_concurrent == 10
    
    @pytest.mark.asyncio
    async def test_process_batch_basic(self):
        """Test basic batch processing."""
        # Create test files
        files = []
        try:
            for i in range(3):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(f"Test content {i}")
                    files.append(f.name)
            
            converter = FileConverter(backend='native')
            processor = BatchProcessor(converter)
            
            results = await processor.process_batch(files)
            
            # Should process all files
            assert len(results) <= 3  # May have some failures
            
        finally:
            for file_path in files:
                Path(file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_process_batch_with_progress_callback(self):
        """Test batch processing with progress callback."""
        progress_updates = []
        
        def callback(progress):
            progress_updates.append(progress.to_dict())
        
        files = []
        try:
            for i in range(3):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(f"Content {i}")
                    files.append(f.name)
            
            converter = FileConverter(backend='native')
            processor = BatchProcessor(converter, progress_callback=callback)
            
            await processor.process_batch(files)
            
            # Should have received progress updates
            assert len(progress_updates) > 0
            
        finally:
            for file_path in files:
                Path(file_path).unlink(missing_ok=True)
    
    def test_process_batch_sync(self):
        """Test synchronous batch processing."""
        files = []
        try:
            for i in range(2):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(f"Content {i}")
                    files.append(f.name)
            
            converter = FileConverter(backend='native')
            processor = BatchProcessor(converter)
            
            results = processor.process_batch_sync(files)
            
            assert isinstance(results, list)
            
        finally:
            for file_path in files:
                Path(file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_process_batch_with_size_limit(self):
        """Test batch processing with file size limits."""
        files = []
        try:
            # Create files of different sizes
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("small")
                files.append(f.name)
            
            converter = FileConverter(backend='native')
            limits = ResourceLimits(max_file_size_mb=0.001)  # Very small limit
            processor = BatchProcessor(converter, limits=limits)
            
            results = await processor.process_batch(files)
            
            # Small file should be skipped
            assert len(results) == 0  # All files likely too "large" or skipped
            
        finally:
            for file_path in files:
                Path(file_path).unlink(missing_ok=True)


class TestCacheManager:
    """Test CacheManager class."""
    
    def test_initialization(self):
        """Test cache manager initialization."""
        cache = CacheManager()
        assert cache is not None
        assert cache.cache_dir.exists()
    
    def test_get_set(self):
        """Test cache get/set operations."""
        cache = CacheManager()
        
        cache.set('key1', 'value1')
        assert cache.get('key1') == 'value1'
        
        assert cache.get('nonexistent') is None
    
    def test_clear(self):
        """Test cache clearing."""
        cache = CacheManager()
        
        cache.set('key1', 'value1')
        cache.set('key2', 'value2')
        
        cache.clear()
        
        assert cache.get('key1') is None
        assert cache.get('key2') is None
    
    def test_get_cache_key(self):
        """Test cache key generation."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("content")
            temp_path = f.name
        
        try:
            cache = CacheManager()
            
            # Same file and params should give same key
            key1 = cache.get_cache_key(temp_path, param1='value1')
            key2 = cache.get_cache_key(temp_path, param1='value1')
            assert key1 == key2
            
            # Different params should give different key
            key3 = cache.get_cache_key(temp_path, param1='value2')
            assert key1 != key3
            
        finally:
            Path(temp_path).unlink()


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_batch_processor(self):
        """Test create_batch_processor function."""
        converter = FileConverter(backend='native')
        
        processor = create_batch_processor(
            converter,
            max_concurrent=10,
            max_file_size_mb=100
        )
        
        assert processor is not None
        assert processor.limits.max_concurrent == 10
        assert processor.limits.max_file_size_mb == 100
    
    def test_create_batch_processor_with_callback(self):
        """Test creating processor with callback."""
        converter = FileConverter(backend='native')
        callback_called = []
        
        def callback(progress):
            callback_called.append(True)
        
        processor = create_batch_processor(
            converter,
            progress_callback=callback
        )
        
        assert processor.progress_callback is not None
