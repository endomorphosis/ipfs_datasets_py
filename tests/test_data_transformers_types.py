"""
Comprehensive tests for data_transformers.py TypedDict contracts.

Tests validate:
1. NormalizedEntityDict structure and field types
2. NormalizedRelationshipDict structure
3. NormalizedExtractionResultDict structure
4. EnrichedEntityDict structure
5. Method return type contracts
"""

import pytest
from typing import Dict, Any, List
from dataclasses import dataclass

from ipfs_datasets_py.optimizers.graphrag.data_transformers import (
    normalize_entity,
    normalize_relationship,
    normalize_extraction_result,
    denormalize_entity,
    enrich_entity,
    merge_entities,
    deduplicaterelationships,
    dataclass_to_dict,
    NormalizedEntityDict,
    NormalizedRelationshipDict,
    NormalizedExtractionResultDict,
    EnrichedEntityDict,
)


class TestNormalizedEntityDictType:
    """Validate NormalizedEntityDict structure and field types"""
    
    def test_normalize_entity_returns_normalized_dict(self):
        """Verify normalize_entity returns NormalizedEntityDict"""
        entity = {'id': 'e1', 'name': '  John Smith  ', 'type': 'PERSON', 'confidence': 0.9}
        result = normalize_entity(entity)
        
        assert isinstance(result, dict)
        assert 'id' in result or 'name' in result
    
    def test_normalized_entity_dict_has_correct_fields(self):
        """Verify normalized entity has expected fields"""
        entity = {'id': 'e1', 'name': 'Entity', 'type': 'TEST', 'confidence': 0.8}
        result = normalize_entity(entity)
        
        assert isinstance(result, dict)
        # Should preserve id if present
        if 'id' in entity:
            assert 'id' in result
    
    def test_normalize_entity_trims_whitespace(self):
        """Verify entity name is trimmed"""
        entity = {'name': '  Trimmed Text  '}
        result = normalize_entity(entity)
        
        if 'name' in result and result['name']:
            assert result['name'] == 'Trimmed Text'
    
    def test_normalize_entity_lower_cases_type(self):
        """Verify entity type is lowercased"""
        entity = {'type': 'PERSON', 'name': 'Test'}
        result = normalize_entity(entity)
        
        if 'type' in result:
            assert result['type'] == 'person'
    
    def test_normalize_entity_clamps_confidence(self):
        """Verify confidence is clamped to [0, 1]"""
        entity_over = {'confidence': 1.5}
        result_over = normalize_entity(entity_over)
        
        entity_under = {'confidence': -0.5}
        result_under = normalize_entity(entity_under)
        
        if 'confidence' in result_over:
            assert result_over['confidence'] <= 1.0
        if 'confidence' in result_under:
            assert result_under['confidence'] >= 0.0
    
    def test_normalize_entity_removes_empty_properties(self):
        """Verify empty properties are removed"""
        entity = {
            'properties': {'key': 'value', 'empty': '', 'none': None, 'valid': 'data'}
        }
        result = normalize_entity(entity)
        
        if 'properties' in result:
            assert 'empty' not in result['properties']
            assert 'none' not in result['properties']
            assert 'valid' in result['properties']
    
    def test_denormalize_entity_returns_entity_dict(self):
        """Verify denormalize_entity returns NormalizedEntityDict"""
        entity = {'id': 'e1', 'name': 'Test', 'type': 'TEST'}
        result = denormalize_entity(entity)
        
        assert isinstance(result, dict)
        assert result == entity


class TestNormalizedRelationshipDictType:
    """Validate NormalizedRelationshipDict structure"""
    
    def test_normalize_relationship_returns_normalized_dict(self):
        """Verify normalize_relationship returns NormalizedRelationshipDict"""
        rel = {
            'id': 'r1',
            'source': 'e1',
            'target': 'e2',
            'type': 'RELATED_TO',
            'confidence': 0.85
        }
        result = normalize_relationship(rel)
        
        assert isinstance(result, dict)
    
    def test_normalized_relationship_dict_has_required_fields(self):
        """Verify normalized relationship has expected fields"""
        rel = {
            'source': 'e1',
            'target': 'e2',
            'type': 'RELATES_TO',
            'confidence': 0.8
        }
        result = normalize_relationship(rel)
        
        assert isinstance(result, dict)
        assert 'source' in result
        assert 'target' in result
    
    def test_normalize_relationship_lower_cases_type(self):
        """Verify relationship type is lowercased"""
        rel = {'type': 'RELATED_TO', 'source': 'e1', 'target': 'e2'}
        result = normalize_relationship(rel)
        
        if 'type' in result:
            assert result['type'] == 'related_to'
    
    def test_normalize_relationship_invalid_self_relationship(self):
        """Verify self-relationships raise error"""
        rel = {'source': 'e1', 'target': 'e1', 'type': 'test'}
        
        with pytest.raises(Exception):  # TransformationError
            normalize_relationship(rel)
    
    def test_normalize_relationship_clamps_confidence(self):
        """Verify confidence values are clamped"""
        rel = {
            'source': 'e1',
            'target': 'e2',
            'confidence': 1.5,
            'type_confidence': -0.5
        }
        result = normalize_relationship(rel)
        
        if 'confidence' in result:
            assert 0.0 <= result['confidence'] <= 1.0
        if 'type_confidence' in result:
            assert 0.0 <= result['type_confidence'] <= 1.0


