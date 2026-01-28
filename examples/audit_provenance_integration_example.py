"""
Audit Provenance Integration Example

This example demonstrates how to use the integrated audit-provenance dashboard
to monitor data operations, track lineage, and create comprehensive reports.
"""

import os
import time
import random
import datetime

# Import audit and provenance components
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditLevel, AuditCategory
from ipfs_datasets_py.analytics.data_provenance import ProvenanceManager
from ipfs_datasets_py.audit.audit_provenance_integration import setup_audit_provenance_dashboard, AuditProvenanceDashboard


def generate_sample_provenance_data(provenance_manager):
    """Generate sample provenance data for demonstration."""
    print("Generating sample provenance data...")

    # Create some source data entities
    source1_id = "source_data_1"
    source1_record = provenance_manager.record_source(
        entity_id=source1_id,
        source_uri="file:///data/sample1.csv",
        description="Sample source data 1",
        parameters={"rows": 1000, "format": "csv"},
        metadata={"author": "Alice", "department": "Research"}
    )

    source2_id = "source_data_2"
    source2_record = provenance_manager.record_source(
        entity_id=source2_id,
        source_uri="file:///data/sample2.json",
        description="Sample source data 2",
        parameters={"documents": 500, "format": "json"},
        metadata={"author": "Bob", "department": "Engineering"}
    )

    # Create a transformation
    transform_id = "transformed_data_1"
    transform_record = provenance_manager.record_transformation(
        entity_id=transform_id,
        input_entity_ids=[source1_id, source2_id],
        description="Merge and clean two datasets",
        parameters={"join_key": "id", "clean_fields": ["name", "address"]},
        metadata={"transformation_type": "data_cleaning"},
        duration_ms=random.randint(800, 1500)
    )

    # Create a query operation
    query_id = "query_result_1"
    query_record = provenance_manager.record_query(
        entity_id=query_id,
        input_entity_ids=[transform_id],
        query_text="SELECT * FROM data WHERE category = 'important'",
        description="Filter for important records",
        parameters={"filter_by": "category", "value": "important"},
        metadata={"user": "Charlie", "purpose": "Analysis"},
        duration_ms=random.randint(200, 600)
    )

    # Create an export
    export_id = "export_data_1"
    export_record = provenance_manager.record_checkpoint(
        entity_id=export_id,
        input_entity_ids=[query_id],
        description="Export filtered data to Parquet",
        parameters={"format": "parquet", "compression": "snappy"},
        metadata={"destination": "file:///exports/important_data.parquet"}
    )

    # Add more operations with timestamps spread across time
    for i in range(5):
        # Create some time gap
        time.sleep(0.5)

        derived_id = f"derived_data_{i+1}"
        provenance_manager.record_transformation(
            entity_id=derived_id,
            input_entity_ids=[export_id],
            description=f"Additional processing step {i+1}",
            parameters={"operation": f"process_{i}", "iterations": i+1},
            metadata={"step": i+1},
            duration_ms=random.randint(300, 800)
        )

    print("Sample provenance data generated.")
    return [source1_id, source2_id, transform_id, query_id, export_id, derived_id]


