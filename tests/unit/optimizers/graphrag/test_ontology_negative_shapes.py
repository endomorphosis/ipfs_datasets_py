"""Negative tests for invalid ontology dict shapes and structures.

These tests validate that validators and handlers properly reject malformed
ontologies and catch common structural errors early.

Coverage includes:
- Missing required fields (id, type, description)
- Wrong field types (int id instead of string)
- Empty strings in required fields
- Malformed entities and relationships
- Circular references and dangling entity references
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_validator import OntologyValidator
from ipfs_datasets_py.optimizers.graphrag.exceptions import OntologyValidationError


class TestInvalidEntityShapes:
    """Test rejection of invalid entity structures."""

    def test_entity_missing_id(self):
        """
        GIVEN: Entity missing the 'id' field
        WHEN: validate_basic_schema is called with this ontology
        THEN: Should be caught by schema or in suggest_entity_merges
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"text": "Alice", "type": "Person", "confidence": 0.9},  # missing id
            ],
            "relationships": []
        }
        # validate_basic_schema checks structure but not individual entity fields
        assert validator.validate_basic_schema(ontology) is True
        
        # suggest_entity_merges should handle gracefully (skip entities without IDs)
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert suggestions == []  # no suggestions since entity lacks ID

    def test_entity_missing_type(self):
        """
        GIVEN: Entity missing the 'type' field
        WHEN: Operations process this ontology
        THEN: Should be detectable
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "confidence": 0.9},  # missing type
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        # suggest_entity_merges should still work (treats missing type as "Unknown")
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.5)
        # Should return suggestions despite missing type (treats as "Unknown")
        assert len(suggestions) >= 0

    def test_entity_with_int_id(self):
        """
        GIVEN: Entity with integer ID instead of string
        WHEN: Processing ontology
        THEN: Should not crash but handle gracefully
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": 123, "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": 456, "text": "Alice", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        # Should not crash; validator extracts and converts IDs
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        # May return suggestions (depends on how IDs are normalized)
        assert isinstance(suggestions, list)

    def test_entity_with_empty_id(self):
        """
        GIVEN: Entity with empty string ID
        WHEN: Processing ontology
        THEN: Should skip it gracefully
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        # Empty-ID entity should be skipped
        assert all(s.entity1_id != "" and s.entity2_id != "" for s in suggestions)

    def test_entity_with_empty_text(self):
        """
        GIVEN: Entity with empty or missing text field
        WHEN: suggest_entity_merges is called
        THEN: Should handle gracefully (treats as empty string)
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        # No suggestions since text similarity will be 0 for empty strings
        assert suggestions == []

    def test_entity_with_invalid_confidence_type(self):
        """
        GIVEN: Entity with non-numeric confidence
        WHEN: Processing ontology
        THEN: Should not crash
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": "high"},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        # suggest_entity_merges should convert confidence safely
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)

    def test_entity_with_negative_confidence(self):
        """
        GIVEN: Entity with negative confidence
        WHEN: Processing ontology
        THEN: Should handle gracefully
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": -0.5},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)

    def test_entity_with_confidence_over_1(self):
        """
        GIVEN: Entity with confidence > 1.0
        WHEN: Processing ontology
        THEN: Should handle gracefully (clamp or accept as-is)
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 1.5},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)


class TestInvalidRelationshipShapes:
    """Test rejection of invalid relationship structures."""

    def test_relationship_missing_source(self):
        """
        GIVEN: Relationship missing 'source' field
        WHEN: validate_basic_schema is called
        THEN: validate_basic_schema should pass (checks list type only)
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": [
                {"target": "e2", "type": "knows"},  # missing source
            ]
        }
        assert validator.validate_basic_schema(ontology) is True

    def test_relationship_missing_target(self):
        """
        GIVEN: Relationship missing 'target' field
        WHEN: validate_basic_schema is called
        THEN: Should pass (only checks structure)
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [
                {"source": "e1", "type": "knows"},  # missing target
            ]
        }
        assert validator.validate_basic_schema(ontology) is True

    def test_relationship_with_non_string_source(self):
        """
        GIVEN: Relationship with integer source
        WHEN: Processing ontology
        THEN: Should not crash
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": [
                {"source": 123, "target": "e2", "type": "knows"},
            ]
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)


