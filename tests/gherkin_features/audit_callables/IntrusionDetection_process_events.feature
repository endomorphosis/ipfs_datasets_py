Feature: IntrusionDetection.process_events()
  Tests the process_events() method of IntrusionDetection.
  This callable processes audit events to detect potential intrusions.

  Background:
    Given an IntrusionDetection instance is initialized
    And baseline metrics are established
    And 3 pattern detectors are registered

  Scenario: Process events returns list of SecurityAlerts
    Given 50 audit events exist
    When process_events() is called with events
    Then a list of SecurityAlert objects is returned

  Scenario: Process events returns empty list when no threats detected
    Given 50 normal audit events exist
    When process_events() is called
    Then an empty list is returned

  Scenario: Process events detects brute force login attempts
    Given 10 failed login events exist for user "alice"
    When process_events() is called
    Then a SecurityAlert with type "brute_force_login" is returned

  Scenario: Process events detects account compromise
    Given events show user "bob" accessing from 3 different IPs
    And events show unusual time access at 3 AM
    When process_events() is called
    Then a SecurityAlert with type "account_compromise" is returned

  Scenario: Process events detects data exfiltration
    Given events show user "charlie" downloading 200MB of data
    When process_events() is called
    Then a SecurityAlert with type "data_exfiltration" is returned

  Scenario: Process events calls anomaly detector for each event
    Given 10 events exist
    When process_events() is called
    Then anomaly_detector.process_event() is called 10 times

  Scenario: Process events converts anomalies to SecurityAlerts
    Given anomaly detector returns 2 anomalies
    When process_events() is called
    Then 2 SecurityAlerts are generated from anomalies

  Scenario: Process events calls all pattern detectors
    Given 3 pattern detectors are registered
    When process_events() is called with events
    Then all 3 pattern detectors are called

  Scenario: Process events handles pattern detector exceptions
    Given a pattern detector that raises Exception
    When process_events() is called
    Then the method completes without raising Exception
    And other pattern detectors still execute

  Scenario: Process events filters out duplicate events
    Given event "evt123" was processed previously
    When process_events() is called with "evt123" again
    Then "evt123" is not processed again

  Scenario: Process events updates recent_alerts
    When process_events() is called and generates 3 alerts
    Then recent_alerts contains 3 entries

  Scenario: Process events dispatches alerts to handlers
    Given 2 alert handlers are registered
    When process_events() is called and generates 2 alerts
    Then all handlers receive both alerts

  Scenario: Process events maintains seen_events set
    Given 100 events are processed
    When process_events() is called
    Then seen_events contains 100 event IDs

  Scenario: Process events returns alerts in order generated
    Given events that trigger 3 different alert types
    When process_events() is called
    Then alerts are returned in chronological order

  Scenario: Process events with empty events list
    When process_events() is called with empty list
    Then an empty alert list is returned

  Scenario: Process events aggregates multiple pattern matches
    Given events trigger both brute_force and data_exfiltration patterns
    When process_events() is called
    Then 2 SecurityAlerts are returned
    And one is type "brute_force_login"
    And one is type "data_exfiltration"
