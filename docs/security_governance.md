# Security and Governance Features

IPFS Datasets provides comprehensive security and governance features to protect sensitive data, enforce access controls, maintain audit trails, and ensure comprehensive data provenance integration.

## Key Security Components

### Security-Provenance Integration

The security-provenance integration system combines the enhanced security features with the data provenance tracking system, providing comprehensive security-aware provenance and provenance-aware security enforcement.

```python
from ipfs_datasets_py.audit.security_provenance_integration import (
    SecurityProvenanceIntegrator, secure_provenance_operation
)
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, DataClassification, AccessDecision, SecuritySession
)

# Get integrator instance
integrator = SecurityProvenanceIntegrator()

# Record a secure transformation with security context
record_id = integrator.record_secure_transformation(
    input_ids=["raw_data_001"],  # Input data IDs
    output_id="processed_data_001",  # Output data ID
    transformation_type="anonymize",  # Type of transformation
    parameters={  # Transformation parameters
        "method": "differential_privacy",
        "epsilon": 0.1,
        "fields_anonymized": ["name", "address", "phone"]
    },
    user_id="alice",  # User performing the operation
    verify_lineage=True,  # Verify upstream lineage for sensitive data
    classification=DataClassification.INTERNAL  # Classification for output
)

# Add security metadata to a provenance record
integrator.add_security_metadata_to_record(record_id, user_id="admin")

# Check access with lineage-based context
decision, context = integrator.check_access_with_lineage(
    user_id="bob",
    resource_id="processed_data_001",
    operation="read",
    max_depth=2  # How far to trace lineage
)

if decision == AccessDecision.ALLOW:
    print("Access allowed")
elif decision == AccessDecision.AUDIT_ONLY:
    print("Access allowed with detailed auditing due to sensitive lineage")
    # Add custom auditing for sensitive lineage access
elif decision == AccessDecision.ELEVATE:
    print("Additional authorization required due to data's sensitive source")
    # Request additional authorization
else:
    print("Access denied")

# Secure function with provenance-aware access control
@secure_provenance_operation(user_id_arg="user", data_id_arg="resource_id")
def access_data_with_lineage(user, resource_id):
    """
    This function automatically checks user access based on both
    direct permissions and data lineage before execution.
    """
    # Function body only executes if access is allowed
    return {"status": "access_granted", "resource": resource_id}

# Verify security across document boundaries
results = integrator.verify_cross_document_security(
    document_ids=["document_001", "document_002", "document_003"],
    user_id="security_officer"
)

# Check for security issues
if not results["is_secure"]:
    for issue in results["security_issues"]:
        print(f"Security issue: {issue['type']} - {issue['description']}")
        print(f"Severity: {issue['severity']}")

# Perform a security-aware provenance query
query_results = integrator.secure_provenance_query(
    query_params={
        "record_type": "transformation",
        "transformation_type": "anonymize"
    },
    user_id="analyst",
    include_cross_document=True
)

# The results are automatically filtered based on user permissions
for record in query_results["records"]:
    print(f"Record: {record['record_id']}")
    print(f"Classification: {record['security']['classification']}")
```

### Enhanced Security and Governance System

The enhanced security system provides advanced features for data classification, access control, security policy enforcement, and secure operations through an integrated design.

