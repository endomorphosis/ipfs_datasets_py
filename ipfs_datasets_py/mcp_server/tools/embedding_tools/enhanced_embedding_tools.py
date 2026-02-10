"""
Enhanced Embedding Tools for MCP Server
Provides comprehensive embedding generation and management capabilities
"""

import anyio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

logger = logging.getLogger(__name__)

# Import the enhanced embeddings engine
try:
    from ....embeddings.embeddings_engine import AdvancedIPFSEmbeddings, EmbeddingConfig, ChunkingConfig
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    AdvancedIPFSEmbeddings = None
    EmbeddingConfig = None
    ChunkingConfig = None

async def create_embeddings(
    texts: Union[str, List[str]],
    model: str = "thenlper/gte-small",
    endpoint_type: str = "local",
    endpoint_url: Optional[str] = None,
    batch_size: int = 32,
    max_length: int = 512,
    device: str = "cpu"
) -> Dict[str, Any]:
    """
    Create embeddings for given texts using specified model and endpoint.
    
    Args:
        texts: Single text or list of texts to embed
        model: Model name for embedding generation
        endpoint_type: Type of endpoint (local, tei, openvino, libp2p)
        endpoint_url: URL for remote endpoints
        batch_size: Batch size for processing
        max_length: Maximum token length
        device: Device to use for local endpoints
        
    Returns:
        Dictionary with embedding results and metadata
    """
    try:
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available. Install required dependencies.",
                "required_packages": ["torch", "transformers", "datasets"]
            }
            
        # Normalize input
        if isinstance(texts, str):
            texts = [texts]
            
        # Create configuration
        resources = {}
        metadata = {}
        
        # Setup endpoint configuration
        if endpoint_type == "tei" and endpoint_url:
            resources["tei_endpoints"] = [[model, endpoint_url, max_length]]
        elif endpoint_type == "local":
            resources["local_endpoints"] = [[model, device, max_length]]
        elif endpoint_type == "openvino" and endpoint_url:
            resources["openvino_endpoints"] = [[model, endpoint_url, max_length]]
        elif endpoint_type == "libp2p" and endpoint_url:
            resources["libp2p_endpoints"] = [[model, endpoint_url, max_length]]
        else:
            # Default local endpoint
            resources["local_endpoints"] = [[model, "cpu", max_length]]
            
        # Initialize embeddings engine
        embeddings_engine = AdvancedIPFSEmbeddings(resources, metadata)
        
        # Generate embeddings
        embeddings = await embeddings_engine.generate_embeddings(
            texts, model
        )
        
        return {
            "status": "success",
            "embeddings": embeddings.tolist(),
            "model": model,
            "endpoint_type": endpoint_type,
            "text_count": len(texts),
            "embedding_dimension": embeddings.shape[1] if len(embeddings.shape) > 1 else 0,
            "metadata": {
                "batch_size": batch_size,
                "max_length": max_length,
                "device": device
            }
        }
        
    except Exception as e:
        logger.error(f"Error creating embeddings: {e}")
        return {
            "status": "error",
            "error": str(e),
            "model": model,
            "text_count": len(texts) if isinstance(texts, list) else 1
        }

