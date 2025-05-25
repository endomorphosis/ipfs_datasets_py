# ipfs_datasets_py/mcp_server/tools/dataset_tools/convert_dataset_format.py
"""
MCP tool for converting dataset formats.

This tool handles converting datasets between different formats (parquet, CSV, JSON, etc.).
"""
import asyncio
from typing import Dict, Any, Optional, Union

from ipfs_datasets_py.mcp_server.logger import logger


async def convert_dataset_format(
    dataset_id: str,
    target_format: str,
    output_path: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert a dataset to a different format.

    Args:
        dataset_id: The ID of the dataset to convert
        target_format: The format to convert the dataset to (parquet, csv, json, etc.)
        output_path: Optional path to save the converted dataset
        options: Additional options for the conversion

    Returns:
        Dict containing information about the converted dataset
    """
    try:
        logger.info(f"Converting dataset {dataset_id} to {target_format} format")
        
        # Default options
        if options is None:
            options = {}
            
        # Import the dataset manager
        from ipfs_datasets_py.libp2p_kit import DistributedDatasetManager
        
        # Create a manager instance
        manager = DistributedDatasetManager()
        
        # Get the dataset
        dataset = manager.shard_manager.get_dataset(dataset_id)
        
        # Get the original format
        original_format = dataset.format if hasattr(dataset, "format") else "unknown"
        
        # Convert the dataset
        if output_path:
            # Save to the specified path with the target format
            result = await dataset.save_async(output_path, format=target_format, **options)
            
            # Return information about the conversion
            return {
                "status": "success",
                "dataset_id": dataset_id,
                "original_format": original_format,
                "target_format": target_format,
                "output_path": output_path,
                "size": result.get("size", None)
            }
        else:
            # Convert in memory
            converted_dataset = dataset.convert_format(target_format, **options)
            
            # Add the converted dataset to the manager
            converted_id = manager.shard_manager.add_dataset(converted_dataset)
            
            # Return information about the conversion
            return {
                "status": "success",
                "original_dataset_id": dataset_id,
                "dataset_id": converted_id,
                "original_format": original_format,
                "target_format": target_format,
                "num_records": len(converted_dataset)
            }
    except Exception as e:
        logger.error(f"Error converting dataset format: {e}")
        return {
            "status": "error",
            "message": str(e),
            "dataset_id": dataset_id,
            "target_format": target_format
        }
