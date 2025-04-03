# Security, Audit Logging and Compliance Tutorial

This tutorial demonstrates how to use IPFS Datasets' security features, audit logging, and compliance reporting to secure sensitive data and meet regulatory requirements.

## 1. Basic Security Setup

First, let's set up basic security for our application:

```python
from ipfs_datasets_py.security import SecurityManager, SecurityConfig

# Initialize security manager with basic configuration
security = SecurityManager.initialize(SecurityConfig(
    enable_encryption=True,
    require_authentication=True,
    track_provenance=True,
    audit_log_path="logs/audit.log"
))

# Create admin user
admin_id = security.create_user(
    username="admin",
    password="secure_admin_password",
    access_level="admin"
)

# Create regular user
user_id = security.create_user(
    username="data_scientist",
    password="secure_user_password",
    access_level="read"
)

# Authenticate user
token = security.authenticate("data_scientist", "secure_user_password")
if token:
    print("Authentication successful!")
    print(f"User token: {token}")
else:
    print("Authentication failed!")
```

## 2. Setting Up Audit Logging

Next, let's configure comprehensive audit logging:

```python
from ipfs_datasets_py.audit import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.audit import FileAuditHandler, JSONAuditHandler

# Get the global audit logger
audit_logger = AuditLogger.get_instance()

# Create logs directory
import os
os.makedirs("logs", exist_ok=True)

# Configure file handler for human-readable logs
file_handler = FileAuditHandler(
    name="file",
    file_path="logs/audit.log",
    min_level=AuditLevel.INFO,
    rotate_size_mb=10
)
audit_logger.add_handler(file_handler)

# Configure JSON handler for machine-readable logs
json_handler = JSONAuditHandler(
    name="json",
    file_path="logs/audit.json",
    min_level=AuditLevel.INFO
)
audit_logger.add_handler(json_handler)

# Log authentication event
audit_logger.auth("login", 
                user="data_scientist", 
                status="success",
                details={"ip": "192.168.1.100"})

# Set context for subsequent operations
audit_logger.set_context(user="data_scientist", session_id="session123")
```

## 3. Working with Encrypted Data

Now, let's work with encrypted data:

```python
# Create encryption key
key_id = security.create_encryption_key("sensitive_data_key")
print(f"Created encryption key: {key_id}")

# Encrypt some sensitive data
sensitive_data = "PATIENT_DATA: John Doe, DOB: 1980-01-01, Diagnosis: Hypertension"
encrypted_data = security.encrypt_data(sensitive_data.encode(), key_id)

# Log data access event
audit_logger.data_access(
    "encrypt", 
    resource_id=key_id,
    resource_type="encryption_key",
    details={"operation": "encrypt", "data_type": "patient_records"}
)

# Store encrypted data
with open("encrypted_patient_data.bin", "wb") as f:
    f.write(encrypted_data)

# Later, decrypt the data
with open("encrypted_patient_data.bin", "rb") as f:
    encrypted_content = f.read()

# Verify access permission
if security.check_access(key_id, "read"):
    decrypted_data = security.decrypt_data(encrypted_content, key_id)
    decrypted_text = decrypted_data.decode()
    print(f"Decrypted data: {decrypted_text}")
    
    # Log data access
    audit_logger.data_access(
        "decrypt", 
        resource_id=key_id,
        resource_type="encryption_key",
        details={"operation": "decrypt", "data_type": "patient_records"}
    )
else:
    print("Access denied to encryption key")
    
    # Log access denied
    audit_logger.authz(
        "access_denied", 
        level=AuditLevel.WARNING,
        resource_id=key_id,
        resource_type="encryption_key",
        details={"reason": "insufficient_permissions"}
    )
```

## 4. Resource Access Control

Let's set up access control for a dataset:

