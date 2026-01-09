Feature: AuditLogger.remove_event_listener()
  Tests the remove_event_listener() method of AuditLogger.
  This callable removes a listener function from audit event notifications.

  Background:
    Given an AuditLogger instance is initialized
    And a listener function is registered for all categories

  Scenario: Remove event listener returns True when found
    When remove_event_listener() is called with listener=listener_func, category=None
    Then True is returned

  Scenario: Remove event listener returns False when not found
    Given a different listener function exists
    When remove_event_listener() is called with the different listener
    Then False is returned

  Scenario: Remove event listener stops receiving events
    When remove_event_listener() is called with listener=listener_func, category=None
    And log() is called with level=INFO, category=SYSTEM, action="test"
    Then the listener function is not called

  Scenario: Remove event listener for specific category stops AUTHENTICATION events
    Given a listener is registered for AUTHENTICATION
    Given the same listener is registered for DATA_ACCESS
    When remove_event_listener() is called with category=AUTHENTICATION
    Then the listener no longer receives AUTHENTICATION events

  Scenario: Remove event listener for specific category preserves DATA_ACCESS events
    Given a listener is registered for AUTHENTICATION
    Given the same listener is registered for DATA_ACCESS
    When remove_event_listener() is called with category=AUTHENTICATION
    Then the listener still receives DATA_ACCESS events

  Scenario: Remove event listener is thread-safe
    Given 10 listeners are registered
    When 10 threads call remove_event_listener() concurrently
    Then all listeners are removed

  Scenario: Remove event listener when category list empty
    Given the SECURITY category has no listeners
    When remove_event_listener() is called with category=SECURITY
    Then False is returned

  Scenario: Remove same listener twice
    When remove_event_listener() is called with listener=listener_func
    And remove_event_listener() is called again with same listener
    Then the second call returns False

  Scenario: Remove event listener preserves other listeners keeps listener 1
    Given 3 listeners are registered
    When remove_event_listener() is called for listener 2
    Then listener 1 still receives events

  Scenario: Remove event listener preserves other listeners keeps listener 3
    Given 3 listeners are registered
    When remove_event_listener() is called for listener 2
    Then listener 3 still receives events
