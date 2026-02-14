"""Workflow utilities for GitHub Actions.

This module provides reusable utilities for GitHub Actions workflows,
consolidating common functionality from .github/scripts/.

Public API:
- WorkflowAnalyzer: Analyze workflow failures and generate reports

Example:
    >>> from ipfs_datasets_py.utils.workflows import WorkflowAnalyzer
    >>> 
    >>> analyzer = WorkflowAnalyzer()
    >>> result = analyzer.analyze_failure(workflow_file, error_log)
    >>> print(result['root_cause'])
"""

from .analyzer import WorkflowAnalyzer

__all__ = [
    'WorkflowAnalyzer',
]
