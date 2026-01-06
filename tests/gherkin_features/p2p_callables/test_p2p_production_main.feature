Feature: main function from scripts/test_p2p_production.py
  This function runs production tests

  Scenario: Run all production tests
    When calling main function
    Then test_cache_with_p2p_enabled executes
    And test_github_cli_integration executes

  Scenario: Display test results summary
    Given completed test runs
    When main displays results
    Then passed count is shown
    And total count is shown
    And percentage is calculated

  Scenario: All tests pass
    Given all tests succeed
    When main completes
    Then exit code is 0
    And success message displays

  Scenario: Some tests fail
    Given at least one test fails
    When main completes
    Then exit code is 1
    And failure count displays
