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

### Intrusion Detection and Adaptive Security Response

Identify and respond to potential security threats with the enhanced integrated security system:

```python
from ipfs_datasets_py.audit.intrusion import IntrusionDetection, SecurityAlertManager
from ipfs_datasets_py.audit.enhanced_security import EnhancedSecurityManager
from ipfs_datasets_py.audit.adaptive_security import (
    AdaptiveSecurityManager, ResponseRule, ResponseAction, RuleCondition, 
    SecurityResponse
)

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Create security alert manager
alert_manager = SecurityAlertManager(alert_storage_path="logs/alerts.json")

# Create adaptive security manager for automated responses
adaptive_security = AdaptiveSecurityManager(
    security_manager=security_manager,
    alert_manager=alert_manager,
    response_storage_path="logs/security_responses.json"
)

# Add an email alert handler
def email_alert_handler(alert):
    if alert.level in ['high', 'critical']:
        # Email sending logic
        print(f"ALERT: {alert.level.upper()} - {alert.description}")

alert_manager.add_notification_handler(email_alert_handler)

# Create intrusion detection system
ids = IntrusionDetection()

# Connect IDS to alert manager
ids.add_alert_handler(alert_manager.add_alert)

# Define a custom response rule for a specific threat type
custom_rule = ResponseRule(
    rule_id="custom-sensitive-data-access",
    name="Custom Sensitive Data Access Response",
    alert_type="sensitive_data_access",
    severity_levels=["medium", "high", "critical"],
    actions=[
        {
            # Enhanced audit logging for 24 hours
            "type": "AUDIT",
            "duration_minutes": 1440,
            "parameters": {
                "user_id": "{{alert.user_id}}",
                "level": "forensic",
                "reason": "Suspicious sensitive data access"
            }
        },
        {
            # Throttle access for 2 hours
            "type": "THROTTLE",
            "duration_minutes": 120,
            "parameters": {
                "user_id": "{{alert.user_id}}",
                "resource_type": "sensitive_data",
                "rate_limit": 5,  # 5 requests per minute
                "reason": "Unusual sensitive data access pattern"
            }
        },
        {
            # Notify security team
            "type": "NOTIFY",
            "parameters": {
                "recipient": "security_team",
                "message": "Suspicious sensitive data access detected",
                "severity": "{{alert.severity}}",
                "include_details": True
            }
        }
    ],
    conditions=[
        # Multiple conditions that can be evaluated
        RuleCondition("alert.user_type", "in", ["new_user", "contractor", "external"]),
        RuleCondition("alert.resource_type", "in", ["financial", "personal_data", "credentials"]),
        RuleCondition("alert.access_count", ">=", 10)
    ],
    description="Enhanced response for suspicious sensitive data access by high-risk users"
)

# Add the custom rule to the adaptive security manager
adaptive_security.add_rule(custom_rule)

# Process events through IDS
alerts = ids.process_events(recent_events)

# Process any pending alerts
processed_count = adaptive_security.process_pending_alerts()
print(f"Processed {processed_count} pending alerts")

# The adaptive security manager will automatically:
# 1. Receive alerts from the alert manager
# 2. Match alerts against response rules
# 3. Execute appropriate response actions
# 4. Log all responses to the audit system
# 5. Store response history for future reference

# Check active security responses
active_responses = adaptive_security.get_active_responses()
print(f"Active security responses: {len(active_responses)}")

# Get responses for a specific user
user_responses = adaptive_security.get_active_responses(target="suspicious_user")
for response in user_responses:
    print(f"Response {response.response_id}: {response.response_type.name} until {response.expires_at}")

# Create a manual response
manual_response = SecurityResponse(
    response_id="manual-response-001",
    alert_id="manual-alert",
    rule_id="manual-rule",
    rule_name="Manual Response Rule",
    response_type=ResponseAction.ISOLATE,
    created_at=datetime.datetime.now().isoformat(),
    expires_at=(datetime.datetime.now() + timedelta(hours=2)).isoformat(),
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

# Cancel a response if needed
if user_responses:
    adaptive_security.cancel_response(user_responses[0].response_id)
    
# Check for expired responses
expired_count = adaptive_security.check_expired_responses()
print(f"Found {expired_count} expired responses")
```

