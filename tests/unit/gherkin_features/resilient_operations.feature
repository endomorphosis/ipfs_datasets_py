Feature: Resilient Operations
  Fault-tolerant operations with retry and recovery

  Scenario: Execute operation with retry
    Given an operation that may fail
    When the operation is executed with retry
    Then failed attempts are retried

  Scenario: Apply exponential backoff
    Given a retryable operation
    When retry with exponential backoff is used
    Then retry delays increase exponentially

  Scenario: Handle maximum retry limit
    Given an operation with retry limit
    When maximum retries are exceeded
    Then the operation fails with error

  Scenario: Execute circuit breaker pattern
    Given an operation with circuit breaker
    When consecutive failures occur
    Then the circuit opens to prevent further attempts

  Scenario: Recover from circuit breaker
    Given an open circuit breaker
    When the recovery timeout passes
    Then the circuit transitions to half-open state

  Scenario: Handle transient failures
    Given an operation with transient errors
    When execution is attempted
    Then transient errors are retried

  Scenario: Skip retry for permanent failures
    Given an operation with permanent error
    When execution fails
    Then no retry is attempted

  Scenario: Log retry attempts
    Given a retryable operation
    When retries occur
    Then retry attempts are logged

  Scenario: Execute fallback operation
    Given an operation with fallback
    When the primary operation fails
    Then the fallback operation is executed

  Scenario: Monitor operation health
    Given operations with health monitoring
    When monitoring runs
    Then operation health status is reported
