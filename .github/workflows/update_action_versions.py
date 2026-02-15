#!/usr/bin/env python3
"""
GitHub Actions Version Update Script
Automates updating action versions across all workflow files.

Usage:
    python update_action_versions.py [--dry-run] [--verbose]
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict

# Define updates to apply (old_pattern, new_value, description)
UPDATES = [
    # Actions updates
    (r'actions/checkout@v4', 'actions/checkout@v5', 'actions/checkout v4→v5'),
    (r'actions/setup-python@v4', 'actions/setup-python@v5', 'actions/setup-python v4→v5'),
    (r'actions/upload-artifact@v3', 'actions/upload-artifact@v4', 'actions/upload-artifact v3→v4'),
    (r'codecov/codecov-action@v3', 'codecov/codecov-action@v4', 'codecov/codecov-action v3→v4'),
    
    # Docker actions updates  
    (r'docker/login-action@v2', 'docker/login-action@v3', 'docker/login-action v2→v3'),
    (r'docker/build-push-action@v4', 'docker/build-push-action@v5', 'docker/build-push-action v4→v5'),
    (r'docker/metadata-action@v4', 'docker/metadata-action@v5', 'docker/metadata-action v4→v5'),
]


def update_file(filepath: Path, dry_run: bool = False, verbose: bool = False) -> Tuple[bool, List[str]]:
    """
    Update action versions in a single workflow file.
    
    Returns:
        (changed, changes_made): Boolean if file was changed, list of change descriptions
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            original_content = f.read()
    except Exception as e:
        print(f"❌ Error reading {filepath}: {e}")
        return False, []
    
    content = original_content
    changes_made = []
    
    # Apply each update pattern
    for old_pattern, new_value, description in UPDATES:
        if re.search(old_pattern, content):
            new_content = re.sub(old_pattern, new_value, content)
            if new_content != content:
                count = content.count(old_pattern)
                changes_made.append(f"{description} ({count}x)")
                content = new_content
    
    # Check if file was actually changed
    if content == original_content:
        if verbose:
            print(f"  ⏭️  {filepath.name} - No changes needed")
        return False, []
    
    # Write updated content (unless dry run)
    if not dry_run:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  ✅ {filepath.name}")
            for change in changes_made:
                print(f"      • {change}")
        except Exception as e:
            print(f"  ❌ Error writing {filepath}: {e}")
            return False, []
    else:
        print(f"  🔍 {filepath.name} (DRY RUN)")
        for change in changes_made:
            print(f"      • {change}")
    
    return True, changes_made


def main():
    """Main execution function."""
    # Parse command line arguments
    dry_run = '--dry-run' in sys.argv
    verbose = '--verbose' in sys.argv
    
    # Find workflows directory
    script_dir = Path(__file__).parent
    workflows_dir = script_dir
    
    if not workflows_dir.exists():
        print(f"❌ Workflows directory not found: {workflows_dir}")
        sys.exit(1)
    
    print("=" * 70)
    print("GitHub Actions Version Update Script")
    print("=" * 70)
    if dry_run:
        print("🔍 DRY RUN MODE - No files will be modified")
    print()
    
    # Find all workflow files
    workflow_files = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    workflow_files = [f for f in workflow_files if f.is_file()]
    
    # Skip template files
    workflow_files = [f for f in workflow_files if 'template' not in f.stem.lower()]
    
    print(f"📁 Found {len(workflow_files)} workflow files")
    print()
    
    # Update each file
    files_changed = 0
    total_changes: Dict[str, int] = {}
    
    for filepath in sorted(workflow_files):
        changed, changes = update_file(filepath, dry_run=dry_run, verbose=verbose)
        if changed:
            files_changed += 1
            for change in changes:
                # Extract just the update description (before count)
                change_key = change.split(' (')[0] if ' (' in change else change
                total_changes[change_key] = total_changes.get(change_key, 0) + 1
    
    # Print summary
    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Files processed: {len(workflow_files)}")
    print(f"Files changed: {files_changed}")
    print()
    
    if total_changes:
        print("Updates applied:")
        for change, count in sorted(total_changes.items()):
            print(f"  • {change}: {count} files")
    else:
        print("✅ All files already up to date!")
    
    print()
    if dry_run:
        print("🔍 This was a DRY RUN - rerun without --dry-run to apply changes")
    else:
        print("✅ Updates complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
