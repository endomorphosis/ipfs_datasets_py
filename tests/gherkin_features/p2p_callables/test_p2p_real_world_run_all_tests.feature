Feature: run_all_tests function from scripts/test_p2p_real_world.py
  This async function runs all async tests

  Scenario: Run async P2P tests
    When calling run_all_tests
    Then test_async_p2p_initialization executes
    And test_p2p_with_encryption executes
    And test_two_peers_communication executes

  Scenario: Display test summary
    Given all async tests completed
    When printing summary
    Then passed count displays
    And total count displays
    And percentage displays

  Scenario: All tests pass
    Given all test results are true
    When run_all_tests completes
    Then exit code is 0
    And success message displays

  Scenario: Some tests fail
    Given at least one test fails
    When run_all_tests completes
    Then exit code is 1
    And failure count displays
