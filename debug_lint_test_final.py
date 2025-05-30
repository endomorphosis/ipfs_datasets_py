#!/usr/bin/env python3
"""Debug script to identify linting tools issues"""

import sys
import traceback
import tempfile
import asyncio
from pathlib import Path

# Add the current directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Import linting tool
    print("Importing linting_tools module...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase, LintingTools

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

    # CORRECT APPROACH: Create the tool instance directly
    print("Creating linting tool instance directly...")
    tool = LintingTools()
    
    # Run the execute method
    print("Running the execute method asynchronously...")
    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(tool.execute(
            path=temp_path,
            fix_issues=False,
            dry_run=True
        ))
    except RuntimeError:
        # No event loop in thread
        result = asyncio.run(tool.execute(
            path=temp_path,
            fix_issues=False,
            dry_run=True
        ))

    print(f"Result success: {result['success']}")
    if result['success']:
        print(f"Issues found: {result['result']['total_issues']}")
        
        # Print the first few issues as an example
        if result['result']['issues']:
            print("\nExample issues:")
            for issue in result['result']['issues'][:5]:
                print(f"- {issue['file']}:{issue['line']} - {issue['rule']}: {issue['message']}")

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
