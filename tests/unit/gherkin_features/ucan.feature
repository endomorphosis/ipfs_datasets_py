Feature: UCAN Authorization
  User Controlled Authorization Network tokens and capabilities

  Scenario: Create UCAN token
    Given a user identity and capabilities
    When a UCAN token is created
    Then the token contains the specified capabilities

  Scenario: Sign UCAN token
    Given an unsigned UCAN token and a private key
    When the token is signed
    Then a valid signature is attached

  Scenario: Verify UCAN token signature
    Given a signed UCAN token
    When signature verification is performed
    Then the signature is validated

  Scenario: Check UCAN token expiration
    Given a UCAN token with expiration time
    When the current time is checked
    Then the expiration status is returned

  Scenario: Delegate UCAN capabilities
    Given an existing UCAN token
    When capabilities are delegated
    Then a new token with reduced capabilities is created

  Scenario: Validate UCAN capability chain
    Given a chain of delegated UCAN tokens
    When the chain is validated
    Then each delegation is verified

  Scenario: Revoke UCAN token
    Given an active UCAN token
    When revocation is requested
    Then the token is added to revocation list

  Scenario: Parse UCAN token
    Given a serialized UCAN token
    When the token is parsed
    Then the token structure is extracted

  Scenario: Encode UCAN token
    Given a UCAN token structure
    When the token is encoded
    Then a serialized token string is returned

  Scenario: Verify UCAN audience
    Given a UCAN token with audience claim
    When audience verification is performed
    Then the audience matches expected value
