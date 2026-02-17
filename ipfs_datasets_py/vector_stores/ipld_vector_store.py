"""IPLD Vector Store Implementation.

This module provides an IPLD/IPFS-native vector store that combines:
- Content-addressed storage via IPLD
- Fast similarity search via FAISS
- Automatic router integration for embeddings and IPFS operations
- CAR file import/export for portability

The IPLDVectorStore implements the full BaseVectorStore interface and adds
IPLD-specific functionality for decentralized, content-addressed vector storage.
"""

import logging
import os
import json
import uuid
import tempfile
import pickle
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union
import anyio

# Import base classes and schemas
from .base import BaseVectorStore, VectorStoreError, VectorStoreConnectionError, VectorStoreOperationError
from .config import UnifiedVectorStoreConfig
from .schema import (
    EmbeddingResult,
    SearchResult,
    IPLDEmbeddingResult,
    IPLDSearchResult,
    CollectionMetadata,
    VectorBlock,
)
from .router_integration import RouterIntegration

logger = logging.getLogger(__name__)

# Check for required dependencies
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
    logger.warning("NumPy not available - IPLD vector store will not function")

try:
    import faiss
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False
    logger.warning("FAISS not available - using fallback search")

try:
    from ..processors.storage.ipld.storage import IPLDStorage
    HAVE_IPLD_STORAGE = True
except ImportError:
    HAVE_IPLD_STORAGE = False
    logger.warning("IPLDStorage not available - IPLD operations will be limited")

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False
    logger.info("ipld_car not available - CAR export/import will not be available")


