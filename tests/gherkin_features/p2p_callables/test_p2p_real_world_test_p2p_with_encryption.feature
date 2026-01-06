Feature: test_p2p_with_encryption function from scripts/test_p2p_real_world.py
  This async function tests P2P with encryption

  Scenario: Get GitHub token
    Given GITHUB_TOKEN in environment or gh CLI
    When retrieving token
    Then token is available

  Scenario: Derive encryption key from token
    Given GitHub token
    When using PBKDF2HMAC with SHA256
    Then encryption key is derived
    And Fernet cipher is created

  Scenario: Create P2P host
    Given encryption initialized
    When calling new_host
    Then host is created with ID

  Scenario: Encrypt test message
    Given test message dictionary
    When encrypting with cipher
    Then encrypted bytes are returned

  Scenario: Decrypt message
    Given encrypted bytes
    When decrypting with cipher
    Then decrypted message matches original
    And function returns true

  Scenario: Close host
    Given host running
    When calling close
    Then host closes cleanly

  Scenario: No GitHub token available
    Given GITHUB_TOKEN not available
    When calling test_p2p_with_encryption
    Then function returns true with warning
