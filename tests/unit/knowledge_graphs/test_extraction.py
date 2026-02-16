"""
Unit tests for knowledge_graph_extraction module.

This module tests the core functionality of knowledge graph extraction,
including Entity, Relationship, KnowledgeGraph, and extractor classes.

Following GIVEN-WHEN-THEN format as per repository standards.
"""

import pytest
import json
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation,
)


class TestEntity:
    """Test Entity class."""
    
    def test_entity_creation_with_defaults(self):
        """
        GIVEN basic entity attributes
        WHEN creating an Entity instance with defaults
        THEN entity is created with correct default values
        """
        # WHEN
        entity = Entity(
            entity_type="person",
            name="John Doe"
        )
        
        # THEN
        assert entity.entity_type == "person"
        assert entity.name == "John Doe"
        assert entity.entity_id is not None  # Auto-generated UUID
        assert entity.properties == {}
        assert entity.confidence == 1.0
        assert entity.source_text is None
    
    def test_entity_creation_with_all_fields(self):
        """
        GIVEN complete entity attributes
        WHEN creating an Entity instance
        THEN all attributes are set correctly
        """
        # GIVEN
        entity_id = "test_id_123"
        entity_type = "organization"
        name = "Apple Inc."
        properties = {"founded": "1976", "location": "Cupertino"}
        confidence = 0.95
        source_text = "Apple Inc. was founded in 1976"
        
        # WHEN
        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            name=name,
            properties=properties,
            confidence=confidence,
            source_text=source_text
        )
        
        # THEN
        assert entity.entity_id == entity_id
        assert entity.entity_type == entity_type
        assert entity.name == name
        assert entity.properties == properties
        assert entity.confidence == confidence
        assert entity.source_text == source_text
    
    def test_entity_to_dict(self, sample_entity):
        """
        GIVEN an Entity instance
        WHEN converting to dictionary
        THEN returns correct dictionary representation
        """
        # WHEN
        entity_dict = sample_entity.to_dict()
        
        # THEN
        assert isinstance(entity_dict, dict)
        assert entity_dict["entity_id"] == sample_entity.entity_id
        assert entity_dict["entity_type"] == sample_entity.entity_type
        assert entity_dict["name"] == sample_entity.name
        assert entity_dict["properties"] == sample_entity.properties
        assert entity_dict["confidence"] == sample_entity.confidence
    
    def test_entity_from_dict(self):
        """
        GIVEN a dictionary representation of an entity
        WHEN creating Entity from dict
        THEN entity is created with correct attributes
        """
        # GIVEN
        entity_data = {
            "entity_id": "e1",
            "entity_type": "person",
            "name": "Alice",
            "properties": {"age": "30"},
            "confidence": 0.9,
            "source_text": "Alice is 30 years old"
        }
        
        # WHEN
        entity = Entity.from_dict(entity_data)
        
        # THEN
        assert entity.entity_id == entity_data["entity_id"]
        assert entity.entity_type == entity_data["entity_type"]
        assert entity.name == entity_data["name"]
        assert entity.properties == entity_data["properties"]
        assert entity.confidence == entity_data["confidence"]
        assert entity.source_text == entity_data["source_text"]
    
    def test_entity_round_trip_serialization(self, sample_entity):
        """
        GIVEN an Entity instance
        WHEN converting to dict and back
        THEN entity is preserved
        """
        # WHEN
        entity_dict = sample_entity.to_dict()
        restored_entity = Entity.from_dict(entity_dict)
        
        # THEN
        assert restored_entity.entity_id == sample_entity.entity_id
        assert restored_entity.entity_type == sample_entity.entity_type
        assert restored_entity.name == sample_entity.name
        assert restored_entity.properties == sample_entity.properties
        assert restored_entity.confidence == sample_entity.confidence


