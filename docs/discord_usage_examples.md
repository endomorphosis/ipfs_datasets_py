# Discord Data Ingestion - Usage Examples

This document provides comprehensive examples for using the Discord data ingestion features in ipfs_datasets_py.

## Overview

The Discord integration provides three main components:
1. **Discord Chat Exporter Utility** (`ipfs_datasets_py.utils.discord_chat_exporter`) - Low-level CLI tool management
2. **Discord Wrapper** (`ipfs_datasets_py.multimedia.discord_wrapper`) - High-level Python interface
3. **MCP Tools** (`ipfs_datasets_py.mcp_server.tools.discord_tools`) - Model Context Protocol integration
4. **Discord Dashboard** (`ipfs_datasets_py.discord_dashboard`) - Web-based management UI

## Installation

The Discord Chat Exporter CLI tool will be automatically downloaded and installed on first use. Supported platforms:
- **Linux**: x64, arm64, arm, musl-x64
- **macOS**: x64, arm64
- **Windows**: x64, x86, arm64

No additional dependencies required beyond standard Python libraries.

## Token Management

### Environment Variable (Recommended)

Set the `DISCORD_TOKEN` environment variable for automatic token management:

```bash
# Linux/macOS
export DISCORD_TOKEN="your_discord_token_here"

# Windows (PowerShell)
$env:DISCORD_TOKEN="your_discord_token_here"

# Windows (CMD)
set DISCORD_TOKEN=your_discord_token_here
```

With this configured, all Discord tools will automatically use the token:

```python
from ipfs_datasets_py.multimedia import DiscordWrapper

# Token automatically loaded from environment
wrapper = DiscordWrapper()
guilds = await wrapper.list_guilds()
```

### Direct Token Parameter

You can also pass the token directly (not recommended for production):

```python
wrapper = DiscordWrapper(token="YOUR_TOKEN")
```

### Secure Token Storage

For production environments, consider using:
- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- Environment variables in secure CI/CD systems

## Getting a Discord Token

To export Discord data, you need a Discord bot token or user token. See the [official DiscordChatExporter documentation](https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md) for instructions.

**Security Note**: Never commit your Discord token to source control. Use environment variables or secure configuration management.

## Using the Discord Dashboard

The Discord dashboard provides a web-based interface for managing Discord data exports and analytics.

### Starting the Dashboard

```bash
# Start standalone dashboard
python -m ipfs_datasets_py.discord_dashboard --port 8889

# Or integrate with admin dashboard
python -m ipfs_datasets_py.admin_dashboard
# Dashboard available at: http://localhost:8888/mcp/discord
```

### Dashboard Features

- **Token Management**: Test and validate Discord tokens
- **Server Browser**: View all accessible Discord servers
- **Channel Explorer**: Browse channels within servers
- **Export Manager**: Configure and run exports with advanced options
- **Analytics**: View message statistics, user activity, and content patterns
- **Status Monitor**: Check integration health and configuration

### API Endpoints

The dashboard exposes REST API endpoints:

- `POST /api/test_token` - Validate Discord token
- `GET /api/list_guilds` - List accessible servers
- `GET /api/list_channels/<guild_id>` - List channels in server
- `POST /api/export_channel` - Export channel data
- `POST /api/export_guild` - Export server data
- `GET /api/analyze_channel/<channel_id>` - Analyze channel
- `POST /api/analyze_export` - Analyze exported file
- `GET /api/status` - Get integration status

### Using the Dashboard API

```python
import requests

# Test token
response = requests.post('http://localhost:8889/mcp/discord/api/test_token', 
                        json={"token": "YOUR_TOKEN"})
print(response.json())

# List guilds (uses DISCORD_TOKEN from environment)
response = requests.get('http://localhost:8889/mcp/discord/api/list_guilds')
guilds = response.json()['guilds']

# Export channel
response = requests.post('http://localhost:8889/mcp/discord/api/export_channel',
                        json={
                            "channel_id": "123456789",
                            "format": "Json",
                            "download_media": True
                        })
print(response.json())
```

