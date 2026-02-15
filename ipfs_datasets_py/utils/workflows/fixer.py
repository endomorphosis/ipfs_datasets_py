"""Workflow fix proposal generation utilities.

This module provides tools for generating fix proposals for failed
GitHub Actions workflows, including specific code changes and PR content.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class WorkflowFixer:
    """Generates fix proposals for workflow failures.
    
    Takes analysis results (from WorkflowAnalyzer or elsewhere) and generates
    comprehensive fix proposals including:
    - Branch names
    - PR titles and descriptions
    - Specific code changes
    - Labels and reviewers
    
    Example:
        >>> from ipfs_datasets_py.utils.workflows import WorkflowAnalyzer, WorkflowFixer
        >>> 
        >>> analyzer = WorkflowAnalyzer()
        >>> analysis = analyzer.analyze_failure(workflow_file, error_log)
        >>> 
        >>> fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
        >>> proposal = fixer.generate_fix_proposal()
        >>> print(proposal['pr_title'])
        >>> print(proposal['branch_name'])
        >>> for fix in proposal['fixes']:
        ...     print(f"- {fix['description']}")
    """
    
    def __init__(self, analysis: Dict[str, Any], workflow_name: str):
        """Initialize workflow fixer.
        
        Args:
            analysis: Analysis results (e.g., from WorkflowAnalyzer)
            workflow_name: Name of the workflow
        """
        self.analysis = analysis
        self.workflow_name = workflow_name
        self.proposal: Dict[str, Any] = {}
    
    def generate_fix_proposal(self) -> Dict[str, Any]:
        """Generate comprehensive fix proposal.
        
        Returns:
            Dict with fix proposal including:
            - branch_name: Suggested branch name
            - pr_title: PR title
            - pr_description: Full PR description (markdown)
            - fix_type: Type of fix
            - error_type: Type of error
            - fixes: List of specific fixes
            - analysis_summary: Summary of analysis
            - labels: Suggested PR labels
            - reviewers: Suggested reviewers
            - auto_merge: Whether to auto-merge
        """
        logger.info(f"🔧 Generating fix proposal for {self.workflow_name}...")
        
        # Determine fix type from analysis
        fix_type = self._determine_fix_type()
        error_type = self.analysis.get('error_type', self.analysis.get('root_cause', 'Unknown'))
        
        # Generate components
        branch_name = self._generate_branch_name(fix_type)
        pr_title = self._generate_pr_title(error_type, fix_type)
        pr_description = self._generate_pr_description(fix_type)
        fixes = self._generate_fixes(fix_type)
        
        # Compile proposal
        self.proposal = {
            'branch_name': branch_name,
            'pr_title': pr_title,
            'pr_description': pr_description,
            'fix_type': fix_type,
            'error_type': error_type,
            'fixes': fixes,
            'analysis_summary': {
                'run_id': self.analysis.get('run_id'),
                'workflow_name': self.workflow_name,
                'confidence': self.analysis.get('fix_confidence', self.analysis.get('confidence', 50)),
                'root_cause': self.analysis.get('root_cause'),
                'severity': self.analysis.get('severity', 'medium'),
            },
            'labels': self._generate_labels(fix_type),
            'reviewers': ['github-copilot'],
            'auto_merge': False,  # Require review
        }
        
        return self.proposal
    
    def _determine_fix_type(self) -> str:
        """Determine fix type from analysis.
        
        Returns:
            Fix type string (e.g., 'add_dependency', 'increase_timeout')
        """
        # Check if explicitly provided
        if 'fix_type' in self.analysis:
            return self.analysis['fix_type']
        
        # Infer from root cause or error patterns
        root_cause = self.analysis.get('root_cause', '').lower()
        
        if 'missing' in root_cause or 'module' in root_cause or 'dependency' in root_cause:
            return 'add_dependency'
        elif 'timeout' in root_cause or 'timed out' in root_cause:
            return 'increase_timeout'
        elif 'permission' in root_cause or 'forbidden' in root_cause:
            return 'fix_permissions'
        elif 'connection' in root_cause or 'network' in root_cause:
            return 'add_retry'
        elif 'docker' in root_cause or 'container' in root_cause:
            return 'fix_docker'
        elif 'memory' in root_cause or 'resource' in root_cause:
            return 'increase_resources'
        elif 'environment' in root_cause or 'variable' in root_cause:
            return 'add_env_variable'
        else:
            return 'manual'
    
    def _generate_branch_name(self, fix_type: str) -> str:
        """Generate a descriptive branch name.
        
        Args:
            fix_type: Type of fix
        
        Returns:
            Branch name (e.g., 'autofix/ci-tests/add-dependency/20260214-123456')
        """
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        safe_workflow = re.sub(r'[^a-z0-9-]', '-', self.workflow_name.lower())
        safe_fix_type = re.sub(r'[^a-z0-9-]', '-', fix_type.lower())
        
        return f"autofix/{safe_workflow}/{safe_fix_type}/{timestamp}"
    
    def _generate_pr_title(self, error_type: str, fix_type: str) -> str:
        """Generate PR title.
        
        Args:
            error_type: Type of error
            fix_type: Type of fix
        
        Returns:
            PR title
        """
        return f"fix: Auto-fix {error_type} in {self.workflow_name}"
    
    def _generate_pr_description(self, fix_type: str) -> str:
        """Generate detailed PR description.
        
        Args:
            fix_type: Type of fix
        
        Returns:
            Markdown-formatted PR description
        """
        run_id = self.analysis.get('run_id', 'unknown')
        error_type = self.analysis.get('error_type', self.analysis.get('root_cause', 'Unknown'))
        root_cause = self.analysis.get('root_cause', 'Not specified')
        confidence = self.analysis.get('fix_confidence', self.analysis.get('confidence', 50))
        
        description = f"""# Automated Workflow Fix

