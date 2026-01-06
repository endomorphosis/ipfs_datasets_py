Feature: ConflictDetector.detect_conflicts()
  Tests the detect_conflicts() method of ConflictDetector.
  This callable detects conflicts between deontic statements.

  Background:
    Given a ConflictDetector instance

  Scenario: Detect conflicts with empty statement list returns empty list
    When detect_conflicts() is called with empty list
    Then an empty list is returned

  Scenario: Detect conflicts with single statement returns empty list
    Given 1 statement for "citizens" with modality OBLIGATION
    When detect_conflicts() is called
    Then an empty list is returned

  Scenario: Detect no conflict between different entities
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "employees" must "submit reports"
    When detect_conflicts() is called
    Then 0 conflicts are detected

  Scenario: Detect no conflict between unrelated actions
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must "vote"
    When detect_conflicts() is called
    Then 0 conflicts are detected

  Scenario: Detect OBLIGATION_PROHIBITION conflict
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then 1 conflict is detected

  Scenario: Detected conflict has conflict_type OBLIGATION_PROHIBITION
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict type is OBLIGATION_PROHIBITION

  Scenario: OBLIGATION_PROHIBITION conflict has severity "high"
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict severity is "high"

  Scenario: Conflict has unique id
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict id is "conflict_stmt_1_stmt_2"

  Scenario: Conflict has statement1 and statement2 attributes
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict has statement1 and statement2 attributes

  Scenario: Conflict has explanation text
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict explanation contains "conflicting obligations"

  Scenario: Detect PERMISSION_PROHIBITION conflict
    Given statement 1: "citizens" may "vote"
    And statement 2: "citizens" cannot "vote"
    When detect_conflicts() is called
    Then 1 conflict is detected

  Scenario: PERMISSION_PROHIBITION has conflict_type PERMISSION_PROHIBITION
    Given statement 1: "citizens" may "vote"
    And statement 2: "citizens" cannot "vote"
    When detect_conflicts() is called
    Then the conflict type is PERMISSION_PROHIBITION

  Scenario: PERMISSION_PROHIBITION conflict has severity "high"
    Given statement 1: "citizens" may "vote"
    And statement 2: "citizens" cannot "vote"
    When detect_conflicts() is called
    Then the conflict severity is "high"

  Scenario: PERMISSION_PROHIBITION explanation mentions "permissions"
    Given statement 1: "citizens" may "vote"
    And statement 2: "citizens" cannot "vote"
    When detect_conflicts() is called
    Then the conflict explanation contains "conflicting permissions"

  Scenario: Detect CONDITIONAL_CONFLICT between conditionals
    Given conditional statement 1: if "condition A" then "citizens" must "act"
    And conditional statement 2: if "condition A" then "citizens" must not "act"
    When detect_conflicts() is called
    Then 1 conflict is detected

  Scenario: CONDITIONAL_CONFLICT has conflict_type CONDITIONAL_CONFLICT
    Given conditional statement 1: if "condition A" then "citizens" must "act"
    And conditional statement 2: if "condition A" then "citizens" must not "act"
    When detect_conflicts() is called
    Then the conflict type is CONDITIONAL_CONFLICT

  Scenario: CONDITIONAL_CONFLICT has severity "medium"
    Given conditional statement 1: if "condition A" then "citizens" must "act"
    And conditional statement 2: if "condition A" then "citizens" must not "act"
    When detect_conflicts() is called
    Then the conflict severity is "medium"

  Scenario: Detect JURISDICTIONAL conflict from different sources
    Given statement 1 from "doc1": "citizens" must "pay taxes"
    And statement 2 from "doc2": "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then 1 conflict is detected

  Scenario: JURISDICTIONAL conflict has conflict_type JURISDICTIONAL
    Given statement 1 from "doc1": "citizens" must "pay taxes"
    And statement 2 from "doc2": "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict type is JURISDICTIONAL

  Scenario: JURISDICTIONAL conflict has severity "medium"
    Given statement 1 from "doc1": "citizens" must "pay taxes"
    And statement 2 from "doc2": "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict severity is "medium"

  Scenario: Conflict has resolution_suggestions list
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict has resolution_suggestions list

  Scenario: OBLIGATION_PROHIBITION suggestions include checking exceptions
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then resolution_suggestions contains "Check for exceptions"

  Scenario: JURISDICTIONAL suggestions include determining precedence
    Given statement 1 from "doc1": "citizens" must "pay taxes"
    And statement 2 from "doc2": "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then resolution_suggestions contains "Determine which jurisdiction takes precedence"

  Scenario: Detect multiple conflicts in list
    Given 2 pairs of conflicting statements
    When detect_conflicts() is called
    Then 2 conflicts are detected

  Scenario: Detect 0 conflicts with 3 non-conflicting statements
    Given 3 non-conflicting statements for same entity
    When detect_conflicts() is called
    Then 0 conflicts are detected

  Scenario: Actions are related if they share word "taxes"
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes annually"
    When detect_conflicts() is called
    Then 1 conflict is detected

  Scenario: Actions are not related if no shared words
    Given statement 1: "citizens" must "pay"
    And statement 2: "citizens" must not "vote"
    When detect_conflicts() is called
    Then 0 conflicts are detected

  Scenario: Conflict has metadata dictionary
    Given statement 1: "citizens" must "pay taxes"
    And statement 2: "citizens" must not "pay taxes"
    When detect_conflicts() is called
    Then the conflict has metadata dictionary

  Scenario: Detect 3 conflicts from 4 statements
    Given 4 statements where 3 pairs conflict
    When detect_conflicts() is called
    Then 3 conflicts are detected

  Scenario: No conflict between PERMISSION and OBLIGATION
    Given statement 1: "citizens" may "vote"
    And statement 2: "citizens" must "vote"
    When detect_conflicts() is called
    Then 0 conflicts are detected

  Scenario: Statements grouped by entity for efficiency
    Given 10 statements for 3 different entities
    When detect_conflicts() is called
    Then conflicts are detected only within same entity
