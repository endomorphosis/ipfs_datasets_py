"""
Client implementation for the IPFS Datasets MCP server.

This module provides a convenient Python client for interacting with
the IPFS Datasets MCP server from your Python code.
"""
from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Any, Optional, Union

# Import the MCP client
try:
    from modelcontextprotocol.client import MCPClient
except ImportError:
    raise ImportError(
        "The modelcontextprotocol package is required for the IPFS Datasets MCP client. "
        "Install it with 'pip install modelcontextprotocol'"
    )


class IPFSDatasetsMCPClient:
    """
    Client for the IPFS Datasets MCP server.
    
    This class provides a convenient interface for interacting with the
    IPFS Datasets MCP server from Python code.
    
    Example:
        ```python
        # Create a client
        client = IPFSDatasetsMCPClient("http://localhost:8000")
        
        # Load a dataset
        dataset_info = await client.load_dataset("/path/to/dataset.json")
        
        # Process the dataset
        processed_info = await client.process_dataset(
            dataset_info["dataset_id"],
            [
                {"type": "filter", "column": "value", "condition": ">", "value": 50},
                {"type": "select", "columns": ["id", "name"]}
            ]
        )
        
        # Save the processed dataset
        save_info = await client.save_dataset(
            processed_info["dataset_id"],
            "/path/to/output.csv",
            "csv"
        )
        ```
    """
    
    def __init__(self, server_url: str):
        """
        Initialize the client with the server URL.
        
        Args:
            server_url: URL of the IPFS Datasets MCP server
        """
        self.mcp_client = MCPClient(server_url)
        
    async def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get a list of available tools on the server.
        
        Returns:
            List of tool information dictionaries
        """
        return await self.mcp_client.get_tool_list()
        
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the server.
        
        Args:
            tool_name: Name of the tool to call
            params: Parameters for the tool
            
        Returns:
            Tool result
        """
        return await self.mcp_client.call_tool(tool_name, params)
        
    # Dataset tools
    
    async def load_dataset(
        self,
        source: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Load a dataset from a source.
        
        Args:
            source: Source path or identifier of the dataset
            format: Format of the dataset (auto-detected if not provided)
            options: Additional options for loading the dataset
            
        Returns:
            Dataset information
        """
        params = {"source": source}
        if format:
            params["format"] = format
        if options:
            params["options"] = options
            
        return await self.call_tool("load_dataset", params)
        
    async def save_dataset(
        self,
        dataset_id: str,
        destination: str,
        format: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save a dataset to a destination.
        
        Args:
            dataset_id: ID of the dataset to save
            destination: Destination path or location to save the dataset
            format: Format to save the dataset in
            options: Additional options for saving the dataset
            
        Returns:
            Information about the saved dataset
        """
        params = {
            "dataset_id": dataset_id,
            "destination": destination
        }
        if format:
            params["format"] = format
        if options:
            params["options"] = options
            
        return await self.call_tool("save_dataset", params)
        
    async def process_dataset(
        self,
        dataset_id: str,
        operations: List[Dict[str, Any]],
        output_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a dataset with a series of operations.
        
        Args:
            dataset_id: ID of the dataset to process
            operations: List of operations to apply to the dataset
            output_id: Optional ID for the resulting dataset
            
        Returns:
            Information about the processed dataset
        """
        params = {
            "dataset_id": dataset_id,
            "operations": operations
        }
        if output_id:
            params["output_id"] = output_id
            
        return await self.call_tool("process_dataset", params)
        
    async def convert_dataset_format(
        self,
        dataset_id: str,
        target_format: str,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Convert a dataset to a different format.
        
        Args:
            dataset_id: ID of the dataset to convert
            target_format: Format to convert the dataset to
            output_path: Optional path to save the converted dataset
            
        Returns:
            Information about the converted dataset
        """
        params = {
            "dataset_id": dataset_id,
            "target_format": target_format
        }
        if output_path:
            params["output_path"] = output_path
            
        return await self.call_tool("convert_dataset_format", params)
        
    # IPFS tools
    
    async def pin_to_ipfs(
        self,
        content_path: str,
        recursive: bool = True
    ) -> Dict[str, Any]:
        """
        Pin content to IPFS.
        
        Args:
            content_path: Path to the content to pin
            recursive: Whether to recursively pin directories
            
        Returns:
            Information about the pinned content
        """
        params = {
            "content_path": content_path,
            "recursive": recursive
        }
        
        return await self.call_tool("pin_to_ipfs", params)
        
    async def get_from_ipfs(
        self,
        cid: str,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get content from IPFS.
        
        Args:
            cid: Content identifier
            output_path: Optional path to save the content
            
        Returns:
            Information about the retrieved content
        """
        params = {"cid": cid}
        if output_path:
            params["output_path"] = output_path
            
        return await self.call_tool("get_from_ipfs", params)
        
    # Vector tools
    
    async def create_vector_index(
        self,
        vectors: List[List[float]],
        dimension: int,
        metric: str = "cosine",
        metadata: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Create a vector index.
        
        Args:
            vectors: List of vectors to index
            dimension: Dimension of the vectors
            metric: Distance metric to use
            metadata: Optional metadata for each vector
            
        Returns:
            Information about the created index
        """
        params = {
            "vectors": vectors,
            "dimension": dimension,
            "metric": metric
        }
        if metadata:
            params["metadata"] = metadata
            
        return await self.call_tool("create_vector_index", params)
        
    async def search_vector_index(
        self,
        index_id: str,
        query_vector: List[float],
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Search a vector index.
        
        Args:
            index_id: ID of the index to search
            query_vector: Vector to search for
            top_k: Number of results to return
            
        Returns:
            Search results
        """
        params = {
            "index_id": index_id,
            "query_vector": query_vector,
            "top_k": top_k
        }
        
        return await self.call_tool("search_vector_index", params)
        
    # Additional methods can be added for other tool categories
