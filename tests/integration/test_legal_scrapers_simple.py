#!/usr/bin/env python3
"""
Simplified test script for legal dataset scrapers.

This script demonstrates the functionality without requiring full dependencies.
"""
import anyio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent / '../..'))

# Import scrapers from their actual location
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import (
    us_code_scraper,
    federal_register_scraper,
    state_laws_scraper,
    municipal_laws_scraper,
    recap_archive_scraper
)


async def test_us_code_scraper():
    """Test US Code scraper."""
    print("\n" + "="*60)
    print("Testing US Code Scraper")
    print("="*60)
    
    # Get available titles
    titles_result = await us_code_scraper.get_us_code_titles()
    print(f"\n✓ Available US Code Titles: {titles_result['count']}")
    print(f"  Sample titles: {list(titles_result['titles'].items())[:3]}")
    
    # Scrape sample titles
    result = await us_code_scraper.scrape_us_code(
        titles=["1", "15", "18"],
        max_sections=5
    )
    
    if result['status'] == 'success':
        print(f"\n✓ Scraping completed successfully")
        print(f"  Titles scraped: {result['metadata']['titles_count']}")
        print(f"  Sections scraped: {result['metadata']['sections_count']}")
        print(f"  Time elapsed: {result['metadata']['elapsed_time_seconds']:.2f}s")
    else:
        print(f"\n✗ Scraping failed: {result.get('error')}")
    
    return result


async def test_federal_register_scraper():
    """Test Federal Register scraper."""
    print("\n" + "="*60)
    print("Testing Federal Register Scraper")
    print("="*60)
    
    # Search Federal Register
    search_result = await federal_register_scraper.search_federal_register(
        agencies=["EPA", "FDA"],
        limit=10
    )
    
    print(f"\n✓ Search completed: {search_result['count']} documents found")
    
    # Scrape documents
    result = await federal_register_scraper.scrape_federal_register(
        agencies=["EPA", "FDA"],
        max_documents=5
    )
    
    if result['status'] == 'success':
        print(f"\n✓ Scraping completed successfully")
        print(f"  Agencies scraped: {result['metadata']['agencies_count']}")
        print(f"  Documents scraped: {result['metadata']['documents_count']}")
        print(f"  Time elapsed: {result['metadata']['elapsed_time_seconds']:.2f}s")
    else:
        print(f"\n✗ Scraping failed: {result.get('error')}")
    
    return result


async def test_state_laws_scraper():
    """Test State Laws scraper."""
    print("\n" + "="*60)
    print("Testing State Laws Scraper")
    print("="*60)
    
    # Get available states
    states_result = await state_laws_scraper.list_state_jurisdictions()
    print(f"\n✓ Available States: {states_result['count']}")
    
    # Scrape sample states
    result = await state_laws_scraper.scrape_state_laws(
        states=["CA", "NY", "TX"],
        max_statutes=5
    )
    
    if result['status'] == 'success':
        print(f"\n✓ Scraping completed successfully")
        print(f"  States scraped: {result['metadata']['states_count']}")
        print(f"  Statutes scraped: {result['metadata']['statutes_count']}")
        print(f"  Time elapsed: {result['metadata']['elapsed_time_seconds']:.2f}s")
    else:
        print(f"\n✗ Scraping failed: {result.get('error')}")
    
    return result


async def test_municipal_laws_scraper():
    """Test Municipal Laws scraper."""
    print("\n" + "="*60)
    print("Testing Municipal Laws Scraper")
    print("="*60)
    
    # Search municipal codes
    search_result = await municipal_laws_scraper.search_municipal_codes(
        city_name="New York City"
    )
    
    print(f"\n✓ Search completed: {search_result['count']} ordinances found")
    
    # Scrape sample cities
    result = await municipal_laws_scraper.scrape_municipal_laws(
        cities=["NYC", "LAX", "CHI"],
        max_ordinances=5
    )
    
    if result['status'] == 'success':
        print(f"\n✓ Scraping completed successfully")
        print(f"  Cities scraped: {result['metadata']['cities_count']}")
        print(f"  Ordinances scraped: {result['metadata']['ordinances_count']}")
        print(f"  Time elapsed: {result['metadata']['elapsed_time_seconds']:.2f}s")
    else:
        print(f"\n✗ Scraping failed: {result.get('error')}")
    
    return result


async def test_recap_archive_scraper():
    """Test RECAP Archive scraper."""
    print("\n" + "="*60)
    print("Testing RECAP Archive Scraper")
    print("="*60)
    
    # Search RECAP documents
    search_result = await recap_archive_scraper.search_recap_documents(
        court="ca9",
        document_type="opinion",
        limit=10
    )
    
    print(f"\n✓ Search completed: {search_result['count']} documents found")
    if search_result['count'] > 0:
        print(f"  Sample document: {search_result['documents'][0]['case_name']}")
    
    # Scrape documents
    result = await recap_archive_scraper.scrape_recap_archive(
        courts=["ca9", "nysd"],
        document_types=["opinion", "complaint"],
        max_documents=10
    )
    
    if result['status'] == 'success':
        print(f"\n✓ Scraping completed successfully")
        print(f"  Courts scraped: {result['metadata']['courts_count']}")
        print(f"  Documents scraped: {result['metadata']['documents_count']}")
        print(f"  Time elapsed: {result['metadata']['elapsed_time_seconds']:.2f}s")
        
        # Get a specific document
        if result['data'] and len(result['data']) > 0:
            doc_id = result['data'][0]['id']
            doc_result = await recap_archive_scraper.get_recap_document(doc_id)
            if doc_result['status'] == 'success':
                print(f"  ✓ Retrieved document: {doc_result['document']['case_name']}")
    else:
        print(f"\n✗ Scraping failed: {result.get('error')}")
    
    return result


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Legal Dataset Scrapers Test Suite")
    print("="*60)
    
    results = {}
    
    try:
        # Test each scraper
        results['us_code'] = await test_us_code_scraper()
        results['federal_register'] = await test_federal_register_scraper()
        results['state_laws'] = await test_state_laws_scraper()
        results['municipal_laws'] = await test_municipal_laws_scraper()
        results['recap_archive'] = await test_recap_archive_scraper()
        
        # Summary
        print("\n" + "="*60)
        print("Test Summary")
        print("="*60)
        
        successful = sum(1 for r in results.values() if r.get('status') == 'success')
        total = len(results)
        
        print(f"\n✓ {successful}/{total} scrapers tested successfully")
        
        for name, result in results.items():
            status = "✓" if result.get('status') == 'success' else "✗"
            print(f"  {status} {name.replace('_', ' ').title()}")
        
        # Save results to file
        output_file = Path(__file__).parent / "test_legal_scrapers_output.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n✓ Full results saved to: {output_file}")
        print("\n" + "="*60)
        
    except Exception as e:
        print(f"\n✗ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)
