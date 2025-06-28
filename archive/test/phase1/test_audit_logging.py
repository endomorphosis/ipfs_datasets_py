"""
Tests for the Audit Logging System.

This module contains comprehensive tests for the audit logging system,
ensuring that audit events are properly recorded, processed, and reported.
"""

import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditLevel, AuditCategory
)
from ipfs_datasets_py.audit.handlers import (
    FileAuditHandler, JSONAuditHandler
)
from ipfs_datasets_py.audit.compliance import (
    ComplianceReport, ComplianceStandard, GDPRComplianceReporter
)
from ipfs_datasets_py.audit.intrusion import (
    IntrusionDetection, SecurityAlert, SecurityAlertManager, AnomalyDetector
)


class TestAuditEvent(unittest.TestCase):
    """Tests for the AuditEvent class."""

    def test_creation(self):
        """Test AuditEvent creation and field initialization."""
        event = AuditEvent(
            event_id="test123",
            timestamp="2023-01-01T12:00:00Z",
            level=AuditLevel.INFO,
            category=AuditCategory.AUTHENTICATION,
            action="login",
            user="test_user",
            resource_id="resource123",
            resource_type="user_account",
            status="success",
            details={"ip": "127.0.0.1", "method": "password"}
        )

        self.assertEqual(event.event_id, "test123")
        self.assertEqual(event.timestamp, "2023-01-01T12:00:00Z")
        self.assertEqual(event.level, AuditLevel.INFO)
        self.assertEqual(event.category, AuditCategory.AUTHENTICATION)
        self.assertEqual(event.action, "login")
        self.assertEqual(event.user, "test_user")
        self.assertEqual(event.resource_id, "resource123")
        self.assertEqual(event.resource_type, "user_account")
        self.assertEqual(event.status, "success")
        self.assertEqual(event.details, {"ip": "127.0.0.1", "method": "password"})

    def test_default_values(self):
        """Test default value initialization."""
        event = AuditEvent(
            event_id="",  # Should auto-generate
            timestamp="",  # Should auto-generate
            level=AuditLevel.INFO,
            category=AuditCategory.SYSTEM,
            action="test"
        )

        self.assertNotEqual(event.event_id, "")
        self.assertNotEqual(event.timestamp, "")
        self.assertEqual(event.status, "success")
        self.assertEqual(event.details, {})

    def test_serialization(self):
        """Test serialization to dict and JSON."""
        event = AuditEvent(
            event_id="test456",
            timestamp="2023-01-01T12:00:00Z",
            level=AuditLevel.WARNING,
            category=AuditCategory.SECURITY,
            action="access_denied",
            user="test_user",
            details={"reason": "insufficient_permissions"}
        )

        # Test to_dict()
        event_dict = event.to_dict()
        self.assertEqual(event_dict["event_id"], "test456")
        self.assertEqual(event_dict["level"], "WARNING")
        self.assertEqual(event_dict["category"], "SECURITY")

        # Test to_json()
        json_str = event.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["event_id"], "test456")
        self.assertEqual(parsed["action"], "access_denied")

    def test_deserialization(self):
        """Test deserialization from dict and JSON."""
        # Create a dictionary representation
        event_dict = {
            "event_id": "test789",
            "timestamp": "2023-01-01T12:00:00Z",
            "level": "ERROR",
            "category": "SYSTEM",
            "action": "process_crash",
            "user": "system",
            "details": {"process_id": 1234, "exit_code": -1}
        }

        # Test from_dict()
        event = AuditEvent.from_dict(event_dict)
        self.assertEqual(event.event_id, "test789")
        self.assertEqual(event.level, AuditLevel.ERROR)
        self.assertEqual(event.category, AuditCategory.SYSTEM)

        # Test from_json()
        json_str = json.dumps(event_dict)
        event = AuditEvent.from_json(json_str)
        self.assertEqual(event.event_id, "test789")
        self.assertEqual(event.action, "process_crash")
        self.assertEqual(event.details["process_id"], 1234)


