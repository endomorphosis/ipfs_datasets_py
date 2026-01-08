Feature: AuditEvent.to_dict()
  Tests the to_dict() method of AuditEvent.
  This callable converts an AuditEvent to a dictionary representation.

  Background:
    Given an AuditEvent exists with all fields populated
    And the event has level=INFO
    And the event has category=DATA_ACCESS
    And the event has action="read"
    And the event has user="alice"

  Scenario: To dict returns dictionary
    When to_dict() is called
    Then a dictionary is returned

  Scenario: To dict includes event_id field
    When to_dict() is called
    Then the dictionary contains key "event_id"
    And "event_id" value is a string

  Scenario: To dict includes timestamp field
    When to_dict() is called
    Then the dictionary contains key "timestamp"
    And "timestamp" value is an ISO format string

  Scenario: To dict includes level field as string
    When to_dict() is called
    Then the dictionary contains key "level"
    And "level" value is "INFO"

  Scenario: To dict includes category field as string
    When to_dict() is called
    Then the dictionary contains key "category"
    And "category" value is "DATA_ACCESS"

  Scenario: To dict includes action field
    When to_dict() is called
    Then the dictionary contains key "action"
    And "action" value is "read"

  Scenario: To dict includes user field
    When to_dict() is called
    Then the dictionary contains key "user"
    And "user" value is "alice"

  Scenario: To dict includes resource_id when present
    Given the event has resource_id="file123"
    When to_dict() is called
    Then the dictionary contains key "resource_id"
    And "resource_id" value is "file123"

  Scenario: To dict includes resource_type when present
    Given the event has resource_type="dataset"
    When to_dict() is called
    Then the dictionary contains key "resource_type"
    And "resource_type" value is "dataset"

  Scenario: To dict includes status field
    Given the event has status="success"
    When to_dict() is called
    Then the dictionary contains key "status"
    And "status" value is "success"

  Scenario: To dict includes details dictionary
    Given the event has details={"file_size": 1024}
    When to_dict() is called
    Then the dictionary contains key "details"
    And "details" is a dictionary
    And "details" contains "file_size" with value 1024

  Scenario: To dict includes client_ip when present
    Given the event has client_ip="192.168.1.1"
    When to_dict() is called
    Then the dictionary contains key "client_ip"
    And "client_ip" value is "192.168.1.1"

  Scenario: To dict includes session_id when present
    Given the event has session_id="sess123"
    When to_dict() is called
    Then the dictionary contains key "session_id"
    And "session_id" value is "sess123"

  Scenario: To dict includes hostname
    When to_dict() is called
    Then the dictionary contains key "hostname"
    And "hostname" value is a non-empty string

  Scenario: To dict includes process_id
    When to_dict() is called
    Then the dictionary contains key "process_id"
    And "process_id" value is an integer

  Scenario: To dict converts enums to strings
    When to_dict() is called
    Then the "level" value is string "INFO"
    And the "category" value is string "DATA_ACCESS"
    And neither value is an enum object

  Scenario: To dict includes all standard fields
    When to_dict() is called
    Then the dictionary contains at least 15 keys
