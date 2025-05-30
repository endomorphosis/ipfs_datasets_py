"""
Security and Provenance Integration Module

This module provides integration between the enhanced security system and data
provenance tracking system, enabling security-aware provenance tracking and
provenance-aware security enforcement.
"""

import json
import logging
import datetime
import hashlib
import base64
from typing import Dict, List, Any, Optional, Union, Callable, Set, Tuple

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, DataClassification, AccessDecision,
    SecurityPolicy, AccessControlEntry, SecuritySession, security_operation
)
from ipfs_datasets_py.audit.integration import (
    AuditProvenanceIntegrator, IntegratedComplianceReporter
)

# Try to import provenance module
try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, ProvenanceContext, ProvenanceCryptoVerifier,
        SourceRecord, TransformationRecord, VerificationRecord, AnnotationRecord,
        ModelTrainingRecord, ModelInferenceRecord, IPLDProvenanceStorage
    )
    PROVENANCE_MODULE_AVAILABLE = True
except ImportError:
    PROVENANCE_MODULE_AVAILABLE = False


class SecurityProvenanceIntegrator:
    """
    Integrates the enhanced security system with data provenance tracking.

    This class provides bidirectional integration between the enhanced security
    system and data provenance tracking, enabling:

    1. Security-aware provenance tracking:
       - Add security classifications to provenance records
       - Protect provenance records based on data sensitivity
       - Sign provenance records for integrity verification

    2. Provenance-aware security enforcement:
       - Use lineage information for access control decisions
       - Create security policies based on data provenance
       - Verify data transformation chains for sensitive operations
    """

    def __init__(self, security_manager=None, provenance_manager=None,
                 audit_integrator=None):
        """
        Initialize the security-provenance integrator.

        Args:
            security_manager: EnhancedSecurityManager instance (optional)
            provenance_manager: EnhancedProvenanceManager instance (optional)
            audit_integrator: AuditProvenanceIntegrator instance (optional)
        """
        self.security_manager = security_manager or EnhancedSecurityManager.get_instance()
        self.provenance_manager = provenance_manager
        self.audit_integrator = audit_integrator
        self.logger = logging.getLogger(__name__)

        # Initialize components
        if not PROVENANCE_MODULE_AVAILABLE:
            self.logger.warning("Data provenance module not available. Some features will be disabled.")
            return

        if not self.provenance_manager:
            try:
                self.provenance_manager = EnhancedProvenanceManager()
            except Exception as e:
                self.logger.error(f"Error initializing provenance manager: {str(e)}")
                return

        if not self.audit_integrator:
            try:
                self.audit_integrator = AuditProvenanceIntegrator(
                    audit_logger=self.security_manager.audit_logger,
                    provenance_manager=self.provenance_manager
                )
                self.audit_integrator.setup_audit_event_listener()
            except Exception as e:
                self.logger.error(f"Error initializing audit integrator: {str(e)}")

        # Initialize crypto verifier for provenance integrity
        try:
            self.crypto_verifier = ProvenanceCryptoVerifier()
        except Exception as e:
            self.logger.error(f"Error initializing crypto verifier: {str(e)}")
            self.crypto_verifier = None

    def add_security_metadata_to_record(self, record_id: str,
                                      user_id: Optional[str] = None) -> bool:
        """
        Add security-related metadata to a provenance record.

        This method enhances provenance records with security classifications,
        access control information, and cryptographic verification.

        Args:
            record_id: The ID of the provenance record to enhance
            user_id: The user performing the operation (optional)

        Returns:
            bool: Whether the operation was successful
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return False

        try:
            # Get the provenance record
            record = self.provenance_manager.get_record(record_id)
            if not record:
                self.logger.warning(f"Provenance record not found: {record_id}")
                return False

            # Get data ID from the record
            data_id = None
            if hasattr(record, "data_id"):
                data_id = record.data_id
            elif hasattr(record, "output_id"):
                data_id = record.output_id
            elif hasattr(record, "source_id"):
                data_id = record.source_id

            if not data_id:
                self.logger.warning(f"No data ID found in record: {record_id}")
                return False

            # Get data classification for the associated data
            classification = self.security_manager.get_data_classification(data_id)

            # Prepare security metadata
            security_metadata = {
                "security": {
                    "classification": classification.name if classification else "UNCLASSIFIED",
                    "classified_by": user_id,
                    "classified_at": datetime.datetime.utcnow().isoformat() + 'Z'
                }
            }

            # Add cryptographic verification if available
            if self.crypto_verifier:
                try:
                    signature = self.crypto_verifier.sign_record(record)
                    security_metadata["security"]["signature"] = signature.hex()
                    security_metadata["security"]["signature_algorithm"] = "HMAC-SHA256"
                except Exception as e:
                    self.logger.error(f"Error signing provenance record: {str(e)}")

            # Add ACEs if they exist for this data
            aces = self.security_manager.get_access_control_entries(data_id)
            if aces:
                security_metadata["security"]["access_control"] = {
                    "entries": [self._ace_to_dict(ace) for ace in aces]
                }

            # Update the record with security metadata
            self.provenance_manager.add_metadata_to_record(
                record_id=record_id,
                metadata=security_metadata
            )

            # Log the enhancement
            self.security_manager.audit_logger.security(
                action="add_security_metadata",
                resource_id=record_id,
                resource_type="provenance_record",
                user=user_id,
                details={
                    "data_id": data_id,
                    "classification": classification.name if classification else "UNCLASSIFIED"
                }
            )

            return True

        except Exception as e:
            self.logger.error(f"Error adding security metadata to provenance record: {str(e)}")
            return False

    def _ace_to_dict(self, ace: AccessControlEntry) -> Dict[str, Any]:
        """
        Convert an AccessControlEntry to a simplified dictionary.

        Args:
            ace: The AccessControlEntry to convert

        Returns:
            Dict[str, Any]: Dictionary representation of the ACE
        """
        return {
            "principal_id": ace.principal_id,
            "principal_type": ace.principal_type,
            "permissions": ace.permissions
        }

    def verify_provenance_integrity(self, record_id: str) -> Dict[str, Any]:
        """
        Verify the integrity of a provenance record.

        Args:
            record_id: The ID of the provenance record to verify

        Returns:
            Dict[str, Any]: Verification results
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager or not self.crypto_verifier:
            return {"verified": False, "error": "Required components not available"}

        try:
            # Get the provenance record
            record = self.provenance_manager.get_record(record_id)
            if not record:
                return {"verified": False, "error": "Record not found"}

            # Check if record has security metadata with signature
            if (not hasattr(record, "metadata") or
                not record.metadata or
                "security" not in record.metadata or
                "signature" not in record.metadata["security"]):
                return {"verified": False, "error": "Record has no signature"}

            # Get signature
            signature_hex = record.metadata["security"]["signature"]
            try:
                signature = bytes.fromhex(signature_hex)
            except ValueError:
                return {"verified": False, "error": "Invalid signature format"}

            # Create a copy of the record without the signature for verification
            record_copy = record
            security_copy = record.metadata["security"].copy()
            del security_copy["signature"]
            record_metadata_copy = record.metadata.copy()
            record_metadata_copy["security"] = security_copy
            record_copy.metadata = record_metadata_copy

            # Verify the signature
            is_valid = self.crypto_verifier.verify_record(record_copy, signature)

            return {
                "verified": is_valid,
                "record_id": record_id,
                "verification_time": datetime.datetime.utcnow().isoformat() + 'Z',
                "error": None if is_valid else "Signature verification failed"
            }

        except Exception as e:
            self.logger.error(f"Error verifying provenance integrity: {str(e)}")
            return {"verified": False, "error": str(e)}

    def check_access_with_lineage(self, user_id: str, resource_id: str,
                               operation: str, max_depth: int = 2) -> Tuple[AccessDecision, Dict[str, Any]]:
        """
        Check access using both direct permissions and data lineage information.

        This method enhances access control by considering data lineage when making
        access decisions. It can enforce security policies like:
        - Deny access if upstream data sources have higher classification
        - Require additional authorization for data derived from sensitive sources
        - Verify transformation chain integrity for sensitive operations

        Args:
            user_id: The user requesting access
            resource_id: The resource being accessed
            operation: The operation being performed
            max_depth: Maximum lineage traversal depth

        Returns:
            Tuple[AccessDecision, Dict[str, Any]]: Access decision and context
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            # Fall back to standard access check
            decision = self.security_manager.check_access(user_id, resource_id, operation)
            return decision, {"lineage_check": False}

        try:
            # First, check direct permissions
            direct_decision = self.security_manager.check_access(user_id, resource_id, operation)

            # If direct access is denied, no need to check lineage
            if direct_decision == AccessDecision.DENY:
                return direct_decision, {"lineage_check": False}

            # Get upstream lineage
            lineage_records = self.provenance_manager.get_upstream_lineage(
                resource_id, max_depth=max_depth
            )

            # If no lineage, use direct decision
            if not lineage_records:
                return direct_decision, {"lineage_check": True, "lineage_found": False}

            # Check for sensitive upstream data
            sensitive_sources = []
            for record in lineage_records:
                source_id = None
                if hasattr(record, "source_id"):
                    source_id = record.source_id
                elif hasattr(record, "data_id"):
                    source_id = record.data_id

                if source_id:
                    # Check classification
                    classification = self.security_manager.get_data_classification(source_id)
                    if classification and classification.value >= DataClassification.CONFIDENTIAL.value:
                        sensitive_sources.append({
                            "source_id": source_id,
                            "classification": classification.name,
                            "record_id": record.record_id if hasattr(record, "record_id") else None
                        })

            # Make lineage-aware decision
            lineage_decision = direct_decision
            decision_context = {
                "lineage_check": True,
                "lineage_found": True,
                "lineage_depth": len(lineage_records),
                "sensitive_sources": sensitive_sources
            }

            # Apply lineage-based rules
            if sensitive_sources:
                # For write operations on data with sensitive sources, require elevated access
                if operation in ["write", "update", "delete"] and direct_decision == AccessDecision.ALLOW:
                    lineage_decision = AccessDecision.ELEVATE
                    decision_context["reason"] = "Data derived from sensitive sources"

                # For read operations, use audit-only access for deeper inspection
                elif operation == "read" and direct_decision == AccessDecision.ALLOW:
                    lineage_decision = AccessDecision.AUDIT_ONLY
                    decision_context["reason"] = "Reading data with sensitive lineage"

            # Log the lineage-enhanced access check
            self.security_manager.audit_logger.authz(
                action="lineage_access_check",
                user=user_id,
                resource_id=resource_id,
                details={
                    "operation": operation,
                    "direct_decision": direct_decision.name,
                    "lineage_decision": lineage_decision.name,
                    "sensitive_source_count": len(sensitive_sources),
                    "lineage_depth": len(lineage_records)
                }
            )

            return lineage_decision, decision_context

        except Exception as e:
            self.logger.error(f"Error in lineage-based access check: {str(e)}")
            # Fall back to direct decision on error
            return direct_decision, {"lineage_check": False, "error": str(e)}

    def record_secure_transformation(self, input_ids: List[str], output_id: str,
                                  transformation_type: str, parameters: Dict[str, Any],
                                  user_id: str, verify_lineage: bool = True,
                                  classification: Optional[DataClassification] = None) -> Optional[str]:
        """
        Record a secure data transformation with full security context.

        This method records a transformation operation with:
        - Security classifications for both inputs and outputs
        - Access control enforcement before recording
        - Cryptographic verification for integrity
        - Optional lineage verification

        Args:
            input_ids: IDs of the input data
            output_id: ID of the output data
            transformation_type: Type of transformation
            parameters: Transformation parameters
            user_id: User performing the transformation
            verify_lineage: Whether to verify upstream lineage for sensitive inputs
            classification: Optional classification for the output data

        Returns:
            Optional[str]: The record ID if successful, None otherwise
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return None

        try:
            # Check access for all input IDs
            for input_id in input_ids:
                decision = self.security_manager.check_access(user_id, input_id, "read")
                if decision == AccessDecision.DENY:
                    self.logger.warning(f"Access denied for user {user_id} to read {input_id}")
                    return None

            # Check access for output ID
            decision = self.security_manager.check_access(user_id, output_id, "write")
            if decision == AccessDecision.DENY:
                self.logger.warning(f"Access denied for user {user_id} to write {output_id}")
                return None

            # Verify lineage if requested and inputs are sensitive
            lineage_context = {}
            if verify_lineage:
                for input_id in input_ids:
                    input_classification = self.security_manager.get_data_classification(input_id)
                    if input_classification and input_classification.value >= DataClassification.CONFIDENTIAL.value:
                        # Get and verify the lineage
                        lineage_records = self.provenance_manager.get_upstream_lineage(input_id)
                        lineage_context[input_id] = {
                            "record_count": len(lineage_records),
                            "verified": self._verify_lineage_chain(lineage_records)
                        }

            # Add security context to parameters
            secure_parameters = parameters.copy() if parameters else {}
            secure_parameters["security_context"] = {
                "user_id": user_id,
                "timestamp": datetime.datetime.utcnow().isoformat() + 'Z',
                "lineage_verification": lineage_context if verify_lineage else None
            }

            # Create the transformation record
            record_id = self.provenance_manager.record_transformation(
                input_ids=input_ids,
                output_id=output_id,
                transformation_type=transformation_type,
                parameters=secure_parameters,
                metadata={
                    "security_enhanced": True,
                    "recorded_by": user_id
                }
            )

            # Add security metadata to the record
            self.add_security_metadata_to_record(record_id, user_id)

            # Set classification for output data if provided
            if classification:
                self.security_manager.set_data_classification(output_id, classification, user_id)

            # Log the secure transformation
            self.security_manager.audit_logger.data_modify(
                action="secure_transformation",
                user=user_id,
                resource_id=output_id,
                details={
                    "input_ids": input_ids,
                    "transformation_type": transformation_type,
                    "provenance_record_id": record_id,
                    "classification": classification.name if classification else None
                }
            )

            return record_id

        except Exception as e:
            self.logger.error(f"Error recording secure transformation: {str(e)}")
            return None

    def _verify_lineage_chain(self, lineage_records: List[Any]) -> bool:
        """
        Verify the integrity of a lineage chain.

        Args:
            lineage_records: The lineage records to verify

        Returns:
            bool: Whether the lineage chain is valid
        """
        if not self.crypto_verifier or not lineage_records:
            return False

        try:
            valid_records = 0
            for record in lineage_records:
                if hasattr(record, "record_id"):
                    result = self.verify_provenance_integrity(record.record_id)
                    if result["verified"]:
                        valid_records += 1

            # Ensure at least 50% of records have valid signatures
            return valid_records >= len(lineage_records) / 2

        except Exception as e:
            self.logger.error(f"Error verifying lineage chain: {str(e)}")
            return False

    def create_provenance_based_security_policy(self, policy_id: str, name: str,
                                             resource_pattern: str,
                                             lineage_rules: List[Dict[str, Any]],
                                             user_id: Optional[str] = None) -> bool:
        """
        Create a security policy based on data provenance requirements.

        This method creates a security policy that enforces rules based on data
        lineage and provenance information.

        Args:
            policy_id: Unique ID for the policy
            name: Human-readable name for the policy
            resource_pattern: Pattern for resources this policy applies to
            lineage_rules: Rules for lineage verification
            user_id: User creating the policy (optional)

        Returns:
            bool: Whether the policy was successfully created
        """
        try:
            # Build the policy rules
            rules = []

            for rule in lineage_rules:
                rule_type = rule.get("type", "lineage_verification")

                if rule_type == "lineage_verification":
                    # Rule requiring verified lineage
                    rules.append({
                        "type": "lineage_verification",
                        "required_verification": rule.get("required_verification", True),
                        "min_verified_percentage": rule.get("min_verified_percentage", 50),
                        "severity": rule.get("severity", "high"),
                        "description": rule.get("description", "Requires verified data lineage")
                    })

                elif rule_type == "source_classification":
                    # Rule limiting access based on source classification
                    rules.append({
                        "type": "source_classification",
                        "max_classification": rule.get("max_classification", "RESTRICTED"),
                        "severity": rule.get("severity", "high"),
                        "description": rule.get("description", "Restricts data derived from highly classified sources")
                    })

                elif rule_type == "transformation_chain":
                    # Rule requiring specific transformation chain properties
                    rules.append({
                        "type": "transformation_chain",
                        "required_transformations": rule.get("required_transformations", []),
                        "prohibited_transformations": rule.get("prohibited_transformations", []),
                        "max_chain_length": rule.get("max_chain_length", 10),
                        "severity": rule.get("severity", "medium"),
                        "description": rule.get("description", "Enforces transformation chain requirements")
                    })

            # Create the security policy
            policy = SecurityPolicy(
                policy_id=policy_id,
                name=name,
                description=f"Provenance-based security policy for {resource_pattern}",
                enforcement_level="enforcing",
                rules=rules,
                metadata={
                    "resource_pattern": resource_pattern,
                    "provenance_based": True,
                    "created_at": datetime.datetime.utcnow().isoformat() + 'Z'
                }
            )

            # Add the policy
            success = self.security_manager.add_security_policy(policy, user_id)

            if success:
                # Log policy creation
                self.security_manager.audit_logger.security(
                    action="create_provenance_policy",
                    user=user_id,
                    details={
                        "policy_id": policy_id,
                        "name": name,
                        "resource_pattern": resource_pattern,
                        "rule_count": len(rules)
                    }
                )

            return success

        except Exception as e:
            self.logger.error(f"Error creating provenance-based security policy: {str(e)}")
            return False

    def verify_cross_document_security(self, document_ids: List[str],
                                    user_id: str) -> Dict[str, Any]:
        """
        Verify security across document boundaries.

        This method analyzes cross-document data flows to identify security
        issues like unauthorized data transfers, classification violations,
        or integrity issues.

        Args:
            document_ids: List of document IDs to analyze
            user_id: User requesting the verification

        Returns:
            Dict[str, Any]: Verification results
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return {"error": "Provenance module not available"}

        try:
            storage = self.provenance_manager.storage

            # Build cross-document lineage graph
            lineage_graph = storage.build_cross_document_lineage_graph(
                record_ids=document_ids,
                max_depth=3
            )

            # Analyze cross-document connections
            analysis = storage.analyze_cross_document_lineage(lineage_graph)

            # Extract the document boundaries
            document_boundaries = analysis.get("document_boundaries", [])
            cross_boundary_flows = analysis.get("cross_boundary_flow_count", 0)

            # Check for security issues at boundaries
            security_issues = []
            for boundary in document_boundaries:
                from_doc = boundary.get("from_document")
                to_doc = boundary.get("to_document")

                # Check classification levels
                from_class = self._get_document_classification(from_doc)
                to_class = self._get_document_classification(to_doc)

                # Check if data flows from higher to lower classification
                if from_class and to_class and from_class.value > to_class.value:
                    security_issues.append({
                        "type": "classification_violation",
                        "from_document": from_doc,
                        "to_document": to_doc,
                        "from_classification": from_class.name,
                        "to_classification": to_class.name,
                        "severity": "high",
                        "description": f"Data flows from {from_class.name} to {to_class.name} classification"
                    })

                # Check for appropriate access controls at boundaries
                if not self._verify_boundary_access_controls(from_doc, to_doc):
                    security_issues.append({
                        "type": "boundary_access_control",
                        "from_document": from_doc,
                        "to_document": to_doc,
                        "severity": "medium",
                        "description": "Insufficient access controls at document boundary"
                    })

                # Check for integrity verification across boundaries
                if not self._verify_boundary_integrity(from_doc, to_doc):
                    security_issues.append({
                        "type": "boundary_integrity",
                        "from_document": from_doc,
                        "to_document": to_doc,
                        "severity": "medium",
                        "description": "Integrity verification missing at document boundary"
                    })

            # Log the verification
            self.security_manager.audit_logger.security(
                action="cross_document_verification",
                user=user_id,
                details={
                    "document_count": len(document_ids),
                    "boundary_count": len(document_boundaries),
                    "cross_boundary_flows": cross_boundary_flows,
                    "issue_count": len(security_issues)
                }
            )

            return {
                "verification_time": datetime.datetime.utcnow().isoformat() + 'Z',
                "document_count": len(document_ids),
                "boundary_count": len(document_boundaries),
                "cross_boundary_flows": cross_boundary_flows,
                "security_issues": security_issues,
                "is_secure": len(security_issues) == 0
            }

        except Exception as e:
            self.logger.error(f"Error verifying cross-document security: {str(e)}")
            return {"error": str(e)}

    def _get_document_classification(self, document_id: str) -> Optional[DataClassification]:
        """
        Get the highest classification level in a document.

        Args:
            document_id: The document ID

        Returns:
            Optional[DataClassification]: The highest classification level
        """
        try:
            # In a real implementation, this would query all resources in the document
            # and return the highest classification level found
            return self.security_manager.get_data_classification(document_id)
        except Exception:
            return None

    def _verify_boundary_access_controls(self, from_doc: str, to_doc: str) -> bool:
        """
        Verify that appropriate access controls exist at a document boundary.

        Args:
            from_doc: The source document ID
            to_doc: The target document ID

        Returns:
            bool: Whether appropriate access controls exist
        """
        # In a real implementation, this would check for explicit ACEs at the boundary
        # For now, just check if ACEs exist for either document
        from_aces = self.security_manager.get_access_control_entries(from_doc)
        to_aces = self.security_manager.get_access_control_entries(to_doc)

        return len(from_aces) > 0 or len(to_aces) > 0

    def _verify_boundary_integrity(self, from_doc: str, to_doc: str) -> bool:
        """
        Verify integrity preservation across a document boundary.

        Args:
            from_doc: The source document ID
            to_doc: The target document ID

        Returns:
            bool: Whether integrity is preserved across the boundary
        """
        # In a real implementation, this would verify cryptographic signatures
        # and hash chains across the document boundary
        # For now, return a placeholder result
        return True

    def secure_provenance_query(self, query_params: Dict[str, Any], user_id: str,
                             include_cross_document: bool = False) -> Dict[str, Any]:
        """
        Perform a security-aware provenance query.

        This method performs a provenance query with security checks, filtering
        results based on user permissions and data classifications.

        Args:
            query_params: Query parameters
            user_id: User performing the query
            include_cross_document: Whether to include cross-document analysis

        Returns:
            Dict[str, Any]: Query results with security information
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return {"error": "Provenance module not available"}

        try:
            # Log the query
            self.security_manager.audit_logger.data_access(
                action="secure_provenance_query",
                user=user_id,
                details={
                    "query_params": query_params,
                    "include_cross_document": include_cross_document
                }
            )

            # Execute the query
            records = self.provenance_manager.query_records(**query_params)

            # Filter records based on security permissions
            filtered_records = []
            for record in records:
                data_id = None
                if hasattr(record, "data_id"):
                    data_id = record.data_id
                elif hasattr(record, "output_id"):
                    data_id = record.output_id
                elif hasattr(record, "source_id"):
                    data_id = record.source_id

                if data_id:
                    decision = self.security_manager.check_access(user_id, data_id, "read")
                    if decision != AccessDecision.DENY:
                        # Add the record with security information
                        record_dict = self._record_to_dict(record)

                        # Add security information
                        classification = self.security_manager.get_data_classification(data_id)
                        record_dict["security"] = {
                            "classification": classification.name if classification else "UNCLASSIFIED",
                            "access_decision": decision.name,
                            "requires_elevated_access": decision == AccessDecision.ELEVATE
                        }

                        filtered_records.append(record_dict)

            # Perform cross-document analysis if requested
            cross_document_results = None
            if include_cross_document and len(filtered_records) > 0:
                # Get unique document IDs
                document_ids = set()
                for record in filtered_records:
                    if "document_id" in record:
                        document_ids.add(record["document_id"])
                    if "metadata" in record and "document_id" in record["metadata"]:
                        document_ids.add(record["metadata"]["document_id"])

                if document_ids:
                    cross_document_results = self.verify_cross_document_security(
                        list(document_ids), user_id
                    )

            return {
                "query_time": datetime.datetime.utcnow().isoformat() + 'Z',
                "total_records": len(records),
                "filtered_records": len(filtered_records),
                "records": filtered_records,
                "cross_document_analysis": cross_document_results
            }

        except Exception as e:
            self.logger.error(f"Error in secure provenance query: {str(e)}")
            return {"error": str(e)}

    def _record_to_dict(self, record: Any) -> Dict[str, Any]:
        """
        Convert a provenance record to a dictionary.

        Args:
            record: The provenance record

        Returns:
            Dict[str, Any]: Dictionary representation of the record
        """
        if hasattr(record, "to_dict"):
            return record.to_dict()

        result = {}

        # Extract common attributes
        for attr in ["record_id", "timestamp", "record_type", "metadata"]:
            if hasattr(record, attr):
                result[attr] = getattr(record, attr)

        # Add type-specific attributes
        if hasattr(record, "source_id"):
            result["source_id"] = record.source_id
            result["source_type"] = getattr(record, "source_type", None)
            result["source_uri"] = getattr(record, "source_uri", None)

        if hasattr(record, "input_ids"):
            result["input_ids"] = record.input_ids
            result["output_id"] = getattr(record, "output_id", None)
            result["transformation_type"] = getattr(record, "transformation_type", None)

        if hasattr(record, "data_id"):
            result["data_id"] = record.data_id

        return result


