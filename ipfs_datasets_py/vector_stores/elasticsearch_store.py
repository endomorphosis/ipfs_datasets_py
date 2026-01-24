"""Elasticsearch vector store implementation.

This module provides an Elasticsearch-based vector store for embedding operations,
migrated and adapted from ipfs_embeddings_py.
"""
from __future__ import annotations
import logging
import uuid
from typing import List, Dict, Any, Optional, TypeAlias
import anyio
import json

from .base import BaseVectorStore, VectorStoreError, VectorStoreConnectionError, VectorStoreOperationError
from ..embeddings.schema import EmbeddingResult, SearchResult, VectorStoreConfig, VectorStoreType

try:
    from elasticsearch import Elasticsearch, AsyncElasticsearch
    from elasticsearch.exceptions import NotFoundError, ConnectionError as ESConnectionError
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    Elasticsearch = None
    AsyncElasticsearch = Any
    NotFoundError = Exception
    ESConnectionError = Exception
    ELASTICSEARCH_AVAILABLE = False

AsyncElasticsearchType: TypeAlias = Any
logger = logging.getLogger(__name__)


class ElasticsearchVectorStore(BaseVectorStore):
    """Elasticsearch vector store implementation."""
    
    def __init__(self, config: VectorStoreConfig):
        """Initialize Elasticsearch vector store.
        
        Args:
            config: Vector store configuration
        """
        if not ELASTICSEARCH_AVAILABLE:
            raise VectorStoreError("Elasticsearch client not available. Install with: pip install elasticsearch")
        
        super().__init__(config)
        self.host = config.host or "localhost"
        self.port = config.port or 9200
        self.index_name = config.index_name or config.collection_name
        self.connection_params = config.connection_params or {}
        
        # Elasticsearch configuration
        self.hosts = self.connection_params.get("hosts", [f"{self.host}:{self.port}"])
        self.use_ssl = self.connection_params.get("use_ssl", False)
        self.verify_certs = self.connection_params.get("verify_certs", False)
        self.ca_certs = self.connection_params.get("ca_certs")
        self.username = self.connection_params.get("username")
        self.password = self.connection_params.get("password")
        self.api_key = self.connection_params.get("api_key")
        
        # Vector search configuration
        self.similarity_metric = self._map_distance_metric(self.distance_metric)
    
    def _map_distance_metric(self, distance_metric: str) -> str:
        """Map distance metric to Elasticsearch similarity function."""
        mapping = {
            "cosine": "cosine",
            "euclidean": "l2_norm", 
            "dot": "dot_product",
            "manhattan": "l1_norm"
        }
        return mapping.get(distance_metric.lower(), "cosine")
    
    def _create_client(self) -> AsyncElasticsearchType:
        """Create Elasticsearch async client connection."""
        try:
            client_args = {
                "hosts": self.hosts,
                "use_ssl": self.use_ssl,
                "verify_certs": self.verify_certs
            }
            
            if self.ca_certs:
                client_args["ca_certs"] = self.ca_certs
            
            if self.username and self.password:
                client_args["basic_auth"] = (self.username, self.password)
            elif self.api_key:
                client_args["api_key"] = self.api_key
            
            return AsyncElasticsearch(**client_args)
        except Exception as e:
            raise VectorStoreConnectionError(f"Failed to connect to Elasticsearch: {e}")
    
    def _get_index_mapping(self, dimension: int) -> Dict[str, Any]:
        """Get the mapping configuration for vector index."""
        return {
            "mappings": {
                "properties": {
                    "vector": {
                        "type": "dense_vector",
                        "dims": dimension,
                        "similarity": self.similarity_metric
                    },
                    "content": {
                        "type": "text",
                        "analyzer": "standard"
                    },
                    "chunk_id": {
                        "type": "keyword"
                    },
                    "model_name": {
                        "type": "keyword"
                    },
                    "metadata": {
                        "type": "object",
                        "dynamic": True
                    }
                }
            },
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            }
        }
    
    async def create_collection(self, collection_name: Optional[str] = None, 
                              dimension: Optional[int] = None, **kwargs) -> bool:
        """Create a new Elasticsearch index.
        
        Args:
            collection_name: Name of the index to create
            dimension: Vector dimension
            **kwargs: Additional index parameters
            
        Returns:
            True if index was created successfully
        """
        index_name = collection_name or self.index_name
        dimension = dimension or self.dimension
        
        if not dimension:
            raise VectorStoreError("Vector dimension must be specified")
        
        try:
            mapping = self._get_index_mapping(dimension)
            mapping.update(kwargs)
            
            response = await self.client.indices.create(
                index=index_name,
                body=mapping
            )
            
            logger.info(f"Created Elasticsearch index: {index_name}")
            return response.get("acknowledged", False)
        except Exception as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            raise VectorStoreOperationError(f"Failed to create index: {e}")
    
    async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """Delete an Elasticsearch index.
        
        Args:
            collection_name: Name of the index to delete
            
        Returns:
            True if index was deleted successfully
        """
        index_name = collection_name or self.index_name
        
        try:
            response = await self.client.indices.delete(index=index_name)
            logger.info(f"Deleted Elasticsearch index: {index_name}")
            return response.get("acknowledged", False)
        except NotFoundError:
            logger.warning(f"Index {index_name} not found")
            return True
        except Exception as e:
            logger.error(f"Failed to delete index {index_name}: {e}")
            raise VectorStoreOperationError(f"Failed to delete index: {e}")
    
    async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
        """Check if an Elasticsearch index exists.
        
        Args:
            collection_name: Name of the index to check
            
        Returns:
            True if index exists
        """
        index_name = collection_name or self.index_name
        
        try:
            return await self.client.indices.exists(index=index_name)
        except Exception as e:
            logger.error(f"Failed to check index existence {index_name}: {e}")
            return False
    
    async def add_embeddings(self, embeddings: List[EmbeddingResult], 
                           collection_name: Optional[str] = None) -> List[str]:
        """Add embeddings to Elasticsearch index.
        
        Args:
            embeddings: List of embedding results to add
            collection_name: Target index name
            
        Returns:
            List of document IDs for the added embeddings
        """
        index_name = collection_name or self.index_name
        
        if not embeddings:
            return []
        
        # Ensure index exists
        if not await self.collection_exists(index_name):
            # Auto-create index if it doesn't exist
            dimension = len(embeddings[0].embedding)
            await self.create_collection(index_name, dimension)
        
        # Prepare bulk index operations
        actions = []
        doc_ids = []
        
        for embedding in embeddings:
            doc_id = embedding.chunk_id or str(uuid.uuid4())
            doc_ids.append(doc_id)
            
            # Prepare document
            doc = {
                "vector": embedding.embedding,
                "content": embedding.content,
                "chunk_id": embedding.chunk_id,
                "model_name": embedding.model_name,
                "metadata": embedding.metadata or {}
            }
            
            # Add index action
            actions.append({
                "index": {
                    "_index": index_name,
                    "_id": doc_id
                }
            })
            actions.append(doc)
        
        try:
            # Bulk index
            response = await self.client.bulk(body=actions)
            
            # Check for errors
            if response.get("errors"):
                error_items = [item for item in response["items"] if "error" in item.get("index", {})]
                if error_items:
                    logger.error(f"Bulk index errors: {error_items}")
                    raise VectorStoreOperationError(f"Bulk index failed with errors")
            
            logger.info(f"Added {len(embeddings)} embeddings to index {index_name}")
            return doc_ids
        except Exception as e:
            logger.error(f"Failed to add embeddings to {index_name}: {e}")
            raise VectorStoreOperationError(f"Failed to add embeddings: {e}")
    
    async def search(self, query_vector: List[float], top_k: int = 10,
                    collection_name: Optional[str] = None,
                    filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Search for similar vectors in Elasticsearch.
        
        Args:
            query_vector: Query vector to search for
            top_k: Number of results to return
            collection_name: Index to search in
            filter_dict: Optional metadata filters
            
        Returns:
            List of search results
        """
        index_name = collection_name or self.index_name
        
        # Build query
        query = {
            "knn": {
                "field": "vector",
                "query_vector": query_vector,
                "k": top_k,
                "num_candidates": min(top_k * 10, 10000)
            }
        }
        
        # Add filters if provided
        if filter_dict:
            filter_conditions = []
            for key, value in filter_dict.items():
                if key == "metadata":
                    # Handle nested metadata filters
                    for meta_key, meta_value in value.items():
                        filter_conditions.append({
                            "term": {f"metadata.{meta_key}": meta_value}
                        })
                else:
                    filter_conditions.append({
                        "term": {key: value}
                    })
            
            if filter_conditions:
                query["knn"]["filter"] = {
                    "bool": {
                        "must": filter_conditions
                    }
                }
        
        search_body = {
            "query": query,
            "size": top_k,
            "_source": ["content", "chunk_id", "model_name", "metadata"]
        }
        
        try:
            response = await self.client.search(
                index=index_name,
                body=search_body
            )
            
            results = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                result = SearchResult(
                    chunk_id=source.get("chunk_id", hit["_id"]),
                    content=source.get("content", ""),
                    score=hit["_score"],
                    metadata=source.get("metadata", {}),
                    embedding=None  # Not returned for performance
                )
                results.append(result)
            
            return results
        except Exception as e:
            logger.error(f"Failed to search in index {index_name}: {e}")
            raise VectorStoreOperationError(f"Failed to search: {e}")
    
    async def get_by_id(self, embedding_id: str, 
                       collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
        """Retrieve an embedding by ID from Elasticsearch.
        
        Args:
            embedding_id: ID of the embedding to retrieve
            collection_name: Index to search in
            
        Returns:
            Embedding result if found, None otherwise
        """
        index_name = collection_name or self.index_name
        
        try:
            response = await self.client.get(
                index=index_name,
                id=embedding_id
            )
            
            if response["found"]:
                source = response["_source"]
                return EmbeddingResult(
                    embedding=source.get("vector", []),
                    chunk_id=source.get("chunk_id", embedding_id),
                    content=source.get("content", ""),
                    metadata=source.get("metadata", {}),
                    model_name=source.get("model_name")
                )
            
            return None
        except NotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to get embedding {embedding_id} from {index_name}: {e}")
            return None
    
    async def delete_by_id(self, embedding_id: str,
                          collection_name: Optional[str] = None) -> bool:
        """Delete an embedding by ID from Elasticsearch.
        
        Args:
            embedding_id: ID of the embedding to delete
            collection_name: Index to delete from
            
        Returns:
            True if embedding was deleted successfully
        """
        index_name = collection_name or self.index_name
        
        try:
            response = await self.client.delete(
                index=index_name,
                id=embedding_id
            )
            logger.info(f"Deleted embedding {embedding_id} from {index_name}")
            return response.get("result") == "deleted"
        except NotFoundError:
            logger.warning(f"Embedding {embedding_id} not found in {index_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete embedding {embedding_id} from {index_name}: {e}")
            return False
    
    async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult,
                             collection_name: Optional[str] = None) -> bool:
        """Update an existing embedding in Elasticsearch.
        
        Args:
            embedding_id: ID of the embedding to update
            embedding: New embedding data
            collection_name: Index containing the embedding
            
        Returns:
            True if embedding was updated successfully
        """
        index_name = collection_name or self.index_name
        
        # Prepare document
        doc = {
            "vector": embedding.embedding,
            "content": embedding.content,
            "chunk_id": embedding.chunk_id,
            "model_name": embedding.model_name,
            "metadata": embedding.metadata or {}
        }
        
        try:
            response = await self.client.index(
                index=index_name,
                id=embedding_id,
                body=doc
            )
            logger.info(f"Updated embedding {embedding_id} in {index_name}")
            return response.get("result") in ["created", "updated"]
        except Exception as e:
            logger.error(f"Failed to update embedding {embedding_id} in {index_name}: {e}")
            return False
    
    async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get information about an Elasticsearch index.
        
        Args:
            collection_name: Name of the index
            
        Returns:
            Dictionary with index information
        """
        index_name = collection_name or self.index_name
        
        try:
            # Get index stats
            stats_response = await self.client.indices.stats(index=index_name)
            index_stats = stats_response["indices"][index_name]
            
            # Get index settings and mappings
            settings_response = await self.client.indices.get(index=index_name)
            index_config = settings_response[index_name]
            
            # Extract vector dimension from mapping
            vector_mapping = index_config.get("mappings", {}).get("properties", {}).get("vector", {})
            vector_dim = vector_mapping.get("dims")
            
            return {
                "name": index_name,
                "docs_count": index_stats["total"]["docs"]["count"],
                "docs_deleted": index_stats["total"]["docs"]["deleted"],
                "store_size": index_stats["total"]["store"]["size_in_bytes"],
                "vector_dimension": vector_dim,
                "similarity_metric": vector_mapping.get("similarity"),
                "shards": index_stats["total"]["shards"]["total"],
                "status": "green"  # Simplified status
            }
        except Exception as e:
            logger.error(f"Failed to get index info for {index_name}: {e}")
            raise VectorStoreOperationError(f"Failed to get index info: {e}")
    
    async def list_collections(self) -> List[str]:
        """List all indices in Elasticsearch.
        
        Returns:
            List of index names
        """
        try:
            response = await self.client.indices.get_alias()
            return list(response.keys())
        except Exception as e:
            logger.error(f"Failed to list indices: {e}")
            raise VectorStoreOperationError(f"Failed to list indices: {e}")
    
    async def close(self):
        """Close the Elasticsearch connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None


# Export public interface
__all__ = [
    'ElasticsearchVectorStore'
]
