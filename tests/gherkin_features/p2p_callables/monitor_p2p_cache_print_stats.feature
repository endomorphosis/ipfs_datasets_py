Feature: print_stats function from scripts/monitor_p2p_cache.py
  This function prints cache statistics

  Scenario: Display cache statistics
    Given cache instance with stats
    When calling print_stats
    Then cache size displays
    And max size displays
    And fill rate displays
    And total requests displays
    And hit rate displays

  Scenario: Display P2P networking status
    Given cache with P2P enabled
    When calling print_stats
    Then P2P status shows ENABLED
    And connected peers count displays

  Scenario: Display security status
    Given cache with encryption cipher
    When calling print_stats
    Then encryption status shows ENABLED
    And key derivation method displays

  Scenario: Display performance metrics
    Given cache with requests processed
    When calling print_stats
    Then API reduction percentage displays
    And time saved displays
    And rate limit impact displays