class TestAuditLogger(unittest.TestCase):
    """Tests for the AuditLogger class."""

    def setUp(self):
        """Set up the test environment."""
        # Reset the singleton instance for each test
        AuditLogger._instance = None
        self.logger = AuditLogger.get_instance()

        # Create a temporary directory for log files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = os.path.join(self.temp_dir.name, "audit.log")
        self.json_file = os.path.join(self.temp_dir.name, "audit.json")

        # Add handlers
        self.file_handler = FileAuditHandler("file", file_path=self.log_file)
        self.json_handler = JSONAuditHandler("json", file_path=self.json_file)
        self.logger.add_handler(self.file_handler)
        self.logger.add_handler(self.json_handler)

    def tearDown(self):
        """Clean up after the test."""
        # Clean up temporary directory
        self.temp_dir.cleanup()

        # Reset the logger
        self.logger.reset()

    def test_basic_logging(self):
        """Test basic logging functionality."""
        # Log an event
        event_id = self.logger.log(
            level=AuditLevel.INFO,
            category=AuditCategory.AUTHENTICATION,
            action="login",
            user="test_user",
            status="success"
        )

        # Check that the event was logged to files
        self.assertTrue(os.path.exists(self.log_file))
        self.assertTrue(os.path.exists(self.json_file))

        # Verify file contents
        with open(self.json_file, 'r') as f:
            content = f.read()
            self.assertIn(event_id, content)
            self.assertIn("test_user", content)
            self.assertIn("login", content)

    def test_context_application(self):
        """Test that context is properly applied to events."""
        # Set context
        self.logger.set_context(
            user="context_user",
            session_id="session123",
            client_ip="192.168.1.100"
        )

        # Log an event without specifying these fields
        event_id = self.logger.log(
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="read",
            resource_id="doc123"
        )

        # Verify context was applied
        with open(self.json_file, 'r') as f:
            content = f.read()
            data = json.loads(content)
            self.assertEqual(data["user"], "context_user")
            self.assertEqual(data["session_id"], "session123")
            self.assertEqual(data["client_ip"], "192.168.1.100")

        # Clear context
        self.logger.clear_context()

        # Log another event
        event_id2 = self.logger.log(
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="read",
            resource_id="doc456",
            user="explicit_user"  # This should take precedence
        )

        # Verify context was cleared
        with open(self.json_file, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)  # Two events logged
            data2 = json.loads(lines[1])
            self.assertEqual(data2["user"], "explicit_user")
            self.assertNotEqual(data2["session_id"], "session123")

    def test_convenience_methods(self):
        """Test convenience logging methods."""
        # Test level-based methods
        self.logger.info(AuditCategory.SYSTEM, "test_info")
        self.logger.warning(AuditCategory.SECURITY, "test_warning")
        self.logger.error(AuditCategory.SYSTEM, "test_error")

        # Test category-based methods
        self.logger.auth("login_test")
        self.logger.data_access("read_test")
        self.logger.security("security_test")

        # Verify all events were logged
        with open(self.json_file, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 6)  # Six events logged

            # Check specific events
            data = [json.loads(line) for line in lines]
            actions = [d["action"] for d in data]
            self.assertIn("test_info", actions)
            self.assertIn("test_warning", actions)
            self.assertIn("test_error", actions)
            self.assertIn("login_test", actions)
            self.assertIn("read_test", actions)
            self.assertIn("security_test", actions)

    def test_filtering(self):
        """Test event filtering by level and category."""
        # Set minimum level
        self.logger.min_level = AuditLevel.WARNING

        # Log events with different levels
        self.logger.debug(AuditCategory.SYSTEM, "debug_event")  # Should be filtered
        self.logger.info(AuditCategory.SYSTEM, "info_event")    # Should be filtered
        self.logger.warning(AuditCategory.SYSTEM, "warning_event")  # Should pass
        self.logger.error(AuditCategory.SYSTEM, "error_event")    # Should pass

        # Verify only appropriate events were logged
        with open(self.json_file, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)  # Two events logged

            data = [json.loads(line) for line in lines]
            actions = [d["action"] for d in data]
            self.assertNotIn("debug_event", actions)
            self.assertNotIn("info_event", actions)
            self.assertIn("warning_event", actions)
            self.assertIn("error_event", actions)

        # Reset and test category filtering
        self.logger.reset()
        self.logger.add_handler(self.json_handler)
        self.logger.min_level = AuditLevel.INFO

        # Set included categories
        self.logger.included_categories = {AuditCategory.AUTHENTICATION, AuditCategory.AUTHORIZATION}

        # Log events with different categories
        self.logger.info(AuditCategory.AUTHENTICATION, "auth_event")  # Should pass
        self.logger.info(AuditCategory.AUTHORIZATION, "authz_event")  # Should pass
        self.logger.info(AuditCategory.SYSTEM, "system_event")        # Should be filtered
        self.logger.info(AuditCategory.DATA_ACCESS, "data_event")     # Should be filtered

        # Verify only appropriate events were logged
        with open(self.json_file, 'r') as f:
            # Clear file first
            f.seek(0)
            f.truncate()

            # Now log events
            self.logger.info(AuditCategory.AUTHENTICATION, "auth_event")
            self.logger.info(AuditCategory.AUTHORIZATION, "authz_event")
            self.logger.info(AuditCategory.SYSTEM, "system_event")
            self.logger.info(AuditCategory.DATA_ACCESS, "data_event")

            # Verify
            f.seek(0)
            lines = f.readlines()
            self.assertEqual(len(lines), 2)  # Two events logged

            data = [json.loads(line) for line in lines]
            actions = [d["action"] for d in data]
            self.assertIn("auth_event", actions)
            self.assertIn("authz_event", actions)
            self.assertNotIn("system_event", actions)
            self.assertNotIn("data_event", actions)


