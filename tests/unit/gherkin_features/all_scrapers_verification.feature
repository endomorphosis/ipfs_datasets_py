Feature: All Scrapers Verification Runner
  Runs verify_us_code_scraper.py and verify_federal_register_scraper.py as
  subprocesses and combines their exit codes. The runner exits with code 0
  when both subprocess exit codes are 0, and exits with code 1 otherwise.

  Background:
    Given the verify_all_scrapers module is loaded

  # Subprocess Execution for US Code Verifier

  Scenario: US Code subprocess returns exit code 0 when all tests pass
    When subprocess.run(["python", "verify_us_code_scraper.py"]) completes
    And the subprocess returncode equals 0
    Then us_code_exit is set to 0
    And us_code_status displays "PASSED"

  Scenario: US Code subprocess returns exit code 1 when any test fails
    When subprocess.run(["python", "verify_us_code_scraper.py"]) completes
    And the subprocess returncode equals 1
    Then us_code_exit is set to 1
    And us_code_status displays "FAILED"

  Scenario: US Code subprocess times out after 300 seconds
    When subprocess.run() exceeds timeout=300 seconds
    And subprocess.TimeoutExpired is raised
    Then us_code_exit is set to 1
    And output contains "ERROR: verify_us_code_scraper.py timed out after 5 minutes"

  Scenario: US Code subprocess fails to execute
    When subprocess.run() raises an Exception
    Then us_code_exit is set to 1
    And output contains "ERROR: Failed to run verify_us_code_scraper.py"

  # Subprocess Execution for Federal Register Verifier

  Scenario: Federal Register subprocess returns exit code 0 when all tests pass
    When subprocess.run(["python", "verify_federal_register_scraper.py"]) completes
    And the subprocess returncode equals 0
    Then fed_reg_exit is set to 0
    And fed_reg_status displays "PASSED"

  Scenario: Federal Register subprocess returns exit code 1 when any test fails
    When subprocess.run(["python", "verify_federal_register_scraper.py"]) completes
    And the subprocess returncode equals 1
    Then fed_reg_exit is set to 1
    And fed_reg_status displays "FAILED"

  Scenario: Federal Register subprocess times out after 300 seconds
    When subprocess.run() exceeds timeout=300 seconds
    And subprocess.TimeoutExpired is raised
    Then fed_reg_exit is set to 1
    And output contains "ERROR: verify_federal_register_scraper.py timed out after 5 minutes"

  Scenario: Federal Register subprocess fails to execute
    When subprocess.run() raises an Exception
    Then fed_reg_exit is set to 1
    And output contains "ERROR: Failed to run verify_federal_register_scraper.py"

  # Overall Exit Code Calculation

  Scenario: Runner exits with code 0 when both subprocesses return 0
    When us_code_exit equals 0
    And fed_reg_exit equals 0
    Then overall_exit is calculated as 0
    And overall_status displays "ALL TESTS PASSED"
    And sys.exit(0) is called

  Scenario: Runner exits with code 1 when US Code subprocess returns 1
    When us_code_exit equals 1
    And fed_reg_exit equals 0
    Then overall_exit is calculated as 1
    And overall_status displays "SOME TESTS FAILED"
    And sys.exit(1) is called

  Scenario: Runner exits with code 1 when Federal Register subprocess returns 1
    When us_code_exit equals 0
    And fed_reg_exit equals 1
    Then overall_exit is calculated as 1
    And overall_status displays "SOME TESTS FAILED"
    And sys.exit(1) is called

  Scenario: Runner exits with code 1 when both subprocesses return 1
    When us_code_exit equals 1
    And fed_reg_exit equals 1
    Then overall_exit is calculated as 1
    And overall_status displays "SOME TESTS FAILED"
    And sys.exit(1) is called

  # Exception Handling in Main

  Scenario: Runner exits with code 1 when KeyboardInterrupt is caught
    When main() raises KeyboardInterrupt
    Then output contains "Verification cancelled by user"
    And sys.exit(1) is called

  Scenario: Runner exits with code 1 when unhandled exception is caught
    When main() raises Exception
    Then output contains "Verification suite failed with error"
    And traceback is printed
    And sys.exit(1) is called
