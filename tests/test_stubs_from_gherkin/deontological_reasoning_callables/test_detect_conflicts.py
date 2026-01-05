"""
Test stubs for ConflictDetector.detect_conflicts()

Feature: ConflictDetector.detect_conflicts()
  Tests the detect_conflicts() method of ConflictDetector.
"""

import pytest
from ipfs_datasets_py.deontological_reasoning import ConflictDetector, DeonticStatement, DeonticConflict, ConflictType
from conftest import FixtureError


# Fixtures from Background

@pytest.fixture
def a_conflictdetector_fixture():
    """
    a ConflictDetector instance
    """
    try:
        instance = ConflictDetector()
        if instance is None:
            raise FixtureError("Failed to create fixture a_conflictdetector_fixture: instance is None")
        return instance
    except Exception as e:
        raise FixtureError(f"Failed to create fixture a_conflictdetector_fixture: {e}") from e


# Test scenarios

def test_detect_conflicts_with_empty_statement_list_returns_empty_list(a_conflictdetector_fixture):
    """
    Scenario: Detect conflicts with empty statement list returns empty list
    
    Given:
        a ConflictDetector instance
    
    When:
        detect_conflicts() is called with empty list
    
    Then:
        an empty list is returned
    """
    # When: detect_conflicts() is called with empty list
    empty_list = []
    result = a_conflictdetector_fixture.detect_conflicts(empty_list)
    
    # Then: an empty list is returned
    expected_length = 0
    actual_length = len(result)
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_detect_conflicts_with_single_statement_returns_empty_list(a_conflictdetector_fixture):
    """
    Scenario: Detect conflicts with single statement returns empty list
    
    Given:
        a ConflictDetector instance
        1 statement for "citizens" with modality OBLIGATION
    
    When:
        detect_conflicts() is called
    
    Then:
        an empty list is returned
    """
    # When: detect_conflicts() is called
    statement = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([statement])
    
    # Then: an empty list is returned
    expected_length = 0
    actual_length = len(result)
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_detect_no_conflict_between_different_entities(a_conflictdetector_fixture):
    """
    Scenario: Detect no conflict between different entities
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "employees" must "submit reports"
    
    When:
        detect_conflicts() is called
    
    Then:
        0 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="employees",
        modality="OBLIGATION",
        action="submit reports",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 0 conflicts are detected
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_detect_no_conflict_between_unrelated_actions(a_conflictdetector_fixture):
    """
    Scenario: Detect no conflict between unrelated actions
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        0 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="OBLIGATION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 0 conflicts are detected
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_detect_obligation_prohibition_conflict(a_conflictdetector_fixture):
    """
    Scenario: Detect OBLIGATION_PROHIBITION conflict
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        1 conflict is detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 1 conflict is detected
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_detected_conflict_has_conflict_type_obligation_prohibition(a_conflictdetector_fixture):
    """
    Scenario: Detected conflict has conflict_type OBLIGATION_PROHIBITION
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict type is OBLIGATION_PROHIBITION
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict type is OBLIGATION_PROHIBITION
    expected_type = ConflictType.OBLIGATION_PROHIBITION
    actual_type = result[0].conflict_type
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_obligation_prohibition_conflict_has_severity_high(a_conflictdetector_fixture):
    """
    Scenario: OBLIGATION_PROHIBITION conflict has severity "high"
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict severity is "high"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict severity is "high"
    expected_severity = "high"
    actual_severity = result[0].severity
    assert actual_severity == expected_severity, f"expected {expected_severity}, got {actual_severity}"


def test_conflict_has_unique_id(a_conflictdetector_fixture):
    """
    Scenario: Conflict has unique id
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict id is "conflict_stmt_1_stmt_2"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict id is "conflict_stmt_1_stmt_2"
    expected_id = "conflict_stmt_1_stmt_2"
    actual_id = result[0].id
    assert actual_id == expected_id, f"expected {expected_id}, got {actual_id}"


