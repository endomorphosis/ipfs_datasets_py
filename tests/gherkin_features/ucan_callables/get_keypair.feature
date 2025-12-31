Feature: UCANManager.get_keypair()
  Tests the get_keypair() method of UCANManager.
  This callable retrieves a keypair by its DID.

  Background:
    Given a UCANManager instance is initialized
    And 3 keypairs are stored with DIDs "did:key:alice", "did:key:bob", "did:key:charlie"

  Scenario: Get keypair returns existing keypair
    When get_keypair() is called with did="did:key:alice"
    Then a UCANKeyPair instance is returned
    And the keypair did is "did:key:alice"
    And the keypair has public_key_pem attribute
    And the keypair has private_key_pem attribute

  Scenario: Get keypair returns None for unknown DID
    When get_keypair() is called with did="did:key:unknown"
    Then None is returned

  Scenario: Get keypair returns None for empty DID
    When get_keypair() is called with did=""
    Then None is returned

  Scenario: Get keypair fails when manager not initialized
    Given the manager initialized attribute is False
    When get_keypair() is called with did="did:key:alice"
    Then RuntimeError is raised with message "UCAN manager not initialized"

  Scenario: Get keypair returns correct keypair from multiple stored
    Given keypairs dictionary contains 10 keypairs
    When get_keypair() is called with did="did:key:bob"
    Then the returned keypair did is "did:key:bob"
    And the keypair is not "did:key:alice"
    And the keypair is not "did:key:charlie"
