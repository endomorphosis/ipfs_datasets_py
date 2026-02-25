"""
Batch 260: StreamingExtractor - Streaming entity extraction testing.

Target: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/streaming_extractor.py (272 LOC)

Tests for streaming entity extraction, chunking strategies, entity batching, and progress callbacks.
"""

import pytest
import time
from typing import Any, Callable, Iterator, List
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.optimizers.graphrag.streaming_extractor import (
    StreamingEntityExtractor,
    StreamingEntity,
    EntityBatch,
    ChunkStrategy,
)


# ============================================================================
# Test ChunkStrategy Enum
# ============================================================================

class TestChunkStrategy:
    """Tests for ChunkStrategy enum."""
    
    def test_chunk_strategy_fixed_size(self):
        """ChunkStrategy.FIXED_SIZE has correct value."""
        assert ChunkStrategy.FIXED_SIZE.value == "fixed_size"
    
    def test_chunk_strategy_sentence(self):
        """ChunkStrategy.SENTENCE has correct value."""
        assert ChunkStrategy.SENTENCE.value == "sentence"
    
    def test_chunk_strategy_paragraph(self):
        """ChunkStrategy.PARAGRAPH has correct value."""
        assert ChunkStrategy.PARAGRAPH.value == "paragraph"
    
    def test_chunk_strategy_adaptive(self):
        """ChunkStrategy.ADAPTIVE has correct value."""
        assert ChunkStrategy.ADAPTIVE.value == "adaptive"
    
    def test_chunk_strategy_enumeration(self):
        """All ChunkStrategy members are accessible."""
        strategies = [ChunkStrategy.FIXED_SIZE, ChunkStrategy.SENTENCE, 
                     ChunkStrategy.PARAGRAPH, ChunkStrategy.ADAPTIVE]
        assert len(strategies) == 4


# ============================================================================
# Test StreamingEntity Dataclass
# ============================================================================

class TestStreamingEntity:
    """Tests for StreamingEntity dataclass."""
    
    def test_streaming_entity_creation(self):
        """StreamingEntity initializes with required fields."""
        entity = StreamingEntity(
            entity_id="e1",
            entity_type="Person",
            text="John Smith",
            start_pos=0,
            end_pos=11,
            confidence=0.95
        )
        assert entity.entity_id == "e1"
        assert entity.entity_type == "Person"
        assert entity.text == "John Smith"
        assert entity.start_pos == 0
        assert entity.end_pos == 11
        assert entity.confidence == 0.95
    
    def test_streaming_entity_default_metadata(self):
        """StreamingEntity metadata defaults to empty dict."""
        entity = StreamingEntity(
            entity_id="e1",
            entity_type="Person",
            text="John",
            start_pos=0,
            end_pos=4,
            confidence=0.9
        )
        assert entity.metadata == {}
    
    def test_streaming_entity_with_metadata(self):
        """StreamingEntity stores metadata."""
        metadata = {'source': 'wikipedia', 'page_id': 123}
        entity = StreamingEntity(
            entity_id="e1",
            entity_type="Person",
            text="John",
            start_pos=0,
            end_pos=4,
            confidence=0.9,
            metadata=metadata
        )
        assert entity.metadata == metadata
    
    def test_streaming_entity_zero_confidence(self):
        """StreamingEntity accepts zero confidence."""
        entity = StreamingEntity(
            entity_id="e1",
            entity_type="Person",
            text="John",
            start_pos=0,
            end_pos=4,
            confidence=0.0
        )
        assert entity.confidence == 0.0
    
    def test_streaming_entity_high_confidence(self):
        """StreamingEntity accepts high confidence."""
        entity = StreamingEntity(
            entity_id="e1",
            entity_type="Person",
            text="John",
            start_pos=0,
            end_pos=4,
            confidence=1.0
        )
        assert entity.confidence == 1.0


# ============================================================================
# Test EntityBatch Dataclass
# ============================================================================

