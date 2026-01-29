"""
Security and Provenance Integration Example

This example demonstrates how to use the security and provenance integration
features to create a secure data transformation pipeline with comprehensive
tracking of both security and provenance information.
"""

import uuid
import logging
import datetime
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import security and provenance components
from ipfs_datasets_py.audit.audit_logger import AuditLogger
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, DataClassification, AccessDecision,
    SecurityPolicy, AccessControlEntry, SecuritySession
)
from ipfs_datasets_py.audit.security_provenance_integration import (
    SecurityProvenanceIntegrator, secure_provenance_operation
)

# Try to import provenance module
try:
    from ipfs_datasets_py.analytics.data_provenance_enhanced import EnhancedProvenanceManager
    PROVENANCE_AVAILABLE = True
except ImportError:
    PROVENANCE_AVAILABLE = False
    logger.warning("Data provenance module not available. Some features will be disabled.")


def setup_security_environment():
    """Set up a security environment with classifications and access controls."""
    logger.info("Setting up security environment...")

    # Get security manager
    security_manager = EnhancedSecurityManager.get_instance()

    # Create sample data resources
    resources = {
        "raw_data": "dataset_raw_001",
        "processed_data": "dataset_processed_001",
        "anonymized_data": "dataset_anonymized_001",
        "report": "report_001"
    }

    # Set up data classifications
    security_manager.set_data_classification(
        resource_id=resources["raw_data"],
        classification=DataClassification.CONFIDENTIAL,
        user_id="admin"
    )

    security_manager.set_data_classification(
        resource_id=resources["processed_data"],
        classification=DataClassification.CONFIDENTIAL,
        user_id="admin"
    )

    security_manager.set_data_classification(
        resource_id=resources["anonymized_data"],
        classification=DataClassification.INTERNAL,
        user_id="admin"
    )

    security_manager.set_data_classification(
        resource_id=resources["report"],
        classification=DataClassification.PUBLIC,
        user_id="admin"
    )

    # Set up access control entries

    # Data scientist can read raw data and read/write processed data
    data_scientist_raw_ace = AccessControlEntry(
        resource_id=resources["raw_data"],
        resource_type="dataset",
        principal_id="data_scientist",
        principal_type="role",
        permissions=["read"],
        conditions={"ip_range": "192.168.1.0/24"}
    )
    security_manager.add_access_control_entry(data_scientist_raw_ace, "admin")

    data_scientist_processed_ace = AccessControlEntry(
        resource_id=resources["processed_data"],
        resource_type="dataset",
        principal_id="data_scientist",
        principal_type="role",
        permissions=["read", "write"],
        conditions={"ip_range": "192.168.1.0/24"}
    )
    security_manager.add_access_control_entry(data_scientist_processed_ace, "admin")

    # Privacy officer can access all data
    privacy_officer_ace = AccessControlEntry(
        resource_id=resources["raw_data"],
        resource_type="dataset",
        principal_id="privacy_officer",
        principal_type="role",
        permissions=["read", "write", "delete"],
        conditions={}
    )
    security_manager.add_access_control_entry(privacy_officer_ace, "admin")

    privacy_officer_processed_ace = AccessControlEntry(
        resource_id=resources["processed_data"],
        resource_type="dataset",
        principal_id="privacy_officer",
        principal_type="role",
        permissions=["read", "write", "delete"],
        conditions={}
    )
    security_manager.add_access_control_entry(privacy_officer_processed_ace, "admin")

    privacy_officer_anonymized_ace = AccessControlEntry(
        resource_id=resources["anonymized_data"],
        resource_type="dataset",
        principal_id="privacy_officer",
        principal_type="role",
        permissions=["read", "write", "delete"],
        conditions={}
    )
    security_manager.add_access_control_entry(privacy_officer_anonymized_ace, "admin")

    # Analyst can only access anonymized data and reports
    analyst_ace = AccessControlEntry(
        resource_id=resources["anonymized_data"],
        resource_type="dataset",
        principal_id="analyst",
        principal_type="role",
        permissions=["read"],
        conditions={}
    )
    security_manager.add_access_control_entry(analyst_ace, "admin")

    analyst_report_ace = AccessControlEntry(
        resource_id=resources["report"],
        resource_type="dataset",
        principal_id="analyst",
        principal_type="role",
        permissions=["read", "write"],
        conditions={}
    )
    security_manager.add_access_control_entry(analyst_report_ace, "admin")

    # Create provenance-based security policy
    if PROVENANCE_AVAILABLE:
        integrator = SecurityProvenanceIntegrator()

        # Policy enforcing lineage verification for anonymized data
        lineage_rules = [
            {
                "type": "lineage_verification",
                "required_verification": True,
                "min_verified_percentage": 75,
                "severity": "high",
                "description": "Requires verified data lineage for anonymized data"
            },
            {
                "type": "transformation_chain",
                "required_transformations": ["anonymize"],
                "prohibited_transformations": [],
                "max_chain_length": 5,
                "severity": "high",
                "description": "Requires anonymization in transformation chain"
            }
        ]

        integrator.create_provenance_based_security_policy(
            policy_id="anonymized_data_policy",
            name="Anonymized Data Lineage Policy",
            resource_pattern="dataset_anonymized_*",
            lineage_rules=lineage_rules,
            user_id="admin"
        )

    return resources


