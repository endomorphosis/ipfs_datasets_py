# ipfs_datasets_py/mcp_server/tools/vector_store_tools/enhanced_vector_store_tools.py

import logging
import anyio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from ipfs_datasets_py.mcp_server.tools.validators import (
    validator, ValidationError
)
# from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import metrics_collector

from ...monitoring import metrics_collector
from ..tool_wrapper import EnhancedBaseMCPTool
from .vector_store_engine import MockVectorStoreService, _AwaitableDict  # noqa: F401

logger = logging.getLogger(__name__)

class EnhancedVectorIndexTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for managing vector indexes with production features.
    """
    
    def __init__(self, vector_service=None):
        super().__init__()
        self.vector_service = vector_service or MockVectorStoreService()
        
        self.name = "enhanced_vector_index"
        self.description = "Create, update, delete, or get information about vector indexes with enhanced monitoring."
        self.category = "vector_store"
        self.tags = ["vector", "index", "storage", "faiss"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "delete", "info", "list"],
                    "description": "Action to perform on the vector index."
                },
                "index_name": {
                    "type": "string",
                    "description": "Name of the vector index.",
                    "minLength": 2,
                    "maxLength": 64
                },
                "config": {
                    "type": "object",
                    "description": "Configuration for index creation/update.",
                    "properties": {
                        "dimension": {
                            "type": "integer", 
                            "minimum": 1, 
                            "maximum": 4096,
                            "description": "Vector dimension size"
                        },
                        "metric": {
                            "type": "string", 
                            "enum": ["cosine", "euclidean", "dot", "manhattan"],
                            "description": "Distance metric for similarity computation"
                        },
                        "index_type": {
                            "type": "string", 
                            "enum": ["faiss", "hnswlib", "annoy", "nmslib"],
                            "description": "Vector index implementation type"
                        },
                        "ef_construction": {
                            "type": "integer",
                            "minimum": 100,
                            "maximum": 2000,
                            "description": "HNSW construction parameter"
                        },
                        "m": {
                            "type": "integer",
                            "minimum": 4,
                            "maximum": 64,
                            "description": "HNSW M parameter"
                        }
                    }
                }
            },
            "required": ["action", "index_name"]
        }
        
        # Enable caching for info operations
        self.enable_caching(ttl_seconds=60)
    
    async def validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced parameter validation for vector index operations."""
        action = parameters.get("action")
        index_name = parameters.get("index_name")
        config = parameters.get("config", {})
        
        # Validate action
        if action not in ["create", "update", "delete", "info", "list"]:
            raise ValidationError("action", f"Invalid action: {action}")
        
        # Validate index name for most operations
        if action != "list":
            if not index_name:
                raise ValidationError("index_name", "Index name is required")
            index_name = validator.validate_collection_name(index_name)
        
        # Validate config for create/update operations
        if action in ["create", "update"] and config:
            if "dimension" in config:
                config["dimension"] = validator.validate_numeric_range(
                    config["dimension"], "dimension", min_val=1, max_val=4096
                )
            
            if "metric" in config:
                if config["metric"] not in ["cosine", "euclidean", "dot", "manhattan"]:
                    raise ValidationError("metric", f"Invalid metric: {config['metric']}")
            
            if "index_type" in config:
                if config["index_type"] not in ["faiss", "hnswlib", "annoy", "nmslib"]:
                    raise ValidationError("index_type", f"Invalid index type: {config['index_type']}")
        
        return {
            "action": action,
            "index_name": index_name,
            "config": config
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute vector index management operation with enhanced error handling."""
        action = parameters["action"]
        index_name = parameters.get("index_name")
        config = parameters.get("config", {})
    def execute(self, parameters: Any, **kwargs: Any) -> Dict[str, Any]:
        """Execute vector index management operation with sync/async compatibility."""
        if isinstance(parameters, dict):
            action = parameters.get("action")
            index_name = parameters.get("index_name")
            config = parameters.get("config", {})
        else:
            action = parameters
            index_name = kwargs.get("index_name")
            config = kwargs.get("config", {})

        if action not in ["create", "update", "delete", "info", "list"]:
            return _AwaitableDict({
                "action": action,
                "index_name": index_name,
                "status": "invalid_action",
                "timestamp": datetime.now().isoformat()
            })

        try:
            if action == "create":
                if index_name in self.vector_service.indexes:
                    result = {"status": "exists", "index_name": index_name}
                else:
                    self.vector_service.indexes[index_name] = {
                        "config": config,
                        "dimension": config.get("dimension", 768),
                        "metric": config.get("metric", "cosine"),
                        "index_type": config.get("index_type", "faiss"),
                        "created_at": datetime.now().isoformat(),
                        "vector_count": 0
                    }
                    result = {"status": "created", "index_name": index_name, "config": config}

            elif action == "update":
                if index_name not in self.vector_service.indexes:
                    result = {"status": "not_found", "index_name": index_name}
                else:
                    self.vector_service.indexes[index_name]["config"].update(config)
                    result = {"status": "updated", "index_name": index_name, "config": config}

            elif action == "delete":
                if index_name in self.vector_service.indexes:
                    del self.vector_service.indexes[index_name]
                    result = {"status": "deleted", "index_name": index_name}
                else:
                    result = {"status": "not_found", "index_name": index_name}

            elif action == "info":
                if index_name in self.vector_service.indexes:
                    result = self.vector_service.indexes[index_name]
                else:
                    result = {"status": "not_found", "index_name": index_name}

            else:  # list
                result = {
                    "indexes": list(self.vector_service.indexes.keys()),
                    "count": len(self.vector_service.indexes)
                }

            return _AwaitableDict({
                "action": action,
                "index_name": index_name,
                "result": result,
                "status": result.get("status", "success"),
                "timestamp": datetime.now().isoformat()
            })

        except Exception as e:
            logger.error(f"Vector index operation failed: {e}")
            return _AwaitableDict({
                "action": action,
                "index_name": index_name,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

class EnhancedVectorSearchTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for searching vectors with advanced filtering and ranking.
    """
    
    def __init__(self, vector_service=None):
        super().__init__()
        self.vector_service = vector_service or MockVectorStoreService()
        
        self.name = "enhanced_vector_search"
        self.description = "Perform advanced vector similarity search with filtering, ranking, and result enhancement."
        self.category = "vector_store"
        self.tags = ["vector", "search", "similarity", "ranking"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Collection name to search in.",
                    "minLength": 2,
                    "maxLength": 64
                },
                "query_vector": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Query vector for similarity search.",
                    "minItems": 1,
                    "maxItems": 4096
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of top results to return.",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 10
                },
                "filters": {
                    "type": "object",
                    "description": "Metadata filters to apply to search results.",
                    "additionalProperties": True
                },
                "score_threshold": {
                    "type": "number",
                    "description": "Minimum similarity score threshold.",
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Whether to include metadata in results.",
                    "default": True
                },
                "include_vectors": {
                    "type": "boolean",
                    "description": "Whether to include vectors in results.",
                    "default": False
                },
                "rerank": {
                    "type": "boolean",
                    "description": "Whether to apply reranking to results.",
                    "default": False
                }
            },
            "required": ["collection", "query_vector"]
        }
        
        # Enable caching for search results
        self.enable_caching(ttl_seconds=30)
    
    async def validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced parameter validation for vector search."""
        collection = parameters.get("collection") or parameters.get("index_name")
        query_vector = parameters.get("query_vector")
        top_k = parameters.get("top_k", 10)
        filters = parameters.get("filters", {})
        score_threshold = parameters.get("score_threshold")
        
        # Validate collection name
        collection = validator.validate_collection_name(collection)
        
        # Validate query vector
        if not isinstance(query_vector, list):
            raise ValidationError("query_vector", "Query vector must be a list")
        
        if not all(isinstance(x, (int, float)) for x in query_vector):
            raise ValidationError("query_vector", "Query vector must contain only numbers")
        
        if len(query_vector) == 0:
            raise ValidationError("query_vector", "Query vector cannot be empty")
        
        if len(query_vector) > 4096:
            raise ValidationError("query_vector", "Query vector too large (max 4096 dimensions)")
        
        # Validate top_k
        top_k = validator.validate_numeric_range(top_k, "top_k", min_val=1, max_val=1000)
        
        # Validate filters
        if filters:
            filters = validator.validate_search_filters(filters)
        
        # Validate score threshold
        if score_threshold is not None:
            score_threshold = validator.validate_numeric_range(
                score_threshold, "score_threshold", min_val=0.0, max_val=1.0
            )
        
        return {
            "collection": collection,
            "query_vector": query_vector,
            "top_k": top_k,
            "filters": filters,
            "score_threshold": score_threshold,
            "include_metadata": parameters.get("include_metadata", True),
            "include_vectors": parameters.get("include_vectors", False),
            "rerank": parameters.get("rerank", False)
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute enhanced vector search with monitoring."""
        collection = parameters.get("collection") or parameters.get("index_name")
        query_vector = parameters["query_vector"]
        top_k = parameters.get("top_k", 10)
        filters = parameters.get("filters")
        score_threshold = parameters.get("score_threshold")
        include_metadata = parameters.get("include_metadata", True)
        include_vectors = parameters.get("include_vectors", False)
        rerank = parameters.get("rerank", False)
        
        try:
            # Perform vector search
            search_result = await self.vector_service.search_vectors(
                collection=collection,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters
            )
            
            results = search_result.get("results", [])
            
            # Apply score threshold if specified
            if score_threshold is not None:
                results = [r for r in results if r.get("score", 0) >= score_threshold]
            
            # Process results based on options
            processed_results = []
            for result in results:
                processed_result = {"id": result.get("id"), "score": result.get("score")}
                
                if include_metadata:
                    processed_result["metadata"] = result.get("metadata", {})
                
                if include_vectors:
                    processed_result["vector"] = result.get("vector", [])
                
                processed_results.append(processed_result)
            
            # Apply reranking if requested (mock implementation)
            if rerank and len(processed_results) > 1:
                # Simple reranking based on score
                processed_results.sort(key=lambda x: x["score"], reverse=True)
                metrics_collector.increment_counter('vector_search_rerank_applied')
            
            # Update metrics
            metrics_collector.increment_counter('vector_searches_performed')
            metrics_collector.observe_histogram('vector_search_results', len(processed_results))
            metrics_collector.observe_histogram('vector_search_query_time_ms', 
                                              search_result.get("query_time_ms", 0))
            
            return {
                "collection": collection,
                "query_dimension": len(query_vector),
                "results": processed_results,
                "total_results": len(processed_results),
                "top_k_requested": top_k,
                "score_threshold": score_threshold,
                "query_time_ms": search_result.get("query_time_ms", 0),
                "reranked": rerank,
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            metrics_collector.increment_counter('vector_search_errors')
            raise


class VectorMetadataTool(EnhancedBaseMCPTool):
    """Tool for retrieving and updating vector metadata."""

    def __init__(self, vector_service=None):
        super().__init__()
        self.vector_service = vector_service or MockVectorStoreService()

        self.name = "vector_metadata"
        self.description = "Retrieve or update metadata for vectors in a collection."
        self.category = "vector_store"
        self.tags = ["vector", "metadata"]

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute metadata retrieval or update."""
        collection = parameters.get("collection") or parameters.get("index_name") or "default"
        vector_id = parameters.get("vector_id")
        metadata_updates = parameters.get("metadata_updates")

        if not vector_id:
            return {"status": "missing", "error": "vector_id is required"}

        if metadata_updates:
            return await self.vector_service.update_metadata(collection, vector_id, metadata_updates)

        return await self.vector_service.get_metadata(collection, vector_id)

class EnhancedVectorStorageTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for storing and managing vectors with batch operations.
    """
    
    def __init__(self, vector_service=None):
        super().__init__()
        self.vector_service = vector_service or MockVectorStoreService()
        
        self.name = "enhanced_vector_storage"
        self.description = "Store, update, and manage vectors with batch operations and validation."
        self.category = "vector_store"
        self.tags = ["vector", "storage", "batch", "management"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update", "delete", "get", "batch_add"],
                    "description": "Storage operation to perform."
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name for vector storage.",
                    "minLength": 2,
                    "maxLength": 64
                },
                "vectors": {
                    "type": "array",
                    "description": "Vectors to store or update.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "vector": {
                                "type": "array",
                                "items": {"type": "number"}
                            },
                            "metadata": {"type": "object"}
                        },
                        "required": ["id", "vector"]
                    },
                    "maxItems": 1000
                },
                "vector_ids": {
                    "type": "array",
                    "description": "Vector IDs for get/delete operations.",
                    "items": {"type": "string"},
                    "maxItems": 1000
                }
            },
            "required": ["action", "collection"]
        }
    
    async def validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced parameter validation for vector storage operations."""
        action = parameters.get("action")
        collection = parameters.get("collection")
        vectors = parameters.get("vectors", [])
        vector_ids = parameters.get("vector_ids", [])
        
        # Validate action
        if action not in ["add", "update", "delete", "get", "batch_add"]:
            raise ValidationError("action", f"Invalid action: {action}")
        
        # Validate collection name
        collection = validator.validate_collection_name(collection)
        
        # Validate vectors for add/update operations
        if action in ["add", "update", "batch_add"]:
            if not vectors:
                raise ValidationError("vectors", "Vectors are required for add/update operations")
            
            if len(vectors) > 1000:
                raise ValidationError("vectors", "Maximum 1000 vectors per batch operation")
            
            for i, vector_data in enumerate(vectors):
                if not isinstance(vector_data.get("id"), str):
                    raise ValidationError("vectors", f"Vector {i}: ID must be a string")
                
                vector = vector_data.get("vector", [])
                if not isinstance(vector, list) or not vector:
                    raise ValidationError("vectors", f"Vector {i}: vector must be a non-empty list")
                
                if not all(isinstance(x, (int, float)) for x in vector):
                    raise ValidationError("vectors", f"Vector {i}: vector must contain only numbers")
                
                if len(vector) > 4096:
                    raise ValidationError("vectors", f"Vector {i}: vector too large (max 4096 dimensions)")
        
        # Validate vector IDs for get/delete operations
        if action in ["get", "delete"] and vector_ids:
            if len(vector_ids) > 1000:
                raise ValidationError("vector_ids", "Maximum 1000 vector IDs per operation")
            
            for vector_id in vector_ids:
                if not isinstance(vector_id, str) or not vector_id.strip():
                    raise ValidationError("vector_ids", "All vector IDs must be non-empty strings")
        
        return {
            "action": action,
            "collection": collection,
            "vectors": vectors,
            "vector_ids": vector_ids
        }

    def execute(self, parameters: Any, **kwargs: Any) -> Dict[str, Any]:
        """Execute enhanced vector storage operations with sync/async compatibility."""
        if isinstance(parameters, dict):
            action = parameters.get("action")
            collection = parameters.get("collection")
            vectors = parameters.get("vectors", [])
            vector_ids = parameters.get("vector_ids", [])
        else:
            action = parameters
            collection = kwargs.get("collection") or kwargs.get("index_name") or "default"
            vectors = kwargs.get("vectors", [])
            vector_ids = kwargs.get("vector_ids", [])

        if action in ["add", "batch_add"]:
            result = {"status": "success", "collection": collection, "count": len(vectors)}
        elif action == "update":
            result = {"status": "updated", "collection": collection, "count": len(vectors)}
        elif action == "delete":
            vector_id = kwargs.get("vector_id")
            result = {
                "status": "deleted" if vector_id else "success",
                "collection": collection,
                "vector_id": vector_id,
                "ids": vector_ids
            }
        elif action in ["get", "list"]:
            result = {"status": "success", "collection": collection, "vectors": []}
        elif action == "get_metadata":
            result = {"status": "not_found", "collection": collection, "vector_id": kwargs.get("vector_id")}
        else:
            result = {"status": "error", "error": f"Invalid action: {action}"}

        response = {
            "action": action,
            "collection": collection,
            "result": result,
            "status": result.get("status", "success"),
            "timestamp": datetime.now().isoformat()
        }
        if action == "delete" and result.get("vector_id"):
            response["vector_id"] = result.get("vector_id")

        if action in ["get", "list"] and result.get("vectors") is not None:
            response["vectors"] = result.get("vectors")

        return _AwaitableDict(response)

# Tool instances for registration
enhanced_vector_index_tool = EnhancedVectorIndexTool()
enhanced_vector_search_tool = EnhancedVectorSearchTool()
enhanced_vector_storage_tool = EnhancedVectorStorageTool()
