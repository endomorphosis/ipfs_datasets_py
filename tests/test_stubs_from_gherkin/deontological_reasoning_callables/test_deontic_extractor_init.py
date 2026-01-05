"""
Test stubs for DeonticExtractor.__init__()

Feature: DeonticExtractor.__init__()
  Tests the __init__() method of DeonticExtractor.
  This callable initializes a deontic statement extractor.
"""

import pytest
from ipfs_datasets_py.deontological_reasoning import DeonticExtractor, DeonticPatterns
from conftest import FixtureError


# Fixtures from Background

@pytest.fixture
def deontic_extractor_instance():
    """
    Given a DeonticExtractor instance
    """
    try:
        instance = DeonticExtractor()
        if instance is None:
            raise FixtureError("Failed to create fixture deontic_extractor_instance: instance is None")
        return instance
    except Exception as e:
        raise FixtureError(f"Failed to create fixture deontic_extractor_instance: {e}") from e


# Test scenarios

def test_initialize_creates_deonticextractor_instance():
    """
    Scenario: Initialize creates DeonticExtractor instance
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        a DeonticExtractor instance is returned
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: a DeonticExtractor instance is returned
    expected_type = DeonticExtractor
    actual_type = type(result)
    assert isinstance(result, expected_type), f"expected {expected_type}, got {actual_type}"


def test_initialize_sets_patterns_attribute():
    """
    Scenario: Initialize sets patterns attribute
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        the patterns attribute is set
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: the patterns attribute is set
    expected_has_attribute = True
    actual_has_attribute = hasattr(result, 'patterns')
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_initialize_sets_statement_counter_to_0():
    """
    Scenario: Initialize sets statement_counter to 0
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        the statement_counter attribute is 0
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: the statement_counter attribute is 0
    expected_counter = 0
    actual_counter = result.statement_counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_patterns_attribute_is_deonticpatterns_instance():
    """
    Scenario: Patterns attribute is DeonticPatterns instance
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        the patterns attribute is DeonticPatterns instance
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: the patterns attribute is DeonticPatterns instance
    expected_type = DeonticPatterns
    actual_type = type(result.patterns)
    assert isinstance(result.patterns, expected_type), f"expected {expected_type}, got {actual_type}"


def test_patterns_has_obligation_patterns_list():
    """
    Scenario: Patterns has OBLIGATION_PATTERNS list
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.OBLIGATION_PATTERNS is a list
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.OBLIGATION_PATTERNS is a list
    expected_type = list
    actual_type = type(result.patterns.OBLIGATION_PATTERNS)
    assert isinstance(result.patterns.OBLIGATION_PATTERNS, expected_type), f"expected {expected_type}, got {actual_type}"


def test_patterns_has_permission_patterns_list():
    """
    Scenario: Patterns has PERMISSION_PATTERNS list
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.PERMISSION_PATTERNS is a list
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.PERMISSION_PATTERNS is a list
    expected_type = list
    actual_type = type(result.patterns.PERMISSION_PATTERNS)
    assert isinstance(result.patterns.PERMISSION_PATTERNS, expected_type), f"expected {expected_type}, got {actual_type}"


def test_patterns_has_prohibition_patterns_list():
    """
    Scenario: Patterns has PROHIBITION_PATTERNS list
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.PROHIBITION_PATTERNS is a list
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.PROHIBITION_PATTERNS is a list
    expected_type = list
    actual_type = type(result.patterns.PROHIBITION_PATTERNS)
    assert isinstance(result.patterns.PROHIBITION_PATTERNS, expected_type), f"expected {expected_type}, got {actual_type}"


def test_patterns_has_conditional_patterns_list():
    """
    Scenario: Patterns has CONDITIONAL_PATTERNS list
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.CONDITIONAL_PATTERNS is a list
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.CONDITIONAL_PATTERNS is a list
    expected_type = list
    actual_type = type(result.patterns.CONDITIONAL_PATTERNS)
    assert isinstance(result.patterns.CONDITIONAL_PATTERNS, expected_type), f"expected {expected_type}, got {actual_type}"


def test_patterns_has_exception_patterns_list():
    """
    Scenario: Patterns has EXCEPTION_PATTERNS list
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.EXCEPTION_PATTERNS is a list
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.EXCEPTION_PATTERNS is a list
    expected_type = list
    actual_type = type(result.patterns.EXCEPTION_PATTERNS)
    assert isinstance(result.patterns.EXCEPTION_PATTERNS, expected_type), f"expected {expected_type}, got {actual_type}"


def test_obligation_patterns_contains_pattern_for_must():
    """
    Scenario: OBLIGATION_PATTERNS contains pattern for "must"
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.OBLIGATION_PATTERNS contains pattern matching "must"
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.OBLIGATION_PATTERNS contains pattern matching "must"
    search_term = "must"
    patterns_as_string = " ".join(result.patterns.OBLIGATION_PATTERNS)
    expected_contains = True
    actual_contains = search_term in patterns_as_string
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_permission_patterns_contains_pattern_for_may():
    """
    Scenario: PERMISSION_PATTERNS contains pattern for "may"
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.PERMISSION_PATTERNS contains pattern matching "may"
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.PERMISSION_PATTERNS contains pattern matching "may"
    search_term = "may"
    patterns_as_string = " ".join(result.patterns.PERMISSION_PATTERNS)
    expected_contains = True
    actual_contains = search_term in patterns_as_string
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_prohibition_patterns_contains_pattern_for_must_not():
    """
    Scenario: PROHIBITION_PATTERNS contains pattern for "must not"
    
    Given:
        (implicit - no background)
    
    When:
        DeonticExtractor() is called
    
    Then:
        patterns.PROHIBITION_PATTERNS contains pattern matching "must not"
    """
    # When: DeonticExtractor() is called
    result = DeonticExtractor()
    
    # Then: patterns.PROHIBITION_PATTERNS contains pattern matching "must not"
    search_term = "must not"
    patterns_as_string = " ".join(result.patterns.PROHIBITION_PATTERNS)
    expected_contains = True
    actual_contains = search_term in patterns_as_string
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_statement_counter_increments_after_extraction(deontic_extractor_instance):
    """
    Scenario: Statement counter increments after extraction
    
    Given:
        a DeonticExtractor instance
    
    When:
        extract_statements() is called with text containing 2 statements
    
    Then:
        the statement_counter is 2
    """
    # When: extract_statements() is called with text containing 2 statements
    text_with_statements = "Citizens must pay taxes. Citizens may vote."
    document_id = "test_doc"
    result = deontic_extractor_instance.extract_statements(text_with_statements, document_id)
    
    # Then: the statement_counter is 2
    expected_counter = 2
    actual_counter = deontic_extractor_instance.statement_counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"


def test_multiple_extractions_increment_counter_correctly(deontic_extractor_instance):
    """
    Scenario: Multiple extractions increment counter correctly
    
    Given:
        a DeonticExtractor instance
    
    When:
        extract_statements() is called 3 times with 1 statement each
    
    Then:
        the statement_counter is 3
    """
    # When: extract_statements() is called 3 times with 1 statement each
    text_with_one_statement = "Citizens must pay taxes."
    document_id = "test_doc"
    deontic_extractor_instance.extract_statements(text_with_one_statement, document_id)
    deontic_extractor_instance.extract_statements(text_with_one_statement, document_id)
    result = deontic_extractor_instance.extract_statements(text_with_one_statement, document_id)
    
    # Then: the statement_counter is 3
    expected_counter = 3
    actual_counter = deontic_extractor_instance.statement_counter
    assert actual_counter == expected_counter, f"expected {expected_counter}, got {actual_counter}"