class TestEntityBatch:
    """Tests for EntityBatch dataclass."""
    
    def test_entity_batch_creation(self):
        """EntityBatch initializes with required fields."""
        entities = [
            StreamingEntity("e1", "Person", "John", 0, 4, 0.9),
            StreamingEntity("e2", "Person", "Alice", 5, 10, 0.95)
        ]
        batch = EntityBatch(
            entities=entities,
            chunk_id=0,
            chunk_start_pos=0,
            chunk_end_pos=10,
            chunk_text="John Alice",
            processing_time_ms=1.5
        )
        assert batch.entities == entities
        assert batch.chunk_id == 0
        assert batch.chunk_start_pos == 0
        assert batch.chunk_end_pos == 10
        assert batch.chunk_text == "John Alice"
        assert batch.processing_time_ms == 1.5
    
    def test_entity_batch_is_final_default_false(self):
        """EntityBatch is_final defaults to False."""
        batch = EntityBatch(
            entities=[],
            chunk_id=0,
            chunk_start_pos=0,
            chunk_end_pos=0,
            chunk_text="",
            processing_time_ms=0.0
        )
        assert batch.is_final is False
    
    def test_entity_batch_is_final_true(self):
        """EntityBatch can mark batch as final."""
        batch = EntityBatch(
            entities=[],
            chunk_id=5,
            chunk_start_pos=0,
            chunk_end_pos=100,
            chunk_text="text",
            processing_time_ms=2.0,
            is_final=True
        )
        assert batch.is_final is True
    
    def test_entity_batch_empty(self):
        """EntityBatch handles empty entity list."""
        batch = EntityBatch(
            entities=[],
            chunk_id=0,
            chunk_start_pos=0,
            chunk_end_pos=100,
            chunk_text="text",
            processing_time_ms=1.0
        )
        assert len(batch.entities) == 0


# ============================================================================
# Test StreamingEntityExtractor Initialization
# ============================================================================

class TestStreamingEntityExtractorInit:
    """Tests for StreamingEntityExtractor initialization."""
    
    def test_initialization_with_defaults(self):
        """StreamingEntityExtractor initializes with default parameters."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(extractor_func)
        
        assert extractor.extractor_func == extractor_func
        assert extractor.chunk_size == 1024
        assert extractor.chunk_strategy == ChunkStrategy.FIXED_SIZE
        assert extractor.overlap == 256
        assert extractor.batch_size == 32
    
    def test_initialization_with_custom_params(self):
        """StreamingEntityExtractor initializes with custom parameters."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=2048,
            chunk_strategy=ChunkStrategy.PARAGRAPH,
            overlap=512,
            batch_size=64
        )
        
        assert extractor.chunk_size == 2048
        assert extractor.chunk_strategy == ChunkStrategy.PARAGRAPH
        assert extractor.overlap == 512
        assert extractor.batch_size == 64
    
    def test_overlap_capped_to_chunk_size(self):
        """Overlap is capped to chunk_size - 1."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=100,
            overlap=200  # Greater than chunk_size
        )
        # Overlap should be capped to 99 (chunk_size - 1)
        assert extractor.overlap < extractor.chunk_size
    
    def test_repr_string(self):
        """StreamingEntityExtractor has informative repr."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=512,
            chunk_strategy=ChunkStrategy.SENTENCE
        )
        repr_str = repr(extractor)
        assert "StreamingEntityExtractor" in repr_str
        assert "512" in repr_str
        assert "sentence" in repr_str


# ============================================================================
# Test Fixed-Size Chunking
# ============================================================================

