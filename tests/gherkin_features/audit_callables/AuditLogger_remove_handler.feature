Feature: AuditLogger.remove_handler()
  Tests the remove_handler() method of AuditLogger.
  This callable removes a handler from the audit logger by name.

  Background:
    Given an AuditLogger instance is initialized
    And a FileAuditHandler with name="file_handler" is added
    And a JSONAuditHandler with name="json_handler" is added

  Scenario: Remove handler decreases handlers count
    When remove_handler() is called with name="file_handler"
    Then the handlers list contains 1 handler

  Scenario: Remove handler removes correct handler
    When remove_handler() is called with name="file_handler"
    Then the handlers list does not contain FileAuditHandler
    And the handlers list contains JSONAuditHandler

  Scenario: Remove handler returns True when handler found
    When remove_handler() is called with name="file_handler"
    Then True is returned

  Scenario: Remove handler returns False when handler not found
    When remove_handler() is called with name="nonexistent"
    Then False is returned

  Scenario: Remove handler calls handler close method
    Given the FileAuditHandler has close() method
    When remove_handler() is called with name="file_handler"
    Then the handler close() method is called

  Scenario: Remove handler is thread-safe removes all handlers
    Given 5 handlers with names "h1" to "h5" are added
    When 5 threads call remove_handler() for each handler concurrently
    Then all handlers are removed

  Scenario: Remove handler is thread-safe leaves empty list
    Given 5 handlers with names "h1" to "h5" are added
    When 5 threads call remove_handler() for each handler concurrently
    Then the handlers list is empty

  Scenario: Remove handler handles exceptions from close method completes without error
    Given a handler with name="error_handler" that raises Exception in close()
    When remove_handler() is called with name="error_handler"
    Then the method completes without raising Exception

  Scenario: Remove handler handles exceptions from close method returns True
    Given a handler with name="error_handler" that raises Exception in close()
    When remove_handler() is called with name="error_handler"
    Then True is returned

  Scenario: Remove handler from empty list
    Given the handlers list is empty
    When remove_handler() is called with name="any_handler"
    Then False is returned

  Scenario: Remove handler twice with same name
    When remove_handler() is called with name="file_handler"
    And remove_handler() is called with name="file_handler" again
    Then the second call returns False

  Scenario: Remove handler preserves other handlers has 2 handlers
    Given 3 handlers are added
    When remove_handler() is called with name of second handler
    Then the handlers list contains 2 handlers

  Scenario: Remove handler preserves other handlers keeps first handler
    Given 3 handlers are added
    When remove_handler() is called with name of second handler
    Then first handler is still present

  Scenario: Remove handler preserves other handlers keeps third handler
    Given 3 handlers are added
    When remove_handler() is called with name of second handler
    Then third handler is still present

  Scenario: Removed handler no longer receives events FileAuditHandler excluded
    When remove_handler() is called with name="file_handler"
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the FileAuditHandler does not receive the event

  Scenario: Removed handler no longer receives events JSONAuditHandler still active
    When remove_handler() is called with name="file_handler"
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the JSONAuditHandler receives the event
