#!/usr/bin/env python3
"""
Provenance-Audit Integration Example

This example demonstrates the enhanced integration between the data provenance
tracking system and audit logging system, including:
- Bidirectional linking between audit events and provenance records
- Automatic provenance record creation from audit events
- Cryptographic verification of provenance records
- Event listeners for real-time integration
- Comprehensive tracking of data lineage
"""

import sys
import os
import json
import uuid
import logging
import datetime
from typing import Dict, List, Any, Optional

# Set up logging
logging.basicConfig(level=logging.INFO, 
                  format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # Import audit system
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    from ipfs_datasets_py.audit.handlers import FileAuditHandler, ConsoleAuditHandler
    from ipfs_datasets_py.audit.integration import (
        AuditProvenanceIntegrator, AuditContextManager, audit_function
    )
    
    # Import provenance system
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, ProvenanceCryptoVerifier,
        SourceRecord, TransformationRecord, VerificationRecord
    )
    
    IMPORTS_SUCCESSFUL = True
except ImportError as e:
    logger.error(f"Error importing modules: {str(e)}")
    IMPORTS_SUCCESSFUL = False


def setup_audit_system():
    """Set up the audit logging system with appropriate handlers."""
    audit_logger = AuditLogger.get_instance()
    
    # Add console handler
    console_handler = ConsoleAuditHandler(
        name="console",
        min_level=AuditLevel.INFO
    )
    audit_logger.add_handler(console_handler)
    
    # Add file handler
    file_handler = FileAuditHandler(
        name="file",
        filename="audit_log.jsonl",
        min_level=AuditLevel.DEBUG
    )
    audit_logger.add_handler(file_handler)
    
    # Configure audit logger
    audit_logger.configure({
        "default_user": "example_user",
        "min_level": AuditLevel.DEBUG
    })
    
    return audit_logger


def setup_provenance_system(audit_logger=None):
    """Set up the provenance tracking system with cryptographic verification."""
    # Initialize provenance manager with cryptographic verification enabled
    provenance_manager = EnhancedProvenanceManager(
        storage_path="provenance_store.json",
        enable_ipld_storage=False,
        default_agent_id="example_script",
        tracking_level="detailed",
        audit_logger=audit_logger,
        enable_crypto_verification=True
    )
    
    return provenance_manager


def initialize_integration(audit_logger, provenance_manager):
    """Initialize the bidirectional integration between systems."""
    # Create integrator
    integrator = AuditProvenanceIntegrator(
        audit_logger=audit_logger,
        provenance_manager=provenance_manager
    )
    
    # Set up automatic provenance record creation from audit events
    success = integrator.setup_audit_event_listener()
    if success:
        logger.info("Successfully set up audit event listener")
    else:
        logger.warning("Failed to set up audit event listener")
    
    return integrator


@audit_function(
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id_arg="output_dataset_id",
    resource_type="dataset",
    details_extractor=lambda input_dataset_id, output_dataset_id, **kwargs: {
        "input_dataset": input_dataset_id,
        "transformation": "tokenization",
        "parameters": {"model": "bert-base-uncased"}
    }
)
def tokenize_dataset(input_dataset_id, output_dataset_id, **kwargs):
    """
    Example function that transforms a dataset with automatic audit logging.
    
    This is decorated with audit_function to automatically log the operation.
    """
    logger.info(f"Tokenizing dataset {input_dataset_id} to {output_dataset_id}")
    # Simulate dataset transformation
    return {"tokens": 15000, "status": "success"}


