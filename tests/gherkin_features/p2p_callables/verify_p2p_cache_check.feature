Feature: check function from scripts/verify_p2p_cache.py
  This function runs a test and prints result

  Scenario: Successful test prints green checkmark
    Given test function returns True
    When check("test_name", test_fn) is called
    Then output contains "✓"

  Scenario: Successful test returns True
    Given test function returns True
    When check("test_name", test_fn) is called
    Then result == True

  Scenario: Failed test prints red X
    Given test function returns False
    When check("test_name", test_fn) is called
    Then output contains "✗"

  Scenario: Failed test returns False
    Given test function returns False
    When check("test_name", test_fn) is called
    Then result == False

  Scenario: Exception prints red X
    Given test function raises ValueError
    When check("test_name", test_fn) is called
    Then output contains "✗"

  Scenario: Exception prints error message
    Given test function raises ValueError("test error")
    When check("test_name", test_fn) is called
    Then output contains "test error"

  Scenario: Exception returns False
    Given test function raises Exception
    When check("test_name", test_fn) is called
    Then result == False
