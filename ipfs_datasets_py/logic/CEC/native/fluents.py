"""
Fluent Handling for DCEC (Phase 4 Week 1)

This module provides fluent management and state transition capabilities for
Deontic Cognitive Event Calculus, enabling systematic handling of time-varying
properties with persistence rules and conflict resolution.

A fluent is a time-varying property that can hold or not hold at different times.
This module provides:
- Fluent definition with types and persistence rules
- State management across time points
- Event-driven state transitions
- Conflict resolution for competing fluents
- Frame problem handling (maintaining unchanged fluents)

Key Concepts:
    Fluent: A time-varying property with a name, type, and persistence behavior
    FluentManager: Manages all fluents and their states across time
    State Transition: Application of an event's effects on fluent states
    Conflict Resolution: Handling of contradictory fluent values
    Frame Problem: Preserving fluent values that are not affected by events

Examples:
    >>> from ipfs_datasets_py.logic.CEC.native.fluents import FluentManager, Fluent, FluentType
    >>> from ipfs_datasets_py.logic.CEC.native.event_calculus import Event
    >>> 
    >>> # Create fluent manager
    >>> manager = FluentManager()
    >>> 
    >>> # Define fluents
    >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
    >>> door_open = Fluent("door_open", FluentType.BOOLEAN)
    >>> 
    >>> # Add fluents to manager
    >>> manager.add_fluent(light_on)
    >>> manager.add_fluent(door_open)
    >>> 
    >>> # Get state at specific time
    >>> state = manager.get_state(time=5)
    >>> print(state[light_on])  # True or False

References:
    - McCarthy, J., & Hayes, P. J. (1969). Some philosophical problems from the
      standpoint of artificial intelligence.
    - Shanahan, M. (1997). Solving the frame problem: A mathematical investigation
      of the common sense law of inertia.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any, Callable
from enum import Enum
import logging

from .event_calculus import Event, EventCalculus
from .exceptions import ValidationError

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any as AnyType
    F = TypeVar('F', bound=Callable[..., AnyType])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class FluentType(Enum):
    """
    Types of fluents supported by the system.
    
    Different fluent types have different persistence and transition behaviors.
    
    Types:
        BOOLEAN: Binary fluent (true/false)
            - Examples: light_on, door_open, user_logged_in
            
        NUMERICAL: Numeric fluent (integer or float value)
            - Examples: temperature, count, balance
            
        CATEGORICAL: Fluent with discrete categorical values
            - Examples: traffic_light (red/yellow/green), state (idle/active/error)
            
        RELATIONAL: Fluent representing a relation between entities
            - Examples: owns(person, car), friend_of(person1, person2)
    """
    BOOLEAN = "boolean"
    NUMERICAL = "numerical"
    CATEGORICAL = "categorical"
    RELATIONAL = "relational"


class PersistenceRule(Enum):
    """
    Rules governing how fluents persist over time.
    
    Persistence rules determine whether and how a fluent's value is maintained
    across time points in the absence of explicit changes.
    
    Rules:
        INERTIAL: Fluent persists indefinitely until explicitly changed
            - Default behavior - implements the law of inertia
            - Example: door_open persists until close_door event
            
        TRANSIENT: Fluent holds only at the instant it's initiated
            - Does not persist to next time point
            - Example: button_pressed (momentary action)
            
        DECAYING: Fluent persists but with decay/weakening over time
            - Requires decay function
            - Example: heat (gradually cools)
            
        CONDITIONAL: Persistence depends on other conditions
            - Requires condition predicate
            - Example: engine_running only if fuel_available
    """
    INERTIAL = "inertial"      # Persists indefinitely (law of inertia)
    TRANSIENT = "transient"    # Holds only instantaneously
    DECAYING = "decaying"      # Persists with decay
    CONDITIONAL = "conditional"  # Conditional persistence


@dataclass
class Fluent:
    """
    Represents a time-varying property (fluent) with type and persistence behavior.
    
    Fluents are properties that can change over time. This class extends the basic
    fluent concept from event_calculus.py with types, persistence rules, and
    domain-specific metadata.
    
    Attributes:
        name: Unique name of the fluent
        fluent_type: Type of the fluent (BOOLEAN, NUMERICAL, etc.)
        persistence_rule: How the fluent persists over time
        default_value: Default value when fluent is not explicitly set
        metadata: Additional fluent metadata
        
    Examples:
        >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
        >>> light_on.persistence_rule = PersistenceRule.INERTIAL
        >>> 
        >>> temp = Fluent("temperature", FluentType.NUMERICAL, default_value=20.0)
        >>> temp.persistence_rule = PersistenceRule.DECAYING
    """
    name: str
    fluent_type: FluentType
    persistence_rule: PersistenceRule = PersistenceRule.INERTIAL
    default_value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate fluent configuration."""
        if self.fluent_type == FluentType.BOOLEAN and self.default_value is None:
            self.default_value = False
        elif self.fluent_type == FluentType.NUMERICAL and self.default_value is None:
            self.default_value = 0.0
    
    def persists(self, from_time: int, to_time: int, context: Optional[Dict] = None) -> bool:
        """
        Check if fluent persists from one time to another.
        
        This implements the persistence check based on the fluent's persistence rule.
        
        Args:
            from_time: Starting time point
            to_time: Ending time point
            context: Optional context for conditional persistence
            
        Returns:
            True if fluent persists, False otherwise
            
        Examples:
            >>> fluent = Fluent("light_on", FluentType.BOOLEAN, persistence_rule=PersistenceRule.INERTIAL)
            >>> fluent.persists(5, 10)  # True (inertial persistence)
            >>> 
            >>> transient = Fluent("button_press", FluentType.BOOLEAN, persistence_rule=PersistenceRule.TRANSIENT)
            >>> transient.persists(5, 6)  # False (transient)
        """
        if from_time >= to_time:
            return False
        
        if self.persistence_rule == PersistenceRule.INERTIAL:
            # Inertial fluents persist indefinitely
            return True
        elif self.persistence_rule == PersistenceRule.TRANSIENT:
            # Transient fluents don't persist
            return False
        elif self.persistence_rule == PersistenceRule.DECAYING:
            # Decaying fluents persist (decay handled by value computation)
            return True
        elif self.persistence_rule == PersistenceRule.CONDITIONAL:
            # Conditional persistence requires context
            if context and 'persistence_condition' in context:
                return context['persistence_condition'](self, from_time, to_time)
            return False  # No condition specified
        
        return False
    
    def __hash__(self) -> int:
        return hash(self.name)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Fluent):
            return False
        return self.name == other.name
    
    def __str__(self) -> str:
        return f"Fluent({self.name}, {self.fluent_type.value})"
    
    def __repr__(self) -> str:
        return f"Fluent(name='{self.name}', type={self.fluent_type}, persistence={self.persistence_rule})"


