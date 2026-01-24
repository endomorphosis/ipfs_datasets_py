Feature: SecurityAlertManager.add_alert()
  Tests the add_alert() method of SecurityAlertManager.
  This callable adds a new security alert to the manager.

  Background:
    Given a SecurityAlertManager instance is initialized
    And no alerts exist

  Scenario: Add alert stores alert in alerts dictionary
    Given a SecurityAlert with alert_id="alert-1" exists
    When add_alert() is called with the alert
    Then the alert is stored in alerts dictionary

  Scenario: Add alert creates entry with alert_id key
    Given a SecurityAlert with alert_id="alert-1" exists
    When add_alert() is called with the alert
    Then alerts["alert-1"] exists

  Scenario: Add alert returns alert_id
    Given a SecurityAlert exists
    When add_alert() is called
    Then the alert_id string is returned

  Scenario: Add alert increments alert count
    Given 3 SecurityAlert instances exist
    When add_alert() is called for each alert
    Then the alerts dictionary contains 3 entries

  Scenario: Add alert saves to storage when path configured
    Given storage_path is "/tmp/alerts.json"
    And a SecurityAlert exists
    When add_alert() is called
    Then the alerts are saved to storage file

  Scenario: Add alert notifies all handlers
    Given 2 notification handlers are registered
    And a SecurityAlert exists
    When add_alert() is called
    Then all 2 handlers are called with the alert

  Scenario: Add alert is thread-safe stores all alerts
    Given 10 threads add alerts concurrently
    When all threads complete
    Then 10 alerts are stored

  Scenario: Add alert is thread-safe loses no alerts
    Given 10 threads add alerts concurrently
    When all threads complete
    Then no alerts are lost

  Scenario: Add alert with duplicate alert_id overwrites
    Given a SecurityAlert with alert_id="alert-1" exists in manager
    When add_alert() is called with new alert with alert_id="alert-1"
    Then the new alert replaces the old alert

  Scenario: Add alert handles notification handler exceptions completes without error
    Given a notification handler that raises Exception
    Given a SecurityAlert exists
    When add_alert() is called
    Then the method completes without raising Exception

  Scenario: Add alert handles notification handler exceptions preserves alert
    Given a notification handler that raises Exception
    Given a SecurityAlert exists
    When add_alert() is called
    Then the alert is still stored

  Scenario: Add alert preserves alert properties level
    Given a SecurityAlert with level="high", type="breach" exists
    When add_alert() is called
    Then the stored alert has level="high"

  Scenario: Add alert preserves alert properties type
    Given a SecurityAlert with level="high", type="breach" exists
    When add_alert() is called
    Then the stored alert has type="breach"
