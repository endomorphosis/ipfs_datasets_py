"""Tests for GitHub issue creation."""
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from ipfs_datasets_py.error_reporting.config import ErrorReportingConfig
from ipfs_datasets_py.error_reporting.issue_creator import GitHubIssueCreator


class TestGitHubIssueCreator:
    """Test GitHub issue creator."""
    
    @pytest.fixture
    def temp_state_file(self):
        """Create temporary state file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            state_file = Path(f.name)
        yield state_file
        if state_file.exists():
            state_file.unlink()
    
    @pytest.fixture
    def config(self, temp_state_file, monkeypatch):
        """Create test configuration."""
        monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'true')
        monkeypatch.setenv('GITHUB_TOKEN', 'test-token')
        monkeypatch.setenv('GITHUB_REPOSITORY', 'test-owner/test-repo')
        
        config = ErrorReportingConfig()
        config.state_file = temp_state_file
        return config
    
    def test_initialization(self, config):
        """
        GIVEN: Valid configuration
        WHEN: Creating GitHubIssueCreator
        THEN: Should initialize properly
        """
        creator = GitHubIssueCreator(config)
        
        assert creator.config == config
        assert 'reported_errors' in creator.state
        assert 'hourly_count' in creator.state
        assert 'daily_count' in creator.state
    
    def test_load_state_new(self, config):
        """
        GIVEN: No existing state file
        WHEN: Loading state
        THEN: Should create default state
        """
        creator = GitHubIssueCreator(config)
        
        assert creator.state['hourly_count'] == 0
        assert creator.state['daily_count'] == 0
        assert creator.state['reported_errors'] == {}
    
    def test_load_state_existing(self, config, temp_state_file):
        """
        GIVEN: Existing state file
        WHEN: Loading state
        THEN: Should load existing state
        """
        # Create state file
        existing_state = {
            'reported_errors': {'hash1': datetime.now().isoformat()},
            'hourly_count': 5,
            'daily_count': 10,
            'last_hour_reset': datetime.now().isoformat(),
            'last_day_reset': datetime.now().isoformat(),
        }
        with open(temp_state_file, 'w') as f:
            json.dump(existing_state, f)
        
        creator = GitHubIssueCreator(config)
        
        assert creator.state['hourly_count'] == 5
        assert creator.state['daily_count'] == 10
        assert 'hash1' in creator.state['reported_errors']
    
    def test_get_error_signature(self, config):
        """
        GIVEN: An error and context
        WHEN: Generating error signature
        THEN: Should return consistent hash
        """
        creator = GitHubIssueCreator(config)
        
        error = ValueError("Test error")
        context = {'stack_trace': 'line 1\nline 2\nline 3'}
        
        sig1 = creator._get_error_signature(error, context)
        sig2 = creator._get_error_signature(error, context)
        
        assert sig1 == sig2
        assert isinstance(sig1, str)
        assert len(sig1) == 64  # SHA256 hash length
    
    def test_is_duplicate(self, config):
        """
        GIVEN: Previously reported error
        WHEN: Checking for duplicates
        THEN: Should identify duplicates correctly
        """
        creator = GitHubIssueCreator(config)
        
        # Recent error (should be duplicate)
        recent_sig = 'test_sig_1'
        creator.state['reported_errors'][recent_sig] = datetime.now().isoformat()
        assert creator._is_duplicate(recent_sig) is True
        
        # Old error (should not be duplicate)
        old_sig = 'test_sig_2'
        old_time = datetime.now() - timedelta(hours=25)
        creator.state['reported_errors'][old_sig] = old_time.isoformat()
        assert creator._is_duplicate(old_sig) is False
        
        # New error (should not be duplicate)
        new_sig = 'test_sig_3'
        assert creator._is_duplicate(new_sig) is False
    
    def test_check_rate_limits(self, config):
        """
        GIVEN: Different rate limit states
        WHEN: Checking rate limits
        THEN: Should enforce limits correctly
        """
        creator = GitHubIssueCreator(config)
        
        # Within limits
        creator.state['hourly_count'] = 5
        creator.state['daily_count'] = 20
        assert creator._check_rate_limits() is True
        
        # Hourly limit exceeded
        creator.state['hourly_count'] = 10
        assert creator._check_rate_limits() is False
        
        # Daily limit exceeded
        creator.state['hourly_count'] = 5
        creator.state['daily_count'] = 50
        assert creator._check_rate_limits() is False
    
    def test_format_issue_title(self, config):
        """
        GIVEN: An error and context
        WHEN: Formatting issue title
        THEN: Should create appropriate title
        """
        creator = GitHubIssueCreator(config)
        
        error = ValueError("Test error message")
        context = {'source': 'MCP Server'}
        
        title = creator._format_issue_title(error, context)
        
        assert '[Auto-Report]' in title
        assert 'ValueError' in title
        assert 'MCP Server' in title
        assert 'Test error message' in title
    
    def test_format_issue_body(self, config):
        """
        GIVEN: An error with full context
        WHEN: Formatting issue body
        THEN: Should include all relevant information
        """
        creator = GitHubIssueCreator(config)
        
        error = ValueError("Test error")
        context = {
            'source': 'MCP Server',
            'timestamp': '2024-01-01T00:00:00',
            'stack_trace': 'Traceback...',
            'environment': {
                'python_version': '3.12.0',
                'platform': 'Linux',
                'os': 'posix',
            },
            'logs': 'Recent log output...',
            'additional_info': 'Extra context',
        }
        
        body = creator._format_issue_body(error, context)
        
        assert '# Automatic Error Report' in body
        assert 'ValueError' in body
        assert 'MCP Server' in body
        assert 'Traceback...' in body
        assert '3.12.0' in body
        assert 'Recent log output...' in body
        assert 'Extra context' in body
    
    @patch('ipfs_datasets_py.error_reporting.issue_creator.requests')
    def test_create_issue_success(self, mock_requests, config):
        """
        GIVEN: Valid error and configuration
        WHEN: Creating GitHub issue
        THEN: Should successfully create issue
        """
        # Mock successful API response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'html_url': 'https://github.com/test-owner/test-repo/issues/1'
        }
        mock_requests.post.return_value = mock_response
        
        creator = GitHubIssueCreator(config)
        error = ValueError("Test error")
        
        issue_url = creator.create_issue(error)
        
        assert issue_url == 'https://github.com/test-owner/test-repo/issues/1'
        assert creator.state['hourly_count'] == 1
        assert creator.state['daily_count'] == 1
    
    @patch('ipfs_datasets_py.error_reporting.issue_creator.requests')
    def test_create_issue_duplicate(self, mock_requests, config):
        """
        GIVEN: Duplicate error
        WHEN: Creating GitHub issue
        THEN: Should skip creating issue
        """
        creator = GitHubIssueCreator(config)
        error = ValueError("Test error")
        
        # Create issue first time
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {'html_url': 'https://github.com/test/issues/1'}
        mock_requests.post.return_value = mock_response
        
        first_url = creator.create_issue(error)
        assert first_url is not None
        
        # Try to create same issue again
        second_url = creator.create_issue(error)
        assert second_url is None
    
    @patch('ipfs_datasets_py.error_reporting.issue_creator.requests')
    def test_create_issue_rate_limited(self, mock_requests, config):
        """
        GIVEN: Rate limit exceeded
        WHEN: Creating GitHub issue
        THEN: Should skip creating issue
        """
        creator = GitHubIssueCreator(config)
        creator.state['hourly_count'] = 10  # At limit
        
        error = ValueError("Test error")
        issue_url = creator.create_issue(error)
        
        assert issue_url is None
        mock_requests.post.assert_not_called()
    
    def test_create_issue_disabled(self, config):
        """
        GIVEN: Error reporting disabled
        WHEN: Creating GitHub issue
        THEN: Should skip creating issue
        """
        config.enabled = False
        creator = GitHubIssueCreator(config)
        
        error = ValueError("Test error")
        issue_url = creator.create_issue(error)
        
        assert issue_url is None