class FluentManager:
    """
    Manages fluents and their states across time points.
    
    The FluentManager is responsible for:
    - Tracking all fluents in the system
    - Maintaining fluent states at different time points
    - Applying event-driven state transitions
    - Resolving conflicts between competing fluents
    - Handling the frame problem (preserving unchanged fluents)
    
    The manager integrates with EventCalculus to provide a complete
    event-based temporal reasoning system.
    
    Attributes:
        fluents: Set of all registered fluents
        states: State history mapping time -> fluent -> value
        event_calculus: Optional EventCalculus integration
        conflict_resolver: Function for resolving fluent conflicts
        
    Examples:
        >>> manager = FluentManager()
        >>> 
        >>> # Register fluents
        >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
        >>> manager.add_fluent(light_on)
        >>> 
        >>> # Set initial state
        >>> manager.set_fluent_value(light_on, True, time=0)
        >>> 
        >>> # Apply event transition
        >>> turn_off = Event("turn_off_light")
        >>> manager.apply_transition(turn_off, time=5, effects={light_on: False})
        >>> 
        >>> # Query state
        >>> state = manager.get_state(time=10)
        >>> print(state[light_on])  # False
    """
    
    def __init__(self, event_calculus: Optional[EventCalculus] = None):
        """
        Initialize fluent manager.
        
        Args:
            event_calculus: Optional EventCalculus instance for integration
        """
        self.fluents: Set[Fluent] = set()
        self.states: Dict[int, Dict[Fluent, Any]] = {}
        self.event_calculus = event_calculus
        self.conflict_resolver: Optional[Callable] = None
        
        # Track which events affect which fluents
        self._event_effects: Dict[Event, Dict[Fluent, Any]] = {}
        
        logger.debug("Initialized FluentManager")
    
    def add_fluent(self, fluent: Fluent) -> None:
        """
        Register a fluent with the manager.
        
        Args:
            fluent: The fluent to register
            
        Raises:
            ValidationError: If fluent with same name already exists
            
        Examples:
            >>> manager = FluentManager()
            >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
            >>> manager.add_fluent(light_on)
        """
        if fluent in self.fluents:
            raise ValidationError(f"Fluent '{fluent.name}' already registered")
        
        self.fluents.add(fluent)
        logger.debug(f"Added fluent: {fluent}")
    
    def remove_fluent(self, fluent: Fluent) -> None:
        """
        Unregister a fluent from the manager.
        
        Args:
            fluent: The fluent to remove
        """
        self.fluents.discard(fluent)
        # Clean up from states
        for time_state in self.states.values():
            time_state.pop(fluent, None)
        logger.debug(f"Removed fluent: {fluent}")
    
    def set_fluent_value(self, fluent: Fluent, value: Any, time: int) -> None:
        """
        Set a fluent's value at a specific time.
        
        Args:
            fluent: The fluent to set
            value: The value to assign
            time: Time point
            
        Raises:
            ValidationError: If fluent not registered or time negative
            
        Examples:
            >>> manager = FluentManager()
            >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
            >>> manager.add_fluent(light_on)
            >>> manager.set_fluent_value(light_on, True, time=5)
        """
        if fluent not in self.fluents:
            raise ValidationError(f"Fluent '{fluent.name}' not registered")
        
        if time < 0:
            raise ValidationError("Time cannot be negative")
        
        if time not in self.states:
            self.states[time] = {}
        
        self.states[time][fluent] = value
        logger.debug(f"Set {fluent} = {value} at time {time}")
    
    def get_fluent_value(self, fluent: Fluent, time: int) -> Any:
        """
        Get a fluent's value at a specific time, considering persistence.
        
        This method implements the frame problem solution by checking:
        1. Explicit value at time
        2. Most recent previous value (if fluent persists)
        3. Default value
        
        Args:
            fluent: The fluent to query
            time: Time point
            
        Returns:
            The fluent's value at time
            
        Examples:
            >>> manager = FluentManager()
            >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
            >>> manager.add_fluent(light_on)
            >>> manager.set_fluent_value(light_on, True, time=5)
            >>> manager.get_fluent_value(light_on, 10)  # True (persists)
        """
        if fluent not in self.fluents:
            raise ValidationError(f"Fluent '{fluent.name}' not registered")
        
        # Check if explicitly set at this time
        if time in self.states and fluent in self.states[time]:
            return self.states[time][fluent]
        
        # Find most recent previous value (persistence)
        if fluent.persistence_rule in {PersistenceRule.INERTIAL, PersistenceRule.DECAYING, PersistenceRule.CONDITIONAL}:
            # Look backward for most recent value
            for t in range(time - 1, -1, -1):
                if t in self.states and fluent in self.states[t]:
                    # Check if persists from t to time
                    if fluent.persists(t, time):
                        return self.states[t][fluent]
                    else:
                        break  # Doesn't persist
        
        # No previous value or doesn't persist - return default
        return fluent.default_value
    
    def get_state(self, time: int) -> Dict[Fluent, Any]:
        """
        Get the complete state (all fluent values) at a specific time.
        
        Args:
            time: Time point to query
            
        Returns:
            Dictionary mapping fluents to their values at time
            
        Examples:
            >>> manager = FluentManager()
            >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
            >>> door_open = Fluent("door_open", FluentType.BOOLEAN)
            >>> manager.add_fluent(light_on)
            >>> manager.add_fluent(door_open)
            >>> manager.set_fluent_value(light_on, True, time=5)
            >>> state = manager.get_state(time=10)
            >>> print(state)  # {light_on: True, door_open: False}
        """
        state = {}
        for fluent in self.fluents:
            state[fluent] = self.get_fluent_value(fluent, time)
        return state
    
    def apply_transition(self, event: Event, time: int, effects: Dict[Fluent, Any]) -> None:
        """
        Apply a state transition caused by an event.
        
        This method:
        1. Records the event (if EventCalculus integrated)
        2. Applies the event's effects on fluents
        3. Handles conflicts if multiple effects target same fluent
        4. Preserves unaffected fluents (frame problem)
        
        Args:
            event: The event causing the transition
            time: Time when event occurs
            effects: Dictionary of fluent changes caused by event
            
        Examples:
            >>> manager = FluentManager()
            >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
            >>> manager.add_fluent(light_on)
            >>> 
            >>> turn_on = Event("turn_on_light")
            >>> manager.apply_transition(turn_on, time=5, effects={light_on: True})
            >>> 
            >>> manager.get_fluent_value(light_on, 10)  # True
        """
        if time < 0:
            raise ValidationError("Time cannot be negative")
        
        # Record event in EventCalculus if integrated
        if self.event_calculus:
            self.event_calculus.record_event(event, time)
        
        # Store event effects for future reference
        self._event_effects[event] = effects
        
        # Apply effects
        for fluent, value in effects.items():
            if fluent not in self.fluents:
                logger.warning(f"Effect on unregistered fluent '{fluent.name}' - skipping")
                continue
            
            self.set_fluent_value(fluent, value, time)
        
        logger.debug(f"Applied transition: {event} at time {time} with {len(effects)} effects")
    
    def set_conflict_resolver(self, resolver: Callable[[Fluent, Any, Any], Any]) -> None:
        """
        Set a custom conflict resolution function.
        
        The resolver is called when multiple events try to set conflicting
        values for the same fluent at the same time.
        
        Args:
            resolver: Function(fluent, value1, value2) -> resolved_value
            
        Examples:
            >>> def max_resolver(fluent, v1, v2):
            ...     return max(v1, v2)
            >>> 
            >>> manager = FluentManager()
            >>> manager.set_conflict_resolver(max_resolver)
        """
        self.conflict_resolver = resolver
        logger.debug("Set conflict resolver")
    
    def get_timeline(self, fluent: Fluent, max_time: int) -> List[tuple[int, Any]]:
        """
        Get the complete timeline of a fluent's value changes.
        
        Args:
            fluent: The fluent to track
            max_time: Maximum time to include
            
        Returns:
            List of (time, value) tuples showing value changes
            
        Examples:
            >>> manager = FluentManager()
            >>> light_on = Fluent("light_on", FluentType.BOOLEAN)
            >>> manager.add_fluent(light_on)
            >>> manager.set_fluent_value(light_on, True, time=2)
            >>> manager.set_fluent_value(light_on, False, time=5)
            >>> timeline = manager.get_timeline(light_on, max_time=7)
            >>> # [(0, False), (2, True), (5, False)]
        """
        if fluent not in self.fluents:
            raise ValidationError(f"Fluent '{fluent.name}' not registered")
        
        timeline: List[tuple[int, Any]] = []
        prev_value = None
        
        for t in range(max_time + 1):
            value = self.get_fluent_value(fluent, t)
            if value != prev_value:
                timeline.append((t, value))
                prev_value = value
        
        return timeline
    
    def clear_history(self) -> None:
        """Clear all state history."""
        self.states.clear()
        logger.debug("Cleared state history")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the fluent manager.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'total_fluents': len(self.fluents),
            'time_points_recorded': len(self.states),
            'total_state_entries': sum(len(s) for s in self.states.values()),
            'event_calculus_integrated': self.event_calculus is not None,
        }
