"""Lifecycle Hooks Framework - Production Implementation

Provides a consolidated lifecycle management system for the optimizer ecosystem.
Supports flexible hook composition, error handling, and event tracking.

Key Features:
- Event-driven architecture with 5 standard lifecycle events
- Hook registration, removal, and composition patterns  
- Error handling and recovery support
- Operation-level tracking with invocation ordering
- Extensible for custom hook types

Usage Example:
    manager = LifecycleManager()
    
    # Register hooks
    hook = SimpleLifecycleHook("my_hook")
    manager.register_hook(LifecycleEventType.BEFORE_OPERATION, hook)
    
    # Dispatch events
    event = LifecycleEvent(
        event_type=LifecycleEventType.BEFORE_OPERATION,
        operation_name="process_data",
        timestamp=time.time(),
        data={"items": 100}
    )
    manager.dispatch_event(event)

"""

import time
from typing import Callable, List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from contextlib import contextmanager


class LifecycleEventType(Enum):
    """Standard lifecycle event types for operation management."""
    BEFORE_OPERATION = "before_operation"
    AFTER_OPERATION = "after_operation"
    ON_ERROR = "on_error"
    ON_COMPLETE = "on_complete"
    ON_TIMEOUT = "on_timeout"


@dataclass
class LifecycleEvent:
    """Represents a discrete lifecycle event in an operation's timeline.
    
    Attributes:
        event_type: Type of lifecycle event
        operation_name: Name/identifier of the operation
        timestamp: Unix timestamp when event occurred
        data: Arbitrary event-specific data (errors, metrics, etc.)
    """
    event_type: LifecycleEventType
    operation_name: str
    timestamp: float
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize event to dictionary for logging/export."""
        return {
            "event_type": self.event_type.value,
            "operation_name": self.operation_name,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class LifecycleHook(ABC):
    """Abstract base class for all lifecycle hooks.
    
    Subclasses must implement handle() to process lifecycle events.
    """
    
    @abstractmethod
    def handle(self, event: LifecycleEvent) -> None:
        """Process a lifecycle event.
        
        Args:
            event: The lifecycle event to handle
        """
        pass


class SimpleLifecycleHook(LifecycleHook):
    """Basic hook that records all invocations for inspection.
    
    Useful for testing and debugging lifecycle flows.
    """
    
    def __init__(self, name: str):
        """Initialize the hook with a name.
        
        Args:
            name: Identifier for this hook instance
        """
        self.name = name
        self.invocations: List[LifecycleEvent] = []
    
    def handle(self, event: LifecycleEvent) -> None:
        """Record event in invocation history."""
        self.invocations.append(event)
    
    def reset(self) -> None:
        """Clear invocation history."""
        self.invocations = []


class ConditionalHook(LifecycleHook):
    """Hook that fires only when a condition is satisfied.
    
    Allows selective event processing based on arbitrary predicates.
    """
    
    def __init__(self, condition: Callable[[LifecycleEvent], bool],
                 callback: Callable[[LifecycleEvent], None]):
        """Initialize with condition and callback.
        
        Args:
            condition: Predicate to test event against
            callback: Function to invoke if condition is true
        """
        self.condition = condition
        self.callback = callback
        self.invocations: List[LifecycleEvent] = []
    
    def handle(self, event: LifecycleEvent) -> None:
        """Call callback only if condition is satisfied."""
        if self.condition(event):
            self.callback(event)
            self.invocations.append(event)


class ErrorHandlingHook(LifecycleHook):
    """Specialized hook for capturing and tracking errors."""
    
    def __init__(self):
        """Initialize error tracking."""
        self.errors_caught: List[Tuple[LifecycleEvent, Exception]] = []
    
    def handle(self, event: LifecycleEvent) -> None:
        """Capture errors from ON_ERROR events."""
        if event.event_type == LifecycleEventType.ON_ERROR:
            error = event.data.get("exception")
            if error and isinstance(error, Exception):
                self.errors_caught.append((event, error))


class CallbackHook(LifecycleHook):
    """Simple hook that invokes a callback for all events.
    
    Useful for side effects like logging, metrics collection, etc.
    """
    
    def __init__(self, callback: Callable[[LifecycleEvent], None]):
        """Initialize with callback function.
        
        Args:
            callback: Function to invoke for each event
        """
        self.callback = callback
        self.call_count = 0
    
    def handle(self, event: LifecycleEvent) -> None:
        """Invoke callback."""
        self.callback(event)
        self.call_count += 1


class LifecycleManager:
    """Central manager for lifecycle hooks across operations.
    
    Orchestrates hook registration, event dispatch, and tracking.
    Provides isolation between different operation contexts.
    """
    
    def __init__(self):
        """Initialize empty hook registry and tracking."""
        self.hooks: Dict[LifecycleEventType, List[LifecycleHook]] = {
            event_type: [] for event_type in LifecycleEventType
        }
        self.invocation_order: List[Tuple[LifecycleEventType, str]] = []
    
    def register_hook(self, event_type: LifecycleEventType, 
                      hook: LifecycleHook) -> None:
        """Register a hook for a specific event type.
        
        Args:
            event_type: Type of event this hook handles
            hook: The hook instance
            
        Raises:
            TypeError: If hook is not a LifecycleHook instance
        """
        if not isinstance(hook, LifecycleHook):
            raise TypeError(f"Hook must be instance of LifecycleHook, got {type(hook)}")
        self.hooks[event_type].append(hook)
    
    def remove_hook(self, event_type: LifecycleEventType, 
                    hook: LifecycleHook) -> bool:
        """Remove a previously registered hook.
        
        Args:
            event_type: Event type the hook was registered for
            hook: The hook instance to remove
            
        Returns:
            True if hook was found and removed, False otherwise
        """
        if hook in self.hooks[event_type]:
            self.hooks[event_type].remove(hook)
            return True
        return False
    
    def clear_hooks(self, event_type: Optional[LifecycleEventType] = None) -> None:
        """Clear hooks for all events or a specific type.
        
        Args:
            event_type: If None, clears all hooks. Otherwise clears hooks
                       for the specified event type.
        """
        if event_type is None:
            for hooks_list in self.hooks.values():
                hooks_list.clear()
        else:
            self.hooks[event_type].clear()
    
    def get_hooks(self, event_type: LifecycleEventType) -> List[LifecycleHook]:
        """Get all hooks registered for an event type.
        
        Args:
            event_type: The event type to query
            
        Returns:
            Copy of hooks list for event type
        """
        return self.hooks[event_type].copy()
    
    def dispatch_event(self, event: LifecycleEvent) -> None:
        """Dispatch an event to all registered hooks.
        
        Calls all hooks registered for the event type in order.
        Tracks invocation for debugging/testing purposes.
        
        Args:
            event: The lifecycle event to dispatch
        """
        hooks = self.hooks.get(event.event_type, [])
        self.invocation_order.append((event.event_type, event.operation_name))
        
        for hook in hooks:
            hook.handle(event)
    
    def get_invocation_order(self) -> List[Tuple[LifecycleEventType, str]]:
        """Get chronological order of hook invocations.
        
        Returns:
            List of (event_type, operation_name) tuples in dispatch order
        """
        return self.invocation_order.copy()
    
    def reset_invocation_history(self) -> None:
        """Clear invocation tracking for fresh test/analysis."""
        self.invocation_order = []
    
    @contextmanager
    def operation_lifecycle(self, operation_name: str, 
                           data: Optional[Dict[str, Any]] = None):
        """Context manager for automatic lifecycle event dispatch.
        
        Automatically fires BEFORE_OPERATION and AFTER_OPERATION events.
        If exception occurs, fires ON_ERROR event instead of AFTER.
        
        Args:
            operation_name: Name of the operation
            data: Optional initial data for BEFORE event
            
        Yields:
            Dict that can be modified to update event data
            
        Example:
            with manager.operation_lifecycle("extract_entities") as ctx:
                ctx["item_count"] = 100
                # ... operation code ...
        """
        event_data = data or {}
        
        # Dispatch BEFORE event
        before_event = LifecycleEvent(
            event_type=LifecycleEventType.BEFORE_OPERATION,
            operation_name=operation_name,
            timestamp=time.time(),
            data=event_data,
        )
        self.dispatch_event(before_event)
        
        try:
            yield event_data
        except Exception as e:
            # Dispatch error event
            error_event = LifecycleEvent(
                event_type=LifecycleEventType.ON_ERROR,
                operation_name=operation_name,
                timestamp=time.time(),
                data={"exception": e, **event_data},
            )
            self.dispatch_event(error_event)
            raise
        else:
            # Dispatch AFTER event on success
            after_event = LifecycleEvent(
                event_type=LifecycleEventType.AFTER_OPERATION,
                operation_name=operation_name,
                timestamp=time.time(),
                data=event_data,
            )
            self.dispatch_event(after_event)