The Adaptive Security Response System provides an advanced framework for automated security responses based on detected threats:

#### Response Actions

The system supports multiple types of automated responses:

- **MONITOR**: Enhanced monitoring of users or resources
- **RESTRICT**: Access restrictions for users or resources
- **THROTTLE**: Rate limiting for specific operations
- **LOCKOUT**: Temporary account lockout
- **ISOLATE**: Resource isolation to contain threats
- **NOTIFY**: Security notifications to appropriate teams
- **ESCALATE**: Security incident escalation
- **ROLLBACK**: Configuration rollback
- **SNAPSHOT**: Security snapshots for forensics
- **ENCRYPT**: Enforce encryption for sensitive data
- **AUDIT**: Enhanced audit logging

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
                "user_id": "$user",  # Dynamic parameter from alert
                "reason": "Potential data exfiltration"
            }
        },
        {
            "type": "AUDIT",  # Enhanced auditing
            "duration_minutes": 4320,  # 3 days
            "parameters": {
                "user_id": "$user",
                "level": "forensic",
                "reason": "Data exfiltration investigation"
            }
        },
        {
            "type": "ESCALATE",  # Escalate to incident response
            "parameters": {
                "priority": "high",
                "team": "security_incident_response",
                "message": "Potential data exfiltration detected"
            }
        }
    ],
    description="Respond to potential data exfiltration with access restriction and enhanced auditing"
)

