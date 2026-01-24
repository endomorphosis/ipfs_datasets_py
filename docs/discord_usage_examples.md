# Discord Data Ingestion - Usage Examples

This document provides comprehensive examples for using the Discord data ingestion features in ipfs_datasets_py.

## Overview

The Discord integration provides three main components:
1. **Discord Chat Exporter Utility** (`ipfs_datasets_py.utils.discord_chat_exporter`) - Low-level CLI tool management
2. **Discord Wrapper** (`ipfs_datasets_py.multimedia.discord_wrapper`) - High-level Python interface
3. **MCP Tools** (`ipfs_datasets_py.mcp_server.tools.discord_tools`) - Model Context Protocol integration

## Installation

The Discord Chat Exporter CLI tool will be automatically downloaded and installed on first use. Supported platforms:
- **Linux**: x64, arm64, arm, musl-x64
- **macOS**: x64, arm64
- **Windows**: x64, x86, arm64

No additional dependencies required beyond standard Python libraries.

## Getting a Discord Token

To export Discord data, you need a Discord bot token or user token. See the [official DiscordChatExporter documentation](https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md) for instructions.

**Security Note**: Never commit your Discord token to source control. Use environment variables or secure configuration management.

## Basic Usage

### 1. Using the High-Level Discord Wrapper

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def main():
    # Initialize wrapper with your token
    wrapper = DiscordWrapper(
        token="YOUR_DISCORD_TOKEN",
        default_format="Json",  # Options: Json, HtmlDark, HtmlLight, Csv, PlainText
        default_output_dir="/path/to/exports"
    )
    
    # List all accessible servers (guilds)
    guilds = await wrapper.list_guilds()
    print(f"Found {guilds['count']} servers")
    for guild in guilds['guilds']:
        print(f"  - {guild['name']} (ID: {guild['id']})")
    
    # List channels in a specific server
    channels = await wrapper.list_channels(guild_id="YOUR_GUILD_ID")
    for channel in channels['channels']:
        print(f"  - {channel['name']} (Category: {channel['category']})")
    
    # Export a single channel
    result = await wrapper.export_channel(
        channel_id="YOUR_CHANNEL_ID",
        format="Json",
        download_media=True  # Download attachments, avatars, etc.
    )
    print(f"Exported to: {result['output_path']}")

asyncio.run(main())
```

### 2. Exporting Entire Servers

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def export_server():
    wrapper = DiscordWrapper(token="YOUR_DISCORD_TOKEN")
    
    # Export all channels in a server
    result = await wrapper.export_guild(
        guild_id="YOUR_GUILD_ID",
        output_dir="/path/to/server_exports",
        format="Json",
        include_threads="all",  # Options: 'none', 'active', 'all'
        include_vc=True  # Include voice channels
    )
    
    print(f"Exported {result['channels_exported']} channels")
    print(f"Time taken: {result['export_time']:.2f} seconds")

asyncio.run(export_server())
```

### 3. Advanced Filtering and Date Ranges

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def filtered_export():
    wrapper = DiscordWrapper(token="YOUR_DISCORD_TOKEN")
    
    # Export with date range and message filtering
    result = await wrapper.export_channel(
        channel_id="YOUR_CHANNEL_ID",
        after="2024-01-01",  # Messages after this date
        before="2024-12-31",  # Messages before this date
        filter_text="from:username has:image",  # Message filter expression
        partition_limit="1000"  # Split into files of 1000 messages each
    )
    
    print(f"Export completed: {result['status']}")

asyncio.run(filtered_export())
```

### 4. Exporting Direct Messages

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def export_dms():
    wrapper = DiscordWrapper(token="YOUR_DISCORD_TOKEN")
    
    # List all DM channels
    dms = await wrapper.list_dm_channels()
    print(f"Found {dms['count']} DM channels")
    
    # Export a specific DM channel
    result = await wrapper.export_channel(
        channel_id=dms['channels'][0]['id'],
        format="HtmlDark"
    )
    
    print(f"DM exported to: {result['output_path']}")

asyncio.run(export_dms())
```

