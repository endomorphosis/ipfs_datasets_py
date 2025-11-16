"""
Discord Alert Tools for MCP Server

This module provides MCP-compatible tools for sending Discord notifications
and managing alert rules.

Available tools:
- send_discord_message: Send a message to Discord
- send_discord_embed: Send a rich embed to Discord
- evaluate_alert_rules: Evaluate event against alert rules
- list_alert_rules: List configured alert rules
- add_alert_rule: Add a new alert rule
- remove_alert_rule: Remove an alert rule
- reset_alert_suppression: Reset rule suppression state
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Import alert system components
try:
    from ipfs_datasets_py.alerts import (
        DiscordNotifier,
        DiscordEmbed,
        AlertManager,
        AlertRule,
        RuleEngine
    )
    ALERTS_AVAILABLE = True
except ImportError:
    logger.warning("Alert system not available")
    ALERTS_AVAILABLE = False


# Global instances (lazy initialization)
_notifier: Optional[DiscordNotifier] = None
_alert_manager: Optional[AlertManager] = None


def _get_notifier(config_file: Optional[str] = None) -> DiscordNotifier:
    """Get or create Discord notifier instance."""
    global _notifier
    
    if not ALERTS_AVAILABLE:
        raise ImportError("Alert system not available. Install discord.py and aiohttp.")
    
    if _notifier is None:
        if config_file:
            _notifier = DiscordNotifier(config_file=Path(config_file))
        else:
            # Use default config location
            default_config = Path(__file__).parents[4] / "config" / "discord.yml"
            if default_config.exists():
                _notifier = DiscordNotifier(config_file=default_config)
            else:
                # Initialize from environment variables
                _notifier = DiscordNotifier()
    
    return _notifier


def _get_alert_manager(
    config_file: Optional[str] = None,
    notifier: Optional[DiscordNotifier] = None
) -> AlertManager:
    """Get or create alert manager instance."""
    global _alert_manager
    
    if not ALERTS_AVAILABLE:
        raise ImportError("Alert system not available")
    
    if _alert_manager is None:
        if notifier is None:
            notifier = _get_notifier()
        
        # Load rules from config
        if config_file:
            rules_config = Path(config_file)
        else:
            rules_config = Path(__file__).parents[4] / "config" / "alert_rules.yml"
        
        _alert_manager = AlertManager(
            notifier=notifier,
            config_file=rules_config if rules_config.exists() else None
        )
    
    return _alert_manager


async def send_discord_message(
    text: str,
    role_names: Optional[List[str]] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send a plain text message to Discord.
    
    Args:
        text: Message text to send
        role_names: List of role names to mention (optional)
        channel_id: Channel ID to send to (optional, uses default)
        thread_id: Thread ID to send to (optional)
        config_file: Path to discord.yml config file (optional)
        
    Returns:
        Dictionary with status and message info
        
    Example:
        result = await send_discord_message(
            text="Market alert: Price spike detected!",
            role_names=["trader", "alerts"]
        )
    """
    try:
        notifier = _get_notifier(config_file)
        
        result = await notifier.send_message(
            text=text,
            role_names=role_names,
            channel_id=channel_id,
            thread_id=thread_id
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error sending Discord message: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


async def send_discord_embed(
    title: str,
    description: Optional[str] = None,
    fields: Optional[List[Dict[str, Any]]] = None,
    color: Optional[int] = None,
    footer: Optional[str] = None,
    role_names: Optional[List[str]] = None,
    channel_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send a rich embed message to Discord.
    
    Args:
        title: Embed title
        description: Embed description (optional)
        fields: List of field dicts with 'name', 'value', 'inline' keys (optional)
        color: Embed color as hex int (optional, default blue)
        footer: Footer text (optional)
        role_names: List of role names to mention (optional)
        channel_id: Channel ID to send to (optional)
        thread_id: Thread ID to send to (optional)
        config_file: Path to discord.yml config file (optional)
        
    Returns:
        Dictionary with status and message info
        
    Example:
        result = await send_discord_embed(
            title="Price Alert",
            description="AAPL price spike detected",
            fields=[
                {"name": "Price", "value": "$175.50", "inline": True},
                {"name": "Change", "value": "+5.2%", "inline": True}
            ],
            color=0x00ff00,
            role_names=["trader"]
        )
    """
    try:
        notifier = _get_notifier(config_file)
        
        if not ALERTS_AVAILABLE:
            return {
                'status': 'error',
                'error': 'Alert system not available'
            }
        
        embed = DiscordEmbed(
            title=title,
            description=description,
            color=color or 0x3498db,
            fields=fields or [],
            footer=footer
        )
        
        result = await notifier.send_message(
            embed=embed,
            role_names=role_names,
            channel_id=channel_id,
            thread_id=thread_id
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error sending Discord embed: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


async def evaluate_alert_rules(
    event: Dict[str, Any],
    rule_ids: Optional[List[str]] = None,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluate an event against configured alert rules.
    
    Args:
        event: Event data with variables for rule evaluation
        rule_ids: List of specific rule IDs to evaluate (optional, default all)
        config_file: Path to alert_rules.yml config file (optional)
        
    Returns:
        Dictionary with evaluation results
        
    Example:
        event = {
            "symbol": "AAPL",
            "price": 175.50,
            "volume": 85000000,
            "timestamp": "2024-01-15T10:30:00Z"
        }
        results = await evaluate_alert_rules(event)
    """
    try:
        manager = _get_alert_manager(config_file)
        
        triggered = await manager.evaluate_event(event, rule_ids)
        
        return {
            'status': 'success',
            'triggered_rules': len(triggered),
            'results': triggered
        }
    
    except Exception as e:
        logger.error(f"Error evaluating alert rules: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def list_alert_rules(
    enabled_only: bool = False,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    List configured alert rules.
    
    Args:
        enabled_only: If True, only return enabled rules (optional)
        config_file: Path to alert_rules.yml config file (optional)
        
    Returns:
        Dictionary with list of rules
        
    Example:
        result = list_alert_rules(enabled_only=True)
        for rule in result['rules']:
            print(f"{rule['name']}: {rule['description']}")
    """
    try:
        manager = _get_alert_manager(config_file)
        
        rules = manager.list_rules(enabled_only=enabled_only)
        
        return {
            'status': 'success',
            'count': len(rules),
            'rules': [rule.to_dict() for rule in rules]
        }
    
    except Exception as e:
        logger.error(f"Error listing alert rules: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def add_alert_rule(
    rule_data: Dict[str, Any],
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a new alert rule.
    
    Args:
        rule_data: Rule configuration dictionary
        config_file: Path to alert_rules.yml config file (optional)
        
    Returns:
        Dictionary with result status
        
    Example:
        rule = {
            "rule_id": "my_alert",
            "name": "My Custom Alert",
            "condition": {">": [{"var": "price"}, 100]},
            "message_template": "Price is {price}",
            "severity": "info",
            "enabled": True
        }
        result = add_alert_rule(rule)
    """
    try:
        if not ALERTS_AVAILABLE:
            return {
                'status': 'error',
                'error': 'Alert system not available'
            }
        
        manager = _get_alert_manager(config_file)
        
        rule = AlertRule.from_dict(rule_data)
        manager.add_rule(rule)
        
        return {
            'status': 'success',
            'message': f'Added rule: {rule.name}',
            'rule_id': rule.rule_id
        }
    
    except Exception as e:
        logger.error(f"Error adding alert rule: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def remove_alert_rule(
    rule_id: str,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Remove an alert rule.
    
    Args:
        rule_id: ID of the rule to remove
        config_file: Path to alert_rules.yml config file (optional)
        
    Returns:
        Dictionary with result status
        
    Example:
        result = remove_alert_rule("my_alert")
    """
    try:
        manager = _get_alert_manager(config_file)
        
        success = manager.remove_rule(rule_id)
        
        if success:
            return {
                'status': 'success',
                'message': f'Removed rule: {rule_id}'
            }
        else:
            return {
                'status': 'error',
                'error': f'Rule not found: {rule_id}'
            }
    
    except Exception as e:
        logger.error(f"Error removing alert rule: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def reset_alert_suppression(
    rule_id: Optional[str] = None,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Reset alert suppression state.
    
    Args:
        rule_id: ID of specific rule to reset (optional, None = all rules)
        config_file: Path to alert_rules.yml config file (optional)
        
    Returns:
        Dictionary with result status
        
    Example:
        # Reset specific rule
        result = reset_alert_suppression("price_spike_alert")
        
        # Reset all rules
        result = reset_alert_suppression()
    """
    try:
        manager = _get_alert_manager(config_file)
        
        manager.reset_suppression(rule_id)
        
        if rule_id:
            message = f'Reset suppression for rule: {rule_id}'
        else:
            message = 'Reset suppression for all rules'
        
        return {
            'status': 'success',
            'message': message
        }
    
    except Exception as e:
        logger.error(f"Error resetting suppression: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def get_suppression_status(
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get suppression status for all rules.
    
    Args:
        config_file: Path to alert_rules.yml config file (optional)
        
    Returns:
        Dictionary with suppression status for each rule
        
    Example:
        result = get_suppression_status()
        for rule_id, status in result['rules'].items():
            if status['suppressed']:
                print(f"{rule_id} suppressed for {status['remaining_seconds']}s")
    """
    try:
        manager = _get_alert_manager(config_file)
        
        status = manager.get_suppression_status()
        
        return {
            'status': 'success',
            'rules': status
        }
    
    except Exception as e:
        logger.error(f"Error getting suppression status: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


# Tool metadata for MCP registration
TOOLS = [
    {
        'name': 'send_discord_message',
        'description': 'Send a plain text message to Discord',
        'function': send_discord_message,
        'parameters': {
            'text': 'Message text',
            'role_names': 'List of role names to mention (optional)',
            'channel_id': 'Channel ID (optional)',
            'thread_id': 'Thread ID (optional)',
            'config_file': 'Path to discord.yml (optional)'
        }
    },
    {
        'name': 'send_discord_embed',
        'description': 'Send a rich embed message to Discord',
        'function': send_discord_embed,
        'parameters': {
            'title': 'Embed title',
            'description': 'Embed description (optional)',
            'fields': 'List of field dicts (optional)',
            'color': 'Embed color hex int (optional)',
            'footer': 'Footer text (optional)',
            'role_names': 'List of role names to mention (optional)',
            'channel_id': 'Channel ID (optional)',
            'thread_id': 'Thread ID (optional)',
            'config_file': 'Path to discord.yml (optional)'
        }
    },
    {
        'name': 'evaluate_alert_rules',
        'description': 'Evaluate an event against configured alert rules',
        'function': evaluate_alert_rules,
        'parameters': {
            'event': 'Event data dict with variables',
            'rule_ids': 'List of specific rule IDs (optional)',
            'config_file': 'Path to alert_rules.yml (optional)'
        }
    },
    {
        'name': 'list_alert_rules',
        'description': 'List configured alert rules',
        'function': list_alert_rules,
        'parameters': {
            'enabled_only': 'Only return enabled rules (optional)',
            'config_file': 'Path to alert_rules.yml (optional)'
        }
    },
    {
        'name': 'add_alert_rule',
        'description': 'Add a new alert rule',
        'function': add_alert_rule,
        'parameters': {
            'rule_data': 'Rule configuration dict',
            'config_file': 'Path to alert_rules.yml (optional)'
        }
    },
    {
        'name': 'remove_alert_rule',
        'description': 'Remove an alert rule',
        'function': remove_alert_rule,
        'parameters': {
            'rule_id': 'ID of rule to remove',
            'config_file': 'Path to alert_rules.yml (optional)'
        }
    },
    {
        'name': 'reset_alert_suppression',
        'description': 'Reset alert suppression state',
        'function': reset_alert_suppression,
        'parameters': {
            'rule_id': 'ID of specific rule (optional, None = all)',
            'config_file': 'Path to alert_rules.yml (optional)'
        }
    },
    {
        'name': 'get_suppression_status',
        'description': 'Get suppression status for all rules',
        'function': get_suppression_status,
        'parameters': {
            'config_file': 'Path to alert_rules.yml (optional)'
        }
    }
]
