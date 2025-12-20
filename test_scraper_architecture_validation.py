#!/usr/bin/env python3
"""
Quick Validation Test for New Scraper Architecture

This test validates the newly implemented components:
1. Common Crawl multi-index search
2. IPFS CID computation (multiformats + Kubo fallback)
3. Module structure and imports

Run with: python test_scraper_architecture_validation.py
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def test_imports():
    """Test that all modules can be imported."""
    logger.info("Testing imports...")
    
    try:
        # Test scrapers module
        from ipfs_datasets_py.scrapers import (
            UnifiedWebScraper,
            ScraperConfig,
            ScraperMethod,
            ScraperResult,
            ContentAddressedScraper
        )
        logger.info("✅ Scrapers module imports successful")
        
        # Test integrations module
        from ipfs_datasets_py.integrations import (
            CommonCrawlClient,
            CommonCrawlRecord,
            search_common_crawl,
            IPFSCIDComputer,
            compute_cid_for_content,
            compute_cid_for_file,
            get_cid_computer
        )
        logger.info("✅ Integrations module imports successful")
        
        return True
    
    except ImportError as e:
        logger.error(f"❌ Import failed: {e}")
        return False


def test_cid_computation():
    """Test IPFS CID computation."""
    logger.info("\nTesting IPFS CID computation...")
    
    try:
        from ipfs_datasets_py.integrations import compute_cid_for_content
        
        # Test with bytes
        test_data = b"Hello, IPFS!"
        cid = compute_cid_for_content(test_data)
        
        if cid:
            logger.info(f"✅ CID computed successfully: {cid}")
            return True
        else:
            logger.warning("⚠️  CID computation returned None (may need ipfs_multiformats or Kubo)")
            return False
    
    except Exception as e:
        logger.error(f"❌ CID computation failed: {e}")
        return False


def test_common_crawl_client():
    """Test Common Crawl client initialization."""
    logger.info("\nTesting Common Crawl client...")
    
    try:
        from ipfs_datasets_py.integrations import CommonCrawlClient
        
        client = CommonCrawlClient()
        logger.info(f"✅ CommonCrawlClient initialized")
        logger.info(f"   Default indexes: {len(client.DEFAULT_INDEXES)}")
        logger.info(f"   Latest index: {client.DEFAULT_INDEXES[0]}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ CommonCrawlClient initialization failed: {e}")
        return False


def test_unified_scraper():
    """Test UnifiedWebScraper initialization."""
    logger.info("\nTesting UnifiedWebScraper...")
    
    try:
        from ipfs_datasets_py.scrapers import UnifiedWebScraper, ScraperConfig
        
        config = ScraperConfig(timeout=30)
        scraper = UnifiedWebScraper(config)
        logger.info("✅ UnifiedWebScraper initialized")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ UnifiedWebScraper initialization failed: {e}")
        return False


def test_content_addressed_scraper():
    """Test ContentAddressedScraper initialization."""
    logger.info("\nTesting ContentAddressedScraper...")
    
    try:
        from ipfs_datasets_py.scrapers import ContentAddressedScraper
        
        scraper = ContentAddressedScraper()
        logger.info("✅ ContentAddressedScraper initialized")
        logger.info(f"   Cache directory: {scraper.cache_dir}")
        logger.info(f"   Tracked URLs: {len(scraper.url_mappings)}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ ContentAddressedScraper initialization failed: {e}")
        return False


def test_module_structure():
    """Test that module structure is correct."""
    logger.info("\nTesting module structure...")
    
    try:
        # Check scrapers submodules exist
        from ipfs_datasets_py.scrapers import legal, medical, financial
        logger.info("✅ Scrapers submodules (legal, medical, financial) exist")
        
        # Check integrations exists
        from ipfs_datasets_py import integrations
        logger.info("✅ Integrations module exists")
        
        return True
    
    except ImportError as e:
        logger.error(f"❌ Module structure test failed: {e}")
        return False


def main():
    """Run all validation tests."""
    logger.info("=" * 60)
    logger.info("Scraper Architecture Validation Tests")
    logger.info("=" * 60)
    
    tests = [
        ("Module Imports", test_imports),
        ("IPFS CID Computation", test_cid_computation),
        ("Common Crawl Client", test_common_crawl_client),
        ("Unified Web Scraper", test_unified_scraper),
        ("Content Addressed Scraper", test_content_addressed_scraper),
        ("Module Structure", test_module_structure),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"Test '{name}' raised exception: {e}")
            results.append((name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")
    
    logger.info("-" * 60)
    logger.info(f"Passed: {passed}/{total}")
    
    if passed == total:
        logger.info("\n🎉 All tests passed!")
        return 0
    elif passed > 0:
        logger.info(f"\n⚠️  {total - passed} test(s) failed")
        return 1
    else:
        logger.error("\n❌ All tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
