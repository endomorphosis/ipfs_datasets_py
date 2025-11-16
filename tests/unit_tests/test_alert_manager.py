"""
Unit tests for Alert Manager

Tests the AlertManager and AlertRule classes.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile
import time

from ipfs_datasets_py.alerts.alert_manager import AlertManager, AlertRule
from ipfs_datasets_py.alerts.discord_notifier import DiscordNotifier, DiscordEmbed
from ipfs_datasets_py.alerts.rule_engine import RuleEngine


class TestAlertRule:
    """Test AlertRule data class."""
    
    def test_alert_rule_initialization(self):
        """
        GIVEN rule parameters
        WHEN AlertRule is initialized
        THEN expect all fields to be set correctly
        """
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}",
            severity="warning"
        )
        
        assert rule.rule_id == "test_rule"
        assert rule.name == "Test Rule"
        assert rule.severity == "warning"
        assert rule.enabled is True
        assert rule.suppression_window == 300
    
    def test_alert_rule_from_dict(self):
        """
        GIVEN a rule dictionary
        WHEN AlertRule.from_dict is called
        THEN expect AlertRule instance to be created
        """
        rule_data = {
            'rule_id': 'test_rule',
            'name': 'Test Rule',
            'condition': {'>': [{'var': 'price'}, 100]},
            'message_template': 'Price is {price}',
            'severity': 'critical',
            'enabled': False
        }
        
        rule = AlertRule.from_dict(rule_data)
        
        assert rule.rule_id == 'test_rule'
        assert rule.name == 'Test Rule'
        assert rule.severity == 'critical'
        assert rule.enabled is False
    
    def test_alert_rule_to_dict(self):
        """
        GIVEN an AlertRule instance
        WHEN to_dict is called
        THEN expect correct dictionary representation
        """
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}"
        )
        
        result = rule.to_dict()
        
        assert result['rule_id'] == "test_rule"
        assert result['name'] == "Test Rule"
        assert 'condition' in result
        assert 'message_template' in result


class TestAlertManagerInitialization:
    """Test AlertManager initialization."""
    
    def test_init_with_notifier(self):
        """
        GIVEN a Discord notifier
        WHEN AlertManager is initialized
        THEN expect notifier to be set and empty rules dict
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        assert manager.notifier == mock_notifier
        assert len(manager.rules) == 0
        assert manager.rule_engine is not None
    
    def test_init_with_custom_rule_engine(self):
        """
        GIVEN a custom rule engine
        WHEN AlertManager is initialized
        THEN expect custom engine to be used
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        custom_engine = RuleEngine()
        
        manager = AlertManager(
            notifier=mock_notifier,
            rule_engine=custom_engine
        )
        
        assert manager.rule_engine == custom_engine
    
    def test_init_with_rules_list(self):
        """
        GIVEN a list of AlertRule objects
        WHEN AlertManager is initialized
        THEN expect rules to be added
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        rules = [
            AlertRule(
                rule_id="rule1",
                name="Rule 1",
                condition={'>': [1, 0]},
                message_template="Test"
            ),
            AlertRule(
                rule_id="rule2",
                name="Rule 2",
                condition={'<': [1, 2]},
                message_template="Test2"
            )
        ]
        
        manager = AlertManager(notifier=mock_notifier, rules=rules)
        
        assert len(manager.rules) == 2
        assert "rule1" in manager.rules
        assert "rule2" in manager.rules


class TestAlertManagerRuleManagement:
    """Test rule management methods."""
    
    def test_add_rule(self):
        """
        GIVEN an AlertRule
        WHEN add_rule is called
        THEN expect rule to be added to rules dict
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [1, 0]},
            message_template="Test"
        )
        
        manager.add_rule(rule)
        
        assert "test_rule" in manager.rules
        assert manager.rules["test_rule"] == rule
    
    def test_remove_rule_success(self):
        """
        GIVEN a manager with a rule
        WHEN remove_rule is called with existing rule_id
        THEN expect rule to be removed and True returned
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [1, 0]},
            message_template="Test"
        )
        manager.add_rule(rule)
        
        result = manager.remove_rule("test_rule")
        
        assert result is True
        assert "test_rule" not in manager.rules
    
    def test_remove_rule_not_found(self):
        """
        GIVEN a manager without a specific rule
        WHEN remove_rule is called with non-existent rule_id
        THEN expect False to be returned
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        result = manager.remove_rule("nonexistent")
        
        assert result is False
    
    def test_get_rule(self):
        """
        GIVEN a manager with a rule
        WHEN get_rule is called
        THEN expect correct rule to be returned
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [1, 0]},
            message_template="Test"
        )
        manager.add_rule(rule)
        
        result = manager.get_rule("test_rule")
        
        assert result == rule
    
    def test_list_rules_all(self):
        """
        GIVEN a manager with multiple rules
        WHEN list_rules is called
        THEN expect all rules to be returned
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule1 = AlertRule(
            rule_id="rule1",
            name="Rule 1",
            condition={'>': [1, 0]},
            message_template="Test",
            enabled=True
        )
        rule2 = AlertRule(
            rule_id="rule2",
            name="Rule 2",
            condition={'<': [1, 2]},
            message_template="Test2",
            enabled=False
        )
        
        manager.add_rule(rule1)
        manager.add_rule(rule2)
        
        rules = manager.list_rules()
        
        assert len(rules) == 2
    
    def test_list_rules_enabled_only(self):
        """
        GIVEN a manager with enabled and disabled rules
        WHEN list_rules is called with enabled_only=True
        THEN expect only enabled rules to be returned
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule1 = AlertRule(
            rule_id="rule1",
            name="Rule 1",
            condition={'>': [1, 0]},
            message_template="Test",
            enabled=True
        )
        rule2 = AlertRule(
            rule_id="rule2",
            name="Rule 2",
            condition={'<': [1, 2]},
            message_template="Test2",
            enabled=False
        )
        
        manager.add_rule(rule1)
        manager.add_rule(rule2)
        
        rules = manager.list_rules(enabled_only=True)
        
        assert len(rules) == 1
        assert rules[0].rule_id == "rule1"


