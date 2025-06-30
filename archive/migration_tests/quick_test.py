#!/usr/bin/env python3
"""Quick test of MCP tools after VS Code reload"""

import asyncio
import sys
import traceback
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_key_tools():
    """Test key MCP tools"""
    results = {}
    
    # Test 1: pin_to_ipfs (should work)
    try:
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
        result = await pin_to_ipfs({'test': 'data'})
        results['pin_to_ipfs'] = result.get('status')
        print(f"✅ pin_to_ipfs: {result.get('status')}")
    except Exception as e:
        results['pin_to_ipfs'] = f"error: {e}"
        print(f"❌ pin_to_ipfs: {e}")
    
    # Test 2: load_dataset
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        result = await load_dataset('imdb')
        results['load_dataset'] = result.get('status')
        print(f"✅ load_dataset: {result.get('status')}")
    except Exception as e:
        results['load_dataset'] = f"error: {e}"
        print(f"❌ load_dataset: {e}")
    
    # Test 3: create_vector_index
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        result = await create_vector_index([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        results['create_vector_index'] = result.get('status')
        print(f"✅ create_vector_index: {result.get('status')}")
    except Exception as e:
        results['create_vector_index'] = f"error: {e}"
        print(f"❌ create_vector_index: {e}")
    
    # Test 4: generate_audit_report
    try:
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report
        result = await generate_audit_report()
        results['generate_audit_report'] = result.get('status')
        print(f"✅ generate_audit_report: {result.get('status')}")
    except Exception as e:
        results['generate_audit_report'] = f"error: {e}"
        print(f"❌ generate_audit_report: {e}")
    
    print(f"\n📊 Test Results Summary:")
    for tool, status in results.items():
        print(f"  {tool}: {status}")
    
    return results

if __name__ == "__main__":
    try:
        results = asyncio.run(test_key_tools())
        print(f"\n✅ Test completed successfully")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
