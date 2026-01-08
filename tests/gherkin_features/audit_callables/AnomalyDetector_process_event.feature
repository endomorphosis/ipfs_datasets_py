Feature: AnomalyDetector.process_event()
  Tests the process_event() method of AnomalyDetector.
  This callable processes a single audit event and detects anomalies.

  Background:
    Given an AnomalyDetector instance is initialized
    And baseline metrics are established from 1000 historical events
    And the window_size is 100

  Scenario: Process event returns list of anomalies
    Given an AuditEvent exists
    When process_event() is called with the event
    Then a list is returned

  Scenario: Process event returns empty list when no anomalies
    Given an AuditEvent with normal patterns exists
    When process_event() is called
    Then an empty list is returned

  Scenario: Process event adds event to current_window
    Given the current_window has 50 events
    When process_event() is called with new event
    Then current_window contains 51 events

  Scenario: Process event maintains window_size limit
    Given the current_window has 100 events (at limit)
    When process_event() is called with new event
    Then current_window still has 100 events
    And the oldest event is removed

  Scenario: Process event updates metrics
    Given an AuditEvent with category=AUTHENTICATION exists
    When process_event() is called
    Then metrics_history is updated with new counts

  Scenario: Process event detects authentication failure anomaly
    Given baseline shows 5% failure rate
    And 50 events in window have 90% failure rate
    When process_event() is called with another failure
    Then an anomaly with type="authentication_failure" is returned

  Scenario: Process event detects user activity anomaly
    Given baseline shows user "alice" averages 10 events per window
    And current window has 100 events for "alice"
    When process_event() is called with event from "alice"
    Then an anomaly with type="user_activity" is returned

  Scenario: Process event detects category volume anomaly
    Given baseline shows 20 SECURITY events per window
    And current window has 80 SECURITY events
    When process_event() is called with SECURITY event
    Then an anomaly with type="category_volume" is returned

  Scenario: Process event calculates z-score for metrics
    Given baseline mean is 10 with stddev 2
    And current value is 18
    When process_event() triggers anomaly check
    Then the z_score is 4.0

  Scenario: Process event uses threshold_multiplier
    Given threshold_multiplier is 2.0
    And z-score is 1.5
    When anomaly detection runs
    Then no anomaly is detected (below threshold)
    
  Scenario: Process event includes deviation_percent in anomaly
    Given baseline mean is 100
    And current value is 150
    When an anomaly is detected
    Then deviation_percent is 50.0

  Scenario: Process event calculates severity based on z-score
    Given z-score is 3.5
    When an anomaly is created
    Then severity is "medium"
