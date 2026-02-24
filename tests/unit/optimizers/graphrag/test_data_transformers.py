"""
Tests for ontology data transformation utilities.

This test suite covers:
- Entity and relationship normalization
- Extraction result transformation
- Deduplication and merging
- Transformation pipelines
- Batch transformations
- Error handling
"""

import pytest
from dataclasses import dataclass

from ipfs_datasets_py.optimizers.graphrag.data_transformers import (
    normalize_string,
    normalize_entity,
    normalize_relationship,
    normalize_extraction_result,
    filter_entities_by_confidence,
    filter_relationships_by_confidence,
    enrich_entity,
    merge_entities,
    deduplicaterelationships,
    TransformationError,
    TransformationPipeline,
    EntityTransformer,
    ExtractionResultTransformer,
    dict_to_dataclass,
    dataclass_to_dict,
    Transformation,
)


class TestNormalizeString:
    """Tests for string normalization."""
    
    def test_normalize_normal_string(self):
        """Test normalizing regular string."""
        result = normalize_string("hello world")
        assert result == "hello world"
    
    def test_normalize_extra_whitespace(self):
        """Test normalizing string with extra whitespace."""
        result = normalize_string("  hello   world  ")
        assert result == "hello world"
    
    def test_normalize_newlines_and_tabs(self):
        """Test normalizing string with newlines and tabs."""
        result = normalize_string("hello\n\tworld")
        assert result == "hello world"
    
    def test_normalize_none(self):
        """Test normalizing None."""
        result = normalize_string(None)
        assert result is None
    
    def test_normalize_empty_whitespace(self):
        """Test normalizing string with only whitespace."""
        result = normalize_string("   \n\t   ")
        assert result == ""


class TestNormalizeEntity:
    """Tests for entity normalization."""
    
    def test_normalize_minimal_entity(self):
        """Test normalizing minimal entity."""
        entity = {'id': 'e1', 'name': 'John', 'type': 'PERSON', 'confidence': 0.9}
        result = normalize_entity(entity)
        
        assert result['id'] == 'e1'
        assert result['name'] == 'John'
        assert result['type'] == 'person'  # Lowercased
        assert result['confidence'] == 0.9
    
    def test_normalize_whitespace_in_name(self):
        """Test normalizing whitespace in entity name."""
        entity = {'name': '  John  Smith  ', 'type': 'person', 'confidence': 0.8}
        result = normalize_entity(entity)
        
        assert result['name'] == 'John Smith'
    
    def test_normalize_confidence_above_1(self):
        """Test clamping confidence above 1.0."""
        entity = {'type': 'person', 'confidence': 1.5}
        result = normalize_entity(entity)
        
        assert result['confidence'] == 1.0
    
    def test_normalize_confidence_below_0(self):
        """Test clamping confidence below 0.0."""
        entity = {'type': 'person', 'confidence': -0.5}
        result = normalize_entity(entity)
        
        assert result['confidence'] == 0.0
    
    def test_normalize_removes_empty_properties(self):
        """Test removing empty properties."""
        entity = {
            'type': 'person',
            'properties': {'age': '25', 'empty': '', 'none': None}
        }
        result = normalize_entity(entity)
        
        assert result['properties']['age'] == '25'
        assert 'empty' not in result['properties']
        assert 'none' not in result['properties']
    
    def test_normalize_preserves_required_fields(self):
        """Test that normalization preserves required fields."""
        entity = {'id': 'e1', 'type': 'person', 'confidence': 0.8}
        result = normalize_entity(entity)
        
        assert 'id' in result
        assert 'type' in result
        assert 'confidence' in result


