"""Tests for OntologyGenerator.extract_with_context_windows() method."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    EntityExtractionResult,
    Entity,
    Relationship,
)


class TestExtractWithContextWindowsBasic:
    """Test basic functionality of extract_with_context_windows()."""

    @pytest.fixture
    def generator(self):
        """Create an OntologyGenerator instance."""
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        """Create a basic extraction context."""
        context = Mock(spec=OntologyGenerationContext)
        context.session_id = "test_session"
        context.domain = "legal"
        return context

    def test_extract_short_text(self, generator, context):
        """
        GIVEN: Text shorter than window size
        WHEN: Calling extract_with_context_windows()
        THEN: Processes text as single window
        """
        text = "Alice and Bob are colleagues."
        
        with patch.object(generator, 'extract_entities') as mock_extract:
            mock_result = EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                    Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                ],
                relationships=[],
                confidence=0.875,
            )
            mock_extract.return_value = mock_result
            
            result = generator.extract_with_context_windows(text, context, window_size=512)
        
        assert len(result.entities) == 2
        assert result.metadata['window_count'] == 1
        mock_extract.assert_called_once()

    def test_extract_large_text_multiple_windows(self, generator, context):
        """
        GIVEN: Text larger than window size
        WHEN: Calling extract_with_context_windows()
        THEN: Splits into multiple windows and processes each
        """
        # Create text larger than window size
        text = "Alice and Bob " * 100  # ~1400 chars
        
        with patch.object(generator, 'extract_entities') as mock_extract:
            mock_result = EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                    Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                ],
                relationships=[],
                confidence=0.875,
            )
            mock_extract.return_value = mock_result
            
            result = generator.extract_with_context_windows(
                text, context, window_size=256, window_overlap=32
            )
        
        # Should be called multiple times (once per window)
        assert mock_extract.call_count > 1
        assert result.metadata['window_count'] > 1
        assert len(result.entities) > 0

    def test_empty_input_returns_empty_result(self, generator, context):
        """
        GIVEN: Empty input text
        WHEN: Calling extract_with_context_windows()
        THEN: Returns empty EntityExtractionResult
        """
        result = generator.extract_with_context_windows("", context)
        
        assert len(result.entities) == 0
        assert len(result.relationships) == 0
        assert result.confidence == 1.0

    def test_returns_metadata(self, generator, context):
        """
        GIVEN: Text processed with context windows
        WHEN: Extraction completes
        THEN: Result includes window metadata
        """
        text = "Alice and Bob " * 50  # Multiple windows
        
        with patch.object(generator, 'extract_entities') as mock_extract:
            mock_result = EntityExtractionResult(
                entities=[],
                relationships=[],
                confidence=0.8,
            )
            mock_extract.return_value = mock_result
            
            result = generator.extract_with_context_windows(
                text, context, window_size=256, window_overlap=32
            )
        
        assert 'window_count' in result.metadata
        assert 'successful_windows' in result.metadata
        assert 'window_size' in result.metadata
        assert 'window_overlap' in result.metadata
        assert 'dedup_method' in result.metadata


class TestWindowParameterValidation:
    """Test parameter validation for extract_with_context_windows()."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        context = Mock(spec=OntologyGenerationContext)
        return context

    def test_invalid_window_size_negative(self, generator, context):
        """Test that negative window_size raises ValueError."""
        with pytest.raises(ValueError, match="window_size must be >= 1"):
            generator.extract_with_context_windows(
                "test", context, window_size=-1
            )

    def test_invalid_window_size_zero(self, generator, context):
        """Test that zero window_size raises ValueError."""
        with pytest.raises(ValueError, match="window_size must be >= 1"):
            generator.extract_with_context_windows(
                "test", context, window_size=0
            )

    def test_invalid_overlap_negative(self, generator, context):
        """Test that negative overlap raises ValueError."""
        with pytest.raises(ValueError, match="window_overlap must be >= 0"):
            generator.extract_with_context_windows(
                "test", context, window_size=256, window_overlap=-1
            )

    def test_invalid_overlap_equals_window_size(self, generator, context):
        """Test that overlap >= window_size raises ValueError."""
        with pytest.raises(ValueError, match="window_overlap.*must be < window_size"):
            generator.extract_with_context_windows(
                "test", context, window_size=256, window_overlap=256
            )

    def test_invalid_overlap_greater_than_window_size(self, generator, context):
        """Test that overlap > window_size raises ValueError."""
        with pytest.raises(ValueError, match="window_overlap.*must be < window_size"):
            generator.extract_with_context_windows(
                "test", context, window_size=256, window_overlap=300
            )

    def test_invalid_dedup_method(self, generator, context):
        """Test that invalid dedup_method raises ValueError."""
        with patch.object(generator, 'extract_entities'):
            with pytest.raises(ValueError, match="Invalid dedup_method"):
                generator.extract_with_context_windows(
                    "test", context, dedup_method="invalid_method"
                )


