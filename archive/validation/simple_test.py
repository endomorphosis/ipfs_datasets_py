#!/usr/bin/env python3
    # Test 3: Check MCP tools
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        print("✅ MCP server available")
    except Exception as e:
        print(f"❌ MCP server not available: {e}")mple test to verify the integration is working.
"""

def main():
    print("Testing basic functionality...")
    
    # Test 1: Basic import
    try:
        import ipfs_datasets_py
        print("✅ Package imports successfully")
    except Exception as e:
        print(f"❌ Package import failed: {e}")
        return False
    
    # Test 2: Check if we have the new features
    try:
        from ipfs_datasets_py import enable_embeddings, enable_vector_stores
        print("✅ Feature flags available")
    except Exception as e:
        print(f"❌ Feature flags not available: {e}")
    
    # Test 3: Check MCP tools
    try:
        from ipfs_datasets_py.mcp_server.server import create_server
        print("✅ MCP server available")
    except Exception as e:
        print(f"❌ MCP server not available: {e}")
    
    # Test 4: Check FastAPI
    try:
        from ipfs_datasets_py.fastapi_service import app
        print("✅ FastAPI service available")
    except Exception as e:
        print(f"❌ FastAPI service not available: {e}")
    
    print("Integration test completed!")
    return True

if __name__ == "__main__":
    main()
