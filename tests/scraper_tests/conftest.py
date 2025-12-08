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
    raise NotImplementedError


@pytest.fixture
def mock_search_jurisdictions():
    """Mock implementation of search_jurisdictions callable."""
    raise NotImplementedError


@pytest.fixture
def mock_scrape_jurisdiction():
    """Mock implementation of scrape_jurisdiction callable."""
    raise NotImplementedError


@pytest.fixture
def mock_batch_scrape():
    """Mock implementation of batch_scrape callable."""
    raise NotImplementedError


@pytest.fixture
def mock_network_timeout():
    """Mock network timeout error."""
    raise NotImplementedError


@pytest.fixture
def mock_dns_failure():
    """Mock DNS resolution failure."""
    raise NotImplementedError


@pytest.fixture
def mock_http_429():
    """Mock HTTP 429 Too Many Requests response."""
    raise NotImplementedError


@pytest.fixture
def mock_http_500():
    """Mock HTTP 500 server error."""
    raise NotImplementedError


@pytest.fixture
def mock_invalid_html():
    """Mock invalid HTML response."""
    raise NotImplementedError


@pytest.fixture
def sample_jurisdiction_data():
    """Sample jurisdiction data for testing."""
    raise NotImplementedError


@pytest.fixture
def sample_section_data():
    """Sample code section data for testing."""
    raise NotImplementedError
