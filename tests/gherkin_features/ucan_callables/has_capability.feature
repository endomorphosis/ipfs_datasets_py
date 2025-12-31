Feature: UCANManager.has_capability()
  Tests the has_capability() method of UCANManager.
  This callable checks if a DID has authorization for a resource and action.

  Background:
    Given a UCANManager instance is initialized
    And a valid token exists with audience="did:key:bob"
    And the token has capability resource="file://secret.txt" action="read"

  Scenario: Has capability returns True for exact match
    When has_capability() is called with did="did:key:bob", resource="file://secret.txt", action="read"
    Then True is returned

  Scenario: Has capability returns False when resource does not match
    When has_capability() is called with did="did:key:bob", resource="file://other.txt", action="read"
    Then False is returned

  Scenario: Has capability returns False when action does not match
    When has_capability() is called with did="did:key:bob", resource="file://secret.txt", action="write"
    Then False is returned

  Scenario: Has capability returns False when DID has no capabilities
    When has_capability() is called with did="did:key:unknown", resource="file://secret.txt", action="read"
    Then False is returned

  Scenario: Has capability matches wildcard resource with specific action
    Given a token has capability resource="*" action="read"
    When has_capability() is called with did="did:key:bob", resource="file://any.txt", action="read"
    Then True is returned

  Scenario: Has capability matches specific resource with wildcard action
    Given a token has capability resource="file://secret.txt" action="*"
    When has_capability() is called with did="did:key:bob", resource="file://secret.txt", action="write"
    Then True is returned

  Scenario: Has capability matches full wildcard
    Given a token has capability resource="*" action="*"
    When has_capability() is called with did="did:key:bob", resource="file://any.txt", action="delete"
    Then True is returned

  Scenario: Has capability returns False for expired token
    Given the token is expired
    When has_capability() is called with matching resource and action
    Then False is returned

  Scenario: Has capability returns False for revoked token
    Given the token is revoked
    When has_capability() is called with matching resource and action
    Then False is returned

  Scenario: Has capability checks all valid tokens for DID
    Given 3 valid tokens exist for did="did:key:bob"
    And only token 3 has capability resource="file://data.txt" action="write"
    When has_capability() is called with resource="file://data.txt" action="write"
    Then True is returned

  Scenario: Has capability returns True when any token matches
    Given token 1 has capability resource="file://a.txt" action="read"
    And token 2 has capability resource="file://b.txt" action="read"
    When has_capability() is called with resource="file://b.txt" action="read"
    Then True is returned

  Scenario: Has capability fails when manager not initialized
    Given the manager initialized attribute is False
    When has_capability() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"
