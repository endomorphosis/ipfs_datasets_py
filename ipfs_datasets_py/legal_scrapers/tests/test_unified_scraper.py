"""
Test Suite for Unified Legal Scraper

Tests content addressing, multi-source fallback, WARC export,
Common Crawl integration, and scraper migration.
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Import modules to test
try:
    from .unified_legal_scraper import (
        UnifiedLegalScraper,
        LegalScraperResult,
        scrape_legal_url,
        scrape_legal_urls
    )
    from .scraper_adapter import (
        ScraperAdapter,
        scrape_html,
        scrape_soup,
        MigrationHelper
    )
    from .mcp_tools import (
        mcp_scrape_legal_url,
        mcp_scrape_legal_urls_bulk,
        mcp_search_common_crawl,
        mcp_check_url_cached
    )
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestUnifiedLegalScraper:
    """Test UnifiedLegalScraper class."""
    
    @pytest.fixture
    def temp_cache(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def scraper(self, temp_cache):
        """Create scraper instance with temp cache."""
        return UnifiedLegalScraper(
            cache_dir=temp_cache,
            use_ipfs_daemon=False,
            enable_warc=True
        )
    
    @pytest.mark.asyncio
    async def test_generate_cid(self, scraper):
        """Test CID generation."""
        content = "Hello, IPFS!"
        cid = await scraper.generate_cid(content)
        
        assert cid is not None
        assert len(cid) > 0
        
        # Should be deterministic
        cid2 = await scraper.generate_cid(content)
        assert cid == cid2
    
    @pytest.mark.asyncio
    async def test_check_already_scraped_empty(self, scraper):
        """Test checking cache when empty."""
        result = await scraper.check_already_scraped("https://example.com")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_persistence(self, scraper):
        """Test that cache persists across operations."""
        url = "https://example.com"
        
        # Add to cache manually
        scraper.url_cache[url] = [{
            "cid": "QmTest123",
            "timestamp": "2025-01-01T00:00:00",
            "source": "test"
        }]
        scraper._save_url_cache()
        
        # Check it's cached
        cached = await scraper.check_already_scraped(url)
        assert cached is not None
        assert cached['latest']['cid'] == "QmTest123"
    
    @pytest.mark.asyncio
    async def test_search_common_crawl_mock(self, scraper):
        """Test Common Crawl search with mocked responses."""
        with patch('aiohttp.ClientSession') as mock_session:
            # Mock response
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value="""
{"url": "https://example.com", "timestamp": "20250101000000", "mime": "text/html"}
{"url": "https://example.com/page2", "timestamp": "20250101010000", "mime": "text/html"}
""")
            
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_resp
            
            results = await scraper.search_common_crawl("https://example.com")
            
            assert len(results) == 2
            assert results[0]['url'] == "https://example.com"
    
    @pytest.mark.asyncio
    async def test_scrape_url_result_structure(self, scraper):
        """Test that scrape_url returns correct result structure."""
        # This will likely fail to actually scrape, but should return valid structure
        result = await scraper.scrape_url("https://example.com", prefer_archived=False)
        
        assert isinstance(result, LegalScraperResult)
        assert result.url == "https://example.com"
        assert hasattr(result, 'success')
        assert hasattr(result, 'cid')
        assert hasattr(result, 'source')
        assert hasattr(result, 'already_scraped')
    
    @pytest.mark.asyncio
    async def test_export_to_warc_structure(self, scraper):
        """Test WARC export creates file."""
        url = "https://example.com"
        html = "<html><body>Test</body></html>"
        metadata = {"test": "data"}
        
        warc_path = await scraper.export_to_warc(url, html, metadata)
        
        if warc_path:  # Only if warcio is available
            assert Path(warc_path).exists()
            assert Path(warc_path).suffix == ".gz"


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestScraperAdapter:
    """Test ScraperAdapter class."""
    
    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        return ScraperAdapter(prefer_archived=True)
    
    @pytest.mark.asyncio
    async def test_get_html_returns_string_or_none(self, adapter):
        """Test get_html return type."""
        # Mock the scraper
        with patch.object(adapter.scraper, 'scrape_url') as mock_scrape:
            mock_result = Mock()
            mock_result.success = True
            mock_result.html = "<html>Test</html>"
            mock_scrape.return_value = mock_result
            
            html = await adapter.get_html("https://example.com")
            
            assert html == "<html>Test</html>"
    
    @pytest.mark.asyncio
    async def test_get_soup_returns_beautifulsoup(self, adapter):
        """Test get_soup returns BeautifulSoup object."""
        with patch.object(adapter, 'get_html') as mock_get_html:
            mock_get_html.return_value = "<html><body><h1>Test</h1></body></html>"
            
            soup = await adapter.get_soup("https://example.com")
            
            if soup:  # Only if BeautifulSoup is available
                assert soup.find('h1').text == "Test"
    
    @pytest.mark.asyncio
    async def test_scrape_urls_bulk(self, adapter):
        """Test bulk scraping."""
        urls = ["https://example.com", "https://example.org"]
        
        with patch.object(adapter.scraper, 'scrape_urls_parallel') as mock_scrape:
            # Mock results
            mock_results = [
                Mock(url=urls[0], success=True, html="<html>1</html>"),
                Mock(url=urls[1], success=True, html="<html>2</html>")
            ]
            mock_scrape.return_value = mock_results
            
            results = await adapter.scrape_urls_bulk(urls)
            
            assert len(results) == 2
            assert results[urls[0]] == "<html>1</html>"


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestMigrationHelper:
    """Test MigrationHelper class."""
    
    def test_convert_requests_get(self):
        """Test conversion of requests.get patterns."""
        old_code = """
