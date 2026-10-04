#!/usr/bin/env python3
"""
Update the workflow list in copilot-agent-autofix.yml automatically.

This script scans for workflows and updates the workflow_run trigger
in the auto-healing workflow file.
"""

import os
import re
import sys
import subprocess
from pathlib import Path
from typing import List


def get_workflow_list() -> List[str]:
    """Get the list of workflows using the generator script."""
    script_path = Path(__file__).parent / "generate_workflow_list.py"
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path), "list"],
            capture_output=True,
            text=True,
            check=True
        )
        return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"Error running generate_workflow_list.py: {e}", file=sys.stderr)
        sys.exit(1)


def generate_workflows_yaml(workflow_names: List[str]) -> str:
    """Generate the YAML workflows section."""
    lines = ["    workflows:"]
    for name in workflow_names:
        # Properly escape workflow names
        escaped_name = name.replace('"', '\\"')
        lines.append(f'      - "{escaped_name}"')
    return '\n'.join(lines)


def update_autofix_workflow(workflow_file: Path, workflow_names: List[str]) -> bool:
    """Update the copilot-agent-autofix.yml file with the new workflow list."""
    
    if not workflow_file.exists():
        print(f"Error: {workflow_file} not found!", file=sys.stderr)
        return False
    
    # Read the file
    with open(workflow_file, 'r') as f:
        content = f.read()
    
    # Generate the new workflows section
    new_workflows_section = generate_workflows_yaml(workflow_names)
    
    # Pattern to match the workflows section in the workflow_run trigger
    # We need to match from "workflows:" to the line before "types:"
    pattern = r'(  workflow_run:\n(?:.*\n)*?)    workflows:(?:\n.*)*?(\n    types:)'
    
    # Create the replacement with comment
    comment = "    # NOTE: GitHub Actions does NOT support wildcards like [\"*\"] in workflow_run triggers.\n"
    comment += "    # This list must be explicitly maintained. To update this list automatically, run:\n"
    comment += "    # python3 .github/scripts/generate_workflow_list.py yaml\n"
    
    replacement = r'\1' + comment + new_workflows_section + r'\2'
    
    # Perform the replacement
    new_content, count = re.subn(pattern, replacement, content, count=1)
    
    if count == 0:
        print("Warning: Could not find workflow_run section to update!", file=sys.stderr)
        print("Trying alternative pattern...", file=sys.stderr)
        
        # Try simpler pattern
        pattern2 = r'(    workflows:)(?:\n.*)*?(\n    types:)'
        replacement2 = '\n' + new_workflows_section + r'\2'
        new_content, count = re.subn(pattern2, replacement2, content, count=1)
        
        if count == 0:
            print("Error: Could not update workflow file!", file=sys.stderr)
            return False
    
    # Write back
    with open(workflow_file, 'w') as f:
        f.write(new_content)
    
    print(f"✅ Successfully updated {workflow_file}")
    print(f"📝 Added {len(workflow_names)} workflows to the trigger list")
    
    return True


def main():
    # Get paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    workflow_file = repo_root / ".github" / "workflows" / "copilot-agent-autofix.yml"
    
    print("🔍 Scanning for workflows...")
    workflow_names = get_workflow_list()
    
    if not workflow_names:
        print("Error: No workflows found!", file=sys.stderr)
        return 1
    
    print(f"📋 Found {len(workflow_names)} workflows:")
    for name in workflow_names:
        print(f"  - {name}")
    
    print(f"\n🔧 Updating {workflow_file.name}...")
    if update_autofix_workflow(workflow_file, workflow_names):
        print("\n✅ Update complete!")
        print("\n💡 Tip: Run this script whenever you add or rename workflows.")
        return 0
    else:
        print("\n❌ Update failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
