"""
Tests for response validators and type checkers.

This test suite provides comprehensive coverage of validation utilities for:
- Entity extraction results
- Relationship extraction results
- Critic scores
- Ontology session data
- Query execution plans
- Batch validation operations
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.response_validators import (
    EntityExtractionValidator,
    RelationshipExtractionValidator,
    CriticScoreValidator,
    OntologySessionValidator,
    QueryPlanValidator,
    ValidationResult,
    ResponseValidator,
    validate_batch,
    ValidationSeverity,
)


class TestEntityExtractionValidator:
    """Tests for entity extraction validator."""
    
    def test_valid_entity_minimal(self):
        """Test validation of minimal valid entity."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 'e1',
            'name': 'John Smith',
            'type': 'Person',
            'confidence': 0.95,
        }
        result = validator.validate(entity)
        assert result.is_valid
        assert result.data == entity
        assert len(result.errors) == 0
    
    def test_valid_entity_complete(self):
        """Test validation of complete entity with all fields."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 'e1',
            'name': 'John Smith',
            'type': 'Person',
            'confidence': 0.95,
            'properties': {'age': '45', 'role': 'CEO'},
            'metadata': {'source': 'document_1'},
        }
        result = validator.validate(entity)
        assert result.is_valid
        assert result.data == entity
    
    def test_missing_required_field(self):
        """Test validation fails with missing required field."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 'e1',
            'name': 'John Smith',
            # missing 'type' and 'confidence'
        }
        result = validator.validate(entity)
        assert not result.is_valid
        assert any('type' in err for err in result.errors)
        assert any('confidence' in err for err in result.errors)
    
    def test_invalid_confidence_above_range(self):
        """Test validation fails when confidence is above 1.0."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': 1.5,  # Invalid
        }
        result = validator.validate(entity)
        assert not result.is_valid
        assert any('above maximum' in err for err in result.errors)
    
    def test_invalid_confidence_below_range(self):
        """Test validation fails when confidence is below 0.0."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': -0.1,  # Invalid
        }
        result = validator.validate(entity)
        assert not result.is_valid
        assert any('below minimum' in err for err in result.errors)
    
    def test_invalid_type_not_dict(self):
        """Test validation fails when entity is not a dict."""
        validator = EntityExtractionValidator()
        result = validator.validate("not a dict")
        assert not result.is_valid
        assert any('must be a dictionary' in err for err in result.errors)
    
    def test_invalid_field_type(self):
        """Test validation fails with wrong field type."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 123,  # Should be string
            'name': 'John',
            'type': 'Person',
            'confidence': 0.9,
        }
        result = validator.validate(entity)
        assert not result.is_valid
        assert any('type' in err.lower() for err in result.errors)
    
    def test_null_name_allowed(self):
        """Test that null name is allowed."""
        validator = EntityExtractionValidator()
        entity = {
            'id': 'e1',
            'name': None,
            'type': 'Person',
            'confidence': 0.9,
        }
        result = validator.validate(entity)
        assert result.is_valid


class TestRelationshipExtractionValidator:
    """Tests for relationship extraction validator."""
    
    def test_valid_relationship_minimal(self):
        """Test validation of minimal valid relationship."""
        validator = RelationshipExtractionValidator()
        rel = {
            'source': 'e1',
            'target': 'e2',
            'type': 'works_at',
        }
        result = validator.validate(rel)
        assert result.is_valid
        assert result.data == rel
    
    def test_valid_relationship_complete(self):
        """Test validation of complete relationship."""
        validator = RelationshipExtractionValidator()
        rel = {
            'id': 'r1',
            'source': 'e1',
            'target': 'e2',
            'type': 'works_at',
            'confidence': 0.92,
            'type_confidence': 0.88,
            'properties': {'since': '2020'},
            'metadata': {'distance': 3},
        }
        result = validator.validate(rel)
        assert result.is_valid
        assert result.data == rel
    
    def test_missing_required_field(self):
        """Test validation fails with missing required field."""
        validator = RelationshipExtractionValidator()
        rel = {
            'source': 'e1',
            # missing 'target' and 'type'
        }
        result = validator.validate(rel)
        assert not result.is_valid
        assert any('target' in err for err in result.errors)
    
    def test_invalid_confidence_outside_range(self):
        """Test validation fails with confidence outside [0, 1]."""
        validator = RelationshipExtractionValidator()
        rel = {
            'source': 'e1',
            'target': 'e2',
            'type': 'rel',
            'confidence': 1.5,
        }
        result = validator.validate(rel)
        assert not result.is_valid
    
    def test_self_relationship_warning(self):
        """Test that self-relationships generate warning."""
        validator = RelationshipExtractionValidator()
        rel = {
            'source': 'e1',
            'target': 'e1',  # Same as source
            'type': 'self_ref',
        }
        result = validator.validate(rel)
        assert result.is_valid
        assert len(result.warnings) > 0
        assert any('self' in w.lower() for w in result.warnings)
    
    def test_invalid_type_not_dict(self):
        """Test validation fails when not a dict."""
        validator = RelationshipExtractionValidator()
        result = validator.validate([])
        assert not result.is_valid


class TestCriticScoreValidator:
    """Tests for critic score validator."""
    
    def test_valid_score_0_100_scale(self):
        """Test validation of valid score on 0-100 scale."""
        validator = CriticScoreValidator()
        score = {
            'overall': 85.5,
            'completeness': 0.80,
            'consistency': 0.90,
            'clarity': 0.85,
            'granularity': 0.75,
            'domain_alignment': 0.88,
        }
        result = validator.validate(score)
        assert result.is_valid
        assert result.data == score
    
    def test_valid_score_0_1_scale(self):
        """Test validation of valid score on 0-1 scale."""
        validator = CriticScoreValidator()
        score = {
            'overall': 85.0,
            'completeness': 0.8,
            'consistency': 0.9,
            'clarity': 0.85,
            'granularity': 0.75,
            'domain_alignment': 0.88,
        }
        result = validator.validate(score)
        assert result.is_valid
    
    def test_score_with_recommendations(self):
        """Test score validation with recommendations."""
        validator = CriticScoreValidator()
        score = {
            'overall': 75.0,
            'completeness': 0.7,
            'consistency': 0.8,
            'clarity': 0.75,
            'granularity': 0.65,
            'domain_alignment': 0.72,
            'recommendations': ['Add more entities', 'Improve clarity'],
        }
        result = validator.validate(score)
        assert result.is_valid
    
    def test_invalid_recommendation_not_string(self):
        """Test validation fails when recommendation is not string."""
        validator = CriticScoreValidator()
        score = {
            'overall': 75.0,
            'completeness': 0.7,
            'consistency': 0.8,
            'clarity': 0.75,
            'granularity': 0.65,
            'domain_alignment': 0.72,
            'recommendations': [123],  # Invalid
        }
        result = validator.validate(score)
        assert not result.is_valid
    
    def test_overall_score_above_100(self):
        """Test validation fails when overall > 100."""
        validator = CriticScoreValidator()
        score = {
            'overall': 105.0,  # Invalid
            'completeness': 0.9,
            'consistency': 0.9,
            'clarity': 0.9,
            'granularity': 0.9,
            'domain_alignment': 0.9,
        }
        result = validator.validate(score)
        assert not result.is_valid
    
    def test_strict_mode_missing_dimension(self):
        """Test strict mode requires all dimensions."""
        validator = CriticScoreValidator(strict=True)
        score = {
            'overall': 80.0,
            'completeness': 0.8,
            # missing other dimensions
        }
        result = validator.validate(score)
        assert not result.is_valid


class TestOntologySessionValidator:
    """Tests for ontology session validator."""
    
    def test_valid_session_minimal(self):
        """Test validation of minimal valid session."""
        validator = OntologySessionValidator()
        session = {
            'session_id': 'sess-001',
            'domain': 'legal',
            'status': 'completed',
        }
        result = validator.validate(session)
        assert result.is_valid
    
    def test_valid_session_complete(self):
        """Test validation of complete session."""
        validator = OntologySessionValidator()
        session = {
            'session_id': 'sess-001',
            'domain': 'medical',
            'data_source': 'medical_records.txt',
            'status': 'completed',
            'duration_ms': 5000.5,
            'iterations': 10,
            'initial_score': 65.0,
            'final_score': 85.0,
            'improvement_score': 20.0,
        }
        result = validator.validate(session)
        assert result.is_valid
    
    def test_invalid_status(self):
        """Test validation fails with invalid status."""
        validator = OntologySessionValidator()
        session = {
            'session_id': 'sess-001',
            'domain': 'legal',
            'status': 'invalid_status',  # Invalid
        }
        result = validator.validate(session)
        assert not result.is_valid
        assert any('status' in err.lower() for err in result.errors)
    
    def test_valid_statuses(self):
        """Test all valid status values."""
        validator = OntologySessionValidator()
        valid_statuses = ['pending', 'running', 'completed', 'failed', 'cancelled']
        
        for status in valid_statuses:
            session = {
                'session_id': 'sess-001',
                'domain': 'legal',
                'status': status,
            }
            result = validator.validate(session)
            assert result.is_valid, f"Status '{status}' should be valid"
    
    def test_invalid_numeric_field_negative(self):
        """Test validation fails with negative numeric field."""
        validator = OntologySessionValidator()
        session = {
            'session_id': 'sess-001',
            'domain': 'legal',
            'status': 'completed',
            'duration_ms': -100,  # Invalid
        }
        result = validator.validate(session)
        assert not result.is_valid
    
    def test_score_outside_0_100_range(self):
        """Test validation fails when score outside [0, 100]."""
        validator = OntologySessionValidator()
        session = {
            'session_id': 'sess-001',
            'domain': 'legal',
            'status': 'completed',
            'final_score': 105.0,  # Invalid
        }
        result = validator.validate(session)
        assert not result.is_valid


class TestQueryPlanValidator:
    """Tests for query plan validator."""
    
    def test_valid_plan_minimal(self):
        """Test validation of minimal valid query plan."""
        validator = QueryPlanValidator()
        plan = {
            'query_id': 'q1',
            'query_text': 'Find all persons named John',
            'plan_type': 'vector',
            'steps': [
                {'operation': 'embed', 'query': 'persons named John'},
                {'operation': 'search', 'index': 'entities'},
            ],
        }
        result = validator.validate(plan)
        assert result.is_valid
    
    def test_valid_plan_types(self):
        """Test all valid plan types."""
        validator = QueryPlanValidator()
        valid_types = ['vector', 'direct', 'traversal', 'hybrid', 'keyword', 'semantic']
        
        for plan_type in valid_types:
            plan = {
                'query_id': 'q1',
                'query_text': 'test',
                'plan_type': plan_type,
                'steps': [{'op': 'test'}],
            }
            result = validator.validate(plan)
            assert result.is_valid, f"Plan type '{plan_type}' should be valid"
    
    def test_invalid_plan_type(self):
        """Test validation fails with invalid plan type."""
        validator = QueryPlanValidator()
        plan = {
            'query_id': 'q1',
            'query_text': 'test',
            'plan_type': 'invalid_type',  # Invalid
            'steps': [],
        }
        result = validator.validate(plan)
        assert not result.is_valid
        assert any('plan_type' in err.lower() for err in result.errors)
    
    def test_steps_must_be_list(self):
        """Test validation fails when steps is not list."""
        validator = QueryPlanValidator()
        plan = {
            'query_id': 'q1',
            'query_text': 'test',
            'plan_type': 'vector',
            'steps': 'not a list',  # Invalid
        }
        result = validator.validate(plan)
        assert not result.is_valid
    
    def test_negative_estimated_cost(self):
        """Test validation fails with negative estimated cost."""
        validator = QueryPlanValidator()
        plan = {
            'query_id': 'q1',
            'query_text': 'test',
            'plan_type': 'vector',
            'steps': [],
            'estimated_cost': -10.0,  # Invalid
        }
        result = validator.validate(plan)
        assert not result.is_valid


class TestBatchValidation:
    """Tests for batch validation utilities."""
    
    def test_validate_batch_all_valid(self):
        """Test batch validation with all valid items."""
        validator = EntityExtractionValidator()
        entities = [
            {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
            {'id': 'e2', 'name': 'Jane', 'type': 'Person', 'confidence': 0.85},
        ]
        valid_items, results = validate_batch(entities, validator)
        
        assert len(valid_items) == 2
        assert len(results) == 2
        assert all(r.is_valid for r in results)
    
    def test_validate_batch_mixed_validity(self):
        """Test batch validation with mix of valid and invalid items."""
        validator = EntityExtractionValidator()
        entities = [
            {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
            {'id': 'e2', 'name': 'Jane', 'type': 'Person', 'confidence': 1.5},  # Invalid
            {'id': 'e3', 'name': 'Bob', 'type': 'Person', 'confidence': 0.75},
        ]
        valid_items, results = validate_batch(entities, validator)
        
        assert len(valid_items) == 2
        assert len(results) == 3
        assert results[0].is_valid
        assert not results[1].is_valid
        assert results[2].is_valid
    
    def test_validate_batch_empty(self):
        """Test batch validation with empty batch."""
        validator = EntityExtractionValidator()
        valid_items, results = validate_batch([], validator)
        
        assert len(valid_items) == 0
        assert len(results) == 0


class TestValidationResult:
    """Tests for ValidationResult data class."""
    
    def test_add_error(self):
        """Test adding error to result."""
        result = ValidationResult(is_valid=True)
        result.add_error("Test error", field='test_field', code='test_code')
        
        assert not result.is_valid
        assert len(result.errors) == 1
        assert 'Test error' in result.errors[0]
        assert len(result.detailed_errors) == 1
        assert result.detailed_errors[0]['field'] == 'test_field'
    
    def test_add_warning(self):
        """Test adding warning to result."""
        result = ValidationResult(is_valid=True)
        result.add_warning("Test warning", field='test_field')
        
        assert result.is_valid  # Warning doesn't change is_valid
        assert len(result.warnings) == 1
        assert 'Test warning' in result.warnings[0]
    
    def test_multiple_errors(self):
        """Test adding multiple errors."""
        result = ValidationResult(is_valid=True)
        result.add_error("Error 1", field='field1')
        result.add_error("Error 2", field='field2')
        
        assert not result.is_valid
        assert len(result.errors) == 2
        assert len(result.detailed_errors) == 2


class TestDetailedErrorReporting:
    """Tests for detailed error reporting capabilities."""
    
    def test_detailed_errors_enabled(self):
        """Test detailed error reporting when enabled."""
        validator = EntityExtractionValidator(detailed_errors=True)
        entity = {
            'id': 123,  # Invalid type
            'name': 'John',
            'type': 'Person',
            'confidence': 1.5,  # Invalid range
        }
        result = validator.validate(entity)
        
        assert not result.is_valid
        assert len(result.detailed_errors) >= 2
        assert any(e['field'] == 'id' for e in result.detailed_errors)
        assert any(e['field'] == 'confidence' for e in result.detailed_errors)
    
    def test_error_codes_included(self):
        """Test that error codes are included in detailed errors."""
        validator = EntityExtractionValidator(detailed_errors=True)
        entity = {'id': 'e1', 'name': 'John'}  # Missing type and confidence
        result = validator.validate(entity)
        
        assert not result.is_valid
        assert len(result.detailed_errors) > 0
        assert any(e.get('code') == 'missing_field' for e in result.detailed_errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
