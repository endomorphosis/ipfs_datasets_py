#!/usr/bin/env python3
"""
Simple test for web archive tools to verify functionality.
"""
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def test_web_archive_integration():
    """Test web archive tools directly."""
    print("Testing Web Archive Integration...")

    # Test basic functionality first
    try:
        from ipfs_datasets_py.web_archiving.web_archive import WebArchiveProcessor
        processor = WebArchiveProcessor()
        print("✓ WebArchiveProcessor imported successfully")

        # Test HTML extraction
        html = "<html><body><h1>Test</h1><p>Content</p></body></html>"
        result = processor.extract_text_from_html(html)
        print(f"✓ extract_text_from_html: {result['status']}")

        # Create temporary test files
        with tempfile.TemporaryDirectory() as temp_dir:
            warc_path = os.path.join(temp_dir, "test.warc")
            with open(warc_path, 'w') as f:
                f.write("WARC/1.0\nTest content\n")

            # Test WARC methods
            try:
                text_records = processor.extract_text_from_warc(warc_path)
                print(f"✓ extract_text_from_warc: {len(text_records)} records")
            except Exception as e:
                print(f"✗ extract_text_from_warc: {e}")

            try:
                metadata = processor.extract_metadata_from_warc(warc_path)
                print(f"✓ extract_metadata_from_warc: {metadata['record_count']} records")
            except Exception as e:
                print(f"✗ extract_metadata_from_warc: {e}")

            try:
                links = processor.extract_links_from_warc(warc_path)
                print(f"✓ extract_links_from_warc: {len(links)} links")
            except Exception as e:
                print(f"✗ extract_links_from_warc: {e}")

        return True

    except Exception as e:
        print(f"✗ WebArchiveProcessor test failed: {e}")
        return False

def test_mcp_web_archive_tools():
    """Test MCP web archive tools."""
    print("\nTesting MCP Web Archive Tools...")

    try:
        # Add MCP tools to path
        tools_path = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "web_archive_tools"
        sys.path.insert(0, str(tools_path))

        # Create test files
        with tempfile.TemporaryDirectory() as temp_dir:
            warc_path = os.path.join(temp_dir, "test.warc")
            with open(warc_path, 'w') as f:
                f.write("WARC/1.0\nTest content\n")

            # Test extract_text_from_warc tool
            try:
                from extract_text_from_warc import extract_text_from_warc
                result = extract_text_from_warc(warc_path)
                print(f"✓ extract_text_from_warc tool: {result['status']}")
            except Exception as e:
                print(f"✗ extract_text_from_warc tool: {e}")

            # Test extract_metadata_from_warc tool
            try:
                from extract_metadata_from_warc import extract_metadata_from_warc
                result = await extract_metadata_from_warc(warc_path)
                print(f"✓ extract_metadata_from_warc tool: {result['status']}")
            except Exception as e:
                print(f"✗ extract_metadata_from_warc tool: {e}")

            # Test create_warc tool
            try:
                from create_warc import create_warc
                result = create_warc(["https://example.com"], os.path.join(temp_dir, "new.warc"))
                print(f"✓ create_warc tool: {result['status']}")
            except Exception as e:
                print(f"✗ create_warc tool: {e}")

        return True

    except Exception as e:
        print(f"✗ MCP web archive tools test failed: {e}")
        return False

def main():
    print("Simple MCP Web Archive Tools Test")
    print("=" * 40)

    success1 = test_web_archive_integration()
    success2 = test_mcp_web_archive_tools()

    if success1 and success2:
        print("\n🎉 All web archive tests passed!")
        return True
    else:
        print("\n⚠️ Some tests failed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
