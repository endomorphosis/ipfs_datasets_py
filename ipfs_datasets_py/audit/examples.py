"""
Example usage for the audit logging system.

This module demonstrates how to use the comprehensive audit logging system
with various handlers and configurations.
"""

import os
import sys
import logging
from datetime import datetime, timedelta

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditLevel, AuditCategory, AuditHandler
)
from ipfs_datasets_py.audit.handlers import (
    FileAuditHandler, JSONAuditHandler, SyslogAuditHandler, 
    ElasticsearchAuditHandler, AlertingAuditHandler
)
from ipfs_datasets_py.audit.compliance import (
    ComplianceReport, ComplianceStandard, GDPRComplianceReporter
)
from ipfs_datasets_py.audit.intrusion import (
    IntrusionDetection, SecurityAlert, SecurityAlertManager
)


def setup_basic_audit_logging():
    """Set up basic audit logging with file output."""
    # Get the global audit logger instance
    audit_logger = AuditLogger.get_instance()
    
    # Configure the logger
    audit_logger.min_level = AuditLevel.INFO
    audit_logger.default_application = "ipfs_datasets_example"
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Add a file handler
    file_handler = FileAuditHandler(
        name="file",
        file_path="logs/audit.log",
        min_level=AuditLevel.INFO,
        rotate_size_mb=10,
        rotate_count=5
    )
    audit_logger.add_handler(file_handler)
    
    # Add a JSON handler for machine-readable logs
    json_handler = JSONAuditHandler(
        name="json",
        file_path="logs/audit.json",
        min_level=AuditLevel.INFO,
        pretty=False,
        rotate_size_mb=10,
        rotate_count=5
    )
    audit_logger.add_handler(json_handler)
    
    return audit_logger


def setup_compliance_monitoring():
    """Set up compliance monitoring with GDPR requirements."""
    # Create a GDPR compliance reporter
    reporter = GDPRComplianceReporter()
    
    # Create a file handler for storing compliance-relevant events
    compliance_handler = JSONAuditHandler(
        name="compliance",
        file_path="logs/compliance.json",
        min_level=AuditLevel.INFO,
        pretty=False
    )
    
    # Add the handler to the audit logger
    audit_logger = AuditLogger.get_instance()
    audit_logger.add_handler(compliance_handler)
    
    return reporter


def setup_intrusion_detection():
    """Set up intrusion detection with alerting."""
    # Create the intrusion detection system
    ids = IntrusionDetection()
    
    # Create an alert manager
    alert_manager = SecurityAlertManager(alert_storage_path="logs/alerts.json")
    
    # Add a simple console alert handler
    def alert_handler(alert):
        print(f"SECURITY ALERT: {alert.level.upper()} - {alert.description}")
    
    alert_manager.add_notification_handler(alert_handler)
    
    # Add an email alert handler (commented out, implement if needed)
    """
    def email_alert_handler(alert):
        if alert.level in ['high', 'critical']:
            # Implement email sending logic here
            subject = f"SECURITY ALERT: {alert.level.upper()} - {alert.type}"
            body = f"Description: {alert.description}\n\nDetails: {alert.details}"
            send_email("security@example.com", subject, body)
    
    alert_manager.add_notification_handler(email_alert_handler)
    """
    
    # Connect the intrusion detection to the alert manager
    ids.add_alert_handler(alert_manager.add_alert)
    
    return ids, alert_manager


def demonstrate_audit_logging():
    """Demonstrate various audit logging capabilities."""
    # Set up audit logging
    audit_logger = setup_basic_audit_logging()
    
    # Set user context for this thread
    audit_logger.set_context(user="example_user", session_id="session123")
    
    # Log some example events
    print("Logging example audit events...")
    
    # Authentication events
    audit_logger.auth("login", status="success", 
                   details={"method": "password", "mfa_used": True})
    
    # Data access events
    audit_logger.data_access("read", 
                          resource_id="dataset123", 
                          resource_type="dataset",
                          details={"rows_accessed": 1000, "query": "SELECT * FROM table"})
    
    # Configuration change
    audit_logger.log(
        level=AuditLevel.NOTICE,
        category=AuditCategory.CONFIGURATION,
        action="update_settings",
        resource_id="config",
        resource_type="system_config",
        details={
            "changes": {"log_level": "DEBUG", "retention_days": 90},
            "reason": "Increased logging for security audit"
        }
    )
    
    # Security event
    audit_logger.security("permission_change",
                       level=AuditLevel.WARNING,
                       resource_id="role123",
                       resource_type="role",
                       details={
                           "target_user": "jane_doe",
                           "permissions_added": ["admin"],
                           "permissions_removed": []
                       })
    
    # Error event
    audit_logger.error(
        category=AuditCategory.SYSTEM,
        action="process_failure",
        details={
            "process": "data_import",
            "error": "Database connection timeout",
            "retry_count": 3
        }
    )
    
    print("Events logged successfully to logs/audit.log and logs/audit.json")


