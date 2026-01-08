Feature: ComplianceReporter.generate_report()
  Tests the generate_report() method of ComplianceReporter.
  This callable generates a compliance report from audit events for a specific standard.

  Background:
    Given a ComplianceReporter for GDPR standard is initialized
    And 5 compliance requirements are configured
    And 100 audit events exist in the system

  Scenario: Generate report returns ComplianceReport instance
    When generate_report() is called with events
    Then a ComplianceReport instance is returned

  Scenario: Generate report sets report_id
    When generate_report() is called
    Then the report has a unique report_id
    And report_id format is "{standard}-{timestamp}"

  Scenario: Generate report sets standard
    When generate_report() is called
    Then the report standard is GDPR

  Scenario: Generate report sets time period from parameters
    When generate_report() is called with start_time="2024-01-01T00:00:00Z", end_time="2024-01-31T23:59:59Z"
    Then the report time_period start is "2024-01-01T00:00:00Z"
    And the report time_period end is "2024-01-31T23:59:59Z"

  Scenario: Generate report uses default 30 day period when not specified
    When generate_report() is called without time parameters
    Then the report time_period spans 30 days

  Scenario: Generate report filters events by time period
    Given events exist from 2024-01-01 to 2024-03-01
    When generate_report() is called with start_time="2024-02-01T00:00:00Z", end_time="2024-02-29T23:59:59Z"
    Then only February events are evaluated

  Scenario: Generate report checks all requirements
    Given 5 requirements are configured
    When generate_report() is called
    Then the report contains 5 requirement results

  Scenario: Generate report marks requirement as Compliant when met
    Given requirement "GDPR-Art30" has 50 matching events
    When generate_report() is called
    Then requirement "GDPR-Art30" status is "Compliant"

  Scenario: Generate report marks requirement as Non-Compliant when not met
    Given requirement "GDPR-Art33" has 0 matching events
    When generate_report() is called
    Then requirement "GDPR-Art33" status is "Non-Compliant"

  Scenario: Generate report includes evidence count for each requirement
    Given requirement "GDPR-Art30" has 25 matching events
    When generate_report() is called
    Then requirement "GDPR-Art30" evidence_count is 25

  Scenario: Generate report calculates compliance summary
    Given 3 requirements are Compliant
    And 2 requirements are Non-Compliant
    When generate_report() is called
    Then summary compliant_count is 3
    And summary non_compliant_count is 2
    And summary total_requirements is 5

  Scenario: Generate report calculates compliance_rate percentage
    Given 4 out of 5 requirements are Compliant
    When generate_report() is called
    Then summary compliance_rate is 80.0

  Scenario: Generate report sets compliant to False when any requirement fails
    Given 4 requirements are Compliant
    And 1 requirement is Non-Compliant
    When generate_report() is called
    Then report compliant is False

  Scenario: Generate report sets compliant to True when all requirements pass
    Given all 5 requirements are Compliant
    When generate_report() is called
    Then report compliant is True

  Scenario: Generate report generates remediation suggestions for failures
    Given 2 requirements are Non-Compliant
    When generate_report() is called
    Then remediation_suggestions contains 2 entries
    And each entry has a list of suggestions

  Scenario: Generate report uses custom verification function when provided
    Given requirement "CUSTOM-1" has a verification_function
    When generate_report() is called
    Then the verification_function is called for "CUSTOM-1"

  Scenario: Generate report handles verification function errors
    Given requirement "ERROR-1" verification_function raises Exception
    When generate_report() is called
    Then the requirement status is "Non-Compliant"
    And the report generation completes without error

  Scenario: Generate report with empty events list
    Given the events list is empty
    When generate_report() is called
    Then all requirements are marked "Non-Compliant"

  Scenario: Generate report sets generated_at timestamp
    When generate_report() is called
    Then the report generated_at is an ISO format timestamp
    And generated_at is close to current time
