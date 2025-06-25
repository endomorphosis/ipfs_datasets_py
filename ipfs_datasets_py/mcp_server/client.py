"""
Simplified client implementation for the IPFS Datasets MCP server.

This module provides a streamlined Python client for interacting with
the IPFS Datasets MCP server from your Python code.
"""
from __future__ import annotations
import inspect
from typing import Dict, List, Any, Optional, Self, Callable
from functools import wraps

# Import the actual MCP client (fix circular import)
try:
    from mcp import Client as MCPClient
except ImportError:
    try:
        # Fallback if different package structure
        from modelcontextprotocol import Client as MCPClient
    except ImportError:
        raise ImportError(
            "The modelcontextprotocol package is required for the IPFS Datasets MCP client. "
            "Install it with 'pip install modelcontextprotocol'"
        )


def tool_call(tool_name: str) -> Callable:
    """
    Decorator for tool calling methods that automatically handles parameter mapping.
    
    Args:
        tool_name: Name of the MCP tool to call
        
    Returns:
        Decorated method that calls the specified tool
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs) -> Dict[str, Any]:
            # Get method signature and bind arguments
            sig = inspect.signature(func)
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            
            # Remove 'self' and filter out None values
            params = {k: v for k, v in bound.arguments.items() 
                     if k != 'self' and v is not None}
            
            return await self.call_tool(tool_name, **params)
        return wrapper
    return decorator


class DatasetMixin:
    """Mixin for dataset-related operations."""
    
    @tool_call("load_dataset")
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
        pass  # Implementation handled by decorator

    @tool_call("save_dataset")
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
        pass  # Implementation handled by decorator

    @tool_call("process_dataset")
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
        pass  # Implementation handled by decorator

    @tool_call("convert_dataset_format")
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
        pass  # Implementation handled by decorator


class IPFSMixin:
    """Mixin for IPFS-related operations."""
    
    @tool_call("pin_to_ipfs")
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
        pass  # Implementation handled by decorator

    @tool_call("get_from_ipfs")
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
        pass  # Implementation handled by decorator


class VectorMixin:
    """Mixin for vector-related operations."""
    
    @tool_call("create_vector_index")
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
        pass  # Implementation handled by decorator

    @tool_call("search_vector_index")
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
        pass  # Implementation handled by decorator


class IPFSDatasetsMCPClient(DatasetMixin, IPFSMixin, VectorMixin):
    """
    Simplified client for the IPFS Datasets MCP server.

    This class provides a streamlined interface for interacting with the
    IPFS Datasets MCP server from Python code using mixins and decorators
    to reduce boilerplate.

    Example:
        ```python
        # Use as context manager for automatic connection management
        async with IPFSDatasetsMCPClient("http://localhost:8000") as client:
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

        Or use manually:
        ```python
        client = IPFSDatasetsMCPClient("http://localhost:8000")
        await client.connect()
        try:
            # Your operations here
            tools = await client.get_available_tools()
        finally:
            await client.disconnect()
        ```
    """

    def __init__(self, server_url: str) -> None:
        """
        Initialize the client with the server URL.

        Args:
            server_url: URL of the IPFS Datasets MCP server
        """
        self.server_url = server_url
        self.mcp_client = MCPClient(server_url)
        self._connected = False

    async def connect(self) -> None:
        """Connect to the MCP server."""
        if not self._connected:
            await self.mcp_client.connect()
            self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._connected:
            await self.mcp_client.disconnect()
            self._connected = False

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def _build_params(self, **kwargs) -> Dict[str, Any]:
        """
        Build parameters dictionary, filtering out None values.
        
        Args:
            **kwargs: Keyword arguments to include in parameters
            
        Returns:
            Dictionary with non-None values
        """
        return {k: v for k, v in kwargs.items() if v is not None}

    async def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Call a tool on the server with simplified parameter handling.

        Args:
            tool_name: Name of the tool to call
            **kwargs: Parameters for the tool

        Returns:
            Tool result
            
        Raises:
            ConnectionError: If not connected to server
            ValueError: If tool call fails
        """
        if not self._connected:
            raise ConnectionError("Not connected to MCP server. Call connect() first or use as context manager.")
        
        try:
            params = self._build_params(**kwargs) if kwargs else {}
            return await self.mcp_client.call_tool(tool_name, params)
        except Exception as e:
            raise ValueError(f"Tool call '{tool_name}' failed: {e}") from e

    async def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get a list of available tools on the server.

        Returns:
            List of tool information dictionaries
            
        Raises:
            ConnectionError: If not connected to server
        """
        if not self._connected:
            raise ConnectionError("Not connected to MCP server. Call connect() first or use as context manager.")
        
        return await self.mcp_client.get_tool_list()

    async def health_check(self) -> bool:
        """
        Perform a health check on the server connection.
        
        Returns:
            True if server is responding, False otherwise
        """
        try:
            await self.get_available_tools()
            return True
        except Exception:
            return False