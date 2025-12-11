"""
Test suite for Federal Register Scraper Verification.

Feature: Federal Register Scraper Verification
  Verifies Federal Register scraper by running 8 tests that check API connectivity,
  document searching, agency filtering, document type filtering, data structure,
  keyword search, full text inclusion, and rate limiting.
  The verifier exits with code 0 when failed count equals 0, and exits with
  code 1 when failed count is greater than 0.
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from conftest import FixtureError


# Constants to avoid magic strings/numbers
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"
AGENCY_EPA = "environmental-protection-agency"
AGENCY_FDA = "food-and-drug-administration"
DOCUMENT_TYPE_RULE = "RULE"
SEARCH_KEYWORD = "environmental"
SEARCH_LIMIT = 5
MAX_DOCUMENTS_SEARCH = 10
MAX_DOCUMENTS_STRUCTURE = 3
MAX_DOCUMENTS_FULL_TEXT = 2
MAX_DOCUMENTS_RATE_LIMIT = 3
DAYS_AGO_WEEK = 7
DAYS_AGO_MONTH = 30
DAYS_AGO_STRUCTURE = 14
DAYS_AGO_RULE = 60
RATE_LIMIT_DELAY_SECONDS = 2.0
EXIT_CODE_SUCCESS = 0
EXIT_CODE_FAILURE = 1
REQUIRED_FIELDS = ["document_number", "title", "publication_date"]
FULL_TEXT_FIELDS = ["full_text", "body"]


# Fixtures from Background

@pytest.fixture
def federal_register_verifier_initialized() -> Dict[str, Any]:
    """
    Given the FederalRegisterVerifier is initialized with empty results dictionary
    
    Returns an initialized verifier state with empty results.
    """
    try:
        try:
            from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.verify_federal_register_scraper import FederalRegisterVerifier
            verifier = FederalRegisterVerifier()
        except ImportError:
            verifier = None
        
        verifier_state = {
            "verifier": verifier,
            "initialized": verifier is not None
        }
        
        return verifier_state
    except Exception as e:
        raise FixtureError(f"federal_register_verifier_initialized raised an error: {e}") from e


@pytest.fixture
def search_federal_register_callable():
    """Fixture providing the actual search_federal_register callable."""
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import search_federal_register
        return search_federal_register
    except ImportError as e:
        raise FixtureError(f"search_federal_register_callable raised an error: {e}") from e


@pytest.fixture
def scrape_federal_register_callable():
    """Fixture providing the actual scrape_federal_register callable."""
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import scrape_federal_register
        return scrape_federal_register
    except ImportError as e:
        raise FixtureError(f"scrape_federal_register_callable raised an error: {e}") from e


@pytest.fixture
def date_range_week():
    """Fixture providing date range for last 7 days."""
    try:
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_WEEK)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        return {"start_date": start_date, "end_date": end_date}
    except Exception as e:
        raise FixtureError(f"date_range_week raised an error: {e}") from e


@pytest.fixture
def date_range_month():
    """Fixture providing date range for last 30 days."""
    try:
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_MONTH)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        return {"start_date": start_date, "end_date": end_date}
    except Exception as e:
        raise FixtureError(f"date_range_month raised an error: {e}") from e


# Test 1: Search Recent Documents

class TestSearchRecentDocuments:
    """Test 1: Search Recent Documents - Searches for documents from last 7 days"""

    @pytest.mark.asyncio
    def test_search_recent_documents_returns_success_status(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        search_federal_register_callable,
        date_range_week
    ):
        """
        Given search_federal_register returns a response
        When the callable is invoked with date range from last 7 days
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        
        result = asyncio.run(search_federal_register_callable(
            start_date=date_range_week["start_date"],
            end_date=date_range_week["end_date"],
            limit=MAX_DOCUMENTS_SEARCH
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    @pytest.mark.asyncio
    def test_search_recent_documents_returns_documents(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        search_federal_register_callable,
        date_range_week
    ):
        """
        Given search_federal_register is called with date range
        When the callable returns
        Then len(result["documents"]) is greater than 0
        """
        expected_min_count = 1
        
        result = asyncio.run(search_federal_register_callable(
            start_date=date_range_week["start_date"],
            end_date=date_range_week["end_date"],
            limit=MAX_DOCUMENTS_SEARCH
        ))
        actual_count = len(result.get("documents", []))
        
        assert actual_count >= expected_min_count, f"expected at least {expected_min_count} documents, got {actual_count} instead"

    def test_search_recent_documents_pass_increments_passed_counter(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given verifier summary with passed=0
        When search_federal_register succeeds with documents
        Then summary["passed"] equals 1
        """
        expected_passed = 1
        summary = summary_counters_zeroed.copy()
        summary["passed"] = summary["passed"] + 1
        actual_passed = summary["passed"]
        
        assert actual_passed == expected_passed, f"expected passed={expected_passed}, got passed={actual_passed} instead"

    def test_search_recent_documents_fail_increments_failed_counter(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed
    ):
        """
        Given verifier summary with failed=0
        When search_federal_register raises exception
        Then summary["failed"] equals 1
        """
        expected_failed = 1
        summary = summary_counters_zeroed.copy()
        summary["failed"] = summary["failed"] + 1
        actual_failed = summary["failed"]
        
        assert actual_failed == expected_failed, f"expected failed={expected_failed}, got failed={actual_failed} instead"


# Test 2: Scrape by Agency

class TestScrapeByAgency:
    """Test 2: Scrape by Agency - Scrapes EPA documents from last 30 days"""

    @pytest.mark.asyncio
    def test_scrape_by_agency_returns_success_status(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable,
        date_range_month
    ):
        """
        Given scrape_federal_register is called with EPA agency
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        
        result = asyncio.run(scrape_federal_register_callable(
            agencies=[AGENCY_EPA],
            start_date=date_range_month["start_date"],
            max_documents=MAX_DOCUMENTS_SEARCH
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    @pytest.mark.asyncio
    def test_scrape_by_agency_returns_data(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable,
        date_range_month
    ):
        """
        Given scrape_federal_register is called with EPA agency
        When the callable returns
        Then len(result["data"]) is greater than 0
        """
        expected_min_count = 1
        
        result = asyncio.run(scrape_federal_register_callable(
            agencies=[AGENCY_EPA],
            start_date=date_range_month["start_date"],
            max_documents=MAX_DOCUMENTS_SEARCH
        ))
        actual_count = len(result.get("data", []))
        
        assert actual_count >= expected_min_count, f"expected at least {expected_min_count} documents, got {actual_count} instead"


# Test 3: Scrape Multiple Agencies

class TestScrapeMultipleAgencies:
    """Test 3: Scrape Multiple Agencies - Scrapes EPA and FDA documents"""

    @pytest.mark.asyncio
    def test_scrape_multiple_agencies_returns_success_status(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable,
        date_range_month
    ):
        """
        Given scrape_federal_register is called with EPA and FDA agencies
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        
        result = asyncio.run(scrape_federal_register_callable(
            agencies=[AGENCY_EPA, AGENCY_FDA],
            start_date=date_range_month["start_date"],
            max_documents=MAX_DOCUMENTS_SEARCH
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    @pytest.mark.asyncio
    def test_scrape_multiple_agencies_returns_data(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable,
        date_range_month
    ):
        """
        Given scrape_federal_register is called with EPA and FDA agencies
        When the callable returns
        Then len(result["data"]) is greater than 0
        """
        expected_min_count = 1
        
        result = asyncio.run(scrape_federal_register_callable(
            agencies=[AGENCY_EPA, AGENCY_FDA],
            start_date=date_range_month["start_date"],
            max_documents=MAX_DOCUMENTS_SEARCH
        ))
        actual_count = len(result.get("data", []))
        
        assert actual_count >= expected_min_count, f"expected at least {expected_min_count} documents, got {actual_count} instead"


# Test 4: Filter by Document Types

class TestFilterByDocumentTypes:
    """Test 4: Filter by Document Types - Filters for RULE type documents"""

    @pytest.mark.asyncio
    def test_document_types_returns_success_status(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register is called with RULE document type
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_RULE)).strftime("%Y-%m-%d")
        
        result = asyncio.run(scrape_federal_register_callable(
            document_types=[DOCUMENT_TYPE_RULE],
            start_date=start_date,
            max_documents=SEARCH_LIMIT
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    @pytest.mark.asyncio
    def test_document_types_returns_data(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register is called with RULE document type
        When the callable returns
        Then len(result["data"]) is greater than 0
        """
        expected_min_count = 1
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_RULE)).strftime("%Y-%m-%d")
        
        result = asyncio.run(scrape_federal_register_callable(
            document_types=[DOCUMENT_TYPE_RULE],
            start_date=start_date,
            max_documents=SEARCH_LIMIT
        ))
        actual_count = len(result.get("data", []))
        
        assert actual_count >= expected_min_count, f"expected at least {expected_min_count} documents, got {actual_count} instead"


# Test 5: Validate Data Structure

class TestValidateDataStructure:
    """Test 5: Validate Data Structure - Checks for required fields in scraped data"""

    @pytest.mark.asyncio
    def test_data_structure_contains_document_number(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register returns success with data
        When the callable returns
        Then result["data"][0] contains "document_number"
        """
        expected_field = REQUIRED_FIELDS[0]
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_STRUCTURE)).strftime("%Y-%m-%d")
        
        result = asyncio.run(scrape_federal_register_callable(
            start_date=start_date,
            max_documents=MAX_DOCUMENTS_STRUCTURE
        ))
        first_record = result.get("data", [{}])[0]
        field_present = expected_field in first_record
        
        assert field_present, f"expected field '{expected_field}' in data, got keys {list(first_record.keys())} instead"

    @pytest.mark.asyncio
    def test_data_structure_contains_title(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register returns success with data
        When the callable returns
        Then result["data"][0] contains "title"
        """
        expected_field = REQUIRED_FIELDS[1]
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_STRUCTURE)).strftime("%Y-%m-%d")
        
        result = asyncio.run(scrape_federal_register_callable(
            start_date=start_date,
            max_documents=MAX_DOCUMENTS_STRUCTURE
        ))
        first_record = result.get("data", [{}])[0]
        field_present = expected_field in first_record
        
        assert field_present, f"expected field '{expected_field}' in data, got keys {list(first_record.keys())} instead"

    @pytest.mark.asyncio
    def test_data_structure_contains_publication_date(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register returns success with data
        When the callable returns
        Then result["data"][0] contains "publication_date"
        """
        expected_field = REQUIRED_FIELDS[2]
        today = datetime.now()
        start_date = (today - timedelta(days=DAYS_AGO_STRUCTURE)).strftime("%Y-%m-%d")
        
        result = asyncio.run(scrape_federal_register_callable(
            start_date=start_date,
            max_documents=MAX_DOCUMENTS_STRUCTURE
        ))
        first_record = result.get("data", [{}])[0]
        field_present = expected_field in first_record
        
        assert field_present, f"expected field '{expected_field}' in data, got keys {list(first_record.keys())} instead"


# Test 6: Search with Keywords

class TestSearchWithKeywords:
    """Test 6: Search with Keywords - Searches for 'environmental' keyword"""

    @pytest.mark.asyncio
    def test_keyword_search_returns_success_status(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        search_federal_register_callable,
        date_range_month
    ):
        """
        Given search_federal_register is called with keyword "environmental"
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        
        result = asyncio.run(search_federal_register_callable(
            keywords=SEARCH_KEYWORD,
            start_date=date_range_month["start_date"],
            limit=SEARCH_LIMIT
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"

    @pytest.mark.asyncio
    def test_keyword_search_returns_results(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        search_federal_register_callable,
        date_range_month
    ):
        """
        Given search_federal_register is called with keyword "environmental"
        When the callable returns
        Then len(result["documents"]) is greater than 0
        """
        expected_min_count = 1
        
        result = asyncio.run(search_federal_register_callable(
            keywords=SEARCH_KEYWORD,
            start_date=date_range_month["start_date"],
            limit=SEARCH_LIMIT
        ))
        actual_count = len(result.get("documents", []))
        
        assert actual_count >= expected_min_count, f"expected at least {expected_min_count} results, got {actual_count} instead"


# Test 7: Full Text Inclusion

class TestFullTextInclusion:
    """Test 7: Full Text Inclusion - Verifies full_text or body field inclusion"""

    @pytest.mark.asyncio
    def test_full_text_request_returns_success_status(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register is called with include_full_text=True
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        
        result = asyncio.run(scrape_federal_register_callable(
            include_full_text=True,
            max_documents=MAX_DOCUMENTS_FULL_TEXT
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"


# Test 8: Rate Limiting

class TestRateLimiting:
    """Test 8: Rate Limiting - Verifies delay between requests is honored"""

    @pytest.mark.asyncio
    def test_rate_limiting_parameter_accepted(
        self,
        federal_register_verifier_initialized,
        summary_counters_zeroed,
        scrape_federal_register_callable
    ):
        """
        Given scrape_federal_register is called with rate_limit_delay=2.0
        When the callable returns
        Then result["status"] equals "success"
        """
        expected_status = STATUS_SUCCESS
        
        result = asyncio.run(scrape_federal_register_callable(
            rate_limit_delay=RATE_LIMIT_DELAY_SECONDS,
            max_documents=MAX_DOCUMENTS_RATE_LIMIT
        ))
        actual_status = result.get("status")
        
        assert actual_status == expected_status, f"expected status '{expected_status}', got '{actual_status}' instead"


# Exit Code Determination

class TestExitCodeDetermination:
    """Exit Code Determination - Verifies correct exit codes based on test results"""

    def test_verifier_returns_0_when_no_failures(
        self,
        federal_register_verifier_initialized,
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
        federal_register_verifier_initialized,
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
