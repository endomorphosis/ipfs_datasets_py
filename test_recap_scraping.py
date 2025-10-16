#!/usr/bin/env python3
"""
Test script for RECAP Archive scraping functionality.

This script tests the RECAP Archive scraper to ensure it can:
1. Search for documents
2. Retrieve document details
3. Scrape multiple documents with proper state management

Usage:
    python test_recap_scraping.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Import directly from the scraper module to avoid circular import issues
from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.recap_archive_scraper import (
    search_recap_documents,
    scrape_recap_archive,
    get_recap_document
)


async def test_search():
    """Test searching RECAP Archive."""
    print("\n=== Test 1: Search RECAP Archive ===")
    
    result = await search_recap_documents(
        court='ca9',  # 9th Circuit
        document_type='opinion',
        limit=5
    )
    
    print(f"Status: {result['status']}")
    print(f"Documents found: {result['count']}")
    
    if result['status'] == 'success' and result['documents']:
        print("\nFirst document:")
        doc = result['documents'][0]
        print(f"  Case: {doc.get('case_name', 'N/A')}")
        print(f"  Court: {doc.get('court', 'N/A')}")
        print(f"  Filed: {doc.get('date_filed', 'N/A')}")
        print(f"  ID: {doc.get('id', 'N/A')}")
    
    return result['status'] == 'success'


async def test_get_document():
    """Test retrieving a specific document."""
    print("\n=== Test 2: Get Specific Document ===")
    
    # First search to get a document ID
    search_result = await search_recap_documents(
        court='ca9',
        document_type='opinion',
        limit=1
    )
    
    if search_result['status'] != 'success' or not search_result['documents']:
        print("Could not find document for testing")
        return False
    
    doc_id = search_result['documents'][0].get('id')
    if not doc_id:
        print("Document has no ID")
        return False
    
    print(f"Fetching document ID: {doc_id}")
    
    result = await get_recap_document(
        document_id=str(doc_id),
        include_text=False,  # Skip text to save bandwidth
        include_metadata=True
    )
    
    print(f"Status: {result['status']}")
    
    if result['status'] == 'success' and result.get('document'):
        doc = result['document']
        print(f"  Case: {doc.get('case_name', 'N/A')}")
        print(f"  Court: {doc.get('court', 'N/A')}")
        print(f"  Pages: {doc.get('page_count', 'N/A')}")
    
    return result['status'] == 'success'


async def test_scrape_small():
    """Test scraping a small dataset."""
    print("\n=== Test 3: Scrape Small Dataset ===")
    
    result = await scrape_recap_archive(
        courts=['ca9'],
        document_types=['opinion'],
        filed_after='2024-01-01',
        filed_before='2024-01-31',
        include_text=False,  # Skip text to save bandwidth
        include_metadata=True,
        rate_limit_delay=1.0,
        max_documents=3,  # Small test
        job_id='test_scrape_small'
    )
    
    print(f"Status: {result['status']}")
    
    if result['status'] == 'success':
        metadata = result.get('metadata', {})
        print(f"  Documents: {metadata.get('documents_count', 0)}")
        print(f"  Courts: {metadata.get('courts_count', 0)}")
        print(f"  Elapsed time: {metadata.get('elapsed_time_seconds', 0):.2f}s")
        print(f"  Job ID: {result.get('job_id', 'N/A')}")
        print(f"  Source: {metadata.get('source', 'N/A')}")
    else:
        print(f"  Error: {result.get('error', 'Unknown error')}")
    
    return result['status'] == 'success'


async def test_resume():
    """Test resume capability."""
    print("\n=== Test 4: Resume Capability ===")
    
    # Use the same job_id to test resume
    result = await scrape_recap_archive(
        courts=['ca9'],
        document_types=['opinion'],
        filed_after='2024-01-01',
        filed_before='2024-01-31',
        include_text=False,
        include_metadata=True,
        rate_limit_delay=1.0,
        max_documents=3,
        job_id='test_scrape_small',
        resume=True  # Try to resume
    )
    
    print(f"Status: {result['status']}")
    
    if result['status'] == 'success':
        metadata = result.get('metadata', {})
        print(f"  Resumed: {metadata.get('resumed', False)}")
        print(f"  Documents: {metadata.get('documents_count', 0)}")
        print(f"  Job ID: {result.get('job_id', 'N/A')}")
    
    return result['status'] == 'success'


async def main():
    """Run all tests."""
    print("=" * 60)
    print("RECAP Archive Scraper Test Suite")
    print("=" * 60)
    
    tests = [
        ("Search Documents", test_search),
        ("Get Document", test_get_document),
        ("Scrape Small Dataset", test_scrape_small),
        ("Resume Capability", test_resume),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"ERROR in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(1 for _, success in results if success)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return 0 if passed == total else 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
