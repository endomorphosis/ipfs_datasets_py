Feature: GDPRComplianceReporter initialization
  Tests the initialization of GDPRComplianceReporter.
  This callable creates a compliance reporter with GDPR-specific requirements.

  Scenario: GDPRComplianceReporter initializes with GDPR standard
    When GDPRComplianceReporter() is instantiated
    Then the standard is ComplianceStandard.GDPR

  Scenario: GDPRComplianceReporter adds Article 30 requirement with id
    When GDPRComplianceReporter() is instantiated
    Then a requirement with id="GDPR-Art30" exists

  Scenario: GDPRComplianceReporter adds Article 30 requirement with description
    When GDPRComplianceReporter() is instantiated
    Then the requirement description mentions "Records of processing activities"

  Scenario: GDPRComplianceReporter adds Article 32 requirement with id
    When GDPRComplianceReporter() is instantiated
    Then a requirement with id="GDPR-Art32" exists

  Scenario: GDPRComplianceReporter adds Article 32 requirement with description
    When GDPRComplianceReporter() is instantiated
    Then the requirement description mentions "Security of processing"

  Scenario: GDPRComplianceReporter adds Article 33 requirement with id
    When GDPRComplianceReporter() is instantiated
    Then a requirement with id="GDPR-Art33" exists

  Scenario: GDPRComplianceReporter adds Article 33 requirement with description
    When GDPRComplianceReporter() is instantiated
    Then the requirement description mentions "Notification of personal data breaches"

  Scenario: GDPRComplianceReporter adds Article 15 requirement with id
    When GDPRComplianceReporter() is instantiated
    Then a requirement with id="GDPR-Art15" exists

  Scenario: GDPRComplianceReporter adds Article 15 requirement with description
    When GDPRComplianceReporter() is instantiated
    Then the requirement description mentions "Right of access by the data subject"

  Scenario: GDPRComplianceReporter adds Article 17 requirement with id
    When GDPRComplianceReporter() is instantiated
    Then a requirement with id="GDPR-Art17" exists

  Scenario: GDPRComplianceReporter adds Article 17 requirement with description
    When GDPRComplianceReporter() is instantiated
    Then the requirement description mentions "Right to erasure"

  Scenario: GDPRComplianceReporter configures Article 30 categories includes DATA_ACCESS
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" audit_categories include DATA_ACCESS

  Scenario: GDPRComplianceReporter configures Article 30 categories includes DATA_MODIFICATION
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" audit_categories include DATA_MODIFICATION

  Scenario: GDPRComplianceReporter configures Article 30 actions includes read
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" actions include "read"

  Scenario: GDPRComplianceReporter configures Article 30 actions includes write
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" actions include "write"

  Scenario: GDPRComplianceReporter configures Article 30 actions includes update
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" actions include "update"

  Scenario: GDPRComplianceReporter configures Article 30 actions includes delete
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" actions include "delete"

  Scenario: GDPRComplianceReporter configures Article 30 required fields includes user
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" required_fields include "user"

  Scenario: GDPRComplianceReporter configures Article 30 required fields includes resource_id
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" required_fields include "resource_id"

  Scenario: GDPRComplianceReporter configures Article 30 required fields includes timestamp
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art30" required_fields include "timestamp"

  Scenario: GDPRComplianceReporter sets Article 32 security categories includes SECURITY
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art32" audit_categories include SECURITY

  Scenario: GDPRComplianceReporter sets Article 32 security categories includes AUTHENTICATION
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art32" audit_categories include AUTHENTICATION

  Scenario: GDPRComplianceReporter sets Article 33 breach detection categories
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art33" audit_categories include INTRUSION_DETECTION

  Scenario: GDPRComplianceReporter sets Article 33 breach detection min_level
    When GDPRComplianceReporter() is instantiated
    Then requirement "GDPR-Art33" min_level is WARNING

  Scenario: GDPRComplianceReporter creates 5 requirements
    When GDPRComplianceReporter() is instantiated
    Then the requirements list contains 5 requirements
