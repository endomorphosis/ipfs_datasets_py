#!/usr/bin/env python3
"""Debug script to identify linting tools issues"""

import sys
import traceback
import tempfile
import anyio
from pathlib import Path

# Add the current directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Import linting tool
    print("Importing linting_tools module...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

    print(f"Type of lint_python_codebase: {type(lint_python_codebase)}")

    # Check if it's a callable
    if callable(lint_python_codebase):
        print("lint_python_codebase is callable")
    else:
        print("WARNING: lint_python_codebase is not callable!")

    # Create a temporary Python file with deliberate linting issues
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w+', delete=False) as temp:
        print(f"Creating temporary file {temp.name}...")
        temp.write("""
import sys, os  # Multiple imports should be on separate lines
def bad_function( a,b ):  # Extra space after open paren
    x = 10  # Unused variable
    return None
        """)
        temp_path = temp.name

    # Import config for debugging
    print("Getting configuration...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.config import get_config
    config = get_config()
    print(f"LintingToolsConfig attributes: {vars(config.linting_tools)}")

    # Get a linting tool instance
    print("Creating linting tool instance...")
    tool_instance = lint_python_codebase()
    print(f"Tool instance: {tool_instance}, type: {type(tool_instance)}")

    # Use the correct approach: run_until_complete on the execute coroutine
    print("Running the execute method asynchronously...")
    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(tool_instance.execute(
            path=temp_path,
            fix_issues=False,
            dry_run=True
        ))
    except RuntimeError:
        # No event loop in thread
        result = anyio.run(tool_instance.execute(
            path=temp_path,
            fix_issues=False,
            dry_run=True
        ))

    print(f"Result: {result}")

except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
finally:
    # Clean up temporary file
    try:
        Path(temp_path).unlink(missing_ok=True)
        print(f"Deleted temporary file {temp_path}")
    except:
        pass
