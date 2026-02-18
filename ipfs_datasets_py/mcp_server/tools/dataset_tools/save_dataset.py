# ipfs_datasets_py/mcp_server/tools/dataset_tools/save_dataset.py
"""
MCP tool for saving datasets.

This is a THIN WRAPPER around DatasetSaver from core_operations.
All business logic is in ipfs_datasets_py.core_operations.dataset_saver

Refactored on 2026-02-18 during Phase 1 of MCP refactoring.
See docs/MCP_REFACTORING_PLAN.md for details.
"""
import json
from typing import Dict, Any, Optional, Union

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

from ipfs_datasets_py.core_operations import DatasetSaver


async def save_dataset(
    dataset_data: Union[str, Dict[str, Any]],
    destination: Optional[str] = None,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Save a dataset to a destination.

    This is a thin wrapper around DatasetSaver.save().
    All business logic is in ipfs_datasets_py.core_operations.dataset_saver

    Args:
        dataset_data: The dataset to save (Dataset ID string or dictionary)
        destination: Destination path where to save the dataset
        format: Output format (json, csv, parquet, arrow, car, etc.)
        options: Additional options for saving

    Returns:
        Dict containing save results or error information
    """
    # MCP JSON-string entrypoint (legacy format for backward compatibility)
    if isinstance(dataset_data, str) and destination is None and format is None and options is None:
        data, error = parse_json_object(dataset_data)
        if error is not None:
            return error

        if "destination" not in data:
            return mcp_error_response("Missing required field: destination", error_type="validation")
        if "dataset_data" not in data:
            return mcp_error_response("Missing required field: dataset_data", error_type="validation")

        # Legacy ipfs_datasets backend support (for backward compatibility)
        if ipfs_datasets is not None:
            try:
                result = ipfs_datasets.save_dataset(
                    data["dataset_data"],
                    data["destination"],
                    format=data.get("format"),
                    options=data.get("options"),
                )
                payload: Dict[str, Any] = {"status": "success"}
                if isinstance(result, dict):
                    payload.update(result)
                else:
                    payload["result"] = result
                return mcp_text_response(payload)
            except Exception as e:
                return mcp_text_response({"status": "error", "error": str(e)})

    # Use core module for all dataset saving (THIN WRAPPER pattern)
    try:
        saver = DatasetSaver()
        result = await saver.save(dataset_data, destination, format=format, options=options)
        return result
    except Exception as e:
        logger.error(f"Error in save_dataset MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "destination": destination
        }
