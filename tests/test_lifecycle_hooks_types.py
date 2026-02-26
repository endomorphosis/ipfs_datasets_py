"""
Type validation tests for lifecycle_hooks.py

Tests the structure and typing of lifecycle event management:
- LifecycleEventDict: Serialized lifecycle event representation
"""

import pytest
import time
from ipfs_datasets_py.optimizers.lifecycle_hooks import (
    LifecycleEvent, LifecycleEventType, LifecycleEventDict,
    SimpleLifecycleHook, LifecycleManager
)


class TestLifecycleEventDict:
    """Tests for LifecycleEventDict TypedDict structure."""
    
    def test_lifecycle_event_to_dict_structure(self):
        """Verify LifecycleEvent.to_dict() returns LifecycleEventDict."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="test_operation",
            timestamp=time.time(),
            data={"param1": "value1"}
        )
        result = event.to_dict()
        
        # Verify it's a dict
        assert isinstance(result, dict)
        
    def test_lifecycle_event_dict_required_fields(self):
        """Verify LifecycleEventDict contains all required fields."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="process_data",
            timestamp=12345.67,
            data={"items": 100}
        )
        result = event.to_dict()
        
        # Check all required fields
        assert "event_type" in result
        assert "operation_name" in result
        assert "timestamp" in result
        assert "data" in result
        
    def test_lifecycle_event_dict_event_type_string(self):
        """Verify event_type is converted to string value."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_ERROR,
            operation_name="error_check",
            timestamp=time.time(),
            data={"error": "Connection failed"}
        )
        result = event.to_dict()
        
        # event_type should be string, not enum
        assert isinstance(result["event_type"], str)
        assert result["event_type"] == "on_error"
        
    def test_lifecycle_event_dict_operation_name(self):
        """Verify operation_name field is preserved."""
        op_name = "custom_operation_123"
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name=op_name,
            timestamp=time.time(),
            data={}
        )
        result = event.to_dict()
        
        assert result["operation_name"] == op_name
        
    def test_lifecycle_event_dict_timestamp(self):
        """Verify timestamp field is preserved."""
        ts = 1234567890.5
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_COMPLETE,
            operation_name="complete_op",
            timestamp=ts,
            data={}
        )
        result = event.to_dict()
        
        assert result["timestamp"] == ts
        assert isinstance(result["timestamp"], float)
        
    def test_lifecycle_event_dict_data_field(self):
        """Verify data field preserves event-specific information."""
        data = {
            "status": "success",
            "duration": 45.3,
            "items_processed": 500,
            "errors": ["warning_1"]
        }
        event = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="batch_process",
            timestamp=time.time(),
            data=data
        )
        result = event.to_dict()
        
        assert result["data"] == data
        
    def test_lifecycle_event_dict_empty_data(self):
        """Verify to_dict() handles empty data field."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="init",
            timestamp=time.time(),
            data={}
        )
        result = event.to_dict()
        
        assert "data" in result
        assert result["data"] == {}


