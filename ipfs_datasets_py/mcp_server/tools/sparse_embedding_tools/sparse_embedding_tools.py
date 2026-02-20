# sparse_embedding_tools.py — thin MCP wrapper
"""
Sparse embedding tools for MCP server.

Business logic (SparseModel, SparseEmbedding, MockSparseEmbeddingService) lives in
ipfs_datasets_py.ml.embeddings.sparse_embedding_engine.  This module is a thin
MCP wrapper that validates inputs, delegates to the engine, and formats responses.
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime

from ipfs_datasets_py.embeddings.sparse_embedding_engine import (  # noqa: F401
    SparseModel,
    SparseEmbedding,
    MockSparseEmbeddingService,
    get_default_sparse_service,
)

logger = logging.getLogger(__name__)

# Module-level singleton — shared across calls within one server process.
_sparse_service = get_default_sparse_service()

async def generate_sparse_embedding(
    text: str,
    model: str = "splade",
    top_k: int = 100,
    normalize: bool = True,
    return_dense: bool = False
) -> Dict[str, Any]:
    """
    Generate sparse embeddings from text using various sparse models.
    
    Args:
        text: Input text to generate embeddings for
        model: Sparse embedding model to use
        top_k: Number of top dimensions to keep
        normalize: Whether to normalize the embedding values
        return_dense: Whether to also return dense representation
    
    Returns:
        Dict containing sparse embedding data
    """
    try:
        logger.info(f"Generating sparse embedding for text (length: {len(text)}) using {model}")
        
        if not text.strip():
            raise ValueError("Text cannot be empty")
        
        # Generate sparse embedding
        embedding = _sparse_service.generate_sparse_embedding(text, model, top_k, normalize)
        
        result = {
            "text": text,
            "model": model,
            "sparse_embedding": {
                "indices": embedding.indices,
                "values": embedding.values,
                "dimension": embedding.dimension,
                "sparsity": embedding.sparsity,
                "num_nonzero": len(embedding.indices)
            },
            "metadata": embedding.metadata,
            "generation_config": {
                "top_k": top_k,
                "normalize": normalize,
                "model": model
            },
            "generated_at": datetime.now().isoformat()
        }
        
        # Add dense representation if requested
        if return_dense:
            dense_vector = np.zeros(embedding.dimension)
            dense_vector[embedding.indices] = embedding.values
            result["dense_embedding"] = dense_vector.tolist()
        
        return result
        
    except Exception as e:
        logger.error(f"Sparse embedding generation failed: {e}")
        raise

async def index_sparse_collection(
    collection_name: str,
    dataset: str,
    split: str = "train",
    column: str = "text",
    models: List[str] = None,
    batch_size: int = 100,
    index_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Index sparse embeddings for efficient retrieval.
    
    Args:
        collection_name: Name for the indexed collection
        dataset: Dataset identifier to index
        split: Dataset split to use
        column: Text column to generate embeddings for
        models: List of sparse models to use
        batch_size: Batch size for processing
        index_config: Configuration for index creation
    
    Returns:
        Dict containing indexing results
    """
    try:
        models = models or ["splade"]
        logger.info(f"Indexing sparse embeddings for collection '{collection_name}' with models: {models}")
        
        # Mock dataset loading - in real implementation, load from datasets library
        mock_documents = [
            {
                "id": f"doc_{i}",
                "text": f"Sample document {i} for sparse indexing with various terms and concepts",
                "metadata": {"index": i, "dataset": dataset, "split": split}
            }
            for i in range(1000)  # Mock 1000 documents
        ]
        
        results = {}
        
        # Index with each model
        for model in models:
            logger.info(f"Indexing with model: {model}")
            
            # Process in batches
            total_batches = (len(mock_documents) + batch_size - 1) // batch_size
            processed_docs = 0
            
            for batch_idx in range(total_batches):
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(mock_documents))
                batch_docs = mock_documents[start_idx:end_idx]
                
                # Index batch
                stats = _sparse_service.index_sparse_embeddings(
                    f"{collection_name}_{model}",
                    batch_docs,
                    model,
                    index_config
                )
                
                processed_docs += len(batch_docs)
                
                # Mock progress update
                if batch_idx % 10 == 0:
                    logger.info(f"Processed {processed_docs}/{len(mock_documents)} documents for {model}")
            
            results[model] = {
                "collection_name": f"{collection_name}_{model}",
                "model": model,
                "stats": stats,
                "processed_documents": processed_docs
            }
        
        return {
            "collection_name": collection_name,
            "dataset": dataset,
            "split": split,
            "column": column,
            "models": models,
            "results": results,
            "total_documents": len(mock_documents),
            "indexing_config": index_config or {},
            "completed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Sparse embedding indexing failed: {e}")
        raise

