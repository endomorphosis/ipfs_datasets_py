Feature: AdaptiveSecurityManager.add_rule()
  Tests the add_rule() method of AdaptiveSecurityManager.
  This callable adds a response rule to the adaptive security manager.

  Background:
    Given an AdaptiveSecurityManager instance is initialized
    And no custom response rules exist

  Scenario: Add rule increases rules count
    Given a ResponseRule instance exists
    When add_rule() is called with the rule
    Then the response_rules list contains 1 custom rule

  Scenario: Add rule appends to response_rules list
    Given a ResponseRule with rule_id="custom-1" exists
    When add_rule() is called
    Then the rule is in response_rules list

  Scenario: Add rule allows multiple rules
    Given 3 ResponseRule instances exist
    When add_rule() is called for each rule
    Then response_rules contains 3 custom rules

  Scenario: Add rule preserves rule configuration
    Given a ResponseRule with alert_type="brute_force" exists
    When add_rule() is called
    Then the rule in list has alert_type="brute_force"

  Scenario: Add rule makes rule available for alert matching
    Given a ResponseRule for alert_type="data_breach" is added
    When a SecurityAlert with type="data_breach" is generated
    Then the rule is matched for the alert

  Scenario: Add rule with duplicate rule_id
    Given a ResponseRule with rule_id="rule-1" is added
    When add_rule() is called with another rule_id="rule-1"
    Then both rules are in response_rules list

  Scenario: Add rule is thread-safe
    Given 10 threads add rules concurrently
    When all threads complete
    Then 10 rules are in response_rules list

  Scenario: Add rule with disabled rule stores in list
    Given a ResponseRule with enabled=False exists
    When add_rule() is called
    Then the rule is in response_rules list

  Scenario: Add rule with disabled rule will not match alerts
    Given a ResponseRule with enabled=False exists
    When add_rule() is called
    Then the rule will not match alerts

  Scenario: Add rule with multiple severity levels
    Given a ResponseRule for severity_levels=["medium", "high", "critical"]
    When add_rule() is called
    Then the rule matches alerts with any of those severities

  Scenario: Add rule with multiple actions
    Given a ResponseRule with 3 actions exists
    When add_rule() is called
    And an alert matches the rule
    Then all 3 actions are executed
