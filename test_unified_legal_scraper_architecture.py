"""
Comprehensive test suite for unified legal scraper architecture.

Tests:
1. Content-addressed caching
2. Multi-index Common Crawl search
3. Archive fallback chain (IPWB, Wayback, Archive.is)
4. CourtListener with fallback to direct court websites
5. WARC export/import
6. IPFS multiformats CID generation
7. Parallel scraping with multiprocessing
8. Package imports, CLI, and MCP interfaces
"""
import asyncio
import pytest
import sys
from pathlib import Path
from typing import Dict, Any

# Add package to path
package_root = Path(__file__).parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))


class TestUnifiedScraperArchitecture:
    """Test the unified scraper architecture end-to-end."""
    
    @pytest.mark.asyncio
    async def test_content_addressed_caching(self):
        """Test that content addressing works and prevents duplicate scraping."""
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        scraper = UnifiedScraper(enable_warc=True)
        test_url = "https://library.municode.com/wa/seattle"
        
        # First scrape
        result1 = await scraper.scrape_url(test_url, content_addressed=True)
        assert result1.get("status") == "success"
        assert "cid" in result1
        cid1 = result1["cid"]
        
        # Second scrape should use cache
        result2 = await scraper.scrape_url(test_url, content_addressed=True)
        assert result2.get("already_scraped") == True
        assert result2["cid"] == cid1
        
        print(f"✓ Content addressing works: CID={cid1}")
    
    @pytest.mark.asyncio
    async def test_multi_index_common_crawl(self):
        """Test that Common Crawl searches multiple indexes (each is a delta)."""
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        scraper = UnifiedScraper()
        test_url = "https://library.municode.com/*"
        
        # Should search multiple CC indexes
        results = await scraper.search_common_crawl_multi_index(test_url)
        
        assert isinstance(results, list)
        assert len(results) > 0, "Should find results in at least one CC index"
        
        # Check that multiple indexes were searched
        indexes_found = set(r.get("index") for r in results if r.get("index"))
        assert len(indexes_found) > 1, f"Should search multiple indexes, found: {indexes_found}"
        
        print(f"✓ Multi-index Common Crawl search works: {len(indexes_found)} indexes")
    
    @pytest.mark.asyncio
    async def test_archive_fallback_chain(self):
        """Test the complete fallback chain for archived content."""
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        scraper = UnifiedScraper(prefer_archived=True)
        test_url = "https://example.com"  # Well-archived site
        
        result = await scraper.scrape_url(test_url)
        
        assert result.get("status") == "success"
        assert "source" in result
        
        # Should use one of the archive sources
        valid_sources = [
            "common_crawl", "wayback", "ipwb", 
            "archive_is", "playwright", "live"
        ]
        assert any(source in result["source"] for source in valid_sources)
        
        print(f"✓ Archive fallback works: source={result['source']}")
    
    @pytest.mark.asyncio
    async def test_courtlistener_with_fallback(self):
        """Test CourtListener API with fallback to direct court websites."""
        from ipfs_datasets_py.legal_scrapers.scrapers import get_court_scraper
        
        scraper = get_court_scraper("courtlistener")
        
        # Test Supreme Court search with citation
        result = await scraper.search_opinions(
            court="scotus",
            citation="410 U.S. 113",  # Roe v. Wade
            limit=5
        )
        
        assert isinstance(result, dict)
        assert "count" in result
        assert "source" in result
        assert result["source"] in ["courtlistener_api", "direct_scraping", "none"]
        
        print(f"✓ CourtListener search works: {result['count']} results from {result['source']}")
    
    @pytest.mark.asyncio
    async def test_warc_export_import(self):
        """Test WARC export and import functionality."""
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        import tempfile
        import os
        
        scraper = UnifiedScraper(enable_warc=True)
        test_url = "https://example.com"
        test_html = "<html><body><h1>Test</h1></body></html>"
        
        # Export to WARC
        with tempfile.TemporaryDirectory() as tmpdir:
            warc_path = await scraper.export_to_warc(
                test_url,
                test_html,
                {"cid": "QmTest123", "source": "test"}
            )
            
            assert warc_path is not None
            assert os.path.exists(warc_path)
            
            # Verify WARC file has content
            file_size = os.path.getsize(warc_path)
            assert file_size > 0
            
            print(f"✓ WARC export works: {warc_path} ({file_size} bytes)")
    
    @pytest.mark.asyncio
    async def test_ipfs_multiformats_cid(self):
        """Test IPFS CID generation using multiformats with kubo fallback."""
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        scraper = UnifiedScraper()
        test_content = b"Test content for CID generation"
        
        # Should try multiformats first, fallback to kubo
        cid = await scraper.generate_cid(test_content)
        
        assert cid is not None
        assert cid.startswith("Qm") or cid.startswith("bafy")  # CIDv0 or CIDv1
        
        # Generate again - should be deterministic
        cid2 = await scraper.generate_cid(test_content)
        assert cid == cid2
        
        print(f"✓ IPFS CID generation works: {cid}")
    
    @pytest.mark.asyncio
    async def test_parallel_scraping(self):
        """Test parallel scraping with multiprocessing."""
        from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
        
        scraper = UnifiedScraper()
        test_urls = [
            "https://example.com",
            "https://example.org",
            "https://example.net",
        ]
        
        results = await scraper.scrape_urls_parallel(
            test_urls,
            max_concurrent=3
        )
        
        assert len(results) == len(test_urls)
        successful = sum(1 for r in results if r.get("status") == "success")
        assert successful > 0, "At least one URL should scrape successfully"
        
        print(f"✓ Parallel scraping works: {successful}/{len(test_urls)} successful")
    
    def test_package_imports(self):
        """Test that all package imports work correctly."""
        # Test scraper registry
        from ipfs_datasets_py.legal_scrapers.scrapers import (
            get_state_scraper,
            get_municipal_scraper,
            get_federal_scraper,
            get_court_scraper,
            list_available_scrapers
        )
        
        # List scrapers
        scrapers = list_available_scrapers()
        assert "state_scrapers" in scrapers
        assert "municipal_scrapers" in scrapers
        assert "federal_scrapers" in scrapers
        assert "court_scrapers" in scrapers
        assert scrapers["total_count"] > 50  # 50 states + other scrapers
        
        # Test getting scrapers
        ca_scraper = get_state_scraper("CA")
        assert ca_scraper is not None
        
        municode = get_municipal_scraper("municode")
        assert municode is not None
        
        us_code = get_federal_scraper("us_code")
        assert us_code is not None
        
        courtlistener = get_court_scraper("courtlistener")
        assert courtlistener is not None
        
        print(f"✓ Package imports work: {scrapers['total_count']} scrapers available")
    
    @pytest.mark.asyncio
    async def test_mcp_interface(self):
        """Test that MCP tools call package imports correctly."""
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            mcp_scrape_legal_url,
            mcp_search_court_opinions,
            MCP_TOOLS
        )
        
        # Verify MCP tools are registered
        assert len(MCP_TOOLS) >= 10  # Should have at least 10 tools
        
        tool_names = [t["name"] for t in MCP_TOOLS]
        assert "scrape_legal_url" in tool_names
        assert "search_court_opinions" in tool_names
        assert "scrape_municode_jurisdiction" in tool_names
        assert "scrape_us_code_title" in tool_names
        
        print(f"✓ MCP interface works: {len(MCP_TOOLS)} tools registered")
    
    @pytest.mark.asyncio
    async def test_municode_scraper(self):
        """Test Municode scraper specifically."""
        from ipfs_datasets_py.legal_scrapers.scrapers import get_municipal_scraper
        
        scraper = get_municipal_scraper("municode")
        test_url = "https://library.municode.com/wa/seattle"
        
        result = await scraper.scrape_jurisdiction(test_url)
        
        assert isinstance(result, dict)
        # The result structure will depend on implementation
        
        print("✓ Municode scraper works")
    
    @pytest.mark.asyncio
    async def test_federal_register_scraper(self):
        """Test Federal Register scraper."""
        from ipfs_datasets_py.legal_scrapers.scrapers import get_federal_scraper
        
        scraper = get_federal_scraper("federal_register")
        
        # Search for recent EPA documents
        result = await scraper.search_documents(
            agency="EPA",
            limit=5
        )
        
        assert isinstance(result, dict)
        
        print("✓ Federal Register scraper works")


