Feature: check function from scripts/verify_p2p_cache.py
  This function runs a test and prints result

  Scenario: Run successful test
    Given a test function that returns true
    When calling check with test name
    Then green checkmark prints

  Scenario: Run successful test - assertion 2
    Given a test function that returns true
    When calling check with test name
    Then function returns true

  Scenario: Run failing test
    Given a test function that returns false
    When calling check with test name
    Then red X prints

  Scenario: Run failing test - assertion 2
    Given a test function that returns false
    When calling check with test name
    Then function returns false

  Scenario: Handle test exception
    Given a test function that raises exception
    When calling check with test name
    Then red X prints

  Scenario: Handle test exception - assertion 2
    Given a test function that raises exception
    When calling check with test name
    Then exception message displays

  Scenario: Handle test exception - assertion 3
    Given a test function that raises exception
    When calling check with test name
    Then function returns false
