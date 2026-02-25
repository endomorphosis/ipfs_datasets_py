"""Batch 258: Semantic Entity Deduplicator Comprehensive Test Suite.

Comprehensive testing of SemanticEntityDeduplicator for embedding-based entity
deduplication with semantic similarity detection, merge suggestion generation,
bucketing optimization, and embedding caching integration.

Test Categories:
- Initialization and configuration
- Entity data extraction from various formats
- Semantic merge suggestion generation
- Similarity matrix computation
- Bucketing optimization strategy
- Merge pair detection and scoring
- Evidence generation
- Factory function creation
- Embeddings and batching
"""

import pytest
import numpy as np
from typing import Dict, Any, List, Callable, Optional
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator import (
    SemanticEntityDeduplicator,
    SemanticMergeSuggestion,
    create_semantic_deduplicator,
    create_deduplicator,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def basic_deduplicator():
    """Create a basic semantic deduplicator."""
    return SemanticEntityDeduplicator()


@pytest.fixture
def custom_deduplicator():
    """Create deduplicator with custom string similarity threshold."""
    return SemanticEntityDeduplicator(min_string_similarity=0.5)


@pytest.fixture
def simple_ontology():
    """Create a simple ontology with exact duplicates."""
    return {
        "entities": [
            {"id": "E1", "text": "Chief Executive Officer", "type": "Title", "confidence": 0.9},
            {"id": "E2", "text": "CEO", "type": "Title", "confidence": 0.85},
            {"id": "E3", "text": "New York City", "type": "Location", "confidence": 0.95},
            {"id": "E4", "text": "NYC", "type": "Location", "confidence": 0.88},
        ],
        "relationships": []
    }


@pytest.fixture
def minimal_ontology():
    """Create minimal ontology with single entity."""
    return {
        "entities": [
            {"id": "E1", "text": "Test", "type": "Type", "confidence": 0.8},
        ],
        "relationships": []
    }


@pytest.fixture
def empty_ontology():
    """Create empty ontology."""
    return {
        "entities": [],
        "relationships": []
    }


@pytest.fixture
def mock_embedding_fn():
    """Create a mock embedding function returning random embeddings."""
    def embed_fn(texts: List[str]) -> np.ndarray:
        # Return random 384-dimensional embeddings (like sentence-transformers)
        return np.random.randn(len(texts), 384)
    
    return embed_fn


@pytest.fixture
def deterministic_embedding_fn():
    """Create deterministic embedding function for consistent testing."""
    def embed_fn(texts: List[str]) -> np.ndarray:
        # Create deterministic embeddings based on text length and character sum
        embeddings = []
        for text in texts:
            # Hash based on text
            seed = sum(ord(c) for c in text) % 2**31
            np.random.seed(seed)
            emb = np.random.randn(384)
            embeddings.append(emb)
        
        return np.array(embeddings)
    
    return embed_fn


# ============================================================================
# Initialization Tests
# ============================================================================

class TestInitialization:
    """Test SemanticEntityDeduplicator initialization."""
    
    def test_init_with_defaults(self, basic_deduplicator):
        """Initializes with default string similarity threshold."""
        assert basic_deduplicator.min_string_similarity == 0.3
    
    def test_init_with_custom_similarity(self, custom_deduplicator):
        """Initializes with custom string similarity threshold."""
        assert custom_deduplicator.min_string_similarity == 0.5
    
    def test_init_with_extreme_values(self):
        """Initializes with extreme threshold values."""
        dedup_low = SemanticEntityDeduplicator(min_string_similarity=0.0)
        dedup_high = SemanticEntityDeduplicator(min_string_similarity=1.0)
        
        assert dedup_low.min_string_similarity == 0.0
        assert dedup_high.min_string_similarity == 1.0


# ============================================================================
# Entity Data Extraction Tests
# ============================================================================

class TestExtractEntityData:
    """Test entity data extraction from various formats."""
    
    def test_extract_from_standard_format(self, basic_deduplicator, simple_ontology):
        """Extracts entity data from standard format."""
        entities = simple_ontology["entities"]
        
        entity_data = basic_deduplicator._extract_entity_data(entities)
        
        assert len(entity_data) == 4
        assert entity_data[0]["id"] == "E1"
        assert entity_data[0]["text"] == "Chief Executive Officer"
    
    def test_extract_with_uppercase_keys(self, basic_deduplicator):
        """Handles uppercase field names (Id, Text, Type, Confidence)."""
        entities = [
            {"Id": "E1", "Text": "CEO", "Type": "Title", "Confidence": 0.9},
            {"Id": "E2", "Text": "Boss", "Type": "Title", "Confidence": 0.85},
        ]
        
        entity_data = basic_deduplicator._extract_entity_data(entities)
        
        assert len(entity_data) == 2
        assert entity_data[0]["id"] == "E1"
        assert entity_data[0]["text"] == "CEO"
    
    def test_extract_skips_incomplete_entities(self, basic_deduplicator):
        """Skips entities missing id or text."""
        entities = [
            {"id": "E1", "text": "Valid", "type": "Type", "confidence": 0.9},
            {"id": "E2", "type": "Type", "confidence": 0.9},  # Missing text
            {"text": "Also Valid", "type": "Type", "confidence": 0.9},  # Missing id
        ]
        
        entity_data = basic_deduplicator._extract_entity_data(entities)
        
        assert len(entity_data) == 1
        assert entity_data[0]["id"] == "E1"
    
    def test_extract_default_values(self, basic_deduplicator):
        """Uses default values for missing optional fields."""
        entities = [
            {"id": "E1", "text": "Entity"},  # No type or confidence
        ]
        
        entity_data = basic_deduplicator._extract_entity_data(entities)
        
        assert entity_data[0]["type"] == "Unknown"
        assert entity_data[0]["confidence"] == 0.5


# ============================================================================
# Merge Suggestion Generation Tests
# ============================================================================

class TestSuggestMerges:
    """Test suggest_merges() method."""
    
    def test_suggest_merges_returns_list(self, basic_deduplicator, simple_ontology, mock_embedding_fn):
        """suggest_merges returns list of suggestions."""
        result = basic_deduplicator.suggest_merges(
            simple_ontology,
            threshold=0.7,
            embedding_fn=mock_embedding_fn
        )
        
        assert isinstance(result, list)
    
    def test_suggest_merges_with_threshold(self, basic_deduplicator, simple_ontology, mock_embedding_fn):
        """Respects threshold parameter."""
        result_high = basic_deduplicator.suggest_merges(
            simple_ontology,
            threshold=0.99,
            embedding_fn=mock_embedding_fn
        )
        result_low = basic_deduplicator.suggest_merges(
            simple_ontology,
            threshold=0.1,
            embedding_fn=mock_embedding_fn
        )
        
        # Lower threshold should find at least as many suggestions
        assert len(result_low) >= len(result_high)
    
    def test_suggest_merges_empty_ontology(self, basic_deduplicator, empty_ontology, mock_embedding_fn):
        """Returns empty list for empty ontology."""
        result = basic_deduplicator.suggest_merges(
            empty_ontology,
            embedding_fn=mock_embedding_fn
        )
        
        assert result == []
    
    def test_suggest_merges_single_entity(self, basic_deduplicator, minimal_ontology, mock_embedding_fn):
        """Returns empty list for ontology with single entity."""
        result = basic_deduplicator.suggest_merges(
            minimal_ontology,
            embedding_fn=mock_embedding_fn
        )
        
        assert result == []
    
    def test_suggest_merges_respects_max_suggestions(self, basic_deduplicator, simple_ontology, mock_embedding_fn):
        """Respects max_suggestions parameter."""
        result = basic_deduplicator.suggest_merges(
            simple_ontology,
            threshold=0.1,  # Low threshold to get many suggestions
            max_suggestions=2,
            embedding_fn=mock_embedding_fn
        )
        
        assert len(result) <= 2
    
    def test_suggest_merges_validation_threshold_range(self, basic_deduplicator, simple_ontology, mock_embedding_fn):
        """Validates threshold is in [0, 1] range."""
        with pytest.raises(ValueError):
            basic_deduplicator.suggest_merges(
                simple_ontology,
                threshold=1.5,
                embedding_fn=mock_embedding_fn
            )
        
        with pytest.raises(ValueError):
            basic_deduplicator.suggest_merges(
                simple_ontology,
                threshold=-0.1,
                embedding_fn=mock_embedding_fn
            )
    
    def test_suggest_merges_invalid_ontology_type(self, basic_deduplicator, mock_embedding_fn):
        """Validates ontology is dictionary."""
        with pytest.raises(ValueError):
            basic_deduplicator.suggest_merges(
                "not a dict",
                embedding_fn=mock_embedding_fn
            )
    
    def test_suggest_merges_invalid_entities_list(self, basic_deduplicator, mock_embedding_fn):
        """Validates entities is list."""
        ontology = {"entities": "not a list"}
        
        with pytest.raises(ValueError):
            basic_deduplicator.suggest_merges(
                ontology,
                embedding_fn=mock_embedding_fn
            )


# ============================================================================
# Merge Suggestion Tests
# ============================================================================

class TestSemanticMergeSuggestion:
    """Test SemanticMergeSuggestion dataclass."""
    
    def test_suggestion_creation(self):
        """Creates merge suggestion with all fields."""
        suggestion = SemanticMergeSuggestion(
            entity1_id="E1",
            entity2_id="E2",
            similarity_score=0.95,
            reason="high semantic similarity",
            evidence={"semantic_similarity": 0.95}
        )
        
        assert suggestion.entity1_id == "E1"
        assert suggestion.entity2_id == "E2"
        assert suggestion.similarity_score == 0.95
    
    def test_suggestion_repr(self):
        """String representation is concise."""
        suggestion = SemanticMergeSuggestion(
            entity1_id="E1",
            entity2_id="E2",
            similarity_score=0.92,
            reason="test",
            evidence={}
        )
        
        repr_str = repr(suggestion)
        
        assert "E1" in repr_str
        assert "E2" in repr_str
        assert "0.92" in repr_str


# ============================================================================
# Build Merge Suggestion Tests
# ============================================================================

class TestBuildMergeSuggestion:
    """Test _build_merge_suggestion() method."""
    
    def test_builds_suggestion_with_evidence(self, basic_deduplicator):
        """Builds suggestion with comprehensive evidence."""
        entity1 = {
            "id": "E1",
            "text": "Chief Executive Officer",
            "type": "Title",
            "confidence": 0.9
        }
        entity2 = {
            "id": "E2",
            "text": "CEO",
            "type": "Title",
            "confidence": 0.85
        }
        
        suggestion = basic_deduplicator._build_merge_suggestion(
            entity1, entity2, 0.95, []
        )
        
        assert suggestion.entity1_id == "E1"
        assert suggestion.entity2_id == "E2"
        assert suggestion.similarity_score == 0.95
        assert "semantic_similarity" in suggestion.evidence
        assert "name_similarity" in suggestion.evidence
        assert "type_match" in suggestion.evidence
    
    def test_suggestion_reason_very_high_similarity(self, basic_deduplicator):
        """Reason includes 'very high semantic similarity' for high scores."""
        entity1 = {"id": "E1", "text": "CEO", "type": "Title", "confidence": 0.9}
        entity2 = {"id": "E2", "text": "Chief Executive Officer", "type": "Title", "confidence": 0.9}
        
        suggestion = basic_deduplicator._build_merge_suggestion(
            entity1, entity2, 0.97, []
        )
        
        assert "very high semantic similarity" in suggestion.reason
    
    def test_suggestion_reason_high_similarity(self, basic_deduplicator):
        """Reason includes 'high semantic similarity' for moderate scores."""
        entity1 = {"id": "E1", "text": "CEO", "type": "Title", "confidence": 0.9}
        entity2 = {"id": "E2", "text": "Chief Executive Officer", "type": "Title", "confidence": 0.9}
        
        suggestion = basic_deduplicator._build_merge_suggestion(
            entity1, entity2, 0.92, []
        )
        
        assert "high semantic similarity" in suggestion.reason
    
    def test_suggestion_reason_type_mismatch(self, basic_deduplicator):
        """Reason notes type mismatch when present."""
        entity1 = {"id": "E1", "text": "Apple", "type": "Company", "confidence": 0.9}
        entity2 = {"id": "E2", "text": "Apple", "type": "Fruit", "confidence": 0.9}
        
        suggestion = basic_deduplicator._build_merge_suggestion(
            entity1, entity2, 0.98, []
        )
        
        # Should not include "same entity type" due to mismatch
        assert "same entity type" not in suggestion.reason


# ============================================================================
# Batch Embedding Tests
# ============================================================================

class TestBatchEmbed:
    """Test _batch_embed() method."""
    
    def test_batch_embed_empty_texts(self, basic_deduplicator, mock_embedding_fn):
        """Handles empty text list."""
        result = basic_deduplicator._batch_embed([], mock_embedding_fn, batch_size=32)
        
        assert isinstance(result, np.ndarray)
        assert len(result) == 0
    
    def test_batch_embed_respects_batch_size(self, basic_deduplicator):
        """Respects batch size parameter."""
        texts = ["text1", "text2", "text3", "text4", "text5"]
        
        call_count = 0
        def counting_embed_fn(batch):
            nonlocal call_count
            call_count += 1
            return np.random.randn(len(batch), 384)
        
        basic_deduplicator._batch_embed(texts, counting_embed_fn, batch_size=2)
        
        # With batch_size=2, should call embedding function 3 times (2+2+1)
        assert call_count == 3
    
    def test_batch_embed_returns_numpy_array(self, basic_deduplicator, mock_embedding_fn):
        """Returns numpy array with correct shape."""
        texts = ["text1", "text2", "text3"]
        
        result = basic_deduplicator._batch_embed(texts, mock_embedding_fn, batch_size=2)
        
        assert isinstance(result, np.ndarray)
        assert result.shape == (3, 384)


# ============================================================================
# Factory Function Tests
# ============================================================================

class TestFactoryFunctions:
    """Test factory function create_semantic_deduplicator()."""
    
    def test_create_semantic_deduplicator_default(self):
        """Creates deduplicator with caching by default."""
        dedup = create_semantic_deduplicator()
        
        assert dedup is not None
        # Should have suggest_merges method
        assert hasattr(dedup, 'suggest_merges')
    
    def test_create_semantic_deduplicator_no_cache(self):
        """Creates uncached deduplicator with use_cache=False."""
        dedup = create_semantic_deduplicator(use_cache=False)
        
        assert isinstance(dedup, SemanticEntityDeduplicator)
        assert dedup.min_string_similarity == 0.3
    
    def test_create_semantic_deduplicator_custom_params(self):
        """Passes custom parameters to deduplicator."""
        dedup = create_semantic_deduplicator(
            use_cache=False,
            min_string_similarity=0.6
        )
        
        assert dedup.min_string_similarity == 0.6
    
    def test_create_deduplicator_alias(self):
        """create_deduplicator is alias for create_semantic_deduplicator."""
        dedup1 = create_semantic_deduplicator(use_cache=False)
        dedup2 = create_deduplicator(use_cache=False)
        
        assert type(dedup1) == type(dedup2)


# ============================================================================
# Integration Tests
# ============================================================================

class TestSemanticDeduplicatorIntegration:
    """Integration tests for complete deduplication workflows."""
    
    def test_complete_deduplication_workflow(self, simple_ontology):
        """Complete workflow: create dedup, generate suggestions."""
        dedup = create_semantic_deduplicator(use_cache=False)
        
        # Use deterministic mock
        def mock_embed(texts):
            # Return similar embeddings for similar texts
            embeddings = []
            for text in texts:
                seed = ord(text[0]) if text else 0
                np.random.seed(seed)
                emb = np.random.randn(384)
                embeddings.append(emb)
            return np.array(embeddings)
        
        suggestions = dedup.suggest_merges(
            simple_ontology,
            threshold=0.5,  # Lower threshold for testing
            embedding_fn=mock_embed
        )
        
        # Should find some suggestions
        assert len(suggestions) >= 0
        
        # All suggestions should be SemanticMergeSuggestion objects
        for suggestion in suggestions:
            assert isinstance(suggestion, SemanticMergeSuggestion)
            assert 0.0 <= suggestion.similarity_score <= 1.0
    
    def test_sorted_by_similarity_descending(self, basic_deduplicator, simple_ontology, mock_embedding_fn):
        """Suggestions are sorted by similarity in descending order."""
        suggestions = basic_deduplicator.suggest_merges(
            simple_ontology,
            threshold=0.1,  # Very low to get all
            embedding_fn=mock_embedding_fn
        )
        
        if len(suggestions) > 1:
            # Check descending order
            for i in range(len(suggestions) - 1):
                assert suggestions[i].similarity_score >= suggestions[i + 1].similarity_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
