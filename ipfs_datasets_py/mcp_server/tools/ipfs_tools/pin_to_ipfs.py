# ipfs_datasets_py/mcp_server/tools/ipfs_tools/pin_to_ipfs.py
"""
MCP tool for pinning content to IPFS.

This is a thin wrapper around the core IPFSPinner class.
Core implementation: ipfs_datasets_py.core_operations.ipfs_pinner.IPFSPinner
"""
import json
import os
from typing import Dict, Any, Union

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

from ipfs_datasets_py.core_operations import IPFSPinner

async def pin_to_ipfs(
    content_source: Union[str, Dict[str, Any]],
    recursive: bool = True,
    wrap_with_directory: bool = False,
    hash_algo: str = "sha2-256"
) -> Dict[str, Any]:
    """
    Pin a file, directory, or data to IPFS.

    This is a thin wrapper around IPFSPinner.pin().
    All business logic is in ipfs_datasets_py.core_operations.ipfs_pinner

    Args:
        content_source: Path to the file/directory to pin, or data dict to pin
        recursive: Whether to add the directory recursively
        wrap_with_directory: Whether to wrap the file(s) in a directory
        hash_algo: The hash algorithm to use

    Returns:
        Dict containing information about the pinned content
    """
    # MCP JSON-string entrypoint (used by unit tests)
    if (
        isinstance(content_source, str)
        and recursive is True
        and wrap_with_directory is False
        and hash_algo == "sha2-256"
        and (
            not content_source.strip()
            or content_source.lstrip().startswith("{")
            or content_source.lstrip().startswith("[")
            or any(ch.isspace() for ch in content_source)
        )
    ):
        data, error = parse_json_object(content_source)
        if error is not None:
            return error

        if "content_source" not in data:
            return mcp_error_response("Missing required field: content_source", error_type="validation")

        # Use legacy ipfs_datasets backend if available
        if ipfs_datasets is not None:
            try:
                result = ipfs_datasets.pin_to_ipfs(
                    data["content_source"],
                    recursive=data.get("recursive", True),
                    wrap_with_directory=data.get("wrap_with_directory", False),
                )
                payload: Dict[str, Any] = {"status": "success"}
                if isinstance(result, dict):
                    payload.update(result)
                else:
                    payload["result"] = result
                return mcp_text_response(payload)
            except Exception as e:
                return mcp_text_response({"status": "error", "error": str(e)})

    # Use core module for all IPFS pinning
    try:
        pinner = IPFSPinner()
        result = await pinner.pin(
            content_source,
            recursive=recursive,
            wrap_with_directory=wrap_with_directory,
            hash_algo=hash_algo
        )
        return result
    except Exception as e:
        logger.error(f"Error in pin_to_ipfs MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "content_path": str(content_source)
        }
