#!/usr/bin/env python3
"""
Test script for web scraping and archival features.

This script tests all the new web archiving and scraping integrations.
"""
import anyio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import search_common_crawl
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import search_wayback_machine
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.ipwb_integration import search_ipwb_archive
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.autoscraper_integration import list_autoscraper_models
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_is_integration import archive_to_archive_is

async def test_common_crawl():
    """Test Common Crawl integration."""
    print("Testing Common Crawl integration...")
    
    try:
        result = await search_common_crawl("example.com", limit=5)
        print(f"Common Crawl search result: {result['status']}")
        
        if result['status'] == 'success':
            print(f"Found {result['count']} records")
        elif result['status'] == 'error':
            print(f"Error: {result['error']}")
            
    except Exception as e:
        print(f"Common Crawl test failed: {e}")
    
    print()

async def test_wayback_machine():
    """Test Wayback Machine integration."""
    print("Testing Wayback Machine integration...")
    
    try:
        result = await search_wayback_machine("example.com", limit=5)
        print(f"Wayback Machine search result: {result['status']}")
        
        if result['status'] == 'success':
            print(f"Found {result['count']} captures")
        elif result['status'] == 'error':
            print(f"Error: {result['error']}")
            
    except Exception as e:
        print(f"Wayback Machine test failed: {e}")
    
    print()

async def test_ipwb():
    """Test IPWB integration."""
    print("Testing IPWB integration...")
    
    try:
        # Create a dummy CDXJ file for testing
        import tempfile
        import json
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cdxj', delete=False) as f:
            cdxj_path = f.name
            sample_record = {
                "url": "http://example.com/",
                "timestamp": "20240101000000",
                "mime": "text/html",
                "status": "200",
                "ipfs_hash": "QmTestHash123"
            }
            f.write(json.dumps(sample_record) + '\n')
        
        result = await search_ipwb_archive(cdxj_path, "example.com", limit=5)
        print(f"IPWB search result: {result['status']}")
        
        if result['status'] == 'success':
            print(f"Found {result['count']} records")
        elif result['status'] == 'error':
            print(f"Error: {result['error']}")
        
        # Clean up
        os.unlink(cdxj_path)
            
    except Exception as e:
        print(f"IPWB test failed: {e}")
    
    print()

async def test_autoscraper():
    """Test AutoScraper integration."""
    print("Testing AutoScraper integration...")
    
    try:
        result = await list_autoscraper_models()
        print(f"AutoScraper models listing result: {result['status']}")
        
        if result['status'] == 'success':
            print(f"Found {result['count']} models")
        elif result['status'] == 'error':
            print(f"Error: {result['error']}")
            
    except Exception as e:
        print(f"AutoScraper test failed: {e}")
    
    print()

async def test_archive_is():
    """Test Archive.is integration."""
    print("Testing Archive.is integration...")
    
    try:
        # Test with a safe URL
        result = await archive_to_archive_is("http://example.com", wait_for_completion=False)
        print(f"Archive.is archiving result: {result['status']}")
        
        if result['status'] == 'success':
            print(f"Archive URL: {result.get('archive_url', 'N/A')}")
        elif result['status'] == 'error':
            print(f"Error: {result['error']}")
        elif result['status'] == 'pending':
            print(f"Submission ID: {result.get('submission_id', 'N/A')}")
            
    except Exception as e:
        print(f"Archive.is test failed: {e}")
    
    print()

async def main():
    """Run all tests."""
    print("=" * 60)
    print("Web Scraping and Archival Tools Test Suite")
    print("=" * 60)
    print()
    
    # Run tests
    await test_common_crawl()
    await test_wayback_machine() 
    await test_ipwb()
    await test_autoscraper()
    await test_archive_is()
    
    print("=" * 60)
    print("Test suite completed!")
    print("=" * 60)

if __name__ == "__main__":
    anyio.run(main())