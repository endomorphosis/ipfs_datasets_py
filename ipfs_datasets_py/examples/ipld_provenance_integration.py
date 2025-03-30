"""
Example demonstrating the integration of IPLD storage with data provenance tracking.

This example shows how to:
1. Initialize an EnhancedProvenanceManager with IPLD storage enabled
2. Record various provenance events with automatic IPLD storage
3. Export the provenance graph to a CAR file
4. Import the provenance graph from a CAR file
5. Verify the integrity of the imported graph
"""

import os
import time
import tempfile
import argparse
from typing import Dict, List, Any

from ipfs_datasets_py.data_provenance_enhanced import (
    EnhancedProvenanceManager, 
    ProvenanceRecord,
    ProvenanceCryptoVerifier
)

def main(args):
    # Create a temporary directory for storage
    temp_dir = args.storage_dir or tempfile.mkdtemp()
    print(f"Using storage directory: {temp_dir}")
    
    # Step 1: Initialize provenance manager with IPLD storage
    print("\n1. Initializing EnhancedProvenanceManager with IPLD storage...")
    manager = EnhancedProvenanceManager(
        storage_path=temp_dir,
        enable_ipld_storage=True,
        default_agent_id="ipld-example-agent",
        tracking_level="detailed",
        enable_crypto_verification=True,
        ipfs_api=args.ipfs_api
    )
    
    # Step 2: Record provenance events
    print("\n2. Recording provenance events...")
    
    # Source record
    source_id = manager.record_source(
        output_id="dataset-001",
        source_type="file",
        format="csv",
        location="/path/to/dataset.csv",
        description="Original CSV dataset"
    )
    print(f"  Recorded source: {source_id}")
    
    # Transformation record
    transform_id = manager.record_transformation(
        input_ids=["dataset-001"],
        output_id="dataset-002",
        transformation_type="clean",
        tool="pandas",
        parameters={"drop_na": True, "drop_duplicates": True},
        description="Clean dataset by removing NA values and duplicates"
    )
    print(f"  Recorded transformation: {transform_id}")
    
    # Verification record
    verify_id = manager.record_verification(
        data_id="dataset-002",
        verification_type="schema",
        schema={"id": "integer", "name": "string", "value": "float"},
        pass_count=1000,
        fail_count=0,
        description="Verify data schema"
    )
    print(f"  Recorded verification: {verify_id}")
    
    # Model training record
    model_id = manager.record_model_training(
        input_ids=["dataset-002"],
        output_id="model-001",
        model_type="random_forest",
        model_framework="scikit-learn",
        hyperparameters={"n_estimators": 100, "max_depth": 10},
        metrics={"accuracy": 0.92, "f1": 0.91},
        description="Train random forest classifier"
    )
    print(f"  Recorded model training: {model_id}")
    
    # Model inference record
    inference_id = manager.record_model_inference(
        model_id="model-001",
        input_ids=["dataset-002"],
        output_id="predictions-001",
        model_version="1.0",
        output_type="classification",
        performance_metrics={"latency_ms": 250},
        description="Generate predictions using trained model"
    )
    print(f"  Recorded model inference: {inference_id}")
    
    # Annotation record
    annotation_id = manager.record_annotation(
        data_id="predictions-001",
        content="Predictions appear to be biased towards class 0",
        annotation_type="issue",
        tags=["bias", "accuracy"],
        description="Note potential bias in model predictions"
    )
    print(f"  Recorded annotation: {annotation_id}")
    
    # Step 3: Examine IPLD storage
    print("\n3. Examining IPLD storage...")
    print(f"  Record CIDs: {len(manager.record_cids)} records stored in IPLD")
    for record_id, cid in list(manager.record_cids.items())[:3]:
        print(f"  - {record_id}: {cid}")
    
    if len(manager.record_cids) > 3:
        print(f"  - ... and {len(manager.record_cids) - 3} more")
    
    # Step 4: Export to CAR file
    car_path = os.path.join(temp_dir, "provenance.car")
    print(f"\n4. Exporting provenance graph to CAR file: {car_path}")
    root_cid = manager.export_to_car(car_path)
    print(f"  Exported successfully. Root CID: {root_cid}")
    
    # Step 5: Create a new provenance manager to import the data
    print("\n5. Creating new provenance manager to import data...")
    import_manager = EnhancedProvenanceManager(
        storage_path=temp_dir,
        enable_ipld_storage=True,
        default_agent_id="ipld-example-agent",
        tracking_level="detailed",
        enable_crypto_verification=True,
        ipfs_api=args.ipfs_api
    )
    
    # Step 6: Import from CAR file
    print(f"\n6. Importing provenance graph from CAR file: {car_path}")
    success = import_manager.import_from_car(car_path)
    if success:
        print(f"  Imported successfully. Root CID: {import_manager.ipld_root_cid}")
        print(f"  Records: {len(import_manager.records)}")
        print(f"  Graph nodes: {import_manager.graph.number_of_nodes()}")
        print(f"  Graph edges: {import_manager.graph.number_of_edges()}")
    else:
        print("  Import failed. Check logs for details.")
    
    # Step 7: Verify the integrity of the imported graph
    print("\n7. Verifying integrity of imported graph...")
    if import_manager.enable_crypto_verification:
        verification_results = import_manager.verify_all_records()
        valid_count = sum(1 for v in verification_results.values() if v)
        print(f"  Valid records: {valid_count}/{len(verification_results)}")
        
        if valid_count < len(verification_results):
            print("  Warning: Some records could not be verified!")
            for record_id, is_valid in verification_results.items():
                if not is_valid:
                    print(f"  - Invalid record: {record_id}")
    else:
        print("  Cryptographic verification not enabled.")
    
    # Step 8: Run a semantic search query on the imported graph
    print("\n8. Running a semantic search query...")
    query_results = import_manager.semantic_search("model training random forest", limit=2)
    print(f"  Found {len(query_results)} matches:")
    for i, result in enumerate(query_results):
        print(f"  Result {i+1}:")
        print(f"    ID: {result['record_id']}")
        print(f"    Type: {result['record_type']}")
        print(f"    Description: {result['description']}")
        print(f"    Score: {result['score']}")
    
    print("\nIPLD-Enhanced Provenance Example Completed Successfully")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IPLD Provenance Integration Example")
    parser.add_argument("--storage-dir", type=str, default=None, 
                        help="Directory for storage (default: temporary directory)")
    parser.add_argument("--ipfs-api", type=str, default="/ip4/127.0.0.1/tcp/5001", 
                        help="IPFS API endpoint (default: /ip4/127.0.0.1/tcp/5001)")
    
    args = parser.parse_args()
    main(args)