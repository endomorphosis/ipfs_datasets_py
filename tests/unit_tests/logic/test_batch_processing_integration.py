"""
Integration tests for batch processing.

Tests batch processing functionality end-to-end.
"""

import pytest
import asyncio
from ipfs_datasets_py.logic.batch_processing import (
    FOLBatchProcessor,
    ChunkedBatchProcessor,
    BatchResult,
)


class TestFOLBatchProcessorIntegration:
    """Integration tests for FOL batch processing."""

    @pytest.mark.asyncio
    async def test_batch_conversion_success(self):
        """
        GIVEN: A batch of valid sentences
        WHEN: Processing with FOLBatchProcessor
        THEN: Should convert all successfully
        """
        processor = FOLBatchProcessor(max_concurrency=5)
        
        texts = [
            "All humans are mortal",
            "Some birds can fly",
            "Dogs are animals",
            "Cats are mammals",
            "Fish live in water"
        ]
        
        result = await processor.convert_batch(
            texts,
            use_nlp=False,  # Faster for tests
            confidence_threshold=0.5
        )
        
        assert isinstance(result, BatchResult)
        assert result.total_items == 5
        assert result.successful >= 4  # At least 80% success
        assert result.items_per_second > 0
        assert result.total_time > 0

    @pytest.mark.asyncio
    async def test_batch_with_empty_items(self):
        """
        GIVEN: Batch containing empty strings
        WHEN: Processing batch
        THEN: Should handle gracefully
        """
        processor = FOLBatchProcessor(max_concurrency=5)
        
        texts = [
            "All humans are mortal",
            "",  # Empty
            "Some birds can fly",
            "",  # Empty
            "Dogs are animals"
        ]
        
        result = await processor.convert_batch(texts, use_nlp=False)
        
        assert result.total_items == 5
        assert result.successful >= 3  # Non-empty items

    @pytest.mark.asyncio
    async def test_large_batch_performance(self):
        """
        GIVEN: Large batch of texts
        WHEN: Processing with batch processor
        THEN: Should achieve good throughput
        """
        processor = FOLBatchProcessor(max_concurrency=10)
        
        # Generate 50 texts
        texts = [f"Statement number {i} is true" for i in range(50)]
        
        result = await processor.convert_batch(texts, use_nlp=False)
        
        assert result.total_items == 50
        assert result.items_per_second > 10  # At least 10 items/sec
        assert result.success_rate() > 80  # At least 80% success rate

    @pytest.mark.asyncio
    async def test_batch_error_handling(self):
        """
        GIVEN: Batch with some invalid items
        WHEN: Processing batch
        THEN: Should continue processing and track errors
        """
        processor = FOLBatchProcessor(max_concurrency=5)
        
        texts = [
            "Valid sentence one",
            "Valid sentence two",
            "Valid sentence three"
        ]
        
        result = await processor.convert_batch(texts, use_nlp=False)
        
        # Should complete even if some items fail
        assert result.total_items == 3
        assert result.successful + result.failed == 3


class TestChunkedBatchProcessorIntegration:
    """Integration tests for chunked batch processing."""

    @pytest.mark.asyncio
    async def test_chunked_processing(self):
        """
        GIVEN: Large dataset requiring chunking
        WHEN: Processing with ChunkedBatchProcessor
        THEN: Should process in chunks efficiently
        """
        processor = ChunkedBatchProcessor(
            chunk_size=10,
            max_concurrency=5
        )
        
        # Generate 25 items (3 chunks)
        items = [f"Item {i}" for i in range(25)]
        
        async def simple_processor(item):
            await asyncio.sleep(0.001)  # Simulate work
            return {"processed": item}
        
        result = await processor.process_large_batch(
            items=items,
            process_func=simple_processor
        )
        
        assert result.total_items == 25
        assert result.successful == 25
        assert len(result.results) == 25

    @pytest.mark.asyncio
    async def test_memory_efficient_processing(self):
        """
        GIVEN: Very large dataset
        WHEN: Processing with small chunks
        THEN: Should not load all into memory
        """
        processor = ChunkedBatchProcessor(
            chunk_size=5,
            max_concurrency=3
        )
        
        # Simulate large dataset
        large_dataset = [f"Data {i}" for i in range(100)]
        
        async def process_item(item):
            return {"result": len(item)}
        
        result = await processor.process_large_batch(
            items=large_dataset,
            process_func=process_item
        )
        
        assert result.total_items == 100
        assert result.successful == 100


class TestBatchProcessingPerformance:
    """Performance tests for batch processing."""

    @pytest.mark.asyncio
    async def test_batch_faster_than_sequential(self):
        """
        GIVEN: Same workload
        WHEN: Comparing batch vs sequential
        THEN: Batch should be significantly faster
        """
        import time
        
        texts = ["Test sentence"] * 20
        
        # Sequential
        start = time.time()
        for text in texts:
            from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol
            await convert_text_to_fol(text, use_nlp=False)
        sequential_time = time.time() - start
        
        # Batch
        processor = FOLBatchProcessor(max_concurrency=10)
        start = time.time()
        await processor.convert_batch(texts, use_nlp=False)
        batch_time = time.time() - start
        
        # Batch should be faster
        speedup = sequential_time / batch_time
        assert speedup > 1.5  # At least 1.5x faster

    @pytest.mark.asyncio
    async def test_concurrency_scaling(self):
        """
        GIVEN: Different concurrency levels
        WHEN: Processing same batch
        THEN: Higher concurrency should be faster
        """
        import time
        
        texts = ["Test"] * 20
        results = {}
        
        for concurrency in [1, 5, 10]:
            processor = FOLBatchProcessor(max_concurrency=concurrency)
            
            start = time.time()
            result = await processor.convert_batch(texts, use_nlp=False)
            elapsed = time.time() - start
            
            results[concurrency] = result.items_per_second
        
        # Higher concurrency should give better throughput
        assert results[10] > results[5] > results[1]


class TestBatchResultStatistics:
    """Test batch result statistics and reporting."""

    @pytest.mark.asyncio
    async def test_batch_result_structure(self):
        """
        GIVEN: Completed batch processing
        WHEN: Examining result
        THEN: Should have all expected fields
        """
        processor = FOLBatchProcessor(max_concurrency=5)
        
        result = await processor.convert_batch(
            ["Test 1", "Test 2"],
            use_nlp=False
        )
        
        assert hasattr(result, 'total_items')
        assert hasattr(result, 'successful')
        assert hasattr(result, 'failed')
        assert hasattr(result, 'total_time')
        assert hasattr(result, 'items_per_second')
        assert hasattr(result, 'results')
        assert hasattr(result, 'errors')

    @pytest.mark.asyncio
    async def test_success_rate_calculation(self):
        """
        GIVEN: Batch with mixed success/failure
        WHEN: Calculating success rate
        THEN: Should compute correctly
        """
        processor = FOLBatchProcessor(max_concurrency=5)
        
        result = await processor.convert_batch(
            ["Valid"] * 8 + [""] * 2,  # 80% valid
            use_nlp=False
        )
        
        success_rate = result.success_rate()
        assert 70 <= success_rate <= 100  # At least 70%

    @pytest.mark.asyncio
    async def test_to_dict_serialization(self):
        """
        GIVEN: BatchResult
        WHEN: Converting to dictionary
        THEN: Should serialize properly
        """
        processor = FOLBatchProcessor(max_concurrency=5)
        
        result = await processor.convert_batch(
            ["Test"],
            use_nlp=False
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict, dict)
        assert 'total_items' in result_dict
        assert 'successful' in result_dict
        assert 'success_rate' in result_dict
        assert 'items_per_second' in result_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
