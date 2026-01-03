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

  Scenario: Revoke stores UCANRevocation in revocations dictionary
    When revoke_token() is called with token_id="token-123", revoker_did="did:key:alice", reason="compromised"
    Then a UCANRevocation is stored in revocations dictionary

  Scenario: Revocation has correct token_id
    When revoke_token() is called with token_id="token-123", revoker_did="did:key:alice", reason="compromised"
    Then the revocation token_id is "token-123"

  Scenario: Revocation has correct revoked_by
    When revoke_token() is called with token_id="token-123", revoker_did="did:key:alice", reason="compromised"
    Then the revocation revoked_by is "did:key:alice"

  Scenario: Revocation has correct reason
    When revoke_token() is called with token_id="token-123", revoker_did="did:key:alice", reason="compromised"
    Then the revocation reason is "compromised"

  Scenario: Revoke token updates revocations.json file
    When revoke_token() is called with token_id="token-123", revoker_did="did:key:alice", reason="compromised"
    Then revocations.json file is updated

  Scenario: Revoke token succeeds when revoker is audience
    When revoke_token() is called with revoker_did="did:key:bob", reason="no longer needed"
    Then True is returned

  Scenario: Revocation by audience has correct revoked_by
    When revoke_token() is called with revoker_did="did:key:bob", reason="no longer needed"
    Then the revocation revoked_by is "did:key:bob"

  Scenario: Revoke token fails when revoker is neither issuer nor audience
    When revoke_token() is called with revoker_did="did:key:charlie", reason="test"
    Then False is returned

  Scenario: Revoke by unauthorized revoker stores no revocation
    When revoke_token() is called with revoker_did="did:key:charlie", reason="test"
    Then no revocation is stored

  Scenario: Revoke token fails when token not found
    When revoke_token() is called with token_id="nonexistent"
    Then False is returned

  Scenario: Revoke token creates revocation with timestamp
    When revoke_token() is called with valid parameters
    Then the revocation revoked_at is in ISO 8601 format

  Scenario: Revocation timestamp is approximately current time
    When revoke_token() is called with valid parameters
    Then the revoked_at timestamp is approximately current time

  Scenario: Revoke token persists revocation to storage
    When revoke_token() is called with valid parameters
    Then revocations.json file contains the new revocation

  Scenario: Revoke token prints success message
    When revoke_token() is called with valid parameters
    Then a success message is printed with revocation count

  Scenario: Revoke token allows revoking already revoked token
    Given the token is already revoked
    When revoke_token() is called by issuer
    Then True is returned

  Scenario: Revoke already revoked token updates revocation
    Given the token is already revoked
    When revoke_token() is called by issuer
    Then the revocation is updated

  Scenario: Revoke token fails when manager not initialized
    Given the manager initialized attribute is False
    When revoke_token() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
