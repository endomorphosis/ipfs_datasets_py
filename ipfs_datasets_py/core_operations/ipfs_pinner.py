"""
IPFS pinner - Core business logic for pinning content to IPFS.

This module contains the core logic for pinning files and data to IPFS.
It is used by:
- MCP server tools/ipfs_tools/pin_to_ipfs.py
- CLI commands
- Direct Python API imports
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Union

logger = logging.getLogger(__name__)


class IPFSPinner:
    """
    Pin files, directories, and data to IPFS.

    Supports:
    - File pinning
    - Directory pinning (recursive)
    - Data dictionary pinning
    - Multiple IPFS backends (direct ipfs_kit_py, MCP client)
    """

    def __init__(self, integration_mode: str = "direct"):
        """
        Initialize the IPFS pinner.

        Args:
            integration_mode: Mode for IPFS integration ("direct" or "mcp_client")
                             Can also be set via IPFS_KIT_INTEGRATION env var
        """
        self.logger = logging.getLogger(__name__ + ".IPFSPinner")
        self.integration_mode = os.environ.get("IPFS_KIT_INTEGRATION", integration_mode)

    async def pin(
        self,
        content_source: Union[str, Dict[str, Any]],
        recursive: bool = True,
        wrap_with_directory: bool = False,
        hash_algo: str = "sha2-256",
    ) -> Dict[str, Any]:
        """
        Pin a file, directory, or data to IPFS.

        Args:
            content_source: Path to the file/directory to pin, or data dict to pin
            recursive: Whether to add the directory recursively
            wrap_with_directory: Whether to wrap the file(s) in a directory
            hash_algo: The hash algorithm to use

        Returns:
            Dict containing:
            - status: "success" or "error"
            - cid: Content identifier (CID) of the pinned content
            - content_type: Type of content ("file", "directory", or "data")
            - size: Size in bytes
            - hash_algo: Hash algorithm used
            - message: Error message if status is "error"
        """
        try:
            self.logger.info(f"Pinning content from {content_source} to IPFS")

            # Handle different input types
            if isinstance(content_source, dict):
                # Data dictionary: write to a temp file and pin it genuinely.
                # Never fabricate a CID.
                import tempfile
                data_str = json.dumps(content_source)
                data_size = len(data_str)
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
                    tf.write(data_str)
                    temp_path = tf.name
                try:
                    if self.integration_mode == "direct":
                        return await self._pin_direct(
                            temp_path, recursive, wrap_with_directory, hash_algo
                        )
                    else:
                        return await self._pin_via_mcp(
                            temp_path, recursive, wrap_with_directory, hash_algo
                        )
                finally:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

            content_path = str(content_source)

            # Check if the path exists
            if not os.path.exists(content_path):
                return {
                    "status": "error",
                    "message": f"Path does not exist: {content_path}",
                    "content_path": content_path,
                }

            if self.integration_mode == "direct":
                return await self._pin_direct(
                    content_path, recursive, wrap_with_directory, hash_algo
                )
            else:
                return await self._pin_via_mcp(
                    content_path, recursive, wrap_with_directory, hash_algo
                )

        except Exception as e:
            self.logger.error(f"Error pinning content to IPFS: {e}")
            return {"status": "error", "message": str(e), "content_path": str(content_source)}

    async def _pin_direct(
        self, content_path: str, recursive: bool, wrap_with_directory: bool, hash_algo: str
    ) -> Dict[str, Any]:
        """
        Pin content directly using ipfs_kit_py.

        Args:
            content_path: Path to content
            recursive: Whether to add recursively
            wrap_with_directory: Whether to wrap with directory
            hash_algo: Hash algorithm

        Returns:
            Dict with pinning results
        """
        try:
            import ipfs_kit_py

            # Use the correct method name for adding content
            if hasattr(ipfs_kit_py, "add"):
                result = ipfs_kit_py.add(
                    content_path,
                    recursive=recursive,
                    wrap_with_directory=wrap_with_directory,
                    hash=hash_algo,
                )
            elif hasattr(ipfs_kit_py, "pin_add"):
                result = ipfs_kit_py.pin_add(content_path)
            else:
                # No pinning method available in ipfs_kit_py: honest error,
                # never fabricate a CID.
                raise RuntimeError(
                    "ipfs_kit_py has no add/pin_add method available; "
                    "cannot pin content without an IPFS backend"
                )

            cid = result.get("Hash")
            if not cid:
                raise RuntimeError(
                    "ipfs_kit_py pin operation returned no CID; "
                    "pin may have failed silently"
                )
            return {
                "status": "success",
                "cid": cid,
                "content_type": "file",
                "size": result.get("Size", os.path.getsize(content_path)),
                "hash_algo": hash_algo,
                "recursive": recursive,
                "wrap_with_directory": wrap_with_directory,
            }
        except Exception as e:
            self.logger.error(f"IPFS pin failed: {e}")
            # Honest error — never fabricate a CID on failure.
            return {
                "status": "error",
                "message": f"IPFS pin failed: {e}",
                "content_path": content_path,
            }

    async def _pin_via_mcp(
        self, content_path: str, recursive: bool, wrap_with_directory: bool, hash_algo: str
    ) -> Dict[str, Any]:
        """
        Pin content via MCP client to ipfs_kit_py MCP server.

        Args:
            content_path: Path to content
            recursive: Whether to add recursively
            wrap_with_directory: Whether to wrap with directory
            hash_algo: Hash algorithm

        Returns:
            Dict with pinning results
        """
        try:
            from modelcontextprotocol.client import MCPClient
        except ImportError:
            # Fallback if MCP client not available
            self.logger.warning("MCP client not available, falling back to direct mode")
            return await self._pin_direct(content_path, recursive, wrap_with_directory, hash_algo)

        # Create client
        ipfs_kit_mcp_url = os.environ.get("IPFS_KIT_MCP_URL", "http://localhost:5001")
        client = MCPClient(ipfs_kit_mcp_url)

        # Call the add tool
        result = await client.call_tool(
            "add",
            {
                "path": content_path,
                "recursive": recursive,
                "wrap_with_directory": wrap_with_directory,
                "hash": hash_algo,
            },
        )

        return {
            "status": "success",
            "cid": result["Hash"],
            "size": result["Size"],
            "name": result["Name"],
            "content_path": content_path,
        }

    def pin_sync(
        self,
        content_source: Union[str, Dict[str, Any]],
        recursive: bool = True,
        wrap_with_directory: bool = False,
        hash_algo: str = "sha2-256",
    ) -> Dict[str, Any]:
        """
        Synchronous version of pin method.

        This is provided for compatibility with synchronous code.
        For async code, use the pin() method directly.
        """
        from ipfs_datasets_py.utils.anyio_compat import run as _anyio_run

        return _anyio_run(self.pin(content_source, recursive, wrap_with_directory, hash_algo))