```python
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, SecurityPolicy, AccessControlEntry, DataClassification, 
    DataEncryptionConfig, AccessDecision, SecuritySession, security_operation
)

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Set data classifications
security_manager.set_data_classification(
    resource_id="customer_data",
    classification=DataClassification.CONFIDENTIAL,
    user_id="admin_user"
)

# Add access control entries
ace = AccessControlEntry(
    resource_id="customer_data",
    resource_type="dataset",
    principal_id="data_analyst",
    principal_type="user",
    permissions=["read"],
    conditions={"time_range": {"start": "08:00:00", "end": "18:00:00"}}
)
security_manager.add_access_control_entry(ace)

# Create security policies
policy = SecurityPolicy(
    policy_id="data_access_policy",
    name="Sensitive Data Access Policy",
    description="Controls access to sensitive data",
    enforcement_level="enforcing",
    rules=[
        {
            "type": "access_time",
            "allowed_hours": {"start": 8, "end": 18},
            "severity": "medium",
            "description": "Restricts access to business hours"
        },
        {
            "type": "data_volume",
            "threshold_bytes": 50 * 1024 * 1024,  # 50MB
            "severity": "high",
            "description": "Alerts on large data operations"
        }
    ]
)
security_manager.add_security_policy(policy)

# Create encryption configurations
encryption_config = DataEncryptionConfig(
    enabled=True,
    key_id="customer_data_key",
    algorithm="AES-256-GCM",
    key_rotation_days=30
)
security_manager.add_encryption_config("customer_data", encryption_config)

# Check access permissions
decision = security_manager.check_access(
    user_id="data_analyst",
    resource_id="customer_data",
    operation="read",
    context={"client_ip": "192.168.1.100"}
)

if decision == AccessDecision.ALLOW:
    print("Access allowed")
elif decision == AccessDecision.DENY:
    print("Access denied")
elif decision == AccessDecision.ELEVATE:
    print("Elevated access required")
elif decision == AccessDecision.AUDIT_ONLY:
    print("Access allowed with detailed auditing")

# Secure operations with security decorator
@security_operation(user_id_arg="user_id", resource_id_arg="resource_id", action="process_sensitive_data")
def process_sensitive_data(user_id, resource_id, operation_type):
    # Function is automatically protected with access checks and auditing
    return f"Processed {resource_id} with {operation_type} operation"

# Security session context manager
with SecuritySession(
    user_id="data_analyst",
    resource_id="customer_data",
    action="analyze_data"
) as session:
    # Set context for the session
    session.set_context("purpose", "quarterly_analysis")
    session.set_context("client_ip", "192.168.1.100")
    
    # Check access within the session
    decision = session.check_access("read")
    
    # Perform operation if allowed
    if decision == AccessDecision.ALLOW:
        # Perform analysis operation
        pass
```

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

# Enhanced encryption with data classification
from ipfs_datasets_py.audit.enhanced_security import EnhancedSecurityManager, DataEncryptionConfig

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Configure encryption for a sensitive resource
encryption_config = DataEncryptionConfig(
    enabled=True,
    key_id="sensitive_data_key",
    algorithm="AES-256-GCM",
    key_rotation_days=30
)
security_manager.add_encryption_config("sensitive_data", encryption_config)

# Encrypt sensitive data
data = "Highly confidential information".encode()
encrypted_data, key_id = security_manager.encrypt_sensitive_data(data, "sensitive_data")

# Decrypt the data
decrypted_data = security_manager.decrypt_sensitive_data(encrypted_data, key_id)
```

### Comprehensive Audit Logging

The integrated audit logging system provides comprehensive logging capabilities for security, compliance, and operational monitoring, with bidirectional integration with data provenance tracking.

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.handlers import FileAuditHandler, JSONAuditHandler
from ipfs_datasets_py.audit.integration import (
    AuditContextManager, AuditProvenanceIntegrator, IntegratedComplianceReporter
)

# Get the global audit logger
audit_logger = AuditLogger.get_instance()

# Configure handlers
audit_logger.add_handler(FileAuditHandler("file", "logs/audit.log"))
audit_logger.add_handler(JSONAuditHandler("json", "logs/audit.json"))

# Set up context for thread-local information
audit_logger.set_context(user="admin", session_id="session-123")

# Log various types of events
audit_logger.auth("login", status="success", details={"ip": "192.168.1.100"})
audit_logger.data_access("read", resource_id="dataset123", resource_type="dataset")
audit_logger.security("permission_change", level=AuditLevel.WARNING,
                   details={"target_role": "admin", "changes": ["added_user"]})

# Use context manager for automatic timing and error handling
with AuditContextManager(
    category=AuditCategory.DATA_MODIFICATION,
    action="transform_dataset",
    resource_id="dataset123",
    resource_type="dataset",
    details={"transformation": "normalization"}
):
    # Perform the transformation
    # Timing information and exceptions are automatically logged
    transform_dataset(dataset123)
```

#### Audit-Provenance-Lineage Integration

The system now features comprehensive bidirectional integration between audit logging, enhanced data provenance, and cross-document lineage tracking, creating a unified governance framework:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker
from ipfs_datasets_py.audit.integration import (
    AuditProvenanceIntegrator, ProvenanceAuditSearchIntegrator, LineageAuditIntegrator
)
from ipfs_datasets_py.security import SecurityManager

