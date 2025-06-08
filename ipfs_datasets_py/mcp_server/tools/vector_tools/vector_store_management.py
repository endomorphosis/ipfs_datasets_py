"""
Vector Store Management Tools for MCP Server
Provides comprehensive vector database operations and management
"""

import asyncio
import json
import logging
import os
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

logger = logging.getLogger(__name__)

# Vector store backends
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    QdrantClient = None
    models = None

try:
    from elasticsearch import Elasticsearch
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    ELASTICSEARCH_AVAILABLE = False
    Elasticsearch = None

# Import embeddings engine
try:
    from ...ipfs_embeddings_py.embeddings_engine import AdvancedIPFSEmbeddings
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    AdvancedIPFSEmbeddings = None

async def create_vector_index(
    index_name: str,
    documents: List[Dict[str, Any]],
    backend: str = "faiss",
    vector_dim: int = 384,
    distance_metric: str = "cosine",
    index_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a vector index for similarity search.
    
    Args:
        index_name: Name of the index to create
        documents: List of documents with 'text' and optional 'metadata'
        backend: Vector store backend (faiss, qdrant, elasticsearch)
        vector_dim: Dimension of the vectors
        distance_metric: Distance metric (cosine, euclidean, dot_product)
        index_config: Backend-specific configuration
        
    Returns:
        Dictionary with index creation results
    """
    try:
        if backend == "faiss":
            return await _create_faiss_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        elif backend == "qdrant":
            return await _create_qdrant_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        elif backend == "elasticsearch":
            return await _create_elasticsearch_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        else:
            return {
                "status": "error",
                "error": f"Unsupported backend: {backend}",
                "supported_backends": ["faiss", "qdrant", "elasticsearch"]
            }
            
    except Exception as e:
        logger.error(f"Error creating vector index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "index_name": index_name,
            "backend": backend
        }

async def _create_faiss_index(
    index_name: str,
    documents: List[Dict[str, Any]],
    vector_dim: int,
    distance_metric: str,
    config: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Create FAISS vector index"""
    if not FAISS_AVAILABLE:
        return {
            "status": "error",
            "error": "FAISS not available. Install with: pip install faiss-cpu"
        }
        
    try:
        # Create FAISS index
        if distance_metric == "cosine":
            index = faiss.IndexFlatIP(vector_dim)  # Inner product for cosine
        elif distance_metric == "euclidean":
            index = faiss.IndexFlatL2(vector_dim)  # L2 distance
        else:
            index = faiss.IndexFlatIP(vector_dim)  # Default to inner product
            
        # Generate embeddings for documents
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        # Extract texts
        texts = [doc.get("text", "") for doc in documents]
        
        # Setup embeddings engine
        resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
        embeddings_engine = AdvancedIPFSEmbeddings(resources, {})
        
        # Generate embeddings
        embeddings = await embeddings_engine.generate_embeddings(texts, "thenlper/gte-small")
        
        # Normalize for cosine similarity if needed
        if distance_metric == "cosine":
            faiss.normalize_L2(embeddings)
            
        # Add vectors to index
        index.add(embeddings)
        
        # Save index and metadata
        index_dir = f"./vector_indexes/{index_name}"
        os.makedirs(index_dir, exist_ok=True)
        
        # Save FAISS index
        faiss.write_index(index, f"{index_dir}/index.faiss")
        
        # Save metadata
        metadata = {
            "index_name": index_name,
            "backend": "faiss",
            "vector_dim": vector_dim,
            "distance_metric": distance_metric,
            "document_count": len(documents),
            "documents": documents
        }
        
        with open(f"{index_dir}/metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
            
        return {
            "status": "success",
            "index_name": index_name,
            "backend": "faiss",
            "vector_dim": vector_dim,
            "document_count": len(documents),
            "index_path": index_dir
        }
        
    except Exception as e:
        logger.error(f"Error creating FAISS index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "backend": "faiss"
        }

async def _create_qdrant_index(
    index_name: str,
    documents: List[Dict[str, Any]],
    vector_dim: int,
    distance_metric: str,
    config: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Create Qdrant vector index"""
    if not QDRANT_AVAILABLE:
        return {
            "status": "error",
            "error": "Qdrant client not available. Install with: pip install qdrant-client"
        }
        
    try:
        # Setup Qdrant client
        qdrant_url = config.get("url", "localhost") if config else "localhost"
        qdrant_port = config.get("port", 6333) if config else 6333
        
        client = QdrantClient(host=qdrant_url, port=qdrant_port)
        
        # Map distance metric
        distance_map = {
            "cosine": models.Distance.COSINE,
            "euclidean": models.Distance.EUCLID,
            "dot_product": models.Distance.DOT
        }
        qdrant_distance = distance_map.get(distance_metric, models.Distance.COSINE)
        
        # Create collection
        client.create_collection(
            collection_name=index_name,
            vectors_config=models.VectorParams(
                size=vector_dim,
                distance=qdrant_distance
            )
        )
        
        # Generate embeddings for documents
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        texts = [doc.get("text", "") for doc in documents]
        
        resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
        embeddings_engine = AdvancedIPFSEmbeddings(resources, {})
        
        embeddings = await embeddings_engine.generate_embeddings(texts, "thenlper/gte-small")
        
        # Upload vectors to Qdrant
        points = []
        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            point = models.PointStruct(
                id=i,
                vector=embedding.tolist(),
                payload={
                    "text": doc.get("text", ""),
                    "metadata": doc.get("metadata", {})
                }
            )
            points.append(point)
            
        client.upsert(
            collection_name=index_name,
            points=points
        )
        
        return {
            "status": "success",
            "index_name": index_name,
            "backend": "qdrant",
            "vector_dim": vector_dim,
            "document_count": len(documents),
            "collection_name": index_name
        }
        
    except Exception as e:
        logger.error(f"Error creating Qdrant index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "backend": "qdrant"
        }

async def _create_elasticsearch_index(
    index_name: str,
    documents: List[Dict[str, Any]],
    vector_dim: int,
    distance_metric: str,
    config: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Create Elasticsearch vector index"""
    if not ELASTICSEARCH_AVAILABLE:
        return {
            "status": "error",
            "error": "Elasticsearch not available. Install with: pip install elasticsearch"
        }
        
    try:
        # Setup Elasticsearch client
        es_url = config.get("url", "localhost:9200") if config else "localhost:9200"
        es = Elasticsearch([es_url])
        
        # Create index mapping
        mapping = {
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "vector": {
                        "type": "dense_vector",
                        "dims": vector_dim,
                        "index": True,
                        "similarity": "cosine" if distance_metric == "cosine" else "l2_norm"
                    },
                    "metadata": {"type": "object"}
                }
            }
        }
        
        # Create index
        es.indices.create(index=index_name, body=mapping)
        
        # Generate embeddings for documents
        if not EMBEDDINGS_AVAILABLE:
            return {
                "status": "error",
                "error": "Embeddings engine not available"
            }
            
        texts = [doc.get("text", "") for doc in documents]
        
        resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
        embeddings_engine = AdvancedIPFSEmbeddings(resources, {})
        
        embeddings = await embeddings_engine.generate_embeddings(texts, "thenlper/gte-small")
        
        # Index documents
        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            doc_body = {
                "text": doc.get("text", ""),
                "vector": embedding.tolist(),
                "metadata": doc.get("metadata", {})
            }
            es.index(index=index_name, id=i, body=doc_body)
            
        # Refresh index
        es.indices.refresh(index=index_name)
        
        return {
            "status": "success",
            "index_name": index_name,
            "backend": "elasticsearch",
            "vector_dim": vector_dim,
            "document_count": len(documents),
            "es_index": index_name
        }
        
    except Exception as e:
        logger.error(f"Error creating Elasticsearch index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "backend": "elasticsearch"
        }

async def search_vector_index(
    index_name: str,
    query: str,
    backend: str = "faiss",
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search a vector index for similar documents.
    
    Args:
        index_name: Name of the index to search
        query: Query text to search for
        backend: Vector store backend
        top_k: Number of top results to return
        filters: Optional filters for search
        config: Backend-specific configuration
        
    Returns:
        Dictionary with search results
    """
    try:
        if backend == "faiss":
            return await _search_faiss_index(index_name, query, top_k, config)
        elif backend == "qdrant":
            return await _search_qdrant_index(index_name, query, top_k, filters, config)
        elif backend == "elasticsearch":
            return await _search_elasticsearch_index(index_name, query, top_k, filters, config)
        else:
            return {
                "status": "error",
                "error": f"Unsupported backend: {backend}"
            }
            
    except Exception as e:
        logger.error(f"Error searching vector index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "index_name": index_name,
            "backend": backend
        }

async def _search_faiss_index(
    index_name: str,
    query: str,
    top_k: int,
    config: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Search FAISS vector index"""
    try:
        index_dir = f"./vector_indexes/{index_name}"
        
        if not os.path.exists(f"{index_dir}/index.faiss"):
            return {
                "status": "error",
                "error": f"FAISS index not found: {index_name}"
            }
            
        # Load index and metadata
        index = faiss.read_index(f"{index_dir}/index.faiss")
        
        with open(f"{index_dir}/metadata.json", "r") as f:
            metadata = json.load(f)
            
        # Generate query embedding
        resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
        embeddings_engine = AdvancedIPFSEmbeddings(resources, {})
        
        query_embedding = await embeddings_engine.generate_embeddings([query], "thenlper/gte-small")
        query_vector = query_embedding[0].reshape(1, -1)
        
        # Normalize for cosine similarity if needed
        if metadata.get("distance_metric") == "cosine":
            faiss.normalize_L2(query_vector)
            
        # Search
        scores, indices = index.search(query_vector, top_k)
        
        # Format results
        results = []
        documents = metadata.get("documents", [])
        
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(documents):
                result = {
                    "document": documents[idx],
                    "score": float(score),
                    "index": int(idx)
                }
                results.append(result)
                
        return {
            "status": "success",
            "query": query,
            "results": results,
            "total_results": len(results),
            "backend": "faiss",
            "index_name": index_name
        }
        
    except Exception as e:
        logger.error(f"Error searching FAISS index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "backend": "faiss"
        }

async def list_vector_indexes(backend: str = "all") -> Dict[str, Any]:
    """
    List available vector indexes.
    
    Args:
        backend: Backend to list indexes for (all, faiss, qdrant, elasticsearch)
        
    Returns:
        Dictionary with list of available indexes
    """
    try:
        indexes = {}
        
        if backend in ["all", "faiss"]:
            # List FAISS indexes
            faiss_indexes = []
            indexes_dir = "./vector_indexes"
            if os.path.exists(indexes_dir):
                for item in os.listdir(indexes_dir):
                    item_path = os.path.join(indexes_dir, item)
                    if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "index.faiss")):
                        # Load metadata
                        metadata_path = os.path.join(item_path, "metadata.json")
                        if os.path.exists(metadata_path):
                            with open(metadata_path, "r") as f:
                                metadata = json.load(f)
                            faiss_indexes.append({
                                "name": item,
                                "backend": "faiss",
                                "vector_dim": metadata.get("vector_dim"),
                                "document_count": metadata.get("document_count"),
                                "distance_metric": metadata.get("distance_metric")
                            })
            indexes["faiss"] = faiss_indexes
            
        # TODO: Add Qdrant and Elasticsearch listing
        # This would require connecting to the services and listing collections/indexes
        
        return {
            "status": "success",
            "backend": backend,
            "indexes": indexes
        }
        
    except Exception as e:
        logger.error(f"Error listing vector indexes: {e}")
        return {
            "status": "error",
            "error": str(e),
            "backend": backend
        }

