Feature: AuditHandler.handle()
  Tests the handle() method of AuditHandler.
  This callable processes an audit event through the handler.

  Background:
    Given an AuditHandler subclass instance exists
    And the handler is enabled
    And the handler min_level is INFO

  Scenario: Handle method returns True when event processed
    Given an AuditEvent with level=INFO exists
    When handle() is called with the event
    Then True is returned

  Scenario: Handle method returns False when handler disabled
    Given the handler is disabled
    And an AuditEvent with level=INFO exists
    When handle() is called
    Then False is returned

  Scenario: Handle method returns False when event level below min_level
    Given the handler min_level is ERROR
    And an AuditEvent with level=WARNING exists
    When handle() is called
    Then False is returned

  Scenario: Handle method calls _handle_event when conditions met
    Given an AuditEvent with level=ERROR exists
    And the handler min_level is INFO
    When handle() is called
    Then _handle_event() is called with the event

  Scenario: Handle method does not call _handle_event when handler disabled
    Given the handler is disabled
    And an AuditEvent with level=INFO exists
    When handle() is called
    Then _handle_event() is not called

  Scenario: Handle method does not call _handle_event when level too low
    Given the handler min_level is CRITICAL
    And an AuditEvent with level=ERROR exists
    When handle() is called
    Then _handle_event() is not called

  Scenario: Handle method passes event unchanged to _handle_event
    Given an AuditEvent with specific fields exists
    When handle() is called
    Then _handle_event() receives the same event object

  Scenario: Handle method accepts event with any level
    Given events exist with all 7 severity levels
    When handle() is called for each event
    Then each call completes without error

  Scenario: Handle method returns value from _handle_event
    Given _handle_event() returns True
    When handle() is called
    Then True is returned from handle()
    
  Scenario: Handle method with event at exact min_level calls handler
    Given the handler min_level is WARNING
    Given an AuditEvent with level=WARNING exists
    When handle() is called
    Then _handle_event() is called

  Scenario: Handle method with event at exact min_level returns True
    Given the handler min_level is WARNING
    Given an AuditEvent with level=WARNING exists
    When handle() is called
    Then True is returned

  Scenario: Handle method with event above min_level calls handler
    Given the handler min_level is INFO
    Given an AuditEvent with level=CRITICAL exists
    When handle() is called
    Then _handle_event() is called

  Scenario: Handle method with event above min_level returns True
    Given the handler min_level is INFO
    Given an AuditEvent with level=CRITICAL exists
    When handle() is called
    Then True is returned
