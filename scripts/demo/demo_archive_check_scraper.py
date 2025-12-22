#!/usr/bin/env python3
"""
Demo script showing how to use the unified web scraper with automatic
archive checking and submission.

This demonstrates:
1. Checking Archive.org and Archive.is before scraping
2. Automatically submitting pages to archives if not present
3. Continuing with normal scraping after archive operations
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig


async def demo_basic_archive_check():
    """Demonstrate basic archive check and submit functionality."""
    print("=" * 80)
    print("Demo 1: Basic Archive Check and Submit")
    print("=" * 80)
    
    # Configure scraper to check archives before scraping
    config = ScraperConfig(
        archive_check_before_scrape=True,  # Enable archive checking
        archive_check_wayback=True,        # Check Archive.org
        archive_check_archive_is=True,     # Check Archive.is
        archive_submit_if_missing=True,    # Submit if not found
        archive_wait_for_completion=False, # Don't wait for submission to complete
        archive_submission_timeout=60      # Timeout for submissions
    )
    
    scraper = UnifiedWebScraper(config=config)
    
    # Example URL - legal website
    test_url = "https://www.supremecourt.gov"
    
    print(f"\nScraping with archive check: {test_url}")
    print("-" * 80)
    
    result = await scraper.scrape(test_url)
    
    print(f"\nScraping Status: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"Method Used: {result.method_used.value if result.method_used else 'None'}")
    print(f"Extraction Time: {result.extraction_time:.2f}s")
    
    # Display archive check results
    if result.metadata and "archive_check" in result.metadata:
        archive_info = result.metadata["archive_check"]
        print("\nArchive Check Results:")
        print(f"  - Archive.org Present: {archive_info.get('archive_org_present', False)}")
        print(f"  - Archive.is Present: {archive_info.get('archive_is_present', False)}")
        print(f"  - Submitted to Archive.org: {archive_info.get('submitted_to_archive_org', False)}")
        print(f"  - Submitted to Archive.is: {archive_info.get('submitted_to_archive_is', False)}")
        print(f"  - Summary: {archive_info.get('summary', 'N/A')}")
        print(f"  - Recommendation: {archive_info.get('recommendation', 'N/A')}")
        
        if archive_info.get('archive_org_url'):
            print(f"\n  Archive.org URL: {archive_info['archive_org_url']}")
        if archive_info.get('archive_is_url'):
            print(f"  Archive.is URL: {archive_info['archive_is_url']}")
    
    if result.success:
        print(f"\nContent Length: {len(result.html)} bytes")
        print(f"Title: {result.title[:100] if result.title else 'N/A'}")
    else:
        print(f"\nErrors: {result.errors}")
    
    return result


async def demo_batch_archive_check():
    """Demonstrate batch archive checking for multiple URLs."""
    print("\n" + "=" * 80)
    print("Demo 2: Batch Archive Check")
    print("=" * 80)
    
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import batch_check_and_submit
    
    # List of legal dataset URLs
    test_urls = [
        "https://www.supremecourt.gov",
        "https://www.law.cornell.edu",
        "https://www.courtlistener.com",
        "https://caselaw.findlaw.com"
    ]
    
    print(f"\nBatch checking {len(test_urls)} URLs...")
    print("-" * 80)
    
    result = await batch_check_and_submit(
        urls=test_urls,
        check_archive_org=True,
        check_archive_is=True,
        submit_if_missing=True,
        max_concurrent=2,  # Check 2 URLs concurrently
        delay_seconds=1.0  # 1 second delay between operations
    )
    
    print(f"\nBatch Results:")
    print(f"  Total URLs: {result.get('total_urls', 0)}")
    print(f"  Already Archived: {result.get('already_archived_count', 0)}")
    print(f"  Submitted to Archives: {result.get('submitted_count', 0)}")
    print(f"  Errors: {result.get('error_count', 0)}")
    
    # Display individual results
    print("\nPer-URL Results:")
    for url, url_result in result.get('results', {}).items():
        print(f"\n  {url}:")
        print(f"    Archive.org: {'✓ Present' if url_result.get('archive_org_present') else '✗ Not Present'}")
        print(f"    Archive.is: {'✓ Present' if url_result.get('archive_is_present') else '✗ Not Present'}")
        if url_result.get('submitted_to_archive_org'):
            print(f"    → Submitted to Archive.org")
        if url_result.get('submitted_to_archive_is'):
            print(f"    → Submitted to Archive.is")
    
    return result


async def demo_legal_scraper_with_archives():
    """Demonstrate using unified scraper with archive checking for legal content."""
    print("\n" + "=" * 80)
    print("Demo 3: Legal Scraper with Archive Protection")
    print("=" * 80)
    
    # Configure scraper optimized for legal content with archive protection
    config = ScraperConfig(
        # Archive settings
        archive_check_before_scrape=True,
        archive_check_wayback=True,
        archive_check_archive_is=True,
        archive_submit_if_missing=True,
        archive_wait_for_completion=False,
        
        # Scraping settings
        timeout=30,
        max_retries=3,
        rate_limit_delay=2.0,  # Be respectful to legal sites
        
        # Prefer archive sources first for legal content
        fallback_enabled=True,
    )
    
    scraper = UnifiedWebScraper(config=config)
    
    # Legal content URLs
    legal_urls = [
        "https://www.supremecourt.gov/opinions/opinions.aspx",
        "https://www.law.cornell.edu/supremecourt/text/home",
    ]
    
    print(f"\nScraping {len(legal_urls)} legal URLs with archive protection...")
    print("-" * 80)
    
    results = []
    for url in legal_urls:
        print(f"\nProcessing: {url}")
        result = await scraper.scrape(url)
        results.append(result)
        
        if result.success:
            print(f"  ✓ Successfully scraped using {result.method_used.value if result.method_used else 'unknown'}")
            
            # Show archive info
            if result.metadata and "archive_check" in result.metadata:
                archive_info = result.metadata["archive_check"]
                if archive_info.get('archive_org_present') or archive_info.get('archive_is_present'):
                    print(f"  ℹ Found in archives")
                elif archive_info.get('submitted_to_archive_org') or archive_info.get('submitted_to_archive_is'):
                    print(f"  ℹ Submitted to archives for preservation")
        else:
            print(f"  ✗ Failed to scrape: {result.errors[:2] if result.errors else 'Unknown error'}")
    
    # Summary
    successful = sum(1 for r in results if r.success)
    print(f"\n{'=' * 80}")
    print(f"Summary: {successful}/{len(results)} URLs successfully scraped")
    print(f"{'=' * 80}")
    
    return results


async def demo_check_only_mode():
    """Demonstrate checking archives without submitting."""
    print("\n" + "=" * 80)
    print("Demo 4: Archive Check Only (No Submission)")
    print("=" * 80)
    
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import check_and_submit_to_archives
    
    test_url = "https://www.courtlistener.com"
    
    print(f"\nChecking if {test_url} is archived (no submission)...")
    print("-" * 80)
    
    result = await check_and_submit_to_archives(
        url=test_url,
        check_archive_org=True,
        check_archive_is=True,
        submit_if_missing=False  # Don't submit, just check
    )
    
    print(f"\nArchive Status:")
    print(f"  Archive.org: {'✓ Archived' if result.get('archive_org_present') else '✗ Not Archived'}")
    if result.get('archive_org_url'):
        print(f"    URL: {result['archive_org_url']}")
    
    print(f"  Archive.is: {'✓ Archived' if result.get('archive_is_present') else '✗ Not Archived'}")
    if result.get('archive_is_url'):
        print(f"    URL: {result['archive_is_url']}")
    
    print(f"\n  Recommendation: {result.get('recommendation', 'N/A')}")
    
    return result


async def main():
    """Run all demos."""
    print("\n" + "=" * 80)
    print("Unified Web Scraper - Archive Check & Submit Demo")
    print("=" * 80)
    print("\nThis demo shows how the unified web scraper can automatically:")
    print("1. Check if pages are archived on Archive.org and Archive.is")
    print("2. Submit pages to archives if not present")
    print("3. Continue with normal scraping operations")
    print("\nThis is especially useful for legal content and other important pages")
    print("that should be preserved for posterity.")
    
    try:
        # Run demos
        await demo_basic_archive_check()
        await asyncio.sleep(2)
        
        await demo_batch_archive_check()
        await asyncio.sleep(2)
        
        await demo_legal_scraper_with_archives()
        await asyncio.sleep(2)
        
        await demo_check_only_mode()
        
        print("\n" + "=" * 80)
        print("All demos completed successfully!")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
    except Exception as e:
        print(f"\n\nDemo failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
