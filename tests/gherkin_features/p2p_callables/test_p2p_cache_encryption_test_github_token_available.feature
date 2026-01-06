Feature: test_github_token_available function from scripts/test_p2p_cache_encryption.py
  This function tests GitHub token availability

  Scenario: Token from environment variable
    Given GITHUB_TOKEN environment variable is set
    When calling test_github_token_available
    Then token prefix displays
    And function returns true

  Scenario: Token from gh CLI
    Given GITHUB_TOKEN not in environment
    And gh auth token command succeeds with output
    When calling test_github_token_available
    Then token is retrieved from gh CLI
    And GITHUB_TOKEN environment variable is set
    And function returns true

  Scenario: No token available
    Given GITHUB_TOKEN not in environment
    And gh auth token command fails
    When calling test_github_token_available
    Then error message displays
    And function returns false