## Summary
This PR was automatically generated to fix a failure in the **{self.workflow_name}** workflow.

## Failure Details
- **Run ID**: {run_id}
- **Error Type**: {error_type}
- **Root Cause**: {root_cause}
- **Fix Confidence**: {confidence}%

## Analysis
{self._format_analysis_section()}

## Proposed Fix
{self._format_fixes_section()}

## Recommendations
{self._format_recommendations_section()}

## Affected Files
{self._format_affected_files_section()}

---

### 🤖 About This PR
- **Generated by**: GitHub Actions Workflow Auto-Fix System
- **Reviewed by**: GitHub Copilot (pending)
- **Type**: Automated Fix
- **Requires Review**: Yes

### Next Steps
1. Review the proposed changes
2. GitHub Copilot will analyze the fix
3. Run tests to verify the fix resolves the issue
4. Merge if all checks pass

### Related
- Workflow Run: https://github.com/${{ github.repository }}/actions/runs/{run_id}
- Workflow File: `.github/workflows/{self._get_workflow_filename()}`
"""
        
        return description
    
    def _format_analysis_section(self) -> str:
        """Format the analysis section."""
        patterns = self.analysis.get('patterns_found', self.analysis.get('error_patterns', []))
        
        if not patterns:
            return "No specific patterns identified."
        
        if isinstance(patterns, list) and len(patterns) > 0:
            if isinstance(patterns[0], dict):
                return "\n".join([f"- {p.get('cause', p)}" for p in patterns])
            else:
                return "\n".join([f"- {p}" for p in patterns])
        
        return "No specific patterns identified."
    
    def _format_fixes_section(self) -> str:
        """Format the fixes section."""
        fixes = self.proposal.get('fixes', [])
        
        if not fixes:
            return "Manual review required."
        
        sections = []
        for fix in fixes:
            sections.append(f"### {fix['description']}\n")
            sections.append(f"**File**: `{fix['file']}`\n")
            sections.append(f"**Action**: {fix['action']}\n")
            
            if fix.get('changes'):
                sections.append("\n```yaml\n" + fix['changes'] + "\n```\n")
        
        return "\n".join(sections)
    
    def _format_recommendations_section(self) -> str:
        """Format recommendations section."""
        recommendations = self.analysis.get('recommendations', self.analysis.get('suggestions', []))
        
        if not recommendations:
            return "No specific recommendations."
        
        if isinstance(recommendations, list):
            return "\n".join([f"- {rec}" for rec in recommendations])
        
        return str(recommendations)
    
    def _format_affected_files_section(self) -> str:
        """Format affected files section."""
        files = self.analysis.get('affected_files', [])
        
        if not files:
            return "No specific files identified."
        
        return "\n".join([f"- `{file}`" for file in files])
    
    def _get_workflow_filename(self) -> str:
        """Get workflow filename from workflow name."""
        # Convert workflow name to likely filename
        filename = re.sub(r'[^a-z0-9-]', '-', self.workflow_name.lower())
        return f"{filename}.yml"
    
    def _generate_fixes(self, fix_type: str) -> List[Dict[str, Any]]:
        """Generate specific fix changes based on fix type.
        
        Args:
            fix_type: Type of fix
        
        Returns:
            List of fix dictionaries
        """
        fix_handlers = {
            'add_dependency': self._fix_add_dependency,
            'increase_timeout': self._fix_increase_timeout,
            'fix_permissions': self._fix_permissions,
            'add_retry': self._fix_add_retry,
            'fix_docker': self._fix_docker,
            'increase_resources': self._fix_increase_resources,
            'add_env_variable': self._fix_add_env_variable,
        }
        
        handler = fix_handlers.get(fix_type)
        if handler:
            return handler()
        else:
            # Generic fix suggestion
            return [{
                'file': f'.github/workflows/{self._get_workflow_filename()}',
                'action': 'review_required',
                'description': 'Manual review and fix required',
                'changes': None,
            }]
    
    def _fix_add_dependency(self) -> List[Dict[str, Any]]:
        """Generate fix for missing dependencies."""
        fixes = []
        
        # Extract package name from analysis
        captured_values = self.analysis.get('captured_values', [])
        
        if captured_values and len(captured_values) > 0:
            package = captured_values[0]
            pip_package = package.replace('_', '-')
            
            # Fix for workflow
            workflow_fix = {
                'file': f'.github/workflows/{self._get_workflow_filename()}',
                'action': 'add_install_step',
                'description': f'Add pip install step for {pip_package}',
                'changes': f"""- name: Install missing dependency
  run: |
    pip install {pip_package}""",
            }
            fixes.append(workflow_fix)
            
            # Fix for requirements.txt
            requirements_fix = {
                'file': 'requirements.txt',
                'action': 'add_line',
                'description': f'Add {pip_package} to requirements.txt',
                'changes': pip_package,
            }
            fixes.append(requirements_fix)
        
        return fixes
    
    def _fix_increase_timeout(self) -> List[Dict[str, Any]]:
        """Generate fix for timeout issues."""
        return [{
            'file': f'.github/workflows/{self._get_workflow_filename()}',
            'action': 'add_timeout',
            'description': 'Increase timeout for long-running step',
            'changes': """timeout-minutes: 30  # Increased from default""",
        }]
    
    def _fix_permissions(self) -> List[Dict[str, Any]]:
        """Generate fix for permission errors."""
        return [{
            'file': f'.github/workflows/{self._get_workflow_filename()}',
            'action': 'add_permissions',
            'description': 'Add required permissions to workflow',
            'changes': """permissions:
  contents: write
  pull-requests: write
  issues: write
  actions: read""",
        }]
    
    def _fix_add_retry(self) -> List[Dict[str, Any]]:
        """Generate fix for network errors."""
        return [{
            'file': f'.github/workflows/{self._get_workflow_filename()}',
            'action': 'add_retry_action',
            'description': 'Add retry logic for network operations',
            'changes': """- name: Retry network operation
  uses: nick-invision/retry@v2
  with:
    timeout_minutes: 10
    max_attempts: 3
    retry_on: error
    command: |
      # Your network command here""",
        }]
    
    def _fix_docker(self) -> List[Dict[str, Any]]:
        """Generate fix for Docker errors."""
        return [{
            'file': f'.github/workflows/{self._get_workflow_filename()}',
            'action': 'add_docker_setup',
            'description': 'Add Docker setup steps',
            'changes': """- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Log in to Container Registry
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}""",
        }]
    
    def _fix_increase_resources(self) -> List[Dict[str, Any]]:
        """Generate fix for resource exhaustion."""
        return [{
            'file': f'.github/workflows/{self._get_workflow_filename()}',
            'action': 'change_runner',
            'description': 'Use a larger runner with more resources',
            'changes': """runs-on: ubuntu-latest-4-cores  # Increased from ubuntu-latest""",
        }]
    
    def _fix_add_env_variable(self) -> List[Dict[str, Any]]:
        """Generate fix for missing environment variables."""
        return [{
            'file': f'.github/workflows/{self._get_workflow_filename()}',
            'action': 'add_env',
            'description': 'Add missing environment variable',
            'changes': """env:
  # Add your required environment variable here
  REQUIRED_VAR: ${{ secrets.REQUIRED_VAR }}""",
        }]
    
    def _generate_labels(self, fix_type: str) -> List[str]:
        """Generate appropriate labels for the PR.
        
        Args:
            fix_type: Type of fix
        
        Returns:
            List of label strings
        """
        labels = [
            'automated-fix',
            'workflow-fix',
            'copilot-ready',
        ]
        
        # Add fix-type specific labels
        if fix_type == 'add_dependency':
            labels.append('dependencies')
        elif fix_type in ['fix_permissions', 'add_env_variable']:
            labels.append('configuration')
        elif fix_type == 'fix_docker':
            labels.append('docker')
        elif fix_type in ['fix_test', 'fix_syntax']:
            labels.append('bug')
        
        return labels
