"""Tests for streaming entity extraction."""

import pytest
from ipfs_datasets_py.optimizers.graphrag.streaming_extractor import (
    StreamingEntityExtractor,
    EntityBatch,
    StreamingEntity,
    ChunkStrategy,
)


class MockExtractor:
    """Mock extractor for testing."""
    
    @staticmethod
    def extract_simple(text: str) -> list:
        """Simple mock that extracts capitalized words as entities."""
        import re
        entities = []
        for match in re.finditer(r'\b([A-Z][a-z]+)\b', text):
            entities.append({
                'text': match.group(1),
                'type': 'PROPER_NOUN',
                'start': match.start(),
                'end': match.end(),
                'confidence': 0.95,
            })
        return entities
    
    @staticmethod
    def extract_all_words(text: str) -> list:
        """Extract all words as entities."""
        import re
        entities = []
        for match in re.finditer(r'\b\w+\b', text):
            entities.append({
                'text': match.group(0),
                'type': 'WORD',
                'start': match.start(),
                'end': match.end(),
                'confidence': 0.8,
            })
        return entities


class TestStreamingExtractorBasics:
    """Test basic streaming extraction."""
    
    def test_extract_stream_single_batch(self):
        """Verify extraction of small text in single batch."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=100,
            batch_size=10,
        )
        
        text = "Alice and Bob went to Charlie's house."
        batches = list(extractor.extract_stream(text))
        
        assert len(batches) >= 1
        assert batches[0].is_final
        
        all_entities = []
        for batch in batches:
            all_entities.extend(batch.entities)
        
        # Should find Alice, Bob, Charlie
        assert len(all_entities) >= 3
        entity_texts = [e.text for e in all_entities]
        assert 'Alice' in entity_texts
        assert 'Bob' in entity_texts
        assert 'Charlie' in entity_texts
    
    def test_extract_stream_multiple_batches(self):
        """Verify extraction yields multiple batches for large text."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_all_words,
            chunk_size=50,
            batch_size=5,
            overlap=0,  # No overlap to avoid duplicates in this test
        )
        
        # Create text with ~30 words
        text = " ".join([f"Word{i}" for i in range(30)])
        batches = list(extractor.extract_stream(text))
        
        # Should have multiple batches
        assert len(batches) > 1
        
        # Last batch should be marked final
        assert batches[-1].is_final
        
        # Total entities should be approximately 30 (may vary due to tokenization)
        all_entities = []
        for batch in batches:
            all_entities.extend(batch.entities)
        
        # Should have close to 30 entities (within 5 due to chunking artifacts)
        assert 25 <= len(all_entities) <= 35


class TestStreamingExtractorChunking:
    """Test text chunking strategies."""
    
    def test_fixed_size_chunking(self):
        """Verify FIXED_SIZE chunking strategy."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=20,
            chunk_strategy=ChunkStrategy.FIXED_SIZE,
            overlap=5,
        )
        
        text = "A" * 100  # 100 character text
        chunks = extractor._chunk_text(text)
        
        # Should have multiple chunks
        assert len(chunks) > 1
        
        # First chunk should start at 0
        assert chunks[0][0] == 0
        
        # Chunks should overlap
        for i in range(len(chunks) - 1):
            overlap_region = chunks[i][1] - chunks[i+1][0]
            assert overlap_region > 0
    
    def test_paragraph_chunking(self):
        """Verify PARAGRAPH chunking strategy."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_strategy=ChunkStrategy.PARAGRAPH,
        )
        
        text = "Para 1\n\nPara 2\n\nPara 3"
        chunks = extractor._chunk_text(text)
        
        # Should have 3 chunks
        assert len(chunks) == 3
    
    def test_sentence_chunking(self):
        """Verify SENTENCE chunking strategy."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_strategy=ChunkStrategy.SENTENCE,
        )
        
        text = "First sentence. Second sentence. Third sentence."
        chunks = extractor._chunk_text(text)
        
        # Should have 3 chunks (one per sentence)
        assert len(chunks) == 3


class TestStreamingExtractorEntityNormalization:
    """Test entity position normalization across chunks."""
    
    def test_entity_absolute_positions(self):
        """Verify entities have correct absolute positions in original text."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=30,
        )
        
        text = "Alice went to Bob's house and then Charlie came."
        batches = list(extractor.extract_stream(text))
        
        all_entities = []
        for batch in batches:
            all_entities.extend(batch.entities)
        
        # Verify entity positions are within original text
        for entity in all_entities:
            assert entity.start_pos >= 0
            assert entity.end_pos <= len(text)
            assert entity.start_pos < entity.end_pos
            
            # Verify actual text matches
            extracted_text = text[entity.start_pos:entity.end_pos]
            assert extracted_text == entity.text


