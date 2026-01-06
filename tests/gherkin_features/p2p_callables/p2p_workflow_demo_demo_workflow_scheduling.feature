Feature: demo_workflow_scheduling function from examples/p2p_workflow_demo.py
  This function demonstrates workflow scheduling with peers

  Scenario: Initialize scheduler with multiple peers
    Given peer IDs "peer1", "peer2", "peer3"
    When creating P2PWorkflowScheduler with "peer1" as main peer
    Then scheduler peer_id equals "peer1"
    And known peers count equals 3

  Scenario: Schedule P2P eligible workflow
    Given an initialized P2PWorkflowScheduler
    When scheduling workflow with ID "wf1" with P2P_ELIGIBLE tag and priority 2.0
    Then workflow is assigned to a peer
    And scheduling result contains success true

  Scenario: Schedule P2P only workflow
    Given an initialized P2PWorkflowScheduler
    When scheduling workflow with ID "wf2" with P2P_ONLY tag and priority 1.0
    Then workflow is assigned to a peer

  Scenario: Reject non-P2P workflow
    Given an initialized P2PWorkflowScheduler
    When scheduling workflow with UNIT_TEST tag
    Then scheduling result contains success false
    And result reason mentions GitHub API

  Scenario: Process workflows in priority order
    Given scheduler with 3 queued workflows
    When getting next workflow from queue
    Then workflow with priority 1.0 is returned first

  Scenario: Get scheduler status
    Given scheduler with assigned workflows
    When calling get_status
    Then status contains queue_size
    And status contains assigned_workflows
    And status contains clock counter
