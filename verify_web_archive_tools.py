#!/usr/bin/env python3
"""
Verify MCP Web Archive Tools Implementation.

This script checks if the web archive tools are properly implemented
in the MCP server and attempts to run them with mocked dependencies.
"""
import os
import sys
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def verify_web_archive_tools():
    """Verify the implementation of web archive tools."""
    print("\nVerifying Web Archive MCP Tools")
    print("=" * 50)
    
    # Define the tools to check
    tools = [
        "create_warc",
        "index_warc",
        "extract_dataset_from_cdxj",
        "extract_text_from_warc",
        "extract_links_from_warc",
        "extract_metadata_from_warc"
    ]
    
    # Create test paths
    test_dir = Path("/tmp/mcp_test")
    os.makedirs(test_dir, exist_ok=True)
    warc_path = test_dir / "test.warc"
    cdxj_path = test_dir / "test.cdxj"
    output_path = test_dir / "output.json"
    
    # Create basic files
    with open(warc_path, "w") as f:
        f.write("mock warc content")
    with open(cdxj_path, "w") as f:
        f.write("mock cdxj content")
    
    # Create mock for WebArchiveProcessor
    mock_processor = MagicMock()
    mock_processor.create_warc.return_value = str(warc_path)
    mock_processor.index_warc.return_value = str(cdxj_path)
    mock_processor.extract_dataset_from_cdxj.return_value = {"data": [{"id": 1}]}
    mock_processor.extract_text_from_warc.return_value = {"text": "sample text"}
    mock_processor.extract_links_from_warc.return_value = ["https://example.com"]
    mock_processor.extract_metadata_from_warc.return_value = {"title": "Example"}
    
    # Track results
    results = []
    
    # Apply patch to WebArchiveProcessor
    with patch("ipfs_datasets_py.web_archive_utils.WebArchiveProcessor", 
               return_value=mock_processor):
        
        # Try to import ipfs_datasets_py
        try:
            import ipfs_datasets_py
            print("✓ Successfully imported ipfs_datasets_py")
            
            # Check each tool
            for tool_name in tools:
                print(f"\nChecking {tool_name}...")
                tool_path = Path(f"ipfs_datasets_py/mcp_server/tools/web_archive_tools/{tool_name}.py")
                
                if not (Path.cwd() / tool_path).exists():
                    print(f"✗ Tool file not found: {tool_path}")
                    results.append((tool_name, False, "File not found"))
                    continue
                
                print(f"✓ Found tool file: {tool_path}")
                
                # Try to import the tool module
                try:
                    # First import the package
                    module_name = f"ipfs_datasets_py.mcp_server.tools.web_archive_tools.{tool_name}"
                    __import__(module_name)
                    module = sys.modules[module_name]
                    print(f"✓ Successfully imported {module_name}")
                    
                    # Check if the module has the expected function
                    if hasattr(module, tool_name):
                        func = getattr(module, tool_name)
                        print(f"✓ Found function: {tool_name}")
                        
                        # Check function signature
                        sig = inspect.signature(func)
                        print(f"  Function signature: {sig}")
                        
                        # Try to call the function
                        try:
                            if tool_name == "create_warc":
                                result = func("https://example.com", str(output_path))
                            elif tool_name == "index_warc":
                                result = func(str(warc_path), str(output_path))
                            elif tool_name == "extract_dataset_from_cdxj":
                                result = func(str(cdxj_path), str(output_path))
                            elif tool_name in ["extract_text_from_warc", "extract_links_from_warc", "extract_metadata_from_warc"]:
                                result = func(str(warc_path), str(output_path))
                            else:
                                result = {"status": "untested"}
                            
                            print(f"  Result: {result}")
                            
                            # Check if the result is as expected
                            if isinstance(result, dict) and "status" in result:
                                status = result["status"]
                                if status == "success":
                                    print(f"✓ Function returned success")
                                    results.append((tool_name, True, "Function works"))
                                else:
                                    print(f"✗ Function returned non-success status: {status}")
                                    results.append((tool_name, False, f"Status: {status}"))
                            else:
                                print(f"✗ Function returned unexpected result")
                                results.append((tool_name, False, "Unexpected result format"))
                        
                        except Exception as e:
                            print(f"✗ Error calling function: {e}")
                            results.append((tool_name, False, f"Error calling function: {e}"))
                    
                    else:
                        print(f"✗ Function {tool_name} not found in module")
                        results.append((tool_name, False, "Function not found"))
                
                except ImportError as e:
                    print(f"✗ Error importing module: {e}")
                    results.append((tool_name, False, f"Import error: {e}"))
        
        except ImportError as e:
            print(f"✗ Error importing ipfs_datasets_py: {e}")
            results.append(("ipfs_datasets_py", False, f"Import error: {e}"))
    
    # Print summary
    print("\nVerification Summary")
    print("=" * 50)
    success_count = sum(1 for _, success, _ in results if success)
    print(f"Verified {success_count}/{len(tools)} tools")
    
    for name, success, message in results:
        status = "✓" if success else "✗"
        print(f"{status} {name}: {message}")
    
    # Clean up
    import shutil
    shutil.rmtree(test_dir)

if __name__ == "__main__":
    verify_web_archive_tools()
