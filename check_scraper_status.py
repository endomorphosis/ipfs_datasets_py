#!/usr/bin/env python3
"""Quick status check for state scrapers."""
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
        status = "✓" if count > 0 else "✗"
        return f"{status} {name:20s} ({code}): {count:3d} statutes"
    except Exception as e:
        return f"✗ {name:20s} ({code}): ERROR - {str(e)[:50]}"

async def main():
    """Test all scrapers."""
    print("\n" + "="*60)
    print("SCRAPER STATUS CHECK")
    print("="*60 + "\n")
    
    scrapers = [
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
    for scraper_class, code, name in scrapers:
        result = await test_scraper(scraper_class, code, name)
        results.append(result)
        print(result)
    
    # Summary
    working = sum(1 for r in results if r.startswith("✓"))
    total = len(results)
    
    print("\n" + "="*60)
    print(f"SUMMARY: {working}/{total} scrapers working ({working*100//total}%)")
    print("="*60)

if __name__ == '__main__':
    anyio.run(main())
