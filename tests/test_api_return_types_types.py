"""
Type validation tests for api_return_types.py

Tests the structure and typing of API return type conversions:
- SerializedResultDict: Dataclass serialization
- JsonSerializableDict: JSON-serializable conversions
"""

import pytest
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any
from ipfs_datasets_py.optimizers.api_return_types import (
    to_dict, to_json_serializable,
    OperationStatus, ExtractorResult, CriticResult, 
    SerializedResultDict, JsonSerializableDict
)


class TestSerializedResultDict:
    """Tests for SerializedResultDict TypedDict structure."""
    
    def test_to_dict_basic_result(self):
        """Verify to_dict() returns SerializedResultDict with basic result."""
        result = ExtractorResult(
            entities=["entity1", "entity2"],
            entity_count=2,
            extraction_time_ms=100.5,
            confidence_scores=[0.9, 0.85]
        )
        serialized = to_dict(result)
        
        # Verify it's a dict
        assert isinstance(serialized, dict)
        # Verify key fields present
        assert "entities" in serialized
        assert "entity_count" in serialized
        assert "extraction_time_ms" in serialized
        assert "confidence_scores" in serialized
        
    def test_to_dict_preserves_values(self):
        """Verify to_dict() preserves field values correctly."""
        result = ExtractorResult(
            entities=["test"],
            entity_count=1,
            extraction_time_ms=50.0,
            confidence_scores=[0.95]
        )
        serialized = to_dict(result)
        
        assert serialized["entity_count"] == 1
        assert serialized["extraction_time_ms"] == 50.0
        assert serialized["entities"] == ["test"]
        
    def test_to_dict_with_relationships(self):
        """Verify to_dict() includes optional relationships field."""
        result = ExtractorResult(
            entities=["entity1", "entity2"],
            entity_count=2,
            extraction_time_ms=75.0,
            confidence_scores=[0.88, 0.92],
            relationships=[("entity1", "entity2")]
        )
        serialized = to_dict(result)
        
        assert "relationships" in serialized
        assert serialized["relationships"] == [("entity1", "entity2")]
        
    def test_to_dict_with_status(self):
        """Verify to_dict() includes status enum field."""
        result = ExtractorResult(
            entities=["entity1"],
            entity_count=1,
            extraction_time_ms=60.0,
            confidence_scores=[0.9],
            status=OperationStatus.SUCCESS
        )
        serialized = to_dict(result)
        
        assert "status" in serialized
        assert serialized["status"] == OperationStatus.SUCCESS
        
    def test_to_dict_critic_result(self):
        """Verify to_dict() works with CriticResult dataclass."""
        result = CriticResult(
            dimension_name="extraction_quality",
            score=0.85,
            max_score=1.0,
            issues=["missing_context"],
            recommendations=["add_context"]
        )
        serialized = to_dict(result)
        
        assert isinstance(serialized, dict)
        assert "dimension_name" in serialized
        assert "score" in serialized
        assert "max_score" in serialized
        
    def test_to_dict_empty_input(self):
        """Verify to_dict() handles edge cases gracefully."""
        # to_dict with non-dataclass should return empty dict
        result = to_dict(None)
        assert isinstance(result, dict)


