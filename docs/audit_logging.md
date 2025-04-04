# Audit Logging and Adaptive Security System

The IPFS Datasets Python library includes a comprehensive audit logging and adaptive security system that provides detailed tracking of all operations performed on datasets, with particular emphasis on security, compliance, and data lineage, along with automated responses to detected security threats.

## Overview

The audit logging and adaptive security system is designed to:

1. Record all significant operations on datasets and system components
2. Provide detailed context for each operation, including who, what, when, and how
3. Enable compliance with regulations and internal policies
4. Integrate with data provenance tracking for complete lineage information
5. Support security monitoring and intrusion detection
6. Enable cryptographic verification of audit records
7. Automatically respond to detected security threats with configurable actions
8. Enforce security policies through automated responses
9. Provide comprehensive security response lifecycle management

## Core Components

### AuditLogger

The central component that records and manages audit events:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory

# Get the singleton instance
audit_logger = AuditLogger.get_instance()

# Log an audit event
event_id = audit_logger.log(
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id="example_dataset",
    resource_type="dataset",
    details={
        "transformation": "normalization",
        "parameters": {"method": "z-score"}
    }
)
```

### AuditEvent

A comprehensive data structure capturing all relevant information about an operation:

```python
from ipfs_datasets_py.audit.audit_logger import AuditEvent

# Create an audit event directly
event = AuditEvent(
    event_id="unique-id-123",
    timestamp="2023-10-25T14:30:00Z",
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_ACCESS,
    action="dataset_load",
    user="user123",
    resource_id="example_dataset",
    resource_type="dataset",
    details={"source": "huggingface"}
)
```

### AuditHandler

Base class for handling audit events (e.g., storing to files, databases, or sending to external systems):

```python
from ipfs_datasets_py.audit.handlers import FileAuditHandler, ConsoleAuditHandler

# Add handlers to the logger
audit_logger.add_handler(FileAuditHandler(
    name="file_handler",
    filename="audit_log.jsonl"
))

audit_logger.add_handler(ConsoleAuditHandler(
    name="console_handler"
))
```

## Event Categories and Levels

### Categories

Audit events are categorized to enable efficient filtering and analysis:

- `AUTHENTICATION`: User login/logout events
- `AUTHORIZATION`: Permission checks and access control
- `DATA_ACCESS`: Reading data or metadata
- `DATA_MODIFICATION`: Writing, updating, or deleting data
- `CONFIGURATION`: System configuration changes
- `RESOURCE`: Resource creation, deletion, modification
- `SECURITY`: Security-related events
- `SYSTEM`: System-level events
- `API`: API calls and responses
- `COMPLIANCE`: Compliance-related events
- `PROVENANCE`: Data provenance tracking
- `OPERATIONAL`: General operational events
- `INTRUSION_DETECTION`: Possible security breaches
- `CUSTOM`: Custom event categories

### Levels

Events are assigned severity levels:

- `DEBUG`: Detailed information for debugging
- `INFO`: Regular operational information
- `NOTICE`: Significant but normal events
- `WARNING`: Potential issues that don't affect operation
- `ERROR`: Errors that affect specific operations
- `CRITICAL`: Serious errors that affect multiple operations
- `EMERGENCY`: System is unusable

## Integration with Data Provenance

The audit logging system integrates tightly with the data provenance tracking system to provide comprehensive lineage information:

### AuditProvenanceIntegrator

The AuditProvenanceIntegrator provides bidirectional integration between audit logging and data provenance systems:

```python
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize components
audit_logger = AuditLogger.get_instance()
provenance_manager = EnhancedProvenanceManager(
    audit_logger=audit_logger,
    enable_ipld_storage=True  # Enable IPLD storage for provenance records
)

# Create integrator
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Set up event listener for automatic provenance record creation
integrator.setup_audit_event_listener()

# Generate audit event from provenance record
record = provenance_manager.records[record_id]
audit_event_id = integrator.audit_from_provenance_record(record)

# Generate provenance record from audit event
event = audit_logger.get_event(event_id)
record_id = integrator.provenance_from_audit_event(event)

# Link audit event to provenance record
integrator.link_audit_to_provenance(audit_event_id, record_id)

# Export provenance records to CAR file for offline storage or transfer
car_path = "/path/to/provenance.car"
root_cid = provenance_manager.export_to_car(car_path)
print(f"Exported provenance to {car_path} with root CID: {root_cid}")
```

### Integrated Compliance Reporting with Cross-Document Lineage

The enhanced IntegratedComplianceReporter generates comprehensive compliance reports that leverage our improved cross-document lineage capabilities to provide detailed insights into data flows across document boundaries:

```python
from ipfs_datasets_py.audit.integration import IntegratedComplianceReporter
from ipfs_datasets_py.audit.compliance import ComplianceStandard, ComplianceRequirement

