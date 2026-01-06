Feature: demo_merkle_clock function from examples/p2p_workflow_demo.py
  This function demonstrates merkle clock functionality

  Scenario: Demonstrate merkle clock initialization
    Given two peers with IDs "peer1" and "peer2"
    When creating MerkleClock instances for each peer
    Then both clocks start with counter 0

  Scenario: Demonstrate clock advancement through ticks
    Given an initialized MerkleClock for "peer1"
    When calling tick twice on the clock
    Then the clock counter equals 2

  Scenario: Demonstrate independent clock advancement
    Given two MerkleClock instances for "peer1" and "peer2"
    When "peer1" clock ticks twice
    And "peer2" clock ticks once
    Then "peer1" counter equals 2

  Scenario: Demonstrate independent clock advancement - assertion 2
    Given two MerkleClock instances for "peer1" and "peer2"
    When "peer1" clock ticks twice
    And "peer2" clock ticks once
    Then "peer2" counter equals 1

  Scenario: Demonstrate clock merging
    Given "peer1" clock with counter 2
    And "peer2" clock with counter 1
    When merging "peer2" clock into "peer1"
    Then merged clock counter equals 3

  Scenario: Demonstrate hash generation
    Given an initialized MerkleClock
    When computing the hash
    Then hash is a non-empty string
