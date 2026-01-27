#!/usr/bin/env python3
"""
Discord CLI Tool for IPFS Datasets.

Command-line interface for Discord data export and analysis including:
- Server (guild) and channel listing
- Channel, server, and DM export
- Data analysis and statistics
- Token management

Usage:
    ipfs-datasets discord [command] [options]
    python -m ipfs_datasets_py.discord_cli [command] [options]
"""

import argparse
import anyio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for Discord CLI."""
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets discord',
        description='Discord Data Export and Analysis CLI'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List guilds command
    guilds_parser = subparsers.add_parser('guilds', help='List accessible Discord servers')
    guilds_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    guilds_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # List channels command
    channels_parser = subparsers.add_parser('channels', help='List channels in a server')
    channels_parser.add_argument('guild_id', help='Discord server (guild) ID')
    channels_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    channels_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # List DMs command
    dms_parser = subparsers.add_parser('dms', help='List direct message channels')
    dms_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    dms_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Export channel command
    export_parser = subparsers.add_parser('export', help='Export a Discord channel')
    export_parser.add_argument('channel_id', help='Channel ID to export')
    export_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    export_parser.add_argument('--output', '-o', help='Output file path')
    export_parser.add_argument('--format', '-f', default='Json',
                              choices=['Json', 'HtmlDark', 'HtmlLight', 'Csv', 'PlainText'],
                              help='Export format (default: Json)')
    export_parser.add_argument('--after', help='Export messages after date (YYYY-MM-DD)')
    export_parser.add_argument('--before', help='Export messages before date (YYYY-MM-DD)')
    export_parser.add_argument('--filter', help='Message filter (e.g., "from:user has:image")')
    export_parser.add_argument('--media', action='store_true', help='Download media assets')
    export_parser.add_argument('--reuse-media', action='store_true', 
                              help='Reuse previously downloaded media')
    export_parser.add_argument('--partition', help='Partition by messages or size (e.g., "100" or "20mb")')
    
    # Export guild command
    guild_parser = subparsers.add_parser('export-guild', help='Export entire Discord server')
    guild_parser.add_argument('guild_id', help='Guild ID to export')
    guild_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    guild_parser.add_argument('--output-dir', '-o', help='Output directory')
    guild_parser.add_argument('--format', '-f', default='Json',
                            choices=['Json', 'HtmlDark', 'HtmlLight', 'Csv', 'PlainText'],
                            help='Export format (default: Json)')
    guild_parser.add_argument('--threads', choices=['none', 'active', 'all'], default='none',
                            help='Include threads (default: none)')
    guild_parser.add_argument('--no-vc', action='store_true', help='Exclude voice channels')
    
    # Export DMs command  
    dm_export_parser = subparsers.add_parser('export-dms', help='Export all direct messages')
    dm_export_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    dm_export_parser.add_argument('--output-dir', '-o', help='Output directory')
    dm_export_parser.add_argument('--format', '-f', default='Json',
                                 choices=['Json', 'HtmlDark', 'HtmlLight', 'Csv', 'PlainText'],
                                 help='Export format (default: Json)')
    dm_export_parser.add_argument('--media', action='store_true', help='Download media assets')
    
    # Export all command
    all_parser = subparsers.add_parser('export-all', help='Export all accessible content')
    all_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    all_parser.add_argument('--output-dir', '-o', help='Output directory')
    all_parser.add_argument('--format', '-f', default='Json',
                           choices=['Json', 'HtmlDark', 'HtmlLight', 'Csv', 'PlainText'],
                           help='Export format (default: Json)')
    all_parser.add_argument('--no-dm', action='store_true', help='Exclude direct messages')
    
    # Analyze channel command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze a Discord channel')
    analyze_parser.add_argument('channel_id', help='Channel ID to analyze')
    analyze_parser.add_argument('--token', help='Discord token (or use DISCORD_TOKEN env var)')
    analyze_parser.add_argument('--types', default='message_stats,user_activity',
                               help='Comma-separated analysis types')
    analyze_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Analyze export command
    analyze_export_parser = subparsers.add_parser('analyze-export', 
                                                  help='Analyze exported Discord data')
    analyze_export_parser.add_argument('export_path', help='Path to exported JSON file')
    analyze_export_parser.add_argument('--types', default='message_stats,user_activity',
                                      help='Comma-separated analysis types')
    analyze_export_parser.add_argument('--output', '-o', help='Output JSON file')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Check Discord integration status')
    
    # Install command
    install_parser = subparsers.add_parser('install', help='Install DiscordChatExporter')
    install_parser.add_argument('--force', action='store_true', help='Force reinstallation')
    
    # Convert export command
    convert_parser = subparsers.add_parser('convert', help='Convert Discord export to different format')
    convert_parser.add_argument('input', help='Input export file path')
    convert_parser.add_argument('output', help='Output file path')
    convert_parser.add_argument('--to-format', '-t', required=True,
                               choices=['json', 'jsonl', 'jsonld', 'jsonld-logic', 'parquet', 'ipld', 'car', 'csv'],
                               help='Target format for conversion')
    convert_parser.add_argument('--compression', '-c', 
                               choices=['snappy', 'gzip', 'brotli'],
                               help='Compression type (for Parquet)')
    convert_parser.add_argument('--context', help='JSON-LD context (JSON string or file path)')
    
    # Batch convert command
    batch_convert_parser = subparsers.add_parser('batch-convert', 
                                                 help='Batch convert Discord exports')
    batch_convert_parser.add_argument('input_dir', help='Input directory with export files')
    batch_convert_parser.add_argument('output_dir', help='Output directory')
    batch_convert_parser.add_argument('--to-format', '-t', required=True,
                                     choices=['json', 'jsonl', 'jsonld', 'jsonld-logic', 'parquet', 'ipld', 'car', 'csv'],
                                     help='Target format for conversion')
    batch_convert_parser.add_argument('--pattern', '-p', default='*.json',
                                     help='File pattern to match (default: *.json)')
    batch_convert_parser.add_argument('--compression', '-c',
                                     choices=['snappy', 'gzip', 'brotli'],
                                     help='Compression type (for Parquet)')
    
    return parser


async def cmd_guilds(args) -> int:
    """Execute guilds listing command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        wrapper = DiscordWrapper(token=args.token)
        result = await wrapper.list_guilds(token=args.token)
        
        if result['status'] == 'success':
            print(f"✓ Found {result['count']} Discord servers:")
            for guild in result['guilds']:
                print(f"  • {guild['name']} (ID: {guild['id']})")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"\n✓ Results saved to {args.output}")
            return 0
        else:
            print(f"✗ Error: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error listing guilds: {e}", file=sys.stderr)
        return 1


