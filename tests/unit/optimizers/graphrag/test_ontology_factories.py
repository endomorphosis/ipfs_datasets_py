"""Tests for ontology factory fixtures.

Verifies that factory methods create valid, properly-structured ontology
objects with expected properties.
"""

import pytest
from tests.fixtures.graphrag.ontology_factories import (
    EntityFactory,
    RelationshipFactory,
    OntologyFactory,
    ExtractionResultFactory,
)


class TestEntityFactory:
    """Test EntityFactory methods."""
    
    def test_default_creates_valid_entity(self):
        """default() should create valid entity with defaults."""
        entity = EntityFactory.default()
        
        assert entity.id == "e1"
        assert entity.type == "Person"
        assert entity.text == "Alice"
        assert entity.confidence == 0.9
        assert entity.properties == {}
        assert entity.source_span is None
        assert entity.last_seen is None
    
    def test_default_with_custom_values(self):
        """default() should accept custom overrides."""
        entity = EntityFactory.default(
            entity_id="custom_id",
            entity_type="Location",
            text="Paris",
            confidence=0.75,
        )
        
        assert entity.id == "custom_id"
        assert entity.type == "Location"
        assert entity.text == "Paris"
        assert entity.confidence == 0.75
    
    def test_high_confidence(self):
        """high_confidence() should create entity with 0.95 confidence."""
        entity = EntityFactory.high_confidence()
        
        assert entity.confidence == 0.95
    
    def test_low_confidence(self):
        """low_confidence() should create entity with 0.55 confidence."""
        entity = EntityFactory.low_confidence()
        
        assert entity.confidence == 0.55
    
    def test_with_properties(self):
        """with_properties() should include custom properties."""
        entity = EntityFactory.with_properties(
            properties={"role": "Manager", "level": 3}
        )
        
        assert entity.properties["role"] == "Manager"
        assert entity.properties["level"] == 3
    
    def test_with_span(self):
        """with_span() should set source_span."""
        entity = EntityFactory.with_span(start=10, end=20)
        
        assert entity.source_span == (10, 20)
    
    def test_batch(self):
        """batch() should create multiple entities."""
        entities = EntityFactory.batch(count=5)
        
        assert len(entities) == 5
        assert entities[0].id == "e1"
        assert entities[4].id == "e5"
        assert all(e.confidence == 0.9 for e in entities)
    
    def test_entity_serialization(self):
        """Created entities should serialize to dict."""
        entity = EntityFactory.default()
        d = entity.to_dict()
        
        assert d["id"] == "e1"
        assert d["type"] == "Person"
        assert d["text"] == "Alice"


class TestRelationshipFactory:
    """Test RelationshipFactory methods."""
    
    def test_default_creates_valid_relationship(self):
        """default() should create valid relationship."""
        rel = RelationshipFactory.default()
        
        assert rel.id == "r1"
        assert rel.source_id == "e1"
        assert rel.target_id == "e2"
        assert rel.type == "works_for"
        assert rel.confidence == 0.85
        assert rel.direction == "subject_to_object"
    
    def test_default_with_custom_values(self):
        """default() should accept custom values."""
        rel = RelationshipFactory.default(
            rel_id="custom_rel",
            source_id="person1",
            target_id="org1",
            rel_type="located_in",
            confidence=0.95,
        )
        
        assert rel.id == "custom_rel"
        assert rel.source_id == "person1"
        assert rel.target_id == "org1"
        assert rel.type == "located_in"
        assert rel.confidence == 0.95
    
    def test_undirected(self):
        """undirected() should create undirected relationship."""
        rel = RelationshipFactory.undirected()
        
        assert rel.direction == "undirected"
    
    def test_unknown_direction(self):
        """unknown_direction() should create unknown direction relationship."""
        rel = RelationshipFactory.unknown_direction()
        
        assert rel.direction == "unknown"
    
    def test_batch(self):
        """batch() should create multiple relationships."""
        rels = RelationshipFactory.batch(count=3)
        
        assert len(rels) == 3
        assert all(isinstance(r.id, str) for r in rels)
    
    def test_batch_with_custom_entity_ids(self):
        """batch() should connect specified entities."""
        source_ids = ["person1", "person2"]
        target_ids = ["org1", "org2"]
        
        rels = RelationshipFactory.batch(
            count=4,
            source_ids=source_ids,
            target_ids=target_ids,
        )
        
        assert len(rels) == 4
        # Should cycle through provided IDs
        assert rels[0].source_id in source_ids
        assert rels[0].target_id in target_ids


