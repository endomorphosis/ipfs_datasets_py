Feature: test_libp2p function from scripts/verify_p2p_cache.py
  This function tests libp2p library

  Scenario: Import and create libp2p host
    When importing from libp2p
    Then new_host function is available

  Scenario: Create libp2p host with ID
    Given libp2p package installed
    When calling new_host
    Then host has non-null ID

  Scenario: Create libp2p host with ID - assertion 2
    Given libp2p package installed
    When calling new_host
    Then function returns true

  Scenario: Libp2p library missing
    Given libp2p package not installed
    When calling test_libp2p
    Then exception is caught

  Scenario: Libp2p library missing - assertion 2
    Given libp2p package not installed
    When calling test_libp2p
    Then function returns false
