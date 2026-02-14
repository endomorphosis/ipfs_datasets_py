"""Workflow utilities for GitHub Actions.

This module provides reusable utilities for GitHub Actions workflows,
consolidating common functionality from .github/scripts/.

Public API:
- WorkflowAnalyzer: Analyze workflow failures and generate reports
- DashboardGenerator: Generate API usage dashboards and reports

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
"""

from .analyzer import WorkflowAnalyzer
from .dashboard import DashboardGenerator

__all__ = [
    'WorkflowAnalyzer',
    'DashboardGenerator',
]