async def cmd_channels(args) -> int:
    """Execute channels listing command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        wrapper = DiscordWrapper(token=args.token)
        result = await wrapper.list_channels(guild_id=args.guild_id, token=args.token)
        
        if result['status'] == 'success':
            print(f"✓ Found {result['count']} channels in server:")
            for channel in result['channels']:
                print(f"  • {channel['name']} (Category: {channel['category']}, ID: {channel['id']})")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"\n✓ Results saved to {args.output}")
            return 0
        else:
            print(f"✗ Error: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error listing channels: {e}", file=sys.stderr)
        return 1


async def cmd_dms(args) -> int:
    """Execute DMs listing command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        wrapper = DiscordWrapper(token=args.token)
        result = await wrapper.list_dm_channels(token=args.token)
        
        if result['status'] == 'success':
            print(f"✓ Found {result['count']} DM channels:")
            for dm in result['channels']:
                print(f"  • {dm['name']} (ID: {dm['id']})")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"\n✓ Results saved to {args.output}")
            return 0
        else:
            print(f"✗ Error: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error listing DMs: {e}", file=sys.stderr)
        return 1


async def cmd_export(args) -> int:
    """Execute channel export command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        print(f"Exporting channel {args.channel_id}...")
        
        wrapper = DiscordWrapper(token=args.token)
        result = await wrapper.export_channel(
            channel_id=args.channel_id,
            token=args.token,
            output_path=args.output,
            format=args.format,
            after_date=args.after,
            before_date=args.before,
            filter_text=args.filter,
            download_media=args.media,
            reuse_media=args.reuse_media,
            partition_limit=args.partition
        )
        
        if result['status'] == 'success':
            print(f"✓ Export successful!")
            print(f"  Output: {result['output_path']}")
            print(f"  Format: {result['format']}")
            print(f"  Time: {result['export_time']:.2f}s")
            return 0
        else:
            print(f"✗ Export failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error exporting channel: {e}", file=sys.stderr)
        return 1


async def cmd_export_guild(args) -> int:
    """Execute guild export command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        print(f"Exporting guild {args.guild_id}...")
        
        wrapper = DiscordWrapper(token=args.token)
        result = await wrapper.export_guild(
            guild_id=args.guild_id,
            token=args.token,
            output_dir=args.output_dir,
            format=args.format,
            include_threads=args.threads,
            include_vc=not args.no_vc
        )
        
        if result['status'] == 'success':
            print(f"✓ Export successful!")
            print(f"  Output directory: {result['output_dir']}")
            print(f"  Channels exported: {result['channels_exported']}")
            print(f"  Time: {result['export_time']:.2f}s")
            return 0
        else:
            print(f"✗ Export failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error exporting guild: {e}", file=sys.stderr)
        return 1


