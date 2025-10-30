#!/usr/bin/env python3
"""
Generate a list of workflow names for the auto-healing workflow trigger.

This script scans the .github/workflows directory and extracts workflow names
to be used in the workflow_run trigger configuration.
"""

import os
import re
import sys
import yaml
from pathlib import Path
from typing import List


def extract_workflow_name(workflow_file: Path) -> str:
    """Extract the workflow name from a YAML file."""
    try:
        with open(workflow_file, 'r') as f:
            content = f.read()
            # Try to parse as YAML
            try:
                data = yaml.safe_load(content)
                if data and isinstance(data, dict) and 'name' in data:
                    return data['name']
            except yaml.YAMLError:
                pass
            
            # Fallback: regex extraction for simple cases
            match = re.search(r'^name:\s*["\']?([^"\'\n]+)["\']?', content, re.MULTILINE)
            if match:
                return match.group(1).strip()
    except Exception as e:
        print(f"Warning: Could not parse {workflow_file}: {e}", file=sys.stderr)
    
    return None


def get_workflow_names(workflows_dir: Path, exclude_patterns: List[str]) -> List[str]:
    """Get all workflow names from the workflows directory."""
    workflow_names = []
    
    for workflow_file in workflows_dir.glob("*.yml"):
        # Skip excluded workflows
        filename = workflow_file.name
        if any(pattern in filename for pattern in exclude_patterns):
            continue
        
        name = extract_workflow_name(workflow_file)
        if name:
            workflow_names.append(name)
    
    return sorted(set(workflow_names))


def generate_yaml_list(names: List[str], indent: int = 6) -> str:
    """Generate YAML list format for workflow names."""
    if not names:
        return ""
    
    lines = []
    for name in names:
        # Properly escape workflow names with quotes
        escaped_name = name.replace('"', '\\"')
        lines.append(f'{" " * indent}- "{escaped_name}"')
    
    return '\n'.join(lines)


def main():
    # Get repository root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    workflows_dir = repo_root / ".github" / "workflows"
    
    # Workflows to exclude from the trigger list
    exclude_patterns = [
        'copilot-agent-autofix.yml',
        'workflow-auto-fix.yml',
        'workflow-auto-fix-config.yml',
    ]
    
    # Get workflow names
    workflow_names = get_workflow_names(workflows_dir, exclude_patterns)
    
    if not workflow_names:
        print("Error: No workflows found!", file=sys.stderr)
        sys.exit(1)
    
    # Output in different formats based on command line argument
    output_format = sys.argv[1] if len(sys.argv) > 1 else "yaml"
    
    if output_format == "yaml":
        print(generate_yaml_list(workflow_names))
    elif output_format == "json":
        import json
        print(json.dumps(workflow_names, indent=2))
    elif output_format == "count":
        print(len(workflow_names))
    else:
        # Plain list
        for name in workflow_names:
            print(name)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
