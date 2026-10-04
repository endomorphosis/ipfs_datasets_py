Feature: demo_peer_assignment function from examples/p2p_workflow_demo.py
  This function demonstrates hamming distance based peer assignment

  Scenario: Calculate hamming distance returns non-negative integer
    Given 5 peers
    And workflow_id "demo_wf"
    When calculate_hamming_distance(workflow_hash, peer_id) is called
    Then distance >= 0

  Scenario: Assign workflow to peer with minimum distance
    Given scheduler with 5 peers
    And workflow to schedule
    When scheduler.schedule_workflow(workflow) is called
    Then assigned_peer has minimum hamming distance

  Scenario: Peer distances are sorted ascending
    Given scheduler with peers "peer1" through "peer5"
    And workflow to schedule
    When computing distances for all peers
    Then distances[i] <= distances[i+1] for all i
