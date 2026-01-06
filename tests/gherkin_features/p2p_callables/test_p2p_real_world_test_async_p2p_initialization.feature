Feature: test_async_p2p_initialization function from scripts/test_p2p_real_world.py
  This async function tests async P2P initialization

  Scenario: Create libp2p host
    When calling new_host
    Then host is created

  Scenario: Create libp2p host - assertion 2
    When calling new_host
    Then host has ID

  Scenario: Get listen addresses
    Given host created
    When calling get_addrs
    Then addresses list is returned

  Scenario: Get listen addresses - assertion 2
    Given host created
    When calling get_addrs
    Then addresses are displayed

  Scenario: Register stream handler
    Given host instance
    When setting stream handler for "/github-cache/1.0.0"
    Then handler is registered

  Scenario: Keep host running
    Given host with handler
    When waiting 2 seconds
    Then host remains active

  Scenario: Close host cleanly
    Given host running
    When calling close
    Then host closes without error

  Scenario: Close host cleanly - assertion 2
    Given host running
    When calling close
    Then function returns true

  Scenario: P2P initialization fails
    Given host creation raises exception
    When calling test_async_p2p_initialization
    Then function returns false
