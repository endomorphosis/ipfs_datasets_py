#!/usr/bin/env python3
"""
Bulk add timeout-minutes to GitHub Actions workflow jobs.

This script analyzes workflow files and adds appropriate timeout values
based on job characteristics and runner types.
"""

import yaml
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Timeout recommendations based on job characteristics
TIMEOUT_RULES = {
    # Self-hosted runners (more resources, complex operations)
    'self-hosted': {
        'default': 45,
        'gpu': 60,
        'docker': 90,
        'build': 60,
        'test': 45,
        'deploy': 30,
        'monitor': 30,
        'summary': 15,
    },
    # GitHub-hosted runners (standard operations)
    'github-hosted': {
        'default': 30,
        'build': 45,
        'test': 30,
        'deploy': 20,
        'lint': 15,
        'validate': 20,
        'summary': 10,
    }
}

def detect_job_type(job_name: str, job_config: Dict[str, Any]) -> str:
    """Detect the type of job based on name and configuration."""
    name_lower = job_name.lower()
    
    if 'gpu' in name_lower or 'cuda' in name_lower:
        return 'gpu'
    elif 'docker' in name_lower or 'container' in str(job_config.get('container', '')).lower():
        return 'docker'
    elif 'build' in name_lower or 'compile' in name_lower:
        return 'build'
    elif 'test' in name_lower or 'pytest' in name_lower or 'unittest' in name_lower:
        return 'test'
    elif 'deploy' in name_lower or 'publish' in name_lower or 'release' in name_lower:
        return 'deploy'
    elif 'lint' in name_lower or 'format' in name_lower or 'style' in name_lower:
        return 'lint'
    elif 'validate' in name_lower or 'check' in name_lower or 'verify' in name_lower:
        return 'validate'
    elif 'monitor' in name_lower or 'watch' in name_lower:
        return 'monitor'
    elif 'summary' in name_lower or 'report' in name_lower:
        return 'summary'
    else:
        return 'default'

def detect_runner_type(runs_on: Any) -> str:
    """Detect if using self-hosted or GitHub-hosted runners."""
    if isinstance(runs_on, list):
        if 'self-hosted' in runs_on:
            return 'self-hosted'
    elif isinstance(runs_on, str):
        if 'self-hosted' in runs_on:
            return 'self-hosted'
    return 'github-hosted'

def get_recommended_timeout(job_name: str, job_config: Dict[str, Any]) -> int:
    """Get recommended timeout based on job characteristics."""
    runner_type = detect_runner_type(job_config.get('runs-on', ''))
    job_type = detect_job_type(job_name, job_config)
    
    rules = TIMEOUT_RULES.get(runner_type, TIMEOUT_RULES['github-hosted'])
    timeout = rules.get(job_type, rules['default'])
    
    return timeout

def add_timeout_to_job(job_config: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Add timeout-minutes to job configuration, preserving order."""
    # Create new dict with timeout after runs-on
    new_config = {}
    
    for key, value in job_config.items():
        new_config[key] = value
        # Insert timeout after runs-on
        if key == 'runs-on' and 'timeout-minutes' not in job_config:
            new_config['timeout-minutes'] = timeout
    
    # If runs-on wasn't found but timeout is needed, add at beginning
    if 'timeout-minutes' not in new_config and 'timeout-minutes' not in job_config:
        new_config = {'timeout-minutes': timeout, **new_config}
    
    return new_config

def process_workflow(workflow_path: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Process a workflow file and add timeouts where missing.
    
    Returns:
        Tuple of (jobs_processed, jobs_updated)
    """
    try:
        with open(workflow_path, 'r') as f:
            content = f.read()
            workflow = yaml.safe_load(content)
        
        if not workflow or 'jobs' not in workflow:
            return 0, 0
        
        jobs_processed = 0
        jobs_updated = 0
        
        for job_name, job_config in workflow['jobs'].items():
            if not isinstance(job_config, dict):
                continue
            
            jobs_processed += 1
            
            # Skip if already has timeout
            if 'timeout-minutes' in job_config:
                continue
            
            # Get recommended timeout
            timeout = get_recommended_timeout(job_name, job_config)
            
            # Add timeout
            workflow['jobs'][job_name] = add_timeout_to_job(job_config, timeout)
            jobs_updated += 1
            
            print(f"  {workflow_path.name}: job '{job_name}' -> {timeout} minutes")
        
        # Write back if not dry run and changes were made
        if not dry_run and jobs_updated > 0:
            # Use PyYAML to write, maintaining structure
            with open(workflow_path, 'w') as f:
                yaml.dump(workflow, f, default_flow_style=False, sort_keys=False, width=120)
            print(f"  ✅ Updated {workflow_path.name}")
        
        return jobs_processed, jobs_updated
        
    except Exception as e:
        print(f"  ❌ Error processing {workflow_path.name}: {e}")
        return 0, 0

def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Add timeouts to GitHub Actions workflows')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')
    parser.add_argument('--workflows-dir', default='.github/workflows', help='Path to workflows directory')
    parser.add_argument('--pattern', default='*.yml', help='File pattern to match')
    args = parser.parse_args()
    
    workflows_dir = Path(args.workflows_dir)
    if not workflows_dir.exists():
        print(f"❌ Workflows directory not found: {workflows_dir}")
        sys.exit(1)
    
    print(f"{'🔍 DRY RUN: ' if args.dry_run else ''}Processing workflows in {workflows_dir}/")
    print()
    
    total_workflows = 0
    total_jobs_processed = 0
    total_jobs_updated = 0
    
    for workflow_path in sorted(workflows_dir.glob(args.pattern)):
        if workflow_path.is_file():
            total_workflows += 1
            jobs_processed, jobs_updated = process_workflow(workflow_path, args.dry_run)
            total_jobs_processed += jobs_processed
            total_jobs_updated += jobs_updated
    
    print()
    print("=" * 70)
    print(f"📊 Summary:")
    print(f"  Workflows processed: {total_workflows}")
    print(f"  Jobs processed: {total_jobs_processed}")
    print(f"  Jobs updated: {total_jobs_updated}")
    
    if args.dry_run:
        print()
        print("ℹ️  This was a dry run. Run without --dry-run to apply changes.")
    else:
        print()
        print("✅ Changes applied successfully!")
    
    return 0 if total_jobs_updated >= 0 else 1

if __name__ == '__main__':
    sys.exit(main())