# Create reporter with bidirectional integration
reporter = IntegratedComplianceReporter(
    standard=ComplianceStandard.GDPR,
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Add compliance requirements
reporter.add_requirement(ComplianceRequirement(
    id="GDPR-Art30",
    standard=ComplianceStandard.GDPR,
    description="Records of processing activities",
    audit_categories=[AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION],
    actions=["read", "write", "update", "delete"]
))

# Generate report with enhanced cross-document lineage analysis
report = reporter.generate_report(
    start_time="2023-01-01T00:00:00Z",
    end_time="2023-12-31T23:59:59Z",
    include_cross_document_analysis=True,  # Enable cross-document analysis
    include_lineage_metrics=True           # Include metrics about lineage graph
)

# The enhanced report now includes:
# - Document boundary detection and analysis
# - Relationship analysis across document boundaries
# - Compliance-specific insights based on cross-document flows
# - Visualization data for interactive representations

# Example of accessing enhanced cross-document lineage information
cross_doc_info = report.details.get("cross_document_lineage", {})
print(f"Document count: {cross_doc_info.get('document_count', 0)}")

# Document boundaries information
if "document_boundaries" in cross_doc_info:
    boundaries = cross_doc_info["document_boundaries"]
    print(f"Boundary count: {boundaries.get('count', 0)}")
    print(f"Cross-boundary flows: {boundaries.get('cross_boundary_flow_count', 0)}")
    
# Document relationships information
if "document_relationships" in cross_doc_info:
    relationships = cross_doc_info["document_relationships"]
    print(f"Relationship count: {relationships.get('relationship_count', 0)}")
    print(f"High-risk relationships: {relationships.get('high_risk_relationships', 0)}")

# Compliance-specific insights from cross-document analysis
if "provenance_insights" in report.details:
    print("Compliance insights from cross-document analysis:")
    for insight in report.details["provenance_insights"]:
        print(f"- {insight}")

# Save report in various formats
report.save_json("gdpr_compliance.json")
report.save_html("gdpr_compliance.html")
report.save_csv("gdpr_compliance.csv")

# Helper function for easy report generation
from ipfs_datasets_py.audit.integration import generate_integrated_compliance_report

gdpr_report = generate_integrated_compliance_report(
    standard_name="GDPR",
    start_time="2023-01-01T00:00:00Z",
    end_time="2023-12-31T23:59:59Z",
    output_format="json",
    output_path="gdpr_report.json"
)
```

The enhanced compliance reports provide standard-specific insights based on cross-document lineage analysis:

#### GDPR-Specific Insights
- Identification of cross-document data flows requiring data sharing agreements (Article 26/28)
- Detection of international transfers requiring appropriate safeguards (Articles 44-50)
- Analysis of data sharing relationships across document boundaries
- Identification of high-risk data processing requiring DPIA (Article 35)

#### HIPAA-Specific Insights
- Identification of PHI data flows crossing document boundaries
- Analysis of technical safeguards for PHI boundaries
- Detection of PHI sharing relationships requiring Business Associate Agreements
- Monitoring of de-identification processes across document boundaries

#### SOC2-Specific Insights
- Identification of critical data transit points requiring enhanced monitoring
- Analysis of data transformation processes for processing integrity
- Detection of boundary controls required for logical access security
- Monitoring of data processing relationships for input validation

### Enhanced Cross-Document Search Capabilities

The enhanced ProvenanceAuditSearchIntegrator provides unified search across audit logs and provenance records, with advanced support for cross-document lineage-aware searching:

```python
from ipfs_datasets_py.audit.integration import ProvenanceAuditSearchIntegrator

# Create search integrator
search = ProvenanceAuditSearchIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Basic search by time range and resource type
results = search.search(
    query={
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        },
        "resource_type": "dataset",
        "resource_id": "example_dataset",
        "action": "transform"
    },
    include_audit=True,
    include_provenance=True,
    correlation_mode="auto"  # Automatically detect correlations
)

# Enhanced cross-document lineage-aware search
cross_doc_results = search.search(
    query={
        "document_id": "source_document",  # Start search from this document
        "max_depth": 3,                   # Search up to 3 hops across documents
        "link_types": ["derived_from", "exported_from", "processes"],  # Filter by link types
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        },
        "keywords": ["sensitive", "pii", "personal"]  # Optional keyword filters
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True,  # Enable cross-document search
    correlation_mode="auto"
)

# Compliance-focused cross-document search
compliance_results = search.search(
    query={
        "document_id": "sensitive_data_document",
        "max_depth": 2,
        "link_types": ["contains_pii", "processes_pii", "anonymizes"],  # Focus on PII-related links
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        }
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True
)

# Access standard search results
print(f"Found {results.get('audit_count', 0)} audit events")
print(f"Found {results.get('provenance_count', 0)} provenance records")
print(f"Established {results.get('correlation_count', 0)} correlations")

# Access enhanced cross-document search results
print(f"Found {cross_doc_results.get('provenance_count', 0)} provenance records across document boundaries")
print(f"Documents involved: {cross_doc_results.get('cross_document_analysis', {}).get('document_count', 0)}")