class TestFileHandlers(unittest.TestCase):
    """Tests for the audit log file handlers."""

    def setUp(self):
        """Set up the test environment."""
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        """Clean up after the test."""
        self.temp_dir.cleanup()

    def test_file_handler(self):
        """Test the FileAuditHandler."""
        log_file = os.path.join(self.temp_dir.name, "audit.log")

        # Create handler with rotation
        handler = FileAuditHandler(
            name="test",
            file_path=log_file,
            rotate_size_mb=0.001,  # Very small to force rotation
            rotate_count=3
        )

        # Create test event
        event = AuditEvent(
            event_id="test123",
            timestamp=datetime.now().isoformat(),
            level=AuditLevel.INFO,
            category=AuditCategory.SYSTEM,
            action="test_action"
        )

        # Write enough events to trigger rotation
        for i in range(50):
            event.event_id = f"test{i}"
            handler._handle_event(event)

        # Check that files were created and rotated
        self.assertTrue(os.path.exists(log_file))
        self.assertTrue(os.path.exists(log_file + ".1"))

        # Close handler
        handler.close()

    def test_json_handler(self):
        """Test the JSONAuditHandler."""
        json_file = os.path.join(self.temp_dir.name, "audit.json")

        # Create handler
        handler = JSONAuditHandler(
            name="test",
            file_path=json_file,
            pretty=True
        )

        # Create test event
        event = AuditEvent(
            event_id="json123",
            timestamp=datetime.now().isoformat(),
            level=AuditLevel.WARNING,
            category=AuditCategory.SECURITY,
            action="security_test",
            details={"critical": True, "reason": "suspicious activity"}
        )

        # Write event
        handler._handle_event(event)

        # Verify file contents
        with open(json_file, 'r') as f:
            content = f.read()
            self.assertIn("json123", content)
            self.assertIn("suspicious activity", content)
            self.assertIn("SECURITY", content)

        # Close handler
        handler.close()


class TestComplianceReporting(unittest.TestCase):
    """Tests for the compliance reporting functionality."""

    def test_gdpr_compliance_reporter(self):
        """Test the GDPRComplianceReporter."""
        # Create a reporter
        reporter = GDPRComplianceReporter()

        # Create some test events
        events = [
            # Article 30 - Records of processing
            AuditEvent(
                event_id="gdpr1",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_ACCESS,
                action="read",
                user="test_user",
                resource_id="personal_data_123",
                resource_type="personal_data"
            ),
            # Article 32 - Security
            AuditEvent(
                event_id="gdpr2",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.SECURITY,
                action="encryption_check",
                user="admin",
                resource_id="database",
                resource_type="storage",
                details={"encryption_status": "enabled"}
            ),
            # Article 15 - Right of access
            AuditEvent(
                event_id="gdpr3",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_ACCESS,
                action="subject_access_request",
                user="admin",
                resource_id="user_456",
                resource_type="user_data"
            )
        ]

        # Generate a report
        report = reporter.generate_report(events)

        # Verify report contents
        self.assertEqual(report.standard, ComplianceStandard.GDPR)
        self.assertFalse(report.compliant)  # Should not be fully compliant

        # Check requirements
        req_ids = [req["id"] for req in report.requirements]
        self.assertIn("GDPR-Art30", req_ids)
        self.assertIn("GDPR-Art32", req_ids)
        self.assertIn("GDPR-Art15", req_ids)

        # Check summary
        self.assertEqual(report.summary["total_requirements"], 5)  # Total GDPR requirements

        # Test report formats
        temp_dir = tempfile.TemporaryDirectory()
        try:
            # Save in different formats
            json_path = os.path.join(temp_dir.name, "report.json")
            csv_path = os.path.join(temp_dir.name, "report.csv")
            html_path = os.path.join(temp_dir.name, "report.html")

            report.save_json(json_path)
            report.save_csv(csv_path)
            report.save_html(html_path)

            # Verify files exist
            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(csv_path))
            self.assertTrue(os.path.exists(html_path))

            # Check content
            with open(json_path, 'r') as f:
                data = json.load(f)
                self.assertEqual(data["standard"], "GDPR")

        finally:
            temp_dir.cleanup()


