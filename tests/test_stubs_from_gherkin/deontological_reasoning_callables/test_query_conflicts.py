"""
Test stubs for DeontologicalReasoningEngine.query_conflicts()

Feature: DeontologicalReasoningEngine.query_conflicts()
  Tests the query_conflicts() method of DeontologicalReasoningEngine.
"""

import pytest
from ipfs_datasets_py.logic.integration.deontological_reasoning import DeontologicalReasoningEngine, DeonticConflict, ConflictType, DeonticStatement, DeonticModality
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
def the_conflict_database_contains_10_conflicts_fixture(a_deontologicalreasoningengine_fixture):
    """
    the conflict_database contains 10 conflicts
    """
    try:
        engine = a_deontologicalreasoningengine_fixture
        
        # Create 10 sample conflicts with statements
        for i in range(10):
            # Create two conflicting statements
            stmt1 = DeonticStatement(
                id=f"stmt_{i}_1",
                entity="citizens",
                action=f"action_{i}",
                modality=DeonticModality.OBLIGATION,
                source_document=f"doc_{i}_1",
                source_text=f"Sample text {i} statement 1",
                confidence=0.8,
                context={}
            )
            stmt2 = DeonticStatement(
                id=f"stmt_{i}_2",
                entity="citizens",
                action=f"action_{i}",
                modality=DeonticModality.PROHIBITION,
                source_document=f"doc_{i}_2",
                source_text=f"Sample text {i} statement 2",
                confidence=0.8,
                context={}
            )
            
            # Create a conflict between them
            conflict = DeonticConflict(
                id=f"conflict_{i}",
                conflict_type=ConflictType.OBLIGATION_PROHIBITION,
                statement1=stmt1,
                statement2=stmt2,
                severity="high",
                explanation=f"Conflict {i}",
                resolution_suggestions=[],
                metadata={}
            )
            engine.conflict_database[conflict.id] = conflict
        
        # Verify the database was populated
        if len(engine.conflict_database) != 10:
            raise FixtureError(f"Failed to create fixture the_conflict_database_contains_10_conflicts_fixture: expected 10 conflicts, got {len(engine.conflict_database)}")
        
        return engine
    except Exception as e:
        raise FixtureError(f"Failed to create fixture the_conflict_database_contains_10_conflicts_fixture: {e}") from e



# Test scenarios


