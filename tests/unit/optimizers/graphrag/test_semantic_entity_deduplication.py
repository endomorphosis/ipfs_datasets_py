"""Tests for semantic entity deduplication using embeddings.

This test suite covers the SemanticEntityDeduplicator class which uses
embedding-based similarity to find semantically duplicate entities.
"""

import pytest
import numpy as np
from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator import (
    SemanticEntityDeduplicator,
    SemanticMergeSuggestion,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_validator import OntologyValidator


@pytest.fixture
def deduplicator():
    """Create SemanticEntityDeduplicator instance for testing."""
    return SemanticEntityDeduplicator()


@pytest.fixture
def validator():
    """Create OntologyValidator instance for testing."""
    return OntologyValidator()


@pytest.fixture
def simple_ontology():
    """Create simple ontology for testing."""
    return {
        "entities": [
            {"id": "e1", "text": "attorney", "type": "Profession", "confidence": 0.9},
            {"id": "e2", "text": "lawyer", "type": "Profession", "confidence": 0.85},
            {"id": "e3", "text": "doctor", "type": "Profession", "confidence": 0.9},
        ],
        "relationships": []
    }


@pytest.fixture
def mock_embedding_fn():
    """Create mock embedding function for testing."""
    # Pre-computed embeddings for testing (attorney ~ lawyer, both different from doctor)
    embeddings_map = {
        "attorney": np.array([0.9, 0.2, 0.1]),
        "lawyer": np.array([0.85, 0.25, 0.15]),
        "doctor": np.array([0.1, 0.9, 0.2]),
        "CEO": np.array([0.8, 0.3, 0.2]),
        "Chief Executive Officer": np.array([0.82, 0.28, 0.18]),
        "NYC": np.array([0.2, 0.8, 0.3]),
        "New York City": np.array([0.22, 0.78, 0.32]),
    }
    
    def embed_fn(texts):
        embeddings = []
        for text in texts:
            if text in embeddings_map:
                embeddings.append(embeddings_map[text])
            else:
                # Random embedding for unknown texts
                np.random.seed(hash(text) % 2**32)
                embeddings.append(np.random.randn(3))
        return np.array(embeddings)
    
    return embed_fn


class TestSemanticDeduplicationBasics:
    """Basic functionality tests for semantic deduplication."""
    
    def test_returns_merge_suggestions(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Ontology with semantically similar entities
        WHEN: suggest_entity_merges_semantic called
        THEN: Returns list of SemanticMergeSuggestion objects
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert isinstance(suggestions, list)
        assert all(isinstance(s, SemanticMergeSuggestion) for s in suggestions)
    
    def test_finds_semantic_duplicates(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Entities 'attorney' and 'lawyer' (semantically similar)
        WHEN: suggest_entity_merges_semantic called
        THEN: Suggests merging attorney and lawyer
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        # Should suggest attorney <-> lawyer (semantically similar)
        assert len(suggestions) > 0
        suggestion = suggestions[0]
        assert {suggestion.entity1_id, suggestion.entity2_id} == {"e1", "e2"}
    
    def test_does_not_suggest_dissimilar_entities(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Entities 'attorney' and 'doctor' (semantically different)
        WHEN: suggest_entity_merges_semantic called with high threshold
        THEN: Does not suggest merging attorney and doctor
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.95, embedding_fn=mock_embedding_fn
        )
        
        # attorney and doctor should not be suggested (semantically different)
        for s in suggestions:
            assert not ({s.entity1_id, s.entity2_id} == {"e1", "e3"})
    
    def test_similarity_score_in_valid_range(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Ontology with entities
        WHEN: suggest_entity_merges_semantic called
        THEN: All similarity scores in [0, 1]
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.7, embedding_fn=mock_embedding_fn
        )
        
        for s in suggestions:
            assert 0.0 <= s.similarity_score <= 1.0
    
    def test_sorted_by_similarity_descending(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Multiple merge suggestions
        WHEN: suggest_entity_merges_semantic called
        THEN: Results sorted by similarity_score (descending)
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.5, embedding_fn=mock_embedding_fn
        )
        
        if len(suggestions) > 1:
            scores = [s.similarity_score for s in suggestions]
            assert scores == sorted(scores, reverse=True)


class TestSemanticDeduplicationThreshold:
    """Test threshold filtering behavior."""
    
    def test_threshold_filters_results(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Ontology with entities
        WHEN: Different thresholds used
        THEN: Higher thresholds produce fewer suggestions
        """
        low_threshold_results = deduplicator.suggest_merges(
            simple_ontology, threshold=0.5, embedding_fn=mock_embedding_fn
        )
        high_threshold_results = deduplicator.suggest_merges(
            simple_ontology, threshold=0.95, embedding_fn=mock_embedding_fn
        )
        
        assert len(low_threshold_results) >= len(high_threshold_results)
    
    def test_threshold_validation(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Invalid threshold (<0 or >1)
        WHEN: suggest_entity_merges_semantic called
        THEN: Raises ValueError
        """
        with pytest.raises(ValueError):
            deduplicator.suggest_merges(
                simple_ontology, threshold=1.5, embedding_fn=mock_embedding_fn
            )
        
        with pytest.raises(ValueError):
            deduplicator.suggest_merges(
                simple_ontology, threshold=-0.1, embedding_fn=mock_embedding_fn
            )


class TestSemanticDeduplicationMaxSuggestions:
    """Test max_suggestions parameter behavior."""
    
    def test_max_suggestions_limits_results(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Multiple potential merge suggestions
        WHEN: max_suggestions=2 specified
        THEN: Returns at most 2 suggestions
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.5, max_suggestions=2, embedding_fn=mock_embedding_fn
        )
        
        assert len(suggestions) <= 2
    
    def test_max_suggestions_zero_returns_empty(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: max_suggestions=0
        WHEN: suggest_entity_merges_semantic called
        THEN: Returns empty list
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.5, max_suggestions=0, embedding_fn=mock_embedding_fn
        )
        
        assert suggestions == []
    
    def test_max_suggestions_none_returns_all(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: max_suggestions=None (default)
        WHEN: suggest_entity_merges_semantic called
        THEN: Returns all suggestions above threshold
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.5, max_suggestions=None, embedding_fn=mock_embedding_fn
        )
        
        # Should return all pairs above threshold
        assert len(suggestions) > 0


class TestSemanticDeduplicationEvidence:
    """Test evidence dict contents in suggestions."""
    
    def test_evidence_contains_semantic_similarity(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Merge suggestion
        WHEN: Evidence inspected
        THEN: Contains semantic_similarity field
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert len(suggestions) > 0
        evidence = suggestions[0].evidence
        assert "semantic_similarity" in evidence
        assert 0.0 <= evidence["semantic_similarity"] <= 1.0
    
    def test_evidence_contains_method_tag(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Semantic merge suggestion
        WHEN: Evidence inspected
        THEN: Contains method='embedding-based' tag
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert len(suggestions) > 0
        evidence = suggestions[0].evidence
        assert evidence["method"] == "embedding-based"
    
    def test_evidence_contains_type_info(self, deduplicator, simple_ontology, mock_embedding_fn):
        """GIVEN: Merge suggestion
        WHEN: Evidence inspected
        THEN: Contains type1, type2, type_match fields
        """
        suggestions = deduplicator.suggest_merges(
            simple_ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert len(suggestions) > 0
        evidence = suggestions[0].evidence
        assert "type1" in evidence
        assert "type2" in evidence
        assert "type_match" in evidence


class TestSemanticDeduplicationRealExamples:
    """Real-world semantic deduplication examples."""
    
    def test_abbreviation_expansion(self, deduplicator, mock_embedding_fn):
        """GIVEN: CEO and Chief Executive Officer (abbreviation expansion)
        WHEN: suggest_entity_merges_semantic called
        THEN: Suggests merging CEO and Chief Executive Officer
        """
        ontology = {
            "entities": [
                {"id": "e1", "text": "CEO", "type": "Position", "confidence": 0.9},
                {"id": "e2", "text": "Chief Executive Officer", "type": "Position", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.85, embedding_fn=mock_embedding_fn
        )
        
        assert len(suggestions) > 0
        assert {suggestions[0].entity1_id, suggestions[0].entity2_id} == {"e1", "e2"}
    
    def test_location_variants(self, deduplicator, mock_embedding_fn):
        """GIVEN: NYC and New York City (location variants)
        WHEN: suggest_entity_merges_semantic called
        THEN: Suggests merging NYC and New York City
        """
        ontology = {
            "entities": [
                {"id": "e1", "text": "NYC", "type": "Location", "confidence": 0.9},
                {"id": "e2", "text": "New York City", "type": "Location", "confidence": 0.88},
            ],
            "relationships": []
        }
        
        suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.85, embedding_fn=mock_embedding_fn
        )
        
        assert len(suggestions) > 0
        assert {suggestions[0].entity1_id, suggestions[0].entity2_id} == {"e1", "e2"}


class TestSemanticDeduplicationEdgeCases:
    """Edge case tests."""
    
    def test_empty_entities_list(self, deduplicator, mock_embedding_fn):
        """GIVEN: Ontology with empty entities list
        WHEN: suggest_entity_merges_semantic called
        THEN: Returns empty list
        """
        ontology = {"entities": [], "relationships": []}
        
        suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert suggestions == []
    
    def test_single_entity(self, deduplicator, mock_embedding_fn):
        """GIVEN: Ontology with single entity
        WHEN: suggest_entity_merges_semantic called
        THEN: Returns empty list (no pairs to compare)
        """
        ontology = {
            "entities": [{"id": "e1", "text": "attorney", "type": "Profession", "confidence": 0.9}],
            "relationships": []
        }
        
        suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert suggestions == []
    
    def test_entities_without_text(self, deduplicator, mock_embedding_fn):
        """GIVEN: Entities missing text field
        WHEN: suggest_entity_merges_semantic called
        THEN: Skips entities without text
        """
        ontology = {
            "entities": [
                {"id": "e1", "text": "attorney", "type": "Profession", "confidence": 0.9},
                {"id": "e2", "type": "Profession", "confidence": 0.85},  # Missing text
                {"id": "e3", "text": "lawyer", "type": "Profession", "confidence": 0.88},
            ],
            "relationships": []
        }
        
        # Should not fail, just skip entities without text
        suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert isinstance(suggestions, list)
    
    def test_entities_without_id(self, deduplicator, mock_embedding_fn):
        """GIVEN: Entities missing id field
        WHEN: suggest_entity_merges_semantic called
        THEN: Skips entities without ID
        """
        ontology = {
            "entities": [
                {"id": "e1", "text": "attorney", "type": "Profession", "confidence": 0.9},
                {"text": "doctor", "type": "Profession", "confidence": 0.85},  # Missing id
            ],
            "relationships": []
        }
        
        # Should not fail, just skip entities without ID
        suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        assert isinstance(suggestions, list)


class TestSemanticDeduplicationErrorHandling:
    """Error handling tests."""
    
    def test_invalid_ontology_type(self, deduplicator, mock_embedding_fn):
        """GIVEN: Non-dict ontology
        WHEN: suggest_entity_merges_semantic called
        THEN: Raises ValueError
        """
        with pytest.raises(ValueError):
            deduplicator.suggest_merges(
                "not a dict", threshold=0.8, embedding_fn=mock_embedding_fn
            )
    
    def test_entities_not_list(self, deduplicator, mock_embedding_fn):
        """GIVEN: Ontology where entities is not a list
        WHEN: suggest_entity_merges_semantic called
        THEN: Raises ValueError
        """
        ontology = {"entities": "not a list", "relationships": []}
        
        with pytest.raises(ValueError):
            deduplicator.suggest_merges(
                ontology, threshold=0.8, embedding_fn=mock_embedding_fn
            )

    def test_embedding_function_failure_is_wrapped(self, deduplicator, simple_ontology):
        """Embedding callback errors should be wrapped as RuntimeError."""
        def failing_embedding_fn(_texts):
            raise ValueError("vectorizer failed")

        with pytest.raises(RuntimeError, match="Embedding generation failed: vectorizer failed"):
            deduplicator.suggest_merges(
                simple_ontology,
                threshold=0.8,
                embedding_fn=failing_embedding_fn,
            )


class TestSemanticDeduplicationBatching:
    """Test batch processing for embeddings."""
    
    def test_batch_size_parameter(self, deduplicator, mock_embedding_fn):
        """GIVEN: Large ontology with many entities
        WHEN: Different batch_size values used
        THEN: Results are consistent regardless of batch size
        """
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"entity{i}", "type": "Type", "confidence": 0.9}
                for i in range(10)
            ],
            "relationships": []
        }
        
        results_batch_2 = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn, batch_size=2
        )
        results_batch_5 = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn, batch_size=5
        )
        
        # Results should be the same regardless of batch size
        assert len(results_batch_2) == len(results_batch_5)


class TestSemanticVsStringBasedComparison:
    """Compare semantic and string-based deduplication."""
    
    def test_semantic_finds_what_string_misses(self, deduplicator, validator, mock_embedding_fn):
        """GIVEN: Semantically similar but textually different entities
        WHEN: Both methods called
        THEN: Semantic method finds more duplicates
        """
        ontology = {
            "entities": [
                {"id": "e1", "text": "attorney", "type": "Profession", "confidence": 0.9},
                {"id": "e2", "text": "lawyer", "type": "Profession", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        # String-based won't find attorney <-> lawyer (low string similarity)
        string_suggestions = validator.suggest_entity_merges(
            ontology, threshold=0.8
        )
        
        # Semantic should find it
        semantic_suggestions = deduplicator.suggest_merges(
            ontology, threshold=0.8, embedding_fn=mock_embedding_fn
        )
        
        # Semantic should find more (or equal) suggestions
        assert len(semantic_suggestions) >= len(string_suggestions)
