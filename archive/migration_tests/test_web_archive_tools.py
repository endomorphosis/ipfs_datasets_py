#!/usr/bin/env python3
"""Test the fixed web archive tools"""

import asyncio
import sys
import json
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

async def test_web_archive_tools():
    """Test the web archive tools we just fixed"""
    results = {}
    
    print("🧪 Testing Fixed Web Archive Tools")
    print("=" * 40)
    
    # Test 1: extract_links_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc
        result = extract_links_from_warc("/tmp/test.warc")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} extract_links_from_warc: {result.get('status')}")
        results['extract_links_from_warc'] = result.get('status')
    except Exception as e:
        print(f"❌ extract_links_from_warc: error - {e}")
        results['extract_links_from_warc'] = f"error: {e}"
    
    # Test 2: extract_metadata_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc
        result = extract_metadata_from_warc("/tmp/test_meta.warc")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} extract_metadata_from_warc: {result.get('status')}")
        results['extract_metadata_from_warc'] = result.get('status')
    except Exception as e:
        print(f"❌ extract_metadata_from_warc: error - {e}")
        results['extract_metadata_from_warc'] = f"error: {e}"
    
    # Test 3: extract_text_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc
        result = extract_text_from_warc("/tmp/test_text.warc")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} extract_text_from_warc: {result.get('status')}")
        results['extract_text_from_warc'] = result.get('status')
    except Exception as e:
        print(f"❌ extract_text_from_warc: error - {e}")
        results['extract_text_from_warc'] = f"error: {e}"
    
    # Test 4: index_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc
        result = index_warc("/tmp/test_index.warc")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} index_warc: {result.get('status')}")
        results['index_warc'] = result.get('status')
    except Exception as e:
        print(f"❌ index_warc: error - {e}")
        results['index_warc'] = f"error: {e}"
    
    # Test 5: extract_dataset_from_cdxj (already fixed)
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj
        result = extract_dataset_from_cdxj("/tmp/test.cdxj")
        status = "✅" if result.get('status') == 'success' else "❌"
        print(f"{status} extract_dataset_from_cdxj: {result.get('status')}")
        results['extract_dataset_from_cdxj'] = result.get('status')
    except Exception as e:
        print(f"❌ extract_dataset_from_cdxj: error - {e}")
        results['extract_dataset_from_cdxj'] = f"error: {e}"
    
    print("\n📊 Summary:")
    passed = sum(1 for v in results.values() if v == 'success')
    total = len(results)
    print(f"   {passed}/{total} web archive tools working ({passed/total*100:.1f}%)")
    
    # Save results
    with open('/home/barberb/ipfs_datasets_py/web_archive_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return results

if __name__ == "__main__":
    try:
        results = asyncio.run(test_web_archive_tools())
        print("\n✅ Web archive tools test completed")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
