#!/usr/bin/env python3
"""
Example script demonstrating the enhanced data provenance and lineage reporting capabilities.

This script shows how to:
1. Create and track provenance for data transformations
2. Record data lineage through multiple processing steps
3. Generate provenance reports in different formats
4. Create lineage visualizations

Usage:
    python provenance_report_example.py

Notes:
    This is for demonstration purposes only and doesn't process real data.
"""

import os
import time
import uuid
import json
import datetime
from typing import Dict, List, Any, Optional

from ipfs_datasets_py.security import (
    SecurityManager,
    SecurityConfig,
    DataProvenance,
    DataLineage,
    ProcessStep
)


def setup_security():
    """Initialize the security manager with a basic configuration."""
    config = SecurityConfig(
        security_dir=os.path.expanduser("~/.ipfs_datasets/security"),
        track_provenance=True,
        log_all_access=True
    )
    security_manager = SecurityManager.initialize(config)
    return security_manager


def create_sample_dataset(security_manager: SecurityManager) -> str:
    """
    Create a sample dataset and record its provenance.

    Args:
        security_manager: The security manager instance

    Returns:
        str: The data ID of the created dataset
    """
    # Generate a data ID
    data_id = f"dataset_{uuid.uuid4()}"

    # Record basic provenance information
    security_manager.record_provenance(
        data_id=data_id,
        source="example_source",
        creator="example_user",
        creation_time=datetime.datetime.now().isoformat(),
        process_steps=[],
        parent_ids=[],
        checksum="0x123456789abcdef",
        version="1.0",
        data_type="dataset",
        schema={"columns": ["id", "name", "value"]},
        size_bytes=1024,
        record_count=100,
        content_type="application/json",
        lineage_info={
            "source_system": "example_system",
            "source_type": "database",
            "extraction_method": "sql_query",
            "extraction_time": datetime.datetime.now().isoformat()
        },
        tags=["example", "sample", "demo"]
    )

    print(f"Created sample dataset with ID: {data_id}")
    return data_id


def transform_data(security_manager: SecurityManager, source_data_id: str) -> str:
    """
    Perform a mock data transformation and record provenance.

    Args:
        security_manager: The security manager instance
        source_data_id: The data ID of the source dataset

    Returns:
        str: The data ID of the transformed dataset
    """
    # Generate a data ID for the transformed dataset
    transformed_data_id = f"transformed_{uuid.uuid4()}"

    # Record the transformation step
    step_id = security_manager.record_transformation_step(
        data_id=source_data_id,
        operation="filter",
        description="Filter rows where value > 50",
        tool="duckdb",
        parameters={"condition": "value > 50"},
        inputs=[source_data_id],
        outputs=[transformed_data_id],
        metrics={"execution_time_ms": 150, "filtered_rows": 30}
    )

    # Simulate processing time
    time.sleep(1)

    # Complete the transformation step
    security_manager.complete_transformation_step(
        data_id=source_data_id,
        step_id=step_id,
        status="completed",
        outputs=[transformed_data_id],
        metrics={"execution_time_ms": 150, "filtered_rows": 30}
    )

    # Record provenance for the transformed dataset
    security_manager.record_provenance(
        data_id=transformed_data_id,
        source="transformation",
        creator="example_user",
        creation_time=datetime.datetime.now().isoformat(),
        process_steps=[{"step_id": step_id, "operation": "filter"}],
        parent_ids=[source_data_id],
        checksum="0xabcdef123456789",
        version="1.0",
        data_type="dataset",
        schema={"columns": ["id", "name", "value"]},
        size_bytes=512,
        record_count=70,
        content_type="application/json",
        lineage_info={
            "source_system": "transformation_pipeline",
            "source_type": "transformation",
            "extraction_method": "filter_operation",
            "extraction_time": datetime.datetime.now().isoformat(),
            "upstream_datasets": [source_data_id]
        },
        tags=["filtered", "example", "demo"]
    )

    print(f"Created transformed dataset with ID: {transformed_data_id}")
    return transformed_data_id


