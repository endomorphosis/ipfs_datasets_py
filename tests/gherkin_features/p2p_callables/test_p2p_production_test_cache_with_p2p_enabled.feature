Feature: test_cache_with_p2p_enabled function from scripts/test_p2p_production.py
  This function tests cache with P2P enabled

  Scenario: Enable P2P via environment variables
    Given environment variable CACHE_ENABLE_P2P set to "true"
    And environment variable P2P_LISTEN_PORT set to "9000"
    When creating GitHubAPICache with enable_p2p true
    Then cache p2p_enabled status is true

  Scenario: Create cache instance with P2P
    Given P2P environment configured
    When creating GitHubAPICache instance
    Then cache creation succeeds

  Scenario: Create cache instance with P2P - assertion 2
    Given P2P environment configured
    When creating GitHubAPICache instance
    Then cache statistics show p2p_enabled true

  Scenario: Test cache put operation
    Given cache with P2P enabled
    When putting test data with key "test/production/endpoint"
    Then put operation completes successfully

  Scenario: Test cache get operation
    Given cache with data at key "test/production/endpoint"
    When getting data from cache
    Then retrieved data matches original data

  Scenario: Check cache statistics
    Given active P2P cache
    When calling get_stats
    Then stats contain hits count

  Scenario: Check cache statistics - assertion 2
    Given active P2P cache
    When calling get_stats
    Then stats contain misses count

  Scenario: Check cache statistics - assertion 3
    Given active P2P cache
    When calling get_stats
    Then stats contain hit_rate

  Scenario: Check cache statistics - assertion 4
    Given active P2P cache
    When calling get_stats
    Then stats contain p2p_enabled status

  Scenario: Verify encryption status
    Given cache instance
    When checking encryption cipher
    Then encryption status is reported
