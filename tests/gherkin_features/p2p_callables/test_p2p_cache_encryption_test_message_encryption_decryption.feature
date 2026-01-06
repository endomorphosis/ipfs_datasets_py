Feature: test_message_encryption_decryption function from scripts/test_p2p_cache_encryption.py
  This function tests message encryption and decryption

  Scenario: Encrypt test message
    Given cache with encryption initialized
    And test message with key and entry
    When calling _encrypt_message
    Then encrypted bytes are returned

  Scenario: Encrypt test message - assertion 2
    Given cache with encryption initialized
    And test message with key and entry
    When calling _encrypt_message
    Then encrypted data differs from plaintext

  Scenario: Decrypt encrypted message
    Given encrypted message
    When calling _decrypt_message
    Then decrypted message is returned

  Scenario: Verify decryption matches original
    Given original test message
    And encrypted then decrypted message
    When comparing messages
    Then decrypted equals original

  Scenario: Verify decryption matches original - assertion 2
    Given original test message
    And encrypted then decrypted message
    When comparing messages
    Then function returns true

  Scenario: Encryption or decryption fails
    Given encryption operation raises exception
    When calling test_message_encryption_decryption
    Then function returns false
