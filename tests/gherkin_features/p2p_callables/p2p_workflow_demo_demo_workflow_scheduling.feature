Feature: demo_workflow_scheduling function from examples/p2p_workflow_demo.py
  This function demonstrates workflow scheduling with peers

  Scenario: Create scheduler with 3 peers
    Given peer_ids ["peer1", "peer2", "peer3"]
    When P2PWorkflowScheduler("peer1", peers=["peer1", "peer2", "peer3"]) is called
    Then scheduler.peer_id == "peer1"

  Scenario: Scheduler knows 3 peers
    Given peer_ids ["peer1", "peer2", "peer3"]
    When P2PWorkflowScheduler("peer1", peers=["peer1", "peer2", "peer3"]) is called
    Then len(scheduler.peers) == 3

  Scenario: Schedule P2P eligible workflow returns success True
    Given P2PWorkflowScheduler with peers
    And WorkflowDefinition(workflow_id="wf1", tags=[WorkflowTag.P2P_ELIGIBLE], priority=2.0)
    When scheduler.schedule_workflow(workflow) is called
    Then result["success"] == True

  Scenario: Schedule P2P eligible workflow assigns to peer
    Given P2PWorkflowScheduler with peers
    And WorkflowDefinition(workflow_id="wf1", tags=[WorkflowTag.P2P_ELIGIBLE], priority=2.0)
    When scheduler.schedule_workflow(workflow) is called
    Then result["assigned_peer"] in scheduler.peers

  Scenario: Schedule P2P only workflow returns success True
    Given P2PWorkflowScheduler with peers
    And WorkflowDefinition(workflow_id="wf2", tags=[WorkflowTag.P2P_ONLY], priority=1.0)
    When scheduler.schedule_workflow(workflow) is called
    Then result["success"] == True

  Scenario: Schedule non-P2P workflow returns success False
    Given P2PWorkflowScheduler with peers
    And WorkflowDefinition(tags=[WorkflowTag.UNIT_TEST])
    When scheduler.schedule_workflow(workflow) is called
    Then result["success"] == False

  Scenario: Schedule non-P2P workflow reason contains GitHub API
    Given P2PWorkflowScheduler with peers
    And WorkflowDefinition(tags=[WorkflowTag.UNIT_TEST])
    When scheduler.schedule_workflow(workflow) is called
    Then "GitHub API" in result["reason"]

  Scenario: Get next workflow returns highest priority workflow
    Given scheduler with workflows priority 5.0, 1.0, 3.0
    When scheduler.get_next_workflow() is called
    Then next_workflow.workflow_id == "wf2"

  Scenario: Get status returns queue_size as integer
    Given P2PWorkflowScheduler with scheduled workflow
    When scheduler.get_status() is called
    Then isinstance(status["queue_size"], int)

  Scenario: Get status returns assigned_workflows as dict
    Given P2PWorkflowScheduler with scheduled workflow
    When scheduler.get_status() is called
    Then isinstance(status["assigned_workflows"], dict)

  Scenario: Get status returns clock counter greater than 0
    Given P2PWorkflowScheduler with scheduled workflow
    When scheduler.get_status() is called
    Then status["clock"]["counter"] > 0
