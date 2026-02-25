"""
Batch 266: Comprehensive tests for OntologyUtils deterministic ordering.

Tests all sorting and validation functions in ontology_utils.py:
- sort_entities: Entity sorting by (id, type, text, confidence)
- sort_relationships: Relationship sorting by (source, target, type, id, confidence)
- sort_ontology: Complete ontology sorting (entities + relationships)
- is_sorted_ontology: Validation of deterministic ordering

Coverage: 40 tests across 11 test classes
"""

import pytest
from typing import Dict, List, Any

from ipfs_datasets_py.optimizers.graphrag.ontology_utils import (
    sort_entities,
    sort_relationships,
    sort_ontology,
    is_sorted_ontology,
)


class TestSortEntities:
    """Test sort_entities function with various entity structures."""
    
    def test_sort_entities_by_id_primary(self):
        """Test entities sorted primarily by ID."""
        entities = [
            {"id": "person_3", "type": "Person", "text": "John"},
            {"id": "person_1", "type": "Person", "text": "Alice"},
            {"id": "person_2", "type": "Person", "text": "Bob"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        assert len(sorted_ents) == 3
        assert sorted_ents[0]["id"] == "person_1"
        assert sorted_ents[1]["id"] == "person_2"
        assert sorted_ents[2]["id"] == "person_3"
    
    def test_sort_entities_by_type_secondary(self):
        """Test entities sorted by type when IDs are equal."""
        entities = [
            {"id": "entity_1", "type": "Organization", "text": "Acme"},
            {"id": "entity_1", "type": "Location", "text": "Springfield"},
            {"id": "entity_1", "type": "Person", "text": "John"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # All have same ID, so should be sorted by type
        assert sorted_ents[0]["type"] == "Location"  # alphabetically first
        assert sorted_ents[1]["type"] == "Organization"
        assert sorted_ents[2]["type"] == "Person"
    
    def test_sort_entities_by_text_tertiary(self):
        """Test entities sorted by text when ID and type are equal."""
        entities = [
            {"id": "person_1", "type": "Person", "text": "Zoe"},
            {"id": "person_1", "type": "Person", "text": "Alice"},
            {"id": "person_1", "type": "Person", "text": "Bob"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        assert sorted_ents[0]["text"] == "Alice"
        assert sorted_ents[1]["text"] == "Bob"
        assert sorted_ents[2]["text"] == "Zoe"
    
    def test_sort_entities_by_confidence_descending(self):
        """Test entities with identical id/type/text sorted by confidence descending."""
        entities = [
            {"id": "e1", "type": "Person", "text": "John", "confidence": 0.5},
            {"id": "e1", "type": "Person", "text": "John", "confidence": 0.95},
            {"id": "e1", "type": "Person", "text": "John", "confidence": 0.7},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Confidence should be descending (highest first)
        assert sorted_ents[0]["confidence"] == 0.95
        assert sorted_ents[1]["confidence"] == 0.7
        assert sorted_ents[2]["confidence"] == 0.5
    
    def test_sort_entities_case_insensitive_id(self):
        """Test entity sorting preserves ID case but sorts correctly."""
        entities = [
            {"id": "Person_Z", "type": "Person", "text": "Zoe"},
            {"id": "person_A", "type": "Person", "text": "Alice"},
            {"id": "PERSON_M", "type": "Person", "text": "Mary"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Should preserve case, sort lexicographically
        assert sorted_ents[0]["id"] == "PERSON_M"  # uppercase first in ASCII
        assert sorted_ents[1]["id"] == "Person_Z"
        assert sorted_ents[2]["id"] == "person_A"
    
    def test_sort_entities_with_capital_field_names(self):
        """Test entities with uppercase field names (Id, Type, Text, Confidence)."""
        entities = [
            {"Id": "entity_2", "Type": "Person", "Text": "Bob"},
            {"Id": "entity_1", "Type": "Person", "Text": "Alice"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        assert sorted_ents[0]["Id"] == "entity_1"
        assert sorted_ents[1]["Id"] == "entity_2"
    
    def test_sort_entities_empty_list(self):
        """Test sorting empty entity list."""
        sorted_ents = sort_entities([])
        
        assert sorted_ents == []
    
    def test_sort_entities_missing_fields(self):
        """Test entities with missing optional fields."""
        entities = [
            {"id": "e2", "type": "Person"},  # missing text, confidence
            {"id": "e1"},  # missing type, text, confidence
            {"id": "e3", "type": "Organization", "text": "Acme", "confidence": 0.9},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Should handle missing fields gracefully (defaults to "", "Unknown", 0.0)
        assert sorted_ents[0]["id"] == "e1"
        assert sorted_ents[1]["id"] == "e2"
        assert sorted_ents[2]["id"] == "e3"
    
    def test_sort_entities_preserves_original_list(self):
        """Test that original list is not modified."""
        original = [
            {"id": "e3", "type": "Person"},
            {"id": "e1", "type": "Person"},
        ]
        original_copy = original.copy()
        
        sorted_ents = sort_entities(original)
        
        # Original should be unchanged
        assert original == original_copy
        assert sorted_ents[0]["id"] == "e1"  # but result is sorted


class TestSortRelationships:
    """Test sort_relationships function with various relationship structures."""
    
    def test_sort_relationships_by_source_primary(self):
        """Test relationships sorted primarily by source entity."""
        relationships = [
            {"source": "person_3", "target": "org_1", "type": "works_at"},
            {"source": "person_1", "target": "org_1", "type": "works_at"},
            {"source": "person_2", "target": "org_2", "type": "owns"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        assert sorted_rels[0]["source"] == "person_1"
        assert sorted_rels[1]["source"] == "person_2"
        assert sorted_rels[2]["source"] == "person_3"
    
    def test_sort_relationships_by_target_secondary(self):
        """Test relationships sorted by target when sources are equal."""
        relationships = [
            {"source": "person_1", "target": "org_3", "type": "works_at"},
            {"source": "person_1", "target": "org_1", "type": "owns"},
            {"source": "person_1", "target": "org_2", "type": "manages"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        assert sorted_rels[0]["target"] == "org_1"
        assert sorted_rels[1]["target"] == "org_2"
        assert sorted_rels[2]["target"] == "org_3"
    
    def test_sort_relationships_by_type_tertiary(self):
        """Test relationships sorted by type when source and target are equal."""
        relationships = [
            {"source": "p1", "target": "o1", "type": "works_at"},
            {"source": "p1", "target": "o1", "type": "manages"},
            {"source": "p1", "target": "o1", "type": "owns"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        assert sorted_rels[0]["type"] == "manages"
        assert sorted_rels[1]["type"] == "owns"
        assert sorted_rels[2]["type"] == "works_at"
    
    def test_sort_relationships_by_id_quaternary(self):
        """Test relationships sorted by id when source/target/type are equal."""
        relationships = [
            {"source": "p1", "target": "o1", "type": "works_at", "id": "rel_3"},
            {"source": "p1", "target": "o1", "type": "works_at", "id": "rel_1"},
            {"source": "p1", "target": "o1", "type": "works_at", "id": "rel_2"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        assert sorted_rels[0]["id"] == "rel_1"
        assert sorted_rels[1]["id"] == "rel_2"
        assert sorted_rels[2]["id"] == "rel_3"
    
    def test_sort_relationships_by_confidence_descending(self):
        """Test relationships with identical source/target/type/id sorted by confidence descending."""
        relationships = [
            {"source": "p1", "target": "o1", "type": "works_at", "id": "rel_1", "confidence": 0.6},
            {"source": "p1", "target": "o1", "type": "works_at", "id": "rel_1", "confidence": 0.9},
            {"source": "p1", "target": "o1", "type": "works_at", "id": "rel_1", "confidence": 0.7},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        assert sorted_rels[0]["confidence"] == 0.9
        assert sorted_rels[1]["confidence"] == 0.7
        assert sorted_rels[2]["confidence"] == 0.6
    
    def test_sort_relationships_with_capital_field_names(self):
        """Test relationships with uppercase field names (Source, Target, Type, etc.)."""
        relationships = [
            {"Source": "p2", "Target": "o1", "Type": "works_at"},
            {"Source": "p1", "Target": "o1", "Type": "owns"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        assert sorted_rels[0]["Source"] == "p1"
        assert sorted_rels[1]["Source"] == "p2"
    
    def test_sort_relationships_empty_list(self):
        """Test sorting empty relationship list."""
        sorted_rels = sort_relationships([])
        
        assert sorted_rels == []
    
    def test_sort_relationships_missing_fields(self):
        """Test relationships with missing optional fields."""
        relationships = [
            {"source": "p2", "target": "o1"},  # missing type, confidence, id
            {"source": "p1"},  # missing target, type, confidence, id
            {"source": "p3", "target": "o2", "type": "owns", "confidence": 0.8, "id": "rel_1"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        # Should handle missing fields gracefully
        assert sorted_rels[0]["source"] == "p1"
        assert sorted_rels[1]["source"] == "p2"
        assert sorted_rels[2]["source"] == "p3"
    
    def test_sort_relationships_preserves_original_list(self):
        """Test that original list is not modified."""
        original = [
            {"source": "p3", "target": "o1", "type": "works_at"},
            {"source": "p1", "target": "o2", "type": "owns"},
        ]
        original_copy = original.copy()
        
        sorted_rels = sort_relationships(original)
        
        assert original == original_copy
        assert sorted_rels[0]["source"] == "p1"


class TestSortOntology:
    """Test sort_ontology function with complete ontology structures."""
    
    def test_sort_ontology_complete_structure(self):
        """Test sorting complete ontology with entities and relationships."""
        ontology = {
            "entities": [
                {"id": "e3", "type": "Person", "text": "Charlie"},
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Organization", "text": "Acme"},
            ],
            "relationships": [
                {"source": "e3", "target": "e2", "type": "works_at"},
                {"source": "e1", "target": "e2", "type": "owns"},
            ]
        }
        
        sorted_onto = sort_ontology(ontology)
        
        # Check entities are sorted by ID
        assert sorted_onto["entities"][0]["id"] == "e1"
        assert sorted_onto["entities"][1]["id"] == "e2"
        assert sorted_onto["entities"][2]["id"] == "e3"
        
        # Check relationships are sorted by source
        assert sorted_onto["relationships"][0]["source"] == "e1"
        assert sorted_onto["relationships"][1]["source"] == "e3"
    
    def test_sort_ontology_empty_lists(self):
        """Test sorting ontology with empty entities and relationships."""
        ontology = {
            "entities": [],
            "relationships": []
        }
        
        sorted_onto = sort_ontology(ontology)
        
        assert sorted_onto["entities"] == []
        assert sorted_onto["relationships"] == []
    
    def test_sort_ontology_preserves_additional_fields(self):
        """Test that additional fields in ontology dict are preserved."""
        ontology = {
            "entities": [{"id": "e2"}, {"id": "e1"}],
            "relationships": [],
            "metadata": {"version": "1.0", "domain": "legal"},
            "extra_field": "some_value"
        }
        
        sorted_onto = sort_ontology(ontology)
        
        # Additional fields should be preserved
        assert sorted_onto["metadata"]["version"] == "1.0"
        assert sorted_onto["extra_field"] == "some_value"
        
        # But entities should be sorted
        assert sorted_onto["entities"][0]["id"] == "e1"
    
    def test_sort_ontology_does_not_modify_original(self):
        """Test that original ontology dict is not modified."""
        original = {
            "entities": [{"id": "e2"}, {"id": "e1"}],
            "relationships": []
        }
        original_entity_order = [e["id"] for e in original["entities"]]
        
        sorted_onto = sort_ontology(original)
        
        # Original should be unchanged
        assert [e["id"] for e in original["entities"]] == original_entity_order
        
        # But result should be sorted
        assert sorted_onto["entities"][0]["id"] == "e1"
    
    def test_sort_ontology_with_complex_entities(self):
        """Test sorting ontology with entities containing many fields."""
        ontology = {
            "entities": [
                {
                    "id": "e2",
                    "type": "Person",
                    "text": "Bob",
                    "confidence": 0.9,
                    "metadata": {"age": 30},
                    "attributes": ["tall", "kind"]
                },
                {
                    "id": "e1",
                    "type": "Organization",
                    "text": "Acme",
                    "confidence": 0.95,
                    "location": "Springfield"
                },
            ],
            "relationships": []
        }
        
        sorted_onto = sort_ontology(ontology)
        
        # Should sort by ID
        assert sorted_onto["entities"][0]["id"] == "e1"
        assert sorted_onto["entities"][1]["id"] == "e2"
        
        # All fields should be preserved
        assert sorted_onto["entities"][0]["location"] == "Springfield"
        assert sorted_onto["entities"][1]["attributes"] == ["tall", "kind"]
    
    def test_sort_ontology_with_complex_relationships(self):
        """Test sorting ontology with relationships containing many fields."""
        ontology = {
            "entities": [],
            "relationships": [
                {
                    "source": "p2",
                    "target": "o1",
                    "type": "works_at",
                    "confidence": 0.8,
                    "id": "rel_2",
                    "evidence": ["contract", "email"],
                    "metadata": {"start_date": "2020-01-01"}
                },
                {
                    "source": "p1",
                    "target": "o1",
                    "type": "owns",
                    "confidence": 0.95,
                    "id": "rel_1"
                },
            ]
        }
        
        sorted_onto = sort_ontology(ontology)
        
        # Should sort by source
        assert sorted_onto["relationships"][0]["source"] == "p1"
        assert sorted_onto["relationships"][1]["source"] == "p2"
        
        # All fields should be preserved
        assert sorted_onto["relationships"][1]["evidence"] == ["contract", "email"]


class TestSortOntologyErrorHandling:
    """Test error handling in sort_ontology."""
    
    def test_sort_ontology_invalid_type(self):
        """Test error when ontology is not a dict."""
        with pytest.raises(ValueError, match="Expected dict"):
            sort_ontology("not a dict")
    
    def test_sort_ontology_missing_entities_key(self):
        """Test error when entities key is missing."""
        ontology = {"relationships": []}
        
        with pytest.raises(ValueError, match="must have 'entities' and 'relationships' keys"):
            sort_ontology(ontology)
    
    def test_sort_ontology_missing_relationships_key(self):
        """Test error when relationships key is missing."""
        ontology = {"entities": []}
        
        with pytest.raises(ValueError, match="must have 'entities' and 'relationships' keys"):
            sort_ontology(ontology)
    
    def test_sort_ontology_entities_not_list(self):
        """Test error when entities is not a list."""
        ontology = {
            "entities": "not a list",
            "relationships": []
        }
        
        with pytest.raises(ValueError, match="'entities' must be a list"):
            sort_ontology(ontology)
    
    def test_sort_ontology_relationships_not_list(self):
        """Test error when relationships is not a list."""
        ontology = {
            "entities": [],
            "relationships": {"rel1": "data"}
        }
        
        with pytest.raises(ValueError, match="'relationships' must be a list"):
            sort_ontology(ontology)


class TestIsSortedOntology:
    """Test is_sorted_ontology validation function."""
    
    def test_is_sorted_ontology_already_sorted(self):
        """Test that already sorted ontology returns True."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
                {"id": "e3", "type": "Organization", "text": "Acme"},
            ],
            "relationships": [
                {"source": "e1", "target": "e3", "type": "works_at"},
                {"source": "e2", "target": "e3", "type": "owns"},
            ]
        }
        
        assert is_sorted_ontology(ontology) is True
    
    def test_is_sorted_ontology_unsorted_entities(self):
        """Test that unsorted entities returns False."""
        ontology = {
            "entities": [
                {"id": "e3", "type": "Organization", "text": "Acme"},
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
            ],
            "relationships": []
        }
        
        assert is_sorted_ontology(ontology) is False
    
    def test_is_sorted_ontology_unsorted_relationships(self):
        """Test that unsorted relationships returns False."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
            ],
            "relationships": [
                {"source": "e2", "target": "e1", "type": "knows"},
                {"source": "e1", "target": "e2", "type": "works_with"},
            ]
        }
        
        assert is_sorted_ontology(ontology) is False
    
    def test_is_sorted_ontology_empty_ontology(self):
        """Test that empty ontology is considered sorted."""
        ontology = {
            "entities": [],
            "relationships": []
        }
        
        assert is_sorted_ontology(ontology) is True
    
    def test_is_sorted_ontology_single_entity(self):
        """Test that single entity ontology is always sorted."""
        ontology = {
            "entities": [{"id": "e1", "type": "Person"}],
            "relationships": []
        }
        
        assert is_sorted_ontology(ontology) is True
    
    def test_is_sorted_ontology_handles_capital_field_names(self):
        """Test validation with uppercase field names."""
        ontology = {
            "entities": [
                {"Id": "e1", "Type": "Person"},
                {"Id": "e2", "Type": "Organization"},
            ],
            "relationships": []
        }
        
        # Should recognize as sorted
        assert is_sorted_ontology(ontology) is True
    
    def test_is_sorted_ontology_invalid_structure_returns_false(self):
        """Test that invalid ontology structure returns False (not exception)."""
        # Invalid: not a dict
        assert is_sorted_ontology("not a dict") is False
        
        # Invalid: missing keys
        assert is_sorted_ontology({"entities": []}) is False
        
        # Invalid: entities not a list
        assert is_sorted_ontology({"entities": "not a list", "relationships": []}) is False


class TestSortingStability:
    """Test sorting stability and determinism."""
    
    def test_sort_entities_stable_sorting(self):
        """Test that sorting is stable (preserves relative order of equal elements)."""
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice", "metadata": {"index": 1}},
            {"id": "e1", "type": "Person", "text": "Alice", "metadata": {"index": 2}},
            {"id": "e1", "type": "Person", "text": "Alice", "metadata": {"index": 3}},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # When all sort keys are equal, original order should be preserved (stable sort)
        # Python's sorted() is stable by default
        assert sorted_ents[0]["metadata"]["index"] == 1
        assert sorted_ents[1]["metadata"]["index"] == 2
        assert sorted_ents[2]["metadata"]["index"] == 3
    
    def test_multiple_sorts_produce_identical_results(self):
        """Test that sorting same ontology multiple times produces identical results."""
        ontology = {
            "entities": [
                {"id": "e3", "type": "Person"},
                {"id": "e1", "type": "Organization"},
                {"id": "e2", "type": "Location"},
            ],
            "relationships": [
                {"source": "e3", "target": "e1", "type": "works_at"},
                {"source": "e1", "target": "e2", "type": "located_at"},
            ]
        }
        
        sorted1 = sort_ontology(ontology)
        sorted2 = sort_ontology(ontology)
        sorted3 = sort_ontology(sorted1)  # Sort already sorted
        
        # All should be identical
        assert sorted1 == sorted2 == sorted3
    
    def test_different_orderings_produce_same_sorted_result(self):
        """Test that different orderings of same content produce identical sorted results."""
        ontology1 = {
            "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
            "relationships": []
        }
        
        ontology2 = {
            "entities": [{"id": "e3"}, {"id": "e1"}, {"id": "e2"}],
            "relationships": []
        }
        
        ontology3 = {
            "entities": [{"id": "e2"}, {"id": "e3"}, {"id": "e1"}],
            "relationships": []
        }
        
        sorted1 = sort_ontology(ontology1)
        sorted2 = sort_ontology(ontology2)
        sorted3 = sort_ontology(ontology3)
        
        # All should produce identical sorted results
        assert sorted1 == sorted2 == sorted3


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""
    
    def test_deduplication_use_case(self):
        """Test sorting enables dictionary-based deduplication."""
        # Same content, different orderings
        onto1 = {
            "entities": [{"id": "e2"}, {"id": "e1"}],
            "relationships": [{"source": "e2", "target": "e1"}]
        }
        
        onto2 = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"source": "e2", "target": "e1"}]
        }
        
        # Unsorted, they look different
        assert onto1 != onto2
        
        # But sorted, they're identical
        sorted1 = sort_ontology(onto1)
        sorted2 = sort_ontology(onto2)
        
        assert sorted1 == sorted2
    
    def test_snapshot_testing_use_case(self):
        """Test sorting enables reproducible snapshot testing."""
        # Generate ontology (order may vary)
        generated = {
            "entities": [
                {"id": "e3", "type": "Person", "text": "Charlie"},
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
            ],
            "relationships": []
        }
        
        # Sort for deterministic comparison
        sorted_onto = sort_ontology(generated)
        
        # Expected snapshot (sorted order)
        expected_snapshot = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
                {"id": "e3", "type": "Person", "text": "Charlie"},
            ],
            "relationships": []
        }
        
        assert sorted_onto == expected_snapshot
    
    def test_validation_workflow(self):
        """Test complete validation workflow: check if sorted, sort if needed."""
        ontology = {
            "entities": [{"id": "e3"}, {"id": "e1"}],
            "relationships": []
        }
        
        # Check if already sorted
        if not is_sorted_ontology(ontology):
            # Sort if needed
            ontology = sort_ontology(ontology)
        
        # Now should be sorted
        assert is_sorted_ontology(ontology) is True
        assert ontology["entities"][0]["id"] == "e1"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_entities_with_none_values(self):
        """Test entities with None values."""
        entities = [
            {"id": None, "type": None, "text": None},
            {"id": "e1", "type": "Person", "text": "Alice"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # None should be converted to "" and sort first
        assert sorted_ents[0]["id"] is None
        assert sorted_ents[1]["id"] == "e1"
    
    def test_relationships_with_none_values(self):
        """Test relationships with None values."""
        relationships = [
            {"source": "e1", "target": None, "type": None},
            {"source": None, "target": "e2", "type": "knows"},
        ]
        
        sorted_rels = sort_relationships(relationships)
        
        # None source should sort first
        assert sorted_rels[0]["source"] is None
        assert sorted_rels[1]["source"] == "e1"
    
    def test_very_large_entity_list(self):
        """Test sorting large entity list."""
        # Generate 1000 entities in reverse order
        entities = [{"id": f"e{i:04d}"} for i in range(1000, 0, -1)]
        
        sorted_ents = sort_entities(entities)
        
        # Should be in ascending order
        assert sorted_ents[0]["id"] == "e0001"
        assert sorted_ents[999]["id"] == "e1000"
        assert len(sorted_ents) == 1000
    
    def test_unicode_entity_text(self):
        """Test entities with Unicode text."""
        entities = [
            {"id": "e3", "type": "Person", "text": "李明"},  # Chinese
            {"id": "e1", "type": "Person", "text": "Alice"},  # English
            {"id": "e2", "type": "Person", "text": "José"},  # Spanish
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Should sort by ID regardless of Unicode in text
        assert sorted_ents[0]["id"] == "e1"
        assert sorted_ents[1]["id"] == "e2"
        assert sorted_ents[2]["id"] == "e3"
    
    def test_special_characters_in_ids(self):
        """Test entities with special characters in IDs."""
        entities = [
            {"id": "person:123", "type": "Person"},
            {"id": "person-456", "type": "Person"},
            {"id": "person_789", "type": "Person"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Should sort by ASCII values (- before : before _)
        assert sorted_ents[0]["id"] == "person-456"
        assert sorted_ents[1]["id"] == "person:123"
        assert sorted_ents[2]["id"] == "person_789"
    
    def test_duplicate_entities_different_confidence(self):
        """Test handling of duplicate entities with different confidence scores."""
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.7},
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9},
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.8},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Should be ordered by confidence (descending) when other fields equal
        assert sorted_ents[0]["confidence"] == 0.9
        assert sorted_ents[1]["confidence"] == 0.8
        assert sorted_ents[2]["confidence"] == 0.7
    
    def test_numeric_string_ids(self):
        """Test entities with numeric string IDs."""
        entities = [
            {"id": "100", "type": "Person"},
            {"id": "20", "type": "Person"},
            {"id": "3", "type": "Person"},
        ]
        
        sorted_ents = sort_entities(entities)
        
        # Should sort lexicographically, not numerically
        # "100" < "20" < "3" in lexicographic order
        assert sorted_ents[0]["id"] == "100"
        assert sorted_ents[1]["id"] == "20"
        assert sorted_ents[2]["id"] == "3"


class TestOntologyUtilsIntegration:
    """Test integration scenarios across multiple functions."""
    
    def test_complete_sorting_pipeline(self):
        """Test complete sorting pipeline from unsorted to validated."""
        unsorted_ontology = {
            "entities": [
                {"id": "e3", "type": "Person", "text": "Charlie", "confidence": 0.8},
                {"id": "e1", "type": "Organization", "text": "Acme", "confidence": 0.95},
                {"id": "e2", "type": "Location", "text": "Springfield", "confidence": 0.7},
            ],
            "relationships": [
                {"source": "e3", "target": "e1", "type": "works_at", "confidence": 0.9},
                {"source": "e1", "target": "e2", "type": "located_at", "confidence": 0.85},
                {"source": "e2", "target": "e1", "type": "contains", "confidence": 0.6},
            ]
        }
        
        # Step 1: Check if sorted
        assert is_sorted_ontology(unsorted_ontology) is False
        
        # Step 2: Sort entities
        sorted_entities = sort_entities(unsorted_ontology["entities"])
        assert sorted_entities[0]["id"] == "e1"
        assert sorted_entities[1]["id"] == "e2"
        assert sorted_entities[2]["id"] == "e3"
        
        # Step 3: Sort relationships
        sorted_relationships = sort_relationships(unsorted_ontology["relationships"])
        assert sorted_relationships[0]["source"] == "e1"
        assert sorted_relationships[1]["source"] == "e2"
        assert sorted_relationships[2]["source"] == "e3"
        
        # Step 4: Sort complete ontology
        sorted_ontology = sort_ontology(unsorted_ontology)
        
        # Step 5: Validate sorted
        assert is_sorted_ontology(sorted_ontology) is True
    
    def test_sort_idempotence(self):
        """Test that sorting is idempotent (sorting sorted data produces same result)."""
        ontology = {
            "entities": [{"id": "e3"}, {"id": "e1"}, {"id": "e2"}],
            "relationships": [{"source": "e2", "target": "e1"}]
        }
        
        sorted_once = sort_ontology(ontology)
        sorted_twice = sort_ontology(sorted_once)
        sorted_thrice = sort_ontology(sorted_twice)
        
        # All should be identical
        assert sorted_once == sorted_twice == sorted_thrice
        assert is_sorted_ontology(sorted_once) is True
    
    def test_mixed_case_field_consistency(self):
        """Test that mixed lowercase/uppercase field names are handled consistently."""
        ontology1 = {
            "entities": [
                {"id": "e2", "type": "Person"},
                {"id": "e1", "type": "Organization"},
            ],
            "relationships": []
        }
        
        ontology2 = {
            "entities": [
                {"Id": "e2", "Type": "Person"},
                {"Id": "e1", "Type": "Organization"},
            ],
            "relationships": []
        }
        
        sorted1 = sort_ontology(ontology1)
        sorted2 = sort_ontology(ontology2)
        
        # Both should produce sorted results (by ID regardless of case)
        assert sorted1["entities"][0]["id"] == "e1"
        assert sorted2["entities"][0]["Id"] == "e1"
