Feature: demo_mcp_tools function from examples/p2p_workflow_demo.py
  This async function demonstrates MCP server tools

  Scenario: Initialize P2P scheduler via MCP tools
    Given MCP tools are available
    When calling initialize_p2p_scheduler with peer_id "mcp_peer"
    Then result success is true

  Scenario: Initialize P2P scheduler via MCP tools - assertion 2
    Given MCP tools are available
    When calling initialize_p2p_scheduler with peer_id "mcp_peer"
    Then status contains peer_id "mcp_peer"

  Scenario: Get workflow tags via MCP tools
    Given initialized MCP tools
    When calling get_workflow_tags
    Then result contains tags list

  Scenario: Get workflow tags via MCP tools - assertion 2
    Given initialized MCP tools
    When calling get_workflow_tags
    Then result contains descriptions

  Scenario: Schedule workflow via MCP tools
    Given initialized P2P scheduler via MCP
    When calling schedule_p2p_workflow with ID "mcp_wf1"
    Then result success is true

  Scenario: Schedule workflow via MCP tools - assertion 2
    Given initialized P2P scheduler via MCP
    When calling schedule_p2p_workflow with ID "mcp_wf1"
    Then workflow is assigned to a peer

  Scenario: Get scheduler status via MCP tools
    Given active P2P scheduler via MCP
    When calling get_p2p_scheduler_status
    Then status contains queue_size

  Scenario: Get scheduler status via MCP tools - assertion 2
    Given active P2P scheduler via MCP
    When calling get_p2p_scheduler_status
    Then status contains total_workflows

  Scenario: Handle MCP tools unavailable
    Given MCP tools are not installed
    When attempting to import MCP tools
    Then function returns early with warning message
