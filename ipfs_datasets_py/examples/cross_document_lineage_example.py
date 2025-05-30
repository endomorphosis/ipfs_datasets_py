"""
Cross-Document Lineage Tracking Example

This example demonstrates the enhanced cross-document lineage tracking
capabilities in ipfs_datasets_py, including domain-based organization,
transformation details, version tracking, and IPLD integration.
"""

import os
import sys
import time
import datetime
import logging
import networkx as nx
import matplotlib.pyplot as plt

# Add parent directory to path to ensure imports work
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import required modules
from ipfs_datasets_py.data_provenance_enhanced import (
    EnhancedProvenanceManager, SourceRecord, TransformationRecord,
    ProvenanceRecordType
)
from ipfs_datasets_py.cross_document_lineage import (
    EnhancedLineageTracker, LineageNode, LineageLink, LineageDomain,
    LineageBoundary, LineageTransformationDetail, LineageVersion, LineageSubgraph
)
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_provenance_data():
    """
    Create test provenance data with multiple documents for demonstration.

    Returns:
        EnhancedProvenanceManager: Provenance manager with test data
    """
    # Create provenance manager
    manager = EnhancedProvenanceManager()

    # Create records for Document 1
    doc1_metadata = {"document_id": "doc1", "title": "Source Dataset"}

    # Source records
    source1 = manager.record_source(
        source_id="dataset1",
        source_type="csv",
        source_uri="s3://data-bucket/dataset1.csv",
        description="Original source data",
        metadata=doc1_metadata
    )

    source2 = manager.record_source(
        source_id="dataset2",
        source_type="api",
        source_uri="https://api.example.com/data",
        description="API data source",
        metadata=doc1_metadata
    )

    # Transformation records
    transform1 = manager.record_transformation(
        input_ids=[source1],
        output_id="cleaned_data1",
        transformation_type="clean",
        description="Clean dataset1",
        metadata=doc1_metadata
    )

    transform2 = manager.record_transformation(
        input_ids=[source2],
        output_id="cleaned_data2",
        transformation_type="clean",
        description="Clean dataset2",
        metadata=doc1_metadata
    )

    # Create records for Document 2
    doc2_metadata = {"document_id": "doc2", "title": "Analytics Processing"}

    # Source records (references data from Document 1)
    source3 = manager.record_source(
        source_id="cleaned_data1",
        source_type="parquet",
        source_uri="s3://data-bucket/cleaned_data1.parquet",
        description="Cleaned data from Document 1",
        metadata=doc2_metadata
    )

    source4 = manager.record_source(
        source_id="cleaned_data2",
        source_type="parquet",
        source_uri="s3://data-bucket/cleaned_data2.parquet",
        description="Cleaned data from Document 1",
        metadata=doc2_metadata
    )

    # Transformation records for Document 2
    transform3 = manager.record_transformation(
        input_ids=[source3, source4],
        output_id="merged_data",
        transformation_type="merge",
        description="Merge cleaned datasets",
        metadata=doc2_metadata
    )

    transform4 = manager.record_transformation(
        input_ids=[transform3],
        output_id="analyzed_data",
        transformation_type="analyze",
        description="Analyze merged data",
        metadata=doc2_metadata
    )

    # Create records for Document 3
    doc3_metadata = {"document_id": "doc3", "title": "ML Training"}

    # Source records (references data from Document 2)
    source5 = manager.record_source(
        source_id="analyzed_data",
        source_type="parquet",
        source_uri="s3://data-bucket/analyzed_data.parquet",
        description="Analyzed data from Document 2",
        metadata=doc3_metadata
    )

    # Transformation records for Document 3
    transform5 = manager.record_transformation(
        input_ids=[source5],
        output_id="training_data",
        transformation_type="split",
        description="Split into training data",
        metadata=doc3_metadata
    )

    transform6 = manager.record_transformation(
        input_ids=[transform5],
        output_id="ml_model",
        transformation_type="train",
        description="Train ML model",
        metadata=doc3_metadata
    )

    # Create cross-document links
    storage = manager.storage

    # Link Document 1 to Document 2
    enhancer = CrossDocumentLineageEnhancer(storage)

    # Link with semantic context and boundary type
    enhancer.link_cross_document_provenance(
        source_record_id=transform1,
        target_record_id=source3,
        link_type="derived_from",
        confidence=0.95,
        semantic_context={
            "category": "causal",
            "description": "Direct data derivation with cleaning",
            "keywords": ["clean", "transform", "source"]
        },
        boundary_type="dataset"
    )

    enhancer.link_cross_document_provenance(
        source_record_id=transform2,
        target_record_id=source4,
        link_type="derived_from",
        confidence=0.95,
        semantic_context={
            "category": "causal",
            "description": "Direct data derivation with cleaning",
            "keywords": ["clean", "transform", "source"]
        },
        boundary_type="dataset"
    )

    # Link Document 2 to Document 3
    enhancer.link_cross_document_provenance(
        source_record_id=transform4,
        target_record_id=source5,
        link_type="derived_from",
        confidence=0.95,
        semantic_context={
            "category": "causal",
            "description": "Data analysis pipeline",
            "keywords": ["analyze", "process", "derived"]
        },
        boundary_type="system"
    )

    return manager


