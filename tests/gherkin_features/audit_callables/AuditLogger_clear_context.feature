Feature: AuditLogger.clear_context()
  Tests the clear_context() method of AuditLogger.
  This callable clears the thread-local context for audit events.

  Background:
    Given an AuditLogger instance is initialized
    And set_context() was called with user="alice", session_id="sess123"

  Scenario: Clear context removes all context values
    When clear_context() is called
    Then the thread-local context does not exist

  Scenario: Clear context affects subsequent log calls
    When clear_context() is called
    And log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event does not have user from context

  Scenario: Clear context is thread-local clears thread 1
    Given set_context() is called with user="user1" in thread 1
    Given set_context() is called with user="user2" in thread 2
    When clear_context() is called in thread 1
    Then thread 1 context does not exist

  Scenario: Clear context is thread-local preserves thread 2
    Given set_context() is called with user="user1" in thread 1
    Given set_context() is called with user="user2" in thread 2
    When clear_context() is called in thread 1
    Then thread 2 context still has user="user2"

  Scenario: Clear context when no context exists
    Given the thread-local context does not exist
    When clear_context() is called
    Then the method completes without error

  Scenario: Clear context does not affect global defaults
    Given default_user is set to "default_user"
    And set_context() was called with user="custom_user"
    When clear_context() is called
    And log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event has user="default_user"

  Scenario: Set context after clear creates new context with user
    Given set_context() was called with user="bob"
    When clear_context() is called
    When set_context() is called with user="charlie"
    Then the thread-local context contains user="charlie"

  Scenario: Set context after clear removes previous values
    Given set_context() was called with user="bob"
    When clear_context() is called
    When set_context() is called with user="charlie"
    Then the thread-local context does not contain previous values
