Feature: test_github_cli_with_p2p function from scripts/test_p2p_networking.py
  This function tests GitHub CLI integration with P2P cache

  Scenario: Create GitHubCLI with P2P enabled
    Given CACHE_ENABLE_P2P set to "true"
    When creating GitHubCLI instance
    Then GitHubCLI is created

  Scenario: Get global cache from GitHubCLI
    Given GitHubCLI instance
    When calling get_global_cache
    Then cache instance is returned

  Scenario: Get global cache from GitHubCLI - assertion 2
    Given GitHubCLI instance
    When calling get_global_cache
    Then cache stats show p2p_enabled

  Scenario: Try GitHub CLI version command
    Given GitHubCLI created
    When running version command
    Then command executes or shows not authenticated

  Scenario: Verify GitHubCLI P2P integration
    Given GitHubCLI with P2P cache
    When checking integration
    Then function returns true
