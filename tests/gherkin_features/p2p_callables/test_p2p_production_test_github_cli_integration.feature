Feature: test_github_cli_integration function from scripts/test_p2p_production.py
  This function tests GitHub CLI wrapper integration

  Scenario: Create GitHubCLI instance with P2P
    Given P2P environment enabled
    When creating GitHubCLI instance
    Then GitHubCLI creates successfully

  Scenario: Check cache integration with GitHubCLI
    Given GitHubCLI instance created
    When getting global cache
    Then cache is integrated with GitHubCLI

  Scenario: Check cache integration with GitHubCLI - assertion 2
    Given GitHubCLI instance created
    When getting global cache
    Then cache statistics are available

  Scenario: Verify cache P2P status with GitHubCLI
    Given GitHubCLI with cache
    When checking cache stats
    Then stats contain p2p_enabled field

  Scenario: Verify cache P2P status with GitHubCLI - assertion 2
    Given GitHubCLI with cache
    When checking cache stats
    Then stats contain cache_size field
