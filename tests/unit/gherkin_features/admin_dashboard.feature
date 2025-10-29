Feature: Admin Dashboard
  Administrative interface for system management

  Scenario: Display system status
    Given the dashboard is accessed
    When system status is requested
    Then current system metrics are displayed

  Scenario: View active users
    Given the dashboard is accessed
    When user list is requested
    Then active users are displayed

  Scenario: Monitor resource usage
    Given resource monitoring is enabled
    When the dashboard is accessed
    Then CPU and memory usage are displayed

  Scenario: View recent activity logs
    Given activity logging is enabled
    When logs are requested
    Then recent activities are displayed

  Scenario: Manage user accounts
    Given admin privileges
    When user management is accessed
    Then user accounts can be created or modified

  Scenario: Configure system settings
    Given admin privileges
    When settings are accessed
    Then system configuration can be modified

  Scenario: View error reports
    Given error logging is enabled
    When error reports are requested
    Then recent errors are displayed

  Scenario: Export system metrics
    Given system metrics are collected
    When export is requested
    Then metrics are exported in specified format

  Scenario: Reset system state
    Given admin privileges
    When reset is requested
    Then system state is reset to defaults

  Scenario: Schedule maintenance tasks
    Given admin privileges
    When task scheduling is accessed
    Then maintenance tasks can be scheduled
