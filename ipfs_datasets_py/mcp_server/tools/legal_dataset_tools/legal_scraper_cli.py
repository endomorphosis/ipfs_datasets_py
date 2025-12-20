#!/usr/bin/env python3
"""
CLI Tool for Unified Legal Scraping

Provides command-line interface for scraping legal datasets with
content addressing and multi-source fallback.

Usage:
    # Scrape single URL
    python legal_scraper_cli.py scrape https://library.municode.com/wa/seattle
    
    # Scrape multiple URLs
    python legal_scraper_cli.py scrape-bulk urls.txt --max-concurrent 10
    
    # Search Common Crawl
    python legal_scraper_cli.py search-cc "https://library.municode.com/*"
    
    # Check if URL cached
    python legal_scraper_cli.py check-cache https://library.municode.com/wa/seattle
    
    # Migrate existing scraper
    python legal_scraper_cli.py migrate state_scrapers/california.py
"""

import asyncio
import argparse
import sys
import json
import logging
from pathlib import Path
from typing import List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def cmd_scrape(args):
    """Scrape a single URL."""
    from .unified_legal_scraper import UnifiedLegalScraper
    
    scraper = UnifiedLegalScraper(
        enable_warc=args.warc,
        use_ipfs_daemon=args.ipfs_daemon
    )
    
    logger.info(f"Scraping: {args.url}")
    result = await scraper.scrape_url(
        args.url,
        force_rescrape=args.force,
        prefer_archived=not args.no_archive
    )
    
    if result.success:
        print(f"✓ Successfully scraped {args.url}")
        print(f"  CID: {result.cid}")
        print(f"  Source: {result.source}")
        print(f"  Size: {len(result.html)} bytes")
        
        if result.already_scraped:
            print(f"  (Previously scraped)")
        
        if result.common_crawl_indexes:
            print(f"  Common Crawl indexes: {', '.join(result.common_crawl_indexes)}")
        
        if result.warc_path:
            print(f"  WARC: {result.warc_path}")
        
        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            if args.format == 'html':
                output_path.write_text(result.html)
            else:
                output_path.write_text(json.dumps(result.to_dict(), indent=2))
            print(f"  Saved to: {output_path}")
        
        return 0
    else:
        print(f"✗ Failed to scrape {args.url}")
        for error in result.errors:
            print(f"  Error: {error}")
        return 1


async def cmd_scrape_bulk(args):
    """Scrape multiple URLs from file."""
    from .unified_legal_scraper import UnifiedLegalScraper
    
    # Read URLs from file
    urls_file = Path(args.urls_file)
    if not urls_file.exists():
        print(f"Error: File not found: {urls_file}")
        return 1
    
    urls = [line.strip() for line in urls_file.read_text().splitlines() if line.strip()]
    
    logger.info(f"Scraping {len(urls)} URLs (max concurrent: {args.max_concurrent})")
    
    scraper = UnifiedLegalScraper(
        enable_warc=args.warc,
        use_ipfs_daemon=args.ipfs_daemon
    )
    
    results = await scraper.scrape_urls_parallel(
        urls,
        max_concurrent=args.max_concurrent,
        force_rescrape=args.force,
        prefer_archived=not args.no_archive
    )
    
    # Print summary
    successful = sum(1 for r in results if r.success)
    cached = sum(1 for r in results if r.already_scraped)
    
    print(f"\n=== Scraping Summary ===")
    print(f"Total: {len(urls)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(urls) - successful}")
    print(f"From cache: {cached}")
    
    # Count sources
    sources = {}
    for r in results:
        if r.success and r.source:
            sources[r.source] = sources.get(r.source, 0) + 1
    
    if sources:
        print(f"\nSources used:")
        for source, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  {source}: {count}")
    
    # Save results if requested
    if args.output:
        output_path = Path(args.output)
        results_data = [r.to_dict() for r in results]
        output_path.write_text(json.dumps(results_data, indent=2))
        print(f"\nResults saved to: {output_path}")
    
    return 0 if successful == len(urls) else 1


async def cmd_search_cc(args):
    """Search Common Crawl indexes."""
    from .unified_legal_scraper import UnifiedLegalScraper
    
    scraper = UnifiedLegalScraper()
    
    if args.indexes:
        scraper.common_crawl_indexes = args.indexes
    
    logger.info(f"Searching Common Crawl for: {args.url}")
    logger.info(f"Indexes: {', '.join(scraper.common_crawl_indexes)}")
    
    results = await scraper.search_common_crawl(args.url)
    
    if results:
        print(f"✓ Found {len(results)} entries\n")
        
        # Group by index
        by_index = {}
        for entry in results:
            index = entry.get('index', 'unknown')
            if index not in by_index:
                by_index[index] = []
            by_index[index].append(entry)
        
        for index, entries in sorted(by_index.items()):
            print(f"{index}: {len(entries)} entries")
            if args.verbose:
                for entry in entries[:5]:  # Show first 5
                    print(f"  - {entry.get('url', 'N/A')}")
                    print(f"    Timestamp: {entry.get('timestamp', 'N/A')}")
                    print(f"    MIME: {entry.get('mime', 'N/A')}")
        
        # Save results if requested
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json.dumps(results, indent=2))
            print(f"\nResults saved to: {output_path}")
        
        return 0
    else:
        print(f"✗ No entries found in Common Crawl")
        return 1