# Initialize components
audit_logger = AuditLogger.get_instance()
security_manager = SecurityManager.get_instance()
provenance_manager = EnhancedProvenanceManager(
    enable_ipld_storage=True,
    enable_crypto_verification=True
)

# Create domains with security controls
finance_domain = {
    "name": "Finance",
    "domain_type": "business",
    "attributes": {
        "sensitivity": "high",
        "compliance_frameworks": ["SOX", "GDPR"],
        "security_classification": "restricted",
        "data_owner": "finance_team"
    },
    "metadata_schema": {
        "required": ["classification", "retention_period"],
        "properties": {
            "classification": {"enum": ["public", "internal", "confidential", "restricted"]},
            "retention_period": {"type": "string"}
        }
    }
}

analytics_domain = {
    "name": "Analytics",
    "domain_type": "business",
    "attributes": {
        "sensitivity": "medium",
        "security_classification": "internal",
        "data_owner": "analytics_team"
    }
}

# Set up the enhanced lineage tracker with audit and security integration
lineage_tracker = EnhancedLineageTracker(
    provenance_manager=provenance_manager,
    storage=None,  # Will create automatically
    config={
        "enable_audit_integration": True,
        "enable_semantic_detection": True,
        "enable_ipld_storage": True,
        "enable_temporal_consistency": True,
        "security_manager": security_manager,
        "domain_validation_level": "strict"  # Enforce domain boundary validation
    }
)

# Create the domains
finance_domain_id = lineage_tracker.create_domain(**finance_domain)
analytics_domain_id = lineage_tracker.create_domain(**analytics_domain)

# Create boundary with security constraints
boundary_id = lineage_tracker.create_domain_boundary(
    source_domain_id=finance_domain_id,
    target_domain_id=analytics_domain_id,
    boundary_type="data_transfer",
    attributes={
        "encryption": "AES-256",
        "access_control": "role_based",
        "data_masking": "enabled",
        "approval_required": True
    },
    constraints=[
        {"type": "field_level", "fields": ["ssn", "account_number"], "action": "mask"},
        {"type": "time_constraint", "hours": "8-17", "days": "mon-fri"},
        {"type": "approval", "approvers": ["data_governance_team"]}
    ]
)

# Set up bidirectional audit-provenance integration
audit_provenance_integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)
audit_provenance_integrator.setup_audit_event_listener()

# Set up lineage-audit integration
lineage_audit_integrator = LineageAuditIntegrator(
    audit_logger=audit_logger,
    lineage_tracker=lineage_tracker
)
lineage_audit_integrator.setup_lineage_event_listeners()

# Create an audit trail for lineage actions with security context
with audit_logger.audit_context(
    category="DATA_ACCESS",
    operation="create",
    subject="customer_data",
    status="success",
    security_context={
        "authentication": "mfa",
        "authorization": "role_based",
        "security_clearance": "confidential"
    }
):
    # Create lineage node with security attributes
    customer_data_node = lineage_tracker.create_node(
        node_type="dataset",
        metadata={
            "name": "Sensitive Customer Data",
            "format": "parquet",
            "sensitivity": "high",
            "classification": "restricted",
            "contains_pii": True,
            "retention_period": "7 years",
            "encryption": "column-level",
            "security_controls": {
                "access_restriction": "need-to-know",
                "masking_rules": ["customer_id", "ssn", "phone"]
            }
        },
        domain_id=finance_domain_id,
        entity_id="customer_data_001"
    )

