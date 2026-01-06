Feature: test_cache_broadcast_mechanism function from scripts/test_p2p_networking.py
  This function tests cache broadcast mechanism is functional

  Scenario: Create cache with P2P for broadcasting
    Given CACHE_ENABLE_P2P enabled
    When creating GitHubAPICache
    Then cache is created

  Scenario: Trigger broadcast with put operation
    Given cache instance
    When putting test data with key "test/broadcast/endpoint"
    Then put operation completes
    And broadcast mechanism executes

  Scenario: Wait for async broadcast
    Given put operation completed
    When waiting 0.5 seconds
    Then async broadcast has time to execute

  Scenario: Verify broadcast executed without errors
    Given broadcast mechanism ran
    When checking operation result
    Then function returns true

  Scenario: Check cache statistics after broadcast
    Given cache with broadcast completed
    When calling get_stats
    Then statistics are returned
