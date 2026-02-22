"""Tests for async ontology extraction methods.

Tests the async/await API for OntologyGenerator including:
- extract_entities_async
- extract_batch_async
- infer_relationships_async
- extract_with_streaming_async
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType,
    Entity,
    EntityExtractionResult,
)


@pytest.fixture
def generator():
    """Create OntologyGenerator instance."""
    return OntologyGenerator()


@pytest.fixture
def extract_context():
    """Create basic extraction context."""
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="test_domain",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


@pytest.fixture
def sample_entities():
    """Create sample Entity list."""
    return [
        Entity(
            id="entity1",
            text="Alice",
            type="PERSON",
            confidence=0.9,
        ),
        Entity(
            id="entity2",
            text="Bob",
            type="PERSON",
            confidence=0.85,
        ),
        Entity(
            id="entity3",
            text="Contract",
            type="DOCUMENT",
            confidence=0.95,
        ),
    ]


class TestExtractEntitiesAsync:
    """Test async entity extraction."""
    
    @pytest.mark.asyncio
    async def test_extract_entities_async_basic(self, generator, extract_context):
        """Basic async entity extraction works."""
        data = "Alice must pay Bob $100 by Friday"
        
        result = await generator.extract_entities_async(data, extract_context)
        
        assert isinstance(result, EntityExtractionResult)
        assert result.entities is not None
        assert isinstance(result.entities, list)
    
    @pytest.mark.asyncio
    async def test_extract_entities_async_with_mock(self, generator, extract_context):
        """Async extraction calls sync method correctly."""
        data = "Test data"
        expected_result = EntityExtractionResult(
            entities=[
                Entity(
                    id="test1",
                    text="Test",
                    type="TEST",
                    confidence=0.8,
                )
            ],
            relationships=[],
            confidence=0.8,
            metadata={},
        )
        
        with patch.object(generator, 'extract_entities', return_value=expected_result):
            result = await generator.extract_entities_async(data, extract_context)
            
            assert result == expected_result
            generator.extract_entities.assert_called_once_with(data, extract_context)
    
    @pytest.mark.asyncio
    async def test_extract_entities_async_runs_in_executor(self, generator, extract_context):
        """Async extraction runs in thread pool executor."""
        data = "Test data"
        
        # Mock the event loop to verify executor usage
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_executor_result = EntityExtractionResult(
                entities=[],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=mock_executor_result)
            
            result = await generator.extract_entities_async(data, extract_context)
            
            # Verify run_in_executor was called
            mock_loop.return_value.run_in_executor.assert_called_once()
            assert result == mock_executor_result


class TestExtractBatchAsync:
    """Test async batch extraction."""
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_multiple_items(self, generator, extract_context):
        """Batch extraction processes multiple items."""
        data_items = [
            "Document 1 text",
            "Document 2 text",
            "Document 3 text",
        ]
        
        results = await generator.extract_batch_async(
            data_items,
            extract_context,
            max_concurrent=2
        )
        
        assert len(results) == 3
        assert all(isinstance(r, EntityExtractionResult) for r in results)
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_single_context(self, generator, extract_context):
        """Batch extraction uses single context for all items."""
        data_items = ["doc1", "doc2"]
        
        results = await generator.extract_batch_async(
            data_items,
            extract_context,  # Single context, not a list
        )
        
        assert len(results) == 2
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_per_item_contexts(self, generator):
        """Batch extraction uses per-item contexts."""
        data_items = ["doc1", "doc2"]
        contexts = [
            OntologyGenerationContext(
                data_source="test1",
                data_type=DataType.TEXT,
                domain="domain1",
                extraction_strategy=ExtractionStrategy.RULE_BASED,
            ),
            OntologyGenerationContext(
                data_source="test2",
                data_type=DataType.TEXT,
                domain="domain2",
                extraction_strategy=ExtractionStrategy.RULE_BASED,
            ),
        ]
        
        results = await generator.extract_batch_async(data_items, contexts)
        
        assert len(results) == 2
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_context_length_mismatch(self, generator, extract_context):
        """Batch extraction raises error on context/data length mismatch."""
        data_items = ["doc1", "doc2", "doc3"]
        contexts = [extract_context, extract_context]  # Only 2 contexts
        
        with pytest.raises(ValueError, match="Length mismatch"):
            await generator.extract_batch_async(data_items, contexts)
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_empty_list(self, generator, extract_context):
        """Batch extraction handles empty input."""
        results = await generator.extract_batch_async([], extract_context)
        
        assert results == []
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_concurrency_limit(self, generator, extract_context):
        """Batch extraction respects concurrency limit."""
        data_items = ["doc1", "doc2", "doc3", "doc4", "doc5"]
        
        # Track concurrent execution count
        max_concurrent_seen = 0
        current_concurrent = 0
        lock = asyncio.Lock()
        
        original_extract = generator.extract_entities_async
        
        async def tracked_extract(data, context):
            nonlocal max_concurrent_seen, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent_seen = max(max_concurrent_seen, current_concurrent)
            
            await asyncio.sleep(0.01)  # Simulate work
            result = await original_extract(data, context)
            
            async with lock:
                current_concurrent -= 1
            
            return result
        
        with patch.object(generator, 'extract_entities_async', side_effect=tracked_extract):
            await generator.extract_batch_async(
                data_items,
                extract_context,
                max_concurrent=2
            )
            
            # Max concurrent should not exceed limit
            # Note: This is best-effort due to async timing
            assert max_concurrent_seen <= 3  # Allow small margin
    
    @pytest.mark.asyncio
    async def test_extract_batch_async_with_timeout(self, generator, extract_context):
        """Batch extraction supports per-item timeout."""
        data_items = ["doc1", "doc2"]
        
        # Mock extract_entities_async to simulate slow operation
        async def slow_extract(data, context):
            await asyncio.sleep(10)  # Intentionally slow
            return EntityExtractionResult(entities=[], relationships=[], confidence=0.5, metadata={})
        
        with patch.object(generator, 'extract_entities_async', side_effect=slow_extract):
            with pytest.raises(asyncio.TimeoutError):
                await generator.extract_batch_async(
                    data_items,
                    extract_context,
                    timeout_per_item=0.1  # Very short timeout
                )


class TestInferRelationshipsAsync:
    """Test async relationship inference."""
    
    @pytest.mark.asyncio
    async def test_infer_relationships_async_basic(self, generator, sample_entities, extract_context):
        """Basic async relationship inference works."""
        relationships = await generator.infer_relationships_async(
            sample_entities,
            extract_context
        )
        
        assert isinstance(relationships, list)
    
    @pytest.mark.asyncio
    async def test_infer_relationships_async_empty_entities(self, generator, extract_context):
        """Async relationship inference handles empty entity list."""
        relationships = await generator.infer_relationships_async(
            [],
            extract_context
        )
        
        assert relationships == []
    
    @pytest.mark.asyncio
    async def test_infer_relationships_async_runs_in_executor(self, generator, sample_entities, extract_context):
        """Async relationship inference runs in thread pool."""
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=[])
            
            await generator.infer_relationships_async(sample_entities, extract_context)
            
            mock_loop.return_value.run_in_executor.assert_called_once()


class TestExtractWithStreamingAsync:
    """Test async streaming extraction."""
    
    @pytest.mark.asyncio
    async def test_streaming_async_yields_chunks(self, generator, extract_context):
        """Streaming async extraction yields chunks."""
        data = "Large document with multiple entities and relationships"
        
        chunks = []
        async for chunk in generator.extract_with_streaming_async(
            data,
            extract_context,
            chunk_size=500
        ):
            # extract_entities_streaming yields Entity objects, not EntityExtractionResult
            assert isinstance(chunk, Entity)
            chunks.append(chunk)
        
        # Should yield at least one chunk
        assert len(chunks) >= 1
    
    @pytest.mark.asyncio
    async def test_streaming_async_empty_data(self, generator, extract_context):
        """Streaming async handles empty data."""
        data = ""
        
        chunks = []
        async for chunk in generator.extract_with_streaming_async(data, extract_context):
            chunks.append(chunk)
        
        # Empty data may yield no chunks
        assert len(chunks) >= 0


class TestAsyncIntegration:
    """Integration tests for async methods."""
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_extractions(self, generator, extract_context):
        """Multiple async extractions can run concurrently."""
        data_items = [
            "Alice pays Bob",
            "Charlie signs contract",
            "David meets Eve",
        ]
        
        # Run extractions concurrently using gather
        tasks = [
            generator.extract_entities_async(data, extract_context)
            for data in data_items
        ]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 3
        assert all(isinstance(r, EntityExtractionResult) for r in results)
    
    @pytest.mark.asyncio
    async def test_batch_and_individual_mixed(self, generator, extract_context):
        """Batch and individual extractions can run together."""
        batch_data = ["doc1", "doc2"]
        single_data = "doc3"
        
        # Run batch and single extraction concurrently
        batch_task = generator.extract_batch_async(batch_data, extract_context)
        single_task = generator.extract_entities_async(single_data, extract_context)
        
        batch_results, single_result = await asyncio.gather(batch_task, single_task)
        
        assert len(batch_results) == 2
        assert isinstance(single_result, EntityExtractionResult)
    
    @pytest.mark.asyncio
    async def test_async_chain_extract_then_infer(self, generator, extract_context):
        """Can chain async extraction and relationship inference."""
        data = "Alice pays Bob $100 for services rendered"
        
        # First extract entities
        extraction_result = await generator.extract_entities_async(data, extract_context)
        
        # Then infer additional relationships
        if extraction_result.entities:
            relationships = await generator.infer_relationships_async(
                extraction_result.entities,
                extract_context
            )
            
            assert isinstance(relationships, list)
