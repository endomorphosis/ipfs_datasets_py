Feature: main function from examples/p2p_workflow_demo.py
  This function runs all P2P workflow demonstrations

  Scenario: Main calls demo_merkle_clock
    When main() is called
    Then demo_merkle_clock() is executed

  Scenario: Main calls demo_workflow_scheduling
    When main() is called
    Then demo_workflow_scheduling() is executed

  Scenario: Main calls demo_peer_assignment
    When main() is called
    Then demo_peer_assignment() is executed

  Scenario: Main calls demo_mcp_tools
    When main() is called
    Then demo_mcp_tools() is executed

  Scenario: Main prints banner with P2P WORKFLOW SCHEDULER
    When main() is called
    Then output contains "P2P WORKFLOW SCHEDULER"

  Scenario: Main prints banner with merkle clock
    When main() is called
    Then output contains "merkle clock"

  Scenario: Main prints banner with fibonacci heap
    When main() is called
    Then output contains "fibonacci heap"

  Scenario: Main prints banner with hamming distance
    When main() is called
    Then output contains "hamming distance"

  Scenario: Main prints completion message
    When main() is called
    Then output contains completion message

  Scenario: Main prints usage hints
    When main() is called
    Then output contains usage hints
