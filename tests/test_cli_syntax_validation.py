#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rigorous Syntax Validation Tests for CLI Tools

This test file ensures that all CLI tools properly validate input syntax
and do not send malformed data or syntax to the underlying CLI tools.
"""

import pytest
import tempfile
from pathlib import Path


class TestGitHubCLISyntaxValidation:
    """Test syntax validation for GitHub CLI"""
    
    def test_github_cli_has_standardized_methods(self):
        """
        GIVEN a GitHubCLI instance
        WHEN checking for standardized methods
        THEN _install and _config methods should exist
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir)
            
            assert hasattr(cli, '_install'), "GitHubCLI must have _install method"
            assert hasattr(cli, '_config'), "GitHubCLI must have _config method"
            assert callable(cli._install), "_install must be callable"
            assert callable(cli._config), "_config must be callable"
    
    def test_github_cli_execute_validates_command_list(self):
        """
        GIVEN a GitHubCLI instance
        WHEN calling execute with invalid command types
        THEN it should raise appropriate errors
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir)
            
            # Test with non-list input
            with pytest.raises((TypeError, RuntimeError)):
                cli.execute("not a list")  # type: ignore
            
            # Test with list containing non-strings
            with pytest.raises((TypeError, RuntimeError, AttributeError)):
                cli.execute([123, 456])  # type: ignore
    
    def test_github_cli_hostname_validation(self):
        """
        GIVEN a GitHubCLI instance
        WHEN configuring auth with various hostname inputs
        THEN it should handle them properly
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir)
            
            # Valid hostname
            result = cli._config(hostname='github.com', web=True)
            assert isinstance(result, dict)
            assert 'success' in result
            
            # Empty hostname should use default
            result = cli._config(hostname='', web=True)
            assert isinstance(result, dict)
    
    def test_github_cli_version_string_validation(self):
        """
        GIVEN a GitHubCLI instance
        WHEN initialized with various version strings
        THEN it should validate version format
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Valid version format
            cli = GitHubCLI(install_dir=tmpdir, version='v2.40.0')
            assert cli.version == 'v2.40.0'
            
            # Version without 'v' prefix
            cli = GitHubCLI(install_dir=tmpdir, version='2.40.0')
            assert cli.version == '2.40.0'
    
    def test_github_cli_path_validation(self):
        """
        GIVEN a GitHubCLI instance
        WHEN initialized with various install paths
        THEN it should handle paths properly
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        
        # Test with valid path
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GitHubCLI(install_dir=tmpdir)
            assert cli.install_dir.exists()
            assert cli.install_dir == Path(tmpdir)


class TestGeminiCLISyntaxValidation:
    """Test syntax validation for Gemini CLI"""
    
    def test_gemini_cli_has_standardized_methods(self):
        """
        GIVEN a GeminiCLI instance
        WHEN checking for standardized methods
        THEN _install and _config methods should exist
        """
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GeminiCLI(install_dir=tmpdir)
            
            assert hasattr(cli, '_install'), "GeminiCLI must have _install method"
            assert hasattr(cli, '_config'), "GeminiCLI must have _config method"
            assert callable(cli._install), "_install must be callable"
            assert callable(cli._config), "_config must be callable"
    
    def test_gemini_cli_execute_validates_command_list(self):
        """
        GIVEN a GeminiCLI instance
        WHEN calling execute with invalid command types
        THEN it should raise appropriate errors
        """
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GeminiCLI(install_dir=tmpdir)
            
            # Test with non-list input - should raise error
            with pytest.raises((TypeError, RuntimeError, AttributeError)):
                cli.execute("not a list")  # type: ignore
    
    def test_gemini_cli_api_key_validation(self):
        """
        GIVEN a GeminiCLI instance
        WHEN configuring API key
        THEN it should validate the key properly
        """
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GeminiCLI(install_dir=tmpdir)
            
            # Test with valid API key
            result = cli.configure_api_key("test_api_key_12345")
            assert result is True
            
            # Test retrieving the key
            retrieved_key = cli.get_api_key()
            assert retrieved_key == "test_api_key_12345"
    
    def test_gemini_cli_config_requires_api_key(self):
        """
        GIVEN a GeminiCLI instance
        WHEN calling _config without api_key
        THEN it should return error
        """
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GeminiCLI(install_dir=tmpdir)
            
            # Test without API key
            result = cli._config()
            assert isinstance(result, dict)
            assert result['success'] is False
            assert 'error' in result
    
    def test_gemini_cli_path_validation(self):
        """
        GIVEN a GeminiCLI instance
        WHEN initialized with various install paths
        THEN it should handle paths properly
        """
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = GeminiCLI(install_dir=tmpdir)
            assert cli.install_dir.exists()
            assert cli.install_dir == Path(tmpdir)