# Add the rule to the adaptive security manager
adaptive_security.add_response_rule(exfiltration_rule)
```

#### Dynamic Response Parameters

Response actions can include dynamic parameters extracted from the security alert:

```python
# Rule with dynamic parameters
rule = ResponseRule(
    rule_id="brute-force-response",
    name="Brute Force Login Response",
    alert_type="brute_force_login",
    severity_levels=["medium", "high", "critical"],
    actions=[
        {
            "type": "LOCKOUT",
            "duration_minutes": 30,
            "parameters": {
                "user_id": "$user",  # Will be replaced with alert.details["user"]
                "source_ip": "$source_ip",  # Will be replaced with alert.details["source_ip"]
                "failure_count": "$failure_count",  # Will be replaced with alert.details["failure_count"]
                "reason": "Brute force login detection"
            }
        }
    ]
)
```

#### Conditional Rules

Rules can include additional conditions to fine-tune when they apply:

```python
# Rule with conditions
conditional_rule = ResponseRule(
    rule_id="admin-account-protection",
    name="Admin Account Protection",
    alert_type="brute_force_login",
    severity_levels=["medium", "high"],
    actions=[
        {
            "type": "LOCKOUT",
            "duration_minutes": 60,  # Longer lockout for admin accounts
        },
        {
            "type": "NOTIFY",
            "parameters": {
                "recipient": "security_admin",
                "message": "Admin account brute force attempt",
                "severity": "critical"  # Higher severity notification
            }
        }
    ],
    conditions={
        "user": ["admin", "root", "system"],  # Only for these users
        "failure_count": lambda x: x > 3  # Custom condition function
    }
)
```

#### Response Lifecycle Management

The system automatically manages the lifecycle of security responses:

1. **Creation**: Responses are created when alerts match rules
2. **Activation**: Responses are immediately activated and logged
3. **Monitoring**: Active responses are tracked in memory and storage
4. **Expiration**: Responses automatically expire after their duration
5. **Cancellation**: Responses can be manually cancelled if needed

This provides a complete audit trail of security responses and ensures temporary security measures are properly applied and removed.

The enhanced intrusion detection system can detect:
- Brute Force Login Attempts
- Multiple Access Denials
- Sensitive Data Access
- Account Compromise
- Privilege Escalation
- Data Exfiltration
- Unauthorized Configuration Changes

### Cross-Document Lineage for Security and Compliance

The enhanced cross-document lineage tracking enables powerful security and compliance capabilities through the integration of detailed lineage tracking:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.audit.integration import ProvenanceAuditSearchIntegrator
from ipfs_datasets_py.audit.compliance import ComplianceStandard
from ipfs_datasets_py.cross_document_lineage import CrossDocumentLineageTracker, LinkType
from ipfs_datasets_py.cross_document_lineage_enhanced import DetailedLineageIntegrator

# Initialize components
audit_logger = AuditLogger.get_instance()
provenance_manager = EnhancedProvenanceManager(enable_ipld_storage=True)
lineage_tracker = CrossDocumentLineageTracker(
    provenance_storage=provenance_manager,
    audit_logger=audit_logger,
    link_verification=True,  # Enable cryptographic verification of links
    min_confidence_threshold=0.85  # Set minimum confidence threshold for links
)

# Create detailed lineage integrator for enhanced capabilities
lineage_integrator = DetailedLineageIntegrator(
    provenance_manager=provenance_manager,
    lineage_tracker=lineage_tracker,
    semantic_detection_level="high",  # Enable high-level semantic detection
    flow_pattern_analysis=True  # Enable flow pattern analysis
)

# Create unified search integrator
search = ProvenanceAuditSearchIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager,
    lineage_tracker=lineage_tracker,  # Include lineage tracker for enhanced capabilities
    lineage_integrator=lineage_integrator  # Include the new detailed lineage integrator
)

# Create detailed lineage with semantic relationship enrichment
integrated_lineage = lineage_integrator.integrate_provenance_with_lineage(
    provenance_graph=provenance_manager.get_provenance_graph(),
    lineage_graph=lineage_tracker.get_lineage_graph()
)

# Use the enhanced provenance manager to create detailed cross-document lineage
detailed_lineage = provenance_manager.create_cross_document_lineage(
    output_path="cross_document_lineage_report.html",
    include_visualization=True
)

# Perform advanced security analysis with semantic understanding
security_insights = lineage_integrator.analyze_security_boundaries(
    integrated_lineage,
    include_semantic_analysis=True,
    include_flow_patterns=True,
    detect_security_anomalies=True
)

# Trace PII data flows across document boundaries for GDPR compliance
pii_flows = search.search(
    query={
        "document_id": "customer_data_document",
        "max_depth": 3,
        "link_types": [LinkType.CONTAINS_PII, LinkType.PROCESSES, LinkType.ANONYMIZES],
        "min_confidence": 0.9,  # Only include high-confidence links
        "timerange": {
            "start": (datetime.datetime.now() - datetime.timedelta(days=365)).isoformat(),
            "end": datetime.datetime.now().isoformat()
        },
        "security_context": {  # Add security context for more accurate analysis
            "classification_min": "CONFIDENTIAL",
            "require_verification": True
        },
        "semantic_context": {  # New semantic analysis capabilities
            "relationship_semantics": ["transfers", "processes", "anonymizes"],
            "detect_implied_relationships": True,
            "confidence_threshold": 0.75
        }
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True,  # Enable cross-document search
    include_security_context=True,  # Include security information
    include_detailed_lineage=True  # Use new detailed lineage capabilities
)

# Analyze PII data flows for compliance risks with enhanced detection
if "cross_document_analysis" in pii_flows:
    analysis = pii_flows["cross_document_analysis"]
    print(f"Documents involved in PII processing: {analysis.get('document_count', 0)}")
    
    # Get flow pattern insights from the new analysis capabilities
    if "flow_patterns" in analysis:
        patterns = analysis["flow_patterns"]
        print(f"Identified {len(patterns)} common flow patterns in PII processing")
        for pattern in patterns:
            print(f"Flow pattern: {pattern['name']} (confidence: {pattern['confidence']})")
            print(f"  Security impact: {pattern['security_impact']}")
            print(f"  Compliance impact: {pattern['compliance_impact']}")
    
    # Check for international transfers (GDPR risk)
    if "relationship_types" in analysis and LinkType.INTERNATIONAL_TRANSFER in analysis["relationship_types"]:
        transfer_count = analysis["relationship_types"][LinkType.INTERNATIONAL_TRANSFER]
        print(f"WARNING: {transfer_count} international PII transfers detected")
        print("Action required: Document these transfers and ensure appropriate safeguards")
        
    # Check for cross-domain transfers without proper anonymization
    if "security_insights" in analysis:
        insights = analysis["security_insights"]
        if "pii_transfer_without_anonymization" in insights and insights["pii_transfer_without_anonymization"] > 0:
            print(f"CRITICAL: {insights['pii_transfer_without_anonymization']} PII transfers without proper anonymization")
            print("Action required: Implement anonymization before transfer or obtain explicit consent")
            
        # New detailed document boundary analysis
        if "document_boundaries" in insights:
            boundaries = insights["document_boundaries"]
            print(f"Document boundaries analyzed: {len(boundaries)}")
            for boundary in boundaries:
                print(f"Boundary: {boundary['source']} -> {boundary['target']}")
                print(f"  Security classification: {boundary['security_classification']}")
                print(f"  Security controls: {', '.join(boundary['security_controls'])}")
                if boundary.get('potential_data_leakage', False):
                    print(f"  ⚠️ ALERT: Potential data leakage path detected")
                    print(f"  Recommended action: {boundary['recommended_action']}")
        
    # Check records with cross-document info
    for record in pii_flows.get("provenance_records", []):
        if "cross_document_info" in record:
            doc_info = record["cross_document_info"]
            print(f"Record {record['record_id']} in document {doc_info.get('document_id')}")
            print(f"  Distance from source: {doc_info.get('distance_from_source')}")
            print(f"  Confidence: {doc_info.get('confidence', 'unknown')}")
            
            # Examine relationship path to detect unauthorized flows
            if "relationship_path" in doc_info:
                path = doc_info["relationship_path"]
                for step in path:
                    if step["type"] in [LinkType.UNAUTHORIZED_TRANSFER, LinkType.HIGH_RISK_PROCESSING]:
                        print(f"  SECURITY ALERT: Unauthorized data flow: {step['from']} --({step['type']})--> {step['to']}")
                        
                    # Show verification status for each step in the path
                    if "verification" in step:
                        verification = step["verification"]
                        status = "✓ Verified" if verification.get("verified", False) else "⚠ Not verified"
                        print(f"    Verification: {status} ({verification.get('method', 'unknown')})")
                    
                    # New: Show semantic relationship insights
                    if "semantic_insights" in step:
                        semantics = step["semantic_insights"]
                        print(f"    Semantic relationship: {semantics.get('relationship_type', 'unknown')}")
                        print(f"    Data context: {semantics.get('data_context', 'unknown')}")
                        print(f"    Semantic confidence: {semantics.get('confidence', 0.0)}")

# Generate a comprehensive security lineage report with detailed insights
security_report = lineage_integrator.generate_detailed_security_report(
    integrated_lineage=integrated_lineage,
    document_id="customer_data_document",
    include_semantic_analysis=True,
    include_flow_patterns=True,
    include_boundary_analysis=True,
    output_format="html",
    output_path="security_lineage_report.html"
)
```