class TestJsonSerializableDict:
    """Tests for JsonSerializableDict TypedDict structure."""
    
    def test_to_json_serializable_basic(self):
        """Verify to_json_serializable() returns JsonSerializableDict."""
        result = ExtractorResult(
            entities=["entity1"],
            entity_count=1,
            extraction_time_ms=100.0,
            confidence_scores=[0.9]
        )
        serialized = to_json_serializable(result)
        
        assert isinstance(serialized, dict)
        assert "entities" in serialized
        assert "entity_count" in serialized
        
    def test_to_json_serializable_enum_conversion(self):
        """Verify to_json_serializable() converts Enum to string."""
        result = ExtractorResult(
            entities=["test"],
            entity_count=1,
            extraction_time_ms=50.0,
            confidence_scores=[0.95],
            status=OperationStatus.SUCCESS
        )
        serialized = to_json_serializable(result)
        
        # Status should be converted to string value
        assert isinstance(serialized["status"], str)
        assert serialized["status"] == "success"
        
    def test_to_json_serializable_partial_status(self):
        """Verify enum conversion for PARTIAL status."""
        result = ExtractorResult(
            entities=["e1", "e2"],
            entity_count=2,
            extraction_time_ms=80.0,
            confidence_scores=[0.8, 0.75],
            status=OperationStatus.PARTIAL
        )
        serialized = to_json_serializable(result)
        
        assert serialized["status"] == "partial"
        
    def test_to_json_serializable_failed_status(self):
        """Verify enum conversion for FAILED status."""
        result = ExtractorResult(
            entities=[],
            entity_count=0,
            extraction_time_ms=10.0,
            confidence_scores=[],
            status=OperationStatus.FAILED
        )
        serialized = to_json_serializable(result)
        
        assert serialized["status"] == "failed"
        
    def test_to_json_serializable_timeout_status(self):
        """Verify enum conversion for TIMEOUT status."""
        result = ExtractorResult(
            entities=[],
            entity_count=0,
            extraction_time_ms=5000.0,
            confidence_scores=[],
            status=OperationStatus.TIMEOUT
        )
        serialized = to_json_serializable(result)
        
        assert serialized["status"] == "timeout"
        
    def test_to_json_serializable_with_critic_result(self):
        """Verify to_json_serializable works with different result types."""
        result = CriticResult(
            dimension_name="validation_score",
            score=0.75,
            max_score=1.0,
            issues=["incomplete"],
            recommendations=["review"]
        )
        serialized = to_json_serializable(result)
        
        assert isinstance(serialized, dict)
        assert serialized["dimension_name"] == "validation_score"
        assert serialized["score"] == 0.75


class TestTypeConsistency:
    """Tests for consistency between to_dict and to_json_serializable."""
    
    def test_consistency_basic_fields(self):
        """Verify both functions preserve basic field values."""
        result = ExtractorResult(
            entities=["a", "b", "c"],
            entity_count=3,
            extraction_time_ms=150.0,
            confidence_scores=[0.9, 0.88, 0.85]
        )
        
        dict_result = to_dict(result)
        json_result = to_json_serializable(result)
        
        # Should have same basic fields
        assert dict_result["entity_count"] == json_result["entity_count"]
        assert dict_result["extraction_time_ms"] == json_result["extraction_time_ms"]
        assert dict_result["entities"] == json_result["entities"]
        
    def test_consistency_with_enum(self):
        """Verify to_json_serializable is superset (with enum conversion)."""
        result = ExtractorResult(
            entities=["x"],
            entity_count=1,
            extraction_time_ms=25.0,
            confidence_scores=[0.98],
            status=OperationStatus.SUCCESS
        )
        
        dict_result = to_dict(result)
        json_result = to_json_serializable(result)
        
        # json_result should have stringified enum
        assert isinstance(dict_result["status"], OperationStatus)
        assert isinstance(json_result["status"], str)
        assert json_result["status"] == dict_result["status"].value
        
    def test_all_results_are_dicts(self):
        """Verify both functions always return dict instances."""
        result = ExtractorResult(
            entities=["test"],
            entity_count=1,
            extraction_time_ms=1.0,
            confidence_scores=[1.0]
        )
        
        dict_result = to_dict(result)
        json_result = to_json_serializable(result)
        
        assert isinstance(dict_result, dict)
        assert isinstance(json_result, dict)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""
    
    def test_to_dict_with_none(self):
        """Verify to_dict handles None gracefully."""
        result = to_dict(None)
        assert isinstance(result, dict)
        
    def test_to_dict_with_dict_input(self):
        """Verify to_dict can handle dict input."""
        input_dict = {"key": "value", "count": 10}
        result = to_dict(input_dict)
        assert isinstance(result, dict)
        
    def test_to_json_serializable_maintains_structure(self):
        """Verify JSON serialization maintains overall structure."""
        result = ExtractorResult(
            entities=["entity1", "entity2", "entity3"],
            entity_count=3,
            extraction_time_ms=200.0,
            confidence_scores=[0.95, 0.90, 0.88],
            relationships=[("e1", "e2"), ("e2", "e3")]
        )
        
        serialized = to_json_serializable(result)
        
        # Verify all top-level keys are present
        assert len(serialized.keys()) > 0
        # Verify list fields remain lists
        assert isinstance(serialized["entities"], list)
        assert isinstance(serialized["confidence_scores"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
