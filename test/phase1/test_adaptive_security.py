import os
import json
import time
import unittest
import datetime
from unittest.mock import MagicMock, patch

from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.intrusion import SecurityAlert, SecurityAlertManager, IntrusionDetection
from ipfs_datasets_py.audit.enhanced_security import EnhancedSecurityManager
from ipfs_datasets_py.audit.adaptive_security import (
    AdaptiveSecurityManager, ResponseAction, SecurityResponse, ResponseRule
)


class TestAdaptiveSecurity(unittest.TestCase):
    """Test suite for the adaptive security response system."""

    def setUp(self):
        """Set up test environment."""
        # Mock dependencies
        self.audit_logger = MagicMock(spec=AuditLogger)
        self.security_manager = MagicMock(spec=EnhancedSecurityManager)
        self.alert_manager = MagicMock(spec=SecurityAlertManager)

        # Create temporary response storage file
        self.response_storage_path = "/tmp/test_responses.json"
        if os.path.exists(self.response_storage_path):
            os.remove(self.response_storage_path)

        # Create adaptive security manager
        self.adaptive_security = AdaptiveSecurityManager(
            security_manager=self.security_manager,
            alert_manager=self.alert_manager,
            audit_logger=self.audit_logger,
            response_storage_path=self.response_storage_path
        )

        # Sample security alert for testing
        self.sample_alert = SecurityAlert(
            alert_id="test-alert-123",
            timestamp=datetime.datetime.utcnow().isoformat() + 'Z',
            level="high",
            type="brute_force_login",
            description="Potential brute force login attempt detected",
            source_events=["event-1", "event-2"],
            details={
                "user": "test_user",
                "source_ip": "192.168.1.100",
                "failure_count": 5
            }
        )

    def tearDown(self):
        """Clean up after tests."""
        # Remove temporary files
        if os.path.exists(self.response_storage_path):
            os.remove(self.response_storage_path)

    def test_response_rule_matching(self):
        """Test that response rules correctly match alerts."""
        # Create test rule
        rule = ResponseRule(
            rule_id="test-rule",
            name="Test Rule",
            alert_type="brute_force_login",
            severity_levels=["medium", "high"],
            actions=[{"type": "LOCKOUT", "duration_minutes": 30}]
        )

        # Test matching
        self.assertTrue(rule.matches_alert(self.sample_alert))

        # Test non-matching alert type
        non_matching_alert = SecurityAlert(
            alert_id="test-alert-456",
            timestamp=datetime.datetime.utcnow().isoformat() + 'Z',
            level="high",
            type="data_exfiltration",  # Different type
            description="Potential data exfiltration detected",
            source_events=["event-3"],
            details={}
        )
        self.assertFalse(rule.matches_alert(non_matching_alert))

        # Test non-matching severity
        low_severity_alert = SecurityAlert(
            alert_id="test-alert-789",
            timestamp=datetime.datetime.utcnow().isoformat() + 'Z',
            level="low",  # Different severity
            type="brute_force_login",
            description="Minor brute force attempt",
            source_events=["event-4"],
            details={}
        )
        self.assertFalse(rule.matches_alert(low_severity_alert))

        # Test with conditions
        conditional_rule = ResponseRule(
            rule_id="conditional-rule",
            name="Conditional Rule",
            alert_type="brute_force_login",
            severity_levels=["high"],
            actions=[{"type": "LOCKOUT"}],
            conditions={"user": ["admin", "root"]}  # Only for these users
        )

        # Alert with matching user
        admin_alert = SecurityAlert(
            alert_id="admin-alert",
            timestamp=datetime.datetime.utcnow().isoformat() + 'Z',
            level="high",
            type="brute_force_login",
            description="Admin brute force attempt",
            source_events=["event-5"],
            details={"user": "admin"}
        )
        self.assertTrue(conditional_rule.matches_alert(admin_alert))

        # Our sample alert has user="test_user", should not match
        self.assertFalse(conditional_rule.matches_alert(self.sample_alert))

    def test_response_rule_actions(self):
        """Test that response rules generate correct actions."""
        rule = ResponseRule(
            rule_id="test-action-rule",
            name="Test Action Rule",
            alert_type="brute_force_login",
            severity_levels=["high"],
            actions=[
                {
                    "type": "LOCKOUT",
                    "duration_minutes": 30,
                    "parameters": {
                        "user_id": "$user",  # Dynamic parameter
                        "reason": "Brute force detection"
                    }
                }
            ]
        )

        # Get actions
        actions = rule.get_actions_for_alert(self.sample_alert)

        # Verify action count
        self.assertEqual(len(actions), 1)

        # Verify action parameters
        action = actions[0]
        self.assertEqual(action["type"], "LOCKOUT")
        self.assertEqual(action["duration_minutes"], 30)
        self.assertEqual(action["parameters"]["user_id"], "test_user")  # Filled from alert
        self.assertEqual(action["parameters"]["reason"], "Brute force detection")

    def test_handle_security_alert(self):
        """Test handling of security alerts."""
        # Patch the _execute_response_action method to prevent actual execution
        with patch.object(self.adaptive_security, '_execute_response_action') as mock_execute:
            # Trigger alert handling
            self.adaptive_security._handle_security_alert(self.sample_alert)

            # Verify that actions were executed
            self.assertTrue(mock_execute.called)

            # Check number of actions executed (based on default rules)
            # The brute force rule has 3 actions: LOCKOUT, MONITOR, NOTIFY
            self.assertEqual(mock_execute.call_count, 3)

    def test_execute_response_action(self):
        """Test execution of response actions."""
        # Create test action
        action = {
            "type": "MONITOR",
            "duration_minutes": 60,
            "parameters": {
                "user_id": "test_user",
                "level": "enhanced"
            }
        }

        # Patch the response handler
        with patch.object(self.adaptive_security, '_handle_monitor_response') as mock_handler:
            mock_handler.return_value = {"status": "success"}

            # Execute action
            self.adaptive_security._execute_response_action(self.sample_alert, action)

            # Verify handler was called
            self.assertTrue(mock_handler.called)

            # Verify audit log was called
            self.assertTrue(self.audit_logger.security.called)

            # Verify active responses updated
            self.assertEqual(len(self.adaptive_security.active_responses), 1)
            self.assertEqual(len(self.adaptive_security.response_history), 1)

    def test_response_lifecycle(self):
        """Test the full lifecycle of a security response."""
        # Add a response
        response = SecurityResponse(
            response_id="test-response-123",
            alert_id="test-alert-123",
            action_type=ResponseAction.LOCKOUT,
            target_id="test_user",
            target_type="user",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            duration_minutes=60,
            expiration=(datetime.datetime.utcnow() + datetime.timedelta(minutes=60)).isoformat() + 'Z'
        )

        self.adaptive_security.active_responses[response.response_id] = response
        self.adaptive_security.response_history.append(response)

        # Test getting active responses
        responses = self.adaptive_security.get_active_responses()
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].response_id, "test-response-123")

        # Test filtered queries
        user_responses = self.adaptive_security.get_active_responses(target_id="test_user")
        self.assertEqual(len(user_responses), 1)

        # Test cancellation
        result = self.adaptive_security.cancel_response("test-response-123")
        self.assertTrue(result)
        self.assertEqual(len(self.adaptive_security.active_responses), 0)

        # Verify audit log was called for cancellation
        self.audit_logger.security.assert_called_with(
            action="cancel_security_response",
            details={
                "response_id": "test-response-123",
                "response_type": "LOCKOUT",
                "target_id": "test_user",
                "target_type": "user"
            }
        )

    def test_response_expiration(self):
        """Test automatic expiration of responses."""
        # Add a response that is already expired
        past_time = (datetime.datetime.utcnow() - datetime.timedelta(minutes=10)).isoformat() + 'Z'

        expired_response = SecurityResponse(
            response_id="expired-response",
            alert_id="test-alert-123",
            action_type=ResponseAction.MONITOR,
            target_id="test_user",
            target_type="user",
            created_at=past_time,
            duration_minutes=5,  # 5 minutes
            expiration=past_time,  # Already expired
            status="active"  # Marked as active but should be expired
        )

        self.adaptive_security.active_responses[expired_response.response_id] = expired_response
        self.adaptive_security.response_history.append(expired_response)

        # Add another response that is not expired
        future_time = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat() + 'Z'

        active_response = SecurityResponse(
            response_id="active-response",
            alert_id="test-alert-123",
            action_type=ResponseAction.RESTRICT,
            target_id="test_user",
            target_type="user",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            duration_minutes=20,  # 20 minutes
            expiration=future_time,  # Not expired yet
            status="active"
        )

        self.adaptive_security.active_responses[active_response.response_id] = active_response
        self.adaptive_security.response_history.append(active_response)

        # Run expiration
        self.adaptive_security._expire_responses()

        # Verify expired response was removed from active responses
        self.assertNotIn("expired-response", self.adaptive_security.active_responses)
        self.assertIn("active-response", self.adaptive_security.active_responses)

        # Verify response status was updated
        for response in self.adaptive_security.response_history:
            if response.response_id == "expired-response":
                self.assertEqual(response.status, "expired")
            elif response.response_id == "active-response":
                self.assertEqual(response.status, "active")

    def test_save_and_load_responses(self):
        """Test saving and loading responses from storage."""
        # Add some responses
        response1 = SecurityResponse(
            response_id="response-1",
            alert_id="alert-1",
            action_type=ResponseAction.MONITOR,
            target_id="user1",
            target_type="user",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            duration_minutes=60,
            expiration=(datetime.datetime.utcnow() + datetime.timedelta(minutes=60)).isoformat() + 'Z'
        )

        response2 = SecurityResponse(
            response_id="response-2",
            alert_id="alert-2",
            action_type=ResponseAction.RESTRICT,
            target_id="resource1",
            target_type="resource",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            duration_minutes=120,
            expiration=(datetime.datetime.utcnow() + datetime.timedelta(minutes=120)).isoformat() + 'Z'
        )

        self.adaptive_security.active_responses = {
            response1.response_id: response1,
            response2.response_id: response2
        }
        self.adaptive_security.response_history = [response1, response2]

        # Save responses
        self.adaptive_security._save_responses()

        # Verify file exists
        self.assertTrue(os.path.exists(self.response_storage_path))

        # Create a new manager instance to load from storage
        new_manager = AdaptiveSecurityManager(
            security_manager=self.security_manager,
            alert_manager=self.alert_manager,
            audit_logger=self.audit_logger,
            response_storage_path=self.response_storage_path
        )

        # Clear the auto-loaded responses and manually load
        new_manager.active_responses = {}
        new_manager.response_history = []
        new_manager._load_responses()

        # Verify responses were loaded
        self.assertEqual(len(new_manager.response_history), 2)
        self.assertEqual(len(new_manager.active_responses), 2)

        # Verify response details
        for response_id in ["response-1", "response-2"]:
            self.assertIn(response_id, new_manager.active_responses)

            loaded_response = new_manager.active_responses[response_id]
            original_response = self.adaptive_security.active_responses[response_id]

            self.assertEqual(loaded_response.target_id, original_response.target_id)
            self.assertEqual(loaded_response.action_type, original_response.action_type)

    def test_response_handlers(self):
        """Test individual response handlers."""
        # Test MONITOR response
        monitor_response = SecurityResponse(
            response_id="monitor-response",
            alert_id="alert-1",
            action_type=ResponseAction.MONITOR,
            target_id="test_user",
            target_type="user",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            duration_minutes=60,
            expiration=(datetime.datetime.utcnow() + datetime.timedelta(minutes=60)).isoformat() + 'Z',
            parameters={"level": "enhanced"}
        )

        result = self.adaptive_security._handle_monitor_response(monitor_response)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["user_id"], "test_user")
        self.assertEqual(result["level"], "enhanced")

        # Verify security manager was called
        self.security_manager.set_enhanced_monitoring.assert_called_with(
            user_id="test_user",
            duration_minutes=60
        )

        # Test RESTRICT response
        restrict_response = SecurityResponse(
            response_id="restrict-response",
            alert_id="alert-1",
            action_type=ResponseAction.RESTRICT,
            target_id="resource1",
            target_type="resource",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            duration_minutes=60,
            parameters={"resource_type": "dataset"}
        )

        result = self.adaptive_security._handle_restrict_response(restrict_response)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["resource_id"], "resource1")
        self.assertEqual(result["resource_type"], "dataset")

        # Verify security manager was called
        self.security_manager.add_temporary_access_restriction.assert_called_with(
            resource_id="resource1",
            duration_minutes=60
        )

        # Test NOTIFY response
        notify_response = SecurityResponse(
            response_id="notify-response",
            alert_id="alert-1",
            action_type=ResponseAction.NOTIFY,
            target_id="user1",
            target_type="user",
            created_at=datetime.datetime.utcnow().isoformat() + 'Z',
            parameters={
                "recipient": "security@example.com",
                "message": "Security incident detected",
                "severity": "high"
            }
        )

        result = self.adaptive_security._handle_notify_response(notify_response)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["recipient"], "security@example.com")
        self.assertEqual(result["message"], "Security incident detected")
        self.assertEqual(result["severity"], "high")

        # Verify audit logger was called
        self.audit_logger.security.assert_called_with(
            action="security_notification",
            level=AuditLevel.INFO,
            details={
                "recipient": "security@example.com",
                "message": "Security incident detected",
                "severity": "high",
                "response_id": "notify-response"
            }
        )


if __name__ == '__main__':
    unittest.main()
