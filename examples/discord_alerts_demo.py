#!/usr/bin/env python3
"""
Discord Alerts System Demo

This script demonstrates how to use the Discord alert system for financial market monitoring.

Features demonstrated:
1. Setting up Discord notifier (webhook and bot modes)
2. Creating custom alert rules
3. Evaluating market events against rules
4. Sending rich embeds and role mentions
5. Using statistical predicates (zscore, sma, ema)

Usage:
    # Using webhook (simplest)
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python discord_alerts_demo.py --mode webhook

    # Using bot (full features)
    export DISCORD_BOT_TOKEN="your_bot_token"
    export DISCORD_GUILD_ID="your_guild_id"
    export DISCORD_CHANNEL_ID="your_channel_id"
    python discord_alerts_demo.py --mode bot

    # Dry run (no actual Discord messages)
    python discord_alerts_demo.py --dry-run
"""

import anyio
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
import random

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parents[1]))

from ipfs_datasets_py.optimizers.optimizer_alert_system import (
    DiscordNotifier,
    DiscordEmbed,
    AlertManager,
    AlertRule,
    RuleEngine
)


async def demo_basic_message(notifier: DiscordNotifier, dry_run: bool = False):
    """Demonstrate sending a basic text message."""
    print("\n=== Demo 1: Basic Text Message ===")
    
    if dry_run:
        print("DRY RUN: Would send: 'Hello from IPFS Datasets Alert System!'")
        return
    
    result = await notifier.send_message(
        text="🚀 Hello from IPFS Datasets Alert System!"
    )
    
    print(f"Result: {result}")


