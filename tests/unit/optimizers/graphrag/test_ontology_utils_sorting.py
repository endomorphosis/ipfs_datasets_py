"""Tests for deterministic ontology sorting utilities.

These tests ensure that the sorting functions produce consistent, predictable
ordering regardless of input order, enabling snapshot testing and reproducibility.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_utils import (
    sort_entities,
    sort_relationships,
    sort_ontology,
    is_sorted_ontology,
)


class TestSortEntities:
    """Test sorting of entity lists."""

    def test_sort_single_entity(self):
        """
        GIVEN: Single entity in list
        WHEN: sort_entities is called
        THEN: Returns the same entity (nothing to sort)
        """
        entities = [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9}]
        sorted_ents = sort_entities(entities)
        
        assert len(sorted_ents) == 1
        assert sorted_ents[0]["id"] == "e1"

    def test_sort_multiple_entities_by_id(self):
        """
        GIVEN: Multiple entities with different IDs
        WHEN: sort_entities is called
        THEN: Returns entities sorted by ID (alphanumeric)
        """
        entities = [
            {"id": "e3", "type": "Person", "text": "Charlie", "confidence": 0.8},
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9},
            {"id": "e2", "type": "Person", "text": "Bob", "confidence": 0.85},
        ]
        sorted_ents = sort_entities(entities)
        
        assert [e["id"] for e in sorted_ents] == ["e1", "e2", "e3"]

    def test_sort_entities_same_id_different_type(self):
        """
        GIVEN: Entities with same ID but different types
        WHEN: sort_entities is called
        THEN: Returns sorted by type (secondary sort key)
        """
        entities = [
            {"id": "e1", "type": "Org", "text": "Company", "confidence": 0.9},
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9},
        ]
        sorted_ents = sort_entities(entities)
        
        # Org comes before Person alphabetically
        assert sorted_ents[0]["type"] == "Org"
        assert sorted_ents[1]["type"] == "Person"

    def test_sort_stability_same_id_same_type(self):
        """
        GIVEN: Entities with same ID and type but different text
        WHEN: sort_entities is called
        THEN: Sorted by text to ensure consistency
        """
        entities = [
            {"id": "e1", "type": "Person", "text": "Zoe", "confidence": 0.9},
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9},
        ]
        sorted_ents = sort_entities(entities)
        
        assert sorted_ents[0]["text"] == "Alice"
        assert sorted_ents[1]["text"] == "Zoe"

    def test_sort_by_confidence_tiebreak(self):
        """
        GIVEN: Entities with same ID, type, text but different confidence
        WHEN: sort_entities is called
        THEN: Higher confidence comes first (descending)
        """
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.7},
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9},
        ]
        sorted_ents = sort_entities(entities)
        
        # Higher confidence (0.9) should come first due to negative confidence in sort key
        assert sorted_ents[0]["confidence"] == 0.9
        assert sorted_ents[1]["confidence"] == 0.7

    def test_empty_entity_list(self):
        """
        GIVEN: Empty entity list
        WHEN: sort_entities is called
        THEN: Returns empty list
        """
        sorted_ents = sort_entities([])
        assert sorted_ents == []

    def test_missing_fields_handled(self):
        """
        GIVEN: Entities with missing fields
        WHEN: sort_entities is called
        THEN: Handles gracefully with defaults
        """
        entities = [
            {"id": "e2"},  # missing type, text, confidence
            {"id": "e1", "type": "Person"},  # missing text, confidence
        ]
        sorted_ents = sort_entities(entities)
        
        # Should not crash, e1 comes before e2 by ID
        assert len(sorted_ents) == 2
        assert sorted_ents[0]["id"] == "e1"

    def test_original_list_not_modified(self):
        """
        GIVEN: Original entity list
        WHEN: sort_entities is called
        THEN: Original list is not modified (returns new list)
        """
        original = [
            {"id": "e2", "type": "Person"},
            {"id": "e1", "type": "Person"},
        ]
        original_ids = [e["id"] for e in original]
        
        sorted_ents = sort_entities(original)
        
        # Original should be unchanged
        assert [e["id"] for e in original] == original_ids
        assert [e["id"] for e in sorted_ents] == ["e1", "e2"]


class TestSortRelationships:
    """Test sorting of relationship lists."""

    def test_sort_single_relationship(self):
        """
        GIVEN: Single relationship in list
        WHEN: sort_relationships is called
        THEN: Returns the same relationship
        """
        rels = [{"source": "e1", "target": "e2", "type": "knows", "confidence": 0.8}]
        sorted_rels = sort_relationships(rels)
        
        assert len(sorted_rels) == 1
        assert sorted_rels[0]["source"] == "e1"

    def test_sort_by_source_then_target(self):
        """
        GIVEN: Multiple relationships with different source/target
        WHEN: sort_relationships is called
        THEN: Sorted by source first, then target
        """
        rels = [
            {"source": "e2", "target": "e1", "type": "knows", "confidence": 0.8},
            {"source": "e1", "target": "e3", "type": "knows", "confidence": 0.8},
            {"source": "e1", "target": "e2", "type": "knows", "confidence": 0.8},
        ]
        sorted_rels = sort_relationships(rels)
        
        # Should sort by (source, target)
        assert sorted_rels[0]["source"] == "e1" and sorted_rels[0]["target"] == "e2"
        assert sorted_rels[1]["source"] == "e1" and sorted_rels[1]["target"] == "e3"
        assert sorted_rels[2]["source"] == "e2" and sorted_rels[2]["target"] == "e1"

    def test_sort_by_type_tiebreak(self):
        """
        GIVEN: Relationships with same source/target but different types
        WHEN: sort_relationships is called
        THEN: Sorted by type (tertiary sort key)
        """
        rels = [
            {"source": "e1", "target": "e2", "type": "works_for", "confidence": 0.8},
            {"source": "e1", "target": "e2", "type": "knows", "confidence": 0.8},
        ]
        sorted_rels = sort_relationships(rels)
        
        # "knows" < "works_for" alphabetically
        assert sorted_rels[0]["type"] == "knows"
        assert sorted_rels[1]["type"] == "works_for"

    def test_sort_by_confidence_descending(self):
        """
        GIVEN: Relationships with same source/target/type but different confidence
        WHEN: sort_relationships is called
        THEN: Higher confidence comes first (descending)
        """
        rels = [
            {"source": "e1", "target": "e2", "type": "knows", "confidence": 0.7},
            {"source": "e1", "target": "e2", "type": "knows", "confidence": 0.9},
        ]
        sorted_rels = sort_relationships(rels)
        
        assert sorted_rels[0]["confidence"] == 0.9
        assert sorted_rels[1]["confidence"] == 0.7

    def test_empty_relationship_list(self):
        """
        GIVEN: Empty relationship list
        WHEN: sort_relationships is called
        THEN: Returns empty list
        """
        sorted_rels = sort_relationships([])
        assert sorted_rels == []

    def test_original_relationships_not_modified(self):
        """
        GIVEN: Original relationship list
        WHEN: sort_relationships is called
        THEN: Original list is not modified
        """
        original = [
            {"source": "e2", "target": "e1", "type": "knows"},
            {"source": "e1", "target": "e2", "type": "knows"},
        ]
        original_sources = [r["source"] for r in original]
        
        sorted_rels = sort_relationships(original)
        
        # Original unchanged
        assert [r["source"] for r in original] == original_sources
        # Sorted has different order
        assert [r["source"] for r in sorted_rels] == ["e1", "e2"]


class TestSortOntology:
    """Test sorting of complete ontology dicts."""

    def test_sort_minimal_ontology(self):
        """
        GIVEN: Minimal valid ontology
        WHEN: sort_ontology is called
        THEN: Returns sorted ontology with same structure
        """
        ontology = {
            "entities": [{"id": "e2"}, {"id": "e1"}],
            "relationships": [],
        }
        sorted_onto = sort_ontology(ontology)
        
        assert sorted_onto["entities"][0]["id"] == "e1"
        assert sorted_onto["entities"][1]["id"] == "e2"

    def test_sort_complete_ontology(self):
        """
        GIVEN: Complete ontology with entities and relationships
        WHEN: sort_ontology is called
        THEN: Both entities and relationships are sorted
        """
        ontology = {
            "entities": [
                {"id": "e3", "type": "Person", "text": "Charlie"},
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
            ],
            "relationships": [
                {"source": "e3", "target": "e1", "type": "knows"},
                {"source": "e1", "target": "e2", "type": "knows"},
                {"source": "e2", "target": "e3", "type": "knows"},
            ],
            "metadata": {},
        }
        sorted_onto = sort_ontology(ontology)
        
        # Entities sorted by ID
        assert [e["id"] for e in sorted_onto["entities"]] == ["e1", "e2", "e3"]
        
        # Relationships sorted
        rels = sorted_onto["relationships"]
        assert rels[0]["source"] == "e1" and rels[0]["target"] == "e2"

    def test_sort_preserves_extra_fields(self):
        """
        GIVEN: Ontology with extra metadata fields
        WHEN: sort_ontology is called
        THEN: Extra fields are preserved
        """
        ontology = {
            "entities": [{"id": "e1"}],
            "relationships": [],
            "metadata": {"version": "1.0", "domain": "legal"},
            "custom_field": "custom_value",
        }
        sorted_onto = sort_ontology(ontology)
        
        assert sorted_onto["metadata"]["version"] == "1.0"
        assert sorted_onto["custom_field"] == "custom_value"

    def test_sort_ontology_invalid_structure(self):
        """
        GIVEN: Invalid ontology (not a dict)
        WHEN: sort_ontology is called
        THEN: Raises ValueError
        """
        with pytest.raises(ValueError, match="Expected dict"):
            sort_ontology([{"entities": []}])

    def test_sort_ontology_missing_keys(self):
        """
        GIVEN: Ontology missing required keys
        WHEN: sort_ontology is called
        THEN: Raises ValueError
        """
        with pytest.raises(ValueError, match="must have"):
            sort_ontology({"entities": []})  # missing relationships

    def test_sort_ontology_invalid_list_types(self):
        """
        GIVEN: Ontology with non-list entities
        WHEN: sort_ontology is called
        THEN: Raises ValueError
        """
        with pytest.raises(ValueError, match="list"):
            sort_ontology({"entities": "not a list", "relationships": []})

    def test_sort_idempotent(self):
        """
        GIVEN: Sorted ontology
        WHEN: sort_ontology is called again
        THEN: Result is unchanged (idempotent)
        """
        ontology = {
            "entities": [{"id": "e2"}, {"id": "e1"}],
            "relationships": [
                {"source": "e2", "target": "e1", "type": "knows"},
                {"source": "e1", "target": "e2", "type": "knows"},
            ],
        }
        
        sorted_once = sort_ontology(ontology)
        sorted_twice = sort_ontology(sorted_once)
        
        # Entity IDs should be identical
        e1_ids = [e["id"] for e in sorted_once["entities"]]
        e2_ids = [e["id"] for e in sorted_twice["entities"]]
        assert e1_ids == e2_ids

    def test_sort_deterministic_across_permutations(self):
        """
        GIVEN: Two ontologies with same content in different order
        WHEN: Both are sorted
        THEN: Result after sorting is identical
        """
        ontology1 = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
            ],
            "relationships": [],
        }
        
        ontology2 = {
            "entities": [
                {"id": "e2", "type": "Person"},
                {"id": "e1", "type": "Person"},
            ],
            "relationships": [],
        }
        
        sorted1 = sort_ontology(ontology1)
        sorted2 = sort_ontology(ontology2)
        
        # After sorting, entity IDs should be in same order
        ids1 = [e["id"] for e in sorted1["entities"]]
        ids2 = [e["id"] for e in sorted2["entities"]]
        assert ids1 == ids2


class TestIsSortedOntology:
    """Test detection of sorted ontologies."""

    def test_is_sorted_already_sorted(self):
        """
        GIVEN: Ontology already in sorted order
        WHEN: is_sorted_ontology is called
        THEN: Returns True
        """
        ontology = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [],
        }
        assert is_sorted_ontology(ontology) is True

    def test_is_not_sorted_unsorted(self):
        """
        GIVEN: Ontology not in sorted order
        WHEN: is_sorted_ontology is called
        THEN: Returns False
        """
        ontology = {
            "entities": [{"id": "e2"}, {"id": "e1"}],
            "relationships": [],
        }
        assert is_sorted_ontology(ontology) is False

    def test_is_sorted_invalid_ontology(self):
        """
        GIVEN: Invalid ontology structure
        WHEN: is_sorted_ontology is called
        THEN: Returns False (catches exceptions)
        """
        assert is_sorted_ontology({"entities": "not a list"}) is False
        assert is_sorted_ontology(None) is False
        assert is_sorted_ontology([]) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
