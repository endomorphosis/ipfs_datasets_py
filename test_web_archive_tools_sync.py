#!/usr/bin/env python3
"""
Test the Web Archive MCP tools existence and structure.

This script checks if the required web archive tools exist and have the
correct structure without attempting to import them.
"""
import os
import sys
import ast
from pathlib import Path
import asyncio

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

print("\nChecking Web Archive MCP Tools")
print("=" * 40)

def check_web_archive_tools():
    """Check all web archive tools."""
    # Define tool names to check
    tools = [
        "create_warc",
        "index_warc",
        "extract_dataset_from_cdxj",
        "extract_text_from_warc",
        "extract_links_from_warc",
        "extract_metadata_from_warc"
    ]

    # Get the tools directory path
    project_root = Path(__file__).resolve().parent
    tools_dir = project_root / "ipfs_datasets_py" / "mcp_server" / "tools" / "web_archive_tools"

    print(f"Looking for tools in: {tools_dir}")

    if not tools_dir.exists():
        print(f"✗ Tools directory not found: {tools_dir}")
        return False

    # Track results
    results = []

    # Check each tool
    for tool_name in tools:
        tool_path = tools_dir / f"{tool_name}.py"
        print(f"\nChecking {tool_name}...")

        if not tool_path.exists():
            print(f"✗ Tool file not found: {tool_path}")
            results.append((tool_name, "missing"))
            continue

        print(f"✓ Found tool file: {tool_path}")

        # Check file content
        try:
            with open(tool_path, "r") as f:
                content = f.read()

            # Use AST to parse the Python file
            tree = ast.parse(content)

            # Look for function definition with the same name as the file
            function_found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == tool_name:
                    function_found = True
                    print(f"✓ Found function definition: {tool_name}()")

                    # Check if function has correct parameters
                    args = [arg.arg for arg in node.args.args]
                    print(f"  Parameters: {', '.join(args)}")

                    # Check for import of WebArchiveProcessor
                    imports_processor = False
                    for subnode in ast.walk(tree):
                        if isinstance(subnode, ast.ImportFrom) and subnode.module and "web_archive_utils" in subnode.module:
                            imports_processor = True
                            print(f"✓ Imports from web_archive_utils")

                    if not imports_processor:
                        print(f"✗ Does not import from web_archive_utils")

                    results.append((tool_name, "valid" if imports_processor else "incomplete"))
                    break

            if not function_found:
                print(f"✗ Function definition not found: {tool_name}()")
                results.append((tool_name, "invalid"))

        except Exception as e:
            print(f"✗ Error processing {tool_path}: {e}")
            results.append((tool_name, "error"))

    # Print summary
    print("\nTool Check Summary")
    print("-" * 30)

    status_counts = {"valid": 0, "incomplete": 0, "invalid": 0, "missing": 0, "error": 0}

    for name, status in results:
        print(f"{name}: {status}")
        status_counts[status] += 1

    print("\nStatus Counts:")
    for status, count in status_counts.items():
        print(f"{status}: {count}")

    return status_counts["valid"] == len(tools)

# Test paths
test_dir = Path("/tmp/mcp_web_archive_test")
url = "https://example.com"
warc_path = test_dir / "test.warc"
cdxj_path = test_dir / "test.cdxj"
output_path = test_dir / "output.json"

if __name__ == "__main__":
    # Create test directory
    os.makedirs(test_dir, exist_ok=True)
    print(f"✓ Created test directory: {test_dir}")

    # Create empty test files
    warc_path.touch()
    cdxj_path.touch()
    print("✓ Created test files")

    check_web_archive_tools()

    # Import the tools
    try:
        # Import the main test function from test_web_archive_mcp_tools.py
        from test_web_archive_mcp_tools import test_web_archive_tools as run_web_archive_mcp_tests

        print("\nRunning web_archive_mcp_tools tests...")
        # The test_web_archive_mcp_tools function is async, so it needs to be awaited.
        # The main block is not async, so we use asyncio.run to run the async function.
        success = asyncio.run(run_web_archive_mcp_tests())

        if success:
            print("✓ All web_archive_mcp_tools tests passed.")
        else:
            print("✗ Some web_archive_mcp_tools tests failed.")

    except ImportError as e:
        print(f"✗ Error importing web archive tools: {e}")

    # Clean up
    import shutil
    shutil.rmtree(test_dir)
    print(f"✓ Cleaned up test directory: {test_dir}")
