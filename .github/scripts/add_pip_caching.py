#!/usr/bin/env python3
"""
Add pip caching to GitHub Actions Python workflows.

This script adds actions/cache for pip dependencies to workflows
that install Python packages but don't have caching configured.
"""

import yaml
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

def has_python_setup(steps: List[Dict[str, Any]]) -> bool:
    """Check if workflow uses Python setup."""
    for step in steps:
        if isinstance(step, dict):
            uses = step.get('uses', '')
            if 'actions/setup-python' in uses:
                return True
            # Check run commands for pip
            run = step.get('run', '')
            if isinstance(run, str) and ('pip install' in run or 'pip3 install' in run):
                return True
    return False

def has_caching(steps: List[Dict[str, Any]]) -> bool:
    """Check if workflow already has caching configured."""
    for step in steps:
        if isinstance(step, dict):
            uses = step.get('uses', '')
            if 'actions/cache' in uses or 'actions/setup-python' in uses:
                # Check if setup-python has cache parameter
                with_dict = step.get('with', {})
                if isinstance(with_dict, dict) and with_dict.get('cache'):
                    return True
                if 'actions/cache' in uses:
                    return True
    return False

def find_setup_python_step(steps: List[Dict[str, Any]]) -> Optional[int]:
    """Find the index of the setup-python step."""
    for i, step in enumerate(steps):
        if isinstance(step, dict):
            uses = step.get('uses', '')
            if 'actions/setup-python' in uses:
                return i
    return None

def add_cache_to_setup_python(step: Dict[str, Any]) -> Dict[str, Any]:
    """Add cache parameter to setup-python step."""
    if 'with' not in step:
        step['with'] = {}
    
    # Only add if not already present
    if isinstance(step['with'], dict) and 'cache' not in step['with']:
        step['with']['cache'] = 'pip'
    
    return step

def process_workflow(workflow_path: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Process a workflow file and add pip caching where appropriate.
    
    Returns:
        Tuple of (jobs_checked, jobs_updated)
    """
    try:
        with open(workflow_path, 'r') as f:
            content = f.read()
            workflow = yaml.safe_load(content)
        
        if not workflow or 'jobs' not in workflow:
            return 0, 0
        
        jobs_checked = 0
        jobs_updated = 0
        
        for job_name, job_config in workflow['jobs'].items():
            if not isinstance(job_config, dict):
                continue
            
            steps = job_config.get('steps', [])
            if not isinstance(steps, list):
                continue
            
            jobs_checked += 1
            
            # Skip if no Python setup or already has caching
            if not has_python_setup(steps):
                continue
            
            if has_caching(steps):
                continue
            
            # Find setup-python step and add cache
            setup_idx = find_setup_python_step(steps)
            if setup_idx is not None:
                workflow['jobs'][job_name]['steps'][setup_idx] = add_cache_to_setup_python(
                    workflow['jobs'][job_name]['steps'][setup_idx]
                )
                jobs_updated += 1
                print(f"  {workflow_path.name}: job '{job_name}' -> added pip cache")
        
        # Write back if not dry run and changes were made
        if not dry_run and jobs_updated > 0:
            with open(workflow_path, 'w') as f:
                yaml.dump(workflow, f, default_flow_style=False, sort_keys=False, width=120)
            print(f"  ✅ Updated {workflow_path.name}")
        
        return jobs_checked, jobs_updated
        
    except Exception as e:
        print(f"  ⚠️  Skipping {workflow_path.name}: {e}")
        return 0, 0

def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Add pip caching to GitHub Actions workflows')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')
    parser.add_argument('--workflows-dir', default='.github/workflows', help='Path to workflows directory')
    parser.add_argument('--pattern', default='*.yml', help='File pattern to match')
    args = parser.parse_args()
    
    workflows_dir = Path(args.workflows_dir)
    if not workflows_dir.exists():
        print(f"❌ Workflows directory not found: {workflows_dir}")
        sys.exit(1)
    
    print(f"{'🔍 DRY RUN: ' if args.dry_run else ''}Adding pip caching to Python workflows...")
    print()
    
    total_workflows = 0
    total_jobs_checked = 0
    total_jobs_updated = 0
    
    for workflow_path in sorted(workflows_dir.glob(args.pattern)):
        if workflow_path.is_file():
            total_workflows += 1
            jobs_checked, jobs_updated = process_workflow(workflow_path, args.dry_run)
            total_jobs_checked += jobs_checked
            total_jobs_updated += jobs_updated
    
    print()
    print("=" * 70)
    print(f"📊 Summary:")
    print(f"  Workflows processed: {total_workflows}")
    print(f"  Jobs checked: {total_jobs_checked}")
    print(f"  Jobs updated: {total_jobs_updated}")
    
    if args.dry_run:
        print()
        print("ℹ️  This was a dry run. Run without --dry-run to apply changes.")
    else:
        print()
        print("✅ Changes applied successfully!")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
