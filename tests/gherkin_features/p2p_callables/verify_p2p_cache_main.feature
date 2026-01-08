Feature: main function from scripts/verify_p2p_cache.py
  This function runs main verification

  Scenario: Main runs dependency checks
    When main() is called
    Then check("cryptography", test_cryptography) is called

  Scenario: Main runs configuration checks
    When main() is called
    Then check("github_token", test_github_token) is called

  Scenario: Main runs functionality checks
    When main() is called
    Then check("cache_operations", test_cache_operations) is called

  Scenario: Main runs test suite check
    When main() is called
    Then check("test_suite", run_test_suite) is called

  Scenario: All checks pass returns exit code 0
    Given all check() calls return True
    When main() completes
    Then sys.exit(0) is called

  Scenario: All checks pass outputs success
    Given all check() calls return True
    When main() completes
    Then output contains "SUCCESS"

  Scenario: 80 percent checks pass returns exit code 0
    Given 8 of 10 checks return True
    When main() completes
    Then sys.exit(0) is called

  Scenario: 80 percent checks pass outputs operational
    Given 8 of 10 checks return True
    When main() completes
    Then output contains "operational"

  Scenario: Less than 80 percent pass returns exit code 1
    Given 7 of 10 checks return True
    When main() completes
    Then sys.exit(1) is called

  Scenario: Less than 80 percent pass outputs failure
    Given 7 of 10 checks return True
    When main() completes
    Then output contains "FAIL"

  Scenario: No GitHub token outputs usage hint
    Given test_github_token returns False
    When main() completes
    Then output contains "GITHUB_TOKEN"
