"""
Example for using the provenance dashboard module.

This example demonstrates how to set up and use the provenance dashboard
to visualize data provenance information, including integration with
audit logging and RAG query visualization.
"""

import os
import json
import time
import logging
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import required modules
from ipfs_datasets_py.analytics.data_provenance import ProvenanceManager, ProvenanceContext
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import LineageTracker
from ipfs_datasets_py.provenance_dashboard import ProvenanceDashboard, setup_provenance_dashboard

# Optional imports for integrated dashboard
try:
    from ipfs_datasets_py.rag.rag_query_visualization import QueryMetricsCollector, RAGQueryVisualizer
    QUERY_VIS_AVAILABLE = True
except ImportError:
    QUERY_VIS_AVAILABLE = False

try:
    from ipfs_datasets_py.audit.audit_logger import AuditLogger
    from ipfs_datasets_py.audit.audit_visualization import setup_audit_visualization
    AUDIT_VIS_AVAILABLE = True
except ImportError:
    AUDIT_VIS_AVAILABLE = False


def create_sample_data_provenance():
    """Create sample provenance data for the example."""
    # Initialize provenance manager
    provenance_manager = ProvenanceManager(
        storage_path=None,  # In-memory only
        enable_ipld_storage=False,
        default_agent_id="example_user",
        tracking_level="detailed"
    )

    # Record a source
    source_id = provenance_manager.record_source(
        data_id="raw_data_001",
        source_type="file",
        location="/path/to/data.csv",
        format="csv",
        description="Raw data from customer survey",
        size=1024 * 1024,  # 1 MB
        hash="sha256:abc123"
    )

    # Record a transformation
    with ProvenanceContext(
        provenance_manager=provenance_manager,
        description="Clean and preprocess survey data",
        transformation_type="preprocessing",
        tool="pandas",
        version="1.5.3",
        input_ids=["raw_data_001"],
        parameters={"dropna": True, "normalize": True}
    ) as context:
        # Simulate processing
        time.sleep(0.5)  # Simulate some work

        # Set output IDs
        context.set_output_ids(["preprocessed_data_001"])

    # Record a query
    query_id = provenance_manager.record_query(
        input_ids=["preprocessed_data_001"],
        query_type="sql",
        query_text="SELECT * FROM survey_data WHERE age > 30",
        description="Filter survey data for respondents over 30",
        query_parameters={"min_age": 30}
    )

    # Record the query result
    result_id = provenance_manager.record_query_result(
        query_id=query_id,
        output_id="filtered_data_001",
        result_count=250,
        result_type="filtered_dataset",
        size=512 * 1024,  # 512 KB
        fields=["id", "age", "gender", "response"]
    )

    # Record a merge operation
    merge_id = provenance_manager.record_merge(
        input_ids=["preprocessed_data_001", "raw_data_002"],
        output_id="merged_data_001",
        merge_type="join",
        description="Merge survey data with external demographic data",
        merge_keys=["respondent_id"],
        merge_strategy="left_join",
        parameters={"how": "left", "on": "respondent_id"}
    )

    # Record a checkpoint
    checkpoint_id = provenance_manager.record_checkpoint(
        data_id="merged_data_001",
        description="Checkpoint after merging data",
        checkpoint_type="snapshot"
    )

    return provenance_manager


def create_sample_cross_document_lineage():
    """Create sample cross-document lineage data."""
    # Initialize lineage tracker
    lineage_tracker = LineageTracker()

    # Add documents
    doc1_id = lineage_tracker.add_document(
        document_id="doc_001",
        name="Research Paper A",
        document_type="paper",
        metadata={
            "author": "John Smith",
            "publication_date": "2023-01-15",
            "keywords": ["machine learning", "neural networks"]
        }
    )

    doc2_id = lineage_tracker.add_document(
        document_id="doc_002",
        name="Research Paper B",
        document_type="paper",
        metadata={
            "author": "Jane Doe",
            "publication_date": "2023-03-22",
            "keywords": ["deep learning", "transformers"]
        }
    )

    doc3_id = lineage_tracker.add_document(
        document_id="doc_003",
        name="Dataset Documentation",
        document_type="documentation",
        metadata={
            "author": "Data Team",
            "creation_date": "2023-02-10",
            "dataset_size": "10GB"
        }
    )

    # Add relationships
    lineage_tracker.add_relationship(
        source_id="doc_002",
        target_id="doc_001",
        relationship_type="cites",
        metadata={
            "citation_context": "As demonstrated by Smith (2023)...",
            "section": "Related Work"
        }
    )

    lineage_tracker.add_relationship(
        source_id="doc_003",
        target_id="doc_001",
        relationship_type="references",
        metadata={
            "reference_type": "methodology",
            "page": 42
        }
    )

    lineage_tracker.add_relationship(
        source_id="doc_002",
        target_id="doc_003",
        relationship_type="uses",
        metadata={
            "usage_context": "We evaluate our model on the dataset described in...",
            "section": "Evaluation"
        }
    )

    return lineage_tracker


