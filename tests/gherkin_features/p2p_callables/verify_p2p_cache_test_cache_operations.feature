Feature: test_cache_operations function from scripts/verify_p2p_cache.py
  This function tests basic cache operations

  Scenario: Test cache put operation
    Given GitHubAPICache instance
    When putting data with key "test_key"
    Then put operation succeeds

  Scenario: Test cache get operation
    Given cache with data at "test_key"
    When getting data from cache
    Then retrieved data equals original data

  Scenario: Test cache get operation - assertion 2
    Given cache with data at "test_key"
    When getting data from cache
    Then function returns true

  Scenario: Cache operations fail
    Given cache operation raises exception
    When calling test_cache_operations
    Then function returns false
