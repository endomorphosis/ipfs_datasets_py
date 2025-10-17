#!/usr/bin/env python3
"""Test Delaware scraper with updated link extraction."""
import asyncio
import logging
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_scrapers import DelawareScraper

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def test_delaware():
    """Test Delaware scraper."""
    scraper = DelawareScraper('DE', 'Delaware')
    codes = scraper.get_code_list()
    
    print(f"Testing Delaware Code: {codes[0]['name']}")
    result = await scraper.scrape_code(codes[0]['name'], codes[0]['url'])
    
    print(f"\n{'='*60}")
    print(f"Delaware Result: {len(result)} statutes scraped")
    print(f"{'='*60}")
    
    if result:
        print("\nSample statutes:")
        for statute in result[:5]:
            print(f"  - {statute['title'][:80]}...")

if __name__ == '__main__':
    asyncio.run(test_delaware())
