#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Legal Search CLI Tool

A dedicated command-line interface for natural language legal search using
the Brave Legal Search system and web archive integration.

Usage Examples:
    # Basic legal search
    python legal_search_cli.py search "EPA water pollution regulations California"
    
    # Generate search terms only
    python legal_search_cli.py terms "housing discrimination laws"
    
    # Explain query processing
    python legal_search_cli.py explain "OSHA workplace safety requirements"
    
    # Search knowledge base
    python legal_search_cli.py entities "EPA"
    
    # Web archive search (current + historical)
    python legal_search_cli.py archive "housing laws" --include-archives
    
    # Historical search with date range
    python legal_search_cli.py historical "California regulations" --from-date 2020-01-01 --to-date 2023-12-31
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ipfs_datasets_py.processors.legal_scrapers import (
        BraveLegalSearch,
        LegalWebArchiveSearch,
        LegalKnowledgeBase
    )
except ImportError as e:
    print(f"Error importing legal search modules: {e}")
    print("Please ensure ipfs_datasets_py is installed.")
    sys.exit(1)


class LegalSearchCLI:
    """Command-line interface for legal search."""
    
    def __init__(self):
        """Initialize CLI."""
        self.brave_search = None
        self.archive_search = None
        self.kb = None
    
    def _init_brave_search(self):
        """Lazy initialize Brave search."""
        if self.brave_search is None:
            self.brave_search = BraveLegalSearch()
        return self.brave_search
    
    def _init_archive_search(self, archive_dir: Optional[str] = None):
        """Lazy initialize archive search."""
        if self.archive_search is None:
            self.archive_search = LegalWebArchiveSearch(
                archive_dir=archive_dir,
                auto_archive=True
            )
        return self.archive_search
    
    def _init_kb(self):
        """Lazy initialize knowledge base."""
        if self.kb is None:
            self.kb = LegalKnowledgeBase()
            self.kb.load_all()
        return self.kb
    
    def search(self, query: str, max_results: int = 10, format: str = 'pretty') -> Dict[str, Any]:
        """Execute a legal search.
        
        Args:
            query: Natural language query
            max_results: Maximum number of results
            format: Output format (pretty, json, compact)
        
        Returns:
            Search results
        """
        searcher = self._init_brave_search()
        results = searcher.search(query, max_results=max_results)
        
        if format == 'json':
            print(json.dumps(results, indent=2))
        elif format == 'compact':
            self._print_compact(results)
        else:
            self._print_pretty(results)
        
        return results
    
    def generate_terms(self, query: str, format: str = 'pretty') -> Dict[str, Any]:
        """Generate search terms without executing search.
        
        Args:
            query: Natural language query
            format: Output format (pretty, json, list)
        
        Returns:
            Query intent and search terms
        """
        searcher = self._init_brave_search()
        
        # Generate terms without searching
        intent = searcher.query_processor.process(query)
        terms = searcher.term_generator.generate(intent)
        
        result = {
            'query': query,
            'intent': {
                'agencies': intent.get('agencies', []),
                'jurisdictions': intent.get('jurisdictions', []),
                'topics': intent.get('topics', []),
                'domains': intent.get('legal_domains', [])
            },
            'search_terms': [
                {'term': term['term'], 'priority': term['priority']}
                for term in terms
            ]
        }
        
        if format == 'json':
            print(json.dumps(result, indent=2))
        elif format == 'list':
            print("\nSearch Terms:")
            for term in result['search_terms']:
                print(f"  • {term['term']} (priority: {term['priority']:.2f})")
        else:
            self._print_intent(result)
        
        return result
    
    def explain(self, query: str) -> Dict[str, Any]:
        """Explain how a query will be processed.
        
        Args:
            query: Natural language query
        
        Returns:
            Explanation of query processing
        """
        searcher = self._init_brave_search()
        
        # Process query
        intent = searcher.query_processor.process(query)
        terms = searcher.term_generator.generate(intent)
        
        print(f"\n📋 Query Analysis for: '{query}'")
        print("=" * 70)
        
        print("\n🎯 Extracted Intent:")
        print(f"  Agencies: {', '.join(intent.get('agencies', [])) or 'None'}")
        print(f"  Jurisdictions: {', '.join(intent.get('jurisdictions', [])) or 'None'}")
        print(f"  Topics: {', '.join(intent.get('topics', [])) or 'None'}")
        print(f"  Legal Domains: {', '.join(intent.get('legal_domains', [])) or 'None'}")
        print(f"  Confidence: {intent.get('confidence', 0):.2f}")
        
        print(f"\n🔍 Generated {len(terms)} Search Terms:")
        for i, term in enumerate(terms[:10], 1):
            print(f"  {i}. {term['term']}")
            print(f"     Priority: {term['priority']:.2f}")
            print(f"     Strategy: {term.get('strategy', 'unknown')}")
        
        if len(terms) > 10:
            print(f"  ... and {len(terms) - 10} more terms")
        
        return {'intent': intent, 'terms': terms}
    
    def search_entities(self, query: str, format: str = 'pretty') -> Dict[str, Any]:
        """Search knowledge base entities.
        
        Args:
            query: Entity name to search
            format: Output format (pretty, json)
        
        Returns:
            Matching entities
        """
        kb = self._init_kb()
        
        # Search in all categories
        results = {
            'federal': kb.find_entities_by_name(query, category='federal'),
            'state': kb.find_entities_by_name(query, category='state'),
            'municipal': kb.find_entities_by_name(query, category='municipal')
        }
        
        if format == 'json':
            print(json.dumps(results, indent=2))
        else:
            print(f"\n🏛️  Knowledge Base Search: '{query}'")
            print("=" * 70)
            
            for category, entities in results.items():
                if entities:
                    print(f"\n{category.title()} Entities ({len(entities)} found):")
                    for entity in entities[:10]:
                        name = entity.get('name', 'Unknown')
                        url = entity.get('url', 'N/A')
                        print(f"  • {name}")
                        if url != 'N/A':
                            print(f"    {url}")
                    if len(entities) > 10:
                        print(f"  ... and {len(entities) - 10} more")
        
        return results
    
    def archive_search(
        self,
        query: str,
        include_archives: bool = True,
        archive_dir: Optional[str] = None,
        max_results: int = 10,
        format: str = 'pretty'
    ) -> Dict[str, Any]:
        """Search with web archive integration.
        
        Args:
            query: Natural language query
            include_archives: Include archived content
            archive_dir: Directory for archives
            max_results: Maximum number of results
            format: Output format
        
        Returns:
            Search results from current + archived content
        """
        searcher = self._init_archive_search(archive_dir)
        
        results = searcher.unified_search(
            query,
            include_archives=include_archives,
            max_results=max_results,
            archive_results=True
        )
        
        if format == 'json':
            print(json.dumps(results, indent=2))
        else:
            self._print_archive_results(results)
        
        return results
    
    def historical_search(
        self,
        query: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        archive_dir: Optional[str] = None,
        format: str = 'pretty'
    ) -> Dict[str, Any]:
        """Search historical archived content only.
        
        Args:
            query: Natural language query
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            archive_dir: Directory for archives
            format: Output format
        
        Returns:
            Historical search results
        """
        searcher = self._init_archive_search(archive_dir)
        
        results = searcher.search_archives(
            query,
            from_date=from_date,
            to_date=to_date
        )
        
        if format == 'json':
            print(json.dumps(results, indent=2))
        else:
            self._print_archive_results(results, historical_only=True)
        
        return results
    
    def _print_pretty(self, results: Dict[str, Any]):
        """Pretty print search results."""
        print(f"\n🔍 Search Results for: '{results.get('query', 'unknown')}'")
        print("=" * 70)
        
        intent = results.get('query_intent', {})
        if intent:
            print("\n📊 Query Intent:")
            if intent.get('agencies'):
                print(f"  Agencies: {', '.join(intent['agencies'])}")
            if intent.get('jurisdictions'):
                print(f"  Jurisdictions: {', '.join(intent['jurisdictions'])}")
            if intent.get('topics'):
                print(f"  Topics: {', '.join(intent['topics'])}")
        
        search_results = results.get('results', [])
        if search_results:
            print(f"\n📄 Found {len(search_results)} results:")
            for i, result in enumerate(search_results, 1):
                print(f"\n  {i}. {result.get('title', 'No title')}")
                print(f"     {result.get('url', 'No URL')}")
                desc = result.get('description', '')
                if desc:
                    # Truncate long descriptions
                    if len(desc) > 150:
                        desc = desc[:150] + "..."
                    print(f"     {desc}")
                relevance = result.get('relevance_score', 0)
                if relevance > 0:
                    print(f"     Relevance: {relevance:.2f}")
        else:
            print("\n  No results found.")
    
    def _print_compact(self, results: Dict[str, Any]):
        """Compact print of search results."""
        search_results = results.get('results', [])
        for result in search_results:
            print(f"{result.get('title', 'No title')}")
            print(f"  {result.get('url', 'No URL')}")
    
    def _print_intent(self, result: Dict[str, Any]):
        """Print query intent and search terms."""
        print(f"\n🎯 Query: '{result['query']}'")
        print("=" * 70)
        
        intent = result['intent']
        print("\n📊 Extracted Intent:")
        for key, value in intent.items():
            if value:
                print(f"  {key.title()}: {', '.join(value) if isinstance(value, list) else value}")
        
        terms = result['search_terms']
        print(f"\n🔍 Generated {len(terms)} Search Terms:")
        for i, term in enumerate(terms, 1):
            print(f"  {i}. {term['term']} (priority: {term['priority']:.2f})")
    
    def _print_archive_results(self, results: Dict[str, Any], historical_only: bool = False):
        """Print archive search results."""
        title = "Historical Search Results" if historical_only else "Unified Search Results"
        print(f"\n📚 {title} for: '{results.get('query', 'unknown')}'")
        print("=" * 70)
        
        search_results = results.get('results', [])
        current_results = [r for r in search_results if r.get('source_type') == 'current']
        archived_results = [r for r in search_results if r.get('source_type') == 'archived']
        
        if not historical_only and current_results:
            print(f"\n🌐 Current Results ({len(current_results)}):")
            for i, result in enumerate(current_results, 1):
                print(f"  {i}. {result.get('title', 'No title')}")
                print(f"     {result.get('url', 'No URL')}")
        
        if archived_results:
            print(f"\n📁 Archived Results ({len(archived_results)}):")
            for i, result in enumerate(archived_results, 1):
                print(f"  {i}. {result.get('title', 'No title')}")
                print(f"     {result.get('url', 'No URL')}")
                if result.get('archive_date'):
                    print(f"     Archived: {result['archive_date']}")
        
        # Archive stats
        stats = results.get('archive_stats', {})
        if stats:
            print(f"\n📊 Archive Statistics:")
            print(f"  Archived files: {stats.get('archived_count', 0)}")
            print(f"  Total size: {stats.get('total_size_mb', 0):.2f} MB")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Legal Search CLI - Natural language legal search',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Execute legal search')
    search_parser.add_argument('query', help='Natural language query')
    search_parser.add_argument('--max-results', type=int, default=10, help='Maximum results')
    search_parser.add_argument('--format', choices=['pretty', 'json', 'compact'], default='pretty')
    
    # Terms command
    terms_parser = subparsers.add_parser('terms', help='Generate search terms only')
    terms_parser.add_argument('query', help='Natural language query')
    terms_parser.add_argument('--format', choices=['pretty', 'json', 'list'], default='pretty')
    
    # Explain command
    explain_parser = subparsers.add_parser('explain', help='Explain query processing')
    explain_parser.add_argument('query', help='Natural language query')
    
    # Entities command
    entities_parser = subparsers.add_parser('entities', help='Search knowledge base')
    entities_parser.add_argument('query', help='Entity name to search')
    entities_parser.add_argument('--format', choices=['pretty', 'json'], default='pretty')
    
    # Archive command
    archive_parser = subparsers.add_parser('archive', help='Search with archives')
    archive_parser.add_argument('query', help='Natural language query')
    archive_parser.add_argument('--include-archives', action='store_true', help='Include archived content')
    archive_parser.add_argument('--archive-dir', help='Archive directory')
    archive_parser.add_argument('--max-results', type=int, default=10, help='Maximum results')
    archive_parser.add_argument('--format', choices=['pretty', 'json'], default='pretty')
    
    # Historical command
    historical_parser = subparsers.add_parser('historical', help='Search historical content only')
    historical_parser.add_argument('query', help='Natural language query')
    historical_parser.add_argument('--from-date', help='Start date (YYYY-MM-DD)')
    historical_parser.add_argument('--to-date', help='End date (YYYY-MM-DD)')
    historical_parser.add_argument('--archive-dir', help='Archive directory')
    historical_parser.add_argument('--format', choices=['pretty', 'json'], default='pretty')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Initialize CLI
    cli = LegalSearchCLI()
    
    try:
        # Execute command
        if args.command == 'search':
            cli.search(args.query, args.max_results, args.format)
        elif args.command == 'terms':
            cli.generate_terms(args.query, args.format)
        elif args.command == 'explain':
            cli.explain(args.query)
        elif args.command == 'entities':
            cli.search_entities(args.query, args.format)
        elif args.command == 'archive':
            cli.archive_search(
                args.query,
                args.include_archives,
                args.archive_dir,
                args.max_results,
                args.format
            )
        elif args.command == 'historical':
            cli.historical_search(
                args.query,
                args.from_date,
                args.to_date,
                args.archive_dir,
                args.format
            )
        
        return 0
    
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
