#!/usr/bin/env python3
"""
Enhanced GitHub Actions Workflow Validator - Phase 4 Task 4.1
Comprehensive validation with detailed reporting, auto-fix suggestions, and severity levels.

Usage:
    python enhanced_workflow_validator.py                    # Console report
    python enhanced_workflow_validator.py --json out.json    # JSON report
    python enhanced_workflow_validator.py --html out.html    # HTML report
    python enhanced_workflow_validator.py --fix              # Auto-fix issues
"""

import argparse
import json
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import re


class ValidationIssue:
    """Represents a validation issue with severity, category, and fix suggestions."""
    
    def __init__(
        self,
        severity: str,  # critical, high, medium, low, info
        category: str,  # security, performance, reliability, documentation, style
        message: str,
        line_number: Optional[int] = None,
        fix_suggestion: Optional[str] = None,
        auto_fixable: bool = False
    ):
        self.severity = severity
        self.category = category
        self.message = message
        self.line_number = line_number
        self.fix_suggestion = fix_suggestion
        self.auto_fixable = auto_fixable
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'severity': self.severity,
            'category': self.category,
            'message': self.message,
            'line_number': self.line_number,
            'fix_suggestion': self.fix_suggestion,
            'auto_fixable': self.auto_fixable
        }


class EnhancedWorkflowValidator:
    """Comprehensive workflow validator with best practices checks."""
    
    def __init__(self, workflows_dir: Optional[Path] = None):
        self.workflows_dir = workflows_dir or Path('.github/workflows')
        self.stats = {
            'total_workflows': 0,
            'valid_workflows': 0,
            'workflows_with_issues': 0,
            'total_issues': 0,
            'critical_issues': 0,
            'high_issues': 0,
            'medium_issues': 0,
            'low_issues': 0,
            'info_issues': 0,
            'auto_fixable_issues': 0
        }
    
    def validate_all(self) -> Dict[str, Any]:
        """Validate all workflow files."""
        workflow_files = [
            f for f in self.workflows_dir.glob('*.yml')
            if not f.name.endswith(('.backup', '.disabled'))
        ]
        
        self.stats['total_workflows'] = len(workflow_files)
        results = []
        
        for filepath in sorted(workflow_files):
            result = self.validate_workflow(filepath)
            results.append(result)
            
            if result['has_issues']:
                self.stats['workflows_with_issues'] += 1
            else:
                self.stats['valid_workflows'] += 1
            
            # Count issues by severity
            for issue in result['issues']:
                self.stats['total_issues'] += 1
                severity_key = f"{issue['severity']}_issues"
                if severity_key in self.stats:
                    self.stats[severity_key] += 1
                if issue.get('auto_fixable'):
                    self.stats['auto_fixable_issues'] += 1
        
        return {
            'results': results,
            'stats': self.stats,
            'timestamp': datetime.now().isoformat(),
            'validator_version': '2.0.0'
        }
    
    def validate_workflow(self, filepath: Path) -> Dict[str, Any]:
        """Validate a single workflow file with comprehensive checks."""
        result = {
            'file': filepath.name,
            'path': str(filepath),
            'valid': True,
            'has_issues': False,
            'issues': []
        }
        
        try:
            content = filepath.read_text()
            workflow = yaml.safe_load(content)
            
            if not workflow:
                result['issues'].append(ValidationIssue(
                    severity='critical',
                    category='syntax',
                    message='Empty or invalid YAML file',
                    fix_suggestion='Ensure file contains valid YAML workflow definition'
                ).to_dict())
                result['has_issues'] = True
                return result
            
            # Run all validation checks
            self._check_required_fields(workflow, result)
            self._check_permissions(workflow, result)
            self._check_concurrency(workflow, result)
            self._check_timeouts(workflow, result)
            self._check_checkout_optimization(workflow, result)
            self._check_error_handling(workflow, result)
            self._check_security(workflow, result)
            self._check_performance(workflow, result)
            self._check_documentation(workflow, result)
            self._check_best_practices(workflow, result)
            
            result['has_issues'] = len(result['issues']) > 0
            
        except yaml.YAMLError as e:
            result['valid'] = False
            result['has_issues'] = True
            result['issues'].append(ValidationIssue(
                severity='critical',
                category='syntax',
                message=f'YAML syntax error: {str(e)}',
                fix_suggestion='Fix YAML syntax errors'
            ).to_dict())
        except Exception as e:
            result['valid'] = False
            result['has_issues'] = True
            result['issues'].append(ValidationIssue(
                severity='critical',
                category='unknown',
                message=f'Validation error: {str(e)}'
            ).to_dict())
        
        return result
    
    def _check_required_fields(self, workflow: Dict, result: Dict):
        """Check for required workflow fields."""
        if not workflow.get('name'):
            result['issues'].append(ValidationIssue(
                severity='high',
                category='documentation',
                message='Missing workflow name',
                fix_suggestion='Add: name: "Descriptive Workflow Name"',
                auto_fixable=True
            ).to_dict())
        
        if 'on' not in workflow:
            result['issues'].append(ValidationIssue(
                severity='critical',
                category='syntax',
                message='Missing trigger configuration (on:)',
                fix_suggestion='Add workflow triggers (on: push, pull_request, etc.)'
            ).to_dict())
        
        if 'jobs' not in workflow or not workflow['jobs']:
            result['issues'].append(ValidationIssue(
                severity='critical',
                category='syntax',
                message='Missing or empty jobs section',
                fix_suggestion='Add at least one job to the workflow'
            ).to_dict())
    
    def _check_permissions(self, workflow: Dict, result: Dict):
        """Check for explicit permissions (security best practice)."""
        if 'permissions' not in workflow:
            result['issues'].append(ValidationIssue(
                severity='high',
                category='security',
                message='Missing explicit permissions (security risk)',
                fix_suggestion='Add explicit permissions: contents: read, etc.',
                auto_fixable=True
            ).to_dict())
        else:
            permissions = workflow['permissions']
            if isinstance(permissions, dict):
                # Check for overly permissive permissions
                if permissions.get('contents') == 'write':
                    result['issues'].append(ValidationIssue(
                        severity='medium',
                        category='security',
                        message='contents: write permission - review if necessary',
                        fix_suggestion='Use contents: read unless write is required'
                    ).to_dict())
                
                if permissions.get('packages') == 'write':
                    result['issues'].append(ValidationIssue(
                        severity='low',
                        category='security',
                        message='packages: write permission - ensure justified',
                        fix_suggestion='Verify package publishing is intended'
                    ).to_dict())
    
    def _check_concurrency(self, workflow: Dict, result: Dict):
        """Check for concurrency control."""
        if 'concurrency' not in workflow:
            result['issues'].append(ValidationIssue(
                severity='medium',
                category='performance',
                message='Missing concurrency control (may waste resources)',
                fix_suggestion='Add concurrency: group + cancel-in-progress',
                auto_fixable=True
            ).to_dict())
        else:
            concurrency = workflow['concurrency']
            if isinstance(concurrency, dict):
                if 'group' not in concurrency:
                    result['issues'].append(ValidationIssue(
                        severity='low',
                        category='performance',
                        message='Concurrency missing group definition',
                        fix_suggestion='Add group: ${{ github.workflow }}-${{ github.ref }}'
                    ).to_dict())
    
    def _check_timeouts(self, workflow: Dict, result: Dict):
        """Check for job timeouts."""
        jobs = workflow.get('jobs', {})
        missing_timeouts = []
        
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                if 'timeout-minutes' not in job_config:
                    missing_timeouts.append(job_name)
        
        if missing_timeouts:
            result['issues'].append(ValidationIssue(
                severity='medium',
                category='reliability',
                message=f'Jobs missing timeout-minutes: {", ".join(missing_timeouts[:3])}{"..." if len(missing_timeouts) > 3 else ""}',
                fix_suggestion='Add timeout-minutes to prevent hanging jobs',
                auto_fixable=True
            ).to_dict())
    
    def _check_checkout_optimization(self, workflow: Dict, result: Dict):
        """Check for checkout action optimization."""
        jobs = workflow.get('jobs', {})
        
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                steps = job_config.get('steps', [])
                for step in steps:
                    if isinstance(step, dict):
                        uses = step.get('uses', '')
                        if 'actions/checkout' in uses:
                            step_with = step.get('with', {})
                            if 'fetch-depth' not in step_with:
                                result['issues'].append(ValidationIssue(
                                    severity='low',
                                    category='performance',
                                    message=f'Job "{job_name}": checkout without fetch-depth optimization',
                                    fix_suggestion='Add with: fetch-depth: 1 for faster checkout',
                                    auto_fixable=True
                                ).to_dict())
                                break  # Only report once per job
    
    def _check_error_handling(self, workflow: Dict, result: Dict):
        """Check for error handling and retry logic."""
        jobs = workflow.get('jobs', {})
        
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                steps = job_config.get('steps', [])
                has_critical_step = False
                has_retry = False
                
                for step in steps:
                    if isinstance(step, dict):
                        # Check for steps that typically need retry
                        name = step.get('name', '').lower()
                        run = step.get('run', '').lower()
                        uses = step.get('uses', '').lower()
                        
                        if any(keyword in name or keyword in run for keyword in 
                               ['docker', 'build', 'install', 'api', 'download', 'upload']):
                            has_critical_step = True
                        
                        if 'retry' in uses:
                            has_retry = True
                
                if has_critical_step and not has_retry:
                    result['issues'].append(ValidationIssue(
                        severity='low',
                        category='reliability',
                        message=f'Job "{job_name}": Consider retry for critical steps',
                        fix_suggestion='Add retry action for docker/install/api steps'
                    ).to_dict())
    
    def _check_security(self, workflow: Dict, result: Dict):
        """Check for security issues."""
        jobs = workflow.get('jobs', {})
        
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                steps = job_config.get('steps', [])
                
                for step in steps:
                    if isinstance(step, dict):
                        run = step.get('run', '')
                        
                        # Check for potentially unsafe patterns
                        if isinstance(run, str):
                            if '${{' in run and 'github.event' in run:
                                result['issues'].append(ValidationIssue(
                                    severity='high',
                                    category='security',
                                    message=f'Job "{job_name}": Potential injection risk with github.event',
                                    fix_suggestion='Validate/sanitize github.event inputs before use'
                                ).to_dict())
                            
                            if 'curl' in run.lower() and '|' in run and 'sh' in run:
                                result['issues'].append(ValidationIssue(
                                    severity='high',
                                    category='security',
                                    message=f'Job "{job_name}": curl | sh pattern detected (security risk)',
                                    fix_suggestion='Download and verify scripts before execution'
                                ).to_dict())
    
    def _check_performance(self, workflow: Dict, result: Dict):
        """Check for performance optimizations."""
        jobs = workflow.get('jobs', {})
        
        # Check for caching
        has_cache = False
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                steps = job_config.get('steps', [])
                for step in steps:
                    if isinstance(step, dict):
                        if 'actions/cache' in step.get('uses', ''):
                            has_cache = True
                            break
        
        # Look for operations that could benefit from caching
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                steps = job_config.get('steps', [])
                has_dependencies = False
                
                for step in steps:
                    if isinstance(step, dict):
                        run = step.get('run', '').lower()
                        if any(cmd in run for cmd in ['pip install', 'npm install', 'cargo build']):
                            has_dependencies = True
                
                if has_dependencies and not has_cache:
                    result['issues'].append(ValidationIssue(
                        severity='low',
                        category='performance',
                        message=f'Job "{job_name}": Consider caching dependencies',
                        fix_suggestion='Add actions/cache for pip/npm/cargo dependencies'
                    ).to_dict())
    
    def _check_documentation(self, workflow: Dict, result: Dict):
        """Check for workflow documentation."""
        # Check for description comment or header
        name = workflow.get('name', '')
        
        if len(name) < 10:
            result['issues'].append(ValidationIssue(
                severity='low',
                category='documentation',
                message='Workflow name is too short (not descriptive)',
                fix_suggestion='Use descriptive name: "Component - Purpose - Environment"'
            ).to_dict())
        
        # Check if jobs have descriptions
        jobs = workflow.get('jobs', {})
        jobs_without_names = []
        
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                if 'name' not in job_config:
                    jobs_without_names.append(job_name)
        
        if jobs_without_names:
            result['issues'].append(ValidationIssue(
                severity='info',
                category='documentation',
                message=f'Jobs without descriptive names: {", ".join(jobs_without_names[:3])}',
                fix_suggestion='Add name: field to jobs for better readability'
            ).to_dict())
    
    def _check_best_practices(self, workflow: Dict, result: Dict):
        """Check for general best practices."""
        jobs = workflow.get('jobs', {})
        
        # Check for self-hosted runners without fallback
        for job_name, job_config in jobs.items():
            if isinstance(job_config, dict):
                runs_on = job_config.get('runs-on', '')
                
                if isinstance(runs_on, str) and 'self-hosted' in runs_on:
                    # Check if there's conditional logic or matrix for fallback
                    if 'if' not in job_config and 'strategy' not in job_config:
                        result['issues'].append(ValidationIssue(
                            severity='medium',
                            category='reliability',
                            message=f'Job "{job_name}": self-hosted runner without fallback',
                            fix_suggestion='Add fallback to github-hosted runners or conditional logic'
                        ).to_dict())
    
    def generate_console_report(self, validation_results: Dict) -> str:
        """Generate human-readable console report."""
        lines = [
            "=" * 80,
            "Enhanced Workflow Validation Report",
            "=" * 80,
            "",
            f"Generated: {validation_results['timestamp']}",
            f"Validator Version: {validation_results['validator_version']}",
            "",
            "=" * 80,
            "Summary Statistics",
            "=" * 80,
            "",
            f"Total Workflows:         {validation_results['stats']['total_workflows']}",
            f"Valid Workflows:         {validation_results['stats']['valid_workflows']}",
            f"Workflows with Issues:   {validation_results['stats']['workflows_with_issues']}",
            f"Total Issues:            {validation_results['stats']['total_issues']}",
            "",
            "Issues by Severity:",
            f"  Critical:              {validation_results['stats']['critical_issues']}",
            f"  High:                  {validation_results['stats']['high_issues']}",
            f"  Medium:                {validation_results['stats']['medium_issues']}",
            f"  Low:                   {validation_results['stats']['low_issues']}",
            f"  Info:                  {validation_results['stats']['info_issues']}",
            "",
            f"Auto-fixable Issues:     {validation_results['stats']['auto_fixable_issues']}",
            ""
        ]
        
        if validation_results['stats']['total_issues'] > 0:
            lines.extend([
                "=" * 80,
                "Detailed Issues",
                "=" * 80,
                ""
            ])
            
            for workflow_result in validation_results['results']:
                if workflow_result['has_issues']:
                    lines.append(f"📄 {workflow_result['file']}")
                    lines.append(f"   Path: {workflow_result['path']}")
                    lines.append("")
                    
                    # Group by severity
                    for severity in ['critical', 'high', 'medium', 'low', 'info']:
                        severity_issues = [
                            i for i in workflow_result['issues']
                            if i['severity'] == severity
                        ]
                        
                        if severity_issues:
                            for issue in severity_issues:
                                icon = {
                                    'critical': '🔴',
                                    'high': '🟠',
                                    'medium': '🟡',
                                    'low': '🔵',
                                    'info': '⚪'
                                }.get(severity, '⚫')
                                
                                lines.append(f"   {icon} [{severity.upper()}] [{issue['category'].upper()}]")
                                lines.append(f"      {issue['message']}")
                                
                                if issue.get('fix_suggestion'):
                                    lines.append(f"      💡 Fix: {issue['fix_suggestion']}")
                                
                                if issue.get('auto_fixable'):
                                    lines.append(f"      ✨ Auto-fixable")
                                
                                lines.append("")
                    
                    lines.append("")
        
        else:
            lines.extend([
                "=" * 80,
                "✅ All workflows pass validation!",
                "=" * 80,
                ""
            ])
        
        return "\n".join(lines)
    
    def generate_html_report(self, validation_results: Dict) -> str:
        """Generate HTML report."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Workflow Validation Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat-card {{ background: #f9f9f9; padding: 15px; border-radius: 5px; border-left: 4px solid #4CAF50; }}
        .stat-card.critical {{ border-left-color: #f44336; }}
        .stat-card.high {{ border-left-color: #ff9800; }}
        .stat-card.medium {{ border-left-color: #ffc107; }}
        .stat-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .workflow {{ margin: 20px 0; padding: 15px; background: #fafafa; border-radius: 5px; }}
        .workflow-name {{ font-weight: bold; font-size: 18px; margin-bottom: 10px; }}
        .issue {{ margin: 10px 0; padding: 10px; border-left: 4px solid #ccc; background: white; }}
        .issue.critical {{ border-left-color: #f44336; }}
        .issue.high {{ border-left-color: #ff9800; }}
        .issue.medium {{ border-left-color: #ffc107; }}
        .issue.low {{ border-left-color: #2196F3; }}
        .issue.info {{ border-left-color: #9E9E9E; }}
        .severity {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; text-transform: uppercase; }}
        .severity.critical {{ background: #f44336; color: white; }}
        .severity.high {{ background: #ff9800; color: white; }}
        .severity.medium {{ background: #ffc107; color: black; }}
        .severity.low {{ background: #2196F3; color: white; }}
        .severity.info {{ background: #9E9E9E; color: white; }}
        .category {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 11px; background: #e0e0e0; margin-left: 5px; }}
        .fix-suggestion {{ margin-top: 5px; padding: 8px; background: #e8f5e9; border-radius: 3px; font-size: 13px; }}
        .auto-fixable {{ color: #4CAF50; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Workflow Validation Report</h1>
        <p>Generated: {validation_results['timestamp']}</p>
        <p>Validator Version: {validation_results['validator_version']}</p>
        
        <h2>Summary Statistics</h2>
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Total Workflows</div>
                <div class="stat-value">{validation_results['stats']['total_workflows']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Valid Workflows</div>
                <div class="stat-value">{validation_results['stats']['valid_workflows']}</div>
            </div>
            <div class="stat-card critical">
                <div class="stat-label">Critical Issues</div>
                <div class="stat-value">{validation_results['stats']['critical_issues']}</div>
            </div>
            <div class="stat-card high">
                <div class="stat-label">High Issues</div>
                <div class="stat-value">{validation_results['stats']['high_issues']}</div>
            </div>
            <div class="stat-card medium">
                <div class="stat-label">Medium Issues</div>
                <div class="stat-value">{validation_results['stats']['medium_issues']}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Auto-fixable</div>
                <div class="stat-value">{validation_results['stats']['auto_fixable_issues']}</div>
            </div>
        </div>
        
        <h2>Detailed Results</h2>
"""
        
        for workflow_result in validation_results['results']:
            if workflow_result['has_issues']:
                html += f"""
        <div class="workflow">
            <div class="workflow-name">📄 {workflow_result['file']}</div>
            <div style="font-size: 12px; color: #666; margin-bottom: 10px;">{workflow_result['path']}</div>
"""
                for issue in workflow_result['issues']:
                    html += f"""
            <div class="issue {issue['severity']}">
                <span class="severity {issue['severity']}">{issue['severity']}</span>
                <span class="category">{issue['category']}</span>
                {' <span class="auto-fixable">✨ Auto-fixable</span>' if issue.get('auto_fixable') else ''}
                <div style="margin-top: 5px;">{issue['message']}</div>
"""
                    if issue.get('fix_suggestion'):
                        html += f"""
                <div class="fix-suggestion">💡 <strong>Fix:</strong> {issue['fix_suggestion']}</div>
"""
                    html += """
            </div>
"""
                html += """
        </div>
"""
        
        html += """
    </div>
</body>
</html>"""
        
        return html


