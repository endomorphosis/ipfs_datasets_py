"""
MCP Tool Registration for Enhanced Embeddings Tools

Registers all the new embedding tools from the embeddings integration
with the MCP server for discovery and execution.
"""

from typing import Dict, Any, List
import logging

# Import the new embedding tool functions
try:
    from .advanced_embedding_generation import (
        generate_embedding, 
        generate_batch_embeddings, 
        generate_embeddings_from_file
    )
    HAVE_ADVANCED_EMBEDDINGS = True
except ImportError as e:
    logging.warning(f"Advanced embeddings not available: {e}")
    HAVE_ADVANCED_EMBEDDINGS = False

try:
    from .shard_embeddings import (
        shard_embeddings_by_dimension,
        shard_embeddings_by_cluster, 
        merge_embedding_shards
    )
    HAVE_SHARD_EMBEDDINGS = True
except ImportError as e:
    logging.warning(f"Shard embeddings not available: {e}")
    HAVE_SHARD_EMBEDDINGS = False

try:
    from .advanced_search import (
        semantic_search,
        multi_modal_search,
        hybrid_search,
        search_with_filters
    )
    HAVE_ADVANCED_SEARCH = True
except ImportError as e:
    logging.warning(f"Advanced search not available: {e}")
    HAVE_ADVANCED_SEARCH = False

logger = logging.getLogger(__name__)


