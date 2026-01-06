Feature: test_encryption_with_p2p function from scripts/test_p2p_networking.py
  This function tests encryption works with P2P enabled

  Scenario: Initialize cache with P2P and encryption
    Given CACHE_ENABLE_P2P set to "true"
    When creating GitHubAPICache
    Then cache is created with P2P

  Scenario: Check encryption initialization
    Given cache with encryption_key
    When checking _encryption_key attribute
    Then encryption key is initialized

  Scenario: Encrypt message with P2P
    Given test data dictionary
    When calling _encrypt_message
    Then encrypted bytes are returned

  Scenario: Decrypt message with P2P
    Given encrypted message
    When calling _decrypt_message
    Then decrypted data matches original
    And function returns true

  Scenario: Encryption not initialized
    Given cache without encryption_key
    When calling test_encryption_with_p2p
    Then function returns true with warning
