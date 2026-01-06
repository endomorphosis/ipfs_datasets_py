Feature: test_libp2p_dependencies function from scripts/test_p2p_cache_encryption.py
  This function tests libp2p dependencies

  Scenario: Import new_host from libp2p
    When importing libp2p.new_host
    Then import succeeds

  Scenario: Import new_host from libp2p - assertion 2
    When importing libp2p.new_host
    Then function returns true

  Scenario: Libp2p missing
    Given libp2p package not installed
    When calling test_libp2p_dependencies
    Then warning message displays

  Scenario: Libp2p missing - assertion 2
    Given libp2p package not installed
    When calling test_libp2p_dependencies
    Then function returns false