def register_enhanced_embedding_tools() -> List[Dict[str, Any]]:
    """
    Register all enhanced embedding tools with the MCP server.
    
    Returns:
        List of tool definitions for MCP registration
    """
    tools = []
    
    if HAVE_ADVANCED_EMBEDDINGS:
        # Advanced Embedding Generation Tools
        tools.extend([
            {
                "name": "generate_embedding",
                "description": "Generate a single embedding for text using advanced models with IPFS integration",
                "function": generate_embedding,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to generate embedding for",
                            "maxLength": 10000
                        },
                        "model_name": {
                            "type": "string", 
                            "description": "Name of the embedding model to use",
                            "default": "sentence-transformers/all-MiniLM-L6-v2"
                        },
                        "normalize": {
                            "type": "boolean",
                            "description": "Whether to normalize the embedding vector",
                            "default": True
                        },
                        "batch_size": {
                            "type": "integer",
                            "description": "Batch size for processing",
                            "default": 32,
                            "minimum": 1,
                            "maximum": 256
                        },
                        "use_gpu": {
                            "type": "boolean", 
                            "description": "Whether to use GPU acceleration",
                            "default": False
                        }
                    },
                    "required": ["text"]
                },
                "category": "embeddings",
                "tags": ["ai", "ml", "nlp", "vectors", "ipfs"]
            },
            {
                "name": "generate_batch_embeddings",
                "description": "Generate embeddings for multiple texts in an optimized batch operation",
                "function": generate_batch_embeddings,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "texts": {
                            "type": "array",
                            "items": {"type": "string", "maxLength": 10000},
                            "description": "List of texts to generate embeddings for",
                            "minItems": 1,
                            "maxItems": 100
                        },
                        "model_name": {
                            "type": "string",
                            "description": "Name of the embedding model to use",
                            "default": "sentence-transformers/all-MiniLM-L6-v2"
                        },
                        "normalize": {
                            "type": "boolean",
                            "description": "Whether to normalize embedding vectors",
                            "default": True
                        },
                        "batch_size": {
                            "type": "integer",
                            "description": "Batch size for processing",
                            "default": 32,
                            "minimum": 1,
                            "maximum": 256
                        },
                        "use_gpu": {
                            "type": "boolean",
                            "description": "Whether to use GPU acceleration", 
                            "default": False
                        },
                        "max_texts": {
                            "type": "integer",
                            "description": "Maximum number of texts to process",
                            "default": 100,
                            "minimum": 1,
                            "maximum": 1000
                        }
                    },
                    "required": ["texts"]
                },
                "category": "embeddings",
                "tags": ["ai", "ml", "nlp", "vectors", "batch", "ipfs"]
            },
            {
                "name": "generate_embeddings_from_file",
                "description": "Generate embeddings from a text file with chunking and batch processing",
                "function": generate_embeddings_from_file,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to input text file"
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Path to save embeddings (optional)"
                        },
                        "model_name": {
                            "type": "string",
                            "description": "Name of the embedding model to use",
                            "default": "sentence-transformers/all-MiniLM-L6-v2"
                        },
                        "batch_size": {
                            "type": "integer",
                            "description": "Batch size for processing",
                            "default": 32,
                            "minimum": 1
                        },
                        "chunk_size": {
                            "type": "integer",
                            "description": "Size of text chunks (optional)"
                        },
                        "max_length": {
                            "type": "integer",
                            "description": "Maximum text length per chunk"
                        },
                        "output_format": {
                            "type": "string",
                            "description": "Output format",
                            "enum": ["json", "parquet", "hdf5"],
                            "default": "json"
                        }
                    },
                    "required": ["file_path"]
                },
                "category": "embeddings",
                "tags": ["ai", "ml", "nlp", "files", "batch", "ipfs"]
            }
        ])
    
    if HAVE_SHARD_EMBEDDINGS:
        # Embedding Sharding Tools
        tools.extend([
            {
                "name": "shard_embeddings_by_dimension", 
                "description": "Shard embeddings by splitting high-dimensional vectors into smaller chunks",
                "function": shard_embeddings_by_dimension,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "embeddings_data": {
                            "oneOf": [
                                {"type": "string", "description": "Path to embeddings file"},
                                {"type": "array", "description": "List of embedding dictionaries"}
                            ],
                            "description": "Embeddings data source"
                        },
                        "output_directory": {
                            "type": "string",
                            "description": "Directory to save sharded embeddings"
                        },
                        "shard_size": {
                            "type": "integer",
                            "description": "Maximum number of embeddings per shard",
                            "default": 1000,
                            "minimum": 1
                        },
                        "dimension_chunks": {
                            "type": "integer",
                            "description": "Number of dimensions per chunk (for dimension-based sharding)"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Additional metadata to include"
                        }
                    },
                    "required": ["embeddings_data", "output_directory"]
                },
                "category": "embeddings",
                "tags": ["vectors", "sharding", "optimization", "storage", "ipfs"]
            },
            {
                "name": "shard_embeddings_by_cluster",
                "description": "Shard embeddings by clustering similar vectors together",
                "function": shard_embeddings_by_cluster,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "embeddings_data": {
                            "oneOf": [
                                {"type": "string", "description": "Path to embeddings file"},
                                {"type": "array", "description": "List of embedding dictionaries"}
                            ]
                        },
                        "output_directory": {
                            "type": "string",
                            "description": "Directory to save sharded embeddings"
                        },
                        "num_clusters": {
                            "type": "integer",
                            "description": "Number of clusters to create",
                            "default": 10,
                            "minimum": 2,
                            "maximum": 1000
                        },
                        "clustering_method": {
                            "type": "string",
                            "description": "Clustering algorithm to use",
                            "enum": ["kmeans", "hierarchical"],
                            "default": "kmeans"
                        },
                        "shard_size": {
                            "type": "integer",
                            "description": "Maximum number of embeddings per shard within each cluster",
                            "default": 1000,
                            "minimum": 1
                        }
                    },
                    "required": ["embeddings_data", "output_directory"]
                },
                "category": "embeddings",
                "tags": ["vectors", "clustering", "sharding", "ml", "ipfs"]
            },
            {
                "name": "merge_embedding_shards",
                "description": "Merge previously sharded embeddings back into a single file",
                "function": merge_embedding_shards,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "manifest_file": {
                            "type": "string",
                            "description": "Path to the sharding manifest file"
                        },
                        "output_file": {
                            "type": "string",
                            "description": "Path for the merged output file"
                        },
                        "merge_strategy": {
                            "type": "string",
                            "description": "Strategy for merging",
                            "enum": ["sequential", "clustered"],
                            "default": "sequential"
                        }
                    },
                    "required": ["manifest_file", "output_file"]
                },
                "category": "embeddings",
                "tags": ["vectors", "merging", "reconstruction", "ipfs"]
            }
        ])
    
    if HAVE_ADVANCED_SEARCH:
        # Advanced Search Tools
        tools.extend([
            {
                "name": "semantic_search",
                "description": "Perform semantic search using embedding similarity with IPFS integration",
                "function": semantic_search,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query text",
                            "minLength": 1
                        },
                        "vector_store_id": {
                            "type": "string",
                            "description": "ID of the vector store to search"
                        },
                        "model_name": {
                            "type": "string",
                            "description": "Embedding model to use for query encoding",
                            "default": "sentence-transformers/all-MiniLM-L6-v2"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 1000
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "description": "Minimum similarity score for results",
                            "default": 0.7,
                            "minimum": 0.0,
                            "maximum": 1.0
                        },
                        "include_metadata": {
                            "type": "boolean",
                            "description": "Whether to include document metadata",
                            "default": True
                        }
                    },
                    "required": ["query", "vector_store_id"]
                },
                "category": "search",
                "tags": ["semantic", "similarity", "vectors", "ai", "ipfs"]
            },
            {
                "name": "multi_modal_search",
                "description": "Perform multi-modal search combining text and image queries",
                "function": multi_modal_search,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text query (optional)"
                        },
                        "image_query": {
                            "type": "string",
                            "description": "Image query path or URL (optional)"
                        },
                        "vector_store_id": {
                            "type": "string",
                            "description": "ID of the vector store to search"
                        },
                        "model_name": {
                            "type": "string",
                            "description": "Multi-modal model to use",
                            "default": "clip-ViT-B-32"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 1000
                        },
                        "modality_weights": {
                            "type": "object",
                            "description": "Weights for different modalities",
                            "properties": {
                                "text": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                "image": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                            }
                        }
                    },
                    "required": ["vector_store_id"]
                },
                "category": "search",
                "tags": ["multimodal", "vision", "text", "ai", "ipfs"]
            },
            {
                "name": "hybrid_search",
                "description": "Perform hybrid search combining lexical and semantic search methods",
                "function": hybrid_search,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query text",
                            "minLength": 1
                        },
                        "vector_store_id": {
                            "type": "string",
                            "description": "ID of the vector store to search"
                        },
                        "lexical_weight": {
                            "type": "number",
                            "description": "Weight for lexical/keyword search component",
                            "default": 0.3,
                            "minimum": 0.0,
                            "maximum": 1.0
                        },
                        "semantic_weight": {
                            "type": "number", 
                            "description": "Weight for semantic/embedding search component",
                            "default": 0.7,
                            "minimum": 0.0,
                            "maximum": 1.0
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 1000
                        },
                        "rerank_results": {
                            "type": "boolean",
                            "description": "Whether to apply reranking to final results",
                            "default": True
                        }
                    },
                    "required": ["query", "vector_store_id"]
                },
                "category": "search",
                "tags": ["hybrid", "lexical", "semantic", "ranking", "ipfs"]
            },
            {
                "name": "search_with_filters",
                "description": "Perform filtered search with metadata and content constraints",
                "function": search_with_filters,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query text",
                            "minLength": 1
                        },
                        "vector_store_id": {
                            "type": "string",
                            "description": "ID of the vector store to search"
                        },
                        "filters": {
                            "type": "object",
                            "description": "Metadata filters to apply"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 1000
                        },
                        "search_method": {
                            "type": "string",
                            "description": "Search method to use",
                            "enum": ["semantic", "lexical", "hybrid"],
                            "default": "semantic"
                        }
                    },
                    "required": ["query", "vector_store_id", "filters"]
                },
                "category": "search",
                "tags": ["filtered", "metadata", "constrained", "ipfs"]
            }
        ])
    
    logger.info(f"Registered {len(tools)} enhanced embedding tools")
    return tools


