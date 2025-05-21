# ipfs_datasets_py/mcp_server/tools/ipfs_tools/pin_to_ipfs.py
"""
MCP tool for pinning content to IPFS.

This tool handles pinning files and directories to IPFS.
"""
import asyncio
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union

from ipfs_datasets_py.mcp_server.logger import logger


async def pin_to_ipfs(
    content_path: str,
    recursive: bool = True,
    wrap_with_directory: bool = False,
    hash_algo: str = "sha2-256"
) -> Dict[str, Any]:
    """
    Pin a file or directory to IPFS.

    Args:
        content_path: Path to the file or directory to pin
        recursive: Whether to add the directory recursively
        wrap_with_directory: Whether to wrap the file(s) in a directory
        hash_algo: The hash algorithm to use

    Returns:
        Dict containing information about the pinned content
    """
    try:
        logger.info(f"Pinning content from {content_path} to IPFS")
        
        # Check if the path exists
        if not os.path.exists(content_path):
            return {
                "status": "error",
                "message": f"Path does not exist: {content_path}",
                "content_path": content_path
            }
            
        # Determine if we're using direct ipfs_kit_py or MCP client
        from ipfs_datasets_py.mcp_server.configs import configs
        
        if configs.ipfs_kit_integration == "direct":
            # Direct integration with ipfs_kit_py
            import ipfs_kit_py
            
            # Pin the content
            result = await ipfs_kit_py.add_async(
                content_path, 
                recursive=recursive,
                wrap_with_directory=wrap_with_directory,
                hash=hash_algo
            )
            
            return {
                "status": "success",
                "cid": result["Hash"],
                "size": result["Size"],
                "name": result["Name"],
                "content_path": content_path
            }
        else:
            # Use MCP client to call ipfs_kit_py MCP server
            from modelcontextprotocol.client import MCPClient
            
            # Create client 
            client = MCPClient(configs.ipfs_kit_mcp_url)
            
            # Call the add tool
            result = await client.call_tool("add", {
                "path": content_path,
                "recursive": recursive,
                "wrap_with_directory": wrap_with_directory,
                "hash": hash_algo
            })
            
            return {
                "status": "success",
                "cid": result["Hash"],
                "size": result["Size"],
                "name": result["Name"],
                "content_path": content_path
            }
    except Exception as e:
        logger.error(f"Error pinning content to IPFS: {e}")
        return {
            "status": "error",
            "message": str(e),
            "content_path": content_path
        }
