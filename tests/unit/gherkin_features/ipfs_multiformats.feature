Feature: IPFS Multiformats
  Content identifier generation and validation using IPFS multiformats

  Scenario: Generate SHA-256 hash for file
    Given a file exists at a path
    When the SHA-256 hash is generated
    Then a hash digest is returned

  Scenario: Generate multihash from SHA-256 digest
    Given a SHA-256 hash digest
    When the digest is wrapped in multihash format
    Then a multihash object is returned

  Scenario: Generate CID for file content
    Given a file exists at a path
    When a CID is generated for the file
    Then a valid CIDv1 string is returned

  Scenario: Generate CID for string content
    Given a string content
    When a CID is generated for the string
    Then a valid CIDv1 string is returned

  Scenario: Process large file in chunks
    Given a large file exists
    When the SHA-256 hash is generated
    Then the file is processed in chunks
    And the hash digest is correct

  Scenario: Handle temporary file for string content
    Given a string content
    When a CID is generated
    Then a temporary file is created
    And the temporary file is cleaned up

  Scenario: Validate CID format
    Given a generated CID
    When the CID format is checked
    Then the CID follows multiformats specification

  Scenario: Generate deterministic CIDs
    Given identical file content
    When CIDs are generated multiple times
    Then all generated CIDs are identical

  Scenario: Support base32 encoding
    Given a file content
    When a CID is generated
    Then the CID uses base32 encoding
