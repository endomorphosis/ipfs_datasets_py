Feature: main function from scripts/monitor_p2p_cache.py
  This function is main entry point

  Scenario: Parse command line arguments
    Given command line with --interval 10
    When calling main
    Then interval is set to 10

  Scenario: Run once mode
    Given --once flag provided
    When calling main
    Then banner prints
    And stats print once
    And program exits

  Scenario: Run continuous monitoring
    Given no --once flag
    When calling main
    Then monitor_loop executes with interval

  Scenario: Register signal handler
    When main starts
    Then SIGINT handler is registered
