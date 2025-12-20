#!/usr/bin/env python3
"""
Municode CLI - Command Line Interface

Command-line tool for scraping Municode jurisdictions.

Usage:
    legal-scraper municode <url> [options]
    legal-scraper municode --batch <file> [options]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from legal_scrapers.core import MunicodeScraper, run_async_scraper


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for Municode CLI."""
    parser = argparse.ArgumentParser(
        description="Scrape municipal codes from Municode library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape single jurisdiction
  %(prog)s https://library.municode.com/wa/seattle

  # Save to file with IPFS
  %(prog)s https://library.municode.com/wa/seattle \\
    --output seattle.json \\
    --enable-ipfs

  # Batch scrape from file
  %(prog)s --batch jurisdictions.txt \\
    --output-dir ./scraped \\
    --format json

  # Import from Common Crawl
  %(prog)s --import-warc "library.municode.com/wa/*" \\
    --index CC-MAIN-2025-47 \\
    --max-records 100
        """
    )
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "url",
        nargs="?",
        help="Jurisdiction URL to scrape"
    )
    input_group.add_argument(
        "--batch",
        "-b",
        help="File with list of jurisdiction URLs (one per line)"
    )
    input_group.add_argument(
        "--import-warc",
        metavar="PATTERN",
        help="Import from Common Crawl (URL pattern)"
    )
    
    # Output options
    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "--output",
        "-o",
        help="Output file (default: stdout)"
    )
    output_group.add_argument(
        "--output-dir",
        "-d",
        help="Output directory for batch scraping"
    )
    output_group.add_argument(
        "--format",
        "-f",
        choices=["json", "parquet", "csv", "warc"],
        default="json",
        help="Output format (default: json)"
    )
    
    # Scraping options
    scrape_group = parser.add_argument_group("scraping options")
    scrape_group.add_argument(
        "--enable-ipfs",
        action="store_true",
        help="Store scraped content in IPFS"
    )
    scrape_group.add_argument(
        "--enable-warc",
        action="store_true",
        help="Enable WARC import/export"
    )
    scrape_group.add_argument(
        "--check-archives",
        action="store_true",
        default=True,
        help="Check Common Crawl/Wayback before scraping (default: True)"
    )
    scrape_group.add_argument(
        "--no-check-archives",
        action="store_false",
        dest="check_archives",
        help="Skip archive checking"
    )
    scrape_group.add_argument(
        "--cache-dir",
        help="Cache directory (default: ./legal_scraper_cache/municode)"
    )
    scrape_group.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum concurrent requests for batch scraping (default: 5)"
    )
    
    # WARC import options
    warc_group = parser.add_argument_group("WARC import options")
    warc_group.add_argument(
        "--index",
        default="CC-MAIN-2025-47",
        help="Common Crawl index ID (default: CC-MAIN-2025-47)"
    )
    warc_group.add_argument(
        "--max-records",
        type=int,
        default=100,
        help="Maximum records to import from Common Crawl (default: 100)"
    )
    
    # Other options
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Quiet output (errors only)"
    )
    
    return parser


async def scrape_single(args, scraper: MunicodeScraper):
    """Scrape a single jurisdiction."""
    result = await scraper.scrape(args.url)
    return [result]


async def scrape_batch(args, scraper: MunicodeScraper):
    """Scrape multiple jurisdictions from file."""
    # Read URLs from file
    urls = []
    with open(args.batch, 'r') as f:
        for line in f:
            url = line.strip()
            if url and not url.startswith('#'):
                urls.append(url)
    
    print(f"Loaded {len(urls)} URLs from {args.batch}")
    
    # Scrape all URLs
    results = await scraper.scrape_multiple(
        jurisdiction_urls=urls,
        max_concurrent=args.max_concurrent
    )
    
    return results


async def import_warc(args, scraper: MunicodeScraper):
    """Import from Common Crawl."""
    if not args.enable_warc:
        print("Error: --enable-warc required for WARC import", file=sys.stderr)
        sys.exit(1)
    
    print(f"Importing from Common Crawl index: {args.index}")
    print(f"URL pattern: {args.import_warc}")
    
    records = await scraper.import_from_common_crawl(
        url_pattern=args.import_warc,
        index_id=args.index,
        max_records=args.max_records
    )
    
    print(f"Imported {len(records)} records")
    return records


def save_results(results: List[dict], args):
    """Save results to file or stdout."""
    if args.format == "json":
        output = json.dumps(results, indent=2)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Saved to {args.output}")
        else:
            print(output)
    
    elif args.format == "parquet":
        try:
            import pandas as pd
            df = pd.DataFrame(results)
            output_file = args.output or "output.parquet"
            df.to_parquet(output_file)
            print(f"Saved to {output_file}")
        except ImportError:
            print("Error: pandas required for parquet format", file=sys.stderr)
            sys.exit(1)
    
    elif args.format == "csv":
        try:
            import pandas as pd
            df = pd.DataFrame(results)
            output_file = args.output or "output.csv"
            df.to_csv(output_file, index=False)
            print(f"Saved to {output_file}")
        except ImportError:
            print("Error: pandas required for CSV format", file=sys.stderr)
            sys.exit(1)
    
    elif args.format == "warc":
        if not args.enable_warc:
            print("Error: --enable-warc required for WARC format", file=sys.stderr)
            sys.exit(1)
        
        # WARC export handled by scraper
        print("WARC export not yet implemented for CLI")


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Setup logging
    import logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    elif args.quiet:
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Initialize scraper
    scraper = MunicodeScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives,
        output_format=args.format
    )
    
    # Run appropriate scraping mode
    try:
        if args.url:
            results = run_async_scraper(scrape_single(args, scraper))
        elif args.batch:
            results = run_async_scraper(scrape_batch(args, scraper))
        elif args.import_warc:
            results = run_async_scraper(import_warc(args, scraper))
        else:
            parser.print_help()
            sys.exit(1)
        
        # Save results
        save_results(results, args)
        
        # Print summary
        if not args.quiet:
            success = sum(1 for r in results if r.get('status') == 'success')
            cached = sum(1 for r in results if r.get('status') == 'cached')
            errors = sum(1 for r in results if r.get('status') == 'error')
            
            print(f"\nSummary:")
            print(f"  Success: {success}")
            print(f"  Cached: {cached}")
            print(f"  Errors: {errors}")
            print(f"  Total: {len(results)}")
    
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