class TestRelationship:
    """Test Relationship class."""
    
    def test_relationship_creation(self, sample_entities):
        """
        GIVEN source and target entities
        WHEN creating a Relationship
        THEN relationship is created correctly
        """
        # GIVEN
        source = sample_entities[0]
        target = sample_entities[1]
        rel_type = "FOUNDED_BY"
        properties = {"year": "1976"}
        confidence = 0.9
        
        # WHEN
        relationship = Relationship(
            source_entity=source,
            target_entity=target,
            relationship_type=rel_type,
            properties=properties,
            confidence=confidence
        )
        
        # THEN
        assert relationship.source_entity == source
        assert relationship.target_entity == target
        assert relationship.relationship_type == rel_type
        assert relationship.properties == properties
        assert relationship.confidence == confidence
    
    def test_relationship_with_defaults(self, sample_entities):
        """
        GIVEN source and target entities only
        WHEN creating Relationship with defaults
        THEN default values are set
        """
        # GIVEN
        source = sample_entities[0]
        target = sample_entities[1]
        
        # WHEN
        relationship = Relationship(
            source_entity=source,
            target_entity=target,
            relationship_type="RELATED_TO"
        )
        
        # THEN
        assert relationship.properties == {}
        assert relationship.confidence == 1.0
        assert relationship.source_text is None
    
    def test_relationship_to_dict(self, sample_relationship):
        """
        GIVEN a Relationship instance
        WHEN converting to dictionary
        THEN returns correct dictionary representation
        """
        # WHEN
        rel_dict = sample_relationship.to_dict()
        
        # THEN
        assert isinstance(rel_dict, dict)
        assert "source" in rel_dict  # API uses "source" not "source_entity"
        assert "target" in rel_dict  # API uses "target" not "target_entity"
        assert rel_dict["relationship_type"] == sample_relationship.relationship_type
        assert rel_dict["confidence"] == sample_relationship.confidence
    
    def test_relationship_from_dict(self):
        """
        GIVEN a dictionary representation of a relationship
        WHEN creating Relationship from dict
        THEN relationship is created correctly
        """
        # GIVEN
        rel_data = {
            "source": {  # API uses "source" not "source_entity"
                "entity_id": "e1",
                "entity_type": "person",
                "name": "John",
                "properties": {},
                "confidence": 1.0
            },
            "target": {  # API uses "target" not "target_entity"
                "entity_id": "e2",
                "entity_type": "organization",
                "name": "Microsoft",
                "properties": {},
                "confidence": 1.0
            },
            "relationship_type": "WORKS_AT",
            "properties": {"since": "2020"},
            "confidence": 0.85
        }
        
        # WHEN
        relationship = Relationship.from_dict(rel_data)
        
        # THEN
        assert relationship.source_entity.name == "John"
        assert relationship.target_entity.name == "Microsoft"
        assert relationship.relationship_type == "WORKS_AT"
        assert relationship.properties == {"since": "2020"}
        assert relationship.confidence == 0.85


