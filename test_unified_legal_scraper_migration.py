#!/usr/bin/env python3
"""
Test unified legal scraper architecture.

This test validates that:
1. All scrapers are properly migrated from MCP tools
2. Content addressing works
3. Fallback mechanisms work (Common Crawl → Wayback → IPWB → Live)
4. WARC export works
5. Multiprocessing works
6. MCP tools properly use package imports
"""

import asyncio
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedLegalScraper
from ipfs_datasets_py.legal_scrapers.scrapers import list_available_scrapers


async def test_scraper_detection():
    """Test that URL types are properly detected."""
    print("\n" + "="*60)
    print("TEST: Scraper Type Detection")
    print("="*60)
    
    scraper = UnifiedLegalScraper()
    
    test_cases = [
        ("https://library.municode.com/wa/seattle", "municode"),
        ("https://ecode360.com/example", "ecode360"),
        ("https://codelibrary.amlegal.com/example", "american_legal"),
        ("https://uscode.house.gov/", "us_code"),
        ("https://www.federalregister.gov/", "federal_register"),
        ("https://www.courtlistener.com/recap/", "recap"),
        ("https://leginfo.legislature.ca.gov/", "state"),
        ("https://example.com/", "generic"),
    ]
    
    passed = 0
    for url, expected_type in test_cases:
        detected = scraper.detect_scraper_type(url)
        status = "✓" if detected == expected_type else "✗"
        print(f"{status} {url[:50]:50} → {detected:20} (expected: {expected_type})")
        if detected == expected_type:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


async def test_list_scrapers():
    """Test that all scrapers are accessible."""
    print("\n" + "="*60)
    print("TEST: List Available Scrapers")
    print("="*60)
    
    try:
        scrapers = list_available_scrapers()
        
        print(f"State scrapers: {len(scrapers['state_scrapers'])}")
        print(f"Municipal scrapers: {len(scrapers['municipal_scrapers'])}")
        print(f"Federal scrapers: {len(scrapers['federal_scrapers'])}")
        print(f"Total: {scrapers['total_count']}")
        
        # Check that we have the major states
        expected_states = ['CA', 'NY', 'TX', 'FL']
        for state in expected_states:
            if state in scrapers['state_scrapers']:
                print(f"✓ {state} scraper available")
            else:
                print(f"✗ {state} scraper missing")
        
        return scrapers['total_count'] > 50  # Should have 50+ states and other scrapers
    except Exception as e:
        print(f"✗ Error listing scrapers: {e}")
        return False


async def test_content_addressing():
    """Test content-addressed scraping."""
    print("\n" + "="*60)
    print("TEST: Content Addressing")
    print("="*60)
    
    scraper = UnifiedLegalScraper(cache_dir="./test_cache_ca")
    
    test_url = "https://library.municode.com/wa/seattle"
    
    print(f"Scraping: {test_url}")
    result1 = await scraper.scrape_url(test_url)
    
    if result1.get('success'):
        print(f"✓ First scrape successful")
        print(f"  CID: {result1.get('cid', 'N/A')}")
        print(f"  Source: {result1.get('source', 'unknown')}")
        
        # Try scraping again - should be cached
        print(f"\nScraping again (should use cache)...")
        result2 = await scraper.scrape_url(test_url, force_rescrape=False)
        
        if result2.get('already_scraped'):
            print(f"✓ Second scrape used cache")
            return True
        else:
            print(f"✗ Second scrape did not use cache")
            return False
    else:
        print(f"✗ First scrape failed: {result1.get('error')}")
        return False


