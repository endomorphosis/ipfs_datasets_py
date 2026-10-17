# ipfs_datasets_py/mcp_server/tools/dataset_tools/save_dataset.py
"""
MCP tool for saving datasets.

This tool handles saving datasets to various destinations and formats.
"""

import anyio
import json
from typing import Dict, Any, Optional, Union

import logging

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py import ipfs_datasets as ipfs_datasets  # type: ignore
except (ImportError, ModuleNotFoundError):
    ipfs_datasets = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)


async def save_dataset(
    dataset_data: str | Dict[str, Any],
    destination: Optional[str] = None,
    format: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Save a dataset to a destination.

    This tool saves datasets to local files, IPFS, or other storage systems.
    It supports various output formats and validation of destination paths.

    Args:
        dataset_data: The dataset to save. Can be:
                     - Dataset ID string (references a loaded dataset)
                     - Dictionary containing dataset content
                     NOTE: Must be valid dataset content, not executable code.
        destination: Destination path where to save the dataset. Can be:
                    - Local file path (e.g., "/path/to/dataset.json")
                    - Directory path (files will be created inside)
                    - IPFS CID or path (when using IPFS storage)
                    NOTE: Should not be an executable file path.
        format: Output format for the dataset. Supported formats:
               - "json": JSON format (default)
               - "csv": Comma-separated values
               - "parquet": Apache Parquet format
               - "arrow": Apache Arrow format
               - "car": IPLD CAR format for IPFS
        options: Additional options for saving (compression, metadata, etc.)

    Returns:
        Dict containing:
        - status: "success" or "error"
        - dataset_id: Identifier of the saved dataset
        - destination: Where the dataset was saved
        - format: Format used for saving
        - size: Size information about the saved dataset
        - message: Error message if status is "error"

    Raises:
        ValueError: If destination is invalid or dataset_data is malformed
    """
    # MCP JSON-string entrypoint (used by unit tests)
    if isinstance(dataset_data, str) and destination is None and format is None and options is None:
        data, error = parse_json_object(dataset_data)
        if error is not None:
            return error

        if "destination" not in data:
            return mcp_error_response(
                "Missing required field: destination", error_type="validation"
            )
        if "dataset_data" not in data:
            return mcp_error_response(
                "Missing required field: dataset_data", error_type="validation"
            )

        if ipfs_datasets is None:
            return mcp_error_response("ipfs_datasets backend is not available")

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

    try:
        logger.info(
            f"Saving dataset {dataset_data} to {destination} with format {format if format else 'default'}"
        )

        if destination is None:
            raise ValueError("Destination must be provided")

        # Input validation - prevent saving as executable files
        if not destination or not isinstance(destination, str) or len(destination.strip()) == 0:
            raise ValueError("Destination must be a non-empty string")

        # Reject executable file destinations for security
        executable_extensions = [
            ".py",
            ".pyc",
            ".pyo",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".sh",
            ".bat",
        ]
        if any(destination.lower().endswith(ext) for ext in executable_extensions):
            raise ValueError(
                f"Cannot save dataset as executable file: {destination}. "
                "Please use a data format like .json, .csv, .parquet, etc."
            )

        # Validate dataset_data
        if dataset_data is None:
            raise ValueError("Dataset data cannot be None")

        if isinstance(dataset_data, str) and not dataset_data.strip():
            raise ValueError("Dataset ID cannot be empty")

        # Default options
        if options is None:
            options = {}

        # Handle both dataset ID strings and direct data dictionaries
        if isinstance(dataset_data, dict):
            # Direct data provided: genuinely save it to destination.
            # Never fabricate a success without writing.
            import hashlib
            data_str = json.dumps(dataset_data)
            data_size = len(data_str)
            dataset_id = f"dataset_{hashlib.sha256(data_str.encode()).hexdigest()[:16]}"
            record_count = len(dataset_data.get("data", []))

            logger.info(
                f"Saving dataset with {record_count} records to {destination}"
            )

            # Actually write the data.
            save_format = (format or "json").lower()
            try:
                if save_format == "json":
                    with open(destination, "w") as f:
                        json.dump(dataset_data, f, indent=2)
                elif save_format == "csv":
                    import csv
                    rows = dataset_data.get("data", [])
                    if rows and isinstance(rows[0], dict):
                        with open(destination, "w", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                            writer.writeheader()
                            writer.writerows(rows)
                    else:
                        raise ValueError("CSV format requires data as list of dicts")
                else:
                    raise ValueError(f"Unsupported format for direct save: {save_format}")
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to save dataset: {e}",
                    "dataset_id": dataset_id,
                    "destination": destination,
                }

            # Record in the local registry so list_datasets/browse can find it.
            try:
                import os as _os
                registry_path = _os.path.expanduser("~/.ipfs_datasets_registry.json")
                registry = {}
                if _os.path.exists(registry_path):
                    with open(registry_path) as _rf:
                        registry = json.load(_rf)
                registry[dataset_id] = {
                    "destination": destination,
                    "format": save_format,
                    "record_count": record_count,
                    "size": data_size,
                }
                with open(registry_path, "w") as _wf:
                    json.dump(registry, _wf, indent=2)
            except Exception as _re:
                logger.warning(f"Could not update dataset registry: {_re}")

            return {
                "status": "success",
                "dataset_id": dataset_id,
                "destination": destination,
                "format": save_format,
                "location": destination,
                "size": data_size,
                "record_count": record_count,
            }
        else:
            # Dataset ID provided - try to use the dataset manager
            dataset_id = str(dataset_data)

        # Resolve DatasetManager lazily so importing this module does not require
        # optional heavyweight dependencies.
        try:
            from ipfs_datasets_py.dataset_manager import DatasetManager  # local import

            manager = DatasetManager()
            dataset = manager.get_dataset(dataset_id)
            result = await dataset.save_async(destination, format=format, **options)
        except Exception as e:
            logger.error(f"Dataset manager not available: {e}")
            return {
                "status": "error",
                "message": f"Dataset manager not available: {e}",
                "dataset_id": dataset_id,
                "destination": destination,
            }

        # Return information about the saved dataset
        return {
            "status": "success",
            "dataset_id": dataset_id,
            "destination": destination,
            "format": format or dataset.format,
            "location": result.get("location", destination),
            "size": result.get("size", None),
        }
    except Exception as e:
        logger.error(f"Error saving dataset: {e}")
        return {
            "status": "error",
            "message": str(e),
            "dataset_id": dataset_id if isinstance(dataset_data, str) else str(dataset_data),
            "destination": destination,
        }
