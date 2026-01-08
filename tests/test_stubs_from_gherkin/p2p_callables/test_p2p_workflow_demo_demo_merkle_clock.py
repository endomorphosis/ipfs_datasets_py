"""
Test stubs for demo_merkle_clock

This feature file describes the demo_merkle_clock callable
from examples/p2p_workflow_demo.py.
"""

import pytest
from ipfs_datasets_py.p2p_workflow_scheduler import MerkleClock


def test_create_two_merkle_clocks_with_counter_0(peer_id_peer1, peer_id_peer2):
    """
    Scenario: Create two merkle clocks with counter 0

    Given:
        peer_id "peer1"
        peer_id "peer2"

    When:
        MerkleClock("peer1") is called
        MerkleClock("peer2") is called

    Then:
        clock1.counter == 0
    """
    expected_counter = 0
    
    clock1 = MerkleClock(peer_id=peer_id_peer1)
    
    actual_counter = clock1.counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_create_two_merkle_clocks_with_counter_0_peer2(peer_id_peer1, peer_id_peer2):
    """
    Scenario: Create two merkle clocks with counter 0 - peer2

    Given:
        peer_id "peer1"
        peer_id "peer2"

    When:
        MerkleClock("peer1") is called
        MerkleClock("peer2") is called

    Then:
        clock2.counter == 0
    """
    expected_counter = 0
    
    clock2 = MerkleClock(peer_id=peer_id_peer2)
    
    actual_counter = clock2.counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_tick_clock_twice_increments_counter_to_2(merkle_clock_peer1):
    """
    Scenario: Tick clock twice increments counter to 2

    Given:
        MerkleClock("peer1")

    When:
        clock.tick() is called
        clock.tick() is called

    Then:
        clock.counter == 2
    """
    expected_counter = 2
    
    clock_after_first_tick = merkle_clock_peer1.tick()
    clock_after_second_tick = clock_after_first_tick.tick()
    
    actual_counter = clock_after_second_tick.counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_tick_peer1_clock_twice_sets_counter_to_2(merkle_clock_peer1, merkle_clock_peer2):
    """
    Scenario: Tick peer1 clock twice sets counter to 2

    Given:
        MerkleClock("peer1")
        MerkleClock("peer2")

    When:
        clock1.tick() is called twice
        clock2.tick() is called once

    Then:
        clock1.counter == 2
    """
    expected_counter = 2
    
    clock1_after_tick1 = merkle_clock_peer1.tick()
    clock1_after_tick2 = clock1_after_tick1.tick()
    
    actual_counter = clock1_after_tick2.counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_tick_peer2_clock_once_sets_counter_to_1(merkle_clock_peer1, merkle_clock_peer2):
    """
    Scenario: Tick peer2 clock once sets counter to 1

    Given:
        MerkleClock("peer1")
        MerkleClock("peer2")

    When:
        clock1.tick() is called twice
        clock2.tick() is called once

    Then:
        clock2.counter == 1
    """
    expected_counter = 1
    
    clock2_after_tick = merkle_clock_peer2.tick()
    
    actual_counter = clock2_after_tick.counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_merge_clocks_with_counters_2_and_1_produces_counter_3(merkle_clock_with_counter_2, merkle_clock_with_counter_1):
    """
    Scenario: Merge clocks with counters 2 and 1 produces counter 3

    Given:
        MerkleClock("peer1") with counter=2
        MerkleClock("peer2") with counter=1

    When:
        clock1.merge(clock2) is called

    Then:
        merged_clock.counter == 3
    """
    expected_counter = 3
    
    merged_clock = merkle_clock_with_counter_2.merge(merkle_clock_with_counter_1)
    
    actual_counter = merged_clock.counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_hash_returns_64_character_hex_string(merkle_clock_peer1):
    """
    Scenario: Hash returns 64 character hex string

    Given:
        MerkleClock("peer1")

    When:
        clock.hash() is called

    Then:
        len(result) == 64
    """
    expected_length = 64
    
    result = merkle_clock_peer1.hash()
    
    actual_length = len(result)
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


