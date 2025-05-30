#!/usr/bin/env python3
"""
Simple test script to check MCP server startup.
"""
import sys
import os
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

try:
    from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
    
    print("Creating MCP server...")
    server = IPFSDatasetsMCPServer()
    
    print("Registering tools...")
    server.register_tools()
    
    print(f"Registered {len(server.tools)} tools:")
    for tool_name in sorted(server.tools.keys()):
        print(f"  - {tool_name}")
        
    print("✅ MCP server startup successful!")
    
    # Test the load_dataset tool validation
    if 'load_dataset' in server.tools:
        import asyncio
        load_dataset_func = server.tools['load_dataset']
        
        print("\nTesting load_dataset input validation...")
        
        # Test with Python file (should fail)
        try:
            result = asyncio.run(load_dataset_func(source="test.py"))
            print("❌ Python file validation failed - should have been rejected")
        except ValueError as e:
            print(f"✅ Python file correctly rejected: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            
        # Test with valid dataset name (should work)
        try:
            result = asyncio.run(load_dataset_func(source="squad"))
            print(f"✅ Valid dataset name accepted: {result['status']}")
        except Exception as e:
            print(f"📝 Dataset loading test result: {e}")
    
except Exception as e:
    print(f"❌ MCP server startup failed: {e}")
    import traceback
    traceback.print_exc()
