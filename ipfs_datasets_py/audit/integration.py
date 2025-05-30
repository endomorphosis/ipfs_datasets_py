"""
Audit Logging Integration Module

This module provides integration between the audit logging system and other
IPFS Datasets components, particularly data provenance tracking. It enables
comprehensive tracking and correlation of audit events with data provenance.
"""

import json
import datetime
import logging
from typing import Dict, List, Any, Optional, Union, Set
from dataclasses import asdict

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)
from ipfs_datasets_py.audit.compliance import (
    ComplianceReporter, ComplianceReport, ComplianceRequirement, ComplianceStandard
)

# Try to import provenance module for integration
try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, ProvenanceContext,
        SourceRecord, TransformationRecord, VerificationRecord, AnnotationRecord,
        ModelTrainingRecord, ModelInferenceRecord, IPLDProvenanceStorage
    )
    PROVENANCE_MODULE_AVAILABLE = True
except ImportError:
    PROVENANCE_MODULE_AVAILABLE = False


class AuditProvenanceIntegrator:
    """
    Integrates audit logging with data provenance tracking.

    This class provides bidirectional integration between audit logging and
    data provenance tracking systems, enabling comprehensive tracking and
    correlation of system activities.
    """

    def __init__(self, audit_logger=None, provenance_manager=None):
        """
        Initialize the integrator.

        Args:
            audit_logger: AuditLogger instance (optional, will use global instance if None)
            provenance_manager: EnhancedProvenanceManager instance (optional)
        """
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.provenance_manager = provenance_manager
        self.logger = logging.getLogger(__name__)

        if not PROVENANCE_MODULE_AVAILABLE:
            self.logger.warning("Data provenance module not available. Some features will be disabled.")

    def initialize_provenance_manager(self):
        """Initialize the provenance manager if not already done."""
        if not PROVENANCE_MODULE_AVAILABLE:
            return False

        if not self.provenance_manager:
            try:
                self.provenance_manager = EnhancedProvenanceManager()
                return True
            except Exception as e:
                self.logger.error(f"Error initializing provenance manager: {str(e)}")
                return False

        return True

    def audit_from_provenance_record(self, record: Any, additional_details: Dict[str, Any] = None) -> Optional[str]:
        """
        Generate an audit event from a provenance record.

        Args:
            record: Provenance record (SourceRecord, TransformationRecord, etc.)
            additional_details: Additional details to include in the audit event

        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        if not PROVENANCE_MODULE_AVAILABLE:
            return None

        try:
            # Determine audit category and action based on record type
            category = AuditCategory.PROVENANCE
            action = "unknown"
            resource_id = None
            resource_type = None
            details = additional_details or {}

            # Extract record-specific information
            if hasattr(record, "record_id"):
                details["provenance_record_id"] = record.record_id

            if hasattr(record, "timestamp"):
                details["provenance_timestamp"] = record.timestamp

            # Determine action and resource based on record type
            if isinstance(record, SourceRecord):
                action = "data_source_access"
                resource_id = record.source_id
                resource_type = "data_source"
                details["source_type"] = record.source_type
                details["source_uri"] = record.source_uri

            elif isinstance(record, TransformationRecord):
                action = "data_transformation"
                resource_id = record.output_id
                resource_type = "transformed_data"
                details["input_ids"] = record.input_ids
                details["transformation_type"] = record.transformation_type

            elif isinstance(record, VerificationRecord):
                action = "data_verification"
                resource_id = record.data_id
                resource_type = "verified_data"
                details["verification_type"] = record.verification_type
                details["result"] = record.result

            elif isinstance(record, AnnotationRecord):
                action = "data_annotation"
                resource_id = record.data_id
                resource_type = "annotated_data"
                details["annotation_type"] = record.annotation_type

            elif isinstance(record, ModelTrainingRecord):
                action = "model_training"
                resource_id = record.model_id
                resource_type = "ml_model"
                details["dataset_ids"] = record.dataset_ids
                details["parameters"] = record.parameters

            elif isinstance(record, ModelInferenceRecord):
                action = "model_inference"
                resource_id = record.model_id
                resource_type = "ml_model"
                details["input_id"] = record.input_id
                details["output_id"] = record.output_id

            # Generate the audit event
            event_id = self.audit_logger.log(
                level=AuditLevel.INFO,
                category=category,
                action=action,
                resource_id=resource_id,
                resource_type=resource_type,
                details=details
            )

            return event_id

        except Exception as e:
            self.logger.error(f"Error generating audit event from provenance record: {str(e)}")
            return None

    def provenance_from_audit_event(self, event: AuditEvent) -> Optional[str]:
        """
        Generate a provenance record from an audit event.

        Args:
            event: The audit event to convert

        Returns:
            str: Record ID of the generated provenance record, or None if failed
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.initialize_provenance_manager():
            return None

        try:
            record_id = None

            # Map audit category/action to provenance record type
            if event.category == AuditCategory.DATA_ACCESS and event.action in ["read", "load", "import"]:
                # Create a source record
                record_id = self.provenance_manager.record_source(
                    source_id=event.resource_id,
                    source_type=event.resource_type or "unknown",
                    source_uri=event.details.get("uri", ""),
                    metadata={
                        "audit_event_id": event.event_id,
                        "user": event.user,
                        "timestamp": event.timestamp,
                        **event.details
                    }
                )

            elif event.category == AuditCategory.DATA_MODIFICATION and event.action in ["transform", "process", "convert"]:
                # Create a transformation record
                input_ids = event.details.get("input_ids", [])
                if isinstance(input_ids, str):
                    input_ids = [input_ids]

                record_id = self.provenance_manager.record_transformation(
                    input_ids=input_ids,
                    output_id=event.resource_id,
                    transformation_type=event.details.get("transformation_type", "unknown"),
                    parameters=event.details.get("parameters", {}),
                    metadata={
                        "audit_event_id": event.event_id,
                        "user": event.user,
                        "timestamp": event.timestamp
                    }
                )

            elif event.category == AuditCategory.COMPLIANCE and event.action in ["verify", "validate"]:
                # Create a verification record
                record_id = self.provenance_manager.record_verification(
                    data_id=event.resource_id,
                    verification_type=event.details.get("verification_type", "unknown"),
                    result=event.details.get("result", {}),
                    metadata={
                        "audit_event_id": event.event_id,
                        "user": event.user,
                        "timestamp": event.timestamp
                    }
                )

            return record_id

        except Exception as e:
            self.logger.error(f"Error generating provenance record from audit event: {str(e)}")
            return None

    def link_audit_to_provenance(self, audit_event_id: str, provenance_record_id: str) -> bool:
        """
        Create a link between an audit event and a provenance record.

        Args:
            audit_event_id: ID of the audit event
            provenance_record_id: ID of the provenance record

        Returns:
            bool: Whether the linking was successful
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.initialize_provenance_manager():
            return False

        try:
            # Add audit event reference to provenance record
            self.provenance_manager.add_metadata_to_record(
                record_id=provenance_record_id,
                metadata={"linked_audit_event_id": audit_event_id}
            )

            # Log the link in audit logs
            self.audit_logger.log(
                level=AuditLevel.INFO,
                category=AuditCategory.PROVENANCE,
                action="link_audit_provenance",
                details={
                    "audit_event_id": audit_event_id,
                    "provenance_record_id": provenance_record_id
                }
            )

            return True

        except Exception as e:
            self.logger.error(f"Error linking audit event to provenance record: {str(e)}")
            return False

    def setup_audit_event_listener(self) -> bool:
        """
        Set up automatic provenance record creation from audit events.

        This method adds a listener to the audit logger that automatically
        creates corresponding provenance records for relevant audit events.

        Returns:
            bool: Whether the listener was successfully set up
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.initialize_provenance_manager():
            return False

        try:
            # Create a handler for the audit logger
            def audit_to_provenance_handler(event: AuditEvent):
                # Filter events that should generate provenance records
                if event.category in [AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION,
                                      AuditCategory.COMPLIANCE]:
                    # Generate provenance record from audit event
                    record_id = self.provenance_from_audit_event(event)

                    # If successful, link the audit event to the provenance record
                    if record_id:
                        self.link_audit_to_provenance(event.event_id, record_id)

            # Add the handler as an event listener for relevant categories
            for category in [AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION,
                          AuditCategory.COMPLIANCE]:
                self.audit_logger.add_event_listener(audit_to_provenance_handler, category)

            return True

        except Exception as e:
            self.logger.error(f"Error setting up audit event listener: {str(e)}")
            return False


