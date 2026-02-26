"""Batch 325: Lifecycle Hooks Consolidation - Comprehensive Test Suite

Provides consolidated lifecycle hook management across the optimizer system.

Key test areas:
- Hook registration and removal
- Hook invocation with proper ordering
- Error handling and propagation
- Hook composition and chaining
- Lifecycle event types
- Integration patterns

"""

import pytest
from typing import Callable, List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from contextlib import contextmanager


class LifecycleEventType(Enum):
    """Types of lifecycle events."""
    BEFORE_OPERATION = "before_operation"
    AFTER_OPERATION = "after_operation"
    ON_ERROR = "on_error"
    ON_COMPLETE = "on_complete"
    ON_TIMEOUT = "on_timeout"


@dataclass
class LifecycleEvent:
    """Represents a lifecycle event."""
    event_type: LifecycleEventType
    operation_name: str
    timestamp: float
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_type": self.event_type.value,
            "operation_name": self.operation_name,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class LifecycleHook(ABC):
    """Base class for lifecycle hooks."""
    
    @abstractmethod
    def handle(self, event: LifecycleEvent) -> None:
        """Handle a lifecycle event."""
        pass


class SimpleLifecycleHook(LifecycleHook):
    """Simple hook that stores invocation history."""
    
    def __init__(self, name: str):
        self.name = name
        self.invocations: List[LifecycleEvent] = []
    
    def handle(self, event: LifecycleEvent) -> None:
        """Handle event by storing in invocations list."""
        self.invocations.append(event)
    
    def reset(self) -> None:
        """Reset invocation history."""
        self.invocations = []


class ConditionalHook(LifecycleHook):
    """Hook that only fires under certain conditions."""
    
    def __init__(self, condition: Callable[[LifecycleEvent], bool], callback: Callable[[LifecycleEvent], None]):
        self.condition = condition
        self.callback = callback
        self.invocations: List[LifecycleEvent] = []
    
    def handle(self, event: LifecycleEvent) -> None:
        """Handle event if condition is met."""
        if self.condition(event):
            self.callback(event)
            self.invocations.append(event)


class ErrorHandlingHook(LifecycleHook):
    """Hook that captures and transforms errors."""
    
    def __init__(self):
        self.errors_caught: List[Tuple[LifecycleEvent, Exception]] = []
    
    def handle(self, event: LifecycleEvent) -> None:
        """Handle error event."""
        if event.event_type == LifecycleEventType.ON_ERROR:
            error = event.data.get("exception")
            if error:
                self.errors_caught.append((event, error))


class LifecycleManager:
    """Manages lifecycle hooks for operations."""
    
    def __init__(self):
        self.hooks: Dict[LifecycleEventType, List[LifecycleHook]] = {
            event_type: [] for event_type in LifecycleEventType
        }
        self.invocation_order: List[Tuple[LifecycleEventType, str]] = []
    
    def register_hook(self, event_type: LifecycleEventType, hook: LifecycleHook) -> None:
        """Register a hook for a lifecycle event."""
        if not isinstance(hook, LifecycleHook):
            raise TypeError(f"Hook must be instance of LifecycleHook, got {type(hook)}")
        self.hooks[event_type].append(hook)
    
    def remove_hook(self, event_type: LifecycleEventType, hook: LifecycleHook) -> bool:
        """Remove a hook. Returns True if hook was found and removed."""
        if hook in self.hooks[event_type]:
            self.hooks[event_type].remove(hook)
            return True
        return False
    
    def clear_hooks(self, event_type: Optional[LifecycleEventType] = None) -> None:
        """Clear hooks for event type, or all hooks if event_type is None."""
        if event_type is None:
            for hooks_list in self.hooks.values():
                hooks_list.clear()
        else:
            self.hooks[event_type].clear()
    
    def get_hooks(self, event_type: LifecycleEventType) -> List[LifecycleHook]:
        """Get all hooks for an event type."""
        return self.hooks[event_type].copy()
    
    def dispatch_event(self, event: LifecycleEvent) -> None:
        """Dispatch an event to all registered hooks."""
        hooks = self.hooks.get(event.event_type, [])
        self.invocation_order.append((event.event_type, event.operation_name))
        
        for hook in hooks:
            hook.handle(event)
    
    def get_invocation_order(self) -> List[Tuple[LifecycleEventType, str]]:
        """Get the order in which hooks were invoked."""
        return self.invocation_order.copy()
    
    def reset_invocation_history(self) -> None:
        """Reset invocation order tracking."""
        self.invocation_order = []


# Test Suite