# Record access and transformation with security audit integration
with audit_logger.audit_context(
    category="DATA_TRANSFORMATION",
    operation="anonymize",
    subject="customer_data_001",
    object="anonymized_data_001",
    status="success",
    details={
        "transformation_type": "anonymization",
        "fields_affected": ["customer_id", "ssn", "phone"],
        "compliance": "GDPR Article 17"
    }
):
    # Create transformation node with security context
    transform_node = lineage_tracker.create_node(
        node_type="transformation",
        metadata={
            "name": "PII Anonymization",
            "tool": "privacy_toolkit",
            "version": "2.3.1",
            "security_context": {
                "encryption_in_transit": True,
                "encryption_at_rest": True,
                "security_classification": "confidential",
                "compliance_verified": True,
                "verification_date": "2023-06-15T14:30:00Z",
                "verifier": "compliance_team"
            }
        },
        domain_id=finance_domain_id,
        entity_id="pii_anonymize_transform_001"
    )

    # Create transformation details with security requirements
    lineage_tracker.record_transformation_details(
        transformation_id=transform_node,
        operation_type="anonymization",
        inputs=[
            {"field": "customer_id", "type": "string", "sensitivity": "high", "pii": True},
            {"field": "ssn", "type": "string", "sensitivity": "high", "pii": True},
            {"field": "phone", "type": "string", "sensitivity": "high", "pii": True},
            {"field": "purchase_history", "type": "array", "sensitivity": "medium", "pii": False}
        ],
        outputs=[
            {"field": "customer_hash", "type": "string", "sensitivity": "low", "pii": False, "anonymized": True},
            {"field": "ssn", "type": "null", "removed": True},
            {"field": "phone", "type": "null", "removed": True},
            {"field": "purchase_history", "type": "array", "sensitivity": "medium", "pii": False}
        ],
        parameters={
            "anonymization_method": "sha256",
            "salt": "secure-random-salt",
            "k_anonymity": 5,
            "security_verified": True
        },
        impact_level="field"
    )

    # Create link with security attributes for governance
    lineage_tracker.create_link(
        source_id=customer_data_node,
        target_id=transform_node,
        relationship_type="input_to",
        metadata={
            "gdpr_compliant": True,
            "security_controls": {
                "access_approved_by": "data_governance_team",
                "verification_status": "verified",
                "audit_recorded": True
            }
        },
        confidence=1.0
    )

    # Create anonymized data node in analytics domain
    anonymized_data_node = lineage_tracker.create_node(
        node_type="dataset",
        metadata={
            "name": "Anonymized Customer Data",
            "format": "parquet",
            "sensitivity": "medium",
            "classification": "internal",
            "contains_pii": False,
            "retention_period": "3 years",
            "purpose_limitation": "analytics_only",
            "security_controls": {
                "access_restriction": "department-level"
            }
        },
        domain_id=analytics_domain_id,
        entity_id="anonymized_data_001"
    )

    # Create cross-domain link with boundary crossing security controls
    lineage_tracker.create_link(
        source_id=transform_node,
        target_id=anonymized_data_node,
        relationship_type="output_from",
        metadata={
            "boundary_crossing": {
                "approved_by": "data_governance_team",
                "approval_date": "2023-06-15T15:00:00Z",
                "security_validation": "passed",
                "data_quality_score": 0.98
            }
        },
        confidence=1.0,
        cross_domain=True  # Explicitly mark as cross-domain
    )

# Unified search across audit logs, provenance records, and lineage
search_integrator = ProvenanceAuditSearchIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager,
    lineage_tracker=lineage_tracker,
    security_manager=security_manager
)

# Search with security context and correlation across all systems
results = search_integrator.search(
    query={
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        },
        "resource_type": "dataset",
        "action": "transform",
        "metadata_filters": {
            "sensitivity": "high",
            "classification": "restricted"
        },
        "security_context": {
            "compliance_frameworks": ["GDPR"]
        },
        "lineage_filter": {
            "cross_domain": True,
            "relationship_types": ["input_to", "output_from"]
        }
    },
    include_audit=True,
    include_provenance=True,
    include_lineage=True,
    include_security_context=True,
    correlation_mode="comprehensive"
)

# Generate comprehensive governance report with impact analysis
report = lineage_tracker.generate_provenance_report(
    entity_id="customer_data_001",
    include_visualization=True,
    include_security_context=True,
    include_audit_trail=True,
    include_impact_analysis=True,
    format="html"
)

# Access the unified governance view
for correlation in results["correlations"]:
    print(f"Governance Correlation: {correlation['type']} between "
          f"audit event {correlation['audit_event_id']}, "
          f"provenance record {correlation['provenance_record_id']}, and "
          f"lineage node {correlation['lineage_node_id']}")
    
    # Get security implications
    if "security_implications" in correlation:
        for implication in correlation["security_implications"]:
            print(f"Security: {implication['type']} - {implication['description']}")
            
    # Get compliance implications
    if "compliance_implications" in correlation:
        for framework, status in correlation["compliance_implications"].items():
            print(f"Compliance: {framework} - {status}")

# Export lineage graph with security context to IPLD with encryption 
root_cid = lineage_tracker.export_to_ipld(
    include_domains=True,
    include_boundaries=True,
    include_versions=True,
    include_transformation_details=True,
    include_security_context=True,
    encrypt_sensitive_data=True
)
print(f"Exported secure governance data to IPLD with root CID: {root_cid}")