def aggregate_data(security_manager: SecurityManager, source_data_id: str) -> str:
    """
    Perform a mock data aggregation and record provenance.

    Args:
        security_manager: The security manager instance
        source_data_id: The data ID of the source dataset

    Returns:
        str: The data ID of the aggregated dataset
    """
    # Generate a data ID for the aggregated dataset
    aggregated_data_id = f"aggregated_{uuid.uuid4()}"

    # Record the aggregation step
    step_id = security_manager.record_transformation_step(
        data_id=source_data_id,
        operation="aggregate",
        description="Aggregate by name and calculate sum of values",
        tool="duckdb",
        parameters={"group_by": "name", "aggregate": "sum(value)"},
        inputs=[source_data_id],
        outputs=[aggregated_data_id],
        metrics={"execution_time_ms": 200}
    )

    # Simulate processing time
    time.sleep(1)

    # Complete the aggregation step
    security_manager.complete_transformation_step(
        data_id=source_data_id,
        step_id=step_id,
        status="completed",
        outputs=[aggregated_data_id],
        metrics={"execution_time_ms": 200, "groups": 10}
    )

    # Record provenance for the aggregated dataset
    security_manager.record_provenance(
        data_id=aggregated_data_id,
        source="transformation",
        creator="example_user",
        creation_time=datetime.datetime.now().isoformat(),
        process_steps=[{"step_id": step_id, "operation": "aggregate"}],
        parent_ids=[source_data_id],
        checksum="0x987654321abcdef",
        version="1.0",
        data_type="dataset",
        schema={"columns": ["name", "sum_value"]},
        size_bytes=256,
        record_count=10,
        content_type="application/json",
        lineage_info={
            "source_system": "transformation_pipeline",
            "source_type": "transformation",
            "extraction_method": "aggregate_operation",
            "extraction_time": datetime.datetime.now().isoformat(),
            "upstream_datasets": [source_data_id]
        },
        tags=["aggregated", "example", "demo"]
    )

    print(f"Created aggregated dataset with ID: {aggregated_data_id}")
    return aggregated_data_id


def merge_data(security_manager: SecurityManager, data_id1: str, data_id2: str) -> str:
    """
    Perform a mock data merge and record provenance.

    Args:
        security_manager: The security manager instance
        data_id1: The data ID of the first source dataset
        data_id2: The data ID of the second source dataset

    Returns:
        str: The data ID of the merged dataset
    """
    # Generate a data ID for the merged dataset
    merged_data_id = f"merged_{uuid.uuid4()}"

    # Create a new transformation step for the merge operation
    step_id1 = security_manager.record_transformation_step(
        data_id=data_id1,
        operation="merge",
        description="Merge transformed and aggregated datasets",
        tool="duckdb",
        parameters={"join_column": "name"},
        inputs=[data_id1, data_id2],
        outputs=[merged_data_id],
        metrics={"execution_time_ms": 250}
    )

    # Record the same step for the second dataset
    step_id2 = security_manager.record_transformation_step(
        data_id=data_id2,
        operation="merge",
        description="Merge transformed and aggregated datasets",
        tool="duckdb",
        parameters={"join_column": "name"},
        inputs=[data_id1, data_id2],
        outputs=[merged_data_id],
        metrics={"execution_time_ms": 250}
    )

    # Simulate processing time
    time.sleep(1)

    # Complete the steps
    security_manager.complete_transformation_step(
        data_id=data_id1,
        step_id=step_id1,
        status="completed",
        outputs=[merged_data_id],
        metrics={"execution_time_ms": 250, "merged_rows": 80}
    )

    security_manager.complete_transformation_step(
        data_id=data_id2,
        step_id=step_id2,
        status="completed",
        outputs=[merged_data_id],
        metrics={"execution_time_ms": 250, "merged_rows": 80}
    )

    # Record provenance for the merged dataset
    security_manager.record_provenance(
        data_id=merged_data_id,
        source="transformation",
        creator="example_user",
        creation_time=datetime.datetime.now().isoformat(),
        process_steps=[
            {"step_id": step_id1, "operation": "merge"},
            {"step_id": step_id2, "operation": "merge"}
        ],
        parent_ids=[data_id1, data_id2],
        checksum="0xfedcba987654321",
        version="1.0",
        data_type="dataset",
        schema={"columns": ["id", "name", "value", "sum_value"]},
        size_bytes=768,
        record_count=80,
        content_type="application/json",
        lineage_info={
            "source_system": "transformation_pipeline",
            "source_type": "transformation",
            "extraction_method": "merge_operation",
            "extraction_time": datetime.datetime.now().isoformat(),
            "upstream_datasets": [data_id1, data_id2]
        },
        tags=["merged", "example", "demo"]
    )

    print(f"Created merged dataset with ID: {merged_data_id}")
    return merged_data_id


