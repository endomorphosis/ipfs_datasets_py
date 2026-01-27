#!/usr/bin/env python3
"""
Finance Dashboard CLI Tool.

Command-line interface for finance dashboard functionality including:
- Stock data scraping
- News intelligence gathering
- Executive profile analysis
- Vector embedding correlation
- Financial theorem application

Usage:
    ipfs-datasets finance [command] [options]
    python -m ipfs_datasets_py.finance_cli [command] [options]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Optional


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for finance CLI."""
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets finance',
        description='Finance Dashboard CLI Tool'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Stock data command
    stock_parser = subparsers.add_parser('stock', help='Fetch stock market data')
    stock_parser.add_argument('symbol', help='Stock ticker symbol (e.g., AAPL)')
    stock_parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    stock_parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    stock_parser.add_argument('--interval', default='1d', help='Data interval (1d, 1h, etc.)')
    stock_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # News scraping command
    news_parser = subparsers.add_parser('news', help='Fetch financial news')
    news_parser.add_argument('topic', help='News topic or search query')
    news_parser.add_argument('--sources', default='reuters,ap,bloomberg', 
                            help='Comma-separated news sources')
    news_parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    news_parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    news_parser.add_argument('--max-articles', type=int, default=100, 
                            help='Maximum articles to fetch')
    news_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Executive analysis command
    exec_parser = subparsers.add_parser('executives', help='Analyze executive performance')
    exec_parser.add_argument('--news', required=True, help='News articles JSON file')
    exec_parser.add_argument('--stocks', required=True, help='Stock data JSON file')
    exec_parser.add_argument('--hypothesis', required=True, 
                            help='Hypothesis to test (e.g., "Female CEOs outperform male CEOs")')
    exec_parser.add_argument('--attribute', required=True, 
                            help='Attribute to compare (e.g., gender, personality_traits)')
    exec_parser.add_argument('--group-a', required=True, help='Value for group A (e.g., female)')
    exec_parser.add_argument('--group-b', required=True, help='Value for group B (e.g., male)')
    exec_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Embedding correlation command
    embed_parser = subparsers.add_parser('embeddings', help='Analyze embedding correlations')
    embed_parser.add_argument('--news', required=True, help='News articles JSON file')
    embed_parser.add_argument('--stocks', required=True, help='Stock data JSON file')
    embed_parser.add_argument('--multimodal', action='store_true', 
                             help='Enable multimodal (text + image) analysis')
    embed_parser.add_argument('--time-window', type=int, default=24, 
                             help='Time window in hours for market impact')
    embed_parser.add_argument('--clusters', type=int, default=10, 
                             help='Number of clusters for pattern discovery')
    embed_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Theorems command
    theorem_parser = subparsers.add_parser('theorems', help='List or apply financial theorems')
    theorem_parser.add_argument('--list', action='store_true', help='List all available theorems')
    theorem_parser.add_argument('--apply', help='Apply theorem by ID')
    theorem_parser.add_argument('--event-type', help='Filter by event type')
    theorem_parser.add_argument('--data', help='Event data JSON for theorem application')
    theorem_parser.add_argument('--output', '-o', help='Output JSON file')
    
    return parser


def cmd_stock(args) -> int:
    """Execute stock data fetching command."""
    try:
        from ipfs_datasets_py.finance import get_stock_data
        
        result = get_stock_data(
            symbol=args.symbol,
            start_date=args.start or (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
            end_date=args.end or datetime.now().strftime('%Y-%m-%d'),
            interval=args.interval
        )
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"✓ Stock data saved to {args.output}")
        else:
            print(json.dumps(result, indent=2))
        
        return 0
    except Exception as e:
        print(f"✗ Error fetching stock data: {e}", file=sys.stderr)
        return 1


def cmd_news(args) -> int:
    """Execute news scraping command."""
    try:
        from ipfs_datasets_py.finance import scrape_financial_news
        
        result = scrape_financial_news(
            topic=args.topic,
            start_date=args.start or (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
            end_date=args.end or datetime.now().strftime('%Y-%m-%d'),
            sources=args.sources.split(','),
            max_articles=args.max_articles
        )
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(json.dumps(result, indent=2))
            print(f"✓ News data saved to {args.output}")
        else:
            print(json.dumps(result, indent=2))
        
        return 0
    except Exception as e:
        print(f"✗ Error fetching news: {e}", file=sys.stderr)
        return 1


def cmd_executives(args) -> int:
    """Execute executive analysis command."""
    try:
        from ipfs_datasets_py.finance import analyze_news_with_graphrag
        
        # Load input files
        with open(args.news, 'r') as f:
            news_data = json.load(f)
        
        with open(args.stocks, 'r') as f:
            stock_data = json.load(f)
        
        result = analyze_news_with_graphrag(
            news_articles=news_data,
            stock_data=stock_data,
            analysis_type='executive_performance',
            hypothesis=args.hypothesis,
            attribute=args.attribute,
            groups={'A': args.group_a, 'B': args.group_b}
        )
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"✓ Analysis saved to {args.output}")
        else:
            print(json.dumps(result, indent=2))
        
        return 0
    except Exception as e:
        print(f"✗ Error analyzing executives: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def cmd_embeddings(args) -> int:
    """Execute embedding correlation command."""
    try:
        from ipfs_datasets_py.finance import analyze_multimodal_correlations
        
        # Load input files
        with open(args.news, 'r') as f:
            news_data = json.load(f)
        
        with open(args.stocks, 'r') as f:
            stock_data = json.load(f)
        
        result = analyze_multimodal_correlations(
            news_articles=news_data,
            stock_data=stock_data,
            enable_multimodal=args.multimodal,
            time_window=args.time_window,
            n_clusters=args.clusters
        )
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"✓ Embedding analysis saved to {args.output}")
        else:
            print(json.dumps(result, indent=2))
        
        return 0
    except Exception as e:
        print(f"✗ Error analyzing embeddings: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def cmd_theorems(args) -> int:
    """Execute theorems command."""
    try:
        from ipfs_datasets_py.finance import list_finance_theorems, apply_theorem
        
        if args.list:
            result = list_finance_theorems(event_type=args.event_type)
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"✓ Theorems list saved to {args.output}")
            else:
                print(json.dumps(result, indent=2))
        
        elif args.apply:
            if not args.data:
                print("✗ Error: --data required for theorem application", file=sys.stderr)
                return 1
            
            with open(args.data, 'r') as f:
                event_data = json.load(f)
            
            result = apply_theorem(
                theorem_id=args.apply,
                event_data=event_data
            )
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"✓ Theorem application saved to {args.output}")
            else:
                print(json.dumps(result, indent=2))
        else:
            print("✗ Error: Use --list or --apply", file=sys.stderr)
            return 1
        
        return 0
    except Exception as e:
        print(f"✗ Error with theorems: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[list] = None) -> int:
    """Main entry point for finance CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Dispatch to command handlers
    commands = {
        'stock': cmd_stock,
        'news': cmd_news,
        'executives': cmd_executives,
        'embeddings': cmd_embeddings,
        'theorems': cmd_theorems,
    }
    
    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"✗ Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
