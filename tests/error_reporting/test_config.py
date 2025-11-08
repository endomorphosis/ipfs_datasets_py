"""Tests for error reporting configuration."""
import os
import tempfile
from pathlib import Path
import pytest

from ipfs_datasets_py.error_reporting.config import ErrorReportingConfig


class TestErrorReportingConfig:
    """Test error reporting configuration."""
    
    def test_default_config(self):
        """
        GIVEN: No environment variables set
        WHEN: Creating ErrorReportingConfig
        THEN: Default values should be used
        """
        # Save original env vars
        original_env = {
            'ERROR_REPORTING_ENABLED': os.environ.get('ERROR_REPORTING_ENABLED'),
            'GITHUB_TOKEN': os.environ.get('GITHUB_TOKEN'),
        }
        
        try:
            # Clear env vars
            for key in original_env:
                if key in os.environ:
                    del os.environ[key]
            
            config = ErrorReportingConfig()
            
            assert config.enabled is True
            assert config.github_token is None
            assert config.max_issues_per_hour == 10
            assert config.max_issues_per_day == 50
            assert config.dedup_window_hours == 24
            
        finally:
            # Restore env vars
            for key, value in original_env.items():
                if value is not None:
                    os.environ[key] = value
    
    def test_env_var_config(self, monkeypatch):
        """
        GIVEN: Environment variables are set
        WHEN: Creating ErrorReportingConfig
        THEN: Environment variable values should be used
        """
        monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'false')
        monkeypatch.setenv('GITHUB_TOKEN', 'test-token')
        monkeypatch.setenv('ERROR_REPORTING_MAX_PER_HOUR', '5')
        monkeypatch.setenv('ERROR_REPORTING_MAX_PER_DAY', '20')
        
        config = ErrorReportingConfig()
        
        assert config.enabled is False
        assert config.github_token == 'test-token'
        assert config.max_issues_per_hour == 5
        assert config.max_issues_per_day == 20
    
    def test_is_valid(self, monkeypatch):
        """
        GIVEN: Different configuration states
        WHEN: Checking if configuration is valid
        THEN: Should return correct validation status
        """
        # Valid config
        monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'true')
        monkeypatch.setenv('GITHUB_TOKEN', 'test-token')
        config = ErrorReportingConfig()
        assert config.is_valid() is True
        
        # Disabled config
        monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'false')
        config = ErrorReportingConfig()
        assert config.is_valid() is False
        
        # No token config
        monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'true')
        monkeypatch.delenv('GITHUB_TOKEN', raising=False)
        config = ErrorReportingConfig()
        assert config.is_valid() is False
    
    def test_get_repo_owner(self):
        """
        GIVEN: Repository string in different formats
        WHEN: Extracting owner
        THEN: Should return correct owner
        """
        config = ErrorReportingConfig()
        config.github_repo = 'owner/repo'
        assert config.get_repo_owner() == 'owner'
        
        config.github_repo = 'repo'
        assert config.get_repo_owner() == ''
    
    def test_get_repo_name(self):
        """
        GIVEN: Repository string in different formats
        WHEN: Extracting repo name
        THEN: Should return correct repo name
        """
        config = ErrorReportingConfig()
        config.github_repo = 'owner/repo'
        assert config.get_repo_name() == 'repo'
        
        config.github_repo = 'repo'
        assert config.get_repo_name() == 'repo'
    
    def test_state_file_creation(self):
        """
        GIVEN: Fresh configuration
        WHEN: Initializing config
        THEN: State file parent directory should be created
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / 'test_state' / 'error_state.json'
            config = ErrorReportingConfig()
            config.state_file = state_file
            config.__post_init__()
            
            assert config.state_file.parent.exists()
