"""
Alert Manager for IPFS Datasets Alert System

This module provides the main alert management system that:
- Loads alert rules from configuration
- Evaluates rules against event payloads
- Triggers Discord notifications when rules match
- Manages debouncing and suppression windows
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json

from ipfs_datasets_py.alerts.discord_notifier import DiscordNotifier, DiscordEmbed
from ipfs_datasets_py.alerts.rule_engine import RuleEngine, RuleEvaluationError

logger = logging.getLogger(__name__)


@dataclass
class AlertRule:
    """
    Represents an alert rule.
    
    Attributes:
        rule_id: Unique identifier for the rule
        name: Human-readable rule name
        description: Rule description
        condition: Rule condition (JSON-Logic format)
        severity: Alert severity (info, warning, critical)
        message_template: Template for alert message (supports {variable} substitution)
        role_names: List of Discord roles to mention
        embed_config: Optional embed configuration
        suppression_window: Seconds before re-triggering (0 = no suppression)
        enabled: Whether rule is active
        metadata: Additional metadata
    """
    rule_id: str
    name: str
    condition: Dict[str, Any]
    message_template: str
    description: str = ""
    severity: str = "info"
    role_names: List[str] = field(default_factory=list)
    embed_config: Optional[Dict[str, Any]] = None
    suppression_window: int = 300  # 5 minutes default
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AlertRule:
        """Create AlertRule from dictionary."""
        return cls(
            rule_id=data['rule_id'],
            name=data['name'],
            condition=data['condition'],
            message_template=data['message_template'],
            description=data.get('description', ''),
            severity=data.get('severity', 'info'),
            role_names=data.get('role_names', []),
            embed_config=data.get('embed_config'),
            suppression_window=data.get('suppression_window', 300),
            enabled=data.get('enabled', True),
            metadata=data.get('metadata', {})
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'rule_id': self.rule_id,
            'name': self.name,
            'description': self.description,
            'condition': self.condition,
            'severity': self.severity,
            'message_template': self.message_template,
            'role_names': self.role_names,
            'embed_config': self.embed_config,
            'suppression_window': self.suppression_window,
            'enabled': self.enabled,
            'metadata': self.metadata
        }


class AlertManager:
    """
    Manages alert rules and triggers notifications.
    
    The alert manager:
    1. Loads rules from configuration
    2. Evaluates rules against incoming events
    3. Formats alert messages
    4. Sends notifications via Discord
    5. Manages suppression windows to prevent spam
    """
    
    def __init__(
        self,
        notifier: DiscordNotifier,
        rule_engine: Optional[RuleEngine] = None,
        rules: Optional[List[AlertRule]] = None,
        config_file: Optional[Union[str, Path]] = None
    ):
        """
        Initialize alert manager.
        
        Args:
            notifier: Discord notifier instance
            rule_engine: Rule engine instance (creates new if None)
            rules: List of alert rules (loads from config if None)
            config_file: Path to alert rules config file
        """
        self.notifier = notifier
        self.rule_engine = rule_engine or RuleEngine()
        self.rules: Dict[str, AlertRule] = {}
        self.last_triggered: Dict[str, float] = {}
        
        # Load rules
        if rules:
            for rule in rules:
                self.add_rule(rule)
        elif config_file:
            self.load_rules_from_file(config_file)
    
    def add_rule(self, rule: AlertRule):
        """Add or update an alert rule."""
        self.rules[rule.rule_id] = rule
        logger.info(f"Added alert rule: {rule.name} ({rule.rule_id})")
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove an alert rule."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            logger.info(f"Removed alert rule: {rule_id}")
            return True
        return False
    
    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        """Get an alert rule by ID."""
        return self.rules.get(rule_id)
    
    def list_rules(self, enabled_only: bool = False) -> List[AlertRule]:
        """List all alert rules."""
        rules = list(self.rules.values())
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        return rules
    
    def load_rules_from_file(self, config_file: Union[str, Path]):
        """
        Load alert rules from YAML config file.
        
        Args:
            config_file: Path to YAML file containing rules
        """
        try:
            import yaml
            
            path = Path(config_file)
            if not path.exists():
                logger.warning(f"Config file not found: {config_file}")
                return
            
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
            
            if not config or 'rules' not in config:
                logger.warning(f"No rules found in config: {config_file}")
                return
            
            for rule_data in config['rules']:
                try:
                    rule = AlertRule.from_dict(rule_data)
                    self.add_rule(rule)
                except Exception as e:
                    logger.error(f"Error loading rule: {e}", exc_info=True)
        
        except ImportError:
            logger.error("PyYAML required for loading config files")
        except Exception as e:
            logger.error(f"Error loading rules from file: {e}", exc_info=True)
    
    def save_rules_to_file(self, config_file: Union[str, Path]):
        """
        Save alert rules to YAML config file.
        
        Args:
            config_file: Path to output YAML file
        """
        try:
            import yaml
            
            config = {
                'rules': [rule.to_dict() for rule in self.rules.values()]
            }
            
            path = Path(config_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Saved {len(self.rules)} rules to {config_file}")
        
        except ImportError:
            logger.error("PyYAML required for saving config files")
        except Exception as e:
            logger.error(f"Error saving rules to file: {e}", exc_info=True)
    
    async def evaluate_event(
        self,
        event: Dict[str, Any],
        rule_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Evaluate an event against alert rules.
        
        Args:
            event: Event payload with variables for rule evaluation
            rule_ids: List of specific rule IDs to evaluate (None = all rules)
            
        Returns:
            List of triggered alerts with results
        """
        results = []
        
        # Determine which rules to evaluate
        rules_to_check = []
        if rule_ids:
            rules_to_check = [self.rules[rid] for rid in rule_ids if rid in self.rules]
        else:
            rules_to_check = [r for r in self.rules.values() if r.enabled]
        
        # Evaluate each rule
        for rule in rules_to_check:
            try:
                result = await self._evaluate_rule(rule, event)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(
                    f"Error evaluating rule {rule.rule_id}: {e}",
                    exc_info=True
                )
        
        return results
    
    async def _evaluate_rule(
        self,
        rule: AlertRule,
        event: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Evaluate a single rule against an event."""
        # Check if rule is suppressed
        if self._is_suppressed(rule.rule_id, rule.suppression_window):
            logger.debug(f"Rule {rule.rule_id} is suppressed")
            return None
        
        # Evaluate condition
        try:
            matched = self.rule_engine.evaluate(rule.condition, event)
        except RuleEvaluationError as e:
            logger.error(f"Rule evaluation error for {rule.rule_id}: {e}")
            return {
                'rule_id': rule.rule_id,
                'status': 'error',
                'error': str(e)
            }
        
        if not matched:
            return None
        
        # Rule matched - trigger alert
        logger.info(f"Rule matched: {rule.name} ({rule.rule_id})")
        
        # Update suppression
        self.last_triggered[rule.rule_id] = time.time()
        
        # Format message
        message = self._format_message(rule.message_template, event)
        
        # Create embed if configured
        embed = None
        if rule.embed_config:
            embed = self._create_embed(rule, event)
        
        # Send notification
        try:
            send_result = await self.notifier.send_message(
                text=message,
                role_names=rule.role_names if rule.role_names else None,
                embed=embed
            )
            
            return {
                'rule_id': rule.rule_id,
                'rule_name': rule.name,
                'severity': rule.severity,
                'status': 'triggered',
                'message': message,
                'notification_result': send_result,
                'timestamp': datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error sending notification: {e}", exc_info=True)
            return {
                'rule_id': rule.rule_id,
                'status': 'error',
                'error': f"Failed to send notification: {e}"
            }
    
    def _is_suppressed(self, rule_id: str, suppression_window: int) -> bool:
        """Check if a rule is currently suppressed."""
        if suppression_window <= 0:
            return False
        
        if rule_id not in self.last_triggered:
            return False
        
        elapsed = time.time() - self.last_triggered[rule_id]
        return elapsed < suppression_window
    
    def _format_message(self, template: str, context: Dict[str, Any]) -> str:
        """
        Format message template with context variables.
        
        Supports {variable} and {nested.variable} syntax.
        """
        try:
            # Simple string formatting
            message = template
            
            # Replace variables
            for key, value in context.items():
                placeholder = f"{{{key}}}"
                if placeholder in message:
                    message = message.replace(placeholder, str(value))
            
            # Handle nested variables (e.g., {data.price})
            import re
            pattern = r'\{([^}]+)\}'
            
            def replace_nested(match):
                path = match.group(1)
                parts = path.split('.')
                value = context
                
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                        if value is None:
                            return match.group(0)  # Keep original
                    else:
                        return match.group(0)
                
                return str(value)
            
            message = re.sub(pattern, replace_nested, message)
            
            return message
        
        except Exception as e:
            logger.error(f"Error formatting message: {e}")
            return template
    
    def _create_embed(
        self,
        rule: AlertRule,
        context: Dict[str, Any]
    ) -> Optional[DiscordEmbed]:
        """Create Discord embed from rule configuration."""
        if not rule.embed_config:
            return None
        
        try:
            config = rule.embed_config
            
            # Format fields
            fields = []
            if 'fields' in config:
                for field_config in config['fields']:
                    fields.append({
                        'name': self._format_message(field_config['name'], context),
                        'value': self._format_message(field_config['value'], context),
                        'inline': field_config.get('inline', False)
                    })
            
            # Determine color based on severity
            color_map = {
                'info': 0x3498db,      # Blue
                'warning': 0xf39c12,   # Orange
                'critical': 0xe74c3c   # Red
            }
            color = config.get('color', color_map.get(rule.severity, 0x3498db))
            
            embed = DiscordEmbed(
                title=self._format_message(config.get('title', rule.name), context),
                description=self._format_message(
                    config.get('description', ''),
                    context
                ) if config.get('description') else None,
                color=color,
                fields=fields,
                footer=self._format_message(
                    config.get('footer', ''),
                    context
                ) if config.get('footer') else None,
                url=config.get('url')
            )
            
            return embed
        
        except Exception as e:
            logger.error(f"Error creating embed: {e}", exc_info=True)
            return None
    
    def reset_suppression(self, rule_id: Optional[str] = None):
        """
        Reset suppression state.
        
        Args:
            rule_id: If provided, reset only this rule. If None, reset all.
        """
        if rule_id:
            if rule_id in self.last_triggered:
                del self.last_triggered[rule_id]
        else:
            self.last_triggered.clear()
    
    def get_suppression_status(self) -> Dict[str, Dict[str, Any]]:
        """Get suppression status for all rules."""
        status = {}
        current_time = time.time()
        
        for rule_id, rule in self.rules.items():
            if rule_id in self.last_triggered:
                last_time = self.last_triggered[rule_id]
                elapsed = current_time - last_time
                remaining = max(0, rule.suppression_window - elapsed)
                
                status[rule_id] = {
                    'suppressed': remaining > 0,
                    'last_triggered': datetime.fromtimestamp(last_time).isoformat(),
                    'elapsed_seconds': elapsed,
                    'remaining_seconds': remaining
                }
            else:
                status[rule_id] = {
                    'suppressed': False,
                    'last_triggered': None,
                    'elapsed_seconds': None,
                    'remaining_seconds': None
                }
        
        return status
