"""
IPFS Datasets Alert System

This package provides alert and notification functionality for financial signals
and market events, with Discord integration support.
"""

from ipfs_datasets_py.alerts.discord_notifier import (
    DiscordNotifier,
    DiscordEmbed,
    BotClient,
    WebhookClient
)
from ipfs_datasets_py.alerts.rule_engine import (
    RuleEngine,
    RuleEvaluationError
)
from ipfs_datasets_py.alerts.alert_manager import (
    AlertManager,
    AlertRule
)

__all__ = [
    'DiscordNotifier',
    'DiscordEmbed',
    'BotClient',
    'WebhookClient',
    'RuleEngine',
    'RuleEvaluationError',
    'AlertManager',
    'AlertRule',
]

__version__ = '0.1.0'
