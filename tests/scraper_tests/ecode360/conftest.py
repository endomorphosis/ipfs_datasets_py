"""
Pytest configuration and fixtures for Ecode360 scraper tests.

Background:
    Given the Ecode360 is available at "https://ecode360.com"
"""
import pytest


class FixtureError(Exception):
    """Custom exception for fixture-related errors."""
    pass


@pytest.fixture
def ecode360_base_url():
    """
    Base URL for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return "https://ecode360.com"


@pytest.fixture
def mock_ecode360_search_jurisdictions():
    """
    Mock implementation of search_jurisdictions callable for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
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
                        "url": "https://ecode360.com/seattle",
                        "provider": "ecode360"
                    },
                    {
                        "name": "Tacoma, WA",
                        "state": "WA",
                        "url": "https://ecode360.com/tacoma",
                        "provider": "ecode360"
                    }
                ]
            elif state == "CA":
                jurisdictions = [
                    {
                        "name": "Los Angeles, CA",
                        "state": "CA",
                        "url": "https://ecode360.com/losangeles",
                        "provider": "ecode360"
                    },
                    {
                        "name": "San Francisco, CA",
                        "state": "CA",
                        "url": "https://ecode360.com/sanfrancisco",
                        "provider": "ecode360"
                    }
                ]
            elif jurisdiction == "Seattle":
                jurisdictions = [
                    {
                        "name": "Seattle, WA",
                        "state": "WA",
                        "url": "https://ecode360.com/seattle",
                        "provider": "ecode360"
                    }
                ]
            elif keywords:
                jurisdictions = [
                    {
                        "name": "Sample City, XX",
                        "state": "XX",
                        "url": "https://ecode360.com/sample",
                        "provider": "ecode360"
                    }
                ]
            
            jurisdictions = jurisdictions[:limit]
            return {"jurisdictions": jurisdictions}
        except Exception as e:
            raise FixtureError(f"mock_ecode360_search_jurisdictions errored: {e}") from e
    
    return _search


@pytest.fixture
def mock_ecode360_scrape_jurisdiction():
    """
    Mock implementation of scrape_jurisdiction callable for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
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
            raise FixtureError(f"mock_ecode360_scrape_jurisdiction errored: {e}") from e
    
    return _scrape


@pytest.fixture
def mock_ecode360_batch_scrape():
    """
    Mock implementation of batch_scrape callable for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
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
                    "provider": "ecode360"
                }
            
            return response
        except Exception as e:
            raise FixtureError(f"mock_ecode360_batch_scrape errored: {e}") from e
    
    return _batch_scrape


@pytest.fixture
def mock_ecode360_network_timeout():
    """
    Mock network timeout error for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {"error": "Network timeout", "error_type": "timeout"}


@pytest.fixture
def mock_ecode360_dns_failure():
    """
    Mock DNS resolution failure for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {"error": "DNS resolution failed", "error_type": "dns"}


@pytest.fixture
def mock_ecode360_http_429():
    """
    Mock HTTP 429 Too Many Requests response for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {"error": "Rate limit exceeded", "error_type": "rate_limit"}


@pytest.fixture
def mock_ecode360_http_500():
    """
    Mock HTTP 500 server error for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {"error": "Server error", "error_type": "server_error"}


@pytest.fixture
def mock_ecode360_invalid_html():
    """
    Mock invalid HTML response for Ecode360.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {
        "sections": [],
        "note": "Malformed HTML encountered"
    }


@pytest.fixture
def sample_ecode360_jurisdiction_data():
    """
    Sample jurisdiction data for Ecode360 testing.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {
        "name": "Seattle, WA",
        "state": "WA",
        "url": "https://ecode360.com/seattle",
        "provider": "ecode360"
    }


@pytest.fixture
def sample_ecode360_section_data():
    """
    Sample code section data for Ecode360 testing.
    
    Background:
        Given the Ecode360 is available at "https://ecode360.com"
    """
    return {
        "section_number": "1.01.020",
        "title": "Definitions",
        "text": "For purposes of this code...",
        "source_url": "https://ecode360.com/seattle/1_01_020",
        "scraped_at": "2024-12-08T12:00:00Z"
    }
