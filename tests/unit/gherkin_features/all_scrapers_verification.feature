Feature: All Scrapers Verification Runner
  The all scrapers verification runner executes verification tools for
  US Code and Federal Register scrapers and provides a combined summary.

  Background:
    Given the verify_all_scrapers module is loaded

  # Running Individual Verifications

  Scenario: Run US Code verification script
    When I run the verification for "verify_us_code_scraper.py"
    Then a subprocess is started
    And the process runs with a 5 minute timeout
    And output is captured from stdout and stderr

  Scenario: Run Federal Register verification script
    When I run the verification for "verify_federal_register_scraper.py"
    Then a subprocess is started
    And the process runs with a 5 minute timeout
    And output is captured from stdout and stderr

  Scenario: Verification script times out
    When I run a verification script
    And the script exceeds 5 minutes
    Then the exit code is 1
    And the output contains "ERROR: timed out after 5 minutes"

  Scenario: Verification script fails to start
    When I run a verification script
    And an exception occurs during execution
    Then the exit code is 1
    And the output contains "ERROR: Failed to run"

  # Combined Verification Suite

  Scenario: Run all verifications displays header
    When I run the main verification suite
    Then the output contains "LEGAL DATASET TOOLS VERIFICATION SUITE"
    And the output contains the start timestamp

  Scenario: Run all verifications executes US Code verification first
    When I run the main verification suite
    Then the output contains "RUNNING: US Code Scraper Verification"
    And US Code verification output is printed

  Scenario: Run all verifications executes Federal Register verification second
    When I run the main verification suite
    Then the output contains "RUNNING: Federal Register Scraper Verification"
    And Federal Register verification output is printed

  # Combined Summary

  Scenario: Both verifications pass
    Given US Code verification exit code is 0
    And Federal Register verification exit code is 0
    When I run the main verification suite
    Then the combined summary shows US Code Scraper as "PASSED"
    And the combined summary shows Federal Register as "PASSED"
    And the overall status is "ALL TESTS PASSED"
    And the exit code is 0

  Scenario: US Code verification fails
    Given US Code verification exit code is 1
    And Federal Register verification exit code is 0
    When I run the main verification suite
    Then the combined summary shows US Code Scraper as "FAILED"
    And the combined summary shows Federal Register as "PASSED"
    And the overall status is "SOME TESTS FAILED"
    And the exit code is 1

  Scenario: Federal Register verification fails
    Given US Code verification exit code is 0
    And Federal Register verification exit code is 1
    When I run the main verification suite
    Then the combined summary shows US Code Scraper as "PASSED"
    And the combined summary shows Federal Register as "FAILED"
    And the overall status is "SOME TESTS FAILED"
    And the exit code is 1

  Scenario: Both verifications fail
    Given US Code verification exit code is 1
    And Federal Register verification exit code is 1
    When I run the main verification suite
    Then the combined summary shows US Code Scraper as "FAILED"
    And the combined summary shows Federal Register as "FAILED"
    And the overall status is "SOME TESTS FAILED"
    And the exit code is 1

  # User Interruption

  Scenario: User cancels verification with keyboard interrupt
    When I run the main verification suite
    And the user presses Ctrl+C
    Then the output contains "Verification cancelled by user"
    And the exit code is 1

  # Unexpected Errors

  Scenario: Main verification suite encounters exception
    When I run the main verification suite
    And an unexpected exception occurs
    Then the output contains "Verification suite failed with error"
    And a traceback is printed
    And the exit code is 1

  # Completion Information

  Scenario: Verification suite displays completion timestamp
    When I run the main verification suite
    Then the combined summary contains "Completed at:"
    And the timestamp is in format "YYYY-MM-DD HH:MM:SS"
