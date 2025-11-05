#!/usr/bin/env python3
"""
GitHub Actions Workflow Validator

This script validates GitHub Actions workflows for common issues including:
- Missing GH_TOKEN environment variables
- Incorrect Copilot invocation
- Missing permissions
- Self-hosted runner issues
- Script dependencies
"""

import argparse
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple

class WorkflowValidator:
    """Validates GitHub Actions workflows for common issues."""
    
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = Path(workflows_dir)
        self.issues: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.info: List[Dict[str, Any]] = []
    
    def validate_all(self) -> Tuple[int, int, int]:
        """
        Validate all workflows in the directory.
        
        Returns:
            Tuple of (errors, warnings, info)
        """
        print(f"🔍 Validating workflows in {self.workflows_dir}")
        print("-" * 80)
        
        workflow_files = list(self.workflows_dir.glob('*.yml'))
        workflow_files = [f for f in workflow_files if '.disabled' not in str(f)]
        
        print(f"Found {len(workflow_files)} active workflow files\n")
        
        for workflow_file in sorted(workflow_files):
            print(f"📄 Validating {workflow_file.name}...")
            self.validate_workflow(workflow_file)
            print()
        
        return len(self.issues), len(self.warnings), len(self.info)
    
    def validate_workflow(self, workflow_file: Path):
        """Validate a single workflow file."""
        try:
            with open(workflow_file) as f:
                workflow = yaml.safe_load(f)
            
            if not workflow:
                self.add_issue(workflow_file.name, "Empty workflow file")
                return
            
            workflow_name = workflow_file.name
            
            # Validate structure
            if 'jobs' not in workflow:
                self.add_issue(workflow_name, "No jobs defined")
                return
            
            # Validate each job
            for job_name, job_config in workflow['jobs'].items():
                self.validate_job(workflow_name, job_name, job_config)
            
            # Check for Copilot workflows
            if self.uses_copilot(workflow):
                self.validate_copilot_workflow(workflow_name, workflow)
            
            # Check permissions
            self.validate_permissions(workflow_name, workflow)
            
        except yaml.YAMLError as e:
            self.add_issue(workflow_file.name, f"YAML parse error: {e}")
        except Exception as e:
            self.add_issue(workflow_file.name, f"Validation error: {e}")
    
    def validate_job(self, workflow_name: str, job_name: str, job_config: Dict[str, Any]):
        """Validate a workflow job."""
        # Check for self-hosted runners
        runs_on = job_config.get('runs-on', [])
        if isinstance(runs_on, str):
            runs_on = [runs_on]
        
        uses_self_hosted = any('self-hosted' in str(r) for r in runs_on)
        uses_container = 'container' in job_config
        
        if uses_self_hosted and not uses_container:
            self.add_warning(
                workflow_name,
                f"Job '{job_name}' uses self-hosted runner without container isolation",
                "Add 'container:' configuration for better isolation"
            )
        
        # Validate steps
        if 'steps' not in job_config:
            return
        
        for i, step in enumerate(job_config['steps']):
            self.validate_step(workflow_name, job_name, i, step, job_config)
    
    def validate_step(
        self,
        workflow_name: str,
        job_name: str,
        step_index: int,
        step: Dict[str, Any],
        job_config: Dict[str, Any]
    ):
        """Validate a workflow step."""
        step_name = step.get('name', f'Step {step_index}')
        
        # Check if step uses gh CLI
        if 'run' in step:
            run_cmd = step['run']
            
            if 'gh ' in run_cmd or run_cmd.strip().startswith('gh'):
                # Check if GH_TOKEN is set
                has_token = False
                
                # Check step env
                if 'env' in step and 'GH_TOKEN' in step['env']:
                    has_token = True
                
                # Check job env
                if 'env' in job_config and 'GH_TOKEN' in job_config['env']:
                    has_token = True
                
                if not has_token:
                    self.add_issue(
                        workflow_name,
                        f"Step '{step_name}' in job '{job_name}' uses 'gh' without GH_TOKEN",
                        "Add: env:\\n  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}"
                    )
            
            # Check for @copilot mentions
            if '@copilot' in run_cmd or '@github-copilot' in run_cmd:
                self.add_info(
                    workflow_name,
                    f"Step '{step_name}' mentions Copilot - ensure repository has Copilot enabled"
                )
            
            # Check for deprecated gh agent-task usage
            if 'gh agent-task' in run_cmd:
                self.add_info(
                    workflow_name,
                    f"Step '{step_name}' uses 'gh agent-task' (preview feature) - consider fallback"
                )
    
    def validate_copilot_workflow(self, workflow_name: str, workflow: Dict[str, Any]):
        """Validate Copilot-specific workflow configuration."""
        # Check if workflow has necessary permissions
        permissions = workflow.get('permissions', {})
        
        required_perms = ['contents', 'pull-requests', 'issues']
        for perm in required_perms:
            if perm not in permissions:
                self.add_warning(
                    workflow_name,
                    f"Copilot workflow missing '{perm}' permission",
                    f"Add: permissions:\\n  {perm}: write"
                )
    
    def validate_permissions(self, workflow_name: str, workflow: Dict[str, Any]):
        """Validate workflow permissions."""
        if 'permissions' not in workflow:
            # Using default permissions
            self.add_info(
                workflow_name,
                "No explicit permissions defined - using repository defaults"
            )
            return
        
        permissions = workflow['permissions']
        
        # Check for overly permissive settings
        if permissions == 'write-all':
            self.add_warning(
                workflow_name,
                "Uses 'write-all' permissions - consider limiting to specific permissions"
            )
    
    def uses_copilot(self, workflow: Dict[str, Any]) -> bool:
        """Check if workflow uses Copilot features."""
        workflow_str = yaml.dump(workflow).lower()
        copilot_indicators = [
            'copilot',
            '@github-copilot',
            'gh agent-task',
            'invoke_copilot',
        ]
        return any(indicator in workflow_str for indicator in copilot_indicators)
    
    def add_issue(self, workflow: str, message: str, suggestion: str = ""):
        """Add an issue (error)."""
        self.issues.append({
            'workflow': workflow,
            'type': 'ERROR',
            'message': message,
            'suggestion': suggestion
        })
        print(f"  ❌ ERROR: {message}")
        if suggestion:
            print(f"     Suggestion: {suggestion}")
    
    def add_warning(self, workflow: str, message: str, suggestion: str = ""):
        """Add a warning."""
        self.warnings.append({
            'workflow': workflow,
            'type': 'WARNING',
            'message': message,
            'suggestion': suggestion
        })
        print(f"  ⚠️  WARNING: {message}")
        if suggestion:
            print(f"     Suggestion: {suggestion}")
    
    def add_info(self, workflow: str, message: str):
        """Add an info message."""
        self.info.append({
            'workflow': workflow,
            'type': 'INFO',
            'message': message
        })
        print(f"  ℹ️  INFO: {message}")
    
    def print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        
        print(f"\n📊 Results:")
        print(f"  ❌ Errors:   {len(self.issues)}")
        print(f"  ⚠️  Warnings: {len(self.warnings)}")
        print(f"  ℹ️  Info:     {len(self.info)}")
        
        if self.issues:
            print(f"\n❌ Critical Issues ({len(self.issues)}):")
            for issue in self.issues:
                print(f"  - [{issue['workflow']}] {issue['message']}")
        
        if self.warnings:
            print(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for warning in self.warnings[:10]:  # Show first 10
                print(f"  - [{warning['workflow']}] {warning['message']}")
            if len(self.warnings) > 10:
                print(f"  ... and {len(self.warnings) - 10} more warnings")
        
        print("\n" + "=" * 80)
        
        if self.issues:
            print("❌ Validation FAILED - Please fix the errors above")
            return 1
        elif self.warnings:
            print("⚠️  Validation PASSED with warnings")
            return 0
        else:
            print("✅ Validation PASSED - All workflows look good!")
            return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Validate GitHub Actions workflows for common issues'
    )
    parser.add_argument(
        '--workflows-dir',
        type=str,
        default='.github/workflows',
        help='Path to workflows directory (default: .github/workflows)'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors'
    )
    
    args = parser.parse_args()
    
    workflows_dir = Path(args.workflows_dir)
    if not workflows_dir.exists():
        print(f"❌ Workflows directory not found: {workflows_dir}")
        return 1
    
    validator = WorkflowValidator(workflows_dir)
    errors, warnings, info = validator.validate_all()
    
    exit_code = validator.print_summary()
    
    if args.strict and warnings > 0:
        print("\n⚠️  Strict mode: Treating warnings as errors")
        exit_code = 1
    
    return exit_code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