# Analyze cross-document search results
if "cross_document_analysis" in cross_doc_results:
    analysis = cross_doc_results["cross_document_analysis"]
    print(f"Document boundaries crossed: {len(analysis.get('documents', []))}")
    
    # Relationship types found in the search
    if "relationship_types" in analysis:
        print("Relationship types across documents:")
        for rel_type, count in analysis.get("relationship_types", {}).items():
            print(f"- {rel_type}: {count}")
    
    # Distribution of records across documents
    if "records_by_document" in analysis:
        print("Records by document:")
        for doc_id, count in analysis.get("records_by_document", {}).items():
            print(f"- {doc_id}: {count}")

# Examine records with cross-document metadata
for record in cross_doc_results.get("provenance_records", []):
    if "cross_document_info" in record:
        doc_info = record["cross_document_info"]
        print(f"Record {record['record_id']} in document {doc_info.get('document_id')}")
        print(f"  Distance from source: {doc_info.get('distance_from_source')}")
        
        # Show relationship path from source record/document
        if "relationship_path" in doc_info:
            path = doc_info["relationship_path"]
            print("  Relationship path:")
            for step in path:
                print(f"    {step['from']} --({step['type']})--> {step['to']}")
```

The enhanced cross-document search capabilities enable comprehensive tracking of data flows across document boundaries with features specifically designed for compliance and security use cases:

1. **Document boundary traversal**: Discover how data flows across document boundaries, enabling complete lineage understanding regardless of document structure
2. **Relationship type filtering**: Focus searches on specific types of relationships (e.g., PII processing, data transformations)
3. **Path analysis**: See the exact path from source to target records across document boundaries
4. **Document relationship metrics**: Get statistical information about cross-document relationships
5. **Compliance-focused filtering**: Use specialized link types for compliance-focused searches (e.g., GDPR, HIPAA, SOC2)

### Dataset Operation Integration

The AuditDatasetIntegrator simplifies audit logging for dataset operations:

```python
from ipfs_datasets_py.audit.integration import AuditDatasetIntegrator

# Create dataset integrator
dataset_integrator = AuditDatasetIntegrator(audit_logger=audit_logger)

# Record dataset operations
load_event_id = dataset_integrator.record_dataset_load(
    dataset_name="example_dataset",
    dataset_id="ds123",
    source="huggingface",
    user="user123"
)

transform_event_id = dataset_integrator.record_dataset_transform(
    input_dataset="ds123",
    output_dataset="ds123_transformed",
    transformation_type="normalize",
    parameters={"columns": ["col1", "col2"], "method": "z-score"},
    user="user123"
)

save_event_id = dataset_integrator.record_dataset_save(
    dataset_name="example_dataset_transformed",
    dataset_id="ds123_transformed",
    destination="ipfs",
    format="car",
    user="user123"
)

query_event_id = dataset_integrator.record_dataset_query(
    dataset_name="ds123_transformed",
    query="SELECT * FROM dataset WHERE value > 0.5",
    query_type="sql",
    user="user123"
)
```

### Event Listeners

The audit logger supports event listeners for real-time integration with other systems:

```python
# Add event listener for specific category
audit_logger.add_event_listener(
    listener=my_listener_function,
    category=AuditCategory.DATA_MODIFICATION
)

# Add global listener for all events
audit_logger.add_event_listener(
    listener=my_global_listener
)

# Remove an event listener
audit_logger.remove_event_listener(
    listener=my_listener_function,
    category=AuditCategory.DATA_MODIFICATION
)
```

## Convenient Usage Patterns

### Context Manager

```python
from ipfs_datasets_py.audit.integration import AuditContextManager

# Use context manager to log operation start and end
with AuditContextManager(
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id="example_dataset",
    resource_type="dataset",
    details={"transformation": "normalization"}
):
    # Perform the operation
    # Timing and exceptions are automatically logged
    transform_dataset(example_dataset)
```

### Function Decorator

```python
from ipfs_datasets_py.audit.integration import audit_function

# Decorate function to automatically log calls
@audit_function(
    category=AuditCategory.DATA_ACCESS,
    action="dataset_load",
    resource_id_arg="dataset_id",
    resource_type="dataset"
)
def load_dataset(dataset_id, **kwargs):
    # Function logic
    return dataset
```

## Standardized Consumer Interface

For applications that need to access integrated audit and provenance information, a standardized consumer interface is provided:

```python
from ipfs_datasets_py.audit.provenance_consumer import ProvenanceConsumer

# Create consumer
consumer = ProvenanceConsumer(
    provenance_manager=provenance_manager,
    audit_logger=audit_logger,
    integrator=integrator
)

# Get integrated record
integrated_record = consumer.get_integrated_record(record_id)

