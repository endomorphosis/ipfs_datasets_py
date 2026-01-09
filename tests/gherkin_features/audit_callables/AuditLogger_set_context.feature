Feature: AuditLogger.set_context()
  Tests the set_context() method of AuditLogger.
  This callable sets thread-local context that is included in future audit events.

  Background:
    Given an AuditLogger instance is initialized
    And the thread-local context is empty

  Scenario: Set context with user parameter
    When set_context() is called with user="alice"
    Then the thread-local context contains user="alice"

  Scenario: Set context with session_id parameter
    When set_context() is called with session_id="sess123"
    Then the thread-local context contains session_id="sess123"

  Scenario: Set context with client_ip parameter
    When set_context() is called with client_ip="192.168.1.1"
    Then the thread-local context contains client_ip="192.168.1.1"

  Scenario: Set context with application parameter
    When set_context() is called with application="web_app"
    Then the thread-local context contains application="web_app"

  Scenario: Set context with multiple parameters includes user
    When set_context() is called with user="bob", session_id="sess456", client_ip="10.0.0.1"
    Then the thread-local context contains user="bob"

  Scenario: Set context with multiple parameters includes session_id
    When set_context() is called with user="bob", session_id="sess456", client_ip="10.0.0.1"
    Then the thread-local context contains session_id="sess456"

  Scenario: Set context with multiple parameters includes client_ip
    When set_context() is called with user="bob", session_id="sess456", client_ip="10.0.0.1"
    Then the thread-local context contains client_ip="10.0.0.1"

  Scenario: Set context applies to subsequent log calls
    When set_context() is called with user="charlie"
    And log() is called with level=INFO, category=SYSTEM, action="test"
    Then the created event has user="charlie"

  Scenario: Set context does not affect previous events
    Given log() is called with level=INFO, category=SYSTEM, action="before"
    When set_context() is called with user="dave"
    Then the previous event does not have user="dave"

  Scenario: Set context overwrites previous user value
    Given set_context() was called with user="eve"
    When set_context() is called with user="frank"
    Then the thread-local context contains user="frank"

  Scenario: Set context removes previous user value when overwritten
    Given set_context() was called with user="eve"
    When set_context() is called with user="frank"
    Then the thread-local context does not contain user="eve"

  Scenario: Set context is thread-local in thread 1
    Given set_context() is called with user="user1" in thread 1
    When set_context() is called with user="user2" in thread 2
    Then thread 1 context has user="user1"

  Scenario: Set context is thread-local in thread 2
    Given set_context() is called with user="user1" in thread 1
    When set_context() is called with user="user2" in thread 2
    Then thread 2 context has user="user2"

  Scenario: Set context with None values does not update
    Given set_context() was called with user="grace"
    When set_context() is called with user=None
    Then the thread-local context still contains user="grace"

  Scenario: Set context updates only provided parameters preserves user
    Given set_context() was called with user="henry", session_id="sess789"
    When set_context() is called with user="irene"
    Then the thread-local context contains user="irene"

  Scenario: Set context updates only provided parameters preserves session_id
    Given set_context() was called with user="henry", session_id="sess789"
    When set_context() is called with user="irene"
    Then the thread-local context contains session_id="sess789"

  Scenario: Set context initializes context dictionary if not exists
    Given the thread-local context does not exist
    When set_context() is called with user="judy"
    Then the thread-local context is created

  Scenario: Set context populates user when initializing context dictionary
    Given the thread-local context does not exist
    When set_context() is called with user="judy"
    Then the thread-local context contains user="judy"
