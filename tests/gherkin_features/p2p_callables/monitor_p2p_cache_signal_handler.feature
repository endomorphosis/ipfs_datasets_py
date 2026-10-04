Feature: signal_handler function from scripts/monitor_p2p_cache.py
  This function handles interrupt signals

  Scenario: SIGINT signal exits with code 0
    Given monitor running
    When SIGINT signal received
    Then exit_code == 0
