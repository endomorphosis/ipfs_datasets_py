"""
Comprehensive tests for ontology_serialization.py TypedDict contracts.

Tests validate:
1. EntityDictModel structure and field presence
2. RelationshipDictModel structure and field types
3. OntologyDictModel with entities and relationships
4. Return type contracts for serialization functions
5. Data flow and completeness
6. Type contract compliance across the module
"""

import pytest
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.ontology_serialization import (
    entity_model_to_dict,
    relationship_model_to_dict,
    build_ontology_dict,
    ontology_from_extraction_result,
    EntityDictModel,
    RelationshipDictModel,
    OntologyDictModel,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)


class TestEntityDictModelType:
    """Validate EntityDictModel structure and field types"""
    
    def test_entity_model_to_dict_returns_all_required_fields(self):
        """Verify entity_model_to_dict returns all EntityDictModel fields"""
        entity = Entity(
            id="entity_123",
            text="John Doe",
            type="PERSON",
            confidence=0.95,
            properties={"age": 30, "title": "Engineer"}
        )
        
        result = entity_model_to_dict(entity)
        
        assert 'id' in result
        assert 'text' in result
        assert 'type' in result
        assert 'confidence' in result
        assert 'properties' in result
    
    def test_entity_dict_id_is_string(self):
        """Verify entity ID is string in output"""
        entity = Entity(
            id="entity_456",
            text="Test Entity",
            type="TEST",
            confidence=0.9,
            properties={}
        )
        
        result = entity_model_to_dict(entity)
        
        assert isinstance(result['id'], str)
        assert result['id'] == "entity_456"
    
    def test_entity_dict_text_is_string(self):
        """Verify entity text representation is string"""
        entity = Entity(
            id="e1",
            text="Organization Name",
            type="ORGANIZATION",
            confidence=0.85,
            properties={}
        )
        
        result = entity_model_to_dict(entity)
        
        assert isinstance(result['text'], str)
        assert result['text'] == "Organization Name"
    
    def test_entity_dict_type_is_string(self):
        """Verify entity type is string"""
        entity = Entity(
            id="e2",
            text="Location",
            type="LOCATION",
            confidence=0.88,
            properties={}
        )
        
        result = entity_model_to_dict(entity)
        
        assert isinstance(result['type'], str)
        assert result['type'] == "LOCATION"
    
    def test_entity_dict_confidence_is_float_in_valid_range(self):
        """Verify confidence is float between 0 and 1"""
        entity = Entity(
            id="e3",
            text="Test",
            type="TYPE",
            confidence=0.75,
            properties={}
        )
        
        result = entity_model_to_dict(entity)
        
        assert isinstance(result['confidence'], float)
        assert 0.0 <= result['confidence'] <= 1.0
    
    def test_entity_dict_properties_is_dict(self):
        """Verify properties field is dictionary"""
        props = {"key1": "value1", "nested": {"key2": "value2"}}
        entity = Entity(
            id="e4",
            text="Entity",
            type="TEST",
            confidence=0.9,
            properties=props
        )
        
        result = entity_model_to_dict(entity)
        
        assert isinstance(result['properties'], dict)
        assert result['properties'] == props
    
    def test_entity_dict_with_empty_properties(self):
        """Verify entity with empty properties is handled correctly"""
        entity = Entity(
            id="e5",
            text="Minimal Entity",
            type="TYPE",
            confidence=0.8,
            properties={}
        )
        
        result = entity_model_to_dict(entity)
        
        assert isinstance(result['properties'], dict)
        assert len(result['properties']) == 0


