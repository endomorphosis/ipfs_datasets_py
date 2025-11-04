#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test GitHub CLI and Copilot CLI Caching

Tests for query caching functionality in GitHub CLI and Copilot CLI utilities.
"""

import tempfile
import time
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


class TestGitHubCLICaching:
    """Test suite for GitHub CLI caching functionality."""
    
    def test_github_cli_cache_initialization(self):
        """
        GIVEN GitHub CLI initialization parameters
        WHEN creating a GitHubCLI instance with caching enabled
        THEN it should initialize cache correctly
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(
                install_dir=tmpdir,
                enable_cache=True,
                cache_maxsize=50,
                cache_ttl=120
            )
            
            assert cli.cache is not None
            assert cli.cache.maxsize == 50
            assert cli.cache.ttl == 120
    
    def test_github_cli_cache_disabled(self):
        """
        GIVEN GitHub CLI with caching disabled
        WHEN creating a GitHubCLI instance
        THEN cache should be None
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir, enable_cache=False)
            
            assert cli.cache is None
    
    def test_github_cli_is_cacheable_command(self):
        """
        GIVEN various GitHub CLI commands
        WHEN checking if they are cacheable
        THEN it should identify read-only commands correctly
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir)
            
            # Cacheable commands
            assert cli._is_cacheable_command(['repo', 'list']) is True
            assert cli._is_cacheable_command(['repo', 'view']) is True
            assert cli._is_cacheable_command(['auth', 'status']) is True
            assert cli._is_cacheable_command(['--version']) is True
            assert cli._is_cacheable_command(['pr', 'list']) is True
            
            # Non-cacheable commands
            assert cli._is_cacheable_command(['repo', 'create']) is False
            assert cli._is_cacheable_command(['pr', 'create']) is False
            assert cli._is_cacheable_command(['auth', 'login']) is False
    
    @patch('subprocess.run')
    def test_github_cli_cache_hit(self, mock_run):
        """
        GIVEN a cached GitHub CLI query
        WHEN executing the same query again
        THEN it should return cached result without calling subprocess
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        # Mock subprocess result
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir, enable_cache=True)
            
            # Create a fake gh executable
            cli.cli_executable.parent.mkdir(parents=True, exist_ok=True)
            cli.cli_executable.touch()
            cli.cli_executable.chmod(0o755)
            
            # First call - should execute command
            result1 = cli.execute(['repo', 'list'])
            assert mock_run.call_count == 1
            assert result1.stdout == "test output"
            
            # Second call - should use cache
            result2 = cli.execute(['repo', 'list'])
            assert mock_run.call_count == 1  # Not called again
            assert result2.stdout == "test output"
            
            # Check cache stats
            stats = cli.get_cache_stats()
            assert stats is not None
            assert stats['hits'] == 1
            assert stats['sets'] == 1
    
    @patch('subprocess.run')
    def test_github_cli_cache_miss_different_args(self, mock_run):
        """
        GIVEN cached GitHub CLI queries
        WHEN executing with different arguments
        THEN it should not use cache
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir, enable_cache=True)
            
            cli.cli_executable.parent.mkdir(parents=True, exist_ok=True)
            cli.cli_executable.touch()
            cli.cli_executable.chmod(0o755)
            
            # Different commands should not use cache
            cli.execute(['repo', 'list', '--limit', '10'])
            cli.execute(['repo', 'list', '--limit', '20'])
            
            assert mock_run.call_count == 2
    
    def test_github_cli_cache_clear(self):
        """
        GIVEN a GitHub CLI with cached results
        WHEN clearing the cache
        THEN all cached entries should be removed
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir, enable_cache=True)
            
            # Manually add to cache
            cli.cache.set("test_key", "test_value")
            assert cli.cache.get("test_key") == "test_value"
            
            # Clear cache
            cli.clear_cache()
            assert cli.cache.get("test_key") is None
    
    @patch('subprocess.run')
    def test_github_cli_cache_bypass(self, mock_run):
        """
        GIVEN a cached GitHub CLI
        WHEN executing with use_cache=False
        THEN it should bypass cache
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir, enable_cache=True)
            
            cli.cli_executable.parent.mkdir(parents=True, exist_ok=True)
            cli.cli_executable.touch()
            cli.cli_executable.chmod(0o755)
            
            # First call with caching
            cli.execute(['repo', 'list'])
            
            # Second call bypassing cache
            cli.execute(['repo', 'list'], use_cache=False)
            
            # Should have called subprocess twice
            assert mock_run.call_count == 2


