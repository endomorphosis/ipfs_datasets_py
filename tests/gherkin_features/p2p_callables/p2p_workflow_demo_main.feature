Feature: main function from examples/p2p_workflow_demo.py
  This function runs all P2P workflow demonstrations

  Scenario: Run all demonstrations
    When calling main function
    Then demo_merkle_clock executes

  Scenario: Run all demonstrations - assertion 2
    When calling main function
    Then demo_workflow_scheduling executes

  Scenario: Run all demonstrations - assertion 3
    When calling main function
    Then demo_peer_assignment executes

  Scenario: Run all demonstrations - assertion 4
    When calling main function
    Then demo_mcp_tools executes

  Scenario: Display demonstration banner
    When starting main function
    Then banner displays P2P WORKFLOW SCHEDULER DEMONSTRATION

  Scenario: Display demonstration banner - assertion 2
    When starting main function
    Then description mentions merkle clock

  Scenario: Display demonstration banner - assertion 3
    When starting main function
    Then description mentions fibonacci heap

  Scenario: Display demonstration banner - assertion 4
    When starting main function
    Then description mentions hamming distance

  Scenario: Complete all demonstrations
    Given all demonstration functions
    When main executes
    Then completion message displays

  Scenario: Complete all demonstrations - assertion 2
    Given all demonstration functions
    When main executes
    Then usage hints are shown
