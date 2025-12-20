#!/usr/bin/env python3
"""
Validate the unified scraper architecture by testing against real municipal code URLs.
Tests the complete fallback chain and content-addressed storage.
"""

import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.content_addressed_scraper import ContentAddressedScraper


async def test_scraper_with_url(scraper: ContentAddressedScraper, url: str, metadata: Dict[str, str]) -> Dict[str, Any]:
    """Test scraping a single URL and return results."""
    result = {
        "url": url,
        "place_name": metadata.get("place_name", "Unknown"),
        "state_code": metadata.get("state_code", "Unknown"),
        "gnis": metadata.get("gnis", "Unknown"),
        "timestamp": datetime.utcnow().isoformat(),
        "success": False,
        "method_used": None,
        "content_hash": None,
        "error": None,
        "content_length": 0,
        "metadata": {}
    }
    
    try:
        print(f"\n{'='*80}")
        print(f"Testing: {metadata.get('place_name', 'Unknown')} ({metadata.get('state_code', 'Unknown')})")
        print(f"URL: {url}")
        print(f"{'='*80}")
        
        # Attempt to scrape with content-addressed scraper
        scrape_result = await scraper.scrape_with_content_addressing(
            url,
            metadata={
                "place_name": metadata.get("place_name"),
                "state_code": metadata.get("state_code"),
                "gnis": metadata.get("gnis"),
                "source_type": "municipal_code"
            }
        )
        
        # Check if successful - handle both "status":"success" and "success":True formats
        is_success = (
            scrape_result.get("status") == "success" or 
            scrape_result.get("success") == True
        )
        
        if is_success and scrape_result.get("content"):
            result["success"] = True
            result["method_used"] = scrape_result.get("method", "content_addressed")
            result["content_hash"] = scrape_result.get("content_cid") or scrape_result.get("content_hash")
            result["content_length"] = len(scrape_result.get("content", b""))
            result["metadata"] = scrape_result.get("metadata", {})
            result["version"] = scrape_result.get("version", 1)
            
            print(f"✓ SUCCESS: {result['method_used']}")
            print(f"  Content Hash/CID: {result['content_hash']}")
            print(f"  Content Length: {result['content_length']} bytes")
            print(f"  Version: {result['version']}")
        else:
            error_msg = scrape_result.get("error", "Unknown error")
            # Get more details if available
            if "status" in scrape_result and scrape_result["status"] != "success":
                error_msg = f"{error_msg} (status: {scrape_result['status']})"
            result["error"] = error_msg
            result["scrape_details"] = {k: str(v)[:200] for k, v in scrape_result.items() if k != 'content'}  # Store details (truncated)
            print(f"✗ FAILED: {error_msg}")
            
    except Exception as e:
        result["error"] = str(e)
        print(f"✗ EXCEPTION: {e}")
    
    return result


async def run_validation(csv_path: str, max_tests: int = None, output_file: str = None):
    """Run validation tests on URLs from CSV."""
    
    print(f"\n{'#'*80}")
    print(f"# Municipal Code Scraper Validation")
    print(f"# CSV: {csv_path}")
    print(f"# Max Tests: {max_tests if max_tests else 'All'}")
    print(f"{'#'*80}\n")
    
    # Initialize scrapers
    print("Initializing content-addressed scraper...")
    scraper = ContentAddressedScraper(
        cache_dir="./municode_validation_cache"
    )
    
    # Load CSV
    urls_to_test = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            urls_to_test.append({
                "url": row.get("source_url", "").strip(),
                "place_name": row.get("place_name", "").strip(),
                "state_code": row.get("state_code", "").strip(),
                "gnis": row.get("gnis", "").strip()
            })
    
    if max_tests:
        urls_to_test = urls_to_test[:max_tests]
    
    print(f"Found {len(urls_to_test)} URLs to test\n")
    
    # Run tests
    results = []
    for idx, test_case in enumerate(urls_to_test, 1):
        print(f"\n[{idx}/{len(urls_to_test)}] ", end="")
        result = await test_scraper_with_url(
            scraper,
            test_case["url"],
            test_case
        )
        results.append(result)
        
        # Brief pause between requests
        await asyncio.sleep(1)
    
    # Generate summary
    print(f"\n\n{'#'*80}")
    print(f"# VALIDATION SUMMARY")
    print(f"{'#'*80}\n")
    
    total = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total - successful
    
    print(f"Total Tests: {total}")
    print(f"Successful: {successful} ({100*successful/total:.1f}%)")
    print(f"Failed: {failed} ({100*failed/total:.1f}%)")
    
    # Method breakdown
    methods = {}
    for r in results:
        if r["success"]:
            method = r["method_used"]
            methods[method] = methods.get(method, 0) + 1
    
    print(f"\nMethods Used:")
    for method, count in sorted(methods.items(), key=lambda x: x[1], reverse=True):
        print(f"  {method}: {count} ({100*count/successful:.1f}% of successful)")
    
    # Error breakdown
    if failed > 0:
        errors = {}
        for r in results:
            if not r["success"] and r["error"]:
                error_type = r["error"][:100]  # First 100 chars
                errors[error_type] = errors.get(error_type, 0) + 1
        
        print(f"\nTop Errors:")
        for error, count in sorted(errors.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"  [{count}x] {error}")
    
    # Save results
    if output_file:
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump({
                "summary": {
                    "total": total,
                    "successful": successful,
                    "failed": failed,
                    "success_rate": successful/total if total > 0 else 0,
                    "methods": methods
                },
                "results": results
            }, f, indent=2)
        print(f"\nResults saved to: {output_path}")
    
    print(f"\n{'#'*80}\n")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate unified scraper with municipal code URLs")
    parser.add_argument("--csv", default="validation_municode_urls.csv", help="CSV file with URLs to test")
    parser.add_argument("--max-tests", type=int, help="Maximum number of URLs to test")
    parser.add_argument("--output", default="municode_validation_results.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    asyncio.run(run_validation(args.csv, args.max_tests, args.output))