#### Enhanced Security Features of Cross-Document Lineage

The cross-document lineage system provides comprehensive security and compliance capabilities through its specialized link types and verification mechanisms:

```python
from ipfs_datasets_py.cross_document_lineage import CrossDocumentLineageTracker, LinkType, SecurityLinkAnalyzer
from ipfs_datasets_py.audit.integration import LineagePolicyEnforcer
from ipfs_datasets_py.security import SecurityManager

# Initialize components
security_manager = SecurityManager.get_instance()
lineage_tracker = CrossDocumentLineageTracker(
    provenance_storage=provenance_manager,
    audit_logger=audit_logger,
    link_verification=True
)

# Create a security analyzer for cross-document links
security_analyzer = SecurityLinkAnalyzer(
    lineage_tracker=lineage_tracker,
    security_manager=security_manager
)

# Define security policies for cross-document links
policy_enforcer = LineagePolicyEnforcer(
    audit_logger=audit_logger,
    lineage_tracker=lineage_tracker
)

# Add a data classification preservation policy
policy_enforcer.add_policy({
    "id": "SEC-001",
    "name": "Classification Preservation Policy",
    "description": "Data flowing to lower classification domains must be properly sanitized",
    "rule": {
        "condition": {
            "source_classification": ["CONFIDENTIAL", "RESTRICTED"],
            "target_classification": ["INTERNAL", "PUBLIC"]
        },
        "requirement": {
            "intermediate_link_types": [LinkType.ANONYMIZES, LinkType.SANITIZES, LinkType.DECLASSIFIES],
            "required": True,
            "verified": True
        }
    },
    "action": {
        "if_violated": {
            "log_level": "WARNING",
            "notification": ["security@example.com"],
            "remediation": "Insert proper anonymization or declassification step"
        }
    }
})

# Create security-enhanced links with verification
source_doc = "financial_data_document"  # CONFIDENTIAL classification
target_doc = "analytics_document"       # INTERNAL classification

# Create a proper flow with anonymization
anonymize_link = lineage_tracker.create_link(
    source_document_id=source_doc,
    target_document_id="anonymized_data",
    link_type=LinkType.ANONYMIZES,
    confidence=0.98,
    metadata={
        "anonymization_method": "k-anonymity",
        "k_value": 5,
        "fields_anonymized": ["customer_id", "account_number"],
        "verified_by": "data_privacy_officer",
        "verification_date": datetime.datetime.now().isoformat()
    },
    security_context={
        "source_classification": "CONFIDENTIAL",
        "target_classification": "INTERNAL",
        "requires_approval": True,
        "approval_status": "APPROVED",
        "approved_by": "compliance_team"
    },
    sign=True  # Cryptographically sign this link
)

# Create link from anonymized data to analytics document
analytics_link = lineage_tracker.create_link(
    source_document_id="anonymized_data",
    target_document_id=target_doc,
    link_type=LinkType.DERIVED_FROM,
    confidence=0.95,
    metadata={
        "transformation": "aggregation",
        "purpose": "quarterly_analytics"
    },
    security_context={
        "source_classification": "INTERNAL",
        "target_classification": "INTERNAL"
    },
    sign=True
)

# Verify the entire chain meets security policies
verification_result = policy_enforcer.verify_path_compliance(
    source_document_id=source_doc,
    target_document_id=target_doc
)

print(f"Path compliance: {'Compliant' if verification_result['compliant'] else 'Non-compliant'}")
if not verification_result['compliant']:
    for violation in verification_result['violations']:
        print(f"Violation: {violation['policy_id']} - {violation['description']}")
        print(f"Severity: {violation['severity']}")
        print(f"Remediation: {violation['remediation']}")

# Create a comprehensive security report for cross-document flows
security_report = security_analyzer.generate_security_report(
    document_id=source_doc,
    include_downstream=True,
    max_depth=3,
    include_verification=True,
    include_audit_events=True
)

# Export the security report
with open("cross_document_security_report.json", "w") as f:
    json.dump(security_report, f, indent=2)

# Generate visualization with security highlights
visualization = lineage_tracker.generate_visualization_data(
    document_id=source_doc,
    include_downstream=True,
    max_depth=3,
    highlight_security_issues=True,
    include_verification_status=True
)

# Verify cryptographic integrity of a document's complete lineage
crypto_verification = lineage_tracker.verify_document_lineage(
    document_id=target_doc,
    include_upstream=True,
    include_downstream=False,
    max_depth=3
)

print(f"Lineage verification: {'Verified' if crypto_verification['verified'] else 'Failed'}")
print(f"Links verified: {crypto_verification['links_verified']}")
print(f"Links with issues: {crypto_verification['links_with_issues']}")

# If verification fails, log security incident
if not crypto_verification['verified']:
    audit_logger.log(
        level="CRITICAL",
        category="SECURITY",
        action="lineage_verification_failed",
        resource_id=target_doc,
        resource_type="document",
        details={
            "verification_result": crypto_verification,
            "affected_links": crypto_verification['links_with_issues']
        }
    )
```

