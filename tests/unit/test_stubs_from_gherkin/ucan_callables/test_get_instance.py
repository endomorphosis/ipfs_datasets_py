"""
Test stubs for get_instance.

Feature: UCANManager.get_instance()
  Tests the get_instance() class method of UCANManager.
  This callable returns the singleton instance of UCANManager.
"""
import pytest


# Fixtures for Background

@pytest.fixture
def the_ucanmanager_class_is_imported():
    """
    Given the UCANManager class is imported
    """
    # TODO: Implement fixture
    pass


# Test scenarios

def test_first_call_to_get_instance_returns_ucanmanager_instance(the_ucanmanager_class_is_imported):
    """
    Scenario: First call to get_instance returns UCANManager instance
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then a UCANManager instance is returned
    """
    # TODO: Implement test
    pass


def test_returned_instance_has_initialized_attribute_set_to_false(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has initialized attribute set to False
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has initialized attribute set to False
    """
    # TODO: Implement test
    pass


def test_returned_instance_has_keypairs_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has keypairs dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has keypairs dictionary
    """
    # TODO: Implement test
    pass


def test_returned_instance_has_tokens_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has tokens dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has tokens dictionary
    """
    # TODO: Implement test
    pass


def test_returned_instance_has_revocations_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has revocations dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has revocations dictionary
    """
    # TODO: Implement test
    pass


def test_second_call_to_get_instance_returns_same_instance(the_ucanmanager_class_is_imported):
    """
    Scenario: Second call to get_instance returns same instance
    
    Given the UCANManager class is imported
    Given get_instance() has been called once
    When get_instance() is called again
    Then the same UCANManager instance is returned
    """
    # TODO: Implement test
    pass


def test_second_call_instance_id_matches_the_first_call(the_ucanmanager_class_is_imported):
    """
    Scenario: Second call instance id matches the first call
    
    Given the UCANManager class is imported
    Given get_instance() has been called once
    When get_instance() is called again
    Then the instance id matches the first call
    """
    # TODO: Implement test
    pass


def test_multiple_calls_return_instances_with_same_id(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls return instances with same id
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all returned instances have the same id
    """
    # TODO: Implement test
    pass


def test_multiple_calls_share_same_keypairs_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls share same keypairs dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all instances share the same keypairs dictionary
    """
    # TODO: Implement test
    pass


def test_multiple_calls_share_same_tokens_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls share same tokens dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all instances share the same tokens dictionary
    """
    # TODO: Implement test
    pass


def test_multiple_calls_share_same_revocations_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls share same revocations dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all instances share the same revocations dictionary
    """
    # TODO: Implement test
    pass

