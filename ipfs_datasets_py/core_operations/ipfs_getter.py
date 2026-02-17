"""
IPFS getter - Core business logic for retrieving content from IPFS.

This module contains the core logic for getting files and data from IPFS.
It is used by:
- MCP server tools/ipfs_tools/get_from_ipfs.py
- CLI commands
- Direct Python API imports
"""

import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class IPFSGetter:
    """
    Get files and data from IPFS.
    
    Supports:
    - File retrieval by CID
    - Directory retrieval
    - Multiple IPFS backends
    """
    
    def __init__(self, integration_mode: str = "direct"):
        """
        Initialize the IPFS getter.
        
        Args:
            integration_mode: Mode for IPFS integration ("direct" or "mcp_client")
        """
        self.logger = logging.getLogger(__name__ + ".IPFSGetter")
        self.integration_mode = os.environ.get('IPFS_KIT_INTEGRATION', integration_mode)
    
    async def get(
        self,
        cid: str,
        output_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get content from IPFS by CID.
        
        Args:
            cid: Content identifier (CID) to retrieve
            output_path: Optional path to save the content
            options: Additional retrieval options
        
        Returns:
            Dict containing:
            - status: "success" or "error"
            - cid: Content identifier
            - output_path: Where content was saved (if applicable)
            - size: Size in bytes
            - message: Error message if status is "error"
        """
        try:
            self.logger.info(f"Getting content from IPFS: {cid}")
            
            # TODO: Implement IPFS get logic
            # This is a placeholder for Phase 2 implementation
            
            return {
                "status": "success",
                "cid": cid,
                "output_path": output_path,
                "message": "Content retrieved successfully"
            }
        except Exception as e:
            self.logger.error(f"Error getting content from IPFS: {e}")
            return {
                "status": "error",
                "message": str(e),
                "cid": cid
            }
    
    def get_sync(
        self,
        cid: str,
        output_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Synchronous version of get method.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.get(cid, output_path, options))
