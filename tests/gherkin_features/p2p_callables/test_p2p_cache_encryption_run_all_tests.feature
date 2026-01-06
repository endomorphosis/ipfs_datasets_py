Feature: run_all_tests function from scripts/test_p2p_cache_encryption.py
  This function runs all tests and reports results

  Scenario: Run dependency tests
    When calling run_all_tests
    Then test_encryption_dependencies executes

  Scenario: Run dependency tests - assertion 2
    When calling run_all_tests
    Then test_multiformats_dependencies executes

  Scenario: Run dependency tests - assertion 3
    When calling run_all_tests
    Then test_libp2p_dependencies executes

  Scenario: Run dependency tests - assertion 4
    When calling run_all_tests
    Then test_github_token_available executes

  Scenario: Run encryption tests when dependencies available
    Given encryption dependencies available
    And GitHub token available
    When running encryption tests
    Then test_encryption_key_derivation executes

  Scenario: Run encryption tests when dependencies available - assertion 2
    Given encryption dependencies available
    And GitHub token available
    When running encryption tests
    Then test_message_encryption_decryption executes

  Scenario: Run encryption tests when dependencies available - assertion 3
    Given encryption dependencies available
    And GitHub token available
    When running encryption tests
    Then test_wrong_key_decryption executes

  Scenario: Skip encryption tests when dependencies missing
    Given encryption dependencies not available
    When running tests
    Then encryption tests are skipped

  Scenario: Skip encryption tests when dependencies missing - assertion 2
    Given encryption dependencies not available
    When running tests
    Then warning message displays

  Scenario: Run basic functionality tests
    When running basic tests
    Then test_cache_basic_operations executes

  Scenario: Run basic functionality tests - assertion 2
    When running basic tests
    Then test_content_hashing executes

  Scenario: Run basic functionality tests - assertion 3
    When running basic tests
    Then test_github_cli_integration executes

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
