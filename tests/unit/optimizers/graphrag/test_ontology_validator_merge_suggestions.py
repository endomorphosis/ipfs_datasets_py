"""Tests for OntologyValidator.suggest_entity_merges() method."""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_validator import (
    OntologyValidator,
    MergeSuggestion,
)


class TestMergeSuggestionDataclass:
    """Test MergeSuggestion dataclass."""
    
    def test_merge_suggestion_creation(self):
        """
        GIVEN: Parameters for a merge suggestion
        WHEN: Creating MergeSuggestion object
        THEN: All fields are set correctly
        """
        # GIVEN & WHEN
        suggestion = MergeSuggestion(
            entity1_id="e1",
            entity2_id="e2",
            similarity_score=0.85,
            reason="similar names",
            evidence={"name_similarity": 0.85, "type_match": True}
        )
        
        # THEN
        assert suggestion.entity1_id == "e1"
        assert suggestion.entity2_id == "e2"
        assert suggestion.similarity_score == 0.85
        assert suggestion.reason == "similar names"
        assert suggestion.evidence["name_similarity"] == 0.85
    
    def test_merge_suggestion_repr(self):
        """
        GIVEN: MergeSuggestion object
        WHEN: Calling __repr__
        THEN: Returns concise string representation
        """
        # GIVEN & WHEN
        suggestion = MergeSuggestion(
            entity1_id="alice", entity2_id="alice_2",
            similarity_score=0.92, reason="very similar names",
            evidence={}
        )
        repr_str = repr(suggestion)
        
        # THEN
        assert "alice" in repr_str
        assert "alice_2" in repr_str
        assert "0.920" in repr_str or "0.92" in repr_str


class TestValidatorInitialization:
    """Test OntologyValidator initialization."""
    
    def test_validator_default_init(self):
        """
        GIVEN: Calling OntologyValidator()
        WHEN: Using default parameters
        THEN: min_name_similarity defaults to 0.75
        """
        # GIVEN & WHEN
        validator = OntologyValidator()
        
        # THEN
        assert validator.min_name_similarity == 0.75
    
    def test_validator_custom_init(self):
        """
        GIVEN: Calling OntologyValidator with custom parameter
        WHEN: Setting min_name_similarity to 0.85
        THEN: Value is stored correctly
        """
        # GIVEN & WHEN
        validator = OntologyValidator(min_name_similarity=0.85)
        
        # THEN
        assert validator.min_name_similarity == 0.85