## Using the Discord CLI

The comprehensive Discord CLI provides command-line access to all Discord features.

### Installation Check

```bash
# Check if DiscordChatExporter is installed
ipfs-datasets discord status

# Install if needed
ipfs-datasets discord install
```

### List Servers and Channels

```bash
# List all accessible Discord servers
ipfs-datasets discord guilds

# List channels in a specific server
ipfs-datasets discord channels GUILD_ID

# List all DM channels
ipfs-datasets discord dms
```

### Export Commands

```bash
# Export a single channel
ipfs-datasets discord export CHANNEL_ID --format Json --media

# Export with date range and filter
ipfs-datasets discord export CHANNEL_ID \
  --format HtmlDark \
  --after 2024-01-01 \
  --before 2024-12-31 \
  --filter "from:username has:image"

# Export entire server with threads
ipfs-datasets discord export-guild GUILD_ID \
  --format Json \
  --threads all

# Export all DMs using native exportdm (most efficient)
ipfs-datasets discord export-dms --format Json --media

# Export all accessible content
ipfs-datasets discord export-all --format Csv
```

### Analysis Commands

```bash
# Analyze a channel (exports first, then analyzes)
ipfs-datasets discord analyze CHANNEL_ID \
  --types message_stats,user_activity,content_patterns

# Analyze a previously exported file
ipfs-datasets discord analyze-export /path/to/export.json \
  --types message_stats,user_activity

# Save analysis to file
ipfs-datasets discord analyze CHANNEL_ID --output analysis.json
```

### CLI Help

```bash
# Show all available commands
ipfs-datasets discord --help

# Show help for specific command
ipfs-datasets discord export --help
```

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

#### Native exportdm (Recommended - Most Efficient)

```python
import asyncio
from ipfs_datasets_py.multimedia import DiscordWrapper

async def export_all_dms():
    wrapper = DiscordWrapper(token="YOUR_DISCORD_TOKEN")
    
    # Export all DMs using native exportdm command (most efficient)
    result = await wrapper.export_dm(
        format="Json",
        output_dir="/exports/dms"
    )
    
    print(f"Exported {result['dm_channels_exported']} DM channels")
    print(f"Output: {result['output_dir']}")

asyncio.run(export_all_dms())
```

#### Individual DM Export

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

**Note**: Use `export_dm()` for exporting all DMs at once - it's significantly faster than exporting each DM individually as it uses Discord ChatExporter's native `exportdm` command.

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
    discord_export_dm_channels,  # Native exportdm
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
    
    # Export all DMs using native exportdm (most efficient)
    dm_result = await discord_export_dm_channels(
        token="YOUR_TOKEN",
        format="Json"
    )
    
    # Export everything accessible
    all_result = await discord_export_all_channels(
        token="YOUR_TOKEN",
        format="Csv"
    )
    
    print(f"Channel export: {channel_result['status']}")
    print(f"Guild export: {guild_result['status']}")
    print(f"DM export: {dm_result['status']} - {dm_result['dm_channels_exported']} channels")
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

## Format Conversion

### Universal Data Format Converter

The Discord integration includes a universal data format converter that supports conversion between 12+ formats. This is a package-wide utility available to all modules.

#### Supported Formats

- **JSON**: Standard JSON format
- **JSONL**: JSON Lines (newline-delimited, streaming-friendly)
- **JSON-LD**: JSON Linked Data with semantic web context
- **JSON-LD-LOGIC**: JSON-LD with formal logic annotations
- **Parquet**: Apache Parquet (columnar, analytics-optimized)
- **IPLD**: InterPlanetary Linked Data (content-addressed)
- **CAR**: Content Addressable aRchive (IPFS format)
- **Arrow**: Apache Arrow tables
- **CSV**: Comma-separated values
- **DataFrame**: Pandas DataFrames
- **HuggingFace**: HuggingFace Dataset objects
- **Dict/List**: Python native formats

### CLI Format Conversion

#### Convert Single File

