#!/usr/bin/env python3
"""Test Indiana and Tennessee scrapers."""
import anyio
import sys
sys.path.insert(0, '/home/devel/ipfs_datasets_py')

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    IndianaScraper, TennesseeScraper
)

async def run_scraper(scraper_class, code, name):
    """Run a single scraper (helper for the main script).

    Note: intentionally not named like a pytest test function.
    """
    print(f"\n{'='*60}")
    print(f"Testing {name} ({code})")
    print('='*60)
    
    try:
        scraper = scraper_class(code, name)
        codes = scraper.get_code_list()
        print(f"URL: {codes[0]['url']}")
        
        result = await scraper.scrape_code(codes[0]['name'], codes[0]['url'])
        count = len(result)
        
        print(f"\nResult: {count} statutes scraped")
        
        if count > 0:
            print("\nFirst 3 statutes:")
            for i, statute in enumerate(result[:3]):
                print(f"  {i+1}. {statute.section_name[:60]}")
            return f"✓ {name}: {count} statutes"
        else:
            return f"✗ {name}: 0 statutes"
            
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return f"✗ {name}: ERROR - {str(e)[:50]}"

async def main():
    """Test both scrapers."""
    results = []
    
    results.append(await run_scraper(IndianaScraper, "IN", "Indiana"))
    results.append(await run_scraper(TennesseeScraper, "TN", "Tennessee"))
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    for result in results:
        print(result)

if __name__ == '__main__':
    anyio.run(main())
