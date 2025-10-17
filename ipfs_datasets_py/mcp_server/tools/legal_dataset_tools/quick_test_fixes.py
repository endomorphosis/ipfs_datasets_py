#!/usr/bin/env python3
"""
Quick test of scraper fixes for the 7 failing states.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from state_scrapers import (
    AlabamaScraper,
    DelawareScraper,
    GeorgiaScraper,
    IndianaScraper,
    MissouriScraper,
    TennesseeScraper,
    WyomingScraper,
)


async def test_scraper(scraper_class, state_name, state_code):
    """Test a single scraper."""
    print(f"\n{'='*60}")
    print(f"Testing {state_name}...")
    print(f"{'='*60}")
    
    try:
        scraper = scraper_class(state_code, state_name)
        codes = scraper.get_code_list()
        
        if not codes:
            print(f"{state_name}: No codes available")
            return False
        
        code = codes[0]
        print(f"{state_name}: Scraping '{code['name']}' from {code['url']}")
        
        result = await scraper.scrape_code(code['name'], code['url'])
        
        print(f"{state_name}: ✓ Scraped {len(result)} statutes")
        
        if result:
            print(f"{state_name}: Sample statute: {result[0].section_name[:80]}")
            return True
        else:
            print(f"{state_name}: ✗ No statutes found")
            return False
            
    except Exception as e:
        print(f"{state_name}: ✗ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Test all 7 failing scrapers."""
    scrapers_to_test = [
        (AlabamaScraper, "Alabama", "AL"),
        (DelawareScraper, "Delaware", "DE"),
        (GeorgiaScraper, "Georgia", "GA"),
        (IndianaScraper, "Indiana", "IN"),
        (MissouriScraper, "Missouri", "MO"),
        (TennesseeScraper, "Tennessee", "TN"),
        (WyomingScraper, "Wyoming", "WY"),
    ]
    
    results = {}
    
    for scraper_class, state_name, state_code in scrapers_to_test:
        results[state_name] = await test_scraper(scraper_class, state_name, state_code)
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    successful = sum(1 for v in results.values() if v)
    total = len(results)
    
    for state_name, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"{state_name:15} {status}")
    
    print(f"\n{successful}/{total} states successfully scraped")
    
    return successful, total


if __name__ == "__main__":
    successful, total = asyncio.run(main())
    sys.exit(0 if successful == total else 1)
