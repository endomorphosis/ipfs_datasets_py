#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Error Reporting System
"""

import os
import pytest
import tempfile
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from ipfs_datasets_py.error_reporting import (
    ErrorReporter,
    get_global_error_reporter,
    GitHubIssueClient
)


class TestGitHubIssueClient:
    """Test GitHub issue client functionality."""
    
    def test_initialization_default_repo(self):
        """Test client initialization with default repository."""
        # GIVEN default environment
        # WHEN creating a client
        client = GitHubIssueClient()
        
        # THEN it should use default repository
        assert client.repo == 'endomorphosis/ipfs_datasets_py'
    
    def test_initialization_custom_repo(self):
        """Test client initialization with custom repository."""
        # GIVEN a custom repository name
        custom_repo = 'test/repo'
        
        # WHEN creating a client
        client = GitHubIssueClient(repo=custom_repo)
        
        # THEN it should use the custom repository
        assert client.repo == custom_repo
    
    @patch('subprocess.run')
    def test_is_available_when_gh_installed(self, mock_run):
        """Test availability check when gh CLI is installed."""
        # GIVEN gh CLI is installed and authenticated
        mock_run.return_value = Mock(returncode=0)
        client = GitHubIssueClient()
        
        # WHEN checking availability
        available = client.is_available()
        
        # THEN it should return True
        assert available is True
    
    @patch('subprocess.run')
    def test_is_available_when_gh_not_installed(self, mock_run):
        """Test availability check when gh CLI is not installed."""
        # GIVEN gh CLI is not installed
        mock_run.return_value = Mock(returncode=1)
        client = GitHubIssueClient()
        
        # WHEN checking availability
        available = client.is_available()
        
        # THEN it should return False
        assert available is False
    
    @patch('subprocess.run')
    def test_create_issue_success(self, mock_run):
        """Test successful issue creation."""
        # GIVEN gh CLI is available and returns success
        mock_run.side_effect = [
            Mock(returncode=0),  # is_available check 1
            Mock(returncode=0),  # is_available check 2
            Mock(returncode=0, stdout='https://github.com/test/repo/issues/123', stderr='')  # create issue
        ]
        client = GitHubIssueClient(repo='test/repo', github_token='fake_token')
        
        # WHEN creating an issue
        result = client.create_issue(
            title='Test Issue',
            body='Test body',
            labels=['bug']
        )
        
        # THEN it should succeed
        assert result['success'] is True
        assert result['issue_number'] == '123'
        assert 'https://github.com/test/repo/issues/123' in result['issue_url']
    
    @patch('subprocess.run')
    def test_create_issue_when_unavailable(self, mock_run):
        """Test issue creation when gh CLI is not available."""
        # GIVEN gh CLI is not available
        mock_run.return_value = Mock(returncode=1)
        client = GitHubIssueClient()
        
        # WHEN trying to create an issue
        result = client.create_issue(
            title='Test Issue',
            body='Test body'
        )
        
        # THEN it should fail gracefully
        assert result['success'] is False
        assert 'not available' in result['error']


class TestErrorReporter:
    """Test error reporter functionality."""
    
    def test_initialization_disabled_by_default(self):
        """Test that error reporter is disabled by default."""
        # GIVEN default environment
        # WHEN creating a reporter
        reporter = ErrorReporter()
        
        # THEN it should be disabled
        assert reporter.enabled is False
    
    def test_initialization_enabled_via_env(self):
        """Test enabling reporter via environment variable."""
        # GIVEN ERROR_REPORTING_ENABLED is set
        with patch.dict(os.environ, {'ERROR_REPORTING_ENABLED': 'true'}):
            # WHEN creating a reporter
            reporter = ErrorReporter()
            
            # THEN it should be enabled
            assert reporter.enabled is True
    
    def test_compute_error_hash_consistent(self):
        """Test that error hash is consistent for same input."""
        # GIVEN an error reporter
        reporter = ErrorReporter(enabled=False)
        
        # WHEN computing hash for same error twice
        hash1 = reporter._compute_error_hash('TypeError', 'test message', 'file.py:10')
        hash2 = reporter._compute_error_hash('TypeError', 'test message', 'file.py:10')
        
        # THEN hashes should be identical
        assert hash1 == hash2
    
    def test_compute_error_hash_different_for_different_errors(self):
        """Test that different errors produce different hashes."""
        # GIVEN an error reporter
        reporter = ErrorReporter(enabled=False)
        
        # WHEN computing hashes for different errors
        hash1 = reporter._compute_error_hash('TypeError', 'message1', 'file.py:10')
        hash2 = reporter._compute_error_hash('ValueError', 'message1', 'file.py:10')
        hash3 = reporter._compute_error_hash('TypeError', 'message2', 'file.py:10')
        
        # THEN hashes should be different
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
    
    def test_should_report_error_first_time(self):
        """Test that error should be reported on first occurrence."""
        # GIVEN an error reporter
        reporter = ErrorReporter(enabled=True)
        error_hash = 'test_hash'
        
        # WHEN checking if error should be reported for first time
        should_report = reporter._should_report_error(error_hash)
        
        # THEN it should return True
        assert should_report is True
    
    def test_should_not_report_duplicate_error(self):
        """Test that duplicate error should not be reported."""
        # GIVEN an error reporter that has seen an error
        reporter = ErrorReporter(enabled=True, min_report_interval=3600)
        error_hash = 'test_hash'
        reporter._should_report_error(error_hash)  # First report
        
        # WHEN checking if same error should be reported again
        should_report = reporter._should_report_error(error_hash)
        
        # THEN it should return False
        assert should_report is False
    
    def test_report_error_when_disabled(self):
        """Test that errors are not reported when disabled."""
        # GIVEN a disabled error reporter
        reporter = ErrorReporter(enabled=False)
        
        # WHEN trying to report an error
        result = reporter.report_error(
            error_type='TypeError',
            error_message='test error',
            source='python'
        )
        
        # THEN it should fail
        assert result['success'] is False
        assert 'disabled' in result['error']
    
    @patch('ipfs_datasets_py.error_reporting.github_issue_client.GitHubIssueClient.is_available')
    @patch('ipfs_datasets_py.error_reporting.github_issue_client.GitHubIssueClient.create_issue')
    def test_report_error_when_enabled(self, mock_create_issue, mock_is_available):
        """Test error reporting when enabled."""
        # GIVEN an enabled error reporter with mocked GitHub client
        mock_is_available.return_value = True
        mock_create_issue.return_value = {
            'success': True,
            'issue_url': 'https://github.com/test/repo/issues/1',
            'issue_number': '1'
        }
        
        reporter = ErrorReporter(enabled=True)
        
        # WHEN reporting an error
        result = reporter.report_error(
            error_type='TypeError',
            error_message='test error',
            source='python',
            error_location='test.py:10',
            stack_trace='Traceback...',
            context={'key': 'value'}
        )
        
        # THEN it should succeed
        assert result['success'] is True
        assert 'issue_url' in result
        assert mock_create_issue.called
    
    def test_report_exception(self):
        """Test reporting a Python exception."""
        # GIVEN an enabled error reporter
        with patch('ipfs_datasets_py.error_reporting.github_issue_client.GitHubIssueClient.is_available', return_value=True):
            with patch('ipfs_datasets_py.error_reporting.github_issue_client.GitHubIssueClient.create_issue') as mock_create:
                mock_create.return_value = {'success': True, 'issue_url': 'test_url', 'issue_number': '1'}
                reporter = ErrorReporter(enabled=True)
                
                # WHEN reporting an exception
                try:
                    raise ValueError("Test exception")
                except ValueError as e:
                    result = reporter.report_exception(e, source='python')
                
                # THEN it should report with correct type and message
                assert result['success'] is True
                assert result['error_data']['error_type'] == 'ValueError'
                assert result['error_data']['error_message'] == 'Test exception'
    
    def test_format_error_title(self):
        """Test error title formatting."""
        # GIVEN an error reporter
        reporter = ErrorReporter(enabled=False)
        
        # WHEN formatting an error title
        title = reporter._format_error_title(
            'TypeError',
            'Something went wrong',
            'python'
        )
        
        # THEN it should be properly formatted
        assert 'TypeError' in title
        assert 'Something went wrong' in title
        assert 'python' in title
        assert title.startswith('[Runtime Error]')
    
    def test_format_error_body_with_all_fields(self):
        """Test error body formatting with all fields."""
        # GIVEN an error reporter
        reporter = ErrorReporter(enabled=False)
        error_data = {
            'error_type': 'TypeError',
            'error_message': 'test error',
            'source': 'python',
            'timestamp': '2024-01-01T00:00:00',
            'error_location': 'test.py:10',
            'stack_trace': 'Traceback...',
            'context': {'key': 'value'},
            'hostname': 'test-host'
        }
        
        # WHEN formatting the error body
        body = reporter._format_error_body(error_data)
        
        # THEN it should include all fields
        assert 'TypeError' in body
        assert 'test error' in body
        assert 'python' in body
        assert 'test.py:10' in body
        assert 'Traceback...' in body
        assert 'key' in body
        assert 'test-host' in body


class TestGlobalErrorReporter:
    """Test global error reporter singleton."""
    
    def test_get_global_error_reporter_returns_instance(self):
        """Test that get_global_error_reporter returns an instance."""
        # GIVEN nothing
        # WHEN getting global reporter
        reporter = get_global_error_reporter()
        
        # THEN it should return an ErrorReporter instance
        assert isinstance(reporter, ErrorReporter)
    
    def test_get_global_error_reporter_returns_same_instance(self):
        """Test that multiple calls return the same instance."""
        # GIVEN nothing
        # WHEN getting global reporter multiple times
        reporter1 = get_global_error_reporter()
        reporter2 = get_global_error_reporter()
        
        # THEN they should be the same instance
        assert reporter1 is reporter2
