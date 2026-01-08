Feature: print_stats function from scripts/monitor_p2p_cache.py
  This function prints cache statistics

  Scenario: Print stats outputs cache_size line
    Given cache with size 100
    When print_stats(cache) is called
    Then output contains "cache_size: 100"

  Scenario: Print stats outputs max_size line
    Given cache with max_size 1000
    When print_stats(cache) is called
    Then output contains "max_size: 1000"

  Scenario: Print stats outputs fill_rate as percentage
    Given cache with size 100 and max_size 1000
    When print_stats(cache) is called
    Then output contains "fill_rate: 10.0%"

  Scenario: Print stats outputs total_requests count
    Given cache with total_requests 500
    When print_stats(cache) is called
    Then output contains "total_requests: 500"

  Scenario: Print stats outputs hit_rate as percentage
    Given cache with hits 400 and total_requests 500
    When print_stats(cache) is called
    Then output contains "hit_rate: 80.0%"

  Scenario: Print stats outputs P2P status ENABLED
    Given cache with p2p_enabled True
    When print_stats(cache) is called
    Then output contains "P2P: ENABLED"

  Scenario: Print stats outputs connected_peers count
    Given cache with 3 connected peers
    When print_stats(cache) is called
    Then output contains "connected_peers: 3"

  Scenario: Print stats outputs encryption ENABLED
    Given cache with cipher initialized
    When print_stats(cache) is called
    Then output contains "encryption: ENABLED"

  Scenario: Print stats outputs key_derivation method
    Given cache with key_derivation "PBKDF2-HMAC-SHA256"
    When print_stats(cache) is called
    Then output contains "key_derivation: PBKDF2-HMAC-SHA256"

  Scenario: Print stats outputs api_reduction percentage
    Given cache preventing 300 API calls from 500 requests
    When print_stats(cache) is called
    Then output contains "api_reduction: 60.0%"

  Scenario: Print stats outputs time_saved in seconds
    Given cache saving 150 seconds
    When print_stats(cache) is called
    Then output contains "time_saved: 150s"

  Scenario: Print stats outputs rate_limit_impact count
    Given cache preventing 50 rate limit hits
    When print_stats(cache) is called
    Then output contains "rate_limit_impact: 50"