class IPLDVectorStore(BaseVectorStore):
    """IPLD/IPFS-native vector store with FAISS indexing.
    
    This vector store combines content-addressed IPLD storage with FAISS-based
    similarity search, providing both decentralized storage and fast retrieval.
    
    Features:
    - Content-addressed vector storage with CIDs
    - FAISS backend for fast similarity search
    - Router integration for automatic embeddings and IPFS operations
    - Collection management with metadata
    - CAR file export/import for portability
    - Chunking support for large collections
    - Async operations throughout
    
    Example:
        ```python
        from ipfs_datasets_py.vector_stores import IPLDVectorStore
        from ipfs_datasets_py.vector_stores.config import create_ipld_config
        
        config = create_ipld_config(
            collection_name="documents",
            dimension=768,
            use_embeddings_router=True,
            use_ipfs_router=True
        )
        
        store = IPLDVectorStore(config)
        await store.create_collection()
        
        # Add embeddings (will auto-generate if use_embeddings_router=True)
        ids = await store.add_embeddings(embeddings)
        
        # Search
        results = await store.search(query_vector, top_k=5)
        
        # Export to IPLD
        root_cid = await store.export_to_ipld()
        ```
    """
    
    def __init__(self, config: UnifiedVectorStoreConfig):
        """Initialize IPLD vector store.
        
        Args:
            config: UnifiedVectorStoreConfig with IPLD and router settings
        """
        super().__init__(config)
        
        if not HAVE_NUMPY:
            raise VectorStoreError("NumPy is required for IPLD vector store")
        
        if not HAVE_FAISS:
            logger.warning("FAISS not available - search will be slow")
        
        # Store config
        self.config: UnifiedVectorStoreConfig = config
        
        # Initialize router integration if enabled
        self.router = None
        if config.use_embeddings_router or config.use_ipfs_router:
            self.router = RouterIntegration(
                use_embeddings_router=config.use_embeddings_router,
                use_ipfs_router=config.use_ipfs_router,
                embeddings_provider=config.embeddings_router_provider,
                ipfs_backend=config.ipfs_router_backend
            )
        
        # Initialize IPLD storage if available
        self.ipld_storage = None
        if HAVE_IPLD_STORAGE and config.use_ipfs_router:
            try:
                self.ipld_storage = IPLDStorage(
                    base_dir=config.ipld_storage_path,
                    ipfs_api=config.ipfs_gateway
                )
            except Exception as e:
                logger.warning(f"Failed to initialize IPLD storage: {e}")
        
        # Collections: collection_name -> metadata
        self.collections: Dict[str, Dict[str, Any]] = {}
        
        # Indexes: collection_name -> faiss.Index
        self.indexes: Dict[str, Any] = {}
        
        # Vectors: collection_name -> List[np.ndarray]
        self.vectors: Dict[str, List[np.ndarray]] = {}
        
        # Metadata: collection_name -> List[Dict]
        self.metadata: Dict[str, List[Dict[str, Any]]] = {}
        
        # CID mappings: collection_name -> List[str]
        self.cids: Dict[str, List[str]] = {}
        
        # Vector IDs: collection_name -> List[str]
        self.vector_ids: Dict[str, List[str]] = {}
    
    def _create_client(self):
        """Create client connection (not needed for IPLD store)."""
        return None
    
    def _create_faiss_index(self, dimension: int, metric: str = "cosine") -> Any:
        """Create FAISS index based on metric.
        
        Args:
            dimension: Vector dimension
            metric: Distance metric (cosine, euclidean, dot)
            
        Returns:
            FAISS index instance
        """
        if not HAVE_FAISS:
            logger.warning("FAISS not available, using numpy fallback")
            return None
        
        if metric == "cosine":
            # Normalize vectors and use inner product
            index = faiss.IndexFlatIP(dimension)
        elif metric in ["euclidean", "l2"]:
            index = faiss.IndexFlatL2(dimension)
        elif metric in ["dot", "ip"]:
            index = faiss.IndexFlatIP(dimension)
        else:
            logger.warning(f"Unknown metric '{metric}', using cosine")
            index = faiss.IndexFlatIP(dimension)
        
        return index
    
    async def create_collection(self, 
                               collection_name: Optional[str] = None,
                               dimension: Optional[int] = None, 
                               **kwargs) -> bool:
        """Create a new vector collection.
        
        Args:
            collection_name: Name of the collection
            dimension: Vector dimension
            **kwargs: Additional parameters
            
        Returns:
            True if created successfully
        """
        name = collection_name or self.collection_name
        dim = dimension or self.dimension
        
        if not dim:
            raise VectorStoreError("Vector dimension must be specified")
        
        if name in self.collections:
            logger.warning(f"Collection '{name}' already exists")
            return False
        
        # Create collection metadata
        metadata = CollectionMetadata(
            name=name,
            dimension=dim,
            metric=self.distance_metric,
            count=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            schema_version="1.0",
            compression=self.config.ipld_compression,
            chunked=True,
            chunk_size=self.config.ipld_chunk_size
        )
        
        # Initialize data structures
        self.collections[name] = {
            "metadata": metadata,
            "root_cid": None
        }
        self.indexes[name] = self._create_faiss_index(dim, self.distance_metric)
        self.vectors[name] = []
        self.metadata[name] = []
        self.cids[name] = []
        self.vector_ids[name] = []
        
        logger.info(f"Created collection '{name}' with dimension {dim}")
        return True
    
    async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """Delete a collection.
        
        Args:
            collection_name: Name of the collection to delete
            
        Returns:
            True if deleted successfully
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            logger.warning(f"Collection '{name}' does not exist")
            return False
        
        # Remove all data
        del self.collections[name]
        del self.indexes[name]
        del self.vectors[name]
        del self.metadata[name]
        del self.cids[name]
        del self.vector_ids[name]
        
        logger.info(f"Deleted collection '{name}'")
        return True
    
    async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
        """Check if a collection exists.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            True if collection exists
        """
        name = collection_name or self.collection_name
        return name in self.collections
    
    async def add_embeddings(self, 
                           embeddings: List[EmbeddingResult],
                           collection_name: Optional[str] = None) -> List[str]:
        """Add embeddings to the collection.
        
        Args:
            embeddings: List of embedding results to add
            collection_name: Target collection name
            
        Returns:
            List of vector IDs
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            raise VectorStoreError(f"Collection '{name}' does not exist")
        
        if not embeddings:
            return []
        
        # Extract vectors and metadata
        vectors = []
        metadata_list = []
        ids = []
        
        for emb in embeddings:
            # Get vector - might need to generate via router
            if hasattr(emb, 'vector') and emb.vector:
                vector = np.array(emb.vector, dtype=np.float32)
            elif hasattr(emb, 'text') and emb.text and self.router and self.router.is_embeddings_available():
                # Generate embedding via router
                logger.debug(f"Generating embedding for text via router")
                vecs = await self.router.generate_embeddings([emb.text])
                vector = np.array(vecs[0], dtype=np.float32)
            else:
                raise VectorStoreError("Embedding has no vector and cannot generate one")
            
            # Normalize if cosine metric
            if self.distance_metric == "cosine":
                norm = np.linalg.norm(vector)
                if norm > 0:
                    vector = vector / norm
            
            vectors.append(vector)
            
            # Extract metadata
            meta = {
                "text": getattr(emb, 'text', None),
                "metadata": getattr(emb, 'metadata', {}),
                "id": getattr(emb, 'id', None) or str(uuid.uuid4())
            }
            metadata_list.append(meta)
            ids.append(meta["id"])
        
        # Convert to numpy array
        vectors_np = np.array(vectors, dtype=np.float32)
        
        # Add to FAISS index
        if self.indexes[name] is not None and HAVE_FAISS:
            self.indexes[name].add(vectors_np)
        
        # Store vectors and metadata
        self.vectors[name].extend(vectors)
        self.metadata[name].extend(metadata_list)
        self.vector_ids[name].extend(ids)
        
        # Store to IPLD if router available
        cids_added = []
        if self.router and self.router.is_ipfs_available():
            for i, (vector, meta) in enumerate(zip(vectors, metadata_list)):
                try:
                    # Create vector data block
                    vector_data = {
                        "vector": vector.tolist(),
                        "text": meta.get("text"),
                        "metadata": meta.get("metadata", {}),
                        "id": ids[i],
                        "stored_at": datetime.now(timezone.utc).isoformat()
                    }
                    
                    # Serialize and store
                    data_bytes = json.dumps(vector_data).encode('utf-8')
                    cid = await self.router.store_to_ipfs(
                        data_bytes,
                        pin=self.config.auto_pin_to_ipfs
                    )
                    cids_added.append(cid)
                    logger.debug(f"Stored vector to IPFS: {cid}")
                    
                except Exception as e:
                    logger.warning(f"Failed to store vector to IPFS: {e}")
                    cids_added.append(None)
        else:
            cids_added = [None] * len(vectors)
        
        self.cids[name].extend(cids_added)
        
        # Update collection metadata
        self.collections[name]["metadata"].count += len(vectors)
        self.collections[name]["metadata"].updated_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"Added {len(vectors)} embeddings to collection '{name}'")
        return ids
    
    async def search(self, 
                    query_vector: List[float],
                    top_k: int = 10,
                    collection_name: Optional[str] = None,
                    filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Search for similar vectors.
        
        Args:
            query_vector: Query vector
            top_k: Number of results to return
            collection_name: Collection to search
            filter_dict: Optional metadata filters
            
        Returns:
            List of search results
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            raise VectorStoreError(f"Collection '{name}' does not exist")
        
        if not self.vectors[name]:
            return []
        
        # Convert query to numpy
        query_np = np.array(query_vector, dtype=np.float32).reshape(1, -1)
        
        # Normalize if cosine
        if self.distance_metric == "cosine":
            norm = np.linalg.norm(query_np)
            if norm > 0:
                query_np = query_np / norm
        
        # Search using FAISS if available
        if self.indexes[name] is not None and HAVE_FAISS:
            distances, indices = self.indexes[name].search(query_np, min(top_k, len(self.vectors[name])))
            distances = distances[0]
            indices = indices[0]
        else:
            # Fallback to numpy similarity
            vectors_np = np.array(self.vectors[name], dtype=np.float32)
            if self.distance_metric == "cosine":
                similarities = np.dot(vectors_np, query_np.T).flatten()
                indices = np.argsort(-similarities)[:top_k]
                distances = similarities[indices]
            else:
                # L2 distance
                diff = vectors_np - query_np
                distances_all = np.linalg.norm(diff, axis=1)
                indices = np.argsort(distances_all)[:top_k]
                distances = distances_all[indices]
        
        # Create results
        results = []
        for i, (idx, score) in enumerate(zip(indices, distances)):
            if idx < 0 or idx >= len(self.vectors[name]):
                continue
            
            meta = self.metadata[name][idx]
            vid = self.vector_ids[name][idx]
            cid = self.cids[name][idx] if idx < len(self.cids[name]) else None
            
            # Apply filters if provided
            if filter_dict:
                if not self._matches_filter(meta.get("metadata", {}), filter_dict):
                    continue
            
            result = SearchResult(
                chunk_id=vid,
                score=float(score),
                content=meta.get("text"),
                metadata=meta.get("metadata", {}),
                embedding=None  # Don't return embedding by default
            )
            
            # Add IPLD metadata if available
            if cid:
                result = IPLDSearchResult(
                    chunk_id=vid,
                    score=float(score),
                    content=meta.get("text"),
                    metadata=meta.get("metadata", {}),
                    cid=cid,
                    retrieved_from="local_cache"
                )
            
            results.append(result)
        
        return results[:top_k]
    
    def _matches_filter(self, metadata: Dict[str, Any], filter_dict: Dict[str, Any]) -> bool:
        """Check if metadata matches filter criteria.
        
        Args:
            metadata: Metadata to check
            filter_dict: Filter criteria
            
        Returns:
            True if matches
        """
        for key, value in filter_dict.items():
            if key not in metadata or metadata[key] != value:
                return False
        return True
    
    async def get_by_id(self, 
                       embedding_id: str,
                       collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
        """Retrieve an embedding by ID.
        
        Args:
            embedding_id: ID of the embedding
            collection_name: Collection to search
            
        Returns:
            EmbeddingResult if found, None otherwise
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            return None
        
        # Find index
        try:
            idx = self.vector_ids[name].index(embedding_id)
        except ValueError:
            return None
        
        # Get data
        vector = self.vectors[name][idx]
        meta = self.metadata[name][idx]
        cid = self.cids[name][idx] if idx < len(self.cids[name]) else None
        
        result = EmbeddingResult(
            chunk_id=embedding_id,
            content=meta.get("text"),
            embedding=vector.tolist(),
            metadata=meta.get("metadata", {})
        )
        
        return result
    
    async def delete_by_id(self, 
                          embedding_id: str,
                          collection_name: Optional[str] = None) -> bool:
        """Delete an embedding by ID.
        
        Args:
            embedding_id: ID to delete
            collection_name: Collection name
            
        Returns:
            True if deleted
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            return False
        
        # Find index
        try:
            idx = self.vector_ids[name].index(embedding_id)
        except ValueError:
            return False
        
        # Remove from all lists
        del self.vectors[name][idx]
        del self.metadata[name][idx]
        del self.vector_ids[name][idx]
        if idx < len(self.cids[name]):
            del self.cids[name][idx]
        
        # Rebuild FAISS index
        if self.indexes[name] is not None and HAVE_FAISS and self.vectors[name]:
            vectors_np = np.array(self.vectors[name], dtype=np.float32)
            self.indexes[name] = self._create_faiss_index(
                vectors_np.shape[1],
                self.distance_metric
            )
            self.indexes[name].add(vectors_np)
        
        # Update count
        self.collections[name]["metadata"].count -= 1
        
        logger.info(f"Deleted embedding {embedding_id} from collection '{name}'")
        return True
    
    async def update_embedding(self, 
                             embedding_id: str,
                             embedding: EmbeddingResult,
                             collection_name: Optional[str] = None) -> bool:
        """Update an existing embedding.
        
        Args:
            embedding_id: ID to update
            embedding: New embedding data
            collection_name: Collection name
            
        Returns:
            True if updated
        """
        # For simplicity, delete and re-add
        name = collection_name or self.collection_name
        
        if await self.delete_by_id(embedding_id, name):
            # Set the ID
            if hasattr(embedding, 'id'):
                embedding.id = embedding_id
            elif hasattr(embedding, 'chunk_id'):
                embedding.chunk_id = embedding_id
            
            ids = await self.add_embeddings([embedding], name)
            return len(ids) > 0
        
        return False
    
    async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get collection information.
        
        Args:
            collection_name: Collection name
            
        Returns:
            Collection information dict
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            raise VectorStoreError(f"Collection '{name}' does not exist")
        
        metadata = self.collections[name]["metadata"]
        return {
            "name": metadata.name,
            "dimension": metadata.dimension,
            "metric": metadata.metric,
            "count": metadata.count,
            "created_at": metadata.created_at,
            "updated_at": metadata.updated_at,
            "root_cid": metadata.root_cid,
            "chunked": metadata.chunked,
            "chunk_size": metadata.chunk_size,
        }
    
    async def list_collections(self) -> List[str]:
        """List all collections.
        
        Returns:
            List of collection names
        """
        return list(self.collections.keys())
    
    # IPLD-specific methods
    
    async def export_to_ipld(self, collection_name: Optional[str] = None) -> Optional[str]:
        """Export collection to IPLD format.
        
        Args:
            collection_name: Collection to export
            
        Returns:
            Root CID of the collection
        """
        name = collection_name or self.collection_name
        
        if name not in self.collections:
            raise VectorStoreError(f"Collection '{name}' does not exist")
        
        if not self.router or not self.router.is_ipfs_available():
            logger.warning("IPFS router not available for IPLD export")
            return None
        
        try:
            # Create collection metadata
            metadata = self.collections[name]["metadata"]
            metadata_dict = metadata.to_dict()
            
            # Store metadata
            metadata_bytes = json.dumps(metadata_dict).encode('utf-8')
            metadata_cid = await self.router.store_to_ipfs(
                metadata_bytes,
                pin=self.config.auto_pin_to_ipfs
            )
            
            # Create root structure
            root_data = {
                "type": "ipld_vector_collection",
                "version": "1.0",
                "metadata_cid": metadata_cid,
                "vectors_cids": self.cids[name],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Store root
            root_bytes = json.dumps(root_data).encode('utf-8')
            root_cid = await self.router.store_to_ipfs(
                root_bytes,
                pin=self.config.auto_pin_to_ipfs
            )
            
            # Update collection
            self.collections[name]["root_cid"] = root_cid
            metadata.root_cid = root_cid
            
            logger.info(f"Exported collection '{name}' to IPLD: {root_cid}")
            return root_cid
            
        except Exception as e:
            logger.error(f"Failed to export to IPLD: {e}")
            raise VectorStoreOperationError(f"IPLD export failed: {e}")
    
    async def import_from_ipld(self, 
                              root_cid: str,
                              collection_name: Optional[str] = None) -> bool:
        """Import collection from IPLD CID.
        
        Args:
            root_cid: Root CID to import
            collection_name: Name for imported collection
            
        Returns:
            True if successful
        """
        if not self.router or not self.router.is_ipfs_available():
            logger.warning("IPFS router not available for IPLD import")
            return False
        
        try:
            # Fetch root data
            root_bytes = await self.router.load_from_ipfs(root_cid)
            root_data = json.loads(root_bytes.decode('utf-8'))
            
            # Fetch metadata
            metadata_bytes = await self.router.load_from_ipfs(root_data["metadata_cid"])
            metadata_dict = json.loads(metadata_bytes.decode('utf-8'))
            metadata = CollectionMetadata.from_dict(metadata_dict)
            
            # Use provided name or original name
            name = collection_name or metadata.name
            
            # Create collection
            await self.create_collection(name, metadata.dimension)
            
            # Fetch vectors
            vector_cids = root_data.get("vectors_cids", [])
            embeddings = []
            
            for cid in vector_cids:
                if not cid:
                    continue
                try:
                    vector_bytes = await self.router.load_from_ipfs(cid)
                    vector_data = json.loads(vector_bytes.decode('utf-8'))
                    
                    emb = EmbeddingResult(
                        chunk_id=vector_data.get("id"),
                        content=vector_data.get("text"),
                        embedding=vector_data.get("vector"),
                        metadata=vector_data.get("metadata", {})
                    )
                    embeddings.append(emb)
                except Exception as e:
                    logger.warning(f"Failed to fetch vector {cid}: {e}")
            
            # Add embeddings
            if embeddings:
                await self.add_embeddings(embeddings, name)
            
            logger.info(f"Imported collection '{name}' from IPLD: {root_cid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import from IPLD: {e}")
            return False
    
    async def export_to_car(self, 
                           output_path: str,
                           collection_name: Optional[str] = None) -> bool:
        """Export collection to CAR file.
        
        Args:
            output_path: Path to write CAR file
            collection_name: Collection to export
            
        Returns:
            True if successful
        """
        if not HAVE_IPLD_CAR:
            logger.warning("ipld_car not available - CAR export not supported")
            return False
        
        # First export to IPLD to get CIDs
        root_cid = await self.export_to_ipld(collection_name)
        if not root_cid:
            return False
        
        # Use router to export DAG
        if self.router and self.router.is_ipfs_available():
            try:
                car_data = await self.router.dag_export(root_cid)
                
                # Write to file
                with open(output_path, 'wb') as f:
                    f.write(car_data)
                
                logger.info(f"Exported collection to CAR: {output_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to export CAR: {e}")
                return False
        
        return False
    
    async def import_from_car(self, 
                             car_path: str,
                             collection_name: Optional[str] = None) -> bool:
        """Import collection from CAR file.
        
        Args:
            car_path: Path to CAR file
            collection_name: Name for imported collection
            
        Returns:
            True if successful
        """
        if not HAVE_IPLD_CAR:
            logger.warning("ipld_car not available - CAR import not supported")
            return False
        
        logger.warning("CAR import not fully implemented yet")
        return False
    
    async def get_store_info(self) -> Dict[str, Any]:
        """Get vector store metadata and statistics.
        
        Returns:
            Store information dict
        """
        collections = await self.list_collections()
        
        total_vectors = sum(
            self.collections[name]["metadata"].count 
            for name in collections
        )
        
        return {
            'store_type': 'IPLDVectorStore',
            'collections': collections,
            'total_collections': len(collections),
            'total_vectors': total_vectors,
            'default_collection': self.collection_name,
            'dimension': self.dimension,
            'distance_metric': self.distance_metric,
            'ipfs_enabled': self.router.is_ipfs_available() if self.router else False,
            'embeddings_enabled': self.router.is_embeddings_available() if self.router else False,
            'faiss_available': HAVE_FAISS,
            'ipld_storage_available': HAVE_IPLD_STORAGE,
            'car_export_available': HAVE_IPLD_CAR,
            'config': self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
        }


# Export
__all__ = ['IPLDVectorStore']
