# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""
MCP tool for loading datasets.

This tool handles loading datasets from various sources and formats.
"""
import asyncio
from typing import Dict, Any, Optional, Union

from ipfs_datasets_py.mcp_server.logger import logger

# Try to import Hugging Face datasets with fallback
try:
    from datasets import load_dataset as hf_load_dataset
    HF_DATASETS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Hugging Face datasets not available: {e}")
    HF_DATASETS_AVAILABLE = False
    hf_load_dataset = None

async def load_dataset(
    source: str,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Load a dataset from a source.

    This tool loads datasets from Hugging Face Hub, local directories, or files.
    It supports various dataset formats like JSON, CSV, Parquet, and others.

    Args:
        source: Source identifier of the dataset. Can be:
                - Hugging Face dataset name (e.g., "squad", "glue/mnli")
                - Local directory path containing dataset files
                - Local file path (JSON, CSV, Parquet, etc.)
                - URL to a dataset file
                NOTE: Python (.py) files are not valid dataset sources.
        format: Format of the dataset. Supported formats: json, csv, parquet, text, etc.
                If not provided, format will be auto-detected.
        options: Additional options for loading the dataset (split, streaming, etc.)

    Returns:
        Dict containing:
        - status: "success" or "error"
        - dataset_id: Identifier for the loaded dataset
        - metadata: Dataset metadata including description and features
        - summary: Dataset summary with record count, schema, source, and format
        - message: Error message if status is "error"

    Raises:
        ValueError: If source is a Python file or invalid format
    """
    try:
        logger.info(f"Loading dataset from {source} with format {format if format else 'auto'}")

        # Input validation - reject Python files and dangerous sources
        if not source or not isinstance(source, str) or len(source.strip()) == 0:
            raise ValueError("Source must be a non-empty string")
            
        # Reject Python files for security
        if source.lower().endswith('.py'):
            raise ValueError(
                "Python files (.py) are not valid dataset sources. "
                "Please provide a dataset identifier from Hugging Face Hub, "
                "a directory path, or a data file (JSON, CSV, Parquet, etc.)"
            )
        
        # Reject other executable files
        executable_extensions = ['.pyc', '.pyo', '.exe', '.dll', '.so', '.dylib', '.sh', '.bat']
        if any(source.lower().endswith(ext) for ext in executable_extensions):
            raise ValueError(f"Executable files are not valid dataset sources: {source}")

        # Default options
        if options is None:
            options = {}

        # Check if Hugging Face datasets is available
        if not HF_DATASETS_AVAILABLE:
            logger.warning("Hugging Face datasets not available, returning error")
            return {
                "status": "error",
                "message": "Hugging Face datasets library is not available. Please install it with: pip install datasets",
                "source": source
            }

        # Load the dataset directly using Hugging Face datasets
        try:
            dataset = hf_load_dataset(source, format=format, **options)

            # Hugging Face datasets can return DatasetDict if multiple splits, handle this
            if isinstance(dataset, dict) and "train" in dataset:
                # Assuming 'train' split is the primary one for summary purposes
                dataset_obj = dataset["train"]
            else:
                dataset_obj = dataset
        except Exception as e:
            logger.error(f"Failed to load dataset: {e}")
            return {
                "status": "error",
                "message": f"Failed to load dataset from {source}: {str(e)}",
                "source": source
            }

        # Return summary info
        info = getattr(dataset_obj, "info", None)
        metadata = {}
        if info:
            # Extract common metadata fields safely
            metadata = {
                "description": getattr(info, "description", ""),
                "citation": getattr(info, "citation", ""),
                "homepage": getattr(info, "homepage", ""),
                "license": getattr(info, "license", ""),
                "version": str(getattr(info, "version", "")),
                "features": str(getattr(info, "features", ""))
            }
        
        return {
            "status": "success",
            "dataset_id": f"dataset_{source}_{id(dataset_obj)}", # Generate unique ID
            "metadata": metadata,
            "summary": {
                "num_records": len(dataset_obj),
                "schema": str(dataset_obj.features) if hasattr(dataset_obj, "features") else None,
                "source": source,
                "format": format if format else "auto-detected"
            }
        }
    except Exception as e:
        logger.error(f"Error loading dataset: {e}")
        return {
            "status": "error",
            "message": str(e),
            "source": source
        }
