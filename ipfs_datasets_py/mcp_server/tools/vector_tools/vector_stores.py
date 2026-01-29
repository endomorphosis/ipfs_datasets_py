"""
Vector Stores MCP Wrapper

This module provides MCP tool interfaces for vector store management.
The core implementation is in ipfs_datasets_py.vector_stores

All business logic should reside in the core module, and this file serves
as a thin wrapper to expose that functionality through the MCP interface.
"""

from typing import Dict, Any, List, Optional
import anyio
import logging

# Import from core vector_stores module
from ipfs_datasets_py.vector_stores import (
    BaseVectorStore,
    QdrantVectorStore,
    FAISSVectorStore,
    ElasticsearchVectorStore
)

logger = logging.getLogger(__name__)

# Store registry for managing vector store instances
_store_registry: Dict[str, BaseVectorStore] = {}


def _get_or_create_store(store_type: str, **kwargs) -> BaseVectorStore:
    """Get or create a vector store instance.
    
    Args:
        store_type: Type of vector store (qdrant, faiss, elasticsearch)
        **kwargs: Store-specific configuration parameters
        
    Returns:
        Vector store instance
    """
    store_key = f"{store_type}_{hash(str(kwargs))}"
    
    if store_key not in _store_registry:
        if store_type == "qdrant":
            _store_registry[store_key] = QdrantVectorStore(**kwargs)
        elif store_type == "faiss":
            _store_registry[store_key] = FAISSVectorStore(**kwargs)
        elif store_type == "elasticsearch":
            if ElasticsearchVectorStore is None:
                raise ImportError("Elasticsearch dependencies not available")
            _store_registry[store_key] = ElasticsearchVectorStore(**kwargs)
        else:
            raise ValueError(f"Unknown store type: {store_type}")
    
    return _store_registry[store_key]


async def manage_vector_store(
    operation: str,
    store_type: str = "faiss",  # Default to faiss as it's lightweight
    collection_name: str = "default",
    **kwargs
) -> Dict[str, Any]:
    """
    Tool for managing vector stores including creation, indexing, and querying.
    
    This is a thin wrapper around the core vector store implementations.
    
    Args:
        operation: Operation to perform (create, index, query, delete)
        store_type: Type of vector store (qdrant, elasticsearch, faiss)
        collection_name: Name of the collection/index
        **kwargs: Additional parameters specific to the operation
            - For index: vectors (List), ids (List), metadata (List)
            - For query: query_vector (List), top_k (int)
            - For delete: ids (List)
    
    Returns:
        Dict containing operation results
    """
    try:
        logger.info(f"Vector store operation: {operation} on {store_type}")
        
        # Get or create the vector store instance
        store = _get_or_create_store(store_type, collection_name=collection_name)
        
        if operation == "create":
            # Store is already created/initialized
            return {
                "status": "success",
                "operation": "create",
                "store_type": store_type,
                "collection_name": collection_name,
                "message": f"Created {store_type} vector store for collection '{collection_name}'"
            }
            
        elif operation == "index":
            vectors = kwargs.get("vectors", [])
            ids = kwargs.get("ids")
            metadata = kwargs.get("metadata")
            
            if not vectors:
                return {
                    "status": "error",
                    "message": "vectors required for index operation"
                }
            
            # Add vectors to the store using core functionality
            store.add(vectors=vectors, ids=ids, metadata=metadata)
            
            return {
                "status": "success",
                "operation": "index",
                "store_type": store_type,
                "collection_name": collection_name,
                "indexed_count": len(vectors),
                "message": f"Indexed {len(vectors)} vectors in {store_type}"
            }
            
        elif operation == "query":
            query_vector = kwargs.get("query_vector")
            top_k = kwargs.get("top_k", 5)
            
            if not query_vector:
                return {
                    "status": "error",
                    "message": "query_vector required for query operation"
                }
            
            # Search using core functionality
            results = store.search(query_vector=query_vector, top_k=top_k)
            
            return {
                "status": "success",
                "operation": "query",
                "store_type": store_type,
                "collection_name": collection_name,
                "results": results,
                "results_count": len(results),
                "message": f"Query executed on {store_type} store"
            }
            
        elif operation == "delete":
            ids = kwargs.get("ids")
            
            if ids:
                # Delete specific IDs
                store.delete(ids=ids)
                return {
                    "status": "success",
                    "operation": "delete",
                    "store_type": store_type,
                    "collection_name": collection_name,
                    "deleted_count": len(ids),
                    "message": f"Deleted {len(ids)} vectors from {store_type}"
                }
            else:
                # Clear entire collection
                store.clear()
                return {
                    "status": "success",
                    "operation": "delete",
                    "store_type": store_type,
                    "collection_name": collection_name,
                    "message": f"Cleared {store_type} vector store collection '{collection_name}'"
                }
                
        else:
            return {
                "status": "error",
                "message": f"Unknown operation: {operation}. Valid operations: create, index, query, delete"
            }
            
    except Exception as e:
        logger.error(f"Vector store management error: {e}")
        return {
            "status": "error",
            "operation": operation,
            "store_type": store_type,
            "message": str(e)
        }


async def optimize_vector_store(
    store_type: str = "faiss",
    collection_name: str = "default",
    optimization_type: str = "index"
) -> Dict[str, Any]:
    """
    Optimize vector store performance.
    
    This is a thin wrapper around core vector store optimization methods.
    
    Args:
        store_type: Type of vector store to optimize
        collection_name: Name of the collection
        optimization_type: Type of optimization (index, memory, disk)
    
    Returns:
        Dict containing optimization results
    """
    try:
        logger.info(f"Optimizing {store_type} vector store")
        
        # Get the store instance
        store = _get_or_create_store(store_type, collection_name=collection_name)
        
        # Call optimization method if available
        if hasattr(store, 'optimize'):
            store.optimize()
            message = f"Optimized {store_type} store ({optimization_type})"
        else:
            message = f"{store_type} store does not support optimization"
        
        return {
            "status": "success",
            "store_type": store_type,
            "collection_name": collection_name,
            "optimization_type": optimization_type,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"Vector store optimization error: {e}")
        return {
            "status": "error",
            "store_type": store_type,
            "message": str(e)
        }

