#!/usr/bin/env python3
"""
Common Crawl Search Engine Integration Demo

This script demonstrates the various ways to use the Common Crawl Search Engine
integration in IPFS Datasets Python.
"""

import sys
import json


def demo_local_mode():
    """Demonstrate local mode integration."""
    print("=" * 60)
    print("Demo 1: Local Mode Integration")
    print("=" * 60)
    
    try:
        from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine
        
        # Initialize in local mode (default)
        print("\n1. Initializing CommonCrawlSearchEngine in local mode...")
        engine = CommonCrawlSearchEngine(mode="local")
        
        print(f"   ✓ Engine initialized")
        print(f"   ✓ Available: {engine.is_available()}")
        
        if not engine.is_available():
            print("\n   ⚠ Submodule not initialized. Run:")
            print("   git submodule update --init --recursive")
            return
        
        # Example: Search for a domain
        print("\n2. Searching for domain 'example.com'...")
        results = engine.search_domain("example.com", max_matches=5)
        print(f"   ✓ Found {len(results)} results")
        
        if results:
            print("\n   Sample result:")
            print(f"   {json.dumps(results[0], indent=4)}")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")


def demo_remote_mode():
    """Demonstrate remote mode integration."""
    print("\n" + "=" * 60)
    print("Demo 2: Remote Mode Integration")
    print("=" * 60)
    
    try:
        from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine
        
        # Initialize in remote mode (requires MCP server)
        print("\n1. Initializing CommonCrawlSearchEngine in remote mode...")
        print("   Note: This requires a running MCP server")
        
        # Example endpoint (would need to be real)
        endpoint = "http://localhost:8787"
        
        engine = CommonCrawlSearchEngine(
            mode="remote",
            mcp_endpoint=endpoint
        )
        
        print(f"   ✓ Engine configured for remote mode")
        print(f"   ✓ Endpoint: {endpoint}")
        print(f"   ✓ Available: {engine.is_available()}")
        
        # Would perform actual search if server was running
        print("\n2. To use remote mode, start the MCP server:")
        print("   ccindex-mcp-server --mode tcp --host 0.0.0.0 --port 8787")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")


def demo_cli_mode():
    """Demonstrate CLI mode integration."""
    print("\n" + "=" * 60)
    print("Demo 3: CLI Mode Integration")
    print("=" * 60)
    
    try:
        from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine
        
        print("\n1. Initializing CommonCrawlSearchEngine in CLI mode...")
        engine = CommonCrawlSearchEngine(mode="cli")
        
        print(f"   ✓ Engine configured for CLI mode")
        print(f"   ✓ Available: {engine.is_available()}")
        
        if not engine.is_available():
            print("\n   ⚠ ccindex CLI not installed. Install with:")
            print("   cd ipfs_datasets_py/web_archiving/common_crawl_search_engine")
            print("   pip install -e .")
            return
        
        print("\n2. CLI commands available:")
        print("   ipfs-datasets common-crawl search example.com")
        print("   ipfs-datasets common-crawl collections")
        print("   ipfs-datasets common-crawl info CC-MAIN-2024-10")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")


def demo_mcp_tools():
    """Demonstrate MCP tools integration."""
    print("\n" + "=" * 60)
    print("Demo 4: MCP Tools Integration")
    print("=" * 60)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
            search_common_crawl_advanced,
            list_common_crawl_collections_advanced,
        )
        
        print("\n1. MCP tools imported successfully:")
        print("   ✓ search_common_crawl_advanced")
        print("   ✓ list_common_crawl_collections_advanced")
        print("   ✓ fetch_warc_record_advanced")
        print("   ✓ get_common_crawl_collection_info_advanced")
        
        print("\n2. Example async usage:")
        print("   import asyncio")
        print("   result = await search_common_crawl_advanced(")
        print("       domain='example.com',")
        print("       max_matches=100")
        print("   )")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")


def demo_dashboard_integration():
    """Demonstrate dashboard integration."""
    print("\n" + "=" * 60)
    print("Demo 5: Dashboard Integration")
    print("=" * 60)
    
    try:
        from ipfs_datasets_py.dashboards.common_crawl_dashboard import (
            CommonCrawlDashboardIntegration,
            create_dashboard_integration
        )
        
        print("\n1. Creating dashboard integration...")
        integration = create_dashboard_integration(
            mode="remote",
            remote_endpoint="http://localhost:8787"
        )
        
        print(f"   ✓ Dashboard integration created")
        
        # Get configuration
        iframe_config = integration.get_iframe_config()
        print(f"\n2. Dashboard configuration:")
        print(f"   Name: {iframe_config['name']}")
        print(f"   Title: {iframe_config['title']}")
        print(f"   Icon: {iframe_config['icon']}")
        print(f"   Category: {iframe_config['category']}")
        
        nav_item = integration.get_nav_item()
        print(f"\n3. Navigation item:")
        print(f"   ID: {nav_item['id']}")
        print(f"   Label: {nav_item['label']}")
        print(f"   URL: {nav_item['url']}")
        
        print("\n4. To integrate with Flask app:")
        print("   from ipfs_datasets_py.dashboards.common_crawl_dashboard import register_dashboard_routes")
        print("   register_dashboard_routes(app, prefix='/subdashboard/common-crawl')")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")


def demo_package_exports():
    """Demonstrate package exports."""
    print("\n" + "=" * 60)
    print("Demo 6: Package Exports")
    print("=" * 60)
    
    try:
        # Import from top-level package
        import ipfs_datasets_py
        
        print("\n1. Checking package exports...")
        
        has_common_crawl = hasattr(ipfs_datasets_py, 'CommonCrawlSearchEngine')
        print(f"   CommonCrawlSearchEngine: {'✓' if has_common_crawl else '✗'}")
        
        has_create_engine = hasattr(ipfs_datasets_py, 'create_search_engine')
        print(f"   create_search_engine: {'✓' if has_create_engine else '✗'}")
        
        has_flag = hasattr(ipfs_datasets_py, 'HAVE_COMMON_CRAWL')
        print(f"   HAVE_COMMON_CRAWL: {'✓' if has_flag else '✗'}")
        
        if has_flag:
            print(f"\n2. HAVE_COMMON_CRAWL = {ipfs_datasets_py.HAVE_COMMON_CRAWL}")
        
        print("\n3. Usage:")
        print("   from ipfs_datasets_py import CommonCrawlSearchEngine")
        print("   engine = CommonCrawlSearchEngine()")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  Common Crawl Search Engine Integration Demo".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")
    
    # Run all demos
    demo_local_mode()
    demo_remote_mode()
    demo_cli_mode()
    demo_mcp_tools()
    demo_dashboard_integration()
    demo_package_exports()
    
    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nFor more information, see:")
    print("  docs/common_crawl_integration.md")
    print()


if __name__ == "__main__":
    main()
