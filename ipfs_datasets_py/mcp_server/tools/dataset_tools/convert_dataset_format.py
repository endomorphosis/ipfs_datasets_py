# ipfs_datasets_py/mcp_server/tools/dataset_tools/convert_dataset_format.py
"""
MCP tool for converting dataset formats.

This is a THIN WRAPPER around DatasetConverter from core_operations.
All business logic is in ipfs_datasets_py.core_operations.dataset_converter

Refactored on 2026-02-18 during Phase 1 of MCP refactoring.
See docs/MCP_REFACTORING_PLAN.md for details.
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

from ipfs_datasets_py.core_operations import DatasetConverter


async def convert_dataset_format(
    dataset_id: str,
    target_format: Optional[str] = None,
    output_path: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert a dataset to a different format.

    This is a thin wrapper around DatasetConverter.convert().
    All business logic is in ipfs_datasets_py.core_operations.dataset_converter

    Args:
        dataset_id: The ID of the dataset to convert
        target_format: The format to convert the dataset to (parquet, csv, json, arrow, car, etc.)
        output_path: Optional path to save the converted dataset
        options: Additional options for the conversion

    Returns:
        Dict containing information about the converted dataset
    """
    # MCP JSON-string entrypoint (legacy format for backward compatibility)
    if isinstance(dataset_id, str) and target_format is None and output_path is None and options is None:
        data, error = parse_json_object(dataset_id)
        if error is not None:
            return error

        if "dataset_id" not in data:
            return mcp_error_response("Missing required field: dataset_id", error_type="validation")
        if "target_format" not in data:
            return mcp_error_response("Missing required field: target_format", error_type="validation")

        # Legacy ipfs_datasets backend support (for backward compatibility)
        if ipfs_datasets is not None:
            try:
                result = ipfs_datasets.convert_dataset_format(
                    data["dataset_id"],
                    data["target_format"],
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

    # Use core module for all dataset conversion (THIN WRAPPER pattern)
    try:
        converter = DatasetConverter()
        result = await converter.convert(dataset_id, target_format, output_path=output_path, options=options)
        return result
    except Exception as e:
        logger.error(f"Error in convert_dataset_format MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "dataset_id": dataset_id,
            "target_format": target_format
        }