## Using MCP Tools

The MCP tools provide a standardized interface for AI assistants and automation systems.

### 1. Listing Servers and Channels

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_list_guilds,
    discord_list_channels,
    discord_list_dm_channels
)

async def list_discord_data():
    # List all servers
    guilds_result = await discord_list_guilds(token="YOUR_TOKEN")
    
    # List channels in a server
    channels_result = await discord_list_channels(
        guild_id="YOUR_GUILD_ID",
        token="YOUR_TOKEN"
    )
    
    # List DM channels
    dm_result = await discord_list_dm_channels(token="YOUR_TOKEN")
    
    print(f"Guilds: {guilds_result['count']}")
    print(f"Channels: {channels_result['count']}")
    print(f"DMs: {dm_result['count']}")

asyncio.run(list_discord_data())
```

### 2. Exporting with MCP Tools

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_export_channel,
    discord_export_guild,
    discord_export_all_channels
)

async def mcp_exports():
    # Export a single channel
    channel_result = await discord_export_channel(
        channel_id="YOUR_CHANNEL_ID",
        token="YOUR_TOKEN",
        format="Json",
        download_media=True
    )
    
    # Export entire server
    guild_result = await discord_export_guild(
        guild_id="YOUR_GUILD_ID",
        token="YOUR_TOKEN",
        include_threads="all"
    )
    
    # Export everything accessible
    all_result = await discord_export_all_channels(
        token="YOUR_TOKEN",
        format="Csv"
    )
    
    print(f"Channel export: {channel_result['status']}")
    print(f"Guild export: {guild_result['status']}")
    print(f"All channels export: {all_result['status']}")

asyncio.run(mcp_exports())
```

### 3. Analyzing Discord Data

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_analyze_channel,
    discord_analyze_guild,
    discord_analyze_export
)

async def analyze_discord():
    # Analyze a channel (automatically exports first)
    analysis = await discord_analyze_channel(
        channel_id="YOUR_CHANNEL_ID",
        token="YOUR_TOKEN",
        analysis_types=[
            'message_stats',    # Basic message statistics
            'user_activity',    # User activity patterns
            'content_patterns', # Content analysis
            'time_patterns'     # Temporal patterns
        ]
    )
    
    # Print analysis results
    if analysis['status'] == 'success':
        stats = analysis['analyses']['message_stats']
        print(f"Total messages: {stats['total_messages']}")
        print(f"Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")
        
        activity = analysis['analyses']['user_activity']
        print(f"Active users: {activity['total_users']}")
        print(f"Most active: {activity['most_active_user']}")
    
    # Analyze a previously exported file
    file_analysis = await discord_analyze_export(
        export_path="/path/to/export.json"
    )
    
    print(f"File analysis: {file_analysis['status']}")

asyncio.run(analyze_discord())
```

## Advanced Usage

### 1. Low-Level CLI Control

For advanced users who need direct control over the DiscordChatExporter CLI:

```python
from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter

# Initialize with custom settings
exporter = DiscordChatExporter(
    install_dir="/custom/install/path",
    version="2.46"  # Specific version
)

# Download and install
if not exporter.is_installed():
    exporter.download_and_install()

# Verify installation
if exporter.verify_installation():
    print(f"Installed version: {exporter.get_version()}")

# Execute raw CLI commands
result = exporter.execute([
    'export',
    '-c', 'CHANNEL_ID',
    '-t', 'YOUR_TOKEN',
    '-f', 'Json',
    '-o', '/output/path.json'
], timeout=300)

print(f"Exit code: {result.returncode}")
print(f"Output: {result.stdout}")
```

### 2. Batch Processing Multiple Servers

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def batch_export_servers():
    wrapper = DiscordWrapper(token="YOUR_TOKEN", default_format="Json")
    
    # Get all servers
    guilds = await wrapper.list_guilds()
    
    # Export each server
    for guild in guilds['guilds']:
        print(f"Exporting {guild['name']}...")
        
        result = await wrapper.export_guild(
            guild_id=guild['id'],
            output_dir=f"/exports/{guild['name']}",
            include_threads="active"
        )
        
        print(f"  - Status: {result['status']}")
        print(f"  - Channels: {result.get('channels_exported', 0)}")
        print(f"  - Time: {result['export_time']:.2f}s")

asyncio.run(batch_export_servers())
```