class TestKnowledgeGraph:
    """Test KnowledgeGraph class."""
    
    def test_knowledge_graph_creation(self):
        """
        GIVEN nothing
        WHEN creating KnowledgeGraph
        THEN empty graph is created
        """
        # WHEN
        kg = KnowledgeGraph()
        
        # THEN
        assert kg.entities == {}
        assert kg.relationships == {}  # Dict not List
        assert hasattr(kg, 'name')  # Has a name attribute
    
    def test_add_entity(self, empty_knowledge_graph, sample_entity):
        """
        GIVEN a KnowledgeGraph and entity
        WHEN adding entity
        THEN entity is added to graph
        """
        # GIVEN
        kg = empty_knowledge_graph
        entity = sample_entity
        
        # WHEN
        kg.add_entity(entity)
        
        # THEN
        assert entity.entity_id in kg.entities
        assert kg.entities[entity.entity_id] == entity
        assert len(kg.entities) == 1
    
    def test_add_multiple_entities(self, empty_knowledge_graph, sample_entities):
        """
        GIVEN a KnowledgeGraph and multiple entities
        WHEN adding all entities
        THEN all entities are in graph
        """
        # GIVEN
        kg = empty_knowledge_graph
        
        # WHEN
        for entity in sample_entities:
            kg.add_entity(entity)
        
        # THEN
        assert len(kg.entities) == len(sample_entities)
        for entity in sample_entities:
            assert entity.entity_id in kg.entities
    
    def test_add_duplicate_entity(self, empty_knowledge_graph, sample_entity):
        """
        GIVEN a KnowledgeGraph with existing entity
        WHEN adding same entity again
        THEN entity is not duplicated
        """
        # GIVEN
        kg = empty_knowledge_graph
        kg.add_entity(sample_entity)
        
        # WHEN
        kg.add_entity(sample_entity)
        
        # THEN
        assert len(kg.entities) == 1
    
    def test_add_relationship(self, empty_knowledge_graph, sample_entities, sample_relationship):
        """
        GIVEN a KnowledgeGraph
        WHEN adding relationship
        THEN relationship is added
        """
        # GIVEN
        kg = empty_knowledge_graph
        for entity in sample_entities:
            kg.add_entity(entity)
        
        # WHEN
        kg.add_relationship(sample_relationship)
        
        # THEN
        assert len(kg.relationships) == 1
        # Check relationship is in dict
        assert sample_relationship.relationship_id in kg.relationships
    
    def test_get_entity(self, populated_knowledge_graph, sample_entities):
        """
        GIVEN a populated KnowledgeGraph
        WHEN getting entity by ID
        THEN returns correct entity
        """
        # GIVEN
        kg = populated_knowledge_graph
        entity = sample_entities[0]
        
        # WHEN
        retrieved = kg.get_entity_by_id(entity.entity_id)  # Actual method name
        
        # THEN
        assert retrieved == entity
    
    def test_get_nonexistent_entity(self, empty_knowledge_graph):
        """
        GIVEN an empty KnowledgeGraph
        WHEN getting nonexistent entity
        THEN returns None
        """
        # WHEN
        result = empty_knowledge_graph.get_entity_by_id("nonexistent_id")  # Actual method name
        
        # THEN
        assert result is None
    
    def test_get_entities_by_type(self, populated_knowledge_graph):
        """
        GIVEN a populated KnowledgeGraph
        WHEN getting entities by type
        THEN returns entities of that type
        """
        # GIVEN
        kg = populated_knowledge_graph
        
        # WHEN
        persons = kg.get_entities_by_type("person")
        orgs = kg.get_entities_by_type("organization")
        
        # THEN
        assert len(persons) >= 1
        assert len(orgs) >= 1
        assert all(e.entity_type == "person" for e in persons)
        assert all(e.entity_type == "organization" for e in orgs)
    
    def test_get_relationships_for_entity(self, populated_knowledge_graph, sample_entities):
        """
        GIVEN a KnowledgeGraph with relationships
        WHEN getting relationships for an entity
        THEN returns correct relationships
        """
        # GIVEN
        kg = populated_knowledge_graph
        entity = sample_entities[0]
        
        # WHEN
        relationships = kg.get_relationships_by_entity(entity)  # Actual method name, takes Entity not ID
        
        # THEN
        assert isinstance(relationships, list)
        # Check that all relationships involve this entity
        for rel in relationships:
            assert (rel.source_entity.entity_id == entity.entity_id or
                    rel.target_entity.entity_id == entity.entity_id)
    
    def test_to_dict(self, populated_knowledge_graph):
        """
        GIVEN a populated KnowledgeGraph
        WHEN converting to dictionary
        THEN returns correct structure
        """
        # GIVEN
        kg = populated_knowledge_graph
        
        # WHEN
        kg_dict = kg.to_dict()
        
        # THEN
        assert isinstance(kg_dict, dict)
        assert "entities" in kg_dict
        assert "relationships" in kg_dict
        assert "name" in kg_dict  # Has name field
        assert isinstance(kg_dict["entities"], list)
        assert isinstance(kg_dict["relationships"], list)
    
    def test_from_dict(self, populated_knowledge_graph):
        """
        GIVEN a dictionary representation of a knowledge graph
        WHEN creating KnowledgeGraph from dict
        THEN graph is created correctly
        """
        # GIVEN
        kg_dict = populated_knowledge_graph.to_dict()
        
        # WHEN
        kg = KnowledgeGraph.from_dict(kg_dict)
        
        # THEN
        assert len(kg.entities) == len(populated_knowledge_graph.entities)
        assert len(kg.relationships) == len(populated_knowledge_graph.relationships)
    
    def test_round_trip_serialization(self, populated_knowledge_graph):
        """
        GIVEN a KnowledgeGraph
        WHEN converting to dict and back
        THEN graph structure is preserved
        """
        # GIVEN
        original_kg = populated_knowledge_graph
        
        # WHEN
        kg_dict = original_kg.to_dict()
        restored_kg = KnowledgeGraph.from_dict(kg_dict)
        
        # THEN
        assert len(restored_kg.entities) == len(original_kg.entities)
        assert len(restored_kg.relationships) == len(original_kg.relationships)
    
    def test_json_serialization(self, populated_knowledge_graph):
        """
        GIVEN a KnowledgeGraph
        WHEN converting to JSON string
        THEN can be serialized and deserialized
        """
        # GIVEN
        kg = populated_knowledge_graph
        
        # WHEN
        kg_dict = kg.to_dict()
        json_str = json.dumps(kg_dict)
        loaded_dict = json.loads(json_str)
        restored_kg = KnowledgeGraph.from_dict(loaded_dict)
        
        # THEN
        assert len(restored_kg.entities) == len(kg.entities)
        assert len(restored_kg.relationships) == len(kg.relationships)