class TestRelationshipDictModelType:
    """Validate RelationshipDictModel structure and field types"""
    
    def test_relationship_model_to_dict_returns_all_required_fields(self):
        """Verify relationship_model_to_dict returns all RelationshipDictModel fields"""
        rel = Relationship(
            id="rel_001",
            source_id="entity_1",
            target_id="entity_2",
            type="IS-RELATED-TO",
            confidence=0.92,
            properties={"context": "inferred"}
        )
        
        result = relationship_model_to_dict(rel)
        
        assert 'id' in result
        assert 'source_id' in result
        assert 'target_id' in result
        assert 'type' in result
        assert 'confidence' in result
        assert 'properties' in result
    
    def test_relationship_dict_id_is_string(self):
        """Verify relationship ID is string"""
        rel = Relationship(
            id="rel_123",
            source_id="s1",
            target_id="t1",
            type="TYPE",
            confidence=0.9,
            properties={}
        )
        
        result = relationship_model_to_dict(rel)
        
        assert isinstance(result['id'], str)
        assert result['id'] == "rel_123"
    
    def test_relationship_dict_source_and_target_ids_are_strings(self):
        """Verify source_id and target_id are strings"""
        rel = Relationship(
            id="r1",
            source_id="entity_A",
            target_id="entity_B",
            type="CONNECTED",
            confidence=0.85,
            properties={}
        )
        
        result = relationship_model_to_dict(rel)
        
        assert isinstance(result['source_id'], str)
        assert isinstance(result['target_id'], str)
        assert result['source_id'] == "entity_A"
        assert result['target_id'] == "entity_B"
    
    def test_relationship_dict_type_is_string(self):
        """Verify relationship type is string"""
        rel = Relationship(
            id="r2",
            source_id="s",
            target_id="t",
            type="KNOWS",
            confidence=0.9,
            properties={}
        )
        
        result = relationship_model_to_dict(rel)
        
        assert isinstance(result['type'], str)
        assert result['type'] == "KNOWS"
    
    def test_relationship_dict_confidence_is_float_in_valid_range(self):
        """Verify confidence is float between 0 and 1"""
        rel = Relationship(
            id="r3",
            source_id="s",
            target_id="t",
            type="TYPE",
            confidence=0.67,
            properties={}
        )
        
        result = relationship_model_to_dict(rel)
        
        assert isinstance(result['confidence'], float)
        assert 0.0 <= result['confidence'] <= 1.0
    
    def test_relationship_dict_properties_is_dict(self):
        """Verify properties is dictionary"""
        props = {"direction": "bidirectional", "since": 2020}
        rel = Relationship(
            id="r4",
            source_id="s",
            target_id="t",
            type="TYPE",
            confidence=0.88,
            properties=props
        )
        
        result = relationship_model_to_dict(rel)
        
        assert isinstance(result['properties'], dict)
        assert result['properties'] == props


class TestOntologyDictModelType:
    """Validate OntologyDictModel structure"""
    
    def test_build_ontology_dict_returns_entities_and_relationships(self):
        """Verify build_ontology_dict returns proper structure"""
        entities = [
            Entity(id="e1", text="Entity 1", type="T1", confidence=0.9, properties={}),
            Entity(id="e2", text="Entity 2", type="T2", confidence=0.85, properties={})
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e2", type="REL", confidence=0.88, properties={})
        ]
        
        result = build_ontology_dict(entities=entities, relationships=relationships)
        
        assert 'entities' in result
        assert 'relationships' in result
    
    def test_ontology_dict_entities_is_list_of_dicts(self):
        """Verify entities field is list of entity dicts"""
        entities = [
            Entity(id="e1", text="E1", type="T", confidence=0.9, properties={}),
            Entity(id="e2", text="E2", type="T", confidence=0.85, properties={})
        ]
        
        result = build_ontology_dict(entities=entities, relationships=[])
        
        assert isinstance(result['entities'], list)
        assert len(result['entities']) == 2
        assert all(isinstance(e, dict) for e in result['entities'])
    
    def test_ontology_dict_relationships_is_list_of_dicts(self):
        """Verify relationships field is list of relationship dicts"""
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e2", type="T", confidence=0.9, properties={}),
            Relationship(id="r2", source_id="e2", target_id="e1", type="T", confidence=0.88, properties={})
        ]
        
        result = build_ontology_dict(entities=[], relationships=relationships)
        
        assert isinstance(result['relationships'], list)
        assert len(result['relationships']) == 2
        assert all(isinstance(r, dict) for r in result['relationships'])


