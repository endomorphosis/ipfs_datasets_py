Feature: main function from examples/p2p_workflow_demo.py
  This function runs all P2P workflow demonstrations

  Scenario: Run all demonstrations
    When calling main function
    Then demo_merkle_clock executes
    And demo_workflow_scheduling executes
    And demo_peer_assignment executes
    And demo_mcp_tools executes

  Scenario: Display demonstration banner
    When starting main function
    Then banner displays P2P WORKFLOW SCHEDULER DEMONSTRATION
    And description mentions merkle clock
    And description mentions fibonacci heap
    And description mentions hamming distance

  Scenario: Complete all demonstrations
    Given all demonstration functions
    When main executes
    Then completion message displays
    And usage hints are shown
