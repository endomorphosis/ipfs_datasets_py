# Discord Tools

MCP tools for exporting, listing, converting, and analysing Discord chat data.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `discord_export.py` | `discord_export_channel()`, `discord_export_server()`, `discord_export_dm()` | Export Discord channels/servers/DMs to JSON via DiscordChatExporter |
| `discord_list.py` | `discord_list_servers()`, `discord_list_channels()`, `discord_list_dms()` | List available servers, channels, and DMs |
| `discord_convert.py` | `discord_convert()` | Convert Discord exports between JSON, JSONL, JSON-LD, Parquet, IPLD, CAR |
| `discord_analyze.py` | `discord_analyze_messages()`, `discord_user_activity()`, `discord_content_stats()` | Message statistics, user activity, content analysis |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_export_channel, discord_convert, discord_analyze_messages
)

# Export a channel
export = await discord_export_channel(
    token="YOUR_DISCORD_TOKEN",
    channel_id="123456789",
    output_path="/data/discord_export.json",
    date_after="2024-01-01"
)

# Convert to Parquet
await discord_convert(
    input_path="/data/discord_export.json",
    output_path="/data/discord_export.parquet",
    output_format="parquet"
)

# Analyse message activity
analysis = await discord_analyze_messages(
    input_path="/data/discord_export.json",
    metrics=["volume_per_day", "top_users", "keyword_frequency"]
)
```

## Dependencies

- `DiscordChatExporter` CLI binary — for channel/server exports
- `pyarrow` — for Parquet conversion

## Status

| Tool | Status |
|------|--------|
| `discord_export` | ✅ Production ready (requires DiscordChatExporter binary) |
| `discord_list` | ✅ Production ready |
| `discord_convert` | ✅ Production ready |
| `discord_analyze` | ✅ Production ready |