def generate_sample_audit_events(audit_logger, data_ids):
    """Generate sample audit events for demonstration."""
    print("Generating sample audit events...")

    # Different actions to simulate
    data_actions = ["read", "write", "update", "delete", "query", "export", "share"]
    auth_actions = ["login", "logout", "password_change", "access_request"]
    admin_actions = ["user_create", "role_assign", "permission_change", "system_config"]

    # Different users
    users = ["alice", "bob", "charlie", "admin"]

    # Generate audit events spread over time
    start_time = time.time() - 3600  # 1 hour ago

    for i in range(50):
        # Choose random attributes for this event
        category = random.choice([AuditCategory.DATA_ACCESS, AuditCategory.AUTHENTICATION,
                                AuditCategory.ADMINISTRATION, AuditCategory.DATA_MODIFICATION])

        if category == AuditCategory.DATA_ACCESS or category == AuditCategory.DATA_MODIFICATION:
            action = random.choice(data_actions)
            resource_id = random.choice(data_ids) if data_ids else f"resource_{random.randint(1, 10)}"
            resource_type = "dataset"
        elif category == AuditCategory.AUTHENTICATION:
            action = random.choice(auth_actions)
            resource_id = None
            resource_type = "auth_system"
        else:
            action = random.choice(admin_actions)
            resource_id = f"user_{random.randint(1, 5)}" if "user" in action else None
            resource_type = "admin_console"

        level = random.choice([AuditLevel.INFO, AuditLevel.INFO, AuditLevel.INFO,
                             AuditLevel.WARNING, AuditLevel.ERROR])

        user = random.choice(users)
        status = "success" if random.random() > 0.1 else "failure"
        client_ip = f"192.168.1.{random.randint(2, 254)}"

        # Create event timestamp with some randomness but generally increasing
        timestamp = start_time + (i * 60) + random.randint(-20, 20)

        # Details with more information
        details = {
            "client_app": random.choice(["web_interface", "api_client", "mobile_app"]),
            "session_id": f"session_{random.randint(1000, 9999)}",
        }

        # Add duration for some actions
        if action in ["query", "export", "update"]:
            details["duration_ms"] = random.randint(50, 2000)

        # Add specific error information for failures
        if status == "failure":
            if category == AuditCategory.AUTHENTICATION:
                details["error"] = "Invalid credentials" if action == "login" else "Session expired"
            else:
                details["error"] = random.choice(["Permission denied", "Resource not found", "Validation error"])

        # Create the event
        event = AuditEvent(
            timestamp=timestamp,
            category=category,
            level=level,
            action=action,
            status=status,
            user=user,
            resource_id=resource_id,
            resource_type=resource_type,
            client_ip=client_ip,
            details=details
        )

        # Log the event
        audit_logger.log_event(event)

    print("Sample audit events generated.")


def main():
    # Create output directory for dashboards
    output_dir = "dashboard_output"
    os.makedirs(output_dir, exist_ok=True)

    print("Setting up provenance manager...")
    provenance_manager = ProvenanceManager()

    # Generate sample provenance data
    data_ids = generate_sample_provenance_data(provenance_manager)

    print("Setting up audit logger...")
    audit_metrics = AuditMetricsAggregator()
    audit_logger = AuditLogger()

    # Add a handler to feed events to the metrics aggregator
    audit_logger.add_handler(lambda event: audit_metrics.process_event(event))

    # Generate sample audit events
    generate_sample_audit_events(audit_logger, data_ids)

    print("Creating integrated dashboard...")
    dashboard = setup_audit_provenance_dashboard(
        audit_logger=audit_logger,
        provenance_manager=provenance_manager
    )

    # Create a timeline visualization showing both audit and provenance events
    print("Creating integrated timeline visualization...")
    timeline_path = os.path.join(output_dir, "integrated_timeline.png")
    dashboard.create_provenance_audit_timeline(
        data_ids=data_ids,
        hours=1,
        output_file=timeline_path
    )
    print(f"Integrated timeline created at: {timeline_path}")

    # Create metrics comparison
    print("Creating metrics comparison visualization...")
    comparison_path = os.path.join(output_dir, "metrics_comparison.png")
    dashboard.create_provenance_metrics_comparison(
        metrics_type='overview',
        output_file=comparison_path
    )
    print(f"Metrics comparison created at: {comparison_path}")

    # Create complete dashboard with all visualizations
    print("Creating full integrated dashboard...")
    dashboard_path = dashboard.create_integrated_dashboard(
        output_dir=output_dir,
        data_ids=data_ids,
        dashboard_name="integrated_dashboard.html"
    )
    print(f"Full dashboard created at: {dashboard_path}")

    # Generate a provenance report for a specific entity
    report_path = os.path.join(output_dir, "entity_report.html")
    provenance_dashboard = dashboard.provenance_dashboard
    entity_id = data_ids[-1]  # Use the last generated entity

    print(f"Generating provenance report for entity {entity_id}...")
    provenance_dashboard.generate_provenance_report(
        data_ids=[entity_id],
        format="html",
        include_lineage_graph=True,
        include_audit_events=True,
        output_file=report_path
    )
    print(f"Entity report created at: {report_path}")

    print("\nExample completed successfully!")
    print(f"All output files are in the '{output_dir}' directory.")
    print("""
Available outputs:
- integrated_timeline.png: Timeline showing both audit and provenance events
- metrics_comparison.png: Comparison of audit and provenance metrics
- integrated_dashboard.html: Complete dashboard with all visualizations
- entity_report.html: Detailed report for a specific entity
""")


if __name__ == "__main__":
    main()