def record_data_accesses(security_manager: SecurityManager, data_ids: List[str]):
    """
    Record some sample data accesses.

    Args:
        security_manager: The security manager instance
        data_ids: List of data IDs to record accesses for
    """
    users = ["alice", "bob", "charlie"]
    operations = ["read", "analyze", "export", "verify"]

    for data_id in data_ids:
        for i in range(3):  # Record 3 accesses per dataset
            user = users[i % len(users)]
            operation = operations[i % len(operations)]

            security_manager.record_data_access(
                data_id=data_id,
                operation=operation,
                details={
                    "reason": f"Example {operation} access",
                    "system": "example_system"
                }
            )

            # Simulate time passing between accesses
            time.sleep(0.2)

    print(f"Recorded sample data accesses for {len(data_ids)} datasets")


def generate_and_save_reports(security_manager: SecurityManager, data_id: str, output_dir: str):
    """
    Generate provenance reports in different formats and save to files.

    Args:
        security_manager: The security manager instance
        data_id: The data ID to generate reports for
        output_dir: Directory to save the reports
    """
    os.makedirs(output_dir, exist_ok=True)

    # Generate reports in different formats
    formats = ["json", "text", "html", "markdown"]
    report_types = ["summary", "detailed", "technical"]

    for report_type in report_types:
        for format_type in formats:
            report = security_manager.generate_provenance_report(
                data_id=data_id,
                report_type=report_type,
                format=format_type,
                include_lineage=True,
                include_access_history=True
            )

            # Determine file extension
            ext = format_type
            if format_type == "json":
                ext = "json"

            # Save the report to a file
            filename = f"{data_id}_{report_type}_{format_type}.{ext}"
            filepath = os.path.join(output_dir, filename)

            if format_type == "json":
                with open(filepath, "w") as f:
                    json.dump(report, f, indent=2)
            elif format_type == "text":
                with open(filepath, "w") as f:
                    f.write(report["text_content"])
            elif format_type == "html":
                with open(filepath, "w") as f:
                    f.write(report["html_content"])
            elif format_type == "markdown":
                with open(filepath, "w") as f:
                    f.write(report["markdown_content"])

    print(f"Generated and saved reports for dataset {data_id} in directory: {output_dir}")


def generate_and_save_visualizations(security_manager: SecurityManager, data_id: str, output_dir: str):
    """
    Generate lineage visualizations in different formats and save to files.

    Args:
        security_manager: The security manager instance
        data_id: The data ID to generate visualizations for
        output_dir: Directory to save the visualizations
    """
    os.makedirs(output_dir, exist_ok=True)

    # Generate visualizations in different formats
    formats = ["dot", "mermaid", "d3", "json"]

    for format_type in formats:
        visualization = security_manager.generate_lineage_visualization(
            data_id=data_id,
            format=format_type,
            max_depth=3,
            direction="both",
            include_attributes=True
        )

        # Determine file extension and content
        if format_type == "dot":
            ext = "dot"
            content = visualization["dot_content"]
        elif format_type == "mermaid":
            ext = "mmd"
            content = visualization["mermaid_content"]
        elif format_type == "d3":
            ext = "json"
            content = json.dumps(visualization["d3_data"], indent=2)
        else:  # json
            ext = "json"
            content = json.dumps(visualization, indent=2)

        # Save the visualization to a file
        filename = f"{data_id}_lineage_{format_type}.{ext}"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w") as f:
            f.write(content)

    print(f"Generated and saved visualizations for dataset {data_id} in directory: {output_dir}")


def main():
    """Main function to demonstrate data provenance capabilities."""
    print("Demonstrating enhanced data provenance capabilities...")

    # Initialize security manager
    security_manager = setup_security()

    # Create a sample data transformation pipeline
    print("\n1. Creating sample data transformation pipeline...")
    original_data_id = create_sample_dataset(security_manager)
    transformed_data_id = transform_data(security_manager, original_data_id)
    aggregated_data_id = aggregate_data(security_manager, original_data_id)
    merged_data_id = merge_data(security_manager, transformed_data_id, aggregated_data_id)

    # Record some data accesses
    print("\n2. Recording sample data accesses...")
    record_data_accesses(security_manager, [
        original_data_id,
        transformed_data_id,
        aggregated_data_id,
        merged_data_id
    ])

    # Generate provenance reports
    print("\n3. Generating provenance reports...")
    output_dir = os.path.expanduser("~/provenance_reports")
    generate_and_save_reports(security_manager, merged_data_id, output_dir)

    # Generate lineage visualizations
    print("\n4. Generating lineage visualizations...")
    generate_and_save_visualizations(security_manager, merged_data_id, output_dir)

    print(f"\nAll outputs have been saved to: {output_dir}")
    print("Example completed successfully!")


if __name__ == "__main__":
    main()
