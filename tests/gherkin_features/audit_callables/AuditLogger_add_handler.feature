Feature: AuditLogger.add_handler()
  Tests the add_handler() method of AuditLogger.
  This callable adds a handler to the audit logger for processing audit events.

  Background:
    Given an AuditLogger instance is initialized
    And the handlers list is empty

  Scenario: Add handler increases handlers count
    Given a FileAuditHandler instance exists
    When add_handler() is called with the handler
    Then the handlers list contains 1 handler

  Scenario: Add handler appends to handlers list
    Given a FileAuditHandler instance exists
    When add_handler() is called with the handler
    Then the handler is in the handlers list

  Scenario: Add handler allows multiple handlers
    Given 3 different AuditHandler instances exist
    When add_handler() is called for each handler
    Then the handlers list contains 3 handlers

  Scenario: Add handler allows handlers of different types has 2 handlers
    Given a FileAuditHandler exists
    Given a JSONAuditHandler exists
    When add_handler() is called for both handlers
    Then the handlers list contains 2 handlers

  Scenario: Add handler allows handlers of different types includes FileAuditHandler
    Given a FileAuditHandler exists
    Given a JSONAuditHandler exists
    When add_handler() is called for both handlers
    Then one handler is FileAuditHandler type

  Scenario: Add handler allows handlers of different types includes JSONAuditHandler
    Given a FileAuditHandler exists
    Given a JSONAuditHandler exists
    When add_handler() is called for both handlers
    Then one handler is JSONAuditHandler type

  Scenario: Add handler is thread-safe
    Given 10 threads call add_handler() concurrently
    When all threads complete
    Then the handlers list contains 10 handlers

  Scenario: Add handler accepts custom handler subclass
    Given a custom AuditHandler subclass instance exists
    When add_handler() is called with the custom handler
    Then the handler is in the handlers list

  Scenario: Added handler receives subsequent events
    Given a FileAuditHandler is added
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the FileAuditHandler receives the event

  Scenario: Add handler does not affect existing events
    Given log() is called with level=INFO, category=SYSTEM, action="before"
    When add_handler() is called with a FileAuditHandler
    And log() is called with level=INFO, category=SYSTEM, action="after"
    Then the FileAuditHandler receives only the "after" event

  Scenario: Add handler with same name twice adds both handlers
    Given a FileAuditHandler with name="handler1" is added
    When add_handler() is called with another handler named "handler1"
    Then the handlers list contains 2 handlers

  Scenario: Add handler with same name twice both have same name
    Given a FileAuditHandler with name="handler1" is added
    When add_handler() is called with another handler named "handler1"
    Then both handlers have name="handler1"

  Scenario: Add handler preserves handler configuration
    Given a FileAuditHandler with min_level=ERROR exists
    When add_handler() is called with the handler
    Then the handler in list has min_level=ERROR