class TestAllEventTypes:
    """Tests for all LifecycleEventType values."""
    
    def test_before_operation_event(self):
        """Verify BEFORE_OPERATION event serialization."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="prep",
            timestamp=time.time(),
            data={"preparing": True}
        )
        result = event.to_dict()
        
        assert result["event_type"] == "before_operation"
        
    def test_after_operation_event(self):
        """Verify AFTER_OPERATION event serialization."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="cleanup",
            timestamp=time.time(),
            data={"cleaned": True}
        )
        result = event.to_dict()
        
        assert result["event_type"] == "after_operation"
        
    def test_on_error_event(self):
        """Verify ON_ERROR event serialization."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_ERROR,
            operation_name="error_handler",
            timestamp=time.time(),
            data={"error_code": 500, "message": "Internal error"}
        )
        result = event.to_dict()
        
        assert result["event_type"] == "on_error"
        
    def test_on_complete_event(self):
        """Verify ON_COMPLETE event serialization."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_COMPLETE,
            operation_name="finalize",
            timestamp=time.time(),
            data={"success": True}
        )
        result = event.to_dict()
        
        assert result["event_type"] == "on_complete"
        
    def test_on_timeout_event(self):
        """Verify ON_TIMEOUT event serialization."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_TIMEOUT,
            operation_name="timeout_handler",
            timestamp=time.time(),
            data={"timeout_seconds": 300}
        )
        result = event.to_dict()
        
        assert result["event_type"] == "on_timeout"


class TestEventDictConsistency:
    """Tests for consistency of event serialization."""
    
    def test_multiple_serializations_consistent(self):
        """Verify multiple calls to to_dict() produce same result."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="consistent_op",
            timestamp=100.5,
            data={"key": "value"}
        )
        
        result1 = event.to_dict()
        result2 = event.to_dict()
        
        assert result1 == result2
        
    def test_event_dict_is_always_dict(self):
        """Verify to_dict() always returns dict."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="any_op",
            timestamp=time.time(),
            data={}
        )
        result = event.to_dict()
        
        assert isinstance(result, dict)
        assert not isinstance(result, list)
        assert not isinstance(result, tuple)
        
    def test_event_serialization_preserves_types(self):
        """Verify event serialization preserves field types."""
        ts = 1234567890.123
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="type_check",
            timestamp=ts,
            data={"number": 42, "float": 3.14, "bool": True}
        )
        result = event.to_dict()
        
        assert isinstance(result["timestamp"], float)
        assert isinstance(result["operation_name"], str)
        assert isinstance(result["data"]["number"], int)
        assert isinstance(result["data"]["float"], float)
        assert isinstance(result["data"]["bool"], bool)


class TestIntegrationWithHooks:
    """Tests for integration with lifecycle hooks."""
    
    def test_simple_hook_integration(self):
        """Verify LifecycleEvent works with SimpleLifecycleHook."""
        hook = SimpleLifecycleHook("test_hook")
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="hook_test",
            timestamp=time.time(),
            data={}
        )
        
        # Serialize event for logging
        event_dict = event.to_dict()
        
        # Handle event (should work with hook)
        hook.handle(event)
        
        # Event should be in hook's invocations
        assert len(hook.invocations) == 1
        
    def test_lifecycle_manager_with_event_dict(self):
        """Verify LifecycleEvent serialization works with manager."""
        manager = LifecycleManager()
        hook = SimpleLifecycleHook("manager_hook")
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="manager_op",
            timestamp=time.time(),
            data={"test": True}
        )
        
        # Dispatch event
        manager.dispatch_event(event)
        
        # Convert to dict for storage/logging
        event_dict = event.to_dict()
        assert isinstance(event_dict, dict)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_event_with_large_data(self):
        """Verify event serialization with large data payload."""
        large_data = {
            "items": list(range(1000)),
            "metadata": {"count": 1000, "size": "large"}
        }
        event = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="large_data_op",
            timestamp=time.time(),
            data=large_data
        )
        result = event.to_dict()
        
        assert len(result["data"]["items"]) == 1000
        
    def test_event_with_nested_data(self):
        """Verify event serialization with nested data structures."""
        nested_data = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "deep"
                    }
                }
            }
        }
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_ERROR,
            operation_name="nested_error",
            timestamp=time.time(),
            data=nested_data
        )
        result = event.to_dict()
        
        assert result["data"]["level1"]["level2"]["level3"]["value"] == "deep"
        
    def test_event_with_special_characters(self):
        """Verify event handles special characters in strings."""
        special_data = {
            "message": "Error: Connection\nFailed! 😢",
            "path": "/home/user/dir/file.txt",
            "json": '{"nested": "json"}'
        }
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_ERROR,
            operation_name="special_chars_op",
            timestamp=time.time(),
            data=special_data
        )
        result = event.to_dict()
        
        assert result["data"]["message"] == special_data["message"]
        assert result["data"]["json"] == special_data["json"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
