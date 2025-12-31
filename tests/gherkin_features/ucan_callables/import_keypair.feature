Feature: UCANManager.import_keypair()
  Tests the import_keypair() method of UCANManager.
  This callable imports an existing keypair into the manager.

  Background:
    Given a UCANManager instance is initialized
    And the cryptography module is available
    And a valid PEM-encoded public key is available
    And a valid PEM-encoded private key is available

  Scenario: Import keypair with public and private keys returns instance
    When import_keypair() is called with public_key_pem and private_key_pem
    Then a UCANKeyPair instance is returned

  Scenario: Imported keypair has did attribute starting with did:key:
    When import_keypair() is called with public_key_pem and private_key_pem
    Then the keypair has did attribute starting with "did:key:"

  Scenario: Imported keypair public_key_pem matches input
    When import_keypair() is called with public_key_pem and private_key_pem
    Then the keypair public_key_pem matches input public_key_pem

  Scenario: Imported keypair private_key_pem matches input
    When import_keypair() is called with public_key_pem and private_key_pem
    Then the keypair private_key_pem matches input private_key_pem

  Scenario: Imported keypair is stored in keypairs dictionary
    When import_keypair() is called with public_key_pem and private_key_pem
    Then the keypair is stored in keypairs dictionary

  Scenario: Import keypair with public key only returns instance
    When import_keypair() is called with public_key_pem and private_key_pem=None
    Then a UCANKeyPair instance is returned

  Scenario: Import public key only has matching public_key_pem
    When import_keypair() is called with public_key_pem and private_key_pem=None
    Then the keypair public_key_pem matches input

  Scenario: Import public key only has private_key_pem None
    When import_keypair() is called with public_key_pem and private_key_pem=None
    Then the keypair private_key_pem is None

  Scenario: Import keypair generates DID from public key
    When import_keypair() is called with public_key_pem
    Then the did is "did:key:" plus SHA-256 hash of public_key_pem

  Scenario: Import keypair DID computed consistently
    When import_keypair() is called with public_key_pem
    Then the did is computed consistently for same public key

  Scenario: Import keypair updates keypairs.json file
    When import_keypair() is called with public and private keys
    Then keypairs.json file is updated

  Scenario: Import keypair adds to file
    When import_keypair() is called with public and private keys
    Then the file contains the new keypair

  Scenario: Import keypair prints success message
    When import_keypair() is called with public and private keys
    Then a success message is printed with keypair count

  Scenario: Import keypair fails when manager not initialized
    Given the manager initialized attribute is False
    When import_keypair() is called with valid keys
    Then RuntimeError is raised with message "UCAN manager not initialized"

  Scenario: Import keypair fails when cryptography unavailable
    Given the manager is initialized
    Given CRYPTOGRAPHY_AVAILABLE is False
    When import_keypair() is called with valid keys
    Then RuntimeError is raised with message "Cryptography module not available"

  Scenario: Import same keypair twice creates single entry
    Given a keypair has been imported with did "did:key:abc123"
    When import_keypair() is called again with same public_key_pem
    Then the keypairs dictionary contains only 1 entry for "did:key:abc123"

  Scenario: Import same keypair twice uses second import attributes
    Given a keypair has been imported with did "did:key:abc123"
    When import_keypair() is called again with same public_key_pem
    Then the keypair attributes are from the second import
