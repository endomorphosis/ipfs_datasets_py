"""
Event Calculus for DCEC (Phase 4 Week 1)

This module provides event calculus primitives for reasoning about events,
fluents, and their interactions over time in Deontic Cognitive Event Calculus.

Event Calculus is a logical formalism for representing and reasoning about
actions/events and their effects on fluents (time-varying properties).

Features:
- Event occurrence tracking (Happens)
- Fluent initiation and termination (Initiates, Terminates)
- Fluent persistence (HoldsAt)
- Clipping detection (Clipped)
- Frame problem handling

Key Concepts:
    Event: An occurrence at a specific time point
    Fluent: A time-varying property that can hold or not hold
    Happens(e, t): Event e occurs at time t
    Initiates(e, f, t): Event e initiates fluent f at time t
    Terminates(e, f, t): Event e terminates fluent f at time t
    HoldsAt(f, t): Fluent f holds at time t
    Clipped(t1, f, t2): Fluent f is terminated between t1 and t2

Examples:
    >>> from ipfs_datasets_py.logic.CEC.native.event_calculus import EventCalculus, Event, Fluent
    >>> 
    >>> # Create event calculus
    >>> ec = EventCalculus()
    >>> 
    >>> # Define events and fluents
    >>> turn_on = Event("turn_on_light")
    >>> light_on = Fluent("light_on")
    >>> 
    >>> # Specify that turning on light initiates light being on
    >>> ec.add_initiation_rule(turn_on, light_on)
    >>> 
    >>> # Record event occurrence
    >>> ec.record_event(turn_on, time=1)
    >>> 
    >>> # Check if light is on at time 2
    >>> ec.holds_at(light_on, time=2)  # True

References:
    - Kowalski, R. A., & Sergot, M. J. (1986). A logic-based calculus of events.
    - Mueller, E. T. (2014). Commonsense reasoning (2nd ed.).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Any
from enum import Enum
import logging

from .exceptions import ValidationError

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any as AnyType
    F = TypeVar('F', bound=Callable[..., AnyType])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True)
class Event:
    """
    Represents an event that occurs at a point in time.
    
    Events are instantaneous occurrences that can initiate or terminate
    fluents. Examples: turning on a light, opening a door, sending a message.
    
    Attributes:
        name: Name/type of the event
        parameters: Optional parameters for parameterized events
    
    Examples:
        >>> turn_on = Event("turn_on_light")
        >>> open_door = Event("open", parameters=("front_door",))
    """
    name: str
    parameters: Tuple[Any, ...] = field(default_factory=tuple)
    
    def __str__(self) -> str:
        if self.parameters:
            params_str = ", ".join(str(p) for p in self.parameters)
            return f"{self.name}({params_str})"
        return self.name


@dataclass(frozen=True, eq=True)
class Fluent:
    """
    Represents a time-varying property (fluent).
    
    Fluents are properties that can hold or not hold at different times.
    They are initiated by events and persist until terminated.
    Examples: light_on, door_open, user_logged_in.
    
    Attributes:
        name: Name of the fluent
        parameters: Optional parameters for parameterized fluents
    
    Examples:
        >>> light_on = Fluent("light_on")
        >>> door_open = Fluent("open", parameters=("front_door",))
    """
    name: str
    parameters: Tuple[Any, ...] = field(default_factory=tuple)
    
    def __str__(self) -> str:
        if self.parameters:
            params_str = ", ".join(str(p) for p in self.parameters)
            return f"{self.name}({params_str})"
        return self.name


class TimePoint:
    """
    Represents a discrete time point.
    
    Time is discrete and ordered, represented as integers.
    
    Attributes:
        value: Integer time value
    """
    
    def __init__(self, value: int):
        """
        Initialize time point.
        
        Args:
            value: Integer time value
            
        Raises:
            ValidationError: If value is negative
        """
        if value < 0:
            raise ValidationError("Time cannot be negative")
        self.value = value
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimePoint):
            return False
        return self.value == other.value
    
    def __lt__(self, other: 'TimePoint') -> bool:
        return self.value < other.value
    
    def __le__(self, other: 'TimePoint') -> bool:
        return self.value <= other.value
    
    def __gt__(self, other: 'TimePoint') -> bool:
        return self.value > other.value
    
    def __ge__(self, other: 'TimePoint') -> bool:
        return self.value >= other.value
    
    def __hash__(self) -> int:
        return hash(self.value)
    
    def __str__(self) -> str:
        return f"t{self.value}"
    
    def __repr__(self) -> str:
        return f"TimePoint({self.value})"


class EventCalculus:
    """
    Event Calculus reasoning system.
    
    This class implements the core event calculus predicates and reasoning
    mechanisms for tracking events, fluents, and their temporal relationships.
    
    Predicates:
        happens(e, t): Event e occurs at time t
        initiates(e, f, t): Event e initiates fluent f at time t
        terminates(e, f, t): Event e terminates fluent f at time t
        holds_at(f, t): Fluent f holds at time t
        clipped(t1, f, t2): Fluent f is terminated between t1 and t2
    
    Examples:
        >>> ec = EventCalculus()
        >>> 
        >>> # Define domain
        >>> turn_on = Event("turn_on")
        >>> turn_off = Event("turn_off")
        >>> light_on = Fluent("light_on")
        >>> 
        >>> # Add causal rules
        >>> ec.add_initiation_rule(turn_on, light_on)
        >>> ec.add_termination_rule(turn_off, light_on)
        >>> 
        >>> # Record event occurrences
        >>> ec.record_event(turn_on, time=1)
        >>> ec.record_event(turn_off, time=5)
        >>> 
        >>> # Query fluent status
        >>> ec.holds_at(light_on, time=3)  # True (after turn_on, before turn_off)
        >>> ec.holds_at(light_on, time=6)  # False (after turn_off)
    """
    
    def __init__(self):
        """Initialize event calculus reasoning system."""
        # Event occurrences: {(event, time_value)}
        self._event_occurrences: Set[Tuple[Event, int]] = set()
        
        # Initiation rules: {(event, fluent): True}
        self._initiation_rules: Dict[Tuple[Event, Fluent], bool] = {}
        
        # Termination rules: {(event, fluent): True}
        self._termination_rules: Dict[Tuple[Event, Fluent], bool] = {}
        
        # Initially true fluents: {fluent: True}
        self._initially_true: Set[Fluent] = set()
        
        # Cache for holds_at queries
        self._holds_at_cache: Dict[Tuple[Fluent, int], bool] = {}
        
        logger.debug("Initialized EventCalculus")
    
    def record_event(self, event: Event, time: int) -> None:
        """
        Record that an event occurs at a specific time.
        
        Implements: Happens(event, time)
        
        Args:
            event: The event that occurs
            time: Time point when event occurs
            
        Raises:
            ValidationError: If time is negative
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> ec.record_event(turn_on, time=5)
            >>> ec.happens(turn_on, 5)  # True
        """
        if time < 0:
            raise ValidationError("Time cannot be negative")
        
        self._event_occurrences.add((event, time))
        # Invalidate cache since new event affects fluent persistence
        self._holds_at_cache.clear()
        logger.debug(f"Recorded event: {event} at time {time}")
    
    def happens(self, event: Event, time: int) -> bool:
        """
        Check if an event occurs at a specific time.
        
        Implements: Happens(event, time)
        
        Args:
            event: The event to check
            time: Time point to check
            
        Returns:
            True if event occurs at time, False otherwise
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> ec.record_event(turn_on, time=5)
            >>> ec.happens(turn_on, 5)  # True
            >>> ec.happens(turn_on, 6)  # False
        """
        return (event, time) in self._event_occurrences
    
    def add_initiation_rule(self, event: Event, fluent: Fluent) -> None:
        """
        Add a rule specifying that an event initiates a fluent.
        
        Implements: Initiates(event, fluent, time)
        
        Args:
            event: Event that initiates the fluent
            fluent: Fluent that is initiated
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> light_on = Fluent("light_on")
            >>> ec.add_initiation_rule(turn_on, light_on)
        """
        self._initiation_rules[(event, fluent)] = True
        self._holds_at_cache.clear()
        logger.debug(f"Added initiation rule: {event} initiates {fluent}")
    
    def initiates(self, event: Event, fluent: Fluent, time: int) -> bool:
        """
        Check if an event initiates a fluent at a specific time.
        
        Implements: Initiates(event, fluent, time)
        
        Args:
            event: The event
            fluent: The fluent
            time: Time point
            
        Returns:
            True if event initiates fluent at time, False otherwise
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> light_on = Fluent("light_on")
            >>> ec.add_initiation_rule(turn_on, light_on)
            >>> ec.record_event(turn_on, time=5)
            >>> ec.initiates(turn_on, light_on, 5)  # True
        """
        # Check if there's an initiation rule and event happens at time
        return (event, fluent) in self._initiation_rules and self.happens(event, time)
    
    def add_termination_rule(self, event: Event, fluent: Fluent) -> None:
        """
        Add a rule specifying that an event terminates a fluent.
        
        Implements: Terminates(event, fluent, time)
        
        Args:
            event: Event that terminates the fluent
            fluent: Fluent that is terminated
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_off = Event("turn_off")
            >>> light_on = Fluent("light_on")
            >>> ec.add_termination_rule(turn_off, light_on)
        """
        self._termination_rules[(event, fluent)] = True
        self._holds_at_cache.clear()
        logger.debug(f"Added termination rule: {event} terminates {fluent}")
    
    def terminates(self, event: Event, fluent: Fluent, time: int) -> bool:
        """
        Check if an event terminates a fluent at a specific time.
        
        Implements: Terminates(event, fluent, time)
        
        Args:
            event: The event
            fluent: The fluent
            time: Time point
            
        Returns:
            True if event terminates fluent at time, False otherwise
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_off = Event("turn_off")
            >>> light_on = Fluent("light_on")
            >>> ec.add_termination_rule(turn_off, light_on)
            >>> ec.record_event(turn_off, time=5)
            >>> ec.terminates(turn_off, light_on, 5)  # True
        """
        # Check if there's a termination rule and event happens at time
        return (event, fluent) in self._termination_rules and self.happens(event, time)
    
    def set_initially_true(self, fluent: Fluent) -> None:
        """
        Specify that a fluent is initially true (at time 0).
        
        Args:
            fluent: The fluent that is initially true
        
        Examples:
            >>> ec = EventCalculus()
            >>> door_closed = Fluent("door_closed")
            >>> ec.set_initially_true(door_closed)
            >>> ec.holds_at(door_closed, 0)  # True
        """
        self._initially_true.add(fluent)
        self._holds_at_cache.clear()
        logger.debug(f"Set initially true: {fluent}")
    
    def clipped(self, t1: int, fluent: Fluent, t2: int) -> bool:
        """
        Check if a fluent is clipped (terminated) between two time points.
        
        Implements: Clipped(t1, fluent, t2)
        
        A fluent is clipped between t1 and t2 if there exists a time t such that:
        t1 < t < t2 and some event terminates the fluent at t.
        
        Args:
            t1: Start time
            fluent: The fluent to check
            t2: End time
            
        Returns:
            True if fluent is clipped between t1 and t2, False otherwise
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_off = Event("turn_off")
            >>> light_on = Fluent("light_on")
            >>> ec.add_termination_rule(turn_off, light_on)
            >>> ec.record_event(turn_off, time=5)
            >>> ec.clipped(3, light_on, 7)  # True (terminated at 5)
        """
        if t1 >= t2:
            return False
        
        # Check all events in the interval (t1, t2)
        for event, time in self._event_occurrences:
            if t1 < time < t2:
                if self.terminates(event, fluent, time):
                    return True
        
        return False
    
    def holds_at(self, fluent: Fluent, time: int) -> bool:
        """
        Check if a fluent holds at a specific time.
        
        Implements: HoldsAt(fluent, time)
        
        A fluent holds at time t if:
        1. It was initiated at some time t' < t, AND
        2. It was not clipped between t' and t
        
        Or:
        3. It is initially true (at time 0) and not clipped between 0 and t
        
        Args:
            fluent: The fluent to check
            time: Time point to check
            
        Returns:
            True if fluent holds at time, False otherwise
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> light_on = Fluent("light_on")
            >>> ec.add_initiation_rule(turn_on, light_on)
            >>> ec.record_event(turn_on, time=2)
            >>> ec.holds_at(light_on, 1)  # False (before turn_on)
            >>> ec.holds_at(light_on, 3)  # True (after turn_on)
        """
        # Check cache
        cache_key = (fluent, time)
        if cache_key in self._holds_at_cache:
            return self._holds_at_cache[cache_key]
        
        result = self._compute_holds_at(fluent, time)
        self._holds_at_cache[cache_key] = result
        return result
    
    def _compute_holds_at(self, fluent: Fluent, time: int) -> bool:
        """Compute holds_at without caching."""
        # Find all times when fluent was initiated before time
        initiation_times: List[int] = []
        
        for event, event_time in self._event_occurrences:
            if event_time < time and self.initiates(event, fluent, event_time):
                initiation_times.append(event_time)
        
        # Check if initially true
        if fluent in self._initially_true:
            initiation_times.append(0)
        
        if not initiation_times:
            return False  # Never initiated
        
        # Find the most recent initiation
        most_recent_initiation = max(initiation_times)
        
        # Check if fluent was clipped between initiation and current time
        if self.clipped(most_recent_initiation, fluent, time):
            return False
        
        return True
    
    def get_all_fluents_at(self, time: int) -> Set[Fluent]:
        """
        Get all fluents that hold at a specific time.
        
        Args:
            time: Time point to query
            
        Returns:
            Set of fluents that hold at time
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> light_on = Fluent("light_on")
            >>> ec.add_initiation_rule(turn_on, light_on)
            >>> ec.record_event(turn_on, time=2)
            >>> fluents = ec.get_all_fluents_at(3)
            >>> light_on in fluents  # True
        """
        result = set()
        
        # Get all fluents mentioned in rules
        all_fluents = set()
        for _, fluent in self._initiation_rules.keys():
            all_fluents.add(fluent)
        for _, fluent in self._termination_rules.keys():
            all_fluents.add(fluent)
        all_fluents.update(self._initially_true)
        
        # Check each fluent
        for fluent in all_fluents:
            if self.holds_at(fluent, time):
                result.add(fluent)
        
        return result
    
    def get_timeline(self, fluent: Fluent, max_time: int) -> List[Tuple[int, bool]]:
        """
        Get the complete timeline of a fluent's truth value.
        
        Args:
            fluent: The fluent to track
            max_time: Maximum time to query
            
        Returns:
            List of (time, holds) tuples showing fluent changes
        
        Examples:
            >>> ec = EventCalculus()
            >>> turn_on = Event("turn_on")
            >>> turn_off = Event("turn_off")
            >>> light_on = Fluent("light_on")
            >>> ec.add_initiation_rule(turn_on, light_on)
            >>> ec.add_termination_rule(turn_off, light_on)
            >>> ec.record_event(turn_on, time=2)
            >>> ec.record_event(turn_off, time=5)
            >>> timeline = ec.get_timeline(light_on, max_time=7)
            >>> # [(0, False), (2, True), (5, False)]
        """
        timeline: List[Tuple[int, bool]] = []
        prev_holds = None
        
        for t in range(max_time + 1):
            holds = self.holds_at(fluent, t)
            if holds != prev_holds:
                timeline.append((t, holds))
                prev_holds = holds
        
        return timeline
