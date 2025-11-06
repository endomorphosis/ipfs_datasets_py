#!/usr/bin/env python3
"""
Deduplicate GitHub issues by workflow name.
Keeps the most recent issue for each workflow failure type and closes older duplicates.
"""

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime


def run_command(cmd):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}", file=sys.stderr)
        print(f"STDERR: {e.stderr}", file=sys.stderr)
        return None


def normalize_title(title):
    """Normalize issue title by removing run ID."""
    import re
    # Remove run ID: "Run 19146999120)" -> "Run XXX)"
    normalized = re.sub(r'Run \d+\)', 'Run XXX)', title)
    return normalized


def get_open_issues():
    """Get all open issues from the repository."""
    cmd = 'gh issue list --repo endomorphosis/ipfs_datasets_py --state open --limit 200 --json number,title,createdAt'
    result = run_command(cmd)
    if not result:
        return []
    
    try:
        issues = json.loads(result)
        return issues
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        return []


def group_duplicates(issues):
    """Group issues by normalized title."""
    groups = defaultdict(list)
    
    for issue in issues:
        normalized = normalize_title(issue['title'])
        groups[normalized].append(issue)
    
    return groups


def close_duplicate_issues(dry_run=False):
    """Close duplicate issues, keeping the most recent one."""
    print("Fetching open issues...")
    issues = get_open_issues()
    print(f"Found {len(issues)} open issues\n")
    
    groups = group_duplicates(issues)
    
    # Find groups with duplicates
    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Found {len(duplicate_groups)} workflow types with duplicates\n")
    
    total_to_close = 0
    for normalized_title, issue_list in sorted(duplicate_groups.items()):
        # Sort by creation date (newest first)
        sorted_issues = sorted(
            issue_list,
            key=lambda x: datetime.fromisoformat(x['createdAt'].replace('Z', '+00:00')),
            reverse=True
        )
        
        # Keep the newest, close the rest
        keep_issue = sorted_issues[0]
        to_close = sorted_issues[1:]
        
        print(f"\n{'='*80}")
        print(f"Workflow: {normalized_title}")
        print(f"  Keeping:  #{keep_issue['number']} (created {keep_issue['createdAt']})")
        print(f"  Closing {len(to_close)} duplicates:")
        
        for issue in to_close:
            print(f"    - #{issue['number']} (created {issue['createdAt']})")
            total_to_close += 1
            
            if not dry_run:
                comment = (
                    f"Closing duplicate issue. "
                    f"The most recent issue for this workflow is #{keep_issue['number']}"
                )
                cmd = f'gh issue close {issue["number"]} --repo endomorphosis/ipfs_datasets_py --comment "{comment}"'
                result = run_command(cmd)
                if result is not None:
                    print(f"      ✓ Closed #{issue['number']}")
                else:
                    print(f"      ✗ Failed to close #{issue['number']}")
    
    print(f"\n{'='*80}")
    print(f"\nSummary:")
    print(f"  - Total issues analyzed: {len(issues)}")
    print(f"  - Workflow types with duplicates: {len(duplicate_groups)}")
    print(f"  - Total duplicates to close: {total_to_close}")
    
    if dry_run:
        print(f"\n⚠️  DRY RUN - No issues were closed. Run with --execute to close issues.")
    else:
        print(f"\n✓ Closed {total_to_close} duplicate issues")


if __name__ == "__main__":
    dry_run = "--execute" not in sys.argv
    
    if dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No changes will be made")
        print("Run with --execute to actually close duplicate issues")
        print("=" * 80 + "\n")
    
    close_duplicate_issues(dry_run=dry_run)
