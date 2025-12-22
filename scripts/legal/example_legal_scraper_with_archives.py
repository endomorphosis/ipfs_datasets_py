#!/usr/bin/env python3
"""
Example script showing how to use archive checking with legal dataset scrapers.

This demonstrates how to:
1. Configure legal scrapers to automatically archive pages
2. Batch check and archive multiple legal URLs
3. Integrate with existing legal scraper workflows
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import (
    check_and_submit_to_archives,
    batch_check_and_submit
)


# Example legal URLs to scrape
LEGAL_URLS = {
    "supreme_court": [
        "https://www.supremecourt.gov/opinions/opinions.aspx",
        "https://www.supremecourt.gov/oral_arguments/argument_calendars.aspx",
    ],
    "circuit_courts": [
        "https://www.ca9.uscourts.gov/opinions/",
        "https://www.ca2.uscourts.gov/decisions",
    ],
    "state_courts": [
        "https://www.courts.ca.gov/opinions.htm",
        "https://nycourts.gov/reporter/slipidx/aidxtable.shtml",
    ],
    "legal_resources": [
        "https://www.law.cornell.edu/supremecourt/text/home",
        "https://www.courtlistener.com/",
    ]
}


async def example_1_simple_legal_scraper():
    """Example 1: Simple legal scraper with archive protection."""
    print("=" * 80)
    print("Example 1: Simple Legal Scraper with Archive Protection")
    print("=" * 80)
    
    # Configure scraper for legal content with archive protection
    config = ScraperConfig(
        # Enable archive checking
        archive_check_before_scrape=True,
        archive_check_wayback=True,
        archive_check_archive_is=True,
        archive_submit_if_missing=True,
        
        # Be respectful to legal sites
        rate_limit_delay=2.0,
        timeout=30,
        max_retries=2
    )
    
    scraper = UnifiedWebScraper(config=config)
    
    # Scrape a Supreme Court page
    url = "https://www.supremecourt.gov/opinions/opinions.aspx"
    print(f"\nScraping: {url}")
    
    result = await scraper.scrape(url)
    
    if result.success:
        print(f"✓ Successfully scraped")
        print(f"  Method: {result.method_used.value if result.method_used else 'unknown'}")
        print(f"  Content size: {len(result.html)} bytes")
        
        # Show archive info
        if result.metadata and "archive_check" in result.metadata:
            archive = result.metadata["archive_check"]
            print(f"\n  Archive Status:")
            print(f"    Archive.org: {'✓ Present' if archive.get('archive_org_present') else '✗ Not Present'}")
            print(f"    Archive.is: {'✓ Present' if archive.get('archive_is_present') else '✗ Not Present'}")
            
            if archive.get('submitted_to_archive_org'):
                print(f"    → Submitted to Archive.org")
            if archive.get('submitted_to_archive_is'):
                print(f"    → Submitted to Archive.is")
    else:
        print(f"✗ Failed to scrape")
        print(f"  Errors: {result.errors[:2]}")


async def example_2_batch_archive_legal_urls():
    """Example 2: Batch archive checking for legal URLs."""
    print("\n" + "=" * 80)
    print("Example 2: Batch Archive Legal URLs Before Scraping")
    print("=" * 80)
    
    # Collect all legal URLs
    all_urls = []
    for category, urls in LEGAL_URLS.items():
        all_urls.extend(urls)
    
    print(f"\nChecking archive status for {len(all_urls)} legal URLs...")
    
    # Batch check and submit
    result = await batch_check_and_submit(
        urls=all_urls,
        check_archive_org=True,
        check_archive_is=True,
        submit_if_missing=True,
        max_concurrent=3,  # Don't overwhelm servers
        delay_seconds=1.5  # Be respectful
    )
    
    print(f"\nBatch Results:")
    print(f"  Total URLs: {result['total_urls']}")
    print(f"  Already Archived: {result['already_archived_count']}")
    print(f"  Submitted to Archives: {result['submitted_count']}")
    print(f"  Errors: {result['error_count']}")
    
    # Show per-category breakdown
    print("\nPer-Category Breakdown:")
    for category, urls in LEGAL_URLS.items():
        print(f"\n  {category.replace('_', ' ').title()}:")
        for url in urls:
            url_result = result['results'].get(url)
            if url_result:
                status = []
                if url_result.get('archive_org_present'):
                    status.append("Archive.org ✓")
                if url_result.get('archive_is_present'):
                    status.append("Archive.is ✓")
                if url_result.get('submitted_to_archive_org'):
                    status.append("Submitted to Archive.org")
                if url_result.get('submitted_to_archive_is'):
                    status.append("Submitted to Archive.is")
                
                print(f"    {url[:60]}...")
                print(f"      {', '.join(status) if status else 'Not archived'}")


async def example_3_legal_scraper_with_verification():
    """Example 3: Legal scraper with archive verification."""
    print("\n" + "=" * 80)
    print("Example 3: Legal Scraper with Archive Verification")
    print("=" * 80)
    
    # First, check if URLs are archived
    test_urls = LEGAL_URLS["supreme_court"]
    
    print(f"\nStep 1: Verify archive status for {len(test_urls)} URLs")
    print("-" * 80)
    
    archive_statuses = {}
    for url in test_urls:
        result = await check_and_submit_to_archives(
            url,
            check_archive_org=True,
            check_archive_is=True,
            submit_if_missing=False  # Just check, don't submit yet
        )
        archive_statuses[url] = result
        
        print(f"\n{url[:60]}...")
        print(f"  Archive.org: {'✓ Yes' if result.get('archive_org_present') else '✗ No'}")
        print(f"  Archive.is: {'✓ Yes' if result.get('archive_is_present') else '✗ No'}")
    
    # Identify URLs not archived anywhere
    unarchived_urls = [
        url for url, status in archive_statuses.items()
        if not status.get('archive_org_present') and not status.get('archive_is_present')
    ]
    
    if unarchived_urls:
        print(f"\nStep 2: Archive {len(unarchived_urls)} unarchived URLs")
        print("-" * 80)
        
        for url in unarchived_urls:
            print(f"\nArchiving: {url[:60]}...")
            result = await check_and_submit_to_archives(
                url,
                check_archive_org=False,  # Already checked
                check_archive_is=False,
                submit_if_missing=True
            )
            
            if result.get('submitted_to_archive_org'):
                print(f"  → Submitted to Archive.org")
            if result.get('submitted_to_archive_is'):
                print(f"  → Submitted to Archive.is")
    else:
        print("\nStep 2: All URLs already archived! ✓")
    
    # Now scrape
    print(f"\nStep 3: Scrape content")
    print("-" * 80)
    
    config = ScraperConfig(
        archive_check_before_scrape=False,  # Already checked above
        rate_limit_delay=2.0
    )
    
    scraper = UnifiedWebScraper(config=config)
    
    for url in test_urls:
        result = await scraper.scrape(url)
        status_icon = "✓" if result.success else "✗"
        print(f"{status_icon} {url[:60]}...")


async def example_4_create_legal_archive_report():
    """Example 4: Create a report of legal URLs and their archive status."""
    print("\n" + "=" * 80)
    print("Example 4: Generate Legal Archive Status Report")
    print("=" * 80)
    
    # Collect all URLs
    all_urls = []
    for urls in LEGAL_URLS.values():
        all_urls.extend(urls)
    
    print(f"\nGenerating archive status report for {len(all_urls)} legal URLs...")
    
    # Check all URLs
    results = []
    for url in all_urls:
        result = await check_and_submit_to_archives(
            url,
            check_archive_org=True,
            check_archive_is=True,
            submit_if_missing=False  # Report only
        )
        result['url'] = url
        results.append(result)
        await asyncio.sleep(0.5)  # Rate limit
    
    # Generate report
    print("\n" + "=" * 80)
    print("LEGAL URLS ARCHIVE STATUS REPORT")
    print("=" * 80)
    print(f"Generated: {results[0]['timestamp'] if results else 'N/A'}")
    print(f"Total URLs: {len(results)}")
    
    # Statistics
    archived_org = sum(1 for r in results if r.get('archive_org_present'))
    archived_is = sum(1 for r in results if r.get('archive_is_present'))
    archived_both = sum(1 for r in results if r.get('archive_org_present') and r.get('archive_is_present'))
    not_archived = sum(1 for r in results if not r.get('archive_org_present') and not r.get('archive_is_present'))
    
    print(f"\nStatistics:")
    print(f"  Archived on Archive.org: {archived_org} ({archived_org/len(results)*100:.1f}%)")
    print(f"  Archived on Archive.is: {archived_is} ({archived_is/len(results)*100:.1f}%)")
    print(f"  Archived on both: {archived_both} ({archived_both/len(results)*100:.1f}%)")
    print(f"  Not archived anywhere: {not_archived} ({not_archived/len(results)*100:.1f}%)")
    
    # Detailed listing
    print("\nDetailed Listing:")
    print("-" * 80)
    
    for result in results:
        url = result['url']
        org_status = "✓" if result.get('archive_org_present') else "✗"
        is_status = "✓" if result.get('archive_is_present') else "✗"
        
        print(f"\n{url}")
        print(f"  Archive.org: {org_status}")
        if result.get('archive_org_url'):
            print(f"    {result['archive_org_url']}")
        print(f"  Archive.is: {is_status}")
        if result.get('archive_is_url'):
            print(f"    {result['archive_is_url']}")
    
    # Recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    
    if not_archived > 0:
        print(f"\n⚠ {not_archived} URLs are not archived anywhere!")
        print("  Recommendation: Archive these URLs immediately to prevent data loss.")
        print("\n  To archive these URLs:")
        print("  python scripts/legal/archive_legal_urls.py --submit")
    else:
        print("\n✓ All legal URLs are archived!")
        print("  Great job! Your legal content is protected.")


async def main():
    """Run all examples."""
    print("\n" + "=" * 80)
    print("Legal Scraper Archive Integration Examples")
    print("=" * 80)
    print("\nThese examples show how to integrate archive checking")
    print("with legal dataset scrapers to ensure content preservation.")
    
    try:
        # Run examples
        await example_1_simple_legal_scraper()
        await asyncio.sleep(2)
        
        await example_2_batch_archive_legal_urls()
        await asyncio.sleep(2)
        
        await example_3_legal_scraper_with_verification()
        await asyncio.sleep(2)
        
        await example_4_create_legal_archive_report()
        
        print("\n" + "=" * 80)
        print("All examples completed!")
        print("=" * 80)
        print("\nKey Takeaways:")
        print("1. Always enable archive checking for legal content")
        print("2. Use batch operations for efficiency")
        print("3. Verify archive status before critical scraping")
        print("4. Generate regular archive status reports")
        print("5. Submit missing URLs to archives proactively")
        
    except KeyboardInterrupt:
        print("\n\nExamples interrupted by user")
    except Exception as e:
        print(f"\n\nExamples failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
