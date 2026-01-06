Feature: main function from scripts/ci/init_p2p_cache.py
  This function initializes and tests P2P cache

  Scenario: Import P2P cache modules
    When importing from ipfs_datasets_py.cache
    And importing from ipfs_datasets_py.p2p_peer_registry
    Then imports succeed

  Scenario: Load configuration from environment
    Given environment variables set
    When reading configuration
    Then cache_dir is read
    And github_repo is read
    And cache_size is read
    And enable_p2p is read
    And enable_peer_discovery is read

  Scenario: Initialize cache with P2P
    Given configuration loaded
    When creating GitHubAPICache
    Then cache initializes successfully

  Scenario: Check peer registry active
    Given cache with _peer_registry
    When checking peer registry
    Then peer discovery is active

  Scenario: Discover peers
    Given active peer registry
    When calling discover_peers with max_peers 5
    Then peers list is returned
    And peer count displays

  Scenario: Test cache functionality
    Given initialized cache
    When putting test data
    And getting test data
    Then retrieved data matches original

  Scenario: Get cache statistics
    Given cache with operations
    When calling get_stats
    Then stats display total_entries
    And stats display hits
    And stats display misses
    And stats display peer_hits

  Scenario: All initialization succeeds
    Given cache is operational
    When main completes
    Then exit code is 0
    And success notice displays

  Scenario: P2P modules not available
    Given import fails
    When calling main
    Then warning message displays
    And exit code is 0

  Scenario: Initialization fails
    Given cache initialization raises exception
    When calling main
    Then exit code is 1
    And error message displays
