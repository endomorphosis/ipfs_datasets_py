"""Workflow utilities for GitHub Actions.

This module provides reusable utilities for GitHub Actions workflows,
consolidating common functionality from .github/scripts/.

Public API:
- WorkflowAnalyzer: Analyze workflow failures and generate reports
- DashboardGenerator: Generate API usage dashboards and reports
- WorkflowFixer: Generate fix proposals for workflow failures

Example:
    >>> from ipfs_datasets_py.utils.workflows import WorkflowAnalyzer
    >>> 
    >>> analyzer = WorkflowAnalyzer()
    >>> result = analyzer.analyze_failure(workflow_file, error_log)
    >>> print(result['root_cause'])
    
    >>> from ipfs_datasets_py.utils.workflows import DashboardGenerator
    >>> 
    >>> generator = DashboardGenerator(repo='owner/repo')
    >>> generator.load_all_metrics(metrics_dir=Path('/tmp'))
    >>> report = generator.generate_report(format='html')
    
    >>> from ipfs_datasets_py.utils.workflows import WorkflowFixer
    >>> 
    >>> fixer = WorkflowFixer(analysis, workflow_name='CI Tests')
    >>> proposal = fixer.generate_fix_proposal()
"""

from .analyzer import WorkflowAnalyzer
from .dashboard import DashboardGenerator
from .fixer import WorkflowFixer

__all__ = [
    'WorkflowAnalyzer',
    'DashboardGenerator',
    'WorkflowFixer',
]