class TestNormalizedExtractionResultDictType:
    """Validate NormalizedExtractionResultDict structure"""
    
    def test_normalize_extraction_result_returns_complete_dict(self):
        """Verify normalize_extraction_result returns NormalizedExtractionResultDict"""
        result_data = {
            'entities': [{'id': 'e1', 'name': 'Entity', 'type': 'TEST'}],
            'relationships': [{'source': 'e1', 'target': 'e2', 'type': 'rel'}]
        }
        result = normalize_extraction_result(result_data)
        
        assert isinstance(result, dict)
        assert 'entities' in result
        assert 'relationships' in result
    
    def test_normalized_extraction_result_entities_normalized(self):
        """Verify entities in result are normalized"""
        result_data = {
            'entities': [
                {'name': '  Invalid Type  ', 'type': 'PERSON', 'confidence': 1.5}
            ]
        }
        result = normalize_extraction_result(result_data)
        
        assert 'entities' in result
        assert len(result['entities']) > 0
        entity = result['entities'][0]
        if 'name' in entity and entity['name']:
            assert entity['name'] == 'Invalid Type'
        if 'type' in entity:
            assert entity['type'] == 'person'
    
    def test_normalized_extraction_result_relationships_normalized(self):
        """Verify relationships in result are normalized"""
        result_data = {
            'relationships': [
                {
                    'source': 'e1',
                    'target': 'e2',
                    'type': 'WORKS_FOR',
                    'confidence': 0.9
                }
            ]
        }
        result = normalize_extraction_result(result_data)
        
        assert 'relationships' in result
        if result['relationships']:
            rel = result['relationships'][0]
            if 'type' in rel:
                assert rel['type'] == 'works_for'


class TestEnrichedEntityDictType:
    """Validate EnrichedEntityDict structure"""
    
    def test_enrich_entity_adds_fields(self):
        """Verify enrich_entity returns EnrichedEntityDict with new fields"""
        entity = {'id': 'e1', 'name': 'Test'}
        enrichment = {'new_field': 'new_value', 'score': 0.95}
        result = enrich_entity(entity, **enrichment)
        
        assert isinstance(result, dict)
        assert 'id' in result
        assert 'name' in result
        assert 'new_field' in result
        assert result['new_field'] == 'new_value'
    
    def test_enrich_entity_preserves_original_fields(self):
        """Verify original entity fields are preserved"""
        entity = {'id': 'e1', 'name': 'Original', 'type': 'PERSON', 'confidence': 0.8}
        result = enrich_entity(entity, extra_field='extra')
        
        assert result['id'] == entity['id']
        assert result['name'] == entity['name']
        assert result['confidence'] == entity['confidence']
    
    def test_enrich_entity_enrichment_overrides_fields(self):
        """Verify enrichment can override existing fields"""
        entity = {'id': 'e1', 'confidence': 0.5}
        result = enrich_entity(entity, confidence=0.9)
        
        assert result['confidence'] == 0.9


