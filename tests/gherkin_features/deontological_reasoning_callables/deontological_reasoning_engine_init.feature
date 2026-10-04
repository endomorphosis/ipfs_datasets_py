Feature: DeontologicalReasoningEngine.__init__()
  Tests the __init__() method of DeontologicalReasoningEngine.
  This callable initializes the deontological reasoning engine.

  Scenario: Initialize creates DeontologicalReasoningEngine instance
    When DeontologicalReasoningEngine() is called
    Then a DeontologicalReasoningEngine instance is returned

  Scenario: Initialize with no dashboard parameter
    When DeontologicalReasoningEngine() is called
    Then a DeontologicalReasoningEngine instance is returned

  Scenario: Initialize with mcp_dashboard parameter
    Given an mcp_dashboard instance
    When DeontologicalReasoningEngine(mcp_dashboard) is called
    Then a DeontologicalReasoningEngine instance is returned

  Scenario: Initialize sets dashboard attribute
    Given an mcp_dashboard instance
    When DeontologicalReasoningEngine(mcp_dashboard) is called
    Then the dashboard attribute is set

  Scenario: Initialize sets dashboard to None when not provided
    When DeontologicalReasoningEngine() is called
    Then the dashboard attribute is None

  Scenario: Initialize sets extractor attribute
    When DeontologicalReasoningEngine() is called
    Then the extractor attribute is set

  Scenario: Extractor is DeonticExtractor instance
    When DeontologicalReasoningEngine() is called
    Then the extractor attribute is DeonticExtractor instance

  Scenario: Initialize sets conflict_detector attribute
    When DeontologicalReasoningEngine() is called
    Then the conflict_detector attribute is set

  Scenario: Conflict detector is ConflictDetector instance
    When DeontologicalReasoningEngine() is called
    Then the conflict_detector attribute is ConflictDetector instance

  Scenario: Initialize sets statement_database to empty dict
    When DeontologicalReasoningEngine() is called
    Then the statement_database attribute is empty dictionary

  Scenario: Initialize sets conflict_database to empty dict
    When DeontologicalReasoningEngine() is called
    Then the conflict_database attribute is empty dictionary

  Scenario: Statement database stores statements after analysis
    Given a DeontologicalReasoningEngine instance
    When analyze_corpus_for_deontic_conflicts() is called with 1 document
    Then the statement_database contains statements

  Scenario: Conflict database stores conflicts after analysis
    Given a DeontologicalReasoningEngine instance
    When analyze_corpus_for_deontic_conflicts() is called with conflicting statements
    Then the conflict_database contains conflicts

  Scenario: Statements are indexed by id in database
    Given a DeontologicalReasoningEngine instance
    When analyze_corpus_for_deontic_conflicts() is called
    Then each statement in statement_database is indexed by id

  Scenario: Conflicts are indexed by id in database
    Given a DeontologicalReasoningEngine instance
    When analyze_corpus_for_deontic_conflicts() is called with conflicting statements
    Then each conflict in conflict_database is indexed by id
