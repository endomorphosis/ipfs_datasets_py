"""
Test implementations for DeontologicalReasoningEngine.query_deontic_statements()

Feature: DeontologicalReasoningEngine.query_deontic_statements()
  Tests the query_deontic_statements() method of DeontologicalReasoningEngine.
"""

import pytest
import anyio
from ipfs_datasets_py.deontological_reasoning import (
    DeontologicalReasoningEngine, 
    DeonticStatement, 
    DeonticModality
)
from conftest import FixtureError


# Fixtures from Background

@pytest.fixture
def a_deontologicalreasoningengine_fixture():
    """
    a DeontologicalReasoningEngine instance
    """
    try:
        instance = DeontologicalReasoningEngine()
        if instance is None:
            raise FixtureError("Failed to create fixture a_deontologicalreasoningengine_fixture: instance is None")
        return instance
    except Exception as e:
        raise FixtureError(f"Failed to create fixture a_deontologicalreasoningengine_fixture: {e}") from e


@pytest.fixture
def the_statement_database_contains_10_statements_fixture(a_deontologicalreasoningengine_fixture):
    """
    the statement_database contains 10 statements
    """
    try:
        engine = a_deontologicalreasoningengine_fixture
        
        # Create diverse 10 sample statements
        statements_data = [
            ("stmt_0", "citizens", "pay taxes", DeonticModality.OBLIGATION),
            ("stmt_1", "citizens", "vote", DeonticModality.OBLIGATION),
            ("stmt_2", "citizens", "protest", DeonticModality.PERMISSION),
            ("stmt_3", "employees", "file reports", DeonticModality.OBLIGATION),
            ("stmt_4", "employees", "take breaks", DeonticModality.PERMISSION),
            ("stmt_5", "citizens", "pay taxes", DeonticModality.OBLIGATION),
            ("stmt_6", "drivers", "stop at red lights", DeonticModality.PROHIBITION),
            ("stmt_7", "drivers", "speed", DeonticModality.PROHIBITION),
            ("stmt_8", "citizens", "file taxes", DeonticModality.OBLIGATION),
            ("stmt_9", "residents", "maintain property", DeonticModality.OBLIGATION),
        ]
        
        for stmt_id, entity, action, modality in statements_data:
            stmt = DeonticStatement(
                id=stmt_id,
                entity=entity,
                action=action,
                modality=modality,
                source_document=f"doc_{stmt_id}",
                source_text=f"Sample text for {stmt_id}",
                confidence=0.8,
                context={}
            )
            engine.statement_database[stmt.id] = stmt
        
        # Verify the database was populated
        if len(engine.statement_database) != 10:
            raise FixtureError(f"Failed to create fixture the_statement_database_contains_10_statements_fixture: expected 10 statements, got {len(engine.statement_database)}")
        
        return engine
    except Exception as e:
        raise FixtureError(f"Failed to create fixture the_statement_database_contains_10_statements_fixture: {e}") from e


# Test scenarios