html = requests.get(url).text
data = requests.get(api_url).json()
soup = BeautifulSoup(requests.get(url).text, 'html.parser')
"""
        
        new_code = MigrationHelper.convert_requests_get(old_code)
        
        assert "await adapter.get_html(url)" in new_code
        assert "await adapter.get_json(api_url)" in new_code
        assert "await adapter.get_soup(url" in new_code
    
    def test_generate_migration_report(self):
        """Test migration report generation."""
        # Create temporary file with old patterns
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
import requests
from bs4 import BeautifulSoup

def scrape():
    html = requests.get('https://example.com').text
    soup = BeautifulSoup(html, 'html.parser')
""")
            temp_file = Path(f.name)
        
        try:
            report = MigrationHelper.generate_migration_report(temp_file)
            
            assert 'patterns_found' in report
            assert report['needs_migration'] == True
            assert len(report['patterns_found']) > 0
        finally:
            temp_file.unlink()


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestMCPTools:
    """Test MCP tool functions."""
    
    @pytest.mark.asyncio
    async def test_mcp_scrape_legal_url_structure(self):
        """Test MCP tool returns correct structure."""
        result = await mcp_scrape_legal_url(
            "https://example.com",
            force_rescrape=False,
            prefer_archived=True
        )
        
        assert isinstance(result, dict)
        assert 'success' in result
        assert 'url' in result
        assert result['url'] == "https://example.com"
    
    @pytest.mark.asyncio
    async def test_mcp_scrape_bulk_structure(self):
        """Test MCP bulk scrape returns correct structure."""
        urls = ["https://example.com", "https://example.org"]
        
        result = await mcp_scrape_legal_urls_bulk(
            urls,
            max_concurrent=2
        )
        
        assert isinstance(result, dict)
        assert 'success' in result
        assert 'total' in result
        assert result['total'] == 2
        assert 'results' in result
    
    @pytest.mark.asyncio
    async def test_mcp_check_url_cached_structure(self):
        """Test MCP cache check returns correct structure."""
        result = await mcp_check_url_cached("https://example.com")
        
        assert isinstance(result, dict)
        assert 'cached' in result
        assert 'url' in result
        assert 'versions' in result


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Required modules not available")
class TestIntegration:
    """Integration tests for the complete system."""
    
    @pytest.mark.asyncio
    async def test_scrape_and_cache(self):
        """Test complete scrape -> cache -> retrieve flow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            
            # First scrape
            scraper1 = UnifiedLegalScraper(cache_dir=cache_dir)
            
            # Mock a successful scrape
            with patch.object(scraper1, 'unified_scraper') as mock_unified:
                mock_result = Mock()
                mock_result.success = True
                mock_result.html = "<html>Test</html>"
                mock_result.title = "Test"
                mock_result.text = "Test"
                mock_result.method_used = Mock(value="test")
                mock_unified.scrape = AsyncMock(return_value=mock_result)
                
                result1 = await scraper1.scrape_url("https://example.com")
                
                assert result1.success
                assert result1.cid is not None
            
            # Create new scraper with same cache
            scraper2 = UnifiedLegalScraper(cache_dir=cache_dir)
            
            # Check cache
            cached = await scraper2.check_already_scraped("https://example.com")
            
            assert cached is not None
            assert len(cached['versions']) > 0
    
    @pytest.mark.asyncio
    async def test_parallel_scraping(self):
        """Test parallel scraping of multiple URLs."""
        urls = [
            "https://example.com",
            "https://example.org",
            "https://example.net"
        ]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = UnifiedLegalScraper(cache_dir=Path(tmpdir))
            
            # Mock successful scrapes
            with patch.object(scraper, 'scrape_url') as mock_scrape:
                async def mock_scrape_url(url, **kwargs):
                    return LegalScraperResult(
                        url=url,
                        success=True,
                        html=f"<html>{url}</html>",
                        cid=f"Qm{hash(url)}"
                    )
                
                mock_scrape.side_effect = mock_scrape_url
                
                results = await scraper.scrape_urls_parallel(urls, max_concurrent=2)
                
                assert len(results) == 3
                assert all(r.success for r in results)


def test_imports():
    """Test that all modules can be imported."""
    assert IMPORTS_AVAILABLE, "Required modules not available"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