# Generate an integrated compliance report with lineage information
compliance_report = integrator.generate_compliance_report(
    standard="GDPR",
    include_lineage=True,
    timeline_start="2023-01-01T00:00:00Z",
    timeline_end="2023-12-31T23:59:59Z"
)

# Access detailed cross-domain lineage in compliance context
if "domain_boundaries" in compliance_report:
    print(f"Domain boundaries analyzed: {len(compliance_report['domain_boundaries'])}")
    for boundary in compliance_report['domain_boundaries']:
        print(f"Boundary {boundary['id']}: {boundary['source']} -> {boundary['target']}")
        print(f"Compliance status: {boundary['compliance_status']}")
```

#### Dataset-Specific Audit Integration

```python
from ipfs_datasets_py.audit.integration import AuditDatasetIntegrator

# Create dataset integrator
dataset_integrator = AuditDatasetIntegrator(audit_logger=audit_logger)

# Record dataset operations
dataset_integrator.record_dataset_load(
    dataset_name="example_dataset",
    dataset_id="ds123",
    source="huggingface",
    user="user123"
)

dataset_integrator.record_dataset_transform(
    input_dataset="ds123",
    output_dataset="ds123_transformed",
    transformation_type="normalize",
    parameters={"columns": ["col1", "col2"]},
    user="user123"
)

dataset_integrator.record_dataset_save(
    dataset_name="example_dataset_transformed",
    dataset_id="ds123_transformed",
    destination="ipfs",
    format="car",
    user="user123"
)
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

### Enhanced Data Classification and Policy Enforcement

The enhanced security system provides comprehensive data classification and policy enforcement capabilities:

```python
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, SecurityPolicy, DataClassification
)

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Set up data classifications for resources
classifications = {
    "customer_database": DataClassification.CONFIDENTIAL,
    "financial_reports": DataClassification.RESTRICTED,
    "product_catalog": DataClassification.INTERNAL,
    "press_releases": DataClassification.PUBLIC
}

for resource_id, classification in classifications.items():
    security_manager.set_data_classification(resource_id, classification, user_id="admin")

# Create and register security policies
# 1. Time-based access control policy
time_policy = SecurityPolicy(
    policy_id="time_access_policy",
    name="Business Hours Access Policy",
    description="Restrict access to sensitive data to business hours",
    enabled=True,
    enforcement_level="enforcing",
    rules=[
        {
            "type": "access_time",
            "allowed_hours": {"start": 8, "end": 18},
            "severity": "medium",
            "description": "Access outside business hours"
        }
    ]
)
security_manager.add_security_policy(time_policy)

# 2. Volume-based monitoring policy
volume_policy = SecurityPolicy(
    policy_id="data_volume_policy",
    name="Large Data Operation Policy",
    description="Monitor large data operations for potential data exfiltration",
    enabled=True,
    enforcement_level="enforcing",
    rules=[
        {
            "type": "data_volume",
            "threshold_bytes": 50 * 1024 * 1024,  # 50MB
            "severity": "high",
            "description": "Large data operation detected"
        }
    ]
)
security_manager.add_security_policy(volume_policy)

# 3. Classification-based access policy
classification_policy = SecurityPolicy(
    policy_id="classification_policy",
    name="Data Classification Access Policy",
    description="Enforce access controls based on data classification",
    enabled=True,
    enforcement_level="strict",
    rules=[
        {
            "type": "data_classification",
            "min_classification": "CONFIDENTIAL",
            "severity": "high",
            "description": "Access to confidential data without clearance"
        }
    ]
)
security_manager.add_security_policy(classification_policy)

# Access the policies
policies = security_manager.list_security_policies()
for policy in policies:
    print(f"Policy: {policy.name} - Rules: {len(policy.rules)}")

# Check a resource's classification
resource_id = "financial_reports"
classification = security_manager.get_data_classification(resource_id)
if classification:
    print(f"Resource {resource_id} is classified as {classification.name}")
```

### Integrated Compliance Reporting

Generate enhanced compliance reports that leverage cross-document lineage data:

