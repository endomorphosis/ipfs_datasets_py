Feature: signal_handler function from scripts/monitor_p2p_cache.py
  This function handles interrupt signals

  Scenario: Receive interrupt signal
    Given monitor is running
    When SIGINT signal is received
    Then monitoring stopped message prints

  Scenario: Receive interrupt signal - assertion 2
    Given monitor is running
    When SIGINT signal is received
    Then program exits with code 0
