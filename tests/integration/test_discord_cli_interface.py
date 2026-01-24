"""
Integration tests for Discord CLI interface stability.

These tests verify that the Discord integration continues to work correctly
even if the external DiscordChatExporter CLI interface changes. This helps
identify whether issues originate from:
1. External CLI changes (DiscordChatExporter updates)
2. Application logic errors
3. User input/configuration errors
"""
import pytest
import asyncio
import os
import platform
import tempfile
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter
from ipfs_datasets_py.multimedia.discord_wrapper import DiscordWrapper, DISCORD_AVAILABLE
from ipfs_datasets_py.discord_cli import main as discord_cli_main


class TestDiscordChatExporterCLIInterface:
    """Test the external CLI interface stability."""
    
    def test_cli_help_command_structure(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: Help command is executed
        THEN: Should return expected command structure
        
        Purpose: Detect if CLI command structure has changed
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            # Test help command
            result = exporter.execute(['--help'], timeout=10)
            
            # Verify basic command structure hasn't changed
            assert result.returncode == 0
            help_text = result.stdout.lower()
            
            # These commands should always exist
            expected_commands = ['export', 'exportdm', 'exportguild', 'guilds', 'channels', 'dm']
            for cmd in expected_commands:
                assert cmd in help_text, f"Expected command '{cmd}' not found in help output"
    
    def test_cli_version_command_format(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: Version command is executed
        THEN: Should return version in expected format
        
        Purpose: Detect version string format changes
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            version = exporter.get_version()
            
            # Verify version format (should be numeric like "2.43.1")
            assert version is not None
            assert len(version) > 0
            # Check for semver-like format (at least has a digit and dot)
            assert any(c.isdigit() for c in version)
            assert '.' in version or version.replace('.', '').isdigit()
    
    def test_cli_export_command_parameters(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: Export command parameters are checked
        THEN: Required parameters should be documented
        
        Purpose: Verify export command interface hasn't changed
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            # Test export help
            result = exporter.execute(['export', '--help'], timeout=10)
            
            # Should require channel ID and token
            help_text = result.stdout.lower()
            assert '-c' in help_text or '--channel' in help_text
            assert '-t' in help_text or '--token' in help_text
            assert '-f' in help_text or '--format' in help_text
            assert '-o' in help_text or '--output' in help_text
    
    def test_cli_exportdm_command_exists(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: exportdm command is checked
        THEN: Command should exist and have proper parameters
        
        Purpose: Verify exportdm command (critical for DM functionality)
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            # Test exportdm help
            result = exporter.execute(['exportdm', '--help'], timeout=10)
            
            # exportdm should exist
            assert result.returncode == 0
            help_text = result.stdout.lower()
            
            # Should require token and support format/output
            assert '-t' in help_text or '--token' in help_text
            assert '-f' in help_text or '--format' in help_text
    
    def test_cli_format_options_available(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: Format options are checked
        THEN: All expected formats should be available
        
        Purpose: Verify supported export formats haven't changed
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            result = exporter.execute(['export', '--help'], timeout=10)
            help_text = result.stdout.lower()
            
            # These formats are critical for functionality
            expected_formats = ['json', 'html', 'csv', 'plaintext']
            for fmt in expected_formats:
                assert fmt in help_text, f"Format '{fmt}' not found in help"
    
    def test_cli_error_handling_invalid_token(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: Invalid token is provided
        THEN: Should return appropriate error
        
        Purpose: Verify error responses haven't changed
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            # Test with obviously invalid token
            result = exporter.execute([
                'guilds',
                '-t', 'INVALID_TOKEN_123'
            ], timeout=15)
            
            # Should fail with non-zero exit code
            assert result.returncode != 0
            # Error should mention authentication or token
            error_text = result.stderr.lower()
            assert any(word in error_text for word in ['token', 'auth', 'unauthorized', 'invalid'])


class TestDiscordWrapperCLIIntegration:
    """Test that wrapper correctly interfaces with CLI."""
    
    @pytest.mark.asyncio
    async def test_wrapper_handles_cli_output_format(self):
        """
        GIVEN: DiscordWrapper instance
        WHEN: CLI output is parsed
        THEN: Should correctly parse various output formats
        
        Purpose: Verify output parsing is resilient to format changes
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        wrapper = DiscordWrapper(token="dummy_token", auto_install=False)
        
        # Test list output parsing format
        # Simulate guild list output
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "123456789 | Test Guild\n987654321 | Another Guild"
        mock_result.stderr = ""
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.list_guilds(token="test")
            
            assert result['status'] == 'success'
            assert result['count'] == 2
            assert len(result['guilds']) == 2
    
    @pytest.mark.asyncio
    async def test_wrapper_handles_cli_errors_gracefully(self):
        """
        GIVEN: DiscordWrapper instance
        WHEN: CLI returns error
        THEN: Should return structured error response
        
        Purpose: Verify error handling doesn't break on CLI changes
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        wrapper = DiscordWrapper(token="dummy_token", auto_install=False)
        
        # Simulate CLI error
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Authentication failed: Invalid token"
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.list_guilds(token="test")
            
            assert result['status'] == 'error'
            assert 'error' in result
            assert 'Invalid token' in result['error']
    
    @pytest.mark.asyncio
    async def test_export_dm_uses_correct_cli_command(self):
        """
        GIVEN: DiscordWrapper instance
        WHEN: export_dm is called
        THEN: Should use 'exportdm' CLI command
        
        Purpose: Verify correct CLI command is used for DM export
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapper = DiscordWrapper(
                token="test_token",
                default_output_dir=tmpdir,
                auto_install=False
            )
            
            # Mock the execute method to capture command
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "Export completed"
            mock_result.stderr = ""
            
            captured_commands = []
            
            def capture_execute(cmd, **kwargs):
                captured_commands.append(cmd)
                return mock_result
            
            with patch.object(wrapper.exporter, 'execute', side_effect=capture_execute):
                await wrapper.export_dm(format="Json")
                
                # Verify exportdm command was used
                assert len(captured_commands) == 1
                assert 'exportdm' in captured_commands[0]
                assert '-t' in captured_commands[0]
                assert '-f' in captured_commands[0]
                assert 'Json' in captured_commands[0]


class TestDiscordCLICommands:
    """Test the ipfs-datasets discord CLI commands."""
    
    def test_cli_status_command(self):
        """
        GIVEN: Discord CLI module
        WHEN: status command is run
        THEN: Should return integration status
        
        Purpose: Verify CLI status command works
        """
        result = discord_cli_main(['status'])
        
        # Status should always succeed (returns 0 or handled gracefully)
        assert result in [0, 1]  # May return 1 if not fully configured
    
    def test_cli_install_command_help(self):
        """
        GIVEN: Discord CLI module
        WHEN: install --help is run
        THEN: Should display help without error
        
        Purpose: Verify install command exists
        """
        # This should not raise an exception
        try:
            result = discord_cli_main(['install', '--help'])
            # Help should exit with 0
            assert result == 0
        except SystemExit as e:
            # argparse may call sys.exit for help
            assert e.code == 0
    
    def test_cli_export_command_requires_channel_id(self):
        """
        GIVEN: Discord CLI module
        WHEN: export command is run without channel ID
        THEN: Should display error or usage
        
        Purpose: Verify input validation
        """
        # Should fail without channel ID; argparse will call sys.exit
        with pytest.raises(SystemExit) as excinfo:
            discord_cli_main(['export'])
        assert excinfo.value.code != 0  # Should fail with non-zero exit code
    
    def test_cli_guilds_command_validates_token(self):
        """
        GIVEN: Discord CLI module
        WHEN: guilds command is run without token
        THEN: Should handle missing token appropriately
        
        Purpose: Verify token validation
        """
        # Clear environment variable for this test
        old_token = os.environ.get('DISCORD_TOKEN')
        if old_token:
            del os.environ['DISCORD_TOKEN']
        
        try:
            result = discord_cli_main(['guilds'])
            # Should fail or return error (not crash)
            assert result in [0, 1]
        finally:
            # Restore token
            if old_token:
                os.environ['DISCORD_TOKEN'] = old_token


class TestMCPToolsCLIIntegration:
    """Test MCP tools correctly use CLI."""
    
    @pytest.mark.asyncio
    async def test_mcp_export_channel_validates_inputs(self):
        """
        GIVEN: MCP discord_export_channel function
        WHEN: Called with invalid inputs
        THEN: Should return error response (not crash)
        
        Purpose: Verify input validation prevents CLI errors
        """
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_export_channel
        
        # Test with missing token
        result = await discord_export_channel(
            channel_id="123456789",
            token=None  # No token
        )
        
        assert result['status'] == 'error'
        assert 'token' in result['error'].lower()
    
    @pytest.mark.asyncio
    async def test_mcp_export_dm_channels_uses_native_command(self):
        """
        GIVEN: MCP discord_export_dm_channels function
        WHEN: Called
        THEN: Should use native exportdm command
        
        Purpose: Verify correct CLI command is invoked
        """
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_export_dm_channels
        from unittest.mock import AsyncMock
        
        # Mock the wrapper to verify command usage
        with patch('ipfs_datasets_py.mcp_server.tools.discord_tools.discord_export.create_discord_wrapper') as mock_create:
            mock_wrapper = Mock()
            
            # Use AsyncMock for proper async function mocking
            mock_wrapper.export_dm = AsyncMock(
                return_value={'status': 'success', 'dm_channels_exported': 5}
            )
            mock_create.return_value = mock_wrapper
            
            result = await discord_export_dm_channels(token="test_token")
            
            # Verify export_dm was called and result is correct
            mock_wrapper.export_dm.assert_called_once()
            assert result['status'] == 'success'
            assert result['dm_channels_exported'] == 5
    
    @pytest.mark.asyncio
    async def test_mcp_list_guilds_parses_cli_output(self):
        """
        GIVEN: MCP discord_list_guilds function
        WHEN: CLI returns guild list
        THEN: Should correctly parse output
        
        Purpose: Verify output parsing is robust
        """
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_list_guilds
        
        # Test with mocked wrapper
        with patch('ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list.create_discord_wrapper') as mock_create:
            mock_wrapper = Mock()
            mock_wrapper.list_guilds = asyncio.coroutine(
                lambda **kwargs: {
                    'status': 'success',
                    'guilds': [
                        {'id': '123', 'name': 'Test Guild'}
                    ],
                    'count': 1
                }
            )
            mock_create.return_value = mock_wrapper
            
            result = await discord_list_guilds(token="test_token")
            
            assert result['status'] == 'success'
            assert result['count'] == 1
            assert len(result['guilds']) == 1


class TestCLIVersionCompatibility:
    """Test compatibility across different CLI versions."""
    
    def test_cli_version_parsing(self):
        """
        GIVEN: DiscordChatExporter instance
        WHEN: Version is retrieved
        THEN: Should parse version correctly
        
        Purpose: Verify version detection works across versions
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            version = exporter.get_version()
            
            # Version should be parseable
            assert version is not None
            # Should be able to compare versions (basic check)
            parts = version.split('.')
            assert len(parts) >= 2  # At least major.minor
            assert all(part.replace('-', '').replace('+', '').replace('beta', '').replace('alpha', '').strip().replace('.', '').isdigit() or part.isdigit() for part in parts if part)
    
    def test_cli_command_backwards_compatibility(self):
        """
        GIVEN: DiscordChatExporter of any version
        WHEN: Core commands are tested
        THEN: Essential commands should exist
        
        Purpose: Verify core commands remain stable across versions
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            # These commands should exist in all versions
            essential_commands = ['export', 'guilds', 'channels']
            
            for cmd in essential_commands:
                result = exporter.execute([cmd, '--help'], timeout=10)
                assert result.returncode == 0, f"Essential command '{cmd}' failed"


class TestErrorOriginDiagnostics:
    """Tests to help identify where errors originate."""
    
    def test_token_validation_at_wrapper_level(self):
        """
        GIVEN: Invalid token
        WHEN: Passed to wrapper
        THEN: Should be caught at wrapper level before CLI
        
        Purpose: Identify if error is from validation or CLI
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        wrapper = DiscordWrapper(token=None, auto_install=False)
        
        # Should catch missing token before calling CLI
        with pytest.raises(ValueError, match="No Discord token"):
            wrapper._ensure_token()
    
    def test_format_validation_at_wrapper_level(self):
        """
        GIVEN: Invalid format
        WHEN: Passed to wrapper
        THEN: Should be caught at wrapper level before CLI
        
        Purpose: Identify if error is from validation or CLI
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        # Should catch invalid format at initialization
        with pytest.raises(ValueError, match="Invalid format"):
            DiscordWrapper(default_format="InvalidFormat")
    
    @pytest.mark.asyncio
    async def test_cli_timeout_handling(self):
        """
        GIVEN: CLI operation that times out
        WHEN: Timeout occurs
        THEN: Should return timeout error (not hang)
        
        Purpose: Identify timeout issues
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        wrapper = DiscordWrapper(token="dummy_token", auto_install=False)
        
        # Mock a timeout scenario
        def timeout_execute(cmd, **kwargs):
            import time
            time.sleep(kwargs.get('timeout', 30) + 1)
            result = Mock()
            result.returncode = -1
            result.stdout = ""
            result.stderr = "Timeout"
            return result
        
        with patch.object(wrapper.exporter, 'execute', side_effect=TimeoutError("Command timed out")):
            try:
                result = await wrapper.list_guilds(token="test")
                # Should return error, not crash
                assert result['status'] == 'error'
            except TimeoutError:
                # Acceptable - timeout was raised explicitly
                pass
    
    def test_environment_variable_loading(self):
        """
        GIVEN: DISCORD_TOKEN environment variable
        WHEN: Wrapper is initialized without token
        THEN: Should load token from environment
        
        Purpose: Verify environment variable integration
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        # Set test token in environment
        test_token = "TEST_TOKEN_12345"
        os.environ['DISCORD_TOKEN'] = test_token
        
        try:
            wrapper = DiscordWrapper(token=None, auto_install=False)
            
            # Should have loaded token from environment
            assert wrapper.token == test_token
        finally:
            # Clean up
            if 'DISCORD_TOKEN' in os.environ:
                del os.environ['DISCORD_TOKEN']


class TestCLIStabilityMonitoring:
    """Tests that monitor CLI stability over time."""
    
    def test_cli_help_output_structure(self):
        """
        GIVEN: DiscordChatExporter CLI
        WHEN: Help is requested
        THEN: Output should follow expected structure
        
        Purpose: Detect major CLI interface changes
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            result = exporter.execute(['--help'], timeout=10)
            help_text = result.stdout
            
            # Help should contain usage information
            assert 'usage' in help_text.lower() or 'commands' in help_text.lower()
            # Should list available commands
            assert 'export' in help_text.lower()
    
    def test_cli_error_message_format(self):
        """
        GIVEN: DiscordChatExporter CLI with invalid input
        WHEN: Error occurs
        THEN: Error message should be readable
        
        Purpose: Verify error messages remain user-friendly
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            # Trigger error with invalid command
            result = exporter.execute(['invalid_command'], timeout=10)
            
            # Should have error output
            assert result.returncode != 0
            assert len(result.stderr) > 0 or len(result.stdout) > 0
    
    def test_cli_execution_performance(self):
        """
        GIVEN: DiscordChatExporter CLI
        WHEN: Simple command is executed
        THEN: Should complete within reasonable time
        
        Purpose: Detect performance degradation
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            if not exporter.is_installed():
                pytest.skip("DiscordChatExporter not installed")
            
            import time
            start = time.time()
            result = exporter.execute(['--version'], timeout=10)
            duration = time.time() - start
            
            # Version check should be fast (< 5 seconds)
            assert duration < 5, f"Version check took {duration}s, expected < 5s"
            assert result.returncode == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
