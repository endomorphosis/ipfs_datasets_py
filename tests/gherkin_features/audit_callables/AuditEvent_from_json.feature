Feature: AuditEvent.from_json()
  Tests the from_json() class method of AuditEvent.
  This callable creates an AuditEvent instance from a JSON string.

  Background:
    Given a JSON string with event data exists
    And the JSON contains "event_id": "evt789"
    And the JSON contains "level": "WARNING"
    And the JSON contains "category": "SECURITY"
    And the JSON contains "action": "breach"

  Scenario: From json returns AuditEvent instance
    When from_json() is called with the JSON string
    Then an AuditEvent instance is returned

  Scenario: From json parses event_id
    When from_json() is called
    Then the event event_id is "evt789"

  Scenario: From json parses level
    When from_json() is called
    Then the event level is AuditLevel.WARNING

  Scenario: From json parses category
    When from_json() is called
    Then the event category is AuditCategory.SECURITY

  Scenario: From json parses action
    When from_json() is called
    Then the event action is "breach"

  Scenario: From json handles nested details
    Given the JSON contains "details": {"ip": "10.0.0.1", "count": 5}
    When from_json() is called
    Then the event details is a dictionary
    And details contains "ip" with value "10.0.0.1"
    And details contains "count" with value 5

  Scenario: From json handles null values
    Given the JSON contains "user": null
    When from_json() is called
    Then the event user is None

  Scenario: From json raises error on invalid JSON
    Given an invalid JSON string exists
    When from_json() is called with invalid string
    Then JSONDecodeError is raised

  Scenario: From json with pretty formatted JSON
    Given a JSON string with indentation and newlines
    When from_json() is called
    Then an AuditEvent is returned without error
    And the event has all expected fields

  Scenario: From json with compact JSON
    Given a JSON string without whitespace
    When from_json() is called
    Then an AuditEvent is returned without error

  Scenario: From json roundtrip preserves data
    Given an original AuditEvent exists
    When to_json() is called on the original
    And from_json() is called on the JSON string
    Then the new event matches the original event
