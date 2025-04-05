#!/usr/bin/env python3
"""
Audit Reporting Example

This example demonstrates how to use the audit reporting capabilities
to generate comprehensive audit reports with security, compliance, and
operational insights.
"""

import os
import sys
import datetime
import time

# Add parent directory to path if running from examples
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)
from ipfs_datasets_py.audit.audit_visualization import (
    AuditMetricsAggregator, AuditVisualizer, setup_audit_visualization
)
from ipfs_datasets_py.audit.audit_reporting import (
    setup_audit_reporting, generate_comprehensive_audit_report
)


def generate_sample_audit_events(audit_logger: AuditLogger, count: int = 100):
    """Generate sample audit events for demonstration."""
    categories = [AuditCategory.AUTHENTICATION, 
                 AuditCategory.DATA_ACCESS, 
                 AuditCategory.SECURITY,
                 AuditCategory.SYSTEM,
                 AuditCategory.DATA_MODIFICATION]
    
    levels = [AuditLevel.INFO, AuditLevel.INFO, AuditLevel.INFO,  # More common
             AuditLevel.WARNING, AuditLevel.WARNING,
             AuditLevel.ERROR, 
             AuditLevel.CRITICAL]  # Less common
    
    actions = ["read", "write", "update", "delete", "login", "logout", 
              "query", "configure", "backup", "restore"]
    
    users = ["user1", "user2", "admin", "system", None]
    
    resources = ["dataset1", "dataset2", "model1", "index1", "config", None]
    
    # Generate events
    for i in range(count):
        level = levels[i % len(levels)]
        category = categories[i % len(categories)]
        action = actions[i % len(actions)]
        user = users[i % len(users)]
        resource_id = resources[i % len(resources)]
        
        # Some status failures based on level
        status = "success" if level == AuditLevel.INFO else (
            "failure" if level in [AuditLevel.ERROR, AuditLevel.CRITICAL] else 
            "success" if i % 3 == 0 else "failure"
        )
        
        # Create event
        event = AuditEvent(
            event_id=f"test-{i}",
            timestamp=datetime.datetime.now().isoformat(),
            level=level,
            category=category,
            action=action,
            user=user,
            resource_id=resource_id,
            resource_type="dataset" if resource_id and "dataset" in resource_id else (
                "model" if resource_id and "model" in resource_id else
                "index" if resource_id and "index" in resource_id else
                "system" if resource_id and "config" in resource_id else None
            ),
            status=status,
            details={
                "source_ip": f"192.168.1.{i % 255}" if user else None,
                "duration_ms": i * 10 if action in ["read", "query"] else i * 50
            }
        )
        
        # Log event
        audit_logger.log_event(event)
        
    # Add some compliance-related events
    audit_logger.log_event(AuditEvent(
        event_id="compliance-1",
        timestamp=datetime.datetime.now().isoformat(),
        level=AuditLevel.WARNING,
        category=AuditCategory.COMPLIANCE,
        action="gdpr_check",
        status="failure",
        details={"requirement": "data_access_logging", "violation": "Missing user tracking"}
    ))
    
    # Add some security alerts
    audit_logger.log_event(AuditEvent(
        event_id="security-1",
        timestamp=datetime.datetime.now().isoformat(),
        level=AuditLevel.CRITICAL,
        category=AuditCategory.SECURITY,
        action="intrusion_detection",
        status="failure",
        details={"alert": "Multiple failed login attempts", "source_ip": "10.0.0.5"}
    ))
    
    # Add some login failures for pattern detection
    for i in range(10):
        audit_logger.log_event(AuditEvent(
            event_id=f"auth-fail-{i}",
            timestamp=datetime.datetime.now().isoformat(),
            level=AuditLevel.WARNING,
            category=AuditCategory.AUTHENTICATION,
            action="login",
            user="target_user",
            status="failure",
            details={"source_ip": "10.0.0.5", "reason": "Invalid password"}
        ))


def main():
    """Run the audit reporting example."""
    print("Audit Reporting Example")
    print("======================\n")
    
    # Set up audit logger
    audit_logger = AuditLogger.get_instance()
    
    # Generate sample audit events
    print("Generating sample audit events...")
    generate_sample_audit_events(audit_logger, count=100)
    print("Generated 100 sample audit events plus special test cases\n")
    
    # Set up visualization and metrics collection
    metrics_aggregator, visualizer, _ = setup_audit_visualization(audit_logger)
    
    # Process the events to populate metrics
    print("Collecting metrics from audit events...")
    # Normally this would happen automatically as events are logged,
    # but for this example, we manually trigger metric collection
    # by calling process_event on some new events
    audit_logger.log_event(AuditEvent(
        event_id="metric-trigger",
        timestamp=datetime.datetime.now().isoformat(),
        level=AuditLevel.INFO,
        category=AuditCategory.SYSTEM,
        action="metric_collection"
    ))
    time.sleep(1)  # Give time for metrics collection to happen
    print("Metrics collection complete\n")
    
    # Set up the reporting system
    print("Setting up audit reporting system...")
    report_generator, pattern_detector, compliance_analyzer = setup_audit_reporting(
        audit_logger=audit_logger,
        metrics_aggregator=metrics_aggregator,
        visualizer=visualizer
    )
    print("Audit reporting system ready\n")
    
    # Generate various report types
    reports_dir = os.path.join(os.path.dirname(__file__), "../audit_reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Security report
    print("Generating security report...")
    security_report = report_generator.generate_security_report()
    security_report_path = report_generator.export_report(
        report=security_report,
        format='json',
        output_file=os.path.join(reports_dir, "security_report.json")
    )
    print(f"Security report generated: {security_report_path}")
    
    # Comprehensive report
    print("\nGenerating comprehensive HTML report...")
    html_report_path = generate_comprehensive_audit_report(
        output_file=os.path.join(reports_dir, "comprehensive_report.html"),
        audit_logger=audit_logger,
        metrics_aggregator=metrics_aggregator,
        report_format='html'
    )
    print(f"Comprehensive report generated: {html_report_path}")
    print(f"\nOpen {html_report_path} in a web browser to view the full report.")


if __name__ == "__main__":
    main()