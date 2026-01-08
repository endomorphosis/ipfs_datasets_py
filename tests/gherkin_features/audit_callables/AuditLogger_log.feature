Feature: AuditLogger.log()
  Tests the log() method of AuditLogger.
  This callable logs an audit event with specified level, category, action, and details.

  Background:
    Given an AuditLogger instance is initialized
    And the audit logger is enabled
    And at least one audit handler is attached

  Scenario: Log method creates audit event with required fields
    When log() is called with level=INFO, category=AUTHENTICATION, action="login"
    Then an AuditEvent is created
    And the event has event_id attribute
    And the event has timestamp attribute
    And the event level is INFO
    And the event category is AUTHENTICATION
    And the event action is "login"

  Scenario: Log method returns event ID
    When log() is called with level=INFO, category=DATA_ACCESS, action="read"
    Then a string event_id is returned
    And the event_id is a valid UUID

  Scenario: Log method includes user in event when provided
    When log() is called with level=INFO, category=DATA_ACCESS, action="read", user="alice"
    Then the created event has user="alice"

  Scenario: Log method includes resource_id in event when provided
    When log() is called with level=INFO, category=DATA_ACCESS, action="read", resource_id="file123"
    Then the created event has resource_id="file123"

  Scenario: Log method includes resource_type in event when provided
    When log() is called with level=INFO, category=DATA_ACCESS, action="read", resource_type="dataset"
    Then the created event has resource_type="dataset"

  Scenario: Log method includes status in event when provided
    When log() is called with level=INFO, category=AUTHENTICATION, action="login", status="failure"
    Then the created event has status="failure"

  Scenario: Log method includes details dictionary when provided
    When log() is called with level=INFO, category=DATA_ACCESS, action="read", details={"file_size": 1024}
    Then the created event has details dictionary
    And details contains key "file_size" with value 1024

  Scenario: Log method includes client_ip when provided
    When log() is called with level=INFO, category=AUTHENTICATION, action="login", client_ip="192.168.1.1"
    Then the created event has client_ip="192.168.1.1"

  Scenario: Log method includes session_id when provided
    When log() is called with level=INFO, category=AUTHENTICATION, action="login", session_id="sess123"
    Then the created event has session_id="sess123"

  Scenario: Log method applies thread-local context to event
    Given set_context() was called with user="bob", session_id="sess456"
    When log() is called with level=INFO, category=DATA_ACCESS, action="read"
    Then the created event has user="bob"
    And the created event has session_id="sess456"

  Scenario: Log method dispatches event to all handlers
    Given 3 audit handlers are attached
    When log() is called with level=INFO, category=SYSTEM, action="startup"
    Then all 3 handlers receive the event

  Scenario: Log method notifies event listeners
    Given 2 event listeners are registered
    When log() is called with level=INFO, category=SECURITY, action="breach"
    Then all 2 listeners are called with the event

  Scenario: Log method returns None when logger is disabled
    Given the audit logger is disabled
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then None is returned
    And no event is created

  Scenario: Log method returns None when level is below min_level
    Given the audit logger min_level is WARNING
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then None is returned
    And no event is created

  Scenario: Log method returns None when category is excluded
    Given category OPERATIONAL is in excluded_categories
    When log() is called with level=INFO, category=OPERATIONAL, action="test"
    Then None is returned
    And no event is created

  Scenario: Log method returns None when category not in included_categories
    Given included_categories contains only SECURITY
    When log() is called with level=INFO, category=AUTHENTICATION, action="login"
    Then None is returned
    And no event is created

  Scenario: Log method captures source_module from call stack
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event has source_module attribute
    And source_module is not "audit_logger.py"

  Scenario: Log method captures source_function from call stack
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event has source_function attribute
    And source_function is a non-empty string

  Scenario: Log method handles handler exceptions gracefully
    Given an audit handler that raises Exception
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the method completes without raising Exception
    And the event_id is returned

  Scenario: Log method stores event in events list
    When log() is called with level=INFO, category=AUTHENTICATION, action="login"
    Then the event is appended to the events list

  Scenario: Log method creates event with default status
    When log() is called with level=INFO, category=DATA_ACCESS, action="read"
    Then the created event has status="success"

  Scenario: Log method creates event with default hostname
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event has hostname attribute
    And hostname is a non-empty string

  Scenario: Log method creates event with default process_id
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event has process_id attribute
    And process_id is a positive integer
