Feature: test_p2p_stream_protocol function from scripts/test_p2p_networking.py
  This function tests P2P stream protocol definition

  Scenario: Create cache instance
    When creating GitHubAPICache
    Then cache is created

  Scenario: Check stream protocol ID
    Given cache instance
    When checking protocol ID
    Then protocol ID equals "/github-cache/1.0.0"
    And function returns true

  Scenario: Stream protocol test fails
    Given protocol check raises exception
    When calling test_p2p_stream_protocol
    Then function returns false