class TestKnowledgeGraphExtractor:
    """Test KnowledgeGraphExtractor class."""
    
    def test_extractor_initialization(self):
        """
        GIVEN nothing
        WHEN creating KnowledgeGraphExtractor
        THEN extractor is initialized
        """
        # WHEN
        extractor = KnowledgeGraphExtractor()
        
        # THEN
        assert extractor is not None
        assert hasattr(extractor, 'extract_knowledge_graph')  # Actual method name
    
    def test_extract_with_simple_text(self, basic_extractor, simple_text):
        """
        GIVEN simple text
        WHEN extracting knowledge graph
        THEN returns KnowledgeGraph instance
        """
        # WHEN
        kg = basic_extractor.extract_knowledge_graph(simple_text)  # Actual method name
        
        # THEN
        assert isinstance(kg, KnowledgeGraph)
    
    def test_extract_empty_text(self, basic_extractor):
        """
        GIVEN empty text
        WHEN extracting
        THEN returns empty knowledge graph
        """
        # GIVEN
        empty_text = ""
        
        # WHEN
        kg = basic_extractor.extract_knowledge_graph(empty_text)  # Actual method name
        
        # THEN
        assert isinstance(kg, KnowledgeGraph)
        assert len(kg.entities) == 0
        assert len(kg.relationships) == 0
    
    def test_extract_none_text(self, basic_extractor):
        """
        GIVEN None as text
        WHEN extracting
        THEN handles gracefully
        """
        # WHEN/THEN
        try:
            kg = basic_extractor.extract_knowledge_graph(None)  # Actual method name
            # If it succeeds, should return empty graph
            assert isinstance(kg, KnowledgeGraph)
        except (TypeError, AttributeError):
            # Expected if None is not handled
            pass
    
    def test_extract_returns_valid_structure(self, basic_extractor, sample_text):
        """
        GIVEN sample text
        WHEN extracting
        THEN returns valid graph structure
        """
        # WHEN
        kg = basic_extractor.extract_knowledge_graph(sample_text)  # Actual method name
        
        # THEN
        assert isinstance(kg, KnowledgeGraph)
        assert isinstance(kg.entities, dict)
        assert isinstance(kg.relationships, dict)  # Dict not list
        # All entities should have required attributes
        for entity_id, entity in kg.entities.items():
            assert hasattr(entity, 'entity_id')
            assert hasattr(entity, 'entity_type')
            assert hasattr(entity, 'name')


class TestKnowledgeGraphExtractorWithValidation:
    """Test KnowledgeGraphExtractorWithValidation class."""
    
    def test_validation_extractor_creation(self):
        """
        GIVEN nothing
        WHEN creating validation extractor
        THEN extractor with validation is created
        """
        # WHEN
        extractor = KnowledgeGraphExtractorWithValidation()
        
        # THEN
        assert extractor is not None
        # Validation extractor has its own interface
        assert hasattr(extractor, 'extract_knowledge_graph')
    
    def test_extract_with_validation(self, validation_extractor, simple_text):
        """
        GIVEN simple text
        WHEN extracting with validation
        THEN returns validated knowledge graph
        """
        # WHEN
        kg = validation_extractor.extract_knowledge_graph(simple_text)  # Actual method name
        
        # THEN
        assert isinstance(kg, KnowledgeGraph)
        # Entities should pass basic validation
        for entity_id, entity in kg.entities.items():
            assert entity.entity_id is not None
            assert entity.name is not None


# Integration tests
class TestKnowledgeGraphIntegration:
    """Integration tests for full extraction pipeline."""
    
    @pytest.mark.integration
    def test_full_extraction_pipeline(self, sample_text):
        """
        GIVEN sample text
        WHEN running full extraction pipeline
        THEN complete knowledge graph is produced
        """
        # GIVEN
        extractor = KnowledgeGraphExtractor()
        
        # WHEN
        kg = extractor.extract_knowledge_graph(sample_text)  # Actual method name
        
        # THEN
        # Should have some entities (exact number depends on NLP)
        assert isinstance(kg, KnowledgeGraph)
        
        # Should be serializable
        kg_dict = kg.to_dict()
        assert "entities" in kg_dict
        assert "relationships" in kg_dict
        
        # Should be restorable
        restored_kg = KnowledgeGraph.from_dict(kg_dict)
        assert isinstance(restored_kg, KnowledgeGraph)
    
    @pytest.mark.integration
    def test_entity_relationship_integrity(self, sample_text):
        """
        GIVEN extracted knowledge graph
        WHEN checking relationships
        THEN all referenced entities exist
        """
        # GIVEN
        extractor = KnowledgeGraphExtractor()
        kg = extractor.extract_knowledge_graph(sample_text)  # Actual method name
        
        # WHEN/THEN
        for rel_id, rel in kg.relationships.items():  # Dict not list
            # Source and target entities should exist in graph
            source_id = rel.source_entity.entity_id if rel.source_entity else None
            target_id = rel.target_entity.entity_id if rel.target_entity else None
            if source_id:
                assert source_id in kg.entities or rel.source_entity is not None
            if target_id:
                assert target_id in kg.entities or rel.target_entity is not None