```python
# Create a resource policy
dataset_policy = security.create_resource_policy(
    resource_id="patient_dataset",
    resource_type="dataset",
    owner="admin"
)

# Grant access to user
security.update_resource_policy(
    resource_id="patient_dataset",
    updates={
        "read_access": ["admin", "data_scientist"],
        "write_access": ["admin"]
    }
)

# Check access (as data_scientist)
if security.check_access("patient_dataset", "read"):
    print("User has read access to patient_dataset")
    
    # Log successful access
    audit_logger.authz(
        "access_granted", 
        resource_id="patient_dataset",
        resource_type="dataset",
        details={"access_type": "read"}
    )
    
    # Simulate dataset access
    audit_logger.data_access(
        "read", 
        resource_id="patient_dataset",
        resource_type="dataset",
        details={"records_accessed": 100}
    )
else:
    print("User does not have read access to patient_dataset")
    
    # Log access denied
    audit_logger.authz(
        "access_denied", 
        level=AuditLevel.WARNING,
        resource_id="patient_dataset",
        resource_type="dataset",
        details={"access_type": "read", "reason": "insufficient_permissions"}
    )
    
# Try write access (which should be denied for data_scientist)
if security.check_access("patient_dataset", "write"):
    print("User has write access to patient_dataset")
else:
    print("User does not have write access to patient_dataset")
    
    # Log access denied
    audit_logger.authz(
        "access_denied", 
        level=AuditLevel.WARNING,
        resource_id="patient_dataset",
        resource_type="dataset",
        details={"access_type": "write", "reason": "insufficient_permissions"}
    )
```

## 5. Enhanced Data Provenance and Lineage for Compliance

Track comprehensive data provenance and lineage for regulatory compliance with detailed tracking across domains:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker
from ipfs_datasets_py.security import SecurityManager
import datetime

# Initialize components
security_manager = SecurityManager.get_instance()
provenance_manager = EnhancedProvenanceManager(
    storage_path="provenance_data",
    enable_ipld_storage=True,
    enable_crypto_verification=True,
    default_agent_id="compliance_officer"
)

# Initialize the enhanced lineage tracker with security integration
lineage_tracker = EnhancedLineageTracker(
    config={
        "enable_audit_integration": True,
        "enable_temporal_consistency": True,
        "enable_ipld_storage": True,
        "security_manager": security_manager,
        "domain_validation_level": "strict"
    }
)

# Create domains for organizing lineage data
healthcare_domain = lineage_tracker.create_domain(
    name="HealthcareSystem",
    description="Protected healthcare data system",
    domain_type="business",
    attributes={
        "organization": "Hospital System",
        "compliance_frameworks": ["HIPAA", "GDPR"],
        "data_owner": "medical_records_department",
        "classification": "restricted"
    },
    metadata_schema={
        "required": ["retention_period", "classification", "consent_level"],
        "properties": {
            "retention_period": {"type": "string"},
            "classification": {"enum": ["public", "internal", "confidential", "restricted"]},
            "consent_level": {"enum": ["none", "basic", "research", "full"]}
        }
    }
)

analytics_domain = lineage_tracker.create_domain(
    name="AnalyticsSystem",
    description="Healthcare analytics platform",
    domain_type="business",
    attributes={
        "organization": "Research Department",
        "compliance_frameworks": ["HIPAA", "GDPR"],
        "data_owner": "data_science_team",
        "classification": "confidential"
    }
)

# Create boundary with HIPAA compliance constraints
healthcare_to_analytics = lineage_tracker.create_domain_boundary(
    source_domain_id=healthcare_domain,
    target_domain_id=analytics_domain,
    boundary_type="data_transfer",
    attributes={
        "encryption": "AES-256",
        "access_control": "role_based",
        "data_masking": "enabled",
        "deidentification": "required",
        "requires_approval": True,
        "compliance_verified": True
    },
    constraints=[
        {"type": "field_level", "fields": ["patient_name", "ssn", "mrn"], "action": "mask"},
        {"type": "field_level", "fields": ["date_of_birth"], "action": "generalize"},
        {"type": "approval", "approvers": ["compliance_officer", "privacy_officer"]}
    ]
)

