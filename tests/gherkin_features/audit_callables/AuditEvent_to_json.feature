Feature: AuditEvent.to_json()
  Tests the to_json() method of AuditEvent.
  This callable serializes an AuditEvent to JSON string.

  Background:
    Given an AuditEvent exists with all fields populated
    And the event has level=INFO
    And the event has category=DATA_ACCESS
    And the event has action="read"
    And the event has user="alice"

  Scenario: To json returns string
    When to_json() is called
    Then a string is returned

  Scenario: To json returns valid JSON
    When to_json() is called
    Then the string can be parsed as JSON

  Scenario: To json includes event_id
    When to_json() is called
    And the JSON is parsed
    Then the parsed object contains "event_id"

  Scenario: To json includes level as string contains level key
    When to_json() is called
    When the JSON is parsed
    Then the parsed object contains "level"

  Scenario: To json includes level as string has INFO value
    When to_json() is called
    When the JSON is parsed
    Then "level" value is "INFO"

  Scenario: To json includes category as string contains category key
    When to_json() is called
    When the JSON is parsed
    Then the parsed object contains "category"

  Scenario: To json includes category as string has DATA_ACCESS value
    When to_json() is called
    When the JSON is parsed
    Then "category" value is "DATA_ACCESS"

  Scenario: To json with pretty=False returns compact JSON without indentation
    When to_json() is called with pretty=False
    Then the string does not contain indentation

  Scenario: To json with pretty=False returns compact JSON without newlines
    When to_json() is called with pretty=False
    Then the string does not contain newlines

  Scenario: To json with pretty=True returns formatted JSON with indentation
    When to_json() is called with pretty=True
    Then the string contains indentation

  Scenario: To json with pretty=True returns formatted JSON with newlines
    When to_json() is called with pretty=True
    Then the string contains newlines

  Scenario: To json includes details as nested object with details key
    Given the event has details={"file_size": 1024, "path": "/data"}
    When to_json() is called
    When the JSON is parsed
    Then the parsed object contains "details"

  Scenario: To json includes details as nested object that is an object
    Given the event has details={"file_size": 1024, "path": "/data"}
    When to_json() is called
    When the JSON is parsed
    Then "details" is an object

  Scenario: To json includes details with file_size
    Given the event has details={"file_size": 1024, "path": "/data"}
    When to_json() is called
    When the JSON is parsed
    Then "details" contains "file_size" with value 1024

  Scenario: To json includes details with path
    Given the event has details={"file_size": 1024, "path": "/data"}
    When to_json() is called
    When the JSON is parsed
    Then "details" contains "path" with value "/data"

  Scenario: To json handles None values without error
    Given the event has resource_id=None
    When to_json() is called
    Then the method completes without error

  Scenario: To json handles None values with valid JSON
    Given the event has resource_id=None
    When to_json() is called
    Then the string is valid JSON

  Scenario: To json includes timestamp in ISO format contains timestamp
    When to_json() is called
    When the JSON is parsed
    Then the parsed object contains "timestamp"

  Scenario: To json includes timestamp in ISO format ends with Z
    When to_json() is called
    When the JSON is parsed
    Then "timestamp" ends with "Z"

  Scenario: To json result can be parsed back
    When to_json() is called
    And the JSON string is parsed
    Then all original event fields are present