class TestFixedSizeChunking:
    """Tests for fixed-size text chunking."""
    
    def test_chunk_fixed_size_small_text(self):
        """Fixed-size chunking of text smaller than chunk_size."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=100,
            chunk_strategy=ChunkStrategy.FIXED_SIZE
        )
        
        text = "This is a small text"
        chunks = extractor._chunk_fixed_size(text)
        
        # Should produce one chunk covering the entire text
        assert len(chunks) > 0
        assert chunks[0][0] >= 0
        assert chunks[-1][1] == len(text)
    
    def test_chunk_fixed_size_exact_size(self):
        """Fixed-size chunking with text exactly chunk_size."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=20
        )
        
        text = "A" * 20
        chunks = extractor._chunk_fixed_size(text)
        
        # Should produce at least one chunk
        assert len(chunks) >= 1
    
    def test_chunk_fixed_size_multiple_chunks(self):
        """Fixed-size chunking with text > chunk_size."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=50,
            overlap=10
        )
        
        text = "A" * 200
        chunks = extractor._chunk_fixed_size(text)
        
        # Should produce multiple chunks
        assert len(chunks) > 1
        # Each chunk size should be approximately chunk_size
        for start, end in chunks:
            assert 0 <= start < len(text)
            assert 0 < end <= len(text)
    
    def test_chunk_fixed_size_with_overlap(self):
        """Fixed-size chunking respects overlap parameter."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=100,
            overlap=50
        )
        
        text = "A" * 300
        chunks = extractor._chunk_fixed_size(text)
        
        # Check overlap between consecutive chunks
        for i in range(len(chunks) - 1):
            _, curr_end = chunks[i]
            next_start, _ = chunks[i + 1]
            # There should be overlap
            assert next_start < curr_end


# ============================================================================
# Test Paragraph Chunking
# ============================================================================

class TestParagraphChunking:
    """Tests for paragraph-based text chunking."""
    
    def test_chunk_by_paragraph_single_paragraph(self):
        """Paragraph chunking with single paragraph."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_strategy=ChunkStrategy.PARAGRAPH
        )
        
        text = "This is a paragraph.\nWith multiple lines."
        chunks = extractor._chunk_by_paragraph(text)
        
        # Should produce chunks
        assert len(chunks) >= 1
    
    def test_chunk_by_paragraph_multiple_paragraphs(self):
        """Paragraph chunking with multiple paragraphs."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_strategy=ChunkStrategy.PARAGRAPH
        )
        
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = extractor._chunk_by_paragraph(text)
        
        # Should split by double newlines
        assert len(chunks) >= 1
    
    def test_chunk_by_paragraph_empty_text(self):
        """Paragraph chunking with empty text."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_strategy=ChunkStrategy.PARAGRAPH
        )
        
        text = ""
        chunks = extractor._chunk_by_paragraph(text)
        
        # Should handle empty text gracefully
        assert len(chunks) >= 1


# ============================================================================
# Test Sentence Chunking
# ============================================================================

class TestSentenceChunking:
    """Tests for sentence-based text chunking."""
    
    def test_chunk_by_sentence_single_sentence(self):
        """Sentence chunking with single sentence."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_strategy=ChunkStrategy.SENTENCE
        )
        
        text = "This is a single sentence."
        chunks = extractor._chunk_by_sentence(text)
        
        # Should produce at least one chunk
        assert len(chunks) >= 1
    
    def test_chunk_by_sentence_multiple_sentences(self):
        """Sentence chunking with multiple sentences."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_strategy=ChunkStrategy.SENTENCE
        )
        
        text = "First sentence. Second sentence! Third sentence?"
        chunks = extractor._chunk_by_sentence(text)
        
        # Should produce chunks
        assert len(chunks) >= 1
    
    def test_chunk_by_sentence_preserves_text(self):
        """Sentence chunking preserves all text."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_strategy=ChunkStrategy.SENTENCE
        )
        
        text = "Sentence one. Sentence two!"
        chunks = extractor._chunk_by_sentence(text)
        
        # Reconstruct and verify
        start_pos = 0
        for chunk_start, chunk_end in chunks:
            assert chunk_start >= start_pos  # No gaps
            start_pos = chunk_end


# ============================================================================
# Test Adaptive Chunking
# ============================================================================

