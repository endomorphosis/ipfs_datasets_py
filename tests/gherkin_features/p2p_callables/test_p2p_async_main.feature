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
    And total count displays

  Scenario: All async tests pass
    Given all results are true
    When main completes
    Then exit code is 0
    And success message displays

  Scenario: Some async tests fail
    Given at least one test fails
    When main completes
    Then exit code is 1
    And failure message displays