@pytest.mark.asyncio
class TestAlertManagerEvaluation:
    """Test alert evaluation and triggering."""
    
    async def test_evaluate_event_no_match(self):
        """
        GIVEN a rule that doesn't match the event
        WHEN evaluate_event is called
        THEN expect empty results list
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}"
        )
        manager.add_rule(rule)
        
        event = {'price': 50}
        results = await manager.evaluate_event(event)
        
        assert len(results) == 0
    
    async def test_evaluate_event_match(self):
        """
        GIVEN a rule that matches the event
        WHEN evaluate_event is called
        THEN expect rule to trigger and notification to be sent
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        mock_notifier.send_message = AsyncMock(return_value={'status': 'success'})
        
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}"
        )
        manager.add_rule(rule)
        
        event = {'price': 150}
        results = await manager.evaluate_event(event)
        
        assert len(results) == 1
        assert results[0]['status'] == 'triggered'
        assert results[0]['rule_id'] == 'test_rule'
        mock_notifier.send_message.assert_called_once()
    
    async def test_evaluate_specific_rules(self):
        """
        GIVEN multiple rules and specific rule_ids
        WHEN evaluate_event is called with rule_ids
        THEN expect only specified rules to be evaluated
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        mock_notifier.send_message = AsyncMock(return_value={'status': 'success'})
        
        manager = AlertManager(notifier=mock_notifier)
        
        rule1 = AlertRule(
            rule_id="rule1",
            name="Rule 1",
            condition={'>': [{'var': 'value'}, 50]},
            message_template="Value is {value}"
        )
        rule2 = AlertRule(
            rule_id="rule2",
            name="Rule 2",
            condition={'<': [{'var': 'value'}, 100]},
            message_template="Value is {value}"
        )
        
        manager.add_rule(rule1)
        manager.add_rule(rule2)
        
        event = {'value': 75}
        results = await manager.evaluate_event(event, rule_ids=['rule1'])
        
        # Only rule1 should be evaluated
        assert len(results) == 1
        assert results[0]['rule_id'] == 'rule1'
    
    async def test_disabled_rule_not_evaluated(self):
        """
        GIVEN a disabled rule
        WHEN evaluate_event is called
        THEN expect rule not to be evaluated
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}",
            enabled=False
        )
        manager.add_rule(rule)
        
        event = {'price': 150}
        results = await manager.evaluate_event(event)
        
        assert len(results) == 0


