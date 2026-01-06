Feature: test_wrong_key_decryption function from scripts/test_p2p_cache_encryption.py
  This function tests unauthorized decryption prevention

  Scenario: Create two caches with different keys
    Given cache1 with GitHub token key
    And cache2 with different Fernet key
    When both caches are initialized
    Then each has different cipher

  Scenario: Encrypt message with cache1
    Given test message
    When encrypting with cache1 _encrypt_message
    Then encrypted bytes are returned

  Scenario: Attempt decrypt with wrong key
    Given message encrypted with cache1
    When decrypting with cache2 _decrypt_message
    Then decryption returns None

  Scenario: Attempt decrypt with wrong key - assertion 2
    Given message encrypted with cache1
    When decrypting with cache2 _decrypt_message
    Then function returns true

  Scenario: Decryption succeeds with wrong key
    Given message encrypted with cache1
    When decrypting with cache2 succeeds
    Then security breach detected

  Scenario: Decryption succeeds with wrong key - assertion 2
    Given message encrypted with cache1
    When decrypting with cache2 succeeds
    Then function returns false
