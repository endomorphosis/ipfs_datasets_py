# ipfs_datasets_py/mcp_server/tools/vector_store_tools/list_indices.py
"""
List vector indices tool for vector store management.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

async def list_indices(
    store_type: Optional[str] = None,
    include_stats: bool = False,
    namespace: Optional[str] = None
) -> Dict[str, Any]:
    """
    List all vector indices across different vector stores.
    
    Args:
        store_type: Filter by store type (faiss, qdrant, elasticsearch, chromadb)
        include_stats: Include statistics for each index
        namespace: Filter by namespace
        
    Returns:
        Dict containing list of indices and their metadata
    """
    try:
        # Mock vector indices data - replace with actual vector store integrations
        mock_indices = [
            {
                "index_id": "idx_embeddings_001",
                "name": "document_embeddings",
                "store_type": "faiss",
                "dimension": 768,
                "metric": "cosine",
                "vector_count": 15420,
                "namespace": "documents",
                "created_at": "2025-06-15T10:30:00Z",
                "last_updated": "2025-07-02T08:15:00Z",
                "status": "active",
                "size_mb": 45.2,
                "metadata": {
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "source": "pdf_documents",
                    "chunk_size": 512
                }
            },
            {
                "index_id": "idx_embeddings_002", 
                "name": "knowledge_graph_embeddings",
                "store_type": "qdrant",
                "dimension": 1024,
                "metric": "euclidean",
                "vector_count": 8730,
                "namespace": "knowledge_graphs",
                "created_at": "2025-06-20T14:45:00Z",
                "last_updated": "2025-07-01T16:20:00Z",
                "status": "active",
                "size_mb": 67.8,
                "metadata": {
                    "model": "text-embedding-ada-002",
                    "source": "entity_relationships",
                    "chunk_size": 1024
                }
            },
            {
                "index_id": "idx_embeddings_003",
                "name": "search_embeddings",
                "store_type": "elasticsearch",
                "dimension": 512,
                "metric": "cosine",
                "vector_count": 25600,
                "namespace": "search",
                "created_at": "2025-06-25T09:15:00Z",
                "last_updated": "2025-07-02T12:30:00Z",
                "status": "indexing",
                "size_mb": 89.1,
                "metadata": {
                    "model": "all-mpnet-base-v2",
                    "source": "web_archive",
                    "chunk_size": 256
                }
            },
            {
                "index_id": "idx_embeddings_004",
                "name": "experimental_embeddings",
                "store_type": "chromadb",
                "dimension": 384,
                "metric": "cosine",
                "vector_count": 3200,
                "namespace": "experiments",
                "created_at": "2025-07-01T11:00:00Z",
                "last_updated": "2025-07-02T09:45:00Z",
                "status": "active",
                "size_mb": 12.4,
                "metadata": {
                    "model": "all-MiniLM-L12-v2",
                    "source": "test_data",
                    "chunk_size": 128
                }
            }
        ]
        
        # Apply filters
        filtered_indices = mock_indices
        
        if store_type:
            filtered_indices = [idx for idx in filtered_indices if idx["store_type"] == store_type]
            
        if namespace:
            filtered_indices = [idx for idx in filtered_indices if idx["namespace"] == namespace]
            
        # Add statistics if requested
        if include_stats:
            total_vectors = sum(idx["vector_count"] for idx in filtered_indices)
            total_size_mb = sum(idx["size_mb"] for idx in filtered_indices)
            store_type_counts = {}
            status_counts = {}
            
            for idx in filtered_indices:
                store_type_counts[idx["store_type"]] = store_type_counts.get(idx["store_type"], 0) + 1
                status_counts[idx["status"]] = status_counts.get(idx["status"], 0) + 1
                
            stats = {
                "total_indices": len(filtered_indices),
                "total_vectors": total_vectors,
                "total_size_mb": round(total_size_mb, 2),
                "store_type_distribution": store_type_counts,
                "status_distribution": status_counts,
                "avg_vectors_per_index": round(total_vectors / len(filtered_indices), 0) if filtered_indices else 0
            }
        else:
            stats = None
            
        return {
            "success": True,
            "indices": filtered_indices,
            "count": len(filtered_indices),
            "filters_applied": {
                "store_type": store_type,
                "namespace": namespace,
                "include_stats": include_stats
            },
            "statistics": stats,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to list vector indices: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
