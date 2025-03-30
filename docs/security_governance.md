# Security and Governance Features

IPFS Datasets provides comprehensive security and governance features to protect sensitive data, enforce access controls, and maintain audit trails.

## Key Security Components

### Authentication and Authorization

```python
from ipfs_datasets_py.security import SecurityManager, require_authentication, require_access

# Initialize security manager
security = SecurityManager()

# Create users with different roles
admin_id = security.create_user("admin", "admin_password", role="admin")
user_id = security.create_user("standard_user", "user_password", role="user")

# Use authentication and access control
@require_authentication
@require_access("dataset_id", "write")
def update_dataset(user_token, dataset_id, new_data):
    # Update logic here
    return True
```

### Data Encryption

```python
# Generate encryption key
key_id = security.create_encryption_key("my-secret-key")

# Encrypt data
encrypted_data = security.encrypt_data("This is confidential".encode(), key_id)

# Decrypt data
decrypted_data = security.decrypt_data(encrypted_data, key_id)

# Encrypt/decrypt files
security.encrypt_file("input.txt", "encrypted.bin", key_id)
security.decrypt_file("encrypted.bin", "decrypted.txt", key_id)
```

### Audit Logging

The integrated audit logging system provides comprehensive logging capabilities for security, compliance, and operational monitoring.

```python
from ipfs_datasets_py.audit import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.audit import FileAuditHandler, JSONAuditHandler

# Get the global audit logger
audit_logger = AuditLogger.get_instance()

# Configure handlers
audit_logger.add_handler(FileAuditHandler("file", "logs/audit.log"))
audit_logger.add_handler(JSONAuditHandler("json", "logs/audit.json"))

# Log various types of events
audit_logger.auth("login", status="success", details={"ip": "192.168.1.100"})
audit_logger.data_access("read", resource_id="dataset123", resource_type="dataset")
audit_logger.security("permission_change", level=AuditLevel.WARNING,
                   details={"target_role": "admin", "changes": ["added_user"]})
```

#### Audit Event Categories

- **AUTHENTICATION**: User login/logout events
- **AUTHORIZATION**: Permission checks and access control
- **DATA_ACCESS**: Reading data or metadata
- **DATA_MODIFICATION**: Writing, updating, or deleting data
- **CONFIGURATION**: System configuration changes
- **RESOURCE**: Resource creation, deletion, modification
- **SECURITY**: Security-related events
- **SYSTEM**: System-level events
- **API**: API calls and responses
- **COMPLIANCE**: Compliance-related events
- **PROVENANCE**: Data provenance tracking
- **OPERATIONAL**: General operational events
- **INTRUSION_DETECTION**: Possible security breaches

### Compliance Reporting

Generate compliance reports for various regulatory standards:

```python
from ipfs_datasets_py.audit import GDPRComplianceReporter

# Create a GDPR reporter
reporter = GDPRComplianceReporter()

# Generate report from audit events
report = reporter.generate_report(events)

# Save report in various formats
report.save_json("gdpr_compliance.json")
report.save_csv("gdpr_compliance.csv")
report.save_html("gdpr_compliance.html")
```

Supported compliance standards include:
- GDPR (General Data Protection Regulation)
- HIPAA (Health Insurance Portability and Accountability Act)
- SOC2 (Service Organization Control 2)
- PCI-DSS (Payment Card Industry Data Security Standard)
- CCPA (California Consumer Privacy Act)
- NIST 800-53 (NIST Special Publication 800-53)
- ISO 27001 (ISO/IEC 27001)

### Intrusion Detection

Identify and alert on potential security threats:

```python
from ipfs_datasets_py.audit import IntrusionDetection, SecurityAlertManager

# Create intrusion detection system
ids = IntrusionDetection()
alert_manager = SecurityAlertManager(alert_storage_path="logs/alerts.json")

# Add an email alert handler
def email_alert_handler(alert):
    if alert.level in ['high', 'critical']:
        # Email sending logic
        print(f"ALERT: {alert.level.upper()} - {alert.description}")

alert_manager.add_notification_handler(email_alert_handler)

# Connect IDS to alert manager
ids.add_alert_handler(alert_manager.add_alert)

# Process events through IDS
alerts = ids.process_events(recent_events)
```

The intrusion detection system can detect:
- Brute Force Login Attempts
- Multiple Access Denials
- Sensitive Data Access
- Account Compromise
- Privilege Escalation
- Data Exfiltration
- Unauthorized Configuration Changes

### Data Provenance

Track the complete lineage of data with enhanced IPLD-based provenance tracking:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize with enhanced IPLD storage
manager = EnhancedProvenanceManager(
    enable_ipld_storage=True,
    enable_crypto_verification=True
)