def demonstrate_compliance_reporting():
    """Demonstrate compliance reporting capabilities."""
    # Set up audit logging if not already done
    if not AuditLogger.get_instance().handlers:
        setup_basic_audit_logging()
    
    # Set up compliance monitoring
    reporter = setup_compliance_monitoring()
    
    # Log some compliance-relevant events
    audit_logger = AuditLogger.get_instance()
    
    print("Logging compliance-relevant events...")
    
    # Log events relevant to GDPR Article 30 (Records of processing)
    audit_logger.data_access("read", 
                          resource_id="personal_data_123", 
                          resource_type="personal_data",
                          details={"purpose": "customer_support", "legal_basis": "legitimate_interest"})
    
    # Log events relevant to GDPR Article 32 (Security)
    audit_logger.security("encryption_check",
                       resource_id="database",
                       resource_type="storage",
                       details={"encryption_status": "enabled", "algorithm": "AES-256"})
    
    # Log events relevant to GDPR Article 15 (Right of access)
    audit_logger.data_access("subject_access_request",
                          resource_id="user_456",
                          resource_type="user_data",
                          details={"request_id": "sar123", "fulfilled": True, "fulfill_date": datetime.now().isoformat()})
    
    # Generate a compliance report
    # In a real scenario, we would load historical events from storage
    events = []  # This would be loaded from logs in a real scenario
    
    # For demonstration, we'll use placeholder report creation
    report = ComplianceReport(
        report_id=f"GDPR-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        standard=ComplianceStandard.GDPR,
        generated_at=datetime.now().isoformat(),
        time_period={
            "start": (datetime.now() - timedelta(days=30)).isoformat(),
            "end": datetime.now().isoformat()
        },
        requirements=[
            {
                "id": "GDPR-Art30",
                "description": "Records of processing activities",
                "status": "Compliant",
                "evidence_count": 5,
                "notes": "Processing activities properly recorded"
            },
            {
                "id": "GDPR-Art32",
                "description": "Security of processing",
                "status": "Partial",
                "evidence_count": 3,
                "notes": "Encryption in place, but regular testing not evidenced"
            }
        ],
        summary={
            "total_requirements": 2,
            "compliant_count": 1,
            "non_compliant_count": 0,
            "partial_count": 1,
            "compliance_rate": 50.0
        },
        compliant=False,
        remediation_suggestions={
            "GDPR-Art32": [
                "Implement regular security testing",
                "Document test results in audit logs"
            ]
        }
    )
    
    # Save report in various formats
    os.makedirs("reports", exist_ok=True)
    report.save_json("reports/gdpr_compliance.json")
    report.save_csv("reports/gdpr_compliance.csv")
    report.save_html("reports/gdpr_compliance.html")
    
    print("Compliance report generated and saved to reports/ directory")


def demonstrate_intrusion_detection():
    """Demonstrate intrusion detection capabilities."""
    # Set up audit logging if not already done
    if not AuditLogger.get_instance().handlers:
        setup_basic_audit_logging()
    
    # Set up intrusion detection
    ids, alert_manager = setup_intrusion_detection()
    
    print("Simulating security-relevant events...")
    
    # Generate a series of events that should trigger alerts
    audit_logger = AuditLogger.get_instance()
    
    # Simulate brute force login attempts
    for i in range(6):
        audit_logger.auth("login", 
                       user="attacker",
                       client_ip="192.168.1.100",
                       status="failure",
                       details={"reason": "invalid_password", "attempt": i+1})
    
    # Simulate multiple access denials
    for i in range(4):
        audit_logger.authz("access_denied",
                        user="suspicious_user",
                        resource_id=f"sensitive_resource_{i}",
                        resource_type="financial_data",
                        details={"reason": "insufficient_permissions"})
    
    # Simulate privilege escalation
    audit_logger.security("permission_change",
                       user="malicious_admin",
                       resource_id="user_role",
                       resource_type="role",
                       details={
                           "target_user": "compromised_account",
                           "permissions_added": ["admin", "system"],
                           "permissions_removed": [],
                           "justification": "emergency access"
                       })
    
    # Simulate unauthorized configuration change
    audit_logger.log(
        level=AuditLevel.WARNING,
        category=AuditCategory.CONFIGURATION,
        action="update_settings",
        user="unauthorized_user",
        resource_id="security_config",
        resource_type="system_config",
        status="failure",
        details={
            "changes": {"audit_enabled": False, "firewall_enabled": False},
            "reason": "unauthorized"
        }
    )
    
    # Process events through intrusion detection
    # In a real scenario, we would periodically process batched events
    # For demonstration, we'll assume events are being processed in real-time
    print("\nAlerts should appear above as events are processed")
    print("Alerts are also saved to logs/alerts.json")


def main():
    """Main entry point for the example."""
    # Configure logging
    logging.basicConfig(level=logging.INFO, 
                      format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("===== Audit Logging System Examples =====\n")
    
    # Run demonstrations
    demonstrate_audit_logging()
    print("\n")
    
    demonstrate_compliance_reporting()
    print("\n")
    
    demonstrate_intrusion_detection()
    print("\n")
    
    print("All examples completed. Check the logs/ and reports/ directories for output.")


if __name__ == "__main__":
    main()