### 3. Custom Export Formats

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def multiple_formats():
    wrapper = DiscordWrapper(token="YOUR_TOKEN")
    
    channel_id = "YOUR_CHANNEL_ID"
    
    # Export in multiple formats
    formats = ['Json', 'HtmlDark', 'Csv', 'PlainText']
    
    for fmt in formats:
        result = await wrapper.export_channel(
            channel_id=channel_id,
            format=fmt,
            output_path=f"/exports/channel_{channel_id}.{fmt.lower()}"
        )
        print(f"{fmt}: {result['status']}")

asyncio.run(multiple_formats())
```

### 4. Error Handling

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def safe_export():
    try:
        wrapper = DiscordWrapper(token="YOUR_TOKEN")
        
        result = await wrapper.export_channel(
            channel_id="INVALID_ID"
        )
        
        if result['status'] == 'error':
            print(f"Export failed: {result['error']}")
        else:
            print(f"Export successful: {result['output_path']}")
            
    except ValueError as e:
        print(f"Configuration error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

asyncio.run(safe_export())
```

## Integration with IPFS

Combine Discord exports with IPFS storage:

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper
# Assuming you have IPFS integration available

async def export_to_ipfs():
    wrapper = DiscordWrapper(token="YOUR_TOKEN")
    
    # Export channel
    result = await wrapper.export_channel(
        channel_id="YOUR_CHANNEL_ID",
        format="Json"
    )
    
    if result['status'] == 'success':
        export_path = result['output_path']
        
        # Add to IPFS (example - adjust based on your IPFS integration)
        # ipfs_hash = await ipfs_client.add_file(export_path)
        # print(f"Discord export stored on IPFS: {ipfs_hash}")
        
        print(f"Ready to upload to IPFS: {export_path}")

asyncio.run(export_to_ipfs())
```

## Best Practices

1. **Token Security**: Store tokens in environment variables or secure vaults
2. **Rate Limiting**: Discord has rate limits; space out large batch operations
3. **Storage**: Discord exports can be large; ensure adequate disk space
4. **Privacy**: Respect user privacy and Discord's Terms of Service
5. **Backup**: Keep backups of important channel exports
6. **Format Selection**: 
   - Use JSON for programmatic processing
   - Use HTML for human-readable archives
   - Use CSV for data analysis
   - Use PlainText for simple text searches

## Troubleshooting

### Binary Installation Issues

```python
from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter

exporter = DiscordChatExporter()

# Check if already installed
if exporter.is_installed():
    print("✓ Already installed")
else:
    print("Installing...")
    success = exporter.download_and_install(force=True)
    if success:
        print("✓ Installation successful")
    else:
        print("✗ Installation failed")

# Verify
if exporter.verify_installation():
    print(f"✓ Working: {exporter.get_version()}")
```

### Platform Detection

```python
from ipfs_datasets_py.utils.discord_chat_exporter import DiscordChatExporter

exporter = DiscordChatExporter()
print(f"Platform: {exporter.platform_name}")
print(f"Architecture: {exporter.arch}")
print(f"Download URL: {exporter.get_download_url()}")
```

## Additional Resources

- [DiscordChatExporter Repository](https://github.com/Tyrrrz/DiscordChatExporter)
- [Discord API Documentation](https://discord.com/developers/docs/intro)
- [Message Filter Syntax](https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Message-filters.md)
- [Token and IDs Guide](https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md)

## Support

For issues specific to:
- **Discord integration**: Open an issue in ipfs_datasets_py repository
- **DiscordChatExporter CLI**: See [upstream repository](https://github.com/Tyrrrz/DiscordChatExporter)
- **Discord API**: Check [Discord Developer Portal](https://discord.com/developers/docs)
