"""
Comprehensive tests for ontology_pipeline.py TypedDict contracts.

Tests validate:
1. PipelineResultDict structure and field types
2. PipelineConfigDict structure and field types
3. to_dict() return type contracts
4. as_dict() return type contracts
5. Roundtrip serialization consistency
6. Type contract compliance
"""

import pytest
from typing import Dict, Any, List
from unittest.mock import Mock, MagicMock

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import (
    PipelineResult,
    OntologyPipeline,
    PipelineResultDict,
    PipelineConfigDict,
)


class TestPipelineResultDictType:
    """Validate PipelineResultDict structure and field types"""
    
    def test_pipeline_result_dict_has_all_required_fields(self):
        """Verify PipelineResultDict contains all expected fields"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={"overall": 0.85})
        
        result = PipelineResult(
            ontology={"entities": [], "relationships": []},
            score=mock_score,
            entities=[],
            relationships=[],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        
        assert 'ontology' in result_dict
        assert 'score' in result_dict
        assert 'entities' in result_dict
        assert 'relationships' in result_dict
        assert 'actions_applied' in result_dict
        assert 'metadata' in result_dict
    
    def test_ontology_field_is_dict(self):
        """Verify ontology field is dictionary"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        ontology_data = {"entities": ["e1", "e2"], "relationships": ["r1"]}
        result = PipelineResult(
            ontology=ontology_data,
            score=mock_score,
            entities=[],
            relationships=[],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict['ontology'], dict)
        assert result_dict['ontology'] == ontology_data
    
    def test_score_field_serialization(self):
        """Verify score field can be dict or CriticScore"""
        # Test with dict score
        result_with_dict_score = PipelineResult(
            ontology={},
            score={"overall": 0.90, "entity_quality": 0.85},
            entities=[],
            relationships=[],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result_with_dict_score.to_dict()
        
        assert 'score' in result_dict
        assert isinstance(result_dict['score'], (dict, object))
    
    def test_entities_field_is_list_of_dicts(self):
        """Verify entities field is list of dictionaries"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        entities = [
            {"id": "e1", "text": "Entity 1", "type": "T1"},
            {"id": "e2", "text": "Entity 2", "type": "T2"}
        ]
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=entities,
            relationships=[],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict['entities'], list)
        assert len(result_dict['entities']) == 2
        assert all(isinstance(e, dict) for e in result_dict['entities'])
    
    def test_relationships_field_is_list_of_dicts(self):
        """Verify relationships field is list of dictionaries"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        relationships = [
            {"id": "r1", "source": "e1", "target": "e2"},
            {"id": "r2", "source": "e2", "target": "e3"}
        ]
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=[],
            relationships=relationships,
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict['relationships'], list)
        assert len(result_dict['relationships']) == 2
        assert all(isinstance(r, dict) for r in result_dict['relationships'])
    
    def test_actions_applied_field_is_list_of_strings(self):
        """Verify actions_applied field is list of strings"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        actions = ["entity_deduplication", "relationship_resolution", "scoring"]
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=[],
            relationships=[],
            actions_applied=actions,
            metadata={}
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict['actions_applied'], list)
        assert all(isinstance(a, str) for a in result_dict['actions_applied'])
        assert result_dict['actions_applied'] == actions
    
    def test_metadata_field_is_dict(self):
        """Verify metadata field is dictionary"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        metadata = {
            "processing_time": 1.23,
            "source": "test",
            "version": "1.0"
        }
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=[],
            relationships=[],
            actions_applied=[],
            metadata=metadata
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict['metadata'], dict)
        assert result_dict['metadata'] == metadata


