"""
Test stubs for get_instance.

Feature: UCANManager.get_instance()
  Tests the get_instance() class method of UCANManager.
  This callable returns the singleton instance of UCANManager.
"""
import pytest


# Test scenarios

def test_first_call_to_get_instance_returns_ucanmanager_instance(the_ucanmanager_class_is_imported):
    """
    Scenario: First call to get_instance returns UCANManager instance
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then a UCANManager instance is returned
    """
    UCANManager = the_ucanmanager_class_is_imported
    
    result = UCANManager.get_instance()
    
    expected_type = UCANManager
    result_type = type(result)
    assert isinstance(result, expected_type), f"expected instance of {expected_type}, got {result_type}"


def test_returned_instance_has_initialized_attribute_set_to_false(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has initialized attribute set to False
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has initialized attribute set to False
    """
    UCANManager = the_ucanmanager_class_is_imported
    instance = UCANManager.get_instance()
    
    result = instance.initialized
    
    expected = False
    assert result == expected, f"expected {expected}, got {result}"


def test_returned_instance_has_keypairs_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has keypairs dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has keypairs dictionary
    """
    UCANManager = the_ucanmanager_class_is_imported
    instance = UCANManager.get_instance()
    
    result = hasattr(instance, 'keypairs')
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"


def test_returned_instance_has_tokens_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has tokens dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has tokens dictionary
    """
    UCANManager = the_ucanmanager_class_is_imported
    instance = UCANManager.get_instance()
    
    result = hasattr(instance, 'tokens')
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"


def test_returned_instance_has_revocations_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Returned instance has revocations dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then the instance has revocations dictionary
    """
    UCANManager = the_ucanmanager_class_is_imported
    instance = UCANManager.get_instance()
    
    result = hasattr(instance, 'revocations')
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"


def test_second_call_to_get_instance_returns_same_instance(the_ucanmanager_class_is_imported):
    """
    Scenario: Second call to get_instance returns same instance
    
    Given the UCANManager class is imported
    Given get_instance() has been called once
    When get_instance() is called again
    Then the same UCANManager instance is returned
    """
    UCANManager = the_ucanmanager_class_is_imported
    first_instance = UCANManager.get_instance()
    
    result = UCANManager.get_instance()
    
    expected = first_instance
    assert result is expected, f"expected {expected}, got {result}"


def test_second_call_instance_id_matches_the_first_call(the_ucanmanager_class_is_imported):
    """
    Scenario: Second call instance id matches the first call
    
    Given the UCANManager class is imported
    Given get_instance() has been called once
    When get_instance() is called again
    Then the instance id matches the first call
    """
    UCANManager = the_ucanmanager_class_is_imported
    first_instance = UCANManager.get_instance()
    second_instance = UCANManager.get_instance()
    
    result = id(second_instance)
    
    expected = id(first_instance)
    assert result == expected, f"expected {expected}, got {result}"


def test_multiple_calls_return_instances_with_same_id(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls return instances with same id
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all returned instances have the same id
    """
    UCANManager = the_ucanmanager_class_is_imported
    num_calls = 5
    instances = [UCANManager.get_instance() for _ in range(num_calls)]
    first_instance_id = id(instances[0])
    
    result = all(id(instance) == first_instance_id for instance in instances)
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"


def test_multiple_calls_share_same_keypairs_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls share same keypairs dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all instances share the same keypairs dictionary
    """
    UCANManager = the_ucanmanager_class_is_imported
    num_calls = 5
    instances = [UCANManager.get_instance() for _ in range(num_calls)]
    first_keypairs_id = id(instances[0].keypairs)
    
    result = all(id(instance.keypairs) == first_keypairs_id for instance in instances)
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"


def test_multiple_calls_share_same_tokens_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls share same tokens dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all instances share the same tokens dictionary
    """
    UCANManager = the_ucanmanager_class_is_imported
    num_calls = 5
    instances = [UCANManager.get_instance() for _ in range(num_calls)]
    first_tokens_id = id(instances[0].tokens)
    
    result = all(id(instance.tokens) == first_tokens_id for instance in instances)
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"


def test_multiple_calls_share_same_revocations_dictionary(the_ucanmanager_class_is_imported):
    """
    Scenario: Multiple calls share same revocations dictionary
    
    Given the UCANManager class is imported
    When get_instance() is called 5 times
    Then all instances share the same revocations dictionary
    """
    UCANManager = the_ucanmanager_class_is_imported
    num_calls = 5
    instances = [UCANManager.get_instance() for _ in range(num_calls)]
    first_revocations_id = id(instances[0].revocations)
    
    result = all(id(instance.revocations) == first_revocations_id for instance in instances)
    
    expected = True
    assert result == expected, f"expected {expected}, got {result}"