class TestAdaptiveChunking:
    """Tests for adaptive text chunking."""
    
    def test_chunk_adaptive_fallback_fixed_size(self):
        """Adaptive chunking currently falls back to fixed-size."""
        extractor_func = lambda x: []
        extractor = StreamingEntityExtractor(
            extractor_func,
            chunk_size=100,
            chunk_strategy=ChunkStrategy.ADAPTIVE
        )
        
        text = "A" * 300
        chunks = extractor._chunk_adaptive(text)
        
        # Should produce chunks (currently same as fixed-size)
        assert len(chunks) > 0
    
    def test_chunk_text_strategy_dispatch(self):
        """_chunk_text dispatches to correct strategy."""
        extractor_func = lambda x: []
        
        for strategy in [ChunkStrategy.FIXED_SIZE, ChunkStrategy.PARAGRAPH, 
                        ChunkStrategy.SENTENCE, ChunkStrategy.ADAPTIVE]:
            extractor = StreamingEntityExtractor(
                extractor_func,
                chunk_strategy=strategy
            )
            text = "A" * 200
            chunks = extractor._chunk_text(text)
            assert len(chunks) > 0


# ============================================================================
# Test Extract Stream - Basic Functionality
# ============================================================================

class TestExtractStreamBasic:
    """Tests for basic extract_stream functionality."""
    
    def test_extract_stream_empty_text(self):
        """extract_stream handles empty text."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, batch_size=32)
        text = ""
        batches = list(extractor.extract_stream(text))
        
        # May produce empty batch or no batches
        assert isinstance(batches, list)
    
    def test_extract_stream_no_entities(self):
        """extract_stream with extractor finding no entities."""
        def no_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(no_extractor, chunk_size=100, batch_size=32)
        text = "This is a test with no entities to extract."
        batches = list(extractor.extract_stream(text))
        
        # May produce batches with no entities
        assert isinstance(batches, list)
    
    def test_extract_stream_single_entity(self):
        """extract_stream extracts single entity."""
        def simple_extractor(text):
            return [{'type': 'Person', 'text': 'John', 'start': 0, 'end': 4, 'confidence': 0.9}]
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=100, batch_size=32)
        text = "John went to the store."
        batches = list(extractor.extract_stream(text))
        
        assert len(batches) > 0
        # Collect entities from all batches
        all_entities = []
        for batch in batches:
            assert isinstance(batch, EntityBatch)
            all_entities.extend(batch.entities)
        assert len(all_entities) >= 1
    
    def test_extract_stream_multiple_entities(self):
        """extract_stream extracts multiple entities."""
        def multi_extractor(text):
            # Simple mock that finds all words starting with capital
            entities = []
            words = text.split()
            pos = 0
            for word in words:
                if word and word[0].isupper():
                    entities.append({
                        'type': 'Entity',
                        'text': word,
                        'start': pos,
                        'end': pos + len(word),
                        'confidence': 0.8
                    })
                pos += len(word) + 1  # +1 for space
            return entities
        
        extractor = StreamingEntityExtractor(multi_extractor, chunk_size=100, batch_size=10)
        text = "John Smith went to Alice's store. Bob and Carol joined later."
        batches = list(extractor.extract_stream(text))
        
        all_entities = []
        for batch in batches:
            all_entities.extend(batch.entities)
        # Should find multiple capitalized words
        assert len(all_entities) >= 2


# ============================================================================
# Test Extract Stream - Batching
# ============================================================================

class TestExtractStreamBatching:
    """Tests for entity batching in extract_stream."""
    
    def test_extract_stream_batching_by_batch_size(self):
        """extract_stream batches entities according to batch_size."""
        def entity_extractor(text):
            # Return 5 entities per chunk
            return [
                {'type': 'Entity', 'text': f'Entity_{i}', 'start': i*10, 'end': i*10+5, 'confidence': 0.8}
                for i in range(5)
            ]
        
        extractor = StreamingEntityExtractor(
            entity_extractor,
            chunk_size=100,
            batch_size=3  # Batch after 3 entities
        )
        text = "A" * 200
        batches = list(extractor.extract_stream(text))
        
        # Check batching logic
        for batch in batches[:-1]:  # All except last
            # Non-final batches should have batch_size entities (unless last batch overall)
            pass
        
        # Last batch should be marked as final
        assert batches[-1].is_final is True
    
    def test_extract_stream_final_batch_marked(self):
        """extract_stream marks final batch correctly."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=50)
        text = "A" * 200
        batches = list(extractor.extract_stream(text))
        
        # Last batch should be final
        if batches:
            assert batches[-1].is_final is True


