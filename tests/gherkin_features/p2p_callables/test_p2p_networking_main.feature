Feature: main function from scripts/test_p2p_networking.py
  This function runs all P2P networking tests

  Scenario: Run all networking tests
    When calling main
    Then test_p2p_initialization executes

  Scenario: Run all networking tests - assertion 2
    When calling main
    Then test_encryption_with_p2p executes

  Scenario: Run all networking tests - assertion 3
    When calling main
    Then test_cache_broadcast_mechanism executes

  Scenario: Run all networking tests - assertion 4
    When calling main
    Then test_github_cli_with_p2p executes

  Scenario: Run all networking tests - assertion 5
    When calling main
    Then test_multiaddr_support executes

  Scenario: Run all networking tests - assertion 6
    When calling main
    Then test_p2p_stream_protocol executes

  Scenario: Display test summary
    Given all tests completed
    When main prints summary
    Then passed count displays

  Scenario: Display test summary - assertion 2
    Given all tests completed
    When main prints summary
    Then total count displays

  Scenario: Display test summary - assertion 3
    Given all tests completed
    When main prints summary
    Then percentage displays

  Scenario: All tests pass
    Given all tests return true
    When main completes
    Then exit code is 0

  Scenario: All tests pass - assertion 2
    Given all tests return true
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