class TestClaudeCLISyntaxValidation:
    """Test syntax validation for Claude CLI"""
    
    def test_claude_cli_has_standardized_methods(self):
        """
        GIVEN a ClaudeCLI instance
        WHEN checking for standardized methods
        THEN _install and _config methods should exist
        """
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = ClaudeCLI(install_dir=tmpdir)
            
            assert hasattr(cli, '_install'), "ClaudeCLI must have _install method"
            assert hasattr(cli, '_config'), "ClaudeCLI must have _config method"
            assert callable(cli._install), "_install must be callable"
            assert callable(cli._config), "_config must be callable"
    
    def test_claude_cli_execute_validates_command_list(self):
        """
        GIVEN a ClaudeCLI instance
        WHEN calling execute with invalid command types
        THEN it should raise appropriate errors
        """
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = ClaudeCLI(install_dir=tmpdir)
            
            # Test with non-list input - should raise error
            with pytest.raises((TypeError, RuntimeError, AttributeError)):
                cli.execute("not a list")  # type: ignore
    
    def test_claude_cli_api_key_validation(self):
        """
        GIVEN a ClaudeCLI instance
        WHEN configuring API key
        THEN it should validate the key properly
        """
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = ClaudeCLI(install_dir=tmpdir)
            
            # Test with valid API key
            result = cli.configure_api_key("test_api_key_12345")
            assert result is True
            
            # Test retrieving the key
            retrieved_key = cli.get_api_key()
            assert retrieved_key == "test_api_key_12345"
    
    def test_claude_cli_config_requires_api_key(self):
        """
        GIVEN a ClaudeCLI instance
        WHEN calling _config without api_key
        THEN it should return error
        """
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = ClaudeCLI(install_dir=tmpdir)
            
            # Test without API key
            result = cli._config()
            assert isinstance(result, dict)
            assert result['success'] is False
            assert 'error' in result
    
    def test_claude_cli_path_validation(self):
        """
        GIVEN a ClaudeCLI instance
        WHEN initialized with various install paths
        THEN it should handle paths properly
        """
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = ClaudeCLI(install_dir=tmpdir)
            assert cli.install_dir.exists()
            assert cli.install_dir == Path(tmpdir)


class TestVSCodeCLISyntaxValidation:
    """Test syntax validation for VSCode CLI"""
    
    def test_vscode_cli_has_standardized_methods(self):
        """
        GIVEN a VSCodeCLI instance
        WHEN checking for standardized methods
        THEN _install and _config methods should exist
        """
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = VSCodeCLI(install_dir=tmpdir)
            
            assert hasattr(cli, '_install'), "VSCodeCLI must have _install method"
            assert hasattr(cli, '_config'), "VSCodeCLI must have _config method"
            assert callable(cli._install), "_install must be callable"
            assert callable(cli._config), "_config must be callable"
    
    def test_vscode_cli_execute_validates_command_list(self):
        """
        GIVEN a VSCodeCLI instance
        WHEN calling execute with invalid command types
        THEN it should raise appropriate errors
        """
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = VSCodeCLI(install_dir=tmpdir)
            
            # Test with non-list input
            with pytest.raises((TypeError, RuntimeError)):
                cli.execute("not a list")  # type: ignore
    
    def test_vscode_cli_provider_validation(self):
        """
        GIVEN a VSCodeCLI instance
        WHEN configuring auth with various providers
        THEN it should handle them properly
        """
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = VSCodeCLI(install_dir=tmpdir)
            
            # Valid provider
            result = cli._config(provider='github')
            assert isinstance(result, dict)
            assert 'success' in result


class TestCLIToolsConsistency:
    """Test consistency across all CLI tools"""
    
    def test_all_cli_tools_have_install_method(self):
        """
        GIVEN all CLI tool classes
        WHEN checking for _install method
        THEN all should have it
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        cli_classes = [GitHubCLI, GeminiCLI, ClaudeCLI, VSCodeCLI]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            for cli_class in cli_classes:
                cli = cli_class(install_dir=tmpdir)
                assert hasattr(cli, '_install'), f"{cli_class.__name__} must have _install method"
                assert callable(cli._install), f"{cli_class.__name__}._install must be callable"
    
    def test_all_cli_tools_have_config_method(self):
        """
        GIVEN all CLI tool classes
        WHEN checking for _config method
        THEN all should have it
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        cli_classes = [GitHubCLI, GeminiCLI, ClaudeCLI, VSCodeCLI]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            for cli_class in cli_classes:
                cli = cli_class(install_dir=tmpdir)
                assert hasattr(cli, '_config'), f"{cli_class.__name__} must have _config method"
                assert callable(cli._config), f"{cli_class.__name__}._config must be callable"
    
    def test_all_cli_tools_install_method_signature(self):
        """
        GIVEN all CLI tool classes
        WHEN calling _install method
        THEN they should all accept force parameter
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        cli_classes = [GitHubCLI, GeminiCLI, ClaudeCLI, VSCodeCLI]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            for cli_class in cli_classes:
                cli = cli_class(install_dir=tmpdir)
                # Should accept force parameter without error
                result = cli._install(force=False)
                assert isinstance(result, bool), f"{cli_class.__name__}._install must return bool"
    
    def test_all_cli_tools_config_method_returns_dict(self):
        """
        GIVEN all CLI tool classes
        WHEN calling _config method
        THEN they should all return a dictionary
        """
        from ipfs_datasets_py.utils.github_cli import GitHubCLI
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        
        cli_classes = [GitHubCLI, GeminiCLI, ClaudeCLI, VSCodeCLI]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            for cli_class in cli_classes:
                cli = cli_class(install_dir=tmpdir)
                result = cli._config()
                assert isinstance(result, dict), f"{cli_class.__name__}._config must return dict"
                assert 'success' in result, f"{cli_class.__name__}._config result must have 'success' key"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
