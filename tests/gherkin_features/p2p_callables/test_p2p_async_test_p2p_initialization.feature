Feature: test_p2p_initialization function from test_p2p_async.py
  This async function tests P2P cache initialization in async context

  Scenario: Check libp2p availability
    When importing libp2p
    Then libp2p is available

  Scenario: Create cache with P2P in temp directory
    Given temp directory created
    When creating GitHubAPICache with P2P enabled
    Then cache is created

  Scenario: Wait for P2P initialization
    Given cache created
    When waiting 1 second
    Then P2P has time to initialize

  Scenario: Check cache statistics
    Given cache initialized
    When calling get_stats
    Then P2P enabled status displays

  Scenario: Check cache statistics - assertion 2
    Given cache initialized
    When calling get_stats
    Then connected peers displays

  Scenario: P2P fully initialized
    Given stats with p2p_enabled true
    And stats with peer_id
    When checking initialization
    Then function returns true

  Scenario: P2P initializing
    Given stats without peer_id
    When checking initialization
    Then function returns true with pending message

  Scenario: P2P not enabled
    Given stats with p2p_enabled false
    When checking initialization
    Then function returns false

  Scenario: Libp2p not installed
    Given libp2p import fails
    When calling test_p2p_initialization
    Then function returns true with skip message
