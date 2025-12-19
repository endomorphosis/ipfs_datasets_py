#!/usr/bin/env python3
"""
Unified Web Scraper CLI

Command-line interface for the unified web scraping system with automatic fallbacks.

Usage:
    python -m ipfs_datasets_py.scraper_cli scrape <url> [--method METHOD]
    python -m ipfs_datasets_py.scraper_cli scrape-multiple <url1> <url2> ... [--method METHOD]
    python -m ipfs_datasets_py.scraper_cli check-methods
    python -m ipfs_datasets_py.scraper_cli scrape-file <file> [--method METHOD]

Examples:
    # Scrape with automatic fallback
    python -m ipfs_datasets_py.scraper_cli scrape https://example.com
    
    # Scrape with specific method
    python -m ipfs_datasets_py.scraper_cli scrape https://example.com --method playwright
    
    # Scrape multiple URLs
    python -m ipfs_datasets_py.scraper_cli scrape-multiple https://example.com https://example.org
    
    # Scrape URLs from a file
    python -m ipfs_datasets_py.scraper_cli scrape-file urls.txt
    
    # Check available methods
    python -m ipfs_datasets_py.scraper_cli check-methods
"""

import sys
import argparse
import json
import asyncio
from pathlib import Path
from typing import List

from ipfs_datasets_py.unified_web_scraper import (
    UnifiedWebScraper,
    ScraperConfig,
    ScraperMethod,
    scrape_url,
    scrape_urls
)


def scrape_url_command(args):
    """Scrape a single URL."""
    print(f"Scraping: {args.url}")
    
    # Create config
    config = ScraperConfig(
        timeout=args.timeout,
        extract_links=args.extract_links,
        extract_text=True,
        fallback_enabled=not args.no_fallback
    )
    
    scraper = UnifiedWebScraper(config)
    
    # Parse method
    method = None
    if args.method:
        try:
            method = ScraperMethod(args.method.lower())
        except ValueError:
            print(f"Error: Invalid method '{args.method}'")
            print(f"Valid methods: {', '.join([m.value for m in ScraperMethod])}")
            return 1
    
    # Scrape
    result = scraper.scrape_sync(args.url, method=method)
    
    if result.success:
        print(f"✓ Successfully scraped using {result.method_used.value if result.method_used else 'unknown'}")
        print(f"Title: {result.title}")
        print(f"Content length: {len(result.content)} chars")
        print(f"Links found: {len(result.links)}")
        print(f"Extraction time: {result.extraction_time:.2f}s")
        
        # Output content
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if args.format == 'json':
                with open(output_path, 'w') as f:
                    json.dump(result.to_dict(), f, indent=2)
                print(f"Saved to: {output_path}")
            elif args.format == 'text':
                with open(output_path, 'w') as f:
                    f.write(f"URL: {result.url}\n")
                    f.write(f"Title: {result.title}\n")
                    f.write(f"Method: {result.method_used.value if result.method_used else 'unknown'}\n")
                    f.write(f"Timestamp: {result.timestamp}\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(result.text)
                print(f"Saved to: {output_path}")
            elif args.format == 'html':
                with open(output_path, 'w') as f:
                    f.write(result.html)
                print(f"Saved to: {output_path}")
        
        # Print preview
        if args.preview:
            print("\nContent preview:")
            print("-" * 80)
            print(result.text[:500] + ("..." if len(result.text) > 500 else ""))
            print("-" * 80)
        
        return 0
    else:
        print(f"✗ Failed to scrape {args.url}")
        print("Errors:")
        for error in result.errors:
            print(f"  - {error}")
        return 1


def scrape_multiple_command(args):
    """Scrape multiple URLs."""
    print(f"Scraping {len(args.urls)} URLs...")
    
    # Create config
    config = ScraperConfig(
        timeout=args.timeout,
        extract_links=args.extract_links,
        fallback_enabled=not args.no_fallback
    )
    
    scraper = UnifiedWebScraper(config)
    
    # Parse method
    method = None
    if args.method:
        try:
            method = ScraperMethod(args.method.lower())
        except ValueError:
            print(f"Error: Invalid method '{args.method}'")
            return 1
    
    # Scrape
    results = scraper.scrape_multiple_sync(
        args.urls,
        max_concurrent=args.concurrent,
        method=method
    )
    
    # Print results
    successful = 0
    failed = 0
    
    for i, result in enumerate(results, 1):
        if result.success:
            successful += 1
            print(f"[{i}/{len(results)}] ✓ {result.url} ({result.method_used.value if result.method_used else 'unknown'})")
        else:
            failed += 1
            print(f"[{i}/{len(results)}] ✗ {result.url} - {result.errors[0] if result.errors else 'Unknown error'}")
    
    print(f"\nResults: {successful} successful, {failed} failed")
    
    # Save results
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        output_data = [r.to_dict() for r in results]
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"Saved results to: {output_path}")
    
    return 0 if failed == 0 else 1


