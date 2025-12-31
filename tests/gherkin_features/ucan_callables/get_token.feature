Feature: UCANManager.get_token()
  Tests the get_token() method of UCANManager.
  This callable retrieves a token by its ID.

  Background:
    Given a UCANManager instance is initialized
    And 3 tokens are stored with IDs "token-1", "token-2", "token-3"

  Scenario: Get token returns existing token
    When get_token() is called with token_id="token-1"
    Then a UCANToken instance is returned
    And the token token_id is "token-1"
    And the token has issuer attribute
    And the token has audience attribute
    And the token has capabilities list
    And the token has expires_at attribute
    And the token has signature attribute

  Scenario: Get token returns None for unknown token ID
    When get_token() is called with token_id="nonexistent"
    Then None is returned

  Scenario: Get token returns None for empty token ID
    When get_token() is called with token_id=""
    Then None is returned

  Scenario: Get token returns correct token from multiple stored
    Given tokens dictionary contains 10 tokens
    When get_token() is called with token_id="token-2"
    Then the returned token token_id is "token-2"
    And the token is not "token-1"
    And the token is not "token-3"

  Scenario: Get token returns revoked tokens without validation
    Given token "token-1" is revoked
    When get_token() is called with token_id="token-1"
    Then a UCANToken instance is returned
    And the token is returned without revocation check

  Scenario: Get token returns expired tokens without validation
    Given token "token-1" is expired
    When get_token() is called with token_id="token-1"
    Then a UCANToken instance is returned
    And the token is returned without expiration check

  Scenario: Get token fails when manager not initialized
    Given the manager initialized attribute is False
    When get_token() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
