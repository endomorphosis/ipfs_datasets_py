"""
Example of comprehensive audit visualization using interactive components.

This example demonstrates how to create interactive visualizations of audit events,
showing trends over time and correlations between different types of audit events.
"""

import os
import sys
import json
import time
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, 
                  format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Import audit logging components
from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)
from ipfs_datasets_py.audit.handlers import (
    FileAuditHandler, JSONAuditHandler, SyslogAuditHandler, 
    ElasticsearchAuditHandler, AlertingAuditHandler
)
from ipfs_datasets_py.audit.integration import (
    AuditProvenanceIntegrator, AuditDatasetIntegrator,
    AuditContextManager, audit_function
)
from ipfs_datasets_py.audit.compliance import (
    ComplianceStandard, ComplianceReport, GDPRComplianceReporter
)
from ipfs_datasets_py.audit.intrusion import (
    IntrusionDetection, SecurityAlert, SecurityAlertManager
)

# Try to import data provenance components
try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, ProvenanceContext,
        SourceRecord, TransformationRecord
    )
    PROVENANCE_AVAILABLE = True
except ImportError:
    PROVENANCE_AVAILABLE = False
    logging.warning("Data provenance module not available. Some examples will be skipped.")


def setup_audit_logging():
    """Set up comprehensive audit logging with multiple handlers."""
    # Get the global audit logger instance
    audit_logger = AuditLogger.get_instance()
    
    # Configure general settings
    audit_logger.min_level = AuditLevel.INFO
    audit_logger.default_application = "ipfs_datasets_example"
    
    # Create output directories
    os.makedirs("logs", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    
    # Add a basic file handler
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
    
    # Add handler for security-specific events
    security_handler = JSONAuditHandler(
        name="security",
        file_path="logs/security.json",
        min_level=AuditLevel.WARNING,
        pretty=False
    )
    audit_logger.add_handler(security_handler)
    
    # Add syslog handler if available
    try:
        syslog_handler = SyslogAuditHandler(
            name="syslog",
            min_level=AuditLevel.NOTICE,
            identity="ipfs_datasets_audit"
        )
        audit_logger.add_handler(syslog_handler)
        logging.info("Added syslog handler")
    except Exception as e:
        logging.warning(f"Could not add syslog handler: {str(e)}")
    
    # Add Elasticsearch handler if available
    try:
        from elasticsearch import Elasticsearch
        es_handler = ElasticsearchAuditHandler(
            name="elasticsearch",
            hosts=["localhost:9200"],
            index_pattern="audit-logs-{date}",
            min_level=AuditLevel.INFO,
            bulk_size=100
        )
        audit_logger.add_handler(es_handler)
        logging.info("Added Elasticsearch handler")
    except Exception as e:
        logging.warning(f"Could not add Elasticsearch handler: {str(e)}")
    
    # Add an alerting handler for high-severity events
    alerting_handler = AlertingAuditHandler(
        name="alerting",
        min_level=AuditLevel.WARNING,
        alert_handlers=[lambda event: print(f"ALERT: {event.level} - {event.category}: {event.action}")],
        rate_limit_seconds=60
    )
    audit_logger.add_handler(alerting_handler)
    
    return audit_logger


def demonstrate_basic_audit_logging():
    """Demonstrate basic audit logging capabilities."""
    # Get the audit logger
    audit_logger = AuditLogger.get_instance()
    
    # Set thread-local context for this section
    audit_logger.set_context(user="example_user", session_id="session123", client_ip="192.168.1.2")
    
    logging.info("Demonstrating basic audit logging...")
    
    # Log authentication events
    audit_logger.auth("login", status="success", 
                   details={"method": "password", "mfa_used": True})
    
    # Log data access events
    audit_logger.data_access("read", 
                          resource_id="dataset123", 
                          resource_type="dataset",
                          details={"format": "parquet", "rows_accessed": 1000})
    
    # Log data modification events
    audit_logger.data_modify("update",
                          resource_id="dataset123",
                          resource_type="dataset",
                          details={"changes": {"added_column": "new_feature"}})
    
    # Log configuration change
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
    
    # Log security event
    audit_logger.security("permission_change",
                       level=AuditLevel.WARNING,
                       resource_id="role123",
                       resource_type="role",
                       details={
                           "target_user": "jane_doe",
                           "permissions_added": ["admin"],
                           "permissions_removed": []
                       })
    
    # Log error event
    audit_logger.error(
        category=AuditCategory.SYSTEM,
        action="process_failure",
        details={
            "process": "data_import",
            "error": "Database connection timeout",
            "retry_count": 3
        }
    )
    
    # Clear context when done
    audit_logger.clear_context()
    
    logging.info("Basic audit logging complete")


def demonstrate_dataset_audit_integration():
    """Demonstrate integration with dataset operations."""
    # Create the dataset integrator
    dataset_integrator = AuditDatasetIntegrator()
    
    logging.info("Demonstrating dataset audit integration...")
    
    # Record dataset loading
    dataset_integrator.record_dataset_load(
        dataset_name="wikipedia-sample",
        dataset_id="wiki123",
        source="huggingface",
        user="researcher"
    )
    
    # Record dataset transformation
    dataset_integrator.record_dataset_transform(
        input_dataset="wiki123",
        output_dataset="wiki123-processed",
        transformation_type="text_extraction",
        parameters={"tokenizer": "bert-base-uncased", "max_length": 512},
        user="researcher"
    )
    
    # Record dataset query
    dataset_integrator.record_dataset_query(
        dataset_name="wiki123-processed",
        query="SELECT * FROM dataset WHERE topic = 'science'",
        query_type="sql",
        user="researcher"
    )
    
    # Record dataset saving
    dataset_integrator.record_dataset_save(
        dataset_name="wiki123-processed",
        dataset_id="wiki123-processed",
        destination="ipfs",
        format="car",
        user="researcher"
    )
    
    logging.info("Dataset audit integration complete")


def demonstrate_context_manager():
    """Demonstrate the audit context manager for operations."""
    logging.info("Demonstrating audit context manager...")
    
    # Example operation with audit context
    with AuditContextManager(
        category=AuditCategory.DATA_MODIFICATION,
        action="process_dataset",
        resource_id="dataset123",
        resource_type="dataset",
        details={"algorithm": "tokenization", "batch_size": 1000}
    ) as audit_ctx:
        # Perform the operation
        logging.info("Processing dataset...")
        time.sleep(1)  # Simulate processing
    
    # Example with error handling
    try:
        with AuditContextManager(
            category=AuditCategory.DATA_ACCESS,
            action="export_dataset",
            resource_id="dataset456",
            resource_type="dataset",
            level=AuditLevel.WARNING
        ):
            # Simulate an error
            logging.info("Exporting dataset (will fail)...")
            time.sleep(0.5)
            raise ValueError("Simulated export error")
    except ValueError:
        # Error is logged automatically by the context manager
        pass
    
    logging.info("Context manager demonstration complete")


@audit_function(
    category=AuditCategory.DATA_ACCESS,
    action="retrieve_vector",
    resource_id_arg="vector_id",
    resource_type="vector_embedding"
)
def retrieve_vector(vector_id, include_metadata=True):
    """Example function decorated with audit logging."""
    logging.info(f"Retrieving vector {vector_id}...")
    time.sleep(0.2)  # Simulate retrieval
    return {"id": vector_id, "vector": [0.1, 0.2, 0.3], "metadata": {"source": "example"}}


def demonstrate_decorator():
    """Demonstrate the audit function decorator."""
    logging.info("Demonstrating audit function decorator...")
    
    # Call the decorated function
    vector = retrieve_vector("vec123")
    
    # Call again with different parameters
    vector = retrieve_vector("vec456", include_metadata=False)
    
    logging.info("Decorator demonstration complete")


def demonstrate_provenance_integration():
    """Demonstrate integration with data provenance."""
    if not PROVENANCE_AVAILABLE:
        logging.warning("Skipping provenance integration demo: module not available")
        return
    
    logging.info("Demonstrating provenance integration...")
    
    # Initialize provenance manager
    provenance_manager = EnhancedProvenanceManager()
    
    # Initialize audit-provenance integrator
    integrator = AuditProvenanceIntegrator(provenance_manager=provenance_manager)
    
    # Create a provenance record
    with ProvenanceContext(provenance_manager):
        source_id = provenance_manager.record_source(
            source_id="wikipedia",
            source_type="dataset",
            source_uri="huggingface:wikipedia/20220301.en"
        )
        
        # Generate an audit event from the provenance record
        source_record = provenance_manager.get_record(source_id)
        audit_event_id = integrator.audit_from_provenance_record(source_record)
        
        # Create a transformation record
        transform_id = provenance_manager.record_transformation(
            input_ids=[source_id],
            output_id="wikipedia-processed",
            transformation_type="tokenization",
            parameters={"model": "bert-base-uncased"}
        )
        
        # Generate an audit event from the transformation record
        transform_record = provenance_manager.get_record(transform_id)
        audit_event_id = integrator.audit_from_provenance_record(transform_record)
        
        # Link the records
        integrator.link_audit_to_provenance(audit_event_id, transform_id)
    
    logging.info("Provenance integration complete")


def demonstrate_compliance_reporting(historic_events=None):
    """Demonstrate compliance reporting capabilities."""
    logging.info("Demonstrating compliance reporting...")
    
    # Create a GDPR compliance reporter
    reporter = GDPRComplianceReporter()
    
    # In a real scenario, we would load historical events
    # For demonstration, we'll create some test events
    events = historic_events or []
    
    # Generate placeholder events if none provided
    if not events:
        # Create a few representative events
        events = [
            AuditEvent(
                event_id="evt1",
                timestamp=(datetime.now() - timedelta(days=5)).isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_ACCESS,
                action="read",
                user="user123",
                resource_id="personal_data",
                resource_type="user_data",
                details={"purpose": "customer_support", "legal_basis": "legitimate_interest"}
            ),
            AuditEvent(
                event_id="evt2",
                timestamp=(datetime.now() - timedelta(days=3)).isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.SECURITY,
                action="encryption_check",
                resource_id="database",
                resource_type="storage",
                details={"encryption_status": "enabled", "algorithm": "AES-256"}
            ),
            AuditEvent(
                event_id="evt3",
                timestamp=(datetime.now() - timedelta(days=1)).isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_ACCESS,
                action="subject_access_request",
                user="admin",
                resource_id="user456",
                resource_type="user_data",
                details={"request_id": "sar123", "fulfilled": True}
            )
        ]
    
    # Generate a compliance report
    report = reporter.generate_report(events)
    
    # Save report in various formats
    report.save_json("reports/gdpr_compliance.json")
    report.save_csv("reports/gdpr_compliance.csv")
    report.save_html("reports/gdpr_compliance.html")
    
    logging.info("Compliance report generated")
    logging.info(f"Compliance rate: {report.summary['compliance_rate']}%")
    logging.info(f"Generated files: reports/gdpr_compliance.*")


def demonstrate_intrusion_detection():
    """Demonstrate intrusion detection capabilities."""
    logging.info("Demonstrating intrusion detection...")
    
    # Set up intrusion detection
    ids = IntrusionDetection()
    alert_manager = SecurityAlertManager(alert_storage_path="logs/alerts.json")
    
    # Add a simple console alert handler
    def alert_handler(alert):
        print(f"SECURITY ALERT: {alert.level.upper()} - {alert.description}")
    
    alert_manager.add_notification_handler(alert_handler)
    
    # Connect the IDS to the alert manager
    ids.add_alert_handler(alert_manager.add_alert)
    
    # Generate test events
    audit_logger = AuditLogger.get_instance()
    test_events = []
    
    # Simulate brute force login attempts
    for i in range(6):
        event = AuditEvent(
            event_id=f"login-fail-{i}",
            timestamp=datetime.now().isoformat(),
            level=AuditLevel.WARNING,
            category=AuditCategory.AUTHENTICATION,
            action="login",
            user="attacker",
            client_ip="192.168.1.100",
            status="failure",
            details={"reason": "invalid_password", "attempt": i+1}
        )
        test_events.append(event)
    
    # Simulate multiple access denials
    for i in range(4):
        event = AuditEvent(
            event_id=f"access-deny-{i}",
            timestamp=datetime.now().isoformat(),
            level=AuditLevel.WARNING,
            category=AuditCategory.AUTHORIZATION,
            action="access_denied",
            user="suspicious_user",
            resource_id=f"sensitive_resource_{i}",
            resource_type="financial_data",
            details={"reason": "insufficient_permissions"}
        )
        test_events.append(event)
    
    # Simulate privilege escalation
    event = AuditEvent(
        event_id="priv-escalation",
        timestamp=datetime.now().isoformat(),
        level=AuditLevel.ERROR,
        category=AuditCategory.SECURITY,
        action="permission_change",
        user="malicious_admin",
        resource_id="user_role",
        resource_type="role",
        details={
            "target_user": "compromised_account",
            "permissions_added": ["admin", "system"],
            "permissions_removed": [],
            "justification": "emergency access"
        }
    )
    test_events.append(event)
    
    # Process events through intrusion detection
    alerts = ids.process_events(test_events)
    
    logging.info(f"Generated {len(alerts)} security alerts")
    logging.info("Alerts saved to logs/alerts.json")


def demonstrate_advanced_usage():
    """Demonstrate advanced audit logging usage scenarios."""
    audit_logger = AuditLogger.get_instance()
    
    logging.info("Demonstrating advanced audit logging usage...")
    
    # 1. Dynamic audit level based on operation sensitivity
    def get_audit_level(resource_type, operation):
        if resource_type in ["financial_data", "personal_data", "credentials"]:
            return AuditLevel.NOTICE  # Higher visibility for sensitive data
        if operation in ["delete", "update_permissions", "encrypt"]:
            return AuditLevel.NOTICE  # Higher visibility for sensitive operations
        return AuditLevel.INFO
    
    # Example usage
    resource_type = "financial_data"
    operation = "read"
    audit_level = get_audit_level(resource_type, operation)
    
    audit_logger.log(
        level=audit_level,
        category=AuditCategory.DATA_ACCESS,
        action=operation,
        resource_id="financial_report_q2",
        resource_type=resource_type,
        details={"reason": "quarterly_review"}
    )
    
    # 2. Transaction-like audit logging
    audit_logger.set_context(user="transaction_user", session_id="batch_process_123")
    
    # Start transaction
    tx_id = audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.OPERATIONAL,
        action="transaction_start",
        details={"transaction_type": "batch_processing"}
    )
    
    # Individual operations within transaction
    for i in range(3):
        audit_logger.log(
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_MODIFICATION,
            action="process_item",
            resource_id=f"item_{i}",
            resource_type="data_item",
            details={"transaction_id": tx_id, "sequence": i}
        )
    
    # End transaction
    audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.OPERATIONAL,
        action="transaction_end",
        details={"transaction_id": tx_id, "items_processed": 3, "status": "complete"}
    )
    
    audit_logger.clear_context()
    
    # 3. Capturing distributed system events
    audit_logger.log(
        level=AuditLevel.INFO,
        category=AuditCategory.SYSTEM,
        action="node_communication",
        details={
            "source_node": "worker-1",
            "target_node": "worker-2",
            "message_type": "data_transfer",
            "correlation_id": "corr-123456",
            "data_size_bytes": 1024 * 1024 * 5  # 5MB
        }
    )
    
    logging.info("Advanced usage demonstration complete")


def main():
    """Main function demonstrating comprehensive audit logging."""
    print("===== Comprehensive Audit Logging Demonstration =====\n")
    
    # Step 1: Set up audit logging with multiple handlers
    setup_audit_logging()
    
    # Step 2: Basic audit logging
    demonstrate_basic_audit_logging()
    print("")
    
    # Step 3: Dataset integration
    demonstrate_dataset_audit_integration()
    print("")
    
    # Step 4: Context manager
    demonstrate_context_manager()
    print("")
    
    # Step 5: Function decorator
    demonstrate_decorator()
    print("")
    
    # Step 6: Provenance integration (if available)
    if PROVENANCE_AVAILABLE:
        demonstrate_provenance_integration()
        print("")
    
    # Step 7: Compliance reporting
    demonstrate_compliance_reporting()
    print("")
    
    # Step 8: Intrusion detection
    demonstrate_intrusion_detection()
    print("")
    
    # Step 9: Advanced usage
    demonstrate_advanced_usage()
    print("")
    
    print("===== Audit Logging Demonstration Complete =====")
    print("All logs and reports have been written to the logs/ and reports/ directories.")


if __name__ == "__main__":
    main()