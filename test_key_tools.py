#!/usr/bin/env python3
"""Quick test of key MCP tools after fixes"""

import asyncio
import sys
import json
import traceback
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_key_tools():
    """Test key MCP tools to verify they're working"""
    results = {}
    
    print("🧪 Testing Key MCP Tools After Fixes")
    print("=" * 50)
    
    # Test 1: IPFS tools (should work)
    try:
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
        result = await pin_to_ipfs({'test': 'data'})
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} pin_to_ipfs: {result.get('status')}")
        results['pin_to_ipfs'] = result.get('status')
    except Exception as e:
        print(f"❌ pin_to_ipfs: error - {e}")
        results['pin_to_ipfs'] = f"error: {e}"
    
    # Test 2: Vector tools (recently fixed)
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        result = await create_vector_index(
            vectors=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], 
            metadata=[{'id': 0}, {'id': 1}]
        )
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} create_vector_index: {result.get('status')}")
        results['create_vector_index'] = result.get('status')
    except Exception as e:
        print(f"❌ create_vector_index: error - {e}")
        results['create_vector_index'] = f"error: {e}"
    
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
        result = await search_vector_index('test_index_id', [1.0, 2.0, 3.0])
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} search_vector_index: {result.get('status')}")
        results['search_vector_index'] = result.get('status')
    except Exception as e:
        print(f"❌ search_vector_index: error - {e}")
        results['search_vector_index'] = f"error: {e}"
    
    # Test 3: Web archive tools (recently fixed)
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc
        result = create_warc("https://example.com", "/tmp/test.warc")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} create_warc: {result.get('status')}")
        results['create_warc'] = result.get('status')
    except Exception as e:
        print(f"❌ create_warc: error - {e}")
        results['create_warc'] = f"error: {e}"
    
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj
        result = extract_dataset_from_cdxj("/tmp/test.cdxj")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} extract_dataset_from_cdxj: {result.get('status')}")
        results['extract_dataset_from_cdxj'] = result.get('status')
    except Exception as e:
        print(f"❌ extract_dataset_from_cdxj: error - {e}")
        results['extract_dataset_from_cdxj'] = f"error: {e}"
    
    # Test 4: Dataset tools
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        result = await load_dataset("test_dataset")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} load_dataset: {result.get('status')}")
        results['load_dataset'] = result.get('status')
    except Exception as e:
        print(f"❌ load_dataset: error - {e}")
        results['load_dataset'] = f"error: {e}"
    
    # Test 5: Audit tools
    try:
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report
        result = await generate_audit_report("security")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} generate_audit_report: {result.get('status')}")
        results['generate_audit_report'] = result.get('status')
    except Exception as e:
        print(f"❌ generate_audit_report: error - {e}")
        results['generate_audit_report'] = f"error: {e}"
    
    print("\n📊 Summary:")
    passed = sum(1 for v in results.values() if v == 'success')
    total = len(results)
    print(f"   {passed}/{total} tools working ({passed/total*100:.1f}%)")
    
    # Save detailed results
    with open('/home/barberb/ipfs_datasets_py/key_tools_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return results

if __name__ == "__main__":
    try:
        results = asyncio.run(test_key_tools())
        print("\n✅ Test completed - detailed results saved to key_tools_test_results.json")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
