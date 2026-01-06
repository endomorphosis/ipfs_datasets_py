Feature: main function from test_p2p_async.py
  This async function runs all async tests

  Scenario: Run P2P initialization test
    When calling main
    Then test_p2p_initialization executes

  Scenario: Run cache operations test
    When calling main
    Then test_p2p_cache_operations executes

  Scenario: Display async test summary
    Given all tests completed
    When printing summary
    Then passed count displays

  Scenario: Display async test summary - assertion 2
    Given all tests completed
    When printing summary
    Then total count displays

  Scenario: All async tests pass
    Given all results are true
    When main completes
    Then exit code is 0

  Scenario: All async tests pass - assertion 2
    Given all results are true
    When main completes
    Then success message displays

  Scenario: Some async tests fail
    Given at least one test fails
    When main completes
    Then exit code is 1

  Scenario: Some async tests fail - assertion 2
    Given at least one test fails
    When main completes
    Then failure message displays
