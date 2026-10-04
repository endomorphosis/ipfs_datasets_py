#!/usr/bin/env python
"""
Brave Legal Search Examples

This script demonstrates various use cases of the Brave Legal Search system
for finding legal rules and regulations using natural language queries.

Usage:
    python brave_legal_search_examples.py
    
Requirements:
    - BRAVE_API_KEY environment variable set
    - ipfs_datasets_py installed

Examples included:
1. Basic search
2. Federal regulations
3. State laws
4. Municipal ordinances
5. Search term generation
6. Query explanation
7. Entity knowledge base search
"""

import os
import json
from pathlib import Path


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_results(results: dict, limit: int = 5):
    """Print search results in a readable format."""
    if results.get('status') == 'error':
        print(f"❌ Error: {results.get('error')}")
        return
    
    print(f"Query: {results.get('query')}")
    print(f"\nIntent:")
    intent = results.get('intent', {})
    if intent.get('agencies'):
        print(f"  Agencies: {', '.join(intent['agencies'])}")
    if intent.get('jurisdictions'):
        print(f"  Jurisdictions: {', '.join(intent['jurisdictions'])}")
    if intent.get('topics'):
        print(f"  Topics: {', '.join(intent['topics'])}")
    if intent.get('legal_domains'):
        print(f"  Legal Domains: {', '.join(intent['legal_domains'])}")
    print(f"  Scope: {intent.get('scope')}")
    print(f"  Confidence: {intent.get('confidence', 0):.2f}")
    
    print(f"\nSearch Terms Generated: {', '.join(results.get('search_terms', []))}")
    
    search_results = results.get('results', [])
    print(f"\nResults ({len(search_results)} total, showing top {limit}):")
    for i, result in enumerate(search_results[:limit], 1):
        print(f"\n{i}. {result['title']}")
        print(f"   URL: {result['url']}")
        print(f"   Relevance: {result['relevance_score']:.2f}")
        if result.get('description'):
            desc = result['description'][:150]
            print(f"   {desc}..." if len(result['description']) > 150 else f"   {desc}")


def example_1_basic_search():
    """Example 1: Basic search for EPA regulations."""
    print_section("Example 1: Basic Search - EPA Water Regulations")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        results = searcher.search("EPA regulations on water pollution")
        print_results(results)
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_2_federal_regulations():
    """Example 2: Federal regulations with specific agency."""
    print_section("Example 2: Federal Regulations - OSHA Workplace Safety")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        results = searcher.search("OSHA workplace safety requirements")
        print_results(results)
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_3_state_laws():
    """Example 3: State-level laws."""
    print_section("Example 3: State Laws - California Housing")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        results = searcher.search("California fair housing discrimination laws")
        print_results(results)
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_4_municipal_ordinances():
    """Example 4: Municipal ordinances."""
    print_section("Example 4: Municipal Ordinances - San Francisco Building Codes")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        results = searcher.search("San Francisco building code requirements")
        print_results(results)
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_5_generate_terms():
    """Example 5: Generate search terms without executing search."""
    print_section("Example 5: Generate Search Terms Only")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        
        queries = [
            "EPA environmental regulations",
            "California employment discrimination",
            "New York City zoning ordinances"
        ]
        
        for query in queries:
            terms = searcher.generate_search_terms(query)
            print(f"\nQuery: {query}")
            print(f"Generated Terms:")
            for i, term in enumerate(terms, 1):
                print(f"  {i}. {term}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_6_explain_query():
    """Example 6: Explain how a query is processed."""
    print_section("Example 6: Explain Query Processing")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        
        query = "EPA water pollution regulations in California"
        explanation = searcher.explain_query(query)
        
        print(f"Query: {query}\n")
        print("Intent Details:")
        for key, value in explanation['intent_details'].items():
            if value:
                print(f"  {key}: {value}")
        
        print("\nSearch Strategy:")
        strategy = explanation['search_strategy']
        print(f"  Total terms generated: {strategy['total_terms']}")
        print(f"  Recommended limit: {strategy['recommended_limit']}")
        print(f"  Terms by category:")
        for category, count in strategy['terms_by_category'].items():
            print(f"    {category}: {count}")
        
        print(f"\nTop {len(explanation['top_search_terms'])} Search Terms:")
        for i, term in enumerate(explanation['top_search_terms'], 1):
            print(f"  {i}. {term}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_7_search_entities():
    """Example 7: Search the entity knowledge base."""
    print_section("Example 7: Search Entity Knowledge Base")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        
        # Search for environmental agencies
        print("Searching for 'environmental' entities:")
        results = searcher.search_entities("environmental")
        
        for entity_type, entities in results.items():
            if entities:
                print(f"\n{entity_type.upper()} ({len(entities)} found):")
                for i, entity in enumerate(entities[:5], 1):
                    if hasattr(entity, 'name'):
                        print(f"  {i}. {entity.name}")
                    elif hasattr(entity, 'agency_name'):
                        print(f"  {i}. {entity.agency_name} ({entity.state_name})")
                    else:
                        print(f"  {i}. {entity.place_name}")
        
        # Get knowledge base statistics
        print("\n\nKnowledge Base Statistics:")
        stats = searcher.get_knowledge_base_stats()
        print(f"  Total entities: {stats['total_entities']}")
        print(f"  Federal: {stats['federal']['total']}")
        print(f"  State: {stats['state']['total']}")
        print(f"  Municipal: {stats['municipal']['total']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def example_8_mixed_jurisdiction():
    """Example 8: Mixed jurisdiction search."""
    print_section("Example 8: Mixed Jurisdiction - Federal and State")
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
        
        searcher = BraveLegalSearch()
        results = searcher.search("ADA compliance requirements in California")
        print_results(results)
        
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    """Run all examples."""
    print("\n" + "=" * 80)
    print("  BRAVE LEGAL SEARCH - EXAMPLES")
    print("  Natural Language Search for Legal Rules and Regulations")
    print("=" * 80)
    
    # Check for API key
    api_key = os.environ.get('BRAVE_API_KEY') or os.environ.get('BRAVE_SEARCH_API_KEY')
    if not api_key:
        print("\n⚠️  WARNING: BRAVE_API_KEY not set in environment.")
        print("   Set it to run search examples:")
        print("   export BRAVE_API_KEY='your_api_key_here'\n")
        print("   Some examples will still work (knowledge base, term generation).\n")
    
    # Run examples
    try:
        # These work without API key
        example_5_generate_terms()
        example_6_explain_query()
        example_7_search_entities()
        
        # These require API key
        if api_key:
            example_1_basic_search()
            example_2_federal_regulations()
            example_3_state_laws()
            example_4_municipal_ordinances()
            example_8_mixed_jurisdiction()
        else:
            print_section("Skipping Search Examples (No API Key)")
            print("Set BRAVE_API_KEY to run actual search examples.")
        
        print("\n" + "=" * 80)
        print("  Examples Complete!")
        print("=" * 80 + "\n")
        
    except KeyboardInterrupt:
        print("\n\nExamples interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")


if __name__ == "__main__":
    main()