# Search for records
records = consumer.search_integrated_records(
    query="transform",
    record_types=["transformation"],
    start_time=yesterday,
    end_time=now,
    limit=10
)

# Get lineage graph
lineage_graph = consumer.get_lineage_graph(
    data_id="example_dataset",
    max_depth=5,
    include_audit_events=True
)

# Verify data lineage
verification_result = consumer.verify_data_lineage("example_dataset")

# Export provenance information
export_data = consumer.export_provenance(
    data_id="example_dataset",
    format="json",
    include_audit_events=True
)
```

## Cryptographic Verification

The system supports cryptographic verification of provenance records to ensure integrity and authenticity:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize provenance manager with cryptographic verification
provenance_manager = EnhancedProvenanceManager(
    enable_crypto_verification=True,
    crypto_secret_key="your-secret-key"  # Optional, generated if not provided
)

# Verify a record
is_valid = provenance_manager.verify_record(record_id)

# Verify all records
verification_results = provenance_manager.verify_all_records()

# Sign all unsigned records
sign_results = provenance_manager.sign_all_records()
```

## Configuration

The audit logging system can be configured through code:

```python
# Configure audit logger
audit_logger.configure({
    "enabled": True,
    "min_level": "INFO",
    "default_user": "system",
    "default_application": "ipfs_datasets_py",
    "included_categories": ["DATA_ACCESS", "DATA_MODIFICATION"],
    "excluded_categories": ["DEBUG"]
})
```

## Best Practices

1. **Configure appropriate handlers**: Set up handlers that match your security and compliance requirements.
2. **Use context managers and decorators**: These provide automatic timing and exception handling.
3. **Set appropriate detail level**: Include enough details for troubleshooting and audit, but avoid sensitive information.
4. **Include relevant identifiers**: Always include resource IDs and user information when available.
5. **Use integration with provenance**: Set up the integrator to automatically create provenance records from audit events.
6. **Enable cryptographic verification**: For sensitive data or regulatory requirements, enable cryptographic verification.
7. **Regularly review audit logs**: Set up a process for regular review of audit logs for security and compliance.

## Example: Comprehensive Audit Logging

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.audit.handlers import FileAuditHandler, ConsoleAuditHandler
from ipfs_datasets_py.audit.integration import AuditContextManager
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator

# Initialize components
audit_logger = AuditLogger.get_instance()
audit_logger.add_handler(FileAuditHandler(name="file", filename="audit.jsonl"))
audit_logger.add_handler(ConsoleAuditHandler(name="console", min_level=AuditLevel.INFO))

# Set up provenance manager with cryptographic verification and IPLD storage
provenance_manager = EnhancedProvenanceManager(
    audit_logger=audit_logger,
    enable_crypto_verification=True,
    enable_ipld_storage=True  # Store provenance data in IPLD
)

# Set up integrator
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)
integrator.setup_audit_event_listener()

# Record data source in provenance system
source_id = "example_dataset"
record_id = provenance_manager.record_source(
    source_id=source_id,
    source_type="huggingface",
    source_uri="huggingface:dataset/example",
    description="Example dataset from HuggingFace"
)

# Use context manager for transformation
transformed_id = "transformed_dataset"
with AuditContextManager(
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id=transformed_id,
    resource_type="dataset",
    details={
        "input_dataset": source_id,
        "transformation": "normalization",
        "parameters": {"method": "z-score"}
    },
    audit_logger=audit_logger
):
    # Perform transformation
    # Record in provenance system
    transform_record_id = provenance_manager.record_transformation(
        input_ids=[source_id],
        output_id=transformed_id,
        transformation_type="normalization",
        parameters={"method": "z-score"},
        description="Normalize data using z-score"
    )

# Verify lineage integrity
from ipfs_datasets_py.audit.provenance_consumer import ProvenanceConsumer

consumer = ProvenanceConsumer(
    provenance_manager=provenance_manager,
    audit_logger=audit_logger,
    integrator=integrator
)

verification_result = consumer.verify_data_lineage(transformed_id)
print(f"Lineage verified: {verification_result['verified']}")

# Export provenance information
export_data = consumer.export_provenance(
    data_id=transformed_id,
    format="json",
    include_audit_events=True
)

# Export provenance to CAR file for decentralized storage
car_path = "provenance_export.car"
root_cid = provenance_manager.export_to_car(car_path)
print(f"Exported provenance graph to {car_path}")
print(f"Root CID: {root_cid}")

# To later import the provenance data:
new_manager = EnhancedProvenanceManager(enable_ipld_storage=True, enable_crypto_verification=True)
success = new_manager.import_from_car(car_path)
if success:
    print(f"Successfully imported {len(new_manager.records)} provenance records")