async def delete_vector_index(
    index_name: str,
    backend: str = "faiss",
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Delete a vector index.
    
    Args:
        index_name: Name of the index to delete
        backend: Vector store backend
        config: Backend-specific configuration
        
    Returns:
        Dictionary with deletion results
    """
    try:
        if backend == "faiss":
            index_dir = f"./vector_indexes/{index_name}"
            if os.path.exists(index_dir):
                import shutil
                shutil.rmtree(index_dir)
                return {
                    "status": "success",
                    "message": f"FAISS index {index_name} deleted",
                    "backend": "faiss"
                }
            else:
                return {
                    "status": "error",
                    "error": f"FAISS index {index_name} not found",
                    "backend": "faiss"
                }
                
        elif backend == "qdrant":
            if not QDRANT_AVAILABLE:
                return {
                    "status": "error",
                    "error": "Qdrant client not available"
                }
                
            # Connect to Qdrant and delete collection
            qdrant_url = config.get("url", "localhost") if config else "localhost"
            qdrant_port = config.get("port", 6333) if config else 6333
            
            client = QdrantClient(host=qdrant_url, port=qdrant_port)
            client.delete_collection(collection_name=index_name)
            
            return {
                "status": "success",
                "message": f"Qdrant collection {index_name} deleted",
                "backend": "qdrant"
            }
            
        elif backend == "elasticsearch":
            if not ELASTICSEARCH_AVAILABLE:
                return {
                    "status": "error",
                    "error": "Elasticsearch not available"
                }
                
            # Connect to Elasticsearch and delete index
            es_url = config.get("url", "localhost:9200") if config else "localhost:9200"
            es = Elasticsearch([es_url])
            es.indices.delete(index=index_name)
            
            return {
                "status": "success",
                "message": f"Elasticsearch index {index_name} deleted",
                "backend": "elasticsearch"
            }
            
        else:
            return {
                "status": "error",
                "error": f"Unsupported backend: {backend}"
            }
            
    except Exception as e:
        logger.error(f"Error deleting vector index: {e}")
        return {
            "status": "error",
            "error": str(e),
            "index_name": index_name,
            "backend": backend
        }
