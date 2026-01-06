Feature: TestP2PWorkflowScheduler class from tests/test_p2p_workflow_scheduler.py
  This class tests P2P Workflow Scheduler

  Scenario: test_scheduler_initialization method
    Given peer ID "peer1"
    When creating P2PWorkflowScheduler
    Then scheduler peer_id equals "peer1"
    And "peer1" is in peers set
    And clock peer_id equals "peer1"
    And workflow_queue size equals 0

  Scenario: test_scheduler_add_remove_peer method
    Given initialized scheduler
    When adding peer "peer2"
    Then "peer2" is in peers
    And peers length equals 2
    When removing peer "peer2"
    Then "peer2" is not in peers
    And peers length equals 1

  Scenario: test_scheduler_schedule_github_workflow method
    Given scheduler with peer "peer1"
    And workflow with UNIT_TEST tag
    When scheduling workflow
    Then result success is false
    And result reason contains "GitHub API"

  Scenario: test_scheduler_schedule_p2p_workflow method
    Given scheduler with peers "peer1", "peer2", "peer3"
    And workflow with P2P_ELIGIBLE and CODE_GEN tags, priority 1.0
    When scheduling workflow
    Then result success is true
    And result contains assigned_peer
    And assigned_peer is in scheduler peers

  Scenario: test_scheduler_workflow_assignment_deterministic method
    Given scheduler with peers "peer1", "peer2", "peer3"
    And workflow with P2P_ELIGIBLE tag
    When scheduling workflow twice with different schedulers
    Then both results have success true

  Scenario: test_scheduler_get_next_workflow method
    Given scheduler with peer "peer1"
    And 3 workflows with priorities 5.0, 1.0, 3.0
    When getting next workflow
    Then workflow_id equals "wf2"

  Scenario: test_scheduler_get_status method
    Given scheduler with peers "peer1", "peer2"
    And scheduled workflow
    When calling get_status
    Then status peer_id equals "peer1"
    And status num_peers equals 2
    And status contains clock
    And status clock counter is greater than 0

  Scenario: test_scheduler_merge_clock method
    Given scheduler1 with peer "peer1"
    And scheduler2 with peer "peer2" clock ticked 5 times
    And initial counter from scheduler1
    When merging scheduler2 clock into scheduler1
    Then scheduler1 counter is greater than initial counter

  Scenario: test_scheduler_multiple_peers_distribution method
    Given scheduler with 4 peers
    And 20 workflows scheduled
    When checking assigned peers
    Then assigned_peers set size is at least 2
