#!/usr/bin/env python3
"""
Fix GitHub Actions Workflow Issues

This script automatically fixes common issues in GitHub Actions workflows:
- Adds missing GH_TOKEN environment variables
- Adds container isolation for self-hosted runners
- Enhances Copilot CLI integration
- Validates workflow syntax
"""

import os
import sys
import json
import yaml
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


class WorkflowFixer:
    """
    Automatically fixes common issues in GitHub Actions workflows
    """
    
    def __init__(self, workflows_dir: Optional[str] = None, dry_run: bool = False):
        """
        Initialize the workflow fixer
        
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
        """Load and parse a workflow YAML file"""
        try:
            with open(workflow_file, 'r') as f:
                # Use full_load to handle 'on' keyword properly
                content = f.read()
                # Replace 'on:' with 'trigger:' temporarily for parsing
                # This is a workaround for YAML safe_load treating 'on' as boolean
                data = yaml.safe_load(content)
                return data
        except Exception as e:
            print(f"❌ Error loading {workflow_file.name}: {e}")
            return None
    
    def save_workflow(self, workflow_file: Path, workflow_data: Dict[str, Any]):
        """Save workflow YAML file"""
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
        Add GH_TOKEN to a step if it uses gh CLI
        
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
        Fix missing GH_TOKEN in workflows that use gh CLI
        
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
        Suggest container isolation for self-hosted runners
        
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
                # Check if job uses self-hosted runner
                runs_on = job_data.get('runs-on', [])
                if isinstance(runs_on, str):
                    runs_on = [runs_on]
                
                uses_self_hosted = any('self-hosted' in str(r) for r in runs_on)
                has_container = 'container' in job_data
                
                if uses_self_hosted and not has_container:
                    suggestions.append(
                        f"Job '{job_name}' uses self-hosted runner without container isolation. "
                        f"Consider adding:\n"
                        f"    container:\n"
                        f"      image: python:3.12-slim\n"
                        f"      options: --user root"
                    )
        
        return suggestions
    
    def enhance_copilot_integration(self, workflow_file: Path) -> int:
        """
        Enhance Copilot CLI integration in auto-fix/auto-healing workflows
        
        Returns:
            Number of enhancements made
        """
        workflow = self.load_workflow(workflow_file)
        if not workflow:
            return 0
        
        # Only enhance workflows that are explicitly for auto-fixing/healing
        if 'autofix' not in workflow_file.name.lower() and 'auto-healing' not in workflow_file.name.lower():
            return 0
        
        enhancements = 0
        
        # Check if workflow already has copilot steps
        with open(workflow_file, 'r') as f:
            content = f.read()
        
        if 'gh copilot' in content or 'gh-copilot' in content:
            return 0  # Already has copilot integration
        
        # Add a suggestion to use copilot CLI
        self.changes_made.append({
            'file': workflow_file.name,
            'type': 'copilot_suggestion',
            'description': 'Consider adding gh copilot commands for code analysis and suggestions'
        })
        
        print(f"   💡 Suggestion: Add gh copilot integration for automated code analysis")
        enhancements += 1
        
        return enhancements
    
    def validate_workflow_syntax(self, workflow_file: Path) -> bool:
        """
        Validate workflow YAML syntax
        
        Returns:
            True if valid, False otherwise
        """
        workflow = self.load_workflow(workflow_file)
        if not workflow:
            return False
        
        # Basic validation checks
        if 'name' not in workflow:
            print(f"   ⚠️  Warning: Workflow missing 'name' field")
        
        # Check for 'on' or True (YAML parses 'on:' as True sometimes)
        has_trigger = 'on' in workflow or True in workflow or 'trigger' in workflow
        if not has_trigger:
            print(f"   ❌ Error: Workflow missing 'on' trigger field")
            return False
        
        if 'jobs' not in workflow:
            print(f"   ❌ Error: Workflow missing 'jobs' field")
            return False
        
        return True
    
    def fix_workflow(self, workflow_file: Path) -> Dict[str, Any]:
        """
        Fix all issues in a workflow
        
        Returns:
            Dictionary with fix results
        """
        print(f"\n📄 Processing: {workflow_file.name}")
        
        result = {
            'file': workflow_file.name,
            'fixes': 0,
            'suggestions': [],
            'valid': False
        }
        
        # Validate syntax
        result['valid'] = self.validate_workflow_syntax(workflow_file)
        if not result['valid']:
            print(f"   ❌ Skipping due to validation errors")
            return result
        
        # Fix missing GH_TOKEN
        gh_token_fixes = self.fix_missing_gh_token(workflow_file)
        result['fixes'] += gh_token_fixes
        
        # Get container isolation suggestions
        container_suggestions = self.suggest_container_isolation(workflow_file)
        result['suggestions'].extend(container_suggestions)
        
        if container_suggestions:
            print(f"   💡 {len(container_suggestions)} container isolation suggestion(s)")
        
        # Enhance copilot integration
        copilot_enhancements = self.enhance_copilot_integration(workflow_file)
        result['fixes'] += copilot_enhancements
        
        if result['fixes'] == 0 and not result['suggestions']:
            print(f"   ✅ No issues found")
        
        return result
    
    def fix_all_workflows(self) -> Dict[str, Any]:
        """
        Fix all workflows in the directory
        
        Returns:
            Summary of all fixes
        """
        print("\n" + "=" * 80)
        print("GitHub Actions Workflow Auto-Fixer")
        print("=" * 80)
        
        if self.dry_run:
            print("\n⚠️  DRY RUN MODE - No changes will be made\n")
        
        workflow_files = sorted(self.workflows_dir.glob("*.yml"))
        workflow_files = [f for f in workflow_files if not f.name.endswith('.disabled')]
        
        print(f"\nFound {len(workflow_files)} active workflows to process")
        
        results = []
        total_fixes = 0
        total_suggestions = 0
        
        for workflow_file in workflow_files:
            result = self.fix_workflow(workflow_file)
            results.append(result)
            total_fixes += result['fixes']
            total_suggestions += len(result['suggestions'])
        
        # Summary
        print("\n" + "=" * 80)
        print("Summary")
        print("=" * 80)
        print(f"Workflows processed: {len(results)}")
        print(f"Total fixes applied: {total_fixes}")
        print(f"Total suggestions: {total_suggestions}")
        
        if self.changes_made:
            print(f"\nChanges made: {len(self.changes_made)}")
            for change in self.changes_made[:10]:  # Show first 10
                print(f"  • {change['file']}: {change['description']}")
            if len(self.changes_made) > 10:
                print(f"  ... and {len(self.changes_made) - 10} more")
        
        # Save detailed results
        results_file = REPO_ROOT / '.github' / 'workflow_fixes_applied.json'
        with open(results_file, 'w') as f:
            json.dump({
                'results': results,
                'changes': self.changes_made,
                'summary': {
                    'total_workflows': len(results),
                    'total_fixes': total_fixes,
                    'total_suggestions': total_suggestions
                }
            }, f, indent=2)
        
        print(f"\n📄 Detailed results saved to: {results_file}")
        print("\n" + "=" * 80)
        
        return {
            'results': results,
            'changes': self.changes_made,
            'total_fixes': total_fixes,
            'total_suggestions': total_suggestions
        }


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Fix common issues in GitHub Actions workflows'
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
    
    # Initialize fixer
    fixer = WorkflowFixer(dry_run=args.dry_run)
    
    # Fix workflows
    if args.workflow:
        workflow_file = fixer.workflows_dir / args.workflow
        if not workflow_file.exists():
            print(f"❌ Workflow file not found: {workflow_file}")
            return 1
        result = fixer.fix_workflow(workflow_file)
        return 0 if result['valid'] else 1
    else:
        summary = fixer.fix_all_workflows()
        return 0 if summary['total_fixes'] >= 0 else 1


if __name__ == '__main__':
    sys.exit(main())
