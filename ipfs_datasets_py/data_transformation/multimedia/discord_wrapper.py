"""
Discord Chat Export Wrapper

This module provides a comprehensive interface to DiscordChatExporter for exporting
Discord chat histories from channels, DMs, and servers to various formats.

Features:
- Export single channels, entire servers, or all accessible content
- Multiple output formats: HTML (dark/light), JSON, CSV, PlainText
- Date range filtering and message filtering
- Media download support with asset reuse
- Thread export support
- Comprehensive metadata extraction
- Secure token management via environment variables
- anyio support for asyncio/trio compatibility (libp2p integration)
"""

import anyio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# Import the Discord Chat Exporter utility
try:
    from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter, get_discord_chat_exporter
    DISCORD_EXPORTER_AVAILABLE = True
except ImportError:
    DISCORD_EXPORTER_AVAILABLE = False
    logger.warning("DiscordChatExporter utility not available")

# Backward-compatible flag name used by tests/tools
DISCORD_AVAILABLE = DISCORD_EXPORTER_AVAILABLE


class DiscordWrapper:
    """
    Discord Chat Export Wrapper
    
    Provides a high-level Python interface for exporting Discord chat histories
    using DiscordChatExporter CLI. Supports channels, DMs, servers, and comprehensive
    filtering options.
    
    Features:
    - Single channel, server, or global exports
    - Multiple output formats (HTML, JSON, CSV, PlainText)
    - Date range and message content filtering
    - Media asset downloading
    - Thread export support
    - Progress tracking and error handling
    - Asynchronous operation support
    
    Args:
        token (Optional[str]): Discord bot or user token for authentication.
            Required for most operations. Can also be set via environment variable.
        default_output_dir (Optional[str]): Default directory for exported files.
            Defaults to system temp directory if not specified.
        default_format (str): Default export format: 'HtmlDark', 'HtmlLight', 
            'Json', 'Csv', or 'PlainText'. Defaults to 'Json'.
        auto_install (bool): Automatically install DiscordChatExporter if not present.
        enable_logging (bool): Enable detailed logging output.
    
    Attributes:
        token (Optional[str]): Discord authentication token
        default_output_dir (Path): Default output directory for exports
        default_format (str): Default export format
        exporter (DiscordChatExporter): Underlying CLI manager
        exports (Dict): Registry of export operations
    
    Example:
        >>> wrapper = DiscordWrapper(token="YOUR_TOKEN")
        >>> # Export a single channel
        >>> result = await wrapper.export_channel(
        ...     channel_id="123456789",
        ...     output_path="/exports/channel.json"
        ... )
        >>> # Export entire server
        >>> result = await wrapper.export_guild(
        ...     guild_id="987654321",
        ...     output_dir="/exports/server/"
        ... )
    """
    
    VALID_FORMATS = ['HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText']
    
    def __init__(
        self,
        token: Optional[str] = None,
        default_output_dir: Optional[str] = None,
        default_format: Literal['HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText'] = 'Json',
        auto_install: bool = True,
        enable_logging: bool = True,
    ):
        """Initialize Discord wrapper with authentication and configuration."""
        
        if not DISCORD_EXPORTER_AVAILABLE:
            raise RuntimeError(
                "DiscordChatExporter utility not available. "
                "Ensure discord_chat_exporter.py is properly installed."
            )
        
        # Store token - check environment variable if not provided
        self.token = token or os.environ.get('DISCORD_TOKEN')
        
        # Setup output directory
        if default_output_dir is None:
            default_output_dir = tempfile.gettempdir()
        self.default_output_dir = Path(default_output_dir)
        self.default_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate format
        if default_format not in self.VALID_FORMATS:
            raise ValueError(f"Invalid format '{default_format}'. Must be one of {self.VALID_FORMATS}")
        self.default_format = default_format
        
        # Initialize the CLI exporter
        self.exporter = get_discord_chat_exporter(auto_install=auto_install)
        self.enable_logging = enable_logging
        
        # Track exports
        self.exports = {}
        
        logger.info(f"DiscordWrapper initialized (format={default_format}, output={self.default_output_dir})")
    
    def _ensure_token(self, token: Optional[str] = None) -> str:
        """
        Ensure a valid token is available for operations.
        
        Args:
            token: Token to use, or None to use instance token
        
        Returns:
            Valid token string
        
        Raises:
            ValueError: If no token is available
        """
        use_token = token if token is not None else self.token
        if use_token is None:
            raise ValueError(
                "No Discord token provided. Set token in constructor or pass to method. "
                "See: https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md"
            )
        if not isinstance(use_token, str):
            raise TypeError("Discord token must be a string")

        use_token = use_token.strip()
        if not use_token:
            raise ValueError(
                "No Discord token provided. Set token in constructor or pass to method. "
                "See: https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md"
            )
        return use_token
    
    async def list_guilds(self, token: Optional[str] = None) -> Dict[str, Any]:
        """
        List all accessible Discord servers (guilds).
        
        Args:
            token: Discord token (uses instance token if not provided)
        
        Returns:
            Dictionary with:
                - status: 'success' or 'error'
                - guilds: List of guild information
                - count: Number of guilds
                - error: Error message if failed
        """
        token = self._ensure_token(token)
        
        try:
            result = self.exporter.execute(['guilds', '-t', token], timeout=30)
            
            if result.returncode == 0:
                # Parse output (format: guild_id | guild_name)
                guilds = []
                for line in result.stdout.strip().split('\n'):
                    if '|' in line:
                        guild_id, guild_name = line.split('|', 1)
                        guilds.append({
                            'id': guild_id.strip(),
                            'name': guild_name.strip()
                        })
                
                return {
                    'status': 'success',
                    'guilds': guilds,
                    'count': len(guilds)
                }
            else:
                return {
                    'status': 'error',
                    'error': result.stderr,
                    'guilds': [],
                    'count': 0
                }
        
        except Exception as e:
            logger.error(f"Failed to list guilds: {e}")
            return {
                'status': 'error',
                'error': 'Failed to list guilds due to an internal error.',
                'guilds': [],
                'count': 0
            }
    
    async def list_channels(
        self,
        guild_id: str,
        token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all channels in a specific guild.
        
        Args:
            guild_id: Discord server (guild) ID
            token: Discord token (uses instance token if not provided)
        
        Returns:
            Dictionary with:
                - status: 'success' or 'error'
                - channels: List of channel information
                - count: Number of channels
                - guild_id: Guild ID
                - error: Error message if failed
        """
        token = self._ensure_token(token)
        
        try:
            result = self.exporter.execute(['channels', '-g', guild_id, '-t', token], timeout=30)
            
            if result.returncode == 0:
                # Parse output
                channels = []
                for line in result.stdout.strip().split('\n'):
                    if '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 3:
                            channels.append({
                                'id': parts[0].strip(),
                                'category': parts[1].strip(),
                                'name': parts[2].strip()
                            })
                
                return {
                    'status': 'success',
                    'guild_id': guild_id,
                    'channels': channels,
                    'count': len(channels)
                }
            else:
                return {
                    'status': 'error',
                    'guild_id': guild_id,
                    'error': result.stderr,
                    'channels': [],
                    'count': 0
                }
        
        except Exception as e:
            logger.error(f"Failed to list channels for guild {guild_id}: {e}")
            return {
                'status': 'error',
                'guild_id': guild_id,
                'error': str(e),
                'channels': [],
                'count': 0
            }
    
    async def list_dm_channels(self, token: Optional[str] = None) -> Dict[str, Any]:
        """
        List all direct message channels.
        
        Args:
            token: Discord token (uses instance token if not provided)
        
        Returns:
            Dictionary with:
                - status: 'success' or 'error'
                - channels: List of DM channel information
                - count: Number of DM channels
                - error: Error message if failed
        """
        token = self._ensure_token(token)
        
        try:
            result = self.exporter.execute(['dm', '-t', token], timeout=30)
            
            if result.returncode == 0:
                # Parse output
                channels = []
                for line in result.stdout.strip().split('\n'):
                    if '|' in line:
                        channel_id, channel_name = line.split('|', 1)
                        channels.append({
                            'id': channel_id.strip(),
                            'name': channel_name.strip()
                        })
                
                return {
                    'status': 'success',
                    'channels': channels,
                    'count': len(channels)
                }
            else:
                return {
                    'status': 'error',
                    'error': result.stderr,
                    'channels': [],
                    'count': 0
                }
        
        except Exception as e:
            logger.error(f"Failed to list DM channels: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'channels': [],
                'count': 0
            }
    
    async def export_channel(
        self,
        channel_id: str,
        output_path: Optional[str] = None,
        format: Optional[str] = None,
        token: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        filter_text: Optional[str] = None,
        download_media: bool = False,
        reuse_media: bool = False,
        partition_limit: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Export a single Discord channel.
        
        Args:
            channel_id: Discord channel ID to export
            output_path: Output file path (auto-generated if not provided)
            format: Export format (uses default if not provided)
            token: Discord token (uses instance token if not provided)
            after: Export messages after this date (ISO format or Discord timestamp)
            before: Export messages before this date (ISO format or Discord timestamp)
            filter_text: Message filter expression (e.g., "from:username has:image")
            download_media: Download media assets (avatars, attachments, etc.)
            reuse_media: Reuse previously downloaded media (requires download_media=True)
            partition_limit: Split export into parts (e.g., "100" messages or "20mb")
            **kwargs: Additional DiscordChatExporter CLI arguments
        
        Returns:
            Dictionary with:
                - status: 'success' or 'error'
                - channel_id: Channel ID
                - output_path: Path to exported file
                - format: Export format used
                - message_count: Number of messages exported (if available)
                - export_time: Time taken for export
                - error: Error message if failed
        """
        token = self._ensure_token(token)
        export_format = format or self.default_format
        
        # Generate output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            ext = self._get_format_extension(export_format)
            output_path = self.default_output_dir / f"channel_{channel_id}_{timestamp}.{ext}"
        else:
            output_path = Path(output_path)
        
        # Build command
        cmd = ['export', '-c', channel_id, '-t', token, '-f', export_format, '-o', str(output_path)]
        
        # Add optional parameters
        if after:
            cmd.extend(['--after', after])
        if before:
            cmd.extend(['--before', before])
        if filter_text:
            cmd.extend(['--filter', filter_text])
        if download_media:
            cmd.append('--media')
            if reuse_media:
                cmd.append('--reuse-media')
        if partition_limit:
            cmd.extend(['-p', partition_limit])
        
        # Execute export
        export_id = f"export_{channel_id}_{int(time.time())}"
        start_time = time.time()
        
        try:
            logger.info(f"Exporting channel {channel_id} to {output_path}")
            result = self.exporter.execute(cmd, timeout=600)
            export_time = time.time() - start_time
            
            if result.returncode == 0:
                # Try to extract message count from output
                message_count = None
                if 'messages' in result.stdout.lower():
                    # Parse message count if available in output
                    pass
                
                export_info = {
                    'status': 'success',
                    'export_id': export_id,
                    'channel_id': channel_id,
                    'output_path': str(output_path),
                    'format': export_format,
                    'export_time': export_time,
                    'message_count': message_count,
                    'stdout': result.stdout
                }
                
                self.exports[export_id] = export_info
                return export_info
            else:
                return {
                    'status': 'error',
                    'export_id': export_id,
                    'channel_id': channel_id,
                    'error': result.stderr,
                    'export_time': export_time
                }
        
        except Exception as e:
            logger.error(f"Failed to export channel {channel_id}: {e}")
            return {
                'status': 'error',
                'export_id': export_id,
                'channel_id': channel_id,
                'error': str(e),
                'export_time': time.time() - start_time
            }
    
    async def export_guild(
        self,
        guild_id: str,
        output_dir: Optional[str] = None,
        format: Optional[str] = None,
        token: Optional[str] = None,
        include_threads: Literal['none', 'active', 'all'] = 'none',
        include_vc: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Export all channels in a Discord server (guild).
        
        Args:
            guild_id: Discord server (guild) ID to export
            output_dir: Output directory (auto-generated if not provided)
            format: Export format (uses default if not provided)
            token: Discord token (uses instance token if not provided)
            include_threads: Thread inclusion: 'none', 'active', or 'all'
            include_vc: Include voice channels in export
            **kwargs: Additional export options (passed to export_channel)
        
        Returns:
            Dictionary with:
                - status: 'success' or 'error'
                - guild_id: Guild ID
                - output_dir: Output directory path
                - channels_exported: Number of channels exported
                - export_time: Total export time
                - error: Error message if failed
        """
        token = self._ensure_token(token)
        export_format = format or self.default_format
        
        # Generate output directory if not provided
        if output_dir is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = self.default_output_dir / f"guild_{guild_id}_{timestamp}"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command
        cmd = ['exportguild', '-g', guild_id, '-t', token, '-f', export_format, '-o', str(output_dir)]
        
        # Add optional parameters
        if include_threads != 'none':
            cmd.extend(['--include-threads', include_threads])
        if not include_vc:
            cmd.extend(['--include-vc', 'false'])
        
        # Execute export
        export_id = f"guild_export_{guild_id}_{int(time.time())}"
        start_time = time.time()
        
        try:
            logger.info(f"Exporting guild {guild_id} to {output_dir}")
            result = self.exporter.execute(cmd, timeout=1800)  # 30 min timeout for large servers
            export_time = time.time() - start_time
            
            if result.returncode == 0:
                # Count exported files
                exported_files = list(output_dir.glob(f"*.{self._get_format_extension(export_format)}"))
                
                export_info = {
                    'status': 'success',
                    'export_id': export_id,
                    'guild_id': guild_id,
                    'output_dir': str(output_dir),
                    'format': export_format,
                    'channels_exported': len(exported_files),
                    'export_time': export_time,
                    'stdout': result.stdout
                }
                
                self.exports[export_id] = export_info
                return export_info
            else:
                return {
                    'status': 'error',
                    'export_id': export_id,
                    'guild_id': guild_id,
                    'error': result.stderr,
                    'export_time': export_time
                }
        
        except Exception as e:
            logger.error(f"Failed to export guild {guild_id}: {e}")
            return {
                'status': 'error',
                'export_id': export_id,
                'guild_id': guild_id,
                'error': str(e),
                'export_time': time.time() - start_time
            }
    
    async def export_all(
        self,
        output_dir: Optional[str] = None,
        format: Optional[str] = None,
        token: Optional[str] = None,
        include_dm: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Export all accessible Discord channels and DMs.
        
        Args:
            output_dir: Output directory (auto-generated if not provided)
            format: Export format (uses default if not provided)
            token: Discord token (uses instance token if not provided)
            include_dm: Include direct messages in export
            **kwargs: Additional export options
        
        Returns:
            Dictionary with export status and information
        """
        token = self._ensure_token(token)
        export_format = format or self.default_format
        
        # Generate output directory if not provided
        if output_dir is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = self.default_output_dir / f"all_exports_{timestamp}"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command
        cmd = ['exportall', '-t', token, '-f', export_format, '-o', str(output_dir)]
        
        if not include_dm:
            cmd.extend(['--include-dm', 'false'])
        
        # Execute export
        export_id = f"all_export_{int(time.time())}"
        start_time = time.time()
        
        try:
            logger.info(f"Exporting all accessible channels to {output_dir}")
            result = self.exporter.execute(cmd, timeout=3600)  # 1 hour timeout
            export_time = time.time() - start_time
            
            if result.returncode == 0:
                # Count exported files
                exported_files = list(output_dir.glob(f"*.{self._get_format_extension(export_format)}"))
                
                export_info = {
                    'status': 'success',
                    'export_id': export_id,
                    'output_dir': str(output_dir),
                    'format': export_format,
                    'files_exported': len(exported_files),
                    'export_time': export_time,
                    'stdout': result.stdout
                }
                
                self.exports[export_id] = export_info
                return export_info
            else:
                return {
                    'status': 'error',
                    'export_id': export_id,
                    'error': result.stderr,
                    'export_time': export_time
                }
        
        except Exception as e:
            logger.error(f"Failed to export all channels: {e}")
            return {
                'status': 'error',
                'export_id': export_id,
                'error': str(e),
                'export_time': time.time() - start_time
            }
    
    async def export_dm_channels(
        self,
        output_dir: Optional[str] = None,
        format: Optional[str] = None,
        token: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Export all direct message channels using native exportdm command.
        
        This uses the DiscordChatExporter's native `exportdm` command which is
        more efficient than exporting DMs individually.
        
        Args:
            output_dir: Output directory (auto-generated if not provided)
            format: Export format (uses default if not provided)
            token: Discord token (uses instance token if not provided)
            **kwargs: Additional export options (e.g., download_media, partition_limit)
        
        Returns:
            Dictionary with:
                - status: 'success' or 'error'
                - output_dir: Output directory path
                - dm_channels_exported: Number of DM channels exported
                - export_time: Total export time
                - error: Error message if failed
        
        Example:
            >>> result = await wrapper.export_dm(
            ...     format="Json",
            ...     output_dir="/exports/dms"
            ... )
        """
        token = self._ensure_token(token)
        export_format = format or self.default_format
        
        # Generate output directory if not provided
        if output_dir is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = self.default_output_dir / f"dm_exports_{timestamp}"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command using native exportdm
        cmd = ['exportdm', '-t', token, '-f', export_format, '-o', str(output_dir)]
        
        # Add optional parameters from kwargs
        if kwargs.get('download_media'):
            cmd.append('--media')
            if kwargs.get('reuse_media'):
                cmd.append('--reuse-media')
        if kwargs.get('partition_limit'):
            cmd.extend(['-p', kwargs['partition_limit']])
        
        # Execute export
        export_id = f"dm_export_{int(time.time())}"
        start_time = time.time()
        
        try:
            logger.info(f"Exporting all DM channels to {output_dir}")
            result = self.exporter.execute(cmd, timeout=1800)  # 30 min timeout
            export_time = time.time() - start_time
            
            if result.returncode == 0:
                # Count exported files
                exported_files = list(output_dir.glob(f"*.{self._get_format_extension(export_format)}"))
                
                export_info = {
                    'status': 'success',
                    'export_id': export_id,
                    'output_dir': str(output_dir),
                    'format': export_format,
                    'dm_channels_exported': len(exported_files),
                    'export_time': export_time,
                    'stdout': result.stdout
                }
                
                self.exports[export_id] = export_info
                return export_info
            else:
                return {
                    'status': 'error',
                    'export_id': export_id,
                    'error': result.stderr,
                    'export_time': export_time
                }
        
        except Exception as e:
            logger.error(f"Failed to export DM channels: {e}")
            return {
                'status': 'error',
                'export_id': export_id,
                'error': str(e),
                'export_time': time.time() - start_time
            }

    async def export_dm(
        self,
        output_dir: Optional[str] = None,
        format: Optional[str] = None,
        token: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Backward-compatible alias for exporting all direct message channels.

        Args:
            output_dir: Output directory (auto-generated if not provided)
            format: Export format (uses default if not provided)
            token: Discord token (uses instance token if not provided)
            **kwargs: Additional export options (e.g., download_media, partition_limit)

        Returns:
            Export result dictionary.
        """
        return await self.export_dm_channels(
            output_dir=output_dir,
            format=format,
            token=token,
            **kwargs,
        )
    
    def _get_format_extension(self, format: str) -> str:
        """Get file extension for export format."""
        format_map = {
            'HtmlDark': 'html',
            'HtmlLight': 'html',
            'Json': 'json',
            'Csv': 'csv',
            'PlainText': 'txt'
        }
        return format_map.get(format, 'html')
    
    def get_export_status(self, export_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a specific export operation.
        
        Args:
            export_id: Export ID returned from export methods
        
        Returns:
            Export information dictionary or None if not found
        """
        return self.exports.get(export_id)
    
    def list_exports(self) -> List[Dict[str, Any]]:
        """
        List all tracked export operations.
        
        Returns:
            List of export information dictionaries
        """
        return list(self.exports.values())
    
    async def convert_export(
        self,
        input_path: str,
        output_path: str,
        to_format: Literal['json', 'jsonl', 'jsonld', 'jsonld-logic', 'parquet', 'ipld', 'car', 'csv'] = 'jsonl',
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convert a Discord export to a different format.
        
        This method converts Discord chat exports (typically in JSON format from 
        DiscordChatExporter) to various data formats supported by ipfs_datasets_py,
        including JSONL, JSON-LD, Parquet, IPLD, and CAR.
        
        Args:
            input_path: Path to the input export file (typically JSON)
            output_path: Path for the converted output file
            to_format: Target format for conversion. Supported formats:
                - 'json': Standard JSON
                - 'jsonl': JSON Lines (newline-delimited JSON)
                - 'jsonld': JSON-LD with semantic context
                - 'jsonld-logic': JSON-LD with formal logic annotations
                - 'parquet': Apache Parquet columnar format
                - 'ipld': InterPlanetary Linked Data
                - 'car': Content Addressable aRchive
                - 'csv': Comma-separated values
            **kwargs: Additional format-specific options:
                - context: Custom JSON-LD @context (for jsonld/jsonld-logic)
                - compression: Compression type for Parquet ('snappy', 'gzip')
                - indent: JSON indentation level
        
        Returns:
            Dict containing conversion status and metadata:
                - status: 'success' or 'error'
                - input_path: Source file path
                - output_path: Destination file path
                - from_format: Detected source format
                - to_format: Target format
                - message: Status message
                - file_size: Output file size in bytes (if successful)
        
        Raises:
            FileNotFoundError: If input file doesn't exist
            ImportError: If required dependencies for target format aren't available
            ValueError: If format conversion fails
        
        Example:
            >>> # Export Discord channel as JSON
            >>> result = await wrapper.export_channel("123456", output_path="chat.json")
            >>> 
            >>> # Convert to JSONL for streaming processing
            >>> await wrapper.convert_export("chat.json", "chat.jsonl", to_format="jsonl")
            >>> 
            >>> # Convert to Parquet for analytics
            >>> await wrapper.convert_export("chat.json", "chat.parquet", to_format="parquet")
            >>> 
            >>> # Convert to JSON-LD with semantic annotations
            >>> await wrapper.convert_export(
            ...     "chat.json",
            ...     "chat.json-ld",
            ...     to_format="jsonld",
            ...     context={"discord": "https://discord.com/developers/docs/"}
            ... )
        """
        try:
            from ipfs_datasets_py.utils.data_format_converter import get_converter
            
            # Check input file exists
            if not os.path.exists(input_path):
                return {
                    'status': 'error',
                    'input_path': input_path,
                    'output_path': output_path,
                    'error': f"Input file not found: {input_path}"
                }
            
            logger.info(f"Converting {input_path} to {to_format} format")
            
            # Get converter instance
            converter = get_converter()
            
            # Discord exports are typically in JSON format
            from_format = 'json'
            
            # Perform conversion
            output_file = converter.convert_file(
                input_path,
                output_path,
                from_format=from_format,
                to_format=to_format,
                **kwargs
            )
            
            # Get file size
            file_size = os.path.getsize(output_file)
            
            return {
                'status': 'success',
                'input_path': input_path,
                'output_path': output_file,
                'from_format': from_format,
                'to_format': to_format,
                'message': f'Successfully converted to {to_format} format',
                'file_size': file_size
            }
        
        except ImportError as e:
            error_msg = f"Missing dependency for {to_format} conversion: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'input_path': input_path,
                'output_path': output_path,
                'from_format': 'json',
                'to_format': to_format,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'input_path': input_path,
                'output_path': output_path,
                'from_format': 'json',
                'to_format': to_format,
                'error': error_msg
            }


# Convenience function
def create_discord_wrapper(
    token: Optional[str] = None,
    output_dir: Optional[str] = None,
    format: str = 'Json',
    auto_install: bool = True
) -> DiscordWrapper:
    """
    Create and initialize a Discord wrapper instance.
    
    Args:
        token: Discord authentication token
        output_dir: Default output directory
        format: Default export format
        auto_install: Auto-install DiscordChatExporter if needed
    
    Returns:
        Configured DiscordWrapper instance
    
    Example:
        >>> wrapper = create_discord_wrapper(token="YOUR_TOKEN")
        >>> guilds = await wrapper.list_guilds()
    """
    return DiscordWrapper(
        token=token,
        default_output_dir=output_dir,
        default_format=format,
        auto_install=auto_install
    )
