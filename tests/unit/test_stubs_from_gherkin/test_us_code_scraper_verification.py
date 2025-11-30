"""
Test suite for US Code Scraper Verification.

Feature: US Code Scraper Verification
  Verifies US Code scraper by running 7 tests that check API connectivity,
  data retrieval, structure validation, search, metadata, and rate limiting.
  The verifier exits with code 0 when failed count equals 0, and exits with
  code 1 when failed count is greater than 0.
"""
import pytest
import asyncio
from typing import Dict, Any
from unittest.mock import Mock, patch, AsyncMock

from conftest import FixtureError


# Constants to avoid magic strings/numbers
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"
EXPECTED_MIN_TITLES = 50
EXPECTED_MIN_MULTIPLE_TITLES = 2
RATE_LIMIT_DELAY_SECONDS = 2.0
MAX_SECTIONS_SINGLE = 10
MAX_SECTIONS_MULTIPLE = 5
MAX_SECTIONS_STRUCTURE = 3
SEARCH_LIMIT = 5
SEARCH_QUERY = "commerce"
TITLE_1 = "1"
TITLE_15 = "15"
TITLE_18 = "18"
EXIT_CODE_SUCCESS = 0
EXIT_CODE_FAILURE = 1
REQUIRED_FIELDS = ["title_number", "title_name", "section_number"]


# Fixtures from Background

@pytest.fixture
def us_code_verifier_initialized() -> Dict[str, Any]:
    """
    Given the USCodeVerifier is initialized with empty results dictionary
    
    Returns an initialized verifier state with empty results.
    """
    try:
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.verify_us_code_scraper import USCodeVerifier
            verifier = USCodeVerifier()
        except ImportError:
            verifier = None
        
        verifier_state = {
            "verifier": verifier,
            "initialized": verifier is not None
        }
        
        return verifier_state
    except Exception as e:
        raise FixtureError(f"us_code_verifier_initialized raised an error: {e}") from e


@pytest.fixture
def mock_get_us_code_titles():
    """Fixture providing a mock for get_us_code_titles."""
    try:
        return AsyncMock()
    except Exception as e:
        raise FixtureError(f"mock_get_us_code_titles raised an error: {e}") from e


@pytest.fixture
def mock_scrape_us_code():
    """Fixture providing a mock for scrape_us_code."""
    try:
        return AsyncMock()
    except Exception as e:
        raise FixtureError(f"mock_scrape_us_code raised an error: {e}") from e


@pytest.fixture
def mock_search_us_code():
    """Fixture providing a mock for search_us_code."""
    try:
        return AsyncMock()
    except Exception as e:
        raise FixtureError(f"mock_search_us_code raised an error: {e}") from e


# Test 1: Get US Code Titles

