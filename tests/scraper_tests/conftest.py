"""
Pytest configuration and fixtures for Municode scraper tests.

Background:
    Given the Municode Library is available at "https://library.municode.com"
"""
import pytest


class FixtureError(Exception):
    """Custom exception for fixture-related errors."""
    pass


@pytest.fixture
def municode_base_url():
    """Base URL for Municode Library."""
    return "https://library.municode.com"


@pytest.fixture
def mock_search_jurisdictions():
    """Mock implementation of search_jurisdictions callable."""
    async def _search(state=None, jurisdiction=None, keywords=None, limit=100):
        try:
            if jurisdiction == "NonexistentCity12345":
                return {"jurisdictions": []}
            
            jurisdictions = []
            if state == "WA":
                jurisdictions = [
                    {
                        "name": "Seattle, WA",
                        "state": "WA",
                        "url": "https://library.municode.com/wa/seattle",
                        "provider": "municode"
                    },
                    {
                        "name": "Tacoma, WA",
                        "state": "WA",
                        "url": "https://library.municode.com/wa/tacoma",
                        "provider": "municode"
                    }
                ]
            elif state == "CA":
                jurisdictions = [
                    {
                        "name": "Los Angeles, CA",
                        "state": "CA",
                        "url": "https://library.municode.com/ca/los_angeles",
                        "provider": "municode"
                    },
                    {
                        "name": "San Francisco, CA",
                        "state": "CA",
                        "url": "https://library.municode.com/ca/san_francisco",
                        "provider": "municode"
                    }
                ]
            elif jurisdiction == "Seattle":
                jurisdictions = [
                    {
                        "name": "Seattle, WA",
                        "state": "WA",
                        "url": "https://library.municode.com/wa/seattle",
                        "provider": "municode"
                    }
                ]
            elif keywords:
                jurisdictions = [
                    {
                        "name": "Sample City, XX",
                        "state": "XX",
                        "url": "https://library.municode.com/xx/sample",
                        "provider": "municode"
                    }
                ]
            
            jurisdictions = jurisdictions[:limit]
            return {"jurisdictions": jurisdictions}
        except Exception as e:
            raise FixtureError(f"mock_search_jurisdictions errored: {e}") from e
    
    return _search


@pytest.fixture
def mock_scrape_jurisdiction():
    """Mock implementation of scrape_jurisdiction callable."""
    async def _scrape(jurisdiction, url, include_metadata=False, max_sections=None):
        try:
            if "invalid" in url.lower():
                return {
                    "error": "Invalid URL",
                    "sections": []
                }
            
            sections = [
                {
                    "section_number": "1.01.020",
                    "title": "Definitions",
                    "text": "Sample section text",
                    "source_url": url
                },
                {
                    "section_number": "1.02.030",
                    "title": "General Provisions",
                    "text": "Sample section text",
                    "source_url": url
                }
            ]
            
            if include_metadata:
                for section in sections:
                    section["scraped_at"] = "2024-12-08T12:00:00Z"
            
            if max_sections:
                sections = sections[:max_sections]
            
            return {
                "jurisdiction": jurisdiction,
                "sections": sections
            }
        except Exception as e:
            raise FixtureError(f"mock_scrape_jurisdiction errored: {e}") from e
    
    return _scrape


@pytest.fixture
def mock_batch_scrape():
    """Mock implementation of batch_scrape callable."""
    async def _batch_scrape(
        jurisdictions=None,
        states=None,
        output_format="json",
        include_metadata=False,
        rate_limit_delay=2.0,
        max_jurisdictions=None,
        max_sections_per_jurisdiction=None
    ):
        try:
            if not jurisdictions and not states:
                return {
                    "error": "No jurisdictions or states specified",
                    "data": []
                }
            
            data = []
            
            if jurisdictions:
                for jurisdiction in jurisdictions:
                    result = {
                        "jurisdiction": jurisdiction,
                        "sections": [
                            {
                                "section_number": "1.01.020",
                                "title": "Sample Section",
                                "text": "Sample text"
                            }
                        ]
                    }
                    if max_sections_per_jurisdiction:
                        result["sections"] = result["sections"][:max_sections_per_jurisdiction]
                    data.append(result)
            
            elif states:
                for state in states:
                    result = {
                        "jurisdiction": f"Sample City, {state}",
                        "sections": [
                            {
                                "section_number": "1.01.020",
                                "title": "Sample Section",
                                "text": "Sample text"
                            }
                        ]
                    }
                    data.append(result)
                    if max_jurisdictions and len(data) >= max_jurisdictions:
                        break
            
            response = {
                "data": data,
                "output_format": output_format
            }
            
            if include_metadata:
                response["metadata"] = {
                    "scraped_at": "2024-12-08T12:00:00Z",
                    "jurisdictions_count": len(data),
                    "provider": "municode"
                }
            
            return response
        except Exception as e:
            raise FixtureError(f"mock_batch_scrape errored: {e}") from e
    
    return _batch_scrape


@pytest.fixture
def mock_network_timeout():
    """Mock network timeout error."""
    return {"error": "Network timeout", "error_type": "timeout"}


@pytest.fixture
def mock_dns_failure():
    """Mock DNS resolution failure."""
    return {"error": "DNS resolution failed", "error_type": "dns"}


@pytest.fixture
def mock_http_429():
    """Mock HTTP 429 Too Many Requests response."""
    return {"error": "Rate limit exceeded", "error_type": "rate_limit"}


@pytest.fixture
def mock_http_500():
    """Mock HTTP 500 server error."""
    return {"error": "Server error", "error_type": "server_error"}


@pytest.fixture
def mock_invalid_html():
    """Mock invalid HTML response."""
    return {
        "sections": [],
        "note": "Malformed HTML encountered"
    }


@pytest.fixture
def sample_jurisdiction_data():
    """Sample jurisdiction data for testing."""
    return {
        "name": "Seattle, WA",
        "state": "WA",
        "url": "https://library.municode.com/wa/seattle",
        "provider": "municode"
    }


@pytest.fixture
def sample_section_data():
    """Sample code section data for testing."""
    return {
        "section_number": "1.01.020",
        "title": "Definitions",
        "text": "For purposes of this code...",
        "source_url": "https://library.municode.com/wa/seattle/codes/municipal_code?nodeId=TIT1GEPR",
        "scraped_at": "2024-12-08T12:00:00Z"
    }