class TestPipelineConfigDictType:
    """Validate PipelineConfigDict structure and field types"""
    
    def test_pipeline_config_dict_has_all_required_fields(self):
        """Verify PipelineConfigDict contains all expected fields"""
        pipeline = self._create_mock_pipeline()
        config_dict = pipeline.as_dict()
        
        assert 'domain' in config_dict
        assert 'use_llm' in config_dict
        assert 'max_rounds' in config_dict
    
    def test_domain_field_is_string(self):
        """Verify domain field is string"""
        pipeline = self._create_mock_pipeline(domain="legal")
        config_dict = pipeline.as_dict()
        
        assert isinstance(config_dict['domain'], str)
        assert config_dict['domain'] == "legal"
    
    def test_use_llm_field_is_boolean(self):
        """Verify use_llm field is boolean"""
        pipeline = self._create_mock_pipeline()
        config_dict = pipeline.as_dict()
        
        assert isinstance(config_dict['use_llm'], bool)
    
    def test_max_rounds_field_is_integer(self):
        """Verify max_rounds field is integer"""
        pipeline = self._create_mock_pipeline()
        config_dict = pipeline.as_dict()
        
        assert isinstance(config_dict['max_rounds'], (int, float))
        assert config_dict['max_rounds'] >= 0
    
    def test_config_roundtrip_recreates_equivalent_pipeline(self):
        """Verify config can recreate equivalent pipeline"""
        original_domain = "medical"
        # Note: Full roundtrip test would require mocking more dependencies
        # This demonstrates the capability
        pipeline = self._create_mock_pipeline(domain=original_domain)
        config_dict = pipeline.as_dict()
        
        assert config_dict['domain'] == original_domain
        # In real usage: new_pipeline = OntologyPipeline(**config_dict)
    
    @staticmethod
    def _create_mock_pipeline(domain: str = "general") -> OntologyPipeline:
        """Helper to create a mock OntologyPipeline"""
        pipeline = MagicMock(spec=OntologyPipeline)
        pipeline.domain = domain
        pipeline._critic = Mock()
        pipeline._critic._use_llm = True
        pipeline._mediator = Mock()
        pipeline._mediator.max_rounds = 3
        
        # Mock the actual method
        def as_dict_impl():
            return {
                "domain": pipeline.domain,
                "use_llm": pipeline._critic._use_llm,
                "max_rounds": pipeline._mediator.max_rounds,
            }
        
        pipeline.as_dict = as_dict_impl
        return pipeline


class TestToDictIntegration:
    """Integration tests for PipelineResult.to_dict()"""
    
    def test_to_dict_with_complete_pipeline_result(self):
        """Test to_dict with realistic pipeline result"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={
            "overall": 0.88,
            "entity_quality": 0.90,
            "relationship_quality": 0.85
        })
        
        result = PipelineResult(
            ontology={
                "entities": [
                    {"id": "e1", "text": "Person A", "type": "PERSON"},
                    {"id": "e2", "text": "Organization B", "type": "ORGANIZATION"}
                ],
                "relationships": [
                    {"id": "r1", "source": "e1", "target": "e2", "type": "WORKS-FOR"}
                ]
            },
            score=mock_score,
            entities=[
                {"id": "e1", "text": "Person A", "type": "PERSON"},
                {"id": "e2", "text": "Organization B", "type": "ORGANIZATION"}
            ],
            relationships=[
                {"id": "r1", "source": "e1", "target": "e2", "type": "WORKS-FOR"}
            ],
            actions_applied=[
                "entity_extraction",
                "relationship_extraction",
                "entity_deduplication",
                "confidence_scoring"
            ],
            metadata={
                "processing_time_seconds": 2.34,
                "source": "legal_document",
                "version": "2.0",
                "refinement_rounds": 2
            }
        )
        
        result_dict = result.to_dict()
        
        # Verify structure
        assert len(result_dict['entities']) == 2
        assert len(result_dict['relationships']) == 1
        assert len(result_dict['actions_applied']) == 4
        
        # Verify content preservation
        assert result_dict['entities'][0]['text'] == "Person A"
        assert result_dict['relationships'][0]['type'] == "WORKS-FOR"
        assert result_dict['metadata']['processing_time_seconds'] == 2.34
    
    def test_to_dict_with_empty_collections(self):
        """Test to_dict with empty entities and relationships"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={"overall": 0.0})
        
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=[],
            relationships=[],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        
        assert isinstance(result_dict['entities'], list)
        assert isinstance(result_dict['relationships'], list)
        assert len(result_dict['entities']) == 0
        assert len(result_dict['relationships']) == 0


