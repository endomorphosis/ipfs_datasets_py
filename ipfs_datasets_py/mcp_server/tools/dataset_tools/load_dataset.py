# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""
MCP tool for loading datasets.

This tool handles loading datasets from various sources and formats.
"""
import asyncio
from typing import Dict, Any, Optional, Union

from ipfs_datasets_py.mcp_server.logger import logger


async def load_dataset(
    source: str,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Load a dataset from a source.

    Args:
        source: Source path or identifier of the dataset
        format: Format of the dataset (auto-detected if not provided)
        options: Additional options for loading the dataset

    Returns:
        Dict containing dataset metadata and content summary
    """
    try:
        logger.info(f"Loading dataset from {source} with format {format if format else 'auto'}")
        
        # Default options
        if options is None:
            options = {}
            
        # Import the dataset loader
        from ipfs_datasets_py import DatasetLoader
        
        # Create a loader instance
        loader = DatasetLoader()
        
        # Load the dataset
        dataset = await loader.load_async(source, format=format, **options)
        
        # Return summary info
        return {
            "status": "success",
            "dataset_id": dataset.id,
            "metadata": dataset.metadata,
            "summary": {
                "num_records": len(dataset),
                "schema": str(dataset.schema) if hasattr(dataset, "schema") else None,
                "source": source,
                "format": dataset.format
            }
        }
    except Exception as e:
        logger.error(f"Error loading dataset: {e}")
        return {
            "status": "error",
            "message": str(e),
            "source": source
        }
