Feature: UCANManager.initialize()
  Tests the initialize() method of UCANManager.
  This callable loads keypairs, tokens, and revocations from storage.

  Background:
    Given a UCANManager instance is created via get_instance()
    And the default UCAN directory exists at ~/.ipfs_datasets/ucan

  Scenario: Initialize succeeds when cryptography module is available
    Given the cryptography module is installed
    When initialize() is called
    Then the method returns True
    And the initialized attribute is set to True
    And keypairs are loaded from keypairs.json
    And tokens are loaded from tokens.json
    And revocations are loaded from revocations.json

  Scenario: Initialize fails when cryptography module is missing
    Given the cryptography module is not installed
    When initialize() is called
    Then the method returns False
    And the initialized attribute remains False
    And a warning message is printed to stdout

  Scenario: Initialize with empty storage creates empty collections
    Given the storage files do not exist
    And the cryptography module is installed
    When initialize() is called
    Then the method returns True
    And the keypairs dictionary is empty
    And the tokens dictionary is empty
    And the revocations dictionary is empty

  Scenario: Initialize loads existing keypairs from file
    Given keypairs.json contains 3 keypairs
    And the cryptography module is installed
    When initialize() is called
    Then the keypairs dictionary contains 3 entries
    And each keypair has did attribute
    And each keypair has public_key_pem attribute