```python
from ipfs_datasets_py.audit.compliance import ComplianceStandard, ComplianceRequirement
from ipfs_datasets_py.audit.integration import IntegratedComplianceReporter

# Create integrated compliance reporter with provenance data
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

# Generate enhanced report with cross-document lineage analysis
report = reporter.generate_report(
    start_time="2023-01-01T00:00:00Z",
    end_time="2023-12-31T23:59:59Z",
    include_cross_document_analysis=True,  # Enable document boundary analysis
    include_lineage_metrics=True           # Include detailed lineage metrics
)

# Access cross-document compliance insights
if "cross_document_lineage" in report.details:
    lineage_info = report.details["cross_document_lineage"]
    print(f"Document count: {lineage_info.get('document_count', 0)}")
    
    # Document boundaries information
    if "document_boundaries" in lineage_info:
        boundaries = lineage_info["document_boundaries"]
        print(f"Document boundary count: {boundaries.get('count', 0)}")
        print(f"Cross-boundary flows: {boundaries.get('cross_boundary_flow_count', 0)}")
    
    # Check for high-risk relationships 
    if "document_relationships" in lineage_info:
        relationships = lineage_info["document_relationships"]
        high_risk = relationships.get("high_risk_relationships", 0)
        if high_risk > 0:
            print(f"WARNING: {high_risk} high-risk cross-document data relationships found")
    
    # Compliance-specific insights based on document boundaries
    if "provenance_insights" in report.details:
        print("Compliance insights from cross-document analysis:")
        for insight in report.details.get("provenance_insights", []):
            print(f"- {insight}")

# Save report in various formats
report.save_json("gdpr_compliance.json")
report.save_csv("gdpr_compliance.csv")
report.save_html("gdpr_compliance.html")

# Helper function for easy report generation
from ipfs_datasets_py.audit.integration import generate_integrated_compliance_report

gdpr_report = generate_integrated_compliance_report(
    standard_name="GDPR",
    start_time="2023-01-01T00:00:00Z",
    end_time="2023-12-31T23:59:59Z",
    output_format="html",
    output_path="gdpr_report.html"
)
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

Identify and alert on potential security threats with enhanced integration:

```python
from ipfs_datasets_py.audit.intrusion import IntrusionDetection, SecurityAlertManager
from ipfs_datasets_py.audit.enhanced_security import EnhancedSecurityManager

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Create security alert manager
alert_manager = SecurityAlertManager(alert_storage_path="logs/alerts.json")

# Add an email alert handler
def email_alert_handler(alert):
    if alert.level in ['high', 'critical']:
        # Email sending logic
        print(f"ALERT: {alert.level.upper()} - {alert.description}")

alert_manager.add_notification_handler(email_alert_handler)

# Automated security response handler
def security_response_handler(alert):
    """Implement automated security responses based on alert type."""
    # For high/critical severity alerts, take automatic action
    if alert.level in ['high', 'critical']:
        # Get affected resources and users
        affected_user = alert.details.get("user")
        affected_resources = []
        
        # Implement containment strategy based on alert type
        if alert.type == "brute_force_login":
            # Temporary account lockout
            security_manager.set_enhanced_monitoring(affected_user, 60)
        
        elif alert.type == "data_exfiltration":
            # Restrict access to affected resources
            for resource in affected_resources:
                security_manager.add_temporary_access_restriction(resource, 60)

# Add the security response handler
alert_manager.add_notification_handler(security_response_handler)

# Create intrusion detection system
ids = IntrusionDetection()

# Connect IDS to alert manager
ids.add_alert_handler(alert_manager.add_alert)

