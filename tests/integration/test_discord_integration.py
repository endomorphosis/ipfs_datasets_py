"""
Integration tests for Discord data ingestion.

Tests the Discord Chat Exporter installation, wrapper functionality,
and MCP tools integration.
"""
import pytest
import asyncio
import os
import platform
from pathlib import Path
import tempfile

# Test the utility module
from ipfs_datasets_py.utils.discord_chat_exporter import (
    DiscordChatExporter,
    get_discord_chat_exporter
)

# Test the wrapper module
from ipfs_datasets_py.multimedia.discord_wrapper import (
    DiscordWrapper,
    create_discord_wrapper,
    DISCORD_AVAILABLE
)

# Test MCP tools
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_export_channel,
    discord_export_guild,
    discord_export_all_channels,
    discord_list_guilds,
    discord_list_channels,
    discord_list_dm_channels,
    discord_analyze_channel,
    discord_analyze_guild,
    discord_analyze_export
)


class TestDiscordChatExporterUtility:
    """Test the Discord Chat Exporter utility class."""
    
    def test_platform_detection(self):
        """
        GIVEN: A system with a supported platform
        WHEN: DiscordChatExporter is initialized
        THEN: Platform should be correctly detected
        """
        exporter = DiscordChatExporter()
        
        # Verify platform detection
        assert exporter.platform_name in ['linux', 'darwin', 'windows']
        assert exporter.arch in ['x64', 'x86', 'arm64', 'arm']
        
        # Verify install directory is created
        assert exporter.install_dir.exists()
        assert exporter.install_dir.is_dir()
    
    def test_download_url_generation(self):
        """
        GIVEN: A DiscordChatExporter instance
        WHEN: get_download_url is called
        THEN: Should return a valid GitHub download URL
        """
        exporter = DiscordChatExporter()
        url = exporter.get_download_url()
        
        # Verify URL structure
        assert url.startswith('https://github.com/Tyrrrz/DiscordChatExporter/releases/download/')
        assert 'DiscordChatExporter.Cli' in url
        assert url.endswith('.zip')
    
    def test_version_management(self):
        """
        GIVEN: A DiscordChatExporter instance with specified version
        WHEN: Initialized with custom version
        THEN: Should use the specified version
        """
        custom_version = "2.45"
        exporter = DiscordChatExporter(version=custom_version)
        
        assert exporter.version == custom_version
        assert custom_version in exporter.get_download_url()
    
    def test_executable_path(self):
        """
        GIVEN: A DiscordChatExporter instance
        WHEN: cli_executable is accessed
        THEN: Should point to correct executable based on platform
        """
        exporter = DiscordChatExporter()
        
        if platform.system().lower() == 'windows':
            assert str(exporter.cli_executable).endswith('.exe')
        else:
            assert not str(exporter.cli_executable).endswith('.exe')
    
    @pytest.mark.slow
    def test_download_and_install(self):
        """
        GIVEN: A DiscordChatExporter instance
        WHEN: download_and_install is called
        THEN: Should successfully download and install the CLI tool
        
        Note: This is a slow test that downloads ~10MB binary
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            
            # Initially not installed
            assert not exporter.is_installed()
            
            # Download and install
            success = exporter.download_and_install()
            assert success
            
            # Verify installation
            assert exporter.is_installed()
            assert exporter.cli_executable.exists()
            
            # Verify executable permissions (Unix-like systems)
            if exporter.platform_name != 'windows':
                assert os.access(exporter.cli_executable, os.X_OK)
            
            # Verify can get version
            version = exporter.get_version()
            assert version is not None
            assert len(version) > 0
    
    @pytest.mark.slow
    def test_verify_installation(self):
        """
        GIVEN: An installed DiscordChatExporter
        WHEN: verify_installation is called
        THEN: Should successfully verify the installation
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = DiscordChatExporter(install_dir=tmpdir)
            exporter.download_and_install()
            
            # Verify installation
            assert exporter.verify_installation()
    
    def test_convenience_function(self):
        """
        GIVEN: The get_discord_chat_exporter convenience function
        WHEN: Called with auto_install=False
        THEN: Should return a configured instance
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = get_discord_chat_exporter(
                install_dir=tmpdir,
                auto_install=False
            )
            
            assert isinstance(exporter, DiscordChatExporter)
            assert str(exporter.install_dir) == tmpdir


class TestDiscordWrapper:
    """Test the Discord wrapper functionality."""
    
    def test_wrapper_initialization(self):
        """
        GIVEN: DiscordWrapper class available
        WHEN: Wrapper is initialized
        THEN: Should create instance with correct default values
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapper = DiscordWrapper(
                token=None,
                default_output_dir=tmpdir,
                default_format='Json'
            )
            
            assert wrapper.default_format == 'Json'
            assert wrapper.default_output_dir == Path(tmpdir)
            assert wrapper.token is None
    
    def test_invalid_format(self):
        """
        GIVEN: DiscordWrapper class
        WHEN: Initialized with invalid format
        THEN: Should raise ValueError
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        with pytest.raises(ValueError, match="Invalid format"):
            DiscordWrapper(default_format='InvalidFormat')
    
    def test_ensure_token_validation(self):
        """
        GIVEN: DiscordWrapper instance without token
        WHEN: Operation requires token
        THEN: Should raise ValueError
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        wrapper = DiscordWrapper(token=None)
        
        with pytest.raises(ValueError, match="No Discord token"):
            wrapper._ensure_token()
    
    def test_format_extension_mapping(self):
        """
        GIVEN: DiscordWrapper instance
        WHEN: _get_format_extension is called with various formats
        THEN: Should return correct file extensions
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        wrapper = DiscordWrapper(token="dummy")
        
        assert wrapper._get_format_extension('Json') == 'json'
        assert wrapper._get_format_extension('Csv') == 'csv'
        assert wrapper._get_format_extension('PlainText') == 'txt'
        assert wrapper._get_format_extension('HtmlDark') == 'html'
        assert wrapper._get_format_extension('HtmlLight') == 'html'
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.environ.get('DISCORD_TOKEN'), reason="No Discord token provided")
    async def test_list_guilds_with_token(self):
        """
        GIVEN: A valid Discord token
        WHEN: list_guilds is called
        THEN: Should return guild information
        
        Note: Requires DISCORD_TOKEN environment variable
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        token = os.environ.get('DISCORD_TOKEN')
        wrapper = create_discord_wrapper(token=token)
        
        result = await wrapper.list_guilds()
        
        assert result['status'] == 'success'
        assert 'guilds' in result
        assert 'count' in result
        assert isinstance(result['guilds'], list)
    
    def test_convenience_function(self):
        """
        GIVEN: create_discord_wrapper convenience function
        WHEN: Called with parameters
        THEN: Should return configured DiscordWrapper instance
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapper = create_discord_wrapper(
                token="test_token",
                output_dir=tmpdir,
                format='Json',
                auto_install=False
            )
            
            assert isinstance(wrapper, DiscordWrapper)
            assert wrapper.token == "test_token"
            assert wrapper.default_format == 'Json'


class TestDiscordMCPTools:
    """Test Discord MCP tools."""
    
    @pytest.mark.asyncio
    async def test_discord_list_guilds_no_token(self):
        """
        GIVEN: discord_list_guilds MCP tool
        WHEN: Called without token
        THEN: Should return error status
        """
        result = await discord_list_guilds(token="")
        
        assert result['status'] == 'error'
        assert 'token is required' in result['error'].lower()
    
    @pytest.mark.asyncio
    async def test_discord_list_channels_validation(self):
        """
        GIVEN: discord_list_channels MCP tool
        WHEN: Called with invalid parameters
        THEN: Should return appropriate error messages
        """
        # Test missing guild_id
        result = await discord_list_channels(guild_id="", token="test")
        assert result['status'] == 'error'
        assert 'guild_id is required' in result['error'].lower()
        
        # Test missing token
        result = await discord_list_channels(guild_id="123", token="")
        assert result['status'] == 'error'
        assert 'token is required' in result['error'].lower()
    
    @pytest.mark.asyncio
    async def test_discord_export_channel_validation(self):
        """
        GIVEN: discord_export_channel MCP tool
        WHEN: Called with invalid parameters
        THEN: Should return appropriate error messages
        """
        # Test missing channel_id
        result = await discord_export_channel(channel_id="", token="test")
        assert result['status'] == 'error'
        
        # Test missing token
        result = await discord_export_channel(channel_id="123", token="")
        assert result['status'] == 'error'
    
    @pytest.mark.asyncio
    async def test_discord_export_guild_validation(self):
        """
        GIVEN: discord_export_guild MCP tool
        WHEN: Called with invalid include_threads value
        THEN: Should return error
        """
        result = await discord_export_guild(
            guild_id="123",
            token="test",
            include_threads="invalid"
        )
        
        assert result['status'] == 'error'
        assert 'include_threads' in result['error'].lower()
    
    @pytest.mark.asyncio
    async def test_discord_analyze_export_file_not_found(self):
        """
        GIVEN: discord_analyze_export MCP tool
        WHEN: Called with non-existent file
        THEN: Should return error
        """
        result = await discord_analyze_export(
            export_path="/nonexistent/file.json"
        )
        
        assert result['status'] == 'error'
        assert 'not found' in result['error'].lower()
    
    @pytest.mark.asyncio
    async def test_discord_analyze_export_with_sample_data(self):
        """
        GIVEN: A sample Discord export JSON file
        WHEN: discord_analyze_export is called
        THEN: Should return analysis results
        """
        # Create sample export data
        sample_data = {
            "guild": {"id": "123", "name": "Test Guild"},
            "channel": {"id": "456", "name": "test-channel"},
            "messages": [
                {
                    "id": "1",
                    "timestamp": "2024-01-01T12:00:00Z",
                    "content": "Hello world",
                    "author": {"id": "user1", "name": "User One"},
                    "attachments": [],
                    "embeds": [],
                    "reactions": []
                },
                {
                    "id": "2",
                    "timestamp": "2024-01-01T13:00:00Z",
                    "content": "Testing message with @mention",
                    "author": {"id": "user2", "name": "User Two"},
                    "attachments": [],
                    "embeds": [],
                    "reactions": []
                }
            ]
        }
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            json.dump(sample_data, f)
            temp_path = f.name
        
        try:
            # Analyze the export
            result = await discord_analyze_export(
                export_path=temp_path,
                analysis_types=['message_stats', 'user_activity']
            )
            
            assert result['status'] == 'success'
            assert result['message_count'] == 2
            assert 'analyses' in result
            assert 'message_stats' in result['analyses']
            assert 'user_activity' in result['analyses']
            
            # Verify message stats
            stats = result['analyses']['message_stats']
            assert stats['total_messages'] == 2
            assert stats['messages_with_attachments'] == 0
            
            # Verify user activity
            activity = result['analyses']['user_activity']
            assert activity['total_users'] == 2
            
        finally:
            # Clean up
            Path(temp_path).unlink(missing_ok=True)


class TestEndToEndIntegration:
    """End-to-end integration tests requiring full setup."""
    
    @pytest.mark.slow
    @pytest.mark.skipif(not os.environ.get('DISCORD_TOKEN'), reason="No Discord token provided")
    @pytest.mark.asyncio
    async def test_full_export_and_analyze_workflow(self):
        """
        GIVEN: A valid Discord token and channel ID
        WHEN: Export and analyze workflow is executed
        THEN: Should successfully export and analyze channel data
        
        Note: Requires DISCORD_TOKEN and DISCORD_TEST_CHANNEL_ID environment variables
        """
        if not DISCORD_AVAILABLE:
            pytest.skip("Discord wrapper not available")
        
        token = os.environ.get('DISCORD_TOKEN')
        channel_id = os.environ.get('DISCORD_TEST_CHANNEL_ID')
        
        if not channel_id:
            pytest.skip("No test channel ID provided")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Export channel
            export_result = await discord_export_channel(
                channel_id=channel_id,
                token=token,
                output_path=str(Path(tmpdir) / "export.json"),
                format='Json'
            )
            
            assert export_result['status'] == 'success'
            assert Path(export_result['output_path']).exists()
            
            # Analyze the export
            analysis_result = await discord_analyze_export(
                export_path=export_result['output_path'],
                analysis_types=['message_stats', 'user_activity', 'content_patterns']
            )
            
            assert analysis_result['status'] == 'success'
            assert 'analyses' in analysis_result
            assert analysis_result['message_count'] > 0


# Mark all tests with integration marker
pytestmark = pytest.mark.integration
