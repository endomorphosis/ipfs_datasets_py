"""
Adaptive Security Response Example

This example demonstrates how to use the adaptive security response system to
automatically respond to detected threats in the IPFS Datasets library.
"""

import os
import json
import time
from datetime import datetime, timedelta

from ipfs_datasets_py.audit.intrusion import IntrusionDetection, SecurityAlertManager
from ipfs_datasets_py.audit.adaptive_security import (
    AdaptiveSecurityManager, ResponseAction, ResponseRule, SecurityResponse, RuleCondition
)
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory


def setup_components():
    """Set up the adaptive security components."""
    # Create audit logger
    audit_logger = AuditLogger("adaptive_security_example")
    
    # Create security alert manager
    alert_manager = SecurityAlertManager(
        alert_storage_path="examples/security_alerts.json",
        audit_logger=audit_logger
    )
    
    # Create intrusion detection system
    intrusion_detection = IntrusionDetection(
        alert_manager=alert_manager,
        audit_logger=audit_logger
    )
    
    # Create adaptive security manager
    adaptive_security = AdaptiveSecurityManager(
        alert_manager=alert_manager,
        audit_logger=audit_logger,
        response_storage_path="examples/security_responses.json"
    )
    
    return audit_logger, alert_manager, intrusion_detection, adaptive_security


def create_sample_rules(adaptive_security):
    """Create sample security response rules."""
    # Rule 1: Brute force login attempts
    brute_force_rule = ResponseRule(
        rule_id="brute-force-login",
        name="Brute Force Login Protection",
        description="Responds to brute force login attempts",
        alert_type="brute_force_login",
        severity_levels=["medium", "high"],
        actions=[
            {
                "type": "LOCKOUT",
                "duration_minutes": 30,
                "account": "{{alert.source_entity}}"
            },
            {
                "type": "NOTIFY",
                "message": "Brute force login attempt detected from {{alert.source_entity}}",
                "recipients": ["security@example.com"]
            }
        ],
        conditions=[
            RuleCondition("alert.attempt_count", ">=", 5)
        ]
    )
    
    # Rule 2: Suspicious data access
    data_access_rule = ResponseRule(
        rule_id="suspicious-data-access",
        name="Suspicious Data Access Response",
        description="Responds to suspicious data access patterns",
        alert_type="suspicious_access",
        severity_levels=["medium", "high"],
        actions=[
            {
                "type": "THROTTLE",
                "duration_minutes": 60,
                "max_requests_per_minute": 10,
                "user_id": "{{alert.user_id}}"
            },
            {
                "type": "AUDIT",
                "level": "enhanced",
                "duration_hours": 24,
                "target": "{{alert.user_id}}"
            }
        ]
    )
    
    # Rule 3: Data exfiltration attempt
    exfiltration_rule = ResponseRule(
        rule_id="data-exfiltration",
        name="Data Exfiltration Response",
        description="Responds to potential data exfiltration attempts",
        alert_type="data_exfiltration",
        severity_levels=["high", "critical"],
        actions=[
            {
                "type": "RESTRICT",
                "permissions": ["download", "export"],
                "duration_hours": 48,
                "user_id": "{{alert.user_id}}"
            },
            {
                "type": "NOTIFY",
                "message": "Potential data exfiltration by {{alert.user_id}} detected",
                "recipients": ["security@example.com", "admin@example.com"]
            },
            {
                "type": "ESCALATE",
                "priority": "high",
                "assignee": "security-team"
            }
        ]
    )
    
    # Add rules to the adaptive security manager
    adaptive_security.add_rule(brute_force_rule)
    adaptive_security.add_rule(data_access_rule)
    adaptive_security.add_rule(exfiltration_rule)
    
    print(f"Added {len(adaptive_security.rules)} security response rules")


