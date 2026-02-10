# src/mcp_server/tools/vector_store_tools.py

import logging
from typing import Dict, Any, List, Optional, Union
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.mcp_server.validators import validator

from ipfs_datasets_py.vector_stores.vector_store_tools_api import (
    add_embeddings_to_store_from_parameters,
    create_vector_store_from_parameters,
    delete_from_vector_store_from_parameters,
    get_vector_store_stats_from_parameters,
    manage_vector_index,
    manage_vector_metadata,
    optimize_vector_store_from_parameters,
    retrieve_vectors,
    search_vector_store_from_parameters,
)

logger = logging.getLogger(__name__)

class VectorIndexTool(ClaudeMCPTool):
    """
    Tool for managing vector indexes in the MCP (Model Context Protocol) framework.
    This tool provides functionality to create, update, delete, and retrieve information
    about vector indexes used for efficient similarity search and retrieval operations.

    Attributes:
        name (str): The tool name identifier ("manage_vector_index").
        description (str): Human-readable description of the tool's purpose.
        input_schema (dict): JSON schema defining the tool's input parameters.
        vector_service: The vector service instance used for index operations.

    Methods:
        __init__(vector_service): Initialize the tool with a vector service instance.
        execute(action, index_name, config=None): Execute vector index management operations.

    Parameters:
        action (str): The operation to perform - one of "create", "update", "delete", or "info".
        index_name (str): Name of the vector index to operate on (1-100 characters).
        config (dict, optional): Configuration parameters for index creation/update including:
            - dimension (int): Vector dimension size (minimum 1)
            - metric (str): Distance metric ("cosine", "euclidean", or "dot")
            - index_type (str): Index implementation ("faiss", "hnswlib", or "annoy")

    Returns:
        dict: Operation result containing action, index_name, result data, and success status.

    Raises:
        ValueError: If vector_service is None during initialization.
        Exception: If vector index operation fails during execution.

    Example:
        >>> tool = VectorIndexTool(vector_service)
        >>> result = await tool.execute("create", "my_index", {
        ...     "dimension": 768,
        ...     "metric": "cosine",
        ...     "index_type": "faiss"
        ... })
    """
    def __init__(self, vector_service):
        """Initialize the VectorIndexTool with a vector service.

        This tool provides functionality to create, update, delete, and get information
        about vector indexes for efficient similarity search operations.

        Attributes initialized:
            name (str): The name of the tool, set to "manage_vector_index".
            description (str): Description of the tool's functionality.
            input_schema (dict): JSON schema defining the tool's input parameters including:
                - action: The operation to perform (create, update, delete, info)
                - index_name: Name of the vector index (1-100 characters)
                - config: Optional configuration object with dimension, metric, and index_type
            vector_service: The vector service instance for managing vector indexes.

        Args:
            vector_service: The vector service instance used for managing vector indexes.
                           Must not be None.

        Raises:
            ValueError: If vector_service is None.

        """
        super().__init__()
        if vector_service is None:
            raise ValueError("Vector service cannot be None")
            
        self.name = "manage_vector_index"
        self.description = "Create, update, or manage vector indexes for efficient search."
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "delete", "info"],
                    "description": "Action to perform on the vector index."
                },
                "index_name": {
                    "type": "string",
                    "description": "Name of the vector index.",
                    "minLength": 1,
                    "maxLength": 100
                },
                "config": {
                    "type": "object",
                    "description": "Configuration for index creation/update.",
                    "properties": {
                        "dimension": {"type": "integer", "minimum": 1},
                        "metric": {"type": "string", "enum": ["cosine", "euclidean", "dot"]},
                        "index_type": {"type": "string", "enum": ["faiss", "hnswlib", "annoy"]}
                    }
                }
            },
            "required": ["action", "index_name"]
        }
        self.vector_service = vector_service
    
    async def execute(self, action: str, index_name: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute vector index management operation."""
        try:
            # Validate inputs
            action = validator.validate_algorithm_choice(action, ["create", "update", "delete", "info"])
            index_name = validator.validate_text_input(index_name)

            result = await manage_vector_index(
                vector_service=self.vector_service,
                action=action,
                index_name=index_name,
                config=config,
            )
            return {
                "action": action,
                "index_name": index_name,
                "result": result,
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Vector index operation failed: {e}")
            raise


class VectorRetrievalTool(ClaudeMCPTool):
    """
    Tool for retrieving vectors from storage.
    """
    def __init__(self, vector_service):
        super().__init__()
        if vector_service is None:
            raise ValueError("Vector service cannot be None")
            
        self.name = "retrieve_vectors"
        self.description = "Retrieve vectors from storage with optional filtering."
        self.input_schema = {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection name to retrieve from.",
                    "default": "default"
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific vector IDs to retrieve.",
                    "minItems": 1,
                    "maxItems": 1000
                },
                "filters": {
                    "type": "object",
                    "description": "Metadata filters for retrieval."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of vectors to retrieve.",
                    "minimum": 1,
                    "maximum": 10000,
                    "default": 100
                }
            },
            "required": []
        }
        self.vector_service = vector_service
    
    async def execute(self, collection: str = "default", ids: Optional[List[str]] = None, 
                     filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> Dict[str, Any]:
        """Execute vector retrieval operation."""
        try:
            # Validate inputs
            collection = validator.validate_text_input(collection)
            
            if ids:
                for id_val in ids:
                    validator.validate_text_input(id_val)
            
            vectors = await retrieve_vectors(
                vector_service=self.vector_service,
                collection=collection,
                ids=ids,
                filters=filters,
                limit=limit,
            )
            
            return {
                "collection": collection,
                "vectors": vectors,
                "count": len(vectors),
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            raise


class VectorMetadataTool(ClaudeMCPTool):
    """
    Tool for managing vector metadata.
    """
    
    def __init__(self, vector_service):
        super().__init__()
        if vector_service is None:
            raise ValueError("Vector service cannot be None")
            
        self.name = "manage_vector_metadata"
        self.description = "Manage metadata associated with vectors."
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "update", "delete", "list"],
                    "description": "Action to perform on vector metadata."
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name.",
                    "default": "default"
                },
                "vector_id": {
                    "type": "string",
                    "description": "ID of the vector (required for get, update, delete)."
                },
                "metadata": {
                    "type": "object",
                    "description": "Metadata to update (required for update action)."
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for listing metadata."
                }
            },
            "required": ["action"]
        }
        self.vector_service = vector_service
    
    async def execute(self, action: str, collection: str = "default", 
                     vector_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                     filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute vector metadata management operation."""
        try:
            # Validate inputs
            action = validator.validate_algorithm_choice(action, ["get", "update", "delete", "list"])
            collection = validator.validate_text_input(collection)
            
            if vector_id:
                vector_id = validator.validate_text_input(vector_id)
            
            result = await manage_vector_metadata(
                vector_service=self.vector_service,
                action=action,
                collection=collection,
                vector_id=vector_id,
                metadata=metadata,
                filters=filters,
            )
            
            return {
                "action": action,
                "collection": collection,
                "vector_id": vector_id,
                "result": result,
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Vector metadata operation failed: {e}")
            raise


async def create_vector_store_tool(
    store_path: str,
    dimension: int,
    provider: str = "faiss",
    index_type: str = "flat",
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a vector store with specified configuration.
    
    Args:
        store_path: Path where the vector store will be saved
        dimension: Vector dimension for the store
        provider: Vector store provider (faiss, pinecone, chroma, etc.)
        index_type: Type of index to create
        config: Additional configuration options
        
    Returns:
        Dict containing creation results
    """
    return await create_vector_store_from_parameters(
        store_path=store_path,
        dimension=dimension,
        provider=provider,
        index_type=index_type,
        config=config,
    )


async def add_embeddings_to_store_tool(
    store_id: str,
    embeddings: List[List[float]],
    metadata: Optional[List[Dict[str, Any]]] = None,
    ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Add embeddings to an existing vector store.
    
    Args:
        store_id: ID of the vector store
        embeddings: List of embedding vectors
        metadata: Optional metadata for each embedding
        ids: Optional IDs for embeddings
        
    Returns:
        Dictionary with addition results
    """
    return await add_embeddings_to_store_from_parameters(
        store_id=store_id,
        embeddings=embeddings,
        metadata=metadata,
        ids=ids,
    )


async def search_vector_store_tool(
    store_id: str,
    query_vector: List[float],
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search vectors in a vector store.
    
    Args:
        store_id: ID of the vector store
        query_vector: Query vector for search
        top_k: Number of results to return
        filters: Optional filters for search
        
    Returns:
        Dictionary with search results
    """
    return await search_vector_store_from_parameters(
        store_id=store_id,
        query_vector=query_vector,
        top_k=top_k,
        filters=filters,
    )


async def get_vector_store_stats_tool(store_id: str) -> Dict[str, Any]:
    """
    Get statistics for a vector store.
    
    Args:
        store_id: ID of the vector store
        
    Returns:
        Dictionary with store statistics
    """
    return await get_vector_store_stats_from_parameters(store_id)


async def delete_from_vector_store_tool(
    store_id: str,
    ids: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Delete vectors from a vector store.
    
    Args:
        store_id: ID of the vector store
        ids: List of vector IDs to delete
        filters: Optional filters for bulk deletion
        
    Returns:
        Dictionary with deletion results
    """
    return await delete_from_vector_store_from_parameters(
        store_id=store_id,
        ids=ids,
        filters=filters,
    )


async def optimize_vector_store_tool(store_id: str) -> Dict[str, Any]:
    """
    Optimize a vector store for better performance.
    
    Args:
        store_id: ID of the vector store
        
    Returns:
        Dictionary with optimization results
    """
    return await optimize_vector_store_from_parameters(store_id)
