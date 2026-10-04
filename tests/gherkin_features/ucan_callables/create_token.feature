Feature: UCANManager.create_token()
  Tests the create_token() method of UCANManager.
  This callable creates a new UCAN authorization token.

  Background:
    Given a UCANManager instance is initialized
    And issuer keypair exists with did="did:key:alice" and private key
    And audience keypair exists with did="did:key:bob"
    And a UCANCapability with resource="file://data.txt" and action="read"

  Scenario: Create token with single capability returns instance
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then a UCANToken instance is returned

  Scenario: Created token has token_id as UUID string
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then the token has token_id as UUID string

  Scenario: Created token has correct issuer
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then the token issuer is "did:key:alice"

  Scenario: Created token has correct audience
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then the token audience is "did:key:bob"

  Scenario: Created token capabilities contains 1 entry
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then the token capabilities contains 1 entry

  Scenario: Created token expires_at is ttl seconds from now
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then the token expires_at is ttl seconds from now

  Scenario: Created token has signature attribute
    When create_token() is called with issuer_did, audience_did, and capabilities list
    Then the token has signature attribute

  Scenario: Create token with multiple capabilities contains 3 entries
    Given 3 UCANCapability instances for different resources
    When create_token() is called with capabilities list of 3
    Then the token capabilities contains 3 entries

  Scenario: Multiple capabilities each have resource attribute
    Given 3 UCANCapability instances for different resources
    When create_token() is called with capabilities list of 3
    Then each capability has resource attribute

  Scenario: Multiple capabilities each have action attribute
    Given 3 UCANCapability instances for different resources
    When create_token() is called with capabilities list of 3
    Then each capability has action attribute

  Scenario: Create token with custom TTL
    When create_token() is called with ttl=7200
    Then the token expires_at is 7200 seconds from now

  Scenario: Create token with not_before timestamp
    When create_token() is called with not_before="2025-01-01T00:00:00"
    Then the token not_before is "2025-01-01T00:00:00"

  Scenario: Create token with proof token ID
    Given a parent token exists with token_id="parent-123"
    When create_token() is called with proof="parent-123"
    Then the token proof is "parent-123"

  Scenario: Create token stores token in manager
    When create_token() is called with valid parameters
    Then the token is stored in tokens dictionary

  Scenario: Created token is indexed by token_id
    When create_token() is called with valid parameters
    Then the token is indexed by token_id

  Scenario: Create token updates tokens.json file
    When create_token() is called with valid parameters
    Then tokens.json file is updated

  Scenario: Create token generates JWT signature
    When create_token() is called with valid parameters
    Then the token signature is a JWT string

  Scenario: Token signature contains token_id as jti claim
    When create_token() is called with valid parameters
    Then the signature contains token_id as jti claim

  Scenario: Token signature contains issuer_did as iss claim
    When create_token() is called with valid parameters
    Then the signature contains issuer_did as iss claim

  Scenario: Token signature contains audience_did as aud claim
    When create_token() is called with valid parameters
    Then the signature contains audience_did as aud claim

  Scenario: Create token fails when manager not initialized
    Given the manager initialized attribute is False
    When create_token() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"

  Scenario: Create token fails when issuer not found
    When create_token() is called with issuer_did="did:key:unknown"
    Then ValueError is raised with message containing "not found"

  Scenario: Create token fails when issuer lacks private key
    Given issuer keypair has private_key_pem=None
    When create_token() is called
    Then ValueError is raised with message containing "does not have a private key"

  Scenario: Create token fails when audience not found
    When create_token() is called with audience_did="did:key:unknown"
    Then ValueError is raised with message containing "not found"

  Scenario: Create token fails with unsupported capability action
    Given a UCANCapability with action="invalid_action"
    When create_token() is called with this capability
    Then ValueError is raised with message containing "Unsupported capability action"