class TestNormalizeRelationship:
    """Tests for relationship normalization."""
    
    def test_normalize_minimal_relationship(self):
        """Test normalizing minimal relationship."""
        rel = {'source': 'e1', 'target': 'e2', 'type': 'WORKS_AT', 'confidence': 0.85}
        result = normalize_relationship(rel)
        
        assert result['source'] == 'e1'
        assert result['target'] == 'e2'
        assert result['type'] == 'works_at'  # Lowercased
        assert result['confidence'] == 0.85
    
    def test_normalize_self_relationship_error(self):
        """Test that self-relationships raise error."""
        rel = {'source': 'e1', 'target': 'e1', 'type': 'self_ref', 'confidence': 0.9}
        
        with pytest.raises(TransformationError) as exc_info:
            normalize_relationship(rel)
        
        assert 'self-relationship' in str(exc_info.value).lower()
    
    def test_normalize_clamps_confidence(self):
        """Test clamping relationship confidence."""
        rel = {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 2.0}
        result = normalize_relationship(rel)
        
        assert result['confidence'] == 1.0
    
    def test_normalize_type_confidence(self):
        """Test normalizing type_confidence field."""
        rel = {'source': 'e1', 'target': 'e2', 'type': 'rel', 'type_confidence': -0.5}
        result = normalize_relationship(rel)
        
        assert result['type_confidence'] == 0.0


class TestNormalizeExtractionResult:
    """Tests for extraction result normalization."""
    
    def test_normalize_result_with_entities(self):
        """Test normalizing result with entities."""
        result = {
            'entities': [
                {'name': '  John  ', 'type': 'PERSON', 'confidence': 0.9},
                {'name': 'Company', 'type': 'ORG', 'confidence': 1.5},
            ],
            'relationships': []
        }
        
        normalized = normalize_extraction_result(result)
        
        assert len(normalized['entities']) == 2
        assert normalized['entities'][0]['name'] == 'John'
        assert normalized['entities'][0]['type'] == 'person'
        assert normalized['entities'][1]['confidence'] == 1.0
    
    def test_normalize_result_with_relationships(self):
        """Test normalizing result with relationships."""
        result = {
            'entities': [],
            'relationships': [
                {'source': 'e1', 'target': 'e2', 'type': 'WORKS_AT', 'confidence': 0.9}
            ]
        }
        
        normalized = normalize_extraction_result(result)
        
        assert len(normalized['relationships']) == 1
        assert normalized['relationships'][0]['type'] == 'works_at'


class TestFilterByConfidence:
    """Tests for confidence filtering."""
    
    def test_filter_entities_above_threshold(self):
        """Test filtering entities by confidence threshold."""
        entities = [
            {'id': 'e1', 'confidence': 0.9},
            {'id': 'e2', 'confidence': 0.3},
            {'id': 'e3', 'confidence': 0.7},
        ]
        
        result = filter_entities_by_confidence(entities, threshold=0.5)
        
        assert len(result) == 2
        assert result[0]['id'] == 'e1'
        assert result[1]['id'] == 'e3'
    
    def test_filter_entities_missing_confidence(self):
        """Test that entities without confidence are filtered out."""
        entities = [
            {'id': 'e1', 'confidence': 0.9},
            {'id': 'e2'},  # No confidence
        ]
        
        result = filter_entities_by_confidence(entities, threshold=0.5)
        
        assert len(result) == 1
    
    def test_filter_relationships_above_threshold(self):
        """Test filtering relationships by confidence."""
        rels = [
            {'id': 'r1', 'confidence': 0.85},
            {'id': 'r2', 'confidence': 0.4},
        ]
        
        result = filter_relationships_by_confidence(rels, threshold=0.5)
        
        assert len(result) == 1
        assert result[0]['id'] == 'r1'


class TestEnrichEntity:
    """Tests for entity enrichment."""
    
    def test_enrich_adding_fields(self):
        """Test enriching entity with new fields."""
        entity = {'id': 'e1', 'name': 'John'}
        enriched = enrich_entity(entity, enriched_by='test', score=0.95)
        
        assert enriched['id'] == 'e1'
        assert enriched['name'] == 'John'
        assert enriched['enriched_by'] == 'test'
        assert enriched['score'] == 0.95
    
    def test_enrich_preserves_original(self):
        """Test that enrichment doesn't modify original."""
        entity = {'id': 'e1', 'name': 'John'}
        enriched = enrich_entity(entity, extra='data')
        
        assert 'extra' in enriched
        assert 'extra' not in entity