def demonstrate_enhanced_cross_document_lineage():
    """Demonstrate enhanced cross-document lineage capabilities."""
    # Create test data
    print("Creating test provenance data...")
    manager = create_test_provenance_data()

    # Create enhancer instance
    enhancer = CrossDocumentLineageEnhancer(manager.storage)

    # 1. Build and visualize enhanced cross-document lineage graph
    print("\nBuilding enhanced cross-document lineage graph...")
    start_record = "dataset1"  # Start from the first source record

    lineage_graph = enhancer.build_enhanced_cross_document_lineage_graph(
        record_ids=start_record,
        max_depth=4,
        include_semantic_analysis=True
    )

    print(f"Graph created with {lineage_graph.number_of_nodes()} nodes and "
          f"{lineage_graph.number_of_edges()} edges")

    # Print document clusters
    if 'document_clusters' in lineage_graph.graph:
        print("\nDocument clusters:")
        for cluster_id, docs in lineage_graph.graph['document_clusters'].items():
            print(f"  {cluster_id}: {docs}")

    # Print boundary types
    if 'boundary_types' in lineage_graph.graph:
        print("\nBoundary types:")
        for boundary_type, count in lineage_graph.graph['boundary_types'].items():
            print(f"  {boundary_type}: {count}")

    # Save visualization to file
    print("\nGenerating visualization...")
    image_path = os.path.join(os.path.dirname(__file__), "cross_doc_lineage.png")
    enhancer.visualize_enhanced_cross_document_lineage(
        lineage_graph=lineage_graph,
        highlight_cross_document=True,
        highlight_boundaries=True,
        show_clusters=True,
        show_metrics=True,
        file_path=image_path,
        format="png"
    )
    print(f"Visualization saved to {image_path}")

    # 2. Analyze cross-document lineage
    print("\nAnalyzing cross-document lineage...")
    analysis = enhancer.analyze_cross_document_lineage(
        lineage_graph=lineage_graph,
        include_semantic_analysis=True,
        include_impact_analysis=True,
        include_cluster_analysis=True
    )

    # Print key analysis results
    print("\nCross-document lineage analysis results:")
    print(f"Basic metrics: {analysis['basic_metrics']}")

    if 'document_boundaries' in analysis:
        print(f"Document boundaries: {analysis['document_boundaries']}")

    if 'semantic_relationships' in analysis:
        print(f"Semantic relationships: {analysis['semantic_relationships']}")

    if 'critical_paths' in analysis:
        print(f"Critical paths: {len(analysis['critical_paths'])}")
        for i, path in enumerate(analysis['critical_paths']):
            print(f"  Path {i+1}: {' -> '.join(path)}")

    if 'time_analysis' in analysis:
        print(f"Time span: {analysis['time_analysis']['time_span_days']:.2f} days")

    # 3. Export lineage graph
    print("\nExporting lineage graph...")
    export_path = os.path.join(os.path.dirname(__file__), "cross_doc_lineage.json")
    enhancer.export_cross_document_lineage(
        lineage_graph=lineage_graph,
        format="json",
        file_path=export_path
    )
    print(f"Lineage graph exported to {export_path}")

    # 4. Perform impact analysis
    print("\nPerforming impact analysis on source record...")
    impact_analyzer = CrossDocumentImpactAnalyzer(manager.storage)
    impact = impact_analyzer.analyze_impact(start_record, max_depth=4)

    print(f"Impact metrics: {impact['impact_metrics']}")
    print(f"Impacted documents: {list(impact['impacted_documents'].keys())}")

    # Visualize impact
    impact_path = os.path.join(os.path.dirname(__file__), "impact_analysis.png")
    impact_analyzer.visualize_impact(
        source_id=start_record,
        max_depth=4,
        file_path=impact_path,
        format="png"
    )
    print(f"Impact visualization saved to {impact_path}")


if __name__ == "__main__":
    demonstrate_enhanced_cross_document_lineage()
