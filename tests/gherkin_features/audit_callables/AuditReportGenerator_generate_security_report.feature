Feature: AuditReportGenerator.generate_security_report()
  Tests the generate_security_report() method of AuditReportGenerator.
  This callable generates a security-focused audit report.

  Background:
    Given an AuditReportGenerator instance is initialized
    And metrics_aggregator has audit data
    And pattern_detector is configured

  Scenario: Generate security report returns dictionary
    When generate_security_report() is called
    Then a dictionary is returned

  Scenario: Generate security report sets report_type
    When generate_security_report() is called
    Then the report report_type is "security"

  Scenario: Generate security report includes timestamp
    When generate_security_report() is called
    Then the report contains "timestamp" key
    And timestamp is ISO format string

  Scenario: Generate security report includes report_id
    When generate_security_report() is called
    Then the report contains "report_id" key
    And report_id is a UUID string

  Scenario: Generate security report calculates risk scores
    When generate_security_report() is called
    Then the report contains "summary" key
    And summary contains "overall_risk_score"
    And overall_risk_score is between 0.0 and 1.0

  Scenario: Generate security report includes risk assessment
    When generate_security_report() is called
    Then the report contains "risk_assessment" key
    And risk_assessment contains "scores" dictionary
    And scores contains "authentication" score
    And scores contains "access_control" score
    And scores contains "system_integrity" score
    And scores contains "compliance" score

  Scenario: Generate security report detects anomalies
    Given pattern_detector finds 3 anomalies
    When generate_security_report() is called
    Then the report summary contains "anomalies_detected" with value 3
    And the report contains "anomalies" list with 3 items

  Scenario: Generate security report includes security events count
    Given metrics show 50 security events
    When generate_security_report() is called
    Then summary "security_events" is 50

  Scenario: Generate security report includes authentication metrics
    Given metrics show 100 authentication events
    And metrics show 15 authentication failures
    When generate_security_report() is called
    Then summary "authentication_events" is 100
    And summary "authentication_failures" is 15

  Scenario: Generate security report includes top security events
    When generate_security_report() is called
    Then the report contains "top_security_events" list
    And the list contains at most 5 events

  Scenario: Generate security report generates recommendations
    Given risk scores indicate high authentication risk
    When generate_security_report() is called
    Then the report contains "recommendations" list
    And recommendations is not empty
    And recommendations includes authentication security advice

  Scenario: Generate security report includes critical events
    Given metrics show 5 critical events
    When generate_security_report() is called
    Then summary "critical_events" is 5
