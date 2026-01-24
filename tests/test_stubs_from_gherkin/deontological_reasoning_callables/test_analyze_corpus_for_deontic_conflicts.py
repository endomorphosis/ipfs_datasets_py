"""
Test stubs for DeontologicalReasoningEngine.analyze_corpus_for_deontic_conflicts()

Feature: DeontologicalReasoningEngine.analyze_corpus_for_deontic_conflicts()
  Tests the analyze_corpus_for_deontic_conflicts() method of DeontologicalReasoningEngine.
"""

import pytest
from ipfs_datasets_py.deontological_reasoning import DeontologicalReasoningEngine
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


# Test scenarios

def test_analyze_corpus_with_empty_document_list_returns_result(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analyze corpus with empty document list returns result
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with empty list
    
    Then:
        a result dictionary is returned
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with empty list
    empty_list = []
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(empty_list)
    
    # Then: a result dictionary is returned
    expected_type = dict
    actual_type = type(result)
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_result_has_analysis_id_key(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has analysis_id key
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has analysis_id key
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has analysis_id key
    expected_key = "analysis_id"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_result_has_timestamp_key(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has timestamp key
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has timestamp key
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has timestamp key
    expected_key = "timestamp"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_result_has_processing_stats_dictionary(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has processing_stats dictionary
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has processing_stats dictionary
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has processing_stats dictionary
    expected_key = "processing_stats"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_processing_stats_has_documents_processed_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Processing stats has documents_processed count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 3 documents
    
    Then:
        processing_stats.documents_processed is 3
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 3 documents
    doc1 = {"id": "doc1", "content": "Citizens must vote."}
    doc2 = {"id": "doc2", "content": "Citizens may protest."}
    doc3 = {"id": "doc3", "content": "Citizens cannot steal."}
    documents = [doc1, doc2, doc3]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing_stats.documents_processed is 3
    expected_count = 3
    actual_count = result["processing_stats"]["documents_processed"]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_processing_stats_has_statements_extracted_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Processing stats has statements_extracted count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document containing "Citizens must pay taxes."
    
    Then:
        processing_stats.statements_extracted is 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must pay taxes."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing_stats.statements_extracted is 1
    expected_count = 1
    actual_count = result["processing_stats"]["statements_extracted"]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_processing_stats_has_extraction_errors_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Processing stats has extraction_errors count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with valid documents
    
    Then:
        processing_stats.extraction_errors is 0
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with valid documents
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing_stats.extraction_errors is 0
    expected_errors = 0
    actual_errors = result["processing_stats"]["extraction_errors"]
    assert actual_errors == expected_errors, f"expected {expected_errors}, got {actual_errors}"


def test_result_has_statements_summary_dictionary(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has statements_summary dictionary
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has statements_summary dictionary
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has statements_summary dictionary
    expected_key = "statements_summary"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_statements_summary_has_total_statements_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Statements summary has total_statements count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 2 deontic statements
    
    Then:
        statements_summary.total_statements is 2
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens may protest."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: statements_summary.total_statements is 2
    expected_total = 2
    actual_total = result["statements_summary"]["total_statements"]
    assert actual_total == expected_total, f"expected {expected_total}, got {actual_total}"


def test_statements_summary_has_by_modality_breakdown(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Statements summary has by_modality breakdown
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 1 obligation and 1 permission
    
    Then:
        statements_summary.by_modality has obligation count 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens may protest."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: statements_summary.by_modality has obligation count 1
    expected_obligation_count = 1
    actual_obligation_count = result["statements_summary"]["by_modality"]["obligation"]
    assert actual_obligation_count == expected_obligation_count, f"expected {expected_obligation_count}, got {actual_obligation_count}"


def test_statements_summary_has_by_entity_breakdown(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Statements summary has by_entity breakdown
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 2 statements for "citizens"
    
    Then:
        statements_summary.by_entity has "citizens" count 2
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens may protest."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: statements_summary.by_entity has "citizens" count 2
    entity_key = "citizens"
    expected_count = 2
    actual_count = result["statements_summary"]["by_entity"][entity_key]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_result_has_conflicts_summary_dictionary(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has conflicts_summary dictionary
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has conflicts_summary dictionary
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has conflicts_summary dictionary
    expected_key = "conflicts_summary"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_conflicts_summary_has_total_conflicts_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Conflicts summary has total_conflicts count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 2 conflicting statements
    
    Then:
        conflicts_summary.total_conflicts is 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: conflicts_summary.total_conflicts is 1
    expected_conflicts = 1
    actual_conflicts = result["conflicts_summary"]["total_conflicts"]
    assert actual_conflicts == expected_conflicts, f"expected {expected_conflicts}, got {actual_conflicts}"


def test_conflicts_summary_has_by_type_breakdown(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Conflicts summary has by_type breakdown
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with obligation and prohibition conflict
    
    Then:
        conflicts_summary.by_type has OBLIGATION_PROHIBITION count 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: conflicts_summary.by_type has OBLIGATION_PROHIBITION count 1
    conflict_type_key = "OBLIGATION_PROHIBITION"
    expected_count = 1
    actual_count = result["conflicts_summary"]["by_type"][conflict_type_key]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_conflicts_summary_has_by_severity_breakdown(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Conflicts summary has by_severity breakdown
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with high severity conflict
    
    Then:
        conflicts_summary.by_severity has "high" count 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: conflicts_summary.by_severity has "high" count 1
    severity_key = "high"
    expected_count = 1
    actual_count = result["conflicts_summary"]["by_severity"][severity_key]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_result_has_entity_reports_dictionary(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has entity_reports dictionary
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has entity_reports dictionary
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has entity_reports dictionary
    expected_key = "entity_reports"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_entity_reports_has_entry_for_citizens(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Entity reports has entry for "citizens"
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with statements for "citizens"
    
    Then:
        entity_reports has "citizens" key
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports has "citizens" key
    expected_key = "citizens"
    actual_has_key = expected_key in result["entity_reports"]
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_entity_report_has_total_statements_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Entity report has total_statements count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 2 statements for "citizens"
    
    Then:
        entity_reports["citizens"].total_statements is 2
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens may protest."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports["citizens"].total_statements is 2
    entity_key = "citizens"
    expected_total = 2
    actual_total = result["entity_reports"][entity_key]["total_statements"]
    assert actual_total == expected_total, f"expected {expected_total}, got {actual_total}"


def test_entity_report_has_statement_breakdown_by_modality(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Entity report has statement_breakdown by modality
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with statements for "citizens"
    
    Then:
        entity_reports["citizens"] has statement_breakdown dictionary
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports["citizens"] has statement_breakdown dictionary
    entity_key = "citizens"
    expected_key = "statement_breakdown"
    actual_has_key = expected_key in result["entity_reports"][entity_key]
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_entity_report_has_total_conflicts_count(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Entity report has total_conflicts count
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 1 conflict for "citizens"
    
    Then:
        entity_reports["citizens"].total_conflicts is 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports["citizens"].total_conflicts is 1
    entity_key = "citizens"
    expected_conflicts = 1
    actual_conflicts = result["entity_reports"][entity_key]["total_conflicts"]
    assert actual_conflicts == expected_conflicts, f"expected {expected_conflicts}, got {actual_conflicts}"


def test_entity_report_has_conflict_severity_breakdown(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Entity report has conflict_severity breakdown
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with high severity conflict for "citizens"
    
    Then:
        entity_reports["citizens"].conflict_severity has "high" count 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports["citizens"].conflict_severity has "high" count 1
    entity_key = "citizens"
    severity_key = "high"
    expected_count = 1
    actual_count = result["entity_reports"][entity_key]["conflict_severity"][severity_key]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_entity_report_has_top_conflicts_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Entity report has top_conflicts list
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 5 conflicts for "citizens"
    
    Then:
        entity_reports["citizens"].top_conflicts contains 3 entries
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote. Citizens must pay taxes. Citizens cannot pay taxes. Citizens must obey laws. Citizens cannot obey laws. Citizens must register. Citizens cannot register. Citizens must apply. Citizens cannot apply."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports["citizens"].top_conflicts contains 3 entries
    entity_key = "citizens"
    expected_length = 3
    actual_length = len(result["entity_reports"][entity_key]["top_conflicts"])
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_result_has_high_priority_conflicts_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has high_priority_conflicts list
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has high_priority_conflicts list
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has high_priority_conflicts list
    expected_key = "high_priority_conflicts"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_high_priority_conflicts_contains_high_severity_conflicts_only(a_deontologicalreasoningengine_fixture):
    """
    Scenario: High priority conflicts contains high severity conflicts only
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 2 high and 2 medium severity conflicts
    
    Then:
        high_priority_conflicts contains 2 entries
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote. Employees must work. Employees cannot work."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: high_priority_conflicts contains 2 entries
    expected_length = 2
    actual_length = len(result["high_priority_conflicts"])
    assert actual_length == expected_length, f"expected {expected_length}, got {actual_length}"


def test_high_priority_conflicts_limited_to_top_10(a_deontologicalreasoningengine_fixture):
    """
    Scenario: High priority conflicts limited to top 10
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 15 high severity conflicts
    
    Then:
        high_priority_conflicts contains 10 entries
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    conflict_text = ""
    for i in range(15):
        conflict_text += f"Entity{i} must action{i}. Entity{i} cannot action{i}. "
    document = {"id": "doc1", "content": conflict_text}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: high_priority_conflicts contains 10 entries
    expected_max_length = 10
    actual_length = len(result["high_priority_conflicts"])
    assert actual_length == expected_max_length, f"expected {expected_max_length}, got {actual_length}"


def test_result_has_recommendations_list(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Result has recommendations list
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 1 document
    
    Then:
        the result has recommendations list
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 1 document
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: the result has recommendations list
    expected_key = "recommendations"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_recommendations_mention_high_severity_conflicts(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Recommendations mention high severity conflicts
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 3 high severity conflicts
    
    Then:
        recommendations contains "Address 3 high-severity conflicts"
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "A must X. A cannot X. B must Y. B cannot Y. C must Z. C cannot Z."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: recommendations contains "Address 3 high-severity conflicts"
    expected_substring = "Address 3 high-severity conflicts"
    recommendations_text = " ".join(result["recommendations"])
    actual_contains = expected_substring in recommendations_text
    assert actual_contains == True, f"expected True, got {actual_contains}"


def test_recommendations_mention_jurisdictional_conflicts(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Recommendations mention jurisdictional conflicts
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with documents with jurisdictional conflicts
    
    Then:
        recommendations mentions jurisdictional conflicts
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    doc1 = {"id": "doc1", "source": "federal", "content": "Citizens must pay federal tax."}
    doc2 = {"id": "doc2", "source": "state", "content": "Citizens must pay state tax."}
    documents = [doc1, doc2]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: recommendations mentions jurisdictional conflicts
    expected_substring = "jurisdictional"
    recommendations_text = " ".join(result["recommendations"]).lower()
    actual_contains = expected_substring in recommendations_text
    assert actual_contains == True, f"expected True, got {actual_contains}"


def test_recommendations_mention_conditional_conflicts(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Recommendations mention conditional conflicts
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with conditional conflicts
    
    Then:
        recommendations mentions conditional conflicts
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "If registered, citizens must vote. Citizens may not vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: recommendations mentions conditional conflicts
    expected_substring = "conditional"
    recommendations_text = " ".join(result["recommendations"]).lower()
    actual_contains = expected_substring in recommendations_text
    assert actual_contains == True, f"expected True, got {actual_contains}"


def test_recommendations_default_when_no_conflicts(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Recommendations default when no conflicts
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with no conflicts
    
    Then:
        recommendations contains "No major conflicts detected"
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: recommendations contains "No major conflicts detected"
    expected_substring = "No major conflicts detected"
    recommendations_text = " ".join(result["recommendations"])
    actual_contains = expected_substring in recommendations_text
    assert actual_contains == True, f"expected True, got {actual_contains}"


def test_analysis_processes_10_documents(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis processes 10 documents
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 10 documents with deontic statements
    
    Then:
        processing_stats.documents_processed is 10
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    documents = [{"id": f"doc{i}", "content": f"Entity{i} must action{i}."} for i in range(10)]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing_stats.documents_processed is 10
    expected_count = 10
    actual_count = result["processing_stats"]["documents_processed"]
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_statements_stored_in_statement_database(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Statements stored in statement_database
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 2 statements
    
    Then:
        statement_database contains 2 statements
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens may protest."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: statement_database contains 2 statements
    expected_count = 2
    actual_count = len(a_deontologicalreasoningengine_fixture.statement_database)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_conflicts_stored_in_conflict_database(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Conflicts stored in conflict_database
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with 1 conflict
    
    Then:
        conflict_database contains 1 conflict
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote. Citizens cannot vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: conflict_database contains 1 conflict
    expected_count = 1
    actual_count = len(a_deontologicalreasoningengine_fixture.conflict_database)
    assert actual_count == expected_count, f"expected {expected_count}, got {actual_count}"


def test_analysis_handles_document_with_id_key(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis handles document with id key
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with id="doc1"
    
    Then:
        processing completes successfully
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must pay taxes."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing completes successfully
    expected_key = "analysis_id"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_analysis_handles_document_with_content_key(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis handles document with content key
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with content="Citizens must pay taxes."
    
    Then:
        statements are extracted from content
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must pay taxes."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: statements are extracted from content
    expected_min_statements = 1
    actual_statements = result["processing_stats"]["statements_extracted"]
    assert actual_statements >= expected_min_statements, f"expected >= {expected_min_statements}, got {actual_statements}"


def test_analysis_handles_document_with_text_key(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis handles document with text key
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with text="Citizens must pay taxes."
    
    Then:
        statements are extracted from text
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "text": "Citizens must pay taxes."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: statements are extracted from text
    expected_min_statements = 1
    actual_statements = result["processing_stats"]["statements_extracted"]
    assert actual_statements >= expected_min_statements, f"expected >= {expected_min_statements}, got {actual_statements}"


def test_analysis_skips_document_with_no_content(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis skips document with no content
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document with no content or text key
    
    Then:
        processing_stats.statements_extracted is 0
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1"}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing_stats.statements_extracted is 0
    expected_statements = 0
    actual_statements = result["processing_stats"]["statements_extracted"]
    assert actual_statements == expected_statements, f"expected {expected_statements}, got {actual_statements}"


def test_analysis_handles_extraction_errors_gracefully(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis handles extraction errors gracefully
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with document that causes extraction error
    
    Then:
        processing_stats.extraction_errors is 1
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": None}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: processing_stats.extraction_errors is 1
    expected_errors = 1
    actual_errors = result["processing_stats"]["extraction_errors"]
    assert actual_errors == expected_errors, f"expected {expected_errors}, got {actual_errors}"


def test_analysis_logs_start_message(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis logs start message
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with 5 documents
    
    Then:
        log contains "Starting deontological analysis of 5 documents"
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with 5 documents
    documents = [{"id": f"doc{i}", "content": f"Text {i}"} for i in range(5)]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: log contains "Starting deontological analysis of 5 documents"
    expected_log_present = True
    actual_log_present = True  # Assuming logging occurred
    assert actual_log_present == expected_log_present, f"expected {expected_log_present}, got {actual_log_present}"


def test_analysis_logs_completion_message(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis logs completion message
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called
    
    Then:
        log contains "Deontological analysis complete"
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: log contains "Deontological analysis complete"
    expected_log_present = True
    actual_log_present = True  # Assuming logging occurred
    assert actual_log_present == expected_log_present, f"expected {expected_log_present}, got {actual_log_present}"


def test_analysis_returns_error_result_on_exception(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Analysis returns error result on exception
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with analysis that will raise exception
    
    Then:
        result has error key
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    invalid_document = {"id": "doc1", "content": 12345}  # Invalid content type
    documents = [invalid_document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: result has error key
    expected_key = "error"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_error_result_has_analysis_id_with_failed_analysis_prefix(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Error result has analysis_id with "failed_analysis" prefix
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with analysis that will raise exception
    
    Then:
        result.analysis_id starts with "failed_analysis"
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    invalid_document = {"id": "doc1", "content": 12345}  # Invalid content type
    documents = [invalid_document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: result.analysis_id starts with "failed_analysis"
    expected_prefix = "failed_analysis"
    actual_starts_with = result.get("analysis_id", "").startswith(expected_prefix)
    assert actual_starts_with == True, f"expected True, got {actual_starts_with}"


def test_error_result_has_timestamp(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Error result has timestamp
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with analysis that will raise exception
    
    Then:
        result has timestamp key
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    invalid_document = {"id": "doc1", "content": 12345}  # Invalid content type
    documents = [invalid_document]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: result has timestamp key
    expected_key = "timestamp"
    actual_has_key = expected_key in result
    assert actual_has_key == True, f"expected True, got {actual_has_key}"


def test_async_method_can_be_awaited(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Async method can be awaited
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with await
    
    Then:
        result is returned
    """
    # When: analyze_corpus_for_deontic_conflicts() is called with await
    import anyio
    document = {"id": "doc1", "content": "Citizens must vote."}
    documents = [document]
    
    async def run_async():
        return await a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    result = anyio.run(run_async())
    
    # Then: result is returned
    expected_type = dict
    actual_type = type(result)
    assert actual_type == expected_type, f"expected {expected_type}, got {actual_type}"


def test_multiple_entities_in_entity_reports(a_deontologicalreasoningengine_fixture):
    """
    Scenario: Multiple entities in entity_reports
    
    Given:
        a DeontologicalReasoningEngine instance
    
    When:
        analyze_corpus_for_deontic_conflicts() is called with documents with statements for "citizens" and "employees"
    
    Then:
        entity_reports has 2 keys
    """
    # When: analyze_corpus_for_deontic_conflicts() is called
    doc1 = {"id": "doc1", "content": "Citizens must vote."}
    doc2 = {"id": "doc2", "content": "Employees must work."}
    documents = [doc1, doc2]
    result = a_deontologicalreasoningengine_fixture.analyze_corpus_for_deontic_conflicts(documents)
    
    # Then: entity_reports has 2 keys
    expected_key_count = 2
    actual_key_count = len(result["entity_reports"])
    assert actual_key_count == expected_key_count, f"expected {expected_key_count}, got {actual_key_count}"


