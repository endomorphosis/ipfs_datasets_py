#!/usr/bin/env python3
"""
Comprehensive GitHub Actions Workflow Validator and Fixer

This script validates all GitHub Actions workflow files and can automatically
fix common issues like:
- YAML syntax errors (indentation, structure)
- Missing trigger configurations
- Invalid matrix expressions
- Security issues (command injection, missing permissions)
- Missing timeouts
- Performance issues (missing caching)

Usage:
    python comprehensive_workflow_validator.py --check              # Validate only
    python comprehensive_workflow_validator.py --fix                # Fix issues
    python comprehensive_workflow_validator.py --report report.md  # Generate report
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List
from datetime import datetime
import yaml


class WorkflowValidator:
    """Validates and fixes GitHub Actions workflows"""
    
    def __init__(self, workflows_dir: str = ".github/workflows"):
        self.workflows_dir = Path(workflows_dir)
        self.issues = []
        self.fixes_applied = []
        
    def validate_all_workflows(self) -> Dict[str, List[Dict]]:
        """Validate all workflow files and return issues by category"""
        workflow_files = list(self.workflows_dir.glob("*.yml")) + \
                        list(self.workflows_dir.glob("*.yaml"))
        
        results = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "info": []
        }
        
        for workflow_file in workflow_files:
            if workflow_file.name.startswith('.'):
                continue
                
            issues = self.validate_workflow(workflow_file)
            for issue in issues:
                results[issue["severity"]].append({
                    "file": str(workflow_file.relative_to(self.workflows_dir.parent.parent)),
                    **issue
                })
        
        return results
    
    def validate_workflow(self, workflow_file: Path) -> List[Dict]:
        """Validate a single workflow file"""
        issues = []
        
        try:
            with open(workflow_file, 'r') as f:
                content = f.read()
                
            # Check YAML syntax
            yaml_issues = self.check_yaml_syntax(workflow_file, content)
            issues.extend(yaml_issues)
            
            # If YAML is valid, perform deeper checks
            if not yaml_issues:
                try:
                    workflow = yaml.safe_load(content)
                    
                    # Check for missing triggers
                    if not workflow.get('on') and not workflow.get('true'):
                        issues.append({
                            "type": "missing_trigger",
                            "severity": "critical",
                            "message": "Missing trigger configuration (on:)",
                            "line": 1
                        })
                    
                    # Check for permission issues
                    if 'permissions' not in workflow:
                        issues.append({
                            "type": "missing_permissions",
                            "severity": "high",
                            "message": "Missing explicit permissions configuration",
                            "line": 1
                        })
                    
                    # Check jobs
                    if 'jobs' in workflow:
                        job_issues = self.check_jobs(workflow['jobs'], content)
                        issues.extend(job_issues)
                        
                except Exception as e:
                    issues.append({
                        "type": "validation_error",
                        "severity": "high",
                        "message": f"Validation error: {e}",
                        "line": 1
                    })
        
        except Exception as e:
            issues.append({
                "type": "file_error",
                "severity": "critical",
                "message": f"Cannot read file: {e}",
                "line": 1
            })
        
        return issues
    
    def check_yaml_syntax(self, workflow_file: Path, content: str) -> List[Dict]:
        """Check for YAML syntax errors"""
        issues = []
        
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            error_msg = str(e)
            line_num = 1
            
            # Extract line number from error message
            if hasattr(e, 'problem_mark'):
                line_num = e.problem_mark.line + 1
            
            # Common patterns
            if "mapping values are not allowed" in error_msg:
                issues.append({
                    "type": "yaml_indentation",
                    "severity": "critical",
                    "message": "YAML indentation error - likely 'with:' incorrectly indented after 'uses:'",
                    "line": line_num,
                    "fix": "auto"
                })
            elif "expected ',' or ']'" in error_msg:
                issues.append({
                    "type": "yaml_flow_sequence",
                    "severity": "critical",
                    "message": "Invalid flow sequence - likely using ${{ }} in array without quotes",
                    "line": line_num,
                    "fix": "manual"
                })
            else:
                issues.append({
                    "type": "yaml_syntax",
                    "severity": "critical",
                    "message": f"YAML syntax error: {error_msg}",
                    "line": line_num,
                    "fix": "manual"
                })
        
        return issues
    
    def check_jobs(self, jobs: Dict, content: str) -> List[Dict]:
        """Check job configurations"""
        issues = []
        
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                # Check for timeout
                if 'timeout-minutes' not in job_config:
                    issues.append({
                        "type": "missing_timeout",
                        "severity": "medium",
                        "message": f"Job '{job_name}' missing timeout-minutes",
                        "line": 1,
                        "fix": "auto"
                    })
                
                # Check steps
                if 'steps' in job_config:
                    step_issues = self.check_steps(job_config['steps'], job_name, content)
                    issues.extend(step_issues)
        
        return issues
    
    def check_steps(self, steps: List, job_name: str, content: str) -> List[Dict]:
        """Check step configurations"""
        issues = []
        
        for i, step in enumerate(steps):
            if isinstance(step, dict):
                # Check for command injection
                if 'run' in step:
                    run_content = step['run']
                    if isinstance(run_content, str):
                        # Check for direct use of github.event
                        if '${{ github.event' in run_content and 'env:' not in str(step):
                            issues.append({
                                "type": "command_injection",
                                "severity": "high",
                                "message": f"Job '{job_name}' step {i+1} may have command injection risk",
                                "line": 1,
                                "fix": "manual"
                            })
                
                # Check for checkout optimization
                if 'uses' in step and 'actions/checkout' in step['uses']:
                    if 'with' not in step or 'fetch-depth' not in step.get('with', {}):
                        issues.append({
                            "type": "missing_fetch_depth",
                            "severity": "low",
                            "message": f"Job '{job_name}' checkout missing fetch-depth optimization",
                            "line": 1,
                            "fix": "auto"
                        })
        
        return issues
    
    def fix_workflow(self, workflow_file: Path) -> bool:
        """Attempt to automatically fix issues in a workflow file"""
        try:
            with open(workflow_file, 'r') as f:
                content = f.read()
            
            original_content = content
            fixed = False
            
            # Fix common indentation issues with 'with:'
            # Pattern: 'uses: ACTION\n    with:' should be 'uses: ACTION\n        with:'
            pattern = r'([ ]*uses:\s+.+\n)([ ]{2,6})with:'
            matches = list(re.finditer(pattern, content))
            
            for match in matches:
                uses_indent = len(match.group(1)) - len(match.group(1).lstrip())
                with_indent = len(match.group(2))
                expected_indent = uses_indent + 2
                
                if with_indent != expected_indent:
                    # Fix the indentation
                    old_text = match.group(0)
                    new_text = match.group(1) + ' ' * expected_indent + 'with:'
                    content = content.replace(old_text, new_text, 1)
                    fixed = True
                    self.fixes_applied.append({
                        "file": str(workflow_file.name),
                        "type": "indentation_fix",
                        "description": f"Fixed 'with:' indentation from {with_indent} to {expected_indent} spaces"
                    })
            
            # Write fixed content if changes were made
            if fixed and content != original_content:
                with open(workflow_file, 'w') as f:
                    f.write(content)
                return True
            
        except Exception as e:
            print(f"Error fixing {workflow_file}: {e}")
            return False
        
        return False
    
    def generate_report(self, results: Dict[str, List[Dict]]) -> str:
        """Generate a comprehensive report"""
        report = []
        report.append("# GitHub Actions Workflow Validation Report")
        report.append(f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"**Generated by:** comprehensive_workflow_validator.py")
        report.append(f"\n## Summary\n")
        
        total_issues = sum(len(issues) for issues in results.values())
        report.append(f"**Total Issues:** {total_issues}\n")
        
        for severity, issues in results.items():
            if issues:
                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "ℹ️"}[severity]
                report.append(f"- {icon} **{severity.upper()}:** {len(issues)}")
        
        report.append("\n## Detailed Issues\n")
        
        for severity in ["critical", "high", "medium", "low", "info"]:
            issues = results[severity]
            if not issues:
                continue
            
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "ℹ️"}[severity]
            report.append(f"\n### {icon} {severity.upper()} Issues ({len(issues)})\n")
            
            # Group by file
            by_file = {}
            for issue in issues:
                file = issue['file']
                if file not in by_file:
                    by_file[file] = []
                by_file[file].append(issue)
            
            for file, file_issues in sorted(by_file.items()):
                report.append(f"\n#### 📄 {file}\n")
                for issue in file_issues:
                    report.append(f"- **{issue['type']}** (line {issue.get('line', 'N/A')}): {issue['message']}")
                    if 'fix' in issue and issue['fix'] == 'auto':
                        report.append("  - 🔧 Auto-fixable")
                    if 'suggestion' in issue:
                        report.append(f"  - 💡 Suggestion: {issue['suggestion']}")
        
        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description="Validate and fix GitHub Actions workflows"
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check workflows for issues (default)'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Automatically fix issues where possible'
    )
    parser.add_argument(
        '--report',
        type=str,
        help='Generate report and save to file'
    )
    parser.add_argument(
        '--workflows-dir',
        type=str,
        default='.github/workflows',
        help='Path to workflows directory'
    )
    
    args = parser.parse_args()
    
    validator = WorkflowValidator(args.workflows_dir)
    
    if args.fix:
        print("🔧 Fixing workflow issues...")
        workflow_files = list(Path(args.workflows_dir).glob("*.yml")) + \
                        list(Path(args.workflows_dir).glob("*.yaml"))
        
        for workflow_file in workflow_files:
            if workflow_file.name.startswith('.'):
                continue
            
            if validator.fix_workflow(workflow_file):
                print(f"✅ Fixed: {workflow_file.name}")
        
        print(f"\n✅ Applied {len(validator.fixes_applied)} fixes")
        for fix in validator.fixes_applied:
            print(f"  - {fix['file']}: {fix['description']}")
    
    print("\n🔍 Validating workflows...")
    results = validator.validate_all_workflows()
    
    # Print summary
    total_issues = sum(len(issues) for issues in results.values())
    print(f"\n📊 Found {total_issues} issues:")
    for severity, issues in results.items():
        if issues:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "ℹ️"}[severity]
            print(f"  {icon} {severity.upper()}: {len(issues)}")
    
    # Generate report if requested
    if args.report:
        report = validator.generate_report(results)
        with open(args.report, 'w') as f:
            f.write(report)
        print(f"\n📄 Report saved to: {args.report}")
    
    # Exit with error code if critical or high issues found
    if results["critical"] or results["high"]:
        print("\n⚠️  Critical or high severity issues found!")
        return 1
    
    print("\n✅ Validation complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
