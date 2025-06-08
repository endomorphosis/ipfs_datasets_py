#!/usr/bin/env python3
"""
Integration verification test - outputs results to file.
"""

import os
import sys
import datetime

def write_log(message):
    """Write message to both console and log file."""
    print(message)
    with open('integration_test_results.log', 'a') as f:
        f.write(f"{datetime.datetime.now().isoformat()}: {message}\n")

def main():
    # Clear log file
    if os.path.exists('integration_test_results.log'):
        os.remove('integration_test_results.log')
    
    write_log("=== INTEGRATION VERIFICATION TEST ===")
    write_log(f"Working directory: {os.getcwd()}")
    write_log(f"Python version: {sys.version}")
    
    # Test 1: Check file structure
    write_log("\n1. Checking core files...")
    
    core_files = [
        'ipfs_datasets_py/__init__.py',
        'ipfs_datasets_py/core.py',
        'ipfs_datasets_py/embeddings/core.py',
        'ipfs_datasets_py/vector_stores/base.py',
        'ipfs_datasets_py/mcp_server/server.py',
        'ipfs_datasets_py/fastapi_service.py'
    ]
    
    for file_path in core_files:
        if os.path.exists(file_path):
            write_log(f"✅ {file_path}")
        else:
            write_log(f"❌ {file_path}")
    
    # Test 2: Count MCP tools
    write_log("\n2. Counting MCP tools...")
    
    tool_dirs = [
        'ipfs_datasets_py/mcp_server/tools/embedding_tools',
        'ipfs_datasets_py/mcp_server/tools/admin_tools',
        'ipfs_datasets_py/mcp_server/tools/cache_tools',
        'ipfs_datasets_py/mcp_server/tools/analysis_tools',
        'ipfs_datasets_py/mcp_server/tools/workflow_tools'
    ]
    
    total_tools = 0
    for tool_dir in tool_dirs:
        if os.path.exists(tool_dir):
            py_files = [f for f in os.listdir(tool_dir) if f.endswith('.py') and f != '__init__.py']
            count = len(py_files)
            total_tools += count
            write_log(f"✅ {tool_dir}: {count} tools")
        else:
            write_log(f"❌ {tool_dir}: missing")
    
    write_log(f"\nTotal MCP tools found: {total_tools}")
    
    # Test 3: Check test files
    write_log("\n3. Checking test files...")
    
    test_files = [
        'tests/test_embedding_tools.py',
        'tests/test_admin_tools.py',
        'tests/test_fastapi_integration.py'
    ]
    
    test_count = 0
    for test_file in test_files:
        if os.path.exists(test_file):
            test_count += 1
            write_log(f"✅ {test_file}")
        else:
            write_log(f"❌ {test_file}")
    
    # Test 4: Check documentation
    write_log("\n4. Checking documentation...")
    
    docs = [
        'README.md',
        'FINAL_INTEGRATION_STATUS.md',
        'TOOL_REFERENCE_GUIDE.md'
    ]
    
    doc_count = 0
    for doc in docs:
        if os.path.exists(doc):
            doc_count += 1
            write_log(f"✅ {doc}")
        else:
            write_log(f"❌ {doc}")
    
    # Summary
    write_log("\n=== SUMMARY ===")
    write_log(f"MCP Tools: {total_tools}")
    write_log(f"Test Files: {test_count}")
    write_log(f"Documentation: {doc_count}")
    
    if total_tools > 50 and test_count > 5 and doc_count > 2:
        write_log("🎉 INTEGRATION APPEARS COMPLETE!")
        write_log("✅ All major components are present")
        return True
    else:
        write_log("⚠️ Integration may be incomplete")
        return False

if __name__ == "__main__":
    success = main()
    print(f"\nResults saved to: integration_test_results.log")
    sys.exit(0 if success else 1)
