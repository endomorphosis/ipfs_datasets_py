Feature: monitor_loop function from scripts/monitor_p2p_cache.py
  This function monitors cache in a loop

  Scenario: Initialize monitoring
    Given interval of 10 seconds
    When calling monitor_loop
    Then banner prints

  Scenario: Initialize monitoring - assertion 2
    Given interval of 10 seconds
    When calling monitor_loop
    Then cache initializes

  Scenario: Initialize monitoring - assertion 3
    Given interval of 10 seconds
    When calling monitor_loop
    Then monitoring interval displays

  Scenario: Run monitoring iterations
    Given monitoring active
    When iteration completes
    Then update header displays

  Scenario: Run monitoring iterations - assertion 2
    Given monitoring active
    When iteration completes
    Then stats print

  Scenario: Run monitoring iterations - assertion 3
    Given monitoring active
    When iteration completes
    Then function sleeps for interval

  Scenario: Display tip on first iteration
    Given first monitoring iteration
    When displaying stats
    Then usage tip displays

  Scenario: Stop monitoring with keyboard interrupt
    Given monitoring loop running
    When keyboard interrupt occurs
    Then signal_handler is called
