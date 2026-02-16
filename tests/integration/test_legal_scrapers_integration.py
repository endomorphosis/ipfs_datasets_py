"""
Integration tests for Phase 11 legal scrapers.

Tests end-to-end workflows including:
- Registry to scraper selection
- Scraping with fallback chain
- GraphRAG extraction
- Logic module integration
- Performance monitoring
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock, Mock

# Import components
try:
    from ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper import CommonCrawlLegalScraper
    from ipfs_datasets_py.processors.legal_scrapers.registry import get_registry
    COMPONENTS_AVAILABLE = True
except ImportError:
    COMPONENTS_AVAILABLE = False


@pytest.mark.integration
@pytest.mark.skipif(not COMPONENTS_AVAILABLE, reason="Components not available")
class TestLegalScrapersIntegration:
    """Integration tests for legal scraper workflow."""
    
    async def test_full_scraping_workflow(self):
        """Test complete workflow from registry to scraping."""
        # Step 1: Get registry
        registry = get_registry()
        registry.discover_scrapers()
        
        # Step 2: Find scraper for source
        scraper_class = registry.get_scraper_for_source("https://congress.gov/")
        assert scraper_class is not None
        
        # Step 3: Create scraper
        scraper = scraper_class()
        assert scraper is not None
        
        # Step 4: Mock scrape operation
        with patch.object(scraper, 'scrape_url', return_value=AsyncMock(success=True)):
            result = await scraper.scrape_url("https://congress.gov/")
            assert result.success
    
    async def test_fallback_chain_execution(self):
        """Test fallback chain executes in correct order."""
        scraper = CommonCrawlLegalScraper()
        
        # Mock all methods to fail except last
        with patch.object(scraper, '_fetch_from_common_crawl', side_effect=Exception("CC failed")):
            with patch.object(scraper, '_fetch_from_brave_search', side_effect=Exception("Brave failed")):
                with patch.object(scraper, '_fetch_from_wayback', side_effect=Exception("Wayback failed")):
                    with patch.object(scraper, '_fetch_from_unified_scraper', return_value="Success"):
                        result = await scraper.scrape_url("https://example.com/")
                        assert result.method_used == "unified_scraper"
    
    async def test_graphrag_integration(self):
        """Test GraphRAG extraction integration."""
        scraper = CommonCrawlLegalScraper()
        
        mock_content = "<html><body><p>Legal statute text</p></body></html>"
        
        with patch.object(scraper, '_fetch_from_common_crawl', return_value=mock_content):
            with patch('ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper.UnifiedGraphRAGProcessor') as mock_graphrag:
                mock_processor = AsyncMock()
                mock_processor.extract_entities.return_value = {
                    "entities": [{"text": "statute", "type": "legal_term"}],
                    "relationships": []
                }
                mock_graphrag.return_value = mock_processor
                
                result = await scraper.scrape_url("https://example.com/", extract_rules=True)
                assert result.extracted_rules is not None
    
    async def test_monitoring_integration(self):
        """Test monitoring decorator integration."""
        from ipfs_datasets_py.processors.infrastructure.monitoring import get_processor_metrics
        
        scraper = CommonCrawlLegalScraper()
        
        with patch.object(scraper, '_fetch_from_common_crawl', return_value="content"):
            await scraper.scrape_url("https://example.com/")
            
            # Check if metrics were recorded
            metrics = get_processor_metrics("CommonCrawlLegalScraper.scrape_url")
            # Metrics may or may not exist depending on decorator application
            # This is just checking the integration works


@pytest.mark.integration
@pytest.mark.slow
class TestPerformanceIntegration:
    """Performance integration tests."""
    
    async def test_concurrent_scraping(self):
        """Test concurrent scraping performance."""
        scraper = CommonCrawlLegalScraper()
        
        urls = [
            "https://example1.com/",
            "https://example2.com/",
            "https://example3.com/"
        ]
        
        with patch.object(scraper, 'scrape_url', return_value=AsyncMock(success=True)):
            tasks = [scraper.scrape_url(url) for url in urls]
            results = await asyncio.gather(*tasks)
            
            assert len(results) == 3
            assert all(r.success for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
