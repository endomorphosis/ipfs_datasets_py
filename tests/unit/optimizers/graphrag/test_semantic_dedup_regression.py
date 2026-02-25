"""Regression and performance tests for SemanticEntityDeduplicator.

This test suite validates:
1. Correctness - All valid merge pairs are found
2. Performance - No regression from baseline (1.4-3.5s @ 200 entities)
3. Robustness - Edge cases and error handling
4. Configuration sensitivity - Threshold and batch size effects
"""

import pytest
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Setup imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator import (
    SemanticEntityDeduplicator,
    SemanticMergeSuggestion,
)


class TestSemanticDedupCorrectness:
    """Test correctness of semantic deduplication."""
    
    def test_exact_duplicates_detected(self):
        """Verify exact duplicate entities are detected as mergeable."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Chief Executive Officer", "type": "Role", "confidence": 0.9},
                {"id": "e2", "text": "Chief Executive Officer", "type": "Role", "confidence": 0.9},
                {"id": "e3", "text": "Vice President", "type": "Role", "confidence": 0.8},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.95)
        
        # Should find at least one merge pair (e1 and e2)
        assert len(suggestions) > 0
        similarity_scores = [s.similarity_score for s in suggestions]
        assert any(score >= 0.99 for score in similarity_scores), \
            "Exact duplicates should have similarity >= 0.99"
    
    def test_abbreviation_variants_detected(self):
        """Verify abbreviation variants are detected (CEO vs Chief Executive Officer)."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "CEO", "type": "Role", "confidence": 0.9},
                {"id": "e2", "text": "Chief Executive Officer", "type": "Role", "confidence": 0.9},
                {"id": "e3", "text": "CTO", "type": "Role", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.70)
        
        # Should detect CEO/CTO are different (e1 vs e3), but CEO/CEO variant might match
        assert len(suggestions) > 0
        # At least one pair should be detected
        scores = [s.similarity_score for s in suggestions]
        assert max(scores) > 0.70, f"Expected scores > 0.70, got max {max(scores)}"
    
    def test_no_false_positives_with_high_threshold(self):
        """Verify high threshold (0.95+) filters out dissimilar entities."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "New York City", "type": "Location", "confidence": 0.9},
                {"id": "e2", "text": "Los Angeles", "type": "Location", "confidence": 0.9},
                {"id": "e3", "text": "Chicago", "type": "Location", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.95)
        
        # Different cities shouldn't merge at 0.95 threshold
        for sugg in suggestions:
            assert sugg.similarity_score >= 0.95, \
                f"Suggestion score {sugg.similarity_score} below threshold 0.95"
    
    def test_threshold_affects_suggestion_count(self):
        """Verify lower thresholds produce more suggestions than higher ones."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Attorney", "type": "Role", "confidence": 0.9},
                {"id": "e2", "text": "Lawyer", "type": "Role", "confidence": 0.9},
                {"id": "e3", "text": "Counsel", "type": "Role", "confidence": 0.9},
                {"id": "e4", "text": "Solicitor", "type": "Role", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions_strict = dedup.suggest_merges(ontology, threshold=0.95)
        suggestions_lenient = dedup.suggest_merges(ontology, threshold=0.70)
        
        # Lower threshold should find equal or more suggestions
        assert len(suggestions_lenient) >= len(suggestions_strict), \
            f"Lenient (0.70) found {len(suggestions_lenient)} vs strict (0.95) found {len(suggestions_strict)}"


class TestSemanticDedupRobustness:
    """Test edge cases and error handling."""
    
    def test_empty_entity_list(self):
        """Verify empty entity list is handled gracefully."""
        ontology = {"entities": [], "relationships": []}
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.85)
        
        assert suggestions == []
    
    def test_single_entity(self):
        """Verify single entity returns no suggestions."""
        ontology = {
            "entities": [{"id": "e1", "text": "CEO", "type": "Role", "confidence": 0.9}],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.85)
        
        assert suggestions == []
    
    def test_two_entities(self):
        """Verify minimum case of two entities works."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "New York City", "type": "Location", "confidence": 0.9},
                {"id": "e2", "text": "NYC", "type": "Location", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.50)
        
        # Should execute without error, result depends on embedding similarity
        assert isinstance(suggestions, list)
    
    def test_missing_entity_fields(self):
        """Verify entities with missing text are skipped gracefully."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "CEO", "type": "Role", "confidence": 0.9},
                {"id": "e2", "text": "", "type": "Role", "confidence": 0.9},  # Empty text
                {"id": "e3", "type": "Role", "confidence": 0.9},  # Missing text
                {"id": "e4", "text": "CTO", "type": "Role", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.85)
        
        # Should only process e1 and e4 (valid entities with text)
        if suggestions:
            for sugg in suggestions:
                assert sugg.entity1_id in ["e1", "e4"]
                assert sugg.entity2_id in ["e1", "e4"]
    
    def test_max_suggestions_limit(self):
        """Verify max_suggestions parameter limits results."""
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity{i}", "type": "Thing", "confidence": 0.9}
                for i in range(20)
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions_limited = dedup.suggest_merges(ontology, threshold=0.50, max_suggestions=5)
        suggestions_unlimited = dedup.suggest_merges(ontology, threshold=0.50, max_suggestions=None)
        
        assert len(suggestions_limited) <= 5
        assert len(suggestions_unlimited) >= len(suggestions_limited)
    
    def test_invalid_threshold_raises_error(self):
        """Verify invalid thresholds are rejected."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "CEO", "type": "Role", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        
        with pytest.raises(ValueError):
            dedup.suggest_merges(ontology, threshold=-0.1)
        
        with pytest.raises(ValueError):
            dedup.suggest_merges(ontology, threshold=1.5)


class TestSemanticDedupPerformance:
    """Test performance characteristics and regressions."""
    
    def test_100_entities_completes_in_reasonable_time(self):
        """Verify 100 entities complete in <2.5 seconds."""
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity_{i}_{chr(97 + (i % 26))}", 
                 "type": "Unknown", "confidence": 0.8}
                for i in range(100)
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        start = time.time()
        suggestions = dedup.suggest_merges(ontology, threshold=0.85)
        elapsed = time.time() - start
        
        # Based on profiling: 100 entities should take ~1.4s ± 0.3s
        assert elapsed < 2.5, f"100 entities took {elapsed:.2f}s (expected <2.5s)"
    
    def test_200_entities_completes_in_reasonable_time(self):
        """Verify 200 entities complete in <3.0 seconds."""
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity_{i}_{chr(97 + (i % 26))}", 
                 "type": "Unknown", "confidence": 0.8}
                for i in range(200)
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        start = time.time()
        suggestions = dedup.suggest_merges(ontology, threshold=0.85)
        elapsed = time.time() - start
        
        # Based on profiling: 200 entities should take ~1.5s ± 0.3s
        assert elapsed < 3.0, f"200 entities took {elapsed:.2f}s (expected <3.0s)"
    
    def test_batch_size_affects_performance(self):
        """Verify different batch sizes work correctly."""
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity_{i}", "type": "Unknown", "confidence": 0.8}
                for i in range(50)
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        
        # Test different batch sizes
        for batch_size in [16, 32, 64]:
            start = time.time()
            suggestions = dedup.suggest_merges(ontology, threshold=0.85, batch_size=batch_size)
            elapsed = time.time() - start
            
            # All should complete without error
            assert isinstance(suggestions, list)
            assert elapsed < 5.0, f"Batch size {batch_size} took {elapsed:.2f}s"


class TestSemanticDedupDataStructures:
    """Test data structure invariants and properties."""
    
    def test_merge_suggestion_fields(self):
        """Verify SemanticMergeSuggestion has required fields."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Entity 1", "type": "Thing", "confidence": 0.9},
                {"id": "e2", "text": "Entity 2", "type": "Thing", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.50)
        
        if suggestions:
            sugg = suggestions[0]
            # Check required fields exist
            assert hasattr(sugg, "entity1_id")
            assert hasattr(sugg, "entity2_id")
            assert hasattr(sugg, "similarity_score")
            assert hasattr(sugg, "reason")
            assert hasattr(sugg, "evidence")
            
            # Check field types
            assert isinstance(sugg.entity1_id, str)
            assert isinstance(sugg.entity2_id, str)
            assert isinstance(sugg.similarity_score, float)
            assert isinstance(sugg.reason, str)
            assert isinstance(sugg.evidence, dict)
            
            # Check value ranges
            assert 0.0 <= sugg.similarity_score <= 1.0
    
    def test_suggestions_sorted_by_similarity(self):
        """Verify suggestions are sorted by similarity (highest first)."""
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity_{i}", "type": "Thing", "confidence": 0.9}
                for i in range(10)
            ],
            "relationships": []
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.50)
        
        # Verify descending sort by similarity
        for i in range(len(suggestions) - 1):
            assert suggestions[i].similarity_score >= suggestions[i + 1].similarity_score, \
                "Suggestions should be sorted by similarity (descending)"