def test_conflict_has_statement1_and_statement2_attributes(a_conflictdetector_fixture):
    """
    Scenario: Conflict has statement1 and statement2 attributes
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict has statement1 and statement2 attributes
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict has statement1 and statement2 attributes
    expected_has_attributes = True
    actual_has_attributes = hasattr(result[0], 'statement1') and hasattr(result[0], 'statement2')
    assert actual_has_attributes == expected_has_attributes, f"expected {expected_has_attributes}, got {actual_has_attributes}"


def test_conflict_has_explanation_text(a_conflictdetector_fixture):
    """
    Scenario: Conflict has explanation text
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict explanation contains "conflicting obligations"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict explanation contains "conflicting obligations"
    search_text = "conflicting obligations"
    actual_contains = search_text in result[0].explanation.lower()
    expected_contains = True
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_detect_permission_prohibition_conflict(a_conflictdetector_fixture):
    """
    Scenario: Detect PERMISSION_PROHIBITION conflict
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" may "vote"
        statement 2: "citizens" cannot "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        1 conflict is detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="PERMISSION",
        action="vote",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 1 conflict is detected
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_permission_prohibition_has_conflict_type_permission_prohibition(a_conflictdetector_fixture):
    """
    Scenario: PERMISSION_PROHIBITION has conflict_type PERMISSION_PROHIBITION
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" may "vote"
        statement 2: "citizens" cannot "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict type is PERMISSION_PROHIBITION
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="PERMISSION",
        action="vote",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict type is PERMISSION_PROHIBITION
    expected_type = ConflictType.PERMISSION_PROHIBITION
    actual_type = result[0].conflict_type
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_permission_prohibition_conflict_has_severity_high(a_conflictdetector_fixture):
    """
    Scenario: PERMISSION_PROHIBITION conflict has severity "high"
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" may "vote"
        statement 2: "citizens" cannot "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict severity is "high"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="PERMISSION",
        action="vote",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict severity is "high"
    expected_severity = "high"
    actual_severity = result[0].severity
    assert actual_severity == expected_severity, f"expected {expected_severity}, got {actual_severity}"


def test_permission_prohibition_explanation_mentions_permissions(a_conflictdetector_fixture):
    """
    Scenario: PERMISSION_PROHIBITION explanation mentions "permissions"
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" may "vote"
        statement 2: "citizens" cannot "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict explanation contains "conflicting permissions"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="PERMISSION",
        action="vote",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict explanation contains "conflicting permissions"
    search_text = "conflicting permissions"
    actual_contains = search_text in result[0].explanation.lower()
    expected_contains = True
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_detect_conditional_conflict_between_conditionals(a_conflictdetector_fixture):
    """
    Scenario: Detect CONDITIONAL_CONFLICT between conditionals
    
    Given:
        a ConflictDetector instance
        conditional statement 1: if "condition A" then "citizens" must "act"
        conditional statement 2: if "condition A" then "citizens" must not "act"
    
    When:
        detect_conflicts() is called
    
    Then:
        1 conflict is detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="act",
        document_id="doc1",
        conditions=["condition A"]
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="act",
        document_id="doc1",
        conditions=["condition A"]
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 1 conflict is detected
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_conditional_conflict_has_conflict_type_conditional_conflict(a_conflictdetector_fixture):
    """
    Scenario: CONDITIONAL_CONFLICT has conflict_type CONDITIONAL_CONFLICT
    
    Given:
        a ConflictDetector instance
        conditional statement 1: if "condition A" then "citizens" must "act"
        conditional statement 2: if "condition A" then "citizens" must not "act"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict type is CONDITIONAL_CONFLICT
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="act",
        document_id="doc1",
        conditions=["condition A"]
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="act",
        document_id="doc1",
        conditions=["condition A"]
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict type is CONDITIONAL_CONFLICT
    expected_type = ConflictType.CONDITIONAL_CONFLICT
    actual_type = result[0].conflict_type
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_conditional_conflict_has_severity_medium(a_conflictdetector_fixture):
    """
    Scenario: CONDITIONAL_CONFLICT has severity "medium"
    
    Given:
        a ConflictDetector instance
        conditional statement 1: if "condition A" then "citizens" must "act"
        conditional statement 2: if "condition A" then "citizens" must not "act"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict severity is "medium"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="act",
        document_id="doc1",
        conditions=["condition A"]
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="act",
        document_id="doc1",
        conditions=["condition A"]
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict severity is "medium"
    expected_severity = "medium"
    actual_severity = result[0].severity
    assert actual_severity == expected_severity, f"expected {expected_severity}, got {actual_severity}"


def test_detect_jurisdictional_conflict_from_different_sources(a_conflictdetector_fixture):
    """
    Scenario: Detect JURISDICTIONAL conflict from different sources
    
    Given:
        a ConflictDetector instance
        statement 1 from "doc1": "citizens" must "pay taxes"
        statement 2 from "doc2": "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        1 conflict is detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc2"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 1 conflict is detected
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_jurisdictional_conflict_has_conflict_type_jurisdictional(a_conflictdetector_fixture):
    """
    Scenario: JURISDICTIONAL conflict has conflict_type JURISDICTIONAL
    
    Given:
        a ConflictDetector instance
        statement 1 from "doc1": "citizens" must "pay taxes"
        statement 2 from "doc2": "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict type is JURISDICTIONAL
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc2"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict type is JURISDICTIONAL
    expected_type = ConflictType.JURISDICTIONAL
    actual_type = result[0].conflict_type
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_jurisdictional_conflict_has_severity_medium(a_conflictdetector_fixture):
    """
    Scenario: JURISDICTIONAL conflict has severity "medium"
    
    Given:
        a ConflictDetector instance
        statement 1 from "doc1": "citizens" must "pay taxes"
        statement 2 from "doc2": "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict severity is "medium"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc2"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict severity is "medium"
    expected_severity = "medium"
    actual_severity = result[0].severity
    assert actual_severity == expected_severity, f"expected {expected_severity}, got {actual_severity}"