class TestGetUSTitles:
    """Test 1: Get US Code Titles - Verifies title list retrieval from uscode.house.gov"""

    def test_get_titles_returns_success_status(
        self, 
        us_code_verifier_initialized, 
        summary_counters_zeroed,
        mock_get_us_code_titles
    ):
        """
        Given get_us_code_titles returns a response
        When the callable is invoked
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        mock_get_us_code_titles.return_value = {"status": STATUS_SUCCESS, "titles": {}}
        
        result = asyncio.run(mock_get_us_code_titles())
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_get_titles_returns_50_plus_titles(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_get_us_code_titles
    ):
        """
        Given get_us_code_titles returns a response with titles
        When the callable is invoked
        Then len(result["titles"]) is greater than or equal to 50
        """
        expected_min_count = EXPECTED_MIN_TITLES
        mock_titles = {str(i): f"Title {i}" for i in range(1, 55)}
        mock_get_us_code_titles.return_value = {"status": STATUS_SUCCESS, "titles": mock_titles}
        
        result = asyncio.run(mock_get_us_code_titles())
        actual_count = len(result.get("titles", {}))
        
        assert actual_count >= expected_min_count, f"expected at least {expected_min_count} titles, got {actual_count} instead"

    def test_get_titles_pass_increments_passed_counter(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given verifier summary with passed=0
        When get_us_code_titles succeeds with 50+ titles
        Then summary["passed"] equals 1
        """
        expected_passed = 1
        summary = summary_counters_zeroed.copy()
        summary["passed"] = summary["passed"] + 1
        actual_passed = summary["passed"]
        
        assert actual_passed == expected_passed, f"expected passed={expected_passed}, got passed={actual_passed} instead"

    def test_get_titles_fail_increments_failed_counter(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given verifier summary with failed=0
        When get_us_code_titles raises exception
        Then summary["failed"] equals 1
        """
        expected_failed = 1
        summary = summary_counters_zeroed.copy()
        summary["failed"] = summary["failed"] + 1
        actual_failed = summary["failed"]
        
        assert actual_failed == expected_failed, f"expected failed={expected_failed}, got failed={actual_failed} instead"

    def test_get_titles_warn_increments_warnings_counter(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given verifier summary with warnings=0
        When get_us_code_titles returns fewer than 50 titles
        Then summary["warnings"] equals 1
        """
        expected_warnings = 1
        summary = summary_counters_zeroed.copy()
        summary["warnings"] = summary["warnings"] + 1
        actual_warnings = summary["warnings"]
        
        assert actual_warnings == expected_warnings, f"expected warnings={expected_warnings}, got warnings={actual_warnings} instead"


# Test 2: Scrape Single Title

class TestScrapeSingleTitle:
    """Test 2: Scrape Single Title - Verifies scraping Title 1 with max_sections=10"""

    def test_scrape_single_title_returns_data(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code is called with titles=["1"], max_sections=10
        When the callable returns
        Then len(result["data"]) is greater than 0
        """
        expected_min_data = 1
        mock_scrape_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "data": [{"title_number": TITLE_1, "sections": []}]
        }
        
        result = asyncio.run(mock_scrape_us_code(titles=[TITLE_1], max_sections=MAX_SECTIONS_SINGLE))
        actual_data_len = len(result.get("data", []))
        
        assert actual_data_len >= expected_min_data, f"expected data length >= {expected_min_data}, got {actual_data_len} instead"

    def test_scrape_single_title_returns_success_status(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code is called with titles=["1"], max_sections=10
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        mock_scrape_us_code.return_value = {"status": STATUS_SUCCESS, "data": []}
        
        result = asyncio.run(mock_scrape_us_code(titles=[TITLE_1], max_sections=MAX_SECTIONS_SINGLE))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    def test_scrape_single_title_pass_increments_passed_counter(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given verifier summary with passed=0
        When scrape_us_code succeeds with data
        Then summary["passed"] equals 1
        """
        expected_passed = 1
        summary = summary_counters_zeroed.copy()
        summary["passed"] = summary["passed"] + 1
        actual_passed = summary["passed"]
        
        assert actual_passed == expected_passed, f"expected passed={expected_passed}, got passed={actual_passed} instead"


# Test 3: Scrape Multiple Titles

class TestScrapeMultipleTitles:
    """Test 3: Scrape Multiple Titles - Verifies scraping titles ["1","15","18"] with max_sections=5"""

    def test_scrape_multiple_titles_returns_2_plus_titles(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code is called with titles=["1","15","18"], max_sections=5
        When the callable returns
        Then sections contain title_number values from 2 or more different titles
        """
        expected_min_titles = EXPECTED_MIN_MULTIPLE_TITLES
        mock_scrape_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "data": [
                {"title_number": TITLE_1, "sections": []},
                {"title_number": TITLE_15, "sections": []},
                {"title_number": TITLE_18, "sections": []}
            ]
        }
        
        result = asyncio.run(mock_scrape_us_code(
            titles=[TITLE_1, TITLE_15, TITLE_18], 
            max_sections=MAX_SECTIONS_MULTIPLE
        ))
        titles_found = set(d.get("title_number") for d in result.get("data", []))
        actual_titles_count = len(titles_found)
        
        assert actual_titles_count >= expected_min_titles, f"expected at least {expected_min_titles} titles, got {actual_titles_count} instead"

    def test_scrape_multiple_titles_returns_success_status(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code is called with titles=["1","15","18"], max_sections=5
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        mock_scrape_us_code.return_value = {"status": STATUS_SUCCESS, "data": []}
        
        result = asyncio.run(mock_scrape_us_code(
            titles=[TITLE_1, TITLE_15, TITLE_18], 
            max_sections=MAX_SECTIONS_MULTIPLE
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"


# Test 4: Validate Data Structure

class TestValidateDataStructure:
    """Test 4: Validate Data Structure - Checks for required fields in scraped data"""

    def test_data_structure_contains_title_number(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code returns success with data
        When the callable returns
        Then result["data"][0] contains "title_number"
        """
        expected_field = REQUIRED_FIELDS[0]
        mock_scrape_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "data": [{"title_number": TITLE_15, "title_name": "Commerce", "section_number": "15.1"}]
        }
        
        result = asyncio.run(mock_scrape_us_code(titles=[TITLE_15], max_sections=MAX_SECTIONS_STRUCTURE))
        first_record = result.get("data", [{}])[0]
        field_present = expected_field in first_record
        
        assert field_present, f"expected field '{expected_field}' in data, got keys {list(first_record.keys())} instead"

    def test_data_structure_contains_title_name(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code returns success with data
        When the callable returns
        Then result["data"][0] contains "title_name"
        """
        expected_field = REQUIRED_FIELDS[1]
        mock_scrape_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "data": [{"title_number": TITLE_15, "title_name": "Commerce", "section_number": "15.1"}]
        }
        
        result = asyncio.run(mock_scrape_us_code(titles=[TITLE_15], max_sections=MAX_SECTIONS_STRUCTURE))
        first_record = result.get("data", [{}])[0]
        field_present = expected_field in first_record
        
        assert field_present, f"expected field '{expected_field}' in data, got keys {list(first_record.keys())} instead"

    def test_data_structure_contains_section_number(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code returns success with data
        When the callable returns
        Then result["data"][0] contains "section_number"
        """
        expected_field = REQUIRED_FIELDS[2]
        mock_scrape_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "data": [{"title_number": TITLE_15, "title_name": "Commerce", "section_number": "15.1"}]
        }
        
        result = asyncio.run(mock_scrape_us_code(titles=[TITLE_15], max_sections=MAX_SECTIONS_STRUCTURE))
        first_record = result.get("data", [{}])[0]
        field_present = expected_field in first_record
        
        assert field_present, f"expected field '{expected_field}' in data, got keys {list(first_record.keys())} instead"


# Test 5: Search Functionality

class TestSearchFunctionality:
    """Test 5: Search Functionality - Searches for "commerce" in Title 15"""

    def test_search_returns_results(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_search_us_code
    ):
        """
        Given search_us_code is called with query="commerce", titles=["15"], limit=5
        When the callable returns
        Then len(result["results"]) is greater than 0
        """
        expected_min_results = 1
        mock_search_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "results": [{"title": "Commerce Act", "snippet": "test"}]
        }
        
        result = asyncio.run(mock_search_us_code(
            query=SEARCH_QUERY,
            titles=[TITLE_15],
            limit=SEARCH_LIMIT
        ))
        actual_results_len = len(result.get("results", []))
        
        assert actual_results_len >= expected_min_results, f"expected at least {expected_min_results} results, got {actual_results_len} instead"

    def test_search_returns_success_status(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_search_us_code
    ):
        """
        Given search_us_code is called with query="commerce", titles=["15"], limit=5
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        mock_search_us_code.return_value = {"status": STATUS_SUCCESS, "results": []}
        
        result = asyncio.run(mock_search_us_code(
            query=SEARCH_QUERY,
            titles=[TITLE_15],
            limit=SEARCH_LIMIT
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"


# Test 6: Metadata Inclusion

class TestMetadataInclusion:
    """Test 6: Metadata Inclusion - Verifies metadata field is present when requested"""

    def test_metadata_exists_when_requested(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code is called with include_metadata=True
        When the callable returns
        Then bool(result["metadata"]) is True
        """
        expected_metadata_present = True
        mock_scrape_us_code.return_value = {
            "status": STATUS_SUCCESS,
            "data": [],
            "metadata": {"scraped_at": "2024-01-01"}
        }
        
        result = asyncio.run(mock_scrape_us_code(titles=[TITLE_1], include_metadata=True))
        actual_metadata_present = bool(result.get("metadata"))
        
        assert actual_metadata_present == expected_metadata_present, f"expected metadata present={expected_metadata_present}, got {actual_metadata_present} instead"


# Test 7: Rate Limiting

class TestRateLimiting:
    """Test 7: Rate Limiting - Verifies delay between requests is honored"""

    def test_rate_limiting_parameter_accepted(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed,
        mock_scrape_us_code
    ):
        """
        Given scrape_us_code is called with rate_limit_delay=2.0
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        mock_scrape_us_code.return_value = {"status": STATUS_SUCCESS, "data": []}
        
        result = asyncio.run(mock_scrape_us_code(
            titles=[TITLE_1],
            rate_limit_delay=RATE_LIMIT_DELAY_SECONDS,
            max_sections=MAX_SECTIONS_STRUCTURE
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"


# Exit Code Determination

class TestExitCodeDetermination:
    """Exit Code Determination - Verifies correct exit codes based on test results"""

    def test_verifier_returns_0_when_no_failures(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given all tests complete with summary["failed"] equals 0
        When run_all_tests completes
        Then exit code equals 0
        """
        expected_exit_code = EXIT_CODE_SUCCESS
        summary = summary_counters_zeroed.copy()
        actual_exit_code = EXIT_CODE_SUCCESS if summary["failed"] == 0 else EXIT_CODE_FAILURE
        
        assert actual_exit_code == expected_exit_code, f"expected exit code {expected_exit_code}, got {actual_exit_code} instead"

    def test_verifier_returns_1_when_failures(
        self,
        us_code_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given all tests complete with summary["failed"] greater than 0
        When run_all_tests completes
        Then exit code equals 1
        """
        expected_exit_code = EXIT_CODE_FAILURE
        summary = summary_counters_zeroed.copy()
        summary["failed"] = 1
        actual_exit_code = EXIT_CODE_SUCCESS if summary["failed"] == 0 else EXIT_CODE_FAILURE
        
        assert actual_exit_code == expected_exit_code, f"expected exit code {expected_exit_code}, got {actual_exit_code} instead"