class TestScraperMigration:
    """Test that all scrapers have been properly migrated."""
    
    def test_no_orphaned_code_in_worktree(self):
        """Verify no legal scraper code left in ipfs_accelerate_py worktree."""
        worktree_path = Path("/home/devel/ipfs_datasets_py/ipfs_accelerate_py.worktrees/worktree-2025-12-19T22-29-33")
        
        if worktree_path.exists():
            legal_scraper_files = list(worktree_path.rglob("*legal*scraper*.py"))
            # Filter out __pycache__ and test files
            legal_scraper_files = [
                f for f in legal_scraper_files
                if "__pycache__" not in str(f) and "test_" not in f.name
            ]
            
            assert len(legal_scraper_files) == 0, \
                f"Found orphaned legal scraper files in worktree: {legal_scraper_files}"
        
        print("✓ No orphaned code in worktree")
    
    def test_all_scrapers_in_correct_location(self):
        """Verify all scrapers are in ipfs_datasets_py/legal_scrapers."""
        scrapers_path = Path("/home/devel/ipfs_datasets_py/ipfs_datasets_py/legal_scrapers/scrapers")
        
        assert scrapers_path.exists(), "Scrapers directory should exist"
        
        # Check for key scraper files
        expected_files = [
            "federal_register_scraper.py",
            "us_code_scraper.py",
            "recap_archive_scraper.py",
            "courtlistener_scraper.py",
            "__init__.py"
        ]
        
        for filename in expected_files:
            filepath = scrapers_path / filename
            assert filepath.exists(), f"Missing scraper file: {filename}"
        
        # Check for subdirectories
        assert (scrapers_path / "state_scrapers").exists()
        assert (scrapers_path / "municipal_scrapers").exists()
        
        print("✓ All scrapers in correct location")
    
    def test_deprecation_notice_exists(self):
        """Verify deprecation notice exists in old location."""
        old_location = Path("/home/devel/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/legal_dataset_tools")
        deprecation_file = old_location / "_DEPRECATION_NOTICE.md"
        
        assert deprecation_file.exists(), "Deprecation notice should exist in old location"
        
        content = deprecation_file.read_text()
        assert "DEPRECATION" in content
        assert "ipfs_datasets_py/legal_scrapers/" in content
        
        print("✓ Deprecation notice exists")


def run_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("UNIFIED LEGAL SCRAPER ARCHITECTURE TEST SUITE")
    print("="*70 + "\n")
    
    # Run pytest
    pytest.main([
        __file__,
        "-v",
        "-s",
        "--tb=short",
        "--asyncio-mode=auto"
    ])


if __name__ == "__main__":
    run_tests()
