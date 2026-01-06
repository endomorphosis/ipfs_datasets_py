Feature: main function from scripts/test_p2p_production.py
  This function runs production tests

  Scenario: Run all production tests
    When calling main function
    Then test_cache_with_p2p_enabled executes

  Scenario: Run all production tests - assertion 2
    When calling main function
    Then test_github_cli_integration executes

  Scenario: Display test results summary
    Given completed test runs
    When main displays results
    Then passed count is shown

  Scenario: Display test results summary - assertion 2
    Given completed test runs
    When main displays results
    Then total count is shown

  Scenario: Display test results summary - assertion 3
    Given completed test runs
    When main displays results
    Then percentage is calculated

  Scenario: All tests pass
    Given all tests succeed
    When main completes
    Then exit code is 0

  Scenario: All tests pass - assertion 2
    Given all tests succeed
    When main completes
    Then success message displays

  Scenario: Some tests fail
    Given at least one test fails
    When main completes
    Then exit code is 1

  Scenario: Some tests fail - assertion 2
    Given at least one test fails
    When main completes
    Then failure count displays
