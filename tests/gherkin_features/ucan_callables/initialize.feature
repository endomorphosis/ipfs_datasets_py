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

  Scenario: Initialize sets initialized attribute to True
    Given the cryptography module is installed
    When initialize() is called
    Then the initialized attribute is set to True

  Scenario: Initialize loads keypairs from keypairs.json
    Given the cryptography module is installed
    When initialize() is called
    Then keypairs are loaded from keypairs.json

  Scenario: Initialize loads tokens from tokens.json
    Given the cryptography module is installed
    When initialize() is called
    Then tokens are loaded from tokens.json

  Scenario: Initialize loads revocations from revocations.json
    Given the cryptography module is installed
    When initialize() is called
    Then revocations are loaded from revocations.json

  Scenario: Initialize fails when cryptography module is missing
    Given the cryptography module is not installed
    When initialize() is called
    Then the method returns False

  Scenario: Initialize leaves initialized attribute False when cryptography missing
    Given the cryptography module is not installed
    When initialize() is called
    Then the initialized attribute remains False

  Scenario: Initialize prints warning when cryptography missing
    Given the cryptography module is not installed
    When initialize() is called
    Then a warning message is printed to stdout

  Scenario: Initialize returns True with empty storage
    Given the storage files do not exist
    Given the cryptography module is installed
    When initialize() is called
    Then the method returns True

  Scenario: Initialize creates empty keypairs dictionary with empty storage
    Given the storage files do not exist
    Given the cryptography module is installed
    When initialize() is called
    Then the keypairs dictionary is empty

  Scenario: Initialize creates empty tokens dictionary with empty storage
    Given the storage files do not exist
    Given the cryptography module is installed
    When initialize() is called
    Then the tokens dictionary is empty

  Scenario: Initialize creates empty revocations dictionary with empty storage
    Given the storage files do not exist
    Given the cryptography module is installed
    When initialize() is called
    Then the revocations dictionary is empty

  Scenario: Initialize loads 3 keypairs from file
    Given keypairs.json contains 3 keypairs
    Given the cryptography module is installed
    When initialize() is called
    Then the keypairs dictionary contains 3 entries

  Scenario: Loaded keypairs have did attribute
    Given keypairs.json contains 3 keypairs
    Given the cryptography module is installed
    When initialize() is called
    Then each keypair has did attribute

  Scenario: Loaded keypairs have public_key_pem attribute
    Given keypairs.json contains 3 keypairs
    Given the cryptography module is installed
    When initialize() is called
    Then each keypair has public_key_pem attribute
