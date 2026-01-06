Feature: test_github_token function from scripts/verify_p2p_cache.py
  This function tests GitHub token availability

  Scenario: GitHub token in environment variable
    Given GITHUB_TOKEN environment variable is set
    When calling test_github_token
    Then function returns true

  Scenario: GitHub token from gh CLI
    Given GITHUB_TOKEN not in environment
    And gh auth token command succeeds
    When calling test_github_token
    Then function returns true

  Scenario: No GitHub token available
    Given GITHUB_TOKEN not in environment
    And gh auth token command fails
    When calling test_github_token
    Then function returns false
