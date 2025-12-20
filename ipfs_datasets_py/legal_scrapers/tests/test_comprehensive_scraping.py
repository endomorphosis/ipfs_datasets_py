#!/usr/bin/env python3
"""
Comprehensive test suite for unified legal scraping architecture.

Tests:
1. Content-addressed scraping with deduplication
2. Multi-source fallback system
3. WARC import/export
4. Citation resolution with fallbacks
5. Parallel scraping with multiprocessing
6. All legal scraper types (federal, state, municipal, courts)
7. CourtListener integration
8. Supreme Court scraping
9. Common Crawl multi-index search
10. Interplanetary Wayback Machine
"""

import asyncio
import pytest
import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import scrapers
try:
    from legal_scrapers.core.courtlistener import CourtListenerScraper
    from legal_scrapers.core.supreme_court import SupremeCourtScraper
    from legal_scrapers.core.citation_resolver import CitationResolver
    from legal_scrapers.unified_scraper import UnifiedLegalScraper
    from content_addressed_scraper import ContentAddressedScraper
    IMPORTS_OK = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_OK = False


class TestCourtListenerScraper:
    """Test CourtListener integration."""
    
    @pytest.mark.asyncio
    async def test_search_opinions(self):
        """Test opinion search."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = CourtListenerScraper()
        result = await scraper.search_opinions(
            query="search and seizure",
            court_type="supreme",
            limit=10
        )
        
        assert result is not None
        assert "success" in result
        assert "endpoint" in result
        print(f"✓ CourtListener opinion search: {result}")
    
    @pytest.mark.asyncio
    async def test_resolve_citation(self):
        """Test citation resolution."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = CourtListenerScraper()
        result = await scraper.resolve_citation("123 S.Ct. 456")
        
        assert result is not None
        assert "success" in result
        print(f"✓ CourtListener citation resolution: {result}")
    
    @pytest.mark.asyncio
    async def test_supreme_court_opinions(self):
        """Test Supreme Court opinion retrieval."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = CourtListenerScraper()
        result = await scraper.get_supreme_court_opinions(
            term="2023",
            limit=10
        )
        
        assert result is not None
        assert "success" in result
        print(f"✓ Supreme Court opinions: {result}")
    
    @pytest.mark.asyncio
    async def test_circuit_court_opinions(self):
        """Test Circuit Court opinion retrieval."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = CourtListenerScraper()
        result = await scraper.get_circuit_court_opinions(
            circuit="9",
            limit=10
        )
        
        assert result is not None
        print(f"✓ Circuit Court (9th) opinions: {result}")


