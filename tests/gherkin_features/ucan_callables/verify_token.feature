Feature: UCANManager.verify_token()
  Tests the verify_token() method of UCANManager.
  This callable verifies the validity of a UCAN token.

  Background:
    Given a UCANManager instance is initialized
    And a token exists with token_id="token-123"
    And the token is signed and not expired

  Scenario: Verify token succeeds for valid token
    When verify_token() is called with token_id="token-123"
    Then a tuple (True, None) is returned
    And the first element is True
    And the second element is None

  Scenario: Verify token fails when token not found
    When verify_token() is called with token_id="nonexistent"
    Then a tuple (False, "Token not found") is returned

  Scenario: Verify token fails when token is revoked
    Given the token is in revocations dictionary
    When verify_token() is called with token_id="token-123"
    Then the first element is False
    And the second element contains "Token revoked"
    And the error message contains revoked_by DID
    And the error message contains revocation reason

  Scenario: Verify token fails when token is expired
    Given the token expires_at is 1 hour in the past
    When verify_token() is called with token_id="token-123"
    Then a tuple (False, "Token expired") is returned

  Scenario: Verify token fails when token not yet valid
    Given the token not_before is 1 hour in the future
    When verify_token() is called with token_id="token-123"
    Then a tuple (False, "Token not yet valid") is returned

  Scenario: Verify token fails when issuer not found
    Given the token issuer is "did:key:unknown"
    When verify_token() is called with token_id="token-123"
    Then the first element is False
    And the second element contains "Issuer" and "not found"

  Scenario: Verify token fails when signature missing
    Given the token signature is None
    When verify_token() is called with token_id="token-123"
    Then a tuple (False, "Token not signed") is returned

  Scenario: Verify token validates proof token when present
    Given the token has proof="parent-token-456"
    And parent token is valid and not expired
    When verify_token() is called with token_id="token-123"
    Then verify_token() is called recursively with token_id="parent-token-456"
    And the first element is True if proof is valid

  Scenario: Verify token fails when proof token invalid
    Given the token has proof="parent-token-456"
    And parent token is expired
    When verify_token() is called with token_id="token-123"
    Then the first element is False
    And the second element contains "Proof verification failed"

  Scenario: Verify token checks proof token delegation rights
    Given the token has proof="parent-token-456"
    And parent token audience does not match token issuer
    When verify_token() is called with token_id="token-123"
    Then a tuple (False, "Proof token audience does not match issuer") is returned

  Scenario: Verify token requires delegation capability in proof
    Given the token has proof="parent-token-456"
    And parent token has no "delegate" action capability
    When verify_token() is called with token_id="token-123"
    Then a tuple (False, "Proof token does not have delegation capability") is returned

  Scenario: Verify token fails when manager not initialized
    Given the manager initialized attribute is False
    When verify_token() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
