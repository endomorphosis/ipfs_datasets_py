#!/usr/bin/env python3
"""Quick fix for web archive tools that regressed"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio

def test_web_archive_fix():
    """Test and fix web archive tools"""
    
    print("🔧 Testing Web Archive Tools Fix")
    print("=" * 50)
    
    # Create test WARC file for testing
    test_warc_content = """WARC/1.0
WARC-Type: warcinfo
WARC-Date: 2023-01-01T00:00:00Z
WARC-Record-ID: <urn:uuid:test-record-1>
Content-Length: 0

WARC/1.0
WARC-Type: response
WARC-Target-URI: http://example.com/
WARC-Date: 2023-01-01T00:00:01Z
WARC-Record-ID: <urn:uuid:test-record-2>
Content-Type: application/http; msgtype=response
Content-Length: 100

HTTP/1.1 200 OK
Content-Type: text/html

<html><head><title>Test</title></head><body>Hello World</body></html>
"""
    
    test_warc_file = "/tmp/test_archive.warc"
    with open(test_warc_file, "w") as f:
        f.write(test_warc_content)
    
    # Create test CDXJ file
    test_cdxj_content = """com,example)/ 20230101000001 {"url": "http://example.com/", "mime": "text/html", "status": "200", "digest": "sha1:ABC123", "length": "100", "offset": "123", "filename": "test.warc.gz"}
"""
    
    test_cdxj_file = "/tmp/test_index.cdxj" 
    with open(test_cdxj_file, "w") as f:
        f.write(test_cdxj_content)
    
    print(f"✅ Created test files: {test_warc_file}, {test_cdxj_file}")
    
    # Test individual web archive tools
    results = []
    
    # Test 1: extract_text_from_warc (not async, no output_format parameter)
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc
        result = extract_text_from_warc(warc_path=test_warc_file)
        status = "✅ PASS" if result.get("status") == "success" else "❌ FAIL"
        results.append(("extract_text_from_warc", status, result.get("message", str(result))))
        print(f"extract_text_from_warc: {status}")
    except Exception as e:
        results.append(("extract_text_from_warc", "❌ FAIL", str(e)))
        print(f"extract_text_from_warc: ❌ FAIL - {e}")
    
    # Test 2: extract_dataset_from_cdxj (not async, output_format="dict")
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj
        result = extract_dataset_from_cdxj(cdxj_path=test_cdxj_file, output_format="dict")
        status = "✅ PASS" if result.get("status") == "success" else "❌ FAIL"
        results.append(("extract_dataset_from_cdxj", status, result.get("message", str(result))))
        print(f"extract_dataset_from_cdxj: {status}")
    except Exception as e:
        results.append(("extract_dataset_from_cdxj", "❌ FAIL", str(e)))
        print(f"extract_dataset_from_cdxj: ❌ FAIL - {e}")
    
    # Test 3: extract_links_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc
        result = extract_links_from_warc(warc_path=test_warc_file)
        status = "✅ PASS" if result.get("status") == "success" else "❌ FAIL"
        results.append(("extract_links_from_warc", status, result.get("message", str(result))))
        print(f"extract_links_from_warc: {status}")
    except Exception as e:
        results.append(("extract_links_from_warc", "❌ FAIL", str(e)))
        print(f"extract_links_from_warc: ❌ FAIL - {e}")
    
    # Test 4: extract_metadata_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc
        result = extract_metadata_from_warc(warc_path=test_warc_file)
        status = "✅ PASS" if result.get("status") == "success" else "❌ FAIL"
        results.append(("extract_metadata_from_warc", status, result.get("message", str(result))))
        print(f"extract_metadata_from_warc: {status}")
    except Exception as e:
        results.append(("extract_metadata_from_warc", "❌ FAIL", str(e)))
        print(f"extract_metadata_from_warc: ❌ FAIL - {e}")
    
    # Test 5: index_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc
        result = index_warc(warc_path=test_warc_file, output_path="/tmp/test_output.cdxj")
        status = "✅ PASS" if result.get("status") == "success" else "❌ FAIL"
        results.append(("index_warc", status, result.get("message", str(result))))
        print(f"index_warc: {status}")
    except Exception as e:
        results.append(("index_warc", "❌ FAIL", str(e)))
        print(f"index_warc: ❌ FAIL - {e}")
    
    print(f"\n📊 Web Archive Tools Test Results:")
    passed = sum(1 for _, status, _ in results if "PASS" in status)
    total = len(results)
    print(f"  Passed: {passed}/{total} ({passed/total*100:.1f}%)")
    
    return results

if __name__ == "__main__":
    test_web_archive_fix()
