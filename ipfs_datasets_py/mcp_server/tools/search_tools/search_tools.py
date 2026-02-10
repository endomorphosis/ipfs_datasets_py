# src/mcp_server/tools/search_tools.py

import logging
from typing import Dict, Any, List, Optional, Union
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.mcp_server.validators import validator

from ipfs_datasets_py.search.search_tools_api import (
    faceted_search_from_parameters,
    semantic_search_from_parameters,
    similarity_search_from_parameters,
)

logger = logging.getLogger(__name__)

class SemanticSearchTool(ClaudeMCPTool):
    """
    Tool for performing semantic search on LAION embeddings.
    """
    
    def __init__(self, vector_service):
        super().__init__()
        if vector_service is None:
            raise ValueError("Vector service cannot be None")
            
        self.vector_service = vector_service
        self.name = "semantic_search"
        self.description = "Performs semantic search on LAION embeddings using vector similarity."
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string", 
                    "description": "The search query text.",
                    "minLength": 1,
                    "maxLength": 1000
                },
                "model": {
                    "type": "string", 
                    "description": "The embedding model to use for search.",
                    "default": "sentence-transformers/all-MiniLM-L6-v2"
                },
                "top_k": {
                    "type": "integer", 
                    "description": "Number of top results to return.",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 100
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name to search in.",
                    "default": "default"
                },
                "filters": {
                    "type": "object",
                    "description": "Optional metadata filters for search.",
                    "default": {}
                }
            },
            "required": ["query"]
        }
        self.category = "search"
        self.tags = ["semantic", "vector", "similarity"]
        self.vector_service = vector_service

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute semantic search on LAION embeddings.
        """
        try:
            # Validate parameters against the input schema
            validator.validate_json_schema(parameters, self.input_schema, "parameters")

            query = parameters["query"]
            model = parameters.get("model", "sentence-transformers/all-MiniLM-L6-v2")
            top_k = parameters.get("top_k", 5)
            collection = parameters.get("collection", "default")
            filters = parameters.get("filters", {})

            return await semantic_search_from_parameters(
                vector_service=self.vector_service,
                query=query,
                model=model,
                top_k=top_k,
                collection=collection,
                filters=filters,
            )
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            raise


class SimilaritySearchTool(ClaudeMCPTool):
    """
    Tool for finding similar embeddings based on a reference embedding.
    """
    
    def __init__(self, vector_service):
        super().__init__()
        if vector_service is None:
            raise ValueError("Vector service cannot be None")
            
        self.name = "similarity_search"
        self.description = "Finds similar embeddings based on a reference embedding vector."
        self.input_schema = {
            "type": "object",
            "properties": {
                "embedding": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Reference embedding vector for similarity search.",
                    "minItems": 1
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of similar embeddings to return.",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                },
                "threshold": {
                    "type": "number",
                    "description": "Minimum similarity threshold (0-1).",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name to search in.",
                    "default": "default"
                }
            },
            "required": ["embedding"]
        }
        self.category = "search"
        self.tags = ["similarity", "vector", "nearest_neighbors"]
        self.vector_service = vector_service

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute similarity search based on embedding vector.
        """
        try:
            # Validate parameters against the input schema
            validator.validate_json_schema(parameters, self.input_schema, "parameters")

            embedding = parameters["embedding"]
            top_k = parameters.get("top_k", 10)
            threshold = parameters.get("threshold", 0.5)
            collection = parameters.get("collection", "default")

            return await similarity_search_from_parameters(
                vector_service=self.vector_service,
                embedding=embedding,
                top_k=top_k,
                threshold=threshold,
                collection=collection,
            )
            
        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            raise


class FacetedSearchTool(ClaudeMCPTool):
    """
    Tool for performing faceted search with metadata filtering.
    """
    
    def __init__(self, vector_service):
        super().__init__()
        if vector_service is None:
            raise ValueError("Vector service cannot be None")
            
        self.name = "faceted_search"
        self.description = "Performs faceted search with metadata filters and aggregations."
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text.",
                    "default": ""
                },
                "facets": {
                    "type": "object",
                    "description": "Facet filters to apply.",
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "aggregations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to aggregate on.",
                    "default": []
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return.",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name to search in.",
                    "default": "default"
                }
            },
            "required": []
        }
        self.category = "search"
        self.tags = ["faceted", "filtering", "aggregation"]
        self.vector_service = vector_service

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute faceted search with filtering and aggregations.
        """
        try:
            # Validate parameters against the input schema
            validator.validate_json_schema(parameters, self.input_schema, "parameters")

            query = parameters.get("query", "")
            facets = parameters.get("facets", {})
            aggregations = parameters.get("aggregations", [])
            top_k = parameters.get("top_k", 20)
            collection = parameters.get("collection", "default")

            return await faceted_search_from_parameters(
                vector_service=self.vector_service,
                query=query,
                facets=facets,
                aggregations=aggregations,
                top_k=top_k,
                collection=collection,
            )
            
        except Exception as e:
            logger.error(f"Faceted search failed: {e}")
            raise
