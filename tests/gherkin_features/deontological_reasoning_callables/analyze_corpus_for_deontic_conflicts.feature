Feature: DeontologicalReasoningEngine.analyze_corpus_for_deontic_conflicts()
  Tests the analyze_corpus_for_deontic_conflicts() method of DeontologicalReasoningEngine.
  This callable analyzes a corpus of documents for deontic conflicts.

  Background:
    Given a DeontologicalReasoningEngine instance

  Scenario: Analyze corpus with empty document list returns result
    When analyze_corpus_for_deontic_conflicts() is called with empty list
    Then a result dictionary is returned

  Scenario: Result has analysis_id key
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has analysis_id key

  Scenario: Result has timestamp key
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has timestamp key

  Scenario: Result has processing_stats dictionary
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has processing_stats dictionary

  Scenario: Processing stats has documents_processed count
    When analyze_corpus_for_deontic_conflicts() is called with 3 documents
    Then processing_stats.documents_processed is 3

  Scenario: Processing stats has statements_extracted count
    Given document with text "Citizens must pay taxes."
    When analyze_corpus_for_deontic_conflicts() is called
    Then processing_stats.statements_extracted is 1

  Scenario: Processing stats has extraction_errors count
    When analyze_corpus_for_deontic_conflicts() is called with valid documents
    Then processing_stats.extraction_errors is 0

  Scenario: Result has statements_summary dictionary
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has statements_summary dictionary

  Scenario: Statements summary has total_statements count
    Given document with 2 deontic statements
    When analyze_corpus_for_deontic_conflicts() is called
    Then statements_summary.total_statements is 2

  Scenario: Statements summary has by_modality breakdown
    Given document with 1 obligation and 1 permission
    When analyze_corpus_for_deontic_conflicts() is called
    Then statements_summary.by_modality has obligation count 1

  Scenario: Statements summary has by_entity breakdown
    Given document with 2 statements for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then statements_summary.by_entity has "citizens" count 2

  Scenario: Result has conflicts_summary dictionary
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has conflicts_summary dictionary

  Scenario: Conflicts summary has total_conflicts count
    Given document with 2 conflicting statements
    When analyze_corpus_for_deontic_conflicts() is called
    Then conflicts_summary.total_conflicts is 1

  Scenario: Conflicts summary has by_type breakdown
    Given document with obligation and prohibition conflict
    When analyze_corpus_for_deontic_conflicts() is called
    Then conflicts_summary.by_type has OBLIGATION_PROHIBITION count 1

  Scenario: Conflicts summary has by_severity breakdown
    Given document with high severity conflict
    When analyze_corpus_for_deontic_conflicts() is called
    Then conflicts_summary.by_severity has "high" count 1

  Scenario: Result has entity_reports dictionary
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has entity_reports dictionary

  Scenario: Entity reports has entry for "citizens"
    Given document with statements for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports has "citizens" key

  Scenario: Entity report has total_statements count
    Given document with 2 statements for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports["citizens"].total_statements is 2

  Scenario: Entity report has statement_breakdown by modality
    Given document with statements for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports["citizens"] has statement_breakdown dictionary

  Scenario: Entity report has total_conflicts count
    Given document with 1 conflict for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports["citizens"].total_conflicts is 1

  Scenario: Entity report has conflict_severity breakdown
    Given document with high severity conflict for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports["citizens"].conflict_severity has "high" count 1

  Scenario: Entity report has top_conflicts list
    Given document with 5 conflicts for "citizens"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports["citizens"].top_conflicts contains 3 entries

  Scenario: Result has high_priority_conflicts list
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has high_priority_conflicts list

  Scenario: High priority conflicts contains high severity conflicts only
    Given document with 2 high and 2 medium severity conflicts
    When analyze_corpus_for_deontic_conflicts() is called
    Then high_priority_conflicts contains 2 entries

  Scenario: High priority conflicts limited to top 10
    Given document with 15 high severity conflicts
    When analyze_corpus_for_deontic_conflicts() is called
    Then high_priority_conflicts contains 10 entries

  Scenario: Result has recommendations list
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the result has recommendations list

  Scenario: Recommendations mention high severity conflicts
    Given document with 3 high severity conflicts
    When analyze_corpus_for_deontic_conflicts() is called
    Then recommendations contains "Address 3 high-severity conflicts"

  Scenario: Recommendations mention jurisdictional conflicts
    Given documents with jurisdictional conflicts
    When analyze_corpus_for_deontic_conflicts() is called
    Then recommendations mentions jurisdictional conflicts

  Scenario: Recommendations mention conditional conflicts
    Given document with conditional conflicts
    When analyze_corpus_for_deontic_conflicts() is called
    Then recommendations mentions conditional conflicts

  Scenario: Recommendations default when no conflicts
    Given document with no conflicts
    When analyze_corpus_for_deontic_conflicts() is called
    Then recommendations contains "No major conflicts detected"

  Scenario: Analysis processes 10 documents
    Given 10 documents with deontic statements
    When analyze_corpus_for_deontic_conflicts() is called
    Then processing_stats.documents_processed is 10

  Scenario: Statements stored in statement_database
    Given document with 2 statements
    When analyze_corpus_for_deontic_conflicts() is called
    Then statement_database contains 2 statements

  Scenario: Conflicts stored in conflict_database
    Given document with 1 conflict
    When analyze_corpus_for_deontic_conflicts() is called
    Then conflict_database contains 1 conflict

  Scenario: Analysis handles document with id key
    Given document with id="doc1"
    When analyze_corpus_for_deontic_conflicts() is called
    Then processing completes successfully

  Scenario: Analysis handles document with content key
    Given document with content="Citizens must pay taxes."
    When analyze_corpus_for_deontic_conflicts() is called
    Then statements are extracted from content

  Scenario: Analysis handles document with text key
    Given document with text="Citizens must pay taxes."
    When analyze_corpus_for_deontic_conflicts() is called
    Then statements are extracted from text

  Scenario: Analysis skips document with no content
    Given document with no content or text key
    When analyze_corpus_for_deontic_conflicts() is called
    Then processing_stats.statements_extracted is 0

  Scenario: Analysis handles extraction errors gracefully
    Given document that causes extraction error
    When analyze_corpus_for_deontic_conflicts() is called
    Then processing_stats.extraction_errors is 1

  Scenario: Analysis logs start message
    When analyze_corpus_for_deontic_conflicts() is called with 5 documents
    Then log contains "Starting deontological analysis of 5 documents"

  Scenario: Analysis logs completion message
    When analyze_corpus_for_deontic_conflicts() is called
    Then log contains "Deontological analysis complete"

  Scenario: Analysis returns error result on exception
    Given analysis will raise exception
    When analyze_corpus_for_deontic_conflicts() is called
    Then result has error key

  Scenario: Error result has analysis_id with "failed_analysis" prefix
    Given analysis will raise exception
    When analyze_corpus_for_deontic_conflicts() is called
    Then result.analysis_id starts with "failed_analysis"

  Scenario: Error result has timestamp
    Given analysis will raise exception
    When analyze_corpus_for_deontic_conflicts() is called
    Then result has timestamp key

  Scenario: Async method can be awaited
    When analyze_corpus_for_deontic_conflicts() is called with await
    Then result is returned

  Scenario: Multiple entities in entity_reports
    Given documents with statements for "citizens" and "employees"
    When analyze_corpus_for_deontic_conflicts() is called
    Then entity_reports has 2 keys
