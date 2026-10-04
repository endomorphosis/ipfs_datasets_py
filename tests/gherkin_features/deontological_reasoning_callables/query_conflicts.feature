Feature: DeontologicalReasoningEngine.query_conflicts()
  Tests the query_conflicts() method of DeontologicalReasoningEngine.
  This callable queries detected conflicts by criteria.

  Background:
    Given a DeontologicalReasoningEngine instance
    And the conflict_database contains 10 conflicts

  Scenario: Query with no filters returns all conflicts
    When query_conflicts() is called with no filters
    Then 10 conflicts are returned

  Scenario: Query with entity filter for "citizens"
    Given conflict_database has 3 conflicts for "citizens"
    When query_conflicts(entity="citizens") is called
    Then 3 conflicts are returned

  Scenario: Entity filter is case-insensitive
    Given conflict_database has 3 conflicts for "citizens"
    When query_conflicts(entity="CITIZENS") is called
    Then 3 conflicts are returned

  Scenario: Entity filter does partial match
    Given conflict_database has 3 conflicts for "citizens"
    When query_conflicts(entity="citi") is called
    Then 3 conflicts are returned

  Scenario: Query with conflict_type filter OBLIGATION_PROHIBITION
    Given conflict_database has 2 conflicts with type OBLIGATION_PROHIBITION
    When query_conflicts(conflict_type=OBLIGATION_PROHIBITION) is called
    Then 2 conflicts are returned

  Scenario: Query with conflict_type filter PERMISSION_PROHIBITION
    Given conflict_database has 3 conflicts with type PERMISSION_PROHIBITION
    When query_conflicts(conflict_type=PERMISSION_PROHIBITION) is called
    Then 3 conflicts are returned

  Scenario: Query with conflict_type filter CONDITIONAL_CONFLICT
    Given conflict_database has 1 conflict with type CONDITIONAL_CONFLICT
    When query_conflicts(conflict_type=CONDITIONAL_CONFLICT) is called
    Then 1 conflict is returned

  Scenario: Query with conflict_type filter JURISDICTIONAL
    Given conflict_database has 4 conflicts with type JURISDICTIONAL
    When query_conflicts(conflict_type=JURISDICTIONAL) is called
    Then 4 conflicts are returned

  Scenario: Query with min_severity filter "high"
    Given conflict_database has 5 conflicts with severity "high"
    When query_conflicts(min_severity="high") is called
    Then 5 conflicts are returned

  Scenario: Query with min_severity filter "medium" includes high
    Given conflict_database has 3 "high" and 4 "medium" severity conflicts
    When query_conflicts(min_severity="medium") is called
    Then 7 conflicts are returned

  Scenario: Query with min_severity filter "low" returns all
    Given conflict_database has conflicts at all severity levels
    When query_conflicts(min_severity="low") is called
    Then 10 conflicts are returned

  Scenario: Min severity "high" excludes medium and low
    Given conflict_database has 2 "high", 3 "medium", and 5 "low" conflicts
    When query_conflicts(min_severity="high") is called
    Then 2 conflicts are returned

  Scenario: Query with entity and conflict_type combined
    Given conflict_database has 1 JURISDICTIONAL conflict for "citizens"
    When query_conflicts(entity="citizens", conflict_type=JURISDICTIONAL) is called
    Then 1 conflict is returned

  Scenario: Query with entity and min_severity combined
    Given conflict_database has 2 "high" conflicts for "citizens"
    When query_conflicts(entity="citizens", min_severity="high") is called
    Then 2 conflicts are returned

  Scenario: Query with conflict_type and min_severity combined
    Given conflict_database has 1 "high" OBLIGATION_PROHIBITION conflict
    When query_conflicts(conflict_type=OBLIGATION_PROHIBITION, min_severity="high") is called
    Then 1 conflict is returned

  Scenario: Query with all three filters combined
    Given conflict_database has 1 matching conflict
    When query_conflicts(entity="citizens", conflict_type=JURISDICTIONAL, min_severity="high") is called
    Then 1 conflict is returned

  Scenario: Query with entity that does not exist returns empty list
    When query_conflicts(entity="nonexistent") is called
    Then 0 conflicts are returned

  Scenario: Query returns list of DeonticConflict instances
    When query_conflicts(entity="citizens") is called
    Then each result is DeonticConflict instance

  Scenario: Returned conflicts have id attribute
    When query_conflicts(entity="citizens") is called
    Then each conflict has id attribute

  Scenario: Returned conflicts have conflict_type attribute
    When query_conflicts(conflict_type=JURISDICTIONAL) is called
    Then each conflict conflict_type is JURISDICTIONAL

  Scenario: Returned conflicts have statement1 attribute
    When query_conflicts(entity="citizens") is called
    Then each conflict has statement1 attribute

  Scenario: Returned conflicts have statement2 attribute
    When query_conflicts(entity="citizens") is called
    Then each conflict has statement2 attribute

  Scenario: Returned conflicts have severity attribute
    When query_conflicts(min_severity="high") is called
    Then each conflict severity is "high"

  Scenario: Returned conflicts have explanation attribute
    When query_conflicts(entity="citizens") is called
    Then each conflict has explanation attribute

  Scenario: Returned conflicts have resolution_suggestions list
    When query_conflicts(entity="citizens") is called
    Then each conflict has resolution_suggestions list

  Scenario: Query empty database returns empty list
    Given conflict_database is empty
    When query_conflicts() is called
    Then 0 conflicts are returned

  Scenario: Query with entity filter on empty database returns empty list
    Given conflict_database is empty
    When query_conflicts(entity="citizens") is called
    Then 0 conflicts are returned

  Scenario: Async method can be awaited
    When query_conflicts() is called with await
    Then result is returned

  Scenario: Query after analyzing corpus
    Given analyze_corpus_for_deontic_conflicts() was called
    When query_conflicts() is called
    Then conflicts from analysis are returned

  Scenario: Query filters work independently
    Given conflict_database has diverse conflicts
    When query_conflicts(entity="citizens") is called
    Then only entity filter is applied

  Scenario: Entity filter matches statement1 entity
    Given conflict where statement1.entity is "citizens"
    When query_conflicts(entity="citizens") is called
    Then 1 conflict is returned

  Scenario: Min severity filter compares levels correctly
    Given conflict_database has 1 "low" conflict
    When query_conflicts(min_severity="high") is called
    Then 0 conflicts are returned

  Scenario: Query with conflict_type TEMPORAL
    Given conflict_database has 2 conflicts with type TEMPORAL
    When query_conflicts(conflict_type=TEMPORAL) is called
    Then 2 conflicts are returned

  Scenario: Query with conflict_type HIERARCHICAL
    Given conflict_database has 1 conflict with type HIERARCHICAL
    When query_conflicts(conflict_type=HIERARCHICAL) is called
    Then 1 conflict is returned

  Scenario: Query with invalid min_severity returns all conflicts
    When query_conflicts(min_severity="invalid") is called
    Then 10 conflicts are returned

  Scenario: Query handles None values gracefully
    When query_conflicts(entity=None, conflict_type=None, min_severity=None) is called
    Then 10 conflicts are returned

  Scenario: Multiple filters narrow results progressively
    Given conflict_database has 10 diverse conflicts
    When query_conflicts(entity="citizens", min_severity="high") is called
    Then results match both entity and severity filters
