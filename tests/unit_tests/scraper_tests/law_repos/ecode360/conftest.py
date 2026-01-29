"""
Pytest configuration and fixtures for Ecode360 scraper tests.

Background:
    Given the Ecode360 is available at "https://ecode360.com"
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import anyio

aiohttp = pytest.importorskip("aiohttp")

# Add the path directly to avoid triggering __init__.py imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import directly from the module file
from ipfs_datasets_py.legal_scrapers.municipal_law_database_scrapers.ecode360_scraper import (
    search_jurisdictions,
    get_ecode360_jurisdictions,
    scrape_jurisdiction,
    batch_scrape
)


class FixtureError(Exception):
    """Custom exception for fixture-related errors."""
    pass


@pytest.fixture
def ecode360_base_url():
    """Base URL for Ecode360."""
    return "https://ecode360.com"


@pytest.fixture
def mock_response_factory():
    """Factory for creating mock HTTP responses."""
    def _create(status: int, html: str):
        mock_response = AsyncMock()
        mock_response.status = status
        mock_response.text = AsyncMock(return_value=html)
        return mock_response
    return _create


@pytest.fixture
def mock_context_factory():
    """Factory for creating mock context managers."""
    def _create(mock_response):
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None
        return mock_context
    return _create


@pytest.fixture
def create_mock_http(mock_response_factory, mock_context_factory):
    """Complete HTTP mock creation."""
    def _create(status: int, html: str):
        response = mock_response_factory(status, html)
        return mock_context_factory(response)
    return _create


@pytest.fixture
def standard_html_responses():
    """Common HTML response templates."""
    return {
        'valid_section': '<html><body><h1>1.01.020 Section Title</h1><div>Section content</div></body></html>',
        'search_results': '<html><body><a href="/wa/seattle">Seattle, WA</a></body></html>',
        'not_found': '<html><body>Not Found</body></html>',
        'too_many_requests': '<html><body>Too Many Requests</body></html>',
        'server_error': '<html><body>Internal Server Error</body></html>',
        'malformed': '<html><invalid>Malformed HTML<<</html'
    }


@pytest.fixture
def mock_ecode360_search_jurisdictions(create_mock_http, standard_html_responses):
    """
    Fixture that mocks aiohttp responses for search_jurisdictions.
    Returns the actual function but with mocked HTTP calls.
    """
    async def _mock_search(**kwargs):
        mock_context = create_mock_http(200, standard_html_responses['search_results'])
        with patch('aiohttp.ClientSession.get', return_value=mock_context):
            return await search_jurisdictions(**kwargs)
    
    return _mock_search


@pytest.fixture
def mock_ecode360_scrape_jurisdiction(create_mock_http, standard_html_responses):
    """
    Fixture that mocks aiohttp responses for scrape_jurisdiction.
    Returns the actual function but with mocked HTTP calls.
    """
    async def _mock_scrape(**kwargs):
        jurisdiction_url = kwargs.get('jurisdiction_url', '')

        # Detect invalid URLs and return 404
        if 'invalid' in jurisdiction_url.lower():
            mock_context = create_mock_http(404, standard_html_responses['not_found'])
        else:
            mock_context = create_mock_http(200, standard_html_responses['valid_section'])

        with patch('aiohttp.ClientSession.get', return_value=mock_context):
            return await scrape_jurisdiction(**kwargs)
    
    return _mock_scrape


@pytest.fixture
def mock_ecode360_batch_scrape(create_mock_http, standard_html_responses):
    """
    Fixture that mocks aiohttp responses for batch_scrape.
    Returns the actual function but with mocked HTTP calls.
    """
    async def _mock_batch(**kwargs):
        mock_context = create_mock_http(200, standard_html_responses['valid_section'])
        with patch('aiohttp.ClientSession.get', return_value=mock_context):
            return await batch_scrape(**kwargs)

    return _mock_batch


@pytest.fixture
def mock_ecode360_network_timeout():
    """
    Mock network timeout error by patching aiohttp to raise TimeoutError.
    """
    async def _mock_timeout(**kwargs):
        mock_response = AsyncMock()
        mock_response.status = 408
        with patch('aiohttp.ClientSession.get', side_effect=TimeoutError()):
            return await scrape_jurisdiction(**kwargs)

    return _mock_timeout


@pytest.fixture
def mock_ecode360_dns_failure():
    """
    Mock DNS resolution failure by patching aiohttp to raise aiohttp.ClientConnectorError.
    """
    async def _mock_dns(**kwargs):
        with patch('aiohttp.ClientSession.get', side_effect=aiohttp.ClientConnectorError(Mock(), Mock())):
            return await scrape_jurisdiction(**kwargs)
    return _mock_dns


@pytest.fixture
def mock_ecode360_http_429(create_mock_http, standard_html_responses):
    """
    Mock HTTP 429 Too Many Requests response.
    """
    async def _mock_429(**kwargs):
        mock_context = create_mock_http(429, standard_html_responses['too_many_requests'])
        with patch('aiohttp.ClientSession.get', return_value=mock_context):
            return await scrape_jurisdiction(**kwargs)
    
    return _mock_429


@pytest.fixture
def mock_ecode360_http_500(create_mock_http, standard_html_responses):
    """
    Mock HTTP 500 server error.
    """
    async def _mock_500(**kwargs):
        mock_context = create_mock_http(500, standard_html_responses['server_error'])
        with patch('aiohttp.ClientSession.get', return_value=mock_context):
            return await scrape_jurisdiction(**kwargs)
    
    return _mock_500


@pytest.fixture
def mock_ecode360_invalid_html(create_mock_http, standard_html_responses):
    """
    Mock invalid HTML response.
    """
    async def _mock_invalid(**kwargs):
        mock_context = create_mock_http(200, standard_html_responses['malformed'])
        with patch('aiohttp.ClientSession.get', return_value=mock_context):
            return await scrape_jurisdiction(**kwargs)
    
    return _mock_invalid


@pytest.fixture
def sample_jurisdiction_data():
    """Sample jurisdiction data for testing."""
    return {
        "name": "Seattle, WA",
        "state": "WA",
        "url": "https://ecode360.com/wa/seattle",
        "provider": "ecode360"
    }


@pytest.fixture
def sample_section_data():
    """Sample code section data for testing."""
    return {
        "section_number": "1.01.020",
        "title": "Definitions",
        "text": "For purposes of this code...",
        "source_url": "https://ecode360.com/wa/seattle/codes/municipal_code?nodeId=TIT1GEPR",
        "scraped_at": "2024-12-08T12:00:00Z"
    }
