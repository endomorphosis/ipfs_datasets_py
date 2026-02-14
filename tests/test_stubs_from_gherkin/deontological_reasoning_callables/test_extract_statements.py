"""
Test stubs for DeonticExtractor.extract_statements()

Feature: DeonticExtractor.extract_statements()
  Tests the extract_statements() method of DeonticExtractor.
  This callable extracts deontic statements from text.
"""

import pytest
from ipfs_datasets_py.logic.integration.deontological_reasoning import (
    DeonticExtractor, 
    DeonticStatement, 
    DeonticModality
)
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


@pytest.fixture
def document_id():
    """
    And document_id is "doc1"
    """
    try:
        doc_id = "doc1"
        if not isinstance(doc_id, str) or len(doc_id) == 0:
            raise FixtureError("Failed to create fixture document_id: invalid document ID")
        return doc_id
    except Exception as e:
        raise FixtureError(f"Failed to create fixture document_id: {e}") from e


# Test scenarios

def test_extract_statements_with_empty_text_returns_empty_list(deontic_extractor_instance, document_id):
    """
    Scenario: Extract statements with empty text returns empty list
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = ""
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: returns empty list
    expected_length = 0
    actual_length = len(result)
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_extract_obligation_statement_with_must(deontic_extractor_instance, document_id):
    """
    Scenario: Extract obligation statement with "must"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extracted_obligation_has_modality_obligation(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted obligation has modality OBLIGATION
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement modality is OBLIGATION
    expected_modality = DeonticModality.OBLIGATION
    actual_modality = result[0].modality
    assert actual_modality == expected_modality, f"expected {expected_modality}, got {actual_modality}"


def test_extracted_obligation_has_entity_citizens(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted obligation has entity "citizens"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement entity is "citizens"
    expected_entity = "citizens"
    actual_entity = result[0].entity
    assert actual_entity == expected_entity, f"expected {expected_entity}, got {actual_entity}"


def test_extracted_obligation_has_action_pay_taxes(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted obligation has action "pay taxes"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement action is "pay taxes"
    expected_action = "pay taxes"
    actual_action = result[0].action
    assert actual_action == expected_action, f"expected {expected_action}, got {actual_action}"


def test_extract_permission_statement_with_may(deontic_extractor_instance, document_id):
    """
    Scenario: Extract permission statement with "may"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Drivers may park here."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extracted_permission_has_modality_permission(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted permission has modality PERMISSION
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Drivers may park here."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement modality is PERMISSION
    expected_modality = DeonticModality.PERMISSION
    actual_modality = result[0].modality
    assert actual_modality == expected_modality, f"expected {expected_modality}, got {actual_modality}"


def test_extract_prohibition_statement_with_must_not(deontic_extractor_instance, document_id):
    """
    Scenario: Extract prohibition statement with "must not"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Employees must not smoke indoors."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extracted_prohibition_has_modality_prohibition(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted prohibition has modality PROHIBITION
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Employees must not smoke indoors."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement modality is PROHIBITION
    expected_modality = DeonticModality.PROHIBITION
    actual_modality = result[0].modality
    assert actual_modality == expected_modality, f"expected {expected_modality}, got {actual_modality}"


def test_extract_multiple_statements_from_text(deontic_extractor_instance, document_id):
    """
    Scenario: Extract multiple statements from text
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes. Drivers may park here."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 2 statements are extracted
    expected_count = 2
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_each_statement_has_unique_id(deontic_extractor_instance, document_id):
    """
    Scenario: Each statement has unique id
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes. Drivers may park here."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: all statement ids are unique
    id_list = [stmt.id for stmt in result]
    expected_unique_count = len(id_list)
    actual_unique_count = len(set(id_list))
    assert actual_unique_count == expected_unique_count, f"expected {expected_unique_count}, got {actual_unique_count}"


def test_statement_id_starts_with_stmt_(deontic_extractor_instance, document_id):
    """
    Scenario: Statement id starts with "stmt_"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement id starts with "stmt_"
    expected_prefix = "stmt_"
    actual_starts_with = result[0].id.startswith(expected_prefix)
    expected_starts_with = True
    assert actual_starts_with == expected_starts_with, f"expected {expected_starts_with}, got {actual_starts_with}"


def test_statement_has_source_document_attribute(deontic_extractor_instance, document_id):
    """
    Scenario: Statement has source_document attribute
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement has source_document attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], 'source_document')
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_statement_has_source_text_attribute(deontic_extractor_instance, document_id):
    """
    Scenario: Statement has source_text attribute
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement has source_text attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], 'source_text')
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_statement_has_confidence_attribute(deontic_extractor_instance, document_id):
    """
    Scenario: Statement has confidence attribute
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement has confidence attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], 'confidence')
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_statement_with_must_has_confidence_gte_07(deontic_extractor_instance, document_id):
    """
    Scenario: Statement with "must" has confidence >= 0.7
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement confidence is >= 0.7
    min_confidence = 0.7
    actual_confidence = result[0].confidence
    expected_comparison = True
    actual_comparison = actual_confidence >= min_confidence
    assert actual_comparison == expected_comparison, f"expected {expected_comparison}, got {actual_comparison}"


def test_statement_with_shall_has_confidence_gte_07(deontic_extractor_instance, document_id):
    """
    Scenario: Statement with "shall" has confidence >= 0.7
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens shall pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement confidence is >= 0.7
    min_confidence = 0.7
    actual_confidence = result[0].confidence
    expected_comparison = True
    actual_comparison = actual_confidence >= min_confidence
    assert actual_comparison == expected_comparison, f"expected {expected_comparison}, got {actual_comparison}"


