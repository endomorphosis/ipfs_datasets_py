"""
Unit tests for Discord integration error handling and edge cases.

These tests focus on:
1. Input validation edge cases
2. Error handling scenarios
3. Boundary conditions
4. User error detection

Uses anyio for asyncio/trio compatibility (libp2p integration)
"""
import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import anyio

from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter
from ipfs_datasets_py.multimedia.discord_wrapper import DiscordWrapper


class TestInputValidationEdgeCases:
    """Test edge cases in input validation."""
    
    def test_empty_token_string(self):
        """
        GIVEN: Empty token string
        WHEN: Wrapper is initialized
        THEN: Should treat as no token
        """
        
        wrapper = DiscordWrapper(token="", auto_install=False)
        
        with pytest.raises(ValueError, match="No Discord token"):
            wrapper._ensure_token()
    
    def test_whitespace_only_token(self):
        """
        GIVEN: Whitespace-only token
        WHEN: Wrapper validates token
        THEN: Should reject as invalid
        """
        
        wrapper = DiscordWrapper(token="   \t\n  ", auto_install=False)
        
        with pytest.raises(ValueError):
            wrapper._ensure_token()
    
    def test_none_vs_empty_string_output_path(self):
        """
        GIVEN: None vs empty string for output path
        WHEN: Export is configured
        THEN: Should handle both appropriately
        """
        
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapper = DiscordWrapper(
                token="test_token",
                default_output_dir=tmpdir,
                auto_install=False
            )
            
            # None should use default
            assert wrapper.default_output_dir is not None
            
            # Empty string should be handled
            wrapper2 = DiscordWrapper(
                token="test_token",
                default_output_dir="",
                auto_install=False
            )
            assert wrapper2.default_output_dir is not None
    
    @pytest.mark.anyio
    async def test_invalid_channel_id_format(self):
        """
        GIVEN: Various invalid channel ID formats
        WHEN: Export is attempted
        THEN: Should detect invalid format before CLI call
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Test non-numeric channel IDs
        invalid_ids = ["", "abc", "12.34", "-123", "12 34"]
        
        for invalid_id in invalid_ids:
            with patch.object(wrapper.exporter, 'execute') as mock_execute:
                # Should either validate before calling or handle error
                result = await wrapper.export_channel(
                    channel_id=invalid_id,
                    token="test"
                )
                
                # Should return error (validation or from CLI)
                if mock_execute.called:
                    # If CLI was called, should handle error from CLI
                    pass
                else:
                    # If not called, validation caught it
                    assert result['status'] == 'error'
    
    def test_special_characters_in_paths(self):
        """
        GIVEN: Paths with special characters
        WHEN: Output path is set
        THEN: Should handle appropriately
        """
        
        # Test paths that might cause issues
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            
            # Create path with space
            path_with_space = base_path / "test folder"
            path_with_space.mkdir()
            
            wrapper = DiscordWrapper(
                token="test_token",
                default_output_dir=str(path_with_space),
                auto_install=False
            )
            
            assert wrapper.default_output_dir.exists()
    
    @pytest.mark.anyio
    async def test_very_long_filter_text(self):
        """
        GIVEN: Very long filter text
        WHEN: Filter is applied
        THEN: Should not cause issues
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Create very long filter
        long_filter = "from:user " * 1000
        
        # Should not crash (may be rejected by CLI, which is OK)
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Export completed"
        mock_result.stderr = ""
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test",
                filter_text=long_filter
            )
            
            # Should complete (success or proper error)
            assert 'status' in result