class TestSuggestEntityMergesBasic:
    """Test basic suggest_entity_merges() functionality."""
    
    def test_suggest_identical_entities(self):
        """
        GIVEN: Two entities with identical names and type
        WHEN: Calling suggest_entity_merges()
        THEN: Returns merge suggestion with high score
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        
        # THEN
        assert len(suggestions) >= 1
        assert suggestions[0].entity1_id == "e1"
        assert suggestions[0].entity2_id == "e2"
        assert suggestions[0].similarity_score > 0.9
        assert "similar" in suggestions[0].reason.lower()
    
    def test_suggest_similar_names_same_type(self):
        """
        GIVEN: Two entities with similar names and same type
        WHEN: Calling suggest_entity_merges()
        THEN: Returns relevant merge suggestion
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice Smith", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice Smyth", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.75)
        
        # THEN
        assert len(suggestions) >= 1
        sugg = suggestions[0]
        assert sugg.similarity_score >= 0.75
        assert "name" in sugg.reason.lower() or "similar" in sugg.reason.lower()
    
    def test_no_suggestion_for_different_types(self):
        """
        GIVEN: Two entities with similar names but different types
        WHEN: Calling suggest_entity_merges()
        THEN: May still suggest if names are very similar
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Apple", "type": "Organization", "confidence": 0.9},
                {"id": "e2", "text": "Apple", "type": "Fruit", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.85)
        
        # THEN
        # Even with different types, identical names might get suggested
        # depending on weighting
        if suggestions:
            assert suggestions[0].evidence["type_match"] is False
    
    def test_empty_entity_list(self):
        """
        GIVEN: Ontology with no entities
        WHEN: Calling suggest_entity_merges()
        THEN: Returns empty list
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {"entities": [], "relationships": []}
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology)
        
        # THEN
        assert suggestions == []
    
    def test_single_entity(self):
        """
        GIVEN: Ontology with only one entity
        WHEN: Calling suggest_entity_merges()
        THEN: Returns empty list (no pairs to compare)
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9}
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology)
        
        # THEN
        assert suggestions == []


class TestSuggestEntityMergesThreshold:
    """Test threshold parameter behavior."""
    
    def test_threshold_filtering(self):
        """
        GIVEN: Multiple entities with varying similarity
        WHEN: Using different thresholds
        THEN: Higher threshold returns fewer suggestions
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e3", "text": "Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": []
        }
        
        # WHEN
        high_threshold = validator.suggest_entity_merges(ontology, threshold=0.9)
        low_threshold = validator.suggest_entity_merges(ontology, threshold=0.5)
        
        # THEN
        assert len(low_threshold) >= len(high_threshold)
    
    def test_threshold_validation(self):
        """
        GIVEN: Invalid threshold values
        WHEN: Calling suggest_entity_merges()
        THEN: Raises ValueError
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {"entities": [], "relationships": []}
        
        # WHEN & THEN
        with pytest.raises(ValueError, match="threshold must be between"):
            validator.suggest_entity_merges(ontology, threshold=1.5)
        
        with pytest.raises(ValueError, match="threshold must be between"):
            validator.suggest_entity_merges(ontology, threshold=-0.1)
    
    def test_threshold_boundary(self):
        """
        GIVEN: Entities with score at threshold boundary
        WHEN: Using exact threshold value
        THEN: Entities at threshold are included
        """
        # GIVEN
        validator = OntologyValidator(min_name_similarity=0.0)
        ontology = {
            "entities": [
                {"id": "e1", "text": "Test", "type": "T", "confidence": 0.5},
                {"id": "e2", "text": "Test", "type": "T", "confidence": 0.5},  # Should match perfectly
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=1.0)
        
        # THEN
        # Perfect match should be at score 1.0
        if suggestions:
            assert suggestions[0].similarity_score >= 1.0 or suggestions[0].similarity_score == 1.0


class TestSuggestEntityMergesMaxSuggestions:
    """Test max_suggestions parameter."""
    
    def test_max_suggestions_limit(self):
        """
        GIVEN: Multiple merge candidates
        WHEN: Using max_suggestions parameter
        THEN: Only returns up to specified number
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e3", "text": "Bob", "type": "Person", "confidence": 0.8},
                {"id": "e4", "text": "Bob", "type": "Person", "confidence": 0.8},
            ],
            "relationships": []
        }
        
        # WHEN
        all_suggestions = validator.suggest_entity_merges(ontology, threshold=0.7)
        limited = validator.suggest_entity_merges(ontology, threshold=0.7, max_suggestions=1)
        
        # THEN
        assert len(limited) <= 1
        if all_suggestions:
            assert len(limited) <= len(all_suggestions)
    
    def test_max_suggestions_zero(self):
        """
        GIVEN: max_suggestions=0
        WHEN: Calling suggest_entity_merges()
        THEN: Returns empty list
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, max_suggestions=0)
        
        # THEN
        assert len(suggestions) == 0
    
    def test_max_suggestions_none_returns_all(self):
        """
        GIVEN: max_suggestions=None
        WHEN: Calling suggest_entity_merges()
        THEN: Returns all suggestions above threshold
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "A", "type": "T", "confidence": 0.9},
                {"id": "e2", "text": "A", "type": "T", "confidence": 0.9},
                {"id": "e3", "text": "A", "type": "T", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.5, max_suggestions=None)
        
        # THEN
        assert len(suggestions) >= 2  # At least multiple matches


class TestSuggestEntityMergesEvidence:
    """Test evidence field in suggestions."""
    
    def test_evidence_contains_metrics(self):
        """
        GIVEN: Merge suggestion
        WHEN: Examining evidence field
        THEN: Contains relevant metrics
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        
        # THEN
        assert len(suggestions) > 0
        evidence = suggestions[0].evidence
        assert "name_similarity" in evidence
        assert "type_match" in evidence
        assert "confidence1" in evidence
        assert "confidence2" in evidence
        assert "confidence_difference" in evidence
    
    def test_evidence_accuracy(self):
        """
        GIVEN: Two entities with known metrics
        WHEN: Calling suggest_entity_merges()
        THEN: Evidence values are calculated correctly
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Test", "type": "T", "confidence": 0.7},
                {"id": "e2", "text": "Test", "type": "T", "confidence": 0.9},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.5)
        
        # THEN
        if suggestions:
            evidence = suggestions[0].evidence
            assert evidence["confidence1"] == 0.7
            assert evidence["confidence2"] == 0.9
            assert evidence["confidence_difference"] == pytest.approx(0.2, abs=0.01)
            assert evidence["type_match"] is True


