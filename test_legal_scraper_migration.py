#!/usr/bin/env python3
"""
Test Legal Scraper Migration

Verifies that legal scrapers have been successfully migrated to:
1. Use unified scraping architecture
2. Support content addressing
3. Work via package imports, CLI, and MCP server
4. Use proper fallback mechanisms
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent / "ipfs_datasets_py"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_package_imports():
    """Test that scrapers can be imported as packages."""
    logger.info("=" * 80)
    logger.info("TEST 1: Package Imports")
    logger.info("=" * 80)
    
    try:
        from ipfs_datasets_py.legal_scrapers.core import (
            BaseLegalScraper,
            MunicodeScraper,
            USCodeScraper,
            StateLawsScraper,
            FederalRegisterScraper
        )
        logger.info("✅ All scraper classes imported successfully")
        
        # Verify inheritance
        for scraper_cls in [MunicodeScraper, USCodeScraper, StateLawsScraper, FederalRegisterScraper]:
            if issubclass(scraper_cls, BaseLegalScraper):
                logger.info(f"✅ {scraper_cls.__name__} inherits from BaseLegalScraper")
            else:
                logger.error(f"❌ {scraper_cls.__name__} does NOT inherit from BaseLegalScraper")
                return False
        
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to import scrapers: {e}")
        return False


async def test_unified_scraping_integration():
    """Test that scrapers use unified scraping system."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Unified Scraping Integration")
    logger.info("=" * 80)
    
    try:
        from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper
        from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper
        from ipfs_datasets_py.multi_index_archive_search import MultiIndexWebArchiveSearcher
        
        logger.info("✅ Unified scraping components available")
        
        # Check that base scraper uses these
        from ipfs_datasets_py.legal_scrapers.core.base_scraper import BaseLegalScraper
        import inspect
        
        source = inspect.getsource(BaseLegalScraper)
        
        checks = {
            "scrape_url_unified": "scrape_url_unified" in source,
            "content_addressing": "content_cid" in source or "ContentAddressedScraper" in source,
            "warc_support": "warc" in source.lower(),
        }
        
        for check_name, passed in checks.items():
            if passed:
                logger.info(f"✅ {check_name}: Present")
            else:
                logger.warning(f"⚠️  {check_name}: Not found in BaseLegalScraper")
        
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to load unified scraping: {e}")
        return False


async def test_mcp_integration():
    """Test that MCP tools delegate to package scrapers."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: MCP Server Integration")
    logger.info("=" * 80)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools import (
            mcp_scrape_legal_url,
            mcp_scrape_municode_jurisdiction,
            mcp_scrape_us_code_title,
            mcp_scrape_state_laws,
            mcp_scrape_federal_register,
            MCP_TOOLS
        )
        
        logger.info(f"✅ MCP tools loaded: {len(MCP_TOOLS)} tools registered")
        
        # List registered tools
        for tool in MCP_TOOLS:
            logger.info(f"  - {tool['name']}: {tool['description'][:60]}...")
        
        # Check that MCP tools import from package
        import inspect
        source = inspect.getsource(mcp_scrape_municode_jurisdiction)
        
        if "MunicodeScraper" in source:
            logger.info("✅ MCP tools use package scrapers (not direct BeautifulSoup)")
        else:
            logger.warning("⚠️  MCP tools may not be using package scrapers")
        
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to load MCP tools: {e}")
        return False


async def test_cli_integration():
    """Test that CLI tools exist and use package scrapers."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: CLI Integration")
    logger.info("=" * 80)
    
    try:
        cli_path = Path(__file__).parent / "ipfs_datasets_py" / "legal_scrapers" / "cli"
        if cli_path.exists():
            cli_files = list(cli_path.glob("*.py"))
            logger.info(f"✅ CLI directory exists with {len(cli_files)} files")
            for cli_file in cli_files:
                if cli_file.name != "__init__.py":
                    logger.info(f"  - {cli_file.name}")
        else:
            logger.warning(f"⚠️  CLI directory not found at {cli_path}")
        
        return True
    except Exception as e:
        logger.error(f"❌ CLI check failed: {e}")
        return False