```

## Compliance Features

The audit logging system includes features specifically designed to support compliance with regulations like GDPR, HIPAA, and SOX:

1. **Complete operation history**: All data access and modifications are logged
2. **User attribution**: Operations are linked to specific users
3. **Temporal tracking**: Precise timestamps for all operations
4. **Cryptographic integrity**: Verification of record integrity
5. **Data lineage**: Complete lineage tracking with provenance integration
6. **Export capabilities**: Data can be exported for compliance reporting
7. **Segregation of duties**: Different handlers can route events to different systems

## Security and Adaptive Response Features

The audit system supports comprehensive security monitoring, intrusion detection, and adaptive security responses:

1. **Real-time event listeners**: Can trigger alerts on suspicious activity
2. **Cryptographic verification**: Detect tampering with audit or provenance records
3. **Complete context**: Full details about operations for forensic analysis
4. **Integration with security systems**: Events can be routed to SIEM systems
5. **Adaptive security responses**: Automatically respond to detected threats
6. **Response rules engine**: Match security alerts to appropriate responses
7. **Multiple response actions**: Various types of automated responses (lockout, throttle, etc.)
8. **Response lifecycle management**: Create, track, and expire security responses

### Adaptive Security Components

The adaptive security system provides automated responses to security threats:

```python
from ipfs_datasets_py.audit.adaptive_security import (
    AdaptiveSecurityManager, ResponseAction, ResponseRule, RuleCondition,
    SecurityResponse
)
from ipfs_datasets_py.audit.intrusion import IntrusionDetection, SecurityAlertManager
from ipfs_datasets_py.audit.audit_logger import AuditLogger

# Get the audit logger
audit_logger = AuditLogger.get_instance()

# Initialize components
alert_manager = SecurityAlertManager(alert_storage_path="alerts.json")
ids = IntrusionDetection(alert_manager=alert_manager)

# Create adaptive security manager
adaptive_security = AdaptiveSecurityManager(
    alert_manager=alert_manager,
    audit_logger=audit_logger,
    response_storage_path="security_responses.json"
)

# Define a rule for brute force login attempts
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

# Add rule to the adaptive security manager
adaptive_security.add_rule(brute_force_rule)

# Process any pending alerts
processed_count = adaptive_security.process_pending_alerts()
print(f"Processed {processed_count} pending alerts")

# Get active security responses
active_responses = adaptive_security.get_active_responses()
for response in active_responses:
    print(f"Active response: {response.response_id} - {response.response_type.name}")
    print(f"Target: {response.target}")
    print(f"Expires: {response.expires_at}")

# Cancel a response if needed
if active_responses:
    adaptive_security.cancel_response(active_responses[0].response_id)
```

#### Response Actions

The adaptive security system supports multiple types of automated responses:

- **MONITOR**: Enhanced monitoring for specific users or resources
- **RESTRICT**: Access restriction for resources or users
- **THROTTLE**: Rate limiting to prevent abuse
- **LOCKOUT**: Temporary account lockout
- **ISOLATE**: Resource isolation to prevent contamination
- **NOTIFY**: Security notification to administrators
- **ESCALATE**: Escalate issues to security teams
- **ROLLBACK**: Roll back unauthorized changes
- **SNAPSHOT**: Create security snapshot for forensics
- **ENCRYPT**: Enforce enhanced encryption
- **AUDIT**: Enhanced audit logging for suspicious activities

#### Response Rules

Security responses are driven by configurable rules that match specific alert patterns:

```python
# Create a rule for data exfiltration
exfiltration_rule = ResponseRule(
    rule_id="data-exfiltration-response",
    name="Data Exfiltration Response",
    alert_type="data_exfiltration",  # Match this alert type
    severity_levels=["high", "critical"],  # Match these severity levels
    actions=[
        {
            "type": "RESTRICT",  # Restrict access
            "duration_minutes": 60,
            "parameters": {
                "user_id": "{{alert.user_id}}",  # Dynamic parameter from alert
                "reason": "Potential data exfiltration"
            }
        },
        {
            "type": "AUDIT",  # Enhanced auditing
            "duration_minutes": 4320,  # 3 days
            "parameters": {
                "user_id": "{{alert.user_id}}",
                "level": "forensic",
                "reason": "Data exfiltration investigation"
            }
        }
    ],
    conditions=[
        RuleCondition("alert.data_size", ">=", 50 * 1024 * 1024)  # 50MB threshold
    ],
    description="Respond to potential data exfiltration with access restriction and enhanced auditing"
)
```

#### Response Lifecycle Management

The system automatically manages the lifecycle of security responses:

```python
# Check for expired responses
expired_count = adaptive_security.check_expired_responses()
print(f"Found {expired_count} expired responses")

# Create a manual response
from datetime import datetime, timedelta

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

# Add the manual response
adaptive_security.add_response(manual_response)
```

#### Integration with Security Monitoring

The adaptive security system integrates with the rest of the security infrastructure:

```python
from ipfs_datasets_py.audit.intrusion import IntrusionDetection, SecurityAlertManager
from ipfs_datasets_py.audit.adaptive_security import AdaptiveSecurityManager
from ipfs_datasets_py.audit.audit_logger import AuditLogger

