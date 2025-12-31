Feature: UCANManager.get_instance()
  Tests the get_instance() class method of UCANManager.
  This callable returns the singleton instance of UCANManager.

  Background:
    Given the UCANManager class is imported

  Scenario: First call to get_instance returns UCANManager instance
    When get_instance() is called for the first time
    Then a UCANManager instance is returned
    And the instance has initialized attribute set to False
    And the instance has keypairs dictionary
    And the instance has tokens dictionary
    And the instance has revocations dictionary

  Scenario: Second call to get_instance returns same instance
    Given get_instance() has been called once
    When get_instance() is called again
    Then the same UCANManager instance is returned
    And the instance id matches the first call

  Scenario: Multiple calls return identical singleton
    When get_instance() is called 5 times
    Then all returned instances have the same id
    And all instances share the same keypairs dictionary
    And all instances share the same tokens dictionary
    And all instances share the same revocations dictionary
