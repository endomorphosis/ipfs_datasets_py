"""
Test suite for All Scrapers Verification Runner.

Feature: All Scrapers Verification Runner
  Runs verify_us_code_scraper.py and verify_federal_register_scraper.py as
  subprocesses and combines their exit codes. The runner exits with code 0
  when both subprocess exit codes are 0, and exits with code 1 otherwise.
"""
import pytest
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from conftest import FixtureError


# Constants to avoid magic strings/numbers
EXIT_CODE_SUCCESS = 0
EXIT_CODE_FAILURE = 1
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
TIMEOUT_SECONDS = 300
TIMEOUT_MINUTES = 5
SCRIPTS_DIR = "tests/scraper_tests"
US_CODE_SCRIPT = "verify_us_code_scraper.py"
FEDERAL_REGISTER_SCRIPT = "verify_federal_register_scraper.py"
ERROR_TIMEOUT_US_CODE = "ERROR: verify_us_code_scraper.py timed out after 5 minutes"
ERROR_TIMEOUT_FEDERAL_REGISTER = "ERROR: verify_federal_register_scraper.py timed out after 5 minutes"
ERROR_EXECUTION_US_CODE = "ERROR: Failed to run verify_us_code_scraper.py"
ERROR_EXECUTION_FEDERAL_REGISTER = "ERROR: Failed to run verify_federal_register_scraper.py"
STATUS_ALL_PASSED = "ALL TESTS PASSED"
STATUS_SOME_FAILED = "SOME TESTS FAILED"
ERROR_CANCELLED = "Verification cancelled by user"
ERROR_VERIFICATION_FAILED = "Verification suite failed with error"


# Fixtures from Background

@pytest.fixture
def verify_all_scrapers_module_loaded() -> Dict[str, Any]:
    """
    Given the verify_all_scrapers module is loaded
    """
    try:
        try:
            from tests.scraper_tests import verify_all_scrapers
            module = verify_all_scrapers
        except ImportError:
            module = None
        
        scraper_tests_dir = Path(SCRIPTS_DIR)
        us_code_script = scraper_tests_dir / US_CODE_SCRIPT
        fed_reg_script = scraper_tests_dir / FEDERAL_REGISTER_SCRIPT
        
        scripts_exist = {
            "us_code_scraper": us_code_script.exists() if scraper_tests_dir.exists() else False,
            "federal_register_scraper": fed_reg_script.exists() if scraper_tests_dir.exists() else False
        }
        
        module_state = {
            "module": module,
            "scripts_exist": scripts_exist,
            "loaded": True,
            "scripts_dir": scraper_tests_dir
        }
        
        return module_state
    except Exception as e:
        raise FixtureError(f"verify_all_scrapers_module_loaded raised an error: {e}") from e


@pytest.fixture
def calculate_exit_code_callable():
    """Fixture providing the exit code calculation function."""
    try:
        def calculate_exit_code(us_code_exit: int, fed_reg_exit: int) -> int:
            """Calculate overall exit code from individual script exit codes."""
            combined = us_code_exit + fed_reg_exit
            return EXIT_CODE_SUCCESS if combined == EXIT_CODE_SUCCESS else EXIT_CODE_FAILURE
        return calculate_exit_code
    except Exception as e:
        raise FixtureError(f"calculate_exit_code_callable raised an error: {e}") from e


@pytest.fixture
def get_status_display_callable():
    """Fixture providing the status display function."""
    try:
        def get_status_display(exit_code: int) -> str:
            """Get status display string based on exit code."""
            return STATUS_PASSED if exit_code == EXIT_CODE_SUCCESS else STATUS_FAILED
        return get_status_display
    except Exception as e:
        raise FixtureError(f"get_status_display_callable raised an error: {e}") from e


@pytest.fixture
def get_overall_status_callable():
    """Fixture providing the overall status display function."""
    try:
        def get_overall_status(us_code_exit: int, fed_reg_exit: int) -> str:
            """Get overall status string based on exit codes."""
            combined = us_code_exit + fed_reg_exit
            return STATUS_ALL_PASSED if combined == EXIT_CODE_SUCCESS else STATUS_SOME_FAILED
        return get_overall_status
    except Exception as e:
        raise FixtureError(f"get_overall_status_callable raised an error: {e}") from e


# Subprocess Execution for US Code Verifier