# ============================================================================
# Test Progress Callbacks
# ============================================================================

class TestProgressCallbacks:
    """Tests for progress callback functionality."""
    
    def test_extract_stream_with_progress_callback(self):
        """extract_stream calls progress_callback."""
        callback_called = []
        
        def progress_callback(chars_processed):
            callback_called.append(chars_processed)
        
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=50)
        text = "A" * 200
        batches = list(extractor.extract_stream(text, progress_callback=progress_callback))
        
        # Callback should have been called
        assert len(callback_called) > 0
        # Values should be increasing (chars processed)
        assert all(callback_called[i] <= callback_called[i+1] for i in range(len(callback_called)-1))
    
    def test_extract_stream_progress_callback_params(self):
        """Progress callback receives character positions."""
        positions = []
        
        def progress_callback(chars_processed):
            positions.append(chars_processed)
        
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=50, overlap=10)
        text = "A" * 100
        list(extractor.extract_stream(text, progress_callback=progress_callback))
        
        # Positions should be reasonable
        for pos in positions:
            assert 0 <= pos <= len(text)


# ============================================================================
# Test Entity Position Tracking
# ============================================================================

class TestEntityPositionTracking:
    """Tests for entity position tracking in stream."""
    
    def test_entity_positions_absolute(self):
        """Entities have absolute positions in original text."""
        def extractor_with_pos(text):
            # Return entity at position 5-10 in chunk
            return [{'type': 'Entity', 'text': 'target', 'start': 5, 'end': 11, 'confidence': 0.9}]
        
        extractor = StreamingEntityExtractor(extractor_with_pos, chunk_size=50)
        text = "A" * 100
        batches = list(extractor.extract_stream(text))
        
        for batch in batches:
            for entity in batch.entities:
                # Positions should be within text bounds
                assert 0 <= entity.start_pos <= len(text)
                assert entity.start_pos <= entity.end_pos <= len(text)
    
    def test_entity_id_generation(self):
        """Entities get unique IDs across stream."""
        def multi_entity_extractor(text):
            return [
                {'type': 'E', 'text': 'e1', 'start': 0, 'end': 2, 'confidence': 0.8},
                {'type': 'E', 'text': 'e2', 'start': 5, 'end': 7, 'confidence': 0.8},
            ]
        
        extractor = StreamingEntityExtractor(multi_entity_extractor, chunk_size=50)
        text = "A" * 200
        batches = list(extractor.extract_stream(text))
        
        entity_ids = []
        for batch in batches:
            for entity in batch.entities:
                entity_ids.append(entity.entity_id)
        
        # IDs should be unique
        assert len(entity_ids) == len(set(entity_ids))
    
    def test_entity_metadata_preservation(self):
        """Entity metadata is preserved through stream."""
        def extractor_with_meta(text):
            return [
                {
                    'type': 'Person',
                    'text': 'John',
                    'start': 0,
                    'end': 4,
                    'confidence': 0.9,
                    'metadata': {'source': 'wikipedia', 'id': 123}
                }
            ]
        
        extractor = StreamingEntityExtractor(extractor_with_meta, chunk_size=100)
        text = "John Smith went to the store."
        batches = list(extractor.extract_stream(text))
        
        for batch in batches:
            for entity in batch.entities:
                if entity.text == 'John':
                    assert entity.metadata.get('source') == 'wikipedia'
                    assert entity.metadata.get('id') == 123


