# Alert Tools

MCP tools for sending Discord notifications and managing alert rules.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `discord_alert_tools.py` | `send_discord_message()`, `create_alert_rule()`, `list_alert_rules()`, `delete_alert_rule()` | Send Discord messages and manage per-event alert rules |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.alert_tools import (
    send_discord_message, create_alert_rule
)

# Send a message to Discord
await send_discord_message(
    webhook_url="https://discord.com/api/webhooks/...",
    content="🚨 IPFS node disk usage above 90%",
    username="IPFS Monitor"
)

# Create an alert rule
await create_alert_rule(
    name="high_disk_usage",
    condition="disk_usage > 0.9",
    action="discord",
    webhook_url="https://discord.com/api/webhooks/..."
)
```

## Dependencies

- `requests` or `aiohttp` — HTTP webhook delivery

## Status

| Tool | Status |
|------|--------|
| `discord_alert_tools` | ✅ Production ready |