```bash
# Convert Discord JSON export to JSONL (streaming)
ipfs-datasets discord convert chat.json chat.jsonl --to-format jsonl

# Convert to Parquet with compression
ipfs-datasets discord convert chat.json chat.parquet \
  --to-format parquet \
  --compression snappy

# Convert to JSON-LD with semantic annotations
ipfs-datasets discord convert chat.json chat.json-ld \
  --to-format jsonld

# Convert to JSON-LD-LOGIC with formal logic
ipfs-datasets discord convert chat.json chat.logic.json-ld \
  --to-format jsonld-logic

# Convert to IPLD (content-addressed)
ipfs-datasets discord convert chat.json chat.ipld \
  --to-format ipld

# Convert to CAR (IPFS archive)
ipfs-datasets discord convert chat.json chat.car \
  --to-format car

# Convert to CSV
ipfs-datasets discord convert chat.json chat.csv \
  --to-format csv
```

#### Batch Convert Directory

```bash
# Convert all JSON files in a directory to Parquet
ipfs-datasets discord batch-convert \
  ./exports/json/ \
  ./exports/parquet/ \
  --to-format parquet

# Convert with custom pattern and compression
ipfs-datasets discord batch-convert \
  ./exports/ \
  ./converted/ \
  --to-format parquet \
  --pattern "channel_*.json" \
  --compression gzip
```

### Python Package Format Conversion

#### Using Universal Converter

```python
from ipfs_datasets_py.utils.data_format_converter import get_converter

# Get the global converter instance
converter = get_converter()

# Convert between any supported formats
converter.convert_file("data.json", "data.jsonl", to_format="jsonl")
converter.convert_file("data.json", "data.parquet", to_format="parquet")
converter.convert_file("data.json", "data.json-ld", to_format="jsonld")

# Convert with options
converter.convert_file(
    "data.json",
    "data.parquet",
    to_format="parquet",
    compression="snappy"
)

# Convert with custom JSON-LD context
converter.convert_file(
    "data.json",
    "data.json-ld",
    to_format="jsonld",
    context={
        "@vocab": "http://schema.org/",
        "discord": "https://discord.com/developers/docs/"
    }
)

# Programmatic conversion (in-memory)
data = [{"id": 1, "text": "Hello"}, {"id": 2, "text": "World"}]
parquet_table = converter.convert(data, "list", "parquet")
jsonld_data = converter.convert(data, "list", "jsonld")
```

#### Using Discord Wrapper

```python
from ipfs_datasets_py.multimedia import DiscordWrapper
import asyncio

async def convert_exports():
    wrapper = DiscordWrapper()
    
    # Export Discord channel
    export_result = await wrapper.export_channel(
        channel_id="123456789",
        output_path="channel.json"
    )
    
    # Convert to multiple formats
    await wrapper.convert_export(
        "channel.json",
        "channel.jsonl",
        to_format="jsonl"
    )
    
    await wrapper.convert_export(
        "channel.json",
        "channel.parquet",
        to_format="parquet",
        compression="snappy"
    )
    
    await wrapper.convert_export(
        "channel.json",
        "channel.json-ld",
        to_format="jsonld",
        context={"discord": "https://discord.com/developers/docs/"}
    )

asyncio.run(convert_exports())
```

### MCP Tools Format Conversion

```python
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_convert_export,
    discord_batch_convert_exports
)

# Convert single export
result = await discord_convert_export(
    input_path="channel.json",
    output_path="channel.parquet",
    to_format="parquet",
    compression="snappy"
)

print(f"Status: {result['status']}")
print(f"Output: {result['output_path']}")
print(f"Size: {result['file_size']} bytes")

# Batch convert multiple exports
batch_result = await discord_batch_convert_exports(
    input_dir="./exports/json/",
    output_dir="./exports/parquet/",
    to_format="parquet",
    file_pattern="*.json",
    compression="snappy"
)

print(f"Total files: {batch_result['total_files']}")
print(f"Successful: {batch_result['successful']}")
print(f"Failed: {batch_result['failed']}")
```

### Format-Specific Features

