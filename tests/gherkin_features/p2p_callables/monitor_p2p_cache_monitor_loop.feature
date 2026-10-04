Feature: monitor_loop function from scripts/monitor_p2p_cache.py
  This function monitors cache in a loop

  Scenario: Monitor loop calls print_banner once
    Given interval 10
    When monitor_loop(interval=10) is called
    Then print_banner() called 1 time

  Scenario: Monitor loop creates cache instance
    Given interval 10
    When monitor_loop(interval=10) is called
    Then GitHubAPICache() is instantiated

  Scenario: Monitor loop outputs monitoring interval
    Given interval 10
    When monitor_loop(interval=10) is called
    Then output contains "interval: 10"

  Scenario: Monitor loop calls print_stats each iteration
    Given interval 10
    And 3 iterations
    When monitor_loop(interval=10) runs 3 iterations
    Then print_stats() called 3 times

  Scenario: Monitor loop sleeps for interval seconds
    Given interval 10
    When monitor_loop(interval=10) completes iteration
    Then time.sleep(10) is called

  Scenario: Monitor loop outputs update header each iteration
    Given interval 10
    And 2 iterations
    When monitor_loop(interval=10) runs 2 iterations
    Then output contains "UPDATE" 2 times

  Scenario: Monitor loop outputs tip on first iteration
    Given interval 10
    When monitor_loop(interval=10) runs first iteration
    Then output contains "Tip:"

  Scenario: KeyboardInterrupt stops monitor loop
    Given interval 10
    When KeyboardInterrupt raised
    Then monitor_loop exits