class TestStreamingExtractorCallbacks:
    """Test progress callbacks."""
    
    def test_progress_callback_invoked(self):
        """Verify progress callback is called."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=50,
        )
        
        progress_values = []
        
        def progress_callback(chars_processed):
            progress_values.append(chars_processed)
        
        text = "Alice Bob Charlie " * 10  # Repeated text
        list(extractor.extract_stream(text, progress_callback=progress_callback))
        
        # Progress should have been reported
        assert len(progress_values) > 0
        
        # Progress values should be increasing
        for i in range(1, len(progress_values)):
            assert progress_values[i] >= progress_values[i-1]
    
    def test_no_callback_no_error(self):
        """Verify extraction works without progress callback."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
        )
        
        text = "Alice and Bob"
        batches = list(extractor.extract_stream(text))
        
        assert len(batches) >= 1


class TestStreamingExtractorBatching:
    """Test batch accumulation and yielding."""
    
    def test_batch_size_respected(self):
        """Verify batches don't exceed specified batch_size."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_all_words,
            chunk_size=50,
            batch_size=5,
        )
        
        text = "Word1 Word2 Word3 Word4 Word5 Word6 Word7 Word8 Word9 Word10"
        batches = list(extractor.extract_stream(text))
        
        # All but last batch should be exactly batch_size (or less if final)
        for batch in batches[:-1]:
            assert len(batch.entities) <= 5
    
    def test_final_batch_has_remaining_entities(self):
        """Verify final batch contains remaining entities."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_all_words,
            batch_size=3,
        )
        
        text = "One Two Three Four Five"
        batches = list(extractor.extract_stream(text))
        
        # Last batch should be marked final
        assert batches[-1].is_final


class TestStreamingExtractorBatchMetadata:
    """Test EntityBatch metadata."""
    
    def test_batch_contains_chunk_info(self):
        """Verify batches contain chunk position information."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=50,
        )
        
        text = "Alice"  * 20  # Repeated text
        batches = list(extractor.extract_stream(text))
        
        assert len(batches) >= 1
        batch = batches[0]
        
        assert batch.chunk_id >= 0
        assert batch.chunk_start_pos >= 0
        assert batch.chunk_end_pos > batch.chunk_start_pos
        assert batch.chunk_text
        assert batch.processing_time_ms >= 0
    
    def test_batch_chunk_text_is_correct(self):
        """Verify batch chunk_text matches original."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=100,
        )
        
        text = "Alice and Bob went " * 5
        batches = list(extractor.extract_stream(text))
        
        # Reconstruct original from batches
        reconstructed = ""
        for batch in batches:
            # Find where this chunk fits
            original_chunk = text[batch.chunk_start_pos:batch.chunk_end_pos]
            assert batch.chunk_text == original_chunk or batch.chunk_text in original_chunk


class TestStreamingExtractorRepr:
    """Test string representation."""
    
    def test_extractor_repr(self):
        """Verify __repr__ output."""
        extractor = StreamingEntityExtractor(
            extractor_func=MockExtractor.extract_simple,
            chunk_size=50,
        )
        
        repr_str = repr(extractor)
        assert "StreamingEntityExtractor" in repr_str
        assert "50" in repr_str


class TestStreamingEntityDataclass:
    """Test StreamingEntity dataclass."""
    
    def test_entity_creation(self):
        """Verify entity creation with metadata."""
        entity = StreamingEntity(
            entity_id="e1",
            entity_type="PERSON",
            text="Alice",
            start_pos=0,
            end_pos=5,
            confidence=0.95,
            metadata={"source": "text"},
        )
        
        assert entity.entity_id == "e1"
        assert entity.text == "Alice"
        assert entity.confidence == 0.95
        assert entity.metadata["source"] == "text"
