Feature: UCANManager.revoke_token()
  Tests the revoke_token() method of UCANManager.
  This callable revokes a UCAN token.

  Background:
    Given a UCANManager instance is initialized
    And a token exists with token_id="token-123"
    And the token issuer is "did:key:alice"
    And the token audience is "did:key:bob"

  Scenario: Revoke token succeeds when revoker is issuer
    When revoke_token() is called with token_id="token-123", revoker_did="did:key:alice", reason="compromised"
    Then True is returned
    And a UCANRevocation is stored in revocations dictionary
    And the revocation token_id is "token-123"
    And the revocation revoked_by is "did:key:alice"
    And the revocation reason is "compromised"
    And revocations.json file is updated

  Scenario: Revoke token succeeds when revoker is audience
    When revoke_token() is called with revoker_did="did:key:bob", reason="no longer needed"
    Then True is returned
    And the revocation revoked_by is "did:key:bob"

  Scenario: Revoke token fails when revoker is neither issuer nor audience
    When revoke_token() is called with revoker_did="did:key:charlie", reason="test"
    Then False is returned
    And no revocation is stored

  Scenario: Revoke token fails when token not found
    When revoke_token() is called with token_id="nonexistent"
    Then False is returned

  Scenario: Revoke token creates revocation with timestamp
    When revoke_token() is called with valid parameters
    Then the revocation revoked_at is in ISO 8601 format
    And the revoked_at timestamp is approximately current time

  Scenario: Revoke token persists revocation to storage
    When revoke_token() is called with valid parameters
    Then revocations.json file contains the new revocation
    And a success message is printed with revocation count

  Scenario: Revoke token allows revoking already revoked token
    Given the token is already revoked
    When revoke_token() is called by issuer
    Then True is returned
    And the revocation is updated

  Scenario: Revoke token fails when manager not initialized
    Given the manager initialized attribute is False
    When revoke_token() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
