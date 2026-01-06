Feature: run_all_tests function from scripts/test_p2p_real_world.py
  This async function runs all async tests

  Scenario: Run async P2P tests
    When calling run_all_tests
    Then test_async_p2p_initialization executes

  Scenario: Run async P2P tests - assertion 2
    When calling run_all_tests
    Then test_p2p_with_encryption executes

  Scenario: Run async P2P tests - assertion 3
    When calling run_all_tests
    Then test_two_peers_communication executes

  Scenario: Display test summary
    Given all async tests completed
    When printing summary
    Then passed count displays

  Scenario: Display test summary - assertion 2
    Given all async tests completed
    When printing summary
    Then total count displays

  Scenario: Display test summary - assertion 3
    Given all async tests completed
    When printing summary
    Then percentage displays

  Scenario: All tests pass
    Given all test results are true
    When run_all_tests completes
    Then exit code is 0

  Scenario: All tests pass - assertion 2
    Given all test results are true
    When run_all_tests completes
    Then success message displays

  Scenario: Some tests fail
    Given at least one test fails
    When run_all_tests completes
    Then exit code is 1

  Scenario: Some tests fail - assertion 2
    Given at least one test fails
    When run_all_tests completes
    Then failure count displays
