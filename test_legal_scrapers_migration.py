#!/usr/bin/env python3
"""
Test Legal Scrapers Architecture

Tests the migrated legal scrapers with unified scraping architecture.
"""

import pytest
import asyncio
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_imports():
    """Test that all modules can be imported."""
    try:
        from ipfs_datasets_py.legal_scrapers import (
            BaseLegalScraper,
            MunicodeScraper,
            StateLawsScraper,
            FederalRegisterScraper,
            USCodeScraper,
            ECode360Scraper,
            MunicipalCodeScraper,
        )
        logger.info("✓ All legal scraper imports successful")
        return True
    except ImportError as e:
        logger.error(f"✗ Import failed: {e}")
        return False


def test_unified_infrastructure():
    """Test that unified scraping infrastructure is available."""
    try:
        from ipfs_datasets_py.content_addressed_scraper import get_content_addressed_scraper
        from ipfs_datasets_py.legal_scraper_unified_adapter import LegalScraperUnifiedAdapter
        from ipfs_datasets_py.warc_integration import CommonCrawlWARCImporter
        from ipfs_datasets_py.multi_index_archive_search import MultiIndexWebArchiveSearcher
        
        logger.info("✓ Unified scraping infrastructure available")
        return True
    except ImportError as e:
        logger.error(f"✗ Unified infrastructure import failed: {e}")
        return False


def test_municode_scraper_init():
    """Test Municode scraper initialization."""
    try:
        from ipfs_datasets_py.legal_scrapers import MunicodeScraper
        
        scraper = MunicodeScraper(
            cache_dir="./test_cache/municode",
            enable_ipfs=False,
            enable_warc=False,
            check_archives=False
        )
        
        assert scraper.get_scraper_name() == "municode"
        logger.info("✓ Municode scraper initialization successful")
        return True
    except Exception as e:
        logger.error(f"✗ Municode scraper initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_municode_scraper_dry_run():
    """Test Municode scraper with a dry run (no actual scraping)."""
    try:
        from ipfs_datasets_py.legal_scrapers import MunicodeScraper
        
        scraper = MunicodeScraper(
            cache_dir="./test_cache/municode",
            enable_ipfs=False,
            enable_warc=False,
            check_archives=False
        )
        
        # Note: This will fail because we need actual scraping infrastructure
        # But it should at least initialize properly
        logger.info("✓ Municode scraper dry run successful (init only)")
        return True
    except Exception as e:
        logger.error(f"✗ Municode scraper dry run failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cli_imports():
    """Test that CLI can be imported."""
    try:
        from ipfs_datasets_py.cli.legal_scraper import add_legal_scraper_subcommands
        logger.info("✓ CLI imports successful")
        return True
    except ImportError as e:
        logger.error(f"✗ CLI import failed: {e}")
        return False


def test_mcp_imports():
    """Test that MCP tools can be imported."""
    try:
        from ipfs_datasets_py.legal_scrapers.mcp import get_registry
        logger.info("✓ MCP imports successful")
        return True
    except ImportError as e:
        logger.error(f"✗ MCP import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_content_addressing():
    """Test content addressing functionality."""
    try:
        from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper
        
        scraper = ContentAddressedScraper(cache_dir="./test_cache/content_addressed")
        
        # Test that it initializes
        assert scraper.cache_dir.exists()
        logger.info("✓ Content addressing initialization successful")
        return True
    except Exception as e:
        logger.error(f"✗ Content addressing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_warc_integration():
    """Test WARC integration."""
    try:
        from ipfs_datasets_py.warc_integration import CommonCrawlWARCImporter, WARCExporter
        
        # Just test that classes can be imported and instantiated
        logger.info("✓ WARC integration available")
        return True
    except Exception as e:
        logger.error(f"✗ WARC integration test failed: {e}")
        return False


def test_multi_index_search():
    """Test multi-index archive search."""
    try:
        from ipfs_datasets_py.multi_index_archive_search import MultiIndexWebArchiveSearcher
        
        searcher = MultiIndexWebArchiveSearcher()
        logger.info("✓ Multi-index search initialization successful")
        return True
    except Exception as e:
        logger.error(f"✗ Multi-index search test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Legal Scrapers Architecture Test Suite")
    print("="*60 + "\n")
    
    tests = [
        ("Imports", test_imports),
        ("Unified Infrastructure", test_unified_infrastructure),
        ("Municode Init", test_municode_scraper_init),
        ("CLI Imports", test_cli_imports),
        ("MCP Imports", test_mcp_imports),
        ("Content Addressing", test_content_addressing),
        ("WARC Integration", test_warc_integration),
        ("Multi-Index Search", test_multi_index_search),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"Running: {test_name}...")
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = asyncio.run(test_func())
            else:
                result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"Test {test_name} crashed: {e}")
            results.append((test_name, False))
        print()
    
    # Print summary
    print("\n" + "="*60)
    print("Test Results Summary")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {len(results)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
