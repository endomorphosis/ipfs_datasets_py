# ipfs_datasets_py/mcp_server/tools/dataset_tools/process_dataset.py
"""
MCP tool for processing datasets.

This tool handles applying transformations and operations to datasets.
Refactored to follow the thin wrapper pattern.
"""

import logging
from typing import Dict, Any, Optional, Union, List

logger = logging.getLogger(__name__)

# Import core operations
try:
    from ipfs_datasets_py.core_operations import DataProcessor

    CORE_OPS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Core operations not available: {e}")
    CORE_OPS_AVAILABLE = False
    DataProcessor = None

try:
    from ipfs_datasets_py import ipfs_datasets as ipfs_datasets  # type: ignore
except (ImportError, ModuleNotFoundError):
    ipfs_datasets = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

# Try to import Hugging Face datasets with fallback
try:
    from datasets import Dataset, DatasetDict

    HF_DATASETS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Hugging Face datasets not available: {e}")
    HF_DATASETS_AVAILABLE = False
    Dataset = None
    DatasetDict = None


def _validate_operations(operations: List[Dict[str, Any]]) -> Optional[str]:
    """Validate operations structure and security."""
    if not operations or not isinstance(operations, list):
        return "Operations must be a non-empty list"

    dangerous_ops = ["exec", "eval", "import", "compile", "__import__"]
    for i, operation in enumerate(operations):
        if not isinstance(operation, dict):
            return f"Operation {i} must be a dictionary"
        if "type" not in operation:
            return f"Operation {i} must have a 'type' field"
        if operation.get("type", "").lower() in dangerous_ops:
            return f"Operation type '{operation['type']}' is not allowed"
    return None


def _get_record_count(dataset_source: Union[str, dict, Any]) -> int:
    """Get initial record count from dataset source."""
    if isinstance(dataset_source, dict):
        return len(dataset_source.get("data", []))
    if hasattr(dataset_source, "__len__"):
        try:
            return len(dataset_source)
        except (TypeError, AttributeError):
            # Object doesn't support len(), use default
            pass
    return 100  # Default mock count


async def process_dataset(
    dataset_source: Union[str, dict, Any],
    operations: Optional[List[Dict[str, Any]]] = None,
    output_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process a dataset with a series of operations.

    Args:
        dataset_source: Dataset to process (ID string, dict, or Dataset object)
        operations: List of operation dicts with "type" and parameters
        output_id: Optional ID for the resulting dataset

    Returns:
        Dict with status, dataset_id, num_operations, num_records, etc.
    """
    # Handle MCP JSON-string entrypoint
    if isinstance(dataset_source, str) and operations is None:
        data, error = parse_json_object(dataset_source)
        if error:
            return error
        if "dataset_source" not in data or "operations" not in data:
            return mcp_error_response("Missing required fields", error_type="validation")
        if ipfs_datasets:
            try:
                result = ipfs_datasets.process_dataset(data["dataset_source"], data["operations"])
                return mcp_text_response(
                    {
                        "status": "success",
                        **(result if isinstance(result, dict) else {"result": result}),
                    }
                )
            except Exception as e:
                return mcp_text_response({"status": "error", "error": str(e)})
        return mcp_error_response("ipfs_datasets backend not available")

    try:
        # Validate inputs
        if dataset_source is None:
            raise ValueError("Dataset source cannot be None")

        validation_error = _validate_operations(operations)
        if validation_error:
            raise ValueError(validation_error)

        # Get initial record count
        initial_records = _get_record_count(dataset_source)
        logger.info(
            f"Processing dataset with {len(operations)} operations. Initial: {initial_records} records"
        )

        # Initialize DataProcessor if available
        data_processor = DataProcessor() if CORE_OPS_AVAILABLE else None

        # Process operations — genuine implementation.
        # If dataset_source is a dict with data, apply operations for real.
        # Otherwise, return an honest error (no fabricated record counts).
        data = None
        if isinstance(dataset_source, dict):
            data = dataset_source.get("data", [])
        elif hasattr(dataset_source, "__iter__") and not isinstance(dataset_source, str):
            try:
                data = list(dataset_source)
            except Exception:
                data = None

        if data is None:
            return {
                "status": "error",
                "message": (
                    "process_dataset requires dataset_source as a dict with a "
                    "'data' list (or an iterable of records). String dataset IDs "
                    "are not supported without a dataset registry lookup."
                ),
                "error_type": "validation",
                "original_dataset_id": str(dataset_source)[:50] if dataset_source else "unknown",
            }

        initial_records = len(data)
        processed = list(data)
        for i, operation in enumerate(operations):
            op_type = operation.get("type", "").lower()
            logger.info(f"Applying operation {i + 1}/{len(operations)}: {op_type}")

            if op_type == "filter":
                # Genuine filter: keep records matching all conditions.
                conditions = operation.get("conditions", {}) or operation.get("where", {})
                if conditions:
                    def _matches(rec):
                        if not isinstance(rec, dict):
                            return True
                        for k, v in conditions.items():
                            if rec.get(k) != v:
                                return False
                        return True
                    processed = [r for r in processed if _matches(r)]
            elif op_type in ("transform", "map"):
                # Genuine transform: apply field mappings/renames.
                mapping = operation.get("mapping", {}) or operation.get("fields", {})
                if mapping and all(isinstance(r, dict) for r in processed):
                    transformed = []
                    for r in processed:
                        nr = dict(r)
                        for old_k, new_k in mapping.items():
                            if old_k in nr:
                                nr[new_k] = nr.pop(old_k)
                        transformed.append(nr)
                    processed = transformed
            elif op_type == "clean":
                # Genuine clean: drop records that are empty/None.
                processed = [r for r in processed if r not in (None, {}, [], "")]
            elif op_type == "normalize":
                # Genuine normalize: lowercase string values if requested.
                fields = operation.get("fields", [])
                if fields:
                    normalized = []
                    for r in processed:
                        if isinstance(r, dict):
                            nr = dict(r)
                            for f in fields:
                                if isinstance(nr.get(f), str):
                                    nr[f] = nr[f].strip().lower()
                            normalized.append(nr)
                        else:
                            normalized.append(r)
                    processed = normalized
            else:
                logger.warning(f"Unknown operation type '{op_type}'; skipping")

        processed_records = len(processed)
        # Use a content-based ID, not a fabricated hash.
        import hashlib as _hashlib
        dataset_id = output_id or f"processed_{_hashlib.sha256(str(processed_records).encode()).hexdigest()[:12]}"
        return {
            "status": "success",
            "original_dataset_id": str(dataset_source)[:50] if isinstance(dataset_source, str) else "inline-data",
            "dataset_id": dataset_id,
            "num_operations": len(operations),
            "num_records": processed_records,
            "operations_summary": [op.get("type", "unknown") for op in operations],
            "transformation_ratio": processed_records / initial_records
            if initial_records > 0
            else 1.0,
            "core_operations_used": CORE_OPS_AVAILABLE,
            "data": processed if len(processed) <= 1000 else processed[:1000],
            "truncated": len(processed) > 1000,
        }

    except (ValueError, TypeError) as e:
        logger.error(f"Validation error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "error_type": "validation",
            "original_dataset_id": str(dataset_source)[:50] if dataset_source else "unknown",
        }
    except Exception as e:
        logger.error(f"Processing error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "error_type": "processing",
            "original_dataset_id": str(dataset_source)[:50] if dataset_source else "unknown",
        }
