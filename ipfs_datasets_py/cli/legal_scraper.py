#!/usr/bin/env python3
"""
Legal Scraper CLI Command

Unified CLI interface for all legal data scrapers.

Usage:
    ipfs-datasets legal-scraper municode <url> [options]
    ipfs-datasets legal-scraper state-laws <state> [options]
    ipfs-datasets legal-scraper federal-register [options]
    ipfs-datasets legal-scraper us-code [options]
"""

import argparse
import asyncio
import json
import sys
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def add_legal_scraper_subcommands(subparsers):
    """Add legal scraper subcommands to main CLI parser."""
    
    # Main legal-scraper command
    legal_parser = subparsers.add_parser(
        'legal-scraper',
        help='Legal data scraping tools',
        description='Scrape legal datasets with content addressing and WARC support'
    )
    
    legal_subparsers = legal_parser.add_subparsers(dest='scraper_type', required=True)
    
    # Common arguments for all scrapers
    def add_common_args(parser):
        """Add common arguments to a scraper parser."""
        parser.add_argument(
            '--output', '-o',
            help='Output file (default: stdout for JSON)'
        )
        parser.add_argument(
            '--format', '-f',
            choices=['json', 'parquet', 'csv', 'warc'],
            default='json',
            help='Output format (default: json)'
        )
        parser.add_argument(
            '--enable-ipfs',
            action='store_true',
            help='Store scraped content in IPFS'
        )
        parser.add_argument(
            '--enable-warc',
            action='store_true',
            help='Enable WARC import/export'
        )
        parser.add_argument(
            '--check-archives',
            action='store_true',
            default=True,
            help='Check Common Crawl/Wayback before scraping (default: True)'
        )
        parser.add_argument(
            '--no-check-archives',
            action='store_false',
            dest='check_archives',
            help='Skip archive checking'
        )
        parser.add_argument(
            '--cache-dir',
            help='Cache directory for scraped content'
        )
        parser.add_argument(
            '--verbose', '-v',
            action='store_true',
            help='Verbose output'
        )
        parser.add_argument(
            '--quiet', '-q',
            action='store_true',
            help='Quiet output (errors only)'
        )
    
    # Municode scraper
    municode_parser = legal_subparsers.add_parser(
        'municode',
        help='Scrape Municode jurisdictions (3,500+ jurisdictions)'
    )
    municode_input = municode_parser.add_mutually_exclusive_group(required=True)
    municode_input.add_argument(
        'url',
        nargs='?',
        help='Jurisdiction URL (e.g., https://library.municode.com/wa/seattle)'
    )
    municode_input.add_argument(
        '--batch', '-b',
        help='File with list of jurisdiction URLs (one per line)'
    )
    municode_input.add_argument(
        '--import-warc',
        metavar='PATTERN',
        help='Import from Common Crawl (URL pattern)'
    )
    municode_parser.add_argument(
        '--index',
        default='CC-MAIN-2025-47',
        help='Common Crawl index ID (default: CC-MAIN-2025-47)'
    )
    municode_parser.add_argument(
        '--max-records',
        type=int,
        default=100,
        help='Maximum records to import from Common Crawl (default: 100)'
    )
    municode_parser.add_argument(
        '--max-concurrent',
        type=int,
        default=5,
        help='Maximum concurrent requests for batch scraping (default: 5)'
    )
    add_common_args(municode_parser)
    municode_parser.set_defaults(func=cmd_municode)
    
    # State laws scraper
    state_parser = legal_subparsers.add_parser(
        'state-laws',
        help='Scrape state legislation'
    )
    state_parser.add_argument(
        'state',
        help='State code (e.g., CA, NY, WA)'
    )
    state_parser.add_argument(
        '--bill-id',
        help='Specific bill ID to scrape'
    )
    add_common_args(state_parser)
    state_parser.set_defaults(func=cmd_state_laws)
    
    # Federal Register scraper
    fed_parser = legal_subparsers.add_parser(
        'federal-register',
        help='Scrape Federal Register documents'
    )
    fed_parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD)'
    )
    fed_parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD)'
    )
    fed_parser.add_argument(
        '--agency',
        help='Filter by agency'
    )
    add_common_args(fed_parser)
    fed_parser.set_defaults(func=cmd_federal_register)
    
    # US Code scraper
    uscode_parser = legal_subparsers.add_parser(
        'us-code',
        help='Scrape US Code sections'
    )
    uscode_parser.add_argument(
        '--title',
        help='Title number'
    )
    uscode_parser.add_argument(
        '--section',
        help='Section number'
    )
    add_common_args(uscode_parser)
    uscode_parser.set_defaults(func=cmd_us_code)
    
    # ECode360 scraper
    ecode_parser = legal_subparsers.add_parser(
        'ecode360',
        help='Scrape eCode360 municipal codes'
    )
    ecode_parser.add_argument(
        'url',
        help='eCode360 jurisdiction URL'
    )
    add_common_args(ecode_parser)
    ecode_parser.set_defaults(func=cmd_ecode360)
    
    # Municipal code scraper (generic)
    muni_parser = legal_subparsers.add_parser(
        'municipal-code',
        help='Scrape generic municipal codes'
    )
    muni_parser.add_argument(
        'url',
        help='Municipal code URL'
    )
    add_common_args(muni_parser)
    muni_parser.set_defaults(func=cmd_municipal_code)