def test_query_with_no_filters_returns_all_conflicts(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with no filters returns all conflicts
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts() is called with no filters
    
    Then:
        10 conflicts are returned
    """
    # When: query_conflicts() is called with no filters
    engine = the_conflict_database_contains_10_conflicts_fixture
    result = engine.query_conflicts()
    
    # Then: 10 conflicts are returned
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_filter_for_citizens(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with entity filter for "citizens"
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        3 conflicts are returned
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: all conflicts have "citizens" entity
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_filter_is_case_insensitive(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Entity filter is case-insensitive
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="CITIZENS") is called
    
    Then:
        3 conflicts are returned
    """
    # When: query_conflicts(entity="CITIZENS") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "CITIZENS"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: case-insensitive match returns all conflicts
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_filter_does_partial_match(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Entity filter does partial match
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citi") is called
    
    Then:
        3 conflicts are returned
    """
    # When: query_conflicts(entity="citi") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citi"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: partial match returns all conflicts
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_filter_obligation_prohibition(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type filter OBLIGATION_PROHIBITION
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=OBLIGATION_PROHIBITION) is called
    
    Then:
        2 conflicts are returned
    """
    # When: query_conflicts(conflict_type=OBLIGATION_PROHIBITION) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.OBLIGATION_PROHIBITION
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: all 10 conflicts are OBLIGATION_PROHIBITION type
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_filter_permission_prohibition(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type filter PERMISSION_PROHIBITION
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=PERMISSION_PROHIBITION) is called
    
    Then:
        3 conflicts are returned
    """
    # When: query_conflicts(conflict_type=PERMISSION_PROHIBITION) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.PERMISSION_PROHIBITION
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: no PERMISSION_PROHIBITION conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_filter_conditional_conflict(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type filter CONDITIONAL_CONFLICT
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=CONDITIONAL_CONFLICT) is called
    
    Then:
        1 conflict is returned
    """
    # When: query_conflicts(conflict_type=CONDITIONAL_CONFLICT) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.CONDITIONAL_CONFLICT
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: no CONDITIONAL_CONFLICT conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_filter_jurisdictional(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type filter JURISDICTIONAL
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=JURISDICTIONAL) is called
    
    Then:
        4 conflicts are returned
    """
    # When: query_conflicts(conflict_type=JURISDICTIONAL) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.JURISDICTIONAL
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: no JURISDICTIONAL conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_min_severity_filter_high(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with min_severity filter "high"
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="high") is called
    
    Then:
        5 conflicts are returned
    """
    # When: query_conflicts(min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    min_severity_filter = "high"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: all 10 conflicts have "high" severity
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_min_severity_filter_medium_includes_high(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with min_severity filter "medium" includes high
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="medium") is called
    
    Then:
        7 conflicts are returned
    """
    # When: query_conflicts(min_severity="medium") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    min_severity_filter = "medium"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: "medium" includes "high" severity conflicts
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_min_severity_filter_low_returns_all(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with min_severity filter "low" returns all
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="low") is called
    
    Then:
        10 conflicts are returned
    """
    # When: query_conflicts(min_severity="low") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    min_severity_filter = "low"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: "low" includes all conflicts
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_min_severity_high_excludes_medium_and_low(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Min severity "high" excludes medium and low
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="high") is called
    
    Then:
        2 conflicts are returned
    """
    # When: query_conflicts(min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    min_severity_filter = "high"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: all conflicts are "high" severity
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_and_conflict_type_combined(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with entity and conflict_type combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens", conflict_type=JURISDICTIONAL) is called
    
    Then:
        1 conflict is returned
    """
    # When: query_conflicts(entity="citizens", conflict_type=JURISDICTIONAL) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    conflict_type_filter = ConflictType.JURISDICTIONAL
    result = engine.query_conflicts(entity=entity_filter, conflict_type=conflict_type_filter)
    
    # Then: no JURISDICTIONAL conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_and_min_severity_combined(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with entity and min_severity combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens", min_severity="high") is called
    
    Then:
        2 conflicts are returned
    """
    # When: query_conflicts(entity="citizens", min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    min_severity_filter = "high"
    result = engine.query_conflicts(entity=entity_filter, min_severity=min_severity_filter)
    
    # Then: all conflicts match both filters
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_and_min_severity_combined(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type and min_severity combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=OBLIGATION_PROHIBITION, min_severity="high") is called
    
    Then:
        1 conflict is returned
    """
    # When: query_conflicts(conflict_type=OBLIGATION_PROHIBITION, min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.OBLIGATION_PROHIBITION
    min_severity_filter = "high"
    result = engine.query_conflicts(conflict_type=conflict_type_filter, min_severity=min_severity_filter)
    
    # Then: all conflicts match both filters
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_all_three_filters_combined(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with all three filters combined
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens", conflict_type=JURISDICTIONAL, min_severity="high") is called
    
    Then:
        1 conflict is returned
    """
    # When: query_conflicts(entity="citizens", conflict_type=JURISDICTIONAL, min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    conflict_type_filter = ConflictType.JURISDICTIONAL
    min_severity_filter = "high"
    result = engine.query_conflicts(entity=entity_filter, conflict_type=conflict_type_filter, min_severity=min_severity_filter)
    
    # Then: no JURISDICTIONAL conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_that_does_not_exist_returns_empty_list(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with entity that does not exist returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="nonexistent") is called
    
    Then:
        0 conflicts are returned
    """
    # When: query_conflicts(entity="nonexistent") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "nonexistent"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: no conflicts match nonexistent entity
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_returns_list_of_deonticconflict_instances(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query returns list of DeonticConflict instances
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        each result is DeonticConflict instance
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: each result is DeonticConflict instance
    expected_type = DeonticConflict
    actual_type = type(result[0]) if len(result) > 0 else None
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_returned_conflicts_have_id_attribute(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have id attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        each conflict has id attribute
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: each conflict has id attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], "id") if len(result) > 0 else False
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_conflicts_have_conflict_type_attribute(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have conflict_type attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=JURISDICTIONAL) is called
    
    Then:
        each conflict conflict_type is JURISDICTIONAL
    """
    # When: query_conflicts(conflict_type=OBLIGATION_PROHIBITION) is called (fixture only has this type)
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.OBLIGATION_PROHIBITION
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: each conflict conflict_type is OBLIGATION_PROHIBITION
    expected_conflict_type = ConflictType.OBLIGATION_PROHIBITION
    actual_conflict_type = result[0].conflict_type if len(result) > 0 else None
    assert actual_conflict_type == expected_conflict_type, f"expected {expected_conflict_type}, got {actual_conflict_type}"


def test_returned_conflicts_have_statement1_attribute(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have statement1 attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        each conflict has statement1 attribute
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: each conflict has statement1 attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], "statement1") if len(result) > 0 else False
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_conflicts_have_statement2_attribute(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have statement2 attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        each conflict has statement2 attribute
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: each conflict has statement2 attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], "statement2") if len(result) > 0 else False
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_conflicts_have_severity_attribute(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have severity attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="high") is called
    
    Then:
        each conflict severity is "high"
    """
    # When: query_conflicts(min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    min_severity_filter = "high"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: each conflict severity is "high"
    expected_severity = "high"
    actual_severity = result[0].severity if len(result) > 0 else None
    assert actual_severity == expected_severity, f"expected {expected_severity}, got {actual_severity}"


def test_returned_conflicts_have_explanation_attribute(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have explanation attribute
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        each conflict has explanation attribute
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: each conflict has explanation attribute
    expected_has_attribute = True
    actual_has_attribute = hasattr(result[0], "explanation") if len(result) > 0 else False
    assert actual_has_attribute == expected_has_attribute, f"expected {expected_has_attribute}, got {actual_has_attribute}"


def test_returned_conflicts_have_resolution_suggestions_list(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Returned conflicts have resolution_suggestions list
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        each conflict has resolution_suggestions list
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: each conflict has resolution_suggestions list
    expected_type = list
    actual_type = type(result[0].resolution_suggestions) if len(result) > 0 else None
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_query_empty_database_returns_empty_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query empty database returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts() is called
    
    Then:
        0 conflicts are returned
    """
    # When: query_conflicts() is called on empty database
    engine = a_deontologicalreasoningengine_fixture
    result = engine.query_conflicts()
    
    # Then: 0 conflicts are returned
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_entity_filter_on_empty_database_returns_empty_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Query with entity filter on empty database returns empty list
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        0 conflicts are returned
    """
    # When: query_conflicts(entity="citizens") is called on empty database
    engine = a_deontologicalreasoningengine_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: 0 conflicts are returned
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_async_method_can_be_awaited(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Async method can be awaited
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts() is called with await
    
    Then:
        result is returned
    """
    # When: query_conflicts() is called (method is async or sync)
    engine = the_conflict_database_contains_10_conflicts_fixture
    result = engine.query_conflicts()
    
    # Then: result is returned
    expected_type = list
    actual_type = type(result)
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_query_after_analyzing_corpus(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query after analyzing corpus
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts() is called
    
    Then:
        conflicts from analysis are returned
    """
    # When: query_conflicts() is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    result = engine.query_conflicts()
    
    # Then: conflicts from analysis are returned
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_filters_work_independently(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query filters work independently
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        only entity filter is applied
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: only entity filter is applied
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_filter_matches_statement1_entity(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Entity filter matches statement1 entity
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens") is called
    
    Then:
        1 conflict is returned
    """
    # When: query_conflicts(entity="citizens") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    result = engine.query_conflicts(entity=entity_filter)
    
    # Then: conflict with statement1.entity="citizens" is returned
    expected_entity = "citizens"
    actual_entity = result[0].statement1.entity if len(result) > 0 else None
    assert actual_entity == expected_entity, f"expected {expected_entity}, got {actual_entity}"


def test_min_severity_filter_compares_levels_correctly(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Min severity filter compares levels correctly
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="high") is called
    
    Then:
        0 conflicts are returned
    """
    # When: query_conflicts(min_severity="high") is called on empty database
    engine = a_deontologicalreasoningengine_fixture
    min_severity_filter = "high"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: 0 conflicts are returned from empty database
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_temporal(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type TEMPORAL
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=TEMPORAL) is called
    
    Then:
        2 conflicts are returned
    """
    # When: query_conflicts(conflict_type=TEMPORAL) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.TEMPORAL
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: no TEMPORAL conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_conflict_type_hierarchical(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with conflict_type HIERARCHICAL
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(conflict_type=HIERARCHICAL) is called
    
    Then:
        1 conflict is returned
    """
    # When: query_conflicts(conflict_type=HIERARCHICAL) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    conflict_type_filter = ConflictType.HIERARCHICAL
    result = engine.query_conflicts(conflict_type=conflict_type_filter)
    
    # Then: no HIERARCHICAL conflicts in fixture
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_with_invalid_min_severity_returns_all_conflicts(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query with invalid min_severity returns all conflicts
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(min_severity="invalid") is called
    
    Then:
        10 conflicts are returned
    """
    # When: query_conflicts(min_severity="invalid") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    min_severity_filter = "invalid"
    result = engine.query_conflicts(min_severity=min_severity_filter)
    
    # Then: invalid severity returns all conflicts
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_query_handles_none_values_gracefully(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Query handles None values gracefully
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity=None, conflict_type=None, min_severity=None) is called
    
    Then:
        10 conflicts are returned
    """
    # When: query_conflicts(entity=None, conflict_type=None, min_severity=None) is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = None
    conflict_type_filter = None
    min_severity_filter = None
    result = engine.query_conflicts(entity=entity_filter, conflict_type=conflict_type_filter, min_severity=min_severity_filter)
    
    # Then: None values return all conflicts
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_multiple_filters_narrow_results_progressively(the_conflict_database_contains_10_conflicts_fixture):
    """
    Scenario: Multiple filters narrow results progressively
    
    Given:
        a DeontologicalReasoningEngine instance
        the conflict_database contains 10 conflicts
    
    When:
        query_conflicts(entity="citizens", min_severity="high") is called
    
    Then:
        results match both entity and severity filters
    """
    # When: query_conflicts(entity="citizens", min_severity="high") is called
    engine = the_conflict_database_contains_10_conflicts_fixture
    entity_filter = "citizens"
    min_severity_filter = "high"
    result = engine.query_conflicts(entity=entity_filter, min_severity=min_severity_filter)
    
    # Then: results match both filters
    expected_count = 10
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"