class TestOntologyExtractionIntegration:
    """Integration tests for ontology_from_extraction_result"""
    
    def test_ontology_from_extraction_result_returns_complete_structure(self):
        """Verify ontology_from_extraction_result returns entities and relationships"""
        entity1 = Entity(id="e1", text="Person A", type="PERSON", confidence=0.95, properties={})
        entity2 = Entity(id="e2", text="Company B", type="ORGANIZATION", confidence=0.92, properties={})
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="WORKS-FOR", confidence=0.90, properties={})
        
        extraction = EntityExtractionResult(
            entities=[entity1, entity2],
            relationships=[rel],
            confidence=0.92
        )
        
        result = ontology_from_extraction_result(extraction)
        
        assert 'entities' in result
        assert 'relationships' in result
        assert len(result['entities']) == 2
        assert len(result['relationships']) == 1
    
    def test_ontology_from_extraction_preserves_entity_fields(self):
        """Verify entity fields are preserved through extraction conversion"""
        entity = Entity(
            id="test_id",
            text="Test Person",
            type="PERSON",
            confidence=0.93,
            properties={"role": "analyst"}
        )
        
        extraction = EntityExtractionResult(entities=[entity], relationships=[], confidence=0.9)
        result = ontology_from_extraction_result(extraction)
        
        entity_dict = result['entities'][0]
        assert entity_dict['id'] == "test_id"
        assert entity_dict['text'] == "Test Person"
        assert entity_dict['type'] == "PERSON"
        assert entity_dict['confidence'] == 0.93
        assert entity_dict['properties']['role'] == "analyst"
    
    def test_ontology_from_extraction_preserves_relationship_fields(self):
        """Verify relationship fields are preserved through extraction conversion"""
        rel = Relationship(
            id="rel_id",
            source_id="e1",
            target_id="e2",
            type="MANAGES",
            confidence=0.91,
            properties={"since": 2020}
        )
        
        extraction = EntityExtractionResult(entities=[], relationships=[rel], confidence=0.9)
        result = ontology_from_extraction_result(extraction)
        
        rel_dict = result['relationships'][0]
        assert rel_dict['id'] == "rel_id"
        assert rel_dict['source_id'] == "e1"
        assert rel_dict['target_id'] == "e2"
        assert rel_dict['type'] == "MANAGES"
        assert rel_dict['confidence'] == 0.91
        assert rel_dict['properties']['since'] == 2020


class TestTypeContractDataFlow:
    """Test data flow and consistency of type contracts"""
    
    def test_entity_confidence_values_consistent(self):
        """Verify entity confidence values are preserved accurately"""
        test_confidences = [0.0, 0.25, 0.5, 0.75, 0.99, 1.0]
        
        for conf in test_confidences:
            entity = Entity(id="e", text="t", type="T", confidence=conf, properties={})
            result = entity_model_to_dict(entity)
            assert result['confidence'] == conf
    
    def test_relationship_confidence_values_consistent(self):
        """Verify relationship confidence values are preserved accurately"""
        test_confidences = [0.0, 0.25, 0.5, 0.75, 0.99, 1.0]
        
        for conf in test_confidences:
            rel = Relationship(id="r", source_id="s", target_id="t", type="T", confidence=conf, properties={})
            result = relationship_model_to_dict(rel)
            assert result['confidence'] == conf
    
    def test_entity_properties_with_complex_nesting(self):
        """Verify complex nested properties in entities are preserved"""
        complex_props = {
            "meta": {
                "level1": {
                    "level2": ["a", "b", "c"],
                    "count": 42
                }
            },
            "tags": ["tag1", "tag2"]
        }
        
        entity = Entity(id="e", text="t", type="T", confidence=0.9, properties=complex_props)
        result = entity_model_to_dict(entity)
        
        assert result['properties']['meta']['level1']['level2'] == ["a", "b", "c"]
        assert result['properties']['meta']['level1']['count'] == 42
    
    def test_relationship_properties_with_complex_nesting(self):
        """Verify complex nested properties in relationships are preserved"""
        complex_props = {
            "attributes": {
                "strength": "strong",
                "metadata": {"created": 2024}
            },
            "history": []
        }
        
        rel = Relationship(
            id="r", source_id="s", target_id="t", type="T",
            confidence=0.9, properties=complex_props
        )
        result = relationship_model_to_dict(rel)
        
        assert result['properties']['attributes']['strength'] == "strong"
        assert result['properties']['attributes']['metadata']['created'] == 2024