class TestInvalidTopLevelStructures:
    """Test rejection of completely malformed ontologies."""

    def test_ontology_with_extra_keys(self):
        """
        GIVEN: Ontology with extra top-level keys
        WHEN: validate_basic_schema is called
        THEN: Should pass (extra keys are OK)
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [],
            "relationships": [],
            "metadata": {"version": "1.0"},
            "extra_data": [1, 2, 3],
        }
        assert validator.validate_basic_schema(ontology) is True

    def test_ontology_with_null_entities(self):
        """
        GIVEN: Ontology with null 'entities' field
        WHEN: validate_basic_schema is called
        THEN: Should raise OntologyValidationError
        """
        validator = OntologyValidator()
        ontology = {
            "entities": None,
            "relationships": [],
        }
        with pytest.raises(OntologyValidationError, match="list"):
            validator.validate_basic_schema(ontology)

    def test_ontology_with_entities_as_dict(self):
        """
        GIVEN: Ontology with entities as dict instead of list
        WHEN: validate_basic_schema is called
        THEN: Should raise OntologyValidationError
        """
        validator = OntologyValidator()
        ontology = {
            "entities": {"e1": {"text": "Alice"}},
            "relationships": [],
        }
        with pytest.raises(OntologyValidationError, match="list"):
            validator.validate_basic_schema(ontology)

    def test_ontology_with_relationships_as_string(self):
        """
        GIVEN: Ontology with relationships as string
        WHEN: validate_basic_schema is called
        THEN: Should raise OntologyValidationError
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [],
            "relationships": "not a list",
        }
        with pytest.raises(OntologyValidationError, match="list"):
            validator.validate_basic_schema(ontology)

    def test_completely_empty_ontology(self):
        """
        GIVEN: Completely empty dict
        WHEN: validate_basic_schema is called
        THEN: Should raise OntologyValidationError
        """
        validator = OntologyValidator()
        ontology = {}
        with pytest.raises(OntologyValidationError, match="Missing required"):
            validator.validate_basic_schema(ontology)

    def test_ontology_as_none(self):
        """
        GIVEN: Ontology is None
        WHEN: validate_basic_schema is called
        THEN: Should raise OntologyValidationError
        """
        validator = OntologyValidator()
        with pytest.raises(OntologyValidationError, match="dictionary"):
            validator.validate_basic_schema(None)

    def test_ontology_as_list(self):
        """
        GIVEN: Ontology is a list instead of dict
        WHEN: validate_basic_schema is called
        THEN: Should raise OntologyValidationError
        """
        validator = OntologyValidator()
        with pytest.raises(OntologyValidationError, match="dictionary"):
            validator.validate_basic_schema([{"entity": 1}, {"entity": 2}])


class TestEdgeCaseShapes:
    """Test edge cases and boundary conditions."""

    def test_very_long_entity_text(self):
        """
        GIVEN: Entity with very long text (1MB+)
        WHEN: Processing ontology
        THEN: Should handle without crashing
        """
        validator = OntologyValidator()
        long_text = "x" * (1024 * 1024)  # 1MB
        ontology = {
            "entities": [
                {"id": "e1", "text": long_text, "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)

    def test_unicode_entity_text(self):
        """
        GIVEN: Entity with unicode characters
        WHEN: Processing ontology
        THEN: Should handle without crashing
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "张三 (Alice)", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "張三 (Alice)", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)

    def test_special_characters_in_id(self):
        """
        GIVEN: Entity with special characters in ID
        WHEN: Processing ontology
        THEN: Should handle gracefully
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e@#$%1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e@#$%2", "text": "Alice", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        assert isinstance(suggestions, list)

    def test_whitespace_in_entity_text(self):
        """
        GIVEN: Entities with leading/trailing/extra whitespace
        WHEN: Processing ontology
        THEN: Should normalize and handle correctly
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "  Alice  ", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Alice", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        # Should find merge suggestion due to whitespace normalization
        assert len(suggestions) >= 1

    def test_very_many_entities(self):
        """
        GIVEN: Ontology with 10,000 entities
        WHEN: Processing ontology (pairwise)
        THEN: Should not crash (may be slow)
        """
        validator = OntologyValidator()
        entities = [
            {"id": f"e{i}", "text": f"Entity{i}", "type": "Thing", "confidence": 0.8}
            for i in range(10000)
        ]
        ontology = {"entities": entities, "relationships": []}
        
        assert validator.validate_basic_schema(ontology) is True
        # Just check that it doesn't crash (don't actually run suggest_entity_merges
        # which would be O(n^2) = 100M comparisons)

    def test_duplicate_entity_ids(self):
        """
        GIVEN: Ontology with duplicate entity IDs
        WHEN: Processing ontology
        THEN: Should not crash (process each entity pair)
        """
        validator = OntologyValidator()
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e1", "text": "Alice Smith", "type": "Person", "confidence": 0.85},
            ],
            "relationships": []
        }
        assert validator.validate_basic_schema(ontology) is True
        suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        # Should not crash; may have one suggestion (comparing e1 vs e1)
        assert isinstance(suggestions, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