# Initialize components
audit_logger = AuditLogger.get_instance()
alert_manager = SecurityAlertManager()
ids = IntrusionDetection(alert_manager=alert_manager)
adaptive_security = AdaptiveSecurityManager(
    alert_manager=alert_manager,
    audit_logger=audit_logger
)

# Set up event listeners for security alerts
def handle_security_alert(alert):
    print(f"Alert received: {alert.alert_id} ({alert.alert_type})")
    print(f"Severity: {alert.severity}")
    print(f"Description: {alert.description}")
    
    # The alert will be automatically processed by adaptive security

alert_manager.add_notification_handler(handle_security_alert)

# Connect intrusion detection system to alert manager
ids.add_alert_handler(alert_manager.add_alert)

# Simulate events for intrusion detection
events = [
    {"type": "login", "user": "test_user", "ip": "192.168.1.100", "timestamp": "2023-06-01T10:00:00Z", "success": False},
    {"type": "login", "user": "test_user", "ip": "192.168.1.100", "timestamp": "2023-06-01T10:01:00Z", "success": False},
    {"type": "login", "user": "test_user", "ip": "192.168.1.100", "timestamp": "2023-06-01T10:02:00Z", "success": False},
    {"type": "login", "user": "test_user", "ip": "192.168.1.100", "timestamp": "2023-06-01T10:03:00Z", "success": False},
    {"type": "login", "user": "test_user", "ip": "192.168.1.100", "timestamp": "2023-06-01T10:04:00Z", "success": False}
]

# Process events through IDS (will generate alerts for brute force detection)
ids.process_events(events)

# Security alerts will trigger the adaptive security system automatically
# with responses based on the configured rules
```

## Cross-Document Lineage Integration

The enhanced audit logging system now includes integration with the cross-document lineage tracking system, providing comprehensive visibility into data flows across document boundaries:

```python
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
from ipfs_datasets_py.cross_document_lineage import CrossDocumentLineageTracker, LinkType

# Initialize components
audit_logger = AuditLogger.get_instance()
provenance_manager = EnhancedProvenanceManager(
    audit_logger=audit_logger,
    enable_ipld_storage=True
)

# Create lineage tracker
lineage_tracker = CrossDocumentLineageTracker(
    provenance_storage=provenance_manager,
    audit_logger=audit_logger,
    link_verification=True
)

# Set up integrator
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager,
    lineage_tracker=lineage_tracker  # Now includes lineage tracker
)

# Create a cross-document relationship
relationship_id = lineage_tracker.create_link(
    source_document_id="document1",
    target_document_id="document2",
    link_type=LinkType.DERIVED_FROM,
    confidence=0.95,
    metadata={
        "transformation": "summarization",
        "creator": "user123"
    }
)

# The relationship is automatically logged to the audit system
audit_event_id = lineage_tracker.get_audit_event_id(relationship_id)
audit_event = audit_logger.get_event(audit_event_id)

# Querying cross-document lineage with audit context
results = lineage_tracker.query_lineage(
    document_id="document2",
    include_audit_events=True,  # Include associated audit events
    max_depth=3
)

# Access the audit events associated with lineage
for node in results.get("nodes", []):
    if "audit_events" in node:
        print(f"Document {node['id']} has {len(node['audit_events'])} audit events")
        
        for event_id in node["audit_events"]:
            event = audit_logger.get_event(event_id)
            print(f"- {event.timestamp}: {event.action} by {event.user}")

# Generate a lineage report with audit details
report = lineage_tracker.generate_lineage_report(
    document_id="document2",
    include_audit_events=True,
    format="json"
)

# Save the report
with open("document2_lineage_report.json", "w") as f:
    json.dump(report, f, indent=2)

# Visualization with audit information
viz_data = lineage_tracker.generate_visualization_data(
    document_id="document2",
    include_audit_events=True,
    highlight_critical_paths=True
)
```

### Semantic Link Types for Audit Integration

The cross-document lineage system provides specialized semantic link types that are particularly relevant for audit logging and compliance:

```python
from ipfs_datasets_py.cross_document_lineage import LinkType, CrossDocumentLineageTracker

# Initialize tracker
lineage_tracker = CrossDocumentLineageTracker(
    provenance_storage=provenance_manager,
    audit_logger=audit_logger
)

# Using semantic link types for compliance-aware lineage tracking
compliance_link = lineage_tracker.create_link(
    source_document_id="document1",
    target_document_id="document2",
    link_type=LinkType.CONTAINS_PII,  # Special compliance link type
    confidence=0.98,
    metadata={
        "pii_types": ["name", "email", "address"],
        "has_consent": True,
        "consent_reference": "CONSENT-123456",
        "retention_period": "365 days",
        "data_controller": "Company XYZ",
        "legal_basis": "GDPR Art. 6(1)(a)"
    }
)