def record_data_transformations(resources, user_id="alice"):
    """
    Record a series of data transformations with security and provenance tracking.

    Args:
        resources: Dictionary of resource IDs
        user_id: User performing the operations
    """
    if not PROVENANCE_AVAILABLE:
        logger.error("Provenance module not available. Cannot record transformations.")
        return

    logger.info(f"Recording data transformations for user {user_id}...")

    # Get integrator
    integrator = SecurityProvenanceIntegrator()

    # Record data transformations with secure provenance
    with SecuritySession(user_id=user_id, action="data_processing"):
        # Step 1: Record loading of raw data
        try:
            record_id = integrator.record_secure_transformation(
                input_ids=["external_source_001"],
                output_id=resources["raw_data"],
                transformation_type="load",
                parameters={
                    "source": "external_api",
                    "format": "json",
                    "record_count": 10000
                },
                user_id=user_id,
                verify_lineage=False,  # No upstream lineage to verify for raw data
                classification=DataClassification.CONFIDENTIAL
            )

            logger.info(f"Recorded raw data loading: {record_id}")
        except PermissionError as e:
            logger.error(f"Permission error: {e}")
            return

        # Step 2: Record data processing
        try:
            record_id = integrator.record_secure_transformation(
                input_ids=[resources["raw_data"]],
                output_id=resources["processed_data"],
                transformation_type="process",
                parameters={
                    "operations": ["clean", "normalize", "transform"],
                    "fields_processed": ["name", "address", "phone", "email"],
                    "processing_timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
                },
                user_id=user_id,
                verify_lineage=True,
                classification=DataClassification.CONFIDENTIAL
            )

            logger.info(f"Recorded data processing: {record_id}")

            # Add security metadata to the record
            integrator.add_security_metadata_to_record(record_id, user_id)
        except PermissionError as e:
            logger.error(f"Permission error: {e}")
            return

        # Step 3: Record data anonymization
        try:
            record_id = integrator.record_secure_transformation(
                input_ids=[resources["processed_data"]],
                output_id=resources["anonymized_data"],
                transformation_type="anonymize",
                parameters={
                    "method": "differential_privacy",
                    "epsilon": 0.1,
                    "fields_anonymized": ["name", "address", "phone", "email"],
                    "anonymization_timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
                },
                user_id=user_id,
                verify_lineage=True,
                classification=DataClassification.INTERNAL
            )

            logger.info(f"Recorded data anonymization: {record_id}")

            # Add security metadata to the record
            integrator.add_security_metadata_to_record(record_id, user_id)
        except PermissionError as e:
            logger.error(f"Permission error: {e}")
            return

        # Step 4: Record report generation
        try:
            record_id = integrator.record_secure_transformation(
                input_ids=[resources["anonymized_data"]],
                output_id=resources["report"],
                transformation_type="report",
                parameters={
                    "report_type": "summary_statistics",
                    "report_format": "pdf",
                    "generated_at": datetime.datetime.utcnow().isoformat() + 'Z'
                },
                user_id=user_id,
                verify_lineage=True,
                classification=DataClassification.PUBLIC
            )

            logger.info(f"Recorded report generation: {record_id}")
        except PermissionError as e:
            logger.error(f"Permission error: {e}")
            return


@secure_provenance_operation(user_id_arg="user_id", data_id_arg="resource_id")
def access_data_with_lineage_check(user_id, resource_id):
    """
    Access data with lineage-based security checks.

    This function is decorated with secure_provenance_operation to automatically
    check access permissions based on data lineage before allowing access.

    Args:
        user_id: The user accessing the data
        resource_id: The resource being accessed
    """
    logger.info(f"User {user_id} accessing {resource_id} with lineage check...")

    # This operation only runs if access is allowed based on lineage checks
    # The function body would contain the actual data access logic
    return {
        "status": "success",
        "message": f"Access to {resource_id} granted with lineage verification",
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }


