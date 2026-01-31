# Discord Alerts System Guide

Complete guide for using the Discord alert system for financial market monitoring and GraphRAG analysis.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage Methods](#usage-methods)
  - [Python API](#python-api)
  - [CLI Usage](#cli-usage)
  - [MCP Server Tools](#mcp-server-tools)
- [Alert Rules](#alert-rules)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

The Discord Alert System provides:

- **Two integration modes**: Bot (full features) and Webhook (simple)
- **Safe rule engine**: JSON-Logic style predicates without eval()
- **Statistical predicates**: zscore, sma, ema, stddev, percent_change
- **Rule-based alerting**: Load rules from YAML, evaluate events
- **Suppression windows**: Prevent alert spam with debouncing
- **Rich embeds**: Multi-field messages with colors and formatting
- **Role mentions**: Notify specific Discord roles
- **MCP integration**: 8 tools accessible via MCP server

## Installation

### Basic Installation

```bash
# Install with alerts support
pip install -e ".[alerts]"

# Or install specific dependencies
pip install discord.py aiohttp PyYAML pytest-asyncio
```

### Full Installation

```bash
# Install all features including alerts
pip install -e ".[all]"
```

## Configuration

### Discord Setup

#### Webhook Mode (Simplest)

1. In Discord, go to Server Settings > Integrations > Webhooks
2. Create a new webhook for your desired channel
3. Copy the webhook URL

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
```

#### Bot Mode (Full Features)

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to Bot section and create a bot
4. Enable required intents: Message Content, Guild Messages
5. Copy the bot token
6. Invite bot to your server with appropriate permissions

```bash
export DISCORD_BOT_TOKEN="your_bot_token_here"
export DISCORD_GUILD_ID="your_guild_id"
export DISCORD_CHANNEL_ID="your_channel_id"
export DISCORD_ROLE_MAP='{"trader":"role_id_1","analyst":"role_id_2"}'
```

### Configuration Files

#### `config/discord.yml`

```yaml
mode: webhook  # or "bot"

# Bot configuration
bot_token: ${DISCORD_BOT_TOKEN}
guild_id: ${DISCORD_GUILD_ID}
channel_id: ${DISCORD_CHANNEL_ID}

# Webhook configuration
webhook_url: ${DISCORD_WEBHOOK_URL}

# Role mapping (name -> Discord role ID)
role_map:
  trader: "123456789012345678"
  analyst: "234567890123456789"
  admin: "345678901234567890"
```

#### `config/alert_rules.yml`

Example rules for financial monitoring:

```yaml
rules:
  - rule_id: price_spike_alert
    name: Price Spike Alert
    description: Triggers when stock price increases rapidly
    enabled: true
    severity: warning
    suppression_window: 300
    
    condition:
      and:
        - ">": 
            - var: "price"
            - 100
        - ">":
            - percent_change: ["price", 1]
            - 5.0
    
    message_template: |
      🚨 Price Spike Detected!
      Symbol: {symbol}
      Current Price: ${price}
      Change: {percent_change}%
    
    role_names:
      - trader
      - alerts
    
    embed_config:
      title: "Price Spike Alert"
      description: "Rapid price increase detected"
      fields:
        - name: "Symbol"
          value: "{symbol}"
          inline: true
        - name: "Price"
          value: "${price}"
          inline: true
```

See `config/alert_rules.yml` for more examples.

## Usage Methods

### Python API

#### Basic Message

```python
import asyncio
from ipfs_datasets_py.alerts import DiscordNotifier, DiscordEmbed

async def send_alert():
    # Initialize notifier (webhook mode)
    notifier = DiscordNotifier(
        mode="webhook",
        webhook_url="https://discord.com/api/webhooks/..."
    )
    
    # Send basic message
    result = await notifier.send_message(
        text="🚨 Market alert: Price spike detected!"
    )
    
    await notifier.close()

asyncio.run(send_alert())
```

#### Rich Embed

```python
from ipfs_datasets_py.alerts import DiscordNotifier, DiscordEmbed

async def send_embed():
    notifier = DiscordNotifier(mode="webhook", webhook_url="...")
    
    embed = DiscordEmbed(
        title="📊 Market Alert",
        description="AAPL price spike detected",
        color=0x00ff00,  # Green
        fields=[
            {"name": "Price", "value": "$175.50", "inline": True},
            {"name": "Change", "value": "+5.2%", "inline": True},
        ],
        footer="Alert System | 2024-01-15 10:30:00"
    )
    
    result = await notifier.send_message(
        embed=embed,
        role_names=["trader"]  # Mention role
    )
    
    await notifier.close()

asyncio.run(send_embed())
```

#### Rule-Based Alerts

```python
from ipfs_datasets_py.alerts import (
    DiscordNotifier, AlertManager, AlertRule
)

async def monitor_market():
    # Setup
    notifier = DiscordNotifier(
        config_file="config/discord.yml"
    )
    manager = AlertManager(
        notifier=notifier,
        config_file="config/alert_rules.yml"
    )
    
    # Evaluate market event
    event = {
        "symbol": "AAPL",
        "price": 175.50,
        "change_pct": 7.2,
        "volume": 85000000,
        "timestamp": "2024-01-15T10:30:00Z"
    }
    
    results = await manager.evaluate_event(event)
    
    for result in results:
        if result['status'] == 'triggered':
            print(f"Alert triggered: {result['rule_name']}")
    
    await notifier.close()

asyncio.run(monitor_market())
```

#### Custom Rules

```python
from ipfs_datasets_py.alerts import AlertRule, AlertManager

# Create custom rule
custom_rule = AlertRule(
    rule_id="my_custom_alert",
    name="My Custom Alert",
    description="Custom trading signal",
    condition={
        "and": [
            {">": [{"var": "price"}, 150]},
            {"<": [{"var": "volume"}, 50000000]}
        ]
    },
    message_template="Custom alert: {symbol} at ${price}",
    severity="info",
    suppression_window=600  # 10 minutes
)

# Add to manager
manager.add_rule(custom_rule)
```

#### Statistical Predicates

```python
from ipfs_datasets_py.alerts import RuleEngine

# Using statistical predicates
rule = {
    "and": [
        # Price > 20-period SMA
        {">": [{"var": "price"}, {"sma": ["price", 20]}]},
        # Z-score > 2 (unusual)
        {">": [{"zscore": ["volume", 20]}, 2.0]}
    ]
}

engine = RuleEngine()

# Evaluate with streaming data
for data_point in market_stream:
    matched = engine.evaluate(rule, data_point)
    if matched:
        print(f"Rule matched: {data_point}")
```

### CLI Usage

The alert tools are accessible via the `scripts/cli/enhanced_cli.py` (deprecated, use `ipfs-datasets` CLI instead):

```bash
# List alert tools (deprecated)
python scripts/cli/enhanced_cli.py --list-tools alert_tools

# Recommended - use main CLI
ipfs-datasets tools list alert_tools

# The tools are available as functions in the discord_alert_tools module
# For direct Python usage, see the Python API examples above

# Or use the demonstration script
python examples/discord_alerts_demo.py --dry-run
python examples/discord_alerts_demo.py --mode webhook
python examples/discord_alerts_demo.py --demo 3  # Run specific demo
```

### MCP Server Tools

8 tools available via MCP protocol:

1. **send_discord_message**: Send plain text message
2. **send_discord_embed**: Send rich embed message
3. **evaluate_alert_rules**: Evaluate event against rules
4. **list_alert_rules**: List configured rules
5. **add_alert_rule**: Add new rule
6. **remove_alert_rule**: Remove rule
7. **reset_alert_suppression**: Reset suppression state
8. **get_suppression_status**: Get suppression status

```python
# Access via MCP tools
from ipfs_datasets_py.mcp_server.tools.alert_tools import discord_alert_tools

# Send message
result = await discord_alert_tools.send_discord_message(
    text="Alert message",
    role_names=["trader"]
)

# Evaluate rules
result = await discord_alert_tools.evaluate_alert_rules(
    event={"price": 150, "volume": 1000000},
    rule_ids=["price_spike_alert"]
)
```

## Alert Rules

### Rule Structure

```yaml
rule_id: unique_identifier
name: Human-readable name
description: Rule description
enabled: true/false
severity: info | warning | critical
suppression_window: seconds  # Debounce window

condition:
  # JSON-Logic style predicate
  and:
    - ">": [{"var": "price"}, 100]
    - "<": [{"var": "volume"}, 1000000]

message_template: "Price is {price}"
role_names: [role1, role2]

embed_config:
  title: "Alert Title"
  description: "Alert description"
  fields:
    - name: "Field"
      value: "{variable}"
      inline: true
```

### Supported Operators

**Logical**: and, or, not

**Comparison**: >, <, >=, <=, ==, !=

**Math**: +, -, *, /, abs, max, min

**Collection**: in, any, all

**Statistical**:
- `zscore`: Calculate z-score over rolling window
- `sma`: Simple moving average
- `ema`: Exponential moving average
- `stddev`: Standard deviation
- `percent_change`: Percentage change over N periods

### Rule Examples

#### Price Threshold

```yaml
condition:
  ">": [{"var": "price"}, 100]
```

#### Moving Average Crossover

```yaml
condition:
  ">": [{"var": "price"}, {"sma": ["price", 50]}]
```

#### Volume Anomaly

```yaml
condition:
  ">": [{"zscore": ["volume", 20]}, 2.5]
```

#### Complex Multi-Condition

```yaml
condition:
  and:
    - ">": [{"percent_change": ["price", 1]}, 5]
    - or:
        - ">": [{"zscore": ["volume", 20]}, 2]
        - ">": [{"var": "volatility"}, 0.5]
```

## Examples

### Complete Workflow Example

```python
#!/usr/bin/env python3
"""Complete market monitoring workflow with Discord alerts."""

import asyncio
from datetime import datetime
from ipfs_datasets_py.alerts import (
    DiscordNotifier, AlertManager, AlertRule, RuleEngine
)

async def market_monitoring_workflow():
    # 1. Setup notifier
    notifier = DiscordNotifier(
        mode="webhook",
        webhook_url="https://discord.com/api/webhooks/..."
    )
    
    # 2. Create alert manager
    manager = AlertManager(
        notifier=notifier,
        config_file="config/alert_rules.yml"
    )
    
    # 3. Add custom real-time rule
    realtime_rule = AlertRule(
        rule_id="realtime_spike",
        name="Real-time Price Spike",
        condition={">": [{"percent_change": ["price", 1]}, 3]},
        message_template="⚡ Real-time spike: {symbol} {change_pct:+.2f}%",
        severity="warning",
        suppression_window=60
    )
    manager.add_rule(realtime_rule)
    
    # 4. Simulate market data stream
    async def market_data_stream():
        """Simulate receiving market data."""
        symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]
        
        while True:
            for symbol in symbols:
                yield {
                    "symbol": symbol,
                    "price": 150 + (hash(symbol + str(datetime.now())) % 50),
                    "change_pct": ((hash(symbol) % 20) - 10),
                    "volume": 80000000 + (hash(symbol) % 40000000),
                    "timestamp": datetime.now().isoformat()
                }
            await asyncio.sleep(5)
    
    # 5. Monitor stream
    print("Starting market monitoring...")
    try:
        async for event in market_data_stream():
            results = await manager.evaluate_event(event)
            
            if results:
                for result in results:
                    if result['status'] == 'triggered':
                        print(f"✓ Alert: {result['rule_name']} for {event['symbol']}")
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
    finally:
        await notifier.close()

if __name__ == "__main__":
    asyncio.run(market_monitoring_workflow())
```

### Integration with GraphRAG

```python
from ipfs_datasets_py.alerts import DiscordNotifier, AlertRule, AlertManager

async def graphrag_sentiment_monitor():
    """Monitor GraphRAG analysis outputs for sentiment shifts."""
    
    notifier = DiscordNotifier(mode="webhook", webhook_url="...")
    manager = AlertManager(notifier=notifier)
    
    # Rule for negative sentiment detection
    sentiment_rule = AlertRule(
        rule_id="graphrag_negative_sentiment",
        name="Negative Sentiment Detected",
        condition={
            "and": [
                {"<": [{"var": "graphrag.sentiment_score"}, -0.5]},
                {">": [{"var": "graphrag.confidence"}, 0.7]}
            ]
        },
        message_template="""
        🧠 GraphRAG Alert: Negative sentiment detected
        Symbol: {symbol}
        Sentiment: {graphrag.sentiment_score}
        Confidence: {graphrag.confidence}
        Summary: {graphrag.summary}
        """,
        embed_config={
            "title": "GraphRAG Sentiment Alert",
            "description": "Negative sentiment shift detected in news",
            "color": 0xf39c12,
            "fields": [
                {"name": "Symbol", "value": "{symbol}", "inline": True},
                {"name": "Sentiment", "value": "{graphrag.sentiment_score}", "inline": True},
                {"name": "Summary", "value": "{graphrag.summary}", "inline": False}
            ]
        },
        severity="warning",
        suppression_window=1800  # 30 minutes
    )
    manager.add_rule(sentiment_rule)
    
    # Simulate GraphRAG analysis output
    graphrag_output = {
        "symbol": "AAPL",
        "graphrag": {
            "sentiment_score": -0.75,
            "confidence": 0.85,
            "summary": "Multiple news sources report concerns about supply chain",
            "entities": ["CEO", "Supply Chain", "Manufacturing"]
        }
    }
    
    results = await manager.evaluate_event(graphrag_output)
    await notifier.close()

asyncio.run(graphrag_sentiment_monitor())
```

## Troubleshooting

### Common Issues

#### Webhook Not Working

```python
# Test webhook directly
import aiohttp
import asyncio

async def test_webhook():
    webhook_url = "https://discord.com/api/webhooks/..."
    
    async with aiohttp.ClientSession() as session:
        payload = {"content": "Test message"}
        async with session.post(webhook_url, json=payload) as response:
            print(f"Status: {response.status}")
            print(await response.text())

asyncio.run(test_webhook())
```

#### Bot Not Connecting

1. Check bot token is correct
2. Verify bot has proper permissions in Discord server
3. Enable required intents in Developer Portal
4. Check network connectivity

#### Rules Not Triggering

```python
# Debug rule evaluation
engine = RuleEngine()
rule = {...}  # Your rule
event = {...}  # Your event

try:
    result = engine.evaluate(rule, event)
    print(f"Rule result: {result}")
except Exception as e:
    print(f"Rule error: {e}")
```

#### Import Errors

```bash
# Install missing dependencies
pip install discord.py aiohttp PyYAML

# Verify installation
python -c "import discord; import aiohttp; import yaml; print('OK')"
```

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('ipfs_datasets_py.alerts')
logger.setLevel(logging.DEBUG)
```

## Advanced Topics

### Custom Predicates

```python
from ipfs_datasets_py.alerts import RuleEngine

# Register custom predicate
def bollinger_band(var_path: str, window: int = 20, num_std: int = 2, context=None):
    """Calculate Bollinger Bands."""
    # Your implementation
    pass

engine = RuleEngine()
engine.register_predicate('bollinger', bollinger_band)

# Use in rules
rule = {
    ">": [{"var": "price"}, {"bollinger": ["price", 20, 2]}]
}
```

### Multi-Channel Notifications

```python
# Create multiple notifiers for different channels
notifiers = {
    "alerts": DiscordNotifier(webhook_url="..."),
    "admin": DiscordNotifier(webhook_url="..."),
    "traders": DiscordNotifier(webhook_url="...")
}

# Route alerts based on severity
if result['severity'] == 'critical':
    await notifiers['admin'].send_message(...)
    await notifiers['alerts'].send_message(...)
else:
    await notifiers['alerts'].send_message(...)
```

### Persistence

```python
# Save rules to file
manager.save_rules_to_file("my_custom_rules.yml")

# Load rules from file
manager.load_rules_from_file("my_custom_rules.yml")
```

## Resources

- **Source Code**: `ipfs_datasets_py/alerts/`
- **Tests**: `tests/unit_tests/test_discord_notifier.py`, etc.
- **Examples**: `examples/discord_alerts_demo.py`
- **Config**: `config/discord.yml`, `config/alert_rules.yml`

## Support

For issues or questions:
1. Check this guide and examples
2. Review test files for usage patterns
3. Run demo script: `python examples/discord_alerts_demo.py --dry-run`
4. Open an issue on GitHub
