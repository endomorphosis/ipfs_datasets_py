# Comprehensive Audit Logging Module

This module provides enterprise-grade audit logging capabilities for the IPFS Datasets library. It enables detailed tracking of all system activities for security, compliance, and operational monitoring.

## Features

- **Comprehensive Event Logging**: Track authentication, authorization, data access, configuration changes, and security events
- **Flexible Output Handlers**: Send audit logs to files, syslog, Elasticsearch, or custom destinations
- **Compliance Reporting**: Generate compliance reports for various standards (GDPR, HIPAA, SOC2)
- **Intrusion Detection**: Detect security threats with anomaly detection and pattern matching
- **Security Alerting**: Real-time alerts for security-relevant events
- **Detailed Provenance Tracking**: Integration with the existing provenance tracking system

## Usage Examples

### Basic Audit Logging

```python
from ipfs_datasets_py.audit import AuditLogger, AuditCategory, AuditLevel

# Get the global audit logger instance
audit_logger = AuditLogger.get_instance()

# Add a file handler
from ipfs_datasets_py.audit import FileAuditHandler
file_handler = FileAuditHandler(
    name="file",
    file_path="/path/to/audit.log",
    min_level=AuditLevel.INFO,
    rotate_size_mb=10
)
audit_logger.add_handler(file_handler)

# Log events
audit_logger.auth("login", user="john_doe", status="success")
audit_logger.data_access("read", resource_id="dataset123", resource_type="dataset")
audit_logger.security("permission_change", level=AuditLevel.WARNING,
                     details={"target": "admin_role", "changes": "added_user"})
```

### Context-Aware Logging

```python
# Set thread-local context
audit_logger.set_context(user="current_user", session_id="abc123")

# All subsequent events will include this context
audit_logger.data_access("read", resource_id="file456")
audit_logger.data_modify("update", resource_id="file456")

# Clear context when done
audit_logger.clear_context()
```

### Compliance Reporting

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

### Intrusion Detection

```python
from ipfs_datasets_py.audit import IntrusionDetection, SecurityAlertManager

# Create intrusion detection system
ids = IntrusionDetection()
alert_manager = SecurityAlertManager()

# Set up alerting
def handle_alert(alert):
    print(f"SECURITY ALERT: {alert.level} - {alert.description}")
alert_manager.add_notification_handler(handle_alert)

# Connect IDS to alert manager
ids.add_alert_handler(alert_manager.add_alert)

# Process events through IDS
alerts = ids.process_events(recent_events)
```

## Integration with Security Module

The audit logging system integrates with the existing security module to provide a comprehensive security and compliance solution:

```python
from ipfs_datasets_py.security import SecurityManager
from ipfs_datasets_py.audit import AuditLogger, FileAuditHandler

# Initialize security manager
security = SecurityManager.initialize()

# Set up audit logging
audit_logger = AuditLogger.get_instance()
audit_logger.add_handler(FileAuditHandler(name="file", file_path="audit.log"))

# Security operations now generate audit events
security.authenticate("username", "password")  # Generates auth event
security.check_access("resource123", "read")   # Generates authz event
security.encrypt_file("input.txt", "output.enc", "key1")  # Generates security event
```

## Audit Event Categories

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

## Audit Event Severity Levels

- **DEBUG**: Fine-grained debugging information
- **INFO**: Normal operational events
- **NOTICE**: Significant but normal events
- **WARNING**: Potential issues that don't affect operations
- **ERROR**: Error conditions that affect operations
- **CRITICAL**: Critical conditions requiring immediate attention
- **EMERGENCY**: System is unusable

## Security Alert Types

The intrusion detection system can detect and alert on various security threats, including:

- **Brute Force Login Attempts**: Multiple failed login attempts from the same source
- **Multiple Access Denials**: Unusual patterns of access denials
- **Sensitive Data Access**: Unusual access to sensitive data
- **Account Compromise**: Behavioral anomalies indicating potential compromise
- **Privilege Escalation**: Unexpected privilege changes
- **Data Exfiltration**: Unusual data export activities
- **Unauthorized Configuration**: Attempts to modify sensitive configurations

## Supported Compliance Standards

The compliance reporting system supports generating reports for:

- **GDPR**: General Data Protection Regulation
- **HIPAA**: Health Insurance Portability and Accountability Act
- **SOC2**: Service Organization Control 2
- **PCI-DSS**: Payment Card Industry Data Security Standard
- **CCPA**: California Consumer Privacy Act
- **NIST 800-53**: NIST Special Publication 800-53
- **ISO 27001**: ISO/IEC 27001
- **Custom**: Custom compliance frameworks