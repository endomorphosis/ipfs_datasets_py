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

## 5. Data Provenance Tracking

Track data transformations:

```python
# Record origin of a dataset
provenance = security.record_provenance(
    data_id="patient_dataset",
    source="hospital_system",
    process_steps=[],
    parent_ids=[],
    checksum="sha256:a1b2c3...",
    data_type="dataset",
    content_type="parquet"
)

# Record a transformation
filtered_provenance = security.record_provenance(
    data_id="filtered_patient_dataset",
    source="derived",
    process_steps=[{
        "operation": "filter",
        "description": "Filter patients with hypertension",
        "tool": "duckdb",
        "parameters": {"condition": "diagnosis = 'Hypertension'"}
    }],
    parent_ids=["patient_dataset"],
    checksum="sha256:d4e5f6...",
    data_type="dataset",
    content_type="parquet"
)

# Log transformation in audit log
audit_logger.data_modify(
    "transform",
    resource_id="patient_dataset",
    resource_type="dataset",
    details={
        "output_id": "filtered_patient_dataset",
        "operation": "filter",
        "condition": "diagnosis = 'Hypertension'"
    }
)

# Get provenance information
provenance_info = security.get_provenance("filtered_patient_dataset")
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
5. Track data transformations with provenance
6. Generate compliance reports for GDPR and HIPAA
7. Set up automated intrusion detection and alerting

These features provide the foundation for secure, compliant handling of sensitive data in IPFS Datasets applications.

## Next Steps

To further enhance your security and compliance setup:

1. Configure Elasticsearch for scalable audit log storage and analysis
2. Implement custom audit handlers for your existing security infrastructure
3. Set up automated compliance reporting with scheduled jobs
4. Customize intrusion detection rules for your specific security requirements
5. Integrate with existing identity management systems

For more information, see the [Security and Governance documentation](../security_governance.md) and [Audit Logging documentation](../../ipfs_datasets_py/audit/README.md).