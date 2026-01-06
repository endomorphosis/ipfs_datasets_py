Feature: test_multiformats function from scripts/verify_p2p_cache.py
  This function tests multiformats library

  Scenario: Import multiformats CID
    When importing from multiformats
    Then CID class is available

  Scenario: Multiformats library available
    Given multiformats package installed
    When calling test_multiformats
    Then function returns true

  Scenario: Multiformats library missing
    Given multiformats package not installed
    When calling test_multiformats
    Then ImportError is caught

  Scenario: Multiformats library missing - assertion 2
    Given multiformats package not installed
    When calling test_multiformats
    Then function returns false
