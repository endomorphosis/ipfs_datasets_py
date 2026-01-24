#!/usr/bin/env python3
"""Test all 6 remaining states."""
import anyio
import sys
sys.path.insert(0, '/home/devel/ipfs_datasets_py')

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_scrapers import (
    DelawareScraper, GeorgiaScraper, IndianaScraper, WyomingScraper,
    MissouriScraper, TennesseeScraper
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
        return (name, count, "✓" if count > 0 else "✗")
    except Exception as e:
        print(f"✗ ERROR: {name} - {str(e)[:100]}")
        return (name, 0, "✗")

async def main():
    """Test all 6 states."""
    print("="*70)
    print("TESTING 6 REMAINING STATES")
    print("="*70)
    
    scrapers = [
        (DelawareScraper, "DE", "Delaware"),
        (GeorgiaScraper, "GA", "Georgia"),
        (IndianaScraper, "IN", "Indiana"),
        (WyomingScraper, "WY", "Wyoming"),
        (MissouriScraper, "MO", "Missouri"),
        (TennesseeScraper, "TN", "Tennessee"),
    ]
    
    results = []
    for scraper_class, code, name in scrapers:
        result = await test_scraper(scraper_class, code, name)
        results.append(result)
    
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    for name, count, status in results:
        print(f"{status} {name:20s}: {count:3d} statutes")
    
    working = sum(1 for _, count, _ in results if count > 0)
    total_statutes = sum(count for _, count, _ in results)
    
    print("="*70)
    print(f"States working: {working}/6")
    print(f"Total statutes: {total_statutes}")
    print("="*70)

if __name__ == '__main__':
    anyio.run(main())
