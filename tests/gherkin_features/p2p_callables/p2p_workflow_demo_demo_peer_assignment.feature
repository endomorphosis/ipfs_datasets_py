Feature: demo_peer_assignment function from examples/p2p_workflow_demo.py
  This function demonstrates hamming distance based peer assignment

  Scenario: Calculate hamming distance for peers
    Given 5 peers in the network
    And a workflow with ID "demo_wf"
    When calculating hamming distance for each peer
    Then each peer has a non-negative distance value

  Scenario: Assign workflow to peer with minimum distance
    Given scheduler with 5 peers
    And a workflow to schedule
    When scheduling the workflow
    Then workflow is assigned to peer with minimum hamming distance

  Scenario: Display peer distances
    Given scheduler with peers "peer1" through "peer5"
    When computing distances for a workflow
    Then distances are displayed in sorted order
