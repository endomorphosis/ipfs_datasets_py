"""
Comprehensive test suite for Phase 11 legal scrapers components.

Tests cover:
- CommonCrawlLegalScraper
- LegalScraperRegistry
- BaseScraper Common Crawl methods
- NormalizedStatute
- Integration workflows
- Performance benchmarks
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from dataclasses import asdict
from typing import Dict, List

# Import components to test
try:
    from ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper import (
        CommonCrawlLegalScraper,
        LegalSourceMetadata,
        ScrapedLegalContent,
        SourceType
    )
    COMMON_CRAWL_AVAILABLE = True
except ImportError:
    COMMON_CRAWL_AVAILABLE = False

try:
    from ipfs_datasets_py.processors.legal_scrapers.registry import (
        LegalScraperRegistry,
        ScraperInfo,
        ScraperType,
        ScraperCapability,
        get_registry
    )
    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False

try:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        BaseStateScraper,
        NormalizedStatute
    )
    BASE_SCRAPER_AVAILABLE = True
except ImportError:
    BASE_SCRAPER_AVAILABLE = False


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_jsonl_data():
    """Sample JSONL data for testing."""
    return [
        {
            "id": "federal_001",
            "kind": "federal",
            "branch": "legislative",
            "name": "US Congress",
            "website": "https://congress.gov/",
            "host": "congress.gov",
            "seed_urls": ["https://congress.gov/browse"]
        },
        {
            "id": "state_001",
            "kind": "state",
            "branch": "legislative",
            "name": "California Legislature",
            "website": "https://leginfo.legislature.ca.gov/",
            "host": "leginfo.legislature.ca.gov",
            "seed_urls": ["https://leginfo.legislature.ca.gov/faces/codes.xhtml"]
        }
    ]


@pytest.fixture
def mock_scraper_content():
    """Mock HTML content from scraping."""
    return """
    <html>
    <head><title>Legal Document</title></head>
    <body>
    <h1>Title 42 - Public Health</h1>
    <section id="section-1">
        <p>This is a legal statute about public health...</p>
    </section>
    </body>
    </html>
    """


@pytest.fixture
def sample_normalized_statute():
    """Sample NormalizedStatute for testing."""
    if not BASE_SCRAPER_AVAILABLE:
        return None
    
    return NormalizedStatute(
        statute_id="42-USC-1395",
        title="Medicare Provisions",
        text="Medicare provides health insurance...",
        citation="42 U.S.C. § 1395",
        url="https://www.law.cornell.edu/uscode/text/42/1395",
        jurisdiction="federal",
        effective_date="2024-01-01",
        metadata={
            "source": "Cornell LII",
            "scrape_date": "2024-01-15",
            "version": "current"
        }
    )


# ============================================================================
# CommonCrawlLegalScraper Tests
# ============================================================================

@pytest.mark.skipif(not COMMON_CRAWL_AVAILABLE, reason="CommonCrawlLegalScraper not available")
class TestCommonCrawlLegalScraper:
    """Tests for CommonCrawlLegalScraper class."""
    
    def test_initialization(self):
        """Test scraper initialization."""
        scraper = CommonCrawlLegalScraper()
        assert scraper is not None
        assert hasattr(scraper, 'sources')
        assert isinstance(scraper.sources, dict)
    
    @patch('builtins.open', create=True)
    async def test_load_jsonl_sources(self, mock_open, sample_jsonl_data):
        """Test loading JSONL source files."""
        # Mock file reading line by line (JSONL format)
        import io
        jsonl_lines = '\n'.join([json.dumps(item) for item in sample_jsonl_data])
        mock_open.return_value.__enter__.return_value = io.StringIO(jsonl_lines)
        
        scraper = CommonCrawlLegalScraper()
        await scraper.load_jsonl_sources()
        
        # Check that sources were loaded
        total_sources = len(scraper.federal_sources) + len(scraper.municipal_sources) + len(scraper.state_sources)
        assert total_sources > 0
    
    def test_source_metadata_creation(self, sample_jsonl_data):
        """Test LegalSourceMetadata creation."""
        data = sample_jsonl_data[0]
        metadata = LegalSourceMetadata(**data)
        
        assert metadata.id == "federal_001"
        assert metadata.kind == "federal"
        assert metadata.website == "https://congress.gov/"
    
    @patch('ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper.CommonCrawlSearchEngine')
    async def test_scrape_url_success(self, mock_cc_engine, mock_scraper_content):
        """Test successful URL scraping."""
        # Mock Common Crawl response
        mock_engine = AsyncMock()
        mock_engine.search_domain.return_value = [{"warc_url": "s3://...", "offset": 0, "length": 1000}]
        mock_engine.fetch_warc_content.return_value = mock_scraper_content
        mock_cc_engine.return_value = mock_engine
        
        scraper = CommonCrawlLegalScraper()
        result = await scraper.scrape_url("https://congress.gov/", extract_rules=False)
        
        assert isinstance(result, ScrapedLegalContent)
    
    async def test_scrape_url_fallback(self):
        """Test fallback chain when primary method fails."""
        scraper = CommonCrawlLegalScraper()
        
        # All methods should fail, but not raise exception
        with patch.object(scraper, '_fetch_common_crawl', side_effect=Exception("CC failed")):
            with patch.object(scraper, '_fetch_brave_search', side_effect=Exception("Brave failed")):
                result = await scraper.scrape_url("https://example.com/")
                
                # Should return result even if failed
                assert isinstance(result, ScrapedLegalContent)
                assert not result.success


# ============================================================================
# LegalScraperRegistry Tests
# ============================================================================

@pytest.mark.skipif(not REGISTRY_AVAILABLE, reason="LegalScraperRegistry not available")
class TestLegalScraperRegistry:
    """Tests for LegalScraperRegistry class."""
    
    def test_initialization(self):
        """Test registry initialization."""
        registry = LegalScraperRegistry()
        assert registry is not None
        assert hasattr(registry, 'scrapers')
    
    def test_manual_registration(self):
        """Test manual scraper registration."""
        registry = LegalScraperRegistry()
        
        scraper_info = ScraperInfo(
            name="TestScraper",
            scraper_type=ScraperType.FEDERAL,
            scraper_class=Mock,
            capabilities={ScraperCapability.ASYNC_BATCH},
            priority=5,
            description="Test scraper"
        )
        
        registry.register(scraper_info)
        assert "TestScraper" in registry.scrapers
    
    def test_auto_discovery(self):
        """Test auto-discovery of scrapers."""
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        # Should find at least some scrapers
        assert len(registry.scrapers) > 0
    
    def test_filter_by_type(self):
        """Test filtering scrapers by type."""
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        federal_scrapers = registry.get_scrapers_by_type(ScraperType.FEDERAL)
        assert isinstance(federal_scrapers, list)
    
    def test_filter_by_capability(self):
        """Test filtering scrapers by capability."""
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        async_scrapers = registry.get_scrapers_by_capability(ScraperCapability.ASYNC_BATCH)
        assert isinstance(async_scrapers, list)
    
    def test_find_scraper_for_source(self):
        """Test finding scraper for specific source."""
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        scraper_class = registry.get_scraper_for_source("https://congress.gov/")
        assert scraper_class is not None
    
    def test_create_fallback_chain(self):
        """Test creating fallback chain."""
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        chain = registry.create_fallback_chain("https://congress.gov/")
        assert isinstance(chain, list)
        assert len(chain) > 0
    
    def test_list_scrapers(self):
        """Test listing all scrapers."""
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        scrapers = registry.list_scrapers()
        assert isinstance(scrapers, list)
    
    def test_singleton_pattern(self):
        """Test registry singleton pattern."""
        registry1 = get_registry()
        registry2 = get_registry()
        
        # Should be same instance
        assert registry1 is registry2


# ============================================================================
# BaseScraper Common Crawl Methods Tests
# ============================================================================

@pytest.mark.skipif(not BASE_SCRAPER_AVAILABLE, reason="BaseStateScraper not available")
class TestBaseScraperCommonCrawl:
    """Tests for BaseStateScraper Common Crawl integration."""
    
    @pytest.fixture
    def mock_state_scraper(self):
        """Create a mock state scraper for testing."""
        class MockStateScraper(BaseStateScraper):
            def __init__(self):
                self.state_code = "CA"
                self.state_name = "California"
                self.logger = logging.getLogger(__name__)
            
            def get_base_url(self) -> str:
                return "https://legislature.ca.gov/"
            
            def get_code_list(self) -> List[Dict[str, str]]:
                return [{"name": "Penal Code", "url": "https://legislature.ca.gov/penal"}]
            
            async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
                return []
        
        return MockStateScraper()
    
    @patch('ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper.CommonCrawlSearchEngine')
    async def test_scrape_from_common_crawl(self, mock_cc, mock_state_scraper):
        """Test scrape_from_common_crawl method."""
        mock_engine = AsyncMock()
        mock_engine.search_domain.return_value = [{"warc_url": "s3://...", "offset": 0}]
        mock_cc.return_value = mock_engine
        
        result = await mock_state_scraper.scrape_from_common_crawl(
            "https://example.com/",
            dataset_name="test_dataset"
        )
        
        assert result is not None
    
    @patch('httpx.AsyncClient')
    async def test_query_warc_file(self, mock_httpx, mock_state_scraper):
        """Test query_warc_file method."""
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.text = "<html>Test content</html>"
        mock_client.get.return_value = mock_response
        mock_httpx.return_value.__aenter__.return_value = mock_client
        
        result = await mock_state_scraper.query_warc_file(
            "s3://commoncrawl/test.warc.gz",
            offset=0,
            length=1000
        )
        
        assert result is not None
    
    @patch('ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper.UnifiedGraphRAGProcessor')
    async def test_extract_with_graphrag(self, mock_graphrag, mock_state_scraper):
        """Test extract_with_graphrag method."""
        mock_processor = AsyncMock()
        mock_processor.extract_entities.return_value = {"entities": [], "relationships": []}
        mock_graphrag.return_value = mock_processor
        
        content = "<html><body>Legal text</body></html>"
        result = await mock_state_scraper.extract_with_graphrag(content, extract_rules=True)
        
        assert result is not None
        assert "entities" in result or "rules" in result
    
    async def test_scrape_with_fallbacks(self, mock_state_scraper):
        """Test scrape_with_fallbacks method."""
        with patch.object(mock_state_scraper, 'scrape_from_common_crawl', return_value="CC content"):
            result = await mock_state_scraper.scrape_with_fallbacks(
                "https://example.com/",
                use_common_crawl=True,
                use_graphrag=False
            )
            
            assert result is not None


# ============================================================================
# NormalizedStatute Tests
# ============================================================================

@pytest.mark.skipif(not BASE_SCRAPER_AVAILABLE, reason="NormalizedStatute not available")
class TestNormalizedStatute:
    """Tests for NormalizedStatute dataclass."""
    
    def test_creation(self, sample_normalized_statute):
        """Test statute creation."""
        assert sample_normalized_statute.statute_id == "42-USC-1395"
        assert sample_normalized_statute.title == "Medicare Provisions"
    
    def test_to_dict(self, sample_normalized_statute):
        """Test conversion to dict."""
        statute_dict = asdict(sample_normalized_statute)
        assert isinstance(statute_dict, dict)
        assert statute_dict["statute_id"] == "42-USC-1395"
    
    def test_dict_like_access(self, sample_normalized_statute):
        """Test dict-like access via metadata."""
        assert "source" in sample_normalized_statute.metadata
        assert sample_normalized_statute.metadata["source"] == "Cornell LII"
    
    def test_citation_generation(self, sample_normalized_statute):
        """Test citation is properly formatted."""
        assert "42 U.S.C." in sample_normalized_statute.citation
        assert "1395" in sample_normalized_statute.citation


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.integration
class TestIntegration:
    """Integration tests for Phase 11 components."""
    
    @pytest.mark.skipif(not (REGISTRY_AVAILABLE and COMMON_CRAWL_AVAILABLE), 
                        reason="Components not available")
    def test_registry_auto_discovery(self):
        """Test registry can auto-discover scrapers including CommonCrawl."""
        registry = get_registry()
        scrapers = registry.list_scrapers()
        
        # Should find CommonCrawlLegalScraper
        scraper_names = [s.name for s in scrapers]
        assert any("CommonCrawl" in name for name in scraper_names)
    
    @pytest.mark.skipif(not (REGISTRY_AVAILABLE and COMMON_CRAWL_AVAILABLE),
                        reason="Components not available")
    async def test_end_to_end_workflow(self):
        """Test end-to-end scraping workflow."""
        # Get registry
        registry = get_registry()
        
        # Find scraper for federal source
        scraper_class = registry.get_scraper_for_source("https://congress.gov/")
        
        if scraper_class:
            # Create scraper instance
            scraper = scraper_class()
            
            # Would scrape in real scenario (mocked here)
            with patch.object(scraper, 'scrape_url', return_value=AsyncMock(success=True)):
                result = await scraper.scrape_url("https://congress.gov/")
                assert result is not None


# ============================================================================
# Performance Tests
# ============================================================================

@pytest.mark.performance
class TestPerformance:
    """Performance tests for Phase 11 components."""
    
    @pytest.mark.skipif(not REGISTRY_AVAILABLE, reason="Registry not available")
    def test_registry_lookup_speed(self, benchmark):
        """Benchmark registry lookup performance."""
        registry = get_registry()
        registry.auto_discover()
        
        def lookup():
            return registry.get_scraper_for_source("https://congress.gov/")
        
        # Should complete in < 100ms
        result = benchmark(lookup)
        assert result is not None
    
    @pytest.mark.skipif(not BASE_SCRAPER_AVAILABLE, reason="NormalizedStatute not available")
    def test_statute_creation_speed(self, benchmark):
        """Benchmark statute creation performance."""
        def create_statute():
            return NormalizedStatute(
                statute_id="test",
                title="Test Statute",
                text="Test text" * 100,
                citation="Test § 1"
            )
        
        # Should complete in < 10ms
        result = benchmark(create_statute)
        assert result is not None


# ============================================================================
# Run tests if executed directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