def demonstrate_provenance_audit_integration():
    """Demonstrate the integration between audit logging and data provenance."""
    if not IMPORTS_SUCCESSFUL:
        logger.error("Cannot run demonstration due to import errors")
        return
    
    logger.info("Starting provenance-audit integration demonstration")
    
    # Set up systems
    audit_logger = setup_audit_system()
    provenance_manager = setup_provenance_system(audit_logger)
    integrator = initialize_integration(audit_logger, provenance_manager)
    
    # Create dataset IDs for our example
    source_dataset_id = f"dataset-{uuid.uuid4()}"
    processed_dataset_id = f"processed-{uuid.uuid4()}"
    
    # Step 1: Create a source record directly in provenance system
    logger.info("Step 1: Creating source record in provenance system")
    source_record_id = provenance_manager.record_source(
        source_id=source_dataset_id,
        source_type="huggingface",
        source_uri="huggingface:wikipedia/20220301.en",
        format="parquet",
        description="Wikipedia dataset from HuggingFace"
    )
    
    # Generate audit event from the provenance record
    audit_event_id = integrator.audit_from_provenance_record(
        provenance_manager.records[source_record_id]
    )
    
    # Link the audit event to the provenance record
    integrator.link_audit_to_provenance(audit_event_id, source_record_id)
    
    # Step 2: Use the audit context manager for a data transformation
    logger.info("Step 2: Using audit context manager for transformation")
    with AuditContextManager(
        category=AuditCategory.DATA_MODIFICATION,
        action="dataset_transform",
        resource_id=processed_dataset_id,
        resource_type="dataset",
        details={
            "input_dataset": source_dataset_id,
            "transformation_type": "filtering",
            "parameters": {"min_length": 100, "max_samples": 10000}
        },
        audit_logger=audit_logger
    ):
        # Perform the transformation (just simulation)
        # In a real scenario, this would be actual data processing
        logger.info(f"Filtering dataset {source_dataset_id} to {processed_dataset_id}")
        
        # Create a transformation record in provenance system
        transform_record_id = provenance_manager.record_transformation(
            input_ids=[source_dataset_id],
            output_id=processed_dataset_id,
            transformation_type="filtering",
            parameters={"min_length": 100, "max_samples": 10000},
            tool="ipfs_datasets",
            description="Filter Wikipedia dataset to keep only long articles"
        )
    
    # Step 3: Use the decorated function for automatic audit logging
    logger.info("Step 3: Using decorated function for audit logging")
    result = tokenize_dataset(
        input_dataset_id=processed_dataset_id,
        output_dataset_id=f"tokenized-{uuid.uuid4()}"
    )
    
    # Step 4: Verify provenance record signatures
    logger.info("Step 4: Verifying cryptographic signatures of provenance records")
    verification_results = provenance_manager.verify_all_records()
    
    for record_id, is_valid in verification_results.items():
        status = "valid" if is_valid else "INVALID"
        logger.info(f"Record {record_id}: Signature {status}")
    
    # Step 5: Generate comprehensive report
    logger.info("Step 5: Generating integrated audit-provenance report")
    
    # Get record with graph metrics
    metrics = provenance_manager.calculate_data_metrics(processed_dataset_id)
    
    # Print summary
    logger.info(f"Data lineage depth: {metrics['complexity']['max_depth']}")
    logger.info(f"Transformation operations: {metrics['complexity']['transformation_count']}")
    logger.info(f"Data impact score: {metrics['impact']:.2f}")
    
    # Generate visualization
    try:
        img_path = "provenance_graph.png"
        provenance_manager.visualize_provenance_enhanced(
            data_ids=[processed_dataset_id],
            max_depth=5,
            include_parameters=True,
            show_timestamps=True,
            highlight_critical_path=True,
            include_metrics=True,
            file_path=img_path
        )
        logger.info(f"Visualization saved to {img_path}")
    except Exception as e:
        logger.error(f"Error generating visualization: {str(e)}")
    
    logger.info("Integration demonstration completed successfully")
    return {
        "source_record_id": source_record_id,
        "transform_record_id": transform_record_id,
        "verification_results": verification_results,
        "metrics": metrics
    }


if __name__ == "__main__":
    result = demonstrate_provenance_audit_integration()
    if result:
        print("\nDemonstration completed successfully")
        print(f"Number of records with valid signatures: "
              f"{sum(1 for v in result['verification_results'].values() if v)}")