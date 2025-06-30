import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import datetime
import json

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock the AuditLogger to avoid external dependencies and complex setup
class MockAuditLogger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(MockAuditLogger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.logged_events = []
            self.last_event_timestamp = None
            self._initialized = True

    def log_event(self, **kwargs):
        event_id = f"mock-event-{len(self.logged_events) + 1}"
        self.logged_events.append({"event_id": event_id, **kwargs})
        self.last_event_timestamp = datetime.datetime.now().isoformat()
        return event_id

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

@patch('ipfs_datasets_py.audit.AuditLogger', new=MockAuditLogger)
class TestMCPRecordAuditEvent(unittest.IsolatedAsyncioTestCase):

    async def test_record_audit_event_success(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event

        action = "user.login"
        user_id = "test_user"
        resource_id = "system_console"
        severity = "info"
        details = {"ip_address": "192.168.1.1"}

        result = record_audit_event( # Removed await
            action=action,
            user_id=user_id,
            resource_id=resource_id,
            severity=severity,
            details=details
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], action)
        self.assertIsNotNone(result["event_id"])
        self.assertIsNotNone(result["timestamp"])
        self.assertEqual(result["severity"], severity)
        self.assertEqual(result["resource_id"], resource_id)

        # Verify that the event was logged by the mock
        # Get the patched instance of AuditLogger
        patched_audit_logger = MockAuditLogger.get_instance()
        self.assertEqual(len(patched_audit_logger.logged_events), 1)
        logged_event = patched_audit_logger.logged_events[0]
        self.assertEqual(logged_event["action"], action)
        self.assertEqual(logged_event["user_id"], user_id)
        self.assertEqual(logged_event["resource_id"], resource_id)
        self.assertEqual(logged_event["severity"], severity)
        self.assertEqual(logged_event["details"], details)

    async def test_record_audit_event_error_handling(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event

        # Simulate an error in AuditLogger.log_event
        with patch('ipfs_datasets_py.audit.AuditLogger.log_event', side_effect=Exception("Log error")):
            result = record_audit_event(action="test.error") # Removed await
            self.assertEqual(result["status"], "error")
            self.assertIn("Log error", result["message"])
            self.assertEqual(result["action"], "test.error")

if __name__ == '__main__':
    unittest.main()
