Feature: UCANManager.get_capabilities()
  Tests the get_capabilities() method of UCANManager.
  This callable retrieves all capabilities granted to a DID.

  Background:
    Given a UCANManager instance is initialized
    And a token exists with audience="did:key:bob"
    And the token is valid and not expired
    And the token has 2 capabilities

  Scenario: Get capabilities returns list of UCANCapability instances
    When get_capabilities() is called with did="did:key:bob"
    Then a list of UCANCapability instances is returned

  Scenario: Get capabilities list contains 2 capabilities
    When get_capabilities() is called with did="did:key:bob"
    Then the list contains 2 capabilities

  Scenario: Each capability has resource attribute
    When get_capabilities() is called with did="did:key:bob"
    Then each capability has resource attribute

  Scenario: Each capability has action attribute
    When get_capabilities() is called with did="did:key:bob"
    Then each capability has action attribute

  Scenario: Each capability has caveats dictionary
    When get_capabilities() is called with did="did:key:bob"
    Then each capability has caveats dictionary

  Scenario: Get capabilities returns empty list when no tokens for DID
    When get_capabilities() is called with did="did:key:unknown"
    Then an empty list is returned

  Scenario: Get capabilities excludes expired tokens
    Given a token with audience="did:key:bob" is expired
    Given the expired token has 1 capability
    When get_capabilities() is called with did="did:key:bob"
    Then the expired token capabilities are not in returned list

  Scenario: Get capabilities excludes revoked tokens
    Given a token with audience="did:key:bob" is revoked
    Given the revoked token has 1 capability
    When get_capabilities() is called with did="did:key:bob"
    Then the revoked token capabilities are not in returned list

  Scenario: Get capabilities aggregates from multiple tokens
    Given 3 valid tokens exist with audience="did:key:bob"
    Given token 1 has 2 capabilities
    Given token 2 has 1 capability
    Given token 3 has 3 capabilities
    When get_capabilities() is called with did="did:key:bob"
    Then the list contains 6 capabilities total

  Scenario: Get capabilities verifies each token before including
    Given 2 tokens exist with audience="did:key:bob"
    Given token 1 is valid
    Given token 2 is invalid
    When get_capabilities() is called with did="did:key:bob"
    Then verify_token() is called for each token

  Scenario: Get capabilities returns only valid token capabilities
    Given 2 tokens exist with audience="did:key:bob"
    Given token 1 is valid
    Given token 2 is invalid
    When get_capabilities() is called with did="did:key:bob"
    Then only capabilities from token 1 are returned

  Scenario: Get capabilities returns duplicate capabilities
    Given 2 valid tokens with audience="did:key:bob"
    Given both tokens have capability for resource="file://data.txt" action="read"
    When get_capabilities() is called with did="did:key:bob"
    Then the list contains 2 entries

  Scenario: Duplicate capability entries have same resource and action
    Given 2 valid tokens with audience="did:key:bob"
    Given both tokens have capability for resource="file://data.txt" action="read"
    When get_capabilities() is called with did="did:key:bob"
    Then both entries have same resource and action

  Scenario: Get capabilities fails when manager not initialized
    Given the manager initialized attribute is False
    When get_capabilities() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