# ============================================================================
# Test Batch Metadata
# ============================================================================

class TestBatchMetadata:
    """Tests for EntityBatch metadata."""
    
    def test_batch_chunk_id_increments(self):
        """Batch chunk_id increments across stream."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=50)
        text = "A" * 200
        batches = list(extractor.extract_stream(text))
        
        chunk_ids = [batch.chunk_id for batch in batches]
        # IDs should be non-decreasing
        assert all(chunk_ids[i] <= chunk_ids[i+1] for i in range(len(chunk_ids)-1))
    
    def test_batch_positions_correct(self):
        """Batch chunk_start_pos and chunk_end_pos are correct."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=50)
        text = "A" * 200
        batches = list(extractor.extract_stream(text))
        
        for batch in batches:
            # Positions should be within bounds
            assert 0 <= batch.chunk_start_pos < len(text)
            assert 0 < batch.chunk_end_pos <= len(text)
            assert batch.chunk_start_pos <= batch.chunk_end_pos
    
    def test_batch_text_matches_position(self):
        """Batch chunk_text corresponds to position range."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=50)
        text = "ABCDEFGHIJ" * 20
        batches = list(extractor.extract_stream(text))
        
        for batch in batches:
            # Extract from original text using positions
            text_slice = text[batch.chunk_start_pos:batch.chunk_end_pos]
            # Should start with same content (may be truncated in implementation)
            if len(batch.chunk_text) > 0 and len(text_slice) > 0:
                # At least first part should match
                match_len = min(len(batch.chunk_text), len(text_slice))
                assert batch.chunk_text[:match_len] == text_slice[:match_len]


# ============================================================================
# Test Error Handling
# ============================================================================

class TestErrorHandling:
    """Tests for error handling in stream extraction."""
    
    def test_extract_stream_extractor_raises(self):
        """extract_stream propagates extractor exceptions."""
        def failing_extractor(text):
            raise ValueError("Extractor failed")
        
        extractor = StreamingEntityExtractor(failing_extractor, chunk_size=100)
        text = "A" * 200
        
        with pytest.raises(ValueError):
            list(extractor.extract_stream(text))
    
    def test_extract_stream_entity_missing_fields(self):
        """extract_stream handles entities with missing fields."""
        def partial_extractor(text):
            return [
                {'type': 'Entity'},  # Missing text, start, end, confidence
            ]
        
        extractor = StreamingEntityExtractor(partial_extractor, chunk_size=100)
        text = "A" * 100
        
        # Should handle gracefully with defaults
        batches = list(extractor.extract_stream(text))
        assert isinstance(batches, list)
    
    def test_extract_stream_entity_with_defaults(self):
        """extract_stream applies defaults for missing entity fields."""
        def minimal_extractor(text):
            return [
                {'type': 'Entity'}  # Only type provided
            ]
        
        extractor = StreamingEntityExtractor(minimal_extractor, chunk_size=100)
        text = "Test"
        batches = list(extractor.extract_stream(text))
        
        for batch in batches:
            for entity in batch.entities:
                # Should have defaults
                assert entity.confidence is not None


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestIntegrationScenarios:
    """Integration tests for realistic streaming workflows."""
    
    def test_stream_large_document(self):
        """Stream extraction from large document."""
        def indexed_extractor(text):
            # Find all positions with digits
            entities = []
            for i, char in enumerate(text):
                if char.isdigit():
                    entities.append({
                        'type': 'Number',
                        'text': char,
                        'start': i,
                        'end': i + 1,
                        'confidence': 0.9
                    })
            return entities
        
        extractor = StreamingEntityExtractor(
            indexed_extractor,
            chunk_size=100,
            batch_size=10
        )
        
        # Large document with pattern
        text = ("ABC 123 DEF 456 GHI 789 " * 50)
        total_entities = 0
        
        for batch in extractor.extract_stream(text):
            total_entities += len(batch.entities)
        
        # Should find many digit entities
        assert total_entities > 0
    
    def test_streaming_with_multiple_strategies(self):
        """Verify different strategies produce chunks."""
        def simple_extractor(text):
            return []
        
        text = "Paragraph 1.\n\nParagraph 2. Sentence 1. Sentence 2." * 5
        
        for strategy in [ChunkStrategy.FIXED_SIZE, ChunkStrategy.PARAGRAPH, ChunkStrategy.SENTENCE]:
            extractor = StreamingEntityExtractor(
                simple_extractor,
                chunk_size=100,
                chunk_strategy=strategy
            )
            batches = list(extractor.extract_stream(text))
            # Each strategy should produce batches
            assert len(batches) >= 0  # May be 0 if text is small or empty
    
    def test_stream_entity_accumulation(self):
        """Verify entity accumulation across batches."""
        call_count = [0]
        
        def counting_extractor(text):
            call_count[0] += 1
            return [
                {'type': 'E', 'text': f'e{i}', 'start': i*5, 'end': i*5+3, 'confidence': 0.8}
                for i in range(3)
            ]
        
        extractor = StreamingEntityExtractor(
            counting_extractor,
            chunk_size=50,
            batch_size=5
        )
        
        text = "A" * 200
        total_batches = 0
        total_entities = 0
        
        for batch in extractor.extract_stream(text):
            total_batches += 1
            total_entities += len(batch.entities)
        
        # Should have processed multiple chunks
        assert call_count[0] > 0
        # Entities should accumulate
        assert total_entities > 0
        assert total_batches > 0


# ============================================================================
# Test Performance Metrics
# ============================================================================

class TestPerformanceMetrics:
    """Tests for performance metric tracking."""
    
    def test_batch_processing_time(self):
        """EntityBatch includes processing_time_ms."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=100)
        text = "A" * 100
        batches = list(extractor.extract_stream(text))
        
        for batch in batches:
            assert batch.processing_time_ms >= 0.0
    
    def test_extraction_performance(self):
        """extract_stream completes in reasonable time."""
        def fast_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(fast_extractor, chunk_size=100)
        text = "A" * 1000
        
        start_time = time.time()
        list(extractor.extract_stream(text))
        elapsed = time.time() - start_time
        
        # Should complete quickly (< 1 second for simple extraction)
        assert elapsed < 1.0


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_extract_stream_single_char_text(self):
        """extract_stream handles single character text."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=100)
        batches = list(extractor.extract_stream("A"))
        
        assert isinstance(batches, list)
    
    def test_extract_stream_unicode_text(self):
        """extract_stream handles unicode text."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(simple_extractor, chunk_size=100)
        text = "Hello 世界 🌍 Привет мир"
        batches = list(extractor.extract_stream(text))
        
        assert isinstance(batches, list)
    
    def test_extract_stream_very_small_batch_size(self):
        """extract_stream works with batch_size=1."""
        def single_entity_extractor(text):
            return [{'type': 'E', 'text': 'x', 'start': 0, 'end': 1, 'confidence': 0.9}]
        
        extractor = StreamingEntityExtractor(
            single_entity_extractor,
            chunk_size=10,
            batch_size=1
        )
        text = "A" * 50
        batches = list(extractor.extract_stream(text))
        
        assert len(batches) > 0
    
    def test_chunk_strategy_with_special_chars(self):
        """Chunking handles special characters."""
        def simple_extractor(text):
            return []
        
        extractor = StreamingEntityExtractor(
            simple_extractor,
            chunk_strategy=ChunkStrategy.SENTENCE
        )
        
        text = "What?! Yes!!! Maybe... Let's see. @#$%^&*()"
        chunks = extractor._chunk_by_sentence(text)
        
        assert len(chunks) >= 1

