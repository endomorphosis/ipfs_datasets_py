Feature: main function from scripts/test_p2p_networking.py
  This function runs all P2P networking tests

  Scenario: Run all networking tests
    When calling main
    Then test_p2p_initialization executes
    And test_encryption_with_p2p executes
    And test_cache_broadcast_mechanism executes
    And test_github_cli_with_p2p executes
    And test_multiaddr_support executes
    And test_p2p_stream_protocol executes

  Scenario: Display test summary
    Given all tests completed
    When main prints summary
    Then passed count displays
    And total count displays
    And percentage displays

  Scenario: All tests pass
    Given all tests return true
    When main completes
    Then exit code is 0
    And success message displays

  Scenario: Some tests fail
    Given at least one test fails
    When main completes
    Then exit code is 1
    And failure count displays
