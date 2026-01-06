Feature: test_encryption_functionality function from scripts/verify_p2p_cache.py
  This function tests encryption works

  Scenario: Test encryption with available cipher
    Given GitHubAPICache with cipher initialized
    When encrypting test data
    And decrypting encrypted data
    Then decrypted data matches original

  Scenario: Test encryption with available cipher - assertion 2
    Given GitHubAPICache with cipher initialized
    When encrypting test data
    And decrypting encrypted data
    Then function returns true

  Scenario: Test encryption without token
    Given GitHubAPICache without cipher
    When calling test_encryption_functionality
    Then function returns None

  Scenario: Test encryption fails
    Given encryption operation raises exception
    When calling test_encryption_functionality
    Then function returns false