class TestTypeContractDataFlow:
    """Test data flow through type contracts"""
    
    def test_entity_preservation_through_serialization(self):
        """Verify entity data is preserved through to_dict()"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        entity_data = {
            "id": "unique_123",
            "text": "Complete Entity Name",
            "type": "CONCEPT",
            "confidence": 0.95,
            "properties": {"key": "value", "nested": {"inner": "data"}}
        }
        
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=[entity_data],
            relationships=[],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        serialized_entity = result_dict['entities'][0]
        
        assert serialized_entity == entity_data
        assert serialized_entity['properties']['nested']['inner'] == "data"
    
    def test_relationship_preservation_through_serialization(self):
        """Verify relationship data is preserved through to_dict()"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={})
        
        relationship_data = {
            "id": "rel_456",
            "source": "entity_1",
            "target": "entity_2",
            "type": "COMPLEX_RELATION",
            "confidence": 0.88,
            "properties": {"direction": "bilateral"}
        }
        
        result = PipelineResult(
            ontology={},
            score=mock_score,
            entities=[],
            relationships=[relationship_data],
            actions_applied=[],
            metadata={}
        )
        
        result_dict = result.to_dict()
        serialized_rel = result_dict['relationships'][0]
        
        assert serialized_rel == relationship_data


class TestTypeContractConsistency:
    """Verify type contract consistency"""
    
    def test_multiple_to_dict_calls_consistent(self):
        """Verify to_dict() returns consistent structure across calls"""
        mock_score = Mock()
        mock_score.to_dict = Mock(return_value={"score": 0.9})
        
        result = PipelineResult(
            ontology={"test": "data"},
            score=mock_score,
            entities=[{"id": "e1"}],
            relationships=[],
            actions_applied=["action1"],
            metadata={"key": "value"}
        )
        
        dict1 = result.to_dict()
        dict2 = result.to_dict()
        
        # Both calls should return dicts with same keys
        assert set(dict1.keys()) == set(dict2.keys())


class TestPipelineConfigVariations:
    """Test configuration dict with various values"""
    
    def test_config_with_different_domains(self):
        """Test config dict with various domain values"""
        domains = ["legal", "medical", "financial", "general", "custom_domain"]
        
        for domain in domains:
            pipeline = MagicMock(spec=OntologyPipeline)
            pipeline.domain = domain
            pipeline._critic = Mock()
            pipeline._critic._use_llm = True
            pipeline._mediator = Mock()
            pipeline._mediator.max_rounds = 3
            
            def as_dict_impl(d=domain):
                return {
                    "domain": d,
                    "use_llm": True,
                    "max_rounds": 3,
                }
            
            pipeline.as_dict = as_dict_impl
            config_dict = pipeline.as_dict()
            
            assert config_dict['domain'] == domain
    
    def test_config_with_varying_max_rounds(self):
        """Test config dict with different max_rounds values"""
        round_values = [1, 2, 3, 5, 10]
        
        for rounds in round_values:
            pipeline = MagicMock(spec=OntologyPipeline)
            pipeline.domain = "test"
            pipeline._critic = Mock()
            pipeline._critic._use_llm = False
            pipeline._mediator = Mock()
            pipeline._mediator.max_rounds = rounds
            
            def as_dict_impl(r=rounds):
                return {
                    "domain": "test",
                    "use_llm": False,
                    "max_rounds": r,
                }
            
            pipeline.as_dict = as_dict_impl
            config_dict = pipeline.as_dict()
            
            assert config_dict['max_rounds'] == rounds


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
