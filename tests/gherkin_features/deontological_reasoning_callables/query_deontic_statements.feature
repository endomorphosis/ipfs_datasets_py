Feature: DeontologicalReasoningEngine.query_deontic_statements()
  Tests the query_deontic_statements() method of DeontologicalReasoningEngine.
  This callable queries extracted deontic statements by criteria.

  Background:
    Given a DeontologicalReasoningEngine instance
    And the statement_database contains 10 statements

  Scenario: Query with no filters returns all statements
    When query_deontic_statements() is called with no filters
    Then 10 statements are returned

  Scenario: Query with entity filter for "citizens"
    Given statement_database has 3 statements for "citizens"
    When query_deontic_statements(entity="citizens") is called
    Then 3 statements are returned

  Scenario: Entity filter is case-insensitive
    Given statement_database has 3 statements for "citizens"
    When query_deontic_statements(entity="CITIZENS") is called
    Then 3 statements are returned

  Scenario: Entity filter does partial match
    Given statement_database has 3 statements for "citizens"
    When query_deontic_statements(entity="citi") is called
    Then 3 statements are returned

  Scenario: Query with modality filter OBLIGATION
    Given statement_database has 4 statements with modality OBLIGATION
    When query_deontic_statements(modality=OBLIGATION) is called
    Then 4 statements are returned

  Scenario: Query with modality filter PERMISSION
    Given statement_database has 2 statements with modality PERMISSION
    When query_deontic_statements(modality=PERMISSION) is called
    Then 2 statements are returned

  Scenario: Query with modality filter PROHIBITION
    Given statement_database has 3 statements with modality PROHIBITION
    When query_deontic_statements(modality=PROHIBITION) is called
    Then 3 statements are returned

  Scenario: Query with action_keywords filter for "taxes"
    Given statement_database has 2 statements with action containing "taxes"
    When query_deontic_statements(action_keywords=["taxes"]) is called
    Then 2 statements are returned

  Scenario: Action keywords filter is case-insensitive
    Given statement_database has 2 statements with action containing "taxes"
    When query_deontic_statements(action_keywords=["TAXES"]) is called
    Then 2 statements are returned

  Scenario: Query with multiple action keywords
    Given statement_database has 1 statement with "pay" and 1 with "file"
    When query_deontic_statements(action_keywords=["pay", "file"]) is called
    Then 2 statements are returned

  Scenario: Query with entity and modality filters combined
    Given statement_database has 1 statement for "citizens" with OBLIGATION
    When query_deontic_statements(entity="citizens", modality=OBLIGATION) is called
    Then 1 statement is returned

  Scenario: Query with entity and action_keywords filters combined
    Given statement_database has 1 statement for "citizens" with action "pay taxes"
    When query_deontic_statements(entity="citizens", action_keywords=["taxes"]) is called
    Then 1 statement is returned

  Scenario: Query with all three filters combined
    Given statement_database has 1 matching statement
    When query_deontic_statements(entity="citizens", modality=OBLIGATION, action_keywords=["taxes"]) is called
    Then 1 statement is returned

  Scenario: Query with entity that does not exist returns empty list
    When query_deontic_statements(entity="nonexistent") is called
    Then 0 statements are returned

  Scenario: Query with action_keywords that do not exist returns empty list
    When query_deontic_statements(action_keywords=["nonexistent"]) is called
    Then 0 statements are returned

  Scenario: Query returns list of DeonticStatement instances
    When query_deontic_statements(entity="citizens") is called
    Then each result is DeonticStatement instance

  Scenario: Returned statements have id attribute
    When query_deontic_statements(entity="citizens") is called
    Then each statement has id attribute

  Scenario: Returned statements have entity attribute
    When query_deontic_statements(entity="citizens") is called
    Then each statement entity is "citizens"

  Scenario: Returned statements have action attribute
    When query_deontic_statements(entity="citizens") is called
    Then each statement has action attribute

  Scenario: Returned statements have modality attribute
    When query_deontic_statements(modality=OBLIGATION) is called
    Then each statement modality is OBLIGATION

  Scenario: Returned statements have source_document attribute
    When query_deontic_statements(entity="citizens") is called
    Then each statement has source_document attribute

  Scenario: Returned statements have confidence attribute
    When query_deontic_statements(entity="citizens") is called
    Then each statement has confidence attribute

  Scenario: Query empty database returns empty list
    Given statement_database is empty
    When query_deontic_statements() is called
    Then 0 statements are returned

  Scenario: Query with entity filter on empty database returns empty list
    Given statement_database is empty
    When query_deontic_statements(entity="citizens") is called
    Then 0 statements are returned

  Scenario: Async method can be awaited
    When query_deontic_statements() is called with await
    Then result is returned

  Scenario: Query after analyzing corpus
    Given analyze_corpus_for_deontic_conflicts() was called
    When query_deontic_statements() is called
    Then statements from analysis are returned

  Scenario: Query filters work independently
    Given statement_database has diverse statements
    When query_deontic_statements(entity="citizens") is called
    Then only entity filter is applied

  Scenario: Query with modality CONDITIONAL
    Given statement_database has 2 statements with modality CONDITIONAL
    When query_deontic_statements(modality=CONDITIONAL) is called
    Then 2 statements are returned

  Scenario: Query with modality EXCEPTION
    Given statement_database has 1 statement with modality EXCEPTION
    When query_deontic_statements(modality=EXCEPTION) is called
    Then 1 statement is returned

  Scenario: Query with action keyword matching multiple actions
    Given statement_database has statements with actions "pay taxes" and "file taxes"
    When query_deontic_statements(action_keywords=["taxes"]) is called
    Then 2 statements are returned