def test_statement_has_context_dictionary(deontic_extractor_instance, document_id):
    """
    Scenario: Statement has context dictionary
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement has context attribute that is a dict
    expected_type = dict
    actual_type = type(result[0].context)
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_context_has_surrounding_text_key(deontic_extractor_instance, document_id):
    """
    Scenario: Context has surrounding_text key
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the context has surrounding_text key
    expected_key_present = True
    actual_key_present = 'surrounding_text' in result[0].context
    assert actual_key_present == expected_key_present, f"expected {expected_key_present}, got {actual_key_present}"


def test_context_has_position_key(deontic_extractor_instance, document_id):
    """
    Scenario: Context has position key
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the context has position key
    expected_key_present = True
    actual_key_present = 'position' in result[0].context
    assert actual_key_present == expected_key_present, f"expected {expected_key_present}, got {actual_key_present}"


def test_context_has_extracted_at_timestamp(deontic_extractor_instance, document_id):
    """
    Scenario: Context has extracted_at timestamp
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the context has extracted_at key
    expected_key_present = True
    actual_key_present = 'extracted_at' in result[0].context
    assert actual_key_present == expected_key_present, f"expected {expected_key_present}, got {actual_key_present}"


def test_extract_conditional_statement_with_if(deontic_extractor_instance, document_id):
    """
    Scenario: Extract conditional statement with "if"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "If a person is under 18, they must have parental consent."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extracted_conditional_has_modality_conditional(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted conditional has modality CONDITIONAL
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "If a person is under 18, they must have parental consent."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement modality is CONDITIONAL
    expected_modality = DeonticModality.CONDITIONAL
    actual_modality = result[0].modality
    assert actual_modality == expected_modality, f"expected {expected_modality}, got {actual_modality}"


def test_conditional_statement_has_conditions_list(deontic_extractor_instance, document_id):
    """
    Scenario: Conditional statement has conditions list
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "If a person is under 18, they must have parental consent."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement has conditions attribute that is a list
    expected_type = list
    actual_type = type(result[0].conditions)
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_conditional_statement_id_starts_with_cond_stmt_(deontic_extractor_instance, document_id):
    """
    Scenario: Conditional statement id starts with "cond_stmt_"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "If a person is under 18, they must have parental consent."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement id starts with "cond_stmt_"
    expected_prefix = "cond_stmt_"
    actual_starts_with = result[0].id.startswith(expected_prefix)
    expected_starts_with = True
    assert actual_starts_with == expected_starts_with, f"expected {expected_starts_with}, got {actual_starts_with}"


def test_extract_statement_with_exception(deontic_extractor_instance, document_id):
    """
    Scenario: Extract statement with exception
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "All employees must attend, except those on leave."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extracted_exception_statement_has_modality_exception(deontic_extractor_instance, document_id):
    """
    Scenario: Extracted exception statement has modality EXCEPTION
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "All employees must attend, except those on leave."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement modality is EXCEPTION
    expected_modality = DeonticModality.EXCEPTION
    actual_modality = result[0].modality
    assert actual_modality == expected_modality, f"expected {expected_modality}, got {actual_modality}"


def test_exception_statement_has_exceptions_list(deontic_extractor_instance, document_id):
    """
    Scenario: Exception statement has exceptions list
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "All employees must attend, except those on leave."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement has exceptions attribute that is a list
    expected_type = list
    actual_type = type(result[0].exceptions)
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_exception_statement_id_starts_with_exc_stmt_(deontic_extractor_instance, document_id):
    """
    Scenario: Exception statement id starts with "exc_stmt_"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "All employees must attend, except those on leave."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement id starts with "exc_stmt_"
    expected_prefix = "exc_stmt_"
    actual_starts_with = result[0].id.startswith(expected_prefix)
    expected_starts_with = True
    assert actual_starts_with == expected_starts_with, f"expected {expected_starts_with}, got {actual_starts_with}"


def test_extract_obligation_with_shall(deontic_extractor_instance, document_id):
    """
    Scenario: Extract obligation with "shall"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Contractors shall complete work by deadline."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extract_obligation_with_required_to(deontic_extractor_instance, document_id):
    """
    Scenario: Extract obligation with "required to"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Students are required to submit assignments."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extract_permission_with_can(deontic_extractor_instance, document_id):
    """
    Scenario: Extract permission with "can"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Members can access the lounge."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extract_prohibition_with_cannot(deontic_extractor_instance, document_id):
    """
    Scenario: Extract prohibition with "cannot"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Minors cannot purchase alcohol."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extract_prohibition_with_forbidden_to(deontic_extractor_instance, document_id):
    """
    Scenario: Extract prohibition with "forbidden to"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Visitors are forbidden to take photographs."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 1 statement is extracted
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_is_normalized_to_lowercase(deontic_extractor_instance, document_id):
    """
    Scenario: Entity is normalized to lowercase
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "CITIZENS must pay taxes."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement entity is lowercase
    expected_entity = "citizens"
    actual_entity = result[0].entity
    assert actual_entity == expected_entity, f"expected {expected_entity}, got {actual_entity}"


def test_action_is_normalized_to_lowercase(deontic_extractor_instance, document_id):
    """
    Scenario: Action is normalized to lowercase
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must PAY TAXES."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: the statement action is lowercase
    expected_action = "pay taxes"
    actual_action = result[0].action
    assert actual_action == expected_action, f"expected {expected_action}, got {actual_action}"


