Feature: main function from scripts/verify_p2p_cache.py
  This function runs main verification

  Scenario: Run all verification checks
    When calling main function
    Then dependency checks execute
    And configuration checks execute
    And core functionality checks execute
    And test suite check executes

  Scenario: All checks pass
    Given all checks return true
    When main completes
    Then exit code is 0
    And success message displays

  Scenario: Most checks pass
    Given 80 percent or more checks pass
    When main completes
    Then exit code is 0
    And mostly operational message displays

  Scenario: Some checks fail
    Given less than 80 percent checks pass
    When main completes
    Then exit code is 1
    And failure message displays

  Scenario: Display usage hints
    Given GitHub token not available
    When main completes
    Then usage hint displays for GITHUB_TOKEN
