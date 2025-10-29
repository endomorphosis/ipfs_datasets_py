Feature: Monitoring and Metrics
  System monitoring, logging, and performance metrics collection

  Scenario: Initialize logger with default configuration
    Given a logger configuration with default settings
    When the logger is initialized
    Then the logger is ready to record events

  Scenario: Configure custom log level
    Given a logger configuration with custom log level
    When the logger is initialized
    Then the logger uses the specified log level

  Scenario: Enable file logging
    Given a logger configuration with file path specified
    When the logger is initialized
    Then log entries are written to the file

  Scenario: Enable console logging
    Given a logger configuration with console enabled
    When the logger is initialized
    Then log entries are written to console

  Scenario: Enable log rotation
    Given a logger configuration with rotation enabled
    When the log file exceeds max size
    Then the log file is rotated
    And old logs are backed up

  Scenario: Collect performance metrics
    Given metrics collection is enabled
    When an operation completes
    Then metrics are recorded

  Scenario: Export metrics to Prometheus
    Given Prometheus export is enabled
    When metrics are collected
    Then metrics are available on the Prometheus endpoint

  Scenario: Track operation timing
    Given a timed operation
    When the operation executes
    Then the execution time is recorded

  Scenario: Monitor resource usage
    Given resource monitoring is enabled
    When metrics are collected
    Then CPU and memory usage are recorded

  Scenario: Record counter metrics
    Given a counter metric is defined
    When an event occurs
    Then the counter is incremented

  Scenario: Record gauge metrics
    Given a gauge metric is defined
    When a value changes
    Then the gauge is updated

  Scenario: Capture Python warnings
    Given warning capture is enabled
    When a warning is raised
    Then the warning is logged

  Scenario: Silence specific modules
    Given specific modules are silenced
    When those modules log messages
    Then the messages are suppressed

  Scenario: Include process information in logs
    Given process information is enabled
    When a log entry is created
    Then the log includes process details