#### JSON-LD with Semantic Context

```python
from ipfs_datasets_py.utils.data_format_converter import get_converter

converter = get_converter()

# Convert with custom semantic context
converter.convert_file(
    "discord_export.json",
    "discord_export.json-ld",
    to_format="jsonld",
    context={
        "@vocab": "http://schema.org/",
        "discord": "https://discord.com/developers/docs/",
        "Message": "discord:Message",
        "User": "discord:User",
        "Guild": "discord:Guild",
        "Channel": "discord:Channel",
        "createdAt": {"@type": "http://www.w3.org/2001/XMLSchema#dateTime"},
        "content": "http://schema.org/text"
    }
)
```

#### JSON-LD-LOGIC with Formal Annotations

```python
# Convert with formal logic annotations
converter.convert_file(
    "discord_export.json",
    "discord_export.logic.json-ld",
    to_format="jsonld-logic"
)

# The output includes logic annotations:
# {
#   "@context": {
#     "logic": "http://www.w3.org/ns/logic#",
#     "fol": "http://www.w3.org/ns/logic/fol#",
#     "modal": "http://www.w3.org/ns/logic/modal#",
#     "deontic": "http://www.w3.org/ns/logic/deontic#"
#   },
#   "logic:annotations": {
#     "fol:axioms": [],
#     "fol:rules": [],
#     "modal:operators": [],
#     "deontic:obligations": [],
#     "deontic:permissions": [],
#     "deontic:prohibitions": []
#   },
#   "@graph": [ ... data ... ]
# }
```

#### Parquet with Compression

```python
# Convert to Parquet with different compression algorithms
converter.convert_file(
    "large_export.json",
    "large_export.parquet",
    to_format="parquet",
    compression="snappy"  # Fast compression
)

converter.convert_file(
    "large_export.json",
    "large_export.parquet",
    to_format="parquet",
    compression="gzip"  # Better compression ratio
)

converter.convert_file(
    "large_export.json",
    "large_export.parquet",
    to_format="parquet",
    compression="brotli"  # Best compression
)
```

#### IPLD and CAR for IPFS

```python
# Convert to IPLD (content-addressed)
converter.convert_file(
    "discord_export.json",
    "discord_export.ipld",
    to_format="ipld"
)

# Convert to CAR (IPFS archive)
converter.convert_file(
    "discord_export.json",
    "discord_export.car",
    to_format="car"
)

# The output can be directly added to IPFS:
# ipfs dag import discord_export.car
```

### Complete Workflow Example

```python
from ipfs_datasets_py.multimedia import DiscordWrapper
from ipfs_datasets_py.utils.data_format_converter import get_converter
import asyncio

async def complete_workflow():
    """Complete workflow: Export -> Convert -> Analyze"""
    wrapper = DiscordWrapper()
    converter = get_converter()
    
    # 1. Export Discord channel
    print("Exporting Discord channel...")
    export_result = await wrapper.export_channel(
        channel_id="123456789",
        output_path="channel.json",
        format="Json",
        download_media=True
    )
    
    # 2. Convert to multiple formats for different use cases
    print("Converting to multiple formats...")
    
    # JSONL for streaming processing
    converter.convert_file(
        "channel.json",
        "channel.jsonl",
        to_format="jsonl"
    )
    
    # Parquet for analytics
    converter.convert_file(
        "channel.json",
        "channel.parquet",
        to_format="parquet",
        compression="snappy"
    )
    
    # JSON-LD for semantic web
    converter.convert_file(
        "channel.json",
        "channel.json-ld",
        to_format="jsonld",
        context={"discord": "https://discord.com/developers/docs/"}
    )
    
    # IPLD for IPFS
    converter.convert_file(
        "channel.json",
        "channel.ipld",
        to_format="ipld"
    )
    
    # 3. Analyze the data
    print("Analyzing Discord data...")
    from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze_export
    
    analysis = await discord_analyze_export(
        export_path="channel.json",
        analysis_types=["message_stats", "user_activity", "content_patterns"]
    )
    
    print(f"Total messages: {analysis['message_stats']['total_messages']}")
    print(f"Unique users: {analysis['user_activity']['unique_users']}")
    
    return {
        "export": export_result,
        "formats": ["json", "jsonl", "parquet", "jsonld", "ipld"],
        "analysis": analysis
    }

# Run the complete workflow
result = asyncio.run(complete_workflow())
```

