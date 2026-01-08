Feature: AuditEvent.from_dict()
  Tests the from_dict() class method of AuditEvent.
  This callable creates an AuditEvent instance from a dictionary.

  Background:
    Given a dictionary with event data exists
    And the dictionary has "event_id" set to "evt123"
    And the dictionary has "timestamp" set to "2024-01-01T12:00:00Z"
    And the dictionary has "level" set to "INFO"
    And the dictionary has "category" set to "DATA_ACCESS"
    And the dictionary has "action" set to "read"

  Scenario: From dict returns AuditEvent instance
    When from_dict() is called with the dictionary
    Then an AuditEvent instance is returned

  Scenario: From dict sets event_id
    When from_dict() is called
    Then the event event_id is "evt123"

  Scenario: From dict sets timestamp
    When from_dict() is called
    Then the event timestamp is "2024-01-01T12:00:00Z"

  Scenario: From dict converts level string to enum
    When from_dict() is called
    Then the event level is AuditLevel.INFO enum

  Scenario: From dict converts category string to enum
    When from_dict() is called
    Then the event category is AuditCategory.DATA_ACCESS enum

  Scenario: From dict sets action
    When from_dict() is called
    Then the event action is "read"

  Scenario: From dict sets user when present
    Given the dictionary has "user" set to "bob"
    When from_dict() is called
    Then the event user is "bob"

  Scenario: From dict sets resource_id when present
    Given the dictionary has "resource_id" set to "file456"
    When from_dict() is called
    Then the event resource_id is "file456"

  Scenario: From dict sets status when present
    Given the dictionary has "status" set to "failure"
    When from_dict() is called
    Then the event status is "failure"

  Scenario: From dict sets details when present returns dictionary
    Given the dictionary has "details" set to {"size": 2048}
    When from_dict() is called
    Then the event details is a dictionary

  Scenario: From dict sets details when present contains size
    Given the dictionary has "details" set to {"size": 2048}
    When from_dict() is called
    Then details contains "size" with value 2048

  Scenario: From dict handles missing optional fields
    Given the dictionary has only required fields
    When from_dict() is called
    Then an AuditEvent is returned without error

  Scenario: From dict with level already as enum
    Given the dictionary has "level" as AuditLevel.ERROR enum
    When from_dict() is called
    Then the event level is AuditLevel.ERROR

  Scenario: From dict with category already as enum
    Given the dictionary has "category" as AuditCategory.SECURITY enum
    When from_dict() is called
    Then the event category is AuditCategory.SECURITY

  Scenario: From dict preserves all fields
    Given the dictionary has all 20 standard fields populated
    When from_dict() is called
    Then the event has all 20 fields with correct values
