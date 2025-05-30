"""
Security and Governance Example

This example demonstrates how to use the enhanced security and governance features,
including data classification, access control, policy enforcement, and secure operations.
"""

import os
import json
import datetime
import logging
from typing import Dict, Any, Optional

from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, SecurityPolicy, AccessControlEntry, DataClassification,
    DataEncryptionConfig, AccessDecision, SecuritySession, security_operation
)


# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()


def setup_security_environment():
    """Set up a security environment with policies, classifications, and access controls."""
    logger.info("Setting up security environment...")

    # 1. Create security policies
    data_access_policy = SecurityPolicy(
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

    security_manager.add_security_policy(data_access_policy)
    logger.info(f"Added security policy: {data_access_policy.name}")

    # 2. Set up data classifications
    resources_to_classify = {
        "customer_data": DataClassification.CONFIDENTIAL,
        "financial_reports": DataClassification.RESTRICTED,
        "product_documentation": DataClassification.INTERNAL,
        "marketing_materials": DataClassification.PUBLIC,
        "encryption_keys": DataClassification.CRITICAL
    }

    for resource_id, classification in resources_to_classify.items():
        security_manager.set_data_classification(resource_id, classification)
        logger.info(f"Classified {resource_id} as {classification.name}")

    # 3. Configure access controls
    # Admin user with full access
    admin_ace = AccessControlEntry(
        resource_id="*",  # Wildcard for all resources
        resource_type="*",
        principal_id="admin_user",
        principal_type="user",
        permissions=["read", "write", "update", "delete", "admin"]
    )
    security_manager.add_access_control_entry(admin_ace)

    # Regular user with limited access
    user_ace = AccessControlEntry(
        resource_id="product_documentation",
        resource_type="document",
        principal_id="regular_user",
        principal_type="user",
        permissions=["read"]
    )
    security_manager.add_access_control_entry(user_ace)

    # Data analyst with read access to financial reports but only during business hours
    analyst_ace = AccessControlEntry(
        resource_id="financial_reports",
        resource_type="document",
        principal_id="data_analyst",
        principal_type="user",
        permissions=["read"],
        conditions={
            "time_range": {"start": "08:00:00", "end": "18:00:00"}
        }
    )
    security_manager.add_access_control_entry(analyst_ace)

    logger.info("Access controls configured")

    # 4. Set up encryption configurations
    customer_data_encryption = DataEncryptionConfig(
        enabled=True,
        key_id="customer_data_key",
        algorithm="AES-256-GCM",
        key_rotation_days=30
    )
    security_manager.add_encryption_config("customer_data", customer_data_encryption)

    financial_encryption = DataEncryptionConfig(
        enabled=True,
        key_id="financial_key",
        algorithm="AES-256-GCM",
        key_rotation_days=15
    )
    security_manager.add_encryption_config("financial_reports", financial_encryption)

    logger.info("Encryption configurations set up")

    return "Security environment configured successfully"


@security_operation(user_id_arg="user_id", resource_id_arg="resource_id", action="access_sensitive_data")
def access_sensitive_data(user_id: str, resource_id: str, operation: str) -> Dict[str, Any]:
    """
    Access sensitive data with security controls.

    Args:
        user_id: The user performing the access
        resource_id: The resource to access
        operation: The operation to perform (read/write)

    Returns:
        Dict[str, Any]: Result of the operation
    """
    logger.info(f"User {user_id} attempting to {operation} {resource_id}")

    # Check data classification
    classification = security_manager.get_data_classification(resource_id)
    if not classification:
        classification = DataClassification.INTERNAL  # Default

    logger.info(f"Resource {resource_id} has classification: {classification.name}")

    # Verify access permission
    decision = security_manager.check_access(user_id, resource_id, operation)

    if decision != AccessDecision.ALLOW:
        logger.warning(f"Access decision for {user_id} to {operation} {resource_id}: {decision.name}")
        if decision == AccessDecision.DENY:
            raise PermissionError(f"Access denied for {user_id} to {operation} {resource_id}")
        elif decision == AccessDecision.ELEVATE:
            # In a real system, this would trigger additional authentication
            logger.info("Requiring elevated permissions...")
            # Simulate additional authentication
            logger.info("Elevated permissions granted")

    # Log the access
    logger.info(f"Access granted for {user_id} to {operation} {resource_id}")

    # Perform the operation
    result = {
        "status": "success",
        "resource_id": resource_id,
        "operation": operation,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "classification": classification.name,
        "user": user_id
    }

    return result


def demonstrate_security_features():
    """Demonstrate the enhanced security features."""
    logger.info("Demonstrating security features...")

    # 1. Set up security environment
    setup_security_environment()

    # 2. Demonstrate successful access
    try:
        result = access_sensitive_data(
            user_id="admin_user",
            resource_id="product_documentation",
            operation="read"
        )
        logger.info(f"Access result: {result}")
    except Exception as e:
        logger.error(f"Access error: {str(e)}")

    # 3. Demonstrate access denial
    try:
        result = access_sensitive_data(
            user_id="regular_user",
            resource_id="financial_reports",
            operation="read"
        )
        logger.info(f"Access result: {result}")
    except Exception as e:
        logger.error(f"Access error: {str(e)}")

    # 4. Demonstrate security sessions
    with SecuritySession(
        user_id="data_analyst",
        resource_id="customer_data",
        action="analyze_data"
    ) as session:
        try:
            # Set context for the session
            session.set_context("purpose", "quarterly_analysis")
            session.set_context("client_ip", "192.168.1.100")

            # Check access within the session
            decision = session.check_access("read")
            logger.info(f"Session access decision: {decision.name}")

            # Perform analysis (simulated)
            logger.info("Performing data analysis...")

        except Exception as e:
            logger.error(f"Session error: {str(e)}")

    # 5. Demonstrate policy enforcement
    # Create an audit event that would trigger the data volume policy
    large_data_event = AuditEvent(
        event_id="test_large_data",
        timestamp=datetime.datetime.utcnow().isoformat() + 'Z',
        level=AuditLevel.INFO,
        category=AuditCategory.DATA_ACCESS,
        action="download",
        user="regular_user",
        resource_id="product_documentation",
        resource_type="document",
        details={"data_size_bytes": 75 * 1024 * 1024}  # 75MB (exceeds policy)
    )

    # Process the event to trigger policy checks
    security_manager._process_audit_event(large_data_event)
    logger.info("Processed large data event (policy violation expected)")

    return "Security demonstration completed"


if __name__ == "__main__":
    try:
        result = demonstrate_security_features()
        logger.info(result)
    except Exception as e:
        logger.error(f"Demonstration error: {str(e)}")
