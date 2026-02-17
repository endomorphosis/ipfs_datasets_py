"""CLI commands for Common Crawl Search Engine integration.

Provides command-line access to Common Crawl search and archiving functionality.
"""

import sys
import json
from typing import Optional


def handle_common_crawl_command(args):
    """
    Handle common-crawl CLI commands.
    
    Commands:
        common-crawl search <domain> [options]
        common-crawl collections [options]
        common-crawl fetch <warc-file> <offset> <length> [options]
        common-crawl info <collection> [options]
        common-crawl config [options]
    """
    if len(args) < 2:
        print_common_crawl_help()
        return
    
    subcommand = args[1]
    
    if subcommand == 'search':
        handle_search_command(args[2:])
    elif subcommand == 'collections' or subcommand == 'list':
        handle_collections_command(args[2:])
    elif subcommand == 'fetch':
        handle_fetch_command(args[2:])
    elif subcommand == 'info':
        handle_info_command(args[2:])
    elif subcommand == 'config':
        handle_config_command(args[2:])
    elif subcommand in ['help', '--help', '-h']:
        print_common_crawl_help()
    else:
        print(f"Error: Unknown subcommand '{subcommand}'")
        print_common_crawl_help()
        sys.exit(1)


def handle_search_command(args):
    """Handle 'common-crawl search' command."""
    if len(args) < 1:
        print("Error: domain required")
        print("Usage: ipfs-datasets common-crawl search <domain> [--max-matches N] [--collection NAME] [--mode local|remote|cli] [--endpoint URL] [--json]")
        sys.exit(1)
    
    domain = args[0]
    max_matches = 100
    collection = None
    mode = "local"
    endpoint = None
    json_output = False
    
    # Parse options
    i = 1
    while i < len(args):
        if args[i] in ['--max-matches', '-n'] and i + 1 < len(args):
            max_matches = int(args[i + 1])
            i += 2
        elif args[i] in ['--collection', '-c'] and i + 1 < len(args):
            collection = args[i + 1]
            i += 2
        elif args[i] in ['--mode', '-m'] and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] in ['--endpoint', '-e'] and i + 1 < len(args):
            endpoint = args[i + 1]
            i += 2
        elif args[i] == '--json':
            json_output = True
            i += 1
        else:
            i += 1
    
    # Execute search
    try:
        from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine
        
        # Initialize engine based on mode
        engine_kwargs = {"mode": mode}
        if endpoint:
            engine_kwargs["mcp_endpoint"] = endpoint
        
        engine = CommonCrawlSearchEngine(**engine_kwargs)
        
        if not engine.is_available():
            if json_output:
                print(json.dumps({
                    "status": "error",
                    "error": f"Common Crawl Search Engine not available in {mode} mode"
                }))
            else:
                print(f"Error: Common Crawl Search Engine not available in {mode} mode")
                if mode == "local":
                    print("Hint: Initialize the submodule with: git submodule update --init")
                elif mode == "remote":
                    print(f"Hint: Ensure MCP server is running at: {endpoint}")
            sys.exit(1)
        
        # Perform search
        results = engine.search_domain(domain, max_matches=max_matches, collection=collection)
        
        if json_output:
            print(json.dumps({
                "status": "success",
                "domain": domain,
                "max_matches": max_matches,
                "collection": collection,
                "mode": mode,
                "count": len(results),
                "results": results
            }, indent=2))
        else:
            print(f"Search results for domain: {domain}")
            print(f"Mode: {mode}")
            if collection:
                print(f"Collection: {collection}")
            print(f"Found {len(results)} results")
            print()
            
            for i, result in enumerate(results[:10], 1):  # Show first 10
                print(f"{i}. {result.get('url', 'N/A')}")
                print(f"   Timestamp: {result.get('timestamp', 'N/A')}")
                print(f"   WARC: {result.get('warc_filename', 'N/A')}")
                print()
            
            if len(results) > 10:
                print(f"... and {len(results) - 10} more results")
                print("Tip: Use --json flag to get all results in JSON format")
    
    except Exception as e:
        if json_output:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


def handle_collections_command(args):
    """Handle 'common-crawl collections' command."""
    mode = "local"
    endpoint = None
    json_output = False
    
    # Parse options
    i = 0
    while i < len(args):
        if args[i] in ['--mode', '-m'] and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] in ['--endpoint', '-e'] and i + 1 < len(args):
            endpoint = args[i + 1]
            i += 2
        elif args[i] == '--json':
            json_output = True
            i += 1
        else:
            i += 1
    
    try:
        from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine
        
        engine_kwargs = {"mode": mode}
        if endpoint:
            engine_kwargs["mcp_endpoint"] = endpoint
        
        engine = CommonCrawlSearchEngine(**engine_kwargs)
        
        if not engine.is_available():
            if json_output:
                print(json.dumps({"status": "error", "error": "Engine not available"}))
            else:
                print("Error: Engine not available")
            sys.exit(1)
        
        collections = engine.list_collections()
        
        if json_output:
            print(json.dumps({
                "status": "success",
                "mode": mode,
                "count": len(collections),
                "collections": collections
            }, indent=2))
        else:
            print(f"Available Common Crawl Collections ({len(collections)}):")
            for coll in collections:
                print(f"  - {coll}")
    
    except Exception as e:
        if json_output:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