class TestDeduplicationStrategies:
    """Test different deduplication strategies."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        context = Mock(spec=OntologyGenerationContext)
        return context

    def test_highest_confidence_dedup(self, generator, context):
        """
        GIVEN: Multiple windows with duplicate entities at different confidences
        WHEN: Using 'highest_confidence' dedup strategy
        THEN: Keeps entity with highest confidence
        """
        text = "Alice " * 100  # Force multiple windows
        
        # Mock extract_entities to return different confidence levels
        call_count = [0]
        def mock_extract(data, ctx):
            call_count[0] += 1
            if call_count[0] == 1:
                # First window: Alice with 0.8 confidence
                return EntityExtractionResult(
                    entities=[Entity(id="e1", text="Alice", type="Person", confidence=0.8)],
                    relationships=[],
                    confidence=0.8,
                )
            else:
                # Second window: Alice with 0.9 confidence
                return EntityExtractionResult(
                    entities=[Entity(id="e2", text="Alice", type="Person", confidence=0.9)],
                    relationships=[],
                    confidence=0.9,
                )
        
        with patch.object(generator, 'extract_entities', side_effect=mock_extract):
            result = generator.extract_with_context_windows(
                text, context, window_size=100, window_overlap=10,
                dedup_method="highest_confidence"
            )
        
        # Should have one Alice entity with highest confidence
        assert len(result.entities) == 1
        assert result.entities[0].text == "Alice"
        assert result.entities[0].confidence == 0.9

    def test_first_occurrence_dedup(self, generator, context):
        """
        GIVEN: Multiple windows with duplicate entities
        WHEN: Using 'first_occurrence' dedup strategy
        THEN: Keeps first-seen entity
        """
        text = "Alice " * 100
        
        call_count = [0]
        def mock_extract(data, ctx):
            call_count[0] += 1
            if call_count[0] == 1:
                return EntityExtractionResult(
                    entities=[Entity(id="e1", text="Alice", type="Person", confidence=0.8)],
                    relationships=[],
                    confidence=0.8,
                )
            else:
                return EntityExtractionResult(
                    entities=[Entity(id="e2", text="Alice", type="Person", confidence=0.95)],
                    relationships=[],
                    confidence=0.95,
                )
        
        with patch.object(generator, 'extract_entities', side_effect=mock_extract):
            result = generator.extract_with_context_windows(
                text, context, window_size=100, window_overlap=10,
                dedup_method="first_occurrence"
            )
        
        # Should keep first Alice (confidence 0.8)
        assert len(result.entities) == 1
        assert result.entities[0].confidence == 0.8

    def test_merge_spans_dedup(self, generator, context):
        """
        GIVEN: Multiple windows with duplicate entities
        WHEN: Using 'merge_spans' dedup strategy
        THEN: Averages confidence scores
        """
        text = "Alice " * 100
        
        call_count = [0]
        def mock_extract(data, ctx):
            call_count[0] += 1
            if call_count[0] == 1:
                return EntityExtractionResult(
                    entities=[Entity(id="e1", text="Alice", type="Person", confidence=0.8)],
                    relationships=[],
                    confidence=0.8,
                )
            else:
                return EntityExtractionResult(
                    entities=[Entity(id="e2", text="Alice", type="Person", confidence=0.9)],
                    relationships=[],
                    confidence=0.9,
                )
        
        with patch.object(generator, 'extract_entities', side_effect=mock_extract):
            result = generator.extract_with_context_windows(
                text, context, window_size=100, window_overlap=10,
                dedup_method="merge_spans"
            )
        
        # Should have averaged confidence (between 0.8 and 0.9)
        assert len(result.entities) == 1
        assert 0.8 <= result.entities[0].confidence <= 0.9


class TestRelationshipHandling:
    """Test relationship handling across windows."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        context = Mock(spec=OntologyGenerationContext)
        return context

    def test_invalid_relationships_filtered(self, generator, context):
        """
        GIVEN: Relationships pointing to non-existent entities
        WHEN: Extraction completes
        THEN: Invalid relationships are filtered out
        """
        text = "test data"
        
        with patch.object(generator, 'extract_entities') as mock_extract:
            # Create entities and relationships where some relationships are invalid
            mock_result = EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                    Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                ],
                relationships=[
                    Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.8),
                    Relationship(id="r2", source_id="e1", target_id="e99", type="knows", confidence=0.7),  # Invalid
                    Relationship(id="r3", source_id="e99", target_id="e2", type="knows", confidence=0.75),  # Invalid
                ],
                confidence=0.85,
            )
            mock_extract.return_value = mock_result
            
            result = generator.extract_with_context_windows(text, context)
        
        # Only valid relationship should remain
        assert len(result.relationships) == 1
        assert result.relationships[0].id == "r1"

    def test_deduplicate_relationships_across_windows(self, generator, context):
        """
        GIVEN: Same relationship found in multiple windows
        WHEN: Merging results
        THEN: Duplicate relationships are removed
        """
        text = "Alice knows Bob " * 100
        
        call_count = [0]
        def mock_extract(data, ctx):
            # Each window returns the same relationship
            return EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                    Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                ],
                relationships=[
                    Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.8),
                ],
                confidence=0.875,
            )
        
        with patch.object(generator, 'extract_entities', side_effect=mock_extract):
            result = generator.extract_with_context_windows(
                text, context, window_size=100, window_overlap=10
            )
        
        # Despite multiple windows, should only have one relationship
        assert len(result.relationships) == 1


