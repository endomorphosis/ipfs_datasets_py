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

  Scenario: To dict event_id value is a string
    When to_dict() is called
    Then "event_id" value is a string

  Scenario: To dict includes timestamp field
    When to_dict() is called
    Then the dictionary contains key "timestamp"

  Scenario: To dict timestamp value is an ISO format string
    When to_dict() is called
    Then "timestamp" value is an ISO format string

  Scenario: To dict includes level field as string
    When to_dict() is called
    Then the dictionary contains key "level"

  Scenario: To dict level value is INFO string
    When to_dict() is called
    Then "level" value is "INFO"

  Scenario: To dict includes category field as string
    When to_dict() is called
    Then the dictionary contains key "category"

  Scenario: To dict category value is DATA_ACCESS string
    When to_dict() is called
    Then "category" value is "DATA_ACCESS"

  Scenario: To dict includes action field
    When to_dict() is called
    Then the dictionary contains key "action"

  Scenario: To dict action value is read string
    When to_dict() is called
    Then "action" value is "read"

  Scenario: To dict includes user field
    When to_dict() is called
    Then the dictionary contains key "user"

  Scenario: To dict user value is alice string
    When to_dict() is called
    Then "user" value is "alice"

  Scenario: To dict includes resource_id when present
    Given the event has resource_id="file123"
    When to_dict() is called
    Then the dictionary contains key "resource_id"

  Scenario: To dict resource_id value is file123 string
    Given the event has resource_id="file123"
    When to_dict() is called
    Then "resource_id" value is "file123"

  Scenario: To dict includes resource_type when present
    Given the event has resource_type="dataset"
    When to_dict() is called
    Then the dictionary contains key "resource_type"

  Scenario: To dict resource_type value is dataset string
    Given the event has resource_type="dataset"
    When to_dict() is called
    Then "resource_type" value is "dataset"

  Scenario: To dict includes status field
    Given the event has status="success"
    When to_dict() is called
    Then the dictionary contains key "status"

  Scenario: To dict status value is success string
    Given the event has status="success"
    When to_dict() is called
    Then "status" value is "success"

  Scenario: To dict includes details dictionary
    Given the event has details={"file_size": 1024}
    When to_dict() is called
    Then the dictionary contains key "details"

  Scenario: To dict details is a dictionary
    Given the event has details={"file_size": 1024}
    When to_dict() is called
    Then "details" is a dictionary

  Scenario: To dict details contains file_size
    Given the event has details={"file_size": 1024}
    When to_dict() is called
    Then "details" contains "file_size" with value 1024

  Scenario: To dict includes client_ip when present
    Given the event has client_ip="192.168.1.1"
    When to_dict() is called
    Then the dictionary contains key "client_ip"

  Scenario: To dict client_ip value is IP address string
    Given the event has client_ip="192.168.1.1"
    When to_dict() is called
    Then "client_ip" value is "192.168.1.1"

  Scenario: To dict includes session_id when present
    Given the event has session_id="sess123"
    When to_dict() is called
    Then the dictionary contains key "session_id"

  Scenario: To dict session_id value is sess123 string
    Given the event has session_id="sess123"
    When to_dict() is called
    Then "session_id" value is "sess123"

  Scenario: To dict includes hostname
    When to_dict() is called
    Then the dictionary contains key "hostname"

  Scenario: To dict hostname value is a non-empty string
    When to_dict() is called
    Then "hostname" value is a non-empty string

  Scenario: To dict includes process_id
    When to_dict() is called
    Then the dictionary contains key "process_id"

  Scenario: To dict process_id value is an integer
    When to_dict() is called
    Then "process_id" value is an integer

  Scenario: To dict converts level enum to string
    When to_dict() is called
    Then the "level" value is string "INFO"

  Scenario: To dict converts category enum to string
    When to_dict() is called
    Then the "category" value is string "DATA_ACCESS"

  Scenario: To dict values are not enum objects
    When to_dict() is called
    Then neither value is an enum object

  Scenario: To dict includes all standard fields
    When to_dict() is called
    Then the dictionary contains at least 15 keys
