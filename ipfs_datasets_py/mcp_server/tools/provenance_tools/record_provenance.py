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
        provenance_id = provenance_manager.record_operation(
            dataset_id=dataset_id,
            operation_type=operation,
            input_datasets=inputs or [],
            parameters=parameters or {},
            description=description,
            agent=agent_id,
            timestamp=timestamp,
            tags=tags or []
        )
        
        # Get the provenance record
        provenance_record = provenance_manager.get_record(provenance_id)
        
        # Return information about the recorded provenance
        return {
            "status": "success",
            "provenance_id": provenance_id,
            "dataset_id": dataset_id,
            "operation": operation,
            "timestamp": provenance_record.get("timestamp"),
            "record": provenance_record
        }
    except Exception as e:
        logger.error(f"Error recording provenance: {e}")
        return {
            "status": "error",
            "message": str(e),
            "dataset_id": dataset_id,
            "operation": operation
        }
