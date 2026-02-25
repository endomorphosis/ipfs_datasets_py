"""
Batch 259: ResponseValidators - Comprehensive validation testing.

Target: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/response_validators.py (537 LOC)

Tests for response validation, error handling, batch validation, and schema conformance.
"""

import pytest
import math
from typing import Any, Dict, List
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.graphrag.response_validators import (
    ResponseValidator,
    EntityExtractionValidator,
    RelationshipExtractionValidator,
    CriticScoreValidator,
    OntologySessionValidator,
    QueryPlanValidator,
    ValidationResult,
    ValidationSeverity,
    ValidationErrorDetail,
    validate_batch,
)


# ============================================================================
# Test ValidationResult and Data Structures
# ============================================================================

class TestValidationResult:
    """Tests for ValidationResult dataclass."""
    
    def test_initialization_default_success(self):
        """ValidationResult initializes with default success state."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.data is None
        assert result.errors == []
        assert result.warnings == []
        assert result.detailed_errors == []
    
    def test_initialization_with_data(self):
        """ValidationResult can store validated data."""
        data = {'id': 'test', 'value': 42}
        result = ValidationResult(is_valid=True, data=data)
        assert result.data == data
        assert result.is_valid is True
    
    def test_add_error_updates_validity(self):
        """add_error() marks result as invalid."""
        result = ValidationResult(is_valid=True)
        result.add_error("Field missing", field='name', code='missing')
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "Field missing" in result.errors[0]
    
    def test_add_error_with_details(self):
        """add_error() captures detailed error information."""
        result = ValidationResult(is_valid=True)
        result.add_error("Invalid type", field='age', code='type_mismatch')
        assert len(result.detailed_errors) == 1
        detail = result.detailed_errors[0]
        assert detail['field'] == 'age'
        assert detail['code'] == 'type_mismatch'
        assert detail['severity'] == ValidationSeverity.ERROR.value
    
    def test_add_warning_preserves_validity(self):
        """add_warning() adds warning without invalidating result."""
        result = ValidationResult(is_valid=True)
        result.add_warning("Unusual value", field='confidence')
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert len(result.detailed_errors) == 1
        assert result.detailed_errors[0]['severity'] == ValidationSeverity.WARNING.value
    
    def test_multiple_errors_accumulation(self):
        """Multiple add_error() calls accumulate."""
        result = ValidationResult(is_valid=True)
        result.add_error("Error 1", field='field1')
        result.add_error("Error 2", field='field2')
        result.add_error("Error 3", field='field3')
        assert len(result.errors) == 3
        assert len(result.detailed_errors) == 3
        assert result.is_valid is False


class TestValidationSeverity:
    """Tests for ValidationSeverity enum."""
    
    def test_severity_values(self):
        """ValidationSeverity has expected enum values."""
        assert ValidationSeverity.ERROR.value == "error"
        assert ValidationSeverity.WARNING.value == "warning"
        assert ValidationSeverity.INFO.value == "info"


# ============================================================================
# Test Entity Extraction Validator
# ============================================================================

class TestEntityExtractionValidator:
    """Tests for EntityExtractionValidator."""
    
    def test_valid_minimal_entity(self):
        """Valid minimal entity passes validation."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John Smith',
            'type': 'Person',
            'confidence': 0.95
        }
        result = validator.validate(data)
        assert result.is_valid is True
        assert result.data == data
        assert len(result.errors) == 0
    
    def test_valid_full_entity(self):
        """Valid full entity with all fields passes."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'ACME Corp',
            'type': 'Organization',
            'confidence': 0.88,
            'properties': {'industry': 'Tech', 'revenue': '$1B'},
            'metadata': {'source': 'wikipedia', 'page_id': 123}
        }
        result = validator.validate(data)
        assert result.is_valid is True
        assert result.data == data
    
    def test_invalid_not_dict(self):
        """Non-dict entity fails validation."""
        validator = EntityExtractionValidator()
        result = validator.validate("not a dict")
        assert result.is_valid is False
        assert "dictionary" in result.errors[0].lower()
    
    def test_missing_required_id(self):
        """Entity without id fails."""
        validator = EntityExtractionValidator()
        data = {
            'name': 'John',
            'type': 'Person',
            'confidence': 0.9
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('id' in err for err in result.errors)
    
    def test_missing_required_name(self):
        """Entity without name fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'type': 'Person',
            'confidence': 0.9
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('name' in err for err in result.errors)
    
    def test_missing_required_type(self):
        """Entity without type fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John',
            'confidence': 0.9
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('type' in err for err in result.errors)
    
    def test_missing_required_confidence(self):
        """Entity without confidence fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person'
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('confidence' in err for err in result.errors)
    
    def test_invalid_confidence_type(self):
        """Confidence with wrong type fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': "0.95"  # string instead of float
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_confidence_out_of_range_too_high(self):
        """Confidence > 1.0 fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': 1.5
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('above' in err.lower() or 'maximum' in err.lower() for err in result.errors)
    
    def test_confidence_out_of_range_negative(self):
        """Confidence < 0.0 fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': -0.1
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('below' in err.lower() or 'minimum' in err.lower() for err in result.errors)
    
    def test_null_name_allowed(self):
        """Null name is allowed (name field is Optional)."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': None,
            'type': 'Person',
            'confidence': 0.5
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_invalid_properties_type(self):
        """Non-dict properties fails."""
        validator = EntityExtractionValidator()
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': 0.9,
            'properties': "not a dict"
        }
        result = validator.validate(data)
        assert result.is_valid is False