# Utility decorator for secured provenance operations
def secure_provenance_operation(user_id_arg: str, data_id_arg: str,
                              action: str = "provenance_operation"):
    """
    Decorator for securing provenance operations with access control and auditing.

    Args:
        user_id_arg: Name of the argument containing the user ID
        data_id_arg: Name of the argument containing the data ID
        action: The action being performed

    Returns:
        Callable: Decorated function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract user ID and data ID from arguments
            user_id = kwargs.get(user_id_arg)
            data_id = kwargs.get(data_id_arg)

            # Get security and provenance components
            security_manager = EnhancedSecurityManager.get_instance()
            integrator = SecurityProvenanceIntegrator(security_manager=security_manager)

            # Check access with lineage information
            decision, context = integrator.check_access_with_lineage(
                user_id=user_id,
                resource_id=data_id,
                operation="read"  # Use appropriate operation based on function
            )

            if decision == AccessDecision.DENY:
                # Log access denial
                security_manager.audit_logger.authz(
                    action="provenance_access_denied",
                    level=AuditLevel.WARNING,
                    user=user_id,
                    resource_id=data_id,
                    details={
                        "function": func.__name__,
                        "lineage_context": context
                    }
                )

                # Raise permission error
                raise PermissionError(f"Access denied for user {user_id} to access {data_id}")

            # Create security session for the operation
            with SecuritySession(user_id=user_id, resource_id=data_id, action=action) as session:
                # Add lineage context to the session
                for key, value in context.items():
                    session.set_context(key, value)

                # Execute the function
                return func(*args, **kwargs)

        return wrapper

    return decorator


# Get a singleton integrator instance
def get_security_provenance_integrator(security_manager=None,
                                     provenance_manager=None) -> SecurityProvenanceIntegrator:
    """
    Get a security-provenance integrator instance.

    Args:
        security_manager: EnhancedSecurityManager instance (optional)
        provenance_manager: EnhancedProvenanceManager instance (optional)

    Returns:
        SecurityProvenanceIntegrator: The integrator instance
    """
    return SecurityProvenanceIntegrator(
        security_manager=security_manager,
        provenance_manager=provenance_manager
    )