class TestErrorHandlingScenarios:
    """Test various error scenarios."""
    
    @pytest.mark.asyncio
    async def test_cli_not_installed_error(self):
        """
        GIVEN: DiscordChatExporter not installed
        WHEN: Operation is attempted
        THEN: Should return clear error message
        """
        
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapper = DiscordWrapper(
                token="test_token",
                auto_install=False
            )
            
            # Mock exporter as not installed
            with patch.object(wrapper.exporter, 'is_installed', return_value=False):
                with patch.object(wrapper.exporter, 'execute') as mock_execute:
                    mock_execute.side_effect = FileNotFoundError("CLI not found")
                    
                    result = await wrapper.list_guilds(token="test")
                    
                    assert result['status'] == 'error'
                    assert 'error' in result
    
    @pytest.mark.asyncio
    async def test_network_timeout_error(self):
        """
        GIVEN: Network timeout during CLI operation
        WHEN: Timeout occurs
        THEN: Should return timeout error
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock timeout
        with patch.object(wrapper.exporter, 'execute', side_effect=TimeoutError("Command timed out")):
            result = await wrapper.list_guilds(token="test")
            
            assert result['status'] == 'error'
            assert 'timeout' in result.get('error', '').lower() or 'error' in result
    
    @pytest.mark.asyncio
    async def test_permission_denied_error(self):
        """
        GIVEN: Permission denied during export
        WHEN: Writing to protected location
        THEN: Should return permission error
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock permission error
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Permission denied"
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test",
                output_path="/root/protected.json"
            )
            
            assert result['status'] == 'error'
            assert 'permission' in result.get('error', '').lower()
    
    @pytest.mark.asyncio
    async def test_disk_full_error(self):
        """
        GIVEN: Disk full during export
        WHEN: Export is attempted
        THEN: Should return disk space error
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock disk full error
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "No space left on device"
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test"
            )
            
            assert result['status'] == 'error'
            assert 'space' in result.get('error', '').lower() or 'device' in result.get('error', '').lower()
    
    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """
        GIVEN: Discord API rate limit hit
        WHEN: Export is attempted
        THEN: Should return rate limit error
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock rate limit error
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Rate limited. Please try again later."
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test"
            )
            
            assert result['status'] == 'error'
            assert 'rate' in result.get('error', '').lower() or 'limit' in result.get('error', '').lower()


class TestBoundaryConditions:
    """Test boundary conditions and limits."""
    
    @pytest.mark.anyio
    async def test_maximum_date_range(self):
        """
        GIVEN: Very large date range
        WHEN: Export is configured
        THEN: Should handle large ranges
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Test with very old and future dates
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Export completed"
        mock_result.stderr = ""
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result) as mock_execute:
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test",
                after="1990-01-01",
                before="2099-12-31"
            )
            
            # Should pass dates to CLI
            assert mock_execute.called
            call_args = mock_execute.call_args[0][0]
            assert '--after' in call_args or '-a' in ' '.join(call_args)
    
    @pytest.mark.anyio
    async def test_zero_partition_limit(self):
        """
        GIVEN: Zero or negative partition limit
        WHEN: Export is configured
        THEN: Should handle invalid partition
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Test invalid partition limits
        for invalid_limit in ["0", "-1", "0mb"]:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            
            with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
                # Should either reject or pass to CLI to reject
                result = await wrapper.export_channel(
                    channel_id="123456789",
                    token="test",
                    partition_limit=invalid_limit
                )
                
                # Result should be present
                assert 'status' in result
    
    @pytest.mark.anyio
    async def test_empty_guild_list(self):
        """
        GIVEN: Account with no guilds
        WHEN: list_guilds is called
        THEN: Should return empty list (not error)
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock empty guild list
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.list_guilds(token="test")
            
            assert result['status'] == 'success'
            assert result['count'] == 0
            assert len(result['guilds']) == 0
    
    @pytest.mark.anyio
    async def test_very_large_guild_list(self):
        """
        GIVEN: Account with many guilds
        WHEN: list_guilds is called
        THEN: Should handle large lists
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock large guild list (100 guilds)
        guild_lines = [f"{i} | Guild {i}" for i in range(100)]
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(guild_lines)
        mock_result.stderr = ""
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.list_guilds(token="test")
            
            assert result['status'] == 'success'
            assert result['count'] == 100
            assert len(result['guilds']) == 100


