Feature: test_github_cli_integration function from scripts/test_p2p_cache_encryption.py
  This function tests GitHub CLI uses cache correctly

  Scenario: Create GitHubCLI instance
    Given enable_cache true
    When creating GitHubCLI instance
    Then GitHubCLI is created

  Scenario: Get global cache instance
    Given GitHubCLI created
    When calling get_global_cache
    Then cache instance is retrieved

  Scenario: Check encryption status
    Given cache instance
    When checking _cipher attribute
    Then encryption status is reported

  Scenario: Check cache statistics
    Given cache instance
    When calling get_stats
    Then stats contain cache_size
    And stats contain p2p_enabled
    And stats contain total_requests
    And stats contain hit_rate
    And function returns true

  Scenario: GitHub CLI integration fails
    Given GitHubCLI creation raises exception
    When calling test_github_cli_integration
    Then function returns false
