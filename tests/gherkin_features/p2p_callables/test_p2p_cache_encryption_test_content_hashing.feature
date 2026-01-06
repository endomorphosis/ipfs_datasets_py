Feature: test_content_hashing function from scripts/test_p2p_cache_encryption.py
  This function tests content-addressable hashing with IPFS multiformats

  Scenario: Extract validation fields
    Given test repos with updatedAt fields
    When calling _extract_validation_fields
    Then validation fields are returned

  Scenario: Compute content hash
    Given validation fields extracted
    When calling _compute_validation_hash
    Then content hash is returned

  Scenario: Hash is deterministic
    Given same validation fields
    When computing hash twice
    Then both hashes are identical

  Scenario: Hash changes with data
    Given modified validation fields
    When computing new hash
    Then new hash differs from original hash

  Scenario: Hash changes with data - assertion 2
    Given modified validation fields
    When computing new hash
    Then function returns true

  Scenario: Content hashing fails
    Given hashing operation raises exception
    When calling test_content_hashing
    Then function returns false