# Record initial data source in provenance system
with audit_logger.audit_context(
    category=AuditCategory.DATA_ACCESS,
    operation="import",
    subject="patient_records",
    status="success",
    details={"source": "hospital_system", "record_count": 5000}
):
    source_id = provenance_manager.record_source(
        data_id="patient_dataset",
        source_type="database",
        source_uri="hospital://records/patient_data",
        description="Protected patient health records",
        format="parquet",
        size=1024 * 1024 * 50,  # 50MB
        hash="sha256:a1b2c3...",
        metadata={
            "hipaa_compliant": True,
            "contains_phi": True,
            "consent_obtained": True,
            "document_id": "patient_records_2023"
        }
    )

    # Create corresponding node in lineage tracker
    patient_data_node = lineage_tracker.create_node(
        node_type="dataset",
        metadata={
            "name": "Patient Health Records",
            "format": "parquet",
            "record_count": 5000,
            "retention_period": "7 years",
            "classification": "restricted",
            "consent_level": "research",
            "contains_phi": True,
            "security_controls": {
                "encryption": "field-level",
                "access_restriction": "need-to-know",
                "masking_rules": ["patient_name", "ssn", "mrn"]
            },
            "provenance_record_id": source_id  # Link to provenance record
        },
        domain_id=healthcare_domain,
        entity_id="patient_dataset_2023"
    )

# Record deidentification transformation
with audit_logger.audit_context(
    category=AuditCategory.DATA_TRANSFORMATION,
    operation="deidentify",
    subject="patient_dataset",
    object="deidentified_dataset",
    status="success",
    details={
        "method": "HIPAA Safe Harbor",
        "fields_affected": ["patient_name", "mrn", "ssn", "date_of_birth", "zip"]
    }
):
    # Record in provenance system
    transform_id = provenance_manager.record_transformation(
        input_ids=["patient_dataset"],
        output_id="deidentified_dataset",
        transformation_type="deidentification",
        tool="privacy_toolkit",
        parameters={
            "method": "HIPAA Safe Harbor",
            "k_anonymity": 5,
            "fields_to_mask": ["patient_name", "mrn", "ssn"],
            "fields_to_generalize": ["date_of_birth", "zip"]
        },
        description="Deidentify patient data using HIPAA Safe Harbor method",
        metadata={
            "hipaa_compliant": True,
            "verification_status": "verified",
            "verifier": "privacy_officer",
            "document_id": "patient_deidentification_2023"
        }
    )
    
    # Create transformation node in lineage tracker
    deidentify_node = lineage_tracker.create_node(
        node_type="transformation",
        metadata={
            "name": "Patient Data Deidentification",
            "tool": "privacy_toolkit",
            "version": "2.3.1",
            "method": "HIPAA Safe Harbor",
            "execution_time": "32m",
            "executor": "privacy_officer",
            "execution_id": "job-45678",
            "execution_date": datetime.datetime.now().isoformat(),
            "security_context": {
                "authentication": "mfa",
                "authorization": "role_based",
                "security_clearance": "confidential",
                "compliance_verified": True,
                "verification_date": datetime.datetime.now().isoformat(),
                "verifier": "compliance_officer"
            },
            "provenance_record_id": transform_id  # Link to provenance record
        },
        domain_id=healthcare_domain,
        entity_id="deidentify_transform_2023"
    )
    
    # Record detailed transformation information
    lineage_tracker.record_transformation_details(
        transformation_id=deidentify_node,
        operation_type="deidentification",
        inputs=[
            {"field": "patient_name", "type": "string", "sensitivity": "high", "phi": True},
            {"field": "mrn", "type": "string", "sensitivity": "high", "phi": True},
            {"field": "ssn", "type": "string", "sensitivity": "high", "phi": True},
            {"field": "date_of_birth", "type": "date", "sensitivity": "high", "phi": True},
            {"field": "zip", "type": "string", "sensitivity": "medium", "phi": True},
            {"field": "diagnosis", "type": "string", "sensitivity": "high", "phi": True},
            {"field": "medications", "type": "array", "sensitivity": "high", "phi": True}
        ],
        outputs=[
            {"field": "id", "type": "string", "sensitivity": "low", "phi": False, "anonymized": True},
            {"field": "birth_year", "type": "integer", "sensitivity": "low", "phi": False, "generalized": True},
            {"field": "zip3", "type": "string", "sensitivity": "low", "phi": False, "generalized": True},
            {"field": "diagnosis", "type": "string", "sensitivity": "high", "phi": True},
            {"field": "medications", "type": "array", "sensitivity": "high", "phi": True}
        ],
        parameters={
            "deidentification_method": "HIPAA Safe Harbor",
            "k_anonymity": 5,
            "suppression_threshold": 0.05,
            "generalization_hierarchy": {
                "date_of_birth": "date→month/year→year",
                "zip": "5-digit→3-digit→state"
            }
        },
        impact_level="field"
    )
    
    # Create link between nodes
    lineage_tracker.create_link(
        source_id=patient_data_node,
        target_id=deidentify_node,
        relationship_type="input_to",
        metadata={
            "timestamp": datetime.datetime.now().isoformat(),
            "compliance_context": {
                "hipaa_compliant": True,
                "gdpr_compliant": True,
                "verified_by": "compliance_officer"
            }
        },
        confidence=1.0
    )
    
    # Create deidentified data node
    deidentified_data_node = lineage_tracker.create_node(
        node_type="dataset",
        metadata={
            "name": "Deidentified Patient Data",
            "format": "parquet",
            "record_count": 5000,
            "retention_period": "5 years",
            "classification": "confidential",
            "consent_level": "research",
            "contains_phi": False,
            "deidentification_method": "HIPAA Safe Harbor",
            "security_controls": {
                "encryption": "transport-only",
                "access_restriction": "department-level"
            }
        },
        domain_id=analytics_domain,
        entity_id="deidentified_dataset_2023"
    )
    
    # Create link to deidentified data
    lineage_tracker.create_link(
        source_id=deidentify_node,
        target_id=deidentified_data_node,
        relationship_type="output_from",
        metadata={
            "timestamp": datetime.datetime.now().isoformat(),
            "quality_score": 1.0,
            "compliance_verified": True
        },
        confidence=1.0,
        cross_domain=True  # This crosses domain boundaries
    )

