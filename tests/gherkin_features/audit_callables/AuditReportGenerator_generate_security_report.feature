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

  Scenario: Generate security report includes timestamp key
    When generate_security_report() is called
    Then the report contains "timestamp" key

  Scenario: Generate security report timestamp is ISO format
    When generate_security_report() is called
    Then timestamp is ISO format string

  Scenario: Generate security report includes report_id key
    When generate_security_report() is called
    Then the report contains "report_id" key

  Scenario: Generate security report report_id is a UUID
    When generate_security_report() is called
    Then report_id is a UUID string

  Scenario: Generate security report calculates risk scores contains summary
    When generate_security_report() is called
    Then the report contains "summary" key

  Scenario: Generate security report calculates risk scores includes overall_risk_score
    When generate_security_report() is called
    Then summary contains "overall_risk_score"

  Scenario: Generate security report calculates risk scores within valid range
    When generate_security_report() is called
    Then overall_risk_score is between 0.0 and 1.0

  Scenario: Generate security report includes risk assessment key
    When generate_security_report() is called
    Then the report contains "risk_assessment" key

  Scenario: Generate security report risk assessment contains scores dictionary
    When generate_security_report() is called
    Then risk_assessment contains "scores" dictionary

  Scenario: Generate security report scores contains authentication
    When generate_security_report() is called
    Then scores contains "authentication" score

  Scenario: Generate security report scores contains access_control
    When generate_security_report() is called
    Then scores contains "access_control" score

  Scenario: Generate security report scores contains system_integrity
    When generate_security_report() is called
    Then scores contains "system_integrity" score

  Scenario: Generate security report scores contains compliance
    When generate_security_report() is called
    Then scores contains "compliance" score

  Scenario: Generate security report detects anomalies count
    Given pattern_detector finds 3 anomalies
    When generate_security_report() is called
    Then the report summary contains "anomalies_detected" with value 3

  Scenario: Generate security report detects anomalies list
    Given pattern_detector finds 3 anomalies
    When generate_security_report() is called
    Then the report contains "anomalies" list with 3 items

  Scenario: Generate security report includes security events count
    Given metrics show 50 security events
    When generate_security_report() is called
    Then summary "security_events" is 50

  Scenario: Generate security report includes authentication metrics events
    Given metrics show 100 authentication events
    Given metrics show 15 authentication failures
    When generate_security_report() is called
    Then summary "authentication_events" is 100

  Scenario: Generate security report includes authentication metrics failures
    Given metrics show 100 authentication events
    Given metrics show 15 authentication failures
    When generate_security_report() is called
    Then summary "authentication_failures" is 15

  Scenario: Generate security report includes top security events list
    When generate_security_report() is called
    Then the report contains "top_security_events" list

  Scenario: Generate security report top security events limited to 5
    When generate_security_report() is called
    Then the list contains at most 5 events

  Scenario: Generate security report generates recommendations list
    Given risk scores indicate high authentication risk
    When generate_security_report() is called
    Then the report contains "recommendations" list

  Scenario: Generate security report recommendations not empty
    Given risk scores indicate high authentication risk
    When generate_security_report() is called
    Then recommendations is not empty

  Scenario: Generate security report recommendations includes authentication advice
    Given risk scores indicate high authentication risk
    When generate_security_report() is called
    Then recommendations includes authentication security advice

  Scenario: Generate security report includes critical events
    Given metrics show 5 critical events
    When generate_security_report() is called
    Then summary "critical_events" is 5
