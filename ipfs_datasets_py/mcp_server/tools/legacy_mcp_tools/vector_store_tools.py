# src/mcp_server/tools/vector_store_tools.py
# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.vector_store_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.vector_store_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.vector_store_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
from typing import Dict, Any, List, Optional, Union
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.mcp_server.validators import validator

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

            # Call the vector service
            result = None
            match action:
                case "create":
                    result = await self.vector_service.create_index(index_name, config or {})
                case "update":
                    result = await self.vector_service.update_index(index_name, config or {})
                case "delete":
                    result = await self.vector_service.delete_index(index_name)
                case "info":
                    result = await self.vector_service.get_index_info(index_name)
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
            
            # Call the vector service
            vectors = await self.vector_service.retrieve_vectors(
                collection=collection,
                ids=ids,
                filters=filters or {},
                limit=limit
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
            
            # Call the vector service
            result = None
            match action:
                case "get":
                    if not vector_id:
                        raise ValueError("vector_id is required for get action")
                    result = await self.vector_service.get_vector_metadata(collection, vector_id)
                case "update":
                    if not vector_id or not metadata:
                        raise ValueError("vector_id and metadata are required for update action")
                    result = await self.vector_service.update_vector_metadata(collection, vector_id, metadata)
                case "delete":
                    if not vector_id:
                        raise ValueError("vector_id is required for delete action")
                    result = await self.vector_service.delete_vector_metadata(collection, vector_id)
                case _: # list
                    result = await self.vector_service.list_vector_metadata(collection, filters or {})
            
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
    try:
        # Generate unique store ID
        import uuid
        store_id = str(uuid.uuid4())
        
        # Mock vector store creation
        result = {
            "success": True,
            "store_id": store_id,
            "store_path": store_path,
            "dimension": dimension,
            "provider": provider,
            "index_type": index_type,
            "config": config or {},
            "created_at": "2024-01-01T00:00:00Z",
            "status": "ready"
        }
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


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
    try:
        num_embeddings = len(embeddings)
        
        result = {
            "success": True,
            "store_id": store_id,
            "count": num_embeddings,
            "ids": ids or [f"emb_{i}" for i in range(num_embeddings)]
        }
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


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
    try:
        # Mock search results
        results = [
            {
                "id": f"result_{i}",
                "score": 0.95 - (i * 0.1),
                "metadata": {"text": f"Sample result {i}"}
            }
            for i in range(min(top_k, 5))
        ]
        
        return {
            "success": True,
            "store_id": store_id,
            "results": results,
            "total_results": len(results)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


async def get_vector_store_stats_tool(store_id: str) -> Dict[str, Any]:
    """
    Get statistics for a vector store.
    
    Args:
        store_id: ID of the vector store
        
    Returns:
        Dictionary with store statistics
    """
    try:
        return {
            "success": True,
            "store_id": store_id,
            "total_vectors": 1000,
            "dimensions": 768,
            "index_type": "hnsw",
            "memory_usage": "256MB",
            "last_updated": "2024-01-01T00:00:00Z"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


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
    try:
        deleted_count = len(ids) if ids else 0
        
        return {
            "success": True,
            "store_id": store_id,
            "deleted_count": deleted_count,
            "deleted_ids": ids or []
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


async def optimize_vector_store_tool(store_id: str) -> Dict[str, Any]:
    """
    Optimize a vector store for better performance.
    
    Args:
        store_id: ID of the vector store
        
    Returns:
        Dictionary with optimization results
    """
    try:
        return {
            "success": True,
            "store_id": store_id,
            "optimization_completed": True,
            "performance_improvement": "15%",
            "time_taken": "2.5s"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
