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
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintingTools

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

    # Create linting tool instance directly
    print("Creating linting tool instance...")
    tool = LintingTools()
    
    # Run the execute method asynchronously
    print("Running the execute method...")
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

    print(f"Linting completed successfully: {result['success']}")
    if result['success']:
        issues = result['result'].get('issues', [])
        total_issues = result['result'].get('total_issues', 0)
        print(f"Found {total_issues} issues in the code")
        
        # Print out issue summary by rule
        rule_breakdown = result['result'].get('rule_breakdown', {})
        print("\nIssue breakdown by rule:")
        for rule, count in rule_breakdown.items():
            print(f"- {rule}: {count}")
        
        # Print a few example issues
        if issues:
            print("\nExample issues (first 5):")
            for issue in issues[:5]:
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
