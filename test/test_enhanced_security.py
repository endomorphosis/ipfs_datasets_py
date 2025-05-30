"""
Tests for the Enhanced Security and Governance Module

This module contains tests for the enhanced security and governance features,
including data classification, access control, compliance monitoring, data encryption,
and security policy enforcement.
"""

import os
import json
import time
import datetime
import unittest
from unittest.mock import MagicMock, patch

from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, SecurityPolicy, AccessControlEntry, DataClassification,
    DataEncryptionConfig, AccessDecision, SecuritySession, security_operation
)


class TestEnhancedSecurity(unittest.TestCase):
    """Test cases for the enhanced security module."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock audit logger
        self.mock_audit_logger = MagicMock(spec=AuditLogger)
        self.mock_audit_logger.security = MagicMock(return_value="mock_event_id")

        # Create security manager with mock audit logger
        with patch.object(AuditLogger, 'get_instance', return_value=self.mock_audit_logger):
            self.security_manager = EnhancedSecurityManager()
            # Clear any default settings
            self.security_manager.data_classifications = {}
            self.security_manager.access_control_entries = {}
            self.security_manager.security_policies = {}
            self.security_manager.encryption_configs = {}

    def test_data_classification(self):
        """Test data classification functionality."""
        # Set a classification
        result = self.security_manager.set_data_classification(
            resource_id="test_resource",
            classification=DataClassification.CONFIDENTIAL,
            user_id="test_user"
        )
        self.assertTrue(result)

        # Verify classification was set
        classification = self.security_manager.get_data_classification("test_resource")
        self.assertEqual(classification, DataClassification.CONFIDENTIAL)

        # Verify audit logger was called
        self.mock_audit_logger.security.assert_called_with(
            action="set_data_classification",
            resource_id="test_resource",
            user="test_user",
            details={
                "classification": "CONFIDENTIAL",
                "previous_classification": None
            }
        )

        # Update the classification
        result = self.security_manager.set_data_classification(
            resource_id="test_resource",
            classification=DataClassification.RESTRICTED,
            user_id="test_user"
        )
        self.assertTrue(result)

        # Verify classification was updated
        classification = self.security_manager.get_data_classification("test_resource")
        self.assertEqual(classification, DataClassification.RESTRICTED)

        # Verify audit logger was called for update
        self.mock_audit_logger.security.assert_called_with(
            action="set_data_classification",
            resource_id="test_resource",
            user="test_user",
            details={
                "classification": "RESTRICTED",
                "previous_classification": "CONFIDENTIAL"
            }
        )

    def test_access_control(self):
        """Test access control functionality."""
        # Create an access control entry
        ace = AccessControlEntry(
            resource_id="protected_resource",
            resource_type="document",
            principal_id="alice",
            principal_type="user",
            permissions=["read", "write"],
            conditions={"ip_range": "192.168.1.0/24"},
            expiration=None
        )

        # Add the ACE
        result = self.security_manager.add_access_control_entry(ace, user_id="admin")
        self.assertTrue(result)

        # Verify ACE was added
        entries = self.security_manager.get_access_control_entries("protected_resource")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].principal_id, "alice")

        # Verify audit logger was called
        self.mock_audit_logger.security.assert_called_with(
            action="add_access_control_entry",
            resource_id="protected_resource",
            resource_type="document",
            user="admin",
            details={
                "principal_id": "alice",
                "principal_type": "user",
                "permissions": ["read", "write"],
                "expiration": None
            }
        )

        # Check access control decision - allow
        with patch.object(self.security_manager, '_evaluate_conditions', return_value=True):
            decision = self.security_manager.check_access(
                user_id="alice",
                resource_id="protected_resource",
                operation="read"
            )
            self.assertEqual(decision, AccessDecision.ALLOW)

        # Check access control decision - deny (wrong user)
        decision = self.security_manager.check_access(
            user_id="bob",
            resource_id="protected_resource",
            operation="read"
        )
        self.assertEqual(decision, AccessDecision.DENY)

        # Check access control decision - deny (wrong operation)
        decision = self.security_manager.check_access(
            user_id="alice",
            resource_id="protected_resource",
            operation="delete"
        )
        self.assertEqual(decision, AccessDecision.DENY)

        # Remove the ACE
        result = self.security_manager.remove_access_control_entry(
            resource_id="protected_resource",
            principal_id="alice",
            principal_type="user",
            user_id="admin"
        )
        self.assertTrue(result)

        # Verify ACE was removed
        entries = self.security_manager.get_access_control_entries("protected_resource")
        self.assertEqual(len(entries), 0)

        # Verify audit logger was called for removal
        self.mock_audit_logger.security.assert_called_with(
            action="remove_access_control_entry",
            resource_id="protected_resource",
            user="admin",
            details={
                "principal_id": "alice",
                "principal_type": "user"
            }
        )

    def test_security_policy(self):
        """Test security policy functionality."""
        # Create a security policy
        policy = SecurityPolicy(
            policy_id="test_policy",
            name="Test Security Policy",
            description="A policy for testing",
            enabled=True,
            enforcement_level="enforcing",
            rules=[
                {
                    "type": "data_classification",
                    "min_classification": "CONFIDENTIAL",
                    "severity": "high"
                },
                {
                    "type": "access_time",
                    "allowed_hours": {"start": 8, "end": 18},
                    "severity": "medium"
                }
            ]
        )

        # Add the policy
        result = self.security_manager.add_security_policy(policy, user_id="admin")
        self.assertTrue(result)

        # Verify policy was added
        stored_policy = self.security_manager.get_security_policy("test_policy")
        self.assertEqual(stored_policy.name, "Test Security Policy")

        # Verify audit logger was called
        self.mock_audit_logger.security.assert_called_with(
            action="add_security_policy",
            user="admin",
            details={
                "policy_id": "test_policy",
                "policy_name": "Test Security Policy",
                "enforcement_level": "enforcing",
                "rule_count": 2
            }
        )

        # List policies
        policies = self.security_manager.list_security_policies()
        self.assertEqual(len(policies), 1)

        # Remove the policy
        result = self.security_manager.remove_security_policy("test_policy", user_id="admin")
        self.assertTrue(result)

        # Verify policy was removed
        stored_policy = self.security_manager.get_security_policy("test_policy")
        self.assertIsNone(stored_policy)

        # Verify audit logger was called for removal
        self.mock_audit_logger.security.assert_called_with(
            action="remove_security_policy",
            user="admin",
            details={
                "policy_id": "test_policy"
            }
        )

    def test_encryption_config(self):
        """Test encryption configuration functionality."""
        # Create an encryption configuration
        config = DataEncryptionConfig(
            enabled=True,
            key_id="test_key",
            algorithm="AES-256-GCM",
            key_rotation_days=90
        )

        # Add the configuration
        result = self.security_manager.add_encryption_config(
            resource_id="sensitive_data",
            config=config,
            user_id="admin"
        )
        self.assertTrue(result)

        # Verify configuration was added
        stored_config = self.security_manager.get_encryption_config("sensitive_data")
        self.assertEqual(stored_config.key_id, "test_key")

        # Verify audit logger was called
        self.mock_audit_logger.security.assert_called_with(
            action="add_encryption_config",
            resource_id="sensitive_data",
            user="admin",
            details={
                "encryption_enabled": True,
                "algorithm": "AES-256-GCM",
                "key_rotation_days": 90
            }
        )

    def test_policy_violations(self):
        """Test policy violation detection."""
        # Create a security policy
        policy = SecurityPolicy(
            policy_id="data_volume_policy",
            name="Data Volume Policy",
            description="Restricts large data operations",
            enabled=True,
            enforcement_level="enforcing",
            rules=[
                {
                    "type": "data_volume",
                    "threshold_bytes": 1024 * 1024,  # 1MB
                    "severity": "medium"
                }
            ]
        )

        # Add the policy
        self.security_manager.add_security_policy(policy)

        # Create a mock audit event that would trigger the policy
        event = AuditEvent(
            event_id="test_event",
            timestamp=datetime.datetime.utcnow().isoformat() + 'Z',
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="download",
            user="test_user",
            resource_id="large_file",
            resource_type="file",
            details={"data_size_bytes": 2 * 1024 * 1024}  # 2MB
        )

        # Process the event
        with patch.object(self.security_manager, 'audit_logger') as mock_logger:
            self.security_manager._process_audit_event(event)

            # Verify violation was logged
            mock_logger.security.assert_called_with(
                action="policy_violation",
                level=AuditLevel.WARNING,
                resource_id="large_file",
                resource_type="file",
                user="test_user",
                details={
                    "policy_id": "data_volume_policy",
                    "rule_type": "data_volume",
                    "description": "Data operation size (2.00 MB) exceeds threshold (1.00 MB)",
                    "severity": "medium",
                    "source_event_id": "test_event"
                }
            )

    def test_security_session(self):
        """Test security session context manager."""
        # Use the security session context manager
        with patch.object(self.security_manager, 'audit_logger') as mock_logger:
            with SecuritySession(
                user_id="test_user",
                resource_id="test_resource",
                action="test_operation",
                security_manager=self.security_manager
            ) as session:
                # Set some context
                session.set_context("client_ip", "192.168.1.100")

                # Do some operation
                pass

            # Verify session start was logged
            mock_logger.security.assert_any_call(
                action="test_operation_start",
                user="test_user",
                resource_id="test_resource",
                details={"session_context": {}}
            )

            # Verify session completion was logged
            mock_logger.security.assert_any_call(
                action="test_operation_complete",
                user="test_user",
                resource_id="test_resource",
                status="success",
                details={
                    "duration_ms": unittest.mock.ANY,
                    "session_context": {"client_ip": "192.168.1.100"}
                }
            )

    def test_security_operation_decorator(self):
        """Test security operation decorator."""
        # Create a decorated function
        @security_operation(user_id_arg="user", resource_id_arg="resource")
        def test_function(user, resource, data):
            return f"Processed {data} for {user} on {resource}"

        # Set up access control
        ace = AccessControlEntry(
            resource_id="test_resource",
            resource_type="document",
            principal_id="alice",
            principal_type="user",
            permissions=["read"]
        )
        self.security_manager.add_access_control_entry(ace)

        # Mock check_access to allow access
        with patch.object(self.security_manager, 'check_access', return_value=AccessDecision.ALLOW):
            with patch.object(SecuritySession, '__enter__', return_value=MagicMock()):
                with patch.object(SecuritySession, '__exit__'):
                    # Call the function
                    result = test_function(user="alice", resource="test_resource", data="test_data")
                    self.assertEqual(result, "Processed test_data for alice on test_resource")

        # Mock check_access to deny access
        with patch.object(self.security_manager, 'check_access', return_value=AccessDecision.DENY):
            with patch.object(self.security_manager.audit_logger, 'authz'):
                # Call the function - should raise PermissionError
                with self.assertRaises(PermissionError):
                    test_function(user="bob", resource="test_resource", data="test_data")


if __name__ == '__main__':
    unittest.main()
