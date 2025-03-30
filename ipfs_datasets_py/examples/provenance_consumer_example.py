#!/usr/bin/env python3
"""
Provenance Consumer Example

This example demonstrates the use of the standardized provenance consumer interface
for accessing integrated provenance and audit information through a unified API.
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
    from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
    
    # Import provenance system
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, SourceRecord, TransformationRecord
    )
    
    # Import consumer interface
    from ipfs_datasets_py.audit.provenance_consumer import (
        ProvenanceConsumer, IntegratedProvenanceRecord
    )
    
    IMPORTS_SUCCESSFUL = True
except ImportError as e:
    logger.error(f"Error importing modules: {str(e)}")
    IMPORTS_SUCCESSFUL = False


def setup_systems():
    """Set up audit and provenance systems for demonstration."""
    # Set up audit logger
    audit_logger = AuditLogger.get_instance()
    console_handler = ConsoleAuditHandler(name="console", min_level=AuditLevel.INFO)
    audit_logger.add_handler(console_handler)
    
    # Set up provenance manager with cryptographic verification
    provenance_manager = EnhancedProvenanceManager(
        audit_logger=audit_logger,
        enable_crypto_verification=True
    )
    
    # Set up integration
    integrator = AuditProvenanceIntegrator(
        audit_logger=audit_logger,
        provenance_manager=provenance_manager
    )
    integrator.setup_audit_event_listener()
    
    return audit_logger, provenance_manager, integrator


def create_sample_lineage(provenance_manager, integrator):
    """Create a sample data lineage for demonstration."""
    # Create data entity IDs
    source_id = f"source-{uuid.uuid4()}"
    filtered_id = f"filtered-{uuid.uuid4()}"
    transformed_id = f"transformed-{uuid.uuid4()}"
    merged_id = f"merged-{uuid.uuid4()}"
    
    # Create source record
    source_record_id = provenance_manager.record_source(
        source_id=source_id,
        source_type="file",
        source_uri="file:///data/example.csv",
        format="csv",
        description="Example source data file"
    )
    
    # Generate audit event for source record
    source_audit_id = integrator.audit_from_provenance_record(
        provenance_manager.records[source_record_id]
    )
    integrator.link_audit_to_provenance(source_audit_id, source_record_id)
    
    # Create filtered data record
    filtered_record_id = provenance_manager.record_transformation(
        input_ids=[source_id],
        output_id=filtered_id,
        transformation_type="filter",
        parameters={"condition": "value > 10"},
        tool="pandas",
        description="Filter values greater than 10"
    )
    
    # Generate audit event for filtered record
    filtered_audit_id = integrator.audit_from_provenance_record(
        provenance_manager.records[filtered_record_id]
    )
    integrator.link_audit_to_provenance(filtered_audit_id, filtered_record_id)
    
    # Create second source
    source2_id = f"source2-{uuid.uuid4()}"
    source2_record_id = provenance_manager.record_source(
        source_id=source2_id,
        source_type="api",
        source_uri="https://api.example.com/data",
        format="json",
        description="Additional data from API"
    )
    
    # Create transformed data record
    transformed_record_id = provenance_manager.record_transformation(
        input_ids=[filtered_id],
        output_id=transformed_id,
        transformation_type="normalize",
        parameters={"method": "z-score"},
        tool="sklearn",
        description="Normalize data using z-score"
    )
    
    # Create merged data record
    merged_record_id = provenance_manager.record_transformation(
        input_ids=[transformed_id, source2_id],
        output_id=merged_id,
        transformation_type="merge",
        parameters={"join_on": "id"},
        tool="pandas",
        description="Merge normalized data with API data"
    )
    
    # Create verification record
    verification_record_id = provenance_manager.record_verification(
        data_id=merged_id,
        verification_type="schema",
        validation_rules=[{"field": "value", "type": "number"}],
        pass_count=100,
        fail_count=0,
        description="Validate schema of merged data"
    )
    
    return {
        "source_id": source_id,
        "filtered_id": filtered_id,
        "transformed_id": transformed_id,
        "merged_id": merged_id,
        "source2_id": source2_id,
        "records": {
            "source": source_record_id,
            "filtered": filtered_record_id,
            "source2": source2_record_id,
            "transformed": transformed_record_id,
            "merged": merged_record_id,
            "verification": verification_record_id
        }
    }


def demonstrate_consumer_usage(provenance_manager, integrator, data_ids):
    """Demonstrate the usage of the provenance consumer interface."""
    # Create provenance consumer
    consumer = ProvenanceConsumer(
        provenance_manager=provenance_manager,
        audit_logger=AuditLogger.get_instance(),
        integrator=integrator
    )
    
    # 1. Get a single integrated record
    logger.info("\n1. Getting a single integrated record")
    merged_record_id = provenance_manager.entity_latest_record.get(data_ids["merged_id"])
    if merged_record_id:
        integrated_record = consumer.get_integrated_record(merged_record_id)
        if integrated_record:
            logger.info(f"Integrated Record: {integrated_record.record_id}")
            logger.info(f"  Type: {integrated_record.record_type}")
            logger.info(f"  Description: {integrated_record.description}")
            logger.info(f"  Inputs: {integrated_record.input_ids}")
            logger.info(f"  Verified: {integrated_record.is_verified}")
    
    # 2. Search for records
    logger.info("\n2. Searching for records with keyword 'filter'")
    filtered_records = consumer.search_integrated_records(query="filter", limit=5)
    logger.info(f"Found {len(filtered_records)} records")
    for record in filtered_records:
        logger.info(f"  {record.record_id}: {record.description}")
    
    # 3. Get lineage graph
    logger.info("\n3. Getting lineage graph for merged data")
    lineage_graph = consumer.get_lineage_graph(
        data_ids["merged_id"],
        max_depth=10,
        include_audit_events=True
    )
    logger.info(f"Lineage graph contains {len(lineage_graph['nodes'])} nodes and {len(lineage_graph['edges'])} edges")
    
    # 4. Verify data lineage
    logger.info("\n4. Verifying data lineage integrity")
    verification_result = consumer.verify_data_lineage(data_ids["merged_id"])
    logger.info(f"Lineage verified: {verification_result['verified']}")
    if "details" in verification_result:
        details = verification_result["details"]
        logger.info(f"  Record count: {details['record_count']}")
        logger.info(f"  Verified count: {details['verified_count']}")
        logger.info(f"  Unverified count: {details['unverified_count']}")
    
    # 5. Export provenance information
    logger.info("\n5. Exporting provenance information")
    export_dict = consumer.export_provenance(
        data_ids["merged_id"],
        format="dict",
        include_audit_events=True
    )
    logger.info(f"Exported {len(export_dict['records'])} records")
    
    # 6. Write export to file (optional)
    with open("provenance_export.json", "w") as f:
        json.dump(export_dict, f, indent=2)
    logger.info("Exported provenance to provenance_export.json")


def run_demonstration():
    """Run the complete demonstration."""
    if not IMPORTS_SUCCESSFUL:
        logger.error("Cannot run demonstration due to import errors")
        return
    
    logger.info("Starting provenance consumer demonstration")
    
    # Set up systems
    audit_logger, provenance_manager, integrator = setup_systems()
    
    # Create sample data lineage
    logger.info("Creating sample data lineage")
    data_ids = create_sample_lineage(provenance_manager, integrator)
    
    # Demonstrate consumer usage
    logger.info("Demonstrating consumer usage")
    demonstrate_consumer_usage(provenance_manager, integrator, data_ids)
    
    logger.info("Demonstration completed")


if __name__ == "__main__":
    run_demonstration()