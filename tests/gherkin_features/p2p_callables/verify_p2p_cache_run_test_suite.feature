Feature: run_test_suite function from scripts/verify_p2p_cache.py
  This function runs specific test file

  Scenario: Run test_p2p_cache_encryption.py successfully
    Given test_p2p_cache_encryption.py exists
    When running with python
    Then output contains "10/10 tests passed"

  Scenario: Run test_p2p_cache_encryption.py successfully - assertion 2
    Given test_p2p_cache_encryption.py exists
    When running with python
    Then function returns true

  Scenario: Test suite fails
    Given test suite execution fails
    When calling run_test_suite
    Then function returns false

  Scenario: Test suite times out
    Given test suite takes over 30 seconds
    When calling run_test_suite
    Then timeout exception occurs

  Scenario: Test suite times out - assertion 2
    Given test suite takes over 30 seconds
    When calling run_test_suite
    Then function returns false
