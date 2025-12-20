#!/usr/bin/env python3
"""
Validation script to test unified scraper with CSV of municipal websites
"""
import asyncio
import csv
import sys
from pathlib import Path
import urllib.request

# Add package to path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.unified_scraper import UnifiedScraper
from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper

async def download_csv(url: str, output_path: str):
    """Download CSV file"""
    print(f"Downloading CSV from {url}...")
    urllib.request.urlretrieve(url, output_path)
    print(f"Saved to {output_path}")

async def test_scraper_with_csv(csv_path: str, limit: int = 5):
    """Test scraper with URLs from CSV"""
    scraper = UnifiedScraper()
    ca_scraper = ContentAddressedScraper()
    
    print(f"\n{'='*80}")
    print(f"Testing Unified Scraper with {csv_path}")
    print(f"{'='*80}\n")
    
    # Read CSV
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        urls = []
        for i, row in enumerate(reader):
            if i >= limit:
                break
            # Look for URL column (might be named differently)
            url = None
            for key in row.keys():
                if 'url' in key.lower() or 'link' in key.lower() or 'website' in key.lower():
                    url = row[key]
                    break
            if url:
                urls.append((row, url))
    
    print(f"Found {len(urls)} URLs to test\n")
    
    # Test each URL
    results = []
    for i, (row, url) in enumerate(urls, 1):
        print(f"\n{'-'*80}")
        print(f"Test {i}/{len(urls)}: {url}")
        print(f"Row data: {row}")
        print(f"{'-'*80}")
        
        try:
            # Test unified scraper
            print("\n[1] Testing UnifiedScraper.scrape()...")
            result = await scraper.scrape(url)
            
            if result and result.get('content'):
                content_len = len(result['content'])
                print(f"✓ SUCCESS: Retrieved {content_len} bytes")
                print(f"  Method used: {result.get('method', 'unknown')}")
                print(f"  Status: {result.get('status')}")
                
                # Test content-addressed scraper
                print("\n[2] Testing ContentAddressedScraper...")
                ca_result = await ca_scraper.scrape_with_cid(url)
                if ca_result:
                    print(f"✓ Content CID: {ca_result.get('content_cid', 'N/A')}")
                    print(f"  Metadata CID: {ca_result.get('metadata_cid', 'N/A')}")
                
                results.append({
                    'url': url,
                    'status': 'success',
                    'method': result.get('method'),
                    'size': content_len
                })
            else:
                print(f"✗ FAILED: No content retrieved")
                results.append({
                    'url': url,
                    'status': 'failed',
                    'method': None,
                    'size': 0
                })
                
        except Exception as e:
            print(f"✗ ERROR: {type(e).__name__}: {e}")
            results.append({
                'url': url,
                'status': 'error',
                'error': str(e)
            })
    
    # Summary
    print(f"\n\n{'='*80}")
    print("VALIDATION SUMMARY")
    print(f"{'='*80}\n")
    
    success = sum(1 for r in results if r['status'] == 'success')
    failed = sum(1 for r in results if r['status'] == 'failed')
    errors = sum(1 for r in results if r['status'] == 'error')
    
    print(f"Total URLs tested: {len(results)}")
    print(f"✓ Successful: {success} ({success/len(results)*100:.1f}%)")
    print(f"✗ Failed: {failed} ({failed/len(results)*100:.1f}%)")
    print(f"⚠ Errors: {errors} ({errors/len(results)*100:.1f}%)")
    
    print("\nMethods used:")
    methods = {}
    for r in results:
        if r['status'] == 'success':
            method = r.get('method', 'unknown')
            methods[method] = methods.get(method, 0) + 1
    
    for method, count in sorted(methods.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {method}: {count}")
    
    print(f"\n{'='*80}\n")
    
    return results

async def main():
    csv_url = "https://cdn.discordapp.com/attachments/1341611671663280159/1451717160035422269/us_towns_and_counties_top_100_pop.csv"
    csv_path = "/home/devel/ipfs_datasets_py/test_validation_urls.csv"
    
    # Download CSV
    await download_csv(csv_url, csv_path)
    
    # Test with first 5 URLs
    print("\nStarting validation tests...")
    results = await test_scraper_with_csv(csv_path, limit=5)
    
    print("\nValidation complete!")

if __name__ == "__main__":
    asyncio.run(main())
