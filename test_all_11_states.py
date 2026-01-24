#!/usr/bin/env python3
"""Test all 11 previously failing state scrapers."""
import anyio
import sys
sys.path.insert(0, '/home/devel/ipfs_datasets_py')

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_scrapers import (
    AlabamaScraper, ConnecticutScraper, DelawareScraper, GeorgiaScraper,
    HawaiiScraper, IndianaScraper, LouisianaScraper, MissouriScraper,
    SouthDakotaScraper, TennesseeScraper, WyomingScraper
)

async def test_scraper(scraper_class, code, name):
    """Test a single scraper."""
    try:
        scraper = scraper_class(code, name)
        codes = scraper.get_code_list()
        
        result = await scraper.scrape_code(codes[0]['name'], codes[0]['url'])
        count = len(result)
        
        status = '✓' if count > 0 else '✗'
        return (status, name, count)
            
    except Exception as e:
        return ('✗', name, 0, str(e)[:80])

async def main():
    """Test all 11 scrapers."""
    states = [
        (AlabamaScraper, "AL", "Alabama"),
        (ConnecticutScraper, "CT", "Connecticut"),
        (DelawareScraper, "DE", "Delaware"),
        (GeorgiaScraper, "GA", "Georgia"),
        (HawaiiScraper, "HI", "Hawaii"),
        (IndianaScraper, "IN", "Indiana"),
        (LouisianaScraper, "LA", "Louisiana"),
        (MissouriScraper, "MO", "Missouri"),
        (SouthDakotaScraper, "SD", "South Dakota"),
        (TennesseeScraper, "TN", "Tennessee"),
        (WyomingScraper, "WY", "Wyoming"),
    ]
    
    results = []
    for scraper_class, code, name in states:
        print(f"Testing {name}...", end=" ", flush=True)
        result = await test_scraper(scraper_class, code, name)
        results.append(result)
        
        if len(result) == 3:
            status, name, count = result
            print(f"{status} {count} statutes")
        else:
            status, name, count, error = result
            print(f"{status} ERROR: {error}")
    
    print(f"\n{'='*60}")
    print("FINAL RESULTS")
    print('='*60)
    
    for result in results:
        if len(result) == 3:
            status, name, count = result
            print(f"{status} {name:20s} {count:3d} statutes")
        else:
            status, name, count, error = result
            print(f"{status} {name:20s} ERROR")
    
    working = sum(1 for r in results if r[2] > 0)
    total = sum(r[2] for r in results)
    
    print('='*60)
    print(f"SUCCESS RATE: {working}/11 states ({working*100//11}%)")
    print(f"TOTAL STATUTES: {total}")
    print('='*60)

if __name__ == "__main__":
    anyio.run(main())