# Create data transformation link with audit-relevant metadata
transform_link = lineage_tracker.create_link(
    source_document_id="document2",
    target_document_id="document3",
    link_type=LinkType.ANONYMIZES,  # Indicates PII anonymization
    confidence=0.95,
    metadata={
        "transformation": "pii_anonymization",
        "anonymization_method": "k-anonymity",
        "k_value": 5,
        "approved_by": "compliance_officer",
        "approval_date": "2023-05-15T10:30:00Z",
        "verification_method": "manual_review",
        "verification_date": "2023-05-16T14:45:00Z"
    }
)

# Create data processing link for GDPR Article 30 compliance
processing_link = lineage_tracker.create_link(
    source_document_id="document3",
    target_document_id="document4",
    link_type=LinkType.PROCESSES,  # General processing relationship
    confidence=0.92,
    metadata={
        "processing_purpose": "analytics",
        "retention_period": "90 days",
        "responsible_processor": "Analytics Team",
        "gdpr_art30_record": "PROC-2023-05-001",
        "dpia_reference": "DPIA-2023-003"  # Data Protection Impact Assessment
    }
)

# Query compliance-related links
compliance_links = lineage_tracker.query_links(
    link_types=[LinkType.CONTAINS_PII, LinkType.ANONYMIZES, LinkType.PROCESSES],
    min_confidence=0.9
)

print(f"Found {len(compliance_links)} compliance-related document relationships")
```

### Comprehensive Lineage Audit Search

The enhanced search capabilities now integrate cross-document lineage with audit logging for powerful queries:

```python
from ipfs_datasets_py.audit.integration import CrossDocumentLineageAuditSearch

# Create search component
search = CrossDocumentLineageAuditSearch(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager,
    lineage_tracker=lineage_tracker
)

# Comprehensive search across document boundaries with audit context
results = search.search(
    query={
        "document_id": "document1",  # Start point
        "max_depth": 3,              # How far to traverse
        "link_types": ["derived_from", "influenced_by"],  # Types of links to follow
        "min_confidence": 0.7,       # Minimum confidence threshold
        "audit_filters": {           # Filter by audit properties
            "user": "user123",
            "timerange": {
                "start": "2023-01-01T00:00:00Z",
                "end": "2023-12-31T23:59:59Z"
            },
            "actions": ["create", "transform", "approve"]
        },
        "metadata_filters": {        # Filter by link metadata
            "transformation": "summarization"
        }
    }
)

# Analyze results
print(f"Found {len(results.get('documents', []))} related documents")
print(f"Found {len(results.get('links', []))} relationships")
print(f"Found {len(results.get('audit_events', []))} related audit events")

# Examine lineage paths with audit events
for path in results.get("paths", []):
    print(f"Path from {path['source']} to {path['target']}:")
    
    for step in path.get("steps", []):
        link = step.get("link", {})
        audits = step.get("audit_events", [])
        
        print(f"  {link.get('source')} --({link.get('type')}, confidence: {link.get('confidence', 0):.2f})--> {link.get('target')}")
        print(f"    Audit events: {len(audits)}")
        
        for audit_id in audits[:3]:  # Show first 3 events
            event = audit_logger.get_event(audit_id)
            print(f"    - {event.timestamp}: {event.action} by {event.user}")
        
        if len(audits) > 3:
            print(f"    - ... and {len(audits) - 3} more events")
```

### Audit Event Link Analysis

The system provides analysis of audit events associated with document links:

```python
from ipfs_datasets_py.audit.integration import LineageAuditAnalyzer

# Create analyzer
analyzer = LineageAuditAnalyzer(
    audit_logger=audit_logger,
    lineage_tracker=lineage_tracker
)

# Analyze audit events for document relationship
analysis = analyzer.analyze_link_audit_events(relationship_id)

# Show comprehensive analysis
print(f"Link between {analysis['source_document']} and {analysis['target_document']}")
print(f"Link type: {analysis['link_type']}")
print(f"Confidence: {analysis['confidence']:.2f}")
print(f"Created: {analysis['created_at']}")
print(f"Creator: {analysis['created_by']}")

print("\nAudit timeline:")
for event in analysis.get("audit_timeline", []):
    print(f"- {event['timestamp']}: {event['action']} by {event['user']}")
    if "details" in event:
        for key, value in event["details"].items():
            print(f"  {key}: {value}")

# Get risk assessment
risk = analyzer.assess_link_risk(relationship_id)
print(f"\nRisk assessment: {risk['risk_level']} ({risk['risk_score']:.2f})")
print(f"Factors contributing to risk assessment:")
for factor in risk.get("risk_factors", []):
    print(f"- {factor['factor']}: {factor['score']:.2f} - {factor['reason']}")

# Analyze document modification patterns
mod_analysis = analyzer.analyze_document_modifications(
    document_id="document2",
    include_linked_documents=True,
    timerange={
        "start": "2023-01-01T00:00:00Z",
        "end": "2023-12-31T23:59:59Z"
    }
)

