#!/usr/bin/env python3
"""Test Playwright-enabled scrapers."""
import asyncio
import sys
sys.path.insert(0, '/home/devel/ipfs_datasets_py')

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_scrapers import (
    DelawareScraper, GeorgiaScraper, IndianaScraper, WyomingScraper
)

async def test_scraper(scraper_class, code, name):
    """Test a single scraper."""
    try:
        print(f"\nTesting {name} ({code})...")
        scraper = scraper_class(code, name)
        codes = scraper.get_code_list()
        result = await scraper.scrape_code(codes[0]['name'], codes[0]['url'])
        count = len(result)
        status = "✓ SUCCESS" if count > 0 else "✗ FAILED"
        print(f"{status}: {name} - {count} statutes")
        if count > 0:
            print(f"  Sample: {result[0].section_name[:60]}...")
        return count
    except Exception as e:
        print(f"✗ ERROR: {name} - {str(e)[:100]}")
        import traceback
        traceback.print_exc()
        return 0

async def main():
    """Test all Playwright scrapers."""
    print("="*60)
    print("TESTING PLAYWRIGHT-ENABLED SCRAPERS")
    print("="*60)
    
    scrapers = [
        (DelawareScraper, "DE", "Delaware"),
        (GeorgiaScraper, "GA", "Georgia"),
        (IndianaScraper, "IN", "Indiana"),
        (WyomingScraper, "WY", "Wyoming"),
    ]
    
    total = 0
    for scraper_class, code, name in scrapers:
        count = await test_scraper(scraper_class, code, name)
        total += count
    
    print("\n" + "="*60)
    print(f"TOTAL: {total} statutes scraped from 4 states")
    print("="*60)

if __name__ == '__main__':
    asyncio.run(main())