class TestOntologySerializationConsistency:
    """Test consistency of serialization across different scenarios"""
    
    def test_ontology_with_multiple_entities_and_relationships(self):
        """Test ontology serialization with realistic data volume"""
        entities = [
            Entity(id=f"e{i}", text=f"Entity {i}", type="TYPE", confidence=0.9 - i*0.01, properties={})
            for i in range(10)
        ]
        relationships = [
            Relationship(
                id=f"r{i}",
                source_id=f"e{i}",
                target_id=f"e{(i+1)%10}",
                type="CONNECTS",
                confidence=0.88 - i*0.01,
                properties={}
            )
            for i in range(10)
        ]
        
        extraction = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.9)
        result = ontology_from_extraction_result(extraction)
        
        assert len(result['entities']) == 10
        assert len(result['relationships']) == 10
        assert all('id' in e for e in result['entities'])
        assert all('type' in r for r in result['relationships'])
    
    def test_empty_ontology_serialization(self):
        """Verify empty ontology is handled correctly"""
        extraction = EntityExtractionResult(entities=[], relationships=[], confidence=0.9)
        result = ontology_from_extraction_result(extraction)
        
        assert isinstance(result['entities'], list)
        assert isinstance(result['relationships'], list)
        assert len(result['entities']) == 0
        assert len(result['relationships']) == 0
    
    def test_ontology_with_special_characters_in_text(self):
        """Verify special characters are preserved in serialization"""
        special_text = "Entity with & symbols, quotes 'like this', and émojis 🚀"
        entity = Entity(
            id="e_special",
            text=special_text,
            type="TEST",
            confidence=0.9,
            properties={}
        )
        
        result = entity_model_to_dict(entity)
        
        assert result['text'] == special_text


class TestTypeContractCompliance:
    """Verify type contracts match actual return values"""
    
    def test_entity_dict_model_matches_entity_model_to_dict_output(self):
        """Verify EntityDictModel structure matches actual output"""
        entity = Entity(id="e", text="t", type="T", confidence=0.9, properties={"k": "v"})
        result = entity_model_to_dict(entity)
        
        # Verify all EntityDictModel fields are present
        assert set(['id', 'text', 'type', 'confidence', 'properties']).issubset(set(result.keys()))
    
    def test_relationship_dict_model_matches_output(self):
        """Verify RelationshipDictModel structure matches actual output"""
        rel = Relationship(
            id="r", source_id="s", target_id="t", type="T",
            confidence=0.9, properties={"k": "v"}
        )
        result = relationship_model_to_dict(rel)
        
        # Verify all RelationshipDictModel fields are present
        expected_fields = {'id', 'source_id', 'target_id', 'type', 'confidence', 'properties'}
        assert expected_fields.issubset(set(result.keys()))
    
    def test_ontology_dict_model_matches_extracted_ontology_output(self):
        """Verify OntologyDictModel structure matches actual output"""
        entity = Entity(id="e", text="t", type="T", confidence=0.9, properties={})
        rel = Relationship(id="r", source_id="e", target_id="e", type="T", confidence=0.9, properties={})
        
        extraction = EntityExtractionResult(entities=[entity], relationships=[rel], confidence=0.9)
        result = ontology_from_extraction_result(extraction)
        
        # Verify OntologyDictModel structure
        assert set(['entities', 'relationships']).issubset(set(result.keys()))
        assert isinstance(result['entities'], list)
        assert isinstance(result['relationships'], list)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
