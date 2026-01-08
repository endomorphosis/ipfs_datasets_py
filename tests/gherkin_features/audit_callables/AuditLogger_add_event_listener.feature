Feature: AuditLogger.add_event_listener()
  Tests the add_event_listener() method of AuditLogger.
  This callable adds a listener function for audit events in real-time.

  Background:
    Given an AuditLogger instance is initialized
    And no event listeners are registered

  Scenario: Add event listener for all categories
    Given a listener function exists
    When add_event_listener() is called with listener=listener_func, category=None
    Then the listener is registered for all categories

  Scenario: Add event listener for specific category
    Given a listener function exists
    When add_event_listener() is called with listener=listener_func, category=AUTHENTICATION
    Then the listener is registered for AUTHENTICATION category

  Scenario: Add event listener receives events
    Given a listener function is registered for all categories
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the listener function is called with the event

  Scenario: Add event listener for specific category only receives matching events
    Given a listener function is registered for AUTHENTICATION category
    When log() is called with level=INFO, category=DATA_ACCESS, action="read"
    Then the listener function is not called
    When log() is called with level=INFO, category=AUTHENTICATION, action="login"
    Then the listener function is called

  Scenario: Add multiple event listeners for same category
    Given 3 listener functions exist
    When add_event_listener() is called for each with category=SECURITY
    Then all 3 listeners are registered for SECURITY

  Scenario: Add multiple listeners all receive events
    Given 3 listener functions are registered for all categories
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then all 3 listener functions are called

  Scenario: Add event listener is thread-safe
    Given 10 threads add listeners concurrently
    When all threads complete
    Then 10 listeners are registered

  Scenario: Add event listener handles exceptions gracefully
    Given a listener function that raises Exception
    And the listener is registered
    When log() is called with level=INFO, category=SYSTEM, action="test"
    Then the log() method completes without raising Exception
    And the event is still logged

  Scenario: Add same listener function twice
    Given a listener function exists
    When add_event_listener() is called twice with same listener
    Then the listener is in the list twice
    And the listener is called twice per event

  Scenario: Add listener for multiple categories separately
    Given a listener function exists
    When add_event_listener() is called with category=AUTHENTICATION
    And add_event_listener() is called with category=DATA_ACCESS
    Then the listener receives both AUTHENTICATION and DATA_ACCESS events
