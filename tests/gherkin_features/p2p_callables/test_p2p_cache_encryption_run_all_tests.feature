Feature: run_all_tests function from scripts/test_p2p_cache_encryption.py
  This function runs all tests and reports results

  Scenario: Run dependency tests
    When calling run_all_tests
    Then test_encryption_dependencies executes
    And test_multiformats_dependencies executes
    And test_libp2p_dependencies executes
    And test_github_token_available executes

  Scenario: Run encryption tests when dependencies available
    Given encryption dependencies available
    And GitHub token available
    When running encryption tests
    Then test_encryption_key_derivation executes
    And test_message_encryption_decryption executes
    And test_wrong_key_decryption executes

  Scenario: Skip encryption tests when dependencies missing
    Given encryption dependencies not available
    When running tests
    Then encryption tests are skipped
    And warning message displays

  Scenario: Run basic functionality tests
    When running basic tests
    Then test_cache_basic_operations executes
    And test_content_hashing executes
    And test_github_cli_integration executes

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