async def sparse_search(
    query: str,
    collection_name: str,
    model: str = "splade",
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    search_config: Optional[Dict[str, Any]] = None,
    explain_scores: bool = False
) -> Dict[str, Any]:
    """
    Perform sparse vector search on indexed embeddings.
    
    Args:
        query: Search query text
        collection_name: Collection to search in
        model: Sparse model to use for search
        top_k: Number of top results to return
        filters: Optional metadata filters
        search_config: Configuration for search behavior
        explain_scores: Whether to include score explanations
    
    Returns:
        Dict containing search results
    """
    try:
        logger.info(f"Performing sparse search for query: '{query[:50]}...' in collection: {collection_name}")
        
        # Use model-specific collection name
        search_collection = f"{collection_name}_{model}"
        
        # Perform search
        results = _sparse_service.sparse_search(
            query, search_collection, model, top_k, filters, search_config
        )
        
        # Add explanation details if requested
        if explain_scores:
            for result in results:
                result["score_explanation"] = {
                    "method": "sparse_dot_product",
                    "query_length": len(query.split()),
                    "document_length": len(result["text"].split()),
                    "model_type": model,
                    "normalization": "l2" if search_config and search_config.get("normalize") else "none"
                }
        
        search_metadata = {
            "query": query,
            "collection": collection_name,
            "model": model,
            "top_k": top_k,
            "filters": filters,
            "search_config": search_config or {},
            "results_count": len(results),
            "search_time_ms": 45.2,  # Mock search time
            "searched_at": datetime.now().isoformat()
        }
        
        return {
            "query": query,
            "results": results,
            "metadata": search_metadata,
            "total_found": len(results),
            "has_more": len(results) == top_k  # Approximate
        }
        
    except Exception as e:
        logger.error(f"Sparse search failed: {e}")
        raise

async def manage_sparse_models(
    action: str,
    model_name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Manage sparse embedding models and configurations.
    
    Args:
        action: Management action (list, add, remove, configure)
        model_name: Name of specific model to manage
        config: Configuration for model operations
    
    Returns:
        Dict containing management operation results
    """
    try:
        logger.info(f"Managing sparse models: action={action}, model={model_name}")
        
        if action == "list":
            return {
                "action": "list",
                "available_models": list(_sparse_service.models.keys()),
                "model_details": _sparse_service.models,
                "service_stats": _sparse_service.stats,
                "indexed_collections": list(_sparse_service.indexed_collections.keys())
            }
        
        elif action == "stats":
            if model_name:
                # Stats for specific model
                model_collections = [
                    name for name in _sparse_service.indexed_collections.keys()
                    if name.endswith(f"_{model_name}")
                ]
                
                total_docs = sum(
                    _sparse_service.indexed_collections[col]["stats"]["document_count"]
                    for col in model_collections
                )
                
                return {
                    "model": model_name,
                    "collections": model_collections,
                    "total_documents": total_docs,
                    "model_info": _sparse_service.models.get(model_name, {}),
                    "available": model_name in _sparse_service.models
                }
            else:
                # Global stats
                return {
                    "global_stats": _sparse_service.stats,
                    "models_available": len(_sparse_service.models),
                    "collections_indexed": len(_sparse_service.indexed_collections),
                    "uptime": "running"
                }
        
        elif action == "configure":
            if not model_name or not config:
                return {"error": "model_name and config required for configure action"}
            
            # Update model configuration
            if model_name in _sparse_service.models:
                _sparse_service.models[model_name].update(config)
                return {
                    "action": "configure",
                    "model": model_name,
                    "updated_config": _sparse_service.models[model_name],
                    "success": True
                }
            else:
                return {"error": f"Model '{model_name}' not found"}
        
        elif action == "clear_cache":
            if model_name:
                # Clear cache for specific model
                collections_to_remove = [
                    name for name in _sparse_service.indexed_collections.keys()
                    if name.endswith(f"_{model_name}")
                ]
                
                for collection in collections_to_remove:
                    del _sparse_service.indexed_collections[collection]
                
                return {
                    "action": "clear_cache",
                    "model": model_name,
                    "cleared_collections": collections_to_remove,
                    "success": True
                }
            else:
                # Clear all cache
                cleared_count = len(_sparse_service.indexed_collections)
                _sparse_service.indexed_collections.clear()
                _sparse_service.stats["collections_indexed"] = 0
                _sparse_service.stats["total_documents"] = 0
                
                return {
                    "action": "clear_cache",
                    "cleared_collections": cleared_count,
                    "success": True
                }
        
        else:
            return {"error": f"Unknown action: {action}"}
        
    except Exception as e:
        logger.error(f"Sparse model management failed: {e}")
        raise