class TestEntityExtractionValidatorWithOptions:
    """Tests for EntityExtractionValidator options."""
    
    def test_allow_extra_fields_default_true(self):
        """Extra fields are allowed by default."""
        validator = EntityExtractionValidator(allow_extra_fields=True)
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': 0.9,
            'extra_field': 'unexpected',
            'another_extra': 123
        }
        result = validator.validate(data)
        # Valid because allow_extra_fields=True (warnings allowed)
        assert len(result.errors) == 0
    
    def test_disallow_extra_fields(self):
        """Extra fields can be disallowed."""
        validator = EntityExtractionValidator(allow_extra_fields=False)
        data = {
            'id': 'e1',
            'name': 'John',
            'type': 'Person',
            'confidence': 0.9,
            'extra_field': 'unexpected'
        }
        result = validator.validate(data)
        # Warnings generated, but is_valid still True
        assert len(result.warnings) > 0
        assert 'Unknown fields' in result.warnings[0] or 'extra_field' in result.warnings[0]


# ============================================================================
# Test Relationship Extraction Validator
# ============================================================================

class TestRelationshipExtractionValidator:
    """Tests for RelationshipExtractionValidator."""
    
    def test_valid_minimal_relationship(self):
        """Valid minimal relationship passes."""
        validator = RelationshipExtractionValidator()
        data = {
            'source': 'e1',
            'target': 'e2',
            'type': 'works_for'
        }
        result = validator.validate(data)
        assert result.is_valid is True
        assert result.data == data
    
    def test_valid_full_relationship(self):
        """Valid full relationship with all fields passes."""
        validator = RelationshipExtractionValidator()
        data = {
            'id': 'r1',
            'source': 'e1',
            'target': 'e2',
            'type': 'KNOWS',
            'confidence': 0.92,
            'type_confidence': 0.88,
            'properties': {'since': '2020'},
            'metadata': {'source': 'document'}
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_invalid_not_dict(self):
        """Non-dict relationship fails."""
        validator = RelationshipExtractionValidator()
        result = validator.validate([1, 2, 3])
        assert result.is_valid is False
    
    def test_missing_required_source(self):
        """Relationship without source fails."""
        validator = RelationshipExtractionValidator()
        data = {'target': 'e2', 'type': 'knows'}
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('source' in err for err in result.errors)
    
    def test_missing_required_target(self):
        """Relationship without target fails."""
        validator = RelationshipExtractionValidator()
        data = {'source': 'e1', 'type': 'knows'}
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('target' in err for err in result.errors)
    
    def test_missing_required_type(self):
        """Relationship without type fails."""
        validator = RelationshipExtractionValidator()
        data = {'source': 'e1', 'target': 'e2'}
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('type' in err for err in result.errors)
    
    def test_self_relationship_warning(self):
        """Self-relationships generate warning."""
        validator = RelationshipExtractionValidator()
        data = {
            'source': 'e1',
            'target': 'e1',  # same as source
            'type': 'self_ref'
        }
        result = validator.validate(data)
        # Valid but with warning
        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert 'Self-relationship' in result.warnings[0] or 'identical' in result.warnings[0]
    
    def test_confidence_validation(self):
        """Relationship confidence is validated like entity."""
        validator = RelationshipExtractionValidator()
        data = {
            'source': 'e1',
            'target': 'e2',
            'type': 'knows',
            'confidence': 1.5  # invalid
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_type_confidence_validation(self):
        """Relationship type_confidence is validated."""
        validator = RelationshipExtractionValidator()
        data = {
            'source': 'e1',
            'target': 'e2',
            'type': 'knows',
            'type_confidence': -0.1  # invalid
        }
        result = validator.validate(data)
        assert result.is_valid is False


# ============================================================================
# Test Critic Score Validator
# ============================================================================

class TestCriticScoreValidator:
    """Tests for CriticScoreValidator."""
    
    def test_valid_minimal_score(self):
        """Valid minimal critic score passes."""
        validator = CriticScoreValidator()
        data = {
            'overall': 75.5,
            'completeness': 0.8,
            'consistency': 0.85,
            'clarity': 0.9,
            'granularity': 0.75,
            'domain_alignment': 0.7
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_valid_full_score(self):
        """Valid full critic score with all fields."""
        validator = CriticScoreValidator()
        data = {
            'overall': 85.0,
            'completeness': 0.9,
            'consistency': 0.88,
            'clarity': 0.92,
            'granularity': 0.85,
            'domain_alignment': 0.8,
            'recommendations': ['Improve entity coverage', 'Add more relationships'],
            'dimensions': {'extra': 'metadata'}
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_invalid_not_dict(self):
        """Non-dict score fails."""
        validator = CriticScoreValidator()
        result = validator.validate(42)
        assert result.is_valid is False
    
    def test_invalid_overall_range_too_high(self):
        """Overall > 100 fails."""
        validator = CriticScoreValidator()
        data = {
            'overall': 125.0,
            'completeness': 0.8,
            'consistency': 0.8,
            'clarity': 0.8,
            'granularity': 0.8,
            'domain_alignment': 0.8
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_invalid_overall_negative(self):
        """Overall < 0 fails."""
        validator = CriticScoreValidator()
        data = {
            'overall': -10.0,
            'completeness': 0.8,
            'consistency': 0.8,
            'clarity': 0.8,
            'granularity': 0.8,
            'domain_alignment': 0.8
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_dimension_out_of_range_warning(self):
        """Dimension outside [0,1] or [0,100] generates warning in non-strict."""
        validator = CriticScoreValidator(strict=False)
        data = {
            'overall': 75.0,
            'completeness': 0.8,
            'consistency': 0.8,
            'clarity': 150.0,  # out of typical range
            'granularity': 0.8,
            'domain_alignment': 0.8
        }
        result = validator.validate(data)
        # Should generate warning
        assert len(result.warnings) > 0
    
    def test_strict_mode_missing_dimension(self):
        """Strict mode requires all dimensions."""
        validator = CriticScoreValidator(strict=True)
        data = {
            'overall': 75.0,
            'completeness': 0.8,
            'consistency': 0.8,
            # missing clarity, granularity, domain_alignment
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert len(result.errors) > 0
    
    def test_non_strict_mode_missing_dimension(self):
        """Non-strict mode allows missing dimensions."""
        validator = CriticScoreValidator(strict=False)
        data = {
            'overall': 75.0,
            'completeness': 0.8,
            'consistency': 0.8,
        }
        result = validator.validate(data)
        # Should be valid with warnings
        assert len(result.errors) == 0


class TestCriticScoreValidatorRecommendations:
    """Tests for CriticScoreValidator recommendations field."""
    
    def test_valid_recommendations_list(self):
        """Valid recommendations list passes."""
        validator = CriticScoreValidator()
        data = {
            'overall': 75.0,
            'completeness': 0.8,
            'consistency': 0.8,
            'clarity': 0.8,
            'granularity': 0.8,
            'domain_alignment': 0.8,
            'recommendations': ['Improve entity coverage', 'Better documentation']
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_invalid_recommendations_type(self):
        """Non-list recommendations fails."""
        validator = CriticScoreValidator()
        data = {
            'overall': 75.0,
            'completeness': 0.8,
            'consistency': 0.8,
            'clarity': 0.8,
            'granularity': 0.8,
            'domain_alignment': 0.8,
            'recommendations': 'Not a list'
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_invalid_recommendation_item(self):
        """Non-string recommendation items fail."""
        validator = CriticScoreValidator()
        data = {
            'overall': 75.0,
            'completeness': 0.8,
            'consistency': 0.8,
            'clarity': 0.8,
            'granularity': 0.8,
            'domain_alignment': 0.8,
            'recommendations': ['Valid', 123, 'Another']  # 123 is not string
        }
        result = validator.validate(data)
        assert result.is_valid is False


# ============================================================================
# Test Ontology Session Validator
# ============================================================================

class TestOntologySessionValidator:
    """Tests for OntologySessionValidator."""
    
    def test_valid_minimal_session(self):
        """Valid minimal session passes."""
        validator = OntologySessionValidator()
        data = {
            'session_id': 'sess_123',
            'domain': 'legal',
            'status': 'completed'
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_valid_full_session(self):
        """Valid full session with all fields."""
        validator = OntologySessionValidator()
        data = {
            'session_id': 'sess_123',
            'domain': 'medical',
            'status': 'running',
            'duration_ms': 5000,
            'iterations': 3,
            'initial_score': 45.0,
            'final_score': 78.5,
            'improvement_score': 33.5
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_invalid_not_dict(self):
        """Non-dict session fails."""
        validator = OntologySessionValidator()
        result = validator.validate("session_123")
        assert result.is_valid is False
    
    def test_missing_required_session_id(self):
        """Session without session_id fails."""
        validator = OntologySessionValidator()
        data = {
            'domain': 'legal',
            'status': 'completed'
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_invalid_status(self):
        """Invalid status value fails."""
        validator = OntologySessionValidator()
        data = {
            'session_id': 'sess_123',
            'domain': 'legal',
            'status': 'unknown_status'
        }
        result = validator.validate(data)
        assert result.is_valid is False
        assert any('status' in err.lower() for err in result.errors)
    
    def test_valid_statuses(self):
        """All valid statuses accepted."""
        valid_statuses = ['pending', 'running', 'completed', 'failed', 'cancelled']
        validator = OntologySessionValidator()
        for status in valid_statuses:
            data = {
                'session_id': 'sess_123',
                'domain': 'legal',
                'status': status
            }
            result = validator.validate(data)
            assert result.is_valid is True, f"Status {status} should be valid"
    
    def test_duration_ms_validation(self):
        """duration_ms must be non-negative."""
        validator = OntologySessionValidator()
        data = {
            'session_id': 'sess_123',
            'domain': 'legal',
            'status': 'completed',
            'duration_ms': -1000
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_score_fields_range(self):
        """Score fields must be in 0-100 range."""
        validator = OntologySessionValidator()
        data = {
            'session_id': 'sess_123',
            'domain': 'legal',
            'status': 'completed',
            'initial_score': 150.0  # > 100
        }
        result = validator.validate(data)
        assert result.is_valid is False


# ============================================================================
# Test Query Plan Validator
# ============================================================================

class TestQueryPlanValidator:
    """Tests for QueryPlanValidator."""
    
    def test_valid_minimal_plan(self):
        """Valid minimal query plan passes."""
        validator = QueryPlanValidator()
        data = {
            'query_id': 'q1',
            'query_text': 'What is the capital?',
            'plan_type': 'vector',
            'steps': [{'step': 1, 'action': 'search'}]
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_valid_full_plan(self):
        """Valid full query plan with all fields."""
        validator = QueryPlanValidator()
        data = {
            'query_id': 'q1',
            'query_text': 'Find related entities',
            'plan_type': 'traversal',
            'steps': [
                {'step': 1, 'action': 'extract_entities'},
                {'step': 2, 'action': 'traverse'}
            ],
            'estimated_cost': 125.5,
            'timeout_ms': 5000
        }
        result = validator.validate(data)
        assert result.is_valid is True
    
    def test_invalid_not_dict(self):
        """Non-dict plan fails."""
        validator = QueryPlanValidator()
        result = validator.validate({'query_id': 'q1'})  # not in required format
        assert result.is_valid is False or len(result.errors) > 0
    
    def test_missing_required_query_id(self):
        """Plan without query_id fails."""
        validator = QueryPlanValidator()
        data = {
            'query_text': 'What is the capital?',
            'plan_type': 'vector',
            'steps': [{'step': 1}]
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_invalid_plan_type(self):
        """Invalid plan_type fails."""
        validator = QueryPlanValidator()
        data = {
            'query_id': 'q1',
            'query_text': 'Query?',
            'plan_type': 'invalid_type',  # not in valid types
            'steps': [{'step': 1}]
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_valid_plan_types(self):
        """All valid plan_types accepted."""
        valid_types = ['vector', 'direct', 'traversal', 'hybrid', 'keyword', 'semantic']
        validator = QueryPlanValidator()
        for plan_type in valid_types:
            data = {
                'query_id': 'q1',
                'query_text': 'Query?',
                'plan_type': plan_type,
                'steps': [{'step': 1}]
            }
            result = validator.validate(data)
            assert result.is_valid is True, f"Plan type {plan_type} should be valid"
    
    def test_steps_must_be_list(self):
        """Steps must be a list."""
        validator = QueryPlanValidator()
        data = {
            'query_id': 'q1',
            'query_text': 'Query?',
            'plan_type': 'vector',
            'steps': 'not a list'
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_empty_steps_warning_strict(self):
        """Empty steps generates warning in strict mode."""
        validator = QueryPlanValidator(strict=True)
        data = {
            'query_id': 'q1',
            'query_text': 'Query?',
            'plan_type': 'vector',
            'steps': []
        }
        result = validator.validate(data)
        assert len(result.warnings) > 0
    
    def test_estimated_cost_validation(self):
        """estimated_cost must be non-negative."""
        validator = QueryPlanValidator()
        data = {
            'query_id': 'q1',
            'query_text': 'Query?',
            'plan_type': 'vector',
            'steps': [{'step': 1}],
            'estimated_cost': -100.0
        }
        result = validator.validate(data)
        assert result.is_valid is False
    
    def test_timeout_ms_validation(self):
        """timeout_ms must be non-negative."""
        validator = QueryPlanValidator()
        data = {
            'query_id': 'q1',
            'query_text': 'Query?',
            'plan_type': 'vector',
            'steps': [{'step': 1}],
            'timeout_ms': -1
        }
        result = validator.validate(data)
        assert result.is_valid is False


# ============================================================================
# Test Batch Validation
# ============================================================================

class TestBatchValidation:
    """Tests for validate_batch function."""
    
    def test_validate_batch_all_valid(self):
        """All valid items pass batch validation."""
        entities = [
            {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
            {'id': 'e2', 'name': 'ACME', 'type': 'Org', 'confidence': 0.85},
            {'id': 'e3', 'name': 'Tech', 'type': 'Product', 'confidence': 0.92},
        ]
        validator = EntityExtractionValidator()
        valid_items, results = validate_batch(entities, validator)
        assert len(valid_items) == 3
        assert len(results) == 3
        assert all(r.is_valid for r in results)
    
    def test_validate_batch_mixed_validity(self):
        """Mixed valid/invalid items handled correctly."""
        entities = [
            {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
            {'id': 'e2', 'name': None},  # missing type and confidence
            {'id': 'e3', 'name': 'Tech', 'type': 'Product', 'confidence': 0.92},
        ]
        validator = EntityExtractionValidator()
        valid_items, results = validate_batch(entities, validator)
        assert len(valid_items) == 2  # only e1 and e3
        assert len(results) == 3
        assert results[0].is_valid and not results[1].is_valid and results[2].is_valid
    
    def test_validate_batch_all_invalid(self):
        """All invalid items result in empty valid_items."""
        entities = [
            {'invalid': 'e1'},
            {'invalid': 'e2'},
            {'invalid': 'e3'},
        ]
        validator = EntityExtractionValidator()
        valid_items, results = validate_batch(entities, validator)
        assert len(valid_items) == 0
        assert len(results) == 3
        assert all(not r.is_valid for r in results)
    
    def test_validate_batch_preserves_data(self):
        """Valid items preserved in results."""
        entities = [
            {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
        ]
        validator = EntityExtractionValidator()
        valid_items, results = validate_batch(entities, validator)
        assert valid_items[0] == entities[0]
        assert results[0].data == entities[0]
    
    def test_validate_batch_empty_list(self):
        """Empty batch handled correctly."""
        validator = EntityExtractionValidator()
        valid_items, results = validate_batch([], validator)
        assert len(valid_items) == 0
        assert len(results) == 0


# ============================================================================
# Test ResponseValidator Base Class
# ============================================================================

class TestResponseValidatorBase:
    """Tests for ResponseValidator base class functionality."""
    
    def test_concrete_validator_initialization(self):
        """Concrete validators initialize with settings."""
        validator = EntityExtractionValidator(
            strict=True,
            detailed_errors=True,
            allow_extra_fields=False
        )
        assert validator.strict is True
        assert validator.detailed_errors is True
        assert validator.allow_extra_fields is False
    
    def test_validate_type_valid(self):
        """_validate_type accepts valid types."""
        validator = EntityExtractionValidator()
        result = ValidationResult(is_valid=True)
        is_valid = validator._validate_type("test", str, "field", result)
        assert is_valid is True
        assert len(result.errors) == 0
    
    def test_validate_type_invalid(self):
        """_validate_type rejects wrong types."""
        validator = EntityExtractionValidator()
        result = ValidationResult(is_valid=True)
        is_valid = validator._validate_type(123, str, "field", result)
        assert is_valid is False
        assert len(result.errors) > 0
    
    def test_validate_type_multiple_allowed(self):
        """_validate_type accepts multiple allowed types."""
        validator = EntityExtractionValidator()
        result = ValidationResult(is_valid=True)
        is_valid = validator._validate_type(0.5, (float, int), "field", result)
        assert is_valid is True
    
    def test_validate_range_in_bounds(self):
        """_validate_range accepts in-bounds values."""
        validator = EntityExtractionValidator()
        result = ValidationResult(is_valid=True)
        is_valid = validator._validate_range(0.5, 0.0, 1.0, "field", result)
        assert is_valid is True
        assert len(result.errors) == 0
    
    def test_validate_range_below_minimum(self):
        """_validate_range rejects below-minimum values."""
        validator = EntityExtractionValidator()
        result = ValidationResult(is_valid=True)
        is_valid = validator._validate_range(-0.5, 0.0, 1.0, "field", result)
        assert is_valid is False
        assert any('below' in err.lower() for err in result.errors)
    
    def test_validate_range_above_maximum(self):
        """_validate_range rejects above-maximum values."""
        validator = EntityExtractionValidator()
        result = ValidationResult(is_valid=True)
        is_valid = validator._validate_range(1.5, 0.0, 1.0, "field", result)
        assert is_valid is False
        assert any('above' in err.lower() for err in result.errors)


# ============================================================================
# Test Validator Initialization Options
# ============================================================================

class TestValidatorOptions:
    """Tests for validator initialization options."""
    
    def test_strict_mode_false_default(self):
        """Strict mode default is False."""
        validator = EntityExtractionValidator()
        assert validator.strict is False
    
    def test_detailed_errors_false_default(self):
        """Detailed errors default is False."""
        validator = EntityExtractionValidator()
        assert validator.detailed_errors is False
    
    def test_allow_extra_fields_true_default(self):
        """Allow extra fields default is True."""
        validator = EntityExtractionValidator()
        assert validator.allow_extra_fields is True
    
    def test_all_validators_support_options(self):
        """All validators support common options."""
        validators = [
            EntityExtractionValidator(strict=True, detailed_errors=True),
            RelationshipExtractionValidator(strict=True),
            CriticScoreValidator(detailed_errors=True),
            OntologySessionValidator(allow_extra_fields=False),
            QueryPlanValidator(strict=True, detailed_errors=True),
        ]
        for validator in validators:
            assert hasattr(validator, 'strict')
            assert hasattr(validator, 'detailed_errors')
            assert hasattr(validator, 'allow_extra_fields')


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestIntegrationScenarios:
    """Integration tests for realistic validation workflows."""
    
    def test_validate_extraction_result_workflow(self):
        """Validate complete extraction result workflow."""
        entities = [
            {'id': 'e1', 'name': 'Alice', 'type': 'Person', 'confidence': 0.95},
            {'id': 'e2', 'name': 'Bob', 'type': 'Person', 'confidence': 0.92},
            {'id': 'e3', 'name': 'TechCorp', 'type': 'Org', 'confidence': 0.88},
        ]
        relationships = [
            {'source': 'e1', 'target': 'e3', 'type': 'works_for', 'confidence': 0.9},
            {'source': 'e2', 'target': 'e3', 'type': 'works_for', 'confidence': 0.87},
        ]
        
        entity_validator = EntityExtractionValidator()
        rel_validator = RelationshipExtractionValidator()
        
        valid_entities, entity_results = validate_batch(entities, entity_validator)
        valid_rels, rel_results = validate_batch(relationships, rel_validator)
        
        assert len(valid_entities) == 3
        assert len(valid_rels) == 2
        assert all(r.is_valid for r in entity_results)
        assert all(r.is_valid for r in rel_results)
    
    def test_validate_critic_feedback_workflow(self):
        """Validate critic feedback workflow."""
        scores = [
            {
                'overall': 75.0,
                'completeness': 0.8,
                'consistency': 0.85,
                'clarity': 0.9,
                'granularity': 0.75,
                'domain_alignment': 0.7,
                'recommendations': ['Add more entities', 'Improve relationships']
            },
            {
                'overall': 62.5,
                'completeness': 0.65,
                'consistency': 0.7,
                'clarity': 0.75,
                'granularity': 0.6,
                'domain_alignment': 0.65,
                'recommendations': ['Review entity types']
            }
        ]
        
        validator = CriticScoreValidator()
        valid_scores, results = validate_batch(scores, validator)
        
        assert len(valid_scores) == 2
        assert all(r.is_valid for r in results)
    
    def test_validate_session_and_plans(self):
        """Validate session with query plans."""
        session = {
            'session_id': 'sess_123',
            'domain': 'legal',
            'status': 'completed',
            'duration_ms': 5000
        }
        
        plans = [
            {
                'query_id': 'q1',
                'query_text': 'What is the plaintiff?',
                'plan_type': 'vector',
                'steps': [{'action': 'search'}]
            },
            {
                'query_id': 'q2',
                'query_text': 'Find related cases',
                'plan_type': 'traversal',
                'steps': [{'action': 'traverse'}, {'action': 'filter'}]
            }
        ]
        
        session_validator = OntologySessionValidator()
        plan_validator = QueryPlanValidator()
        
        session_result = session_validator.validate(session)
        valid_plans, plan_results = validate_batch(plans, plan_validator)
        
        assert session_result.is_valid is True
        assert len(valid_plans) == 2
        assert all(r.is_valid for r in plan_results)


# ============================================================================
# Test Error Handling Edge Cases
# ============================================================================

class TestErrorHandlingEdgeCases:
    """Tests for error handling and edge cases."""
    
    def test_validator_handles_none_input(self):
        """Validators handle None input gracefully."""
        validator = EntityExtractionValidator()
        result = validator.validate(None)
        # Should mark as invalid due to type error
        assert result.is_valid is False or any('dict' in err.lower() for err in result.errors)
    
    def test_validator_handles_empty_dict(self):
        """Validators handle empty dict."""
        validator = EntityExtractionValidator()
        result = validator.validate({})
        # Should fail due to missing required fields
        assert result.is_valid is False
    
    def test_detailed_errors_structure(self):
        """Detailed errors have complete structure."""
        result = ValidationResult(is_valid=True)
        result.add_error("Test error", field='test_field', code='test_code')
        
        detail = result.detailed_errors[0]
        assert 'severity' in detail
        assert 'field' in detail
        assert 'message' in detail
        assert 'code' in detail
        assert detail['severity'] == 'error'
    
    def test_multiple_validator_instances_independent(self):
        """Multiple validator instances are independent."""
        v1 = EntityExtractionValidator(strict=True)
        v2 = EntityExtractionValidator(strict=False)
        
        assert v1.strict is True
        assert v2.strict is False
        
        # Validate with each
        data = {'id': 'e1'}
        r1 = v1.validate(data)
        r2 = v2.validate(data)
        
        # Both should fail due to missing fields
        assert r1.is_valid is False
        assert r2.is_valid is False

