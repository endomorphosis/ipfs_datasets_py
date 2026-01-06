Feature: print_stats function from scripts/monitor_p2p_cache.py
  This function prints cache statistics

  Scenario: Display cache statistics
    Given cache instance with stats
    When calling print_stats
    Then cache size displays

  Scenario: Display cache statistics - assertion 2
    Given cache instance with stats
    When calling print_stats
    Then max size displays

  Scenario: Display cache statistics - assertion 3
    Given cache instance with stats
    When calling print_stats
    Then fill rate displays

  Scenario: Display cache statistics - assertion 4
    Given cache instance with stats
    When calling print_stats
    Then total requests displays

  Scenario: Display cache statistics - assertion 5
    Given cache instance with stats
    When calling print_stats
    Then hit rate displays

  Scenario: Display P2P networking status
    Given cache with P2P enabled
    When calling print_stats
    Then P2P status shows ENABLED

  Scenario: Display P2P networking status - assertion 2
    Given cache with P2P enabled
    When calling print_stats
    Then connected peers count displays

  Scenario: Display security status
    Given cache with encryption cipher
    When calling print_stats
    Then encryption status shows ENABLED

  Scenario: Display security status - assertion 2
    Given cache with encryption cipher
    When calling print_stats
    Then key derivation method displays

  Scenario: Display performance metrics
    Given cache with requests processed
    When calling print_stats
    Then API reduction percentage displays

  Scenario: Display performance metrics - assertion 2
    Given cache with requests processed
    When calling print_stats
    Then time saved displays

  Scenario: Display performance metrics - assertion 3
    Given cache with requests processed
    When calling print_stats
    Then rate limit impact displays