# Generate comprehensive compliance report with detailed lineage
compliance_report = lineage_tracker.generate_provenance_report(
    entity_id="deidentified_dataset_2023",
    include_visualization=True,
    include_transformation_details=True,
    include_security_context=True,
    include_audit_trail=True,
    format="html"
)

# Export lineage to IPLD for secure, tamper-proof storage
root_cid = lineage_tracker.export_to_ipld(
    include_domains=True,
    include_boundaries=True,
    include_versions=True,
    include_transformation_details=True,
    encrypt_sensitive_data=True
)
print(f"Exported compliant data lineage to IPLD with root CID: {root_cid}")

# Get full provenance and lineage information for audit
provenance_info = provenance_manager.get_record("deidentified_dataset")
lineage_info = lineage_tracker.get_entity_lineage("deidentified_dataset_2023")

# Verify temporal consistency of data flows
inconsistencies = lineage_tracker.validate_temporal_consistency()
if inconsistencies:
    print(f"COMPLIANCE ISSUE: Found {len(inconsistencies)} temporal inconsistencies")
    for issue in inconsistencies:
        audit_logger.log_event(
            level=AuditLevel.WARNING,
            category=AuditCategory.COMPLIANCE,
            operation="validate",
            subject=issue["source_id"],
            object=issue["target_id"],
            status="failed",
            details={"issue": "temporal_inconsistency", "description": issue["description"]}
        )
else:
    print("COMPLIANCE: All data flows have proper temporal consistency")
```

## 6. Generating Compliance Reports

Use the compliance reporting features to generate regulatory reports:

```python
import datetime
from ipfs_datasets_py.audit import GDPRComplianceReporter, HIPAAComplianceReporter

# Create reporters
gdpr_reporter = GDPRComplianceReporter()
hipaa_reporter = HIPAAComplianceReporter()

# In a real scenario, we would load historical audit events
# For this tutorial, we'll use our current events
# This would normally be loaded from the audit log file
events = [
    # Example events would be loaded here
]

# Set time period for report
start_time = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
end_time = datetime.datetime.now().isoformat()

# Generate GDPR report
gdpr_report = gdpr_reporter.generate_report(events, start_time, end_time)

