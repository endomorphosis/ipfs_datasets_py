#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Tests for JavaScript Error Reporting System

These tests import modules directly to avoid dependency issues.
"""

import sys
import json
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Load modules directly from files
def load_module_from_file(name, filepath):
    """Load a Python module directly from a file path."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Get paths
test_dir = Path(__file__).parent
repo_dir = test_dir.parent.parent / 'ipfs_datasets_py'

# Load js_error_reporter module
js_error_reporter = load_module_from_file(
    'js_error_reporter',
    repo_dir / 'mcp_server' / 'tools' / 'dashboard_tools' / 'js_error_reporter.py'
)

JavaScriptErrorReporter = js_error_reporter.JavaScriptErrorReporter


def test_initialization():
    """Test reporter initialization."""
    # GIVEN: A new reporter instance
    reporter = JavaScriptErrorReporter()
    
    # THEN: Reporter should be properly initialized
    assert reporter is not None
    assert reporter.error_history == []
    assert reporter.max_history == 100
    print("✓ test_initialization passed")


def test_format_error_report_basic():
    """Test formatting a basic error report."""
    # GIVEN: A reporter and raw error data
    reporter = JavaScriptErrorReporter()
    error_data = {
        'errors': [{
            'type': 'error',
            'message': 'Test error message',
            'timestamp': '2024-01-01T00:00:00.000Z',
            'url': 'http://localhost/dashboard',
            'userAgent': 'Mozilla/5.0'
        }],
        'reportedAt': '2024-01-01T00:00:00.000Z',
        'sessionId': 'session_123'
    }
    
    # WHEN: Formatting the error report
    result = reporter.format_error_report(error_data)
    
    # THEN: Report should be properly formatted
    assert result['source'] == 'javascript_dashboard'
    assert result['session_id'] == 'session_123'
    assert result['error_count'] == 1
    assert len(result['errors']) == 1
    assert result['errors'][0]['type'] == 'error'
    assert result['errors'][0]['message'] == 'Test error message'
    print("✓ test_format_error_report_basic passed")


def test_format_error_report_with_stack():
    """Test formatting error with stack trace."""
    # GIVEN: Error data with stack trace
    reporter = JavaScriptErrorReporter()
    error_data = {
        'errors': [{
            'type': 'error',
            'message': 'TypeError',
            'stack': 'TypeError: Cannot read property\n  at Object.foo\n  at bar',
            'filename': 'app.js',
            'lineno': 42,
            'colno': 15
        }]
    }
    
    # WHEN: Formatting the error
    result = reporter.format_error_report(error_data)
    
    # THEN: Stack trace should be included
    error = result['errors'][0]
    assert error['stack'] is not None
    assert error['filename'] == 'app.js'
    assert error['lineno'] == 42
    assert error['colno'] == 15
    print("✓ test_format_error_report_with_stack passed")


def test_create_github_issue_body():
    """Test GitHub issue body generation."""
    # GIVEN: A formatted error report
    reporter = JavaScriptErrorReporter()
    error_report = {
        'session_id': 'session_123',
        'reported_at': '2024-01-01T00:00:00.000Z',
        'error_count': 1,
        'errors': [{
            'type': 'error',
            'message': 'Test error',
            'timestamp': '2024-01-01T00:00:00.000Z',
            'url': 'http://localhost/dashboard',
            'user_agent': 'Mozilla/5.0',
            'stack': 'Error at line 42',
            'filename': 'app.js',
            'lineno': 42,
            'console_history': [{'level': 'error', 'message': 'Test'}],
            'action_history': [{'type': 'click', 'element': 'BUTTON'}]
        }]
    }
    
    # WHEN: Creating issue body
    body = reporter.create_github_issue_body(error_report)
    
    # THEN: Issue body should contain all relevant information
    assert 'JavaScript Dashboard Error Report' in body
    assert 'session_123' in body
    assert 'Test error' in body
    assert 'app.js:42' in body
    assert 'Error at line 42' in body
    assert 'Console History' in body
    assert 'User Actions' in body
    assert 'Auto-Healing' in body
    print("✓ test_create_github_issue_body passed")


def test_process_error_report_without_issue_creation():
    """Test processing error without creating GitHub issue."""
    # GIVEN: A reporter and error data
    reporter = JavaScriptErrorReporter()
    error_data = {
        'errors': [{'type': 'error', 'message': 'Test'}],
        'sessionId': 'session_123'
    }
    
    # WHEN: Processing without issue creation
    result = reporter.process_error_report(error_data, create_issue=False)
    
    # THEN: Report should be processed but no issue created
    assert result['success'] is True
    assert result['issue_created'] is False
    assert len(reporter.error_history) == 1
    print("✓ test_process_error_report_without_issue_creation passed")


def test_get_error_statistics_empty():
    """Test statistics with no errors."""
    # GIVEN: Empty reporter
    reporter = JavaScriptErrorReporter()
    
    # WHEN: Getting statistics
    stats = reporter.get_error_statistics()
    
    # THEN: Should return empty stats
    assert stats['total_reports'] == 0
    assert stats['total_errors'] == 0
    assert stats['error_types'] == {}
    print("✓ test_get_error_statistics_empty passed")


def test_get_error_statistics_with_errors():
    """Test statistics with multiple errors."""
    # GIVEN: Reporter with multiple error reports
    reporter = JavaScriptErrorReporter()
    reporter.error_history = [
        {
            'error_count': 2,
            'reported_at': '2024-01-01T00:00:00.000Z',
            'errors': [
                {'type': 'error'},
                {'type': 'unhandledrejection'}
            ]
        },
        {
            'error_count': 1,
            'reported_at': '2024-01-01T00:01:00.000Z',
            'errors': [
                {'type': 'error'}
            ]
        }
    ]
    
    # WHEN: Getting statistics
    stats = reporter.get_error_statistics()
    
    # THEN: Statistics should be correct
    assert stats['total_reports'] == 2
    assert stats['total_errors'] == 3
    assert stats['error_types']['error'] == 2
    assert stats['error_types']['unhandledrejection'] == 1
    assert stats['last_report'] == '2024-01-01T00:01:00.000Z'
    print("✓ test_get_error_statistics_with_errors passed")


def test_error_history_limit():
    """Test that error history respects max_history limit."""
    # GIVEN: Reporter with max_history of 10
    reporter = JavaScriptErrorReporter()
    reporter.max_history = 10
    
    # WHEN: Adding more than max_history reports
    for i in range(15):
        error_data = {
            'errors': [{'type': 'error', 'message': f'Error {i}'}]
        }
        reporter.process_error_report(error_data, create_issue=False)
    
    # THEN: History should be limited to max_history
    assert len(reporter.error_history) == 10
    # First 5 should be removed, last 10 should remain
    assert 'Error 5' in str(reporter.error_history[0])
    print("✓ test_error_history_limit passed")


def run_all_tests():
    """Run all tests."""
    tests = [
        test_initialization,
        test_format_error_report_basic,
        test_format_error_report_with_stack,
        test_create_github_issue_body,
        test_process_error_report_without_issue_creation,
        test_get_error_statistics_empty,
        test_get_error_statistics_with_errors,
        test_error_history_limit,
    ]
    
    print("\nRunning JavaScript Error Reporter Tests...")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"\nResults: {passed} passed, {failed} failed")
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