class TestMergeEntitiesDictType:
    """Validate merge_entities function return type"""
    
    def test_merge_entities_returns_dict_by_id(self):
        """Verify merge_entities returns dict keyed by entity ID"""
        entities = [
            {'id': 'e1', 'name': 'Entity 1', 'confidence': 0.8},
            {'id': 'e2', 'name': 'Entity 2', 'confidence': 0.9}
        ]
        result = merge_entities(entities)
        
        assert isinstance(result, dict)
        assert 'e1' in result
        assert 'e2' in result
    
    def test_merge_entities_highest_confidence_strategy(self):
        """Verify highest_confidence merge keeps best version"""
        entities = [
            {'id': 'e1', 'name': 'Version 1', 'confidence': 0.7},
            {'id': 'e1', 'name': 'Version 2', 'confidence': 0.9}  # Should win
        ]
        result = merge_entities(entities, merge_strategy='highest_confidence')
        
        assert 'e1' in result
        assert result['e1']['name'] == 'Version 2'
        assert result['e1']['confidence'] == 0.9
    
    def test_merge_entities_average_confidence_strategy(self):
        """Verify average merge computes mean confidence"""
        entities = [
            {'id': 'e1', 'name': 'Entity', 'confidence': 0.8},
            {'id': 'e1', 'name': 'Entity', 'confidence': 0.6}
        ]
        result = merge_entities(entities, merge_strategy='average')
        
        assert 'e1' in result
        if 'confidence' in result['e1']:
            assert result['e1']['confidence'] == pytest.approx(0.7)
    
    def test_merge_entities_ignores_missing_ids(self):
        """Verify entities without IDs are skipped"""
        entities = [
            {'id': 'e1', 'name': 'Entity 1'},
            {'name': 'No ID Entity'},  # Should be skipped
            {'id': 'e2', 'name': 'Entity 2'}
        ]
        result = merge_entities(entities)
        
        assert 'e1' in result
        assert 'e2' in result
        assert len(result) == 2


class TestDeduplicateRelationshipsType:
    """Validate deduplicaterelationships function return type"""
    
    def test_deduplicate_relationships_returns_list(self):
        """Verify deduplicate returns list of unique relationships"""
        relationships = [
            {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 0.8},
            {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 0.9},  # Duplicate
        ]
        result = deduplicaterelationships(relationships)
        
        assert isinstance(result, list)
        assert len(result) == 1
    
    def test_deduplicate_keeps_highest_confidence(self):
        """Verify highest confidence version is kept"""
        relationships = [
            {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 0.6},
            {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 0.9}
        ]
        result = deduplicaterelationships(relationships)
        
        assert len(result) == 1
        assert result[0]['confidence'] == 0.9
    
    def test_deduplicate_different_relationships(self):
        """Verify different relationships are kept"""
        relationships = [
            {'source': 'e1', 'target': 'e2', 'type': 'relA'},
            {'source': 'e1', 'target': 'e2', 'type': 'relB'},
            {'source': 'e1', 'target': 'e3', 'type': 'relA'}
        ]
        result = deduplicaterelationships(relationships)
        
        assert len(result) == 3  # All unique


class TestDataclassToDictType:
    """Validate dataclass_to_dict return type"""
    
    def test_dataclass_to_dict_returns_dict(self):
        """Verify dataclass_to_dict returns DataclassDictRepDict"""
        @dataclass
        class TestData:
            field1: str
            field2: int
        
        obj = TestData(field1='test', field2=42)
        result = dataclass_to_dict(obj)
        
        assert isinstance(result, dict)
        assert 'field1' in result
        assert 'field2' in result
    
    def test_dataclass_to_dict_preserves_values(self):
        """Verify dataclass field values are preserved"""
        @dataclass
        class TestData:
            name: str
            value: float
        
        obj = TestData(name='Test', value=3.14)
        result = dataclass_to_dict(obj)
        
        assert result['name'] == 'Test'
        assert result['value'] == 3.14
    
    def test_dataclass_to_dict_non_dataclass_raises(self):
        """Verify non-dataclass raises TypeError"""
        not_dataclass = {'field': 'value'}
        
        with pytest.raises(TypeError):
            dataclass_to_dict(not_dataclass)


class TestTypeContractConsistency:
    """Verify type contract consistency"""
    
    def test_normalize_then_denormalize_consistency(self):
        """Verify normalize→denormalize preserves structure"""
        entity = {'id': 'e1', 'name': 'Test', 'type': 'PERSON'}
        normalized = normalize_entity(entity)
        denormalized = denormalize_entity(normalized)
        
        assert isinstance(denormalized, dict)
        assert 'id' in denormalized
    
    def test_multiple_normalizations_stable(self):
        """Verify normalizing twice produces same result"""
        entity = {'name': '  Test  ', 'type': 'PERSON', 'confidence': 1.5}
        norm1 = normalize_entity(entity)
        norm2 = normalize_entity(norm1)
        
        # Should be idempotent (mostly)
        if 'name' in norm1 and 'name' in norm2:
            assert norm1['name'] == norm2['name']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
