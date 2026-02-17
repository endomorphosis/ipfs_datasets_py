"""
Legal Data Scraping - Access Federal, State, and Municipal Laws

This example demonstrates how to scrape and process legal datasets using the
comprehensive legal scraper module with its 21,000+ entity knowledge base.

Requirements:
    - beautifulsoup4: pip install beautifulsoup4
    - lxml: pip install lxml
    - Optional: brave search API key

Usage:
    python examples/10_legal_data_scraping.py
"""

import asyncio
from pathlib import Path


async def demo_knowledge_base():
    """Explore the legal knowledge base."""
    print("\n" + "="*70)
    print("DEMO 1: Legal Knowledge Base")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalKnowledgeBase
        
        print("\n📚 Loading legal knowledge base...")
        kb = LegalKnowledgeBase()
        
        # Get statistics
        stats = kb.get_statistics()
        print(f"\n✅ Knowledge Base Statistics:")
        print(f"   Federal entities: {stats.get('federal_entities', 0):,}")
        print(f"   State agencies: {stats.get('state_entities', 0):,}")
        print(f"   Municipal entities: {stats.get('municipal_entities', 0):,}")
        print(f"   Total: {stats.get('total_entities', 0):,}")
        
        # Search for entities
        print("\n🔍 Search Examples:")
        
        # Search for EPA
        epa_results = kb.search("EPA")
        print(f"\n   'EPA' search results: {len(epa_results)} found")
        for result in epa_results[:3]:
            print(f"      - {result.get('name', 'N/A')} ({result.get('jurisdiction', 'N/A')})")
        
        # Search for California agencies
        ca_results = kb.search_by_state("California")
        print(f"\n   California agencies: {len(ca_results)} found")
        for result in ca_results[:3]:
            print(f"      - {result.get('name', 'N/A')}")
        
        return kb
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_query_processing():
    """Process natural language legal queries."""
    print("\n" + "="*70)
    print("DEMO 2: Natural Language Query Processing")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import QueryProcessor
        
        processor = QueryProcessor()
        
        # Example queries
        queries = [
            "environmental protection regulations in California",
            "OSHA workplace safety violations",
            "SEC securities fraud cases",
            "municipal zoning laws in New York City",
        ]
        
        print("\n🔍 Processing natural language queries...")
        
        for query in queries:
            print(f"\n   Query: '{query}'")
            
            # Process query
            processed = await processor.process(query)
            
            print(f"      Intent: {processed.get('intent', 'unknown')}")
            print(f"      Entities: {', '.join(processed.get('entities', []))}")
            print(f"      Jurisdiction: {processed.get('jurisdiction', 'federal')}")
            print(f"      Complaint types: {', '.join(processed.get('complaint_types', []))}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_search_term_generation():
    """Generate optimized search terms for legal queries."""
    print("\n" + "="*70)
    print("DEMO 3: Search Term Generation")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.legal_scrapers import SearchTermGenerator
        
        generator = SearchTermGenerator()
        
        # Example query
        query = "environmental violations by chemical companies in Texas"
        
        print(f"\n📝 Original query: '{query}'")
        print("\n🔧 Generated search terms:")
        
        # Generate terms
        terms = await generator.generate(query)
        
        print(f"\n   Primary terms:")
        for term in terms.get('primary', [])[:5]:
            print(f"      - {term}")
        
        if terms.get('expanded'):
            print(f"\n   Expanded terms:")
            for term in terms.get('expanded', [])[:5]:
                print(f"      - {term}")
        
        if terms.get('boolean_query'):
            print(f"\n   Boolean query:")
            print(f"      {terms.get('boolean_query')}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_brave_search():
    """Search legal content using Brave Search API."""
    print("\n" + "="*70)
    print("DEMO 4: Brave Legal Search")
    print("="*70)
    
    print("\n🔍 Brave Search API Example")
    print("   (Requires BRAVE_API_KEY environment variable)")
    
    example_code = '''
import os
from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch

# Set API key
os.environ['BRAVE_API_KEY'] = 'your_api_key_here'

# Initialize search
search = BraveLegalSearch()

# Search for legal content
results = await search.search(
    query="EPA environmental regulations California",
    jurisdiction="state",
    state="California",
    max_results=10
)

# Process results
for result in results:
    print(f"Title: {result['title']}")
    print(f"URL: {result['url']}")
    print(f"Snippet: {result['snippet']}")
    print(f"Relevance: {result['relevance_score']:.2f}")
    print()
    '''
    
    print(example_code)
    
    print("\n💡 Features:")
    print("   - Natural language queries")
    print("   - Jurisdiction filtering (federal/state/municipal)")
    print("   - State-specific search")
    print("   - Result caching")
    print("   - Relevance scoring")


async def demo_federal_scraping():
    """Scrape federal legal sources."""
    print("\n" + "="*70)
    print("DEMO 5: Federal Legal Sources")
    print("="*70)
    
    print("\n🏛️  Federal Legal Sources")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import FederalRegisterScraper

scraper = FederalRegisterScraper()

# Search Federal Register
documents = await scraper.search(
    query="environmental protection",
    agencies=["EPA"],
    document_types=["Rule", "Proposed Rule"],
    start_date="2023-01-01",
    end_date="2023-12-31"
)

# Process results
for doc in documents:
    print(f"Title: {doc['title']}")
    print(f"Agency: {doc['agency']}")
    print(f"Type: {doc['document_type']}")
    print(f"Publication date: {doc['publication_date']}")
    print(f"FR Citation: {doc['citation']}")
    print()
    '''
    
    print(example_code)
    
    print("\n📚 Supported Federal Sources:")
    print("   - Federal Register (regulations, notices)")
    print("   - US Code (statutory law)")
    print("   - RECAP Archive (court documents)")
    print("   - Congressional Record")


async def demo_state_scraping():
    """Scrape state-level legal sources."""
    print("\n" + "="*70)
    print("DEMO 6: State Legal Sources")
    print("="*70)
    
    print("\n🗺️  State Legal Sources")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import StateLawScraper

scraper = StateLawScraper()

# Search California laws
laws = await scraper.search(
    state="California",
    query="consumer protection",
    code_sections=["Business and Professions Code"],
    year=2023
)

# Process results
for law in laws:
    print(f"Code: {law['code']}")
    print(f"Section: {law['section']}")
    print(f"Title: {law['title']}")
    print(f"Text: {law['text'][:200]}...")
    print()
    '''
    
    print(example_code)
    
    print("\n🏛️  State Coverage:")
    print("   - All 50 states")
    print("   - State codes and statutes")
    print("   - Administrative regulations")
    print("   - State agencies (13,000+ tracked)")


async def demo_data_export():
    """Export scraped data to various formats."""
    print("\n" + "="*70)
    print("DEMO 7: Data Export")
    print("="*70)
    
    print("\n💾 Export Options")
    
    example_code = '''
from ipfs_datasets_py.processors.legal_scrapers import (
    export_to_json,
    export_to_parquet,
    export_to_csv,
    store_dataset_to_ipfs
)

# Assume we have scraped_data from previous operations

# Export to JSON
export_to_json(scraped_data, "legal_data.json")

# Export to Parquet (efficient for large datasets)
export_to_parquet(scraped_data, "legal_data.parquet")

# Export to CSV
export_to_csv(scraped_data, "legal_data.csv")

# Store on IPFS
cid = await store_dataset_to_ipfs(scraped_data)
print(f"Dataset stored on IPFS: {cid}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for legal data scraping."""
    print("\n" + "="*70)
    print("TIPS FOR LEGAL DATA SCRAPING")
    print("="*70)
    
    print("\n1. Query Optimization:")
    print("   - Use specific entity names (EPA, OSHA, SEC)")
    print("   - Include jurisdiction (federal, state, municipal)")
    print("   - Add date ranges to narrow results")
    print("   - Use boolean operators for precision")
    
    print("\n2. Knowledge Base:")
    print("   - 21,000+ entities tracked")
    print("   - Search by name, acronym, or jurisdiction")
    print("   - Use for entity recognition in documents")
    print("   - Validate extracted entities")
    
    print("\n3. Rate Limiting:")
    print("   - Respect source rate limits")
    print("   - Use caching to avoid redundant requests")
    print("   - Implement exponential backoff")
    print("   - Consider bulk downloads during off-peak")
    
    print("\n4. Data Quality:")
    print("   - Validate extracted citations")
    print("   - Check for parsing errors")
    print("   - Cross-reference multiple sources")
    print("   - Keep metadata for provenance")
    
    print("\n5. Storage:")
    print("   - Use Parquet for large datasets")
    print("   - Store on IPFS for decentralization")
    print("   - Include metadata and timestamps")
    print("   - Version control datasets")
    
    print("\n6. Compliance:")
    print("   - Review site terms of service")
    print("   - Don't overload servers")
    print("   - Respect robots.txt")
    print("   - Proper attribution")
    
    print("\n7. Advanced Features:")
    print("   - Common Crawl index integration")
    print("   - Parallel web archiving")
    print("   - HuggingFace dataset hosting")
    print("   - LLM-based query expansion")
    
    print("\n8. Next Steps:")
    print("   - See 11_web_archiving.py for web scraping")
    print("   - See 17_legal_knowledge_base.py (coming) for full system")


async def main():
    """Run all legal scraping demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - LEGAL DATA SCRAPING")
    print("="*70)
    
    await demo_knowledge_base()
    await demo_query_processing()
    await demo_search_term_generation()
    await demo_brave_search()
    await demo_federal_scraping()
    await demo_state_scraping()
    await demo_data_export()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ LEGAL DATA SCRAPING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
