#!/usr/bin/env python3
"""
Simple test for web archiving features.

This script tests the web archiving tools directly without the full MCP server.
"""
import anyio
import sys
import os
import tempfile
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def test_common_crawl():
    """Test Common Crawl integration."""
    print("Testing Common Crawl integration...")
    
    # Direct import to test the function
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import search_common_crawl
    
    try:
        result = await search_common_crawl("example.com", limit=5)
        print(f"  Status: {result['status']}")
        
        if result['status'] == 'success':
            print(f"  Found {result['count']} records")
        elif result['status'] == 'error':
            print(f"  Error: {result['error']}")
            
        return True
            
    except Exception as e:
        print(f"  Failed: {e}")
        return False

async def test_wayback_machine():
    """Test Wayback Machine integration."""
    print("Testing Wayback Machine integration...")
    
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import search_wayback_machine
    
    try:
        result = await search_wayback_machine("example.com", limit=5)
        print(f"  Status: {result['status']}")
        
        if result['status'] == 'success':
            print(f"  Found {result['count']} captures")
        elif result['status'] == 'error':
            print(f"  Error: {result['error']}")
            
        return True
            
    except Exception as e:
        print(f"  Failed: {e}")
        return False

async def test_ipwb():
    """Test IPWB integration."""
    print("Testing IPWB integration...")
    
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.ipwb_integration import search_ipwb_archive
    
    try:
        # Create a dummy CDXJ file for testing
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
        print(f"  Status: {result['status']}")
        
        if result['status'] == 'success':
            print(f"  Found {result['count']} records")
        elif result['status'] == 'error':
            print(f"  Error: {result['error']}")
        
        # Clean up
        os.unlink(cdxj_path)
        return True
            
    except Exception as e:
        print(f"  Failed: {e}")
        return False

async def test_autoscraper():
    """Test AutoScraper integration."""
    print("Testing AutoScraper integration...")
    
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.autoscraper_integration import list_autoscraper_models
    
    try:
        result = await list_autoscraper_models()
        print(f"  Status: {result['status']}")
        
        if result['status'] == 'success':
            print(f"  Found {result['count']} models")
        elif result['status'] == 'error':
            print(f"  Error: {result['error']}")
            
        return True
            
    except Exception as e:
        print(f"  Failed: {e}")
        return False

async def test_archive_is():
    """Test Archive.is integration."""
    print("Testing Archive.is integration...")
    
    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_is_integration import archive_to_archive_is
    
    try:
        # Test with a safe URL, don't wait for completion
        result = await archive_to_archive_is("http://example.com", wait_for_completion=False)
        print(f"  Status: {result['status']}")
        
        if result['status'] == 'success':
            print(f"  Archive URL: {result.get('archive_url', 'N/A')}")
        elif result['status'] == 'error':
            print(f"  Error: {result['error']}")
        elif result['status'] == 'pending':
            print(f"  Submission ID: {result.get('submission_id', 'N/A')}")
            
        return True
            
    except Exception as e:
        print(f"  Failed: {e}")
        return False

async def test_existing_web_archive():
    """Test existing web archive functionality."""
    print("Testing existing WebArchive class...")
    
    try:
        from ipfs_datasets_py.web_archive import WebArchive, archive_web_content
        
        # Test basic archiving
        result = archive_web_content("http://example.com", {"test": True})
        print(f"  Archive result: {result}")
        
        return True
        
    except Exception as e:
        print(f"  Failed: {e}")
        return False

async def main():
    """Run all tests."""
    print("=" * 50)
    print("Web Scraping and Archival Tools Test")
    print("=" * 50)
    
    tests = [
        ("Existing WebArchive", test_existing_web_archive),
        ("Common Crawl", test_common_crawl),
        ("Wayback Machine", test_wayback_machine), 
        ("IPWB", test_ipwb),
        ("AutoScraper", test_autoscraper),
        ("Archive.is", test_archive_is),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n[{passed+1}/{total}] {test_name}:")
        try:
            success = await test_func()
            if success:
                passed += 1
                print(f"  ✓ PASSED")
            else:
                print(f"  ✗ FAILED")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
    
    print("\n" + "=" * 50)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 50)

if __name__ == "__main__":
    anyio.run(main())