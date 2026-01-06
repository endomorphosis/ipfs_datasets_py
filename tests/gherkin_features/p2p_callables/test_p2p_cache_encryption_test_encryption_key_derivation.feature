Feature: test_encryption_key_derivation function from scripts/test_p2p_cache_encryption.py
  This function tests encryption key derivation from GitHub token

  Scenario: Create cache with encryption
    Given GitHub token available
    When creating GitHubAPICache in temp directory
    Then cache instance is created

  Scenario: Initialize encryption
    Given cache instance
    When calling _init_encryption
    Then encryption initialization succeeds
    And function returns true

  Scenario: Verify Fernet cipher created
    Given encryption initialized
    When checking _cipher attribute
    Then cipher is not None
    And cipher type is Fernet

  Scenario: Encryption initialization fails
    Given encryption cannot be initialized
    When calling test_encryption_key_derivation
    Then function returns false
