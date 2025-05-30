# ipfs_datasets_py/mcp_server/tools/provenance_tools/record_provenance.py
"""
MCP tool for recording data provenance.

This tool handles recording data provenance information for datasets.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger


async def record_provenance(
    dataset_id: str,
    operation: str,
    inputs: Optional[List[str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    agent_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Record provenance information for a dataset operation.

    Args:
        dataset_id: ID of the dataset
        operation: The operation performed on the dataset
        inputs: Optional list of input dataset IDs or sources
        parameters: Optional parameters used in the operation
        description: Optional description of the operation
        agent_id: Optional ID of the agent performing the operation
        timestamp: Optional timestamp for the operation (ISO format)
        tags: Optional tags for categorizing the provenance record

    Returns:
        Dict containing information about the recorded provenance
    """
    try:
        logger.info(f"Recording provenance for dataset {dataset_id}, operation: {operation}")

        # Import the provenance manager
        from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

        # Create a provenance manager instance
        provenance_manager = EnhancedProvenanceManager()

        # Record the provenance
        provenance_id = provenance_manager.begin_transformation(
            description=description or f"Operation: {operation}",
            transformation_type=operation,
            tool=agent_id or "mcp-tool",
            input_ids=inputs or [],
            parameters=parameters or {},
            metadata={"tags": tags or [], "timestamp": timestamp}
        )

        # Get the provenance record
        provenance_record = provenance_manager.records.get(provenance_id, None)

        # Extract record info, handling both dict and object types
        if provenance_record:
            if hasattr(provenance_record, 'timestamp'):
                # It's a ProvenanceRecord object
                record_timestamp = provenance_record.timestamp
                record_dict = provenance_record.to_dict() if hasattr(provenance_record, 'to_dict') else {
                    'id': getattr(provenance_record, 'id', provenance_id),
                    'timestamp': record_timestamp,
                    'description': getattr(provenance_record, 'description', ''),
                    'operation': operation
                }
            else:
                # It's a dict
                record_timestamp = provenance_record.get("timestamp")
                record_dict = provenance_record
        else:
            record_timestamp = None
            record_dict = {}

        # Return information about the recorded provenance
        return {
            "status": "success",
            "provenance_id": provenance_id,
            "dataset_id": dataset_id,
            "operation": operation,
            "timestamp": record_timestamp,
            "record": record_dict
        }
    except Exception as e:
        logger.error(f"Error recording provenance: {e}")
        return {
            "status": "error",
            "message": str(e),
            "dataset_id": dataset_id,
            "operation": operation
        }
