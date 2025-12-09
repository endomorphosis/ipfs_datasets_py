"""
Pytest configuration and fixtures for American Legal Publishing scraper tests.

Background:
    Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
"""
import pytest


class FixtureError(Exception):
    """Custom exception for fixture-related errors."""
    pass


@pytest.fixture
def american_legal_base_url():
    """
    Base URL for American Legal Publishing.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return "https://codelibrary.amlegal.com"


@pytest.fixture
def mock_american_legal_search_jurisdictions():
    """
    Mock implementation of search_jurisdictions callable for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
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
                        "url": "https://codelibrary.amlegal.com/codes/seattle",
                        "provider": "american_legal"
                    },
                    {
                        "name": "Tacoma, WA",
                        "state": "WA",
                        "url": "https://codelibrary.amlegal.com/codes/tacoma",
                        "provider": "american_legal"
                    }
                ]
            elif state == "CA":
                jurisdictions = [
                    {
                        "name": "Los Angeles, CA",
                        "state": "CA",
                        "url": "https://codelibrary.amlegal.com/codes/losangeles",
                        "provider": "american_legal"
                    },
                    {
                        "name": "San Francisco, CA",
                        "state": "CA",
                        "url": "https://codelibrary.amlegal.com/codes/sanfrancisco",
                        "provider": "american_legal"
                    }
                ]
            elif jurisdiction == "Seattle":
                jurisdictions = [
                    {
                        "name": "Seattle, WA",
                        "state": "WA",
                        "url": "https://codelibrary.amlegal.com/codes/seattle",
                        "provider": "american_legal"
                    }
                ]
            elif keywords:
                jurisdictions = [
                    {
                        "name": "Sample City, XX",
                        "state": "XX",
                        "url": "https://codelibrary.amlegal.com/codes/sample",
                        "provider": "american_legal"
                    }
                ]
            
            jurisdictions = jurisdictions[:limit]
            return {"jurisdictions": jurisdictions}
        except Exception as e:
            raise FixtureError(f"mock_american_legal_search_jurisdictions errored: {e}") from e
    
    return _search


@pytest.fixture
def mock_american_legal_scrape_jurisdiction():
    """
    Mock implementation of scrape_jurisdiction callable for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
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
            raise FixtureError(f"mock_american_legal_scrape_jurisdiction errored: {e}") from e
    
    return _scrape


@pytest.fixture
def mock_american_legal_batch_scrape():
    """
    Mock implementation of batch_scrape callable for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
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
                    "provider": "american_legal"
                }
            
            return response
        except Exception as e:
            raise FixtureError(f"mock_american_legal_batch_scrape errored: {e}") from e
    
    return _batch_scrape


@pytest.fixture
def mock_american_legal_network_timeout():
    """
    Mock network timeout error for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {"error": "Network timeout", "error_type": "timeout"}


@pytest.fixture
def mock_american_legal_dns_failure():
    """
    Mock DNS resolution failure for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {"error": "DNS resolution failed", "error_type": "dns"}


@pytest.fixture
def mock_american_legal_http_429():
    """
    Mock HTTP 429 Too Many Requests response for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {"error": "Rate limit exceeded", "error_type": "rate_limit"}


@pytest.fixture
def mock_american_legal_http_500():
    """
    Mock HTTP 500 server error for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {"error": "Server error", "error_type": "server_error"}


@pytest.fixture
def mock_american_legal_invalid_html():
    """
    Mock invalid HTML response for American Legal.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {
        "sections": [],
        "note": "Malformed HTML encountered"
    }


@pytest.fixture
def sample_american_legal_jurisdiction_data():
    """
    Sample jurisdiction data for American Legal testing.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {
        "name": "Seattle, WA",
        "state": "WA",
        "url": "https://codelibrary.amlegal.com/codes/seattle",
        "provider": "american_legal"
    }


@pytest.fixture
def sample_american_legal_section_data():
    """
    Sample code section data for American Legal testing.
    
    Background:
        Given the American Legal Publishing is available at "https://codelibrary.amlegal.com"
    """
    return {
        "section_number": "1.01.020",
        "title": "Definitions",
        "text": "For purposes of this code...",
        "source_url": "https://codelibrary.amlegal.com/codes/seattle/1_01_020",
        "scraped_at": "2024-12-08T12:00:00Z"
    }
