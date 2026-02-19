"""
Tests for Fluent Handling (Phase 4 Week 1)

This test module validates fluent management capabilities including
fluent creation, persistence rules, state transitions, conflict resolution,
and frame problem handling.

Test Coverage:
- Fluent creation and validation (2 tests)
- Persistence rules (2 tests)
- State transitions (2 tests)
- Conflict resolution (2 tests)
- Frame problem handling (2 tests)

Total: 10 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.fluents import (
    Fluent,
    FluentType,
    PersistenceRule,
    FluentManager,
)
from ipfs_datasets_py.logic.CEC.native.event_calculus import Event, EventCalculus
from ipfs_datasets_py.logic.CEC.native.exceptions import ValidationError


class TestFluentCreation:
    """Test fluent creation and validation."""
    
    def test_fluent_creation_with_defaults(self):
        """
        GIVEN fluent parameters
        WHEN creating a boolean fluent
        THEN fluent should be created with correct defaults
        """
        # GIVEN/WHEN
        fluent = Fluent("light_on", FluentType.BOOLEAN)
        
        # THEN
        assert fluent.name == "light_on"
        assert fluent.fluent_type == FluentType.BOOLEAN
        assert fluent.persistence_rule == PersistenceRule.INERTIAL
        assert fluent.default_value is False  # Boolean default
    
    def test_fluent_creation_with_custom_values(self):
        """
        GIVEN custom fluent parameters
        WHEN creating a numerical fluent with custom settings
        THEN fluent should be created with specified values
        """
        # GIVEN/WHEN
        temperature = Fluent(
            "temperature",
            FluentType.NUMERICAL,
            persistence_rule=PersistenceRule.DECAYING,
            default_value=20.0
        )
        
        # THEN
        assert temperature.name == "temperature"
        assert temperature.fluent_type == FluentType.NUMERICAL
        assert temperature.persistence_rule == PersistenceRule.DECAYING
        assert temperature.default_value == 20.0


class TestPersistenceRules:
    """Test fluent persistence rules."""
    
    def test_inertial_persistence(self):
        """
        GIVEN an inertial fluent
        WHEN checking if it persists across time
        THEN should return True (inertial fluents persist)
        """
        # GIVEN
        fluent = Fluent("light_on", FluentType.BOOLEAN, persistence_rule=PersistenceRule.INERTIAL)
        
        # WHEN/THEN
        assert fluent.persists(5, 10) is True
        assert fluent.persists(0, 100) is True
    
    def test_transient_persistence(self):
        """
        GIVEN a transient fluent
        WHEN checking if it persists
        THEN should return False (transient fluents don't persist)
        """
        # GIVEN
        fluent = Fluent("button_press", FluentType.BOOLEAN, persistence_rule=PersistenceRule.TRANSIENT)
        
        # WHEN/THEN
        assert fluent.persists(5, 6) is False
        assert fluent.persists(5, 10) is False


class TestStateTransitions:
    """Test event-driven state transitions."""
    
    def test_apply_single_transition(self):
        """
        GIVEN a fluent manager with a fluent
        WHEN applying an event transition
        THEN fluent value should change at that time
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        manager.add_fluent(light_on)
        
        # Initially false
        assert manager.get_fluent_value(light_on, 0) is False
        
        # WHEN
        turn_on = Event("turn_on_light")
        manager.apply_transition(turn_on, time=5, effects={light_on: True})
        
        # THEN
        assert manager.get_fluent_value(light_on, 4) is False  # Before event
        assert manager.get_fluent_value(light_on, 5) is True   # At event
        assert manager.get_fluent_value(light_on, 10) is True  # After (persists)
    
    def test_multiple_transitions(self):
        """
        GIVEN a fluent manager with fluents
        WHEN applying multiple event transitions
        THEN fluents should have correct values at each time
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        door_open = Fluent("door_open", FluentType.BOOLEAN)
        manager.add_fluent(light_on)
        manager.add_fluent(door_open)
        
        # WHEN
        turn_on = Event("turn_on_light")
        open_door = Event("open_door")
        turn_off = Event("turn_off_light")
        
        manager.apply_transition(turn_on, time=2, effects={light_on: True})
        manager.apply_transition(open_door, time=5, effects={door_open: True})
        manager.apply_transition(turn_off, time=8, effects={light_on: False})
        
        # THEN
        # At time 1: both false
        assert manager.get_fluent_value(light_on, 1) is False
        assert manager.get_fluent_value(door_open, 1) is False
        
        # At time 3: light on, door closed
        assert manager.get_fluent_value(light_on, 3) is True
        assert manager.get_fluent_value(door_open, 3) is False
        
        # At time 6: both true
        assert manager.get_fluent_value(light_on, 6) is True
        assert manager.get_fluent_value(door_open, 6) is True
        
        # At time 10: light off, door still open
        assert manager.get_fluent_value(light_on, 10) is False
        assert manager.get_fluent_value(door_open, 10) is True


class TestConflictResolution:
    """Test conflict resolution for competing fluents."""
    
    def test_last_write_wins_default(self):
        """
        GIVEN a fluent with multiple writes at same time
        WHEN no custom conflict resolver is set
        THEN last write should win (default behavior)
        """
        # GIVEN
        manager = FluentManager()
        counter = Fluent("counter", FluentType.NUMERICAL, default_value=0)
        manager.add_fluent(counter)
        
        # WHEN - Multiple writes at same time
        manager.set_fluent_value(counter, 10, time=5)
        manager.set_fluent_value(counter, 20, time=5)  # Overwrites previous
        
        # THEN
        assert manager.get_fluent_value(counter, 5) == 20
    
    def test_custom_conflict_resolver(self):
        """
        GIVEN a fluent manager with custom conflict resolver
        WHEN conflicts occur
        THEN custom resolver should be used (conceptual test)
        """
        # GIVEN
        manager = FluentManager()
        
        def max_resolver(fluent, v1, v2):
            """Resolve conflict by taking maximum value."""
            return max(v1, v2)
        
        manager.set_conflict_resolver(max_resolver)
        
        # THEN - Resolver is set
        assert manager.conflict_resolver is not None
        assert manager.conflict_resolver(None, 10, 20) == 20


class TestFrameProblem:
    """Test frame problem handling (preserving unchanged fluents)."""
    
    def test_unaffected_fluents_persist(self):
        """
        GIVEN multiple fluents with some changing
        WHEN events affect only some fluents
        THEN unaffected fluents should maintain their values (frame problem)
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        door_open = Fluent("door_open", FluentType.BOOLEAN)
        alarm_active = Fluent("alarm_active", FluentType.BOOLEAN)
        
        manager.add_fluent(light_on)
        manager.add_fluent(door_open)
        manager.add_fluent(alarm_active)
        
        # Set initial state
        manager.set_fluent_value(light_on, True, time=0)
        manager.set_fluent_value(door_open, True, time=0)
        manager.set_fluent_value(alarm_active, True, time=0)
        
        # WHEN - Event affects only light
        turn_off_light = Event("turn_off_light")
        manager.apply_transition(turn_off_light, time=5, effects={light_on: False})
        
        # THEN - Only light changed, others persist
        assert manager.get_fluent_value(light_on, 10) is False   # Changed
        assert manager.get_fluent_value(door_open, 10) is True   # Unchanged (frame)
        assert manager.get_fluent_value(alarm_active, 10) is True  # Unchanged (frame)
    
    def test_transient_fluent_frame_problem(self):
        """
        GIVEN transient and inertial fluents
        WHEN checking persistence
        THEN transient fluents should not persist, inertial should
        """
        # GIVEN
        manager = FluentManager()
        button_press = Fluent("button_press", FluentType.BOOLEAN, persistence_rule=PersistenceRule.TRANSIENT)
        light_on = Fluent("light_on", FluentType.BOOLEAN, persistence_rule=PersistenceRule.INERTIAL)
        
        manager.add_fluent(button_press)
        manager.add_fluent(light_on)
        
        # WHEN - Set both at time 5
        manager.set_fluent_value(button_press, True, time=5)
        manager.set_fluent_value(light_on, True, time=5)
        
        # THEN
        # At time 5: both true
        assert manager.get_fluent_value(button_press, 5) is True
        assert manager.get_fluent_value(light_on, 5) is True
        
        # At time 6: transient reverts to default, inertial persists
        assert manager.get_fluent_value(button_press, 6) is False  # Transient (default)
        assert manager.get_fluent_value(light_on, 6) is True       # Inertial (persists)


class TestFluentManagerOperations:
    """Test additional fluent manager operations."""
    
    def test_get_complete_state(self):
        """
        GIVEN multiple fluents at various times
        WHEN getting complete state at specific time
        THEN should return all fluent values
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        door_open = Fluent("door_open", FluentType.BOOLEAN)
        
        manager.add_fluent(light_on)
        manager.add_fluent(door_open)
        
        manager.set_fluent_value(light_on, True, time=2)
        manager.set_fluent_value(door_open, True, time=5)
        
        # WHEN
        state_at_6 = manager.get_state(time=6)
        
        # THEN
        assert len(state_at_6) == 2
        assert state_at_6[light_on] is True
        assert state_at_6[door_open] is True
    
    def test_fluent_timeline(self):
        """
        GIVEN a fluent with value changes over time
        WHEN getting timeline
        THEN should return list of (time, value) changes
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        manager.add_fluent(light_on)
        
        # Apply changes
        manager.set_fluent_value(light_on, True, time=2)
        manager.set_fluent_value(light_on, False, time=5)
        manager.set_fluent_value(light_on, True, time=8)
        
        # WHEN
        timeline = manager.get_timeline(light_on, max_time=10)
        
        # THEN
        assert len(timeline) >= 3  # At least 3 changes
        # First change: False -> True at time 2
        assert (2, True) in timeline
        # Second change: True -> False at time 5
        assert (5, False) in timeline
        # Third change: False -> True at time 8
        assert (8, True) in timeline


class TestEventCalculusIntegration:
    """Test integration with EventCalculus."""
    
    def test_fluent_manager_with_event_calculus(self):
        """
        GIVEN fluent manager integrated with event calculus
        WHEN applying transitions
        THEN events should be recorded in event calculus
        """
        # GIVEN
        ec = EventCalculus()
        manager = FluentManager(event_calculus=ec)
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        manager.add_fluent(light_on)
        
        # WHEN
        turn_on = Event("turn_on_light")
        manager.apply_transition(turn_on, time=5, effects={light_on: True})
        
        # THEN
        # Event should be recorded in event calculus
        assert ec.happens(turn_on, 5) is True
        # Fluent value should be set in manager
        assert manager.get_fluent_value(light_on, 6) is True


class TestValidation:
    """Test validation and error handling."""
    
    def test_duplicate_fluent_validation(self):
        """
        GIVEN a fluent manager with a registered fluent
        WHEN trying to add same fluent again
        THEN ValidationError should be raised
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        manager.add_fluent(light_on)
        
        # WHEN/THEN
        with pytest.raises(ValidationError, match="already registered"):
            manager.add_fluent(light_on)
    
    def test_unregistered_fluent_access(self):
        """
        GIVEN a fluent manager
        WHEN trying to access unregistered fluent
        THEN ValidationError should be raised
        """
        # GIVEN
        manager = FluentManager()
        light_on = Fluent("light_on", FluentType.BOOLEAN)
        # Not registered
        
        # WHEN/THEN
        with pytest.raises(ValidationError, match="not registered"):
            manager.get_fluent_value(light_on, 5)