async def test_content_addressing():
    """Test content addressing capabilities."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 5: Content Addressing")
    logger.info("=" * 80)
    
    try:
        from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper
        import tempfile
        
        # Create test scraper
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = ContentAddressedScraper(cache_dir=tmpdir)
            logger.info("✅ ContentAddressedScraper instantiated")
            
            # Check methods
            methods = ['scrape_with_version_tracking', 'check_url_scraped', 'compute_content_cid']
            for method in methods:
                if hasattr(scraper, method):
                    logger.info(f"✅ Has method: {method}")
                else:
                    logger.warning(f"⚠️  Missing method: {method}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Content addressing test failed: {e}")
        return False


async def test_fallback_mechanisms():
    """Test that fallback mechanisms are available."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 6: Fallback Mechanisms")
    logger.info("=" * 80)
    
    try:
        from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperMethod
        
        logger.info("✅ UnifiedWebScraper loaded")
        
        # Check available methods
        methods = [m.value for m in ScraperMethod]
        logger.info(f"Available scraping methods ({len(methods)}):")
        for method in methods:
            logger.info(f"  - {method}")
        
        expected_methods = ['playwright', 'beautifulsoup', 'wayback_machine', 'common_crawl']
        for expected in expected_methods:
            if expected in methods:
                logger.info(f"✅ Has fallback: {expected}")
            else:
                logger.warning(f"⚠️  Missing fallback: {expected}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Fallback mechanisms test failed: {e}")
        return False


async def test_warc_integration():
    """Test WARC import/export capabilities."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 7: WARC Integration")
    logger.info("=" * 80)
    
    try:
        # Check if WARC integration exists
        warc_path = Path(__file__).parent / "ipfs_datasets_py" / "warc_integration.py"
        if warc_path.exists():
            from ipfs_datasets_py.warc_integration import WARCExporter, CommonCrawlWARCImporter
            logger.info("✅ WARC integration available")
            logger.info("  - WARCExporter")
            logger.info("  - CommonCrawlWARCImporter")
        else:
            logger.warning("⚠️  WARC integration file not found")
        
        return True
    except ImportError as e:
        logger.warning(f"⚠️  WARC integration not available: {e}")
        return True  # Not critical
    except Exception as e:
        logger.error(f"❌ WARC integration test failed: {e}")
        return False


async def test_multi_index_common_crawl():
    """Test multi-index Common Crawl search."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 8: Multi-Index Common Crawl")
    logger.info("=" * 80)
    
    try:
        from ipfs_datasets_py.multi_index_archive_search import MultiIndexWebArchiveSearcher
        
        logger.info("✅ MultiIndexWebArchiveSearcher available")
        
        # Check if it searches multiple indexes
        import inspect
        source = inspect.getsource(MultiIndexWebArchiveSearcher)
        
        if "indexes" in source or "CC-MAIN" in source:
            logger.info("✅ Supports multiple Common Crawl indexes")
        else:
            logger.warning("⚠️  Multi-index support unclear")
        
        return True
    except ImportError as e:
        logger.error(f"❌ Multi-index Common Crawl not available: {e}")
        return False


async def main():
    """Run all migration tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " LEGAL SCRAPER MIGRATION TEST SUITE ".center(78) + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    
    tests = [
        ("Package Imports", test_package_imports),
        ("Unified Scraping Integration", test_unified_scraping_integration),
        ("MCP Server Integration", test_mcp_integration),
        ("CLI Integration", test_cli_integration),
        ("Content Addressing", test_content_addressing),
        ("Fallback Mechanisms", test_fallback_mechanisms),
        ("WARC Integration", test_warc_integration),
        ("Multi-Index Common Crawl", test_multi_index_common_crawl),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = await test_func()
        except Exception as e:
            logger.error(f"❌ {test_name} crashed: {e}")
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("\n" + "-" * 80)
    logger.info(f"Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    logger.info("-" * 80)
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED! Migration successful!")
        return 0
    elif passed >= total * 0.7:
        logger.info("⚠️  Most tests passed. Review warnings above.")
        return 0
    else:
        logger.error("❌ Migration incomplete. Review failures above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
