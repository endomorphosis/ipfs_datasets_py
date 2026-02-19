"""
Tests for Event Calculus (Phase 4 Week 1)

This test module validates event calculus reasoning capabilities,
including event occurrences, fluent initiation/termination, and temporal persistence.

Test Coverage:
- Event occurrence tracking (3 tests)
- Fluent initiation (3 tests)
- Fluent termination (3 tests)
- Fluent persistence (HoldsAt) (3 tests)
- Clipping detection (2 tests)
- Concurrent events (1 test)

Total: 15 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.event_calculus import (
    EventCalculus,
    Event,
    Fluent,
    TimePoint,
)
from ipfs_datasets_py.logic.CEC.native.exceptions import ValidationError


class TestEventOccurrence:
    """Test event occurrence tracking."""
    
    def test_record_and_query_event(self):
        """
        GIVEN an event calculus system
        WHEN recording an event at a specific time
        THEN happens predicate should return True for that time
        """
        # GIVEN
        ec = EventCalculus()
        turn_on = Event("turn_on_light")
        
        # WHEN
        ec.record_event(turn_on, time=5)
        
        # THEN
        assert ec.happens(turn_on, 5) is True
        assert ec.happens(turn_on, 4) is False
        assert ec.happens(turn_on, 6) is False
    
    def test_multiple_event_occurrences(self):
        """
        GIVEN an event calculus system
        WHEN recording the same event at multiple times
        THEN happens should return True for all those times
        """
        # GIVEN
        ec = EventCalculus()
        alarm = Event("alarm_rings")
        
        # WHEN
        ec.record_event(alarm, time=1)
        ec.record_event(alarm, time=5)
        ec.record_event(alarm, time=10)
        
        # THEN
        assert ec.happens(alarm, 1) is True
        assert ec.happens(alarm, 5) is True
        assert ec.happens(alarm, 10) is True
        assert ec.happens(alarm, 3) is False
    
    def test_negative_time_validation(self):
        """
        GIVEN an event calculus system
        WHEN trying to record an event at negative time
        THEN ValidationError should be raised
        """
        # GIVEN
        ec = EventCalculus()
        event = Event("test")
        
        # WHEN/THEN
        with pytest.raises(ValidationError, match="Time cannot be negative"):
            ec.record_event(event, time=-1)


class TestFluentInitiation:
    """Test fluent initiation."""
    
    def test_fluent_initiated_by_event(self):
        """
        GIVEN initiation rule and event occurrence
        WHEN event occurs
        THEN initiates predicate should return True
        """
        # GIVEN
        ec = EventCalculus()
        turn_on = Event("turn_on")
        light_on = Fluent("light_on")
        ec.add_initiation_rule(turn_on, light_on)
        
        # WHEN
        ec.record_event(turn_on, time=5)
        
        # THEN
        assert ec.initiates(turn_on, light_on, 5) is True
        assert ec.initiates(turn_on, light_on, 6) is False  # Different time
    
    def test_fluent_holds_after_initiation(self):
        """
        GIVEN fluent initiated by event
        WHEN querying fluent status after initiation
        THEN holds_at should return True
        """
        # GIVEN
        ec = EventCalculus()
        turn_on = Event("turn_on")
        light_on = Fluent("light_on")
        ec.add_initiation_rule(turn_on, light_on)
        
        # WHEN
        ec.record_event(turn_on, time=5)
        
        # THEN
        assert ec.holds_at(light_on, 4) is False  # Before initiation
        assert ec.holds_at(light_on, 5) is False  # At initiation (not yet holding)
        assert ec.holds_at(light_on, 6) is True   # After initiation
        assert ec.holds_at(light_on, 10) is True  # Persistence
    
    def test_multiple_initiations(self):
        """
        GIVEN multiple events that initiate different fluents
        WHEN events occur
        THEN each fluent should hold after its initiation
        """
        # GIVEN
        ec = EventCalculus()
        open_door = Event("open_door")
        turn_on = Event("turn_on_light")
        door_open = Fluent("door_open")
        light_on = Fluent("light_on")
        
        ec.add_initiation_rule(open_door, door_open)
        ec.add_initiation_rule(turn_on, light_on)
        
        # WHEN
        ec.record_event(open_door, time=2)
        ec.record_event(turn_on, time=5)
        
        # THEN
        assert ec.holds_at(door_open, 3) is True
        assert ec.holds_at(light_on, 3) is False
        assert ec.holds_at(door_open, 6) is True
        assert ec.holds_at(light_on, 6) is True


class TestFluentTermination:
    """Test fluent termination."""
    
    def test_fluent_terminated_by_event(self):
        """
        GIVEN termination rule and event occurrence
        WHEN event occurs
        THEN terminates predicate should return True
        """
        # GIVEN
        ec = EventCalculus()
        turn_off = Event("turn_off")
        light_on = Fluent("light_on")
        ec.add_termination_rule(turn_off, light_on)
        
        # WHEN
        ec.record_event(turn_off, time=5)
        
        # THEN
        assert ec.terminates(turn_off, light_on, 5) is True
        assert ec.terminates(turn_off, light_on, 6) is False
    
    def test_fluent_stops_after_termination(self):
        """
        GIVEN fluent that is initiated then terminated
        WHEN querying fluent status after termination
        THEN holds_at should return False
        """
        # GIVEN
        ec = EventCalculus()
        turn_on = Event("turn_on")
        turn_off = Event("turn_off")
        light_on = Fluent("light_on")
        
        ec.add_initiation_rule(turn_on, light_on)
        ec.add_termination_rule(turn_off, light_on)
        
        # WHEN
        ec.record_event(turn_on, time=2)
        ec.record_event(turn_off, time=5)
        
        # THEN
        assert ec.holds_at(light_on, 1) is False  # Before initiation
        assert ec.holds_at(light_on, 3) is True   # After initiation, before termination
        assert ec.holds_at(light_on, 4) is True   # Still holding
        assert ec.holds_at(light_on, 5) is True   # At termination (still holding at that instant)
        assert ec.holds_at(light_on, 6) is False  # After termination
    
    def test_re_initiation_after_termination(self):
        """
        GIVEN fluent that is initiated, terminated, then initiated again
        WHEN querying fluent status
        THEN fluent should hold after second initiation
        """
        # GIVEN
        ec = EventCalculus()
        turn_on = Event("turn_on")
        turn_off = Event("turn_off")
        light_on = Fluent("light_on")
        
        ec.add_initiation_rule(turn_on, light_on)
        ec.add_termination_rule(turn_off, light_on)
        
        # WHEN
        ec.record_event(turn_on, time=2)
        ec.record_event(turn_off, time=5)
        ec.record_event(turn_on, time=8)
        
        # THEN
        assert ec.holds_at(light_on, 3) is True   # After first initiation
        assert ec.holds_at(light_on, 6) is False  # After termination
        assert ec.holds_at(light_on, 9) is True   # After second initiation


class TestFluentPersistence:
    """Test fluent persistence (HoldsAt)."""
    
    def test_initially_true_fluent(self):
        """
        GIVEN a fluent that is initially true
        WHEN querying at time 0 and later
        THEN holds_at should return True
        """
        # GIVEN
        ec = EventCalculus()
        door_closed = Fluent("door_closed")
        ec.set_initially_true(door_closed)
        
        # THEN
        assert ec.holds_at(door_closed, 0) is True
        assert ec.holds_at(door_closed, 5) is True
        assert ec.holds_at(door_closed, 10) is True
    
    def test_initially_true_terminated(self):
        """
        GIVEN a fluent that is initially true but terminated
        WHEN querying after termination
        THEN holds_at should return False
        """
        # GIVEN
        ec = EventCalculus()
        door_closed = Fluent("door_closed")
        open_door = Event("open_door")
        
        ec.set_initially_true(door_closed)
        ec.add_termination_rule(open_door, door_closed)
        
        # WHEN
        ec.record_event(open_door, time=5)
        
        # THEN
        assert ec.holds_at(door_closed, 3) is True   # Before termination
        assert ec.holds_at(door_closed, 6) is False  # After termination
    
    def test_get_all_fluents_at_time(self):
        """
        GIVEN multiple fluents with different timelines
        WHEN querying all fluents at specific time
        THEN should return correct set of holding fluents
        """
        # GIVEN
        ec = EventCalculus()
        turn_on_light = Event("turn_on_light")
        open_door = Event("open_door")
        light_on = Fluent("light_on")
        door_open = Fluent("door_open")
        
        ec.add_initiation_rule(turn_on_light, light_on)
        ec.add_initiation_rule(open_door, door_open)
        
        # WHEN
        ec.record_event(turn_on_light, time=2)
        ec.record_event(open_door, time=5)
        
        # THEN
        fluents_at_3 = ec.get_all_fluents_at(3)
        assert light_on in fluents_at_3
        assert door_open not in fluents_at_3
        
        fluents_at_6 = ec.get_all_fluents_at(6)
        assert light_on in fluents_at_6
        assert door_open in fluents_at_6


class TestClipping:
    """Test clipping detection."""
    
    def test_fluent_clipped_in_interval(self):
        """
        GIVEN a fluent that is terminated in an interval
        WHEN checking if clipped
        THEN clipped should return True
        """
        # GIVEN
        ec = EventCalculus()
        turn_off = Event("turn_off")
        light_on = Fluent("light_on")
        ec.add_termination_rule(turn_off, light_on)
        
        # WHEN
        ec.record_event(turn_off, time=5)
        
        # THEN
        assert ec.clipped(3, light_on, 7) is True   # Terminated at 5
        assert ec.clipped(5, light_on, 7) is False  # Not in open interval (5, 7)
        assert ec.clipped(3, light_on, 5) is False  # Not in open interval (3, 5)
        assert ec.clipped(7, light_on, 10) is False # No termination in (7, 10)
    
    def test_fluent_not_clipped(self):
        """
        GIVEN a fluent with no termination in interval
        WHEN checking if clipped
        THEN clipped should return False
        """
        # GIVEN
        ec = EventCalculus()
        turn_off = Event("turn_off")
        light_on = Fluent("light_on")
        ec.add_termination_rule(turn_off, light_on)
        
        # No termination event
        
        # THEN
        assert ec.clipped(1, light_on, 10) is False


class TestConcurrentEvents:
    """Test handling of concurrent/overlapping events."""
    
    def test_multiple_fluents_simultaneously(self):
        """
        GIVEN multiple fluents initiated at same time
        WHEN querying later
        THEN all fluents should hold
        """
        # GIVEN
        ec = EventCalculus()
        alarm = Event("alarm")
        alarm_sounds = Fluent("alarm_sounds")
        light_flashes = Fluent("light_flashes")
        
        ec.add_initiation_rule(alarm, alarm_sounds)
        ec.add_initiation_rule(alarm, light_flashes)
        
        # WHEN
        ec.record_event(alarm, time=5)
        
        # THEN
        assert ec.holds_at(alarm_sounds, 6) is True
        assert ec.holds_at(light_flashes, 6) is True
