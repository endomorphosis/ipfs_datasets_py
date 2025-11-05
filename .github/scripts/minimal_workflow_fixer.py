#!/usr/bin/env python3
"""
Minimal Workflow Fixer - Makes surgical changes to workflow files

This script adds missing GH_TOKEN to workflow steps that use gh CLI
without reformatting the entire YAML file.
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).parent.parent.parent


def find_gh_cli_steps(workflow_content: str) -> List[Tuple[int, str]]:
    """
    Find steps that use gh CLI but don't have GH_TOKEN
    
    Returns:
        List of (line_number, step_name) tuples
    """
    lines = workflow_content.split('\n')
    issues = []
    
    in_step = False
    step_start_line = 0
    step_name = ""
    step_has_gh = False
    step_has_token = False
    step_indent = 0
    
    for i, line in enumerate(lines):
        # Check if this is a step start
        if re.match(r'^(\s*)- name:', line):
            # Process previous step if needed
            if in_step and step_has_gh and not step_has_token:
                issues.append((step_start_line, step_name))
            
            # Start new step
            in_step = True
            step_start_line = i
            step_name = line.split('name:', 1)[1].strip()
            step_has_gh = False
            step_has_token = False
            step_indent = len(line) - len(line.lstrip())
        
        elif in_step:
            # Check if we've moved to next step or section
            if line.strip() and not line.startswith(' ' * (step_indent + 2)):
                # Process step
                if step_has_gh and not step_has_token:
                    issues.append((step_start_line, step_name))
                in_step = False
            
            # Check for gh CLI usage
            if 'gh ' in line or 'github-cli' in line.lower():
                step_has_gh = True
            
            # Check for GH_TOKEN
            if 'GH_TOKEN:' in line or 'GITHUB_TOKEN' in line:
                step_has_token = True
    
    # Check final step
    if in_step and step_has_gh and not step_has_token:
        issues.append((step_start_line, step_name))
    
    return issues


def add_gh_token_to_step(workflow_content: str, step_line: int) -> str:
    """
    Add GH_TOKEN to a specific step
    
    Args:
        workflow_content: Original workflow content
        step_line: Line number where step starts
    
    Returns:
        Modified workflow content
    """
    lines = workflow_content.split('\n')
    
    # Find the step and determine its indentation
    step_indent = len(lines[step_line]) - len(lines[step_line].lstrip())
    
    # Find where to insert the env section
    # Look for either 'run:' or 'uses:' after the step name
    insert_line = step_line + 1
    has_env = False
    
    for i in range(step_line + 1, len(lines)):
        line = lines[i]
        
        # Stop if we reach next step
        if line.strip() and not line.startswith(' ' * (step_indent + 2)):
            break
        
        # Check if step already has env section
        if re.match(r'^\s+env:', line):
            has_env = True
            # Insert GH_TOKEN as first env variable
            env_indent = len(line) - len(line.lstrip())
            insert_line = i + 1
            break
        
        # Find run: or uses: line
        if re.match(r'^\s+(run|uses):', line):
            insert_line = i
            break
    
    # Insert GH_TOKEN
    indent = ' ' * (step_indent + 2)
    token_indent = ' ' * (step_indent + 4)
    
    if has_env:
        # Add to existing env section
        new_line = f"{token_indent}GH_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}"
        lines.insert(insert_line, new_line)
    else:
        # Create new env section
        new_lines = [
            f"{indent}env:",
            f"{token_indent}GH_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}"
        ]
        lines[insert_line:insert_line] = new_lines
    
    return '\n'.join(lines)


def fix_workflow_file(workflow_file: Path, dry_run: bool = False) -> int:
    """
    Fix a single workflow file
    
    Returns:
        Number of fixes made
    """
    print(f"\n📄 Checking: {workflow_file.name}")
    
    with open(workflow_file, 'r') as f:
        content = f.read()
    
    issues = find_gh_cli_steps(content)
    
    if not issues:
        print(f"   ✅ No issues found")
        return 0
    
    print(f"   📝 Found {len(issues)} step(s) needing GH_TOKEN:")
    for line_num, step_name in issues:
        print(f"      - Line {line_num}: {step_name}")
    
    if dry_run:
        print(f"   [DRY RUN] Would add GH_TOKEN to {len(issues)} step(s)")
        return len(issues)
    
    # Apply fixes
    modified_content = content
    # Process in reverse order to maintain line numbers
    for line_num, step_name in reversed(issues):
        modified_content = add_gh_token_to_step(modified_content, line_num)
    
    # Write back
    with open(workflow_file, 'w') as f:
        f.write(modified_content)
    
    print(f"   ✅ Added GH_TOKEN to {len(issues)} step(s)")
    return len(issues)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Minimally fix workflow files by adding GH_TOKEN'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without making changes'
    )
    parser.add_argument(
        '--workflow',
        type=str,
        help='Fix a specific workflow file (by name)'
    )
    
    args = parser.parse_args()
    
    workflows_dir = REPO_ROOT / '.github' / 'workflows'
    
    print("=" * 80)
    print("Minimal Workflow Fixer - Adding GH_TOKEN to gh CLI steps")
    print("=" * 80)
    
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")
    
    # Get workflow files
    if args.workflow:
        workflow_files = [workflows_dir / args.workflow]
    else:
        workflow_files = sorted(workflows_dir.glob("*.yml"))
        workflow_files = [f for f in workflow_files if not f.name.endswith('.disabled')]
    
    total_fixes = 0
    
    for workflow_file in workflow_files:
        if not workflow_file.exists():
            print(f"❌ File not found: {workflow_file}")
            continue
        
        fixes = fix_workflow_file(workflow_file, args.dry_run)
        total_fixes += fixes
    
    # Summary
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"Workflows processed: {len(workflow_files)}")
    print(f"Total fixes applied: {total_fixes}")
    print("=" * 80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
