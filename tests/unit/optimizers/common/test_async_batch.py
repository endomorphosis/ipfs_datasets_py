"""Tests for async batch processing support.

Tests AsyncBatchProcessor and AsyncOntologyBatchProcessor for concurrent
batch operations.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock
from ipfs_datasets_py.optimizers.common.async_batch import (
    AsyncBatchProcessor,
    AsyncOntologyBatchProcessor,
    BatchResult,
    process_async_batch,
)


class TestBatchResult:
    """Test BatchResult dataclass."""
    
    def test_success_rate_calculation(self):
        """BatchResult calculates success rate correctly."""
        result = BatchResult(
            results=[1, 2, 3, None],
            errors=[None, None, None, "error"],
            total_time_ms=100.0,
            successful_count=3,
            failed_count=1,
        )
        
        assert result.success_rate == 75.0
    
    def test_success_rate_zero_items(self):
        """BatchResult handles zero items gracefully."""
        result = BatchResult(
            results=[],
            errors=[],
            total_time_ms=0.0,
            successful_count=0,
            failed_count=0,
        )
        
        assert result.success_rate == 0.0


class TestAsyncBatchProcessor:
    """Test AsyncBatchProcessor core functionality."""
    
    @pytest.mark.asyncio
    async def test_process_batch_async_function(self):
        """Processor handles async functions."""
        processor = AsyncBatchProcessor(max_concurrent=2)
        
        async def async_double(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 2
        
        items = [1, 2, 3, 4, 5]
        result = await processor.process_batch(items, async_double)
        
        assert result.successful_count == 5
        assert result.failed_count == 0
        assert result.results == [2, 4, 6, 8, 10]
        assert all(e is None for e in result.errors)
    
    @pytest.mark.asyncio
    async def test_process_batch_sync_function(self):
        """Processor handles sync functions via executor."""
        processor = AsyncBatchProcessor(max_concurrent=2)
        
        def sync_square(x: int) -> int:
            return x ** 2
        
        items = [1, 2, 3, 4]
        result = await processor.process_batch(items, sync_square)
        
        assert result.successful_count == 4
        assert result.failed_count == 0
        assert result.results == [1, 4, 9, 16]
    
    @pytest.mark.asyncio
    async def test_process_batch_with_errors(self):
        """Processor handles errors gracefully."""
        processor = AsyncBatchProcessor(max_concurrent=2, fail_fast=False)
        
        async def may_fail(x: int) -> int:
            if x == 3:
                raise ValueError("Error on 3")
            return x * 10
        
        items = [1, 2, 3, 4]
        result = await processor.process_batch(items, may_fail)
        
        assert result.successful_count == 3
        assert result.failed_count == 1
        assert result.results[0] == 10
        assert result.results[1] == 20
        assert result.results[2] is None  # Failed
        assert result.results[3] == 40
        assert "ValueError" in result.errors[2]
    
    @pytest.mark.asyncio
    async def test_process_batch_with_fallback(self):
        """Processor uses fallback value for errors."""
        processor = AsyncBatchProcessor(max_concurrent=2)
        
        async def may_fail(x: int) -> int:
            if x == 2:
                raise ValueError("Error")
            return x
        
        items = [1, 2, 3]
        result = await processor.process_batch(items, may_fail, fallback_value=-1)
        
        assert result.results == [1, -1, 3]
    
    @pytest.mark.asyncio
    async def test_process_batch_timeout(self):
        """Processor respects timeout_per_item."""
        processor = AsyncBatchProcessor(max_concurrent=2, timeout_per_item=0.05)
        
        async def slow_fn(x: int) -> int:
            if x == 2:
                await asyncio.sleep(0.2)  # Exceeds timeout
            return x
        
        items = [1, 2, 3]
        result = await processor.process_batch(items, slow_fn)
        
        assert result.successful_count == 2
        assert result.failed_count == 1
        assert result.results[0] == 1
        assert result.results[1] is None  # Timeout
        assert result.results[2] == 3
        assert "Timeout" in result.errors[1]
    
    @pytest.mark.asyncio
    async def test_process_batch_concurrency_limit(self):
        """Processor respects max_concurrent limit."""
        processor = AsyncBatchProcessor(max_concurrent=2)
        
        concurrent_count = 0
        max_concurrent_seen = 0
        
        async def track_concurrency(x: int) -> int:
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.02)
            concurrent_count -= 1
            return x
        
        items = list(range(10))
        result = await processor.process_batch(items, track_concurrency)
        
        assert result.successful_count == 10
        assert max_concurrent_seen <= 2
    
    @pytest.mark.asyncio
    async def test_process_batch_empty_list(self):
        """Processor handles empty input list."""
        processor = AsyncBatchProcessor()
        
        async def dummy(x: int) -> int:
            return x
        
        result = await processor.process_batch([], dummy)
        
        assert result.successful_count == 0
        assert result.failed_count == 0
        assert result.results == []
    
    @pytest.mark.asyncio
    async def test_process_batch_timing(self):
        """Processor tracks total processing time."""
        processor = AsyncBatchProcessor(max_concurrent=5)
        
        async def delay_fn(x: int) -> int:
            await asyncio.sleep(0.01)
            return x
        
        items = list(range(5))
        result = await processor.process_batch(items, delay_fn)
        
        # Should be at least 10ms (concurrent), but less than 50ms (sequential)
        assert result.total_time_ms >= 10
        assert result.total_time_ms < 80  # Allow some overhead


class TestAsyncBatchProcessorWithProgress:
    """Test progress tracking functionality."""
    
    @pytest.mark.asyncio
    async def test_process_batch_with_progress_callback(self):
        """Progress callback receives correct updates."""
        processor = AsyncBatchProcessor(max_concurrent=2)
        
        progress_updates = []
        
        def track_progress(completed: int, total: int):
            progress_updates.append((completed, total))
        
        async def process(x: int) -> int:
            await asyncio.sleep(0.01)
            return x
        
        items = [1, 2, 3, 4, 5]
        result = await processor.process_batch_with_progress(
            items,
            process,
            progress_callback=track_progress
        )
        
        assert result.successful_count == 5
        assert len(progress_updates) == 5
        assert progress_updates[-1] == (5, 5)
    
    @pytest.mark.asyncio
    async def test_process_batch_with_progress_no_callback(self):
        """Progress processing works without callback."""
        processor = AsyncBatchProcessor(max_concurrent=2)
        
        async def process(x: int) -> int:
            return x * 2
        
        items = [1, 2, 3]
        result = await processor.process_batch_with_progress(items, process)
        
        assert result.successful_count == 3
        assert result.results == [2, 4, 6]


class TestAsyncBatchProcessorChunked:
    """Test chunked processing functionality."""
    
    @pytest.mark.asyncio
    async def test_process_batch_chunked(self):
        """Chunked processing works correctly."""
        processor = AsyncBatchProcessor(max_concurrent=5)
        
        async def process(x: int) -> int:
            return x + 10
        
        items = list(range(25))
        result = await processor.process_batch_chunked(
            items,
            process,
            chunk_size=10
        )
        
        assert result.successful_count == 25
        assert result.failed_count == 0
        assert len(result.results) == 25
        assert result.results[0] == 10
        assert result.results[24] == 34
    
    @pytest.mark.asyncio
    async def test_process_batch_chunked_with_errors(self):
        """Chunked processing handles errors."""
        processor = AsyncBatchProcessor(max_concurrent=5)
        
        async def may_fail(x: int) -> int:
            if x % 7 == 0:
                raise ValueError(f"Error on {x}")
            return x
        
        items = list(range(20))
        result = await processor.process_batch_chunked(
            items,
            may_fail,
            chunk_size=5
        )
        
        # 0, 7, 14 should fail
        assert result.failed_count == 3
        assert result.successful_count == 17


class TestAsyncOntologyBatchProcessor:
    """Test AsyncOntologyBatchProcessor."""
    
    @pytest.mark.asyncio
    async def test_batch_extract_async(self):
        """Async batch extraction works."""
        mock_generator = Mock()
        mock_result = Mock()
        mock_result.entities = []
        mock_result.relationships = []
        mock_generator.extract_entities.return_value = mock_result
        
        processor = AsyncOntologyBatchProcessor(
            generator=mock_generator,
            max_concurrent=2
        )
        
        documents = ["doc1", "doc2", "doc3"]
        mock_context = Mock()
        
        results = await processor.batch_extract_async(documents, mock_context)
        
        assert len(results) == 3
        assert mock_generator.extract_entities.call_count == 3
    
    @pytest.mark.asyncio
    async def test_batch_extract_with_spans_async(self):
        """Async batch extraction with spans works."""
        mock_generator = Mock()
        mock_result = Mock()
        mock_result.entities = []
        mock_generator.extract_entities_with_spans.return_value = mock_result
        
        processor = AsyncOntologyBatchProcessor(
            generator=mock_generator,
            max_concurrent=2
        )
        
        documents = ["doc1", "doc2"]
        mock_context = Mock()
        
        results = await processor.batch_extract_with_spans_async(
            documents,
            mock_context
        )
        
        assert len(results) == 2
        assert mock_generator.extract_entities_with_spans.call_count == 2


class TestConvenienceFunction:
    """Test process_async_batch convenience function."""
    
    @pytest.mark.asyncio
    async def test_process_async_batch(self):
        """Convenience function works correctly."""
        async def async_fn(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 3
        
        items = [1, 2, 3, 4]
        results = await process_async_batch(
            items,
            async_fn,
            max_concurrent=2
        )
        
        assert results == [3, 6, 9, 12]
    
    @pytest.mark.asyncio
    async def test_process_async_batch_with_timeout(self):
        """Convenience function respects timeout."""
        async def slow_fn(x: int) -> int:
            if x == 3:
                await asyncio.sleep(1.0)
            return x
        
        items = [1, 2, 3, 4]
        results = await process_async_batch(
            items,
            slow_fn,
            max_concurrent=2,
            timeout_per_item=0.05
        )
        
        # Item 3 should timeout and return None
        assert results[0] == 1
        assert results[1] == 2
        assert results[2] is None
        assert results[3] == 4


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    @pytest.mark.asyncio
    async def test_fail_fast_mode(self):
        """Fail-fast mode stops on first error."""
        processor = AsyncBatchProcessor(max_concurrent=2, fail_fast=True)
        
        async def may_fail(x: int) -> int:
            if x == 2:
                raise ValueError("Stop here")
            await asyncio.sleep(0.1)  # Slow to ensure ordering
            return x
        
        items = [1, 2, 3, 4]
        
        with pytest.raises(ValueError):
            await processor.process_batch(items, may_fail)
    
    @pytest.mark.asyncio
    async def test_large_batch_performance(self):
        """Processor handles large batches efficiently."""
        processor = AsyncBatchProcessor(max_concurrent=20)
        
        async def quick_fn(x: int) -> int:
            await asyncio.sleep(0.001)
            return x
        
        items = list(range(1000))
        start = time.time()
        result = await processor.process_batch(items, quick_fn)
        elapsed = time.time() - start
        
        assert result.successful_count == 1000
        # With 20 concurrent, should be much faster than sequential
        assert elapsed < 5.0  # Should take well under 5 seconds
