#!/usr/bin/env python3
"""Test script for search API classes with _install, _config, _queue methods."""

import sys
import os

# Add path
sys.path.insert(0, os.path.abspath('ipfs_datasets_py/mcp_server/tools/web_archive_tools'))


def test_brave_api():
    """Test Brave Search API class."""
    print("=" * 70)
    print("Testing Brave Search API Class")
    print("=" * 70)
    
    from brave_search import BraveSearchAPI
    
    # Initialize
    api = BraveSearchAPI()
    print("✓ BraveSearchAPI initialized")
    
    # Test _install()
    install_result = api._install()
    print("\n_install() result:")
    print(f"  Status: {install_result['status']}")
    print(f"  Dependencies: {install_result['dependencies']}")
    print(f"  Ready: {install_result.get('ready', 'N/A')}")
    
    # Test _config()
    config_result = api._config(timeout=60, max_count=15)
    print("\n_config() result:")
    print(f"  Status: {config_result['status']}")
    print(f"  Configuration: {config_result['configuration']}")
    
    # Test _queue()
    queue_result = api._queue("search", query="test query", count=10)
    print("\n_queue() result:")
    print(f"  Status: {queue_result['status']}")
    print(f"  Queue length: {queue_result['queue_length']}")
    print(f"  Message: {queue_result['message']}")
    
    # Test queue status
    status = api.get_queue_status()
    print(f"\nQueue status: {status['queue_length']} operations pending")
    
    print("\n✅ BraveSearchAPI tests passed!")


def test_openverse_api():
    """Test OpenVerse Search API class."""
    print("\n" + "=" * 70)
    print("Testing OpenVerse Search API Class")
    print("=" * 70)
    
    from openverse_search import OpenVerseSearchAPI
    
    # Initialize
    api = OpenVerseSearchAPI()
    print("✓ OpenVerseSearchAPI initialized")
    
    # Test _install()
    install_result = api._install()
    print("\n_install() result:")
    print(f"  Status: {install_result['status']}")
    print(f"  Instructions: {list(install_result['instructions'].keys())}")
    
    # Test _config()
    config_result = api._config(max_results=50, timeout=45)
    print("\n_config() result:")
    print(f"  Status: {config_result['status']}")
    print(f"  Configuration: {config_result['configuration']}")
    
    # Test _queue()
    queue_result = api._queue("search_images", query="nature", page_size=20)
    print("\n_queue() result:")
    print(f"  Status: {queue_result['status']}")
    print(f"  Queue item ID: {queue_result['queue_item']['id']}")
    
    # Clear queue
    clear_result = api.clear_queue()
    print(f"\nClear queue: {clear_result['message']}")
    
    print("\n✅ OpenVerseSearchAPI tests passed!")


def test_serpstack_api():
    """Test SerpStack Search API class."""
    print("\n" + "=" * 70)
    print("Testing SerpStack Search API Class")
    print("=" * 70)
    
    from serpstack_search import SerpStackSearchAPI
    
    # Initialize
    api = SerpStackSearchAPI()
    print("✓ SerpStackSearchAPI initialized")
    
    # Test _install()
    install_result = api._install()
    print("\n_install() result:")
    print(f"  Status: {install_result['status']}")
    print(f"  Ready: {install_result.get('ready', False)}")
    
    # Test _config()
    config_result = api._config(default_engine="bing", max_results=25)
    print("\n_config() result:")
    print(f"  Status: {config_result['status']}")
    print(f"  Supported engines: {config_result['supported_engines']}")
    
    # Test _queue()
    queue_result = api._queue("search", query="test", engine="google", num=10)
    print("\n_queue() result:")
    print(f"  Status: {queue_result['status']}")
    print(f"  Queue length: {queue_result['queue_length']}")
    
    print("\n✅ SerpStackSearchAPI tests passed!")


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Search API Class Tests" + " " * 30 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    try:
        test_brave_api()
        test_openverse_api()
        test_serpstack_api()
        
        print("\n" + "=" * 70)
        print("✅ All API class tests passed!")
        print("=" * 70)
        print()
        
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
