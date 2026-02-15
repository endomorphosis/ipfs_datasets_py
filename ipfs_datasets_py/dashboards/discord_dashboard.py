#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Discord Dashboard for IPFS Datasets.

This module provides a web interface for managing Discord data exports,
viewing analytics, and monitoring Discord integration status.

Features:
- Discord server (guild) and channel browser
- Export management and status monitoring
- Data analytics and visualizations
- Token configuration and testing
- Export history and logs
"""
from __future__ import annotations

import anyio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

try:
    from flask import Flask, render_template, request, jsonify, Blueprint
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

logger = logging.getLogger(__name__)


def create_discord_dashboard_blueprint() -> Optional[Blueprint]:
    """
    Create a Flask blueprint for the Discord dashboard.
    
    Returns:
        Flask Blueprint if Flask is available, None otherwise
    """
    if not FLASK_AVAILABLE:
        logger.warning("Flask not available, Discord dashboard cannot be created")
        return None
    
    # Create blueprint
    discord_bp = Blueprint('discord', __name__, url_prefix='/mcp/discord')
    
    @discord_bp.route('/')
    def discord_dashboard():
        """Render the Discord dashboard page."""
        return render_template('admin/discord_dashboard.html')
    
    @discord_bp.route('/api/test_token', methods=['POST'])
    async def api_test_token():
        """
        API endpoint for testing Discord token validity.
        
        Request body:
            {
                "token": "discord_token_here"
            }
        
        Returns:
            JSON response with token test results
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_list_guilds
            
            # Get token from request or environment
            data = request.get_json()
            token = data.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No token provided",
                    "valid": False
                }), 400
            
            # Test token by listing guilds
            result = await discord_list_guilds(token=token)
            
            if result['status'] == 'success':
                return jsonify({
                    "status": "success",
                    "valid": True,
                    "guild_count": result['count'],
                    "message": f"Token is valid. Found {result['count']} accessible servers."
                })
            else:
                # Use a generic error message unless it's a known, safe value
                error_message = result.get('error') or 'Token validation failed'
                if error_message not in {
                    "Discord wrapper not available",
                    "Discord token is required",
                    "Discord wrapper not available for this operation"
                }:
                    error_message = 'Token validation failed'
                return jsonify({
                    "status": "error",
                    "valid": False,
                    "error": error_message
                }), 401
                
        except Exception as e:
            logger.error(f"Token test API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "valid": False,
                "error": "Internal server error while testing token"
            }), 500
    
    @discord_bp.route('/api/list_guilds', methods=['GET'])
    async def api_list_guilds():
        """
        API endpoint for listing accessible Discord servers (guilds).
        
        Returns:
            JSON response with guild list
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_list_guilds
            
            # Get token from environment or request
            token = request.args.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided. Set DISCORD_TOKEN environment variable.",
                    "guilds": [],
                    "count": 0
                }), 400
            
            # List guilds
            result = await discord_list_guilds(token=token)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"List guilds API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e),
                "guilds": [],
                "count": 0
            }), 500
    
    @discord_bp.route('/api/list_channels/<guild_id>', methods=['GET'])
    async def api_list_channels(guild_id: str):
        """
        API endpoint for listing channels in a specific guild.
        
        Args:
            guild_id: Discord guild ID
        
        Returns:
            JSON response with channel list
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_list_channels
            
            # Get token
            token = request.args.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided",
                    "channels": [],
                    "count": 0
                }), 400
            
            # List channels
            result = await discord_list_channels(guild_id=guild_id, token=token)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"List channels API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e),
                "channels": [],
                "count": 0
            }), 500
    
    @discord_bp.route('/api/export_channel', methods=['POST'])
    async def api_export_channel():
        """
        API endpoint for exporting a Discord channel.
        
        Request body:
            {
                "channel_id": "123456789",
                "format": "Json",
                "after_date": "2024-01-01",
                "before_date": "2024-12-31",
                "filter_text": "from:user has:image",
                "download_media": true
            }
        
        Returns:
            JSON response with export status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_export_channel
            
            # Get request data
            data = request.get_json()
            token = data.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided"
                }), 400
            
            # Export channel
            result = await discord_export_channel(
                channel_id=data.get('channel_id'),
                token=token,
                format=data.get('format', 'Json'),
                after_date=data.get('after_date'),
                before_date=data.get('before_date'),
                filter_text=data.get('filter_text'),
                download_media=data.get('download_media', False),
                reuse_media=data.get('reuse_media', False),
                partition_limit=data.get('partition_limit')
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Export channel API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @discord_bp.route('/api/export_guild', methods=['POST'])
    async def api_export_guild():
        """
        API endpoint for exporting an entire Discord server.
        
        Request body:
            {
                "guild_id": "987654321",
                "format": "Json",
                "include_threads": "all",
                "include_vc": true
            }
        
        Returns:
            JSON response with export status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_export_guild
            
            # Get request data
            data = request.get_json()
            token = data.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided"
                }), 400
            
            # Export guild
            result = await discord_export_guild(
                guild_id=data.get('guild_id'),
                token=token,
                format=data.get('format', 'Json'),
                include_threads=data.get('include_threads', 'none'),
                include_vc=data.get('include_vc', True)
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Export guild API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @discord_bp.route('/api/analyze_channel/<channel_id>', methods=['GET'])
    async def api_analyze_channel(channel_id: str):
        """
        API endpoint for analyzing a Discord channel.
        
        Args:
            channel_id: Discord channel ID
        
        Query parameters:
            analysis_types: Comma-separated list of analysis types
        
        Returns:
            JSON response with analysis results
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_channel
            
            # Get token
            token = request.args.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided"
                }), 400
            
            # Get analysis types
            analysis_types_str = request.args.get('analysis_types', 'message_stats,user_activity')
            analysis_types = [t.strip() for t in analysis_types_str.split(',')]
            
            # Analyze channel
            result = await discord_analyze_channel(
                channel_id=channel_id,
                token=token,
                analysis_types=analysis_types
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Analyze channel API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @discord_bp.route('/api/analyze_export', methods=['POST'])
    async def api_analyze_export():
        """
        API endpoint for analyzing a previously exported Discord file.
        
        Request body:
            {
                "export_path": "/path/to/export.json",
                "analysis_types": ["message_stats", "user_activity"]
            }
        
        Returns:
            JSON response with analysis results
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_export
            
            # Get request data
            data = request.get_json()
            export_path = data.get('export_path')
            
            if not export_path:
                return jsonify({
                    "status": "error",
                    "error": "No export path provided"
                }), 400
            
            # Get analysis types
            analysis_types = data.get('analysis_types', ['message_stats', 'user_activity'])
            
            # Analyze export
            result = await discord_analyze_export(
                export_path=export_path,
                analysis_types=analysis_types
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Analyze export API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @discord_bp.route('/api/list_dm_channels', methods=['GET'])
    async def api_list_dm_channels():
        """
        API endpoint for listing DM channels.
        
        Returns:
            JSON response with DM channel list
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_list_dm_channels
            
            # Get token
            token = request.args.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided",
                    "channels": [],
                    "count": 0
                }), 400
            
            # List DM channels
            result = await discord_list_dm_channels(token=token)
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"List DM channels API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e),
                "channels": [],
                "count": 0
            }), 500
    
    @discord_bp.route('/api/export_dm_channels', methods=['POST'])
    async def api_export_dm_channels():
        """
        API endpoint for exporting all DM channels using native exportdm.
        
        Request body:
            {
                "format": "Json",
                "output_dir": "/path/to/output"
            }
        
        Returns:
            JSON response with export status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_export_dm_channels
            
            # Get request data
            data = request.get_json()
            token = data.get('token') or os.environ.get('DISCORD_TOKEN')
            
            if not token:
                return jsonify({
                    "status": "error",
                    "error": "No Discord token provided"
                }), 400
            
            # Export DMs
            result = await discord_export_dm_channels(
                token=token,
                format=data.get('format', 'Json'),
                output_dir=data.get('output_dir')
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Export DMs API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @discord_bp.route('/api/convert_export', methods=['POST'])
    async def api_convert_export():
        """
        API endpoint for converting Discord export files.
        
        Request body:
            {
                "input_path": "/path/to/input.json",
                "output_path": "/path/to/output.parquet",
                "to_format": "parquet",
                "compression": "snappy"
            }
        
        Returns:
            JSON response with conversion status
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_convert_export
            
            # Helper functions for safe path handling within the exports directory
            def _get_discord_exports_base_dir() -> Path:
                """
                Get or create the base directory for Discord export conversions.
                
                The directory can be configured via the DISCORD_EXPORT_BASE_DIR
                environment variable. Defaults to ./discord_exports.
                """
                base = os.environ.get("DISCORD_EXPORT_BASE_DIR", os.path.join(os.getcwd(), "discord_exports"))
                base_path = Path(base).resolve()
                base_path.mkdir(parents=True, exist_ok=True)
                return base_path
            
            def _resolve_safe_path(user_path: str) -> Path:
                """
                Resolve a user-provided path safely within the exports base directory.
                
                Raises ValueError if the resolved path escapes the base directory.
                """
                base_dir = _get_discord_exports_base_dir()
                # Treat user_path as relative to the base directory
                candidate = (base_dir / user_path).resolve()
                try:
                    candidate.relative_to(base_dir)
                except ValueError:
                    raise ValueError("Path outside of allowed exports directory")
                return candidate
            
            # Get request data
            data = request.get_json()
            input_path = data.get('input_path')
            output_path = data.get('output_path')
            to_format = data.get('to_format')
            
            if not input_path or not output_path or not to_format:
                return jsonify({
                    "status": "error",
                    "error": "Missing required parameters: input_path, output_path, to_format"
                }), 400
            
            # Resolve and validate paths within the exports base directory
            try:
                safe_input_path = str(_resolve_safe_path(input_path))
                safe_output_path = str(_resolve_safe_path(output_path))
            except ValueError as ve:
                logging.warning("Invalid export path provided: %s", ve)
                return jsonify({
                    "status": "error",
                    "error": "Invalid path: outside of allowed exports directory"
                }), 400
            
            # Convert export
            result = await discord_convert_export(
                input_path=safe_input_path,
                output_path=safe_output_path,
                to_format=to_format,
                compression=data.get('compression'),
                context=data.get('context')
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Convert export API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    @discord_bp.route('/api/status', methods=['GET'])
    def api_status():
        """
        API endpoint for getting Discord integration status.
        
        Returns:
            JSON response with integration status
        """
        try:
            from ipfs_datasets_py.processors.multimedia import HAVE_DISCORD
            from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter
            
            # Check if Discord integration is available
            if not HAVE_DISCORD:
                return jsonify({
                    "status": "unavailable",
                    "message": "Discord integration not available",
                    "discord_available": False,
                    "exporter_installed": False,
                    "token_configured": False
                })
            
            # Check if exporter is installed
            exporter = DiscordChatExporter()
            exporter_installed = exporter.is_installed()
            
            # Check if token is configured
            token_configured = bool(os.environ.get('DISCORD_TOKEN'))
            
            return jsonify({
                "status": "available" if (exporter_installed and token_configured) else "partial",
                "message": "Discord integration is ready" if (exporter_installed and token_configured) else "Configuration needed",
                "discord_available": HAVE_DISCORD,
                "exporter_installed": exporter_installed,
                "exporter_version": exporter.get_version() if exporter_installed else None,
                "token_configured": token_configured,
                "platform": exporter.platform_name,
                "architecture": exporter.arch
            })
            
        except Exception as e:
            logger.error(f"Status API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": str(e),
                "discord_available": False,
                "exporter_installed": False,
                "token_configured": False
            }), 500
    
    return discord_bp


def create_discord_dashboard_app(config: Optional[Dict[str, Any]] = None) -> Optional[Flask]:
    """
    Create a standalone Flask app for the Discord dashboard.
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        Flask app if Flask is available, None otherwise
    """
    if not FLASK_AVAILABLE:
        logger.warning("Flask not available, Discord dashboard cannot be created")
        return None
    
    app = Flask(__name__)
    app.config.update(config or {})
    
    # Register blueprint
    blueprint = create_discord_dashboard_blueprint()
    if blueprint:
        app.register_blueprint(blueprint)
    
    @app.route('/')
    def index():
        """Redirect to Discord dashboard."""
        return render_template('admin/discord_dashboard.html')
    
    return app


def start_discord_dashboard(host: str = '127.0.0.1', port: int = 8889, debug: bool = False):
    """
    Start the Discord dashboard server.
    
    Args:
        host: Host address to bind to
        port: Port number to bind to
        debug: Enable debug mode
    """
    app = create_discord_dashboard_app()
    if app:
        logger.info(f"Starting Discord dashboard at http://{host}:{port}")
        app.run(host=host, port=port, debug=debug)
    else:
        logger.error("Failed to create Discord dashboard app")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Discord Dashboard')
    parser.add_argument('--host', default='127.0.0.1', help='Host address')
    parser.add_argument('--port', type=int, default=8889, help='Port number')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    start_discord_dashboard(host=args.host, port=args.port, debug=args.debug)