def setup_logging(args):
    """Setup logging based on verbosity."""
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    elif args.quiet:
        logging.basicConfig(level=logging.ERROR, format='%(levelname)s: %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')


def save_results(results: List[dict], args):
    """Save results to file or stdout."""
    if args.format == "json":
        output = json.dumps(results, indent=2)
        
        if args.output:
            Path(args.output).write_text(output)
            if not args.quiet:
                print(f"Saved to {args.output}")
        else:
            print(output)
    
    elif args.format == "parquet":
        try:
            import pandas as pd
            df = pd.DataFrame(results)
            output_file = args.output or "output.parquet"
            df.to_parquet(output_file)
            if not args.quiet:
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
            if not args.quiet:
                print(f"Saved to {output_file}")
        except ImportError:
            print("Error: pandas required for CSV format", file=sys.stderr)
            sys.exit(1)


def print_summary(results: List[dict], quiet: bool = False):
    """Print scraping summary."""
    if not quiet and results:
        success = sum(1 for r in results if r.get('status') == 'success')
        cached = sum(1 for r in results if r.get('status') == 'cached')
        errors = sum(1 for r in results if r.get('status') == 'error')
        
        print(f"\nSummary:")
        print(f"  Success: {success}")
        print(f"  Cached: {cached}")
        print(f"  Errors: {errors}")
        print(f"  Total: {len(results)}")


async def cmd_municode(args):
    """Handle Municode scraping."""
    from ipfs_datasets_py.legal_scrapers import MunicodeScraper, run_async_scraper
    
    setup_logging(args)
    
    scraper = MunicodeScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives,
        output_format=args.format
    )
    
    try:
        if args.url:
            # Single URL
            result = await scraper.scrape(args.url)
            results = [result]
        
        elif args.batch:
            # Batch scraping
            urls = []
            with open(args.batch, 'r') as f:
                for line in f:
                    url = line.strip()
                    if url and not url.startswith('#'):
                        urls.append(url)
            
            if not args.quiet:
                print(f"Loaded {len(urls)} URLs from {args.batch}")
            
            results = await scraper.scrape_multiple(
                jurisdiction_urls=urls,
                max_concurrent=args.max_concurrent
            )
        
        elif args.import_warc:
            # WARC import
            if not args.enable_warc:
                print("Error: --enable-warc required for WARC import", file=sys.stderr)
                return 1
            
            if not args.quiet:
                print(f"Importing from Common Crawl index: {args.index}")
                print(f"URL pattern: {args.import_warc}")
            
            results = await scraper.import_from_common_crawl(
                url_pattern=args.import_warc,
                index_id=args.index,
                max_records=args.max_records
            )
        
        # Save and print results
        save_results(results, args)
        print_summary(results, args.quiet)
        
        return 0
    
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


async def cmd_state_laws(args):
    """Handle state laws scraping."""
    from ipfs_datasets_py.legal_scrapers import StateLawsScraper
    
    setup_logging(args)
    
    scraper = StateLawsScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives
    )
    
    try:
        if args.bill_id:
            result = await scraper.scrape_bill(args.state, args.bill_id)
            results = [result]
        else:
            result = await scraper.scrape_state(args.state)
            results = [result]
        
        save_results(results, args)
        print_summary(results, args.quiet)
        return 0
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


async def cmd_federal_register(args):
    """Handle Federal Register scraping."""
    from ipfs_datasets_py.legal_scrapers import FederalRegisterScraper
    
    setup_logging(args)
    
    scraper = FederalRegisterScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives
    )
    
    try:
        result = await scraper.scrape(
            start_date=args.start_date,
            end_date=args.end_date,
            agency=args.agency
        )
        results = [result]
        
        save_results(results, args)
        print_summary(results, args.quiet)
        return 0
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


async def cmd_us_code(args):
    """Handle US Code scraping."""
    from ipfs_datasets_py.legal_scrapers import USCodeScraper
    
    setup_logging(args)
    
    scraper = USCodeScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives
    )
    
    try:
        result = await scraper.scrape(
            title=args.title,
            section=args.section
        )
        results = [result]
        
        save_results(results, args)
        print_summary(results, args.quiet)
        return 0
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


async def cmd_ecode360(args):
    """Handle eCode360 scraping."""
    from ipfs_datasets_py.legal_scrapers import ECode360Scraper
    
    setup_logging(args)
    
    scraper = ECode360Scraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives
    )
    
    try:
        result = await scraper.scrape(args.url)
        results = [result]
        
        save_results(results, args)
        print_summary(results, args.quiet)
        return 0
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


async def cmd_municipal_code(args):
    """Handle generic municipal code scraping."""
    from ipfs_datasets_py.legal_scrapers import MunicipalCodeScraper
    
    setup_logging(args)
    
    scraper = MunicipalCodeScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=args.check_archives
    )
    
    try:
        result = await scraper.scrape(args.url)
        results = [result]
        
        save_results(results, args)
        print_summary(results, args.quiet)
        return 0
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def main(args=None):
    """Main entry point for legal scraper CLI."""
    parser = argparse.ArgumentParser(
        description='Legal Data Scraper CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True)
    add_legal_scraper_subcommands(subparsers)
    
    parsed_args = parser.parse_args(args)
    
    # Run the appropriate command
    if hasattr(parsed_args, 'func'):
        exit_code = asyncio.run(parsed_args.func(parsed_args))
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
