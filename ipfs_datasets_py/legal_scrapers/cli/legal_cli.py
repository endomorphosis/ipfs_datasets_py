#!/usr/bin/env python3
"""
Legal Dataset CLI Tool

Command-line interface for legal data scraping.
Uses the same core scrapers as the package imports and MCP tools.

Usage:
    # Scrape state laws
    python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli state-laws --states CA NY TX
    
    # Scrape US Code
    python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli us-code --titles 18 42
    
    # Scrape Federal Register
    python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli federal-register --agency EPA --start-date 2024-01-01
    
    # Scrape RECAP documents
    python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli recap --query "climate change" --court ca9
    
    # Scrape municipal codes
    python -m ipfs_datasets_py.legal_scrapers.cli.legal_cli municipal --provider municode --jurisdiction "New York, NY"
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any

# Import core scrapers
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from ipfs_datasets_py.legal_scrapers.core.state_laws import StateLawsScraper
    from ipfs_datasets_py.legal_scrapers.core.us_code import USCodeScraper
    from ipfs_datasets_py.legal_scrapers.core.federal_register import FederalRegisterScraper
    from ipfs_datasets_py.legal_scrapers.core.recap import RECAPScraper
    from ipfs_datasets_py.legal_scrapers.core.municode import MunicodeScraper
    from ipfs_datasets_py.legal_scrapers.core.ecode360 import ECode360Scraper
    HAVE_CORE_SCRAPERS = True
except ImportError as e:
    print(f"Error: Failed to import core scrapers: {e}", file=sys.stderr)
    HAVE_CORE_SCRAPERS = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def scrape_state_laws_cli(args) -> Dict[str, Any]:
    """CLI command for state laws scraping."""
    scraper = StateLawsScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=not args.no_archives,
        output_format=args.format
    )
    
    states = args.states if args.states else list(StateLawsScraper.STATE_URLS.keys())
    
    results = []
    for state in states:
        try:
            logger.info(f"Scraping state laws for {state}...")
            result = await scraper.scrape(state_code=state)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to scrape {state}: {e}")
            results.append({"state": state, "status": "error", "error": str(e)})
    
    return {"status": "success", "results": results}


async def scrape_us_code_cli(args) -> Dict[str, Any]:
    """CLI command for US Code scraping."""
    scraper = USCodeScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=not args.no_archives,
        output_format=args.format
    )
    
    titles = args.titles if args.titles else list(USCodeScraper.TITLES.keys())
    
    results = []
    for title in titles:
        try:
            logger.info(f"Scraping US Code Title {title}...")
            result = await scraper.scrape(title=int(title))
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to scrape title {title}: {e}")
            results.append({"title": title, "status": "error", "error": str(e)})
    
    return {"status": "success", "results": results}


async def scrape_federal_register_cli(args) -> Dict[str, Any]:
    """CLI command for Federal Register scraping."""
    scraper = FederalRegisterScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=not args.no_archives
    )
    
    result = await scraper.scrape(
        agency=args.agency,
        date=args.start_date,
        document_type=args.doc_type
    )
    
    return result


async def scrape_recap_cli(args) -> Dict[str, Any]:
    """CLI command for RECAP scraping."""
    scraper = RECAPScraper(
        cache_dir=args.cache_dir,
        enable_ipfs=args.enable_ipfs,
        enable_warc=args.enable_warc,
        check_archives=not args.no_archives
    )
    
    result = await scraper.scrape(
        query=args.query,
        court=args.court,
        case_name=args.case_name,
        filed_after=args.filed_after,
        filed_before=args.filed_before,
        document_type=args.doc_type,
        api_token=args.api_token,
        limit=args.limit
    )
    
    return result


async def scrape_municipal_cli(args) -> Dict[str, Any]:
    """CLI command for municipal code scraping."""
    if args.provider == "municode":
        scraper = MunicodeScraper(
            cache_dir=args.cache_dir,
            enable_ipfs=args.enable_ipfs,
            enable_warc=args.enable_warc,
            check_archives=not args.no_archives
        )
    elif args.provider == "ecode360":
        scraper = ECode360Scraper(
            cache_dir=args.cache_dir,
            enable_ipfs=args.enable_ipfs,
            enable_warc=args.enable_warc,
            check_archives=not args.no_archives
        )
    else:
        return {"status": "error", "error": f"Unknown provider: {args.provider}"}
    
    result = await scraper.scrape(jurisdiction=args.jurisdiction)
    
    return result


def main():
    """Main CLI entry point."""
    if not HAVE_CORE_SCRAPERS:
        print("Error: Core scrapers not available. Check installation.", file=sys.stderr)
        sys.exit(1)
    
    parser = argparse.ArgumentParser(
        description="Legal Dataset Scraper CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Global options
    parser.add_argument("--cache-dir", default="./legal_scraper_cache", help="Cache directory")
    parser.add_argument("--enable-ipfs", action="store_true", help="Enable IPFS storage")
    parser.add_argument("--enable-warc", action="store_true", default=True, help="Enable WARC export")
    parser.add_argument("--no-archives", action="store_true", help="Skip archive checks")
    parser.add_argument("--format", choices=["json", "parquet", "csv"], default="json", help="Output format")
    parser.add_argument("--output", "-o", help="Output file path")
    
    subparsers = parser.add_subparsers(dest="command", help="Scraper command")
    
    # State laws command
    state_parser = subparsers.add_parser("state-laws", help="Scrape state laws")
    state_parser.add_argument("--states", nargs="+", help="State codes (e.g., CA NY TX)")
    
    # US Code command
    usc_parser = subparsers.add_parser("us-code", help="Scrape US Code")
    usc_parser.add_argument("--titles", nargs="+", type=int, help="Title numbers")
    
    # Federal Register command
    fr_parser = subparsers.add_parser("federal-register", help="Scrape Federal Register")
    fr_parser.add_argument("--agency", help="Agency abbreviation")
    fr_parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    fr_parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    fr_parser.add_argument("--doc-type", help="Document type")
    
    # RECAP command
    recap_parser = subparsers.add_parser("recap", help="Scrape RECAP documents")
    recap_parser.add_argument("--query", help="Search query")
    recap_parser.add_argument("--court", help="Court identifier")
    recap_parser.add_argument("--case-name", help="Case name")
    recap_parser.add_argument("--filed-after", help="Filed after date (YYYY-MM-DD)")
    recap_parser.add_argument("--filed-before", help="Filed before date (YYYY-MM-DD)")
    recap_parser.add_argument("--doc-type", help="Document type")
    recap_parser.add_argument("--api-token", help="CourtListener API token")
    recap_parser.add_argument("--limit", type=int, default=100, help="Result limit")
    
    # Municipal codes command
    muni_parser = subparsers.add_parser("municipal", help="Scrape municipal codes")
    muni_parser.add_argument("--provider", required=True, choices=["municode", "ecode360"], help="Code provider")
    muni_parser.add_argument("--jurisdiction", required=True, help="Jurisdiction name")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute command
    try:
        if args.command == "state-laws":
            result = asyncio.run(scrape_state_laws_cli(args))
        elif args.command == "us-code":
            result = asyncio.run(scrape_us_code_cli(args))
        elif args.command == "federal-register":
            result = asyncio.run(scrape_federal_register_cli(args))
        elif args.command == "recap":
            result = asyncio.run(scrape_recap_cli(args))
        elif args.command == "municipal":
            result = asyncio.run(scrape_municipal_cli(args))
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            sys.exit(1)
        
        # Output results
        output_text = json.dumps(result, indent=2)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output_text)
            logger.info(f"Results written to {args.output}")
        else:
            print(output_text)
        
        # Exit with appropriate code
        if result.get("status") == "error":
            sys.exit(1)
        else:
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"Command failed: {e}")
        print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