#### Security-Enhanced Link Types

The cross-document lineage system provides specialized link types for security and compliance purposes:

```python
from ipfs_datasets_py.cross_document_lineage import LinkType, CrossDocumentLineageTracker

# Create links with security-specific link types
lineage_tracker = CrossDocumentLineageTracker(
    provenance_storage=provenance_manager,
    audit_logger=audit_logger
)

# Personal data protection links
pii_link = lineage_tracker.create_link(
    source_document_id="customer_database",
    target_document_id="pii_dataset",
    link_type=LinkType.CONTAINS_PII,
    confidence=0.99,
    metadata={
        "pii_types": ["name", "email", "address", "phone", "dob"],
        "has_consent": True,
        "consent_reference": "CONSENT-456789",
        "legal_basis": "GDPR Art. 6(1)(a)",
        "data_controller": "Example Corp",
        "retention_period": "24 months"
    }
)

# Data sanitization and anonymization links
anonymization_link = lineage_tracker.create_link(
    source_document_id="pii_dataset",
    target_document_id="anonymized_dataset",
    link_type=LinkType.ANONYMIZES,
    confidence=0.97,
    metadata={
        "anonymization_method": "k-anonymity",
        "k_value": 5,
        "techniques": ["generalization", "suppression"],
        "fields_anonymized": ["name", "email", "address", "phone", "dob"],
        "tools_used": ["anonymization_toolkit_v3"],
        "verified_by": "privacy_officer",
        "verification_date": "2023-06-20T14:30:00Z"
    }
)

# International transfer links with appropriate safeguards
transfer_link = lineage_tracker.create_link(
    source_document_id="anonymized_dataset",
    target_document_id="eu_to_us_transfer",
    link_type=LinkType.INTERNATIONAL_TRANSFER,
    confidence=0.95,
    metadata={
        "source_jurisdiction": "EU",
        "target_jurisdiction": "US",
        "transfer_mechanism": "standard_contractual_clauses",
        "transfer_date": "2023-06-22T09:15:00Z",
        "safeguards": ["encryption", "access_controls", "sccs"],
        "impact_assessment": "DPIA-2023-005",
        "approved_by": "legal_department"
    }
)

# Declassification links for changing security classifications
declassify_link = lineage_tracker.create_link(
    source_document_id="classified_document",
    target_document_id="public_document",
    link_type=LinkType.DECLASSIFIES,
    confidence=0.99,
    metadata={
        "original_classification": "CONFIDENTIAL",
        "new_classification": "PUBLIC",
        "declassification_authority": "security_committee",
        "declassification_date": "2023-06-25T11:00:00Z",
        "review_process": "multi_level_review",
        "approval_reference": "DECL-2023-078"
    }
)

# Query for all links related to personal data protection
personal_data_links = lineage_tracker.query_links(
    link_types=[
        LinkType.CONTAINS_PII,
        LinkType.ANONYMIZES,
        LinkType.PROCESSES_PII,
        LinkType.INTERNATIONAL_TRANSFER
    ],
    min_confidence=0.9
)

print(f"Found {len(personal_data_links)} links related to personal data protection")
```

The enhanced cross-document lineage capabilities provide comprehensive security benefits:

1. **Sensitive Data Tracing**: Follow how sensitive data moves across document boundaries with cryptographic verification at each step
2. **Unauthorized Transfer Detection**: Identify when data crosses security boundaries improperly with confidence scoring and automated alerts
3. **Security Policy Enforcement**: Verify that data flows adhere to security policies across document boundaries with specialized link types
4. **Compliance Documentation**: Automatically generate documentation of data flows for audits with complete verification metadata
5. **Data Leakage Prevention**: Detect potential data leakage paths across document boundaries with integration to security monitoring
6. **Access Control Verification**: Ensure proper access controls at each document boundary with security context propagation
7. **Privacy Impact Assessment**: Support automated privacy impact assessment for cross-document processes with specialized PII link types
8. **Classification Management**: Track and enforce data classification rules across document boundaries
9. **Cryptographic Verification**: Ensure data lineage integrity with cryptographic signing and verification
10. **Security Visualization**: Generate visual representations of data flows with security highlights for risk assessment
11. **Automated Policy Enforcement**: Apply and verify security policies across document boundaries programmatically

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