Feature: Audit Logging
  Event logging and tracking for audit trails

  Scenario: Log audit event with required fields
    Given an audit logger is initialized
    When an event is logged with action and resource information
    Then the event is recorded with timestamp and event ID

  Scenario: Log event with user information
    Given an audit logger is initialized
    When an event is logged with user ID and source IP
    Then the event includes user context

  Scenario: Log event with custom details
    Given an audit logger is initialized
    When an event is logged with custom detail dictionary
    Then the event includes all custom details

  Scenario: Log event with severity level
    Given an audit logger is initialized
    When an event is logged with severity level
    Then the event is recorded with the specified severity

  Scenario: Log event with tags
    Given an audit logger is initialized
    When an event is logged with multiple tags
    Then the event includes all specified tags

  Scenario: Generate unique event ID
    Given an audit logger is initialized
    When multiple events are logged
    Then each event has a unique event ID

  Scenario: Handle event without optional fields
    Given an audit logger is initialized
    When an event is logged with only required fields
    Then the event is recorded with default values for optional fields
