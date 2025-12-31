Feature: UCANManager.get_capabilities()
  Tests the get_capabilities() method of UCANManager.
  This callable retrieves all capabilities granted to a DID.

  Background:
    Given a UCANManager instance is initialized
    And a token exists with audience="did:key:bob"
    And the token is valid and not expired
    And the token has 2 capabilities

  Scenario: Get capabilities returns capabilities from valid tokens
    When get_capabilities() is called with did="did:key:bob"
    Then a list of UCANCapability instances is returned
    And the list contains 2 capabilities
    And each capability has resource attribute
    And each capability has action attribute
    And each capability has caveats dictionary

  Scenario: Get capabilities returns empty list when no tokens for DID
    When get_capabilities() is called with did="did:key:unknown"
    Then an empty list is returned

  Scenario: Get capabilities excludes expired tokens
    Given a token with audience="did:key:bob" is expired
    And the expired token has 1 capability
    When get_capabilities() is called with did="did:key:bob"
    Then the expired token capabilities are not in returned list

  Scenario: Get capabilities excludes revoked tokens
    Given a token with audience="did:key:bob" is revoked
    And the revoked token has 1 capability
    When get_capabilities() is called with did="did:key:bob"
    Then the revoked token capabilities are not in returned list

  Scenario: Get capabilities aggregates from multiple tokens
    Given 3 valid tokens exist with audience="did:key:bob"
    And token 1 has 2 capabilities
    And token 2 has 1 capability
    And token 3 has 3 capabilities
    When get_capabilities() is called with did="did:key:bob"
    Then the list contains 6 capabilities total

  Scenario: Get capabilities verifies each token before including
    Given 2 tokens exist with audience="did:key:bob"
    And token 1 is valid
    And token 2 is invalid
    When get_capabilities() is called with did="did:key:bob"
    Then verify_token() is called for each token
    And only capabilities from token 1 are returned

  Scenario: Get capabilities returns duplicate capabilities
    Given 2 valid tokens with audience="did:key:bob"
    And both tokens have capability for resource="file://data.txt" action="read"
    When get_capabilities() is called with did="did:key:bob"
    Then the list contains 2 entries
    And both entries have same resource and action

  Scenario: Get capabilities fails when manager not initialized
    Given the manager initialized attribute is False
    When get_capabilities() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
