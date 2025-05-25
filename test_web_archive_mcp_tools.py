#!/usr/bin/env python3
"""
Test runner for Web Archive MCP tools.

This script tests the web archive tools in the MCP server by directly calling them
with appropriate test data.
"""
import asyncio
import os
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

print("Testing Web Archive MCP Tools")
print("=" * 40)

async def test_web_archive_tools():
    """Test all web archive tools."""
    try:
        # Import tools
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_dataset_from_cdxj import extract_dataset_from_cdxj
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc
        print("✓ Successfully imported web archive tool functions")
    except ImportError as e:
        print(f"✗ Error importing web archive tool functions: {e}")
        return False
    
    # Create test directory
    test_dir = Path("/tmp/mcp_web_archive_test")
    os.makedirs(test_dir, exist_ok=True)
    print(f"✓ Created test directory: {test_dir}")
    
    # Test paths
    url = "https://example.com"
    warc_path = test_dir / "test.warc"
    cdxj_path = test_dir / "test.cdxj"
    output_path = test_dir / "output.json"
    
    # Create empty test files
    warc_path.touch()
    cdxj_path.touch()
    print("✓ Created test files")
    
    # Hack: replace WebArchiveProcessor with a mock
    class MockWebArchiveProcessor:
        def create_warc(self, url: str, output_path: str):
            return {"status": "success", "message": "WARC created (mock)", "warc_path": output_path}
        
        def index_warc(self, warc_path: str, output_path: str):
            return {"status": "success", "message": "WARC indexed (mock)", "cdxj_path": output_path}
        
        def extract_dataset_from_cdxj(self, cdxj_path: str, output_format: str):
            return {"status": "success", "message": "Dataset extracted (mock)", "data": [{"id": 1, "text": "Sample"}]}
        
        def extract_text_from_warc(self, warc_path: str):
            return {"status": "success", "message": "Text extracted (mock)", "text": "Sample extracted text"}
        
        def extract_links_from_warc(self, warc_path: str):
            return {"status": "success", "message": "Links extracted (mock)", "links": ["https://example.com/page1", "https://example.com/page2"]}
        
        def extract_metadata_from_warc(self, warc_path: str):
            return {"status": "success", "message": "Metadata extracted (mock)", "metadata": {"title": "Example Page", "description": "Sample description"}}
    
    # Modify the original WebArchiveProcessor to use our mock
    import ipfs_datasets_py.web_archive_utils
    original_processor = ipfs_datasets_py.web_archive_utils.WebArchiveProcessor
    ipfs_datasets_py.web_archive_utils.WebArchiveProcessor = MockWebArchiveProcessor
    
    try:
        # Test create_warc
        print("\nTesting create_warc...")
        result = create_warc( # Removed await
            url=url,
            output_path=str(warc_path)
        )
        print(f"Result: {result}")
        if result["status"] == "success":
            print("✓ create_warc test passed")
        else:
            print("✗ create_warc test failed")
        
        # Test index_warc
        print("\nTesting index_warc...")
        result = index_warc( # Removed await
            warc_path=str(warc_path),
            output_path=str(cdxj_path)
        )
        print(f"Result: {result}")
        if result["status"] == "success":
            print("✓ index_warc test passed")
        else:
            print("✗ index_warc test failed")
        
        # Test extract_dataset_from_cdxj
        print("\nTesting extract_dataset_from_cdxj...")
        result = extract_dataset_from_cdxj( # Removed await
            cdxj_path=str(cdxj_path),
            output_format="dict" # Changed output_path to output_format
        )
        print(f"Result: {result}")
        if result["status"] == "success":
            print("✓ extract_dataset_from_cdxj test passed")
        else:
            print("✗ extract_dataset_from_cdxj test failed")
        
        # Test extract_text_from_warc
        print("\nTesting extract_text_from_warc...")
        result = extract_text_from_warc( # Removed await
            warc_path=str(warc_path)
        )
        print(f"Result: {result}")
        if result["status"] == "success":
            print("✓ extract_text_from_warc test passed")
        else:
            print("✗ extract_text_from_warc test failed")
        
        # Test extract_links_from_warc
        print("\nTesting extract_links_from_warc...")
        result = extract_links_from_warc( # Removed await
            warc_path=str(warc_path)
        )
        print(f"Result: {result}")
        if result["status"] == "success":
            print("✓ extract_links_from_warc test passed")
        else:
            print("✗ extract_links_from_warc test failed")
        
        # Test extract_metadata_from_warc
        print("\nTesting extract_metadata_from_warc...")
        result = extract_metadata_from_warc( # Removed await
            warc_path=str(warc_path)
        )
        print(f"Result: {result}")
        if result["status"] == "success":
            print("✓ extract_metadata_from_warc test passed")
        else:
            print("✗ extract_metadata_from_warc test failed")
        
        print("\nAll web archive tools tests completed")
        return True
    
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Restore original WebArchiveProcessor
        ipfs_datasets_py.web_archive_utils.WebArchiveProcessor = original_processor
        
        # Clean up test directory
        import shutil
        shutil.rmtree(test_dir)
        print(f"Cleaned up test directory: {test_dir}")

if __name__ == "__main__":
    asyncio.run(test_web_archive_tools())