def verify_cross_document_security(user_id="security_officer"):
    """
    Perform cross-document security verification.

    This function demonstrates how to use the integrator to verify security
    across document boundaries.

    Args:
        user_id: User performing the verification
    """
    if not PROVENANCE_AVAILABLE:
        logger.error("Provenance module not available. Cannot verify cross-document security.")
        return

    logger.info(f"Verifying cross-document security for user {user_id}...")

    # Get integrator
    integrator = SecurityProvenanceIntegrator()

    # Define document IDs for verification
    document_ids = [
        "document_001",  # Containing raw data
        "document_002",  # Containing processed data
        "document_003"   # Containing anonymized data
    ]

    # Perform verification
    try:
        results = integrator.verify_cross_document_security(document_ids, user_id)

        # Log results
        logger.info(f"Cross-document verification results:")
        logger.info(f"  - Documents analyzed: {results.get('document_count', 0)}")
        logger.info(f"  - Boundaries found: {results.get('boundary_count', 0)}")
        logger.info(f"  - Cross-boundary flows: {results.get('cross_boundary_flows', 0)}")
        logger.info(f"  - Security issues: {len(results.get('security_issues', []))}")
        logger.info(f"  - Secure: {results.get('is_secure', False)}")

        # Report security issues if any
        if results.get('security_issues'):
            logger.warning("Security issues found:")
            for i, issue in enumerate(results['security_issues']):
                logger.warning(f"  {i+1}. {issue['type']} - {issue['description']} (Severity: {issue['severity']})")

    except Exception as e:
        logger.error(f"Error during cross-document verification: {e}")


def query_provenance_with_security(user_id="analyst"):
    """
    Perform a secure provenance query.

    This function demonstrates how to query provenance records with security
    filtering based on the user's permissions.

    Args:
        user_id: User performing the query
    """
    if not PROVENANCE_AVAILABLE:
        logger.error("Provenance module not available. Cannot query provenance.")
        return

    logger.info(f"Performing secure provenance query for user {user_id}...")

    # Get integrator
    integrator = SecurityProvenanceIntegrator()

    # Define query parameters
    query_params = {
        "record_type": "transformation",
        "transformation_type": "anonymize"
    }

    # Perform secure query
    try:
        results = integrator.secure_provenance_query(
            query_params=query_params,
            user_id=user_id,
            include_cross_document=True
        )

        # Log results
        logger.info(f"Secure provenance query results:")
        logger.info(f"  - Total records found: {results.get('total_records', 0)}")
        logger.info(f"  - Records accessible to user: {results.get('filtered_records', 0)}")

        # Display accessible records
        if results.get('records'):
            logger.info("Accessible records:")
            for i, record in enumerate(results['records']):
                # Extract key information
                record_id = record.get('record_id', 'Unknown')
                record_type = record.get('record_type', 'Unknown')
                classification = record.get('security', {}).get('classification', 'UNCLASSIFIED')

                logger.info(f"  {i+1}. Record {record_id} ({record_type}) - Classification: {classification}")

        # Report cross-document analysis if included
        if results.get('cross_document_analysis'):
            analysis = results['cross_document_analysis']
            logger.info("Cross-document analysis:")
            logger.info(f"  - Documents analyzed: {analysis.get('document_count', 0)}")
            logger.info(f"  - Security issues: {len(analysis.get('security_issues', []))}")

    except Exception as e:
        logger.error(f"Error during secure provenance query: {e}")


def main():
    """Run the security and provenance integration example."""
    logger.info("Starting Security and Provenance Integration Example")

    # Set up the security environment
    resources = setup_security_environment()
    logger.info(f"Security environment set up with resources: {resources}")

    # Record data transformations as data scientist
    record_data_transformations(resources, user_id="alice")

    # Access data with lineage check
    try:
        result = access_data_with_lineage_check(
            user_id="bob",
            resource_id=resources["anonymized_data"]
        )
        logger.info(f"Data access result: {result}")
    except PermissionError as e:
        logger.warning(f"Data access denied: {e}")

    # Verify cross-document security
    verify_cross_document_security()

    # Query provenance with security filtering
    query_provenance_with_security()

    logger.info("Security and Provenance Integration Example Complete")


if __name__ == "__main__":
    main()