class TestOntologyFactory:
    """Test OntologyFactory methods."""
    
    def test_minimal(self):
        """minimal() should create 1 entity, 0 relationships."""
        ont = OntologyFactory.minimal()
        
        assert len(ont["entities"]) == 1
        assert len(ont["relationships"]) == 0
    
    def test_simple(self):
        """simple() should create ontology with specified counts."""
        ont = OntologyFactory.simple(num_entities=5, num_relationships=3)
        
        assert len(ont["entities"]) == 5
        assert len(ont["relationships"]) == 3
    
    def test_simple_default_size(self):
        """simple() should use defaults if not specified."""
        ont = OntologyFactory.simple()
        
        assert len(ont["entities"]) == 3
        assert len(ont["relationships"]) == 2
    
    def test_complex(self):
        """complex() should create diverse ontology."""
        ont = OntologyFactory.complex(num_entities=10, num_relationships=8)
        
        assert len(ont["entities"]) == 10
        assert len(ont["relationships"]) == 8
        
        # Check entity types are varied
        types = {e["type"] for e in ont["entities"]}
        assert len(types) >= 2  # At least 2 different types
    
    def test_complex_with_custom_types(self):
        """complex() should use custom entity types."""
        custom_types = ["CustomType1", "CustomType2"]
        ont = OntologyFactory.complex(
            num_entities=4,
            entity_types=custom_types,
        )
        
        types = {e["type"] for e in ont["entities"]}
        # All types should be from custom list
        assert types.issubset(set(custom_types))
    
    def test_empty(self):
        """empty() should create empty ontology."""
        ont = OntologyFactory.empty()
        
        assert len(ont["entities"]) == 0
        assert len(ont["relationships"]) == 0
    
    def test_ontology_structure(self):
        """Ontologies should have correct structure."""
        ont = OntologyFactory.simple()
        
        assert "entities" in ont
        assert "relationships" in ont
        assert isinstance(ont["entities"], list)
        assert isinstance(ont["relationships"], list)
        
        # Entities should be dicts with required fields
        for entity in ont["entities"]:
            assert "id" in entity
            assert "type" in entity
            assert "text" in entity


class TestExtractionResultFactory:
    """Test ExtractionResultFactory methods."""
    
    def test_default(self):
        """default() should create extraction result."""
        result = ExtractionResultFactory.default()
        
        assert "entities" in result
        assert "relationships" in result
        assert len(result["entities"]) == 5
        assert len(result["relationships"]) == 3
    
    def test_default_with_custom_counts(self):
        """default() should accept custom entity/relationship counts."""
        result = ExtractionResultFactory.default(
            num_entities=10,
            num_relationships=8,
        )
        
        assert len(result["entities"]) == 10
        assert len(result["relationships"]) == 8
    
    def test_default_confidence_variation(self):
        """default() should create entities with varying confidence."""
        result = ExtractionResultFactory.default(
            num_entities=5,
            average_entity_confidence=0.80,
        )
        
        confidences = [e["confidence"] for e in result["entities"]]
        
        # Should have variation
        assert len(set(confidences)) > 1
        # Should be around the average
        mean_conf = sum(confidences) / len(confidences)
        assert 0.70 <= mean_conf <= 0.90


class TestFactoriesIntegration:
    """Integration tests for factories."""
    
    def test_factories_create_valid_objects(self):
        """All factories should create serializable objects."""
        entity = EntityFactory.default()
        rel = RelationshipFactory.default()
        
        # Should serialize without errors
        entity_dict = entity.to_dict()
        rel_dict = rel.to_dict()
        
        assert isinstance(entity_dict, dict)
        assert isinstance(rel_dict, dict)
    
    def test_factories_can_reconstruct(self):
        """Objects should round-trip through serialization."""
        entity = EntityFactory.default()
        entity_dict = entity.to_dict()
        
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        entity2 = Entity.from_dict(entity_dict)
        
        assert entity2.id == entity.id
        assert entity2.type == entity.type
        assert entity2.text == entity.text
    
    def test_ontology_is_valid(self):
        """Ontologies should have valid structure."""
        ont = OntologyFactory.complex(num_entities=10, num_relationships=15)
        
        # All relationships should reference valid entities
        entity_ids = {e["id"] for e in ont["entities"]}
        
        for rel in ont["relationships"]:
            assert rel["source_id"] in entity_ids
            assert rel["target_id"] in entity_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