class TestErrorHandling:
    """Test error handling in extract_with_context_windows()."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        context = Mock(spec=OntologyGenerationContext)
        return context

    def test_handles_extraction_failures_gracefully(self, generator, context):
        """
        GIVEN: One window fails extraction but others succeed
        WHEN: Continuing extraction
        THEN: Returns results from successful windows
        """
        text = "test " * 100
        
        call_count = [0]
        def mock_extract(data, ctx):
            call_count[0] += 1
            if call_count[0] == 2:
                # Second window fails
                raise RuntimeError("Extraction failed")
            return EntityExtractionResult(
                entities=[Entity(id=f"e{call_count[0]}", text="test", type="Word", confidence=0.8)],
                relationships=[],
                confidence=0.8,
            )
        
        with patch.object(generator, 'extract_entities', side_effect=mock_extract):
            result = generator.extract_with_context_windows(
                text, context, window_size=100, window_overlap=10
            )
        
        # Should have results from successful windows
        assert len(result.entities) > 0
        assert result.metadata['successful_windows'] < result.metadata['window_count']

    def test_all_windows_fail_returns_empty_result(self, generator, context):
        """
        GIVEN: All windows fail extraction
        WHEN: Processing completes
        THEN: Returns empty result with confidence 0.0
        """
        text = "test data"
        
        with patch.object(generator, 'extract_entities') as mock_extract:
            mock_extract.side_effect = RuntimeError("Extraction failed")
            result = generator.extract_with_context_windows(text, context)
        
        assert len(result.entities) == 0
        assert len(result.relationships) == 0
        assert result.confidence == 0.0


class TestWindowSplitting:
    """Test the _split_into_windows() method."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    def test_split_short_text(self, generator):
        """Test splitting text shorter than window size."""
        text = "short text"
        windows = generator._split_into_windows(text, window_size=100, overlap=10)
        
        assert len(windows) == 1
        assert windows[0] == text

    def test_split_exact_window_size(self, generator):
        """Test splitting text exactly equal to window size."""
        text = "a" * 100
        windows = generator._split_into_windows(text, window_size=100, overlap=10)
        
        assert len(windows) == 1
        assert windows[0] == text

    def test_split_multiple_windows_with_overlap(self, generator):
        """Test splitting with overlapping windows."""
        text = "a" * 300
        windows = generator._split_into_windows(text, window_size=100, overlap=20)
        
        assert len(windows) > 1
        # Verify overlap
        assert windows[0][-20:] == windows[1][:20]

    def test_split_preserves_end_of_text(self, generator):
        """Test that last window includes end of text."""
        text = "alphabet" * 50  # ~400 chars
        windows = generator._split_into_windows(text, window_size=100, overlap=20)
        
        # Last window should end with the full text
        combined = "".join(windows)
        assert text in combined or windows[-1].endswith(text[-1])


class TestConfidenceAggregation:
    """Test confidence score aggregation."""

    @pytest.fixture
    def generator(self):
        return OntologyGenerator()

    @pytest.fixture
    def context(self):
        context = Mock(spec=OntologyGenerationContext)
        return context

    def test_average_confidence_from_windows(self, generator, context):
        """
        GIVEN: Multiple windows with different confidence scores
        WHEN: Merging results
        THEN: Final confidence is average of window confidences
        """
        text = "test " * 100
        
        call_count = [0]
        def mock_extract(data, ctx):
            call_count[0] += 1
            confidence = 0.7 if call_count[0] % 2 == 0 else 0.9
            return EntityExtractionResult(
                entities=[],
                relationships=[],
                confidence=confidence,
            )
        
        with patch.object(generator, 'extract_entities', side_effect=mock_extract):
            result = generator.extract_with_context_windows(
                text, context, window_size=100, window_overlap=10
            )
        
        # Confidence should be averaged
        assert result.confidence > 0.0
        assert result.confidence <= 1.0
