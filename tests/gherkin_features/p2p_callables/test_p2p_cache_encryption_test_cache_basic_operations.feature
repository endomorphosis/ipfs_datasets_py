Feature: test_cache_basic_operations function from scripts/test_p2p_cache_encryption.py
  This function tests basic cache operations

  Scenario: Put data in cache
    Given GitHubAPICache with TTL 5
    When putting test data with key "list_repos"
    Then data is cached

  Scenario: Get data from cache
    Given cache with data at "list_repos"
    When getting data from cache
    Then retrieved data equals original data

  Scenario: Test TTL expiration
    Given cached data with TTL 5
    When waiting 6 seconds
    And getting data from cache
    Then data returns None

  Scenario: Test TTL expiration - assertion 2
    Given cached data with TTL 5
    When waiting 6 seconds
    And getting data from cache
    Then function returns true

  Scenario: Test cache statistics
    Given cache with operations performed
    When calling get_stats
    Then stats contain hits greater than 0

  Scenario: Test cache statistics - assertion 2
    Given cache with operations performed
    When calling get_stats
    Then stats contain misses greater than 0

  Scenario: Cache operations fail
    Given cache operation raises exception
    When calling test_cache_basic_operations
    Then function returns false