class AuditDatasetIntegrator:
    """
    Integrates audit logging with dataset operations.

    This class provides utilities for tracking dataset operations
    through the audit logging system.
    """

    def __init__(self, audit_logger=None):
        """
        Initialize the dataset integrator.

        Args:
            audit_logger: AuditLogger instance (optional, will use global instance if None)
        """
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.logger = logging.getLogger(__name__)

    def record_dataset_load(self, dataset_name: str, dataset_id: Optional[str] = None,
                           source: Optional[str] = None, user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset loading operation in audit log.

        Args:
            dataset_name: Name of the dataset
            dataset_id: ID of the dataset (optional)
            source: Source of the dataset (e.g., "local", "huggingface", "ipfs")
            user: User performing the operation (optional)

        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_access(
                action="dataset_load",
                user=user,
                resource_id=dataset_id or dataset_name,
                resource_type="dataset",
                details={
                    "dataset_name": dataset_name,
                    "source": source or "unknown"
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset load: {str(e)}")
            return None

    def record_dataset_save(self, dataset_name: str, dataset_id: Optional[str] = None,
                           destination: Optional[str] = None, format: Optional[str] = None,
                           user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset saving operation in audit log.

        Args:
            dataset_name: Name of the dataset
            dataset_id: ID of the dataset (optional)
            destination: Destination for saving (e.g., "local", "huggingface", "ipfs")
            format: Format of the saved dataset (e.g., "parquet", "car", "arrow")
            user: User performing the operation (optional)

        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_modify(
                action="dataset_save",
                user=user,
                resource_id=dataset_id or dataset_name,
                resource_type="dataset",
                details={
                    "dataset_name": dataset_name,
                    "destination": destination or "unknown",
                    "format": format or "unknown"
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset save: {str(e)}")
            return None

    def record_dataset_transform(self, input_dataset: str, output_dataset: str,
                              transformation_type: str, parameters: Optional[Dict[str, Any]] = None,
                              user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset transformation operation in audit log.

        Args:
            input_dataset: Name or ID of the input dataset
            output_dataset: Name or ID of the output dataset
            transformation_type: Type of transformation applied
            parameters: Parameters of the transformation (optional)
            user: User performing the operation (optional)

        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_modify(
                action="dataset_transform",
                user=user,
                resource_id=output_dataset,
                resource_type="dataset",
                details={
                    "input_dataset": input_dataset,
                    "transformation_type": transformation_type,
                    "parameters": parameters or {}
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset transformation: {str(e)}")
            return None

    def record_dataset_query(self, dataset_name: str, query: str,
                          query_type: Optional[str] = None,
                          user: Optional[str] = None) -> Optional[str]:
        """
        Record dataset query operation in audit log.

        Args:
            dataset_name: Name or ID of the dataset
            query: The query executed
            query_type: Type of query (e.g., "sql", "vector", "graph")
            user: User performing the operation (optional)

        Returns:
            str: Event ID of the generated audit event, or None if failed
        """
        try:
            return self.audit_logger.data_access(
                action="dataset_query",
                user=user,
                resource_id=dataset_name,
                resource_type="dataset",
                details={
                    "query": query,
                    "query_type": query_type or "unknown"
                }
            )
        except Exception as e:
            self.logger.error(f"Error recording dataset query: {str(e)}")
            return None


class IntegratedComplianceReporter:
    """
    Integrated compliance reporting with audit logs and provenance data.

    This class provides advanced compliance reporting capabilities by combining
    audit log data with provenance information, enabling comprehensive
    analysis for regulatory compliance.
    """

    def __init__(self, standard: ComplianceStandard,
                audit_logger=None, provenance_manager=None):
        """
        Initialize the integrated compliance reporter.

        Args:
            standard: The compliance standard to report against
            audit_logger: AuditLogger instance (optional, will use global instance if None)
            provenance_manager: EnhancedProvenanceManager instance (optional)
        """
        self.standard = standard
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.provenance_manager = provenance_manager
        self.base_reporter = ComplianceReporter(standard)
        self.logger = logging.getLogger(__name__)

        # Initialize provenance components if available
        if PROVENANCE_MODULE_AVAILABLE:
            if not self.provenance_manager:
                try:
                    self.provenance_manager = EnhancedProvenanceManager()
                except Exception as e:
                    self.logger.warning(f"Could not initialize provenance manager: {str(e)}")

    def add_requirement(self, requirement: ComplianceRequirement) -> None:
        """
        Add a compliance requirement to check.

        Args:
            requirement: The compliance requirement to add
        """
        self.base_reporter.add_requirement(requirement)

    def get_audit_events(self, start_time: Optional[str] = None,
                     end_time: Optional[str] = None) -> List[AuditEvent]:
        """
        Get audit events for a specific time period.

        This method should be implemented by derived classes that know
        how to fetch audit events from various storage backends.

        Args:
            start_time: Start time for the report period (ISO format)
            end_time: End time for the report period (ISO format)

        Returns:
            List[AuditEvent]: The retrieved audit events
        """
        # In a real implementation, this would fetch events from storage
        # For now, just return an empty list as a placeholder
        return []

    def get_provenance_records(self, start_time: Optional[str] = None,
                            end_time: Optional[str] = None) -> List[Any]:
        """
        Get provenance records for a specific time period.

        Args:
            start_time: Start time for the report period (ISO format)
            end_time: End time for the report period (ISO format)

        Returns:
            List[Any]: The retrieved provenance records
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return []

        try:
            # Format datetime strings for provenance query
            start_dt = None
            end_dt = None

            if start_time:
                start_dt = datetime.datetime.fromisoformat(start_time.rstrip('Z'))

            if end_time:
                end_dt = datetime.datetime.fromisoformat(end_time.rstrip('Z'))

            # Query provenance records
            return self.provenance_manager.query_records(
                start_timestamp=start_dt,
                end_timestamp=end_dt
            )

        except Exception as e:
            self.logger.error(f"Error retrieving provenance records: {str(e)}")
            return []

    def generate_report(self, start_time: Optional[str] = None,
                      end_time: Optional[str] = None,
                      include_cross_document_analysis: bool = True,
                      include_lineage_metrics: bool = True) -> ComplianceReport:
        """
        Generate an integrated compliance report using both audit and provenance data.

        Args:
            start_time: Start time for the report period (ISO format)
            end_time: End time for the report period (ISO format)
            include_cross_document_analysis: Whether to include cross-document lineage analysis
            include_lineage_metrics: Whether to include lineage graph metrics

        Returns:
            ComplianceReport: The generated compliance report
        """
        # Set default time period if not provided
        if not start_time or not end_time:
            # Default to last 30 days
            end = datetime.datetime.utcnow()
            start = end - datetime.timedelta(days=30)
            end_time = end_time or end.isoformat() + 'Z'
            start_time = start_time or start.isoformat() + 'Z'

        # Get audit events
        events = self.get_audit_events(start_time, end_time)

        # Generate the base compliance report
        report = self.base_reporter.generate_report(events, start_time, end_time)

        # Enhance the report with provenance data if available
        if PROVENANCE_MODULE_AVAILABLE and self.provenance_manager:
            try:
                # Get provenance records
                records = self.get_provenance_records(start_time, end_time)

                # Add provenance data to report details
                report.details["provenance_record_count"] = len(records)

                # Process cross-document lineage if requested
                if include_cross_document_analysis and records:
                    self._add_cross_document_analysis(report, records, include_lineage_metrics)

            except Exception as e:
                self.logger.error(f"Error enhancing report with provenance data: {str(e)}")

        return report

    def _add_cross_document_analysis(self, report: ComplianceReport,
                                  records: List[Any],
                                  include_lineage_metrics: bool = True) -> None:
        """
        Add cross-document lineage analysis to the compliance report.

        This enhanced version uses the improved cross-document lineage features
        to provide more comprehensive analysis of data flows across document
        boundaries, including document relationship analysis and boundary detection.

        Args:
            report: The compliance report to enhance
            records: The provenance records to analyze
            include_lineage_metrics: Whether to include lineage graph metrics
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return

        try:
            # Get the storage instance from provenance manager
            storage = self.provenance_manager.storage

            if not isinstance(storage, IPLDProvenanceStorage):
                return

            # Extract record IDs
            record_ids = [record.record_id for record in records if hasattr(record, 'record_id')]

            if not record_ids:
                return

            # Determine appropriate link types for compliance analysis
            link_types = None  # Use all link types by default

            # For HIPAA, focus on PHI-related links
            if self.standard == ComplianceStandard.HIPAA:
                link_types = ["contains_phi", "processes_phi", "transfers_phi", "anonymizes"]

            # For GDPR, focus on PII-related links
            elif self.standard == ComplianceStandard.GDPR:
                link_types = ["contains_pii", "processes_pii", "transfers_pii", "anonymizes", "shares"]

            # Build enhanced cross-document lineage graph with link type filtering
            lineage_graph = storage.build_cross_document_lineage_graph(
                record_ids=record_ids,
                max_depth=3,
                link_types=link_types
            )

            # Analyze the lineage graph
            analysis = storage.analyze_cross_document_lineage(lineage_graph)

            # Add basic analysis to report
            report.details["cross_document_lineage"] = {
                "record_count": len(record_ids),
                "graph_node_count": analysis.get("node_count", 0),
                "graph_edge_count": analysis.get("edge_count", 0),
                "document_count": analysis.get("document_count", 0),
                "critical_paths": analysis.get("critical_paths_count", 0),
                "hub_records": len(analysis.get("hub_records", [])),
                "cross_document_connections": analysis.get("cross_document_connections", 0)
            }

            # Add enhanced document boundary analysis
            if "document_boundaries" in analysis:
                report.details["cross_document_lineage"]["document_boundaries"] = {
                    "count": len(analysis["document_boundaries"]),
                    "boundary_types": analysis.get("boundary_types", {}),
                    "cross_boundary_flow_count": analysis.get("cross_boundary_flow_count", 0)
                }

            # Add document relationship analysis
            if "document_relationships" in analysis:
                report.details["cross_document_lineage"]["document_relationships"] = {
                    "relationship_count": len(analysis["document_relationships"]),
                    "relationship_types": analysis.get("relationship_types", {}),
                    "high_risk_relationships": analysis.get("high_risk_relationships", 0)
                }

            # Add enhanced data flow metrics
            if "data_flow_metrics" in analysis:
                report.details["cross_document_lineage"]["data_flow_metrics"] = {
                    "total_flows": analysis["data_flow_metrics"].get("total_flows", 0),
                    "cross_document_flows": analysis["data_flow_metrics"].get("cross_document_flows", 0),
                    "flow_density": analysis["data_flow_metrics"].get("flow_density", 0),
                    "average_path_length": analysis["data_flow_metrics"].get("average_path_length", 0)
                }

            # Add full metrics if requested
            if include_lineage_metrics and "metrics" in analysis:
                report.details["cross_document_lineage"]["metrics"] = analysis["metrics"]

            # Generate document boundary visualization URL if available
            try:
                if hasattr(storage, 'visualize_cross_document_clusters'):
                    vis_data = storage.visualize_cross_document_clusters(
                        lineage_graph=lineage_graph,
                        format="json"
                    )
                    if vis_data and isinstance(vis_data, dict):
                        report.details["cross_document_lineage"]["visualization_data"] = vis_data
            except Exception as vis_error:
                self.logger.warning(f"Could not generate visualization: {str(vis_error)}")

            # Add compliance-specific insights
            self._add_compliance_insights(report, analysis)

        except Exception as e:
            self.logger.error(f"Error performing cross-document analysis: {str(e)}")

    def _add_compliance_insights(self, report: ComplianceReport,
                              analysis: Dict[str, Any]) -> None:
        """
        Add compliance-specific insights based on provenance analysis.

        This enhanced version leverages the improved cross-document lineage
        analysis to provide more detailed compliance insights, focusing on
        document boundaries, cross-document relationships, and data flow patterns.

        Args:
            report: The compliance report to enhance
            analysis: The lineage analysis results
        """
        insights = []

        # Add standard-specific insights based on enhanced cross-document analysis
        if self.standard == ComplianceStandard.GDPR:
            # GDPR-specific insights
            if analysis.get("cross_document_connections", 0) > 0:
                insights.append(
                    f"Detected {analysis.get('cross_document_connections', 0)} cross-document data flows "
                    "requiring data sharing agreements under GDPR Article 26/28"
                )

            if analysis.get("external_data_sources", 0) > 0:
                insights.append(
                    f"Identified {analysis.get('external_data_sources', 0)} external data sources, "
                    "requiring data controller/processor relationship audit under GDPR Article 30"
                )

            # Enhanced document boundary insights
            if "document_boundaries" in analysis:
                boundary_count = len(analysis.get("document_boundaries", []))
                cross_boundary_flow_count = analysis.get("cross_boundary_flow_count", 0)

                if boundary_count > 0 and cross_boundary_flow_count > 0:
                    insights.append(
                        f"Detected {cross_boundary_flow_count} data flows crossing {boundary_count} document boundaries, "
                        "requiring detailed documentation in your GDPR Article 30 records of processing activities"
                    )

                # Check for international transfers
                if "boundary_types" in analysis and "international_transfer" in analysis.get("boundary_types", {}):
                    intl_transfers = analysis["boundary_types"].get("international_transfer", 0)
                    insights.append(
                        f"Detected {intl_transfers} international data transfers that require "
                        "appropriate safeguards under GDPR Chapter V (Articles 44-50)"
                    )

            # Enhanced document relationship analysis
            if "document_relationships" in analysis and "relationship_types" in analysis:
                rel_types = analysis.get("relationship_types", {})

                if "data_sharing" in rel_types and rel_types["data_sharing"] > 0:
                    insights.append(
                        f"Identified {rel_types['data_sharing']} data sharing relationships "
                        "that require data sharing agreements under GDPR"
                    )

                if "data_processor" in rel_types and rel_types["data_processor"] > 0:
                    insights.append(
                        f"Detected {rel_types['data_processor']} data processor relationships "
                        "requiring processor agreements under GDPR Article 28"
                    )

                if "high_risk_relationships" in analysis and analysis["high_risk_relationships"] > 0:
                    insights.append(
                        f"Found {analysis['high_risk_relationships']} high-risk data relationships "
                        "that may require Data Protection Impact Assessment (DPIA) under GDPR Article 35"
                    )

            # Enhanced high-centrality records analysis
            if "high_centrality_records" in analysis:
                insights.append(
                    f"Identified {len(analysis['high_centrality_records'])} high-centrality records "
                    "that may contain personal data shared across multiple processes, "
                    "requiring enhanced data minimization under GDPR Article 5(1)(c)"
                )

        elif self.standard == ComplianceStandard.HIPAA:
            # HIPAA-specific insights with enhanced cross-document lineage analysis
            if "critical_paths" in analysis and analysis.get("critical_paths_count", 0) > 0:
                insights.append(
                    f"Identified {analysis['critical_paths_count']} critical data paths "
                    "requiring strict access controls and audit trail verification "
                    "under HIPAA Security Rule (45 CFR §164.312)"
                )

            # Enhanced document boundary insights
            if "document_boundaries" in analysis:
                boundary_count = len(analysis.get("document_boundaries", []))
                cross_boundary_flow_count = analysis.get("cross_boundary_flow_count", 0)

                if boundary_count > 0 and cross_boundary_flow_count > 0:
                    insights.append(
                        f"Detected {cross_boundary_flow_count} PHI data flows crossing {boundary_count} document boundaries, "
                        "requiring Business Associate Agreements under HIPAA Privacy Rule (45 CFR §164.502(e))"
                    )

                # Check for PHI-specific boundaries
                if "boundary_types" in analysis and "phi_boundary" in analysis.get("boundary_types", {}):
                    phi_boundaries = analysis["boundary_types"].get("phi_boundary", 0)
                    insights.append(
                        f"Detected {phi_boundaries} boundaries between PHI and non-PHI data, "
                        "requiring technical safeguards under HIPAA Security Rule (45 CFR §164.312)"
                    )

            # Enhanced document relationship analysis
            if "document_relationships" in analysis and "relationship_types" in analysis:
                rel_types = analysis.get("relationship_types", {})

                if "phi_sharing" in rel_types and rel_types["phi_sharing"] > 0:
                    insights.append(
                        f"Identified {rel_types['phi_sharing']} PHI sharing relationships "
                        "that require Business Associate Agreements under HIPAA"
                    )

                if "phi_deidentification" in rel_types and rel_types["phi_deidentification"] > 0:
                    insights.append(
                        f"Detected {rel_types['phi_deidentification']} de-identification processes "
                        "that should be audited for compliance with HIPAA Safe Harbor or Expert Determination methods"
                    )

            if "disconnected_subgraphs" in analysis and analysis.get("disconnected_subgraphs", 0) > 0:
                insights.append(
                    f"Detected {analysis['disconnected_subgraphs']} disconnected data flows "
                    "which could indicate gaps in PHI tracking and may violate "
                    "HIPAA Accounting of Disclosures requirements (45 CFR §164.528)"
                )

            # Enhanced data flow metrics for HIPAA
            if "data_flow_metrics" in analysis:
                if analysis["data_flow_metrics"].get("cross_document_flows", 0) > 5:
                    insights.append(
                        f"High number of cross-document PHI flows ({analysis['data_flow_metrics'].get('cross_document_flows', 0)}) "
                        "indicates need for enhanced transmission security controls under HIPAA Security Rule"
                    )

        elif self.standard == ComplianceStandard.SOC2:
            # SOC2-specific insights with enhanced cross-document analysis
            if "hub_records" in analysis and len(analysis.get("hub_records", [])) > 0:
                insights.append(
                    f"Identified {len(analysis['hub_records'])} hub records that represent "
                    "critical data transit points requiring enhanced monitoring "
                    "for SOC2 Common Criteria CC7.1 and CC7.2 (Change Management)"
                )

            # Enhanced document boundary insights
            if "document_boundaries" in analysis:
                boundary_count = len(analysis.get("document_boundaries", []))
                cross_boundary_flow_count = analysis.get("cross_boundary_flow_count", 0)

                if boundary_count > 0 and cross_boundary_flow_count > 0:
                    insights.append(
                        f"Detected {cross_boundary_flow_count} data flows crossing {boundary_count} document boundaries, "
                        "requiring boundary controls for SOC2 CC6.1 (Logical Access Security)"
                    )

            # Enhanced document relationship analysis
            if "document_relationships" in analysis and "relationship_types" in analysis:
                rel_types = analysis.get("relationship_types", {})

                if "data_transformation" in rel_types and rel_types["data_transformation"] > 0:
                    insights.append(
                        f"Documented {rel_types['data_transformation']} data transformation processes "
                        "demonstrating processing integrity controls for SOC2 PI1.1"
                    )

                if "data_processing" in rel_types and rel_types["data_processing"] > 0:
                    insights.append(
                        f"Identified {rel_types['data_processing']} data processing relationships "
                        "requiring input validation controls for SOC2 PI1.2"
                    )

            if "data_transformation_chains" in analysis:
                insights.append(
                    f"Documented {analysis.get('data_transformation_chains', 0)} transformation chains "
                    "demonstrating complete processing integrity controls for SOC2 PI1.1"
                )

            # Enhanced data flow metrics for SOC2
            if "data_flow_metrics" in analysis:
                insights.append(
                    f"Documented data flow metrics (density: {analysis['data_flow_metrics'].get('flow_density', 0):.2f}, "
                    f"avg path length: {analysis['data_flow_metrics'].get('average_path_length', 0):.2f}) "
                    "supporting SOC2 Common Criteria CC7.1 (System Operation Monitoring)"
                )

        # Add insights to report
        if insights:
            if "provenance_insights" not in report.details:
                report.details["provenance_insights"] = []

            report.details["provenance_insights"].extend(insights)

            # Add to remediation suggestions if applicable
            for req_id, req_data in [(r["id"], r) for r in report.requirements]:
                if req_data["status"] != "Compliant":
                    if req_id not in report.remediation_suggestions:
                        report.remediation_suggestions[req_id] = []

                    # Add relevant insights as remediation suggestions
                    relevant_insights = self._filter_relevant_insights(req_id, insights)
                    if relevant_insights:
                        report.remediation_suggestions[req_id].extend(relevant_insights)

    def _filter_relevant_insights(self, requirement_id: str,
                               insights: List[str]) -> List[str]:
        """
        Filter insights relevant to a specific compliance requirement.

        Args:
            requirement_id: ID of the compliance requirement
            insights: List of all insights

        Returns:
            List[str]: Insights relevant to the requirement
        """
        # Map requirement IDs to keywords for filtering
        keyword_map = {
            # GDPR
            "GDPR-Art30": ["data flows", "sharing", "controller"],
            "GDPR-Art32": ["security", "controls", "access"],
            "GDPR-Art33": ["breach", "incident", "unauthorized"],
            "GDPR-Art15": ["access", "subject access"],
            "GDPR-Art17": ["erasure", "deletion"],

            # HIPAA
            "HIPAA-164.312.a.1": ["access", "identification", "authentication"],
            "HIPAA-164.312.b": ["audit", "controls", "trail"],
            "HIPAA-164.312.c.1": ["integrity", "validation"],
            "HIPAA-164.312.d": ["authentication", "verification"],
            "HIPAA-164.312.e.1": ["transmission", "transfer", "security"],

            # SOC2
            "SOC2-CC1.1": ["organizational", "responsibility"],
            "SOC2-CC5.1": ["access", "security", "cybersecurity"],
            "SOC2-CC5.2": ["changes", "system changes"],
            "SOC2-CC6.1": ["vulnerabilities", "incidents"],
            "SOC2-A1.1": ["availability", "monitoring"],
            "SOC2-PI1.1": ["processing", "integrity", "validation"],
            "SOC2-C1.1": ["confidentiality", "protection"],
            "SOC2-P1.1": ["privacy", "personal information"]
        }

        # Get relevant keywords for this requirement
        keywords = keyword_map.get(requirement_id, [])

        # Filter insights containing any of the keywords
        relevant_insights = []
        for insight in insights:
            if any(keyword.lower() in insight.lower() for keyword in keywords):
                relevant_insights.append(insight)

        return relevant_insights


class AuditContextManager:
    """
    Context manager for comprehensive audit logging in code blocks.

    This class provides a convenient way to log the beginning and end
    of operations, including timing information and exceptions.
    """

    def __init__(self, category: AuditCategory, action: str, resource_id: Optional[str] = None,
                 resource_type: Optional[str] = None, level: AuditLevel = AuditLevel.INFO,
                 details: Optional[Dict[str, Any]] = None, audit_logger=None):
        """
        Initialize the audit context manager.

        Args:
            category: Audit category
            action: Action being performed
            resource_id: ID of the resource being acted upon (optional)
            resource_type: Type of the resource being acted upon (optional)
            level: Audit level
            details: Additional details about the operation (optional)
            audit_logger: AuditLogger instance (optional, will use global instance if None)
        """
        self.category = category
        self.action = action
        self.resource_id = resource_id
        self.resource_type = resource_type
        self.level = level
        self.details = details or {}
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.start_time = None
        self.start_event_id = None

    def __enter__(self):
        """Begin the audited operation."""
        self.start_time = datetime.datetime.now()

        # Log operation start
        self.start_event_id = self.audit_logger.log(
            level=self.level,
            category=self.category,
            action=f"{self.action}_start",
            resource_id=self.resource_id,
            resource_type=self.resource_type,
            details=self.details
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """End the audited operation."""
        end_time = datetime.datetime.now()
        duration_ms = int((end_time - self.start_time).total_seconds() * 1000)

        # Add timing information to details
        details = self.details.copy()
        details["duration_ms"] = duration_ms
        details["start_event_id"] = self.start_event_id

        # Handle exceptions
        if exc_type is not None:
            # Log operation failure
            self.audit_logger.log(
                level=AuditLevel.ERROR,
                category=self.category,
                action=f"{self.action}_error",
                resource_id=self.resource_id,
                resource_type=self.resource_type,
                status="failure",
                details={
                    **details,
                    "error_type": exc_type.__name__,
                    "error_message": str(exc_val)
                }
            )
        else:
            # Log operation completion
            self.audit_logger.log(
                level=self.level,
                category=self.category,
                action=f"{self.action}_complete",
                resource_id=self.resource_id,
                resource_type=self.resource_type,
                status="success",
                details=details
            )

        # Don't suppress exceptions
        return False


def audit_function(category: AuditCategory, action: str, resource_id_arg: Optional[str] = None,
                 resource_type: Optional[str] = None, level: AuditLevel = AuditLevel.INFO,
                 details_extractor: Optional[Callable] = None):
    """
    Decorator for auditing function calls.

    This decorator logs the start and end of function execution,
    including timing information and exceptions.

    Args:
        category: Audit category
        action: Action being performed
        resource_id_arg: Name of the argument containing the resource ID (optional)
        resource_type: Type of the resource being acted upon (optional)
        level: Audit level
        details_extractor: Function to extract additional details from arguments (optional)

    Returns:
        Callable: Decorated function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Get audit logger
            audit_logger = AuditLogger.get_instance()

            # Extract resource ID from arguments if specified
            resource_id = None
            if resource_id_arg:
                if resource_id_arg in kwargs:
                    resource_id = kwargs[resource_id_arg]
                elif args and len(args) > 0:
                    # Try to get from function signature
                    import inspect
                    sig = inspect.signature(func)
                    param_names = list(sig.parameters.keys())

                    for i, param_name in enumerate(param_names):
                        if param_name == resource_id_arg and i < len(args):
                            resource_id = args[i]
                            break

            # Extract additional details if details_extractor is provided
            details = {}
            if details_extractor:
                try:
                    details = details_extractor(*args, **kwargs) or {}
                except Exception as e:
                    logging.error(f"Error extracting audit details: {str(e)}")

            # Add function information to details
            details["function"] = func.__name__
            details["module"] = func.__module__

            # Create audit context
            with AuditContextManager(
                category=category,
                action=action,
                resource_id=resource_id,
                resource_type=resource_type,
                level=level,
                details=details,
                audit_logger=audit_logger
            ):
                # Execute the function
                return func(*args, **kwargs)

        return wrapper

    return decorator


class ProvenanceAuditSearchIntegrator:
    """
    Integrated search across audit logs and provenance records.

    This class provides unified search capabilities across both audit logs
    and provenance records, enabling comprehensive data lineage and compliance
    tracing across the system. The enhanced version supports cross-document
    lineage-aware searching for better understanding of data flows across
    document boundaries.
    """

    def __init__(self, audit_logger=None, provenance_manager=None):
        """
        Initialize the search integrator.

        Args:
            audit_logger: AuditLogger instance (optional, will use global instance if None)
            provenance_manager: EnhancedProvenanceManager instance (optional)
        """
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.provenance_manager = provenance_manager
        self.logger = logging.getLogger(__name__)

        # Initialize provenance manager if needed
        if PROVENANCE_MODULE_AVAILABLE and not self.provenance_manager:
            try:
                self.provenance_manager = EnhancedProvenanceManager()
            except Exception as e:
                self.logger.warning(f"Could not initialize provenance manager: {str(e)}")

    def search(self, query: Dict[str, Any],
             include_audit: bool = True,
             include_provenance: bool = True,
             correlation_mode: str = "auto",
             include_cross_document: bool = False) -> Dict[str, Any]:
        """
        Perform a unified search across audit logs and provenance records.

        This enhanced version supports cross-document lineage-aware searching,
        allowing for discovery of related records across document boundaries.

        Args:
            query: Dictionary containing search parameters
                - timerange: Dict with 'start' and 'end' timestamps
                - user: Optional user to filter by
                - resource_id: Optional resource ID to filter by
                - resource_type: Optional resource type to filter by
                - action: Optional action to filter by
                - status: Optional status to filter by
                - details: Optional dict of details to filter by
                - keywords: Optional list of keywords to search for
                - document_id: Optional document ID for cross-document search
                - link_types: Optional list of link types to filter by
                - max_results: Optional maximum number of results to return
                - max_depth: Optional maximum traversal depth for cross-document search
            include_audit: Whether to include audit events in results
            include_provenance: Whether to include provenance records in results
            correlation_mode: How to correlate audit and provenance records
                - "auto": Automatically detect and establish correlations
                - "linked": Only show records with explicit links
                - "none": Do not correlate records
            include_cross_document: Whether to include cross-document analysis

        Returns:
            Dict[str, Any]: Search results with integrated audit and provenance data
        """
        results = {
            "query": query,
            "timestamp": datetime.datetime.utcnow().isoformat() + 'Z',
            "audit_events": [],
            "provenance_records": [],
            "correlations": []
        }

        # Extract common query parameters
        timerange = query.get("timerange", {})
        start_time = timerange.get("start")
        end_time = timerange.get("end")
        resource_id = query.get("resource_id")
        resource_type = query.get("resource_type")
        document_id = query.get("document_id")
        link_types = query.get("link_types")
        max_results = query.get("max_results", 100)
        max_depth = query.get("max_depth", 2)

        # Search audit logs if requested
        if include_audit:
            try:
                audit_events = self._search_audit_logs(query)
                results["audit_events"] = audit_events[:max_results]
                results["audit_count"] = len(audit_events)
            except Exception as e:
                self.logger.error(f"Error searching audit logs: {str(e)}")
                results["audit_error"] = str(e)

        # Search provenance records if requested
        if include_provenance and PROVENANCE_MODULE_AVAILABLE and self.provenance_manager:
            try:
                # Standard provenance search
                provenance_records = self._search_provenance_records(query)

                # If cross-document search is requested and we have a document ID or resource ID
                if include_cross_document and (document_id or resource_id):
                    cross_doc_records = self._search_cross_document_provenance(
                        document_id or resource_id,
                        max_depth=max_depth,
                        link_types=link_types,
                        start_time=start_time,
                        end_time=end_time
                    )

                    # Merge and deduplicate records
                    existing_record_ids = {r.get("record_id") for r in provenance_records}
                    for record in cross_doc_records:
                        if record.get("record_id") not in existing_record_ids:
                            provenance_records.append(record)
                            existing_record_ids.add(record.get("record_id"))

                    # Add cross-document analysis to results
                    results["cross_document_analysis"] = self._analyze_cross_document_records(
                        document_id or resource_id,
                        provenance_records,
                        max_depth=max_depth,
                        link_types=link_types
                    )

                results["provenance_records"] = provenance_records[:max_results]
                results["provenance_count"] = len(provenance_records)
            except Exception as e:
                self.logger.error(f"Error searching provenance records: {str(e)}")
                results["provenance_error"] = str(e)

        # Correlate results if both types are included
        if include_audit and include_provenance and correlation_mode != "none":
            try:
                correlations = self._correlate_results(
                    results["audit_events"],
                    results["provenance_records"],
                    correlation_mode
                )
                results["correlations"] = correlations
                results["correlation_count"] = len(correlations)
            except Exception as e:
                self.logger.error(f"Error correlating results: {str(e)}")
                results["correlation_error"] = str(e)

        return results

    def _search_audit_logs(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search audit logs based on query parameters.

        Args:
            query: Search query parameters

        Returns:
            List[Dict[str, Any]]: Matching audit events as dictionaries
        """
        # In a real implementation, this would query a database or file storage
        # containing audit events. This is a placeholder implementation.
        return []

    def _search_provenance_records(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search provenance records based on query parameters.

        Args:
            query: Search query parameters

        Returns:
            List[Dict[str, Any]]: Matching provenance records as dictionaries
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return []

        # Extract query parameters
        timerange = query.get("timerange", {})
        start_time = timerange.get("start")
        end_time = timerange.get("end")
        resource_id = query.get("resource_id")
        record_type = query.get("record_type")
        keywords = query.get("keywords")

        try:
            # Format datetime strings for provenance query
            start_dt = None
            end_dt = None

            if start_time:
                start_dt = datetime.datetime.fromisoformat(start_time.rstrip('Z'))

            if end_time:
                end_dt = datetime.datetime.fromisoformat(end_time.rstrip('Z'))

            # Build query parameters for provenance manager
            query_params = {
                "start_timestamp": start_dt,
                "end_timestamp": end_dt
            }

            if resource_id:
                query_params["resource_id"] = resource_id

            if record_type:
                query_params["record_type"] = record_type

            # Query provenance records
            records = self.provenance_manager.query_records(**query_params)

            # Filter by keywords if provided
            if keywords and isinstance(keywords, list) and len(keywords) > 0:
                filtered_records = []
                for record in records:
                    # Check if any keyword is in metadata or description
                    metadata_string = ""
                    if hasattr(record, "metadata") and record.metadata:
                        metadata_string = json.dumps(record.metadata).lower()

                    description = ""
                    if hasattr(record, "description"):
                        description = record.description.lower() if record.description else ""

                    combined_text = metadata_string + " " + description

                    if any(keyword.lower() in combined_text for keyword in keywords):
                        filtered_records.append(record)

                records = filtered_records

            # Convert to dictionaries for the response
            return [
                self._provenance_record_to_dict(record)
                for record in records
            ]

        except Exception as e:
            self.logger.error(f"Error querying provenance records: {str(e)}")
            return []

    def _search_cross_document_provenance(self,
                                      resource_id: str,
                                      max_depth: int = 2,
                                      link_types: Optional[List[str]] = None,
                                      start_time: Optional[str] = None,
                                      end_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for provenance records across document boundaries.

        This method builds a cross-document lineage graph starting from the specified
        resource and traverses document boundaries to find related records.

        Args:
            resource_id: Starting resource ID (can be a record ID or document ID)
            max_depth: Maximum traversal depth across documents
            link_types: Optional list of link types to filter by
            start_time: Optional start time for temporal filtering
            end_time: Optional end time for temporal filtering

        Returns:
            List[Dict[str, Any]]: Related provenance records across document boundaries
        """
        if not PROVENANCE_MODULE_AVAILABLE or not self.provenance_manager:
            return []

        try:
            storage = self.provenance_manager.storage

            if not hasattr(storage, 'build_cross_document_lineage_graph'):
                return []

            # Build cross-document lineage graph
            lineage_graph = storage.build_cross_document_lineage_graph(
                record_ids=resource_id,
                max_depth=max_depth,
                link_types=link_types
            )

            # Extract all record IDs from the graph
            record_ids = list(lineage_graph.nodes)

            # Filter out the starting record ID
            if resource_id in record_ids:
                record_ids.remove(resource_id)

            # Query records by IDs
            records = []
            for record_id in record_ids:
                record = self.provenance_manager.get_record(record_id)
                if record:
                    # Apply temporal filtering if needed
                    if start_time or end_time:
                        record_time = record.timestamp

                        if start_time:
                            start_dt = datetime.datetime.fromisoformat(start_time.rstrip('Z'))
                            if record_time < start_dt:
                                continue

                        if end_time:
                            end_dt = datetime.datetime.fromisoformat(end_time.rstrip('Z'))
                            if record_time > end_dt:
                                continue

                    # Add record with cross-document relationship info
                    record_dict = self._provenance_record_to_dict(record)

                    # Add cross-document relationship information
                    record_dict["cross_document_info"] = {
                        "distance_from_source": self._get_distance_from_source(lineage_graph, resource_id, record_id),
                        "document_id": self._get_document_id_for_record(record),
                        "relationship_path": self._get_relationship_path(lineage_graph, resource_id, record_id)
                    }

                    records.append(record_dict)

            return records

        except Exception as e:
            self.logger.error(f"Error performing cross-document provenance search: {str(e)}")
            return []

    def _get_distance_from_source(self, graph, source_id, target_id) -> int:
        """Get shortest path length between source and target in the graph."""
        import networkx as nx
        try:
            return nx.shortest_path_length(graph, source=source_id, target=target_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return -1

    def _get_document_id_for_record(self, record) -> Optional[str]:
        """Extract document ID from a provenance record."""
        if hasattr(record, "metadata") and record.metadata:
            return record.metadata.get("document_id")
        return None

    def _get_relationship_path(self, graph, source_id, target_id) -> List[Dict[str, str]]:
        """Get the relationship path from source to target in the graph."""
        import networkx as nx
        try:
            path = nx.shortest_path(graph, source=source_id, target=target_id)

            # Build edge relationships along the path
            relationships = []
            for i in range(len(path) - 1):
                from_id = path[i]
                to_id = path[i+1]

                # Get edge data if it exists
                if graph.has_edge(from_id, to_id):
                    edge_data = graph.get_edge_data(from_id, to_id)
                    rel_type = edge_data.get("type", "unknown")
                else:
                    rel_type = "unknown"

                relationships.append({
                    "from": from_id,
                    "to": to_id,
                    "type": rel_type
                })

            return relationships
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def _analyze_cross_document_records(self,
                                    source_id: str,
                                    records: List[Dict[str, Any]],
                                    max_depth: int = 2,
                                    link_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Analyze cross-document relationships in the search results.

        Args:
            source_id: Starting resource ID
            records: List of provenance records
            max_depth: Maximum traversal depth used
            link_types: Link types used for filtering

        Returns:
            Dict[str, Any]: Analysis of cross-document relationships
        """
        try:
            # Extract document IDs from records
            document_ids = set()
            for record in records:
                if "cross_document_info" in record and record["cross_document_info"].get("document_id"):
                    document_ids.add(record["cross_document_info"]["document_id"])

            # Count records by document
            records_by_document = {}
            for record in records:
                doc_id = None
                if "cross_document_info" in record and record["cross_document_info"].get("document_id"):
                    doc_id = record["cross_document_info"]["document_id"]

                if doc_id:
                    if doc_id not in records_by_document:
                        records_by_document[doc_id] = 0
                    records_by_document[doc_id] += 1

            # Count relationship types
            relationship_types = {}
            for record in records:
                if "cross_document_info" in record and "relationship_path" in record["cross_document_info"]:
                    for relationship in record["cross_document_info"]["relationship_path"]:
                        rel_type = relationship.get("type", "unknown")
                        if rel_type not in relationship_types:
                            relationship_types[rel_type] = 0
                        relationship_types[rel_type] += 1

            # Calculate average distance
            distances = [
                record["cross_document_info"]["distance_from_source"]
                for record in records
                if "cross_document_info" in record and
                "distance_from_source" in record["cross_document_info"] and
                record["cross_document_info"]["distance_from_source"] > 0
            ]

            avg_distance = sum(distances) / len(distances) if distances else 0

            return {
                "source_id": source_id,
                "document_count": len(document_ids),
                "documents": list(document_ids),
                "records_by_document": records_by_document,
                "relationship_types": relationship_types,
                "max_depth_used": max_depth,
                "link_types_filter": link_types,
                "average_distance": avg_distance,
                "max_distance": max(distances) if distances else 0
            }

        except Exception as e:
            self.logger.error(f"Error analyzing cross-document records: {str(e)}")
            return {"error": str(e)}

    def _provenance_record_to_dict(self, record: Any) -> Dict[str, Any]:
        """
        Convert a provenance record to a dictionary.

        Args:
            record: Provenance record instance

        Returns:
            Dict[str, Any]: Dictionary representation of the record
        """
        if hasattr(record, "to_dict"):
            return record.to_dict()

        # Fallback to manual conversion
        result = {}

        # Extract common attributes
        for attr in ["record_id", "timestamp", "record_type"]:
            if hasattr(record, attr):
                result[attr] = getattr(record, attr)

        # Add record-type specific attributes
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

        # Include metadata if present
        if hasattr(record, "metadata"):
            result["metadata"] = record.metadata

            # Check for document_id in metadata for easier cross-document analysis
            if record.metadata and "document_id" in record.metadata:
                result["document_id"] = record.metadata["document_id"]

        return result

    def _correlate_results(self, audit_events: List[Dict[str, Any]],
                       provenance_records: List[Dict[str, Any]],
                       mode: str = "auto") -> List[Dict[str, Any]]:
        """
        Correlate audit events and provenance records.

        This enhanced version improves correlation with support for
        document boundary awareness.

        Args:
            audit_events: List of audit events
            provenance_records: List of provenance records
            mode: Correlation mode

        Returns:
            List[Dict[str, Any]]: Correlated records
        """
        correlations = []

        # Map for quick lookups
        audit_by_id = {event.get("event_id"): event for event in audit_events}
        provenance_by_id = {record.get("record_id"): record for record in provenance_records}

        # Map for document grouping
        documents_to_records = {}
        for record_id, record in provenance_by_id.items():
            # Check for document_id in record or metadata
            document_id = record.get("document_id")
            if not document_id and "metadata" in record:
                document_id = record.get("metadata", {}).get("document_id")

            if document_id:
                if document_id not in documents_to_records:
                    documents_to_records[document_id] = []
                documents_to_records[document_id].append(record_id)

        # Look for explicit links in audit events
        for event_id, event in audit_by_id.items():
            details = event.get("details", {})

            # Check for explicit provenance links
            provenance_id = details.get("provenance_record_id")
            if provenance_id and provenance_id in provenance_by_id:
                correlations.append({
                    "type": "explicit",
                    "audit_event_id": event_id,
                    "provenance_record_id": provenance_id,
                    "confidence": 1.0
                })

        # Look for explicit links in provenance records
        for record_id, record in provenance_by_id.items():
            metadata = record.get("metadata", {})

            # Check for explicit audit links
            audit_id = metadata.get("audit_event_id")
            if audit_id and audit_id in audit_by_id:
                # Check if we already have this correlation
                if not any(c["audit_event_id"] == audit_id and c["provenance_record_id"] == record_id
                        for c in correlations):
                    correlations.append({
                        "type": "explicit",
                        "audit_event_id": audit_id,
                        "provenance_record_id": record_id,
                        "confidence": 1.0
                    })

        # If auto mode, look for implicit correlations
        if mode == "auto":
            # Match by resource ID and close timestamp
            for event_id, event in audit_by_id.items():
                if any(c["audit_event_id"] == event_id for c in correlations):
                    continue  # Skip if already correlated

                event_resource = event.get("resource_id")
                if not event_resource:
                    continue

                event_time = datetime.datetime.fromisoformat(event["timestamp"].rstrip('Z'))

                # First try exact resource matches
                for record_id, record in provenance_by_id.items():
                    if any(c["provenance_record_id"] == record_id for c in correlations):
                        continue  # Skip if already correlated

                    # Look for matching resource IDs
                    record_resources = []
                    if "source_id" in record:
                        record_resources.append(record["source_id"])
                    if "data_id" in record:
                        record_resources.append(record["data_id"])
                    if "output_id" in record:
                        record_resources.append(record["output_id"])

                    if event_resource in record_resources:
                        # Check timestamp proximity (within 5 seconds)
                        record_time = datetime.datetime.fromisoformat(record["timestamp"].rstrip('Z'))
                        time_diff = abs((event_time - record_time).total_seconds())

                        if time_diff <= 5:
                            # Add implicit correlation with confidence based on time proximity
                            confidence = 1.0 - (time_diff / 5.0) * 0.5  # 0.5-1.0 based on time diff
                            correlations.append({
                                "type": "implicit",
                                "audit_event_id": event_id,
                                "provenance_record_id": record_id,
                                "confidence": confidence,
                                "match_reason": "resource_id_and_time"
                            })

                # Then try document-level matching for events without direct resource matches
                if not any(c["audit_event_id"] == event_id for c in correlations):
                    # Check if event resource matches a document ID
                    if event_resource in documents_to_records:
                        record_ids = documents_to_records[event_resource]

                        # Find the closest record by timestamp
                        best_record_id = None
                        best_time_diff = float('inf')

                        for record_id in record_ids:
                            if any(c["provenance_record_id"] == record_id for c in correlations):
                                continue  # Skip if already correlated

                            record = provenance_by_id[record_id]
                            record_time = datetime.datetime.fromisoformat(record["timestamp"].rstrip('Z'))
                            time_diff = abs((event_time - record_time).total_seconds())

                            if time_diff < best_time_diff and time_diff <= 60:  # Within 1 minute
                                best_time_diff = time_diff
                                best_record_id = record_id

                        if best_record_id:
                            # Add document-level correlation
                            confidence = 0.7  # Lower confidence for document-level match
                            correlations.append({
                                "type": "implicit",
                                "audit_event_id": event_id,
                                "provenance_record_id": best_record_id,
                                "confidence": confidence,
                                "match_reason": "document_level_match"
                            })

        return correlations


def generate_integrated_compliance_report(standard_name: str,
                                       start_time: Optional[str] = None,
                                       end_time: Optional[str] = None,
                                       output_format: str = "json",
                                       output_path: Optional[str] = None) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Generate an integrated compliance report combining audit and provenance data.

    This function demonstrates the use of the IntegratedComplianceReporter to
    generate comprehensive compliance reports.

    Args:
        standard_name: Name of the compliance standard (GDPR, HIPAA, SOC2, etc.)
        start_time: Start time for the report period (ISO format, optional)
        end_time: End time for the report period (ISO format, optional)
        output_format: Format for the report output (json, html, csv)
        output_path: Path to save the report (optional)

    Returns:
        Optional[Union[str, Dict[str, Any]]]: The report data in the requested format,
                                         or None if saved to a file
    """
    try:
        # Map standard name to enum
        standard_map = {
            "GDPR": ComplianceStandard.GDPR,
            "HIPAA": ComplianceStandard.HIPAA,
            "SOC2": ComplianceStandard.SOC2,
            "PCI_DSS": ComplianceStandard.PCI_DSS,
            "CCPA": ComplianceStandard.CCPA,
            "NIST_800_53": ComplianceStandard.NIST_800_53,
            "ISO_27001": ComplianceStandard.ISO_27001,
            "CUSTOM": ComplianceStandard.CUSTOM
        }

        standard = standard_map.get(standard_name.upper())
        if not standard:
            raise ValueError(f"Unknown compliance standard: {standard_name}")

        # Create reporter based on standard
        if standard == ComplianceStandard.GDPR:
            from ipfs_datasets_py.audit.compliance import GDPRComplianceReporter
            base_reporter = GDPRComplianceReporter()
        elif standard == ComplianceStandard.HIPAA:
            from ipfs_datasets_py.audit.compliance import HIPAAComplianceReporter
            base_reporter = HIPAAComplianceReporter()
        elif standard == ComplianceStandard.SOC2:
            from ipfs_datasets_py.audit.compliance import SOC2ComplianceReporter
            base_reporter = SOC2ComplianceReporter()
        else:
            from ipfs_datasets_py.audit.compliance import ComplianceReporter
            base_reporter = ComplianceReporter(standard)

        # Create the integrated reporter
        reporter = IntegratedComplianceReporter(standard=standard)

        # Copy requirements from base reporter
        for req in base_reporter.requirements:
            reporter.add_requirement(req)

        # Generate the report
        report = reporter.generate_report(
            start_time=start_time,
            end_time=end_time,
            include_cross_document_analysis=True,
            include_lineage_metrics=True
        )

        # Output based on format
        if output_format == "json":
            result = report.to_json(pretty=True)
            if output_path:
                report.save_json(output_path)
                return None
            return result

        elif output_format == "html":
            if output_path:
                report.save_html(output_path)
                return None
            # For HTML without a file path, return the HTML string
            # (This would normally be done by report.save_html writing to a StringIO)
            return "HTML report content would be here"

        elif output_format == "csv":
            if output_path:
                report.save_csv(output_path)
                return None
            # For CSV without a file path, return a placeholder
            return "CSV data would be here"

        else:
            raise ValueError(f"Unsupported output format: {output_format}")

    except Exception as e:
        logging.error(f"Error generating compliance report: {str(e)}")
        logging.exception("Exception details:")
        return {"error": str(e)}