def handle_fetch_command(args):
    """Handle 'common-crawl fetch' command."""
    if len(args) < 3:
        print("Error: warc-filename, offset, and length required")
        print("Usage: ipfs-datasets common-crawl fetch <warc-file> <offset> <length> [--mode local|remote|cli] [--endpoint URL] [--json]")
        sys.exit(1)
    
    warc_filename = args[0]
    warc_offset = int(args[1])
    warc_length = int(args[2])
    mode = "local"
    endpoint = None
    json_output = False
    
    # Parse options
    i = 3
    while i < len(args):
        if args[i] in ['--mode', '-m'] and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] in ['--endpoint', '-e'] and i + 1 < len(args):
            endpoint = args[i + 1]
            i += 2
        elif args[i] == '--json':
            json_output = True
            i += 1
        else:
            i += 1
    
    try:
        from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine
        
        engine_kwargs = {"mode": mode}
        if endpoint:
            engine_kwargs["mcp_endpoint"] = endpoint
        
        engine = CommonCrawlSearchEngine(**engine_kwargs)
        
        if not engine.is_available():
            if json_output:
                print(json.dumps({"status": "error", "error": "Engine not available"}))
            else:
                print("Error: Engine not available")
            sys.exit(1)
        
        content = engine.fetch_warc_record(warc_filename, warc_offset, warc_length)
        
        if json_output:
            print(json.dumps({
                "status": "success",
                "warc_filename": warc_filename,
                "warc_offset": warc_offset,
                "warc_length": warc_length,
                "content_length": len(content)
            }, indent=2))
        else:
            print(f"Fetched WARC record:")
            print(f"  File: {warc_filename}")
            print(f"  Offset: {warc_offset}")
            print(f"  Length: {warc_length}")
            print(f"  Content size: {len(content)} bytes")
    
    except Exception as e:
        if json_output:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


def handle_info_command(args):
    """Handle 'common-crawl info' command."""
    if len(args) < 1:
        print("Error: collection name required")
        print("Usage: ipfs-datasets common-crawl info <collection> [--mode local|remote|cli] [--endpoint URL] [--json]")
        sys.exit(1)
    
    collection = args[0]
    mode = "local"
    endpoint = None
    json_output = False
    
    # Parse options
    i = 1
    while i < len(args):
        if args[i] in ['--mode', '-m'] and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] in ['--endpoint', '-e'] and i + 1 < len(args):
            endpoint = args[i + 1]
            i += 2
        elif args[i] == '--json':
            json_output = True
            i += 1
        else:
            i += 1
    
    try:
        from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine
        
        engine_kwargs = {"mode": mode}
        if endpoint:
            engine_kwargs["mcp_endpoint"] = endpoint
        
        engine = CommonCrawlSearchEngine(**engine_kwargs)
        
        if not engine.is_available():
            if json_output:
                print(json.dumps({"status": "error", "error": "Engine not available"}))
            else:
                print("Error: Engine not available")
            sys.exit(1)
        
        info = engine.get_collection_info(collection)
        
        if json_output:
            print(json.dumps({
                "status": "success",
                "collection": collection,
                "info": info
            }, indent=2))
        else:
            print(f"Collection: {collection}")
            print(f"Info: {json.dumps(info, indent=2)}")
    
    except Exception as e:
        if json_output:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


def handle_config_command(args):
    """Handle 'common-crawl config' command."""
    json_output = '--json' in args
    
    try:
        from ipfs_datasets_py.processors.web_archiving import CommonCrawlSearchEngine
        
        # Show current configuration
        engine = CommonCrawlSearchEngine()
        
        config = {
            "submodule_available": engine.is_available(),
            "mode": "local",
            "state_dir": str(engine.state_dir),
            "supported_modes": ["local", "remote", "cli"]
        }
        
        if json_output:
            print(json.dumps(config, indent=2))
        else:
            print("Common Crawl Search Engine Configuration:")
            print(f"  Submodule available: {config['submodule_available']}")
            print(f"  Default mode: {config['mode']}")
            print(f"  State directory: {config['state_dir']}")
            print(f"  Supported modes: {', '.join(config['supported_modes'])}")
    
    except Exception as e:
        if json_output:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


def print_common_crawl_help():
    """Print help for common-crawl commands."""
    help_text = """
Common Crawl Search Engine Commands

Usage:
  ipfs-datasets common-crawl <command> [options]

Commands:
  search <domain>           Search Common Crawl for URLs from a domain
  collections               List available Common Crawl collections
  fetch <file> <off> <len>  Fetch a WARC record from Common Crawl
  info <collection>         Get information about a collection
  config                    Show configuration and status

Search Options:
  --max-matches, -n N       Maximum number of matches (default: 100)
  --collection, -c NAME     Specific collection to search
  --mode, -m MODE           Integration mode: local, remote, or cli
  --endpoint, -e URL        MCP server endpoint (for remote mode)
  --json                    Output in JSON format

Examples:
  # Search for a domain (local mode)
  ipfs-datasets common-crawl search example.com --max-matches 50
  
  # Search using remote MCP server
  ipfs-datasets common-crawl search example.com --mode remote --endpoint http://cc-server:8787
  
  # List collections
  ipfs-datasets common-crawl collections --json
  
  # Get collection info
  ipfs-datasets common-crawl info CC-MAIN-2024-10
  
  # Fetch WARC record
  ipfs-datasets common-crawl fetch crawl-data/file.warc.gz 12345 1000

For more information, see: docs/common_crawl_integration.md
"""
    print(help_text)


if __name__ == "__main__":
    handle_common_crawl_command(sys.argv)