def scrape_file_command(args):
    """Scrape URLs from a file."""
    urls_file = Path(args.file)
    
    if not urls_file.exists():
        print(f"Error: File not found: {urls_file}")
        return 1
    
    # Read URLs
    with open(urls_file, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"Loaded {len(urls)} URLs from {urls_file}")
    
    # Create a namespace with the URLs for scrape_multiple_command
    import argparse
    file_args = argparse.Namespace(
        urls=urls,
        method=args.method,
        timeout=args.timeout,
        concurrent=args.concurrent,
        extract_links=args.extract_links,
        no_fallback=args.no_fallback,
        output=args.output
    )
    
    return scrape_multiple_command(file_args)


def check_methods_command(args):
    """Check available scraping methods."""
    scraper = UnifiedWebScraper()
    
    print("Unified Web Scraper - Available Methods")
    print("=" * 60)
    
    available_count = 0
    unavailable_count = 0
    
    for method in ScraperMethod:
        is_available = scraper.available_methods.get(method, False)
        status = "✓ Available" if is_available else "✗ Not available"
        print(f"{method.value:20} {status}")
        
        if is_available:
            available_count += 1
        else:
            unavailable_count += 1
    
    print("=" * 60)
    print(f"Available: {available_count}, Not available: {unavailable_count}")
    
    if unavailable_count > 0:
        print("\nTo install missing dependencies:")
        print("  pip install playwright beautifulsoup4 requests wayback cdx-toolkit")
        print("  pip install ipwb newspaper3k readability-lxml")
        print("  playwright install  # For Playwright browser support")
    
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Unified Web Scraper with automatic fallback mechanisms",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Scrape single URL
    scrape_parser = subparsers.add_parser('scrape', help='Scrape a single URL')
    scrape_parser.add_argument('url', help='URL to scrape')
    scrape_parser.add_argument('--method', help='Scraping method to use')
    scrape_parser.add_argument('--timeout', type=int, default=30, help='Request timeout (seconds)')
    scrape_parser.add_argument('--output', '-o', help='Output file path')
    scrape_parser.add_argument('--format', choices=['json', 'text', 'html'], default='text', help='Output format')
    scrape_parser.add_argument('--no-fallback', action='store_true', help='Disable fallback mechanisms')
    scrape_parser.add_argument('--no-links', dest='extract_links', action='store_false', help='Don\'t extract links')
    scrape_parser.add_argument('--preview', action='store_true', help='Show content preview')
    
    # Scrape multiple URLs
    multiple_parser = subparsers.add_parser('scrape-multiple', help='Scrape multiple URLs')
    multiple_parser.add_argument('urls', nargs='+', help='URLs to scrape')
    multiple_parser.add_argument('--method', help='Scraping method to use')
    multiple_parser.add_argument('--timeout', type=int, default=30, help='Request timeout (seconds)')
    multiple_parser.add_argument('--concurrent', type=int, default=5, help='Max concurrent requests')
    multiple_parser.add_argument('--output', '-o', help='Output JSON file path')
    multiple_parser.add_argument('--no-fallback', action='store_true', help='Disable fallback mechanisms')
    multiple_parser.add_argument('--no-links', dest='extract_links', action='store_false', help='Don\'t extract links')
    
    # Scrape from file
    file_parser = subparsers.add_parser('scrape-file', help='Scrape URLs from a file')
    file_parser.add_argument('file', help='File containing URLs (one per line)')
    file_parser.add_argument('--method', help='Scraping method to use')
    file_parser.add_argument('--timeout', type=int, default=30, help='Request timeout (seconds)')
    file_parser.add_argument('--concurrent', type=int, default=5, help='Max concurrent requests')
    file_parser.add_argument('--output', '-o', help='Output JSON file path')
    file_parser.add_argument('--no-fallback', action='store_true', help='Disable fallback mechanisms')
    file_parser.add_argument('--no-links', dest='extract_links', action='store_false', help='Don\'t extract links')
    
    # Check methods
    check_parser = subparsers.add_parser('check-methods', help='Check available scraping methods')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    if args.command == 'scrape':
        return scrape_url_command(args)
    elif args.command == 'scrape-multiple':
        return scrape_multiple_command(args)
    elif args.command == 'scrape-file':
        return scrape_file_command(args)
    elif args.command == 'check-methods':
        return check_methods_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