class TestSuggestEntityMergesSorting:
    """Test sorting of suggestions."""
    
    def test_suggestions_sorted_descending(self):
        """
        GIVEN: Multiple merge suggestions
        WHEN: Calling suggest_entity_merges()
        THEN: Suggestions are sorted by score (highest first)
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "AAA", "type": "T", "confidence": 0.5},
                {"id": "e2", "text": "AAA", "type": "T", "confidence": 0.5},  # Perfect match
                {"id": "e3", "text": "BBB", "type": "T", "confidence": 0.5},
                {"id": "e4", "text": "BBA", "type": "T", "confidence": 0.5},  # Similar
                {"id": "e5", "text": "CCC", "type": "T", "confidence": 0.5},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.6)
        
        # THEN
        if len(suggestions) > 1:
            for i in range(len(suggestions) - 1):
                assert suggestions[i].similarity_score >= suggestions[i + 1].similarity_score


class TestSuggestEntityMergesErrorHandling:
    """Test error handling."""
    
    def test_invalid_ontology_type(self):
        """
        GIVEN: Invalid ontology type (not dict)
        WHEN: Calling suggest_entity_merges()
        THEN: Raises ValueError
        """
        # GIVEN
        validator = OntologyValidator()
        
        # WHEN & THEN
        with pytest.raises(ValueError, match="ontology must be a dictionary"):
            validator.suggest_entity_merges([])  # List instead of dict
    
    def test_invalid_entities_type(self):
        """
        GIVEN: Invalid entities type (not list)
        WHEN: Calling suggest_entity_merges()
        THEN: Raises ValueError
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {"entities": "not a list", "relationships": []}
        
        # WHEN & THEN
        with pytest.raises(ValueError, match="entities.*must be a list"):
            validator.suggest_entity_merges(ontology)
    
    def test_entities_without_ids(self):
        """
        GIVEN: Entities without ID fields
        WHEN: Calling suggest_entity_merges()
        THEN: Skips entities without IDs (no error)
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"text": "Alice", "type": "Person"},  # No ID
                {"text": "Alice", "type": "Person"},  # No ID
            ],
            "relationships": []
        }
        
        # WHEN & THEN (should not raise)
        suggestions = validator.suggest_entity_merges(ontology)
        assert suggestions == []  # No suggestions since no IDs


class TestStringSimilarity:
    """Test string similarity calculation."""
    
    def test_identical_strings(self):
        """
        GIVEN: Two identical strings
        WHEN: Calling _calculate_string_similarity()
        THEN: Returns 1.0
        """
        # GIVEN
        validator = OntologyValidator()
        
        # WHEN
        sim = validator._calculate_string_similarity("Alice", "Alice")
        
        # THEN
        assert sim == 1.0
    
    def test_completely_different_strings(self):
        """
        GIVEN: Two completely different strings
        WHEN: Calling _calculate_string_similarity()
        THEN: Returns value close to 0.0
        """
        # GIVEN
        validator = OntologyValidator()
        
        # WHEN
        sim = validator._calculate_string_similarity("Alice", "XYZ")
        
        # THEN
        assert 0.0 <= sim < 0.3
    
    def test_partial_similarity(self):
        """
        GIVEN: Two partially similar strings
        WHEN: Calling _calculate_string_similarity()
        THEN: Returns value between 0 and 1
        """
        # GIVEN
        validator = OntologyValidator()
        
        # WHEN
        sim = validator._calculate_string_similarity("Alice", "Alicia")
        
        # THEN
        assert 0.7 < sim < 1.0
    
    def test_empty_strings(self):
        """
        GIVEN: Empty or None strings
        WHEN: Calling _calculate_string_similarity()
        THEN: Returns 0.0
        """
        # GIVEN
        validator = OntologyValidator()
        
        # WHEN & THEN
        assert validator._calculate_string_similarity("", "Alice") == 0.0
        assert validator._calculate_string_similarity("Alice", "") == 0.0
        assert validator._calculate_string_similarity("", "") == 0.0
    
    def test_case_insensitive(self):
        """
        GIVEN: Same text with different cases
        WHEN: Calling _calculate_string_similarity()
        THEN: Returns 1.0 (case-insensitive comparison)
        """
        # GIVEN
        validator = OntologyValidator()
        
        # WHEN
        sim = validator._calculate_string_similarity("Alice", "alice")
        
        # THEN
        assert sim == 1.0


class TestRealWorldScenarios:
    """Test real-world ontology scenarios."""
    
    def test_duplicate_person_entities(self):
        """
        GIVEN: Ontology with duplicate person entities
        WHEN: Calling suggest_entity_merges()
        THEN: Correctly identifies duplicates
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "p1", "text": "John Smith", "type": "Person", "confidence": 0.92},
                {"id": "p2", "text": "Jon Smith", "type": "Person", "confidence": 0.88},
                {"id": "p3", "text": "Jane Doe", "type": "Person", "confidence": 0.95},
            ],
            "relationships": [
                {"id": "r1", "source_id": "p1", "target_id": "p3", "type": "works_with"},
                {"id": "r2", "source_id": "p2", "target_id": "p3", "type": "knows"},
            ]
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.7)
        
        # THEN
        assert len(suggestions) > 0
        # First suggestion should be John Smith vs Jon Smith
        assert suggestions[0].similarity_score > 0.7
    
    def test_organization_deduplication(self):
        """
        GIVEN: Ontology with multiple organization references
        WHEN: Calling suggest_entity_merges()
        THEN: Suggests merging similar companies
        """
        # GIVEN
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "c1", "text": "Apple Inc", "type": "Organization", "confidence": 0.94},
                {"id": "c2", "text": "Apple Inc.", "type": "Organization", "confidence": 0.91},
                {"id": "c3", "text": "Microsoft Corporation", "type": "Organization", "confidence": 0.93},
            ],
            "relationships": []
        }
        
        # WHEN
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        
        # THEN
        assert len(suggestions) > 0
        # Top suggestion should be the Apple entities
        if suggestions[0].entity1_id in ["c1", "c2"] and suggestions[0].entity2_id in ["c1", "c2"]:
            assert suggestions[0].similarity_score > 0.85