# Record source data
source_id = manager.record_source(
    output_id="source_dataset",
    source_type="database",
    source_uri="postgresql://localhost/analytics",
    format="table",
    description="Raw customer data from analytics database"
)

# Record transformation step
transform_id = manager.record_transformation(
    input_ids=[source_id],
    output_id="filtered_dataset",
    transformation_type="filter",
    tool="duckdb",
    parameters={"condition": "value > 50"},
    description="Filter rows where value > 50"
)

# Record verification of the filtered dataset
verify_id = manager.record_verification(
    data_id="filtered_dataset",
    verification_type="schema",
    schema={"id": "integer", "value": "float"},
    validation_rules=[{"rule": "range", "column": "value", "min": 50}],
    pass_count=850,
    fail_count=0,
    description="Verify filtered dataset schema and value range"
)

# Advanced traversal to trace data lineage
lineage_graph = manager.traverse_provenance(
    record_id="filtered_dataset",
    max_depth=5,
    direction="both",  # Trace both upstream and downstream
    relation_filter=None  # Include all relation types
)

# Generate a visualization of data lineage
visualization = manager.visualize_provenance_enhanced(
    data_ids=["filtered_dataset"],
    max_depth=3,
    show_timestamps=True,
    highlight_critical_path=True,
    format="html",
    file_path="data_lineage.html"
)

# Export provenance to CAR file for secure storage and verification
cid = manager.export_to_car("dataset_provenance.car")
print(f"Exported provenance with root CID: {cid}")

# Verify the cryptographic integrity of the provenance records
verification_results = manager.verify_all_records()
valid_percentage = sum(1 for v in verification_results.values() if v) / len(verification_results) * 100
print(f"Provenance integrity: {valid_percentage:.1f}% valid records")
```

The enhanced data provenance system now provides:

- **Detailed Lineage Tracking**: Complete history of data transformation and validation
- **Cryptographic Verification**: Ensures integrity of provenance records
- **IPLD-Based Storage**: Content-addressed storage with DAG-PB encoding
- **Advanced Graph Traversal**: Direction and relation filtering for precise lineage analysis
- **Incremental Loading**: Efficiently load relevant portions of large provenance graphs
- **Visualization Options**: Interactive HTML visualization of provenance graphs
- **CAR Import/Export**: Portable provenance records with selective options

## Best Practices

### Encryption

- Use unique encryption keys for different data sets
- Rotate encryption keys periodically
- Store encryption keys securely (using system keyring when possible)
- Use appropriate key sizes (AES-256 for sensitive data)

### Authentication

- Enable multi-factor authentication for sensitive operations
- Use strong password policies
- Implement account lockout after failed attempts
- Use token-based authentication for APIs

### Authorization

- Follow principle of least privilege
- Use role-based access control
- Regularly audit access permissions
- Revoke unused or unnecessary permissions

### Audit Logging

- Enable comprehensive audit logging in production
- Store audit logs in a secure location
- Configure real-time alerting for security-critical events
- Regularly review and analyze audit logs

### Compliance

- Run compliance reports regularly
- Address non-compliant areas promptly
- Maintain documentation of compliance efforts
- Keep up to date with regulatory changes

## Integration with Existing Security Infrastructure

IPFS Datasets security features can integrate with existing security infrastructure:

```python
# Custom authentication backend
class LDAPAuthBackend:
    def authenticate(self, username, password):
        # LDAP authentication logic
        return user_id if successful else None

# Register custom backend
security.register_auth_backend(LDAPAuthBackend())

# Custom audit log handler for SIEM integration
from ipfs_datasets_py.audit import AuditHandler

class SIEMHandler(AuditHandler):
    def _handle_event(self, event):
        # SIEM integration logic
        return True

# Add SIEM handler
audit_logger.add_handler(SIEMHandler("siem"))
```

## Advanced Configuration

The security and audit logging systems can be configured through code or configuration files:

```python
from ipfs_datasets_py.security import SecurityConfig

# Configure security features
security = SecurityManager.initialize(SecurityConfig(
    enable_encryption=True,
    require_authentication=True,
    audit_log_path="/var/log/ipfs_datasets/audit.log",
    use_system_keyring=True,
    track_provenance=True
))

# Configure audit logging
from ipfs_datasets_py.audit import AuditLogger

audit_logger = AuditLogger.get_instance()
audit_logger.configure({
    "enabled": True,
    "min_level": "INFO",
    "default_user": "system",
    "included_categories": ["AUTHENTICATION", "DATA_ACCESS", "SECURITY"],
    "excluded_categories": []
})
```

## Additional Resources

- [Audit Logging Documentation](../ipfs_datasets_py/audit/README.md): Complete documentation for the audit logging system
- [Data Provenance Guide](../ipfs_datasets_py/provenance_reporting.md): Detailed guide on data provenance tracking and reporting