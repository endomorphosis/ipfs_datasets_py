"""
Type validation tests for optimizer_alert_system.py

Tests the structure and typing of learning anomaly management:
- LearningAnomalyDict: Serialized anomaly detection and representation
"""

import pytest
import datetime
from ipfs_datasets_py.optimizers.optimizer_alert_system import (
    LearningAnomaly, LearningAnomalyDict
)


class TestLearningAnomalyDict:
    """Tests for LearningAnomalyDict TypedDict structure."""
    
    def test_learning_anomaly_to_dict_structure(self):
        """Verify LearningAnomaly.to_dict() returns LearningAnomalyDict."""
        anomaly = LearningAnomaly(
            anomaly_type="oscillation",
            severity="warning",
            description="Parameter oscillation detected",
            affected_parameters=["learning_rate", "batch_size"]
        )
        result = anomaly.to_dict()
        
        # Verify it's a dict
        assert isinstance(result, dict)
        
    def test_learning_anomaly_dict_required_fields(self):
        """Verify LearningAnomalyDict contains all required fields."""
        anomaly = LearningAnomaly(
            anomaly_type="decline",
            severity="critical",
            description="Performance declining",
            affected_parameters=["success_rate"],
            metric_values={"success_rate": 0.75}
        )
        result = anomaly.to_dict()
        
        # Check all required fields
        assert "id" in result
        assert "anomaly_type" in result
        assert "severity" in result
        assert "description" in result
        assert "affected_parameters" in result
        assert "timestamp" in result
        assert "metric_values" in result
        
    def test_learning_anomaly_dict_id_field(self):
        """Verify id field is unique and present."""
        anomaly = LearningAnomaly(
            anomaly_type="oscillation",
            severity="info",
            description="Test anomaly"
        )
        result = anomaly.to_dict()
        
        assert "id" in result
        assert isinstance(result["id"], str)
        assert len(result["id"]) > 0
        
    def test_learning_anomaly_dict_anomaly_type(self):
        """Verify anomaly_type field is preserved."""
        anomaly_types = ["oscillation", "decline", "stalled", "effectiveness"]
        
        for atype in anomaly_types:
            anomaly = LearningAnomaly(
                anomaly_type=atype,
                severity="warning",
                description="Test"
            )
            result = anomaly.to_dict()
            
            assert result["anomaly_type"] == atype
            
    def test_learning_anomaly_dict_severity(self):
        """Verify severity field preserves levels."""
        severities = ["info", "warning", "critical"]
        
        for sev in severities:
            anomaly = LearningAnomaly(
                anomaly_type="test",
                severity=sev,
                description="Test"
            )
            result = anomaly.to_dict()
            
            assert result["severity"] == sev
            
    def test_learning_anomaly_dict_description(self):
        """Verify description field is preserved."""
        desc = "This is a detailed description of the anomaly"
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="warning",
            description=desc
        )
        result = anomaly.to_dict()
        
        assert result["description"] == desc
        
    def test_learning_anomaly_dict_affected_parameters(self):
        """Verify affected_parameters list is preserved."""
        params = ["param1", "param2", "param3"]
        anomaly = LearningAnomaly(
            anomaly_type="oscillation",
            severity="warning",
            description="Test",
            affected_parameters=params
        )
        result = anomaly.to_dict()
        
        assert result["affected_parameters"] == params
        assert isinstance(result["affected_parameters"], list)
        
    def test_learning_anomaly_dict_timestamp_iso_format(self):
        """Verify timestamp is converted to ISO format string."""
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description="Test"
        )
        result = anomaly.to_dict()
        
        # Timestamp should be ISO format string
        assert isinstance(result["timestamp"], str)
        # Verify it looks like ISO format (contains 'T')
        assert "T" in result["timestamp"]
        
    def test_learning_anomaly_dict_metric_values(self):
        """Verify metric_values field preserves additional data."""
        metrics = {
            "success_rate": 0.85,
            "response_time": 1.2,
            "parameter_changes": ["lr: 0.01 -> 0.02", "bs: 32 -> 64"]
        }
        anomaly = LearningAnomaly(
            anomaly_type="decline",
            severity="critical",
            description="Test",
            metric_values=metrics
        )
        result = anomaly.to_dict()
        
        assert result["metric_values"] == metrics
        
    def test_learning_anomaly_dict_empty_metric_values(self):
        """Verify to_dict() handles empty metric_values."""
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description="Test",
            metric_values={}
        )
        result = anomaly.to_dict()
        
        assert result["metric_values"] == {}