def test_query_with_no_filters_returns_all_statements(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with no filters returns all statements
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements() is called with no filters
    
    Then:
        10 statements are returned
    """
    # When: query_deontic_statements() is called with no filters
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements())
    
    # Then: 10 statements are returned
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_filter_for_citizens(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with entity filter for "citizens"
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        5 statements are returned
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: 5 statements are returned
    expected_count = 5
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_filter_is_case_insensitive(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Entity filter is case-insensitive
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="CITIZENS") is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(entity="CITIZENS") is called
    entity_filter = "CITIZENS"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: statements are returned
    expected_count = 5
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_filter_does_partial_match(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Entity filter does partial match
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citi") is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(entity="citi") is called
    entity_filter = "citi"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: statements are returned
    expected_count = 5
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_modality_filter_obligation(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with modality filter OBLIGATION
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(modality=OBLIGATION) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(modality=OBLIGATION) is called
    modality_filter = DeonticModality.OBLIGATION
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(modality=modality_filter))
    
    # Then: 6 statements are returned
    expected_count = 6
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_modality_filter_permission(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with modality filter PERMISSION
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(modality=PERMISSION) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(modality=PERMISSION) is called
    modality_filter = DeonticModality.PERMISSION
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(modality=modality_filter))
    
    # Then: 2 statements are returned
    expected_count = 2
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_modality_filter_prohibition(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with modality filter PROHIBITION
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(modality=PROHIBITION) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(modality=PROHIBITION) is called
    modality_filter = DeonticModality.PROHIBITION
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(modality=modality_filter))
    
    # Then: 2 statements are returned
    expected_count = 2
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_action_keywords_filter_for_taxes(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with action_keywords filter for "taxes"
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(action_keywords=["taxes"]) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(action_keywords=["taxes"]) is called
    action_keywords = ["taxes"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(action_keywords=action_keywords))
    
    # Then: 3 statements are returned
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_action_keywords_filter_is_case_insensitive(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Action keywords filter is case-insensitive
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(action_keywords=["TAXES"]) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(action_keywords=["TAXES"]) is called
    action_keywords = ["TAXES"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(action_keywords=action_keywords))
    
    # Then: 3 statements are returned
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_multiple_action_keywords(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with multiple action keywords
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(action_keywords=["pay", "file"]) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(action_keywords=["pay", "file"]) is called
    action_keywords = ["pay", "file"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(action_keywords=action_keywords))
    
    # Then: 4 statements are returned
    expected_count = 4
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_and_modality_filters_combined(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with entity and modality filters combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens", modality=OBLIGATION) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(entity="citizens", modality=OBLIGATION) is called
    entity_filter = "citizens"
    modality_filter = DeonticModality.OBLIGATION
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter, modality=modality_filter))
    
    # Then: 4 statements are returned
    expected_count = 4
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_and_action_keywords_filters_combined(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with entity and action_keywords filters combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens", action_keywords=["taxes"]) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(entity="citizens", action_keywords=["taxes"]) is called
    entity_filter = "citizens"
    action_keywords = ["taxes"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter, action_keywords=action_keywords))
    
    # Then: 3 statements are returned
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_all_three_filters_combined(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with all three filters combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens", modality=OBLIGATION, action_keywords=["taxes"]) is called
    
    Then:
        statements are returned
    """
    # When: query_deontic_statements(entity="citizens", modality=OBLIGATION, action_keywords=["taxes"]) is called
    entity_filter = "citizens"
    modality_filter = DeonticModality.OBLIGATION
    action_keywords = ["taxes"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(
        entity=entity_filter, 
        modality=modality_filter, 
        action_keywords=action_keywords
    ))
    
    # Then: 3 statements are returned
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_that_does_not_exist_returns_empty_list(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with entity that does not exist returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="nonexistent") is called
    
    Then:
        0 statements are returned
    """
    # When: query_deontic_statements(entity="nonexistent") is called
    entity_filter = "nonexistent"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: 0 statements are returned
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_action_keywords_that_do_not_exist_returns_empty_list(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with action_keywords that do not exist returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(action_keywords=["nonexistent"]) is called
    
    Then:
        0 statements are returned
    """
    # When: query_deontic_statements(action_keywords=["nonexistent"]) is called
    action_keywords = ["nonexistent"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(action_keywords=action_keywords))
    
    # Then: 0 statements are returned
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_returns_list_of_deonticstatement_instances(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query returns list of DeonticStatement instances
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        each result is DeonticStatement instance
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: each result is DeonticStatement instance
    expected_type = DeonticStatement
    actual_all_instances = all(isinstance(stmt, expected_type) for stmt in result)
    expected_all_instances = True
    assert actual_all_instances == expected_all_instances, f"expected {expected_all_instances}, got {actual_all_instances}"


def test_returned_statements_have_id_attribute(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Returned statements have id attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        each statement has id attribute
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: each statement has id attribute
    expected_has_attribute = True
    actual_has_attribute = all(hasattr(stmt, 'id') for stmt in result)
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_statements_have_entity_attribute(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Returned statements have entity attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        each statement entity is "citizens"
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: each statement entity is "citizens"
    expected_entity = "citizens"
    actual_all_match = all(stmt.entity == expected_entity for stmt in result)
    expected_all_match = True
    assert actual_all_match == expected_all_match, f"expected {expected_all_match}, got {actual_all_match}"


def test_returned_statements_have_action_attribute(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Returned statements have action attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        each statement has action attribute
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: each statement has action attribute
    expected_has_attribute = True
    actual_has_attribute = all(hasattr(stmt, 'action') for stmt in result)
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_statements_have_modality_attribute(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Returned statements have modality attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(modality=OBLIGATION) is called
    
    Then:
        each statement modality is OBLIGATION
    """
    # When: query_deontic_statements(modality=OBLIGATION) is called
    modality_filter = DeonticModality.OBLIGATION
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(modality=modality_filter))
    
    # Then: each statement modality is OBLIGATION
    expected_modality = DeonticModality.OBLIGATION
    actual_all_match = all(stmt.modality == expected_modality for stmt in result)
    expected_all_match = True
    assert actual_all_match == expected_all_match, f"expected {expected_all_match}, got {actual_all_match}"


def test_returned_statements_have_source_document_attribute(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Returned statements have source_document attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        each statement has source_document attribute
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: each statement has source_document attribute
    expected_has_attribute = True
    actual_has_attribute = all(hasattr(stmt, 'source_document') for stmt in result)
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_statements_have_confidence_attribute(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Returned statements have confidence attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        each statement has confidence attribute
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: each statement has confidence attribute
    expected_has_attribute = True
    actual_has_attribute = all(hasattr(stmt, 'confidence') for stmt in result)
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_query_empty_database_returns_empty_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query empty database returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        statement_database is empty
    
    When:
        query_deontic_statements() is called
    
    Then:
        0 statements are returned
    """
    # When: query_deontic_statements() is called
    result = anyio.run(a_deontologicalreasoningengine_fixture.query_deontic_statements())
    
    # Then: 0 statements are returned
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_filter_on_empty_database_returns_empty_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query with entity filter on empty database returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        statement_database is empty
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        0 statements are returned
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(a_deontologicalreasoningengine_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: 0 statements are returned
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_async_method_can_be_awaited(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Async method can be awaited
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements() is called with await
    
    Then:
        result is returned
    """
    # When: query_deontic_statements() is called with await
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements())
    
    # Then: result is returned
    expected_is_not_none = True
    actual_is_not_none = result is not None
    assert actual_is_not_none == expected_is_not_none, f"expected {expected_is_not_none}, got {actual_is_not_none}"


def test_query_after_analyzing_corpus(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query after analyzing corpus
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        query_deontic_statements() is called after analyze_corpus_for_deontic_conflicts()
    
    Then:
        statements from analysis are returned
    """
    # Given: analyze_corpus_for_deontic_conflicts() was called
    documents = [{'id': 'doc1', 'content': 'Citizens must pay taxes.'}]
    anyio.run(a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents))
    
    # When: query_deontic_statements() is called
    result = anyio.run(a_deontologicalreasoningengine_fixture.query_deontic_statements())
    
    # Then: statements from analysis are returned
    expected_has_statements = True
    actual_has_statements = len(result) > 0
    assert actual_has_statements == expected_has_statements, f"expected {expected_has_statements}, got {actual_has_statements}"


def test_query_filters_work_independently(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query filters work independently
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(entity="citizens") is called
    
    Then:
        only entity filter is applied
    """
    # When: query_deontic_statements(entity="citizens") is called
    entity_filter = "citizens"
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(entity=entity_filter))
    
    # Then: only entity filter is applied
    expected_all_match = True
    actual_all_match = all(stmt.entity == entity_filter for stmt in result)
    assert actual_all_match == expected_all_match, f"expected {expected_all_match}, got {actual_all_match}"


def test_query_with_modality_conditional(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query with modality CONDITIONAL
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        query_deontic_statements(modality=CONDITIONAL) is called
    
    Then:
        statements with CONDITIONAL modality are returned
    """
    # Given: Add CONDITIONAL statements
    for i in range(2):
        stmt = DeonticStatement(
            id=f"cond_{i}",
            entity="citizens",
            action=f"action_{i}",
            modality=DeonticModality.CONDITIONAL,
            source_document=f"doc_{i}",
            source_text=f"Conditional text {i}",
            confidence=0.8,
            context={}
        )
        a_deontologicalreasoningengine_fixture.statement_database[stmt.id] = stmt
    
    # When: query_deontic_statements(modality=CONDITIONAL) is called
    modality_filter = DeonticModality.CONDITIONAL
    result = anyio.run(a_deontologicalreasoningengine_fixture.query_deontic_statements(modality=modality_filter))
    
    # Then: 2 statements are returned
    expected_count = 2
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_modality_exception(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query with modality EXCEPTION
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        query_deontic_statements(modality=EXCEPTION) is called
    
    Then:
        statements with EXCEPTION modality are returned
    """
    # Given: Add EXCEPTION statement
    stmt = DeonticStatement(
        id="exc_0",
        entity="citizens",
        action="action_0",
        modality=DeonticModality.EXCEPTION,
        source_document="doc_0",
        source_text="Exception text 0",
        confidence=0.8,
        context={}
    )
    a_deontologicalreasoningengine_fixture.statement_database[stmt.id] = stmt
    
    # When: query_deontic_statements(modality=EXCEPTION) is called
    modality_filter = DeonticModality.EXCEPTION
    result = anyio.run(a_deontologicalreasoningengine_fixture.query_deontic_statements(modality=modality_filter))
    
    # Then: 1 statement is returned
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_action_keyword_matching_multiple_actions(the_statement_database_contains_10_statements_fixture):
    """
    Scenario: Query with action keyword matching multiple actions
    
    Given:
        a DeontologicalReasoningEngine instance
        the statement_database contains 10 statements
    
    When:
        query_deontic_statements(action_keywords=["taxes"]) is called
    
    Then:
        statements with actions containing "taxes" are returned
    """
    # When: query_deontic_statements(action_keywords=["taxes"]) is called
    action_keywords = ["taxes"]
    result = anyio.run(the_statement_database_contains_10_statements_fixture.query_deontic_statements(action_keywords=action_keywords))
    
    # Then: 3 statements are returned
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"
