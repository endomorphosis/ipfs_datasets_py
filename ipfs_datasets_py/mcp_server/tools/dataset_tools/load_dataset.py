# ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
"""
MCP tool for loading datasets.

This is a thin wrapper around the core DatasetLoader class.
Core implementation: ipfs_datasets_py.core_operations.dataset_loader.DatasetLoader
"""
import json
from typing import Dict, Any, Optional

import logging

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py import ipfs_datasets as ipfs_datasets  # type: ignore
except Exception:
    ipfs_datasets = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

from ipfs_datasets_py.core_operations import DatasetLoader

async def load_dataset(
    source: str,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Load a dataset from a source.

    This is a thin wrapper around DatasetLoader.load().
    All business logic is in ipfs_datasets_py.core_operations.dataset_loader

    Args:
        source: Source identifier of the dataset
        format: Format of the dataset
        options: Additional loading options

    Returns:
        Dict containing load results or error information
    """
    # MCP JSON-string entrypoint (used by unit tests)
    if isinstance(source, str) and format is None and options is None:
        data, error = parse_json_object(source)
        if error is not None:
            return error

        if not data.get("source"):
            return mcp_error_response("Missing required field: source", error_type="validation")

        # Use core module for legacy ipfs_datasets backend
        if ipfs_datasets is not None:
            try:
                result = ipfs_datasets.load_dataset(
                    data["source"],
                    format=data.get("format"),
                    **(data.get("options") or {}),
                )
                payload: Dict[str, Any] = {"status": "success"}
                if isinstance(result, dict):
                    payload.update(result)
                else:
                    payload["result"] = result
                return mcp_text_response(payload)
            except Exception as e:
                return mcp_text_response({"status": "error", "error": str(e)})

    # Use core module for all dataset loading
    try:
        loader = DatasetLoader()
        result = await loader.load(source, format=format, options=options)
        return result
    except Exception as e:
        logger.error(f"Error in load_dataset MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "source": source
        }