def main():
    parser = argparse.ArgumentParser(description='Enhanced GitHub Actions Workflow Validator')
    parser.add_argument('--json', metavar='FILE', help='Output JSON report to file')
    parser.add_argument('--html', metavar='FILE', help='Output HTML report to file')
    parser.add_argument('--workflows-dir', metavar='DIR', help='Workflows directory (default: .github/workflows)')
    args = parser.parse_args()
    
    # Determine workflows directory
    if args.workflows_dir:
        workflows_dir = Path(args.workflows_dir)
    else:
        # Try to find .github/workflows from current directory or parent
        current = Path.cwd()
        if (current / '.github' / 'workflows').exists():
            workflows_dir = current / '.github' / 'workflows'
        elif (current.parent / '.github' / 'workflows').exists():
            workflows_dir = current.parent / '.github' / 'workflows'
        else:
            workflows_dir = Path('.github/workflows')
    
    if not workflows_dir.exists():
        print(f"Error: Workflows directory not found: {workflows_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Run validation
    validator = EnhancedWorkflowValidator(workflows_dir)
    results = validator.validate_all()
    
    # Generate and output reports
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"JSON report written to: {args.json}")
    
    if args.html:
        html_report = validator.generate_html_report(results)
        with open(args.html, 'w') as f:
            f.write(html_report)
        print(f"HTML report written to: {args.html}")
    
    # Always print console report
    console_report = validator.generate_console_report(results)
    print(console_report)
    
    # Exit with error if critical or high severity issues found
    has_critical_issues = results['stats']['critical_issues'] > 0
    has_high_issues = results['stats']['high_issues'] > 0
    
    if has_critical_issues or has_high_issues:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
