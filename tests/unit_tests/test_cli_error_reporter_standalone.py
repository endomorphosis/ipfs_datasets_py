#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Tests for CLI Error Reporting System

These tests import modules directly to avoid dependency issues.
"""

import sys
import importlib.util
from pathlib import Path

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

# Load cli_error_reporter module
cli_error_reporter = load_module_from_file(
    'cli_error_reporter',
    repo_dir / 'error_reporting' / 'cli_error_reporter.py'
)

CLIErrorReporter = cli_error_reporter.CLIErrorReporter


def test_initialization():
    """Test reporter initialization."""
    # GIVEN: A new reporter instance
    reporter = CLIErrorReporter()
    
    # THEN: Reporter should be properly initialized
    assert reporter is not None
    assert reporter.error_history == []
    assert reporter.max_history == 50
    print("✓ test_initialization passed")


def test_format_cli_error_basic():
    """Test formatting a basic CLI error."""
    # GIVEN: A reporter and an error
    reporter = CLIErrorReporter()
    error = ValueError("Test error message")
    command = "ipfs-datasets"
    args = ["info", "status"]
    
    # WHEN: Formatting the error
    result = reporter.format_cli_error(error, command, args)
    
    # THEN: Report should be properly formatted
    assert result['source'] == 'cli_tool'
    assert result['command'] == command
    assert result['args'] == args
    assert result['error_type'] == 'ValueError'
    assert result['error_message'] == 'Test error message'
    assert 'stack_trace' in result
    assert 'timestamp' in result
    print("✓ test_format_cli_error_basic passed")


def test_format_cli_error_with_logs():
    """Test formatting error with logs."""
    # GIVEN: Error with logs
    reporter = CLIErrorReporter()
    error = RuntimeError("Command failed")
    logs = "Log line 1\nLog line 2\nLog line 3"
    
    # WHEN: Formatting the error
    result = reporter.format_cli_error(
        error,
        command="ipfs-datasets",
        args=["dataset", "load"],
        logs=logs
    )
    
    # THEN: Logs should be included
    assert 'logs' in result
    assert result['logs'] == logs
    assert result['logs_truncated'] is False
    print("✓ test_format_cli_error_with_logs passed")


def test_format_cli_error_truncates_long_logs():
    """Test that long logs are truncated."""
    # GIVEN: Error with very long logs
    reporter = CLIErrorReporter()
    error = RuntimeError("Command failed")
    long_logs = '\n'.join([f"Log line {i}" for i in range(200)])
    
    # WHEN: Formatting the error
    result = reporter.format_cli_error(
        error,
        command="ipfs-datasets",
        args=["test"],
        logs=long_logs
    )
    
    # THEN: Logs should be truncated
    assert 'logs' in result
    assert result['logs_truncated'] is True
    # Should only have last 100 lines
    assert result['logs'].count('\n') <= 100
    print("✓ test_format_cli_error_truncates_long_logs passed")


def test_create_github_issue_body():
    """Test GitHub issue body generation."""
    # GIVEN: A formatted error report
    reporter = CLIErrorReporter()
    error_report = {
        'source': 'cli_tool',
        'command': 'ipfs-datasets',
        'args': ['info', 'status'],
        'error_type': 'ValueError',
        'error_message': 'Test error',
        'stack_trace': 'Traceback...\nValueError: Test error',
        'timestamp': '2024-01-30T23:00:00.000Z',
        'python_version': '3.12.0',
        'platform': 'linux',
        'cwd': '/home/user/project',
        'logs': 'Log line 1\nLog line 2'
    }
    
    # WHEN: Creating issue body
    body = reporter.create_github_issue_body(error_report)
    
    # THEN: Issue body should contain all relevant information
    assert 'CLI Tool Error Report' in body
    assert 'ipfs-datasets' in body
    assert 'ValueError' in body
    assert 'Test error' in body
    assert 'Stack Trace' in body
    assert 'Recent Logs' in body
    assert 'Auto-Healing' in body
    assert 'bug' in body
    assert 'cli' in body
    print("✓ test_create_github_issue_body passed")


def test_report_cli_error_without_issue():
    """Test reporting error without creating GitHub issue."""
    # GIVEN: A reporter and error
    reporter = CLIErrorReporter()
    error = RuntimeError("CLI command failed")
    
    # WHEN: Reporting without issue creation
    result = reporter.report_cli_error(
        error=error,
        command="ipfs-datasets",
        args=["test"],
        create_issue=False
    )
    
    # THEN: Report should be processed but no issue created
    assert result['success'] is True
    assert result['issue_created'] is False
    assert len(reporter.error_history) == 1
    print("✓ test_report_cli_error_without_issue passed")


def test_error_history_limit():
    """Test that error history respects max_history limit."""
    # GIVEN: Reporter with max_history of 10
    reporter = CLIErrorReporter()
    reporter.max_history = 10
    
    # WHEN: Adding more than max_history reports
    for i in range(15):
        error = RuntimeError(f"Error {i}")
        reporter.report_cli_error(
            error=error,
            command="ipfs-datasets",
            args=["test"],
            create_issue=False
        )
    
    # THEN: History should be limited to max_history
    assert len(reporter.error_history) == 10
    # First 5 should be removed, last 10 should remain
    assert 'Error 5' in str(reporter.error_history[0])
    print("✓ test_error_history_limit passed")


def test_format_cli_error_with_context():
    """Test formatting error with additional context."""
    # GIVEN: Error with context
    reporter = CLIErrorReporter()
    error = ValueError("Invalid input")
    context = {'user': 'test_user', 'operation': 'dataset_load'}
    
    # WHEN: Formatting the error
    result = reporter.format_cli_error(
        error,
        command="ipfs-datasets",
        args=["dataset", "load"],
        context=context
    )
    
    # THEN: Context should be included
    assert 'context' in result
    assert result['context']['user'] == 'test_user'
    assert result['context']['operation'] == 'dataset_load'
    print("✓ test_format_cli_error_with_context passed")


def test_get_cli_error_reporter_singleton():
    """Test that get_cli_error_reporter returns singleton."""
    # GIVEN: Multiple calls to get_cli_error_reporter
    reporter1 = cli_error_reporter.get_cli_error_reporter()
    reporter2 = cli_error_reporter.get_cli_error_reporter()
    
    # THEN: Should return same instance
    assert reporter1 is reporter2
    print("✓ test_get_cli_error_reporter_singleton passed")


def run_all_tests():
    """Run all tests."""
    tests = [
        test_initialization,
        test_format_cli_error_basic,
        test_format_cli_error_with_logs,
        test_format_cli_error_truncates_long_logs,
        test_create_github_issue_body,
        test_report_cli_error_without_issue,
        test_error_history_limit,
        test_format_cli_error_with_context,
        test_get_cli_error_reporter_singleton,
    ]
    
    print("\nRunning CLI Error Reporter Tests...")
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
