#!/usr/bin/env python3
"""
CLI interface for unified legal scrapers.

This CLI provides access to all legal scraping functionality:
- Scrape individual URLs
- Scrape multiple URLs in parallel or with multiprocessing
- Search Common Crawl, Wayback, etc.
- Export to WARC and IPFS
- Content-addressed deduplication

Examples:
    # Scrape a single URL
    python legal_scraper_cli.py scrape https://library.municode.com/wa/seattle
    
    # Scrape multiple URLs from a file
    python legal_scraper_cli.py scrape-bulk urls.txt --max-workers 20
    
    # Search Common Crawl for a URL pattern
    python legal_scraper_cli.py search-common-crawl "https://library.municode.com/*"
    
    # List available scrapers
    python legal_scraper_cli.py list-scrapers
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedLegalScraper
from ipfs_datasets_py.legal_scrapers.scrapers import list_available_scrapers


def setup_parser():
    """Setup argument parser for CLI."""
    parser = argparse.ArgumentParser(
        description="Unified Legal Scraper CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Scrape command
    scrape_parser = subparsers.add_parser('scrape', help='Scrape a single URL')
    scrape_parser.add_argument('url', help='URL to scrape')
    scrape_parser.add_argument('--force', action='store_true', help='Force rescrape even if cached')
    scrape_parser.add_argument('--no-archives', action='store_true', help='Disable archive sources')
    scrape_parser.add_argument('--enable-ipfs', action='store_true', help='Enable IPFS storage')
    scrape_parser.add_argument('--disable-warc', action='store_true', help='Disable WARC export')
    scrape_parser.add_argument('--output', '-o', help='Output file (JSON)')
    
    # Scrape bulk command
    bulk_parser = subparsers.add_parser('scrape-bulk', help='Scrape multiple URLs')
    bulk_parser.add_argument('input', help='Input file with URLs (one per line)')
    bulk_parser.add_argument('--max-concurrent', type=int, default=10, help='Max concurrent requests')
    bulk_parser.add_argument('--max-workers', type=int, help='Max workers for multiprocessing')
    bulk_parser.add_argument('--force', action='store_true', help='Force rescrape')
    bulk_parser.add_argument('--no-archives', action='store_true', help='Disable archive sources')
    bulk_parser.add_argument('--enable-ipfs', action='store_true', help='Enable IPFS storage')
    bulk_parser.add_argument('--disable-warc', action='store_true', help='Disable WARC export')
    bulk_parser.add_argument('--output', '-o', help='Output file (JSON)')
    bulk_parser.add_argument('--use-multiprocessing', action='store_true', 
                           help='Use multiprocessing for maximum speed')
    
    # Search Common Crawl
    cc_parser = subparsers.add_parser('search-common-crawl', help='Search Common Crawl indexes')
    cc_parser.add_argument('url', help='URL or pattern to search (supports *)')
    cc_parser.add_argument('--indexes', nargs='+', help='Specific indexes to search')
    cc_parser.add_argument('--output', '-o', help='Output file (JSON)')
    
    # List scrapers
    list_parser = subparsers.add_parser('list-scrapers', help='List available scrapers')
    
    # Test scraper
    test_parser = subparsers.add_parser('test', help='Test scraper with sample URLs')
    test_parser.add_argument('--type', choices=['state', 'municipal', 'federal', 'all'],
                           default='all', help='Type of scraper to test')
    
    return parser


async def cmd_scrape(args):
    """Scrape a single URL."""
    scraper = UnifiedLegalScraper(
        enable_ipfs=args.enable_ipfs,
        enable_warc=not args.disable_warc,
        check_archives=not args.no_archives
    )
    
    result = await scraper.scrape_url(
        args.url,
        force_rescrape=args.force,
        prefer_archived=not args.no_archives
    )
    
    # Output result
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Result saved to {args.output}")
    else:
        print(json.dumps(result, indent=2))
    
    # Print summary
    if result.get('success'):
        print(f"\n✓ Successfully scraped {args.url}")
        print(f"  Source: {result.get('source', 'unknown')}")
        print(f"  CID: {result.get('cid', 'N/A')}")
        if result.get('already_scraped'):
            print(f"  (Already scraped, version {result.get('version', 1)})")
    else:
        print(f"\n✗ Failed to scrape {args.url}")
        print(f"  Error: {result.get('error', 'Unknown error')}")
        sys.exit(1)


async def cmd_scrape_bulk(args):
    """Scrape multiple URLs."""
    # Read URLs from file
    with open(args.input, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"Loaded {len(urls)} URLs from {args.input}")
    
    scraper = UnifiedLegalScraper(
        enable_ipfs=args.enable_ipfs,
        enable_warc=not args.disable_warc,
        check_archives=not args.no_archives,
        max_workers=args.max_workers
    )
    
    # Choose scraping method
    if args.use_multiprocessing and args.max_workers:
        print(f"Using multiprocessing with {args.max_workers} workers")
        results = scraper.scrape_urls_multiprocessing(
            urls,
            force_rescrape=args.force,
            prefer_archived=not args.no_archives
        )
    else:
        print(f"Using async with max {args.max_concurrent} concurrent requests")
        results = await scraper.scrape_urls_parallel(
            urls,
            max_concurrent=args.max_concurrent,
            force_rescrape=args.force,
            prefer_archived=not args.no_archives
        )
    
    # Calculate statistics
    successful = sum(1 for r in results if r.get('success'))
    failed = len(results) - successful
    
    # Output results
    output_data = {
        "total": len(results),
        "successful": successful,
        "failed": failed,
        "results": results
    }
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to {args.output}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Scraping Summary")
    print(f"{'='*60}")
    print(f"Total URLs: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Success rate: {successful/len(results)*100:.1f}%")
    
    # Source breakdown
    sources = {}
    for r in results:
        if r.get('success'):
            source = r.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1
    
    if sources:
        print(f"\nSources used:")
        for source, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  {source}: {count}")
    
    if failed > 0:
        sys.exit(1)


async def cmd_search_common_crawl(args):
    """Search Common Crawl for URLs."""
    try:
        from ipfs_datasets_py.multi_index_archive_search import search_all_common_crawl_indexes
        
        results = await search_all_common_crawl_indexes(
            args.url,
            indexes=args.indexes
        )
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Results saved to {args.output}")
        else:
            print(json.dumps(results, indent=2))
        
        # Print summary
        total = sum(len(r.get('captures', [])) for r in results)
        print(f"\nFound {total} captures across {len(results)} indexes")
        
    except ImportError as e:
        print(f"Error: Common Crawl search not available: {e}")
        sys.exit(1)


def cmd_list_scrapers(args):
    """List available scrapers."""
    scrapers = list_available_scrapers()
    
    print("\nAvailable Legal Scrapers:")
    print("="*60)
    
    print(f"\nState Scrapers ({len(scrapers['state_scrapers'])} states):")
    for i, state in enumerate(sorted(scrapers['state_scrapers']), 1):
        print(f"  {state}", end='  ')
        if i % 10 == 0:
            print()
    print()
    
    print(f"\nMunicipal Scrapers ({len(scrapers['municipal_scrapers'])}):")
    for scraper in scrapers['municipal_scrapers']:
        print(f"  - {scraper}")
    
    print(f"\nFederal Scrapers ({len(scrapers['federal_scrapers'])}):")
    for scraper in scrapers['federal_scrapers']:
        print(f"  - {scraper}")
    
    print(f"\nTotal: {scrapers['total_count']} scrapers")


async def cmd_test(args):
    """Test scrapers with sample URLs."""
    test_urls = {
        'state': [
            'https://leginfo.legislature.ca.gov/',
        ],
        'municipal': [
            'https://library.municode.com/wa/seattle',
        ],
        'federal': [
            'https://uscode.house.gov/',
            'https://www.federalregister.gov/',
        ]
    }
    
    if args.type == 'all':
        urls_to_test = []
        for category_urls in test_urls.values():
            urls_to_test.extend(category_urls)
    else:
        urls_to_test = test_urls.get(args.type, [])
    
    print(f"Testing {len(urls_to_test)} URLs...")
    
    scraper = UnifiedLegalScraper()
    
    for url in urls_to_test:
        print(f"\nTesting: {url}")
        result = await scraper.scrape_url(url)
        
        if result.get('success'):
            print(f"  ✓ Success (source: {result.get('source')})")
        else:
            print(f"  ✗ Failed: {result.get('error')}")


def main():
    """Main CLI entry point."""
    parser = setup_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute command
    if args.command == 'scrape':
        asyncio.run(cmd_scrape(args))
    elif args.command == 'scrape-bulk':
        asyncio.run(cmd_scrape_bulk(args))
    elif args.command == 'search-common-crawl':
        asyncio.run(cmd_search_common_crawl(args))
    elif args.command == 'list-scrapers':
        cmd_list_scrapers(args)
    elif args.command == 'test':
        asyncio.run(cmd_test(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