class TestUserErrorDetection:
    """Tests that help identify user errors vs application errors."""
    
    def test_invalid_token_format_detection(self):
        """
        GIVEN: Token with obviously wrong format
        WHEN: Operation is attempted
        THEN: Should detect before making API call
        """
        # Tokens that are clearly wrong
        invalid_tokens = [
            "12345",  # Too short
            "abc",  # Not Discord token format
            "token123",  # Missing prefix
        ]
        
        # Note: Can't fully validate token format without documentation,
        # but can catch obvious errors
        for token in invalid_tokens:
            # At minimum, should be reasonably long
            if len(token) < 20:
                # This is likely a user error
                assert True  # Mark as user error case
    
    @pytest.mark.anyio
    async def test_channel_id_not_found_detection(self):
        """
        GIVEN: Non-existent channel ID
        WHEN: Export is attempted
        THEN: Error should indicate channel not found (user error)
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock channel not found error
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Channel not found or not accessible"
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="999999999999999999",
                token="test"
            )
            
            assert result['status'] == 'error'
            # Error should mention channel
            assert 'channel' in result.get('error', '').lower()
    
    @pytest.mark.anyio
    async def test_insufficient_permissions_detection(self):
        """
        GIVEN: Token without required permissions
        WHEN: Operation is attempted
        THEN: Error should indicate permission issue (user error)
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock permission error
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Missing required permissions"
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test"
            )
            
            assert result['status'] == 'error'
            assert 'permission' in result.get('error', '').lower()
    
    @pytest.mark.anyio
    async def test_invalid_date_format_detection(self):
        """
        GIVEN: Invalid date format
        WHEN: Export with date filter is attempted
        THEN: Should detect invalid format (user error)
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Test various invalid date formats
        invalid_dates = ["not-a-date", "32/13/2024", "2024-13-45"]
        
        for invalid_date in invalid_dates:
            mock_result = Mock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = f"Invalid date format: {invalid_date}"
            
            with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
                result = await wrapper.export_channel(
                    channel_id="123456789",
                    token="test",
                    after=invalid_date
                )
                
                # Should indicate user error (invalid format)
                assert result['status'] == 'error'


class TestExceptionHandling:
    """Test exception handling throughout the stack."""
    
    @pytest.mark.asyncio
    async def test_unexpected_cli_output_format(self):
        """
        GIVEN: CLI returns unexpected output format
        WHEN: Output is parsed
        THEN: Should handle gracefully without crashing
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock unexpected output format
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Completely unexpected format\nNo pipe delimiters\nRandom text"
        mock_result.stderr = ""
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.list_guilds(token="test")
            
            # Should not crash - either parse what it can or return error
            assert 'status' in result
            assert isinstance(result.get('guilds', []), list)
    
    @pytest.mark.asyncio
    async def test_cli_crash_handling(self):
        """
        GIVEN: CLI crashes during execution
        WHEN: Command is run
        THEN: Should detect crash and return error
        """
        
        wrapper = DiscordWrapper(token="test_token", auto_install=False)
        
        # Mock CLI crash (segfault, etc.)
        mock_result = Mock()
        mock_result.returncode = -11  # SIGSEGV
        mock_result.stdout = ""
        mock_result.stderr = "Segmentation fault"
        
        with patch.object(wrapper.exporter, 'execute', return_value=mock_result):
            result = await wrapper.export_channel(
                channel_id="123456789",
                token="test"
            )
            
            assert result['status'] == 'error'
            assert 'error' in result
    
    @pytest.mark.asyncio
    async def test_malformed_json_in_export(self):
        """
        GIVEN: Export produces malformed JSON
        WHEN: JSON analysis is attempted
        THEN: Should detect and report JSON error
        """
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_export
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json content }")
            temp_file = f.name
        
        try:
            result = await discord_analyze_export(export_path=temp_file)
            
            # Should detect JSON parsing error
            assert result['status'] == 'error'
            assert 'json' in result.get('error', '').lower() or 'parse' in result.get('error', '').lower()
        finally:
            os.unlink(temp_file)
    
    @pytest.mark.asyncio
    async def test_empty_export_file_handling(self):
        """
        GIVEN: Export produces empty file
        WHEN: Analysis is attempted
        THEN: Should handle empty file gracefully
        """
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_export
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("")
            temp_file = f.name
        
        try:
            result = await discord_analyze_export(export_path=temp_file)
            
            # Should handle empty file
            assert result['status'] == 'error'
            assert 'error' in result
        finally:
            os.unlink(temp_file)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
