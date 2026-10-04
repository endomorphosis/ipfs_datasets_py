Feature: main function from scripts/monitor_p2p_cache.py
  This function is main entry point

  Scenario: Parse --interval argument sets interval to 10
    Given command line ["--interval", "10"]
    When main() is called
    Then interval == 10

  Scenario: Run once mode calls print_banner
    Given command line ["--once"]
    When main() is called
    Then print_banner() called 1 time

  Scenario: Run once mode calls print_stats once
    Given command line ["--once"]
    When main() is called
    Then print_stats() called 1 time

  Scenario: Run once mode exits after stats
    Given command line ["--once"]
    When main() is called
    Then program exits

  Scenario: Continuous mode calls monitor_loop with interval
    Given command line ["--interval", "15"]
    When main() is called
    Then monitor_loop(interval=15) is called

  Scenario: Register SIGINT handler
    When main() starts
    Then signal.signal(signal.SIGINT, signal_handler) is called