def test_conflict_has_resolution_suggestions_list(a_conflictdetector_fixture):
    """
    Scenario: Conflict has resolution_suggestions list
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict has resolution_suggestions list
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict has resolution_suggestions list
    expected_has_list = True
    actual_has_list = isinstance(result[0].resolution_suggestions, list)
    assert actual_has_list == expected_has_list, f"expected {expected_has_list}, got {actual_has_list}"


def test_obligation_prohibition_suggestions_include_checking_exceptions(a_conflictdetector_fixture):
    """
    Scenario: OBLIGATION_PROHIBITION suggestions include checking exceptions
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        resolution_suggestions contains "Check for exceptions"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: resolution_suggestions contains "Check for exceptions"
    search_text = "Check for exceptions"
    actual_contains = any(search_text in suggestion for suggestion in result[0].resolution_suggestions)
    expected_contains = True
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_jurisdictional_suggestions_include_determining_precedence(a_conflictdetector_fixture):
    """
    Scenario: JURISDICTIONAL suggestions include determining precedence
    
    Given:
        a ConflictDetector instance
        statement 1 from "doc1": "citizens" must "pay taxes"
        statement 2 from "doc2": "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        resolution_suggestions contains "Determine which jurisdiction takes precedence"
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc2"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: resolution_suggestions contains "Determine which jurisdiction takes precedence"
    search_text = "Determine which jurisdiction takes precedence"
    actual_contains = any(search_text in suggestion for suggestion in result[0].resolution_suggestions)
    expected_contains = True
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_detect_multiple_conflicts_in_list(a_conflictdetector_fixture):
    """
    Scenario: Detect multiple conflicts in list
    
    Given:
        a ConflictDetector instance
        2 pairs of conflicting statements
    
    When:
        detect_conflicts() is called
    
    Then:
        2 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt3 = DeonticStatement(
        id="stmt_3",
        entity="citizens",
        modality="PERMISSION",
        action="vote",
        document_id="doc1"
    )
    stmt4 = DeonticStatement(
        id="stmt_4",
        entity="citizens",
        modality="PROHIBITION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2, stmt3, stmt4])
    
    # Then: 2 conflicts are detected
    expected_count = 2
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_detect_0_conflicts_with_3_non_conflicting_statements(a_conflictdetector_fixture):
    """
    Scenario: Detect 0 conflicts with 3 non-conflicting statements
    
    Given:
        a ConflictDetector instance
        3 non-conflicting statements for same entity
    
    When:
        detect_conflicts() is called
    
    Then:
        0 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="OBLIGATION",
        action="vote",
        document_id="doc1"
    )
    stmt3 = DeonticStatement(
        id="stmt_3",
        entity="citizens",
        modality="PERMISSION",
        action="protest",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2, stmt3])
    
    # Then: 0 conflicts are detected
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_actions_are_related_if_they_share_word_taxes(a_conflictdetector_fixture):
    """
    Scenario: Actions are related if they share word "taxes"
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes annually"
    
    When:
        detect_conflicts() is called
    
    Then:
        1 conflict is detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes annually",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 1 conflict is detected
    expected_count = 1
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_actions_are_not_related_if_no_shared_words(a_conflictdetector_fixture):
    """
    Scenario: Actions are not related if no shared words
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay"
        statement 2: "citizens" must not "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        0 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 0 conflicts are detected
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_conflict_has_metadata_dictionary(a_conflictdetector_fixture):
    """
    Scenario: Conflict has metadata dictionary
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" must "pay taxes"
        statement 2: "citizens" must not "pay taxes"
    
    When:
        detect_conflicts() is called
    
    Then:
        the conflict has metadata dictionary
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: the conflict has metadata dictionary
    expected_has_metadata = True
    actual_has_metadata = isinstance(result[0].metadata, dict)
    assert actual_has_metadata == expected_has_metadata, f"expected {expected_has_metadata}, got {actual_has_metadata}"


def test_detect_3_conflicts_from_4_statements(a_conflictdetector_fixture):
    """
    Scenario: Detect 3 conflicts from 4 statements
    
    Given:
        a ConflictDetector instance
        4 statements where 3 pairs conflict
    
    When:
        detect_conflicts() is called
    
    Then:
        3 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc1"
    )
    stmt3 = DeonticStatement(
        id="stmt_3",
        entity="citizens",
        modality="OBLIGATION",
        action="pay taxes",
        document_id="doc2"
    )
    stmt4 = DeonticStatement(
        id="stmt_4",
        entity="citizens",
        modality="PROHIBITION",
        action="pay taxes",
        document_id="doc3"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2, stmt3, stmt4])
    
    # Then: 3 conflicts are detected
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_no_conflict_between_permission_and_obligation(a_conflictdetector_fixture):
    """
    Scenario: No conflict between PERMISSION and OBLIGATION
    
    Given:
        a ConflictDetector instance
        statement 1: "citizens" may "vote"
        statement 2: "citizens" must "vote"
    
    When:
        detect_conflicts() is called
    
    Then:
        0 conflicts are detected
    """
    # When: detect_conflicts() is called
    stmt1 = DeonticStatement(
        id="stmt_1",
        entity="citizens",
        modality="PERMISSION",
        action="vote",
        document_id="doc1"
    )
    stmt2 = DeonticStatement(
        id="stmt_2",
        entity="citizens",
        modality="OBLIGATION",
        action="vote",
        document_id="doc1"
    )
    result = a_conflictdetector_fixture.detect_conflicts([stmt1, stmt2])
    
    # Then: 0 conflicts are detected
    expected_count = 0
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_statements_grouped_by_entity_for_efficiency(a_conflictdetector_fixture):
    """
    Scenario: Statements grouped by entity for efficiency
    
    Given:
        a ConflictDetector instance
        10 statements for 3 different entities
    
    When:
        detect_conflicts() is called
    
    Then:
        conflicts are detected only within same entity
    """
    # When: detect_conflicts() is called
    statements = []
    for i in range(3):
        statements.append(DeonticStatement(
            id=f"stmt_{i}_1",
            entity=f"entity{i}",
            modality="OBLIGATION",
            action="action",
            document_id="doc1"
        ))
        statements.append(DeonticStatement(
            id=f"stmt_{i}_2",
            entity=f"entity{i}",
            modality="PROHIBITION",
            action="action",
            document_id="doc1"
        ))
    statements.append(DeonticStatement(
        id="stmt_extra_1",
        entity="entity0",
        modality="OBLIGATION",
        action="other",
        document_id="doc1"
    ))
    statements.append(DeonticStatement(
        id="stmt_extra_2",
        entity="entity1",
        modality="OBLIGATION",
        action="other",
        document_id="doc1"
    ))
    statements.append(DeonticStatement(
        id="stmt_extra_3",
        entity="entity2",
        modality="OBLIGATION",
        action="other",
        document_id="doc1"
    ))
    statements.append(DeonticStatement(
        id="stmt_extra_4",
        entity="entity2",
        modality="PERMISSION",
        action="extra",
        document_id="doc1"
    ))
    result = a_conflictdetector_fixture.detect_conflicts(statements)
    
    # Then: conflicts are detected only within same entity
    expected_count = 3
    actual_count = len(result)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