@pytest.mark.asyncio
class TestAlertManagerSuppression:
    """Test alert suppression functionality."""
    
    async def test_suppression_prevents_retrigger(self):
        """
        GIVEN a rule with suppression window
        WHEN rule triggers twice within window
        THEN expect only first trigger to send notification
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        mock_notifier.send_message = AsyncMock(return_value={'status': 'success'})
        
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}",
            suppression_window=60  # 60 seconds
        )
        manager.add_rule(rule)
        
        event = {'price': 150}
        
        # First trigger
        results1 = await manager.evaluate_event(event)
        assert len(results1) == 1
        
        # Second trigger (should be suppressed)
        results2 = await manager.evaluate_event(event)
        assert len(results2) == 0
        
        # Should only call send_message once
        assert mock_notifier.send_message.call_count == 1
    
    async def test_suppression_window_zero(self):
        """
        GIVEN a rule with suppression_window=0
        WHEN rule triggers multiple times
        THEN expect all triggers to send notifications
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        mock_notifier.send_message = AsyncMock(return_value={'status': 'success'})
        
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [{'var': 'price'}, 100]},
            message_template="Price is {price}",
            suppression_window=0  # No suppression
        )
        manager.add_rule(rule)
        
        event = {'price': 150}
        
        # Multiple triggers
        await manager.evaluate_event(event)
        await manager.evaluate_event(event)
        
        # Should call send_message twice
        assert mock_notifier.send_message.call_count == 2
    
    def test_reset_suppression_specific_rule(self):
        """
        GIVEN a manager with suppressed rule
        WHEN reset_suppression is called for that rule
        THEN expect suppression to be cleared
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        manager.last_triggered["test_rule"] = time.time()
        
        manager.reset_suppression("test_rule")
        
        assert "test_rule" not in manager.last_triggered
    
    def test_reset_suppression_all_rules(self):
        """
        GIVEN a manager with multiple suppressed rules
        WHEN reset_suppression is called without rule_id
        THEN expect all suppressions to be cleared
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        manager.last_triggered["rule1"] = time.time()
        manager.last_triggered["rule2"] = time.time()
        
        manager.reset_suppression()
        
        assert len(manager.last_triggered) == 0
    
    def test_get_suppression_status(self):
        """
        GIVEN a manager with rules in various suppression states
        WHEN get_suppression_status is called
        THEN expect correct status for each rule
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule1 = AlertRule(
            rule_id="rule1",
            name="Rule 1",
            condition={'>': [1, 0]},
            message_template="Test",
            suppression_window=300
        )
        rule2 = AlertRule(
            rule_id="rule2",
            name="Rule 2",
            condition={'<': [1, 2]},
            message_template="Test2",
            suppression_window=300
        )
        
        manager.add_rule(rule1)
        manager.add_rule(rule2)
        
        # Suppress rule1
        manager.last_triggered["rule1"] = time.time()
        
        status = manager.get_suppression_status()
        
        assert "rule1" in status
        assert "rule2" in status
        assert status["rule1"]["suppressed"] is True
        assert status["rule2"]["suppressed"] is False


class TestAlertManagerMessageFormatting:
    """Test message template formatting."""
    
    def test_format_message_simple(self):
        """
        GIVEN a simple message template with variables
        WHEN _format_message is called
        THEN expect variables to be substituted
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        template = "Price is {price} for {symbol}"
        context = {'price': 150, 'symbol': 'AAPL'}
        
        result = manager._format_message(template, context)
        
        assert result == "Price is 150 for AAPL"
    
    def test_format_message_nested(self):
        """
        GIVEN a message template with nested variables
        WHEN _format_message is called
        THEN expect nested variables to be substituted
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        template = "User: {user.name}, Age: {user.age}"
        context = {
            'user': {
                'name': 'John',
                'age': 30
            }
        }
        
        result = manager._format_message(template, context)
        
        assert result == "User: John, Age: 30"
    
    def test_format_message_missing_variable(self):
        """
        GIVEN a template with variable not in context
        WHEN _format_message is called
        THEN expect placeholder to remain or be handled gracefully
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        template = "Value: {missing}"
        context = {}
        
        result = manager._format_message(template, context)
        
        # Should keep placeholder or handle gracefully
        assert "missing" in result or result == "Value: {missing}"


@pytest.mark.asyncio
class TestAlertManagerEmbedCreation:
    """Test embed creation from rule configuration."""
    
    async def test_create_embed_basic(self):
        """
        GIVEN a rule with embed_config
        WHEN _create_embed is called
        THEN expect DiscordEmbed to be created
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        rule = AlertRule(
            rule_id="test_rule",
            name="Test Rule",
            condition={'>': [1, 0]},
            message_template="Test",
            embed_config={
                'title': 'Alert: {symbol}',
                'description': 'Price is {price}',
                'fields': [
                    {'name': 'Symbol', 'value': '{symbol}', 'inline': True}
                ]
            }
        )
        
        context = {'symbol': 'AAPL', 'price': 150}
        
        embed = manager._create_embed(rule, context)
        
        assert embed is not None
        assert embed.title == 'Alert: AAPL'
        assert embed.description == 'Price is 150'
        assert len(embed.fields) == 1
    
    async def test_create_embed_severity_colors(self):
        """
        GIVEN rules with different severities
        WHEN _create_embed is called
        THEN expect correct colors based on severity
        """
        mock_notifier = Mock(spec=DiscordNotifier)
        manager = AlertManager(notifier=mock_notifier)
        
        # Critical severity
        rule_critical = AlertRule(
            rule_id="critical_rule",
            name="Critical",
            condition={'>': [1, 0]},
            message_template="Test",
            severity="critical",
            embed_config={'title': 'Critical Alert'}
        )
        
        embed_critical = manager._create_embed(rule_critical, {})
        assert embed_critical.color == 0xe74c3c  # Red


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