async def cmd_export_dms(args) -> int:
    """Execute DMs export command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        print("Exporting all DM channels...")
        
        wrapper = DiscordWrapper(token=args.token, default_output_dir=args.output_dir, default_format=args.format)
        result = await wrapper.export_dm(
            token=args.token,
            output_dir=args.output_dir,
            format=args.format
        )
        
        if result['status'] == 'success':
            print(f"✓ Export successful!")
            print(f"  Output directory: {result['output_dir']}")
            print(f"  DM channels exported: {result.get('dm_channels_exported', 'N/A')}")
            print(f"  Time: {result['export_time']:.2f}s")
            return 0
        else:
            print(f"✗ Export failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error exporting DMs: {e}", file=sys.stderr)
        return 1


async def cmd_export_all(args) -> int:
    """Execute export all command."""
    try:
        from ipfs_datasets_py.multimedia import DiscordWrapper
        
        print("Exporting all accessible channels...")
        
        wrapper = DiscordWrapper(token=args.token, default_output_dir=args.output_dir, default_format=args.format)
        result = await wrapper.export_all(
            token=args.token,
            output_dir=args.output_dir,
            format=args.format,
            include_dm=not args.no_dm
        )
        
        if result['status'] == 'success':
            print(f"✓ Export successful!")
            print(f"  Output directory: {result['output_dir']}")
            print(f"  Files exported: {result['files_exported']}")
            print(f"  Time: {result['export_time']:.2f}s")
            return 0
        else:
            print(f"✗ Export failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error exporting all: {e}", file=sys.stderr)
        return 1


async def cmd_analyze(args) -> int:
    """Execute analyze channel command."""
    try:
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_channel
        
        print(f"Analyzing channel {args.channel_id}...")
        
        analysis_types = [t.strip() for t in args.types.split(',')]
        
        result = await discord_analyze_channel(
            channel_id=args.channel_id,
            token=args.token,
            analysis_types=analysis_types
        )
        
        if result['status'] == 'success':
            print(f"✓ Analysis complete!")
            print(f"  Messages analyzed: {result['message_count']}")
            
            # Print summary
            if 'message_stats' in result['analyses']:
                stats = result['analyses']['message_stats']
                print(f"\nMessage Statistics:")
                print(f"  Total messages: {stats['total_messages']}")
                if stats['date_range']:
                    print(f"  Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")
            
            if 'user_activity' in result['analyses']:
                activity = result['analyses']['user_activity']
                print(f"\nUser Activity:")
                print(f"  Total users: {activity['total_users']}")
                if activity['most_active_user']:
                    print(f"  Most active: {activity['most_active_user'][0]} ({activity['most_active_user'][1]} messages)")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"\n✓ Full analysis saved to {args.output}")
            
            return 0
        else:
            print(f"✗ Analysis failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error analyzing channel: {e}", file=sys.stderr)
        return 1


async def cmd_analyze_export(args) -> int:
    """Execute analyze export command."""
    try:
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_export
        
        print(f"Analyzing export file {args.export_path}...")
        
        analysis_types = [t.strip() for t in args.types.split(',')]
        
        result = await discord_analyze_export(
            export_path=args.export_path,
            analysis_types=analysis_types
        )
        
        if result['status'] == 'success':
            print(f"✓ Analysis complete!")
            print(f"  Messages analyzed: {result['message_count']}")
            
            # Print summary (similar to cmd_analyze)
            if 'message_stats' in result['analyses']:
                stats = result['analyses']['message_stats']
                print(f"\nMessage Statistics:")
                print(f"  Total messages: {stats['total_messages']}")
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"\n✓ Full analysis saved to {args.output}")
            
            return 0
        else:
            print(f"✗ Analysis failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error analyzing export: {e}", file=sys.stderr)
        return 1


def cmd_status(args) -> int:
    """Execute status command."""
    try:
        from ipfs_datasets_py.multimedia import HAVE_DISCORD
        from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter
        
        print("Discord Integration Status:")
        print(f"  Discord available: {'✓' if HAVE_DISCORD else '✗'}")
        
        if HAVE_DISCORD:
            exporter = DiscordChatExporter()
            installed = exporter.is_installed()
            print(f"  DiscordChatExporter installed: {'✓' if installed else '✗'}")
            
            if installed:
                version = exporter.get_version()
                print(f"  Version: {version}")
            
            print(f"  Platform: {exporter.platform_name}")
            print(f"  Architecture: {exporter.arch}")
        
        token_configured = bool(os.environ.get('DISCORD_TOKEN'))
        print(f"  Token configured: {'✓' if token_configured else '✗'}")
        
        if not token_configured:
            print("\n  ℹ Set DISCORD_TOKEN environment variable to configure token")
        
        return 0
        
    except Exception as e:
        print(f"✗ Error checking status: {e}", file=sys.stderr)
        return 1


def cmd_install(args) -> int:
    """Execute install command."""
    try:
        from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter
        
        exporter = DiscordChatExporter()
        
        if exporter.is_installed() and not args.force:
            print("✓ DiscordChatExporter is already installed")
            print(f"  Version: {exporter.get_version()}")
            print("\n  Use --force to reinstall")
            return 0
        
        print("Installing DiscordChatExporter...")
        success = exporter.download_and_install(force=args.force)
        
        if success:
            print("✓ Installation successful!")
            print(f"  Version: {exporter.get_version()}")
            return 0
        else:
            print("✗ Installation failed", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error installing: {e}", file=sys.stderr)
        return 1


async def cmd_convert(args) -> int:
    """Execute convert command."""
    try:
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_convert_export
        
        # Handle context parameter
        context = None
        if args.context:
            try:
                if os.path.exists(args.context):
                    # Load from file
                    with open(args.context, 'r') as f:
                        context = json.load(f)
                else:
                    # Parse as JSON string
                    context = json.loads(args.context)
            except FileNotFoundError:
                print(f"✗ Context file not found: {args.context}", file=sys.stderr)
                return 1
            except PermissionError:
                print(f"✗ Permission denied reading context file: {args.context}", file=sys.stderr)
                return 1
            except json.JSONDecodeError as e:
                print(f"✗ Invalid JSON in context: {e}", file=sys.stderr)
                return 1
        
        # Prepare kwargs
        kwargs = {}
        if args.compression:
            kwargs['compression'] = args.compression
        if context:
            kwargs['context'] = context
        
        print(f"Converting {args.input} to {args.to_format} format...")
        
        result = await discord_convert_export(
            input_path=args.input,
            output_path=args.output,
            to_format=args.to_format,
            **kwargs
        )
        
        if result['status'] == 'success':
            file_size_mb = result['file_size'] / (1024 * 1024)
            print(f"✓ Conversion successful!")
            print(f"  Input: {result['input_path']}")
            print(f"  Output: {result['output_path']}")
            print(f"  Format: {result['from_format']} → {result['to_format']}")
            print(f"  Size: {file_size_mb:.2f} MB")
            return 0
        else:
            print(f"✗ Conversion failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error converting: {e}", file=sys.stderr)
        return 1


async def cmd_batch_convert(args) -> int:
    """Execute batch convert command."""
    try:
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_batch_convert_exports
        
        # Prepare kwargs
        kwargs = {}
        if args.compression:
            kwargs['compression'] = args.compression
        
        print(f"Batch converting files in {args.input_dir}...")
        
        result = await discord_batch_convert_exports(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            to_format=args.to_format,
            file_pattern=args.pattern,
            **kwargs
        )
        
        if result['status'] in ['success', 'partial']:
            print(f"✓ Batch conversion completed!")
            print(f"  Total files: {result['total_files']}")
            print(f"  Successful: {result['successful']}")
            print(f"  Failed: {result['failed']}")
            
            if result['failed'] > 0:
                print(f"\n  ⚠ Some conversions failed. Check output for details.")
                return 2 if result['status'] == 'partial' else 1
            
            return 0
        else:
            print(f"✗ Batch conversion failed: {result.get('error')}", file=sys.stderr)
            return 1
            
    except Exception as e:
        print(f"✗ Error in batch conversion: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[list] = None) -> int:
    """Main entry point for Discord CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Synchronous commands
    if args.command == 'status':
        return cmd_status(args)
    elif args.command == 'install':
        return cmd_install(args)
    
    # Async commands
    async_commands = {
        'guilds': cmd_guilds,
        'channels': cmd_channels,
        'dms': cmd_dms,
        'export': cmd_export,
        'export-guild': cmd_export_guild,
        'export-dms': cmd_export_dms,
        'export-all': cmd_export_all,
        'analyze': cmd_analyze,
        'analyze-export': cmd_analyze_export,
        'convert': cmd_convert,
        'batch-convert': cmd_batch_convert,
    }
    
    handler = async_commands.get(args.command)
    if handler:
        return anyio.run(handler, args)
    else:
        print(f"✗ Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
