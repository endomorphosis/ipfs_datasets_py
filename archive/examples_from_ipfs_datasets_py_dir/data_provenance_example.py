"""
Example demonstrating the enhanced data provenance system with audit logging integration.

This example shows how to use the EnhancedProvenanceManager to track data lineage
throughout a complete data processing pipeline, from raw data to model deployment,
with integration to the audit logging system.
"""

import os
import time
import json
import numpy as np
import pandas as pd
from datetime import datetime

# Import provenance components
from ipfs_datasets_py.analytics.data_provenance_enhanced import (
    EnhancedProvenanceManager, ProvenanceMetrics
)

# Import audit components
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    from ipfs_datasets_py.audit.handlers import (
        FileAuditHandler, JSONAuditHandler
    )
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False


def setup_audit_logger():
    """Set up audit logger with appropriate handlers."""
    if not AUDIT_AVAILABLE:
        print("Audit logging module not available. Running without audit integration.")
        return None

    # Create temporary directory for audit logs if it doesn't exist
    audit_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_logs")
    os.makedirs(audit_dir, exist_ok=True)

    # Create audit logger with file and JSON handlers
    audit_logger = AuditLogger(
        app_name="DataProvenanceExample",
        logger_id="demo"
    )

    file_handler = FileAuditHandler(
        log_file=os.path.join(audit_dir, "provenance_audit.log"),
        rotate_size_mb=10,
        keep_logs=5
    )

    json_handler = JSONAuditHandler(
        log_file=os.path.join(audit_dir, "provenance_audit.json"),
        rotate_size_mb=10,
        keep_logs=5
    )

    audit_logger.add_handler(file_handler)
    audit_logger.add_handler(json_handler)

    return audit_logger