def test_skip_statement_with_generic_entity_it(deontic_extractor_instance, document_id):
    """
    Scenario: Skip statement with generic entity "it"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "It must be done."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: no statements are extracted
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_skip_statement_with_generic_entity_this(deontic_extractor_instance, document_id):
    """
    Scenario: Skip statement with generic entity "this"
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "This must be done."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: no statements are extracted
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_skip_statement_with_short_action(deontic_extractor_instance, document_id):
    """
    Scenario: Skip statement with short action
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must go."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: no statements are extracted
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_extract_5_statements_from_text_with_mixed_modalities(deontic_extractor_instance, document_id):
    """
    Scenario: Extract 5 statements from text with mixed modalities
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes. Drivers may park here. Employees must not smoke indoors. Members can access the lounge. Visitors are forbidden to take photographs."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: 5 statements are extracted
    expected_count = 5
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_different_modality_statements_have_different_patterns(deontic_extractor_instance, document_id):
    """
    Scenario: Different modality statements have different patterns
    
    Given:
        a DeonticExtractor instance
        document_id is "doc1"
    
    When:
        extract_statements() is called
    
    Then:
        (see scenario description)
    """
    # When: extract_statements() is called
    text = "Citizens must pay taxes. Drivers may park here. Employees must not smoke indoors."
    result = deontic_extractor_instance.extract_statements(text, document_id)
    
    # Then: extracted statements have different modalities
    modality_list = [stmt.modality for stmt in result]
    expected_unique_count = 3
    actual_unique_count = len(set(modality_list))
    assert actual_unique_count == expected_unique_count, f"expected {expected_unique_count}, got {actual_unique_count}"



