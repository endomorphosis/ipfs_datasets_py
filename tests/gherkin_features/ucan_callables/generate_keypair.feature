Feature: UCANManager.generate_keypair()
  Tests the generate_keypair() method of UCANManager.
  This callable generates a new RSA keypair for UCAN operations.

  Background:
    Given a UCANManager instance is initialized
    And the cryptography module is available

  Scenario: Generate keypair creates UCANKeyPair with all attributes
    When generate_keypair() is called
    Then a UCANKeyPair instance is returned
    And the keypair has did attribute starting with "did:key:"
    And the keypair has public_key_pem starting with "-----BEGIN PUBLIC KEY-----"
    And the keypair has private_key_pem starting with "-----BEGIN PRIVATE KEY-----"
    And the keypair has created_at in ISO 8601 format
    And the keypair has key_type set to "RSA"

  Scenario: Generate keypair stores keypair in manager
    When generate_keypair() is called
    Then the returned keypair is stored in keypairs dictionary
    And the keypair is indexed by its did
    And keypairs.json file is updated

  Scenario: Generate keypair creates unique DIDs
    When generate_keypair() is called 3 times
    Then 3 different UCANKeyPair instances are returned
    And each keypair has a different did
    And each keypair has different public_key_pem
    And each keypair has different private_key_pem

  Scenario: Generate keypair fails when manager not initialized
    Given the manager initialized attribute is False
    When generate_keypair() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"

  Scenario: Generate keypair fails when cryptography unavailable
    Given the manager is initialized
    And CRYPTOGRAPHY_AVAILABLE is False
    When generate_keypair() is called
    Then RuntimeError is raised with message "Cryptography module not available"

  Scenario: Generated keypair DID is SHA-256 hash of public key
    When generate_keypair() is called
    Then the did is "did:key:" plus SHA-256 hash of public_key_pem
    And the hash is computed from public_key_pem bytes
