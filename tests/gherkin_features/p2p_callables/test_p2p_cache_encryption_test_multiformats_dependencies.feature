Feature: test_multiformats_dependencies function from scripts/test_p2p_cache_encryption.py
  This function tests multiformats dependencies

  Scenario: Import CID from multiformats
    When importing multiformats.CID
    Then import succeeds

  Scenario: Import multihash from multiformats
    When importing multiformats.multihash
    Then import succeeds

  Scenario: Multiformats available
    Given multiformats package installed
    When calling test_multiformats_dependencies
    Then function returns true

  Scenario: Multiformats missing
    Given multiformats package not installed
    When calling test_multiformats_dependencies
    Then warning message displays
    And function returns false
