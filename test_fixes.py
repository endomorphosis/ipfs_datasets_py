#!/usr/bin/env python3
"""Test MCP tools fixes and write results to file"""

import asyncio
import sys
import json
import traceback
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_fixed_tools():
    """Test the tools we just fixed"""
    results = {}
    
    # Test 1: create_vector_index (fixed metadata handling)
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        result = await create_vector_index(
            vectors=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], 
            metadata=[{'id': 0}, {'id': 1}]
        )
        results['create_vector_index'] = result.get('status')
        results['create_vector_index_details'] = result
    except Exception as e:
        results['create_vector_index'] = f"error: {e}"
        results['create_vector_index_error'] = traceback.format_exc()
    
    # Test 2: search_vector_index (fixed index creation)
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
        result = await search_vector_index('test_index_id', [1.0, 2.0, 3.0])
        results['search_vector_index'] = result.get('status')
        results['search_vector_index_details'] = result
    except Exception as e:
        results['search_vector_index'] = f"error: {e}"
        results['search_vector_index_error'] = traceback.format_exc()
    
    # Test 3: pin_to_ipfs (should still work)
    try:
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
        result = await pin_to_ipfs({'test': 'data'})
        results['pin_to_ipfs'] = result.get('status')
    except Exception as e:
        results['pin_to_ipfs'] = f"error: {e}"
    
    # Save results to file
    with open('/home/barberb/ipfs_datasets_py/test_fixes_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return results

if __name__ == "__main__":
    try:
        results = asyncio.run(test_fixed_tools())
        print("✅ Test completed - results saved to test_fixes_results.json")
        # Print summary
        for tool, status in results.items():
            if not tool.endswith('_details') and not tool.endswith('_error'):
                print(f"  {tool}: {status}")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        with open('/home/barberb/ipfs_datasets_py/test_fixes_error.txt', 'w') as f:
            f.write(f"Error: {e}\n{traceback.format_exc()}")