class TestSemanticDedupIntegration:
    """Integration tests combining multiple components."""
    
    def test_realistic_entity_set(self):
        """Test with realistic entity types and values."""
        ontology = {
            "entities": [
                {"id": "person_1", "text": "John Smith", "type": "Person", "confidence": 0.95},
                {"id": "person_2", "text": "J. Smith", "type": "Person", "confidence": 0.85},
                {"id": "org_1", "text": "Microsoft Corporation", "type": "Organization", "confidence": 0.98},
                {"id": "org_2", "text": "Microsoft", "type": "Organization", "confidence": 0.90},
                {"id": "loc_1", "text": "New York City", "type": "Location", "confidence": 0.96},
                {"id": "loc_2", "text": "NYC", "type": "Location", "confidence": 0.88},
            ],
            "relationships": [
                {"id": "r1", "source_id": "person_1", "target_id": "org_1", "type": "works_at"},
                {"id": "r2", "source_id": "org_1", "target_id": "loc_1", "type": "located_in"},
            ]
        }
        
        dedup = SemanticEntityDeduplicator()
        suggestions = dedup.suggest_merges(ontology, threshold=0.75)
        
        # Should complete without error and find some suggestions
        assert isinstance(suggestions, list)
        # Check that results are sensible (same-type or closely related)
        for sugg in suggestions:
            assert sugg.similarity_score >= 0.75
            assert 0 < len(sugg.reason) < 500, "Reason should be descriptive but reasonable length"


# Test marker for performance tests
pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
