Feature: UCANManager.delegate_capability()
  Tests the delegate_capability() method of UCANManager.
  This callable delegates a capability from one DID to another.

  Background:
    Given a UCANManager instance is initialized
    And issuer keypair exists with did="did:key:alice"
    And audience keypair exists with did="did:key:bob"
    And alice has capability resource="key-123" action="encrypt"
    And alice has capability resource="key-123" action="delegate"

  Scenario: Delegate capability creates token with single capability
    When delegate_capability() is called with issuer_did="did:key:alice", audience_did="did:key:bob", resource="key-123", action="encrypt"
    Then a UCANToken instance is returned
    And the token issuer is "did:key:alice"
    And the token audience is "did:key:bob"
    And the token capabilities contains 1 entry
    And the capability resource is "key-123"
    And the capability action is "encrypt"

  Scenario: Delegate capability with caveats
    When delegate_capability() is called with caveats={"max_uses": 5}
    Then the token capability caveats contains "max_uses" with value 5

  Scenario: Delegate capability with custom TTL
    When delegate_capability() is called with ttl=7200
    Then the token expires_at is 7200 seconds from now

  Scenario: Delegate capability returns None when issuer lacks target capability
    Given alice does not have capability resource="key-789" action="decrypt"
    When delegate_capability() is called with resource="key-789", action="decrypt"
    Then None is returned

  Scenario: Delegate capability returns None when issuer lacks delegation right
    Given alice has capability resource="key-456" action="read"
    And alice does not have capability resource="key-456" action="delegate"
    When delegate_capability() is called with resource="key-456", action="read"
    Then None is returned

  Scenario: Delegate capability succeeds when issuer is resource owner
    When delegate_capability() is called with issuer_did="key-123", resource="key-123", action="encrypt"
    Then a UCANToken instance is returned
    And delegation succeeds without checking capabilities

  Scenario: Delegate capability calls create_token internally
    When delegate_capability() is called with valid parameters
    Then create_token() is called with issuer_did, audience_did, and capabilities
    And the created token is returned

  Scenario: Delegate capability stores token in manager
    When delegate_capability() is called with valid parameters
    Then the returned token is stored in tokens dictionary
    And tokens.json file is updated

  Scenario: Delegate capability fails when manager not initialized
    Given the manager initialized attribute is False
    When delegate_capability() is called
    Then RuntimeError is raised with message "UCAN manager not initialized"

  Scenario: Delegate capability without caveats uses empty dictionary
    When delegate_capability() is called with caveats=None
    Then the capability caveats is an empty dictionary

  Scenario: Delegate capability checks both target and delegate capabilities
    Given alice has capability resource="key-123" action="encrypt"
    And alice does not have capability resource="key-123" action="delegate"
    When delegate_capability() is called with resource="key-123", action="encrypt"
    Then None is returned
