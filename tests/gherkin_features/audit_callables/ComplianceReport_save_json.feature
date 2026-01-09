Feature: ComplianceReport.save_json()
  Tests the save_json() method of ComplianceReport.
  This callable saves the compliance report to a JSON file.

  Background:
    Given a ComplianceReport instance exists
    And the report has standard=GDPR
    And the report has 5 requirements

  Scenario: Save json creates file at specified path
    When save_json() is called with file_path="/tmp/report.json"
    Then a file exists at "/tmp/report.json"

  Scenario: Save json writes valid JSON
    When save_json() is called with file_path="/tmp/report.json"
    And the file is read
    Then the content is valid JSON

  Scenario: Save json with pretty=True formats JSON with indentation
    When save_json() is called with pretty=True
    When the file is read
    Then the JSON contains indentation

  Scenario: Save json with pretty=True formats JSON with newlines
    When save_json() is called with pretty=True
    When the file is read
    Then the JSON contains newlines

  Scenario: Save json with pretty=False writes compact JSON
    When save_json() is called with pretty=False
    And the file is read
    Then the JSON does not contain extra whitespace

  Scenario: Save json includes report_id field
    When save_json() is called
    When the file is parsed as JSON
    Then the JSON contains "report_id"

  Scenario: Save json includes standard field
    When save_json() is called
    When the file is parsed as JSON
    Then the JSON contains "standard"

  Scenario: Save json includes generated_at field
    When save_json() is called
    When the file is parsed as JSON
    Then the JSON contains "generated_at"

  Scenario: Save json includes requirements field
    When save_json() is called
    When the file is parsed as JSON
    Then the JSON contains "requirements"

  Scenario: Save json includes summary field
    When save_json() is called
    When the file is parsed as JSON
    Then the JSON contains "summary"

  Scenario: Save json includes compliant field
    When save_json() is called
    When the file is parsed as JSON
    Then the JSON contains "compliant"

  Scenario: Save json creates parent directories creates directory
    When save_json() is called with file_path="/tmp/reports/2024/jan/report.json"
    Then the directory "/tmp/reports/2024/jan" exists

  Scenario: Save json creates parent directories creates file
    When save_json() is called with file_path="/tmp/reports/2024/jan/report.json"
    Then the file exists

  Scenario: Save json overwrites existing file
    Given a file exists at "/tmp/report.json"
    When save_json() is called with file_path="/tmp/report.json"
    Then the file is overwritten with new content

  Scenario: Save json uses UTF-8 encoding
    Given the report contains unicode characters
    When save_json() is called
    And the file is read
    Then unicode characters are preserved

  Scenario: Save json converts enums to strings
    Given the report standard is GDPR enum
    When save_json() is called
    And the file is parsed
    Then "standard" value is string "GDPR"

  Scenario: Save json file can be loaded back
    When save_json() is called with file_path="/tmp/report.json"
    And the file is parsed as JSON
    Then a new ComplianceReport can be created from the JSON
