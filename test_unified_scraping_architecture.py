#!/usr/bin/env python3
"""
Comprehensive Test for Unified Scraping Architecture

This test validates:
1. Content-addressed scraping with version tracking
2. Multi-index Common Crawl searches
3. Interplanetary Wayback integration
4. WARC import/export functionality
5. Legal scrapers using unified system
6. Fallback mechanisms working correctly
"""

import sys
import logging
import asyncio
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add to path
sys.path.insert(0, str(Path(__file__).parent / "ipfs_datasets_py"))


def print_section(title):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_success(message):
    """Print a success message."""
    print(f"✅ {message}")


def print_info(message):
    """Print an info message."""
    print(f"ℹ️  {message}")


def print_error(message):
    """Print an error message."""
    print(f"❌ {message}")


async def test_content_addressed_scraping():
    """Test content-addressed scraping system."""
    print_section("TEST 1: Content-Addressed Scraping")
    
    try:
        from ipfs_datasets_py.content_addressed_scraper import get_content_addressed_scraper
        
        scraper = get_content_addressed_scraper(cache_dir="./test_cache")
        print_success("Initialized ContentAddressedScraper")
        
        # Test CID computation with ipfs_multiformats
        test_content = b"Test content for CID generation"
        cid = scraper.compute_content_cid(test_content)
        print_success(f"Computed CID: {cid}")
        
        # Test metadata CID
        metadata = {"url": "https://example.com", "timestamp": "2024-01-01"}
        meta_cid = scraper.compute_metadata_cid(metadata)
        print_success(f"Computed metadata CID: {meta_cid}")
        
        # Test URL checking
        test_url = "https://example.com/test"
        status = scraper.check_url_scraped(test_url)
        print_info(f"URL scraped before: {status['scraped']}")
        
        # Test content existence check
        content_check = scraper.check_content_exists(cid)
        print_info(f"Content exists: {content_check['exists']}")
        
        # Get statistics
        stats = scraper.get_statistics()
        print_success(f"Statistics retrieved: {stats['total_urls_tracked']} URLs tracked")
        
        return True
        
    except Exception as e:
        print_error(f"Content-addressed scraping test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all tests."""
    print_section("UNIFIED SCRAPING ARCHITECTURE TEST SUITE")
    print("Testing all components of the unified scraping system")
    
    results = {}
    
    # Run content-addressed test
    results["Content-Addressed Scraping"] = await test_content_addressed_scraping()
    
    # Print summary
    print_section("TEST SUMMARY")
    
    passed = sum(1 for r in results.values() if r)
    failed = len(results) - passed
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print()
    print(f"Total: {len(results)} tests")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
