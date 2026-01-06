Feature: test_two_peers_communication function from scripts/test_p2p_real_world.py
  This async function tests communication between two P2P peers

  Scenario: Create bootstrap host
    When creating host1
    Then host1 has ID

  Scenario: Create bootstrap host - assertion 2
    When creating host1
    Then host1 has addresses

  Scenario: Register stream handler on host1
    Given host1 created
    When setting stream handler
    Then handler receives streams

  Scenario: Create second host
    When creating host2
    Then host2 has ID

  Scenario: Connect host2 to host1
    Given host1 and host2 created
    When host2 connects to host1 address
    Then hosts are connected

  Scenario: Send message from host2 to host1
    Given hosts connected
    When host2 opens stream to host1
    And host2 sends "Hello from host 2!"
    Then host1 receives message

  Scenario: Receive response from host1
    Given message sent
    When host2 reads response
    Then response equals "ACK"

  Scenario: Close stream
    Given communication completed
    When closing stream
    Then stream closes cleanly

  Scenario: Close hosts
    Given both hosts active
    When calling close on both
    Then both hosts close

  Scenario: Close hosts - assertion 2
    Given both hosts active
    When calling close on both
    Then function returns true

  Scenario: Two peers communication fails
    Given communication raises exception
    When calling test_two_peers_communication
    Then function returns false