class TestUSCodeSubprocessExecution:
    """Subprocess Execution for US Code Verifier"""

    def test_us_code_subprocess_returns_0_when_all_pass(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given both scripts pass
        When subprocess.run() returns 0 for US Code script
        Then the subprocess returncode equals 0
        """
        expected_returncode = EXIT_CODE_SUCCESS
        us_code_exit = EXIT_CODE_SUCCESS
        
        actual_us_code_exit = us_code_exit
        
        assert actual_us_code_exit == expected_returncode, f"expected returncode {expected_returncode}, got {actual_us_code_exit} instead"

    def test_us_code_subprocess_displays_passed(
        self, 
        verify_all_scrapers_module_loaded, 
        get_status_display_callable
    ):
        """
        Given US Code script returns 0
        When status display is generated
        Then us_code_status displays "PASSED"
        """
        expected_status = STATUS_PASSED
        
        actual_status = get_status_display_callable(EXIT_CODE_SUCCESS)
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_us_code_subprocess_returns_1_when_any_fail(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given US Code script has failures
        When subprocess.run() completes with failures
        Then the subprocess returncode equals 1
        """
        expected_returncode = EXIT_CODE_FAILURE
        us_code_exit = EXIT_CODE_FAILURE
        
        actual_exit = us_code_exit
        
        assert actual_exit == expected_returncode, f"expected returncode {expected_returncode}, got {actual_exit} instead"

    def test_us_code_subprocess_displays_failed(
        self, 
        verify_all_scrapers_module_loaded, 
        get_status_display_callable
    ):
        """
        Given US Code script returns 1
        When status display is generated
        Then us_code_status displays "FAILED"
        """
        expected_status = STATUS_FAILED
        
        actual_status = get_status_display_callable(EXIT_CODE_FAILURE)
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_us_code_subprocess_displays_timeout_error(
        self, 
        verify_all_scrapers_module_loaded
    ):
        """
        Given subprocess.run() exceeds timeout
        When error message is generated
        Then output contains timeout error message
        """
        expected_error = ERROR_TIMEOUT_US_CODE
        
        actual_error = ERROR_TIMEOUT_US_CODE
        
        assert expected_error in actual_error, f"expected error containing '{expected_error}', got '{actual_error}' instead"


# Subprocess Execution for Federal Register Verifier

class TestFederalRegisterSubprocessExecution:
    """Subprocess Execution for Federal Register Verifier"""

    def test_federal_register_subprocess_returns_0_when_all_pass(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given Federal Register script passes
        When subprocess.run() completes
        Then the subprocess returncode equals 0
        """
        expected_returncode = EXIT_CODE_SUCCESS
        fed_reg_exit = EXIT_CODE_SUCCESS
        
        actual_exit = fed_reg_exit
        
        assert actual_exit == expected_returncode, f"expected returncode {expected_returncode}, got {actual_exit} instead"

    def test_federal_register_subprocess_displays_passed(
        self, 
        verify_all_scrapers_module_loaded, 
        get_status_display_callable
    ):
        """
        Given Federal Register script returns 0
        When status display is generated
        Then fed_reg_status displays "PASSED"
        """
        expected_status = STATUS_PASSED
        
        actual_status = get_status_display_callable(EXIT_CODE_SUCCESS)
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_federal_register_subprocess_returns_1_when_any_fail(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given Federal Register script has failures
        When subprocess.run() completes with failures
        Then the subprocess returncode equals 1
        """
        expected_returncode = EXIT_CODE_FAILURE
        fed_reg_exit = EXIT_CODE_FAILURE
        
        actual_exit = fed_reg_exit
        
        assert actual_exit == expected_returncode, f"expected returncode {expected_returncode}, got {actual_exit} instead"

    def test_federal_register_subprocess_displays_failed(
        self, 
        verify_all_scrapers_module_loaded, 
        get_status_display_callable
    ):
        """
        Given Federal Register script returns 1
        When status display is generated
        Then fed_reg_status displays "FAILED"
        """
        expected_status = STATUS_FAILED
        
        actual_status = get_status_display_callable(EXIT_CODE_FAILURE)
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_federal_register_subprocess_displays_timeout_error(
        self, 
        verify_all_scrapers_module_loaded
    ):
        """
        Given subprocess.run() exceeds timeout
        When error message is generated
        Then output contains timeout error message
        """
        expected_error = ERROR_TIMEOUT_FEDERAL_REGISTER
        
        actual_error = ERROR_TIMEOUT_FEDERAL_REGISTER
        
        assert expected_error in actual_error, f"expected error containing '{expected_error}', got '{actual_error}' instead"


# Overall Exit Code Calculation

class TestOverallExitCodeCalculation:
    """Overall Exit Code Calculation"""

    def test_runner_calculates_0_when_both_pass(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given both us_code_exit and fed_reg_exit equal 0
        When overall exit code is calculated
        Then overall_exit is calculated as 0
        """
        expected_exit = EXIT_CODE_SUCCESS
        us_code_exit = EXIT_CODE_SUCCESS
        fed_reg_exit = EXIT_CODE_SUCCESS
        
        actual_exit = calculate_exit_code_callable(us_code_exit, fed_reg_exit)
        
        assert actual_exit == expected_exit, f"expected overall_exit={expected_exit}, got {actual_exit} instead"

    def test_runner_displays_all_passed(
        self, 
        verify_all_scrapers_module_loaded, 
        get_overall_status_callable
    ):
        """
        Given both us_code_exit and fed_reg_exit equal 0
        When overall status is displayed
        Then overall_status displays "ALL TESTS PASSED"
        """
        expected_status = STATUS_ALL_PASSED
        us_code_exit = EXIT_CODE_SUCCESS
        fed_reg_exit = EXIT_CODE_SUCCESS
        
        actual_status = get_overall_status_callable(us_code_exit, fed_reg_exit)
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_runner_calculates_1_when_us_code_fails(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given us_code_exit equals 1 and fed_reg_exit equals 0
        When overall exit code is calculated
        Then overall_exit is calculated as 1
        """
        expected_exit = EXIT_CODE_FAILURE
        us_code_exit = EXIT_CODE_FAILURE
        fed_reg_exit = EXIT_CODE_SUCCESS
        
        actual_exit = calculate_exit_code_callable(us_code_exit, fed_reg_exit)
        
        assert actual_exit == expected_exit, f"expected overall_exit={expected_exit}, got {actual_exit} instead"

    def test_runner_calculates_1_when_federal_register_fails(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given us_code_exit equals 0 and fed_reg_exit equals 1
        When overall exit code is calculated
        Then overall_exit is calculated as 1
        """
        expected_exit = EXIT_CODE_FAILURE
        us_code_exit = EXIT_CODE_SUCCESS
        fed_reg_exit = EXIT_CODE_FAILURE
        
        actual_exit = calculate_exit_code_callable(us_code_exit, fed_reg_exit)
        
        assert actual_exit == expected_exit, f"expected overall_exit={expected_exit}, got {actual_exit} instead"

    def test_runner_calculates_1_when_both_fail(
        self, 
        verify_all_scrapers_module_loaded, 
        calculate_exit_code_callable
    ):
        """
        Given us_code_exit equals 1 and fed_reg_exit equals 1
        When overall exit code is calculated
        Then overall_exit is calculated as 1
        """
        expected_exit = EXIT_CODE_FAILURE
        us_code_exit = EXIT_CODE_FAILURE
        fed_reg_exit = EXIT_CODE_FAILURE
        
        actual_exit = calculate_exit_code_callable(us_code_exit, fed_reg_exit)
        
        assert actual_exit == expected_exit, f"expected overall_exit={expected_exit}, got {actual_exit} instead"

    def test_runner_displays_some_failed(
        self, 
        verify_all_scrapers_module_loaded, 
        get_overall_status_callable
    ):
        """
        Given us_code_exit or fed_reg_exit equals 1
        When overall status is displayed
        Then overall_status displays "SOME TESTS FAILED"
        """
        expected_status = STATUS_SOME_FAILED
        us_code_exit = EXIT_CODE_FAILURE
        fed_reg_exit = EXIT_CODE_SUCCESS
        
        actual_status = get_overall_status_callable(us_code_exit, fed_reg_exit)
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"


# Exception Handling in Main

class TestExceptionHandlingInMain:
    """Exception Handling in Main"""

    def test_runner_displays_cancelled_on_keyboard_interrupt(
        self, 
        verify_all_scrapers_module_loaded
    ):
        """
        Given main() raises KeyboardInterrupt
        When error message is generated
        Then output contains "Verification cancelled by user"
        """
        expected_message = ERROR_CANCELLED
        
        actual_message = ERROR_CANCELLED
        
        assert expected_message in actual_message, f"expected message containing '{expected_message}', got '{actual_message}' instead"

    def test_runner_displays_error_on_exception(
        self, 
        verify_all_scrapers_module_loaded
    ):
        """
        Given main() raises Exception
        When error message is generated
        Then output contains "Verification suite failed with error"
        """
        expected_message = ERROR_VERIFICATION_FAILED
        
        actual_message = ERROR_VERIFICATION_FAILED
        
        assert expected_message in actual_message, f"expected message containing '{expected_message}', got '{actual_message}' instead"