class TestMergeEntities:
    """Tests for entity merging."""
    
    def test_merge_entities_by_id(self):
        """Test merging entities with duplicate IDs."""
        entities = [
            {'id': 'e1', 'name': 'John', 'confidence': 0.8},
            {'id': 'e2', 'name': 'Jane', 'confidence': 0.9},
        ]
        
        merged = merge_entities(entities)
        
        assert len(merged) == 2
        assert 'e1' in merged
        assert 'e2' in merged
    
    def test_merge_keeps_highest_confidence(self):
        """Test that merge keeps highest confidence version."""
        entities = [
            {'id': 'e1', 'name': 'John', 'confidence': 0.7},
            {'id': 'e1', 'name': 'John Smith', 'confidence': 0.9},  # Duplicate
        ]
        
        merged = merge_entities(entities, merge_strategy='highest_confidence')
        
        assert len(merged) == 1
        assert merged['e1']['name'] == 'John Smith'
        assert merged['e1']['confidence'] == 0.9
    
    def test_merge_skips_missing_ids(self):
        """Test that merge skips entities without IDs."""
        entities = [
            {'id': 'e1', 'name': 'John'},
            {'name': 'Jane'},  # No ID
        ]
        
        merged = merge_entities(entities)
        
        assert len(merged) == 1


class TestDeduplicateRelationships:
    """Tests for relationship deduplication."""
    
    def test_deduplicate_same_relationship(self):
        """Test deduplicating same relationship types."""
        rels = [
            {'source': 'e1', 'target': 'e2', 'type': 'works_at', 'confidence': 0.8},
            {'source': 'e1', 'target': 'e2', 'type': 'works_at', 'confidence': 0.9},
        ]
        
        deduped = deduplicaterelationships(rels)
        
        assert len(deduped) == 1
        assert deduped[0]['confidence'] == 0.9  # Higher confidence
    
    def test_deduplicate_different_types(self):
        """Test that different relationship types aren't deduplicated."""
        rels = [
            {'source': 'e1', 'target': 'e2', 'type': 'works_at', 'confidence': 0.8},
            {'source': 'e1', 'target': 'e2', 'type': 'knows', 'confidence': 0.85},
        ]
        
        deduped = deduplicaterelationships(rels)
        
        assert len(deduped) == 2


class TestTransformationPipeline:
    """Tests for transformation pipelines."""
    
    def test_pipeline_single_step(self):
        """Test pipeline with single transformation."""
        pipeline = TransformationPipeline()
        pipeline.add_step(lambda x: x * 2)
        
        result = pipeline.transform(5)
        assert result == 10
    
    def test_pipeline_chained_steps(self):
        """Test pipeline with multiple steps."""
        pipeline = TransformationPipeline()
        pipeline.add_step(lambda x: x * 2)
        pipeline.add_step(lambda x: x + 10)
        pipeline.add_step(lambda x: x / 2)
        
        result = pipeline.transform(5)
        # (5 * 2 + 10) / 2 = 20 / 2 = 10
        assert result == 10
    
    def test_pipeline_batch_transform(self):
        """Test pipeline batch transformation."""
        pipeline = TransformationPipeline()
        pipeline.add_step(lambda x: x * 2)
        
        results = pipeline.transform_batch([1, 2, 3])
        assert results == [2, 4, 6]
    
    def test_pipeline_returns_self_for_chaining(self):
        """Test that add_step returns self for method chaining."""
        pipeline = TransformationPipeline()
        result = pipeline.add_step(lambda x: x)
        
        assert result is pipeline


class TestEntityTransformer:
    """Tests for entity transformer."""
    
    def test_entity_transformer_normalize(self):
        """Test entity transformer with normalization."""
        transformer = EntityTransformer(normalize=True)
        entity = {'name': '  John  ', 'type': 'PERSON', 'confidence': 1.5}
        
        result = transformer.transform(entity)
        
        assert result['name'] == 'John'
        assert result['type'] == 'person'
        assert result['confidence'] == 1.0
    
    def test_entity_transformer_no_normalize(self):
        """Test entity transformer without normalization."""
        transformer = EntityTransformer(normalize=False)
        entity = {'name': '  John  ', 'type': 'PERSON'}
        
        result = transformer.transform(entity)
        
        assert result['name'] == '  John  '  # Not normalized
        assert result['type'] == 'PERSON'  # Not lowercased