def get_tool_manifest() -> Dict[str, Any]:
    """
    Get a manifest of all available enhanced embedding tools.
    
    Returns:
        Dict containing tool manifest information
    """
    tools = register_enhanced_embedding_tools()
    
    categories = {}
    for tool in tools:
        category = tool.get('category', 'general')
        if category not in categories:
            categories[category] = []
        categories[category].append(tool['name'])
    
    return {
        "name": "Enhanced IPFS Embeddings Tools",
        "version": "1.0.0",
        "description": "Advanced embedding generation, sharding, and search tools integrated into ipfs_datasets_py",
        "total_tools": len(tools),
        "categories": categories,
        "capabilities": {
            "advanced_embeddings": HAVE_ADVANCED_EMBEDDINGS,
            "shard_embeddings": HAVE_SHARD_EMBEDDINGS,
            "advanced_search": HAVE_ADVANCED_SEARCH
        },
        "integration_status": {
            "phase": "Phase 3 - MCP Tool Integration",
            "completion": "70%",
            "next_steps": [
                "Complete vector store integrations",
                "Add FastAPI endpoints",
                "Implement authentication",
                "Add monitoring and metrics"
            ]
        }
    }


# Export registration functions
__all__ = [
    'register_enhanced_embedding_tools',
    'get_tool_manifest'
]