def simulate_data_processing_pipeline():
    """Simulate a complete data processing pipeline with provenance tracking."""
    # Set up audit logger
    audit_logger = setup_audit_logger()

    # Initialize provenance manager with audit integration
    provenance = EnhancedProvenanceManager(
        storage_path=None,  # In-memory only for this example
        enable_ipld_storage=False,
        default_agent_id="example_user",
        tracking_level="comprehensive",
        audit_logger=audit_logger,
        visualization_engine="matplotlib"
    )

    print("=== Starting Data Processing Pipeline with Provenance Tracking ===")

    # Step 1: Record initial data sources
    print("\n== Step 1: Recording Data Sources ==")

    # Raw customer data source
    customer_data_id = "customer_data_raw"
    customer_source_id = provenance.record_source(
        data_id=customer_data_id,
        source_type="csv",
        location="/data/customers.csv",
        format="csv",
        description="Raw customer demographic data",
        size=1024 * 1024 * 5,  # 5MB
        hash="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    print(f"Recorded customer data source: {customer_source_id}")

    # Transaction data source
    transaction_data_id = "transaction_data_raw"
    transaction_source_id = provenance.record_source(
        data_id=transaction_data_id,
        source_type="database",
        location="postgresql://sales_db/transactions",
        format="sql",
        description="Raw transaction data from sales database",
        size=1024 * 1024 * 50,  # 50MB
        hash="sha256:7d865e959b2466918c9863afca942d0fb89d7c9ac0c99bafc3749504ded97730"
    )
    print(f"Recorded transaction data source: {transaction_source_id}")

    # Step 2: Data cleaning and preprocessing
    print("\n== Step 2: Data Cleaning and Preprocessing ==")

    # Clean customer data
    with provenance.begin_transformation(
        description="Clean customer data",
        transformation_type="data_cleaning",
        tool="pandas",
        version="1.5.3",
        input_ids=[customer_data_id],
        parameters={
            "dropna": True,
            "deduplicate": True,
            "normalize_columns": ["age", "income"]
        }
    ) as context:
        # Simulate processing time
        time.sleep(0.5)

        # Set output ID
        clean_customer_data_id = "customer_data_clean"
        context.set_output_ids([clean_customer_data_id])

    print(f"Cleaned customer data: {clean_customer_data_id}")

    # Verify customer data quality
    verification_id = provenance.record_verification(
        data_id=clean_customer_data_id,
        verification_type="data_quality",
        schema={"required": ["customer_id", "age", "income", "gender"]},
        validation_rules=[
            {"field": "age", "rule": "range", "min": 18, "max": 100},
            {"field": "income", "rule": "range", "min": 0}
        ],
        pass_count=9800,
        fail_count=200,
        error_samples=[
            {"id": 123, "error": "age out of range: 150"},
            {"id": 456, "error": "income negative: -500"}
        ],
        description="Customer data quality verification"
    )
    print(f"Verified customer data quality: {verification_id}")

    # Add annotation about data quality issues
    annotation_id = provenance.record_annotation(
        data_id=clean_customer_data_id,
        content="Found 200 records with data quality issues. Most are age outliers.",
        annotation_type="data_quality",
        author="data_analyst",
        tags=["quality_issue", "outliers", "needs_review"],
        description="Note about data quality issues"
    )
    print(f"Added annotation about data quality: {annotation_id}")

    # Clean transaction data
    with provenance.begin_transformation(
        description="Clean transaction data",
        transformation_type="data_cleaning",
        tool="spark",
        version="3.3.0",
        input_ids=[transaction_data_id],
        parameters={
            "remove_duplicates": True,
            "fix_timestamps": True,
            "currency_conversion": "USD"
        }
    ) as context:
        # Simulate processing time
        time.sleep(0.7)

        # Set output ID
        clean_transaction_data_id = "transaction_data_clean"
        context.set_output_ids([clean_transaction_data_id])

    print(f"Cleaned transaction data: {clean_transaction_data_id}")

    # Step 3: Feature engineering
    print("\n== Step 3: Feature Engineering ==")

    # Generate customer features
    with provenance.begin_transformation(
        description="Generate customer features",
        transformation_type="feature_engineering",
        tool="scikit-learn",
        version="1.2.0",
        input_ids=[clean_customer_data_id],
        parameters={
            "encoding": "one-hot",
            "scaling": "standard",
            "feature_selection": "variance_threshold"
        }
    ) as context:
        # Simulate processing time
        time.sleep(0.6)

        # Set output ID
        customer_features_id = "customer_features"
        context.set_output_ids([customer_features_id])

    print(f"Generated customer features: {customer_features_id}")

    # Generate transaction features
    with provenance.begin_transformation(
        description="Generate transaction features",
        transformation_type="feature_engineering",
        tool="scikit-learn",
        version="1.2.0",
        input_ids=[clean_transaction_data_id],
        parameters={
            "aggregation": "monthly",
            "create_time_features": True,
            "outlier_removal": "IQR"
        }
    ) as context:
        # Simulate processing time
        time.sleep(0.8)

        # Set output ID
        transaction_features_id = "transaction_features"
        context.set_output_ids([transaction_features_id])

    print(f"Generated transaction features: {transaction_features_id}")

    # Step 4: Data merging
    print("\n== Step 4: Data Merging ==")

    # Merge customer and transaction features
    merge_id = provenance.record_merge(
        input_ids=[customer_features_id, transaction_features_id],
        output_id="merged_features",
        merge_type="join",
        description="Merge customer and transaction features",
        merge_keys=["customer_id"],
        merge_strategy="left",
        parameters={
            "how": "left",
            "on": "customer_id",
            "validate": "1:m"
        }
    )
    print(f"Merged features: {merge_id}")

    # Step 5: Train model
    print("\n== Step 5: Model Training ==")

    # Train customer churn prediction model
    model_id = "churn_prediction_model"
    training_id = provenance.record_model_training(
        input_ids=["merged_features"],
        output_id=model_id,
        model_type="classifier",
        model_framework="scikit-learn",
        hyperparameters={
            "model": "RandomForestClassifier",
            "n_estimators": 100,
            "max_depth": 10,
            "min_samples_split": 5
        },
        metrics={
            "accuracy": 0.87,
            "precision": 0.83,
            "recall": 0.79,
            "f1": 0.81,
            "auc": 0.91
        },
        model_size=1024 * 1024 * 2,  # 2MB
        model_hash="sha256:4a3bcf26c6827f188f3c0fa21f15095d075b924b9a3a4f94ba31c41c671ab679",
        description="Customer churn prediction model training"
    )
    print(f"Trained model: {training_id}")

    # Step 6: Model inference
    print("\n== Step 6: Model Inference ==")

    # Run model inference on test data
    test_data_id = "test_data"
    test_source_id = provenance.record_source(
        data_id=test_data_id,
        source_type="csv",
        location="/data/test_customers.csv",
        format="csv",
        description="Test dataset for model evaluation",
        size=1024 * 1024,  # 1MB
        hash="sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    )

    # Clean and prepare test data
    with provenance.begin_transformation(
        description="Prepare test data",
        transformation_type="data_preparation",
        input_ids=[test_data_id],
        parameters={"format": "model_compatible"}
    ) as context:
        # Simulate processing time
        time.sleep(0.3)

        # Set output ID
        prepared_test_data_id = "prepared_test_data"
        context.set_output_ids([prepared_test_data_id])

    # Run model inference
    inference_id = provenance.record_model_inference(
        model_id=model_id,
        input_ids=[prepared_test_data_id],
        output_id="churn_predictions",
        model_version="1.0",
        batch_size=64,
        output_type="probabilities",
        performance_metrics={
            "latency_ms": 125.3,
            "throughput": 512,
            "accuracy": 0.85
        },
        description="Churn prediction inference on test data"
    )
    print(f"Model inference: {inference_id}")

    # Step 7: Analysis and visualization
    print("\n== Step 7: Visualization and Reporting ==")

    # Generate data lineage visualization
    print("Generating data lineage visualization...")

    visualization_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visualizations")
    os.makedirs(visualization_dir, exist_ok=True)

    # Create visualization for model predictions lineage
    viz_path = os.path.join(visualization_dir, "churn_model_lineage.png")
    provenance.visualize_provenance_enhanced(
        data_ids=["churn_predictions"],
        max_depth=10,
        include_parameters=True,
        show_timestamps=True,
        layout="hierarchical",
        highlight_critical_path=True,
        include_metrics=True,
        file_path=viz_path,
        format="png",
        width=1600,
        height=1200
    )
    print(f"Saved lineage visualization to: {viz_path}")

    # Calculate data metrics for model
    print("\nData Metrics for Model:")
    metrics = provenance.calculate_data_metrics(model_id)

    # Print complexity metrics
    print(f"  Complexity:")
    print(f"    Node Count: {metrics['complexity']['node_count']}")
    print(f"    Edge Count: {metrics['complexity']['edge_count']}")
    print(f"    Max Depth: {metrics['complexity']['max_depth']}")
    print(f"    Transformation Count: {metrics['complexity']['transformation_count']}")

    # Print impact metrics
    print(f"  Impact Score: {metrics['impact']:.2f}")

    # Print time metrics if available
    if "age_seconds" in metrics:
        hours = metrics["age_seconds"] / 3600
        print(f"  Processing Age: {hours:.2f} hours")
        print(f"  Update Frequency: {metrics['update_frequency']:.2f} operations per day")

    # Step 8: Semantic search
    print("\n== Step 8: Semantic Search Examples ==")

    print("Searching for 'quality issues':")
    quality_results = provenance.semantic_search("quality issues", limit=3)
    for i, result in enumerate(quality_results):
        print(f"  {i+1}. {result['record_type']}: {result['description']} (Score: {result['score']:.2f})")

    print("\nSearching for 'model training':")
    model_results = provenance.semantic_search("model training", limit=3)
    for i, result in enumerate(model_results):
        print(f"  {i+1}. {result['record_type']}: {result['description']} (Score: {result['score']:.2f})")

    # Export provenance data to JSON
    provenance_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "provenance_data.json")
    json_data = provenance.export_provenance_to_json(provenance_file)
    print(f"\nExported complete provenance data to: {provenance_file}")

    print("\n=== Data Processing Pipeline Completed ===")
    print(f"Total Provenance Records: {len(provenance.records)}")
    return provenance


if __name__ == "__main__":
    provenance = simulate_data_processing_pipeline()