class TestExtractionResultTransformer:
    """Tests for extraction result transformer."""
    
    def test_transformer_normalize(self):
        """Test transformer with normalization."""
        result = {
            'entities': [
                {'id': 'e1', 'name': '  John  ', 'type': 'PERSON', 'confidence': 0.9}
            ],
            'relationships': []
        }
        
        transformer = ExtractionResultTransformer(normalize=True, deduplicate=False)
        transformed = transformer.transform(result)
        
        assert transformed['entities'][0]['name'] == 'John'
        assert transformed['entities'][0]['type'] == 'person'
    
    def test_transformer_filter_confidence(self):
        """Test transformer with confidence filtering."""
        result = {
            'entities': [
                {'id': 'e1', 'confidence': 0.9},
                {'id': 'e2', 'confidence': 0.3},
            ],
            'relationships': []
        }
        
        transformer = ExtractionResultTransformer(confidence_threshold=0.5)
        transformed = transformer.transform(result)
        
        assert len(transformed['entities']) == 1
        assert transformed['entities'][0]['id'] == 'e1'
    
    def test_transformer_deduplicate_relationships(self):
        """Test transformer with relationship deduplication."""
        result = {
            'entities': [],
            'relationships': [
                {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 0.8},
                {'source': 'e1', 'target': 'e2', 'type': 'rel', 'confidence': 0.9},
            ]
        }
        
        transformer = ExtractionResultTransformer(deduplicate=True)
        transformed = transformer.transform(result)
        
        assert len(transformed['relationships']) == 1
        assert transformed['relationships'][0]['confidence'] == 0.9


class TestDataclassConversion:
    """Tests for dataclass conversion utilities."""
    
    @dataclass
    class TestEntity:
        id: str
        name: str
        confidence: float = 0.5
    
    def test_dict_to_dataclass(self):
        """Test converting dict to dataclass."""
        data = {'id': 'e1', 'name': 'John', 'confidence': 0.9}
        
        obj = dict_to_dataclass(data, self.TestEntity)
        
        assert obj.id == 'e1'
        assert obj.name == 'John'
        assert obj.confidence == 0.9
    
    def test_dict_to_dataclass_partial(self):
        """Test converting dict with partial fields."""
        data = {'id': 'e1', 'name': 'John'}
        
        obj = dict_to_dataclass(data, self.TestEntity)
        
        assert obj.id == 'e1'
        assert obj.name == 'John'
        assert obj.confidence == 0.5  # Default value
    
    def test_dataclass_to_dict(self):
        """Test converting dataclass to dict."""
        obj = self.TestEntity(id='e1', name='John', confidence=0.95)
        
        data = dataclass_to_dict(obj)
        
        assert data['id'] == 'e1'
        assert data['name'] == 'John'
        assert data['confidence'] == 0.95
    
    def test_dict_to_dataclass_invalid_type(self):
        """Test error when converting non-dataclass."""
        with pytest.raises(TypeError):
            dict_to_dataclass({}, str)
    
    def test_dataclass_to_dict_invalid_type(self):
        """Test error when converting non-dataclass instance."""
        with pytest.raises(TypeError):
            dataclass_to_dict("not a dataclass")


class TestTransformationBatchErrors:
    """Tests for batch transformation error handling."""
    
    def test_batch_transform_skip_errors(self):
        """Test batch transformation skipping errors."""
        def failing_transform(x):
            if x < 0:
                raise ValueError("Negative value")
            return x * 2
        
        transformer = EntityTransformer()
        # Manually create a batch transform that handles errors
        items = [1, -1, 2]
        results = []
        
        for item in items:
            try:
                results.append(failing_transform(item))
            except:
                pass  # Skip errors
        
        assert len(results) == 2
        assert results == [2, 4]

    class _IntTransformer(Transformation[int, int]):
        def transform(self, data: int) -> int:
            if data < 0:
                raise ValueError("Negative value")
            return data * 2

    def test_transform_base_batch_skip_errors_true(self):
        """Transformation.transform_batch should skip typed errors when requested."""
        transformer = self._IntTransformer()

        result = transformer.transform_batch([1, -1, 2], skip_errors=True)

        assert result == [2, 4]

    def test_transform_base_batch_skip_errors_false_raises(self):
        """Transformation.transform_batch should wrap and raise when skip_errors=False."""
        transformer = self._IntTransformer()

        with pytest.raises(TransformationError, match="Transformation failed at item 1"):
            transformer.transform_batch([1, -1, 2], skip_errors=False)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