async def index_dataset(
    dataset_name: str,
    split: Optional[str] = None,
    column: str = "text",
    output_path: str = "./embeddings_cache",
    models: Optional[List[str]] = None,
    chunk_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Index a dataset with embeddings for similarity search.
    
    Args:
        dataset_name: Name of the dataset to index
        split: Dataset split to use (train, test, validation)
        column: Text column to embed
        output_path: Path to save embeddings
        models: List of models to use for embedding
        chunk_config: Text chunking configuration
        
    Returns:
        Dictionary with indexing results
    """
    try:
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        # Default models
        if models is None:
            models = ["thenlper/gte-small"]
            
        # Create output directory
        os.makedirs(output_path, exist_ok=True)
        
        # Setup resources for local endpoints
        resources = {
            "local_endpoints": [[model, "cpu", 512] for model in models]
        }
        metadata = {}
        
        # Initialize embeddings engine
        embeddings_engine = AdvancedIPFSEmbeddings(resources, metadata)
        
        # Index the dataset
        results = await embeddings_engine.index_dataset(
            dataset_name=dataset_name,
            split=split,
            column=column,
            dst_path=output_path,
            models=models
        )
        
        return {
            "status": "success",
            "dataset": dataset_name,
            "split": split,
            "column": column,
            "output_path": output_path,
            "models": models,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error indexing dataset: {e}")
        return {
            "status": "error",
            "error": str(e),
            "dataset": dataset_name
        }

async def search_embeddings(
    query: str,
    index_path: str,
    model: str = "thenlper/gte-small",
    top_k: int = 10,
    threshold: float = 0.0
) -> Dict[str, Any]:
    """
    Search for similar texts using pre-computed embeddings.
    
    Args:
        query: Query text to search for
        index_path: Path to the embeddings index file
        model: Model used for the index
        top_k: Number of top results to return
        threshold: Minimum similarity threshold
        
    Returns:
        Dictionary with search results
    """
    try:
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        if not os.path.exists(index_path):
            return {
                "status": "error",
                "error": f"Index file not found: {index_path}"
            }
            
        # Setup resources for local endpoint
        resources = {
            "local_endpoints": [[model, "cpu", 512]]
        }
        metadata = {}
        
        # Initialize embeddings engine
        embeddings_engine = AdvancedIPFSEmbeddings(resources, metadata)
        
        # Search for similar texts
        results = await embeddings_engine.search_similar(
            query=query,
            model=model,
            top_k=top_k,
            index_path=index_path
        )
        
        # Filter by threshold
        filtered_results = [
            result for result in results
            if result["similarity"] >= threshold
        ]
        
        return {
            "status": "success",
            "query": query,
            "results": filtered_results,
            "total_results": len(filtered_results),
            "model": model,
            "threshold": threshold
        }
        
    except Exception as e:
        logger.error(f"Error searching embeddings: {e}")
        return {
            "status": "error",
            "error": str(e),
            "query": query
        }

async def chunk_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    method: str = "fixed",
    n_sentences: int = 8,
    step_size: int = 256
) -> Dict[str, Any]:
    """
    Chunk text using various strategies for embedding.
    
    Args:
        text: Text to chunk
        chunk_size: Size of each chunk in characters
        chunk_overlap: Overlap between chunks
        method: Chunking method (fixed, semantic, sliding_window)
        n_sentences: Number of sentences per chunk (for semantic)
        step_size: Step size for sliding window
        
    Returns:
        Dictionary with chunked text results
    """
    try:
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        # Create chunking configuration
        chunk_config = ChunkingConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            method=method,
            n_sentences=n_sentences,
            step_size=step_size
        )
        
        # Setup basic embeddings engine for chunking
        resources = {}
        metadata = {}
        embeddings_engine = AdvancedIPFSEmbeddings(resources, metadata)
        
        # Chunk the text
        chunks = embeddings_engine.chunk_text(text, chunk_config)
        
        # Extract chunk texts
        chunk_texts = []
        for start, end in chunks:
            chunk_text = text[start:end]
            chunk_texts.append({
                "text": chunk_text,
                "start": start,
                "end": end,
                "length": end - start
            })
            
        return {
            "status": "success",
            "original_length": len(text),
            "chunk_count": len(chunk_texts),
            "chunks": chunk_texts,
            "config": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "method": method,
                "n_sentences": n_sentences,
                "step_size": step_size
            }
        }
        
    except Exception as e:
        logger.error(f"Error chunking text: {e}")
        return {
            "status": "error",
            "error": str(e),
            "text_length": len(text)
        }

async def manage_endpoints(
    action: str,
    model: str,
    endpoint: str,
    endpoint_type: str = "tei",
    context_length: int = 512
) -> Dict[str, Any]:
    """
    Manage embedding endpoints (add, remove, test).
    
    Args:
        action: Action to perform (add, remove, test, list)
        model: Model name
        endpoint: Endpoint URL or device
        endpoint_type: Type of endpoint (tei, openvino, libp2p, local)
        context_length: Maximum context length
        
    Returns:
        Dictionary with endpoint management results
    """
    try:
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        # Setup basic configuration
        resources = {}
        metadata = {}
        embeddings_engine = AdvancedIPFSEmbeddings(resources, metadata)
        
        if action == "add":
            if endpoint_type == "tei":
                embeddings_engine.add_tei_endpoint(model, endpoint, context_length)
            elif endpoint_type == "openvino":
                embeddings_engine.add_openvino_endpoint(model, endpoint, context_length)
            elif endpoint_type == "libp2p":
                embeddings_engine.add_libp2p_endpoint(model, endpoint, context_length)
            elif endpoint_type == "local":
                embeddings_engine.add_local_endpoint(model, endpoint, context_length)
            else:
                return {
                    "status": "error",
                    "error": f"Unknown endpoint type: {endpoint_type}"
                }
                
            return {
                "status": "success",
                "action": "added",
                "model": model,
                "endpoint": endpoint,
                "endpoint_type": endpoint_type,
                "context_length": context_length
            }
            
        elif action == "test":
            is_available = await embeddings_engine.test_endpoint(endpoint, model)
            return {
                "status": "success",
                "action": "tested",
                "model": model,
                "endpoint": endpoint,
                "available": is_available
            }
            
        elif action == "list":
            endpoints = embeddings_engine.get_endpoints(model, endpoint_type)
            return {
                "status": "success",
                "action": "listed",
                "model": model,
                "endpoint_type": endpoint_type,
                "endpoints": endpoints
            }
            
        elif action == "status":
            status = embeddings_engine.get_status()
            return {
                "status": "success",
                "action": "status",
                "engine_status": status
            }
            
        else:
            return {
                "status": "error",
                "error": f"Unknown action: {action}"
            }
            
    except Exception as e:
        logger.error(f"Error managing endpoints: {e}")
        return {
            "status": "error",
            "error": str(e),
            "action": action,
            "model": model
        }