# Process events through IDS
alerts = ids.process_events(recent_events)
```

The enhanced intrusion detection system can detect:
- Brute Force Login Attempts
- Multiple Access Denials
- Sensitive Data Access
- Account Compromise
- Privilege Escalation
- Data Exfiltration
- Unauthorized Configuration Changes

### Cross-Document Lineage for Security and Compliance

The enhanced cross-document lineage tracking enables powerful security and compliance capabilities:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.audit.integration import ProvenanceAuditSearchIntegrator
from ipfs_datasets_py.audit.compliance import ComplianceStandard

# Initialize with audit and provenance integration
manager = EnhancedProvenanceManager(enable_ipld_storage=True)
search = ProvenanceAuditSearchIntegrator(
    audit_logger=audit_logger,
    provenance_manager=manager
)

# Trace PII data flows across document boundaries for GDPR compliance
pii_flows = search.search(
    query={
        "document_id": "customer_data_document",
        "max_depth": 3,
        "link_types": ["contains_pii", "processes_pii", "transfers_pii", "anonymizes"],
        "timerange": {
            "start": (datetime.datetime.now() - datetime.timedelta(days=365)).isoformat(),
            "end": datetime.datetime.now().isoformat()
        }
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True  # Enable cross-document search
)

# Analyze PII data flows for compliance risks
if "cross_document_analysis" in pii_flows:
    analysis = pii_flows["cross_document_analysis"]
    print(f"Documents involved in PII processing: {analysis.get('document_count', 0)}")
    
    # Check for international transfers (GDPR risk)
    if "relationship_types" in analysis and "international_transfer" in analysis["relationship_types"]:
        print(f"WARNING: {analysis['relationship_types']['international_transfer']} international PII transfers detected")
        print("Action required: Document these transfers and ensure appropriate safeguards")
        
    # Check records with cross-document info
    for record in pii_flows.get("provenance_records", []):
        if "cross_document_info" in record:
            doc_info = record["cross_document_info"]
            print(f"Record {record['record_id']} in document {doc_info.get('document_id')}")
            print(f"  Distance from source: {doc_info.get('distance_from_source')}")
            
            # Examine relationship path to detect unauthorized flows
            if "relationship_path" in doc_info:
                path = doc_info["relationship_path"]
                for step in path:
                    if step["type"] in ["unauthorized_transfer", "high_risk_processing"]:
                        print(f"  SECURITY ALERT: Unauthorized data flow: {step['from']} --({step['type']})--> {step['to']}")
```

The enhanced cross-document lineage capabilities provide security benefits:

1. **Sensitive Data Tracing**: Follow how sensitive data moves across document boundaries
2. **Unauthorized Transfer Detection**: Identify when data crosses security boundaries improperly
3. **Security Policy Enforcement**: Verify that data flows adhere to security policies across document boundaries
4. **Compliance Documentation**: Automatically generate documentation of data flows for audits
5. **Data Leakage Prevention**: Detect potential data leakage paths across document boundaries
6. **Access Control Verification**: Ensure proper access controls at each document boundary
7. **Privacy Impact Assessment**: Support automated privacy impact assessment for cross-document processes

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

### Data Classification

- Classify all data resources according to their sensitivity level
- Use the most restrictive classification when data contains mixed sensitivity levels
- Review and update classifications regularly
- Document the justification for each classification decision
- Train users on handling data according to its classification

### Access Control

- Implement granular access controls based on least privilege principle
- Use time-bound access controls where appropriate
- Enforce multi-factor authentication for access to restricted and critical data
- Implement conditional access based on context (IP, time, purpose)
- Regularly review and audit access control configurations

### Security Policies

- Create policies that address specific security concerns
- Use different enforcement levels (advisory, enforcing, strict) based on criticality
- Monitor policy violations and adjust thresholds based on patterns
- Document the purpose and scope of each policy
- Review and update policies regularly to address emerging threats

### Encryption

- Use unique encryption keys for different data sets
- Rotate encryption keys periodically
- Store encryption keys securely (using system keyring when possible)
- Use appropriate key sizes (AES-256 for sensitive data)
- Implement key management procedures for key rotation and revocation

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
- Implement correlation between audit logs and data provenance

### Compliance

- Run compliance reports regularly
- Address non-compliant areas promptly
- Maintain documentation of compliance efforts
- Keep up to date with regulatory changes
- Leverage cross-document lineage for comprehensive compliance reporting

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

# Configure enhanced security manager
from ipfs_datasets_py.audit.enhanced_security import EnhancedSecurityManager

security_manager = EnhancedSecurityManager.get_instance()
security_manager.configure({
    "default_classification": "INTERNAL",
    "enforce_data_classification": True,
    "enforce_access_control": True,
    "enable_intrusion_detection": True,
    "enable_encryption": True,
    "default_encryption_algorithm": "AES-256-GCM"
})
```

## Additional Resources

- [Audit Logging Documentation](../ipfs_datasets_py/audit/README.md): Complete documentation for the audit logging system
- [Data Provenance Guide](../ipfs_datasets_py/provenance_reporting.md): Detailed guide on data provenance tracking and reporting
- [Security Governance Example](../examples/security_governance_example.py): Working example of security and governance features
- [Security Provenance Example](../examples/security_provenance_example.py): Complete example of security and provenance integration