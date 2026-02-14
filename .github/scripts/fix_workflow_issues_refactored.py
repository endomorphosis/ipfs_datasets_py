#!/usr/bin/env python3
"""
Fix GitHub Actions Workflow Issues - Refactored

This script automatically fixes common issues in GitHub Actions workflows.
Renamed from WorkflowFixer to WorkflowIssueApplier to avoid name collision
with utils.workflows.WorkflowFixer.

Core workflow analysis delegated to utils.workflows modules where applicable.

Usage:
    python fix_workflow_issues_refactored.py [--dry-run] [--workflows-dir DIR]
"""

import os
import sys
import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


class WorkflowIssueApplier:
    """
    Applies fixes to GitHub Actions workflows.
    
    Renamed from WorkflowFixer to avoid collision with utils.workflows.WorkflowFixer.
    Handles YAML manipulation and specific issue fixes.
    """
    
    def __init__(self, workflows_dir: Optional[str] = None, dry_run: bool = False):
        """
        Initialize the workflow issue applier.
        
        Args:
            workflows_dir: Path to workflows directory
            dry_run: If True, only show what would be changed without making changes
        """
        if workflows_dir is None:
            workflows_dir = REPO_ROOT / '.github' / 'workflows'
        self.workflows_dir = Path(workflows_dir)
        self.dry_run = dry_run
        self.changes_made = []
    
    def load_workflow(self, workflow_file: Path) -> Optional[Dict[str, Any]]:
        """Load and parse a workflow YAML file."""
        try:
            with open(workflow_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"❌ Error loading {workflow_file.name}: {e}")
            return None
    
    def save_workflow(self, workflow_file: Path, workflow_data: Dict[str, Any]):
        """Save workflow YAML file."""
        if self.dry_run:
            print(f"   [DRY RUN] Would save changes to {workflow_file.name}")
            return
        
        try:
            with open(workflow_file, 'w') as f:
                yaml.dump(workflow_data, f, default_flow_style=False, sort_keys=False)
            print(f"   ✅ Saved changes to {workflow_file.name}")
        except Exception as e:
            print(f"   ❌ Error saving {workflow_file.name}: {e}")
    
    def add_gh_token_to_step(self, step: Dict[str, Any]) -> bool:
        """
        Add GH_TOKEN to a step if it uses gh CLI.
        
        Returns:
            True if changes were made
        """
        if 'run' not in step:
            return False
        
        run_content = step['run']
        if not isinstance(run_content, str):
            return False
        
        # Check if step uses gh CLI
        if 'gh ' not in run_content and 'github-cli' not in run_content.lower():
            return False
        
        # Check if GH_TOKEN is already set
        if 'env' in step:
            if 'GH_TOKEN' in step['env'] or 'GITHUB_TOKEN' in step['env']:
                return False
        
        # Add GH_TOKEN to step environment
        if 'env' not in step:
            step['env'] = {}
        
        step['env']['GH_TOKEN'] = '${{ secrets.GITHUB_TOKEN }}'
        return True
    
    def fix_missing_gh_token(self, workflow_file: Path) -> int:
        """
        Fix missing GH_TOKEN in workflows that use gh CLI.
        
        Returns:
            Number of fixes made
        """
        workflow = self.load_workflow(workflow_file)
        if not workflow:
            return 0
        
        fixes = 0
        
        # Check all jobs
        if 'jobs' in workflow:
            for job_name, job_data in workflow['jobs'].items():
                if 'steps' in job_data:
                    for step in job_data['steps']:
                        if self.add_gh_token_to_step(step):
                            fixes += 1
                            self.changes_made.append({
                                'file': workflow_file.name,
                                'type': 'add_gh_token',
                                'job': job_name,
                                'description': 'Added GH_TOKEN to step using gh CLI'
                            })
        
        if fixes > 0:
            print(f"   📝 Added GH_TOKEN to {fixes} step(s)")
            self.save_workflow(workflow_file, workflow)
        
        return fixes
    
    def suggest_container_isolation(self, workflow_file: Path) -> List[str]:
        """
        Suggest container isolation for self-hosted runners.
        
        Returns:
            List of suggestions
        """
        workflow = self.load_workflow(workflow_file)
        if not workflow:
            return []
        
        suggestions = []
        
        # Read the raw file to check for self-hosted
        with open(workflow_file, 'r') as f:
            content = f.read()
        
        if 'self-hosted' not in content:
            return []
        
        # Check all jobs
        if 'jobs' in workflow:
            for job_name, job_data in workflow['jobs'].items():
                runs_on = job_data.get('runs-on', [])
                if isinstance(runs_on, str):
                    runs_on = [runs_on]
                
                uses_self_hosted = any('self-hosted' in str(r) for r in runs_on)
                has_container = 'container' in job_data
                
                if uses_self_hosted and not has_container:
                    suggestions.append(
                        f"Job '{job_name}' uses self-hosted runner without container isolation. "
                        f"Consider adding container configuration."
                    )
        
        return suggestions
    
    def process_all_workflows(self) -> Dict[str, Any]:
        """Process all workflows and apply fixes."""
        print("🔧 GitHub Actions Workflow Issue Fixer\n")
        print("=" * 60)
        
        if self.dry_run:
            print("🔍 DRY RUN MODE - No changes will be made\n")
        
        workflow_files = sorted(self.workflows_dir.glob('*.yml'))
        
        total_fixes = 0
        all_suggestions = []
        
        for workflow_file in workflow_files:
            print(f"\n📄 Checking {workflow_file.name}...")
            
            # Fix missing GH_TOKEN
            fixes = self.fix_missing_gh_token(workflow_file)
            total_fixes += fixes
            
            # Get suggestions
            suggestions = self.suggest_container_isolation(workflow_file)
            if suggestions:
                all_suggestions.extend([(workflow_file.name, s) for s in suggestions])
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Summary:")
        print(f"   Workflows checked: {len(workflow_files)}")
        print(f"   Fixes applied: {total_fixes}")
        print(f"   Suggestions: {len(all_suggestions)}")
        
        if all_suggestions:
            print("\n💡 Suggestions:")
            for workflow_name, suggestion in all_suggestions:
                print(f"\n   {workflow_name}:")
                print(f"      {suggestion}")
        
        if self.changes_made:
            print("\n📝 Changes Made:")
            for change in self.changes_made:
                print(f"   • {change['file']}: {change['description']}")
        
        return {
            'workflows_checked': len(workflow_files),
            'fixes_applied': total_fixes,
            'suggestions': len(all_suggestions),
            'changes': self.changes_made
        }


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Fix common issues in GitHub Actions workflows'
    )
    parser.add_argument(
        '--workflows-dir',
        type=str,
        help='Path to workflows directory (default: .github/workflows)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without making changes'
    )
    
    args = parser.parse_args()
    
    # Initialize applier
    applier = WorkflowIssueApplier(
        workflows_dir=args.workflows_dir,
        dry_run=args.dry_run
    )
    
    # Process workflows
    results = applier.process_all_workflows()
    
    # Exit code based on results
    if results['fixes_applied'] > 0:
        print(f"\n✅ Applied {results['fixes_applied']} fix(es)")
        return 0
    else:
        print("\n✨ No fixes needed - all workflows look good!")
        return 0


if __name__ == '__main__':
    sys.exit(main())
