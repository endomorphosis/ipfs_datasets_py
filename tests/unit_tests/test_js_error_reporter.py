#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for JavaScript Error Reporting System

Tests the complete workflow of capturing JavaScript errors from the dashboard,
creating GitHub issues, and triggering auto-healing.
"""

import sys
import json
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add the parent directory to sys.path to import modules directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'ipfs_datasets_py'))

# Import directly from the module file to avoid dependency issues
from mcp_server.tools.dashboard_tools.js_error_reporter import (
    JavaScriptErrorReporter,
    get_js_error_reporter
)


class TestJavaScriptErrorReporter:
    """Test suite for JavaScriptErrorReporter class."""
    
    def test_initialization(self):
        """Test reporter initialization."""
        # GIVEN: A new reporter instance
        reporter = JavaScriptErrorReporter()
        
        # THEN: Reporter should be properly initialized
        assert reporter is not None
        assert reporter.error_history == []
        assert reporter.max_history == 100
    
    def test_format_error_report_basic(self):
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
    
    def test_format_error_report_with_stack(self):
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
    
    def test_format_error_report_with_console_history(self):
        """Test formatting error with console history."""
        # GIVEN: Error with console history
        reporter = JavaScriptErrorReporter()
        error_data = {
            'errors': [{
                'type': 'error',
                'message': 'Test error',
                'consoleHistory': [
                    {'level': 'log', 'message': 'App started'},
                    {'level': 'warn', 'message': 'Warning'},
                    {'level': 'error', 'message': 'Error occurred'}
                ]
            }]
        }
        
        # WHEN: Formatting the error
        result = reporter.format_error_report(error_data)
        
        # THEN: Console history should be included
        error = result['errors'][0]
        assert len(error['console_history']) == 3
        assert error['console_history'][0]['level'] == 'log'
    
    def test_format_error_report_with_action_history(self):
        """Test formatting error with user action history."""
        # GIVEN: Error with action history
        reporter = JavaScriptErrorReporter()
        error_data = {
            'errors': [{
                'type': 'error',
                'message': 'Test error',
                'actionHistory': [
                    {'type': 'click', 'element': 'BUTTON', 'id': 'submit'},
                    {'type': 'submit', 'element': 'FORM'}
                ]
            }]
        }
        
        # WHEN: Formatting the error
        result = reporter.format_error_report(error_data)
        
        # THEN: Action history should be included
        error = result['errors'][0]
        assert len(error['action_history']) == 2
        assert error['action_history'][0]['type'] == 'click'
    
    def test_create_github_issue_body(self):
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
    
    def test_process_error_report_without_issue_creation(self):
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
    
    @patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.js_error_reporter.GitHubIssueClient')
    def test_process_error_report_with_issue_creation(self, mock_client_class):
        """Test processing error with GitHub issue creation."""
        # GIVEN: A reporter with mocked GitHub client
        mock_client = Mock()
        mock_client.is_available.return_value = True
        mock_client.create_issue.return_value = {
            'success': True,
            'url': 'https://github.com/owner/repo/issues/1',
            'number': 1
        }
        mock_client_class.return_value = mock_client
        
        reporter = JavaScriptErrorReporter()
        error_data = {
            'errors': [{'type': 'error', 'message': 'Test error'}],
            'sessionId': 'session_123'
        }
        
        # WHEN: Processing with issue creation
        result = reporter.process_error_report(error_data, create_issue=True)
        
        # THEN: Issue should be created
        assert result['success'] is True
        assert result['issue_created'] is True
        assert 'issue_url' in result
        assert result['issue_number'] == 1
        mock_client.create_issue.assert_called_once()
    
    @patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.js_error_reporter.GitHubIssueClient')
    def test_github_cli_not_available(self, mock_client_class):
        """Test behavior when GitHub CLI is not available."""
        # GIVEN: GitHub CLI is not available
        mock_client = Mock()
        mock_client.is_available.return_value = False
        mock_client_class.return_value = mock_client
        
        reporter = JavaScriptErrorReporter()
        error_data = {
            'errors': [{'type': 'error', 'message': 'Test'}]
        }
        
        # WHEN: Processing with issue creation
        result = reporter.process_error_report(error_data, create_issue=True)
        
        # THEN: Should succeed but not create issue
        assert result['success'] is True
        assert result['issue_created'] is False
    
    def test_get_error_statistics_empty(self):
        """Test statistics with no errors."""
        # GIVEN: Empty reporter
        reporter = JavaScriptErrorReporter()
        
        # WHEN: Getting statistics
        stats = reporter.get_error_statistics()
        
        # THEN: Should return empty stats
        assert stats['total_reports'] == 0
        assert stats['total_errors'] == 0
        assert stats['error_types'] == {}
    
    def test_get_error_statistics_with_errors(self):
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
    
    def test_error_history_limit(self):
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
    
    def test_get_js_error_reporter_singleton(self):
        """Test that get_js_error_reporter returns singleton."""
        # GIVEN: Multiple calls to get_js_error_reporter
        reporter1 = get_js_error_reporter()
        reporter2 = get_js_error_reporter()
        
        # THEN: Should return same instance
        assert reporter1 is reporter2
    
    @patch("mcp_server.tools.dashboard_tools.js_error_reporter.coordinate_auto_healing")
    @patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.js_error_reporter.GitHubIssueClient')
    def test_auto_healing_trigger(self, mock_client_class, mock_coordinate):
        """Test that auto-healing is triggered after issue creation."""
        # GIVEN: Mocked GitHub client and auto-healing coordinator
        mock_client = Mock()
        mock_client.is_available.return_value = True
        mock_client.create_issue.return_value = {
            'success': True,
            'url': 'https://github.com/owner/repo/issues/42',
            'number': 42
        }
        mock_client_class.return_value = mock_client
        
        mock_coordinate.return_value = {
            'success': True,
            'healing_actions': []
        }
        
        reporter = JavaScriptErrorReporter()
        error_data = {
            'errors': [{'type': 'error', 'message': 'Test'}]
        }
        
        # WHEN: Processing with issue creation
        result = reporter.process_error_report(error_data, create_issue=True)
        
        # THEN: Auto-healing should be triggered
        assert result['issue_created'] is True
        mock_coordinate.assert_called_once()
        call_args = mock_coordinate.call_args[1]
        assert call_args['error_report']['issue_number'] == 42


class TestErrorReportingEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_empty_errors_array(self):
        """Test handling of empty errors array."""
        # GIVEN: Reporter and empty error data
        reporter = JavaScriptErrorReporter()
        error_data = {'errors': []}
        
        # WHEN: Processing empty errors
        result = reporter.process_error_report(error_data, create_issue=False)
        
        # THEN: Should still succeed
        assert result['success'] is True
        assert result['report']['error_count'] == 0
    
    def test_malformed_error_data(self):
        """Test handling of malformed error data."""
        # GIVEN: Reporter and malformed data
        reporter = JavaScriptErrorReporter()
        error_data = {'errors': [{'invalid': 'structure'}]}
        
        # WHEN: Processing malformed data
        result = reporter.process_error_report(error_data, create_issue=False)
        
        # THEN: Should handle gracefully with defaults
        assert result['success'] is True
        error = result['report']['errors'][0]
        assert error['type'] == 'unknown'
        assert error['message'] == 'No error message'
    
    def test_very_long_stack_trace(self):
        """Test handling of very long stack traces."""
        # GIVEN: Error with very long stack trace
        reporter = JavaScriptErrorReporter()
        long_stack = 'Line\n' * 2000  # Very long stack
        error_data = {
            'errors': [{
                'type': 'error',
                'message': 'Test',
                'stack': long_stack
            }]
        }
        
        # WHEN: Creating issue body
        report = reporter.format_error_report(error_data)
        body = reporter.create_github_issue_body(report)
        
        # THEN: Stack should be truncated
        assert len(body) < len(long_stack) + 1000
        assert '```' in body  # Stack trace should still be formatted


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
