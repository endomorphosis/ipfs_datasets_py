#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demonstration of Patent Scraper for Legal Dataset Integration.

This script demonstrates how to:
1. Search USPTO patents using various criteria
2. Build patent datasets for GraphRAG ingestion
3. Access the patent dashboard web interface

Usage:
    python demo_patent_scraper.py
"""
import asyncio
from pathlib import Path

from ipfs_datasets_py.mcp_tools.tools.patent_scraper import (
    USPTOPatentScraper,
    PatentSearchCriteria,
    PatentDatasetBuilder,
    search_patents_by_keyword,
    search_patents_by_inventor,
    search_patents_by_assignee
)


def demo_basic_keyword_search():
    """Demonstrate basic keyword search."""
    print("\n" + "="*80)
    print("DEMO 1: Basic Keyword Search")
    print("="*80)
    
    print("\nSearching for patents containing 'artificial intelligence'...")
    
    try:
        patents = search_patents_by_keyword(
            keywords=["artificial intelligence"],
            limit=5,
            rate_limit_delay=1.0
        )
        
        print(f"\nFound {len(patents)} patents:")
        for i, patent in enumerate(patents, 1):
            print(f"\n{i}. Patent #{patent.patent_number}")
            print(f"   Title: {patent.patent_title}")
            print(f"   Date: {patent.patent_date}")
            if patent.inventors:
                inventors = ", ".join([f"{inv['first_name']} {inv['last_name']}" 
                                     for inv in patent.inventors])
                print(f"   Inventors: {inventors}")
            if patent.assignees:
                assignees = ", ".join([a['organization'] for a in patent.assignees])
                print(f"   Assignees: {assignees}")
    
    except Exception as e:
        print(f"\nError during search: {e}")
        print("Note: This demo requires internet connection to access USPTO API")


def demo_inventor_search():
    """Demonstrate inventor search."""
    print("\n" + "="*80)
    print("DEMO 2: Search by Inventor")
    print("="*80)
    
    print("\nSearching for patents by inventor 'Smith'...")
    
    try:
        patents = search_patents_by_inventor(
            inventor_name="Smith",
            limit=3,
            rate_limit_delay=1.0
        )
        
        print(f"\nFound {len(patents)} patents by inventors named Smith:")
        for i, patent in enumerate(patents, 1):
            print(f"\n{i}. {patent.patent_number}: {patent.patent_title}")
            if patent.inventors:
                inventors = ", ".join([f"{inv['first_name']} {inv['last_name']}" 
                                     for inv in patent.inventors])
                print(f"   Inventors: {inventors}")
    
    except Exception as e:
        print(f"\nError during search: {e}")


def demo_advanced_search():
    """Demonstrate advanced search with multiple criteria."""
    print("\n" + "="*80)
    print("DEMO 3: Advanced Search with Multiple Criteria")
    print("="*80)
    
    print("\nSearching for patents with:")
    print("  - Keywords: machine learning, neural network")
    print("  - Date range: 2020-2024")
    print("  - CPC Classification: G06F (Computing)")
    
    try:
        scraper = USPTOPatentScraper(rate_limit_delay=1.0)
        criteria = PatentSearchCriteria(
            keywords=["machine learning", "neural network"],
            date_from="2020-01-01",
            date_to="2024-12-31",
            cpc_classification=["G06F"],
            limit=5
        )
        
        patents = scraper.search_patents(criteria)
        
        print(f"\nFound {len(patents)} patents:")
        for i, patent in enumerate(patents, 1):
            print(f"\n{i}. {patent.patent_number}")
            print(f"   Title: {patent.patent_title}")
            print(f"   Date: {patent.patent_date}")
            if patent.cpc_classifications:
                cpc = ", ".join(patent.cpc_classifications[:3])
                print(f"   Classifications: {cpc}")
    
    except Exception as e:
        print(f"\nError during search: {e}")


def demo_dataset_building():
    """Demonstrate building a patent dataset for GraphRAG."""
    print("\n" + "="*80)
    print("DEMO 4: Build Patent Dataset for GraphRAG")
    print("="*80)
    
    print("\nBuilding a patent dataset...")
    
    try:
        scraper = USPTOPatentScraper(rate_limit_delay=1.0)
        builder = PatentDatasetBuilder(scraper)
        
        criteria = PatentSearchCriteria(
            keywords=["blockchain"],
            limit=10
        )
        
        output_path = Path("/tmp/patent_dataset_demo.json")
        
        result = builder.build_dataset(
            criteria=criteria,
            output_format="json",
            output_path=output_path
        )
        
        print(f"\nDataset built successfully!")
        print(f"Status: {result['status']}")
        print(f"Patent count: {result['metadata']['patent_count']}")
        print(f"Output file: {result['metadata']['output_path']}")
        print(f"\nDataset metadata:")
        for key, value in result['metadata'].items():
            if key not in ['criteria']:
                print(f"  {key}: {value}")
        
        print("\nGraphRAG Integration Info:")
        print("  Entity Types: Patent, Inventor, Assignee, Classification")
        print("  Relationship Types: INVENTED_BY, ASSIGNED_TO, CLASSIFIED_AS, CITES")
    
    except Exception as e:
        print(f"\nError building dataset: {e}")


async def demo_async_search():
    """Demonstrate async search."""
    print("\n" + "="*80)
    print("DEMO 5: Async Patent Search")
    print("="*80)
    
    print("\nPerforming async search for 'quantum computing'...")
    
    try:
        scraper = USPTOPatentScraper(rate_limit_delay=1.0)
        criteria = PatentSearchCriteria(
            keywords=["quantum computing"],
            limit=3
        )
        
        patents = await scraper.search_patents_async(criteria)
        
        print(f"\nAsync search completed! Found {len(patents)} patents:")
        for i, patent in enumerate(patents, 1):
            print(f"\n{i}. {patent.patent_number}: {patent.patent_title[:60]}...")
    
    except Exception as e:
        print(f"\nError during async search: {e}")


def demo_dashboard_info():
    """Show information about the patent dashboard."""
    print("\n" + "="*80)
    print("DEMO 6: Patent Dashboard Web Interface")
    print("="*80)
    
    print("\nThe patent dashboard provides a web interface for:")
    print("  - Searching USPTO patents with advanced filters")
    print("  - Building structured datasets for GraphRAG")
    print("  - Viewing patent details and relationships")
    print("  - Managing GraphRAG integration")
    
    print("\nTo access the dashboard:")
    print("  1. Start the IPFS Datasets admin dashboard:")
    print("     python -m ipfs_datasets_py.admin_dashboard")
    print("  2. Navigate to: http://127.0.0.1:8888/mcp/patents")
    
    print("\nDashboard Features:")
    print("  - Search Tab: Interactive patent search with multiple filters")
    print("  - Build Dataset Tab: Create GraphRAG-ready patent datasets")
    print("  - Results Tab: View and analyze search results")
    print("  - GraphRAG Tab: Monitor integration status")
    
    print("\nAPI Endpoints:")
    print("  POST /api/mcp/patents/search - Search patents")
    print("  POST /api/mcp/patents/build_dataset - Build dataset")
    print("  POST /api/mcp/patents/graphrag/ingest - Ingest into GraphRAG")


def main():
    """Run all demonstrations."""
    print("\n" + "="*80)
    print("PATENT SCRAPER DEMONSTRATION")
    print("USPTO PatentsView API Integration for Legal Datasets")
    print("="*80)
    
    print("\nThis demonstration shows how to use the patent scraper to:")
    print("  1. Search patents using various criteria")
    print("  2. Build datasets for GraphRAG knowledge graphs")
    print("  3. Access the web dashboard interface")
    
    print("\nNote: These demos require internet connection to access the USPTO API")
    print("      Rate limiting is applied to be respectful to the API")
    
    # Run synchronous demos
    demo_basic_keyword_search()
    demo_inventor_search()
    demo_advanced_search()
    demo_dataset_building()
    
    # Run async demo
    try:
        asyncio.run(demo_async_search())
    except Exception as e:
        print(f"\nAsync demo skipped: {e}")
    
    # Show dashboard info
    demo_dashboard_info()
    
    print("\n" + "="*80)
    print("DEMONSTRATION COMPLETE")
    print("="*80)
    print("\nFor more information:")
    print("  - USPTO PatentsView API: https://patentsview.org/apis/purpose")
    print("  - Patent Dashboard: http://127.0.0.1:8888/mcp/patents")
    print("  - GraphRAG Integration: See /mcp/patents GraphRAG tab")
    print()


if __name__ == "__main__":
    main()
