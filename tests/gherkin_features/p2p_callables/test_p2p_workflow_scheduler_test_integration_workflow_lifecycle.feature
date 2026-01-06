Feature: test_integration_workflow_lifecycle function from tests/test_p2p_workflow_scheduler.py
  This async function tests complete workflow lifecycle

  Scenario: Initialize scheduler with multiple peers
    Given peers "peer1", "peer2", "peer3"
    When creating P2PWorkflowScheduler
    Then scheduler is initialized

  Scenario: Schedule workflows with different priorities
    Given 3 workflows with priorities 2.0, 1.0, 3.0
    When scheduling all workflows
    Then scheduled_count is calculated

  Scenario: Get scheduler status
    Given workflows scheduled
    When calling get_status
    Then status queue_size equals scheduled_count

  Scenario: Process workflows in priority order
    Given workflows in queue
    When getting next workflow repeatedly
    Then workflows are extracted

  Scenario: Process workflows in priority order - assertion 2
    Given workflows in queue
    When getting next workflow repeatedly
    Then processed list is populated

  Scenario: Verify queue is empty
    Given all workflows processed
    When checking queue size
    Then queue size equals 0
