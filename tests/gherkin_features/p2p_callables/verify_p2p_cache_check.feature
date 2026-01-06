Feature: check function from scripts/verify_p2p_cache.py
  This function runs a test and prints result

  Scenario: Run successful test
    Given a test function that returns true
    When calling check with test name
    Then green checkmark prints
    And function returns true

  Scenario: Run failing test
    Given a test function that returns false
    When calling check with test name
    Then red X prints
    And function returns false

  Scenario: Handle test exception
    Given a test function that raises exception
    When calling check with test name
    Then red X prints
    And exception message displays
    And function returns false
