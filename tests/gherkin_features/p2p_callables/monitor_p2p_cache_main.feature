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

  Scenario: Run once mode - assertion 2
    Given --once flag provided
    When calling main
    Then stats print once

  Scenario: Run once mode - assertion 3
    Given --once flag provided
    When calling main
    Then program exits

  Scenario: Run continuous monitoring
    Given no --once flag
    When calling main
    Then monitor_loop executes with interval

  Scenario: Register signal handler
    When main starts
    Then SIGINT handler is registered