def simulate_security_alerts(alert_manager):
    """Simulate security alerts for demonstration purposes."""
    # Brute force login alert
    brute_force_alert = {
        "alert_id": f"bf-{int(time.time())}",
        "timestamp": datetime.now().isoformat(),
        "alert_type": "brute_force_login",
        "severity": "high",
        "source_entity": "192.168.1.100",
        "target_entity": "login-api",
        "attempt_count": 7,
        "time_window_minutes": 5,
        "details": {
            "failed_attempts": 7,
            "last_attempt": datetime.now().isoformat(),
            "authentication_method": "password"
        }
    }
    alert_manager.add_alert(brute_force_alert)
    print(f"Added brute force login alert: {brute_force_alert['alert_id']}")
    
    # Suspicious data access alert
    data_access_alert = {
        "alert_id": f"sa-{int(time.time())}",
        "timestamp": datetime.now().isoformat(),
        "alert_type": "suspicious_access",
        "severity": "medium",
        "user_id": "user123",
        "resource_id": "dataset-456",
        "access_pattern": "unusual_time",
        "details": {
            "typical_access_hours": "9-17",
            "access_time": "03:45:22",
            "accessed_from": "unknown_location"
        }
    }
    alert_manager.add_alert(data_access_alert)
    print(f"Added suspicious access alert: {data_access_alert['alert_id']}")
    
    # Data exfiltration alert
    exfiltration_alert = {
        "alert_id": f"ex-{int(time.time())}",
        "timestamp": datetime.now().isoformat(),
        "alert_type": "data_exfiltration",
        "severity": "critical",
        "user_id": "admin456",
        "resource_id": "confidential-dataset-789",
        "details": {
            "download_size_mb": 1250,
            "normal_usage_mb": 50,
            "destination": "external-storage",
            "files_accessed": 47
        }
    }
    alert_manager.add_alert(exfiltration_alert)
    print(f"Added data exfiltration alert: {exfiltration_alert['alert_id']}")


def demonstrate_response_lifecycle(adaptive_security):
    """Demonstrate the lifecycle of security responses."""
    # Process all pending alerts
    processed_count = adaptive_security.process_pending_alerts()
    print(f"Processed {processed_count} pending alerts")
    
    # Get active responses
    active_responses = adaptive_security.get_active_responses()
    print(f"\nActive security responses ({len(active_responses)}):")
    for resp in active_responses:
        print(f"  - {resp.response_id}: {resp.rule_name} ({resp.response_type})")
        print(f"    Target: {resp.target}")
        print(f"    Created: {resp.created_at}")
        print(f"    Expires: {resp.expires_at}")
        print(f"    Status: {resp.status}")
        print()
    
    # Manually create a response for demonstration
    manual_response = SecurityResponse(
        response_id="manual-response-001",
        alert_id="manual-alert",
        rule_id="manual-rule",
        rule_name="Manual Response Rule",
        response_type=ResponseAction.ISOLATE,
        created_at=datetime.now().isoformat(),
        expires_at=(datetime.now() + timedelta(hours=2)).isoformat(),
        status="active",
        target="dataset-999",
        parameters={
            "isolation_level": "network",
            "allow_admin_access": True,
            "reason": "Manual security response for demonstration"
        }
    )
    
    adaptive_security.add_response(manual_response)
    print(f"Added manual security response: {manual_response.response_id}")
    
    # Simulate response expiration
    print("\nSimulating response expiration check...")
    expired_count = adaptive_security.check_expired_responses()
    print(f"Found {expired_count} expired responses")


def main():
    """Run the adaptive security example."""
    print("=== Adaptive Security Response Example ===\n")
    
    # Set up components
    audit_logger, alert_manager, intrusion_detection, adaptive_security = setup_components()
    
    # Create sample rules
    create_sample_rules(adaptive_security)
    
    # Simulate security alerts
    simulate_security_alerts(alert_manager)
    
    # Demonstrate response lifecycle
    demonstrate_response_lifecycle(adaptive_security)
    
    print("\n=== Example Complete ===")


if __name__ == "__main__":
    main()