class TestIntrusionDetection(unittest.TestCase):
    """Tests for the intrusion detection system."""

    def test_anomaly_detector(self):
        """Test the AnomalyDetector component."""
        # Create detector
        detector = AnomalyDetector(window_size=10)

        # Create baseline events (normal behavior)
        baseline_events = []
        for i in range(50):
            # Normal login pattern - 80% success, 20% failure
            status = "success" if i % 5 != 0 else "failure"
            event = AuditEvent(
                event_id=f"baseline{i}",
                timestamp=(datetime.now() - timedelta(days=1)).isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.AUTHENTICATION,
                action="login",
                user="normal_user",
                status=status
            )
            baseline_events.append(event)

        # Establish baseline
        detector.establish_baseline(baseline_events)

        # Test normal events (should not trigger anomalies)
        anomalies = []
        for i in range(10):
            status = "success" if i % 5 != 0 else "failure"
            event = AuditEvent(
                event_id=f"normal{i}",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.AUTHENTICATION,
                action="login",
                user="normal_user",
                status=status
            )
            result = detector.process_event(event)
            anomalies.extend(result)

        # Verify no anomalies for normal behavior
        self.assertEqual(len(anomalies), 0)

        # Test anomalous events (high failure rate)
        anomalies = []
        for i in range(10):
            # 80% failure rate (opposite of baseline)
            status = "failure" if i % 5 != 0 else "success"
            event = AuditEvent(
                event_id=f"anomalous{i}",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.AUTHENTICATION,
                action="login",
                user="suspicious_user",
                status=status
            )
            result = detector.process_event(event)
            anomalies.extend(result)

        # Verify anomalies detected
        self.assertGreater(len(anomalies), 0)

        # Check anomaly details
        for anomaly in anomalies:
            self.assertIn("type", anomaly)
            self.assertIn("severity", anomaly)
            self.assertIn("description", anomaly)

    def test_pattern_detection(self):
        """Test intrusion pattern detection."""
        # Create intrusion detection system
        ids = IntrusionDetection()

        # Create events that should trigger brute force detection
        brute_force_events = []
        for i in range(6):
            event = AuditEvent(
                event_id=f"brute{i}",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.WARNING,
                category=AuditCategory.AUTHENTICATION,
                action="login",
                user="victim",
                status="failure",
                client_ip="192.168.1.100",
                details={"reason": "invalid_password"}
            )
            brute_force_events.append(event)

        # Add some normal events
        normal_events = []
        for i in range(3):
            event = AuditEvent(
                event_id=f"normal{i}",
                timestamp=datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_ACCESS,
                action="read",
                user="regular_user"
            )
            normal_events.append(event)

        # Mock alert handler
        mock_handler = MagicMock()
        ids.add_alert_handler(mock_handler)

        # Process events
        all_events = brute_force_events + normal_events
        alerts = ids.process_events(all_events)

        # Verify alerts were generated
        self.assertGreater(len(alerts), 0)

        # Check alert handler was called
        self.assertGreater(mock_handler.call_count, 0)

        # Check alert details
        brute_force_detected = False
        for alert in alerts:
            if alert.type == "brute_force_login":
                brute_force_detected = True
                self.assertEqual(alert.level, "high")
                self.assertEqual(len(alert.source_events), 6)

        self.assertTrue(brute_force_detected, "Brute force attack not detected")

    def test_security_alert_manager(self):
        """Test the SecurityAlertManager."""
        # Create a temporary file for alert storage
        temp_dir = tempfile.TemporaryDirectory()
        alerts_file = os.path.join(temp_dir.name, "alerts.json")

        try:
            # Create alert manager
            manager = SecurityAlertManager(alert_storage_path=alerts_file)

            # Create a test alert
            alert = SecurityAlert(
                alert_id="alert123",
                timestamp=datetime.now().isoformat(),
                level="high",
                type="test_alert",
                description="Test security alert",
                source_events=["event1", "event2"]
            )

            # Add alert
            manager.add_alert(alert)

            # Verify alert was stored
            self.assertTrue(os.path.exists(alerts_file))

            # Get alert
            retrieved = manager.get_alert("alert123")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.alert_id, "alert123")

            # Update alert
            manager.update_alert("alert123", {"status": "investigating", "assigned_to": "security_team"})

            # Verify update
            updated = manager.get_alert("alert123")
            self.assertEqual(updated.status, "investigating")
            self.assertEqual(updated.assigned_to, "security_team")

            # Test filtering
            alerts = manager.get_alerts({"level": "high"})
            self.assertEqual(len(alerts), 1)

            alerts = manager.get_alerts({"level": "low"})
            self.assertEqual(len(alerts), 0)

        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
