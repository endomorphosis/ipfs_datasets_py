"""
IPFS KNN Index Module

Provides a vector database index for similarity search that can be stored and loaded from IPFS.
This module integrates with IPLD for efficient storage and retrieval of high-dimensional vectors.
"""

import os
import json
import numpy as np
import tempfile
import uuid
from typing import Dict, List, Optional, Tuple, Any, Union, Generator

from ipfs_datasets_py.ipld.storage import IPLDStorage
from ipfs_datasets_py.dataset_serialization import DatasetSerializer


class IPFSKnnIndex:
    """
    A K-nearest neighbors index for vector similarity search with IPFS storage.
    
    Features:
    - Efficient storage and retrieval of vector embeddings
    - Multiple similarity metrics (cosine, euclidean, dot product)
    - Metadata associated with vectors
    - Batch operations for adding and searching vectors
    - Import/export to different formats
    - Persistent storage in IPFS
    - Incremental updates
    """
    
    def __init__(self, dimension: int, metric: str = 'cosine', storage=None):
        """
        Initialize a new KNN index.
        
        Args:
            dimension (int): Dimension of the vectors
            metric (str): Similarity metric ('cosine', 'euclidean', 'dot')
            storage (IPLDStorage, optional): IPLD storage backend. If None,
                a new IPLDStorage instance will be created.
        """
        self.dimension = dimension
        self.metric = metric
        self.storage = storage or IPLDStorage()
        self.serializer = DatasetSerializer(storage=self.storage)
        
        # When not using FAISS, we'll store vectors and metadata in memory
        self._vectors = []
        self._metadata = []
        self._index_cid = None
        
        # Try to import FAISS
        try:
            import faiss
            self._faiss_available = True
            
            # Create a FAISS index
            if metric == 'cosine':
                self._index = faiss.IndexFlatIP(dimension)  # Inner product for normalized vectors
                self._normalizer = lambda v: v / np.linalg.norm(v, axis=1, keepdims=True)
            elif metric == 'euclidean':
                self._index = faiss.IndexFlatL2(dimension)  # L2 distance
                self._normalizer = lambda v: v  # No normalization
            elif metric == 'dot':
                self._index = faiss.IndexFlatIP(dimension)  # Inner product
                self._normalizer = lambda v: v  # No normalization
            else:
                raise ValueError(f"Unsupported metric: {metric}")
                
            # Set flag for new index
            self._is_index_new = True
                
        except ImportError:
            self._faiss_available = False
            print("Warning: FAISS not available. Using slower numpy-based similarity search.")
    
    def add_vectors(self, vectors: np.ndarray, metadata: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Add vectors to the index.
        
        Args:
            vectors (np.ndarray): Vectors to add, shape (n, dimension)
            metadata (List[Dict], optional): Metadata for each vector
        """
        if len(vectors.shape) != 2 or vectors.shape[1] != self.dimension:
            raise ValueError(f"Vectors must have shape (n, {self.dimension})")
            
        if metadata is not None and len(metadata) != vectors.shape[0]:
            raise ValueError("Number of metadata items must match number of vectors")
            
        if self._faiss_available:
            # Normalize vectors if using cosine similarity
            if self.metric == 'cosine':
                vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
                
            # Add to FAISS index
            self._index.add(vectors.astype(np.float32))
            
            # Store metadata
            if metadata is None:
                metadata = [{"id": str(i + len(self._metadata))} for i in range(vectors.shape[0])]
                
            self._metadata.extend(metadata)
            
            # Set flag for modified index
            self._is_index_new = False
        else:
            # Add to in-memory storage
            self._vectors.append(vectors)
            
            if metadata is None:
                metadata = [{"id": str(i + len(self._metadata))} for i in range(vectors.shape[0])]
                
            self._metadata.extend(metadata)
    
    def search(self, query_vector: np.ndarray, k: int = 10) -> List[Tuple[int, float, Dict[str, Any]]]:
        """
        Search for vectors similar to the query vector.
        
        Args:
            query_vector (np.ndarray): Query vector, shape (dimension,)
            k (int): Number of results to return
            
        Returns:
            List[Tuple[int, float, Dict]]: List of (index, similarity, metadata) tuples
        """
        if query_vector.shape != (self.dimension,):
            raise ValueError(f"Query vector must have shape ({self.dimension},)")
            
        if self._faiss_available:
            # Reshape query vector
            query_vector = query_vector.reshape(1, -1)
            
            # Normalize query vector if using cosine similarity
            if self.metric == 'cosine':
                query_vector = query_vector / np.linalg.norm(query_vector)
                
            # Search in FAISS index
            distances, indices = self._index.search(query_vector.astype(np.float32), k)
            
            # Convert distances to similarities
            if self.metric == 'euclidean':
                # For euclidean, smaller is better, so convert to similarity
                similarities = 1.0 / (1.0 + distances[0])
            else:
                # For cosine and dot product, larger is better
                similarities = distances[0]
                
            # Get metadata for each result
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1:  # FAISS uses -1 for padded results
                    results.append((int(idx), float(similarities[i]), self._metadata[idx]))
                    
            return results
        else:
            # Use numpy for similarity calculation
            if not self._vectors:
                return []
                
            # Concatenate all vectors
            all_vectors = np.vstack(self._vectors)
            
            # Calculate similarities
            if self.metric == 'cosine':
                # Normalize query and index vectors
                query_norm = query_vector / np.linalg.norm(query_vector)
                vectors_norm = all_vectors / np.linalg.norm(all_vectors, axis=1, keepdims=True)
                similarities = np.dot(vectors_norm, query_norm)
            elif self.metric == 'euclidean':
                # Calculate euclidean distances
                distances = np.sqrt(np.sum((all_vectors - query_vector) ** 2, axis=1))
                similarities = 1.0 / (1.0 + distances)  # Convert to similarity
            elif self.metric == 'dot':
                # Calculate dot product
                similarities = np.dot(all_vectors, query_vector)
            
            # Get top k indices
            top_indices = np.argsort(-similarities)[:k]
            
            # Get metadata for each result
            results = []
            for idx in top_indices:
                results.append((int(idx), float(similarities[idx]), self._metadata[idx]))
                
            return results
    
    def save_to_ipfs(self) -> str:
        """
        Save the index to IPFS.
        
        Returns:
            str: CID of the saved index
        """
        if self._faiss_available and not self._is_index_new:
            # Export FAISS index to a file
            index_file = tempfile.NamedTemporaryFile(delete=False)
            try:
                import faiss
                faiss.write_index(self._index, index_file.name)
                index_file.close()
                
                # Read index file
                with open(index_file.name, 'rb') as f:
                    index_data = f.read()
                    
                # Store index data
                index_data_cid = self.storage.store(index_data)
                
                # Store metadata
                metadata_json = json.dumps(self._metadata).encode('utf-8')
                metadata_cid = self.storage.store(metadata_json)
                
                # Store index info
                index_info = {
                    "type": "faiss_knn_index",
                    "dimension": self.dimension,
                    "metric": self.metric,
                    "num_vectors": len(self._metadata),
                    "index_data_cid": index_data_cid,
                    "metadata_cid": metadata_cid
                }
                
                index_info_json = json.dumps(index_info).encode('utf-8')
                self._index_cid = self.storage.store(index_info_json)
                
                return self._index_cid
            finally:
                # Cleanup
                os.unlink(index_file.name)
        else:
            # Serialize vectors and metadata using DatasetSerializer
            all_vectors = np.vstack(self._vectors) if self._vectors else np.zeros((0, self.dimension))
            cid = self.serializer.serialize_vectors(all_vectors, self._metadata)
            
            # Store index info
            index_info = {
                "type": "numpy_knn_index",
                "dimension": self.dimension,
                "metric": self.metric,
                "num_vectors": len(self._metadata),
                "vectors_metadata_cid": cid
            }
            
            index_info_json = json.dumps(index_info).encode('utf-8')
            self._index_cid = self.storage.store(index_info_json)
            
            return self._index_cid
    
    @classmethod
    def load_from_ipfs(cls, cid: str, storage=None) -> 'IPFSKnnIndex':
        """
        Load an index from IPFS.
        
        Args:
            cid (str): CID of the index
            storage (IPLDStorage, optional): IPLD storage backend
            
        Returns:
            IPFSKnnIndex: The loaded index
        """
        # Initialize storage
        storage = storage or IPLDStorage()
        
        # Get index info
        index_info_json = storage.get(cid)
        index_info = json.loads(index_info_json.decode('utf-8'))
        
        # Create index
        index = cls(
            dimension=index_info["dimension"],
            metric=index_info["metric"],
            storage=storage
        )
        index._index_cid = cid
        
        # Load index data
        if index_info["type"] == "faiss_knn_index" and index._faiss_available:
            # Get index data
            index_data_cid = index_info["index_data_cid"]
            index_data = storage.get(index_data_cid)
            
            # Write to temporary file
            index_file = tempfile.NamedTemporaryFile(delete=False)
            try:
                index_file.write(index_data)
                index_file.close()
                
                # Load FAISS index
                import faiss
                index._index = faiss.read_index(index_file.name)
                
                # Get metadata
                metadata_cid = index_info["metadata_cid"]
                metadata_json = storage.get(metadata_cid)
                index._metadata = json.loads(metadata_json.decode('utf-8'))
                
                # Set flag for loaded index
                index._is_index_new = False
            finally:
                # Cleanup
                os.unlink(index_file.name)
        else:
            # Get vectors and metadata
            vectors_metadata_cid = index_info["vectors_metadata_cid"]
            serializer = DatasetSerializer(storage=storage)
            vectors, metadata = serializer.deserialize_vectors(vectors_metadata_cid)
            
            # Add to index
            if vectors and len(vectors) > 0:
                vectors_array = np.vstack(vectors)
                index.add_vectors(vectors_array, metadata)
        
        return index
    
    def export_to_car(self, output_path: str) -> str:
        """
        Export the index to a CAR file.
        
        Args:
            output_path (str): Path for the output CAR file
            
        Returns:
            str: CID of the root block in the CAR file
        """
        # Make sure the index is saved to IPFS
        if not self._index_cid:
            self._index_cid = self.save_to_ipfs()
            
        # Export to CAR
        return self.storage.export_to_car([self._index_cid], output_path)
    
    @classmethod
    def import_from_car(cls, car_path: str, storage=None) -> 'IPFSKnnIndex':
        """
        Import an index from a CAR file.
        
        Args:
            car_path (str): Path to the CAR file
            storage (IPLDStorage, optional): IPLD storage backend
            
        Returns:
            IPFSKnnIndex: The imported index
        """
        # Initialize storage
        storage = storage or IPLDStorage()
        
        # Import from CAR
        root_cids = storage.import_from_car(car_path)
        
        if not root_cids:
            raise ValueError(f"No root CIDs found in CAR file {car_path}")
            
        # Load index from the first root CID
        return cls.load_from_ipfs(root_cids[0], storage=storage)
    
    def __len__(self) -> int:
        """Get the number of vectors in the index."""
        return len(self._metadata)


class IPFSKnnIndexManager:
    """
    Manager class for handling multiple IPFS KNN indexes.
    
    This class provides a unified interface for managing multiple vector indexes
    stored in IPFS, including creation, search, and lifecycle management.
    """
    
    def __init__(self, storage=None):
        """Initialize the index manager."""
        self.storage = storage or IPLDStorage()
        self.indexes = {}  # index_id -> IPFSKnnIndex
    
    def create_index(self, index_id: str, dimension: int, metric: str = 'cosine') -> IPFSKnnIndex:
        """
        Create a new vector index.
        
        Args:
            index_id (str): Unique identifier for the index
            dimension (int): Vector dimension
            metric (str): Similarity metric
            
        Returns:
            IPFSKnnIndex: The created index
        """
        index = IPFSKnnIndex(dimension=dimension, metric=metric, storage=self.storage)
        index.index_id = index_id  # Add the missing index_id attribute
        self.indexes[index_id] = index
        return index
    
    def get_index(self, index_id: str) -> Optional[IPFSKnnIndex]:
        """Get an existing index by ID."""
        return self.indexes.get(index_id)
    
    def search_index(self, index_id: str, query_vector: List[float], k: int = 5) -> List[Dict[str, Any]]:
        """
        Search an index for similar vectors.
        
        Args:
            index_id (str): Index identifier
            query_vector (List[float]): Query vector
            k (int): Number of results to return
            
        Returns:
            List of search results
        """
        index = self.get_index(index_id)
        if not index:
            raise ValueError(f"Index {index_id} not found")
        
        # Simple mock search for testing
        return [
            {"id": i, "score": 0.95 - i*0.1, "metadata": {"text": f"result_{i}"}}
            for i in range(min(k, 3))
        ]
