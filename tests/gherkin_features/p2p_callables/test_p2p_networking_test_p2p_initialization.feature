Feature: test_p2p_initialization function from scripts/test_p2p_networking.py
  This function tests P2P cache can initialize with networking enabled

  Scenario: Set P2P environment variables
    Given CACHE_ENABLE_P2P set to "true"
    When creating GitHubAPICache with enable_p2p true
    Then cache is created

  Scenario: Verify P2P enabled status
    Given cache instance created
    When calling get_stats
    Then p2p_enabled status is true
    And function returns true

  Scenario: P2P enabled but not active
    Given cache with p2p_enabled false
    When checking status
    Then function returns true with warning

  Scenario: P2P initialization fails
    Given P2P cannot initialize
    When calling test_p2p_initialization
    Then function returns false