### Integration with IPFS Workflows

```python
from ipfs_datasets_py.multimedia import DiscordWrapper
from ipfs_datasets_py.utils.data_format_converter import get_converter
import subprocess

async def export_to_ipfs():
    """Export Discord data and add to IPFS"""
    wrapper = DiscordWrapper()
    converter = get_converter()
    
    # Export Discord server
    await wrapper.export_guild(
        guild_id="987654321",
        output_dir="./discord_server/",
        format="Json"
    )
    
    # Convert all exports to CAR format
    await wrapper.convert_export(
        "./discord_server/export.json",
        "./discord_server/export.car",
        to_format="car"
    )
    
    # Add to IPFS
    result = subprocess.run(
        ["ipfs", "dag", "import", "./discord_server/export.car"],
        capture_output=True,
        text=True
    )
    
    print(f"IPFS CID: {result.stdout.strip()}")
    
    return result.stdout.strip()
```

## Best Practices

### Format Selection Guide

- **JSON**: Standard format, human-readable, good for small-medium datasets
- **JSONL**: Streaming, line-by-line processing, good for large datasets
- **JSON-LD**: Semantic web integration, linked data, graph databases
- **JSON-LD-LOGIC**: Formal logic systems, theorem provers, reasoning engines
- **Parquet**: Analytics, data warehouses, columnar queries, compression
- **IPLD**: IPFS storage, content addressing, decentralized applications
- **CAR**: IPFS archiving, bulk imports, offline IPFS bundles
- **CSV**: Spreadsheets, simple analytics, legacy system integration

### Performance Considerations

- Use **JSONL** for streaming large datasets
- Use **Parquet with snappy** for fast analytics
- Use **Parquet with gzip/brotli** for storage optimization
- Convert to **IPLD/CAR** before adding to IPFS
- Use **batch conversion** for multiple files

### Storage Optimization

```python
# Compare file sizes across formats
import os

files = {
    "JSON": "channel.json",
    "JSONL": "channel.jsonl",
    "Parquet (snappy)": "channel.snappy.parquet",
    "Parquet (gzip)": "channel.gzip.parquet",
}

for name, path in files.items():
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"{name}: {size_mb:.2f} MB")
```

## Troubleshooting

### Missing Dependencies

If you get import errors for specific formats:

```bash
# For Parquet/Arrow support
pip install pyarrow

# For Pandas/DataFrame support
pip install pandas

# For HuggingFace datasets
pip install datasets

# For IPLD/CAR support (already included)
# These are built into ipfs_datasets_py
```

### Conversion Errors

```python
from ipfs_datasets_py.utils.data_format_converter import get_converter

converter = get_converter()

try:
    result = converter.convert_file("input.json", "output.parquet", to_format="parquet")
except ImportError as e:
    print(f"Missing dependency: {e}")
except ValueError as e:
    print(f"Invalid format or data: {e}")
except Exception as e:
    print(f"Conversion error: {e}")
```

## Summary

The Discord integration provides comprehensive format conversion capabilities:

✅ **12+ supported formats** - JSON, JSONL, JSON-LD, JSON-LD-LOGIC, Parquet, IPLD, CAR, Arrow, CSV, DataFrame, HuggingFace, native types
✅ **Package-wide utility** - Centralized converter used across all modules
✅ **All access methods** - CLI, Python package, MCP tools, MCP server, dashboard
✅ **Format-specific features** - Compression, semantic context, logic annotations
✅ **IPFS integration** - Native IPLD and CAR format support
✅ **Batch processing** - Convert multiple files efficiently
✅ **Streaming support** - JSONL format for large datasets

For more examples and advanced usage, see the main Discord documentation.
