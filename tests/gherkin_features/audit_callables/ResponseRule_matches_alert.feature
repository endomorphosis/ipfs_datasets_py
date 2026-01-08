Feature: ResponseRule.matches_alert()
  Tests the matches_alert() method of ResponseRule.
  This callable checks if a response rule applies to a security alert.

  Background:
    Given a ResponseRule with alert_type="brute_force_login" exists
    And the rule severity_levels are ["medium", "high", "critical"]
    And the rule is enabled

  Scenario: Matches alert returns True when all conditions met
    Given a SecurityAlert with type="brute_force_login", level="high" exists
    When matches_alert() is called with the alert
    Then True is returned

  Scenario: Matches alert returns False when rule disabled
    Given the rule is disabled
    And a matching SecurityAlert exists
    When matches_alert() is called
    Then False is returned

  Scenario: Matches alert returns False when alert type differs
    Given a SecurityAlert with type="data_breach" exists
    When matches_alert() is called
    Then False is returned

  Scenario: Matches alert returns False when severity not in list
    Given a SecurityAlert with level="low" exists
    When matches_alert() is called
    Then False is returned

  Scenario: Matches alert returns True for wildcard alert_type
    Given the rule alert_type is "*"
    And a SecurityAlert with any type exists
    When matches_alert() is called
    Then True is returned

  Scenario: Matches alert checks additional RuleConditions
    Given the rule has condition: field="details.user", operator="==", value="alice"
    And a SecurityAlert with details.user="alice" exists
    When matches_alert() is called
    Then True is returned

  Scenario: Matches alert returns False when condition not met
    Given the rule has condition: field="details.source_ip", operator="==", value="10.0.0.1"
    And a SecurityAlert with details.source_ip="192.168.1.1" exists
    When matches_alert() is called
    Then False is returned

  Scenario: Matches alert with multiple conditions requires all
    Given the rule has 2 RuleConditions
    And the alert matches condition 1
    But the alert does not match condition 2
    When matches_alert() is called
    Then False is returned

  Scenario: Matches alert with multiple severity levels
    Given the rule severity_levels are ["high", "critical"]
    And a SecurityAlert with level="high" exists
    When matches_alert() is called
    Then True is returned

  Scenario: Matches alert evaluates condition operators
    Given a condition with operator=">" exists
    When the alert field value is greater than condition value
    Then the condition evaluates to True

  Scenario: Matches alert handles nested field paths
    Given a condition with field="details.metrics.count"
    And the alert has details.metrics.count=100
    When matches_alert() is called
    Then the condition is evaluated correctly