class TestCopilotCLICaching:
    """Test suite for Copilot CLI caching functionality."""
    
    def test_copilot_cli_cache_initialization(self):
        """
        GIVEN Copilot CLI initialization parameters
        WHEN creating a CopilotCLI instance with caching enabled
        THEN it should initialize cache correctly
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            
            cli = CopilotCLI(
                enable_cache=True,
                cache_maxsize=75,
                cache_ttl=180
            )
            
            assert cli.cache is not None
            assert cli.cache.maxsize == 75
            assert cli.cache.ttl == 180
    
    def test_copilot_cli_cache_disabled(self):
        """
        GIVEN Copilot CLI with caching disabled
        WHEN creating a CopilotCLI instance
        THEN cache should be None
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            
            cli = CopilotCLI(enable_cache=False)
            
            assert cli.cache is None
    
    @patch('subprocess.run')
    def test_copilot_explain_cache_hit(self, mock_run):
        """
        GIVEN a cached Copilot code explanation
        WHEN requesting the same explanation again
        THEN it should return cached result
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        # Mock subprocess result
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "This code prints hello world"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._check_installed') as mock_check:
                mock_check.return_value = True
                
                cli = CopilotCLI(enable_cache=True)
                
                code = "print('hello world')"
                
                # First call
                result1 = cli.explain_code(code)
                assert mock_run.call_count == 1
                assert result1['success'] is True
                
                # Second call - should use cache
                result2 = cli.explain_code(code)
                assert mock_run.call_count == 1  # Not called again
                assert result2['success'] is True
                
                # Check cache stats
                stats = cli.get_cache_stats()
                assert stats is not None
                assert stats['hits'] == 1
    
    @patch('subprocess.run')
    def test_copilot_suggest_cache_hit(self, mock_run):
        """
        GIVEN a cached Copilot command suggestion
        WHEN requesting the same suggestion again
        THEN it should return cached result
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "ls -la"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._check_installed') as mock_check:
                mock_check.return_value = True
                
                cli = CopilotCLI(enable_cache=True)
                
                description = "list files with details"
                
                # First call
                result1 = cli.suggest_command(description)
                assert mock_run.call_count == 1
                
                # Second call - should use cache
                result2 = cli.suggest_command(description)
                assert mock_run.call_count == 1
                
                stats = cli.get_cache_stats()
                assert stats['hits'] == 1
    
    @patch('subprocess.run')
    def test_copilot_git_suggest_cache_hit(self, mock_run):
        """
        GIVEN a cached Copilot Git suggestion
        WHEN requesting the same suggestion again
        THEN it should return cached result
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "git commit -am 'message'"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._check_installed') as mock_check:
                mock_check.return_value = True
                
                cli = CopilotCLI(enable_cache=True)
                
                description = "commit all changes"
                
                # First call
                result1 = cli.suggest_git_command(description)
                assert mock_run.call_count == 1
                
                # Second call - should use cache
                result2 = cli.suggest_git_command(description)
                assert mock_run.call_count == 1
                
                stats = cli.get_cache_stats()
                assert stats['hits'] == 1
    
    def test_copilot_cache_clear(self):
        """
        GIVEN a Copilot CLI with cached results
        WHEN clearing the cache
        THEN all cached entries should be removed
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            
            cli = CopilotCLI(enable_cache=True)
            
            # Manually add to cache
            cli.cache.set("test_key", "test_value")
            assert cli.cache.get("test_key") == "test_value"
            
            # Clear cache
            cli.clear_cache()
            assert cli.cache.get("test_key") is None
    
    @patch('subprocess.run')
    def test_copilot_cache_bypass(self, mock_run):
        """
        GIVEN a cached Copilot CLI
        WHEN executing with use_cache=False
        THEN it should bypass cache
        """
        from ipfs_datasets_py.utils.copilot_cli import CopilotCLI
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "result"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._find_gh_cli') as mock_find:
            mock_find.return_value = Path('/usr/bin/gh')
            with patch('ipfs_datasets_py.utils.copilot_cli.CopilotCLI._check_installed') as mock_check:
                mock_check.return_value = True
                
                cli = CopilotCLI(enable_cache=True)
                
                code = "test code"
                
                # First call with caching
                cli.explain_code(code)
                
                # Second call bypassing cache
                cli.explain_code(code, use_cache=False)
                
                # Should have called subprocess twice
                assert mock_run.call_count == 2


class TestCachingIntegration:
    """Integration tests for caching across both CLI tools."""
    
    def test_cache_stats_tracking(self):
        """
        GIVEN CLI tools with caching enabled
        WHEN performing various operations
        THEN cache statistics should be tracked correctly
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir, enable_cache=True)
            
            # Manually simulate cache operations
            cli.cache.set("key1", "value1")
            cli.cache.set("key2", "value2")
            
            cli.cache.get("key1")  # Hit
            cli.cache.get("key1")  # Hit
            cli.cache.get("key3")  # Miss
            
            stats = cli.get_cache_stats()
            
            assert stats['sets'] == 2
            assert stats['hits'] == 2
            assert stats['misses'] == 1
            assert stats['hit_rate'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