# Generate HIPAA report
hipaa_report = hipaa_reporter.generate_report(events, start_time, end_time)

# Create reports directory
os.makedirs("reports", exist_ok=True)

# Save reports in different formats
gdpr_report.save_json("reports/gdpr_compliance.json")
gdpr_report.save_html("reports/gdpr_compliance.html")

hipaa_report.save_json("reports/hipaa_compliance.json")
hipaa_report.save_html("reports/hipaa_compliance.html")

# Log compliance reports generation
audit_logger.compliance(
    "report_generated",
    details={
        "report_type": "GDPR",
        "period_start": start_time,
        "period_end": end_time,
        "compliance_rate": gdpr_report.summary["compliance_rate"]
    }
)

audit_logger.compliance(
    "report_generated",
    details={
        "report_type": "HIPAA",
        "period_start": start_time,
        "period_end": end_time,
        "compliance_rate": hipaa_report.summary["compliance_rate"]
    }
)
```

## 7. Setting Up Intrusion Detection

Configure intrusion detection to automatically detect security threats:

```python
from ipfs_datasets_py.audit import IntrusionDetection, SecurityAlertManager
import time

# Create intrusion detection system
ids = IntrusionDetection()

# Create alert manager
alert_manager = SecurityAlertManager(alert_storage_path="logs/alerts.json")

# Define a simple alert handler
def handle_alert(alert):
    print(f"SECURITY ALERT: {alert.level.upper()} - {alert.description}")
    # In a real system, you might send emails, Slack messages, etc.

# Register alert handler
alert_manager.add_notification_handler(handle_alert)

# Connect IDS to alert manager
ids.add_alert_handler(alert_manager.add_alert)

# Simulate suspicious behavior (multiple failed login attempts)
suspicious_events = []
for i in range(6):  # 6 failed attempts should trigger brute force detection
    event = AuditEvent(
        event_id=f"login_fail_{i}",
        timestamp=datetime.datetime.now().isoformat(),
        level=AuditLevel.WARNING,
        category=AuditCategory.AUTHENTICATION,
        action="login",
        user="unknown_user",
        status="failure",
        client_ip="192.168.1.200",
        details={"reason": "invalid_password", "attempt": i+1}
    )
    suspicious_events.append(event)
    time.sleep(0.1)  # Small delay between events

# Process the suspicious events through IDS
alerts = ids.process_events(suspicious_events)

# Check for alerts
if alerts:
    print(f"Generated {len(alerts)} security alerts")
    for alert in alerts:
        print(f"  - {alert.type}: {alert.description}")
else:
    print("No security alerts generated")
```

## 8. Cleaning Up

Finally, let's clean up after our tutorial:

```python
# Remove encryption key (in a real system, you might want to keep it)
# security.delete_encryption_key(key_id)

# Close audit handlers
audit_logger.reset()

print("Tutorial completed. Check the 'logs' and 'reports' directories for output.")
```

## What We've Learned

In this tutorial, we've learned how to:

1. Set up basic security with authentication and authorization
2. Configure comprehensive audit logging for security events
3. Work with encrypted data and manage encryption keys
4. Implement resource access control policies
5. Track cross-document data lineage with domain-based organization
6. Implement field-level transformation tracking for compliance
7. Create secure domain boundaries with constraints
8. Validate temporal consistency of data flows
9. Link provenance and lineage with security context
10. Generate comprehensive compliance reports with visualizations
11. Export tamper-proof lineage to IPLD storage
12. Set up automated intrusion detection and alerting

These features provide the foundation for secure, compliant handling of sensitive data in IPFS Datasets applications with complete data governance capabilities and detailed cross-domain lineage tracking.

## Next Steps

To further enhance your security and compliance setup:

1. Configure Elasticsearch for scalable audit log storage and analysis
2. Implement custom audit handlers for your existing security infrastructure
3. Set up automated compliance reporting with scheduled jobs
4. Customize intrusion detection rules for your specific security requirements
5. Integrate with existing identity management systems

For more information, see the [Security and Governance documentation](../security_governance.md) and [Audit Logging documentation](../../ipfs_datasets_py/audit/README.md).