print("\nDocument modification analysis:")
print(f"Total modifications: {mod_analysis['total_modifications']}")
print(f"Modification frequency: {mod_analysis['modification_frequency']} per day")
print(f"Most active users:")
for user, count in mod_analysis.get("users", {}).items():
    print(f"- {user}: {count} modifications")
```

### Cryptographic Verification of Cross-Document Lineage

The system supports cryptographic verification of lineage relationships to ensure integrity of cross-document data flows:

```python
from ipfs_datasets_py.cross_document_lineage import CrossDocumentLineageTracker, verify_lineage_chain

# Create lineage tracker with verification enabled
lineage_tracker = CrossDocumentLineageTracker(
    provenance_storage=provenance_manager,
    audit_logger=audit_logger,
    link_verification=True,  # Enable cryptographic verification
    crypto_verifier=crypto_verifier  # Optional custom verifier
)

# Create signed link
link_id = lineage_tracker.create_link(
    source_document_id="document1",
    target_document_id="document2",
    link_type=LinkType.DERIVED_FROM,
    confidence=0.95,
    metadata={"transformation": "summarization"},
    sign=True  # Sign this link
)

# Verify a specific link
verification_result = lineage_tracker.verify_link(link_id)
print(f"Link verified: {verification_result['verified']}")
if not verification_result['verified']:
    print(f"Verification failed: {verification_result['reason']}")

# Verify an entire lineage chain
chain_verification = verify_lineage_chain(
    lineage_tracker=lineage_tracker,
    document_id="document5",  # End of the chain
    max_depth=5  # How far back to verify
)

print(f"Lineage chain verified: {chain_verification['verified']}")
print(f"Links verified: {chain_verification['links_verified']}")
print(f"Links with issues: {chain_verification['links_with_issues']}")

# Integration with audit logging
if not chain_verification['verified']:
    # Log verification failure to audit system
    audit_logger.log(
        level=AuditLevel.WARNING,
        category=AuditCategory.SECURITY,
        action="lineage_verification_failed",
        resource_id="document5",
        resource_type="document",
        details={
            "verification_result": chain_verification,
            "links_with_issues": chain_verification['links_with_issues']
        }
    )

# Export verification report
verification_report = lineage_tracker.generate_verification_report(
    document_id="document5",
    max_depth=5,
    include_audit_events=True
)

with open("verification_report.json", "w") as f:
    json.dump(verification_report, f, indent=2)
```

### Automated Audit Policy Enforcement

The cross-document lineage system integrates with the audit system to enforce policies about data flows across document boundaries:

```python
from ipfs_datasets_py.audit.integration import LineagePolicyEnforcer
from ipfs_datasets_py.cross_document_lineage import LinkType

# Create policy enforcer
enforcer = LineagePolicyEnforcer(
    audit_logger=audit_logger,
    lineage_tracker=lineage_tracker
)

# Define a policy about PII data flows
enforcer.add_policy({
    "id": "PII-001",
    "name": "PII Data Anonymization Policy",
    "description": "PII data must be anonymized before analytical processing",
    "rule": {
        "condition": {
            "link_type": LinkType.CONTAINS_PII,
            "target_has_link_type": LinkType.PROCESSES
        },
        "requirement": {
            "intermediate_link_type": LinkType.ANONYMIZES,
            "required": True
        },
        "exception": {
            "metadata": {
                "has_consent": True,
                "legal_basis": "GDPR Art. 6(1)(a)"
            }
        }
    },
    "action": {
        "if_violated": {
            "log_level": AuditLevel.WARNING,
            "notify": ["compliance@example.com", "security@example.com"],
            "block_operation": False
        }
    }
})

# Check compliance of a document
compliance_result = enforcer.check_document_compliance(
    document_id="document3",
    policies=["PII-001"]  # Specific policies to check
)

print(f"Document compliant: {compliance_result['compliant']}")
if not compliance_result['compliant']:
    print("Policy violations:")
    for violation in compliance_result.get('violations', []):
        print(f"- Policy {violation['policy_id']}: {violation['description']}")
        print(f"  Violation details: {violation['details']}")

# Check compliance during link creation (integrate with link creation)
try:
    processing_link = lineage_tracker.create_link(
        source_document_id="document_with_pii",
        target_document_id="analytics_document",
        link_type=LinkType.PROCESSES,
        confidence=0.95,
        metadata={"processing_purpose": "analytics"},
        enforce_policies=True  # Enable policy enforcement
    )
    print("Link created successfully - complies with policies")
except Exception as e:
    print(f"Link creation failed due to policy violation: {str(e)}")
```

## API Reference

For complete API reference, see the code documentation in:
- `ipfs_datasets_py.audit.audit_logger`
- `ipfs_datasets_py.audit.handlers`
- `ipfs_datasets_py.audit.integration`
- `ipfs_datasets_py.audit.provenance_consumer`
- `ipfs_datasets_py.cross_document_lineage`