def create_sample_query_metrics():
    """Create sample query metrics data."""
    if not QUERY_VIS_AVAILABLE:
        return None

    # Create metrics collector
    metrics = QueryMetricsCollector(window_size=86400)  # 24 hours

    # Record sample queries
    for i in range(10):
        query_id = f"query_{i}"

        # Record query start
        metrics.record_query_start(
            query_id=query_id,
            query_params={
                "query_text": f"Sample query text {i}",
                "query_type": "semantic" if i % 2 == 0 else "keyword",
                "filters": {"category": "finance" if i % 3 == 0 else "technology"}
            }
        )

        # Simulate processing
        time.sleep(0.1)

        # Record query end
        metrics.record_query_end(
            query_id=query_id,
            results=[{"id": f"doc_{j}", "score": 0.9 - (j * 0.1)} for j in range(5)],
            metrics={
                "vector_search_time": 0.05,
                "graph_traversal_time": 0.03,
                "results_count": 5
            }
        )

    return metrics


def create_sample_audit_metrics():
    """Create sample audit metrics data."""
    if not AUDIT_VIS_AVAILABLE:
        return None, None

    # Create audit logger
    audit_logger = AuditLogger()

    # Log some sample events
    audit_logger.info(
        category="DATA_ACCESS",
        action="read_dataset",
        details={"dataset_id": "ds_001", "user": "alice"}
    )

    audit_logger.warning(
        category="SECURITY",
        action="failed_authentication",
        details={"user": "bob", "ip": "192.168.1.10", "reason": "invalid_password"}
    )

    audit_logger.error(
        category="DATA_PROCESSING",
        action="transformation_failed",
        details={"job_id": "job_123", "reason": "missing_column"}
    )

    # Set up audit visualization
    metrics, visualizer, alert_manager = setup_audit_visualization(audit_logger)

    return audit_logger, metrics


def main():
    """Run the provenance dashboard example."""
    print("Starting Provenance Dashboard Example...")

    # Create output directory
    output_dir = os.path.join(os.getcwd(), "dashboard_output")
    os.makedirs(output_dir, exist_ok=True)

    # Create sample data
    print("Creating sample provenance data...")
    provenance_manager = create_sample_data_provenance()

    print("Creating sample cross-document lineage data...")
    lineage_tracker = create_sample_cross_document_lineage()

    print("Creating sample query metrics data...")
    query_metrics = create_sample_query_metrics()

    print("Creating sample audit metrics data...")
    audit_logger, audit_metrics = create_sample_audit_metrics()

    # Set up the dashboard
    print("Setting up provenance dashboard...")

    # Option 1: Manual setup
    # dashboard = ProvenanceDashboard(
    #     provenance_manager=provenance_manager,
    #     lineage_tracker=lineage_tracker,
    #     query_visualizer=RAGQueryVisualizer(query_metrics) if query_metrics else None
    # )
    # if audit_metrics:
    #     dashboard.audit_metrics = audit_metrics

    # Option 2: Use the convenience function
    dashboard = setup_provenance_dashboard(
        provenance_manager=provenance_manager,
        lineage_tracker=lineage_tracker,
        query_metrics=query_metrics,
        audit_metrics=audit_metrics
    )

    # Generate visualizations
    print("Generating data lineage visualization...")
    lineage_path = os.path.join(output_dir, "data_lineage.png")
    dashboard.visualize_data_lineage(
        data_ids=["filtered_data_001", "merged_data_001"],
        output_file=lineage_path
    )
    print(f"Data lineage visualization saved to: {lineage_path}")

    print("Generating cross-document lineage visualization...")
    cross_doc_path = os.path.join(output_dir, "cross_doc_lineage.png")
    dashboard.visualize_cross_document_lineage(
        document_ids=["doc_001", "doc_002", "doc_003"],
        output_file=cross_doc_path
    )
    print(f"Cross-document lineage visualization saved to: {cross_doc_path}")

    # Generate provenance report
    print("Generating provenance report...")
    report_path = os.path.join(output_dir, "provenance_report.html")
    dashboard.generate_provenance_report(
        data_ids=["filtered_data_001", "merged_data_001"],
        format="html",
        include_lineage_graph=True,
        include_audit_events=True,
        include_query_metrics=True,
        output_file=report_path
    )
    print(f"Provenance report saved to: {report_path}")

    # Create integrated dashboard
    print("Creating integrated dashboard...")
    dashboard_path = dashboard.create_integrated_dashboard(
        output_dir=output_dir,
        data_ids=["filtered_data_001", "merged_data_001", "raw_data_001", "preprocessed_data_001"],
        include_audit=True,
        include_query=True,
        include_cross_doc=True
    )
    print(f"Integrated dashboard saved to: {dashboard_path}")

    print("\nExample completed successfully!")
    print(f"All outputs saved to: {output_dir}")
    print("Open the HTML files in a web browser to view the dashboards and reports.")


if __name__ == "__main__":
    main()
