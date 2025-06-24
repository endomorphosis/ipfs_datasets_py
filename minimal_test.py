#!/usr/bin/env python3
"""
Minimal MCP Tools Test to check basic functionality
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

async def main():
    """Main test execution"""
    print("🚀 Starting Minimal MCP Tools Test")
    
    total_tests = 0
    passed_tests = 0
    
    # Test dataset tools - load_dataset
    try:
        print("Testing dataset load_dataset...")
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        result = await load_dataset(source="imdb", options={"split": "test[:2]"})
        total_tests += 1
        if result.get('status') == 'success':
            passed_tests += 1
            print("✅ load_dataset PASSED")
        else:
            print(f"❌ load_dataset FAILED: {result.get('message', 'Unknown error')}")
    except Exception as e:
        total_tests += 1
        print(f"💥 load_dataset CRASHED: {e}")
    
    # Test audit tools - record_audit_event (non-async)
    try:
        print("Testing audit record_audit_event...")
        from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
        result = record_audit_event(action="test_action")
        total_tests += 1
        if result.get('status') == 'success':
            passed_tests += 1
            print("✅ record_audit_event PASSED")
        else:
            print(f"❌ record_audit_event FAILED: {result.get('message', 'Unknown error')}")
    except Exception as e:
        total_tests += 1
        print(f"💥 record_audit_event CRASHED: {e}")
    
    # Test web archive tools
    try:
        print("Testing web archive extract_text_from_warc...")
        # Create test WARC file
        test_warc_content = """WARC/1.0\r\nWARC-Type: response\r\nWARC-Record-ID: <urn:uuid:test-record-id>\r\nWARC-Target-URI: https://example.com\r\nContent-Length: 100\r\n\r\n<html><head><title>Test</title></head><body>Test content</body></html>"""
        test_warc_file = "/tmp/test_minimal.warc"
        with open(test_warc_file, 'w') as f:
            f.write(test_warc_content)
        
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc
        result = await extract_text_from_warc(warc_file_path=test_warc_file, output_path="/tmp/test_minimal_text.json")
        total_tests += 1
        if result.get('status') == 'success':
            passed_tests += 1
            print("✅ extract_text_from_warc PASSED")
        else:
            print(f"❌ extract_text_from_warc FAILED: {result.get('message', 'Unknown error')}")
    except Exception as e:
        total_tests += 1
        print(f"💥 extract_text_from_warc CRASHED: {e}")
    
    # Test lizardpersons tools
    try:
        print("Testing lizardpersons use_function_as_tool...")
        from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.meta_tools.use_function_as_tool import use_function_as_tool
        result = await use_function_as_tool(function_name="test_function_name", args=[])
        total_tests += 1
        if result.get('status') == 'success':
            passed_tests += 1
            print("✅ use_function_as_tool PASSED")
        else:
            print(f"❌ use_function_as_tool FAILED: {result.get('message', 'Unknown error')}")
    except Exception as e:
        total_tests += 1
        print(f"💥 use_function_as_tool CRASHED: {e}")
    
    print(f"\n📊 SUMMARY:")
    print(f"   Total tests: {total_tests}")
    print(f"   Passed: {passed_tests}")
    print(f"   Failed: {total_tests - passed_tests}")
    print(f"   Success rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "   No tests run")
    
    return 0 if passed_tests == total_tests else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
