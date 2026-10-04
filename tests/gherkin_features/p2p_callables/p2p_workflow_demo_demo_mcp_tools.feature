Feature: demo_mcp_tools function from examples/p2p_workflow_demo.py
  This async function demonstrates MCP server tools

  Scenario: Initialize P2P scheduler returns success True
    Given peer_id "mcp_peer"
    When initialize_p2p_scheduler(peer_id="mcp_peer") is called
    Then result["success"] == True

  Scenario: Initialize P2P scheduler sets peer_id
    Given peer_id "mcp_peer"
    When initialize_p2p_scheduler(peer_id="mcp_peer") is called
    Then status["peer_id"] == "mcp_peer"

  Scenario: Get workflow tags returns list
    When get_workflow_tags() is called
    Then isinstance(result["tags"], list)

  Scenario: Get workflow tags returns descriptions dict
    When get_workflow_tags() is called
    Then isinstance(result["descriptions"], dict)

  Scenario: Schedule workflow returns success True
    Given P2P scheduler with peer_id "mcp_peer"
    And workflow_id "mcp_wf1"
    When schedule_p2p_workflow(workflow_id="mcp_wf1") is called
    Then result["success"] == True

  Scenario: Schedule workflow assigns to peer
    Given P2P scheduler with peer_id "mcp_peer"
    And workflow_id "mcp_wf1"
    When schedule_p2p_workflow(workflow_id="mcp_wf1") is called
    Then "assigned_peer" in result

  Scenario: Get scheduler status returns queue_size as integer
    Given active P2P scheduler
    When get_p2p_scheduler_status() is called
    Then isinstance(status["queue_size"], int)

  Scenario: Get scheduler status returns total_workflows as integer
    Given active P2P scheduler
    When get_p2p_scheduler_status() is called
    Then isinstance(status["total_workflows"], int)

  Scenario: MCP tools unavailable raises ImportError
    Given MCP tools not installed
    When importing MCP tools
    Then ImportError is raised