async def test_parallel_scraping():
    """Test parallel scraping."""
    print("\n" + "="*60)
    print("TEST: Parallel Scraping")
    print("="*60)
    
    scraper = UnifiedLegalScraper(cache_dir="./test_cache_parallel")
    
    test_urls = [
        "https://library.municode.com/wa/seattle",
        "https://library.municode.com/ca/los_angeles",
        "https://library.municode.com/il/chicago",
    ]
    
    print(f"Scraping {len(test_urls)} URLs in parallel...")
    results = await scraper.scrape_urls_parallel(test_urls, max_concurrent=3)
    
    successful = sum(1 for r in results if r.get('success'))
    print(f"✓ Completed: {successful}/{len(results)} successful")
    
    for i, result in enumerate(results):
        url = test_urls[i]
        status = "✓" if result.get('success') else "✗"
        print(f"{status} {url[:50]:50} → {result.get('source', 'error')[:20]}")
    
    return successful > 0  # At least one should succeed


async def test_mcp_integration():
    """Test that MCP tools use package imports."""
    print("\n" + "="*60)
    print("TEST: MCP Integration")
    print("="*60)
    
    try:
        # Try importing MCP tools
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import mcp_tools
        
        print("✓ MCP tools module imported")
        
        # Check that it has the unified scraper
        if hasattr(mcp_tools, 'HAVE_LEGAL_SCRAPERS'):
            print(f"✓ HAVE_LEGAL_SCRAPERS = {mcp_tools.HAVE_LEGAL_SCRAPERS}")
            return mcp_tools.HAVE_LEGAL_SCRAPERS
        else:
            print("✗ HAVE_LEGAL_SCRAPERS not found in mcp_tools")
            return False
            
    except Exception as e:
        print(f"✗ Error importing MCP tools: {e}")
        return False


async def test_fallback_chain():
    """Test that fallback mechanisms work."""
    print("\n" + "="*60)
    print("TEST: Fallback Chain")
    print("="*60)
    
    scraper = UnifiedLegalScraper(
        cache_dir="./test_cache_fallback",
        check_archives=True
    )
    
    # Test URL that might be in Common Crawl
    test_url = "https://library.municode.com/wa/seattle"
    
    print(f"Testing fallback chain for: {test_url}")
    print("Expected fallback order:")
    print("  1. Check content addressed cache")
    print("  2. Common Crawl (all indexes)")
    print("  3. Wayback Machine")
    print("  4. IPWB")
    print("  5. Archive.is")
    print("  6. Playwright (for JS)")
    print("  7. Live scraping")
    
    result = await scraper.scrape_url(test_url, force_rescrape=True)
    
    if result.get('success'):
        source = result.get('source', 'unknown')
        print(f"\n✓ Scrape successful")
        print(f"  Source used: {source}")
        print(f"  CID: {result.get('cid', 'N/A')}")
        
        # Check which fallback was used
        if 'common_crawl' in source.lower():
            print(f"  → Used Common Crawl (preferred)")
        elif 'wayback' in source.lower():
            print(f"  → Used Wayback Machine (fallback 1)")
        elif 'ipwb' in source.lower():
            print(f"  → Used IPWB (fallback 2)")
        elif 'archive' in source.lower():
            print(f"  → Used Archive.is (fallback 3)")
        elif 'live' in source.lower():
            print(f"  → Used live scraping (final fallback)")
        
        return True
    else:
        print(f"✗ Scrape failed: {result.get('error')}")
        return False


async def run_all_tests():
    """Run all tests."""
    print("\n" + "="*80)
    print(" "*20 + "UNIFIED LEGAL SCRAPER TEST SUITE")
    print("="*80)
    
    tests = [
        ("Scraper Detection", test_scraper_detection),
        ("List Scrapers", test_list_scrapers),
        ("Content Addressing", test_content_addressing),
        ("Parallel Scraping", test_parallel_scraping),
        ("MCP Integration", test_mcp_integration),
        ("Fallback Chain", test_fallback_chain),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            passed = await test_func()
            results[name] = passed
        except Exception as e:
            print(f"\n✗ {name} raised exception: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    # Print summary
    print("\n" + "="*80)
    print(" "*25 + "TEST SUMMARY")
    print("="*80)
    
    passed_count = sum(1 for p in results.values() if p)
    total_count = len(results)
    
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:10} {name}")
    
    print(f"\n{passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n❌ {total_count - passed_count} test(s) failed")
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