async def cmd_check_cache(args):
    """Check if URL is cached."""
    from .unified_legal_scraper import UnifiedLegalScraper
    
    scraper = UnifiedLegalScraper()
    
    logger.info(f"Checking cache for: {args.url}")
    cached = await scraper.check_already_scraped(args.url)
    
    if cached:
        versions = cached['versions']
        print(f"✓ URL is cached with {len(versions)} version(s)\n")
        
        for i, version in enumerate(versions, 1):
            print(f"Version {i}:")
            print(f"  CID: {version['cid']}")
            print(f"  Timestamp: {version['timestamp']}")
            print(f"  Source: {version['source']}")
            print(f"  Size: {version.get('size', 'N/A')} bytes")
            print()
        
        if cached['latest']:
            print(f"Latest CID: {cached['latest']['cid']}")
        
        return 0
    else:
        print(f"✗ URL not found in cache")
        return 1


async def cmd_migrate(args):
    """Analyze scraper file for migration."""
    from .scraper_adapter import MigrationHelper
    
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return 1
    
    logger.info(f"Analyzing: {file_path}")
    report = MigrationHelper.generate_migration_report(file_path)
    
    if 'error' in report:
        print(f"Error: {report['error']}")
        return 1
    
    print(f"\n=== Migration Report ===")
    print(f"File: {report['file']}")
    print(f"Needs migration: {report['needs_migration']}\n")
    
    if report['patterns_found']:
        print("Patterns found:")
        for pattern in report['patterns_found']:
            print(f"  - {pattern['pattern']}: {pattern['count']} occurrence(s)")
        
        print("\nRecommendations:")
        for rec in report.get('recommendations', []):
            print(f"  • {rec}")
    else:
        print("No old patterns found - file may already be migrated!")
    
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Unified Legal Scraper CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Scrape command
    scrape_parser = subparsers.add_parser('scrape', help='Scrape a single URL')
    scrape_parser.add_argument('url', help='URL to scrape')
    scrape_parser.add_argument('-o', '--output', help='Output file')
    scrape_parser.add_argument('-f', '--format', choices=['html', 'json'], default='json',
                               help='Output format')
    scrape_parser.add_argument('--force', action='store_true',
                               help='Force rescrape even if cached')
    scrape_parser.add_argument('--no-archive', action='store_true',
                               help='Skip archived sources, scrape live only')
    scrape_parser.add_argument('--warc', action='store_true',
                               help='Export to WARC format')
    scrape_parser.add_argument('--ipfs-daemon', action='store_true',
                               help='Use IPFS daemon for CID generation')
    
    # Scrape bulk command
    bulk_parser = subparsers.add_parser('scrape-bulk', help='Scrape multiple URLs from file')
    bulk_parser.add_argument('urls_file', help='File with URLs (one per line)')
    bulk_parser.add_argument('-o', '--output', help='Output JSON file')
    bulk_parser.add_argument('--max-concurrent', type=int, default=10,
                            help='Max concurrent requests (default: 10)')
    bulk_parser.add_argument('--force', action='store_true',
                            help='Force rescrape even if cached')
    bulk_parser.add_argument('--no-archive', action='store_true',
                            help='Skip archived sources')
    bulk_parser.add_argument('--warc', action='store_true',
                            help='Export to WARC format')
    bulk_parser.add_argument('--ipfs-daemon', action='store_true',
                            help='Use IPFS daemon for CID generation')
    
    # Search Common Crawl command
    cc_parser = subparsers.add_parser('search-cc', help='Search Common Crawl indexes')
    cc_parser.add_argument('url', help='URL or pattern to search')
    cc_parser.add_argument('-o', '--output', help='Output JSON file')
    cc_parser.add_argument('--indexes', nargs='+', help='Specific indexes to search')
    cc_parser.add_argument('-v', '--verbose', action='store_true',
                          help='Show detailed results')
    
    # Check cache command
    cache_parser = subparsers.add_parser('check-cache', help='Check if URL is cached')
    cache_parser.add_argument('url', help='URL to check')
    
    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Analyze scraper for migration')
    migrate_parser.add_argument('file', help='Scraper file to analyze')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Run command
    if args.command == 'scrape':
        return asyncio.run(cmd_scrape(args))
    elif args.command == 'scrape-bulk':
        return asyncio.run(cmd_scrape_bulk(args))
    elif args.command == 'search-cc':
        return asyncio.run(cmd_search_cc(args))
    elif args.command == 'check-cache':
        return asyncio.run(cmd_check_cache(args))
    elif args.command == 'migrate':
        return asyncio.run(cmd_migrate(args))
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