async def demo_rich_embed(notifier: DiscordNotifier, dry_run: bool = False):
    """Demonstrate sending a rich embed message."""
    print("\n=== Demo 2: Rich Embed Message ===")
    
    embed = DiscordEmbed(
        title="📊 Market Alert",
        description="Example of a rich embed with multiple fields",
        color=0x00ff00,  # Green
        fields=[
            {"name": "Symbol", "value": "AAPL", "inline": True},
            {"name": "Price", "value": "$175.50", "inline": True},
            {"name": "Change", "value": "+2.5%", "inline": True},
            {"name": "Volume", "value": "85M", "inline": True},
            {"name": "Signal", "value": "🟢 BULLISH", "inline": False},
        ],
        footer=f"Alert System | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    if dry_run:
        print(f"DRY RUN: Would send embed:")
        print(f"  Title: {embed.title}")
        print(f"  Description: {embed.description}")
        print(f"  Fields: {len(embed.fields)} fields")
        return
    
    result = await notifier.send_message(embed=embed)
    
    print(f"Result: {result}")


async def demo_rule_evaluation(notifier: DiscordNotifier, dry_run: bool = False):
    """Demonstrate rule-based alert evaluation."""
    print("\n=== Demo 3: Rule-Based Alert Evaluation ===")
    
    # Create rule engine with custom predicates
    engine = RuleEngine()
    
    # Create alert manager
    manager = AlertManager(notifier=notifier, rule_engine=engine)
    
    # Add custom rules
    rules = [
        AlertRule(
            rule_id="price_spike",
            name="Price Spike Alert",
            description="Triggers when price increases significantly",
            condition={
                "and": [
                    {">": [{"var": "price"}, 100]},
                    {">": [{"var": "change_pct"}, 5]}
                ]
            },
            message_template="🚨 Price Spike: {symbol} is at ${price} (+{change_pct}%)",
            severity="warning",
            role_names=["trader"],
            suppression_window=60
        ),
        AlertRule(
            rule_id="volume_anomaly",
            name="Volume Anomaly",
            description="Detects unusual trading volume",
            condition={
                ">": [{"var": "volume"}, 100000000]
            },
            message_template="📊 Volume Alert: {symbol} volume is {volume}",
            severity="info",
            suppression_window=300
        ),
        AlertRule(
            rule_id="critical_drop",
            name="Critical Price Drop",
            description="Emergency alert for major price drops",
            condition={
                "<": [{"var": "change_pct"}, -10]
            },
            message_template="🔴 CRITICAL: {symbol} dropped {change_pct}%!",
            severity="critical",
            role_names=["admin", "trader"],
            embed_config={
                "title": "⚠️ CRITICAL ALERT",
                "description": "Major price drop detected",
                "fields": [
                    {"name": "Symbol", "value": "{symbol}", "inline": True},
                    {"name": "Price", "value": "${price}", "inline": True},
                    {"name": "Change", "value": "{change_pct}%", "inline": True}
                ]
            },
            suppression_window=30
        )
    ]
    
    for rule in rules:
        manager.add_rule(rule)
    
    print(f"Added {len(rules)} alert rules")
    
    # Simulate market events
    events = [
        {
            "symbol": "AAPL",
            "price": 175.50,
            "change_pct": 7.2,
            "volume": 85000000,
            "timestamp": datetime.now().isoformat()
        },
        {
            "symbol": "TSLA",
            "price": 185.20,
            "change_pct": -12.5,
            "volume": 120000000,
            "timestamp": datetime.now().isoformat()
        },
        {
            "symbol": "GOOGL",
            "price": 142.30,
            "change_pct": 1.8,
            "volume": 150000000,
            "timestamp": datetime.now().isoformat()
        }
    ]
    
    print("\nEvaluating market events...")
    for event in events:
        print(f"\nEvent: {event['symbol']} @ ${event['price']} ({event['change_pct']:+.1f}%)")
        
        if dry_run:
            # In dry run, just show what would match
            for rule in manager.list_rules(enabled_only=True):
                try:
                    matched = engine.evaluate(rule.condition, event)
                    if matched:
                        print(f"  ✓ Would trigger: {rule.name}")
                except Exception as e:
                    print(f"  ✗ Error evaluating {rule.name}: {e}")
        else:
            results = await manager.evaluate_event(event)
            
            if results:
                print(f"  Triggered {len(results)} alerts:")
                for result in results:
                    if result['status'] == 'triggered':
                        print(f"    ✓ {result['rule_name']}")
                    else:
                        print(f"    ✗ {result.get('error', 'Unknown error')}")
            else:
                print("  No alerts triggered")


async def demo_statistical_predicates(notifier: DiscordNotifier, dry_run: bool = False):
    """Demonstrate statistical predicates for time-series analysis."""
    print("\n=== Demo 4: Statistical Predicates (SMA, EMA, Z-Score) ===")
    
    engine = RuleEngine()
    manager = AlertManager(notifier=notifier, rule_engine=engine)
    
    # Rule using simple moving average
    sma_rule = AlertRule(
        rule_id="sma_crossover",
        name="SMA Crossover",
        description="Detects when price crosses above its moving average",
        condition={
            ">": [
                {"var": "price"},
                {"sma": ["price", 5]}
            ]
        },
        message_template="📈 {symbol}: Price ${price} crossed above 5-period SMA",
        severity="info"
    )
    manager.add_rule(sma_rule)
    
    # Simulate price data stream
    print("\nSimulating price stream for AAPL...")
    prices = [150, 152, 148, 147, 149, 153, 157]  # Last price crosses above average
    
    for i, price in enumerate(prices):
        event = {
            "symbol": "AAPL",
            "price": price,
            "timestamp": datetime.now().isoformat()
        }
        
        print(f"  t={i}: ${price}")
        
        if dry_run:
            # In dry run, just evaluate rule
            try:
                matched = engine.evaluate(sma_rule.condition, event)
                if matched:
                    print(f"    ✓ Would trigger SMA crossover alert")
            except Exception:
                pass
        else:
            results = await manager.evaluate_event(event, rule_ids=["sma_crossover"])
            if results and results[0]['status'] == 'triggered':
                print(f"    ✓ Alert triggered!")


async def demo_suppression(notifier: DiscordNotifier, dry_run: bool = False):
    """Demonstrate alert suppression to prevent spam."""
    print("\n=== Demo 5: Alert Suppression ===")
    
    manager = AlertManager(notifier=notifier)
    
    # Rule with short suppression window for demo
    rule = AlertRule(
        rule_id="frequent_alert",
        name="Frequent Alert",
        condition={">": [{"var": "value"}, 100]},
        message_template="Value is {value}",
        suppression_window=5  # 5 seconds
    )
    manager.add_rule(rule)
    
    event = {"value": 150}
    
    print("Attempting to trigger alert 3 times rapidly...")
    
    for i in range(3):
        print(f"\nAttempt {i+1}:")
        
        if dry_run:
            status = manager.get_suppression_status()
            suppressed = status.get(rule.rule_id, {}).get('suppressed', False)
            if suppressed:
                print("  DRY RUN: Alert would be suppressed")
            else:
                print("  DRY RUN: Alert would be triggered")
                manager.last_triggered[rule.rule_id] = asyncio.get_event_loop().time()
        else:
            results = await manager.evaluate_event(event)
            
            if results:
                print(f"  ✓ Alert triggered")
            else:
                print(f"  ⊗ Alert suppressed (within suppression window)")
        
        if i < 2:
            await anyio.sleep(1)
    
    print("\nSuppression status:")
    status = manager.get_suppression_status()
    for rule_id, info in status.items():
        if info['suppressed']:
            print(f"  {rule_id}: Suppressed ({info['remaining_seconds']:.1f}s remaining)")
        else:
            print(f"  {rule_id}: Not suppressed")


async def main():
    """Main demo function."""
    parser = argparse.ArgumentParser(description="Discord Alerts System Demo")
    parser.add_argument(
        "--mode",
        choices=["webhook", "bot"],
        default="webhook",
        help="Discord integration mode"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without actually sending Discord messages"
    )
    parser.add_argument(
        "--demo",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="Run specific demo only (1-5)"
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Discord Alerts System Demo".center(70))
    print("=" * 70)
    
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No Discord messages will be sent")
    
    # Initialize notifier
    print(f"\nInitializing Discord notifier in '{args.mode}' mode...")
    
    try:
        if args.mode == "webhook":
            webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
            if not webhook_url and not args.dry_run:
                print("\n❌ Error: DISCORD_WEBHOOK_URL environment variable not set")
                print("Set it with: export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'")
                return
            
            notifier = DiscordNotifier(
                mode="webhook",
                webhook_url=webhook_url or "https://discord.com/api/webhooks/dummy/url"
            )
        else:
            bot_token = os.environ.get("DISCORD_BOT_TOKEN")
            guild_id = os.environ.get("DISCORD_GUILD_ID")
            channel_id = os.environ.get("DISCORD_CHANNEL_ID")
            
            if not all([bot_token, guild_id, channel_id]) and not args.dry_run:
                print("\n❌ Error: Missing bot configuration")
                print("Required environment variables:")
                print("  - DISCORD_BOT_TOKEN")
                print("  - DISCORD_GUILD_ID")
                print("  - DISCORD_CHANNEL_ID")
                return
            
            notifier = DiscordNotifier(
                mode="bot",
                bot_token=bot_token or "dummy_token",
                guild_id=guild_id or "dummy_guild",
                channel_id=channel_id or "dummy_channel"
            )
        
        print("✓ Notifier initialized successfully")
        
        # Run demos
        demos = {
            1: ("Basic Message", demo_basic_message),
            2: ("Rich Embed", demo_rich_embed),
            3: ("Rule Evaluation", demo_rule_evaluation),
            4: ("Statistical Predicates", demo_statistical_predicates),
            5: ("Suppression", demo_suppression),
        }
        
        if args.demo:
            # Run specific demo
            name, func = demos[args.demo]
            await func(notifier, args.dry_run)
        else:
            # Run all demos
            for name, func in demos.values():
                try:
                    await func(notifier, args.dry_run)
                except Exception as e:
                    print(f"\n❌ Error in {name}: {e}")
                    import traceback
                    traceback.print_exc()
        
        # Cleanup
        await notifier.close()
        
        print("\n" + "=" * 70)
        print("Demo complete!".center(70))
        print("=" * 70)
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)
