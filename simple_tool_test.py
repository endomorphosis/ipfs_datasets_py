#!/usr/bin/env python3
"""
Simple test for a single MCP tool.
"""

import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

def test_web_archive_tool():
    """Test the extract_text_from_warc tool."""
    try:
        print("Testing extract_text_from_warc tool...")
        
        # Import the tool
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc
        
        # Create a mock WARC file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name
        
        try:
            result = extract_text_from_warc(warc_path)
            
            print(f"Result: {result}")
            
            if isinstance(result, dict) and "status" in result:
                if result["status"] == "success":
                    print("✓ Tool executed successfully")
                    return True
                else:
                    print(f"✗ Tool returned error: {result.get('error', 'Unknown error')}")
                    return False
            else:
                print(f"✗ Unexpected result format: {type(result)}")
                return False
                
        finally:
            # Clean up temp file
            os.unlink(warc_path)
            
    except Exception as e:
        print(f"✗ Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_web_archive_tool()
    print(f"\nTest {'PASSED' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