class TestLifecycleEventType:
    """Test LifecycleEventType enum."""
    
    def test_event_types_defined(self):
        """Should have all standard event types."""
        assert LifecycleEventType.BEFORE_OPERATION in LifecycleEventType
        assert LifecycleEventType.AFTER_OPERATION in LifecycleEventType
        assert LifecycleEventType.ON_ERROR in LifecycleEventType
        assert LifecycleEventType.ON_COMPLETE in LifecycleEventType
        assert LifecycleEventType.ON_TIMEOUT in LifecycleEventType
    
    def test_event_type_values(self):
        """Event type values should be meaningful strings."""
        assert LifecycleEventType.BEFORE_OPERATION.value == "before_operation"
        assert LifecycleEventType.ON_ERROR.value == "on_error"


class TestLifecycleEvent:
    """Test LifecycleEvent dataclass."""
    
    def test_create_event(self):
        """Should create event with required fields."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="test_op",
            timestamp=123.45,
        )
        
        assert event.event_type == LifecycleEventType.BEFORE_OPERATION
        assert event.operation_name == "test_op"
        assert event.timestamp == 123.45
        assert event.data == {}
    
    def test_event_with_data(self):
        """Should store event data."""
        data = {"key": "value", "count": 42}
        event = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="op",
            timestamp=1.0,
            data=data,
        )
        
        assert event.data == data
        assert event.data["key"] == "value"
    
    def test_event_to_dict(self):
        """Should convert event to dictionary."""
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_ERROR,
            operation_name="failing_op",
            timestamp=999.0,
            data={"error": "test"},
        )
        
        event_dict = event.to_dict()
        
        assert event_dict["event_type"] == "on_error"
        assert event_dict["operation_name"] == "failing_op"
        assert event_dict["timestamp"] == 999.0
        assert event_dict["data"] == {"error": "test"}


class TestSimpleLifecycleHook:
    """Test SimpleLifecycleHook."""
    
    def test_hook_captures_invocations(self):
        """Hook should record all invocations."""
        hook = SimpleLifecycleHook("test_hook")
        
        event1 = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name="op1",
            timestamp=1.0,
        )
        hook.handle(event1)
        
        event2 = LifecycleEvent(
            event_type=LifecycleEventType.AFTER_OPERATION,
            operation_name="op1",
            timestamp=2.0,
        )
        hook.handle(event2)
        
        assert len(hook.invocations) == 2
        assert hook.invocations[0] == event1
        assert hook.invocations[1] == event2
    
    def test_hook_reset(self):
        """Hook should support resetting history."""
        hook = SimpleLifecycleHook("test")
        event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        
        hook.handle(event)
        assert len(hook.invocations) == 1
        
        hook.reset()
        assert len(hook.invocations) == 0


class TestConditionalHook:
    """Test ConditionalHook."""
    
    def test_conditional_hook_filters_events(self):
        """Hook should only fire when condition is true."""
        callback_invocations = []
        
        def callback(event: LifecycleEvent):
            callback_invocations.append(event)
        
        # Condition: only handle BEFORE_OPERATION events
        hook = ConditionalHook(
            condition=lambda e: e.event_type == LifecycleEventType.BEFORE_OPERATION,
            callback=callback,
        )
        
        before_event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        after_event = LifecycleEvent(LifecycleEventType.AFTER_OPERATION, "op", 2.0)
        
        hook.handle(before_event)
        hook.handle(after_event)
        
        # Only BEFORE event should trigger callback
        assert len(hook.invocations) == 1
        assert hook.invocations[0] == before_event
        assert len(callback_invocations) == 1


class TestErrorHandlingHook:
    """Test ErrorHandlingHook."""
    
    def test_hook_captures_errors(self):
        """Hook should capture error events."""
        hook = ErrorHandlingHook()
        
        error = RuntimeError("test error")
        event = LifecycleEvent(
            event_type=LifecycleEventType.ON_ERROR,
            operation_name="failed_op",
            timestamp=1.0,
            data={"exception": error},
        )
        
        hook.handle(event)
        
        assert len(hook.errors_caught) == 1
        assert hook.errors_caught[0][0] == event
        assert hook.errors_caught[0][1] == error


class TestLifecycleManager:
    """Test LifecycleManager."""
    
    def test_register_hook(self):
        """Should register hooks for event types."""
        manager = LifecycleManager()
        hook = SimpleLifecycleHook("hook1")
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        
        hooks = manager.get_hooks(LifecycleEventType.BEFORE_OPERATION)
        assert hook in hooks
    
    def test_register_invalid_hook_raises_error(self):
        """Should reject non-LifecycleHook objects."""
        manager = LifecycleManager()
        
        with pytest.raises(TypeError):
            manager.register_hook(LifecycleEventType.BEFORE_OPERATION, "not a hook")
    
    def test_remove_hook(self):
        """Should remove registered hooks."""
        manager = LifecycleManager()
        hook = SimpleLifecycleHook("hook")
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        assert hook in manager.get_hooks(LifecycleEventType.BEFORE_OPERATION)
        
        removed = manager.remove_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        assert removed is True
        assert hook not in manager.get_hooks(LifecycleEventType.BEFORE_OPERATION)
    
    def test_remove_nonexistent_hook_returns_false(self):
        """Should return False when removing non-existent hook."""
        manager = LifecycleManager()
        hook = SimpleLifecycleHook("hook")
        
        removed = manager.remove_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        assert removed is False
    
    def test_clear_specific_event_type(self):
        """Should clear hooks for specific event type."""
        manager = LifecycleManager()
        before_hook = SimpleLifecycleHook("before")
        after_hook = SimpleLifecycleHook("after")
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, before_hook)
        manager.register_hook(LifecycleEventType.AFTER_OPERATION, after_hook)
        
        manager.clear_hooks(LifecycleEventType.BEFORE_OPERATION)
        
        assert len(manager.get_hooks(LifecycleEventType.BEFORE_OPERATION)) == 0
        assert len(manager.get_hooks(LifecycleEventType.AFTER_OPERATION)) == 1
    
    def test_clear_all_hooks(self):
        """Should clear all hooks when event_type is None."""
        manager = LifecycleManager()
        
        for event_type in LifecycleEventType:
            hook = SimpleLifecycleHook(f"hook_{event_type.value}")
            manager.register_hook(event_type, hook)
        
        manager.clear_hooks()  # None clears all
        
        for event_type in LifecycleEventType:
            assert len(manager.get_hooks(event_type)) == 0
    
    def test_dispatch_event_calls_hooks(self):
        """Should call all registered hooks when dispatching event."""
        manager = LifecycleManager()
        hook1 = SimpleLifecycleHook("hook1")
        hook2 = SimpleLifecycleHook("hook2")
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook1)
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook2)
        
        event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        manager.dispatch_event(event)
        
        assert len(hook1.invocations) == 1
        assert len(hook2.invocations) == 1
        assert hook1.invocations[0] == event
        assert hook2.invocations[0] == event
    
    def test_dispatch_event_tracking(self):
        """Should track invocation order."""
        manager = LifecycleManager()
        hook = SimpleLifecycleHook("hook")
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        
        event1 = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op1", 1.0)
        event2 = LifecycleEvent(LifecycleEventType.AFTER_OPERATION, "op1", 2.0)
        
        manager.dispatch_event(event1)
        manager.dispatch_event(event2)
        
        order = manager.get_invocation_order()
        assert len(order) == 2
        assert order[0] == (LifecycleEventType.BEFORE_OPERATION, "op1")
        assert order[1] == (LifecycleEventType.AFTER_OPERATION, "op1")
    
    def test_reset_invocation_history(self):
        """Should reset invocation tracking."""
        manager = LifecycleManager()
        hook = SimpleLifecycleHook("hook")
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        
        event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        manager.dispatch_event(event)
        
        assert len(manager.get_invocation_order()) > 0
        
        manager.reset_invocation_history()
        assert len(manager.get_invocation_order()) == 0


class TestHookComposition:
    """Test composing multiple hooks together."""
    
    def test_multiple_hooks_same_event(self):
        """Multiple hooks should all be called for same event."""
        manager = LifecycleManager()
        
        hooks = [SimpleLifecycleHook(f"hook_{i}") for i in range(3)]
        for hook in hooks:
            manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        
        event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        manager.dispatch_event(event)
        
        for hook in hooks:
            assert len(hook.invocations) == 1
    
    def test_hook_chaining_events(self):
        """Hooks for different event types should fire in sequence."""
        manager = LifecycleManager()
        
        before_hook = SimpleLifecycleHook("before")
        after_hook = SimpleLifecycleHook("after")
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, before_hook)
        manager.register_hook(LifecycleEventType.AFTER_OPERATION, after_hook)
        
        before_event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        after_event = LifecycleEvent(LifecycleEventType.AFTER_OPERATION, "op", 2.0)
        
        manager.dispatch_event(before_event)
        manager.dispatch_event(after_event)
        
        order = manager.get_invocation_order()
        assert order[0][0] == LifecycleEventType.BEFORE_OPERATION
        assert order[1][0] == LifecycleEventType.AFTER_OPERATION
    
    def test_conditional_and_error_hooks_together(self):
        """Should support mixing different hook types."""
        manager = LifecycleManager()
        
        # Register conditional hook
        callback_calls = []
        conditional_hook = ConditionalHook(
            condition=lambda e: "error" not in e.operation_name,
            callback=lambda e: callback_calls.append(e),
        )
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, conditional_hook)
        
        # Register error hook
        error_hook = ErrorHandlingHook()
        manager.register_hook(LifecycleEventType.ON_ERROR, error_hook)
        
        # Dispatch events
        normal_event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "normal_op", 1.0)
        error_event = LifecycleEvent(
            LifecycleEventType.ON_ERROR,
            "error_op",
            2.0,
            data={"exception": RuntimeError("test")},
        )
        
        manager.dispatch_event(normal_event)
        manager.dispatch_event(error_event)
        
        # Conditional hook should have been called for normal event
        assert len(callback_calls) == 1
        # Error hook should have captured error
        assert len(error_hook.errors_caught) == 1


class TestLifecycleIntegration:
    """Integration tests for lifecycle management."""
    
    def test_operation_lifecycle_flow(self):
        """Should properly sequence lifecycle events for operation."""
        manager = LifecycleManager()
        
        before_hook = SimpleLifecycleHook("before")
        after_hook = SimpleLifecycleHook("after")
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, before_hook)
        manager.register_hook(LifecycleEventType.AFTER_OPERATION, after_hook)
        
        # Simulate operation lifecycle
        before_event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "process", 1.0)
        manager.dispatch_event(before_event)
        
        # ... operation happens ...
        
        after_event = LifecycleEvent(LifecycleEventType.AFTER_OPERATION, "process", 2.0)
        manager.dispatch_event(after_event)
        
        # Verify sequence
        assert before_hook.invocations[0].event_type == LifecycleEventType.BEFORE_OPERATION
        assert after_hook.invocations[0].event_type == LifecycleEventType.AFTER_OPERATION
    
    def test_error_recovery_lifecycle(self):
        """Should handle error events in lifecycle."""
        manager = LifecycleManager()
        
        before_hook = SimpleLifecycleHook("before")
        error_hook = ErrorHandlingHook()
        
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, before_hook)
        manager.register_hook(LifecycleEventType.ON_ERROR, error_hook)
        
        # Before operation
        before_event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        manager.dispatch_event(before_event)
        
        # Operation fails
        error = ValueError("operation failed")
        error_event = LifecycleEvent(
            LifecycleEventType.ON_ERROR,
            "op",
            2.0,
            data={"exception": error},
        )
        manager.dispatch_event(error_event)
        
        assert len(before_hook.invocations) == 1
        assert len(error_hook.errors_caught) == 1
    
    def test_multiple_operations_lifecycle(self):
        """Should handle multiple operations' lifecycles."""
        manager = LifecycleManager()
        
        hook = SimpleLifecycleHook("tracker")
        manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
        manager.register_hook(LifecycleEventType.AFTER_OPERATION, hook)
        
        # Operation 1
        event_b1 = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op1", 1.0)
        event_a1 = LifecycleEvent(LifecycleEventType.AFTER_OPERATION, "op1", 2.0)
        
        # Operation 2
        event_b2 = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op2", 3.0)
        event_a2 = LifecycleEvent(LifecycleEventType.AFTER_OPERATION, "op2", 4.0)
        
        for event in [event_b1, event_a1, event_b2, event_a2]:
            manager.dispatch_event(event)
        
        # All events should be tracked
        assert len(hook.invocations) == 4
        
        # Correct order
        order = manager.get_invocation_order()
        assert order[0][1] == "op1"
        assert order[1][1] == "op1"
        assert order[2][1] == "op2"
        assert order[3][1] == "op2"
    
    def test_lifecycle_manager_isolation(self):
        """Different managers should maintain separate hook lists."""
        manager1 = LifecycleManager()
        manager2 = LifecycleManager()
        
        hook1 = SimpleLifecycleHook("hook1")
        hook2 = SimpleLifecycleHook("hook2")
        
        manager1.register_hook(LifecycleEventType.BEFORE_OPERATION, hook1)
        manager2.register_hook(LifecycleEventType.BEFORE_OPERATION, hook2)
        
        event = LifecycleEvent(LifecycleEventType.BEFORE_OPERATION, "op", 1.0)
        
        manager1.dispatch_event(event)
        
        assert len(hook1.invocations) == 1
        assert len(hook2.invocations) == 0
