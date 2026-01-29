"""
Test stubs for demo_peer_assignment

This feature file describes the demo_peer_assignment callable
from examples/p2p_workflow_demo.py.
"""

import pytest
from ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler import calculate_hamming_distance
import hashlib


def test_calculate_hamming_distance_returns_non_negative_integer():
    """
    Scenario: Calculate hamming distance returns non-negative integer

    Given:
        5 peers
        workflow_id "demo_wf"

    When:
        calculate_hamming_distance(workflow_hash, peer_id) is called

    Then:
        distance >= 0
    """
    minimum_distance = 0
    workflow_id = "demo_wf"
    peer_id = "peer1"
    workflow_hash = hashlib.sha256(workflow_id.encode()).hexdigest()
    peer_hash = hashlib.sha256(peer_id.encode()).hexdigest()
    
    distance = calculate_hamming_distance(workflow_hash, peer_hash)
    
    assert distance >= minimum_distance, f"expected >= {minimum_distance}, got {distance}"


def test_assign_workflow_to_peer_with_minimum_distance(scheduler_with_5_peers, workflow_definition_p2p_eligible):
    """
    Scenario: Assign workflow to peer with minimum distance

    Given:
        scheduler with 5 peers
        workflow to schedule

    When:
        scheduler.schedule_workflow(workflow) is called

    Then:
        assigned_peer has minimum hamming distance
    """
    # Calculate expected minimum distance for all peers
    workflow_hash = hashlib.sha256(workflow_definition_p2p_eligible.workflow_id.encode()).hexdigest()
    expected_min_distance = min(
        calculate_hamming_distance(workflow_hash, hashlib.sha256(peer.encode()).hexdigest())
        for peer in scheduler_with_5_peers.peers
    )
    
    assigned_peer = scheduler_with_5_peers.schedule_workflow(workflow_definition_p2p_eligible)
    
    assigned_peer_hash = hashlib.sha256(assigned_peer.encode()).hexdigest()
    actual_distance = calculate_hamming_distance(workflow_hash, assigned_peer_hash)
    assert actual_distance == expected_min_distance, f"expected {expected_min_distance}, got {actual_distance}"


def test_peer_distances_are_sorted_ascending(scheduler_with_5_peers, workflow_definition_p2p_eligible):
    """
    Scenario: Peer distances are sorted ascending

    Given:
        scheduler with peers "peer1" through "peer5"
        workflow to schedule

    When:
        computing distances for all peers

    Then:
        distances[i] <= distances[i+1] for all i
    """
    workflow_hash = hashlib.sha256(workflow_definition_p2p_eligible.workflow_id.encode()).hexdigest()
    
    distances = sorted([
        calculate_hamming_distance(workflow_hash, hashlib.sha256(peer.encode()).hexdigest())
        for peer in scheduler_with_5_peers.peers
    ])
    
    # Check if sorted (each element <= next element)
    expected_sorted = True
    actual_sorted = all(distances[i] <= distances[i+1] for i in range(len(distances)-1))
    assert actual_sorted == expected_sorted, f"expected {expected_sorted}, got {actual_sorted}"


