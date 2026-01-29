#!/usr/bin/env python3
"""
Test script for the unified web scraper system.

This script tests the unified scraper's functionality including:
- Method availability checking
- Single URL scraping
- Multiple URL scraping
- Fallback mechanisms
"""

import sys
import anyio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent / '../..'))

try:
    from ipfs_datasets_py.web_archiving.unified_web_scraper import (
        UnifiedWebScraper,
        ScraperConfig,
        ScraperMethod,
        scrape_url,
        scrape_urls
    )
    print("✓ Successfully imported unified_web_scraper")
except ImportError as e:
    print(f"✗ Failed to import unified_web_scraper: {e}")
    sys.exit(1)


def test_method_availability():
    """Test checking available scraping methods."""
    print("\n" + "="*60)
    print("Testing Method Availability")
    print("="*60)
    
    scraper = UnifiedWebScraper()
    
    print("\nAvailable Methods:")
    for method in ScraperMethod:
        available = scraper.available_methods.get(method, False)
        status = "✓" if available else "✗"
        print(f"  {status} {method.value}")
    
    available_count = sum(scraper.available_methods.values())
    print(f"\nTotal available: {available_count}/{len(ScraperMethod)}")
    
    return available_count > 0


def test_single_url_scraping():
    """Test scraping a single URL."""
    print("\n" + "="*60)
    print("Testing Single URL Scraping")
    print("="*60)
    
    test_url = "http://example.com"
    print(f"\nScraping: {test_url}")
    
    try:
        result = scrape_url(test_url)
        
        if result.success:
            print(f"✓ Successfully scraped using {result.method_used.value if result.method_used else 'unknown'}")
            print(f"  Title: {result.title[:50]}..." if len(result.title) > 50 else f"  Title: {result.title}")
            print(f"  Content length: {len(result.content)} chars")
            print(f"  Links found: {len(result.links)}")
            print(f"  Extraction time: {result.extraction_time:.2f}s")
            return True
        else:
            print(f"✗ Failed to scrape")
            print("  Errors:")
            for error in result.errors:
                print(f"    - {error}")
            return False
    
    except Exception as e:
        print(f"✗ Exception during scraping: {e}")
        return False


def test_multiple_url_scraping():
    """Test scraping multiple URLs."""
    print("\n" + "="*60)
    print("Testing Multiple URL Scraping")
    print("="*60)
    
    test_urls = [
        "http://example.com",
        "http://example.org",
    ]
    
    print(f"\nScraping {len(test_urls)} URLs...")
    
    try:
        results = scrape_urls(test_urls)
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        print(f"\nResults: {successful} successful, {failed} failed")
        
        for i, result in enumerate(results, 1):
            if result.success:
                print(f"  [{i}] ✓ {result.url} ({result.method_used.value if result.method_used else 'unknown'})")
            else:
                error = result.errors[0] if result.errors else "Unknown error"
                print(f"  [{i}] ✗ {result.url} - {error}")
        
        return successful > 0
    
    except Exception as e:
        print(f"✗ Exception during multi-URL scraping: {e}")
        return False


def test_specific_method():
    """Test scraping with a specific method."""
    print("\n" + "="*60)
    print("Testing Specific Method")
    print("="*60)
    
    scraper = UnifiedWebScraper()
    
    # Find first available method
    available_method = None
    for method in ScraperMethod:
        if scraper.available_methods.get(method, False):
            available_method = method
            break
    
    if not available_method:
        print("✗ No methods available for testing")
        return False
    
    print(f"\nTesting with {available_method.value}...")
    
    try:
        result = scraper.scrape_sync("http://example.com", method=available_method)
        
        if result.success:
            print(f"✓ Successfully scraped using {result.method_used.value if result.method_used else 'unknown'}")
            return True
        else:
            print(f"✗ Failed to scrape with {available_method.value}")
            print(f"  Errors: {result.errors}")
            return False
    
    except Exception as e:
        print(f"✗ Exception: {e}")
        return False


def test_fallback_mechanism():
    """Test the fallback mechanism."""
    print("\n" + "="*60)
    print("Testing Fallback Mechanism")
    print("="*60)
    
    config = ScraperConfig(fallback_enabled=True)
    scraper = UnifiedWebScraper(config)
    
    print("\nTrying to scrape with fallback enabled...")
    print("The scraper will try methods in sequence:")
    for i, method in enumerate(config.preferred_methods, 1):
        available = scraper.available_methods.get(method, False)
        status = "available" if available else "not available"
        print(f"  {i}. {method.value} ({status})")
    
    try:
        result = scraper.scrape_sync("http://example.com")
        
        if result.success:
            print(f"\n✓ Fallback succeeded with {result.method_used.value if result.method_used else 'unknown'}")
            return True
        else:
            print(f"\n✗ All fallback methods failed")
            print("Errors encountered:")
            for error in result.errors:
                print(f"  - {error}")
            return False
    
    except Exception as e:
        print(f"✗ Exception: {e}")
        return False


async def test_async_scraping():
    """Test asynchronous scraping."""
    print("\n" + "="*60)
    print("Testing Async Scraping")
    print("="*60)
    
    scraper = UnifiedWebScraper()
    
    print("\nScraping asynchronously...")
    
    try:
        result = await scraper.scrape("http://example.com")
        
        if result.success:
            print(f"✓ Async scraping succeeded with {result.method_used.value if result.method_used else 'unknown'}")
            return True
        else:
            print("✗ Async scraping failed")
            return False
    
    except Exception as e:
        print(f"✗ Exception: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("UNIFIED WEB SCRAPER - Test Suite")
    print("="*60)
    
    results = {
        "Method Availability": test_method_availability(),
        "Single URL Scraping": test_single_url_scraping(),
        "Multiple URL Scraping": test_multiple_url_scraping(),
        "Specific Method": test_specific_method(),
        "Fallback Mechanism": test_fallback_mechanism(),
        "Async Scraping": anyio.run(test_async_scraping())
    }
    
    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(results.values())
    failed = total - passed
    
    print(f"\nTotal: {total} tests, {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
