Feature: UCANManager.get_instance()
  Tests the get_instance() class method of UCANManager.
  This callable returns the singleton instance of UCANManager.

  Background:
    Given the UCANManager class is imported

  Scenario: First call to get_instance returns UCANManager instance
    When get_instance() is called for the first time
    Then a UCANManager instance is returned

  Scenario: Returned instance has initialized attribute set to False
    When get_instance() is called for the first time
    Then the instance has initialized attribute set to False

  Scenario: Returned instance has keypairs dictionary
    When get_instance() is called for the first time
    Then the instance has keypairs dictionary

  Scenario: Returned instance has tokens dictionary
    When get_instance() is called for the first time
    Then the instance has tokens dictionary

  Scenario: Returned instance has revocations dictionary
    When get_instance() is called for the first time
    Then the instance has revocations dictionary

  Scenario: Second call to get_instance returns same instance
    Given get_instance() has been called once
    When get_instance() is called again
    Then the same UCANManager instance is returned

  Scenario: Second call instance id matches the first call
    Given get_instance() has been called once
    When get_instance() is called again
    Then the instance id matches the first call

  Scenario: Multiple calls return instances with same id
    When get_instance() is called 5 times
    Then all returned instances have the same id

  Scenario: Multiple calls share same keypairs dictionary
    When get_instance() is called 5 times
    Then all instances share the same keypairs dictionary

  Scenario: Multiple calls share same tokens dictionary
    When get_instance() is called 5 times
    Then all instances share the same tokens dictionary

  Scenario: Multiple calls share same revocations dictionary
    When get_instance() is called 5 times
    Then all instances share the same revocations dictionary