class TestAnomalyRoundTrip:
    """Tests for serialization and deserialization."""
    
    def test_to_dict_and_from_dict_roundtrip(self):
        """Verify anomaly can be serialized and deserialized."""
        original = LearningAnomaly(
            anomaly_type="oscillation",
            severity="warning",
            description="Parameter oscillation detected",
            affected_parameters=["learning_rate"],
            metric_values={"oscillation_count": 5}
        )
        
        # Serialize
        serialized = original.to_dict()
        
        # Deserialize
        restored = LearningAnomaly.from_dict(serialized)
        
        # Verify key fields match
        assert restored.anomaly_type == original.anomaly_type
        assert restored.severity == original.severity
        assert restored.description == original.description
        assert restored.affected_parameters == original.affected_parameters
        
    def test_roundtrip_with_custom_id(self):
        """Verify custom ID is preserved through serialization."""
        custom_id = "custom_id_123"
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description="Test",
            id=custom_id
        )
        
        serialized = anomaly.to_dict()
        assert serialized["id"] == custom_id
        
        restored = LearningAnomaly.from_dict(serialized)
        assert restored.id == custom_id


class TestAnomalyTypes:
    """Tests for different anomaly detection scenarios."""
    
    def test_oscillation_anomaly(self):
        """Verify oscillation type anomaly serialization."""
        anomaly = LearningAnomaly(
            anomaly_type="oscillation",
            severity="warning",
            description="Parameters oscillating without convergence",
            affected_parameters=["learning_rate", "momentum"],
            metric_values={"cycle_count": 3}
        )
        result = anomaly.to_dict()
        
        assert result["anomaly_type"] == "oscillation"
        assert result["severity"] == "warning"
        
    def test_performance_decline_anomaly(self):
        """Verify performance decline type anomaly serialization."""
        anomaly = LearningAnomaly(
            anomaly_type="decline",
            severity="critical",
            description="Success rate declining over time",
            affected_parameters=["success_rate"],
            metric_values={
                "previous_rate": 0.95,
                "current_rate": 0.70,
                "decline_percent": 26.3
            }
        )
        result = anomaly.to_dict()
        
        assert result["anomaly_type"] == "decline"
        assert result["severity"] == "critical"
        assert result["metric_values"]["decline_percent"] == 26.3
        
    def test_stalled_learning_anomaly(self):
        """Verify stalled learning type anomaly serialization."""
        anomaly = LearningAnomaly(
            anomaly_type="stalled",
            severity="warning",
            description="No parameter updates despite changing patterns",
            affected_parameters=["all_parameters"],
            metric_values={"iterations_without_update": 100}
        )
        result = anomaly.to_dict()
        
        assert result["anomaly_type"] == "stalled"


class TestTypeConsistency:
    """Tests for consistency of anomaly serialization."""
    
    def test_to_dict_always_returns_dict(self):
        """Verify to_dict() always returns dict instance."""
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description="Test"
        )
        result = anomaly.to_dict()
        
        assert isinstance(result, dict)
        assert not isinstance(result, (list, tuple, str))
        
    def test_multiple_serializations_consistent(self):
        """Verify multiple calls to to_dict() are consistent."""
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="warning",
            description="Test anomaly"
        )
        
        result1 = anomaly.to_dict()
        result2 = anomaly.to_dict()
        
        assert result1 == result2
        
    def test_field_types_preserved(self):
        """Verify field types are preserved in serialization."""
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description="Test",
            affected_parameters=["param1", "param2"],
            metric_values={"count": 42, "score": 0.95}
        )
        result = anomaly.to_dict()
        
        assert isinstance(result["anomaly_type"], str)
        assert isinstance(result["severity"], str)
        assert isinstance(result["description"], str)
        assert isinstance(result["affected_parameters"], list)
        assert isinstance(result["timestamp"], str)
        assert isinstance(result["metric_values"], dict)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_anomaly_with_empty_parameters(self):
        """Verify anomaly with no affected parameters."""
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description="Test",
            affected_parameters=[]
        )
        result = anomaly.to_dict()
        
        assert result["affected_parameters"] == []
        
    def test_anomaly_with_long_description(self):
        """Verify anomaly with lengthy description."""
        long_desc = "A" * 1000
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="info",
            description=long_desc
        )
        result = anomaly.to_dict()
        
        assert result["description"] == long_desc
        assert len(result["description"]) == 1000
        
    def test_anomaly_with_many_parameters(self):
        """Verify anomaly with multiple affected parameters."""
        params = [f"param_{i}" for i in range(100)]
        anomaly = LearningAnomaly(
            anomaly_type="test",
            severity="warning",
            description="Test",
            affected_parameters=params
        )
        result = anomaly.to_dict()
        
        assert len(result["affected_parameters"]) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
