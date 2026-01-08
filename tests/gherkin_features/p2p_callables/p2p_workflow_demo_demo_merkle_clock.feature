Feature: demo_merkle_clock function from examples/p2p_workflow_demo.py
  This function demonstrates merkle clock functionality

  Scenario: Create two merkle clocks with counter 0
    Given peer_id "peer1"
    And peer_id "peer2"
    When MerkleClock("peer1") is called
    And MerkleClock("peer2") is called
    Then clock1.counter == 0

  Scenario: Create two merkle clocks with counter 0 - peer2
    Given peer_id "peer1"
    And peer_id "peer2"
    When MerkleClock("peer1") is called
    And MerkleClock("peer2") is called
    Then clock2.counter == 0

  Scenario: Tick clock twice increments counter to 2
    Given MerkleClock("peer1")
    When clock.tick() is called
    And clock.tick() is called
    Then clock.counter == 2

  Scenario: Tick peer1 clock twice sets counter to 2
    Given MerkleClock("peer1")
    And MerkleClock("peer2")
    When clock1.tick() is called twice
    And clock2.tick() is called once
    Then clock1.counter == 2

  Scenario: Tick peer2 clock once sets counter to 1
    Given MerkleClock("peer1")
    And MerkleClock("peer2")
    When clock1.tick() is called twice
    And clock2.tick() is called once
    Then clock2.counter == 1

  Scenario: Merge clocks with counters 2 and 1 produces counter 3
    Given MerkleClock("peer1") with counter=2
    And MerkleClock("peer2") with counter=1
    When clock1.merge(clock2) is called
    Then merged_clock.counter == 3

  Scenario: Hash returns 64 character hex string
    Given MerkleClock("peer1")
    When clock.hash() is called
    Then len(result) == 64
