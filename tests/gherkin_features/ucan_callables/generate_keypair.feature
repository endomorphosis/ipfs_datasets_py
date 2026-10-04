Feature: UCANManager.generate_keypair()
  Tests the generate_keypair() method of UCANManager.
  This callable generates a new RSA keypair for UCAN operations.

  Background:
    Given a UCANManager instance is initialized
    And the cryptography module is available

  Scenario: Generate keypair creates UCANKeyPair instance
    When generate_keypair() is called
    Then a UCANKeyPair instance is returned

  Scenario: Generated keypair has did attribute starting with did:key:
    When generate_keypair() is called
    Then the keypair has did attribute starting with "did:key:"

  Scenario: Generated keypair has public_key_pem starting with BEGIN PUBLIC KEY
    When generate_keypair() is called
    Then the keypair has public_key_pem starting with "-----BEGIN PUBLIC KEY-----"

  Scenario: Generated keypair has private_key_pem starting with BEGIN PRIVATE KEY
    When generate_keypair() is called
    Then the keypair has private_key_pem starting with "-----BEGIN PRIVATE KEY-----"

  Scenario: Generated keypair has created_at in ISO 8601 format
    When generate_keypair() is called
    Then the keypair has created_at in ISO 8601 format

  Scenario: Generated keypair has key_type set to RSA
    When generate_keypair() is called
    Then the keypair has key_type set to "RSA"

  Scenario: Generate keypair stores keypair in manager
    When generate_keypair() is called
    Then the returned keypair is stored in keypairs dictionary

  Scenario: Generated keypair is indexed by its did
    When generate_keypair() is called
    Then the keypair is indexed by its did

  Scenario: Generate keypair updates keypairs.json file
    When generate_keypair() is called
    Then keypairs.json file is updated

  Scenario: Generate keypair creates 3 different instances
    When generate_keypair() is called 3 times
    Then 3 different UCANKeyPair instances are returned

  Scenario: Generated keypairs have different dids
    When generate_keypair() is called 3 times
    Then each keypair has a different did

  Scenario: Generated keypairs have different public_key_pem
    When generate_keypair() is called 3 times
    Then each keypair has different public_key_pem

  Scenario: Generated keypairs have different private_key_pem
    When generate_keypair() is called 3 times
    Then each keypair has different private_key_pem

  Scenario: Generate keypair fails when manager not initialized
    Given the manager initialized attribute is False
    When generate_keypair() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"

  Scenario: Generate keypair fails when cryptography unavailable
    Given the manager is initialized
    Given CRYPTOGRAPHY_AVAILABLE is False
    When generate_keypair() is called
    Then RuntimeError is raised with message "Cryptography module not available"

  Scenario: Generated keypair DID is SHA-256 hash of public key
    When generate_keypair() is called
    Then the did is "did:key:" plus SHA-256 hash of public_key_pem

  Scenario: DID hash is computed from public_key_pem bytes
    When generate_keypair() is called
    Then the hash is computed from public_key_pem bytes
