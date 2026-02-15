"""Unit tests for utils.workflows.analyzer module."""

import pytest
from pathlib import Path
from ipfs_datasets_py.utils.workflows.analyzer import WorkflowAnalyzer


class TestWorkflowAnalyzer:
    """Test suite for WorkflowAnalyzer class."""
    
    def test_initialization(self):
        """Test WorkflowAnalyzer initialization."""
        analyzer = WorkflowAnalyzer()
        assert hasattr(analyzer, 'analyze_failure')
        assert hasattr(analyzer, 'generate_report')
        assert hasattr(analyzer, '_generate_suggestions')
        assert hasattr(analyzer, '_determine_severity')
        assert hasattr(analyzer, 'analysis_cache')
        assert isinstance(analyzer.analysis_cache, dict)
    
    def test_error_patterns_defined(self):
        """Test that error patterns are properly defined."""
        analyzer = WorkflowAnalyzer()
        assert hasattr(analyzer, 'ERROR_PATTERNS')
        assert isinstance(analyzer.ERROR_PATTERNS, dict)
        assert len(analyzer.ERROR_PATTERNS) > 0
        
        # Check some key patterns exist
        patterns = analyzer.ERROR_PATTERNS
        assert any('rate limit' in pattern for pattern in patterns.keys())
        assert any('timeout' in pattern for pattern in patterns.keys())
        assert any('permission' in pattern for pattern in patterns.keys())
    
    def test_analyze_failure_rate_limit(self):
        """Test analysis of rate limit errors."""
        analyzer = WorkflowAnalyzer()
        workflow_file = Path('.github/workflows/test.yml')
        error_log = 'Error: API rate limit exceeded. Please try again later.'
        
        result = analyzer.analyze_failure(workflow_file, error_log)
        
        assert 'root_cause' in result
        assert 'suggestions' in result
        assert 'severity' in result
        assert 'workflow_file' in result
        assert 'error_log' in result
        assert 'rate limit' in result['root_cause'].lower()
    
    def test_analyze_failure_dependency_error(self):
        """Test analysis of dependency/module errors."""
        analyzer = WorkflowAnalyzer()
        workflow_file = Path('.github/workflows/test.yml')
        error_log = 'ModuleNotFoundError: No module named "numpy"'
        
        result = analyzer.analyze_failure(workflow_file, error_log)
        
        assert 'root_cause' in result
        assert 'module' in result['root_cause'].lower() or 'dependency' in result['root_cause'].lower()
        assert len(result['suggestions']) > 0
    
    def test_analyze_failure_timeout(self):
        """Test analysis of timeout errors."""
        analyzer = WorkflowAnalyzer()
        workflow_file = Path('.github/workflows/test.yml')
        error_log = 'Error: The operation was canceled due to timeout.'
        
        result = analyzer.analyze_failure(workflow_file, error_log)
        
        assert 'root_cause' in result
        assert 'timeout' in result['root_cause'].lower()
    
    def test_analyze_failure_permission_denied(self):
        """Test analysis of permission errors."""
        analyzer = WorkflowAnalyzer()
        workflow_file = Path('.github/workflows/test.yml')
        error_log = 'Error: Permission denied when accessing resource.'
        
        result = analyzer.analyze_failure(workflow_file, error_log)
        
        assert 'root_cause' in result
        assert 'permission' in result['root_cause'].lower()
    
    def test_generate_suggestions_not_empty(self):
        """Test that suggestions are generated for known errors."""
        analyzer = WorkflowAnalyzer()
        
        suggestions = analyzer._generate_suggestions(
            'GitHub API rate limit exceeded',
            'rate limit error'
        )
        
        assert isinstance(suggestions, list)
        assert len(suggestions) > 0
        assert all(isinstance(s, str) for s in suggestions)
    
    def test_determine_severity_levels(self):
        """Test that severity levels are assigned correctly."""
        analyzer = WorkflowAnalyzer()
        
        # High severity: rate limit
        severity = analyzer._determine_severity('rate limit', 'rate limit exceeded')
        assert severity in ['low', 'medium', 'high', 'critical']
        
        # Check various error types
        test_cases = [
            ('timeout', 'timeout error'),
            ('permission denied', 'permission error'),
            ('module not found', 'import error'),
        ]
        
        for root_cause, error_log in test_cases:
            severity = analyzer._determine_severity(root_cause, error_log)
            assert severity in ['low', 'medium', 'high', 'critical']
    
    def test_generate_report(self):
        """Test report generation from analysis results."""
        analyzer = WorkflowAnalyzer()
        
        analysis_result = {
            'root_cause': 'GitHub API rate limit exceeded',
            'suggestions': ['Implement caching', 'Add retry logic'],
            'severity': 'high',
            'workflow_file': Path('.github/workflows/test.yml'),
            'error_log': 'rate limit error'
        }
        
        report = analyzer.generate_report(analysis_result)
        
        assert isinstance(report, str)
        assert len(report) > 0
        assert 'rate limit' in report.lower()
        assert 'severity' in report.lower()
    
    def test_analyze_failure_unknown_pattern(self):
        """Test analysis of errors with no matching pattern."""
        analyzer = WorkflowAnalyzer()
        workflow_file = Path('.github/workflows/test.yml')
        error_log = 'Some completely unknown error that matches no pattern'
        
        result = analyzer.analyze_failure(workflow_file, error_log)
        
        assert 'root_cause' in result
        assert 'suggestions' in result
        assert 'severity' in result
        # Should still provide some analysis even if pattern doesn't match
        assert isinstance(result['suggestions'], list)
    
    def test_multiple_analyses(self):
        """Test that analyzer can handle multiple consecutive analyses."""
        analyzer = WorkflowAnalyzer()
        workflow_file = Path('.github/workflows/test.yml')
        
        errors = [
            'rate limit exceeded',
            'timeout error',
            'module not found',
        ]
        
        results = []
        for error in errors:
            result = analyzer.analyze_failure(workflow_file, error)
            results.append(result)
        
        # Check all analyses completed
        assert len(results) == len(errors)
        
        # Check each has required fields
        for result in results:
            assert 'root_cause' in result
            assert 'suggestions' in result
            assert 'severity' in result
