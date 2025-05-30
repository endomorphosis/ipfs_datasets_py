"""
Examples of using the audit logging and data provenance integration.

This module provides practical examples of using the integrated audit logging
and data provenance tracking system for comprehensive data tracking and compliance.
"""

import os
import json
import datetime
import logging
from typing import Dict, List, Any, Optional, Union

from ipfs_datasets_py.audit.audit_logger import (
    AuditLogger, AuditEvent, AuditCategory, AuditLevel
)
from ipfs_datasets_py.audit.compliance import (
    ComplianceStandard, ComplianceReport, ComplianceReporter,
    GDPRComplianceReporter, HIPAAComplianceReporter, SOC2ComplianceReporter
)
from ipfs_datasets_py.audit.integration import (
    AuditProvenanceIntegrator, IntegratedComplianceReporter,
    ProvenanceAuditSearchIntegrator, generate_integrated_compliance_report,
    AuditDatasetIntegrator, AuditContextManager
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


def setup_audit_provenance_integration():
    """
    Set up the integrated audit and provenance tracking system.

    This function initializes and configures the bidirectional integration
    between audit logging and data provenance tracking.

    Returns:
        tuple: (audit_logger, provenance_manager, integrator)
    """
    # Get the global audit logger instance
    audit_logger = AuditLogger.get_instance()

    # Configure logging to show all categories and levels
    audit_logger.min_level = AuditLevel.DEBUG
    audit_logger.included_categories = set()  # Include all categories
    audit_logger.excluded_categories = set()  # Exclude no categories

    # Initialize provenance manager if available
    provenance_manager = None
    if PROVENANCE_MODULE_AVAILABLE:
        try:
            provenance_manager = EnhancedProvenanceManager()
            print("Provenance tracking enabled.")
        except Exception as e:
            print(f"Could not initialize provenance manager: {str(e)}")
    else:
        print("Provenance module not available. Some features will be disabled.")

    # Create and set up the integrator
    integrator = AuditProvenanceIntegrator(
        audit_logger=audit_logger,
        provenance_manager=provenance_manager
    )

    # Set up bidirectional event listeners
    if PROVENANCE_MODULE_AVAILABLE and provenance_manager:
        integrator.setup_audit_event_listener()
        print("Bidirectional audit-provenance integration established.")

    return audit_logger, provenance_manager, integrator


def example_dataset_processing_with_provenance():
    """
    Example of processing a dataset with integrated audit and provenance tracking.

    This example demonstrates how to use the integrated system to track
    a complete data processing workflow, from loading to transformation
    to export, with full audit logging and provenance tracking.
    """
    # Set up the integrated system
    audit_logger, provenance_manager, integrator = setup_audit_provenance_integration()

    # Create dataset integrator for convenient dataset operations logging
    dataset_integrator = AuditDatasetIntegrator(audit_logger=audit_logger)

    # Example 1: Load a dataset with audit logging and provenance tracking
    dataset_name = "example_dataset"
    source_uri = "s3://example-bucket/datasets/example_dataset.parquet"

    print("\n--- Example: Dataset Loading ---")
    # Log dataset loading in audit log
    load_event_id = dataset_integrator.record_dataset_load(
        dataset_name=dataset_name,
        dataset_id="ds123",
        source="s3",
        user="example_user"
    )
    print(f"Recorded dataset load in audit log (event_id: {load_event_id})")

    # If provenance is available, a source record would be automatically created
    # through the audit event listener we set up earlier
    if PROVENANCE_MODULE_AVAILABLE and provenance_manager:
        # For demonstration, we'll create an explicit provenance record
        source_record_id = provenance_manager.record_source(
            source_id="ds123",
            source_type="dataset",
            source_uri=source_uri,
            metadata={
                "format": "parquet",
                "size_bytes": 1024000,
                "audit_event_id": load_event_id
            }
        )
        print(f"Created provenance source record (record_id: {source_record_id})")

    # Example 2: Transform dataset with audit logging and provenance tracking
    print("\n--- Example: Dataset Transformation ---")
    # Log dataset transformation in audit log
    transform_event_id = dataset_integrator.record_dataset_transform(
        input_dataset="ds123",
        output_dataset="ds123_processed",
        transformation_type="normalize",
        parameters={
            "columns": ["col1", "col2"],
            "method": "min_max_scaling"
        },
        user="example_user"
    )
    print(f"Recorded dataset transformation in audit log (event_id: {transform_event_id})")

    # If provenance is available, a transformation record would be automatically created
    if PROVENANCE_MODULE_AVAILABLE and provenance_manager:
        # For demonstration, we'll create an explicit provenance record
        transform_record_id = provenance_manager.record_transformation(
            input_ids=["ds123"],
            output_id="ds123_processed",
            transformation_type="normalize",
            parameters={
                "columns": ["col1", "col2"],
                "method": "min_max_scaling"
            },
            metadata={
                "audit_event_id": transform_event_id
            }
        )
        print(f"Created provenance transformation record (record_id: {transform_record_id})")

    # Example 3: Save dataset with audit logging and provenance tracking
    print("\n--- Example: Dataset Saving ---")
    # Log dataset saving in audit log
    save_event_id = dataset_integrator.record_dataset_save(
        dataset_name="example_dataset_processed",
        dataset_id="ds123_processed",
        destination="ipfs",
        format="car",
        user="example_user"
    )
    print(f"Recorded dataset save in audit log (event_id: {save_event_id})")

    # Example 4: Using context manager for audit logging
    print("\n--- Example: Using Audit Context Manager ---")
    # Use context manager to log an operation with timing information
    with AuditContextManager(
        category=AuditCategory.DATA_MODIFICATION,
        action="process_dataset",
        resource_id="ds123_processed",
        resource_type="dataset",
        details={
            "operation": "validate",
            "validation_rules": ["no_nulls", "range_check"]
        }
    ):
        # Simulate processing
        print("Processing dataset...")
        import time
        time.sleep(1)  # Simulate work
        print("Dataset processing complete.")

    print("Context manager automatically logged start and completion events with timing information.")

    # Example 5: Cross-document lineage analysis
    if PROVENANCE_MODULE_AVAILABLE and provenance_manager:
        print("\n--- Example: Cross-Document Lineage Analysis ---")
        try:
            # Get record IDs for analysis
            record_ids = ["ds123", "ds123_processed"]
            if hasattr(provenance_manager, 'storage') and isinstance(provenance_manager.storage, IPLDProvenanceStorage):
                # Build lineage graph
                lineage_graph = provenance_manager.storage.build_cross_document_lineage_graph(
                    record_ids=record_ids,
                    max_depth=2
                )

                # Analyze lineage
                analysis = provenance_manager.storage.analyze_cross_document_lineage(lineage_graph)

                print(f"Created lineage graph with {analysis.get('node_count', 0)} nodes and "
                     f"{analysis.get('edge_count', 0)} edges.")

                if 'critical_paths' in analysis:
                    print(f"Identified {len(analysis['critical_paths'])} critical data flow paths.")

                if 'hub_records' in analysis:
                    print(f"Identified {len(analysis['hub_records'])} key hub records that "
                         f"multiple data flows pass through.")
            else:
                print("IPLDProvenanceStorage not available for lineage analysis.")
        except Exception as e:
            print(f"Error performing lineage analysis: {str(e)}")

    return {
        "load_event_id": load_event_id,
        "transform_event_id": transform_event_id,
        "save_event_id": save_event_id,
        "source_record_id": source_record_id if PROVENANCE_MODULE_AVAILABLE and provenance_manager else None,
        "transform_record_id": transform_record_id if PROVENANCE_MODULE_AVAILABLE and provenance_manager else None
    }


def example_generate_compliance_report():
    """
    Example of generating a compliance report with integrated audit and provenance data.

    This example demonstrates how to use the integrated compliance reporting system
    to generate comprehensive reports for regulatory compliance.
    """
    print("\n--- Example: Generating Compliance Reports ---")

    # Example 1: Generate GDPR compliance report
    print("\n1. Generating GDPR Compliance Report")
    gdpr_report = generate_integrated_compliance_report(
        standard_name="GDPR",
        start_time=(datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(),
        end_time=datetime.datetime.now().isoformat(),
        output_format="json"
    )

    # For brevity, we'll just show that it was generated
    if isinstance(gdpr_report, str):
        print("Generated GDPR compliance report in JSON format.")
        print(f"Report size: {len(gdpr_report)} characters")
    elif isinstance(gdpr_report, dict) and "error" in gdpr_report:
        print(f"Error generating report: {gdpr_report['error']}")

    # Example 2: Generate HIPAA compliance report with file output
    print("\n2. Generating HIPAA Compliance Report")
    report_path = os.path.join(os.getcwd(), "hipaa_compliance_report.html")
    try:
        hipaa_report = generate_integrated_compliance_report(
            standard_name="HIPAA",
            output_format="html",
            output_path=report_path
        )
        print(f"Generated HIPAA compliance report at: {report_path}")
    except Exception as e:
        print(f"Error generating HIPAA report: {str(e)}")

    # Example 3: Create a custom compliance report with provenance integration
    print("\n3. Creating Custom Compliance Report with Provenance Integration")
    try:
        # Set up the integrated system
        audit_logger, provenance_manager, integrator = setup_audit_provenance_integration()

        # Create a custom integrated compliance reporter
        reporter = IntegratedComplianceReporter(
            standard=ComplianceStandard.SOC2,
            audit_logger=audit_logger,
            provenance_manager=provenance_manager
        )

        # Add custom SOC2 requirements
        reporter.add_requirement(ComplianceRequirement(
            id="SOC2-Custom1",
            standard=ComplianceStandard.SOC2,
            description="Data integrity across processing pipeline",
            audit_categories=[AuditCategory.DATA_MODIFICATION, AuditCategory.PROVENANCE],
            actions=["transform", "process", "data_transformation"]
        ))

        reporter.add_requirement(ComplianceRequirement(
            id="SOC2-Custom2",
            standard=ComplianceStandard.SOC2,
            description="Complete audit trail of data access",
            audit_categories=[AuditCategory.DATA_ACCESS],
            actions=["read", "query", "export", "data_source_access"]
        ))

        # Generate the report
        report = reporter.generate_report(
            include_cross_document_analysis=True,
            include_lineage_metrics=True
        )

        print(f"Generated custom SOC2 compliance report checking {len(report.requirements)} requirements.")
        print(f"Overall compliance status: {'Compliant' if report.compliant else 'Non-Compliant'}")

        # Show summary statistics
        print(f"Requirements checked: {report.summary.get('total_requirements', 0)}")
        print(f"Compliant: {report.summary.get('compliant_count', 0)}")
        print(f"Non-Compliant: {report.summary.get('non_compliant_count', 0)}")
        print(f"Partial: {report.summary.get('partial_count', 0)}")
        print(f"Compliance rate: {report.summary.get('compliance_rate', 0)}%")

        # If provenance insights were added
        if "provenance_insights" in report.details:
            print("\nProvenance insights:")
            for insight in report.details["provenance_insights"]:
                print(f"- {insight}")

    except Exception as e:
        print(f"Error creating custom report: {str(e)}")


def example_integrated_search():
    """
    Example of integrated search across audit logs and provenance records.

    This example demonstrates how to perform unified searches that span
    both audit logs and provenance records, with correlation between them.
    """
    print("\n--- Example: Integrated Search ---")

    # Set up the integrated system
    audit_logger, provenance_manager, integrator = setup_audit_provenance_integration()

    # Create search integrator
    search = ProvenanceAuditSearchIntegrator(
        audit_logger=audit_logger,
        provenance_manager=provenance_manager
    )

    # Example 1: Search by time range and resource type
    print("\n1. Search by Time Range and Resource Type")
    query1 = {
        "timerange": {
            "start": (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(),
            "end": datetime.datetime.now().isoformat()
        },
        "resource_type": "dataset"
    }

    results1 = search.search(
        query=query1,
        include_audit=True,
        include_provenance=True,
        correlation_mode="auto"
    )

    print(f"Found {results1.get('audit_count', 0)} audit events")
    print(f"Found {results1.get('provenance_count', 0)} provenance records")
    print(f"Established {results1.get('correlation_count', 0)} correlations between records")

    # Example 2: Search for a specific resource ID
    print("\n2. Search for a Specific Resource ID")
    query2 = {
        "resource_id": "ds123_processed"
    }

    results2 = search.search(
        query=query2,
        include_audit=True,
        include_provenance=True
    )

    print(f"Found {results2.get('audit_count', 0)} audit events")
    print(f"Found {results2.get('provenance_count', 0)} provenance records")
    print(f"Established {results2.get('correlation_count', 0)} correlations between records")

    # Example 3: Search with explicit correlations only
    print("\n3. Search with Explicit Correlations Only")
    query3 = {
        "action": "transform"
    }

    results3 = search.search(
        query=query3,
        include_audit=True,
        include_provenance=True,
        correlation_mode="linked"  # Only show explicitly linked records
    )

    print(f"Found {results3.get('audit_count', 0)} audit events")
    print(f"Found {results3.get('provenance_count', 0)} provenance records")
    print(f"Established {results3.get('correlation_count', 0)} explicit correlations between records")


def example_cross_document_audit_search():
    """
    Example of cross-document lineage-aware audit and provenance search.

    This example demonstrates how to use the enhanced cross-document lineage
    features to search for related audit and provenance records across document
    boundaries, providing a comprehensive view of data flows.
    """
    print("\n--- Example: Cross-Document Lineage-Aware Audit Search ---")

    # Set up the integrated system
    audit_logger, provenance_manager, integrator = setup_audit_provenance_integration()

    # Create search integrator
    search = ProvenanceAuditSearchIntegrator(
        audit_logger=audit_logger,
        provenance_manager=provenance_manager
    )

    # Example 1: Cross-document search starting from a specific document
    print("\n1. Cross-Document Search from a Specific Document")

    # First, create some test data for the example
    if PROVENANCE_MODULE_AVAILABLE and provenance_manager:
        # For demonstration, let's assume we've processed multiple related documents
        doc1_id = "document_1"
        doc2_id = "document_2"
        doc3_id = "document_3"

        # Create records for document 1
        source_record_id = provenance_manager.record_source(
            source_id=doc1_id,
            source_type="dataset",
            source_uri="s3://example-bucket/document_1.csv",
            metadata={
                "document_id": doc1_id,
                "format": "csv",
                "size_bytes": 1024000
            }
        )

        # Create records for document 2 with relationship to document 1
        transform_record_id = provenance_manager.record_transformation(
            input_ids=[doc1_id],
            output_id=doc2_id,
            transformation_type="process",
            parameters={"operation": "filter"},
            metadata={
                "document_id": doc2_id,
                "cross_document": True,
                "relationship_type": "derived_from"
            }
        )

        # Create records for document 3 with relationship to document 2
        export_record_id = provenance_manager.record_transformation(
            input_ids=[doc2_id],
            output_id=doc3_id,
            transformation_type="export",
            parameters={"format": "parquet"},
            metadata={
                "document_id": doc3_id,
                "cross_document": True,
                "relationship_type": "exported_from"
            }
        )

        print(f"Created test documents and records for demonstration")
        print(f"- Source document: {doc1_id} (record: {source_record_id})")
        print(f"- Transformed document: {doc2_id} (record: {transform_record_id})")
        print(f"- Exported document: {doc3_id} (record: {export_record_id})")

        # Now perform a cross-document search starting from document 1
        print("\nPerforming cross-document search starting from document 1:")
        query1 = {
            "document_id": doc1_id,
            "max_depth": 3,
            "link_types": ["derived_from", "exported_from", "processes"]
        }

        results1 = search.search(
            query=query1,
            include_audit=True,
            include_provenance=True,
            correlation_mode="auto",
            include_cross_document=True  # Enable cross-document search
        )

        print(f"Found {results1.get('provenance_count', 0)} provenance records across document boundaries")
        print(f"Documents involved: {len(results1.get('cross_document_analysis', {}).get('documents', []))}")

        if "cross_document_analysis" in results1:
            analysis = results1["cross_document_analysis"]
            print("\nCross-document analysis:")
            print(f"- Documents involved: {analysis.get('document_count', 0)}")
            if "documents" in analysis:
                print(f"- Document IDs: {', '.join(analysis.get('documents', []))}")
            if "relationship_types" in analysis:
                print("- Relationship types:")
                for rel_type, count in analysis.get("relationship_types", {}).items():
                    print(f"  * {rel_type}: {count}")

        # Example 2: Search with compliance-focused link types
        print("\n2. Compliance-Focused Cross-Document Search")
        query2 = {
            "document_id": doc1_id,
            "max_depth": 3,
            "link_types": ["contains_pii", "processes_pii", "anonymizes"]  # Focus on PII-related links
        }

        results2 = search.search(
            query=query2,
            include_audit=True,
            include_provenance=True,
            include_cross_document=True
        )

        print(f"Found {results2.get('provenance_count', 0)} provenance records with compliance-focused link types")

        # Example 3: Search with document boundary analysis
        print("\n3. Document Boundary Analysis")
        # Generate a compliance report that includes cross-document analysis
        if hasattr(provenance_manager, 'storage') and hasattr(provenance_manager.storage, 'build_cross_document_lineage_graph'):
            from ipfs_datasets_py.audit.compliance import ComplianceStandard
            from ipfs_datasets_py.audit.integration import IntegratedComplianceReporter

            reporter = IntegratedComplianceReporter(
                standard=ComplianceStandard.GDPR,
                audit_logger=audit_logger,
                provenance_manager=provenance_manager
            )

            # Generate report with cross-document analysis
            report = reporter.generate_report(
                include_cross_document_analysis=True,
                include_lineage_metrics=True
            )

            print("Generated compliance report with cross-document lineage analysis")
            if "cross_document_lineage" in report.details:
                lineage_info = report.details["cross_document_lineage"]
                print(f"- Document count: {lineage_info.get('document_count', 0)}")
                if "document_boundaries" in lineage_info:
                    boundaries = lineage_info["document_boundaries"]
                    print(f"- Boundary count: {boundaries.get('count', 0)}")
                    print(f"- Cross-boundary flows: {boundaries.get('cross_boundary_flow_count', 0)}")

                if "provenance_insights" in report.details:
                    print("\nCompliance insights from cross-document analysis:")
                    for insight in report.details.get("provenance_insights", [])[:3]:
                        print(f"- {insight}")
    else:
        print("Provenance module not available. Cannot perform cross-document search.")


if __name__ == "__main__":
    # Configure basic logging
    logging.basicConfig(level=logging.INFO,
                      format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    print("=== Integrated Audit and Provenance System Examples ===\n")

    # Run the complete dataset processing example
    processing_results = example_dataset_processing_with_provenance()

    # Generate compliance reports
    example_generate_compliance_report()

    # Perform integrated searches
    example_integrated_search()

    # Demonstrate cross-document lineage-aware audit search
    example_cross_document_audit_search()

    print("\n=== All Examples Completed ===")