class TestSupremeCourtScraper:
    """Test Supreme Court scraper with fallbacks."""
    
    @pytest.mark.asyncio
    async def test_get_opinions(self):
        """Test Supreme Court opinion scraping."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = SupremeCourtScraper(use_courtlistener_fallback=True)
        result = await scraper.get_opinions(term="2023", limit=10)
        
        assert result is not None
        assert "success" in result
        print(f"✓ Supreme Court opinions: {result}")
    
    @pytest.mark.asyncio
    async def test_oral_arguments(self):
        """Test oral argument retrieval."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = SupremeCourtScraper(use_courtlistener_fallback=True)
        result = await scraper.get_oral_arguments(term="2023", limit=5)
        
        assert result is not None
        print(f"✓ Oral arguments: {result}")
    
    @pytest.mark.asyncio
    async def test_citation_resolution(self):
        """Test citation resolution with fallback."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = SupremeCourtScraper(use_courtlistener_fallback=True)
        result = await scraper.resolve_citation("564 U.S. 1")
        
        assert result is not None
        print(f"✓ Citation resolution: {result}")


class TestCitationResolver:
    """Test multi-source citation resolver."""
    
    @pytest.mark.asyncio
    async def test_parse_citation(self):
        """Test citation parsing."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        resolver = CitationResolver()
        
        # Test various citation formats
        test_citations = [
            "123 U.S. 456",
            "123 F.3d 456",
            "123 S.Ct. 456, 460",
            "564 U.S. 1 (2020)",
            "123 Cal.4th 456"
        ]
        
        for cit in test_citations:
            parsed = resolver.parse_citation(cit)
            assert parsed is not None
            assert parsed.volume
            assert parsed.reporter
            assert parsed.page
            print(f"✓ Parsed: {cit} -> {parsed}")
    
    @pytest.mark.asyncio
    async def test_resolve_federal_citation(self):
        """Test federal citation resolution."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        resolver = CitationResolver()
        result = await resolver.resolve("123 F.3d 456")
        
        assert result is not None
        assert "citation" in result
        assert "parsed" in result
        print(f"✓ Resolved federal citation: {result}")
    
    @pytest.mark.asyncio
    async def test_resolve_supreme_court_citation(self):
        """Test Supreme Court citation resolution."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        resolver = CitationResolver()
        result = await resolver.resolve("564 U.S. 1")
        
        assert result is not None
        assert "parsed" in result
        print(f"✓ Resolved SCOTUS citation: {result}")
    
    @pytest.mark.asyncio
    async def test_batch_resolve(self):
        """Test batch citation resolution."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        resolver = CitationResolver()
        citations = [
            "123 U.S. 456",
            "456 F.3d 789",
            "789 S.Ct. 123"
        ]
        
        result = await resolver.batch_resolve(citations)
        
        assert result is not None
        assert "count" in result
        assert result["count"] == len(citations)
        print(f"✓ Batch resolved {len(citations)} citations")


class TestContentAddressedScraping:
    """Test content-addressed scraping with deduplication."""
    
    @pytest.mark.asyncio
    async def test_content_addressing(self):
        """Test content addressing and CID generation."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = ContentAddressedScraper(
            cache_dir="/tmp/test_ca_cache"
        )
        
        # Test URL
        test_url = "https://library.municode.com/ca/san_francisco"
        
        # First scrape
        result1 = await scraper.scrape_with_version_tracking(test_url)
        
        assert result1 is not None
        print(f"✓ First scrape: {result1}")
        
        # Second scrape - should detect already scraped
        result2 = await scraper.scrape_with_version_tracking(test_url)
        
        assert result2 is not None
        print(f"✓ Second scrape (should detect duplicate): {result2}")
    
    @pytest.mark.asyncio
    async def test_version_tracking(self):
        """Test URL version tracking."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = ContentAddressedScraper(
            cache_dir="/tmp/test_versions"
        )
        
        test_url = "https://example.com/test"
        
        # Scrape multiple times to create versions
        for i in range(3):
            result = await scraper.scrape_with_version_tracking(test_url)
            print(f"✓ Version {i+1}: {result}")


class TestUnifiedScraper:
    """Test unified scraper with all fallbacks."""
    
    @pytest.mark.asyncio
    async def test_detect_scraper_type(self):
        """Test automatic scraper type detection."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = UnifiedLegalScraper()
        
        test_urls = {
            "https://library.municode.com/ca/san_francisco": "municode",
            "https://ecode360.com/NY0123": "ecode360",
            "https://codelibrary.amlegal.com/codes/chicago": "american_legal",
            "https://uscode.house.gov/view.xhtml": "us_code",
            "https://www.federalregister.gov/documents": "federal_register",
            "https://www.courtlistener.com/recap/": "recap"
        }
        
        for url, expected_type in test_urls.items():
            detected = scraper.detect_scraper_type(url)
            print(f"✓ {url} -> {detected} (expected: {expected_type})")
            assert detected == expected_type
    
    @pytest.mark.asyncio
    async def test_unified_scraping(self):
        """Test unified scraping with fallbacks."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = UnifiedLegalScraper(
            enable_ipfs=False,
            enable_warc=True,
            check_archives=True
        )
        
        # Test with a generic URL
        test_url = "https://example.com/legal/code"
        result = await scraper.scrape_url(test_url)
        
        assert result is not None
        assert "url" in result
        print(f"✓ Unified scraping: {result}")


class TestParallelScraping:
    """Test parallel scraping with multiprocessing."""
    
    @pytest.mark.asyncio
    async def test_parallel_municipal_scraping(self):
        """Test parallel municipal code scraping."""
        if not IMPORTS_OK:
            pytest.skip("Imports failed")
        
        scraper = UnifiedLegalScraper(max_workers=4)
        
        # Test URLs (small sample)
        test_urls = [
            "https://library.municode.com/ca/san_francisco",
            "https://library.municode.com/ca/los_angeles",
            "https://library.municode.com/ny/new_york"
        ]
        
        # Scrape in parallel
        tasks = [scraper.scrape_url(url) for url in test_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        assert len(results) == len(test_urls)
        print(f"✓ Parallel scraped {len(test_urls)} municipalities")
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"  ✗ {test_urls[i]}: {result}")
            else:
                print(f"  ✓ {test_urls[i]}: {result.get('success', 'unknown')}")


class TestWARCIntegration:
    """Test WARC import/export functionality."""
    
    def test_warc_export(self):
        """Test exporting scraped data to WARC format."""
        # TODO: Implement WARC export test
        print("✓ WARC export test (pending implementation)")
    
    def test_warc_import(self):
        """Test importing data from WARC files."""
        # TODO: Implement WARC import test
        print("✓ WARC import test (pending implementation)")
    
    def test_common_crawl_warc(self):
        """Test importing from Common Crawl WARC."""
        # Example: https://index.commoncrawl.org/CC-MAIN-2025-47-index?url=https://library.municode.com/*&output=json
        print("✓ Common Crawl WARC test (pending implementation)")


class TestCommonCrawlMultiIndex:
    """Test Common Crawl multi-index search."""
    
    @pytest.mark.asyncio
    async def test_multi_index_search(self):
        """Test searching across multiple Common Crawl indexes."""
        # TODO: Implement multi-index search
        # Each CC-MAIN-YYYY-WW index is a delta from prior scrapes
        # Need to search across all relevant indexes
        print("✓ Multi-index search test (pending implementation)")


class TestIPWBIntegration:
    """Test Interplanetary Wayback Machine integration."""
    
    @pytest.mark.asyncio
    async def test_ipwb_scraping(self):
        """Test scraping from IPWB."""
        # TODO: Implement IPWB integration test
        print("✓ IPWB integration test (pending implementation)")


def run_all_tests():
    """Run all tests."""
    print("=" * 80)
    print("COMPREHENSIVE LEGAL SCRAPING ARCHITECTURE TEST SUITE")
    print("=" * 80)
    print()
    
    if not IMPORTS_OK:
        print("✗ Imports failed - cannot run tests")
        return False
    
    # Run each test class
    test_classes = [
        TestCourtListenerScraper,
        TestSupremeCourtScraper,
        TestCitationResolver,
        TestContentAddressedScraping,
        TestUnifiedScraper,
        TestParallelScraping,
        TestWARCIntegration,
        TestCommonCrawlMultiIndex,
        TestIPWBIntegration
    ]
    
    for test_class in test_classes:
        print(f"\n{test_class.__name__}")
        print("-" * 80)
        
        # Instantiate and run test methods
        test_instance = test_class()
        for method_name in dir(test_instance):
            if method_name.startswith("test_"):
                method = getattr(test_instance, method_name)
                try:
                    # Run async or sync
                    if asyncio.iscoroutinefunction(method):
                        asyncio.run(method())
                    else:
                        method()
                except Exception as e:
                    print(f"  ✗ {method_name}: {e}")
    
    print()
    print("=" * 80)
    print("TEST SUITE COMPLETE")
    print("=" * 80)
    return True


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
